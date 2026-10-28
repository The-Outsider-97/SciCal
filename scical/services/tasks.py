"""The work itself, as plain functions of a JSON-like task. They run inside the worker processes (see ``workers``), so one
runaway calculation can be stopped without taking the server with it. Nothing in a task is ever evaluated as Python."""
from __future__ import annotations

import math
from typing import Any

from ..errors import BadRequest, NotFound, SciCalError

MAX_REPLAY = 400
KINDS = ("calc", "domain", "graph", "ping")


def _jsonable(x: Any) -> Any:
    """Make a result safe for strict JSON: no NaN or infinity, no non-string keys, no exotic types."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if x is None or isinstance(x, (bool, int, str)):
        return x
    return str(x)


def _domains() -> dict[str, dict]:
    from ..domains.biology import OPS as bio
    from ..domains.constants import OPS as constants
    from ..domains.chemistry import OPS as chem
    from ..domains.formulas import OPS as formulas
    from ..domains.finance import OPS as finance
    from ..domains.measurement import OPS as meas
    return {"chemistry": chem, "biology": bio, "measurement": meas, "formulas": formulas, "finance": finance, "constants": constants}


def make_context(settings: Any, replay: Any) -> Any:
    """A fresh calculation context that has the person's assignments and function definitions applied again, in order."""
    from ..core.numerical.context import Context
    from ..core.numerical.engine import calculate
    ctx = Context(settings=settings)
    if replay in (None, []):
        return ctx
    if not isinstance(replay, list) or len(replay) > MAX_REPLAY or not all(isinstance(x, str) for x in replay):
        raise BadRequest("'context' must be a list of at most %d input lines" % MAX_REPLAY)
    for line in replay:
        calculate(line, ctx)                     # a line that now fails is skipped; it simply defines nothing
    return ctx


def run(task: dict[str, Any]) -> dict[str, Any]:
    from ..core.numerical.context import Settings
    kind = task.get("kind")
    if kind == "ping":
        return {"ok": True, "pong": True}
    if kind not in KINDS:
        raise BadRequest("Unknown task")
    settings = Settings.from_dict(task.get("settings")).validate()
    try:
        if kind == "calc":
            from ..core.numerical.engine import calculate
            text = task.get("input")
            if not isinstance(text, str):
                raise BadRequest("'input' must be text")
            ctx = make_context(settings, task.get("context"))
            result = calculate(text, ctx, explain=bool(task.get("explain")))
        elif kind == "domain":
            table = _domains().get(str(task.get("domain")))
            if table is None:
                raise NotFound(f"Unknown workspace '{task.get('domain')}'")
            fn = table.get(str(task.get("op")))
            if fn is None:
                raise NotFound(f"Unknown operation '{task.get('op')}'", hint="Available: " + ", ".join(sorted(table)))
            params = task.get("params") or {}
            if not isinstance(params, dict):
                raise BadRequest("'params' must be an object")
            result = fn(params, settings)
        else:                                                   # graph
            from ..core.graphing import plot, space
            spec = task.get("spec")
            if not isinstance(spec, dict):
                raise BadRequest("'spec' must be an object")
            ctx = make_context(settings, task.get("context"))
            op = task.get("op")
            if op == "analyze":
                result = plot.analyze(ctx, spec)
            elif op == "render3d":
                result = space.render(ctx, spec)
            elif op == "sample3d":                              # full-precision geometry for the SGEO/SDRW exporters (internal, not on /api/graph)
                result = space.sample_export(ctx, spec)
            else:
                result = plot.render(ctx, spec)
            if isinstance(result, dict) and "ok" not in result:
                result = {"ok": True, **result}
    except SciCalError as exc:
        return {"ok": False, "error": exc.to_dict()}
    except RecursionError:
        return {"ok": False, "error": {"code": "limit_exceeded", "message": "The calculation is nested too deeply"}}
    except MemoryError:
        return {"ok": False, "error": {"code": "limit_exceeded", "message": "The calculation needs too much memory"}}
    return _jsonable(result)
