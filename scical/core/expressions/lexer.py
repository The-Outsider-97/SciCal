"""Tokeniser. Turns text into tokens with source spans; understands the usual Unicode maths symbols.

Number syntax: ``12``, ``0.5``, ``.5``, ``1_000``, ``1.5e-3`` / ``1.5E3`` (scientific notation: the exponent follows the digits with no
space, so ``2e3`` is 2000 while ``2 e^3`` and ``2*e`` are 2 times Euler's number), ``0xFF``, ``0b1010``, ``0o17``. The decimal separator
is always a point; commas separate arguments.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ...errors import ParseError

MAX_LEN = 10_000

NUM, ID, OP, LP, RP, LB, RB, COMMA, SEMI, PIPE, SQRT, END = "num", "id", "op", "(", ")", "[", "]", ",", ";", "|", "sqrt", "end"


@dataclass(slots=True)
class Token:
    kind: str
    text: str
    start: int
    end: int

    def __repr__(self) -> str:
        return f"{self.kind}:{self.text}"


_DEC = re.compile(r"(?:\d[\d_]*(?:\.\d[\d_]*|\.(?!\.))?|\.\d[\d_]*)(?:[eE][+-]?\d+)?")
_HEX = re.compile(r"0[xX][0-9a-fA-F_]+")
_BIN = re.compile(r"0[bB][01_]+")
_OCT = re.compile(r"0[oO][0-7_]+")
_DIGITS = "0123456789"
_SUBS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_SUPS = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}
_MAP = {"×": "*", "·": "*", "⋅": "*", "∙": "*", "÷": "/", "∕": "/", "⁄": "/", "−": "-", "–": "-", "—": "-", "≤": "<=", "≥": ">=",
        "≠": "!=", "→": "->", "⟶": "->", "＋": "+", "：": ":"}
_TWO = {":=": ":=", "==": "=", "!=": "!=", "<=": "<=", ">=": ">=", "->": "->", "**": "^", "<>": "!="}
_ONE = set("+-*/^!%=<>:°'")
_ID_START = re.compile(r"(?![⁰¹²³⁴-⁹])[^\W\d]", re.UNICODE)
_ID_CONT = re.compile(r"(?![⁰¹²³⁴-⁹])[\w₀-₉]", re.UNICODE)


def _int_text(digits: str, base: int) -> str:
    return str(int(digits.replace("_", ""), base))


def tokenize(text: str) -> list[Token]:
    if len(text) > MAX_LEN:
        raise ParseError(f"The expression is too long ({len(text)} characters; the limit is {MAX_LEN})", span=(0, 0))
    out: list[Token] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        # ---- numbers --------------------------------------------------------------------------------------------------
        if ch in _DIGITS or (ch == "." and i + 1 < n and text[i + 1] in _DIGITS):
            for rx, base in ((_HEX, 16), (_BIN, 2), (_OCT, 8)):
                m = rx.match(text, i)
                if m and base != 10:
                    out.append(Token(NUM, _int_text(m.group(0)[2:], base), i, m.end()))
                    i = m.end()
                    break
            else:
                m = _DEC.match(text, i)
                assert m is not None
                raw = m.group(0).replace("_", "")
                if raw.endswith("."):
                    raw = raw[:-1]
                out.append(Token(NUM, raw.replace("E", "e"), i, m.end()))
                i = m.end()
            continue
        # ---- identifiers ------------------------------------------------------------------------------------------------
        if ch == "°" and i + 1 < n and text[i + 1] in "CFR" and not (i + 2 < n and _ID_CONT.match(text[i + 2])):
            out.append(Token(ID, "deg" + text[i + 1], i, i + 2))      # °C, °F, °R as unit names
            i += 2
            continue
        if ch == "Δ" and text[i + 1:i + 3] in ("°C", "°F"):
            out.append(Token(ID, "delta_deg" + text[i + 2], i, i + 3))
            i += 3
            continue
        if _ID_START.match(ch) or ch == "_":
            j = i + 1
            while j < n and _ID_CONT.match(text[j]):
                j += 1
            name = text[i:j].translate(_SUBS)
            out.append(Token(ID, name, i, j))
            i = j
            continue
        # ---- superscript digits become ^digits -------------------------------------------------------------------------
        if ch in _SUPS or (ch == "⁻" and i + 1 < n and text[i + 1] in _SUPS):
            j = i
            sign = ""
            if text[j] == "⁻":
                sign = "-"
                j += 1
            digits = ""
            while j < n and text[j] in _SUPS:
                digits += _SUPS[text[j]]
                j += 1
            out.append(Token(OP, "^", i, i))
            if sign:
                out.append(Token(OP, "-", i, i))
            out.append(Token(NUM, digits, i, j))
            i = j
            continue
        ch = _MAP.get(ch, ch)
        if ch in ("<=", ">=", "!=", "->"):
            out.append(Token(OP, ch, i, i + 1))
            i += 1
            continue
        two = text[i:i + 2]
        if two in _TWO:
            out.append(Token(OP, _TWO[two], i, i + 2))
            i += 2
            continue
        if ch == "(":
            out.append(Token(LP, "(", i, i + 1))
        elif ch == ")":
            out.append(Token(RP, ")", i, i + 1))
        elif ch == "[":
            out.append(Token(LB, "[", i, i + 1))
        elif ch == "]":
            out.append(Token(RB, "]", i, i + 1))
        elif ch == ",":
            out.append(Token(COMMA, ",", i, i + 1))
        elif ch == ";":
            out.append(Token(SEMI, ";", i, i + 1))
        elif ch == "|":
            out.append(Token(PIPE, "|", i, i + 1))
        elif ch == "√":
            out.append(Token(SQRT, "√", i, i + 1))
        elif ch == "∞":
            out.append(Token(ID, "inf", i, i + 1))
        elif ch == "'":
            raise ParseError("The prime mark ' is not an operator here", span=(i, i + 1),
                             hint="Use diff(f, x) for derivatives and transpose(A) for matrix transposes.")
        elif ch in "+-*/^!%=<>:°":
            out.append(Token(OP, ch, i, i + 1))
        elif ch in "{}":
            raise ParseError("Braces are not used; write lists and vectors in square brackets, e.g. [1, 2, 3]", span=(i, i + 1))
        else:
            raise ParseError(f"Unexpected character '{ch}'", span=(i, i + 1))
        i += 1
    out.append(Token(END, "", n, n))
    return out
