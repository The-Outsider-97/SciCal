"""Arithmetic, number theory, trigonometry, complex numbers, number bases, constants and control functions."""
from __future__ import annotations

from typing import Any

import sympy as sp

from ...errors import (BadRequest, ComplexResultError, DimensionError, DomainError, EvaluationError, LimitExceeded, UndefinedError,
                       UnitError)
from ..expressions import ast as A
from ..units import Quantity
from ..units import quantity as Q
from ..units.constants import get as get_constant
from . import ops
from .registry import handler
from .values import Equation, Text, Vec

R = sp.Rational


# ------------------------------------------------------------------------------------------------------------------ helpers
def num(v: Any, name: str) -> sp.Expr:
    return ops.plain(v, f"{name}()")


def symbolic(x: Any) -> bool:
    return bool(getattr(x, "free_symbols", None))


def real_number(x: Any) -> bool:
    return isinstance(x, sp.Basic) and x.is_number and x.is_real is True


def flatten(args: list, name: str) -> list:
    out: list = []
    for a in args:
        if isinstance(a, Vec):
            out.extend(a.items)
        elif ops.is_matrix(a):
            out.extend(list(a))
        else:
            out.append(a)
    if not out:
        raise EvaluationError(f"{name}() needs at least one value")
    return out


def int_arg(v: Any, name: str, lo: int | None = None, hi: int | None = None) -> int:
    return ops.as_int(v, f"The argument of {name}()", lo, hi)


# ------------------------------------------------------------------------------------------------------------------ arithmetic
@handler("abs")
def f_abs(ev, x):
    if isinstance(x, Quantity):
        return Quantity(sp.Abs(x.mag), x.unit)
    return sp.Abs(num(x, "abs"))


@handler("sign")
def f_sign(ev, x):
    return sp.sign(num(x, "sign"))


@handler("sqrt")
def f_sqrt(ev, x):
    if isinstance(x, Quantity):
        return Q.power(x, R(1, 2))
    x = num(x, "sqrt")
    return ops.power_scalar(x, R(1, 2), ev.complex_mode) if not (x.is_number and x.is_real and x < 0 and not ev.complex_mode) else _raise_neg_sqrt(x)


def _raise_neg_sqrt(x):
    raise DomainError(f"The square root of {x} is not a real number", hint="Switch to complex mode to get the complex result.")


@handler("cbrt")
def f_cbrt(ev, x):
    if isinstance(x, Quantity):
        return Q.power(x, R(1, 3))
    return ops.power_scalar(num(x, "cbrt"), R(1, 3), ev.complex_mode)


@handler("root")
def f_root(ev, x, n):
    n = num(n, "root")
    if not (n.is_integer and n.is_number and n > 0):
        raise DomainError("The root index must be a positive whole number")
    if isinstance(x, Quantity):
        return Q.power(x, R(1, int(n)))
    return ops.power_scalar(num(x, "root"), R(1, int(n)), ev.complex_mode)


@handler("exp")
def f_exp(ev, x):
    return sp.exp(num(x, "exp"))


def _check_log_arg(ev, x, name):
    if x == 0:
        raise UndefinedError(f"{name}(0) is undefined")
    if not ev.complex_mode and real_number(x) and x < 0:
        raise DomainError(f"{name} of a negative number is not real: {name}({x})", hint="Switch to complex mode for complex logarithms.")


@handler("ln")
def f_ln(ev, x):
    x = num(x, "ln")
    _check_log_arg(ev, x, "ln")
    return sp.log(x)


def _log_base(ev, x, b, name):
    x = num(x, name)
    _check_log_arg(ev, x, name)
    if b == 1 or b == 0 or (real_number(b) and b < 0 and not ev.complex_mode):
        raise DomainError(f"The base of a logarithm must be positive and not 1 (got {b})")
    return sp.log(x, b)


@handler("log")
def f_log(ev, x, b=None):
    return _log_base(ev, x, sp.Integer(10) if b is None else num(b, "log"), "log")


@handler("log10")
def f_log10(ev, x):
    return _log_base(ev, x, sp.Integer(10), "log10")


