"""The parser: text -> AST. Recursive descent with an explicit, documented precedence (high to low):

  1. parentheses, function calls, vectors/matrices, |x|, numbers, names
  2. postfix  !  %  °
  3. exponent ^  (right associative: 2^3^2 = 2^9; the exponent may be signed: 2^-3)
  4. prefix  -  +  and the radical √   (so -2^2 = -(2^2) = -4, while (-2)^2 = 4)
  5. * / mod and implicit multiplication (2x, 3(x+1)), left to right at the same level: 1/2x is (1/2)x
  6. + -
  7. comparison  = != < > <= >=  (a < b < c means a < b and b < c)
  8. not, and, or
  9. conversion  expr -> unit   /   expr to unit
Statements: ``name := expr`` stores a value, ``f(x, y) := expr`` defines a function.

Ambiguous readings that are legal but easy to misread produce a *warning* with the reading that was chosen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Iterable

from ...errors import ParseError
from . import ast as A
from .functions import KEYWORDS, TRIG_POWERABLE, canonical, is_function
from .lexer import COMMA, END, ID, LB, LP, NUM, OP, PIPE, RB, RP, SEMI, SQRT, Token, tokenize

MAX_DEPTH = 60
RELOPS = {"=", "!=", "<", ">", "<=", ">="}


@dataclass(frozen=True)
class ParseOptions:
    units: bool = False                                # read "5 m" as a quantity
    variables: frozenset[str] = frozenset()            # names that are variables (so "m" stays a variable, "x(3)" is a product)
    functions: frozenset[str] = frozenset()            # user-defined function names
    allow_statements: bool = True


@dataclass
class ParseWarning:
    kind: str
    message: str
    span: tuple[int, int]

    def to_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "span": list(self.span)}


@dataclass
class ParseResult:
    node: A.Node
    warnings: list[ParseWarning] = field(default_factory=list)
    text: str = ""


def _is_unit_symbol(name: str) -> bool:
    from ..units.registry import REGISTRY
    return REGISTRY.is_unit(name)


class Parser:
    def __init__(self, text: str, opts: ParseOptions) -> None:
        self.text = text
        self.opts = opts
        self.toks: list[Token] = tokenize(text)
        self.i = 0
        self.depth = 0
        self.abs_depth = 0
        self.warnings: list[ParseWarning] = []

    # ------------------------------------------------------------------ helpers
    @property
    def tok(self) -> Token:
        return self.toks[self.i]

    def peek(self, k: int = 1) -> Token:
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def advance(self) -> Token:
        t = self.toks[self.i]
        if t.kind != END:
            self.i += 1
        return t

    def is_op(self, text: str, tok: Token | None = None) -> bool:
        t = tok or self.tok
        return t.kind == OP and t.text == text

    def is_kw(self, word: str, tok: Token | None = None) -> bool:
        t = tok or self.tok
        return t.kind == ID and t.text == word

    def fail(self, message: str, tok: Token | None = None, hint: str | None = None) -> ParseError:
        t = tok or self.tok
        return ParseError(message, span=(t.start, max(t.end, t.start)), hint=hint)

    def expect(self, kind: str, what: str) -> Token:
        if self.tok.kind != kind:
            got = "the end of the expression" if self.tok.kind == END else f"'{self.tok.text}'"
            raise self.fail(f"Expected {what} but found {got}")
        return self.advance()

    def enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise self.fail("The expression is nested too deeply", hint="Split it into several steps using variables.")

    def leave(self) -> None:
        self.depth -= 1

    def warn(self, kind: str, message: str, span: tuple[int, int]) -> None:
        self.warnings.append(ParseWarning(kind, message, span))

    def span_of(self, a: A.Node, b: A.Node) -> tuple[int, int]:
        return (a.span[0], b.span[1])                     # type: ignore[attr-defined]

    # ------------------------------------------------------------------ statements
    def parse(self) -> ParseResult:
        if self.tok.kind == END:
            raise ParseError("Nothing to calculate: the expression is empty", span=(0, 0))
        node = self.statement()
        if self.tok.kind != END:
            t = self.tok
            hint = None
            if t.kind == RP:
                hint = "There is a closing parenthesis without a matching opening one."
            elif t.kind == OP and t.text == "=":
                hint = "Use := to store a value in a variable."
            raise self.fail(f"Unexpected '{t.text}'", t, hint)
        return ParseResult(node, self.warnings, self.text)

    def statement(self) -> A.Node:
        t0, t1 = self.tok, self.peek()
        if self.opts.allow_statements and t0.kind == ID and self.is_op(":=", t1):
            self.advance()
            self.advance()
            value = self.conversion()
            return A.Assign(name=t0.text, value=value, span=(t0.start, value.span[1]))   # type: ignore[attr-defined]
        if self.opts.allow_statements and t0.kind == ID and t1.kind == LP:
            fd = self.try_funcdef()
            if fd is not None:
                return fd
        return self.conversion()

    def try_funcdef(self) -> A.Node | None:
        j = self.i + 2
        params: list[str] = []
        toks = self.toks
        if toks[j].kind == RP:
            j += 1
        else:
            while True:
                if toks[j].kind != ID:
                    return None
                params.append(toks[j].text)
                j += 1
                if toks[j].kind == COMMA:
                    j += 1
                    continue
                if toks[j].kind == RP:
                    j += 1
                    break
                return None
        if not (toks[j].kind == OP and toks[j].text == ":="):
            return None
        name = self.tok
        self.i = j + 1
        if len(set(params)) != len(params):
            raise self.fail("A function cannot use the same parameter name twice", name)
        body = self.conversion()
        return A.FuncDef(name=name.text, params=params, body=body, span=(name.start, body.span[1]))   # type: ignore[attr-defined]

    def conversion(self) -> A.Node:
        expr = self.logic_or()
        if self.is_op("->") or self.is_kw("to"):
            self.advance()
            unit = self.unit_expr(required=True)
            return A.Convert(expr=expr, unit=unit, span=(expr.span[0], unit.span[1]))     # type: ignore[attr-defined]
        return expr

    # ------------------------------------------------------------------ logic and comparison
    def logic_or(self) -> A.Node:
        left = self.logic_and()
        while self.is_kw("or"):
            self.advance()
            right = self.logic_and()
            left = A.Logic(op="or", args=[left, right], span=self.span_of(left, right))
        return left

    def logic_and(self) -> A.Node:
        left = self.logic_not()
        while self.is_kw("and"):
            self.advance()
            right = self.logic_not()
            left = A.Logic(op="and", args=[left, right], span=self.span_of(left, right))
        return left

    def logic_not(self) -> A.Node:
        if self.is_kw("not"):
            t = self.advance()
            self.enter()
            arg = self.logic_not()
            self.leave()
            return A.Logic(op="not", args=[arg], span=(t.start, arg.span[1]))             # type: ignore[attr-defined]
        return self.relation()

    def relation(self) -> A.Node:
        left = self.additive()
        if self.tok.kind == OP and self.tok.text in RELOPS:
            parts: list[A.Node] = []
            prev = left
            while self.tok.kind == OP and self.tok.text in RELOPS:
                op = self.advance().text
                right = self.additive()
                parts.append(A.Rel(op=op, left=prev, right=right, span=self.span_of(prev, right)))
                prev = right
            if len(parts) == 1:
                return parts[0]
            if any(p.op == "=" for p in parts):                                            # type: ignore[attr-defined]
                raise self.fail("An equation cannot be chained (a = b = c)", hint="Write separate equations.")
            return A.Logic(op="and", args=parts, span=self.span_of(parts[0], parts[-1]))
        return left

    # ------------------------------------------------------------------ arithmetic
    def additive(self) -> A.Node:
        left = self.term()
        while self.tok.kind == OP and self.tok.text in ("+", "-"):
            op = self.advance().text
            right = self.term()
            left = A.Binary(op=op, left=left, right=right, span=self.span_of(left, right))
        return left

    def starts_operand(self, t: Token) -> bool:
        if t.kind in (NUM, LP, LB, SQRT):
            return True
        if t.kind == ID:
            return t.text not in KEYWORDS
        if t.kind == PIPE:
            return self.abs_depth == 0
        return False

    def term(self) -> A.Node:
        left = self.unary()
        saw_division_at = None
        while True:
            t = self.tok
            if t.kind == OP and t.text in ("*", "/"):
                self.advance()
                right = self.unary()
                left = A.Binary(op=t.text, left=left, right=right, span=self.span_of(left, right))
                if t.text == "/":
                    saw_division_at = left
            elif t.kind == ID and t.text == "mod":
                self.advance()
                right = self.unary()
                left = A.Binary(op="mod", left=left, right=right, span=self.span_of(left, right))
            elif self.starts_operand(t):
                if t.kind == ID and self.opts.units and _is_unit_symbol(t.text) and t.text not in self.opts.variables and isinstance(left, A.Qty):
                    break                                   # handled inside the quantity
                right = self.power()
                if saw_division_at is not None and isinstance(left, A.Binary) and left.op == "/":
                    self.warn("ambiguous", "1/2x is read as (1/2)·x because implicit multiplication has the same precedence as '/'. "
                              "Write 1/(2x) to divide by the whole product.", self.span_of(left, right))
                left = A.Binary(op="*", left=left, right=right, implicit=True, span=self.span_of(left, right))
            else:
                break
        return left

    def unary(self) -> A.Node:
        t = self.tok
        if t.kind == OP and t.text in ("-", "+"):
            self.advance()
            self.enter()
            arg = self.unary()
            self.leave()
            node = A.Unary(op=t.text, arg=arg, span=(t.start, arg.span[1]))               # type: ignore[attr-defined]
            if t.text == "-" and isinstance(arg, A.Binary) and arg.op == "^" and isinstance(arg.left, A.Num):
                self.warn("note", f"-{arg.left.text}^… is read as -({arg.left.text}^…): the power is applied before the minus sign. "
                          f"Write (-{arg.left.text})^… for the power of a negative number.", node.span)
            return node
        return self.power()

    def power(self) -> A.Node:
        base = self.postfix()
        if self.is_op("^"):
            self.advance()
            self.enter()
            exp = self.power_exp()
            self.leave()
            return A.Binary(op="^", left=base, right=exp, span=self.span_of(base, exp))
        return base

    def power_exp(self) -> A.Node:
        t = self.tok
        if t.kind == OP and t.text in ("-", "+"):
            self.advance()
            self.enter()
            arg = self.power_exp()
            self.leave()
            return A.Unary(op=t.text, arg=arg, span=(t.start, arg.span[1]))              # type: ignore[attr-defined]
        return self.power()

    def postfix(self) -> A.Node:
        node = self.primary()
        while self.tok.kind == OP and self.tok.text in ("!", "%", "°"):
            t = self.advance()
            node = A.Postfix(op=t.text, arg=node, span=(node.span[0], t.end))              # type: ignore[attr-defined]
        return node

    # ------------------------------------------------------------------ primaries
    def primary(self) -> A.Node:
        t = self.tok
        if t.kind == NUM:
            self.advance()
            node: A.Node = A.Num(text=t.text, span=(t.start, t.end))
            return self.maybe_quantity(node)
        if t.kind == ID:
            return self.name_or_call()
        if t.kind == LP:
            self.advance()
            self.enter()
            inner = self.logic_or()
            self.leave()
            close = self.expect(RP, "')'")
            inner = _respan(inner, t.start, close.end)
            return self.maybe_quantity(inner)
        if t.kind == LB:
            return self.bracket()
        if t.kind == PIPE:
            self.advance()
            self.abs_depth += 1
            self.enter()
            inner = self.additive()
            self.leave()
            self.abs_depth -= 1
            close = self.expect(PIPE, "the closing '|'")
            return A.Call(name="abs", args=[inner], span=(t.start, close.end))
        if t.kind == SQRT:
            self.advance()
            self.enter()
            operand = self.postfix()
            self.leave()
            return A.Call(name="sqrt", args=[operand], span=(t.start, operand.span[1]))    # type: ignore[attr-defined]
        if t.kind == END:
            raise self.fail("The expression ends too early: something is missing after the last operator")
        if t.kind == OP and t.text in ("*", "/", "^"):
            prev = self.toks[self.i - 1] if self.i > 0 else None
            if prev is not None and prev.kind == OP:
                raise self.fail(f"'{prev.text}' and '{t.text}' cannot follow each other: a value is missing between them")
            raise self.fail(f"'{t.text}' needs a value on its left")
        if t.kind == RP:
            raise self.fail("Unmatched ')'", hint="Remove it or add the missing '('.")
        raise self.fail(f"Unexpected '{t.text}'")

    def name_or_call(self) -> A.Node:
        t = self.advance()
        name = t.text
        nxt = self.tok
        # sin^2(x)
        if name in TRIG_POWERABLE and self.is_op("^"):
            j = self.i + 1
            k = j + 1 if self.toks[j].kind == OP and self.toks[j].text == "-" else j
            if self.toks[k].kind == NUM and self.toks[k + 1].kind == LP:
                self.advance()                                  # ^
                neg = False
                if self.is_op("-"):
                    self.advance()
                    neg = True
                num = self.advance()
                pw: A.Node = A.Num(text=num.text, span=(num.start, num.end))
                if neg:
                    pw = A.Unary(op="-", arg=pw, span=(num.start - 1, num.end))
                args, end = self.arguments()
                return A.Call(name=canonical(name) or name, args=args, power=pw, span=(t.start, end))
        if nxt.kind == LP and nxt.start == t.end or nxt.kind == LP and self.call_like(name):
            if self.call_like(name):
                args, end = self.arguments()
                return A.Call(name=canonical(name) or name, args=args, span=(t.start, end))
        return A.Var(name=name, span=(t.start, t.end))

    def call_like(self, name: str) -> bool:
        if name in self.opts.functions or is_function(name):
            return name not in self.opts.variables or name in self.opts.functions or is_function(name)
        if name in self.opts.variables:
            return False
        return len(name) > 1                                  # f(x) with an unknown multi-letter name is a call (reported when evaluated)

    def arguments(self) -> tuple[list[A.Node], int]:
        self.expect(LP, "'('")
        args: list[A.Node] = []
        self.enter()
        if self.tok.kind != RP:
            while True:
                args.append(self.logic_or())
                if self.tok.kind in (COMMA, SEMI):
                    self.advance()
                    if self.tok.kind == RP:
                        raise self.fail("Expected another argument after the comma")
                    continue
                break
        self.leave()
        close = self.expect(RP, "')' to close the argument list")
        return args, close.end

    def bracket(self) -> A.Node:
        start = self.advance()
        self.enter()
        rows: list[list[A.Node]] = [[]]
        if self.tok.kind != RB:
            while True:
                rows[-1].append(self.logic_or())
                if self.tok.kind == COMMA:
                    self.advance()
                    continue
                if self.tok.kind == SEMI:
                    self.advance()
                    rows.append([])
                    continue
                break
        self.leave()
        close = self.expect(RB, "']'")
        span = (start.start, close.end)
        if len(rows) > 1:                                      # [1, 2; 3, 4]
            if any(len(r) != len(rows[0]) or not r for r in rows):
                raise ParseError("The rows of a matrix must all have the same number of entries", span=span)
            return A.Matrix(rows=rows, span=span)
        items = rows[0]
        if items and all(isinstance(x, A.Vector) for x in items):
            width = len(items[0].items)                         # type: ignore[attr-defined]
            if width == 0 or any(len(x.items) != width for x in items):                      # type: ignore[attr-defined]
                raise ParseError("The rows of a matrix must all have the same number of entries", span=span)
            return A.Matrix(rows=[list(x.items) for x in items], span=span)                   # type: ignore[attr-defined]
        return A.Vector(items=items, span=span)

    # ------------------------------------------------------------------ units
    def maybe_quantity(self, value: A.Node) -> A.Node:
        if not self.opts.units:
            return value
        t = self.tok
        if t.kind == ID and t.text not in KEYWORDS and t.text not in self.opts.variables and _is_unit_symbol(t.text):
            unit = self.unit_expr(required=False)
            return A.Qty(value=value, unit=unit, span=(value.span[0], unit.span[1]))          # type: ignore[attr-defined]
        return value

    def _unit_atom_ahead(self, tok: Token) -> bool:
        if tok.kind == ID:
            return tok.text not in KEYWORDS and tok.text not in self.opts.variables and _is_unit_symbol(tok.text)
        return tok.kind == LP

    def unit_expr(self, required: bool) -> A.UnitExpr:
        start = self.tok
        factors: list[list] = []
        sign = 1
        first = True
        # a leading "1/" is allowed:  -> 1/s
        if self.tok.kind == NUM and self.tok.text == "1" and self.is_op("/", self.peek()):
            self.advance()
            self.advance()
            sign = -1
        end = start.start
        while True:
            t = self.tok
            if t.kind == ID and t.text not in KEYWORDS and (_is_unit_symbol(t.text)) and (first or sign != 0):
                if t.text in self.opts.variables and not required and not first:
                    break
                self.advance()
                e = self.unit_exponent()
                factors.append([t.text, str(Fraction(e) * sign)])
                end = self.toks[self.i - 1].end
            elif t.kind == LP and (first or True):
                if not self._paren_is_unit():
                    break
                self.advance()
                inner = self.unit_expr(required=True)
                self.expect(RP, "')'")
                e = self.unit_exponent()
                factors.extend([s, str(Fraction(x) * Fraction(e) * sign)] for s, x in inner.factors)
                end = self.toks[self.i - 1].end
            else:
                if first:
                    raise self.fail("Expected a unit here (for example m, kg, m/s or °C)", t)
                break
            first = False
            sign = 1
            nxt = self.tok
            if nxt.kind == OP and nxt.text in ("*", "/") and self._unit_atom_ahead(self.peek()):
                sign = -1 if nxt.text == "/" else 1
                self.advance()
                continue
            if nxt.kind == ID and self._unit_atom_ahead(nxt) and nxt.text not in self.opts.variables:
                continue                                   # juxtaposition: kg m s^-2
            break
        return A.UnitExpr(factors=factors, span=(start.start, end))

    def _paren_is_unit(self) -> bool:
        nxt = self.peek()
        return nxt.kind == ID and _is_unit_symbol(nxt.text) and nxt.text not in self.opts.variables

    def unit_exponent(self) -> Fraction:
        if not self.is_op("^"):
            return Fraction(1)
        self.advance()
        paren = False
        if self.tok.kind == LP:
            paren = True
            self.advance()
        neg = False
        if self.is_op("-"):
            neg = True
            self.advance()
        elif self.is_op("+"):
            self.advance()
        t = self.expect(NUM, "a whole number exponent")
        if "." in t.text or "e" in t.text:
            raise self.fail("Unit exponents must be whole numbers or fractions such as 1/2", t)
        value = Fraction(int(t.text))
        if paren and self.is_op("/"):
            self.advance()
            d = self.expect(NUM, "a denominator")
            if int(d.text) == 0:
                raise self.fail("Zero denominator in a unit exponent", d)
            value = value / int(d.text)
        if paren:
            self.expect(RP, "')'")
        return -value if neg else value


def _respan(node: A.Node, start: int, end: int) -> A.Node:
    """Parentheses belong to the span of what they enclose (so selecting '(a+b)' selects the group)."""
    if hasattr(node, "span"):
        node.span = (start, end)                              # type: ignore[attr-defined]
    return node


def parse(text: str, options: ParseOptions | None = None) -> ParseResult:
    try:
        return Parser(text, options or ParseOptions()).parse()
    except RecursionError:
        raise ParseError("The expression is nested too deeply", span=(0, 0), hint="Split it into several steps using variables.") from None


def parse_expression(text: str, options: ParseOptions | None = None) -> A.Node:
    return parse(text, options).node
