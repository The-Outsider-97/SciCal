"""Algebra and calculus: simplify, solve, differentiate, integrate, limits, series, critical points, and the numerical counterparts.

Symbolic results are exact. Where no closed form exists the function says so and points to the numerical version (nsolve, nintegral).
"""
from __future__ import annotations

from typing import Any

import mpmath as mp
import sympy as sp

from ...errors import (DomainError, EvaluationError, LimitExceeded, MissingVariableError, NotConvergedError, UndefinedError,
                       UnsupportedOperation)
from ..expressions import ast as A
from ..units import Quantity
from . import ops
from .registry import handler
from .values import Equation, SolutionSet, Table, Vec

mp.mp.dps = 40


# ------------------------------------------------------------------------------------------------------------------ helpers
def expr_arg(v: Any, name: str) -> sp.Expr:
    if isinstance(v, Equation):
        raise EvaluationError(f"{name}() needs an expression, not an equation")
    if isinstance(v, Quantity):
        raise EvaluationError(f"{name}() works on expressions without units")
    if not isinstance(v, sp.Expr) or isinstance(v, sp.MatrixBase):
        raise EvaluationError(f"{name}() needs an expression such as x^2 + 1")
    return v


def pick_symbol(expr: sp.Expr, sym: Any, name: str) -> sp.Symbol:
    if sym is not None:
        return sym
    free = sorted(expr.free_symbols, key=lambda s: s.name)
    if len(free) == 1:
        return free[0]
    if not free:
        raise MissingVariableError(f"{name}() has no variable to work with: the expression is a constant")
    raise MissingVariableError(f"{name}() needs to know the variable (the expression contains {', '.join(s.name for s in free)})",
                               hint=f"Write {name}(expression, x).")


def real_view(ev, expr: sp.Expr, *syms: sp.Symbol):
    """In real mode, treat the working symbols as real (so abs(x) differentiates to sign(x), sqrt(x^2) is |x| ...)."""
    if ev.complex_mode:
        return expr, list(syms), lambda e: e
    reals = [sp.Symbol(s.name, real=True) for s in syms]
    fwd = dict(zip(syms, reals))
    back = {r: s for s, r in fwd.items()}
    return expr.xreplace(fwd), reals, lambda e: e.xreplace(back)


def numeric_fn(expr: sp.Expr, x: sp.Symbol, name: str):
    others = expr.free_symbols - {x}
    if others:
        raise MissingVariableError(f"{name}() needs a value for {', '.join(sorted(s.name for s in others))}",
                                   hint="Give the variable a value first, for example a := 2.")
    f = sp.lambdify(x, expr, modules="mpmath")

    def g(t):
        try:
            return f(t)
        except ZeroDivisionError:
            raise UndefinedError("The function is undefined at one of the points tested") from None
    return g


def _real_val(v, what):
    if isinstance(v, mp.mpc):
        if abs(v.imag) > mp.mpf(10) ** -30 * max(1, abs(v.real)):
            raise DomainError(f"The function has complex values in the range tested ({what})")
        return v.real
    return v


def _flt(ev, x, method, **info) -> sp.Float:
    ev.numeric_method = method
    ev.numeric_info.update(info)
    return sp.Float(mp.nstr(x, 35, min_fixed=-1000, max_fixed=1000), 35)


# ------------------------------------------------------------------------------------------------------------------ algebra
@handler("simplify")
def f_simplify(ev, e):
    return sp.simplify(expr_arg(e, "simplify"))


@handler("expand")
def f_expand(ev, e):
    return sp.expand(expr_arg(e, "expand"))


@handler("factor")
def f_factor(ev, e):
    e = expr_arg(e, "factor")
    return sp.factor(e, extension=[sp.I] if ev.complex_mode else None)


@handler("apart")
def f_apart(ev, e, x=None):
    e = expr_arg(e, "apart")
    return sp.apart(e, pick_symbol(e, x, "apart"))


@handler("together")
def f_together(ev, e):
    return sp.together(expr_arg(e, "together"))


@handler("subs")
def f_subs(ev, e, x, value):
    e = expr_arg(e, "subs")
    v = ops.plain(value, "subs()")
    out = e.subs(x, v)
    ev.check(out)
    return out


def _poly(e: sp.Expr, x: sp.Symbol, name: str) -> sp.Poly:
    try:
        p = sp.Poly(e, x)
    except sp.PolynomialError:
        raise DomainError(f"{name}() needs a polynomial in {x.name}") from None
    return p


