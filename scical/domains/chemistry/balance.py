"""Balancing chemical equations by linear algebra (atoms and charge), and stoichiometry from the balanced equation."""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from decimal import Decimal
from math import gcd

import sympy as sp

from ...errors import ChemistryError, FormulaSyntaxError
from .formula import Formula, molar_mass, parse_formula

ARROWS = re.compile(r"\s*(?:<->|<=>|⇌|⟶|→|->|=>|=)\s*")
MAX_SPECIES = 14


@dataclass
class Species:
    text: str
    formula: Formula
    given_coef: int | None = None
    is_electron: bool = False


def parse_species(term: str) -> Species:
    t = term.strip()
    m = re.match(r"^(\d+)\s*(.*)$", t)
    coef = None
    if m and m.group(2):
        coef, t = int(m.group(1)), m.group(2)
    if t in ("e-", "e^-", "e−", "e⁻"):
        return Species("e⁻", Formula("e", {}, -1), coef, True)
    if not t:
        raise FormulaSyntaxError("An empty term between two '+' signs")
    return Species(t, parse_formula(t), coef)


def split_side(side: str) -> list[Species]:
    terms: list[str] = []
    for piece in re.split(r"\s+\+\s+", side.strip()):
        terms += re.split(r"(?<!\^)(?<!\^\d)(?<!\^\d\d)\+(?=\S)", piece)   # a "+" at the very end of a term is its charge (Ag+), not a separator
    terms = [t for t in terms if t.strip() != ""]
    if not terms:
        raise FormulaSyntaxError("One side of the equation is empty")
    return [parse_species(t) for t in terms]


def parse_equation(text: str) -> tuple[list[Species], list[Species]]:
    parts = ARROWS.split(text.strip())
    if len(parts) != 2:
        raise FormulaSyntaxError("Write the equation with one arrow, for example: H2 + O2 -> H2O",
                                 hint="Accepted arrows: ->  →  =  <=>  ⇌")
    left, right = split_side(parts[0]), split_side(parts[1])
    if len(left) + len(right) > MAX_SPECIES:
        raise ChemistryError(f"Too many species (limit {MAX_SPECIES})")
    return left, right


def _lcm(a: int, b: int) -> int:
    return a * b // gcd(a, b)


def _matrix(left: list[Species], right: list[Species]) -> tuple[sp.Matrix, list[str]]:
    rows: list[str] = []
    for s in left + right:
        for e in s.formula.comp:
            if e not in rows:
                rows.append(e)
    has_charge = any(s.formula.charge for s in left + right)
    if has_charge:
        rows.append("charge")
    cols = left + right
    data = []
    for r in rows:
        row = []
        for j, s in enumerate(cols):
            v = s.formula.charge if r == "charge" else s.formula.comp.get(r, 0)
            row.append(v if j < len(left) else -v)
        data.append(row)
    return sp.Matrix(data), rows


