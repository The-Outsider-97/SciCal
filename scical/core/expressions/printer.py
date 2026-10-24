"""Printing the AST: ``to_text`` gives input that parses back to an equal tree; ``to_latex`` gives LaTeX for display and export."""
from __future__ import annotations

import re

from . import ast as A
from .functions import FUNCTIONS, canonical

P_OR, P_AND, P_NOT, P_REL, P_ADD, P_MUL, P_UNARY, P_POW, P_POST, P_ATOM = range(1, 11)

_GREEK = {"alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa", "lambda", "mu", "nu", "xi",
          "rho", "sigma", "tau", "phi", "chi", "psi", "omega", "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Phi", "Psi", "Omega"}
_GREEK_CHARS = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "θ": "theta", "λ": "lambda", "μ": "mu", "ν": "nu",
                "ρ": "rho", "σ": "sigma", "φ": "phi", "ω": "omega", "Δ": "Delta", "Ω": "Omega", "Σ": "Sigma", "ζ": "zeta", "η": "eta",
                "ξ": "xi", "χ": "chi", "ψ": "psi", "Γ": "Gamma", "Θ": "Theta", "Λ": "Lambda", "Φ": "Phi", "Ψ": "Psi"}


def prec(n: A.Node) -> int:
    if isinstance(n, A.Binary):
        return {"+": P_ADD, "-": P_ADD, "*": P_MUL, "/": P_MUL, "mod": P_MUL, "^": P_POW}[n.op]
    if isinstance(n, A.Unary):
        return P_UNARY
    if isinstance(n, A.Postfix):
        return P_POST
    if isinstance(n, A.Rel):
        return P_REL
    if isinstance(n, A.Logic):
        return {"or": P_OR, "and": P_AND, "not": P_NOT}[n.op] if n.op != "and" or len(n.args) != 2 or not all(isinstance(a, A.Rel) for a in n.args) else P_REL
    if isinstance(n, (A.Assign, A.FuncDef, A.Convert)):
        return 0
    if isinstance(n, A.Num):
        return P_UNARY if n.text.startswith("-") else P_ATOM
    return P_ATOM


# ================================================================================================================ text
def to_text(n: A.Node) -> str:
    return _t(n)


def _wrap(n: A.Node, minimum: int) -> str:
    s = _t(n)
    return f"({s})" if prec(n) < minimum else s


def _starts_with_letter(s: str) -> bool:
    return bool(s) and (s[0].isalpha() or s[0] in "_√")


def _t(n: A.Node) -> str:
    if isinstance(n, A.Num):
        return n.text
    if isinstance(n, A.Var):
        return n.name
    if isinstance(n, A.Unary):
        return n.op + _wrap(n.arg, P_UNARY if isinstance(n.arg, A.Unary) else P_UNARY)
    if isinstance(n, A.Postfix):
        inner = _t(n.arg)
        if prec(n.arg) < P_POST or (isinstance(n.arg, A.Postfix) and n.op != n.arg.op):
            inner = f"({inner})"
        return inner + n.op
    if isinstance(n, A.Binary):
        return _t_binary(n)
    if isinstance(n, A.Call):
        args = ", ".join(_t(a) for a in n.args)
        if n.power is not None:
            return f"{n.name}^{_t(n.power)}({args})"
        return f"{n.name}({args})"
    if isinstance(n, A.Vector):
        return "[" + ", ".join(_t(x) for x in n.items) + "]"
    if isinstance(n, A.Matrix):
        return "[" + "; ".join(", ".join(_t(x) for x in r) for r in n.rows) + "]"
    if isinstance(n, A.Rel):
        return f"{_wrap(n.left, P_ADD)} {n.op} {_wrap(n.right, P_ADD)}"
    if isinstance(n, A.Logic):
        if n.op == "not":
            return "not " + _wrap(n.args[0], P_REL)
        if n.op == "and" and all(isinstance(a, A.Rel) for a in n.args) and len(n.args) >= 2 and _is_chain(n.args):
            parts = [_wrap(n.args[0].left, P_ADD)]                                   # type: ignore[attr-defined]
            for r in n.args:
                parts.append(r.op)                                                    # type: ignore[attr-defined]
                parts.append(_wrap(r.right, P_ADD))                                  # type: ignore[attr-defined]
            return " ".join(parts)
        p = P_OR if n.op == "or" else P_AND
        return f" {n.op} ".join(_wrap(a, p + 1) for a in n.args)
    if isinstance(n, A.Assign):
        return f"{n.name} := {_t(n.value)}"
    if isinstance(n, A.FuncDef):
        return f"{n.name}({', '.join(n.params)}) := {_t(n.body)}"
    if isinstance(n, A.UnitExpr):
        return _unit_text(n)
    if isinstance(n, A.Qty):
        return f"{_wrap(n.value, P_ATOM)} {_unit_text(n.unit)}"
    if isinstance(n, A.Convert):
        return f"{_t(n.expr)} -> {_unit_text(n.unit)}"
    raise TypeError(f"cannot print {type(n).__name__}")