@handler("coeffs")
def f_coeffs(ev, e, x=None):
    e = expr_arg(e, "coeffs")
    return Vec(tuple(_poly(e, pick_symbol(e, x, "coeffs"), "coeffs").all_coeffs()))


@handler("degree")
def f_degree(ev, e, x=None):
    e = expr_arg(e, "degree")
    return sp.Integer(_poly(e, pick_symbol(e, x, "degree"), "degree").degree())


@handler("roots")
def f_roots(ev, e, x=None):
    e = expr_arg(e, "roots")
    x = pick_symbol(e, x, "roots")
    p = _poly(e, x, "roots")
    if p.degree() < 1:
        raise DomainError("A constant has no roots")
    if p.degree() > 20:
        raise LimitExceeded("Exact roots are limited to degree 20")
    found = sp.roots(p)
    if sum(found.values()) < p.degree():
        found = {}
        for r in p.all_roots():
            found[r] = found.get(r, 0) + 1
    rows, hidden = [], 0
    for r, m in sorted(found.items(), key=lambda kv: (sp.re(sp.N(kv[0], 30)), sp.im(sp.N(kv[0], 30)))):
        if not ev.complex_mode and sp.N(sp.im(r), 30) != 0:
            hidden += m
            continue
        rows.append((r, sp.Integer(m)))
    title = f"Roots of {sp.sstr(e)}"
    if hidden:
        title += f" ({hidden} complex root{'s' if hidden != 1 else ''} not shown in real mode)"
    return Table(("root", "multiplicity"), tuple(rows), title=title)


# ------------------------------------------------------------------------------------------------------------------ solving
def _relation(eq: Any, name: str) -> Equation:
    if isinstance(eq, Equation):
        return eq
    if isinstance(eq, bool):
        raise EvaluationError(f"{name}(): this equation contains no unknown, so it is simply {'true' if eq else 'false'}")
    if isinstance(eq, sp.Expr) and not isinstance(eq, sp.MatrixBase):
        return Equation(eq, sp.Integer(0), "=")
    raise EvaluationError(f"{name}() needs an equation such as x^2 = 4, or an expression that equals 0")


def _sort_solutions(sols: list, complex_mode: bool) -> list:
    def k(s):
        n = sp.N(s, 30)
        return (float(sp.re(n)), float(sp.im(n)))
    try:
        return sorted(sols, key=k)
    except (TypeError, ValueError):
        return sols


def _classify(sol: sp.Basic, ev, x) -> SolutionSet:
    domain = "complex" if ev.complex_mode else "real"
    if sol == sp.EmptySet:
        return SolutionSet(x, (), None, domain, "no solution" if ev.complex_mode else "no real solution")
    if isinstance(sol, sp.FiniteSet):
        return SolutionSet(x, tuple(_sort_solutions(list(sol), ev.complex_mode)), None, domain)
    if sol.has(sp.ConditionSet):
        raise UnsupportedOperation("No closed-form solution was found",
                                   hint="Use nsolve(f, x, guess) for a numerical root, or graph the function to find a good starting value.")
    return SolutionSet(x, (), sol, domain)


def solve_single(ev, eq: Equation, x: sp.Symbol) -> SolutionSet:
    domain = sp.Complexes if ev.complex_mode else sp.Reals
    if eq.op != "=" and ev.complex_mode:
        raise DomainError("Inequalities are only meaningful over the real numbers", hint="Switch to real mode.")
    if eq.op == "!=":
        sol = sp.solveset(sp.Eq(eq.lhs, eq.rhs), x, domain)
        sol = domain.complement(sol) if not isinstance(domain, type) else sp.Complement(domain, sol)
        return _classify(sol, ev, x)
    if eq.op == "=":
        e = sp.simplify(eq.lhs - eq.rhs) if not eq.lhs.has(sp.Abs, sp.Piecewise) else eq.lhs - eq.rhs
        sol = sp.solveset(sp.Eq(eq.lhs, eq.rhs) if e.has(sp.Abs) else e, x, domain)
    else:
        sol = sp.solveset(eq.to_sympy(), x, domain)
    return _classify(sol, ev, x)


def solve_equation(ev, eq: Equation) -> SolutionSet:
    syms = sorted(eq.symbols(), key=lambda s: s.name)
    if len(syms) != 1:
        raise MissingVariableError(f"The equation has several unknowns ({', '.join(s.name for s in syms)}); say which one to solve for",
                                   hint=f"Write solve({_short(eq)}, {syms[0].name}).")
    return solve_single(ev, eq, syms[0])