def _integerize(vec: sp.Matrix) -> list[int]:
    den = 1
    for x in vec:
        den = _lcm(den, int(sp.fraction(sp.nsimplify(x))[1]))
    ints = [int(x * den) for x in vec]
    g = 0
    for x in ints:
        g = gcd(g, abs(x))
    return [x // g for x in ints] if g else ints


def balance(text: str) -> dict:
    left, right = parse_equation(text)
    n_l = len(left)
    # every element must occur on both sides
    el_l = {e for s in left for e in s.formula.comp}
    el_r = {e for s in right for e in s.formula.comp}
    if el_l != el_r:
        diff = sorted(el_l ^ el_r)
        raise ChemistryError(f"Not every element appears on both sides: {', '.join(diff)} appear on one side only",
                             hint="Atoms cannot be created or destroyed. Check the formulas.")
    M, rows = _matrix(left, right)
    ns = M.nullspace()
    if not ns:
        raise ChemistryError("This equation cannot be balanced with whole-number coefficients",
                             hint="Check the formulas: a species may be missing, or one may be written wrongly.")
    basis = [_integerize(v) for v in ns]
    result: dict = {"ok": True, "freedom": len(basis)}
    solutions: list[list[int]] = []
    if len(basis) == 1:
        v = basis[0]
        if all(x > 0 for x in v):
            solutions = [v]
        elif all(x < 0 for x in v):
            solutions = [[-x for x in v]]
        else:
            raise ChemistryError("No balance with positive coefficients exists for these species",
                                 hint="Some species would have to appear on the opposite side. Check which side each species belongs on.")
    else:
        # search small positive combinations of the null-space basis
        k = len(basis)
        found: list[list[int]] = []
        rng = range(-6, 7)
        for combo in itertools.product(rng, repeat=min(k, 4)):
            if not any(combo):
                continue
            v = [sum(c * b[i] for c, b in zip(combo, basis)) for i in range(len(basis[0]))]
            if all(x > 0 for x in v):
                g = 0
                for x in v:
                    g = gcd(g, x)
                v = [x // g for x in v]
                if v not in found:
                    found.append(v)
        found.sort(key=lambda v: (sum(v), v))
        if not found:
            raise ChemistryError("No balance with positive coefficients exists for these species")
        solutions = found[:5]
        result["ambiguous"] = True
        result["note"] = (f"The equation has {k} independent solutions, so it can be balanced in infinitely many ways "
                          "(the species contain more unknown coefficients than the atom balance can fix). The smallest are listed.")
    out = []
    for coefs in solutions:
        out.append(_render(left, right, coefs))
    result.update(out[0])
    result["alternatives"] = out[1:]
    return result


def _render(left: list[Species], right: list[Species], coefs: list[int]) -> dict:
    n_l = len(left)

    def side(items: list[Species], cs: list[int], pretty: bool) -> str:
        parts = []
        for s, c in zip(items, cs):
            body = s.text if s.is_electron is False and not pretty else (s.formula.pretty() if not s.is_electron else "e⁻")
            if not pretty:
                body = s.text if not s.is_electron else "e-"
            parts.append((str(c) if c != 1 else "") + body)
        return " + ".join(parts)
    plain = side(left, coefs[:n_l], False) + " -> " + side(right, coefs[n_l:], False)
    pretty = side(left, coefs[:n_l], True) + " → " + side(right, coefs[n_l:], True)
    lat = " + ".join((str(c) if c != 1 else "") + (r"\mathrm{e}^{-}" if s.is_electron else s.formula.latex()) for s, c in zip(left, coefs[:n_l])) \
        + r" \longrightarrow " + " + ".join((str(c) if c != 1 else "") + (r"\mathrm{e}^{-}" if s.is_electron else s.formula.latex()) for s, c in zip(right, coefs[n_l:]))
    # verification
    atoms_l: dict[str, int] = {}
    atoms_r: dict[str, int] = {}
    ch_l = ch_r = 0
    for s, c in zip(left, coefs[:n_l]):
        ch_l += c * s.formula.charge
        for e, k in s.formula.comp.items():
            atoms_l[e] = atoms_l.get(e, 0) + c * k
    for s, c in zip(right, coefs[n_l:]):
        ch_r += c * s.formula.charge
        for e, k in s.formula.comp.items():
            atoms_r[e] = atoms_r.get(e, 0) + c * k
    ok = atoms_l == atoms_r and ch_l == ch_r
    return {"balanced": plain, "pretty": pretty, "latex": lat, "coefficients": list(coefs),
            "reactants": [{"species": s.text, "pretty": s.formula.pretty() if not s.is_electron else "e⁻", "coefficient": c} for s, c in zip(left, coefs[:n_l])],
            "products": [{"species": s.text, "pretty": s.formula.pretty() if not s.is_electron else "e⁻", "coefficient": c} for s, c in zip(right, coefs[n_l:])],
            "verification": {"atomsLeft": atoms_l, "atomsRight": atoms_r, "chargeLeft": ch_l, "chargeRight": ch_r, "balanced": ok}}
