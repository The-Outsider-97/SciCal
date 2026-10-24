"""Value types produced by evaluation.

Scalars are SymPy expressions (exact), quantities are :class:`scical.core.units.Quantity`, truth values are ``bool``. The classes below
cover everything else a result can be.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sympy as sp


@dataclass(frozen=True)
class Vec:
    """A vector (a list of numbers). A matrix is a ``sympy.ImmutableMatrix``."""
    items: tuple

    def __len__(self) -> int:
        return len(self.items)

    def column(self) -> sp.ImmutableMatrix:
        return sp.ImmutableMatrix(list(self.items))


@dataclass(frozen=True)
class Equation:
    """An equation or inequality that still has unknowns: ``lhs op rhs``."""
    lhs: Any
    rhs: Any
    op: str = "="

    def symbols(self) -> set:
        return set(getattr(self.lhs, "free_symbols", set())) | set(getattr(self.rhs, "free_symbols", set()))

    def expr(self) -> Any:
        return self.lhs - self.rhs

    def to_sympy(self) -> Any:
        import sympy as _sp
        rel = {"=": _sp.Eq, "!=": _sp.Ne, "<": _sp.Lt, ">": _sp.Gt, "<=": _sp.Le, ">=": _sp.Ge}[self.op]
        return rel(self.lhs, self.rhs, evaluate=False)


@dataclass(frozen=True)
class SolutionSet:
    """The answer of ``solve``: a list of solutions, or a set (interval) for inequalities."""
    symbol: Any
    solutions: tuple = ()
    set: Any = None                       # a SymPy Set (intervals) when the answer is not a list
    domain: str = "real"                  # real | complex
    note: str = ""


@dataclass(frozen=True)
class Table:
    """Several labelled results (eigenvalues with multiplicity, critical points, a regression ...)."""
    headers: tuple
    rows: tuple
    title: str = ""


@dataclass(frozen=True)
class Text:
    """A text result such as a number written in another base."""
    text: str
    kind: str = "text"


@dataclass
class Approx:
    """Wrapper marking a numerically obtained scalar together with its error estimate."""
    value: Any
    error: Any = None
    method: str = ""
    extra: dict = field(default_factory=dict)


Value = Any