def _short(eq: Equation) -> str:
    return f"{sp.sstr(eq.lhs)} {eq.op} {sp.sstr(eq.rhs)}"


def solve_system(ev, eqs: list[Equation], xs: list[sp.Symbol]) -> SolutionSet:
    if any(e.op != "=" for e in eqs):
        raise UnsupportedOperation("Systems of inequalities are not supported", hint="Solve each inequality on its own and combine with 'and'.")
    if len(xs) > 6 or len(eqs) > 12:
        raise LimitExceeded("Systems are limited to 6 unknowns and 12 equations")
    exprs = [sp.expand(e.lhs - e.rhs) for e in eqs]
    linear = all(sp.Poly(e, *xs).total_degree() <= 1 for e in exprs if e.free_symbols & set(xs)) if all(e.is_polynomial(*xs) for e in exprs) else False
    if linear:
        res = sp.linsolve(exprs, xs)
    else:
        res = sp.nonlinsolve(exprs, xs)
    domain = "complex" if ev.complex_mode else "real"
    if res == sp.EmptySet or not list(res):
        return SolutionSet(tuple(xs), (), None, domain, "no solution")
    if not isinstance(res, sp.FiniteSet):
        if isinstance(res, sp.ConditionSet) or res.has(sp.ConditionSet):
            raise UnsupportedOperation("No closed-form solution of this system was found")
    sols = []
    for tup in res:
        if not ev.complex_mode and any(t.has(sp.I) or (t.is_number and t.is_real is False) for t in tup):
            continue
        sols.append(tuple(tup))
    if not sols:
        return SolutionSet(tuple(xs), (), None, domain, "no real solution")
    return SolutionSet(tuple(xs), tuple(sols), None, domain)


def unknown_names(nodes: list[A.Node]) -> list[str] | None:
    names: list[str] = []
    for n in nodes:
        if isinstance(n, A.Var):
            names.append(n.name)
        elif isinstance(n, A.Vector) and n.items and all(isinstance(i, A.Var) for i in n.items):
            names.extend(i.name for i in n.items)                                  # type: ignore[attr-defined]
        else:
            return None
    return names


@handler("solve", raw=True)
def f_solve(ev, node, series):
    args = list(node.args)
    # trailing arguments that are plain names (or a list of names) are the unknowns
    cut = len(args)
    while cut > 1 and unknown_names([args[cut - 1]]) is not None:
        cut -= 1
    eq_nodes, var_nodes = args[:cut], args[cut:]
    names = unknown_names(var_nodes) or []
    if len(eq_nodes) == 1 and isinstance(eq_nodes[0], A.Vector) and names == [] and all(isinstance(i, A.Var) for i in eq_nodes[0].items) and eq_nodes[0].items:
        raise EvaluationError("solve() needs an equation before the list of unknowns")
    layer = {nm: sp.Symbol(nm) for nm in names}
    ev.shadow.append(layer)
    try:
        if len(eq_nodes) == 1 and isinstance(eq_nodes[0], A.Vector):
            raw_eqs = [ev.ev(i) for i in eq_nodes[0].items]
        else:
            raw_eqs = [ev.ev(i) for i in eq_nodes]
    finally:
        ev.shadow.pop()
    eqs = [_relation(e, "solve") for e in raw_eqs]
    syms = [layer[nm] for nm in names] if names else sorted({s for e in eqs for s in e.symbols()}, key=lambda s: s.name)
    if not syms:
        raise MissingVariableError("There is no unknown to solve for")
    if len(eqs) == 1 and len(syms) == 1:
        return solve_single(ev, eqs[0], syms[0])
    if len(eqs) == 1:
        raise MissingVariableError(f"One equation cannot determine {len(syms)} unknowns ({', '.join(s.name for s in syms)})",
                                   hint="Solve for one of them: solve(equation, x), or supply as many equations as unknowns.")
    if len(syms) != len(eqs):
        ev.warn(f"{len(eqs)} equations for {len(syms)} unknowns: the solution may be underdetermined or overdetermined.")
    return solve_system(ev, eqs, syms)


def combine_conditions(ev, op: str, vals: list) -> Any:
    eqs = [v for v in vals if isinstance(v, Equation)]
    syms = set().union(*[e.symbols() for e in eqs]) if eqs else set()
    if len(syms) != 1:
        raise EvaluationError("Combined conditions must involve exactly one unknown")
    if ev.complex_mode:
        raise DomainError("Combined conditions are solved over the real numbers", hint="Switch to real mode.")
    (x,) = syms
    sets = []
    for v in vals:
        if isinstance(v, bool):
            sets.append(sp.Reals if v else sp.EmptySet)
        else:
            sets.append(sp.solveset(v.to_sympy() if v.op != "=" else sp.Eq(v.lhs, v.rhs), x, sp.Reals))
    if op == "and":
        res = sp.Intersection(*sets)
    elif op == "or":
        res = sp.Union(*sets)
    else:
        res = sp.Complement(sp.Reals, sets[0])
    return _classify(res, ev, x)


