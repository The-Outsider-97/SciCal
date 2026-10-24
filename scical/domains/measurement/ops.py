"""Measurement operations exposed by the API."""
from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any

import mpmath as mp
import numpy as np
import sympy as sp

from ...core.expressions import ParseOptions, parse
from ...core.numerical.context import Context, Settings
from ...core.numerical.evaluator import Evaluator
from ...core.numerical.funcs_stats import _invt, _tcdf
from ...core.units import PICKER, Quantity, REGISTRY, convert, parse_unit, to_si
from ...core.units import constants as K
from ...errors import BadRequest, DimensionError, DomainError, EvaluationError, SciCalError
from .. import common as C

MAX_POINTS = 5000


def F(x: float) -> sp.Float:
    return sp.Float(x, 15)


# ------------------------------------------------------------------------------------------------------------------ significant figures
_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def parse_measured(text: Any, field: str = "value") -> tuple[Decimal, int, int, bool]:
    """Returns (value, significant figures, exponent of the last significant digit, ambiguous trailing zeros)."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        text = repr(text)
    if not isinstance(text, str):
        raise C.field_error(field, f"'{field}' must be a number written as text")
    t = text.strip().replace("×10^", "e").replace("x10^", "e").replace(" ", "")
    t = t.replace("−", "-")
    if not _NUM.match(t):
        raise C.field_error(field, f"'{text}' is not a plain number", hint="Write numbers like 0.00230, 1200., 1.20e3 (no units or words).")
    mant, _, exp = t.lower().partition("e")
    mant = mant.lstrip("+-")
    e = int(exp) if exp else 0
    has_point = "." in mant
    ip, _, fp = mant.partition(".")
    digits = (ip + fp)
    stripped = digits.lstrip("0")
    if not stripped:
        # zero: the digits after the point are significant
        sig = max(len(fp), 1) if has_point else 1
        last = e - len(fp)
        return Decimal(t), sig, last, False
    lead = len(digits) - len(stripped)
    ambiguous = False
    if has_point or exp:
        sig = len(stripped)
        last = e - len(fp)
    else:
        trailing = len(stripped) - len(stripped.rstrip("0"))
        sig = len(stripped) - trailing
        last = e + trailing
        ambiguous = trailing > 0
    return Decimal(t), sig, last, ambiguous


def _format_sig(d: Decimal, n: int) -> tuple[str, str]:
    """Round to n significant figures, returning (plain text, scientific text); keeps trailing zeros that are significant."""
    if d == 0:
        txt = "0" if n == 1 else "0." + "0" * (n - 1)
        return txt, txt
    with localcontext() as ctx:
        ctx.prec = 80
        exp10 = d.adjusted()
        q = Decimal(1).scaleb(exp10 - n + 1)
        r = d.quantize(q, rounding=ROUND_HALF_UP)
        if r.adjusted() != exp10:                                    # 9.99 -> 10.0 gained a digit
            exp10 = r.adjusted()
            q = Decimal(1).scaleb(exp10 - n + 1)
            r = r.quantize(q, rounding=ROUND_HALF_UP)
        digits = str(abs(r).scaleb(-(exp10 - n + 1)).quantize(Decimal(1)))
        sign = "-" if r < 0 else ""
        sci_m = digits[0] + ("." + digits[1:] if n > 1 else "")
        sci = f"{sign}{sci_m}×10^{exp10}" if exp10 else f"{sign}{sci_m}"
        last = exp10 - n + 1
        if last >= 0:
            plain = f"{sign}{digits}{'0' * last}"
            if last > 0 and n < len(plain.lstrip('-')):
                plain = plain + ("" if n >= exp10 + 1 else "")
        else:
            plain = f"{sign}{r:f}" if last > -400 else sci
            # make sure the number of decimals is exactly -last
            plain = f"{sign}{abs(r).quantize(Decimal(1).scaleb(last)):f}"
        if last > 0:
            plain = plain  # trailing integer zeros are ambiguous; the scientific form is the unambiguous one
    return plain, sci


def sig_figs(params: dict, s: Settings) -> dict:
    mode = C.get(params, "mode", "count")
    out = C.Out(s)
    if mode == "count":
        d, n, last, amb = parse_measured(C.get(params, "value", required=True))
        out.step("Rules", "Non-zero digits and zeros between them count; leading zeros never count; trailing zeros count only after a decimal point")
        if amb:
            out.warn("Trailing zeros without a decimal point are ambiguous. Write 1.20e3 (3 figures) or 1200. (4 figures) to be clear.")
        plain, sci = _format_sig(d, n)
        return out.done(mode=mode, sigFigs=n, scientific=sci, leastSignificantPlace=f"10^{last}", ambiguous=amb)
    if mode == "round":
        d, n0, _, _ = parse_measured(C.get(params, "value", required=True))
        n = int(C.number(params, "figures", integer=True, lo=1, hi=60))
        plain, sci = _format_sig(d, n)
        out.step("Round half up to significant figures", f"{n} significant figure(s)")
        if n > n0:
            out.warn(f"The value only has {n0} significant figure(s); the extra digits are padding, not precision.")
        return out.done(mode=mode, rounded=plain, scientific=sci, sigFigs=n)
    if mode == "arithmetic":
        op = C.get(params, "operation", "add")
        raw = params.get("values")
        if not isinstance(raw, list) or not (2 <= len(raw) <= 20):
            raise C.field_error("values", "Give between 2 and 20 measured values")
        parsed = [parse_measured(v, "values") for v in raw]
        vals = [p[0] for p in parsed]
        with localcontext() as ctx:
            ctx.prec = 60
            if op == "add":
                res = sum(vals, Decimal(0))
            elif op == "subtract":
                res = vals[0] - sum(vals[1:], Decimal(0))
            elif op == "multiply":
                res = Decimal(1)
                for v in vals:
                    res *= v
            elif op == "divide":
                res = vals[0]
                for v in vals[1:]:
                    if v == 0:
                        raise DomainError("Division by zero")
                    res /= v
            else:
                raise C.field_error("operation", "Operation must be add, subtract, multiply or divide")
        if op in ("add", "subtract"):
            place = max(p[2] for p in parsed)                       # coarsest last significant place limits the result
            out.step("Addition and subtraction", "The result keeps as many decimal places as the least precise value")
            if res == 0:
                text, n = "0", 1
            else:
                with localcontext() as ctx:
                    ctx.prec = 80
                    r = res.quantize(Decimal(1).scaleb(place), rounding=ROUND_HALF_UP)
                    n = max(r.adjusted() - place + 1, 1) if r != 0 else 1
                    text = f"{r:f}" if place <= 0 else f"{r:f}"
            plain, sci = (text, text) if res == 0 else _format_sig(res.quantize(Decimal(1).scaleb(place), rounding=ROUND_HALF_UP), n)
            data = {"mode": mode, "result": plain, "scientific": sci, "sigFigs": n, "unroundedValue": str(res.normalize() if res != 0 else 0), "limitedBy": f"10^{place}"}
        else:
            n = min(p[1] for p in parsed)
            out.step("Multiplication and division", f"The result keeps as many significant figures as the least precise value ({n})")
            plain, sci = _format_sig(res, n)
            data = {"mode": mode, "result": plain, "scientific": sci, "sigFigs": n, "unroundedValue": str(res.normalize() if res != 0 else 0)}
        if any(p[3] for p in parsed):
            out.warn("A value has trailing zeros without a decimal point, so its precision is ambiguous; it was read as having those zeros not significant.")
        out.warn("Exact counts and defined conversion factors have unlimited significant figures; only measured values limit the result.")
        out.warn("Round only the final answer: with several steps, carry extra digits and round at the end.")
        return out.done(**data)
    raise BadRequest(f"Unknown mode '{mode}'")


# ------------------------------------------------------------------------------------------------------------------ uncertainty propagation
def _expr(text: str, field: str) -> sp.Expr:
    if len(text) > 500:
        raise C.field_error(field, "The formula is too long")
    ctx = Context(settings=Settings(units=False))
    try:
        res = parse(text, ParseOptions(units=False, allow_statements=False))
        v = Evaluator(ctx).run(res.node)
    except SciCalError as exc:
        exc.details = {**exc.details, "field": field}
        raise
    if not isinstance(v, sp.Expr):
        raise C.field_error(field, "The formula must give a number")
    return v


def _round_unc(value: float, unc: float) -> tuple[str, str, int]:
    """Report 'value ± unc' with the uncertainty to one significant figure (two if it starts with 1), value to the same place."""
    if unc == 0 or not math.isfinite(unc):
        return mp.nstr(value, 6), "0", 0
    d = Decimal(repr(unc))
    lead = int(d.scaleb(-d.adjusted()))
    n = 2 if lead == 1 else 1
    u_txt, _ = _format_sig(d, n)
    place = d.adjusted() - n + 1
    with localcontext() as ctx:
        ctx.prec = 60
        v = Decimal(repr(value)).quantize(Decimal(1).scaleb(place), rounding=ROUND_HALF_UP) if place < 400 else Decimal(repr(value))
    return f"{v:f}", u_txt, place


def uncertainty(params: dict, s: Settings) -> dict:
    out = C.Out(s)
    expr = _expr(C.text(params, "expression"), "expression")
    raw = params.get("variables")
    if not isinstance(raw, dict) or not raw:
        raise C.field_error("variables", "Give each variable's value and uncertainty, e.g. {\"m\": {\"value\": \"2.50\", \"uncertainty\": \"0.05\"}}")
    if len(raw) > 12:
        raise C.field_error("variables", "At most 12 variables")
    method = C.get(params, "method", "quadrature")
    if method not in ("quadrature", "worst_case"):
        raise C.field_error("method", "Method must be quadrature or worst_case")
    vals: dict[sp.Symbol, sp.Expr] = {}
    unc: dict[sp.Symbol, sp.Expr] = {}
    for name, spec in raw.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,15}", str(name)):
            raise C.field_error("variables", f"'{name}' is not a valid variable name")
        if not isinstance(spec, dict):
            raise C.field_error("variables", f"'{name}' needs a value and an uncertainty")
        v = C.number({"v": spec.get("value")}, "v")
        u = C.number({"v": spec.get("uncertainty", 0)}, "v", nonneg=True)
        vals[sp.Symbol(name)] = v
        unc[sp.Symbol(name)] = u
    free = expr.free_symbols
    missing = sorted(str(x) for x in free if x not in vals)
    if missing:
        raise C.field_error("variables", f"No value was given for: {', '.join(missing)}", hint="Every letter in the formula that is not a constant needs a value and an uncertainty.")
    unused = sorted(str(x) for x in vals if x not in free)
    if unused:
        out.warn(f"Not used in the formula: {', '.join(unused)}.")
    f0 = sp.N(expr.subs(vals), 30)
    if f0.has(sp.zoo, sp.nan, sp.oo) or not f0.is_real:
        raise EvaluationError("The formula is not a real number at these values")
    rows = []
    var_sum = mp.mpf(0)
    lin_sum = mp.mpf(0)
    for x in sorted(free, key=str):
        d = sp.diff(expr, x)
        dv = sp.N(d.subs(vals), 30)
        if not dv.is_real:
            raise EvaluationError(f"The sensitivity to {x} is not real at these values")
        contrib = abs(mp.mpf(str(dv))) * mp.mpf(str(sp.N(unc[x], 30)))
        var_sum += contrib ** 2
        lin_sum += contrib
        rows.append({"variable": str(x), "value": out.num(vals[x]), "uncertainty": out.num(unc[x]), "partial": sp.latex(d), "sensitivity": out.num(F(float(dv))),
                     "contribution": float(contrib)})
    total = mp.sqrt(var_sum) if method == "quadrature" else lin_sum
    for r in rows:
        c = mp.mpf(r["contribution"])
        if method == "quadrature":
            r["percentOfVariance"] = out.num(F(float(c ** 2 / var_sum * 100 if var_sum else 0)), "%")
        else:
            r["percentOfTotal"] = out.num(F(float(c / lin_sum * 100 if lin_sum else 0)), "%")
        r["contribution"] = out.num(F(r["contribution"]))
    fv = float(f0)
    v_txt, u_txt, place = _round_unc(fv, float(total))
    rel = float(total) / abs(fv) * 100 if fv else None
    out.step("Sensitivities", "For each variable, the partial derivative ∂f/∂x is found symbolically and evaluated at the measured values")
    if method == "quadrature":
        out.step("Combine in quadrature", "u(f) = √(Σ (∂f/∂xᵢ · uᵢ)²) — valid for independent, random uncertainties", latex=r"u_f=\sqrt{\sum_i\left(\frac{\partial f}{\partial x_i}u_i\right)^2}")
        out.warn("Assumes the input uncertainties are independent and small enough for a linear approximation.")
    else:
        out.step("Worst case", "u(f) = Σ |∂f/∂xᵢ| · uᵢ — a maximum bound, not a standard uncertainty")
    out.step("Report", "One significant figure for the uncertainty (two when it starts with 1); the value is rounded to the same decimal place")
    best = out.done(value=out.num(F(fv)), uncertainty=out.num(F(float(total))), relativeUncertainty=None if rel is None else out.num(F(rel), "%"),
                    reported=f"{v_txt} ± {u_txt}", contributions=rows, method=method, formulaLatex=sp.latex(expr))
    dom = max(rows, key=lambda r: r["contribution"]["value"])
    best["dominant"] = dom["variable"]
    return best


# ------------------------------------------------------------------------------------------------------------------ repeated measurements
def _data_list(params: dict, key: str, minimum: int) -> list[sp.Expr]:
    raw = params.get(key)
    if isinstance(raw, str):
        raw = [t for t in re.split(r"[\s,;]+", raw.strip()) if t]
    if not isinstance(raw, list) or len(raw) < minimum:
        raise C.field_error(key, f"Give at least {minimum} numbers")
    if len(raw) > MAX_POINTS:
        raise C.field_error(key, f"At most {MAX_POINTS} values")
    return [C.number({"v": v}, "v") for v in raw]


def _t_crit(p: float, df: float) -> float:
    return float(_invt(mp.mpf(p), mp.mpf(df)))


def repeated(params: dict, s: Settings) -> dict:
    out = C.Out(s)
    xs = np.array([float(v) for v in _data_list(params, "values", 2)])
    n = len(xs)
    level = float(C.number(params, "confidence", default="0.95", lo=0.5, hi=0.9999))
    mean, sd = float(xs.mean()), float(xs.std(ddof=1))
    sem = sd / math.sqrt(n)
    t = _t_crit(1 - (1 - level) / 2, n - 1)
    half = t * sem
    data: dict[str, Any] = {"n": n, "mean": out.num(F(mean)), "standardDeviation": out.num(F(sd)), "standardError": out.num(F(sem)),
                            "median": out.num(F(float(np.median(xs)))), "minimum": out.num(F(float(xs.min()))), "maximum": out.num(F(float(xs.max()))),
                            "range": out.num(F(float(xs.max() - xs.min()))), "relativeStandardDeviation": None if mean == 0 else out.num(F(abs(sd / mean) * 100), "%"),
                            "confidenceLevel": out.num(F(level)), "tValue": out.num(F(t)), "halfWidth": out.num(F(half)),
                            "interval": [out.num(F(mean - half)), out.num(F(mean + half))]}
    v_txt, u_txt, _ = _round_unc(mean, sem)
    data["reported"] = f"{v_txt} ± {u_txt} (standard error of the mean, n = {n})"
    out.step("Mean and sample standard deviation", "s uses n − 1 in the denominator")
    out.step("Standard error and confidence interval", f"mean ± t·s/√n with t = {t:.4g} (Student, {n - 1} degrees of freedom)")
    if n == 2:
        out.warn("With only two measurements the interval is extremely wide; take more.")
    if n >= 3 and sd > 0:
        i = int(np.argmax(np.abs(xs - mean)))
        g = abs(xs[i] - mean) / sd
        alpha = 0.05
        tc = _t_crit(1 - alpha / (2 * n), n - 2)
        gcrit = (n - 1) / math.sqrt(n) * math.sqrt(tc ** 2 / (n - 2 + tc ** 2))
        data["outlierTest"] = {"method": "Grubbs, two-sided, α = 0.05", "suspect": out.num(F(float(xs[i]))), "G": out.num(F(g)), "critical": out.num(F(gcrit)), "isOutlier": bool(g > gcrit)}
        if g > gcrit:
            out.warn(f"{xs[i]:g} is a statistical outlier by Grubbs' test. Investigate before removing it; never discard a point only because of a test.")
        if n < 7:
            out.warn("Grubbs' test assumes roughly normal data and is weak for very small samples.")
    acc = C.number(params, "accepted", required=False)
    if acc is not None:
        a = float(acc)
        tstat = (mean - a) / sem if sem else float("inf")
        p = float(2 * (1 - _tcdf(mp.mpf(abs(tstat)), mp.mpf(n - 1)))) if math.isfinite(tstat) else 0.0
        data["comparison"] = {"accepted": out.num(acc), "bias": out.num(F(mean - a)), "percentError": None if a == 0 else out.num(F(abs(mean - a) / abs(a) * 100), "%"),
                              "t": out.num(F(tstat)) if math.isfinite(tstat) else None, "pValue": out.num(F(p)), "significant": bool(p < 0.05),
                              "verdict": "The mean differs significantly from the accepted value (p < 0.05): suspect a systematic error." if p < 0.05 else "No significant difference from the accepted value."}
        out.step("One-sample t-test against the accepted value", "t = (mean − accepted) / SE, two-sided")
    return out.done(**data)


def percent_error(params: dict, s: Settings) -> dict:
    mode = C.get(params, "mode", "error")
    out = C.Out(s)
    if mode == "error":
        e, a = C.number(params, "experimental"), C.number(params, "accepted")
        if a == 0:
            raise DomainError("Percent error is undefined when the accepted value is 0", hint="Report the absolute error instead.")
        signed = (e - a) / a * 100
        out.step("Percent error", "|experimental − accepted| / |accepted| × 100")
        return out.done(mode=mode, percentError=out.num(abs(signed), "%"), signedPercentError=out.num(signed, "%"), absoluteError=out.num(abs(e - a)), signedError=out.num(e - a))
    if mode == "difference":
        a, b = C.number(params, "a"), C.number(params, "b")
        if a + b == 0:
            raise DomainError("The mean of the two values is 0, so a percent difference is undefined")
        out.step("Percent difference", "|a − b| / ((a + b)/2) × 100")
        return out.done(mode=mode, percentDifference=out.num(abs(a - b) / abs((a + b) / 2) * 100, "%"))
    raise BadRequest(f"Unknown mode '{mode}'")


# ------------------------------------------------------------------------------------------------------------------ calibration
def calibration(params: dict, s: Settings) -> dict:
    out = C.Out(s)
    pts = params.get("data")
    if not isinstance(pts, list) or len(pts) < 3:
        raise C.field_error("data", "Give at least three [x, y] points")
    if len(pts) > MAX_POINTS:
        raise C.field_error("data", "Too many points")
    try:
        x = np.array([float(C.number({"v": p[0]}, "v")) for p in pts])
        y = np.array([float(C.number({"v": p[1]}, "v")) for p in pts])
    except (TypeError, IndexError, KeyError):
        raise C.field_error("data", "Each point must be a pair [x, y]")
    n = len(x)
    sxx = float(((x - x.mean()) ** 2).sum())
    if sxx == 0:
        raise DomainError("All x values are the same, so no line can be fitted", details={"field": "data"})
    slope = float(((x - x.mean()) * (y - y.mean())).sum() / sxx)
    icpt = float(y.mean() - slope * x.mean())
    resid = y - (slope * x + icpt)
    sse = float(resid @ resid)
    syx = math.sqrt(sse / (n - 2))
    sst = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - sse / sst if sst else float("nan")
    se_m = syx / math.sqrt(sxx)
    se_b = syx * math.sqrt(1 / n + x.mean() ** 2 / sxx)
    t = _t_crit(0.975, n - 2)
    data: dict[str, Any] = {"n": n, "slope": out.num(F(slope)), "intercept": out.num(F(icpt)), "slopeStdError": out.num(F(se_m)), "interceptStdError": out.num(F(se_b)),
                            "rSquared": out.num(F(r2)), "residualStdDev": out.num(F(syx)), "slopeInterval95": [out.num(F(slope - t * se_m)), out.num(F(slope + t * se_m))],
                            "interceptInterval95": [out.num(F(icpt - t * se_b)), out.num(F(icpt + t * se_b))],
                            "residuals": [[float(a), float(b)] for a, b in zip(x, resid)],
                            "line": [[float(x.min()), float(slope * x.min() + icpt)], [float(x.max()), float(slope * x.max() + icpt)]]}
    out.step("Ordinary least squares", "slope = Sxy / Sxx; intercept = ȳ − slope·x̄; s(y/x) = √(SSE/(n − 2))")
    if slope != 0:
        data["detectionLimit"] = out.num(F(3.3 * syx / abs(slope)))
        data["quantificationLimit"] = out.num(F(10 * syx / abs(slope)))
        out.step("Limits (ICH Q2)", "LOD = 3.3·s(y/x)/slope;  LOQ = 10·s(y/x)/slope")
    if n == 3:
        out.warn("Three points leave one degree of freedom: the uncertainties are very rough.")
    if r2 == r2 and r2 < 0.99:
        out.warn("R² below 0.99: the line may not describe the data well. Look at the residual plot for curvature or outliers.")
    if abs(icpt) > 3 * se_b and se_b > 0:
        out.warn("The intercept differs significantly from zero (a blank or offset); check the blank before forcing the line through the origin.")
    unk = params.get("unknownResponses")
    if unk not in (None, "", []):
        ys = [float(v) for v in _data_list(params, "unknownResponses", 1)]
        m = len(ys)
        y0 = sum(ys) / m
        if slope == 0:
            raise DomainError("The slope is 0, so a response cannot be converted into a concentration")
        x0 = (y0 - icpt) / slope
        sx0 = syx / abs(slope) * math.sqrt(1 / m + 1 / n + (y0 - y.mean()) ** 2 / (slope ** 2 * sxx))
        tt = _t_crit(0.975, n - 2)
        data["unknown"] = {"meanResponse": out.num(F(y0)), "x": out.num(F(x0)), "standardError": out.num(F(sx0)), "interval95": [out.num(F(x0 - tt * sx0)), out.num(F(x0 + tt * sx0))],
                           "replicates": m}
        out.step("Inverse prediction", "x₀ = (ȳ₀ − intercept)/slope; s(x₀) = s(y/x)/|slope| · √(1/m + 1/n + (ȳ₀ − ȳ)²/(slope²·Sxx))")
        if not (min(x) <= x0 <= max(x)):
            out.warn("The unknown lies outside the calibrated range: this is an extrapolation and may be wrong.")
    return out.done(**data)


# ------------------------------------------------------------------------------------------------------------------ units and constants
def convert_units(params: dict, s: Settings) -> dict:
    out = C.Out(s)
    value = C.get(params, "value", required=True)
    src = C.text(params, "from", maxlen=60).strip()
    dst = C.text(params, "to", maxlen=60).strip()
    try:
        u_from, u_to = parse_unit(src), parse_unit(dst)
    except SciCalError as exc:
        exc.details = {**exc.details, "field": "from"}
        raise
    v = C.number({"v": value}, "v")
    q = convert(Quantity(v, u_from), u_to)
    out.step("Convert through SI", f"{u_from.pretty} → SI → {u_to.pretty}; all factors are exact rationals")
    if u_from.dim != u_to.dim:
        raise DimensionError("These units measure different things")
    si = to_si(Quantity(v, u_from))
    return out.done(result=out.num(q.mag, u_to.pretty), inSI=out.num(si.mag, si.unit.pretty), dimension=u_from.dim.name)


def dimensions(params: dict, s: Settings) -> dict:
    out = C.Out(s)
    raw = params.get("expressions")
    if not isinstance(raw, list) or not (1 <= len(raw) <= 10):
        raise C.field_error("expressions", "Give between 1 and 10 expressions with units, e.g. \"5 m/s * 2 s\"")
    rows = []
    for i, text in enumerate(raw):
        if not isinstance(text, str) or not text.strip() or len(text) > 300:
            raise C.field_error("expressions", f"Expression {i + 1} must be non-empty text of at most 300 characters")
        ctx = Context(settings=Settings(units=True))
        try:
            res = parse(text, ParseOptions(units=True, allow_statements=False))
            v = Evaluator(ctx).run(res.node)
        except SciCalError as exc:
            exc.details = {**exc.details, "field": "expressions", "index": i}
            raise
        if isinstance(v, Quantity):
            si = to_si(v)
            rows.append({"expression": text, "dimension": v.unit.dim.name, "si": out.num(si.mag, si.unit.pretty), "_dim": v.unit.dim})
        else:
            rows.append({"expression": text, "dimension": "dimensionless", "si": out.num(v), "_dim": None})
    same = len({(r["_dim"].exps if r["_dim"] is not None else None) for r in rows}) == 1
    for r in rows:
        r.pop("_dim")
    out.step("Dimensional analysis", "Each expression is reduced to powers of the seven SI base dimensions")
    data = {"expressions": rows, "consistent": same}
    if len(rows) > 1:
        data["verdict"] = "All expressions have the same dimension, so they can be added, subtracted or equated." if same else "The expressions have different dimensions, so they cannot be equal or added."
    return out.done(**data)


def unit_catalog(params: dict, s: Settings) -> dict:
    cats = []
    for name, syms in PICKER.items():
        items = []
        for sym in syms:
            try:
                d, _, _ = REGISTRY.resolve(sym.split("/")[0].split("^")[0]) if sym.isalpha() or sym in REGISTRY.defs else (None, None, None)
            except SciCalError:
                d = None
            items.append({"symbol": sym, "name": d.name if d is not None and sym == d.symbol else sym})
        cats.append({"category": name, "units": items})
    return {"ok": True, "categories": cats}


def constants(params: dict, s: Settings) -> dict:
    q = str(params.get("query", "")).strip().lower()
    meta = K.meta()
    out = C.Out(s)
    items = []
    for c in K.constants().values():
        if q and q not in c.key.lower() and q not in c.name.lower() and q not in c.symbol.lower():
            continue
        d = c.public(meta)
        d["valueNumber"] = out.num(c.value)["text"] if not c.exact else d["value"]
        items.append(d)
    return {"ok": True, "constants": items, "meta": meta, "count": len(items)}


from .uncertainty_lab import formula_uncertainty, uncertainty_budget

OPS = {"uncertainty_budget": uncertainty_budget, "formula_uncertainty": formula_uncertainty, "sig_figs": sig_figs, "uncertainty": uncertainty, "repeated": repeated, "percent_error": percent_error, "calibration": calibration,
       "convert": convert_units, "dimensions": dimensions, "units": unit_catalog, "constants": constants}
