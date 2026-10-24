"""SymPy -> SciCal AST. Results are drawn from the same tree type as input, so the page renders and prints them identically."""
from __future__ import annotations

from decimal import Decimal

import sympy as sp

from ...errors import UndefinedError
from ..expressions import ast as A


def num_text(x: sp.Number) -> str:
    """Plain decimal text of a SymPy number (no scientific notation unless the exponent is large)."""
    if isinstance(x, sp.Integer):
        return str(abs(int(x)))
    if isinstance(x, sp.Float):
        d = Decimal(sp.sstr(abs(x), full_prec=True))
        if -6 <= d.adjusted() <= 20:
            return format(d.normalize(), "f") if d != 0 else "0"
        return format(d.normalize(), "e").replace("E", "e").replace("e+", "e")
    return str(abs(x))


def _neg(node: A.Node) -> A.Node:
    return A.Unary(op="-", arg=node)


def _is_neg(e: sp.Basic) -> bool:
    if e.is_Number:
        return bool(e < 0)
    if e.is_Mul:
        c, _ = e.as_coeff_Mul()
        return bool(c < 0)
    return False


def _flip(e: sp.Expr) -> sp.Expr:
    return -e


_FUNC_NAMES = {
    sp.sin: "sin", sp.cos: "cos", sp.tan: "tan", sp.sec: "sec", sp.csc: "csc", sp.cot: "cot",
    sp.asin: "asin", sp.acos: "acos", sp.atan: "atan", sp.asec: "asec", sp.acsc: "acsc", sp.acot: "acot",
    sp.sinh: "sinh", sp.cosh: "cosh", sp.tanh: "tanh", sp.sech: "sech", sp.csch: "csch", sp.coth: "coth",
    sp.asinh: "asinh", sp.acosh: "acosh", sp.atanh: "atanh",
    sp.Abs: "abs", sp.sign: "sign", sp.floor: "floor", sp.ceiling: "ceil", sp.re: "re", sp.im: "im", sp.conjugate: "conj", sp.arg: "arg",
    sp.exp: "exp", sp.gamma: "gamma", sp.erf: "erf", sp.atan2: "atan2", sp.Min: "min", sp.Max: "max", sp.loggamma: "lgamma",
}


def to_ast(e) -> A.Node:
    if isinstance(e, bool) or e is sp.true or e is sp.false:
        return A.Var(name="true" if bool(e) else "false")
    if isinstance(e, int):
        e = sp.Integer(e)
    if isinstance(e, sp.MatrixBase):
        if e.cols == 1 and False:
            return A.Vector(items=[to_ast(x) for x in e])
        return A.Matrix(rows=[[to_ast(e[i, j]) for j in range(e.cols)] for i in range(e.rows)])
    if e.is_Integer:
        return _neg(A.Num(text=num_text(e))) if e < 0 else A.Num(text=num_text(e))
    if e.is_Rational:
        top: A.Node = A.Num(text=str(abs(e.p)))
        return A.Binary(op="/", left=_neg(top) if e < 0 else top, right=A.Num(text=str(e.q)))
    if e.is_Float:
        node = A.Num(text=num_text(e))
        return _neg(node) if e < 0 else node
    if e is sp.pi:
        return A.Var(name="pi")
    if e is sp.E:
        return A.Var(name="e")
    if e is sp.I:
        return A.Var(name="i")
    if e is sp.oo:
        return A.Var(name="inf")
    if e is sp.S.NegativeInfinity:
        return _neg(A.Var(name="inf"))
    if e in (sp.zoo, sp.nan):
        raise UndefinedError("The result is undefined")
    if isinstance(e, sp.Symbol):
        return A.Var(name=e.name)
    if isinstance(e, sp.Add):
        return _add(e)
    if isinstance(e, sp.Mul):
        return _mul(e)
    if isinstance(e, sp.Pow):
        return _pow(e)
    if isinstance(e, sp.factorial):
        return A.Postfix(op="!", arg=to_ast(e.args[0]))
    if isinstance(e, sp.log):
        if len(e.args) == 2:
            return A.Call(name="log", args=[to_ast(e.args[0]), to_ast(e.args[1])])
        return A.Call(name="ln", args=[to_ast(e.args[0])])
    if isinstance(e, sp.Rel):
        op = {"==": "=", "!=": "!=", "<": "<", ">": ">", "<=": "<=", ">=": ">="}[e.rel_op]
        return A.Rel(op=op, left=to_ast(e.lhs), right=to_ast(e.rhs))
    if isinstance(e, sp.And):
        return A.Logic(op="and", args=[to_ast(a) for a in e.args])
    if isinstance(e, sp.Or):
        return A.Logic(op="or", args=[to_ast(a) for a in e.args])
    if isinstance(e, sp.Not):
        return A.Logic(op="not", args=[to_ast(e.args[0])])
    if isinstance(e, sp.Piecewise):
        args: list[A.Node] = []
        for val, cond in e.args:
            if cond is sp.true:
                args.append(to_ast(val))
            else:
                args.extend([to_ast(cond), to_ast(val)])
        return A.Call(name="piecewise", args=args)
    if isinstance(e, sp.Derivative):
        expr, *vars_ = e.args
        v, order = vars_[0]
        call = A.Call(name="diff", args=[to_ast(expr), to_ast(v)] + ([to_ast(sp.Integer(order))] if order != 1 else []))
        return call
    if isinstance(e, sp.Integral):
        expr = e.args[0]
        lims = e.args[1]
        if len(lims) == 3:
            return A.Call(name="integral", args=[to_ast(expr), to_ast(lims[0]), to_ast(lims[1]), to_ast(lims[2])])
        return A.Call(name="integral", args=[to_ast(expr), to_ast(lims[0])])
    if isinstance(e, sp.Sum):
        expr, (k, a, b) = e.args
        return A.Call(name="sum", args=[to_ast(expr), to_ast(k), to_ast(a), to_ast(b)])
    if isinstance(e, sp.Product):
        expr, (k, a, b) = e.args
        return A.Call(name="prod", args=[to_ast(expr), to_ast(k), to_ast(a), to_ast(b)])
    if isinstance(e, sp.binomial):
        return A.Call(name="nCr", args=[to_ast(e.args[0]), to_ast(e.args[1])])
    if isinstance(e, sp.Mod):
        return A.Binary(op="mod", left=to_ast(e.args[0]), right=to_ast(e.args[1]))
    if isinstance(e, sp.CRootOf):
        return A.Call(name="rootof", args=[to_ast(e.poly.as_expr()), to_ast(sp.Integer(e.index))])
    if isinstance(e, sp.Function) or hasattr(e, "func"):
        name = _FUNC_NAMES.get(e.func)
        if name is None:
            name = getattr(e.func, "__name__", str(e.func)).lower()
        return A.Call(name=name, args=[to_ast(a) for a in e.args])
    return A.Var(name=str(e))


