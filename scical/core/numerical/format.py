"""Turning values into what the page shows: exact forms (as AST + LaTeX), decimal approximations (digits, fixed/scientific/engineering
notation) and the labels that tell the person whether a number is exact or approximate."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

import sympy as sp

from ..expressions.printer import to_latex, to_text
from ..units import Quantity
from . import ops
from .context import Settings
from .convert import to_ast
from .values import Equation, SolutionSet, Table, Text, Vec

MAX_INT_DIGITS = 400            # integers longer than this are shown in scientific form (the full digits stay available)


def group_digits(s: str, sep: str = " ") -> str:
    neg = s.startswith("-")
    body = s[1:] if neg else s
    whole, dot, frac = body.partition(".")
    out = []
    while len(whole) > 3:
        out.insert(0, whole[-3:])
        whole = whole[:-3]
    out.insert(0, whole)
    return ("-" if neg else "") + sep.join(out) + (dot + frac if dot else "")


# ---------------------------------------------------------------------------------------------------------------------------
def _decimal_of(x: sp.Expr, digits: int) -> Decimal:
    n = sp.N(x, digits + 15)
    if n.is_Float:
        return Decimal(sp.sstr(n, full_prec=True)) if n != 0 else Decimal(0)
    return Decimal(str(n))


def _round_sig(d: Decimal, digits: int) -> Decimal:
    if d == 0:
        return d
    with localcontext() as c:
        c.prec = digits + 20
        exp = d.adjusted()
        q = Decimal(1).scaleb(exp - digits + 1)
        return d.quantize(q, rounding=ROUND_HALF_UP)


def _plain(d: Decimal, keep_zeros: bool = False) -> str:
    s = format(d, "f")
    if "." in s and not keep_zeros:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def real_text(x: sp.Expr, s: Settings, *, as_exact_integer: bool = True) -> tuple[str, str]:
    """(plain text, LaTeX) of a real number under the display settings."""
    if x in (sp.oo, -sp.oo):
        return ("∞" if x == sp.oo else "-∞"), (r"\infty" if x == sp.oo else r"-\infty")
    notation = s.notation
    if isinstance(x, sp.Integer) and notation in ("auto",) and as_exact_integer:
        text = str(int(x))
        if len(text.lstrip("-")) <= MAX_INT_DIGITS:
            if s.thousands:
                text = group_digits(text)
            return text, text.replace(" ", r"\,")
    d = _decimal_of(x, s.digits)
    if d == 0:
        return "0", "0"
    if notation == "fixed":
        places = s.decimals if s.decimals is not None else 4
        with localcontext() as c:
            c.prec = 400
            q = d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        t = format(q, "f")
        t = "0" + t[1:] if t.startswith("-0") and q == 0 else t
        if s.thousands:
            t = group_digits(t)
        return t, t.replace(" ", r"\,")
    r = _round_sig(d, s.digits)
    exp = r.adjusted()
    use_sci = notation in ("sci", "eng") or exp >= max(s.digits, 12) or exp < -5
    if not use_sci:
        t = _plain(r)
        if s.thousands:
            t = group_digits(t)
        return t, t.replace(" ", r"\,")
    if notation == "eng":
        e3 = (exp // 3) * 3
        mant = r.scaleb(-e3)
        m = _plain(mant)
        return f"{m}e{e3}", rf"{m}\times 10^{{{e3}}}"
    mant = r.scaleb(-exp)
    m = _plain(mant)
    return f"{m}e{exp}", rf"{m}\times 10^{{{exp}}}"


def number_text(x: sp.Expr, s: Settings) -> tuple[str, str]:
    """Plain text and LaTeX of a real or complex number."""
    re, im = sp.re(x), sp.im(x)
    if im == 0:
        return real_text(re, s)
    imt, iml = real_text(abs(im), s)
    sign = "-" if im < 0 else "+"
    imt_full = "i" if imt == "1" else imt + "i"
    iml_full = r"\mathrm{i}" if iml == "1" else iml + r"\,\mathrm{i}"
    if re == 0:
        return (("-" if im < 0 else "") + imt_full), (("-" if im < 0 else "") + iml_full)
    ret, rel = real_text(re, s)
    return f"{ret} {sign} {imt_full}", f"{rel} {sign} {iml_full}"


# ---------------------------------------------------------------------------------------------------------------------------
class Formatter:
    def __init__(self, settings: Settings, decimal_input: bool = False, numeric_method: str | None = None) -> None:
        self.s = settings
        self.decimal_input = decimal_input
        self.numeric_method = numeric_method

    # ----- scalars
    def exact_form(self, x: sp.Expr) -> dict | None:
        try:
            node = to_ast(x)
        except Exception:
            return None
        return {"ast": node.to_json(), "text": to_text(node), "latex": to_latex(node)}

    def scalar(self, x: Any) -> dict:
        if isinstance(x, (int,)):
            x = sp.Integer(x)
        symbolic = bool(x.free_symbols)
        floaty = bool(x.atoms(sp.Float))
        out: dict[str, Any] = {"t": "number", "symbolic": symbolic, "approximate": floaty, "exact": None, "approx": None}
        if symbolic:
            out["exact"] = self.exact_form(x)
            out["primary"] = "exact"
            out["text"] = out["exact"]["text"] if out["exact"] else str(x)
            out["latex"] = out["exact"]["latex"] if out["exact"] else sp.latex(x)
            return out
        if x in (sp.oo, -sp.oo):
            t, l = real_text(x, self.s)
            out.update(exact={"ast": to_ast(x).to_json(), "text": t, "latex": l}, primary="exact", text=t, latex=l)
            return out
        is_int = isinstance(x, sp.Integer)
        t, l = number_text(x, self.s)
        approx = {"text": t, "latex": l}
        if floaty:
            out.update(approx=approx, primary="approx", text=t, latex=l)
            return out
        exact = self.exact_form(x)
        out["exact"] = exact
        # does the exact form say more than the decimal? (integers and plain decimals do not)
        out["approx"] = None if is_int else approx
        mode = self.s.result
        prefer_approx = mode == "approx" or (mode == "auto" and self.decimal_input and not x.is_irrational and (x.is_Rational or x.is_number))
        if mode == "auto" and x.is_Rational and not is_int and len(str(abs(x.p))) + len(str(x.q)) > 16:
            prefer_approx = True                       # an unwieldy fraction reads better as a decimal; the fraction stays available
        if is_int:
            out["primary"] = "exact"
            out["exact"] = exact
            out["approx"] = None
            out["text"], out["latex"] = (exact["text"], exact["latex"]) if exact and len(exact["text"]) <= MAX_INT_DIGITS and self.s.notation == "auto" and not self.s.thousands else (t, l)
        elif prefer_approx:
            out["primary"] = "approx"
            out["text"], out["latex"] = t, l
        else:
            out["primary"] = "exact"
            if exact:
                out["text"], out["latex"] = exact["text"], exact["latex"]
            else:
                out["text"], out["latex"] = t, l
        # a terminating decimal that equals its fraction needs no second line
        if out["exact"] and out["approx"] and out["exact"]["text"] == out["approx"]["text"]:
            out["approx"] = None
        return out

    # ----- general
    def value(self, v: Any) -> dict:
        if isinstance(v, bool):
            return {"t": "bool", "value": v, "text": "true" if v else "false", "latex": r"\text{true}" if v else r"\text{false}"}
        if isinstance(v, Quantity):
            return self.quantity(v)
        if isinstance(v, Vec):
            items = [self.value(x) for x in v.items]
            return {"t": "vector", "items": items, "text": "[" + ", ".join(i["text"] for i in items) + "]",
                    "latex": r"\begin{bmatrix}" + r" \\ ".join(i["latex"] for i in items) + r"\end{bmatrix}"}
        if ops.is_matrix(v):
            rows = [[self.value(v[i, j]) for j in range(v.cols)] for i in range(v.rows)]
            return {"t": "matrix", "rows": rows, "text": "[" + "; ".join(", ".join(c["text"] for c in r) for r in rows) + "]",
                    "latex": r"\begin{bmatrix}" + r" \\ ".join(" & ".join(c["latex"] for c in r) for r in rows) + r"\end{bmatrix}"}
        if isinstance(v, Equation):
            node = to_ast(v.to_sympy()) if False else None
            lhs, rhs = self.scalar(v.lhs), self.scalar(v.rhs)
            return {"t": "equation", "text": f"{lhs['text']} {v.op} {rhs['text']}", "latex": f"{lhs['latex']} {_rel_latex(v.op)} {rhs['latex']}"}
        if isinstance(v, SolutionSet):
            return self.solutions(v)
        if isinstance(v, Table):
            return self.table(v)
        if isinstance(v, Text):
            return {"t": "text", "kind": v.kind, "text": v.text, "latex": r"\mathrm{" + v.text.replace("_", r"\_") + "}"}
        if isinstance(v, sp.Set):
            return self.set_value(v, None)
        if isinstance(v, (sp.Expr,)) or isinstance(v, int):
            return self.scalar(v)
        raise TypeError(f"cannot format {type(v).__name__}")

    def quantity(self, q: Quantity) -> dict:
        mag = self.scalar(q.mag)
        unit = {"text": q.unit.text, "pretty": q.unit.pretty, "dimension": q.unit.dim.name}
        text = f"{mag['text']} {q.unit.pretty}".strip()
        latex = f"{mag['latex']}\\,{_unit_latex(q)}"
        out = {"t": "quantity", "mag": mag, "unit": unit, "text": text, "latex": latex}
        if mag.get("approx") and mag["primary"] == "exact":
            out["approxText"] = f"{mag['approx']['text']} {q.unit.pretty}".strip()
        return out

    # ----- sets and solutions
    def bound(self, x: sp.Expr) -> tuple[str, str]:
        if x in (sp.oo, -sp.oo):
            return ("∞" if x == sp.oo else "-∞"), (r"\infty" if x == sp.oo else r"-\infty")
        f = self.scalar(x)
        return f["text"], f["latex"]

    def set_value(self, s: sp.Set, symbol: Any) -> dict:
        txt, ltx = self.set_strings(s, symbol)
        return {"t": "set", "text": txt, "latex": ltx}

    def set_strings(self, s: sp.Set, symbol: Any) -> tuple[str, str]:
        name = symbol.name if isinstance(symbol, sp.Symbol) else "x"
        if s == sp.Reals:
            return "all real numbers", r"\mathbb{R}"
        if s == sp.Complexes:
            return "all complex numbers", r"\mathbb{C}"
        if s == sp.EmptySet:
            return "no solution", r"\varnothing"
        if isinstance(s, sp.Interval):
            (a, ta), (b, tb) = self.bound(s.start), self.bound(s.end)
            lo, hi = ("(" if s.left_open else "["), (")" if s.right_open else "]")
            if s.start == s.end:
                return f"{name} = {a}", f"{name} = {ta}"
            return f"{lo}{a}, {b}{hi}", rf"\left{lo}{ta}, {tb}\right{hi}"
        if isinstance(s, sp.Union):
            parts = [self.set_strings(p, symbol) for p in sp.Union(*s.args).args]
            return " ∪ ".join(p[0] for p in parts), r" \cup ".join(p[1] for p in parts)
        if isinstance(s, sp.FiniteSet):
            items = [self.scalar(x) for x in s]
            return "{" + ", ".join(i["text"] for i in items) + "}", r"\left\{" + ", ".join(i["latex"] for i in items) + r"\right\}"
        if isinstance(s, sp.ImageSet):
            lam = s.lamda
            n = lam.variables[0]
            expr = self.exact_form(lam.expr.subs(n, sp.Symbol("n")))
            et = expr["text"] if expr else str(lam.expr)
            el = expr["latex"] if expr else sp.latex(lam.expr)
            return f"{name} = {et}, n ∈ ℤ", rf"{name} = {el},\ n \in \mathbb{{Z}}"
        if isinstance(s, sp.Complement):
            a, b = s.args
            ta, la = self.set_strings(a, symbol)
            tb, lb = self.set_strings(b, symbol)
            return f"{ta} without {tb}", rf"{la} \setminus {lb}"
        if isinstance(s, sp.Intersection):
            parts = [self.set_strings(p, symbol) for p in s.args]
            return " ∩ ".join(p[0] for p in parts), r" \cap ".join(p[1] for p in parts)
        return str(s), sp.latex(s)

    def solutions(self, sol: SolutionSet) -> dict:
        out: dict[str, Any] = {"t": "solutions", "domain": sol.domain, "note": sol.note}
        if isinstance(sol.symbol, tuple):                              # system of equations
            names = [s.name for s in sol.symbol]
            out["symbols"] = names
            tuples = [[self.scalar(c) for c in row] for row in sol.solutions]
            out["tuples"] = tuples
            if tuples:
                out["text"] = " or ".join("(" + ", ".join(f"{n} = {c['text']}" for n, c in zip(names, row)) + ")" for row in tuples)
                out["latex"] = r"\ \text{or}\ ".join(r"\left(" + ", ".join(f"{n} = {c['latex']}" for n, c in zip(names, row)) + r"\right)" for row in tuples)
            else:
                out["text"], out["latex"] = (sol.note or "no solution"), r"\varnothing"
            return out
        name = sol.symbol.name
        out["symbol"] = name
        if sol.set is not None:
            out["set"] = dict(zip(("text", "latex"), self.set_strings(sol.set, sol.symbol)))
            if isinstance(sol.set, sp.Interval) or isinstance(sol.set, sp.Union):
                out["text"] = f"{name} ∈ {out['set']['text']}" if not isinstance(sol.set, sp.ImageSet) else out["set"]["text"]
                out["latex"] = rf"{name} \in {out['set']['latex']}"
            else:
                out["text"], out["latex"] = out["set"]["text"], out["set"]["latex"]
            return out
        items = [self.scalar(x) for x in sol.solutions]
        out["items"] = items
        if items:
            out["text"] = " or ".join(f"{name} = {i['text']}" for i in items)
            out["latex"] = r"\ \text{or}\ ".join(f"{name} = {i['latex']}" for i in items)
        else:
            out["text"], out["latex"] = (sol.note or "no solution"), r"\varnothing"
        return out

    def table(self, t: Table) -> dict:
        rows = [[self.value(c) if not isinstance(c, tuple) else {"t": "list", "items": [self.value(x) for x in c],
                                                             "text": ", ".join(self.value(x)["text"] for x in c), "latex": ", ".join(self.value(x)["latex"] for x in c)}
                 for c in row] for row in t.rows]
        lines = [t.title] if t.title else []
        lines += ["  ".join(f"{h}: {c['text']}" for h, c in zip(t.headers, r)) for r in rows]
        return {"t": "table", "title": t.title, "headers": list(t.headers), "rows": rows, "text": "\n".join(lines),
                "latex": r"\begin{array}{" + "l" * len(t.headers) + "}" + r" \\ ".join(" & ".join(c["latex"] for c in r) for r in rows) + r"\end{array}"}


def _rel_latex(op: str) -> str:
    return {"=": "=", "!=": r"\neq", "<": "<", ">": ">", "<=": r"\leq", ">=": r"\geq"}[op]


def _unit_latex(q: Quantity) -> str:
    from ..expressions import ast as A
    return to_latex(A.UnitExpr(factors=[[s, str(e)] for s, e in q.unit.factors]))