# ------------------------------------------------------------------------------------------------------------------ calculus
@handler("diff")
def f_diff(ev, e, x, n=None):
    e = expr_arg(e, "diff")
    order = 1 if n is None else ops.as_int(n, "The derivative order", 1, 20)
    er, (xr,), back = real_view(ev, e, x)
    out = back(sp.diff(er, xr, order))
    return out


@handler("integral")
def f_integral(ev, e, x, a=None, b=None):
    e = expr_arg(e, "integral")
    er, (xr,), back = real_view(ev, e, x)
    if a is None:
        res = sp.integrate(er, xr)
        if res.has(sp.Integral):
            raise UnsupportedOperation("No closed-form antiderivative was found",
                                       hint="Use nintegral(f, x, a, b) for a numerical value over an interval.")
        return back(res) + sp.Symbol("C")
    if b is None:
        raise EvaluationError("integral() needs both limits: integral(f, x, a, b)")
    lo, hi = ops.plain(a, "integral()"), ops.plain(b, "integral()")
    if lo.free_symbols or hi.free_symbols:
        pass
    _check_poles(ev, er, xr, lo, hi)
    res = sp.integrate(er, (xr, lo, hi))
    if res.has(sp.Integral):
        raise UnsupportedOperation("No closed form was found for this definite integral", hint="Use nintegral(f, x, a, b) for a numerical value.")
    ev.check(res)
    return back(res)


def _check_poles(ev, e: sp.Expr, x: sp.Symbol, lo, hi) -> None:
    if not (lo.is_number and hi.is_number and lo.is_real and hi.is_real):
        return
    try:
        l, h = (lo, hi) if lo <= hi else (hi, lo)
        sing = sp.singularities(e, x)
    except Exception:
        return
    for s in sing:
        if s.is_real and l < s < h:
            raise UndefinedError(f"The integrand is undefined at {sp.sstr(s)}, inside the interval of integration",
                                 hint="Split the integral at the singularity and take limits on each side.")


@handler("nintegral")
def f_nintegral(ev, e, x, a, b):
    e = expr_arg(e, "nintegral")
    fn = numeric_fn(e, x, "nintegral")
    lo, hi = _bound(a), _bound(b)
    pts = [lo, hi]
    val, err = mp.quad(lambda t: _real_val(fn(t), "nintegral"), pts, error=True, maxdegree=10)
    if err > mp.mpf(10) ** -8 * max(1, abs(val)):
        raise NotConvergedError("The numerical integral did not converge to the requested accuracy",
                                hint="The function may have a singularity or oscillate wildly in the interval; split the interval.",
                                details={"estimate": mp.nstr(val, 12), "error estimate": mp.nstr(err, 3)})
    return _flt(ev, val, "adaptive Gauss-Legendre/tanh-sinh quadrature (mpmath)", error=mp.nstr(err, 3))


def _bound(v):
    x = ops.plain(v, "A limit")
    if x == sp.oo:
        return mp.inf
    if x == -sp.oo:
        return -mp.inf
    if x.free_symbols or not x.is_real:
        raise EvaluationError("The limits must be real numbers")
    return mp.mpf(str(sp.N(x, 45)))


@handler("nderiv")
def f_nderiv(ev, e, x, a):
    e = expr_arg(e, "nderiv")
    fn = numeric_fn(e, x, "nderiv")
    pt = _bound(a)
    g = lambda t: _real_val(fn(t), "nderiv")                                    # noqa: E731
    d1 = mp.diff(g, pt, h=mp.mpf(10) ** -12)
    d2 = mp.diff(g, pt, h=mp.mpf(10) ** -13)
    return _flt(ev, d1, "central difference (mpmath, 40 digits)", error=mp.nstr(abs(d1 - d2), 3))