def _add(e: sp.Add) -> A.Node:
    terms = e.as_ordered_terms()
    node: A.Node | None = None
    for t in terms:
        if node is None:
            node = to_ast(t)
        elif _is_neg(t):
            node = A.Binary(op="-", left=node, right=to_ast(_flip(t)))
        else:
            node = A.Binary(op="+", left=node, right=to_ast(t))
    assert node is not None
    return node


def _factor_ast(f: sp.Expr) -> A.Node:
    return to_ast(f)


def _mul(e: sp.Mul) -> A.Node:
    negative = _is_neg(e)
    num, den = _split_fraction(-e if negative else e)
    top = _product(num, negative)
    if den:
        return A.Binary(op="/", left=top, right=_product(den, False))
    return top


def _split_fraction(e: sp.Mul) -> tuple[list[sp.Expr], list[sp.Expr]]:
    num: list[sp.Expr] = []
    den: list[sp.Expr] = []
    coeff, rest = e.as_coeff_Mul()
    if coeff != 1:
        if coeff.p != 1:
            num.append(sp.Integer(coeff.p))
        if coeff.q != 1:
            den.append(sp.Integer(coeff.q))
    factors = rest.as_ordered_factors() if not rest.is_Number else [] if rest == 1 else [rest]
    for f in factors:
        if f.is_Pow and f.exp.is_Rational and f.exp < 0 and not (f.exp == -sp.Rational(1, 2) and False):
            den.append(f.base ** (-f.exp))
        elif f.is_Pow and f.exp.is_negative:
            den.append(f.base ** (-f.exp))
        else:
            num.append(f)
    if not num:
        num = [sp.Integer(1)]
    return num, den


def _product(factors: list[sp.Expr], negate: bool) -> A.Node:
    node = to_ast(factors[0])
    if negate:
        node = _neg(node)
    for f in factors[1:]:
        n = to_ast(f)
        node = A.Binary(op="*", left=node, right=n, implicit=not f.is_Number)
    return node


def _pow(e: sp.Pow) -> A.Node:
    b, x = e.args
    if b is sp.E:
        return A.Call(name="exp", args=[to_ast(x)])
    if x == sp.Rational(1, 2):
        return A.Call(name="sqrt", args=[to_ast(b)])
    if x == -sp.Rational(1, 2):
        return A.Binary(op="/", left=A.Num(text="1"), right=A.Call(name="sqrt", args=[to_ast(b)]))
    if x.is_Rational and x.p == 1 and x.q > 2:
        return A.Call(name="root", args=[to_ast(b), A.Num(text=str(x.q))])
    if x.is_Rational and x.p == -1 and x.q > 2:
        return A.Binary(op="/", left=A.Num(text="1"), right=A.Call(name="root", args=[to_ast(b), A.Num(text=str(x.q))]))
    if x.is_negative and not (x.is_Rational and x.q != 1):
        pos = b ** (-x)
        return A.Binary(op="/", left=A.Num(text="1"), right=to_ast(pos))
    return A.Binary(op="^", left=to_ast(b), right=to_ast(x))
