"""Error types. Every error a person can cause has a code, a plain message and (where it helps) the position in the input.

Calculation errors are results, not crashes: the server returns them as JSON and the client shows them next to the input.
Nothing in SciCal replaces an invalid result with zero or a guess.
"""
from __future__ import annotations

from typing import Any


class SciCalError(Exception):
    code = "error"
    status = 422

    def __init__(self, message: str, *, details: dict[str, Any] | None = None, span: tuple[int, int] | None = None,
                 hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.span = span
        self.hint = hint

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint:
            out["hint"] = self.hint
        if self.span is not None:
            out["span"] = [self.span[0], self.span[1]]
        if self.details:
            out["details"] = self.details
        return out


# ---- the request itself is wrong -------------------------------------------------------------------------------------
class BadRequest(SciCalError):
    code, status = "bad_request", 400


class Unauthorized(SciCalError):
    code, status = "unauthorized", 401


class NotFound(SciCalError):
    code, status = "not_found", 404


class LimitExceeded(SciCalError):
    code, status = "limit_exceeded", 413


# ---- the input is not valid mathematics --------------------------------------------------------------------------------
class ParseError(SciCalError):
    code = "parse_error"


class EvaluationError(SciCalError):
    code = "evaluation_error"


class DomainError(EvaluationError):
    """An argument outside a function's domain (ln(-1) in real mode, asin(2), a negative factorial ...)."""
    code = "domain_error"


class UndefinedError(EvaluationError):
    """An expression with no value (division by zero, 0^0, an indeterminate form)."""
    code = "undefined"


class ComplexResultError(EvaluationError):
    code = "complex_result"


class MissingVariableError(EvaluationError):
    code = "missing_variable"


class UnknownNameError(EvaluationError):
    code = "unknown_name"


class ArityError(EvaluationError):
    code = "arity"


class NotConvergedError(EvaluationError):
    """A numerical method that could not deliver a trustworthy answer."""
    code = "not_converged"


class SingularMatrixError(EvaluationError):
    code = "singular_matrix"


class DimensionMismatchError(EvaluationError):
    """Matrix or vector sizes that do not fit the operation."""
    code = "shape_mismatch"


class UnsupportedOperation(SciCalError):
    code, status = "unsupported", 422


# ---- units ------------------------------------------------------------------------------------------------------------
class UnitError(EvaluationError):
    code = "unit_error"


class DimensionError(UnitError):
    """Incompatible physical dimensions (5 kg + 2 m, converting kg into m)."""
    code = "dimension_error"


# ---- domains ------------------------------------------------------------------------------------------------------------
class ChemistryError(EvaluationError):
    code = "chemistry_error"


class FormulaSyntaxError(ChemistryError):
    code = "formula_syntax"


class BiologyError(EvaluationError):
    code = "biology_error"


# ---- running ------------------------------------------------------------------------------------------------------------
class Cancelled(SciCalError):
    code, status = "cancelled", 499


class TimedOut(SciCalError):
    code, status = "timeout", 408


class AgentUnavailable(SciCalError):
    code, status = "agent_unavailable", 503


class DependencyMissing(SciCalError):
    """Something optional that the request needs (the SLAI checkout, an agent, a module) is not available."""
    code, status = "dependency_missing", 503


class Busy(SciCalError):
    code, status = "busy", 503