@handler("log2")
def f_log2(ev, x):
    return _log_base(ev, x, sp.Integer(2), "log2")


@handler("floor")
def f_floor(ev, x):
    return sp.floor(num(x, "floor"))


@handler("ceil")
def f_ceil(ev, x):
    return sp.ceiling(num(x, "ceil"))


def round_half_away(x: sp.Expr, d: int = 0) -> sp.Expr:
    scale = sp.Integer(10) ** d
    y = x * scale
    r = sp.floor(y + R(1, 2)) if y >= 0 else -sp.floor(-y + R(1, 2))
    return sp.Rational(r) / scale


@handler("round")
def f_round(ev, x, d=None):
    x = num(x, "round")
    if symbolic(x) or not real_number(x):
        raise EvaluationError("round() needs a real number")
    return round_half_away(x, 0 if d is None else int_arg(d, "round", -50, 50))


@handler("trunc")
def f_trunc(ev, x):
    x = num(x, "trunc")
    return sp.floor(x) if x >= 0 else sp.ceiling(x)


@handler("frac")
def f_frac(ev, x):
    x = num(x, "frac")
    return x - (sp.floor(x) if x >= 0 else sp.ceiling(x))


def decimal_exponent(x: sp.Expr) -> int:
    """floor(log10|x|) computed without rounding trouble."""
    from decimal import Decimal
    s = str(sp.N(abs(x), 60))
    return Decimal(s).adjusted()


@handler("sig")
def f_sig(ev, x, n):
    x = num(x, "sig")
    n = int_arg(n, "sig", 1, 100)
    if x == 0:
        return x
    if symbolic(x) or not real_number(x):
        raise EvaluationError("sig() needs a real number")
    return round_half_away(x, n - 1 - decimal_exponent(x))


def _extreme(ev, args, name, want):
    vals = flatten(list(args), name)
    best = vals[0]
    for v in vals[1:]:
        if isinstance(v, Vec) or ops.is_matrix(v):
            raise EvaluationError(f"{name}() compares numbers")
        c = ops.compare_numbers(v, best, ev.settings.digits)
        if (c > 0) == (want == "max") and c != 0:
            best = v
    if not isinstance(best, Quantity):
        num(best, name)
    return best


@handler("min")
def f_min(ev, *args):
    return _extreme(ev, args, "min", "min")


@handler("max")
def f_max(ev, *args):
    return _extreme(ev, args, "max", "max")


@handler("mod")
def f_mod(ev, a, b):
    a, b = num(a, "mod"), num(b, "mod")
    if b == 0:
        raise UndefinedError("mod by zero")
    return sp.Mod(a, b)


def _ints(args, name):
    vals = flatten(list(args), name)
    return [ops.as_int(v, f"Every argument of {name}()") for v in vals]


@handler("gcd")
def f_gcd(ev, *args):
    out = 0
    for v in _ints(args, "gcd"):
        out = sp.igcd(out, v)
    return sp.Integer(out)


@handler("lcm")
def f_lcm(ev, *args):
    out = 1
    for v in _ints(args, "lcm"):
        out = sp.ilcm(out, v)
    return sp.Integer(out)


def factorial(ev, x):
    if symbolic(x):
        return sp.factorial(x)
    if x.is_integer:
        n = int(x)
        if n < 0:
            raise DomainError("The factorial of a negative integer is undefined")
        if n > 20_000:
            raise LimitExceeded("The factorial is too large (limit 20000!)")
        return sp.factorial(n)
    if real_number(x):
        if x < -1:
            raise DomainError("The factorial is only defined for numbers above -1 (it uses the gamma function for non-integers)")
        return sp.gamma(x + 1)
    return sp.gamma(x + 1)


@handler("factorial")
def f_factorial(ev, x):
    return factorial(ev, num(x, "factorial"))


