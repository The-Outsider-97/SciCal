"""Chemical formulas: parsing, composition, molar mass (with uncertainty), percent composition, empirical formulas."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from fractions import Fraction

from ...errors import ChemistryError, FormulaSyntaxError
from .elements import atomic_weight, element, symbols

MAX_LEN = 400
MAX_ATOMS = 1_000_000
_SUB = str.maketrans("0123456789+-", "₀₁₂₃₄₅₆₇₈₉⁺⁻")
_SUPDIG = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}
_SUPSIGN = {"⁺": "+", "⁻": "-"}
_SUBDIG = {"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9"}


@dataclass
class Formula:
    text: str
    comp: dict[str, int]
    charge: int = 0
    parts: list[tuple[int, "Formula"]] = field(default_factory=list)       # hydrate parts: (coefficient, formula)

    def hill(self) -> str:
        els = sorted(self.comp)
        if "C" in self.comp:
            order = ["C"] + (["H"] if "H" in self.comp else []) + [e for e in els if e not in ("C", "H")]
        else:
            order = els
        return "".join(e + (str(self.comp[e]) if self.comp[e] > 1 else "") for e in order)

    def pretty(self) -> str:
        s = self.text_normalized()
        out, i = "", 0
        while i < len(s):
            ch = s[i]
            if ch.isdigit() and i > 0 and (s[i - 1].isalpha() or s[i - 1] in ")]"):
                j = i
                while j < len(s) and s[j].isdigit():
                    j += 1
                out += s[i:j].translate(_SUB)
                i = j
            else:
                out += ch
                i += 1
        if self.charge:
            mag = abs(self.charge)
            out += ((str(mag) if mag > 1 else "") + ("+" if self.charge > 0 else "-")).translate(str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻"))
        return out

    def text_normalized(self) -> str:
        return self.text.split("^")[0]

    def latex(self) -> str:
        s = self.text_normalized()
        s = re.sub(r"(?<=[A-Za-z\)\]])(\d+)", r"_{\1}", s).replace("·", r"\cdot ")
        if self.charge:
            mag = abs(self.charge)
            s += "^{" + (str(mag) if mag > 1 else "") + ("+" if self.charge > 0 else "-") + "}"
        return r"\mathrm{" + s + "}"

    def atoms(self) -> int:
        return sum(self.comp.values())


def _normalise(src: str) -> str:
    out = []
    for ch in src.strip():
        if ch in _SUBDIG:
            out.append(_SUBDIG[ch])
        elif ch in _SUPDIG:
            out.append("^" + _SUPDIG[ch] if not out or out[-1] != "^" else _SUPDIG[ch])
        elif ch in _SUPSIGN:
            out.append(_SUPSIGN[ch])
        elif ch in "•⋅∙":
            out.append("·")
        elif ch in "−–":
            out.append("-")
        else:
            out.append(ch)
    s = "".join(out)
    s = re.sub(r"\^(\d+)\^", r"^\1", s)
    return s


class _P:
    def __init__(self, s: str) -> None:
        self.s, self.i = s, 0

    def peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def fail(self, msg: str) -> FormulaSyntaxError:
        return FormulaSyntaxError(msg, span=(self.i, min(self.i + 1, len(self.s))))

    def number(self) -> int | None:
        j = self.i
        while j < len(self.s) and self.s[j].isdigit():
            j += 1
        if j == self.i:
            return None
        n = int(self.s[self.i:j])
        self.i = j
        return n

    def group(self, closer: str) -> dict[str, int]:
        comp: dict[str, int] = {}
        while True:
            c = self.peek()
            if c == "" or c == closer or c in ")]^·":
                break
            if c.isupper():
                sym = c
                if self.i + 1 < len(self.s) and self.s[self.i + 1].islower():
                    two = self.s[self.i:self.i + 2]
                    if two in symbols():
                        sym = two
                if sym not in symbols():
                    raise self.fail(f"'{self.s[self.i:self.i + 2] if self.s[self.i + 1:self.i + 2].islower() else sym}' is not an element symbol")
                self.i += len(sym)
                n = self.number()
                if n == 0:
                    raise self.fail("A count of 0 is not allowed")
                comp[sym] = comp.get(sym, 0) + (1 if n is None else n)
            elif c in "([":
                close = ")" if c == "(" else "]"
                start = self.i
                self.i += 1
                inner = self.group(close)
                if self.peek() != close:
                    raise FormulaSyntaxError(f"Missing '{close}' to match the '{c}'", span=(start, start + 1))
                self.i += 1
                n = self.number()
                if n == 0:
                    raise self.fail("A count of 0 is not allowed")
                for k, v in inner.items():
                    comp[k] = comp.get(k, 0) + v * (1 if n is None else n)
                if not inner:
                    raise FormulaSyntaxError("Empty parentheses", span=(start, self.i))
            elif c.islower():
                raise self.fail(f"A lower-case letter '{c}' cannot start an element symbol")
            else:
                raise self.fail(f"Unexpected '{c}' in the formula")
            if sum(comp.values()) > MAX_ATOMS:
                raise FormulaSyntaxError("The formula has too many atoms")
        return comp


def parse_formula(src: str) -> Formula:
    if not isinstance(src, str) or not src.strip():
        raise FormulaSyntaxError("Enter a chemical formula such as H2O or Ca(OH)2")
    s = _normalise(src)
    if len(s) > MAX_LEN:
        raise FormulaSyntaxError(f"The formula is too long (limit {MAX_LEN} characters)")
    body, charge = s, 0
    m = re.search(r"\^(\d*)([+-])$", s)
    if m:
        charge = (int(m.group(1)) if m.group(1) else 1) * (1 if m.group(2) == "+" else -1)
        body = s[:m.start()]
    elif s[-1] in "+-" and "^" not in s:
        if len(s) > 1 and s[-2].isdigit():
            raise FormulaSyntaxError(f"The charge of {s} is ambiguous: is the digit a count or the size of the charge?",
                                     span=(len(s) - 2, len(s)), hint=f"Write the charge after a caret, for example {s[:-2]}^{s[-2]}{s[-1]} or {s[:-1]}^{s[-1]}.")
        charge = 1 if s[-1] == "+" else -1
        body = s[:-1]
    elif "^" in s:
        raise FormulaSyntaxError("A charge is written like ^2+ or ^- at the end of the formula", span=(s.index("^"), len(s)))
    pieces = re.split(r"[·*]|(?<=[A-Za-z0-9\)\]])\.(?=\d*[A-Z(\[])", body)
    comp: dict[str, int] = {}
    parts: list[tuple[int, Formula]] = []
    for idx, piece in enumerate(pieces):
        coef = 1
        if idx > 0:
            mm = re.match(r"(\d+)(.*)$", piece)
            if mm:
                coef, piece = int(mm.group(1)), mm.group(2)
        if not piece:
            raise FormulaSyntaxError("Nothing after the '·' of the hydrate")
        p = _P(piece)
        c = p.group("")
        if p.i != len(piece):
            raise p.fail(f"Unexpected '{piece[p.i]}'" + (" (unmatched ')')" if piece[p.i] in ")]" else ""))
        if not c:
            raise FormulaSyntaxError("The formula is empty")
        parts.append((coef, Formula(piece, c)))
        for k, v in c.items():
            comp[k] = comp.get(k, 0) + v * coef
    if sum(comp.values()) > MAX_ATOMS:
        raise FormulaSyntaxError("The formula has too many atoms")
    shown = re.sub(r"[*]|(?<=[A-Za-z0-9\)\]])\.(?=\d*[A-Z(\[])", "·", body)
    return Formula(text=shown, comp=comp, charge=charge, parts=parts if len(parts) > 1 else [])


# ------------------------------------------------------------------------------------------------------------------ masses
def molar_mass(f: Formula) -> tuple[Decimal, Decimal | None, list[str]]:
    """(g/mol, uncertainty in quadrature or None when it is not defined, notes). Exact decimal arithmetic on the tabulated weights."""
    total = Decimal(0)
    var = Decimal(0)
    defined = True
    notes: list[str] = []
    for sym, n in f.comp.items():
        w, u, kind = atomic_weight(sym)
        total += w * n
        if u is not None:
            var += (u * n) ** 2
        else:
            defined = False
        if kind == "none":
            notes.append(f"{sym} has no standard atomic weight; the mass number of its longest-lived isotope ({w}) is used")
        elif kind == "conventional":
            notes.append(f"{sym}: the conventional atomic weight {w} is used (the true value varies between natural sources)")
    with localcontext() as c:
        c.prec = 30
        return total, (var.sqrt() if defined else None), notes


def percent_composition(f: Formula) -> list[dict]:
    total, _, _ = molar_mass(f)
    rows = []
    for sym in sorted(f.comp, key=lambda e: (e != "C", e != "H", e)):
        w, _, _ = atomic_weight(sym)
        m = w * f.comp[sym]
        rows.append({"element": sym, "name": element(sym)["name"], "count": f.comp[sym], "mass": m, "percent": m / total * 100})
    return rows


def empirical_from_amounts(moles: dict[str, Fraction], tol: float = 0.06, max_mult: int = 12) -> tuple[dict[str, int], int]:
    """Smallest whole-number ratio of the given amounts (mol). Returns (counts, multiplier used)."""
    if not moles or any(v <= 0 for v in moles.values()):
        raise ChemistryError("Every element needs a positive amount")
    smallest = min(moles.values())
    ratios = {k: v / smallest for k, v in moles.items()}
    for mult in range(1, max_mult + 1):
        scaled = {k: r * mult for k, r in ratios.items()}
        if all(abs(float(v) - round(float(v))) <= tol * (1 if mult == 1 else 1) / (1 if mult < 4 else 1.5) for v in scaled.values()):
            if all(round(float(v)) >= 1 for v in scaled.values()):
                return {k: int(round(float(v))) for k, v in scaled.items()}, mult
    raise ChemistryError("The amounts do not give a clean whole-number ratio", hint="Check the data; experimental percentages should add up to about 100 %.")
