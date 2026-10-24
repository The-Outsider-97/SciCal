"""Arithmetic on values: numbers, quantities, vectors, matrices. Every rule that would otherwise produce a silent wrong answer raises."""
from __future__ import annotations

import math
from typing import Any

import sympy as sp

from ...errors import (ComplexResultError, DimensionError, DomainError, EvaluationError, LimitExceeded, SingularMatrixError,
                       UndefinedError, UnitError)
from ..units import Quantity
from ..units import quantity as Q
from .values import Equation, Vec

MAX_DIGITS = 200_000          # largest integer result we are willing to build (decimal digits)
MAX_MATRIX = 60


def is_scalar(v: Any) -> bool:
    return isinstance(v, sp.Expr) and not isinstance(v, sp.MatrixBase) or (isinstance(v, (int, float)) and not isinstance(v, bool))


def is_matrix(v: Any) -> bool:
    return isinstance(v, sp.MatrixBase)


def kind_name(v: Any) -> str:
    if isinstance(v, Quantity):
        return "a quantity with a unit"
    if isinstance(v, Vec):
        return "a vector"
    if is_matrix(v):
        return "a matrix"
    if isinstance(v, bool):
        return "a true/false value"
    if isinstance(v, Equation):
        return "an equation"
    if is_scalar(v):
        return "a number" if not getattr(v, "free_symbols", None) else "an expression"
    return "this kind of value"


def has_float(v: Any) -> bool:
    if isinstance(v, sp.Basic):
        return bool(v.atoms(sp.Float))
    if isinstance(v, Quantity):
        return has_float(v.mag)
    if isinstance(v, Vec):
        return any(has_float(x) for x in v.items)
    if is_matrix(v):
        return any(has_float(x) for x in v)
    return False


def check_value(v: Any, complex_mode: bool) -> Any:
    """Reject undefined results, and complex results when working in the reals."""
    if isinstance(v, Quantity):
        check_value(v.mag, complex_mode)
        return v
    if isinstance(v, Vec):
        for x in v.items:
            check_value(x, complex_mode)
        return v
    if is_matrix(v):
        for x in v:
            check_value(x, complex_mode)
        return v
    if isinstance(v, sp.Expr):
        if v.has(sp.zoo) or v.has(sp.nan):
            raise UndefinedError("The result is undefined", hint="Check for a division by zero or an indeterminate form such as 0/0.")
        if not complex_mode and v.is_number and (v.has(sp.I) or v.is_extended_real is False):
            raise ComplexResultError("The result is not a real number",
                                     hint="Switch to complex mode to allow complex results (for example the square root of a negative number).")
        if complex_mode and v.is_number and v.has(sp.I) and (v.is_Add or v.is_Mul or v.is_Pow):
            try:
                return sp.expand_complex(v)
            except Exception:
                return v
    return v


def plain(v: Any, what: str = "this operation") -> Any:
    """A scalar without unit; a dimensionless quantity is allowed, a quantity with a unit is not."""
    if isinstance(v, Quantity):
        if v.unit.is_empty() or (v.unit.dim.is_dimensionless() and not v.unit.has_angle):
            return v.mag * v.unit.scale
        raise UnitError(f"{what} needs a number without a unit (got {v.unit.pretty})",
                        hint="Divide by the unit first, or convert the value to a plain number.")
    if isinstance(v, bool):
        raise EvaluationError(f"{what} needs a number, not a true/false value")
    if isinstance(v, (int,)):
        return sp.Integer(v)
    if not is_scalar(v):
        raise EvaluationError(f"{what} needs a single number, not {kind_name(v)}")
    return v


def as_int(v: Any, what: str, lo: int | None = None, hi: int | None = None) -> int:
    v = plain(v, what)
    if not (isinstance(v, sp.Integer) or (getattr(v, "is_integer", False) and v.is_number)):
        raise DomainError(f"{what} must be a whole number (got {v})")
    n = int(v)
    if lo is not None and n < lo:
        raise DomainError(f"{what} must be at least {lo} (got {n})")
    if hi is not None and n > hi:
        raise LimitExceeded(f"{what} is too large (the limit is {hi})")
    return n