@handler("limit")
def f_limit(ev, e, x, a, d=None):
    e = expr_arg(e, "limit")
    pt = ops.plain(a, "limit()")
    er, (xr,), back = real_view(ev, e, x)
    if d is not None:
        dd = ops.plain(d, "The direction")
        if dd not in (1, -1):
            raise DomainError("The direction must be 1 (from the right) or -1 (from the left)")
        res = sp.limit(er, xr, pt, "+" if dd == 1 else "-")
        return _lim_result(back(res))
    if pt in (sp.oo, -sp.oo):
        return _lim_result(back(sp.limit(er, xr, pt)))
    right, left = sp.limit(er, xr, pt, "+"), sp.limit(er, xr, pt, "-")
    if right != left:
        try:
            if sp.simplify(right - left) == 0:
                return _lim_result(back(right))
        except Exception:
            pass
        raise UndefinedError(f"The limit does not exist: from the left it is {sp.sstr(back(left))}, from the right {sp.sstr(back(right))}",
                             hint="Use the direction argument for a one-sided limit: limit(f, x, a, 1) or limit(f, x, a, -1).")
    return _lim_result(back(right))


def _lim_result(res: sp.Expr) -> sp.Expr:
    if res.has(sp.Limit):
        raise UnsupportedOperation("SymPy could not determine this limit")
    if res is sp.nan or res.has(sp.nan):
        raise UndefinedError("The limit does not exist")
    if res.has(sp.AccumBounds):
        raise UndefinedError("The limit does not exist (the function oscillates)")
    return res


@handler("taylor")
def f_taylor(ev, e, x, a, n):
    e = expr_arg(e, "taylor")
    pt = ops.plain(a, "taylor()")
    order = ops.as_int(n, "The degree", 0, 30)
    er, (xr,), back = real_view(ev, e, x)
    res = sp.series(er, xr, pt, order + 1).removeO()
    return back(sp.expand(res))


@handler("critical")
def f_critical(ev, e, x):
    e = expr_arg(e, "critical")
    er, (xr,), back = real_view(ev, e, x)
    d1 = sp.diff(er, xr)
    sol = sp.solveset(d1, xr, sp.Reals)
    if not isinstance(sol, sp.FiniteSet):
        raise UnsupportedOperation("The critical points could not be found in closed form",
                                   hint="Use nsolve on the derivative with a starting value from the graph.")
    d2 = sp.diff(er, xr, 2)
    rows = []
    for p in _sort_solutions(list(sol), False):
        val = er.subs(xr, p)
        s2 = d2.subs(xr, p)
        if s2.is_number and s2 > 0:
            kind = sp.Symbol("local minimum")
        elif s2.is_number and s2 < 0:
            kind = sp.Symbol("local maximum")
        else:
            kind = sp.Symbol("inconclusive (second derivative is 0)")
        rows.append((back(p), back(val), kind))
    return Table(("x", "f(x)", "type"), tuple(rows), title=f"Critical points of {sp.sstr(e)}")


@handler("nsolve")
def f_nsolve(ev, e, x, a, b=None):
    e = expr_arg(e, "nsolve")
    fn = numeric_fn(e, x, "nsolve")
    if b is None:
        guess = ops.plain(a, "nsolve()")
        g0 = complex(sp.N(guess)) if ev.complex_mode and not guess.is_real else mp.mpf(str(sp.N(guess, 45)))
        try:
            root = mp.findroot(fn, g0, tol=mp.mpf(10) ** -30, maxsteps=200)
        except (ValueError, ZeroDivisionError, ArithmeticError) as exc:
            raise NotConvergedError("No root was found near this starting value",
                                    hint="Try another starting value, or use two values that bracket a sign change: nsolve(f, x, a, b).") from exc
    else:
        lo, hi = _bound(a), _bound(b)
        flo, fhi = _real_val(fn(lo), "nsolve"), _real_val(fn(hi), "nsolve")
        if flo * fhi > 0:
            raise NotConvergedError(f"f has the same sign at both ends of [{mp.nstr(lo, 6)}, {mp.nstr(hi, 6)}], so a root is not guaranteed",
                                    hint="Choose an interval where f changes sign (the graph shows where).")
        root = mp.findroot(lambda t: _real_val(fn(t), "nsolve"), (lo, hi), solver="anderson", tol=mp.mpf(10) ** -30, maxsteps=300)
    resid = abs(fn(root))
    if resid > mp.mpf(10) ** -15 * max(1, abs(root)):
        raise NotConvergedError("The iteration did not reach a root", details={"residual": mp.nstr(resid, 3)})
    if isinstance(root, mp.mpc):
        ev.numeric_method = "findroot (mpmath)"
        return sp.Float(mp.nstr(root.real, 35), 35) + sp.I * sp.Float(mp.nstr(root.imag, 35), 35)
    return _flt(ev, root, "findroot (mpmath)", residual=mp.nstr(resid, 3))
