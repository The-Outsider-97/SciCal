"""Physical dimensions as exponent vectors over the seven SI base quantities (exact rational exponents)."""
from __future__ import annotations

from fractions import Fraction
from typing import Iterable

BASE = ("L", "M", "T", "I", "Θ", "N", "J")
BASE_NAMES = {"L": "length", "M": "mass", "T": "time", "I": "electric current", "Θ": "temperature", "N": "amount of substance",
              "J": "luminous intensity"}
_ZERO = tuple(Fraction(0) for _ in BASE)


class Dim:
    """An immutable dimension. ``Dim()`` is dimensionless."""
    __slots__ = ("exps",)

    def __init__(self, exps: Iterable[Fraction | int] | None = None, **named: Fraction | int) -> None:
        if exps is not None:
            vec = tuple(Fraction(e) for e in exps)
            if len(vec) != len(BASE):
                raise ValueError("a dimension has seven exponents")
        else:
            vec = tuple(Fraction(named.get(k, 0)) for k in ("L", "M", "T", "I", "Th", "N", "J"))
        object.__setattr__(self, "exps", vec)

    def __setattr__(self, *_: object) -> None:  # immutable
        raise AttributeError("Dim is immutable")

    def __mul__(self, other: "Dim") -> "Dim":
        return Dim(a + b for a, b in zip(self.exps, other.exps))

    def __truediv__(self, other: "Dim") -> "Dim":
        return Dim(a - b for a, b in zip(self.exps, other.exps))

    def __pow__(self, n: Fraction | int) -> "Dim":
        n = Fraction(n)
        return Dim(a * n for a in self.exps)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Dim) and self.exps == other.exps

    def __hash__(self) -> int:
        return hash(self.exps)

    def is_dimensionless(self) -> bool:
        return self.exps == _ZERO

    def to_dict(self) -> dict[str, str]:
        return {sym: str(e) for sym, e in zip(BASE, self.exps) if e}

    @property
    def name(self) -> str:
        """A human name for messages: 'length', 'force', ... or the base-exponent form when it has no common name."""
        if self.exps in _NAMED:
            return _NAMED[self.exps]
        if self.is_dimensionless():
            return "dimensionless"
        parts = []
        for sym, e in zip(BASE, self.exps):
            if e:
                parts.append(f"{BASE_NAMES[sym]}" + ("" if e == 1 else f"^{e}"))
        return " · ".join(parts)

    def __repr__(self) -> str:
        return f"Dim({self.to_dict()})"


def _d(L=0, M=0, T=0, I=0, Th=0, N=0, J=0) -> tuple[Fraction, ...]:
    return tuple(Fraction(x) for x in (L, M, T, I, Th, N, J))


_NAMED: dict[tuple[Fraction, ...], str] = {
    _d(): "dimensionless", _d(L=1): "length", _d(L=2): "area", _d(L=3): "volume", _d(M=1): "mass", _d(T=1): "time",
    _d(I=1): "electric current", _d(Th=1): "temperature", _d(N=1): "amount of substance", _d(J=1): "luminous intensity",
    _d(L=1, T=-1): "speed", _d(L=1, T=-2): "acceleration", _d(L=1, M=1, T=-2): "force", _d(L=2, M=1, T=-2): "energy",
    _d(L=2, M=1, T=-3): "power", _d(L=-1, M=1, T=-2): "pressure", _d(T=-1): "frequency", _d(L=-3, M=1): "density",
    _d(L=-3, N=1): "amount concentration", _d(L=2, M=1, T=-3, I=-1): "electric potential", _d(T=1, I=1): "electric charge",
    _d(L=-2, M=-1, T=4, I=2): "capacitance", _d(L=2, M=1, T=-3, I=-2): "electrical resistance", _d(M=1, T=-1, L=1): "momentum",
    _d(M=1, T=-2): "surface tension", _d(L=2, T=-2): "specific energy", _d(L=-1, M=1, T=-1): "dynamic viscosity",
    _d(L=2, T=-1): "kinematic viscosity", _d(L=3, T=-1): "volumetric flow rate", _d(M=1, T=-1): "mass flow rate",
    _d(M=-1, N=1): "molality (per mass)", _d(L=2, M=1, T=-2, Th=-1): "heat capacity", _d(L=2, T=-2, Th=-1): "specific heat capacity",
    _d(L=2, M=1, T=-2, N=-1): "molar energy", _d(M=1, N=-1): "molar mass", _d(L=3, N=-1): "molar volume",
    _d(N=1, T=-1): "catalytic activity", _d(M=1, T=-2, I=-1): "magnetic flux density", _d(L=2, M=1, T=-2, I=-1): "magnetic flux",
    _d(L=2, M=1, T=-2, I=-2): "inductance",
}

DIMENSIONLESS = Dim()
