"""Calculation settings and the state a session carries (variables, user functions, the last answer)."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from ...errors import BadRequest

ANGLE_MODES = ("rad", "deg", "grad")
NOTATIONS = ("auto", "fixed", "sci", "eng")
RESULT_MODES = ("auto", "exact", "approx")


@dataclass(frozen=True)
class Settings:
    angle: str = "rad"
    complex: bool = False
    digits: int = 12                    # significant digits shown
    notation: str = "auto"
    decimals: int | None = None         # fixed number of decimals when notation == 'fixed'
    result: str = "auto"                # which form to show first
    units: bool = False                 # read "5 m" as a quantity
    thousands: bool = False             # group digits by thousands in display

    def validate(self) -> "Settings":
        if self.angle not in ANGLE_MODES:
            raise BadRequest(f"angle must be one of {ANGLE_MODES}")
        if self.notation not in NOTATIONS:
            raise BadRequest(f"notation must be one of {NOTATIONS}")
        if self.result not in RESULT_MODES:
            raise BadRequest(f"result must be one of {RESULT_MODES}")
        if not (1 <= int(self.digits) <= 100):
            raise BadRequest("digits must be between 1 and 100")
        if self.decimals is not None and not (0 <= int(self.decimals) <= 100):
            raise BadRequest("decimals must be between 0 and 100")
        return self

    @classmethod
    def from_dict(cls, d: dict | None) -> "Settings":
        d = d or {}
        known = {f for f in cls.__dataclass_fields__}
        kwargs = {k: v for k, v in d.items() if k in known}
        s = cls(**kwargs)
        return s.validate()

    def to_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}

    def with_(self, **kw: Any) -> "Settings":
        return replace(self, **kw).validate()


@dataclass
class Context:
    settings: Settings = field(default_factory=Settings)
    variables: dict[str, Any] = field(default_factory=dict)
    functions: dict[str, Any] = field(default_factory=dict)      # name -> FuncDef node
    ans: Any = None
    max_nodes: int = 5000
    max_call_depth: int = 40
