"""Units and unit-bearing quantities with exact arithmetic and dimensional analysis.

A :class:`Unit` is a product of registered unit symbols with exponents. A :class:`Quantity` is an exact SymPy magnitude with a unit.
The rules (Pint-compatible where it matters, and stricter where a silent answer would mislead):

* ``+`` and ``-`` need identical dimensions; the result is in the left operand's unit.
* An absolute temperature (°C, °F) minus another is a *difference* (``delta_degC``); two absolute temperatures cannot be added; an
  absolute temperature plus or minus a difference or a kelvin amount is absolute. Multiplying an absolute temperature is refused.
* Hz and rpm count cycles, rad counts radians: converting between them without the factor 2*pi is refused.
* A result whose dimensions cancel completely becomes a plain number (``(5 m)/(25 cm)`` is ``20``), except for angles and ratios
  (``deg``, ``ppm``), whose symbol is kept.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Iterable, Sequence

from sympy import Basic, Expr, Integer, Number, Rational, S, nsimplify, sympify

from ...errors import DimensionError, UnitError
from .dimension import BASE, Dim
from .registry import REGISTRY

_SUP = str.maketrans("0123456789-+", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺")


def _exp_text(e: Fraction, pretty: bool) -> str:
    if e == 1:
        return ""
    s = str(e) if e.denominator == 1 else f"({e.numerator}/{e.denominator})"
    return s.translate(_SUP) if pretty and e.denominator == 1 else "^" + s


def _merge(factors: Iterable[tuple[str, Fraction]]) -> tuple[tuple[str, Fraction], ...]:
    acc: dict[str, Fraction] = {}
    for sym, e in factors:
        acc[sym] = acc.get(sym, Fraction(0)) + Fraction(e)
    return tuple((s, e) for s, e in acc.items() if e != 0)


class Unit:
    """An immutable product of unit symbols; ``Unit(())`` is the unit of a plain number."""
    __slots__ = ("factors", "dim", "scale", "offset", "kind", "has_angle", "has_cyclic", "keep")

    def __init__(self, factors: Iterable[tuple[str, Fraction | int]] = ()) -> None:
        facs = _merge((s, Fraction(e)) for s, e in factors)
        dim, scale = Dim(), S.One
        offset, kind, angle, cyclic, keep = S.Zero, "linear", False, False, False
        for sym, e in facs:
            d, pre, _ = REGISTRY.resolve(sym)
            dim = dim * (d.dim ** e)
            scale = scale * (pre * d.scale) ** Rational(e.numerator, e.denominator)
            angle |= d.angle
            cyclic |= d.cyclic
            keep |= d.keep
            if d.kind == "affine":
                if len(facs) != 1 or e != 1:
                    raise UnitError(f"{d.symbol} is an absolute temperature scale and cannot be used inside a compound unit",
                                    hint="Use K for temperature in a compound unit, or delta_degC for a temperature difference.")
                offset, kind = d.offset, "affine"
            elif d.kind == "delta" and len(facs) == 1 and e == 1:
                kind = "delta"
        object.__setattr__(self, "factors", facs)
        object.__setattr__(self, "dim", dim)
        object.__setattr__(self, "scale", scale)
        object.__setattr__(self, "offset", offset)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "has_angle", angle)
        object.__setattr__(self, "has_cyclic", cyclic)
        object.__setattr__(self, "keep", keep)

    def __setattr__(self, *_: object) -> None:
        raise AttributeError("Unit is immutable")

    # ---- algebra ---------------------------------------------------------------------------------------------------------
    def __mul__(self, other: "Unit") -> "Unit":
        return Unit(self.factors + other.factors)

    def __truediv__(self, other: "Unit") -> "Unit":
        return Unit(self.factors + tuple((s, -e) for s, e in other.factors))

    def __pow__(self, n: Fraction | int) -> "Unit":
        n = Fraction(n)
        return Unit(tuple((s, e * n) for s, e in self.factors))

    def inverse(self) -> "Unit":
        return Unit(tuple((s, -e) for s, e in self.factors))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Unit) and set(self.factors) == set(other.factors)

    def __hash__(self) -> int:
        return hash(frozenset(self.factors))

    def is_empty(self) -> bool:
        return not self.factors

    # ---- text ------------------------------------------------------------------------------------------------------------
    def _render(self, pretty: bool) -> str:
        if not self.factors:
            return ""
        num = [(s, e) for s, e in self.factors if e > 0]
        den = [(s, -e) for s, e in self.factors if e < 0]
        sep = "·" if pretty else "*"

        def part(items: list[tuple[str, Fraction]]) -> str:
            return sep.join(self._sym(s, pretty) + _exp_text(e, pretty) for s, e in items)
        top = part(num) if num else "1"
        if not den:
            return top
        bottom = part(den)
        return f"{top}/{bottom}" if len(den) == 1 and den[0][1] == 1 or len(den) == 1 else f"{top}/({bottom})"

    @staticmethod
    def _sym(sym: str, pretty: bool) -> str:
        if not pretty:
            return sym
        return {"degC": "°C", "degF": "°F", "degR": "°R", "ohm": "Ω", "delta_degC": "Δ°C", "delta_degF": "Δ°F", "angstrom": "Å"}.get(sym, sym)

    @property
    def text(self) -> str:
        """ASCII form that :func:`parse_unit` reads back (``kg*m/s^2``)."""
        return self._render(False)

    @property
    def pretty(self) -> str:
        return self._render(True)

    def __repr__(self) -> str:
        return f"Unit({self.text!r})"

    def base_unit(self) -> "Unit":
        """The coherent SI unit with the same dimension, e.g. kg*m/s^2 for a force."""
        order = ("m", "kg", "s", "A", "K", "mol", "cd")
        # BASE is (L, M, T, I, Θ, N, J)
        sym = {"L": "m", "M": "kg", "T": "s", "I": "A", "Θ": "K", "N": "mol", "J": "cd"}
        facs = [(sym[b], e) for b, e in zip(BASE, self.dim.exps) if e]
        facs.sort(key=lambda f: order.index(f[0]))
        return Unit(facs)


class Quantity:
    """An exact magnitude with a unit."""
    __slots__ = ("mag", "unit")

    def __init__(self, mag: Any, unit: Unit) -> None:
        self.mag = sympify(mag)
        self.unit = unit

    def __repr__(self) -> str:
        return f"Quantity({self.mag}, {self.unit.text!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Quantity):
            return False
        try:
            return bool(to_si(self).mag == to_si(other).mag and self.unit.dim == other.unit.dim)
        except UnitError:
            return False

    __hash__ = None  # type: ignore[assignment]

    def si_magnitude(self) -> Expr:
        return self.mag * self.unit.scale + self.unit.offset


# ---------------------------------------------------------------------------------------------------------------------------
def make(mag: Any, unit: Unit) -> Any:
    """Build a quantity and fold away units whose dimensions cancelled (see the module docstring)."""
    mag = sympify(mag)
    if unit.is_empty():
        return mag
    if unit.dim.is_dimensionless() and not unit.keep:
        return mag * unit.scale
    return Quantity(mag, unit)


def as_quantity(x: Any) -> Quantity:
    return x if isinstance(x, Quantity) else Quantity(x, Unit(()))


def _desc(q: Quantity) -> str:
    return f"{q.unit.pretty or 'a plain number'} ({q.unit.dim.name})"


def _check_same_dims(a: Quantity, b: Quantity, what: str) -> None:
    if a.unit.dim != b.unit.dim:
        raise DimensionError(f"Cannot {what}: {_desc(a)} and {_desc(b)} have different dimensions",
                             hint="Convert one of them first, or check the units.", details={"left": a.unit.dim.name, "right": b.unit.dim.name})
    if (a.unit.has_cyclic and b.unit.has_angle) or (a.unit.has_angle and b.unit.has_cyclic):
        raise UnitError(f"Cannot {what}: Hz and rpm count cycles while rad counts radians",
                        hint="1 cycle = 2π rad. Multiply by 2π rad explicitly, e.g. 50 Hz * 2π rad.")


_DELTA_OF = {"degC": "delta_degC", "degF": "delta_degF"}


def add(a: Any, b: Any, sign: int = 1) -> Any:
    """``a + b`` (``sign=1``) or ``a - b`` (``sign=-1``) for quantities."""
    qa, qb = as_quantity(a), as_quantity(b)
    verb = "add" if sign == 1 else "subtract"
    if qa.unit.is_empty() != qb.unit.is_empty():
        raise DimensionError(f"Cannot {verb} a plain number and a quantity with unit {(qa if not qa.unit.is_empty() else qb).unit.pretty}",
                             hint="Give both values a unit, or neither.")
    _check_same_dims(qa, qb, verb)
    ka, kb = qa.unit.kind, qb.unit.kind
    ua, ub = qa.unit, qb.unit
    if ka == "affine" or kb == "affine":
        sym_a, sym_b = ua.factors[0][0] if ka == "affine" else None, ub.factors[0][0] if kb == "affine" else None
        if ka == "affine" and kb == "affine":
            if sign == 1:
                raise UnitError("Cannot add two absolute temperatures", hint="Use a temperature difference (delta_degC) for one of them, or convert both to K.")
            diff = qa.si_magnitude() - qb.si_magnitude()
            out_unit = Unit(((_DELTA_OF[sym_a], 1),))
            return Quantity(diff / out_unit.scale, out_unit)
        if ka == "affine":                         # absolute +/- (difference or kelvin)
            return Quantity(qa.mag + sign * qb.mag * ub.scale / ua.scale, ua)
        if sign == -1:
            raise UnitError("Cannot subtract an absolute temperature from a temperature difference")
        return Quantity(qb.mag + qa.mag * ua.scale / ub.scale, ub)       # difference + absolute
    return make(qa.mag + sign * qb.mag * ub.scale / ua.scale, ua) if not ua.is_empty() else qa.mag + sign * qb.mag


def _no_affine(q: Quantity, op: str) -> None:
    if q.unit.kind == "affine":
        sym = q.unit.factors[0][0]
        raise UnitError(f"{op} an absolute temperature in {q.unit.pretty} is ambiguous",
                        hint=f"Convert to K first ({q.mag} {sym} -> K) or use {_DELTA_OF[sym]} for a temperature difference.")


def mul(a: Any, b: Any) -> Any:
    if not isinstance(a, Quantity) and not isinstance(b, Quantity):
        return a * b
    qa, qb = as_quantity(a), as_quantity(b)
    for q in (qa, qb):
        if not q.unit.is_empty():
            _no_affine(q, "Multiplying")
    return make(qa.mag * qb.mag, qa.unit * qb.unit)


def div(a: Any, b: Any) -> Any:
    if not isinstance(a, Quantity) and not isinstance(b, Quantity):
        return a / b
    qa, qb = as_quantity(a), as_quantity(b)
    for q in (qa, qb):
        if not q.unit.is_empty():
            _no_affine(q, "Dividing")
    return make(qa.mag / qb.mag, qa.unit / qb.unit)


def power(a: Any, n: Any) -> Any:
    if isinstance(n, Quantity):
        raise DimensionError("An exponent cannot carry a unit")
    qa = as_quantity(a)
    _no_affine(qa, "Raising")
    if not (isinstance(n, Number) or getattr(n, "is_number", False)) or not getattr(n, "is_rational", False):
        raise UnitError("A unit can only be raised to a rational power (such as 2, -1 or 1/2)")
    e = Fraction(int(Rational(n).p), int(Rational(n).q))
    return make(qa.mag ** n, qa.unit ** e)


def neg(a: Quantity) -> Quantity:
    return Quantity(-a.mag, a.unit)


def convert(q: Any, target: Unit) -> Quantity:
    """Express ``q`` in ``target``. A plain number converts only into a dimensionless unit."""
    qq = as_quantity(q)
    if qq.unit.dim != target.dim:
        raise DimensionError(f"Cannot convert {_desc(qq)} into {target.pretty} ({target.dim.name})",
                             hint="Both sides of a conversion must measure the same kind of quantity.",
                             details={"from": qq.unit.dim.name, "to": target.dim.name})
    if (qq.unit.has_cyclic and target.has_angle) or (qq.unit.has_angle and target.has_cyclic):
        raise UnitError(f"Hz and rpm count cycles while rad counts radians, so {qq.unit.pretty} cannot be converted into {target.pretty} directly",
                        hint="1 cycle = 2π rad; apply the factor 2π explicitly.")
    si = qq.si_magnitude()
    return Quantity((si - target.offset) / target.scale, target)


def to_si(q: Quantity) -> Quantity:
    unit = q.unit.base_unit()
    return Quantity(q.si_magnitude(), unit)


def compare(a: Any, b: Any) -> int:
    """-1, 0, 1 for two quantities of the same dimension (or two plain numbers)."""
    qa, qb = as_quantity(a), as_quantity(b)
    if qa.unit.is_empty() != qb.unit.is_empty() or qa.unit.dim != qb.unit.dim:
        raise DimensionError(f"Cannot compare {_desc(qa)} with {_desc(qb)}")
    x, y = qa.si_magnitude(), qb.si_magnitude()
    d = x - y
    if d == 0:
        return 0
    return 1 if d.is_positive else -1 if d.is_negative else 1 if float(d) > 0 else -1


# ---------------------------------------------------------------------------------------------------------------------------
_SUPERSCRIPT = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9", "⁻": "-", "⁺": "+"}
def parse_unit(text: str) -> Unit:
    """Read a unit expression: ``km/h``, ``kg*m/s^2``, ``m s^-2``, ``mol/(L*s)``, ``m²``, ``°C``. Left to right, so ``J/mol*K`` is
    ``(J/mol)*K``; write ``J/(mol*K)`` for a quotient."""
    s = text.strip()
    if not s:
        raise UnitError("Empty unit")
    if len(s) > 200:
        raise UnitError("Unit expression too long")
    return _parse_unit_simple(s)


_EXP = re.compile(r"\s*(?:\^|\*\*)\s*(?:\(\s*(-?\d+)\s*(?:/\s*(\d+))?\s*\)|(-?\d+))|([⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+)")
_ATOM = re.compile(r"\s*([A-Za-zµμΩÅ°Δ_][A-Za-zµμΩÅ°Δ_0-9]*)")


def _parse_unit_simple(s: str) -> Unit:
    pos = 0
    n = len(s)

    def ws() -> None:
        nonlocal pos
        while pos < n and s[pos].isspace():
            pos += 1

    def group(depth: int) -> list[tuple[str, Fraction]]:
        """Parse a product/quotient until ')' or the end. Left to right: a/b*c = (a/b)*c."""
        nonlocal pos
        out: list[tuple[str, Fraction]] = []
        sign = 1
        first = True
        while True:
            ws()
            if pos >= n:
                break
            ch = s[pos]
            if ch == ")":
                if depth == 0:
                    raise UnitError("Unbalanced ')' in unit")
                break
            if ch in "*·":
                pos += 1
                sign = 1
                first = False
                continue
            if ch == "/":
                pos += 1
                sign = -1
                first = False
                continue
            if ch == "(":
                pos += 1
                inner = group(depth + 1)
                ws()
                if pos >= n or s[pos] != ")":
                    raise UnitError("Missing ')' in unit")
                pos += 1
                e = _read_exp()
                out.extend((sym, ex * e * sign) for sym, ex in inner)
                sign = 1
                first = False
                continue
            if ch.isdigit():
                m = re.match(r"\d+", s[pos:])
                if m and m.group(0) == "1" and sign == -1:     # "1/s"
                    pos += 1
                    sign = -1
                    continue
                if m and m.group(0) == "1":
                    pos += 1
                    continue
                raise UnitError(f"Unexpected number '{m.group(0) if m else ch}' in unit '{s}'")
            m2 = _ATOM.match(s, pos)
            if not m2:
                raise UnitError(f"Unexpected character '{ch}' in unit '{s}'")
            sym = m2.group(1)
            pos = m2.end()
            e = _read_exp()
            REGISTRY.resolve(sym)
            out.append((sym, e * sign))
            sign = 1
            first = False
        return out

    def _read_exp() -> Fraction:
        nonlocal pos
        m = _EXP.match(s, pos)
        if not m:
            return Fraction(1)
        pos = m.end()
        if m.group(4):
            return Fraction(int("".join(_SUPERSCRIPT[c] for c in m.group(4))))
        if m.group(3) is not None:
            return Fraction(int(m.group(3)))
        num, den = int(m.group(1)), int(m.group(2) or 1)
        if den == 0:
            raise UnitError("Zero denominator in unit exponent")
        return Fraction(num, den)

    facs = group(0)
    ws()
    if pos < n:
        raise UnitError(f"Unexpected '{s[pos:]}' in unit '{s}'")
    return Unit(facs)


def format_quantity(q: Quantity, mag_text: str, pretty: bool = True) -> str:
    u = q.unit.pretty if pretty else q.unit.text
    return f"{mag_text} {u}".strip()