@handler("nPr")
def f_npr(ev, n, r):
    n, r = int_arg(n, "nPr", 0, 20_000), int_arg(r, "nPr", 0)
    if r > n:
        raise DomainError(f"nPr needs r ≤ n (got n = {n}, r = {r})")
    return sp.Integer(sp.factorial(n) // sp.factorial(n - r))


@handler("nCr")
def f_ncr(ev, n, r):
    n, r = int_arg(n, "nCr", 0, 1_000_000), int_arg(r, "nCr", 0)
    if r > n:
        raise DomainError(f"nCr needs r ≤ n (got n = {n}, r = {r})")
    if r > 20_000 and n - r > 20_000:
        raise LimitExceeded("The binomial coefficient is too large to compute here")
    return sp.binomial(n, r)


@handler("isprime")
def f_isprime(ev, n):
    return bool(sp.isprime(ops.as_int(n, "isprime()", 0)))


@handler("factorint")
def f_factorint(ev, n):
    from .values import Table
    k = ops.as_int(n, "factorint()", 1)
    if k.bit_length() > 100:
        raise LimitExceeded("The number is too large to factor reliably here (limit about 30 digits)")
    f = sp.factorint(k)
    return Table(("prime", "exponent"), tuple((sp.Integer(p), sp.Integer(e)) for p, e in sorted(f.items())), title=f"{k} =")


@handler("fib")
def f_fib(ev, n):
    return sp.fibonacci(ops.as_int(n, "fib()", 0, 200_000))


# ------------------------------------------------------------------------------------------------------------------ trigonometry
def _trig(name, fn):
    @handler(name)
    def _h(ev, x, _fn=fn, _name=name):
        a = ev.angle_in(x, f"The argument of {_name}()")
        return _fn(a)
    return _h


for _n, _f in (("sin", sp.sin), ("cos", sp.cos), ("tan", sp.tan), ("sec", sp.sec), ("csc", sp.csc), ("cot", sp.cot)):
    _trig(_n, _f)


def _inv(name, fn, lo=-1, hi=1, closed=True):
    @handler(name)
    def _h(ev, x, _fn=fn, _name=name):
        x = num(x, _name)
        if not ev.complex_mode and real_number(x):
            if _name in ("asin", "acos") and not (-1 <= x <= 1):
                raise DomainError(f"{_name}({x}) is not real: the argument must be between -1 and 1", hint="Switch to complex mode for complex results.")
            if _name in ("asec", "acsc") and -1 < x < 1:
                raise DomainError(f"{_name}({x}) is not real: the argument must satisfy |x| ≥ 1", hint="Switch to complex mode for complex results.")
        return ev.angle_out(_fn(x))
    return _h


for _n, _f in (("asin", sp.asin), ("acos", sp.acos), ("atan", sp.atan), ("asec", sp.asec), ("acsc", sp.acsc), ("acot", sp.acot)):
    _inv(_n, _f)


@handler("atan2")
def f_atan2(ev, y, x):
    y, x = num(y, "atan2"), num(x, "atan2")
    if y == 0 and x == 0:
        raise UndefinedError("atan2(0, 0) is undefined")
    return ev.angle_out(sp.atan2(y, x))


@handler("todeg")
def f_todeg(ev, x):
    return num(x, "todeg") * 180 / sp.pi


@handler("torad")
def f_torad(ev, x):
    return num(x, "torad") * sp.pi / 180


def _hyper(name, fn):
    @handler(name)
    def _h(ev, x, _fn=fn, _name=name):
        x = num(x, _name)
        if not ev.complex_mode and real_number(x):
            if _name == "acosh" and x < 1:
                raise DomainError(f"acosh({x}) is not real: the argument must be at least 1", hint="Switch to complex mode for complex results.")
            if _name == "atanh" and abs(x) >= 1:
                if abs(x) == 1:
                    raise UndefinedError(f"atanh({x}) is infinite")
                raise DomainError(f"atanh({x}) is not real: the argument must be between -1 and 1", hint="Switch to complex mode for complex results.")
        return _fn(x)
    return _h


for _n, _f in (("sinh", sp.sinh), ("cosh", sp.cosh), ("tanh", sp.tanh), ("sech", sp.sech), ("csch", sp.csch), ("coth", sp.coth),
               ("asinh", sp.asinh), ("acosh", sp.acosh), ("atanh", sp.atanh)):
    _hyper(_n, _f)


# ------------------------------------------------------------------------------------------------------------------ complex
@handler("re")
def f_re(ev, z):
    return sp.re(num(z, "re"))


@handler("im")
def f_im(ev, z):
    return sp.im(num(z, "im"))


@handler("conj")
def f_conj(ev, z):
    return sp.conjugate(num(z, "conj"))


@handler("arg")
def f_arg(ev, z):
    z = num(z, "arg")
    if z == 0:
        raise UndefinedError("The argument of 0 is undefined")
    return ev.angle_out(sp.arg(z))


@handler("polar")
def f_polar(ev, z):
    z = num(z, "polar")
    if z == 0:
        return Vec((sp.Integer(0), sp.Integer(0)))
    return Vec((sp.Abs(z), ev.angle_out(sp.arg(z))))


@handler("rect")
def f_rect(ev, r, t):
    th = ev.angle_in(t, "The angle of rect()")
    return num(r, "rect") * (sp.cos(th) + sp.I * sp.sin(th))


# ------------------------------------------------------------------------------------------------------------------ bases, constants
def _to_base(n: int, base: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0:
        return "0"
    out, m = [], abs(n)
    while m:
        m, r = divmod(m, base)
        out.append(digits[r])
    return ("-" if n < 0 else "") + "".join(reversed(out))


@handler("tobase")
def f_tobase(ev, n, b):
    base = ops.as_int(b, "The base", 2, 36)
    return Text(_to_base(ops.as_int(n, "tobase()"), base).upper(), kind=f"base{base}")


@handler("hex")
def f_hex(ev, n):
    k = ops.as_int(n, "hex()")
    return Text(("-" if k < 0 else "") + "0x" + _to_base(abs(k), 16).upper(), kind="hex")


@handler("bin")
def f_bin(ev, n):
    k = ops.as_int(n, "bin()")
    return Text(("-" if k < 0 else "") + "0b" + _to_base(abs(k), 2), kind="bin")


@handler("oct")
def f_oct(ev, n):
    k = ops.as_int(n, "oct()")
    return Text(("-" if k < 0 else "") + "0o" + _to_base(abs(k), 8), kind="oct")


@handler("const")
def f_const(ev, sym):
    c = get_constant(sym.name if isinstance(sym, sp.Symbol) else str(sym))
    return c.quantity()


# ------------------------------------------------------------------------------------------------------------------ control
def _truth(ev, v, what):
    if isinstance(v, bool):
        return v
    if isinstance(v, Equation):
        return None
    raise EvaluationError(f"The condition of {what} must be true or false (for example x > 3)")


@handler("if", raw=True)
def f_if(ev, node, series):
    c = ev.ev(node.args[0])
    t = _truth(ev, c, "if()")
    if t is True:
        return ev.ev(node.args[1])
    if t is False:
        return ev.ev(node.args[2])
    return sp.Piecewise((ops.plain(ev.ev(node.args[1])), c.to_sympy()), (ops.plain(ev.ev(node.args[2])), True))


@handler("piecewise", raw=True)
def f_piecewise(ev, node, series):
    args = node.args
    pairs = [(args[i], args[i + 1]) for i in range(0, len(args) - 1, 2)]
    default = args[-1] if len(args) % 2 == 1 else None
    symbolic_pairs = []
    for cnode, vnode in pairs:
        c = ev.ev(cnode)
        t = _truth(ev, c, "piecewise()")
        if t is True and not symbolic_pairs:
            return ev.ev(vnode)
        if t is True:
            symbolic_pairs.append((ops.plain(ev.ev(vnode)), True))
            return sp.Piecewise(*symbolic_pairs)
        if t is None:
            symbolic_pairs.append((ops.plain(ev.ev(vnode)), c.to_sympy()))
    if symbolic_pairs:
        if default is not None:
            symbolic_pairs.append((ops.plain(ev.ev(default)), True))
        return sp.Piecewise(*symbolic_pairs)
    if default is not None:
        return ev.ev(default)
    raise UndefinedError("None of the conditions of piecewise() is true and no default value was given")