def _is_chain(rels: list) -> bool:
    return all(rels[i].right == rels[i + 1].left for i in range(len(rels) - 1))


def _t_binary(n: A.Binary) -> str:
    op = n.op
    if op == "^":
        base = _t(n.left) if prec(n.left) >= P_ATOM or isinstance(n.left, A.Postfix) else f"({_t(n.left)})"
        if isinstance(n.left, A.Num) and n.left.text.startswith("-"):
            base = f"({base})"
        exp = n.right
        if isinstance(exp, A.Unary) and isinstance(exp.arg, (A.Num, A.Var)):
            es = _t(exp)
        elif prec(exp) >= P_POW:
            es = _t(exp)
        else:
            es = f"({_t(exp)})"
        return f"{base}^{es}"
    left_min = P_MUL if op in ("*", "/", "mod") else P_ADD
    ls = _wrap(n.left, left_min)
    rs = _wrap(n.right, left_min + 1)
    if op == "mod":
        return f"{ls} mod {rs}"
    if op == "*" and n.implicit and _can_juxtapose(n.left, n.right, ls, rs):
        sep = " " if (ls[-1].isalnum() or ls[-1] in "_") and _starts_with_letter(rs) and not ls[-1].isdigit() else ""
        return f"{ls}{sep}{rs}"
    return f"{ls} {op} {rs}"


def _can_juxtapose(left: A.Node, right: A.Node, ls: str, rs: str) -> bool:
    if isinstance(right, A.Num) or rs[0].isdigit() or rs[0] in "-+.":
        return False
    if isinstance(left, A.Var) and len(left.name) > 1 and rs.startswith("("):
        return False
    if isinstance(left, A.Var) and isinstance(right, A.Var):
        return len(left.name) == 1 and len(right.name) == 1 and False
    return True


def _unit_text(u: A.UnitExpr) -> str:
    num, den = [], []
    for sym, exp in u.factors:
        e = _frac(exp)
        target = den if e < 0 else num
        a = abs(e)
        target.append(sym if a == 1 else (f"{sym}^{a.numerator}" if a.denominator == 1 else f"{sym}^({a.numerator}/{a.denominator})"))
    top = " ".join(num) if num else "1"
    if not den:
        return top
    bottom = " ".join(den)
    return f"{top}/{bottom}" if len(den) == 1 else f"{top}/({bottom})"


def _frac(s: str):
    from fractions import Fraction
    return Fraction(s)


# ================================================================================================================ LaTeX
def _name_latex(name: str) -> str:
    name = _GREEK_CHARS.get(name, name)
    if name in ("pi", "π"):
        return r"\pi"
    if name in ("tau", "τ"):
        return r"\tau"
    if name in ("inf", "oo", "∞"):
        return r"\infty"
    if name == "i":
        return r"\mathrm{i}"
    if name == "e":
        return r"\mathrm{e}"
    base, sub = name, None
    m = re.fullmatch(r"([^\W\d_]+)_?(\w+)", name) if "_" in name else None
    if m:
        base, sub = m.group(1), m.group(2)
    elif re.fullmatch(r"[^\W\d_]\d+", name):
        base, sub = name[0], name[1:]
    base = _GREEK_CHARS.get(base, base)
    out = ("\\" + base) if base in _GREEK else (base if len(base) == 1 else r"\mathit{" + base + "}")
    if sub:
        out += "_{" + _GREEK_CHARS.get(sub, sub).replace("_", ",") + "}"
    return out


