"""Fast floating-point evaluation of an expression over arrays, for plotting.

This is a *second* evaluator, deliberately separate from the exact one (it works in float64 with NumPy). The two follow the same rules
(angle mode, real roots such as cbrt(-8) = -2, degrees via °, the same function names); ``tests/test_graph_consistency.py`` checks that they
agree at random points. Where float64 has no answer (square root of a negative number, log of zero) the result is NaN and the plot
leaves a gap; nothing is ever drawn from a guess.
"""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Any, Callable

import numpy as np

from ...errors import ArityError, EvaluationError, MissingVariableError, UnknownNameError, UnsupportedOperation
from ..expressions import ast as A
from ..expressions.functions import canonical
from ..expressions.printer import to_text

Fn = Callable[..., np.ndarray]
_gamma = np.frompyfunc(lambda v: _safe(math.gamma, v), 1, 1)
_erf = np.frompyfunc(lambda v: _safe(math.erf, v), 1, 1)
_lgamma = np.frompyfunc(lambda v: _safe(math.lgamma, v), 1, 1)

CONSTS = {"pi": math.pi, "π": math.pi, "tau": 2 * math.pi, "τ": 2 * math.pi, "e": math.e, "inf": math.inf, "oo": math.inf, "∞": math.inf}
MAX_DEPTH = 24


def _safe(f, v):
    try:
        return f(v)
    except (ValueError, OverflowError):
        return float("nan")


def _vec(ufunc, x):
    return np.asarray(ufunc(np.asarray(x, dtype=float)), dtype=float)


def rational_const(node: A.Node) -> Fraction | None:
    """The exact rational value of a constant node such as 1/3 or -2, or None."""
    if isinstance(node, A.Num):
        try:
            return Fraction(node.text)
        except ValueError:
            return None
    if isinstance(node, A.Unary):
        v = rational_const(node.arg)
        return None if v is None else (-v if node.op == "-" else v)
    if isinstance(node, A.Binary) and node.op in ("/", "*", "+", "-"):
        a, b = rational_const(node.left), rational_const(node.right)
        if a is None or b is None:
            return None
        if node.op == "/":
            return None if b == 0 else a / b
        return {"*": a * b, "+": a + b, "-": a - b}[node.op]
    return None


def real_pow(x: np.ndarray, p: int, q: int) -> np.ndarray:
    """x^(p/q) over the reals: an odd root of a negative number is real (cbrt(-8) = -2)."""
    if q % 2 == 1:
        root = np.sign(x) * np.abs(x) ** (1.0 / q)
        return root ** p
    return np.power(x, p / q)


class Compiled:
    def __init__(self, fn: Fn, is_angle: bool = False) -> None:
        self.fn, self.is_angle = fn, is_angle

    def __call__(self, *a: np.ndarray) -> np.ndarray:
        return self.fn(*a)


