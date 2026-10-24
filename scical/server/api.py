"""The routes. Each handler checks its input, then either runs a task in the worker pool or touches a worksheet."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from ..errors import BadRequest, NotFound
from ..services import exports
from ..services.interpret import interpret
from ..services.sessions import check_id, context_lines
from .app import SciCalApp
from .router import Request, Response, file_response, ok, route

JOB = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
SMALL = 2 * 1024 * 1024


def _job(body: dict[str, Any]) -> str | None:
    j = body.get("jobId")
    if j is None:
        return None
    if not isinstance(j, str) or not JOB.match(j):
        raise BadRequest("'jobId' must be 6-64 letters, digits, - or _")
    return j


def _settings(body: dict[str, Any]) -> dict[str, Any]:
    s = body.get("settings") or {}
    if not isinstance(s, dict):
        raise BadRequest("'settings' must be an object")
    return s


def raw(result: dict[str, Any]) -> Response:
    """Compute results are returned as they are: {"ok": true, ...} or {"ok": false, "error": {...}} (a math error is an answer, not a failure)."""
    return Response(200, json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8"))


# ------------------------------------------------------------------------------------------------------------------ meta
@route("GET", "/api/status")
def status(app: SciCalApp, req: Request) -> Response:
    return ok(app.status())


@route("GET", "/api/functions")
def functions(app: SciCalApp, req: Request) -> Response:
    from ..core.expressions import functions as F
    return ok({"functions": F.catalogue()})


@route("GET", "/api/forms")
def forms_route(app: SciCalApp, req: Request) -> Response:
    from ..domains.forms import catalogue
    return ok({"domains": catalogue()})


@route("GET", "/api/prefs")
def get_prefs(app: SciCalApp, req: Request) -> Response:
    return ok(app.prefs.data)


@route("PUT", "/api/prefs")
def put_prefs(app: SciCalApp, req: Request) -> Response:
    return ok(app.prefs.update(req.json(64 * 1024)))


# ------------------------------------------------------------------------------------------------------------------ compute
@route("POST", "/api/calc")
def calc(app: SciCalApp, req: Request) -> Response:
    b = req.json(SMALL)
    task = {"kind": "calc", "input": b.get("input"), "settings": _settings(b), "context": b.get("context"), "explain": bool(b.get("explain"))}
    return raw(app.compute(task, _job(b)))


@route("POST", "/api/domain")
def domain(app: SciCalApp, req: Request) -> Response:
    b = req.json(SMALL)
    task = {"kind": "domain", "domain": b.get("domain"), "op": b.get("op"), "params": b.get("params") or {}, "settings": _settings(b)}
    return raw(app.compute(task, _job(b)))


@route("POST", "/api/graph")
def graph(app: SciCalApp, req: Request) -> Response:
    b = req.json(SMALL)
    op = b.get("op", "render")
    if op not in ("render", "analyze"):
        raise BadRequest("'op' must be render or analyze")
    task = {"kind": "graph", "op": op, "spec": b.get("spec"), "settings": _settings(b), "context": b.get("context")}
    return raw(app.compute(task, _job(b), timeout=min(app.settings.task_timeout_s, 20)))


@route("POST", "/api/cancel")
def cancel(app: SciCalApp, req: Request) -> Response:
    j = _job(req.json(4096))
    return ok({"cancelled": bool(j and app.pool.cancel(j))})


# ------------------------------------------------------------------------------------------------------------------ worksheets
@route("GET", "/api/sessions")
def sessions_list(app: SciCalApp, req: Request) -> Response:
    return ok({"sessions": app.store.list()})


@route("POST", "/api/sessions")
def sessions_create(app: SciCalApp, req: Request) -> Response:
    b = req.json()
    if isinstance(b.get("import"), dict):
        return ok(app.store.import_doc(b["import"]))
    return ok(app.store.create(b.get("name"), str(b.get("workspace", "math")), b.get("settings") if isinstance(b.get("settings"), dict) else None))


@route("GET", "/api/sessions/{sid}")
def sessions_get(app: SciCalApp, req: Request) -> Response:
    d = app.store.get(req.params["sid"])
    return ok(d, context=context_lines(d["entries"]))


@route("PUT", "/api/sessions/{sid}")
def sessions_put(app: SciCalApp, req: Request) -> Response:
    d = app.store.save(req.params["sid"], req.json())
    return ok({"id": d["id"], "name": d["name"], "updated": d["updated"], "entries": len(d["entries"])})


@route("DELETE", "/api/sessions/{sid}")
def sessions_delete(app: SciCalApp, req: Request) -> Response:
    app.store.delete(req.params["sid"])
    return ok({"deleted": True})


@route("GET", "/api/history/search")
def history_search(app: SciCalApp, req: Request) -> Response:
    return ok({"hits": app.store.search(req.query.get("q", ""), req.int_query("limit", 50, 1, 200))})


# ------------------------------------------------------------------------------------------------------------------ export and hand-off
def _doc_for_export(app: SciCalApp, b: dict[str, Any]) -> dict[str, Any]:
    if isinstance(b.get("sessionId"), str):
        return app.store.get(check_id(b["sessionId"]))
    d = b.get("session")
    if not isinstance(d, dict) or not isinstance(d.get("entries"), list):
        raise BadRequest("Give 'sessionId' or an inline 'session'")
    from ..services.sessions import SessionStore, clean_entry
    return {"id": str(d.get("id") or "inline")[:40], "name": str(d.get("name") or "Worksheet")[:120], "entries": [clean_entry(e, i) for i, e in enumerate(d["entries"][:2000])]}


@route("POST", "/api/export")
def export(app: SciCalApp, req: Request) -> Response:
    b = req.json()
    doc = _doc_for_export(app, b)
    data, name, mime = exports.export(doc, str(b.get("format", "")), app.link)
    return file_response(data, name, mime)


@route("POST", "/api/export/table")
def export_table(app: SciCalApp, req: Request) -> Response:
    b = req.json()
    text = exports.table_csv(b.get("columns"), b.get("rows"))
    return file_response(("﻿" + text).encode("utf-8"), exports.safe_name(str(b.get("name") or "table"), "csv"), exports.MIME["csv"])


@route("POST", "/api/handoff")
def handoff(app: SciCalApp, req: Request) -> Response:
    """Write the worksheet as SLDC into the output folder and a slai-handoff/1 file into the shared hand-off folder."""
    b = req.json()
    target = str(b.get("target", "reader"))
    doc = _doc_for_export(app, b)
    data, name, _ = exports.export(doc, "sldc", app.link)
    out = app.settings.output_dir
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = out / name.replace(".sldc", f"-{stamp}.sldc")
    path.write_bytes(data)
    ho = app.link.write_handoff(app.settings.handoff_dir, target, {"id": f"scical.{doc.get('id', 'x')}", "path": str(path), "format": "sldc", "title": doc.get("name", "Worksheet"),
                                                                    "fingerprint": exports.sha256(data), "revision": None})
    apps = app.link.targets()
    note = ("Reader is not running. Start it with:  python -m slai_reader --handoff \"%s\"" % ho) if target == "reader" and not apps["reader"]["running"] else \
        ("Reader is running; it opens hand-off files with --handoff, so start a second Reader or open the document from the path above." if target == "reader" else
         "Documaster does not read hand-off files yet; open the SLDC file there from the path above.")
    return ok({"document": str(path), "handoff": str(ho), "target": target, "apps": apps, "note": note})


# ------------------------------------------------------------------------------------------------------------------ interpreter and assistant
def _allowed(app: SciCalApp, sid: Any) -> tuple[str, bool]:
    if isinstance(sid, str):
        d = app.store.get(check_id(sid))
        return d["id"], bool(d.get("agentsAllowed"))
    return "scratch", False


@route("POST", "/api/interpret")
def interpret_route(app: SciCalApp, req: Request) -> Response:
    b = req.json(64 * 1024)
    text = b.get("text")
    res = interpret(text if isinstance(text, str) else "")
    sid, allowed = _allowed(app, b.get("sessionId"))
    if allowed and len(res["proposals"]) > 1:
        r = app.assistant.rank_intent(sid, True, text, res["proposals"])
        res["proposals"] = r["ordered"]
        res["agent"] = {"note": r.get("note"), "notes": r.get("notes", [])}
    return ok(res)


@route("GET", "/api/assist/status")
def assist_status(app: SciCalApp, req: Request) -> Response:
    return ok(app.assistant.status())


@route("POST", "/api/assist/probe")
def assist_probe(app: SciCalApp, req: Request) -> Response:
    return ok(app.assistant.probe())


@route("POST", "/api/assist/consent")
def assist_consent(app: SciCalApp, req: Request) -> Response:
    b = req.json(4096)
    sid = check_id(str(b.get("sessionId", "")))
    allow = bool(b.get("allow"))
    res = app.assistant.set_consent(sid, allow)
    app.store.save(sid, {"agentsAllowed": allow})
    return ok(res)


@route("POST", "/api/assist/explain")
def assist_explain(app: SciCalApp, req: Request) -> Response:
    from ..services.sessions import clean_entry
    b = req.json(SMALL)
    entry = clean_entry(b.get("entry"), 0)
    sid, allowed = _allowed(app, b.get("sessionId"))
    return ok(app.assistant.explain(sid, allowed, entry))


@route("POST", "/api/assist/crosscheck")
def assist_crosscheck(app: SciCalApp, req: Request) -> Response:
    b = req.json(SMALL)
    values = b.get("values")
    res = app.compute({"kind": "domain", "domain": "measurement", "op": "repeated", "params": {"values": values}, "settings": {}}, None)
    if not res.get("ok"):
        return raw(res)
    ours = {"mean": res["mean"]["value"], "standardDeviation": res["standardDeviation"]["value"], "median": res["median"]["value"]}
    nums = [float(v) for v in values] if isinstance(values, list) else []
    return ok(app.assistant.crosscheck("statistics", {"values": nums}, ours))


@route("POST", "/api/assist/uncertainty-crosscheck")
def uncertainty_crosscheck(app: SciCalApp, req: Request) -> Response:
    """Consent-gated STEM calculation on a validated, independent-input budget."""
    from ..domains.measurement.uncertainty_lab import _components
    b = req.json(SMALL)
    params = b.get("params")
    if not isinstance(params, dict):
        raise BadRequest("'params' must be an uncertainty budget object")
    res = app.compute({"kind": "domain", "domain": "measurement",
                       "op": "uncertainty_budget", "params": params, "settings": {}}, None)
    if not res.get("ok"):
        return raw(res)
    if res.get("correlationsPresent"):
        raise BadRequest("Correlated budgets are not supported by this independent-input cross-check")
    parts = _components(params)
    sid, allowed = _allowed(app, b.get("sessionId"))
    normalized = [{"standard": item["standard"], "sensitivity": item["sensitivity"]} for item in parts]
    value = float(res["combinedUncertainty"]["value"])
    return ok(app.assistant.verify_uncertainty_budget(sid, allowed, normalized, value))
