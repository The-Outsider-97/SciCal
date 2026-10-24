"""Equation parsing, dimensional analysis of SymPy expressions, and solving for one variable."""
from __future__ import annotations

from fractions import Fraction
from typing import Any

import sympy as sp

from ...core.expressions import ParseOptions, parse
from ...core.numerical.context import Context, Settings
from ...core.numerical.evaluator import Evaluator
from ...core.numerical.values import Equation
from ...core.units import PICKER, REGISTRY, Dim, Quantity, Unit, convert, parse_unit, to_si
from ...core.units.dimension import BASE
from ...errors import BadRequest, DimensionError, EvaluationError, MissingVariableError, SciCalError, UnitError

_SI_SYMBOL = {"L": "m", "M": "kg", "T": "s", "I": "A", "Θ": "K", "N": "mol", "J": "cd"}
_PREFERRED = ["N", "J", "W", "Pa", "Hz", "C", "V", "ohm", "F", "S", "Wb", "T", "H", "Gy"]
MAX_EQ = 400


def parse_equation(text: str, field: str = "equation") -> Equation:
    if not isinstance(text, str) or not text.strip():
        raise BadRequest(f"'{field}' is required", details={"field": field})
    if len(text) > MAX_EQ:
        raise BadRequest(f"The equation is too long (limit {MAX_EQ} characters)", details={"field": field})
    ctx = Context(settings=Settings(units=False))
    try:
        res = parse(text, ParseOptions(units=False, allow_statements=False))
        v = Evaluator(ctx).run(res.node)
    except SciCalError as exc:
        exc.details = {**exc.details, "field": field}
        if "is a function" in str(exc) and not exc.hint:
            exc.hint = "That name is a built-in function, so it cannot be a variable here. Rename the variable (for example q1 → qa)."
        raise
    if not isinstance(v, Equation) or v.op != "=":
        raise BadRequest("Write an equation with one '=' sign and at least one unknown, e.g. F = m*a", details={"field": field})
    return v


def dim_of(e: sp.Basic, dims: dict[sp.Symbol, Dim]) -> Dim:
    """The dimension of a SymPy expression given the dimension of each symbol; raises DimensionError when it is inconsistent."""
    one = Dim()
    if isinstance(e, sp.Symbol):
        if e not in dims:
            raise MissingVariableError(f"The dimension of '{e}' is unknown")
        return dims[e]
    if e.is_Number or isinstance(e, sp.NumberSymbol) or e in (sp.I, sp.zoo, sp.oo):
        return one
    if isinstance(e, sp.Add):
        ds = [dim_of(a, dims) for a in e.args]
        for d, a in zip(ds[1:], e.args[1:]):
            if d != ds[0]:
                raise DimensionError(f"Cannot add {ds[0].name} and {d.name} in '{sp.sstr(e)}'", hint="Every term of a sum must have the same dimension.",
                                     details={"left": ds[0].name, "right": d.name})
        return ds[0]
    if isinstance(e, sp.Mul):
        out = one
        for a in e.args:
            out = out * dim_of(a, dims)
        return out
    if isinstance(e, sp.Pow):
        b, x = e.args
        db, dx = dim_of(b, dims), dim_of(x, dims)
        if not dx.is_dimensionless():
            raise DimensionError(f"An exponent must be dimensionless, but '{sp.sstr(x)}' is {dx.name}")
        if db.is_dimensionless():
            return one
        if not x.is_Rational:
            raise DimensionError(f"A quantity with a dimension ({db.name}) can only be raised to a fixed rational power")
        return db ** Fraction(int(x.p), int(x.q))
    if isinstance(e, (sp.Abs, sp.Max, sp.Min, sp.sign, sp.re, sp.im, sp.floor, sp.ceiling)):
        ds = [dim_of(a, dims) for a in e.args]
        if isinstance(e, sp.sign):
            return one
        if any(d != ds[0] for d in ds):
            raise DimensionError(f"The arguments of {e.func.__name__} must share one dimension")
        return ds[0]
    if isinstance(e, sp.Function) or e.is_Function:
        for a in e.args:
            d = dim_of(a, dims)
            if not d.is_dimensionless():
                raise DimensionError(f"The argument of {e.func.__name__}() must be dimensionless, but '{sp.sstr(a)}' is {d.name}",
                                     hint="Divide by a reference quantity first, e.g. log(c / c0).")
        return one
    raise DimensionError(f"Cannot analyse the dimension of {type(e).__name__}")


def si_unit_for(d: Dim) -> Unit:
    if d.is_dimensionless():
        return Unit(())
    for sym in _PREFERRED:
        try:
            u = parse_unit(sym)
        except SciCalError:
            continue
        if u.dim == d and u.scale == 1:
            return u
    facs = [(_SI_SYMBOL[b], e) for b, e in zip(BASE, d.exps) if e]
    order = ("m", "kg", "s", "A", "K", "mol", "cd")
    facs.sort(key=lambda f: order.index(f[0]))
    return Unit(facs)


def to_dim_unit(text: str) -> Unit:
    t = (text or "").strip()
    return Unit(()) if t in ("", "1") else parse_unit(t)


def quantity_si(q: Any) -> tuple[sp.Expr, Dim]:
    if isinstance(q, Quantity):
        si = to_si(q)
        return si.mag, q.unit.dim
    return sp.sympify(q), Dim()


def solve_for(eq: Equation, target: sp.Symbol, known: dict[sp.Symbol, sp.Expr]) -> list[sp.Expr]:
    """All real solutions for ``target`` after substituting the known values; raises when none exist."""
    unknown = (eq.symbols() - {target}) - set(known)
    if unknown:
        raise MissingVariableError("A value is missing for: " + ", ".join(sorted(str(u) for u in unknown)),
                                   hint=f"To solve for {target}, give a value for every other variable.")
    e = sp.Eq(eq.lhs.subs(known), eq.rhs.subs(known))
    if e is sp.true:
        raise EvaluationError(f"{target} does not appear in the equation (or the equation is always true)")
    if e is sp.false:
        raise EvaluationError("These values contradict the equation")
    try:
        sols = sp.solve(e, target, dict=False)
    except (NotImplementedError, TypeError) as exc:
        raise EvaluationError(f"This equation cannot be solved for {target} in closed form") from exc
    real = []
    for s_ in sols:
        s_ = sp.simplify(s_)
        v = sp.N(s_, 30)
        if v.is_real or (v.is_number and abs(sp.im(v)) < sp.Float(10) ** -25):
            real.append(sp.re(s_) if s_.is_real is None and v.is_number and not s_.is_real else s_)
    if not real:
        raise EvaluationError(f"No real value of {target} satisfies the equation with these values")
    return real