class Compiler:
    def __init__(self, vars_: tuple[str, ...], env: dict[str, float], angle: str, functions: dict[str, A.FuncDef]) -> None:
        self.vars, self.env, self.angle, self.functions = vars_, env, angle, functions
        self.k = {"rad": 1.0, "deg": math.pi / 180, "grad": math.pi / 200}[angle]

    # ----------------------------------------------------------------------------------------------------------- public
    def compile(self, node: A.Node, bind: dict[str, Fn] | None = None, depth: int = 0) -> Compiled:
        if depth > MAX_DEPTH:
            raise EvaluationError("The function definition is nested too deeply to plot")
        m = getattr(self, "c_" + node.kind, None)
        if m is None:
            raise UnsupportedOperation(f"'{to_text(node)}' cannot be plotted (this kind of expression is not a number-valued formula)")
        return m(node, bind or {}, depth)

    def fn(self, node: A.Node, bind: dict, depth: int) -> Fn:
        return self.compile(node, bind, depth).fn

    # ----------------------------------------------------------------------------------------------------------- leaves
    def c_num(self, n, bind, depth):
        v = float(Fraction(n.text))
        return Compiled(lambda *a: np.float64(v))

    def c_var(self, n, bind, depth):
        name = n.name
        if name in bind:
            return Compiled(bind[name])
        if name in self.vars:
            i = self.vars.index(name)
            return Compiled(lambda *a, i=i: a[i])
        if name in self.env:
            v = float(self.env[name])
            return Compiled(lambda *a, v=v: np.float64(v))
        if name in CONSTS:
            v = CONSTS[name]
            return Compiled(lambda *a, v=v: np.float64(v))
        if name == "i":
            raise UnsupportedOperation("Complex numbers cannot be plotted")
        if canonical(name):
            raise EvaluationError(f"'{name}' is a function; write {name}(…) with its argument")
        raise MissingVariableError(f"'{name}' has no value", span=n.span,
                                   hint=f"Give it a value (for example {name} := 2) or add a slider for it.")

    # ----------------------------------------------------------------------------------------------------------- operators
    def c_unary(self, n, bind, depth):
        c = self.compile(n.arg, bind, depth + 1)
        if n.op == "-":
            return Compiled(lambda *a, f=c.fn: -f(*a), c.is_angle)
        return c

    def c_postfix(self, n, bind, depth):
        c = self.fn(n.arg, bind, depth + 1)
        if n.op == "%":
            return Compiled(lambda *a: c(*a) / 100.0)
        if n.op == "°":
            return Compiled(lambda *a: c(*a) * (math.pi / 180), True)
        return Compiled(lambda *a: _vec(_gamma, c(*a) + 1.0))

    def c_bin(self, n, bind, depth):
        l, r = self.compile(n.left, bind, depth + 1), self.compile(n.right, bind, depth + 1)
        lf, rf, op = l.fn, r.fn, n.op
        if op == "+":
            return Compiled(lambda *a: lf(*a) + rf(*a), l.is_angle and r.is_angle)
        if op == "-":
            return Compiled(lambda *a: lf(*a) - rf(*a), l.is_angle and r.is_angle)
        if op == "*":
            return Compiled(lambda *a: lf(*a) * rf(*a), (l.is_angle != r.is_angle))
        if op == "/":
            return Compiled(lambda *a: lf(*a) / rf(*a), l.is_angle and not r.is_angle)
        if op == "mod":
            return Compiled(lambda *a: np.mod(lf(*a), rf(*a)))
        if op == "^":
            q = rational_const(n.right)
            if q is not None and q.denominator > 1 and q.denominator % 2 == 1:
                p_, q_ = q.numerator, q.denominator
                return Compiled(lambda *a: real_pow(lf(*a), p_, q_))
            return Compiled(lambda *a: np.power(lf(*a), rf(*a)))
        raise UnsupportedOperation(f"Operator {op} cannot be plotted")

    def c_rel(self, n, bind, depth):
        l, r = self.fn(n.left, bind, depth + 1), self.fn(n.right, bind, depth + 1)
        ops = {"=": np.isclose, "!=": lambda x, y: ~np.isclose(x, y), "<": np.less, ">": np.greater, "<=": np.less_equal, ">=": np.greater_equal}
        return Compiled(lambda *a: ops[n.op](l(*a), r(*a)))

    def c_logic(self, n, bind, depth):
        fs = [self.fn(x, bind, depth + 1) for x in n.args]
        if n.op == "not":
            return Compiled(lambda *a: np.logical_not(fs[0](*a)))
        red = np.logical_and if n.op == "and" else np.logical_or
        return Compiled(lambda *a: red.reduce([np.broadcast_to(f(*a), np.broadcast(*[np.asarray(x) for x in a]).shape if a else ()) for f in fs]))

    # ----------------------------------------------------------------------------------------------------------- calls
    def c_call(self, n, bind, depth):
        name = n.name
        if name in self.functions:
            return self.user_call(n, bind, depth)
        canon = canonical(name)
        if canon is None:
            raise UnknownNameError(f"Unknown function '{name}'", span=n.span)
        if canon in ("sum", "prod"):
            return self.series(n, canon, bind, depth)
        if canon in ("if", "piecewise"):
            return self.conditional(n, canon, bind, depth)
        if canon not in FUNCS:
            raise UnsupportedOperation(f"{canon}() cannot be used in a graph", span=n.span,
                                       hint="Graphs need number-valued formulas of the plot variable.")
        lo, hi = ARITY.get(canon, (1, 1))
        if not (lo <= len(n.args) <= hi):
            raise ArityError(f"{canon}() takes {lo if lo == hi else f'{lo} to {hi}'} argument(s) but {len(n.args)} were given", span=n.span)
        cargs = [self.compile(x, bind, depth + 1) for x in n.args]
        impl = FUNCS[canon]
        k = self.k
        if canon in TRIG:
            c0 = cargs[0]
            conv = 1.0 if c0.is_angle else k
            f0 = c0.fn
            base = Compiled(lambda *a: impl(f0(*a) * conv))
        elif canon in INVTRIG:
            f0 = cargs[0].fn
            base = Compiled(lambda *a: impl(f0(*a)) / k)
        elif canon == "atan2":
            f0, f1 = cargs[0].fn, cargs[1].fn
            base = Compiled(lambda *a: np.arctan2(f0(*a), f1(*a)) / k)
        else:
            fs = [c.fn for c in cargs]
            base = Compiled(lambda *a: impl(*[f(*a) for f in fs]))
        if n.power is not None:
            pf = self.fn(n.power, bind, depth + 1)
            bf = base.fn
            return Compiled(lambda *a: np.power(bf(*a), pf(*a)))
        return base

    def user_call(self, n, bind, depth):
        f = self.functions[n.name]
        if len(n.args) != len(f.params):
            raise ArityError(f"{n.name}() takes {len(f.params)} argument(s) but {len(n.args)} were given", span=n.span)
        local = {p: self.fn(a, bind, depth + 1) for p, a in zip(f.params, n.args)}
        return self.compile(f.body, local, depth + 1)

    def series(self, n, canon, bind, depth):
        if len(n.args) != 4 or not isinstance(n.args[1], A.Var):
            raise UnsupportedOperation(f"Only the form {canon}(term, k, first, last) can be plotted")
        kname = n.args[1].name
        lo, hi = rational_const(n.args[2]), rational_const(n.args[3])
        if lo is None or hi is None or lo.denominator != 1 or hi.denominator != 1:
            raise UnsupportedOperation(f"The limits of {canon}() must be whole numbers to plot it")
        a_, b_ = int(lo), int(hi)
        if b_ - a_ + 1 > 2000:
            raise UnsupportedOperation("A plotted series is limited to 2000 terms")
        def term(kv):
            return self.fn(n.args[0], {**bind, kname: (lambda *a, kv=kv: np.float64(kv))}, depth + 1)
        terms = [term(kv) for kv in range(a_, b_ + 1)]
        if canon == "sum":
            return Compiled(lambda *a: sum((t(*a) for t in terms), np.float64(0)))
        def prod(*a):
            out = np.float64(1)
            for t in terms:
                out = out * t(*a)
            return out
        return Compiled(prod)

    def conditional(self, n, canon, bind, depth):
        args = n.args
        if canon == "if":
            if len(args) != 3:
                raise ArityError("if() takes 3 arguments", span=n.span)
            c, t, e = (self.fn(x, bind, depth + 1) for x in args)
            return Compiled(lambda *a: np.where(c(*a), t(*a), e(*a)))
        pairs = [(self.fn(args[i], bind, depth + 1), self.fn(args[i + 1], bind, depth + 1)) for i in range(0, len(args) - 1, 2)]
        default = self.fn(args[-1], bind, depth + 1) if len(args) % 2 == 1 else None

        def pw(*a):
            out = default(*a) if default else np.float64(np.nan)
            for cond, val in reversed(pairs):
                out = np.where(cond(*a), val(*a), out)
            return out
        return Compiled(pw)

    def c_funcdef(self, n, bind, depth):
        raise UnsupportedOperation("A function definition cannot be plotted")


