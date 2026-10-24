"""UncertaintyLab: bounded uncertainty budgets and correlated formula propagation.

This extends SciCal's measurement domain; it does not replace legacy operations.
Uses SciCal's safe expression parser and its existing numerical result format.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

import numpy as np
import sympy as sp

from ...core.numerical.context import Settings
from ...errors import EvaluationError
from .. import common as C
from .ops import _expr, _round_unc

MAX_INPUTS = 12
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,15}\Z")


def _finite(value: Any, field: str, *, nonnegative: bool = False) -> float:
    num = float(C.number({"v": value}, "v", nonneg=nonnegative))
    if not math.isfinite(num):
        raise C.field_error(field, "A finite number is required")
    return num


def _components(params: dict) -> list[dict[str, Any]]:
    raw = params.get("components")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_INPUTS:
        raise C.field_error("components", "Provide between 1 and 12 uncertainty sources")
    components = []
    seen = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise C.field_error("components", f"Row {idx + 1} must contain a source and uncertainty")
        name = str(item.get("source", "")).strip()
        if not name or len(name) > 80 or name in seen:
            raise C.field_error("components", "Sources must have distinct names of at most 80 characters")
        seen.add(name)
        distribution = str(item.get("distribution", "normal")).strip().lower()
        if distribution not in ("normal", "rectangular", "triangular", "u_shaped"):
            raise C.field_error("components", f"{name}: unsupported distribution")
        kind = str(item.get("type", "B")).upper()
        if kind not in ("A", "B"):
            raise C.field_error("components", f"{name}: type must be A or B")
        stated = _finite(item.get("uncertainty"), "components", nonnegative=True)
        interpretation = str(item.get("interpretation", "standard"))
        if interpretation not in ("standard", "half_width"):
            raise C.field_error("components", f"{name}: interpretation must be standard or half_width")
        if interpretation == "half_width":
            if distribution == "rectangular":
                standard = stated / math.sqrt(3)
            elif distribution == "triangular":
                standard = stated / math.sqrt(6)
            elif distribution == "u_shaped":
                standard = stated / math.sqrt(2)
            else:
                raise C.field_error("components", f"{name}: normal half-width requires an explicit coverage factor")
        else:
            standard = stated
        sensitivity = _finite(item.get("sensitivity", 1), "components")
        df_raw = item.get("degreesFreedom")
        df = None if df_raw in (None, "") else _finite(df_raw, "components", nonnegative=True)
        if df is not None and df <= 0:
            raise C.field_error("components", f"{name}: degrees of freedom must be positive")
        components.append(dict(source=name, type=kind, distribution=distribution,
                               stated=stated, interpretation=interpretation,
                               standard=standard, sensitivity=sensitivity,
                               degreesFreedom=df))
    return components


def _covariance(standard: list[float], correlations: Any) -> np.ndarray:
    n = len(standard)
    if correlations is None or correlations == "":
        return np.diag(np.square(standard))
    if isinstance(correlations, str):
        if len(correlations) > 4000:
            raise C.field_error("correlations", "Correlation matrix is too large")
        try:
            correlations = json.loads(correlations)
        except json.JSONDecodeError as exc:
            raise C.field_error("correlations", "Enter a JSON array of matrix rows") from exc
    try:
        r = np.asarray(correlations, dtype=float)
    except (TypeError, ValueError) as exc:
        raise C.field_error("correlations", "Provide a numeric correlation matrix") from exc
    if r.shape != (n, n) or not np.isfinite(r).all():
        raise C.field_error("correlations", f"Correlation matrix must be finite and {n} by {n}")
    if not np.allclose(r, r.T, rtol=0, atol=1e-10):
        raise C.field_error("correlations", "Correlation matrix must be symmetric")
    if not np.allclose(np.diag(r), 1.0, rtol=0, atol=1e-10):
        raise C.field_error("correlations", "Correlation matrix diagonal must equal 1")
    if np.any(np.abs(r) > 1 + 1e-10) or float(np.linalg.eigvalsh(r)[0]) < -1e-10:
        raise C.field_error("correlations", "Correlation matrix must be positive semidefinite")
    u = np.asarray(standard, dtype=float)
    return np.outer(u, u) * r


def _budget(components: list[dict], covariance: np.ndarray, out: C.Out, coverage: float) -> dict:
    c = np.asarray([x["sensitivity"] for x in components], dtype=float)
    variance = float(c @ covariance @ c)
    if not math.isfinite(variance) or variance < -1e-12:
        raise C.field_error("components", "The propagated variance is not a valid nonnegative number")
    uc = math.sqrt(max(0.0, variance))
    rows = []
    # Covariance-allocation contributions can be negative; not independent
    # percentages of variance when inputs are correlated.
    allocated = c * (covariance @ c)
    for x, allocation in zip(components, allocated):
        rows.append({"source": x["source"], "type": x["type"], "distribution": x["distribution"],
                     "standardUncertainty": out.num(sp.Float(x["standard"])),
                     "sensitivity": out.num(sp.Float(x["sensitivity"])),
                     "varianceAllocation": out.num(sp.Float(float(allocation))),
                     "percentOfVariance": None if variance == 0 else out.num(sp.Float(100 * float(allocation) / variance), "%"),
                     "degreesFreedom": x["degreesFreedom"]})
    return {"combinedUncertainty": out.num(sp.Float(uc)),
            "expandedUncertainty": out.num(sp.Float(uc * coverage)),
            "coverageFactor": coverage,
            "variance": variance,
            "contributions": rows,
            "correlationsPresent": bool(np.any(np.abs(covariance - np.diag(np.diag(covariance))) > 0))}


def uncertainty_budget(params: dict, s: Settings) -> dict:
    out = C.Out(s)
    parts = _components(params)
    k = _finite(params.get("coverageFactor", 2), "coverageFactor")
    if not 0 < k <= 100:
        raise C.field_error("coverageFactor", "Coverage factor must be greater than zero and at most 100")
    covariance = _covariance([p["standard"] for p in parts], params.get("correlations"))
    data = _budget(parts, covariance, out, k)
    out.step("Standardize uncertainty sources", "Standard deviations are used throughout. Rectangular half-widths divide by sqrt(3); triangular by sqrt(6).")
    out.step("Propagate covariance", "Combined variance = cᵀ Σ c; correlated variance allocations can be negative.")
    out.step("Expand uncertainty", "U = k × u_c. The selected factor does not by itself establish a particular coverage probability.")
    if data["correlationsPresent"]:
        out.warn("Variance allocations include covariance; negative allocations can occur. They are not independent source variances.")
    return out.done(**data, method="GUM first-order covariance propagation",
                    provenance={"provider": "scical-native", "algorithm": "uncertainty_budget_v1"})


def formula_uncertainty(params: dict, s: Settings) -> dict:
    out = C.Out(s)
    expression = _expr(C.text(params, "expression"), "expression")
    raw = params.get("variables")
    if not isinstance(raw, dict) or not 1 <= len(raw) <= MAX_INPUTS:
        raise C.field_error("variables", "Provide between 1 and 12 variables")
    names = sorted(raw)
    if any(not isinstance(n, str) or not NAME.fullmatch(n) for n in names):
        raise C.field_error("variables", "Use valid variable names (letters, numbers and underscores)")
    values = {}
    parts = []
    for name in names:
        spec = raw[name]
        if not isinstance(spec, dict):
            raise C.field_error("variables", f"{name}: value and uncertainty are required")
        values[sp.Symbol(name)] = _finite(spec.get("value"), "variables")
        parts.append({"source": name, "uncertainty": spec.get("uncertainty"),
                      "distribution": spec.get("distribution", "normal"),
                      "interpretation": spec.get("interpretation", "standard"),
                      "type": spec.get("type", "B")})
    if expression.free_symbols != set(values):
        raise C.field_error("variables", "Variables must match the expression symbols exactly")
    evaluated = sp.N(expression.subs(values), 30)
    if not evaluated.is_real or not evaluated.is_finite:
        raise EvaluationError("The model output is not finite and real")
    number = float(evaluated)
    if not math.isfinite(number):
        raise EvaluationError("The model result exceeds finite numerical range")
    for part in parts:
        symbol = sp.Symbol(part["source"])
        gradient = sp.N(sp.diff(expression, symbol).subs(values), 30)
        if not gradient.is_real or not gradient.is_finite:
            raise EvaluationError(f"Undefined sensitivity for {symbol}")
        part["sensitivity"] = float(gradient)
    parsed = _components({"components": parts})
    cov = _covariance([p["standard"] for p in parsed], params.get("correlations"))
    k = _finite(params.get("coverageFactor", 2), "coverageFactor")
    if not 0 < k <= 100:
        raise C.field_error("coverageFactor", "Coverage factor must be greater than zero and at most 100")
    data = _budget(parsed, cov, out, k)
    uc = float(data["combinedUncertainty"]["value"])
    reported_value, reported_unc, _ = _round_unc(number, uc)
    out.step("Differentiate formula", "Symbolic partial derivatives provide first-order sensitivity coefficients.", latex=sp.latex(expression))
    out.step("Covariance propagation", "u_c² = cᵀ Σ c")
    out.warn("First-order propagation assumes sufficiently small uncertainties and a locally smooth model.")
    return out.done(value=out.num(sp.Float(number)), reported=f"{reported_value} ± {reported_unc}",
                    formulaLatex=sp.latex(expression), **data,
                    method="first-order Jacobian covariance propagation",
                    provenance={"provider": "scical-native", "algorithm": "formula_uncertainty_v1"})