def _num_latex(text: str) -> str:
    if "e" in text:
        mant, exp = text.split("e")
        exp = exp.lstrip("+")
        return f"{mant}\\times 10^{{{exp}}}"
    return text


def to_latex(n: A.Node) -> str:
    return _l(n)


def _lw(n: A.Node, minimum: int) -> str:
    s = _l(n)
    return rf"\left({s}\right)" if prec(n) < minimum else s


def _l(n: A.Node) -> str:
    if isinstance(n, A.Num):
        return _num_latex(n.text)
    if isinstance(n, A.Var):
        return _name_latex(n.name)
    if isinstance(n, A.Unary):
        return n.op + _lw(n.arg, P_UNARY)
    if isinstance(n, A.Postfix):
        arg = _lw(n.arg, P_ATOM)
        return {"!": arg + "!", "%": arg + r"\%", "°": arg + r"^{\circ}"}[n.op]
    if isinstance(n, A.Binary):
        return _l_binary(n)
    if isinstance(n, A.Call):
        return _l_call(n)
    if isinstance(n, A.Vector):
        return r"\begin{bmatrix}" + r" \\ ".join(_l(x) for x in n.items) + r"\end{bmatrix}"
    if isinstance(n, A.Matrix):
        return r"\begin{bmatrix}" + r" \\ ".join(" & ".join(_l(x) for x in r) for r in n.rows) + r"\end{bmatrix}"
    if isinstance(n, A.Rel):
        sym = {"=": "=", "!=": r"\neq", "<": "<", ">": ">", "<=": r"\leq", ">=": r"\geq"}[n.op]
        return f"{_lw(n.left, P_ADD)} {sym} {_lw(n.right, P_ADD)}"
    if isinstance(n, A.Logic):
        if n.op == "not":
            return r"\neg " + _lw(n.args[0], P_REL)
        if n.op == "and" and all(isinstance(a, A.Rel) for a in n.args) and _is_chain(n.args):
            sym = {"=": "=", "!=": r"\neq", "<": "<", ">": ">", "<=": r"\leq", ">=": r"\geq"}
            parts = [_lw(n.args[0].left, P_ADD)]                                     # type: ignore[attr-defined]
            for r in n.args:
                parts += [sym[r.op], _lw(r.right, P_ADD)]                             # type: ignore[attr-defined]
            return " ".join(parts)
        word = r"\ \text{or}\ " if n.op == "or" else r"\ \text{and}\ "
        p = P_OR if n.op == "or" else P_AND
        return word.join(_lw(a, p + 1) for a in n.args)
    if isinstance(n, A.Assign):
        return f"{_name_latex(n.name)} := {_l(n.value)}"
    if isinstance(n, A.FuncDef):
        return rf"{_name_latex(n.name)}\left({', '.join(_name_latex(p) for p in n.params)}\right) := {_l(n.body)}"
    if isinstance(n, A.UnitExpr):
        return _unit_latex(n)
    if isinstance(n, A.Qty):
        return rf"{_lw(n.value, P_ATOM)}\,{_unit_latex(n.unit)}"
    if isinstance(n, A.Convert):
        return rf"{_l(n.expr)} \rightarrow {_unit_latex(n.unit)}"
    raise TypeError(f"cannot print {type(n).__name__}")


def _unit_latex(u: A.UnitExpr) -> str:
    def one(sym: str, e) -> str:
        s = r"\mathrm{" + sym.replace("_", r"\_").replace("µ", r"\mu ").replace("Ω", r"\Omega ").replace("°", r"^{\circ}") + "}"
        return s if e == 1 else f"{s}^{{{e.numerator if e.denominator == 1 else rf'{e.numerator}/{e.denominator}'}}}"
    num = [one(s, _frac(x)) for s, x in u.factors if _frac(x) > 0]
    den = [one(s, -_frac(x)) for s, x in u.factors if _frac(x) < 0]
    top = r"\,".join(num) if num else "1"
    if not den:
        return top
    bottom = r"\,".join(den)
    return rf"\frac{{{top}}}{{{bottom}}}"


