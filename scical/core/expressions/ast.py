"""The abstract syntax tree. Every node knows the span of source text it came from (used for selection and error positions).

The tree is the single representation that is evaluated, printed as text, printed as LaTeX and drawn by the web client: what you see is
what is calculated.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from fractions import Fraction
from typing import Any, Iterator, Union

Span = tuple[int, int]
NOSPAN: Span = (-1, -1)


@dataclass(eq=False)
class Node:
    kind = "node"

    def children(self) -> Iterator["Node"]:
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, Node):
                yield v
            elif isinstance(v, (list, tuple)):
                for item in v:
                    if isinstance(item, Node):
                        yield item
                    elif isinstance(item, (list, tuple)):
                        for sub in item:
                            if isinstance(sub, Node):
                                yield sub

    def walk(self) -> Iterator["Node"]:
        yield self
        for c in self.children():
            yield from c.walk()

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"t": self.kind}
        for f in fields(self):
            if f.name == "span":
                s = self.span                       # type: ignore[attr-defined]
                if s != NOSPAN:
                    out["s"] = [s[0], s[1]]
                continue
            out[f.name] = _enc(getattr(self, f.name))
        return out

    def __eq__(self, other: object) -> bool:       # structural equality, ignoring spans
        if type(self) is not type(other):
            return False
        for f in fields(self):
            if f.name == "span" or f.metadata.get("noeq"):
                continue
            if getattr(self, f.name) != getattr(other, f.name):
                return False
        return True

    __hash__ = None  # type: ignore[assignment]


def _enc(v: Any) -> Any:
    if isinstance(v, Node):
        return v.to_json()
    if isinstance(v, (list, tuple)):
        return [_enc(x) for x in v]
    if isinstance(v, Fraction):
        return str(v)
    return v


@dataclass(eq=False)
class Num(Node):
    kind = "num"
    text: str = "0"                 # the digits as written, normalised: '12', '0.5', '1.5e-3'
    span: Span = NOSPAN


@dataclass(eq=False)
class Var(Node):
    kind = "var"
    name: str = ""
    span: Span = NOSPAN


@dataclass(eq=False)
class Unary(Node):
    kind = "unary"
    op: str = "-"                   # '-' or '+'
    arg: Node = None                # type: ignore[assignment]
    span: Span = NOSPAN


@dataclass(eq=False)
class Postfix(Node):
    kind = "postfix"
    op: str = "!"                   # '!' factorial, '%' percent, '°' degrees
    arg: Node = None                # type: ignore[assignment]
    span: Span = NOSPAN


@dataclass(eq=False)
class Binary(Node):
    kind = "bin"
    op: str = "+"                   # + - * / ^ mod
    left: Node = None               # type: ignore[assignment]
    right: Node = None              # type: ignore[assignment]
    implicit: bool = field(default=False, metadata={"noeq": True})   # written as juxtaposition: 2x, 3(x+1)
    span: Span = NOSPAN


@dataclass(eq=False)
class Call(Node):
    kind = "call"
    name: str = ""
    args: list = field(default_factory=list)
    power: Node | None = None       # sin^2(x) is Call('sin', [x], power=2)
    span: Span = NOSPAN


@dataclass(eq=False)
class Vector(Node):
    kind = "vec"
    items: list = field(default_factory=list)
    span: Span = NOSPAN


@dataclass(eq=False)
class Matrix(Node):
    kind = "mat"
    rows: list = field(default_factory=list)       # list of list of Node
    span: Span = NOSPAN


@dataclass(eq=False)
class Rel(Node):
    kind = "rel"
    op: str = "="                   # = != < > <= >=
    left: Node = None               # type: ignore[assignment]
    right: Node = None              # type: ignore[assignment]
    span: Span = NOSPAN


@dataclass(eq=False)
class Logic(Node):
    kind = "logic"
    op: str = "and"                 # and or not
    args: list = field(default_factory=list)
    span: Span = NOSPAN


@dataclass(eq=False)
class Assign(Node):
    kind = "assign"
    name: str = ""
    value: Node = None              # type: ignore[assignment]
    span: Span = NOSPAN


@dataclass(eq=False)
class FuncDef(Node):
    kind = "funcdef"
    name: str = ""
    params: list = field(default_factory=list)      # list[str]
    body: Node = None               # type: ignore[assignment]
    span: Span = NOSPAN


@dataclass(eq=False)
class UnitExpr(Node):
    kind = "unit"
    factors: list = field(default_factory=list)     # list of [symbol, exponent-as-string]
    span: Span = NOSPAN


@dataclass(eq=False)
class Qty(Node):
    kind = "qty"                    # 5 m, 9.8 m/s^2
    value: Node = None              # type: ignore[assignment]
    unit: UnitExpr = None           # type: ignore[assignment]
    span: Span = NOSPAN


@dataclass(eq=False)
class Convert(Node):
    kind = "convert"                # expr -> unit
    expr: Node = None               # type: ignore[assignment]
    unit: UnitExpr = None           # type: ignore[assignment]
    span: Span = NOSPAN


AnyNode = Union[Num, Var, Unary, Postfix, Binary, Call, Vector, Matrix, Rel, Logic, Assign, FuncDef, UnitExpr, Qty, Convert]

STATEMENT_KINDS = ("assign", "funcdef")


def node_count(node: Node) -> int:
    return sum(1 for _ in node.walk())


def depth(node: Node) -> int:
    best = 0
    stack: list[tuple[Node, int]] = [(node, 1)]
    while stack:
        n, d = stack.pop()
        best = max(best, d)
        for c in n.children():
            stack.append((c, d + 1))
    return best


def free_names(node: Node) -> set[str]:
    """Variable names used in the tree (function names are not included)."""
    return {n.name for n in node.walk() if isinstance(n, Var)}