# ---------------------------------------------------------------------------------------------------------------------------
def _digits_of_power(base: sp.Expr, exp: sp.Expr) -> float:
    try:
        b = abs(float(sp.N(base, 15)))
        e = float(sp.N(exp, 15))
    except (TypeError, ValueError):
        return 0.0
    if b in (0.0, 1.0) or math.isinf(b) or math.isinf(e):
        return 0.0
    return abs(e) * abs(math.log10(b))


def power_scalar(base: sp.Expr, exp: sp.Expr, complex_mode: bool) -> sp.Expr:
    if base == 0 and exp == 0:
        raise UndefinedError("0^0 is undefined", hint="Different conventions give different values, so SciCal does not choose one.")
    if base == 0 and exp.is_number and exp.is_real and exp < 0:
        raise UndefinedError("Division by zero (0 to a negative power)")
    if base.is_Rational and exp.is_Rational and (exp.q == 1 or base.is_Rational):
        if _digits_of_power(base, exp) > MAX_DIGITS:
            raise LimitExceeded("The result would have more than 200,000 digits", hint="Use a smaller exponent, or work with logarithms.")
    elif base.is_number and exp.is_number and _digits_of_power(base, exp) > MAX_DIGITS:
        raise LimitExceeded("The result is too large to compute")
    if not complex_mode and base.is_number and base.is_real and base < 0 and exp.is_Rational and exp.q != 1:
        # real root convention: (-8)^(1/3) = -2 when the root index is odd
        if exp.q % 2 == 1:
            root = -((-base) ** sp.Rational(1, exp.q))
            return root ** exp.p
        raise ComplexResultError(f"An even root of a negative number is not real: ({base})^({exp})",
                                 hint="Switch to complex mode for complex results.")
    return base ** exp


def _need_equal_shape(a: Any, b: Any, verb: str) -> None:
    if isinstance(a, Vec) and isinstance(b, Vec) and len(a) != len(b):
        raise DimensionError(f"Cannot {verb} vectors of different length ({len(a)} and {len(b)})")
    if is_matrix(a) and is_matrix(b) and a.shape != b.shape:
        raise DimensionError(f"Cannot {verb} matrices of different shape ({a.rows}×{a.cols} and {b.rows}×{b.cols})")


def add(a: Any, b: Any, sign: int = 1) -> Any:
    verb = "add" if sign == 1 else "subtract"
    if isinstance(a, bool) or isinstance(b, bool):
        raise EvaluationError(f"Cannot {verb} a true/false value")
    if isinstance(a, Quantity) or isinstance(b, Quantity):
        if isinstance(a, (Vec,)) or isinstance(b, (Vec,)) or is_matrix(a) or is_matrix(b):
            raise EvaluationError(f"Cannot {verb} {kind_name(a)} and {kind_name(b)}")
        return Q.add(a, b, sign)
    if isinstance(a, Vec) and isinstance(b, Vec):
        _need_equal_shape(a, b, verb)
        return Vec(tuple(x + sign * y for x, y in zip(a.items, b.items)))
    if is_matrix(a) and is_matrix(b):
        _need_equal_shape(a, b, verb)
        return a + sign * b
    if is_scalar(a) and is_scalar(b):
        return a + sign * b
    raise EvaluationError(f"Cannot {verb} {kind_name(a)} and {kind_name(b)}", hint="Both sides must be of the same kind (two numbers, two vectors of equal length, ...).")


def mul(a: Any, b: Any) -> Any:
    if isinstance(a, bool) or isinstance(b, bool):
        raise EvaluationError("Cannot multiply a true/false value")
    scalar_like = lambda v: is_scalar(v) or isinstance(v, Quantity)           # noqa: E731
    if scalar_like(a) and scalar_like(b):
        return Q.mul(a, b)
    if isinstance(a, Vec) and scalar_like(b):
        return Vec(tuple(Q.mul(x, b) if isinstance(b, Quantity) else x * b for x in a.items))
    if isinstance(b, Vec) and scalar_like(a):
        return mul(b, a)
    if is_matrix(a) and scalar_like(b) and not isinstance(b, Quantity):
        return a * b
    if is_matrix(b) and scalar_like(a) and not isinstance(a, Quantity):
        return b * a
    if is_matrix(a) and is_matrix(b):
        if a.cols != b.rows:
            raise DimensionError(f"Cannot multiply a {a.rows}×{a.cols} matrix by a {b.rows}×{b.cols} matrix",
                                 hint="The number of columns of the left matrix must equal the number of rows of the right one.")
        return a * b
    if is_matrix(a) and isinstance(b, Vec):
        if a.cols != len(b):
            raise DimensionError(f"Cannot multiply a {a.rows}×{a.cols} matrix by a vector of length {len(b)}")
        return Vec(tuple(a * b.column()))
    if isinstance(a, Vec) and isinstance(b, Vec):
        raise EvaluationError("Two vectors cannot be multiplied with *", hint="Use dot(u, v) for the dot product or cross(u, v) for the cross product.")
    raise EvaluationError(f"Cannot multiply {kind_name(a)} by {kind_name(b)}")


