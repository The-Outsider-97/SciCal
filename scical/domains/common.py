"""Shared input handling and result formatting for the subject workspaces."""
from __future__ import annotations

from typing import Any

import sympy as sp

from ..core.expressions import ParseOptions, parse
from ..core.numerical.context import Context, Settings
from ..core.numerical.evaluator import Evaluator
from ..core.numerical.format import Formatter
from ..core.units import Quantity, Unit, convert, parse_unit
from ..core.units.dimension import Dim
from ..errors import BadRequest, DimensionError, SciCalError, UnitError

MAX_TEXT = 20_000


def field_error(field: str, message: str, hint: str | None = None, cls=BadRequest) -> SciCalError:
    return cls(message, details={"field": field}, hint=hint)


def get(params: dict, key: str, default: Any = None, required: bool = False) -> Any:
    v = params.get(key, default)
    if required and (v is None or (isinstance(v, str) and not v.strip())):
        raise field_error(key, f"'{key}' is required")
    return v


def text(params: dict, key: str, required: bool = True, maxlen: int = MAX_TEXT) -> str:
    v = get(params, key, None, required)
    if v is None:
        return ""
    if not isinstance(v, str):
        raise field_error(key, f"'{key}' must be text")
    if len(v) > maxlen:
        raise field_error(key, f"'{key}' is too long (limit {maxlen} characters)")
    return v


def _eval_value(value: Any, units: bool, key: str) -> Any:
    if isinstance(value, bool):
        raise field_error(key, f"'{key}' must be a number")
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise field_error(key, f"'{key}' must be a finite number")
        return sp.Rational(str(value))
    if not isinstance(value, str) or not value.strip():
        raise field_error(key, f"'{key}' must be a number" + (" with a unit" if units else ""))
    if len(value) > 200:
        raise field_error(key, f"'{key}' is too long")
    ctx = Context(settings=Settings(units=units))
    try:
        res = parse(value, ParseOptions(units=units, allow_statements=False))
        v = Evaluator(ctx).run(res.node)
    except SciCalError as exc:
        exc.details = {**exc.details, "field": key}
        raise
    return v


def number(params: dict, key: str, *, default: Any = None, positive: bool = False, nonneg: bool = False, lo: Any = None, hi: Any = None,
           integer: bool = False, required: bool = True) -> sp.Expr | None:
    raw = params.get(key, default)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if required and default is None:
            raise field_error(key, f"'{key}' is required")
        return None
    v = _eval_value(raw, False, key)
    if isinstance(v, Quantity):
        raise field_error(key, f"'{key}' must be a plain number without a unit", cls=UnitError)
    if not isinstance(v, sp.Expr) or v.free_symbols or not v.is_real:
        raise field_error(key, f"'{key}' must be a real number")
    if integer and not v.is_integer:
        raise field_error(key, f"'{key}' must be a whole number")
    if positive and not v > 0:
        raise field_error(key, f"'{key}' must be greater than 0")
    if nonneg and v < 0:
        raise field_error(key, f"'{key}' cannot be negative")
    if lo is not None and v < lo:
        raise field_error(key, f"'{key}' must be at least {lo}")
    if hi is not None and v > hi:
        raise field_error(key, f"'{key}' must be at most {hi}")
    return v


def quantity(params: dict, key: str, dim_unit: str, *, default: Any = None, positive: bool = False, nonneg: bool = False,
             required: bool = True, to: str | None = None) -> Quantity | None:
    """A value with a unit, checked to have the dimension of ``dim_unit`` (for example 'g' for a mass); returned in ``to`` or ``dim_unit``."""
    raw = params.get(key, default)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if required and default is None:
            raise field_error(key, f"'{key}' is required")
        return None
    target = parse_unit(to or dim_unit)
    if isinstance(raw, dict):
        val, unit = raw.get("value"), raw.get("unit")
        raw = f"{val} {unit}" if unit else val
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw = f"{raw} {dim_unit}"
    v = _eval_value(raw, True, key)
    if not isinstance(v, Quantity):
        v = Quantity(v, parse_unit(dim_unit))                 # a bare number is taken in the default unit
    if v.unit.dim != parse_unit(dim_unit).dim:
        raise field_error(key, f"'{key}' must be {Dim_name(dim_unit)} (got {v.unit.pretty or 'a number'} = {v.unit.dim.name})", cls=DimensionError)
    q = convert(v, target)
    m = q.mag
    if not (isinstance(m, sp.Expr) and m.is_real and not m.free_symbols):
        raise field_error(key, f"'{key}' must be a real number with a unit")
    if positive and not m > 0:
        raise field_error(key, f"'{key}' must be greater than 0")
    if nonneg and m < 0:
        raise field_error(key, f"'{key}' cannot be negative")
    return q


def Dim_name(unit: str) -> str:
    return parse_unit(unit).dim.name or unit


def mag(q: Quantity | None) -> sp.Expr | None:
    return None if q is None else q.mag


class Out:
    """Collects a domain result: values, working and warnings."""

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.fmt = Formatter(settings.with_(result="approx"))          # measured quantities read better as decimals; fractions stay in "exact"
        self.data: dict[str, Any] = {"ok": True}
        self.steps: list[dict[str, str]] = []
        self.warnings: list[str] = []

    def num(self, x: Any, unit: str | None = None) -> dict[str, Any]:
        x = sp.sympify(x)
        v = self.fmt.scalar(x)
        out: dict[str, Any] = {"text": v["text"], "latex": v["latex"], "value": float(sp.N(x)) if x.is_real else None}
        if v.get("exact") and v["primary"] == "approx" and not x.atoms(sp.Float) and len(v["exact"]["text"]) <= 28:
            out["exact"] = v["exact"]["text"]
        if x.atoms(sp.Float):
            out["approximate"] = True
        if unit:
            out["unit"] = unit
            out["text"] = f"{out['text']} {unit}"
            ul = unit.replace("%", r"\%").replace("_", r"\_")
            out["latex"] = f"{out['latex']}\\,\\mathrm{{{ul}}}"
        return out

    def step(self, title: str, detail: str = "", latex: str = "") -> None:
        s = {"title": title}
        if detail:
            s["detail"] = detail
        if latex:
            s["latex"] = latex
        self.steps.append(s)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def done(self, **kw: Any) -> dict[str, Any]:
        self.data.update(kw)
        if self.steps:
            self.data["steps"] = self.steps
        if self.warnings:
            self.data["warnings"] = self.warnings
        return self.data