def _l_binary(n: A.Binary) -> str:
    op = n.op
    if op == "/":
        if isinstance(n.left, A.Unary) and n.left.op == "-":
            return rf"-\frac{{{_l(n.left.arg)}}}{{{_l(n.right)}}}"
        return rf"\frac{{{_l(n.left)}}}{{{_l(n.right)}}}"
    if op == "^":
        base = _lw(n.left, P_ATOM) if not isinstance(n.left, A.Call) else _l(n.left) if n.left.power is None and n.left.name in ("sqrt", "abs", "root") else _lw(n.left, P_ATOM)
        return f"{base}^{{{_l(n.right)}}}"
    left_min = P_MUL if op in ("*", "mod") else P_ADD
    ls = _lw(n.left, left_min)
    rs = _lw(n.right, left_min + 1)
    if op == "*":
        if n.implicit and not isinstance(n.right, A.Num):
            return f"{ls}\\,{rs}" if isinstance(n.left, A.Num) is False and isinstance(n.right, (A.Call,)) else f"{ls} {rs}"
        return rf"{ls} \cdot {rs}"
    if op == "mod":
        return rf"{ls} \bmod {rs}"
    return f"{ls} {op} {rs}"


def _l_call(n: A.Call) -> str:
    name = canonical(n.name) or n.name
    a = n.args
    if n.power is None:
        if name == "sqrt" and len(a) == 1:
            return rf"\sqrt{{{_l(a[0])}}}"
        if name == "root" and len(a) == 2:
            return rf"\sqrt[{_l(a[1])}]{{{_l(a[0])}}}"
        if name == "abs" and len(a) == 1:
            return rf"\left|{_l(a[0])}\right|"
        if name == "floor" and len(a) == 1:
            return rf"\left\lfloor {_l(a[0])}\right\rfloor"
        if name == "ceil" and len(a) == 1:
            return rf"\left\lceil {_l(a[0])}\right\rceil"
        if name == "exp" and len(a) == 1:
            return rf"\mathrm{{e}}^{{{_l(a[0])}}}"
        if name in ("nCr",) and len(a) == 2:
            return rf"\binom{{{_l(a[0])}}}{{{_l(a[1])}}}"
        if name == "diff" and len(a) >= 2:
            order = _l(a[2]) if len(a) > 2 else ""
            sup = f"^{{{order}}}" if order else ""
            return rf"\frac{{\mathrm{{d}}{sup}}}{{\mathrm{{d}}{_l(a[1])}{sup}}}\left({_l(a[0])}\right)"
        if name == "integral" and len(a) == 4:
            return rf"\int_{{{_l(a[2])}}}^{{{_l(a[3])}}} {_l(a[0])}\,\mathrm{{d}}{_l(a[1])}"
        if name == "integral" and len(a) == 2:
            return rf"\int {_l(a[0])}\,\mathrm{{d}}{_l(a[1])}"
        if name in ("sum", "prod") and len(a) == 4:
            big = r"\sum" if name == "sum" else r"\prod"
            return rf"{big}_{{{_l(a[1])}={_l(a[2])}}}^{{{_l(a[3])}}} {_lw(a[0], P_MUL)}"
        if name == "limit" and len(a) >= 3:
            return rf"\lim_{{{_l(a[1])} \to {_l(a[2])}}} {_l(a[0])}"
        if name == "transpose" and len(a) == 1:
            return rf"{_lw(a[0], P_ATOM)}^{{\mathsf{{T}}}}"
    fn = FUNCTIONS.get(name)
    cmd = fn.latex if fn and fn.latex.startswith("\\") and name not in ("floor", "ceil") else rf"\operatorname{{{n.name}}}"
    if cmd in ("\\sqrt", "\\lfloor"):
        cmd = rf"\operatorname{{{n.name}}}"
    pw = f"^{{{_l(n.power)}}}" if n.power is not None else ""
    return rf"{cmd}{pw}\left({', '.join(_l(x) for x in a)}\right)"
