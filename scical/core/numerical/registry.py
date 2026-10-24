"""Function implementations register themselves here by canonical name (see ``expressions/functions.py`` for the catalogue)."""
from __future__ import annotations

from typing import Any, Callable

HANDLERS: dict[str, Callable[..., Any]] = {}
RAW: dict[str, bool] = {}


def handler(*names: str, raw: bool = False) -> Callable:
    """Register ``fn(ev, *evaluated_args)``; with ``raw=True`` it receives ``(ev, call_node, series)`` and evaluates its own arguments."""
    def deco(fn: Callable) -> Callable:
        for n in names:
            HANDLERS[n] = fn
            RAW[n] = raw
        return fn
    return deco


def load_all() -> None:
    from . import funcs_basic, funcs_linalg, funcs_stats, funcs_symbolic  # noqa: F401


def missing() -> list[str]:
    from ..expressions.functions import FUNCTIONS
    load_all()
    return sorted(set(FUNCTIONS) - set(HANDLERS))