def _round_half_away(x):
    return np.sign(x) * np.floor(np.abs(x) + 0.5)


def _log(x, b=None):
    return np.log10(x) if b is None else np.log(x) / np.log(b)


def _root(x, n):
    n = np.asarray(n, dtype=float)
    if n.ndim == 0 and float(n) == int(n) and int(n) % 2 == 1:
        return np.sign(x) * np.abs(x) ** (1.0 / float(n))
    return np.power(x, 1.0 / n)


def _minmax(red):
    return lambda *xs: red.reduce(np.broadcast_arrays(*xs))


FUNCS: dict[str, Callable[..., Any]] = {
    "abs": np.abs, "sign": np.sign, "sqrt": np.sqrt, "cbrt": np.cbrt, "root": _root, "exp": np.exp, "ln": np.log, "log": _log,
    "log10": np.log10, "log2": np.log2, "floor": np.floor, "ceil": np.ceil, "round": _round_half_away, "trunc": np.trunc,
    "frac": lambda x: x - np.trunc(x), "min": _minmax(np.minimum), "max": _minmax(np.maximum), "mod": np.mod,
    "factorial": lambda x: _vec(_gamma, x + 1.0), "gamma": lambda x: _vec(_gamma, x), "lgamma": lambda x: _vec(_lgamma, x),
    "sin": np.sin, "cos": np.cos, "tan": np.tan, "sec": lambda x: 1 / np.cos(x), "csc": lambda x: 1 / np.sin(x), "cot": lambda x: 1 / np.tan(x),
    "asin": np.arcsin, "acos": np.arccos, "atan": np.arctan, "asec": lambda x: np.arccos(1 / x), "acsc": lambda x: np.arcsin(1 / x),
    "acot": lambda x: np.arctan(1 / x), "atan2": None,
    "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh, "sech": lambda x: 1 / np.cosh(x), "csch": lambda x: 1 / np.sinh(x),
    "coth": lambda x: 1 / np.tanh(x), "asinh": np.arcsinh, "acosh": np.arccosh, "atanh": np.arctanh,
    "todeg": np.degrees, "torad": np.radians,
    "normalpdf": lambda x, m=0.0, s=1.0: np.exp(-((x - m) / s) ** 2 / 2) / (s * math.sqrt(2 * math.pi)),
    "normalcdf": lambda x, m=0.0, s=1.0: 0.5 * (1 + _vec(_erf, (x - m) / (s * math.sqrt(2)))),
    "re": np.real, "im": np.imag, "conj": np.conj,
}
TRIG = {"sin", "cos", "tan", "sec", "csc", "cot"}
INVTRIG = {"asin", "acos", "atan", "asec", "acsc", "acot"}
ARITY = {"log": (1, 2), "round": (1, 1), "min": (1, 50), "max": (1, 50), "root": (2, 2), "mod": (2, 2), "atan2": (2, 2),
         "normalpdf": (1, 3), "normalcdf": (1, 3)}
FUNCS = {k: v for k, v in FUNCS.items() if v is not None or k == "atan2"}
FUNCS["atan2"] = np.arctan2
for _k in ("re", "im", "conj"):
    FUNCS.pop(_k)


def compile_expr(node: A.Node, vars_: tuple[str, ...], env: dict[str, float] | None = None, angle: str = "rad",
                 functions: dict[str, A.FuncDef] | None = None) -> Compiled:
    return Compiler(vars_, env or {}, angle, functions or {}).compile(node)