def div(a: Any, b: Any) -> Any:
    if isinstance(b, (Vec,)) or is_matrix(b):
        raise EvaluationError(f"Cannot divide by {kind_name(b)}", hint="Use inv(A) * b for matrices.")
    bv = b.mag if isinstance(b, Quantity) else b
    if isinstance(bv, sp.Basic) and bv.is_zero:
        raise UndefinedError("Division by zero")
    if isinstance(a, Vec):
        return Vec(tuple(Q.div(x, b) if isinstance(b, Quantity) else x / b for x in a.items))
    if is_matrix(a):
        return a / plain(b, "Dividing a matrix")
    if (is_scalar(a) or isinstance(a, Quantity)) and (is_scalar(b) or isinstance(b, Quantity)):
        return Q.div(a, b)
    raise EvaluationError(f"Cannot divide {kind_name(a)} by {kind_name(b)}")


def neg(a: Any) -> Any:
    if isinstance(a, Quantity):
        return Q.neg(a)
    if isinstance(a, Vec):
        return Vec(tuple(-x for x in a.items))
    if is_matrix(a):
        return -a
    if isinstance(a, bool):
        raise EvaluationError("Cannot negate a true/false value")
    if is_scalar(a):
        return -a
    raise EvaluationError(f"Cannot negate {kind_name(a)}")


def power(a: Any, b: Any, complex_mode: bool) -> Any:
    if isinstance(b, Quantity):
        b = plain(b, "An exponent")
    if is_matrix(a):
        b = plain(b, "A matrix exponent")
        if a.rows != a.cols:
            raise DimensionError("Only square matrices can be raised to a power")
        if not (isinstance(b, sp.Integer)):
            raise EvaluationError("A matrix can only be raised to a whole-number power")
        n = int(b)
        if abs(n) > 10_000:
            raise LimitExceeded("The matrix exponent is too large")
        if n < 0:
            if a.det() == 0:
                raise SingularMatrixError("The matrix is singular, so it has no inverse")
        return a ** n
    if isinstance(a, Vec) or isinstance(b, Vec) or is_matrix(b):
        raise EvaluationError("Vectors cannot be used as a base or exponent here", hint="Use dot, cross or norm for vector operations.")
    if isinstance(a, Quantity):
        if not b.is_number:
            raise UnitError("A quantity with a unit can only be raised to a number")
        return Q.power(a, b)
    if isinstance(a, bool) or isinstance(b, bool):
        raise EvaluationError("Cannot use a true/false value in a power")
    return power_scalar(a, b, complex_mode)


def compare_numbers(a: Any, b: Any, digits: int = 12) -> int:
    """-1, 0 or 1 for two numbers without unknowns. Exact where SymPy can decide; otherwise 60 digits of evidence."""
    if isinstance(a, Quantity) or isinstance(b, Quantity):
        return Q.compare(a, b)
    d = a - b
    if d == 0:
        return 0
    approx = has_float(a) or has_float(b)
    if not approx:
        try:
            if d.equals(0):
                return 0
        except Exception:
            pass
        if d.is_positive:
            return 1
        if d.is_negative:
            return -1
    x = sp.N(d, 60)
    if x.has(sp.I):
        raise ComplexResultError("Complex numbers cannot be ordered")
    if approx:
        scale = max(abs(sp.N(a, 20)), abs(sp.N(b, 20)), sp.Float(1e-300))
        if abs(x) <= scale * sp.Float(10) ** (-min(digits, 15) + 1):
            return 0
        return 1 if x > 0 else -1
    if abs(x) < sp.Float(10) ** -55:
        return 0
    return 1 if x > 0 else -1
