"""The bridge to SLAI's STEM agent: SLAI's deterministic scientific-computing authority.

SciCal's own engine answers every question first. The STEM agent is used in two ways, both optional and both labelled as the agent's work:

* **STEM check** – an independent second computation of a result SciCal already produced (``stem_checks``). SciCal's value stays the one shown;
  the check says whether the agent agrees, to what tolerance, and by which STEM operation.
* **STEM Lab** – operations only the agent provides (``stem_lab``): differential equations, Monte-Carlo uncertainty, numerical-method comparison,
  conditioning, interpolation, dimensional analysis, bootstrap.

The agent is deterministic and runs in this process: nothing leaves the computer, no language model is involved, so unlike the agents that read
text (explain, intent) it needs no per-worksheet consent. ``--agents none`` switches it off together with the others.

This module only knows how to *reach* the agent and how to talk to it:

* ``StemBridge.agent()``  creates the agent once, through SLAI's AgentFactory (via Documaster's gateway, like every other agent SciCal uses);
* ``StemBridge.call()``   sends one structured request (``perform_task``) and returns plain JSON-able Python, never a STEM object;
* ``plain()``             turns what STEM returns (``Quantity``, ``NumericResult``, ``SolverResult``, NumPy values, fractions) into JSON values.

A missing agent is reported with its reason, never imitated.
"""
from __future__ import annotations

import copy
import dataclasses
import importlib
import math
import os
import sys
import threading
import time
from collections.abc import Mapping
from fractions import Fraction
from typing import Any, Callable

from ..errors import SciCalError
from .slai_link import SlaiLink


class StemUnavailable(SciCalError):
    code = "stem_unavailable"
    status = 503


class StemFailed(SciCalError):
    """The agent was reached but could not do this (an invalid argument, a method that did not converge, an unknown unit)."""
    code = "stem_failed"
    status = 422


def plain(value: Any, _depth: int = 0) -> Any:
    """Convert a STEM result to JSON-safe Python. Unknown objects become text, never a guess; non-finite numbers become ``None``."""
    if _depth > 12:
        return str(value)
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, complex):
        return {"re": plain(value.real, _depth + 1), "im": plain(value.imag, _depth + 1)}
    if hasattr(value, "item") and callable(value.item) and type(value).__module__.startswith("numpy"):
        try:
            return plain(value.item(), _depth + 1) if getattr(value, "ndim", 0) == 0 else plain(value.tolist(), _depth + 1)
        except Exception:                                                              # noqa: BLE001
            return str(value)
    if isinstance(value, Mapping):
        return {str(k): plain(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset, range)):
        return [plain(v, _depth + 1) for v in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return plain(to_dict(), _depth + 1)
        except Exception:                                                              # noqa: BLE001
            pass
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return plain({f.name: getattr(value, f.name) for f in dataclasses.fields(value)}, _depth + 1)
    if hasattr(value, "value") and not callable(value.value):                            # Enum members
        return plain(value.value, _depth + 1)
    return str(value)


def _find_cause(exc: BaseException | None, kind: type) -> Any:
    seen = 0
    while exc is not None and seen < 8:
        if isinstance(exc, kind):
            return exc
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return None


class StemBridge:
    def __init__(self, link: SlaiLink | None, mode: str = "auto", *, provider: Callable[[], Any] | None = None) -> None:
        """``provider`` returns a ready STEM agent (used by tests and tools); without it the agent is made through SLAI's AgentFactory."""
        self.link = link
        self.mode = mode
        self._provider = provider
        self._agent: Any = None
        self._reason: str | None = None
        self._tried = False
        self._lock = threading.Lock()
        self._call_lock = threading.RLock()                 # the agent is used by one request at a time
        self._ops: dict[str, list[str]] | None = None
        self._deadline: float | None = None

    # ------------------------------------------------------------------ reaching the agent
    def agent(self) -> tuple[Any, str | None]:
        """``(agent, None)`` or ``(None, reason)``. The first attempt is remembered; ``reset()`` allows another."""
        with self._lock:
            if self._agent is not None:
                return self._agent, None
            if self.mode == "none":
                return None, "Agents are switched off (SciCal was started with --agents none)."
            if self._tried:
                return None, self._reason
            self._tried = True
            try:
                hook = os.environ.get("SCICAL_STEM_PROVIDER")                                    # development hook: "package.module:function" returning an agent
                if self._provider is not None:
                    self._agent = self._provider()
                elif hook:
                    mod, _, fn = hook.partition(":")
                    self._agent = getattr(importlib.import_module(mod), fn)()
                else:
                    self._agent = self._create_through_slai()
            except Exception as exc:                                                    # noqa: BLE001
                self._agent = None
                self._reason = self._explain_failure(exc)
                return None, self._reason
            if self._agent is None:
                self._reason = self._reason or "The STEM agent could not be created."
                return None, self._reason
            self._reason = None
            return self._agent, None

    def _create_through_slai(self) -> Any:
        link = self.link
        if link is None:
            raise StemUnavailable("SciCal is not connected to a SLAI checkout.")
        link.load()
        if not link.documaster_ok:
            raise StemUnavailable(f"The agent gateway is not available: {link.documaster_reason}")
        gw = link.services.agents
        gw._init_factory()
        if gw.factory is None:
            raise StemUnavailable(gw.fatal or "SLAI's AgentFactory is not available.")
        return gw.factory.create("stem", shared_memory=gw.shared_memory)

    @staticmethod
    def _explain_failure(exc: Exception) -> str:
        text = f"{type(exc).__name__}: {str(exc)[:240]}"
        if isinstance(exc, StemUnavailable):
            return exc.message
        hint = ""
        low = text.lower()
        if "scipy" in low or "numpy" in low:
            hint = " The STEM agent needs NumPy and SciPy in the Python environment that runs SciCal (pip install scipy)."
        elif "colorama" in low:
            hint = " Update colorama in that environment (pip install -U colorama)."
        return f"The STEM agent could not be created: {text}.{hint}"

    def reset(self) -> None:
        with self._lock:
            self._agent = None
            self._reason = None
            self._tried = False
            self._ops = None

    # ------------------------------------------------------------------ what it can do
    def operations(self) -> dict[str, list[str]]:
        agent, why = self.agent()
        if agent is None:
            raise StemUnavailable(why or "The STEM agent is not available.")
        if self._ops is None:
            raw = agent.available_operations()
            self._ops = {str(d): [str(o) for o in ops] for d, ops in dict(raw).items()}
        return self._ops

    def status(self) -> dict[str, Any]:
        agent, why = self.agent()
        if agent is None:
            return {"available": False, "reason": why, "mode": self.mode, "domains": {}, "operationCount": 0}
        ops = self.operations()
        module = sys.modules.get(type(agent).__module__)
        return {"available": True, "reason": None, "mode": self.mode, "domains": ops, "operationCount": sum(len(v) for v in ops.values()),
                "version": getattr(module, "__version__", None)}

    def supports(self, domain: str, operation: str) -> bool:
        try:
            return operation in self.operations().get(domain, [])
        except StemUnavailable:
            return False

    def scoped(self, seconds: float) -> "StemBridge":
        """A view of this bridge, sharing its agent, whose requests stop (StemFailed) once ``seconds`` have passed."""
        self.agent()
        view = copy.copy(self)
        view._deadline = time.monotonic() + seconds
        return view

    # ------------------------------------------------------------------ talking to it
    def call_raw(self, domain: str, operation: str, *args: Any, **kwargs: Any) -> Any:
        """One structured request; returns the agent's own result object (callers use ``plain`` on it). Raises StemUnavailable or StemFailed."""
        agent, why = self.agent()
        if agent is None:
            raise StemUnavailable(why or "The STEM agent is not available.")
        seed = kwargs.pop("_seed", None)
        task: dict[str, Any] = {"domain": domain, "operation": operation, "args": list(args), "kwargs": kwargs, "cache": False, "publish": False}
        if seed is not None:
            task["seed"] = int(seed)
        if self._deadline is not None and time.monotonic() > self._deadline:
            raise StemFailed("The STEM request stopped: the time limit for this operation has passed.")
        try:
            with self._call_lock:
                envelope = agent.perform_task(task)
        except StemFailed:
            raise
        except Exception as exc:                                                         # noqa: BLE001
            inner = _find_cause(exc, StemFailed)                                         # a limit raised inside a callback the agent was running
            if inner is not None:
                raise inner from None
            message = getattr(exc, "message", None) or str(exc)
            raise StemFailed(f"STEM {domain}.{operation}: {message}"[:400], details={"domain": domain, "operation": operation, "type": type(exc).__name__}) from exc
        if not isinstance(envelope, Mapping) or "result" not in envelope:
            raise StemFailed(f"STEM {domain}.{operation} returned an answer SciCal does not read.")
        return envelope["result"]

    def call(self, domain: str, operation: str, *args: Any, **kwargs: Any) -> Any:
        return plain(self.call_raw(domain, operation, *args, **kwargs))

    def number(self, domain: str, operation: str, *args: Any, **kwargs: Any) -> float:
        """A request whose answer is one finite real number (also accepts a ``Quantity``/``NumericResult`` carrying one)."""
        raw = self.call_raw(domain, operation, *args, **kwargs)
        value = plain(raw)
        if isinstance(value, Mapping):
            value = value.get("magnitude", value.get("value"))
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise StemFailed(f"STEM {domain}.{operation} did not return a finite number.")
        return float(value)

    def timed(self, fn: Callable[[], Any]) -> tuple[Any, float]:
        t0 = time.perf_counter()
        out = fn()
        return out, (time.perf_counter() - t0) * 1000.0
