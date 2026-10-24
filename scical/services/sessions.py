"""Worksheets ("sessions"): a named, saved list of entries. Stored as one JSON file each, written atomically.

A session holds what the person did, not what the server computed from it: calculator lines and their results, workspace operations
with their inputs, graph definitions and notes. Opening a session replays the state-defining lines (assignments, function definitions)
through the engine, so a variable never depends on a stale stored value.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from ..errors import BadRequest, LimitExceeded, NotFound
from .fsutil import atomic_write

SCHEMA = "scical-session/1"
ID = re.compile(r"^[0-9a-f]{16}$")
ENTRY_KINDS = ("calc", "domain", "graph", "formula", "note")
WORKSPACES = ("math", "chemistry", "biology", "measurement", "graph", "formula")
MAX_NAME = 120
MAX_INPUT = 10_000
MAX_RESULT_BYTES = 200_000


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def new_id() -> str:
    return secrets.token_hex(8)


def check_id(sid: str) -> str:
    if not isinstance(sid, str) or not ID.match(sid):
        raise NotFound("No such worksheet")
    return sid


def _atomic_write(path: Path, data: bytes) -> None:
    atomic_write(path, data)


def clean_entry(e: Any, index: int) -> dict[str, Any]:
    if not isinstance(e, dict):
        raise BadRequest(f"Entry {index + 1} must be an object")
    kind = e.get("kind")
    if kind not in ENTRY_KINDS:
        raise BadRequest(f"Entry {index + 1} has an unknown kind")
    out: dict[str, Any] = {"id": str(e.get("id") or new_id())[:32], "kind": kind, "time": str(e.get("time") or _now())[:32]}
    ws = e.get("workspace")
    if ws is not None:
        if ws not in WORKSPACES:
            raise BadRequest(f"Entry {index + 1} has an unknown workspace")
        out["workspace"] = ws
    for key in ("input", "title", "text", "domain", "op"):
        if key in e:
            if not isinstance(e[key], str) or len(e[key]) > MAX_INPUT:
                raise BadRequest(f"Entry {index + 1}: '{key}' must be text of at most {MAX_INPUT} characters")
            out[key] = e[key]
    for key in ("params", "spec", "settings", "result", "summary"):
        if key in e and e[key] is not None:
            if not isinstance(e[key], (dict, list)):
                raise BadRequest(f"Entry {index + 1}: '{key}' must be an object")
            if len(json.dumps(e[key], ensure_ascii=False)) > MAX_RESULT_BYTES:
                if key == "result":
                    continue                                   # a huge result is recomputed on demand, not stored
                raise LimitExceeded(f"Entry {index + 1}: '{key}' is too large")
            out[key] = e[key]
    if "defines" in e:
        d = e["defines"]
        if not (isinstance(d, list) and len(d) <= 8 and all(isinstance(x, str) and len(x) <= 40 for x in d)):
            raise BadRequest(f"Entry {index + 1}: 'defines' must be a short list of names")
        out["defines"] = d
    if "ok" in e:
        out["ok"] = bool(e["ok"])
    return out


class SessionStore:
    def __init__(self, directory: Path, max_sessions: int = 200, max_entries: int = 2000, max_bytes: int = 6 * 1024 * 1024) -> None:
        self.dir = directory
        self.max_sessions = max_sessions
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.lock = threading.RLock()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.recovered: list[str] = []

    def _path(self, sid: str) -> Path:
        return self.dir / f"{check_id(sid)}.json"

    # ------------------------------------------------------------------ reading
    def _read(self, path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._quarantine(path)
            return None
        if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("entries"), list):
            self._quarantine(path)
            return None
        return data

    def _quarantine(self, path: Path) -> None:
        try:
            target = path.with_name(path.name + f".corrupt-{int(time.time())}")
            os.replace(path, target)
            self.recovered.append(f"{path.name} could not be read and was set aside as {target.name}")
        except OSError:
            pass

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            items = []
            for p in self.dir.glob("*.json"):
                if not ID.match(p.stem):
                    continue
                d = self._read(p)
                if d is None:
                    continue
                items.append({"id": d["id"], "name": d.get("name", "Untitled"), "created": d.get("created"), "updated": d.get("updated"),
                              "entries": len(d["entries"]), "workspace": d.get("workspace", "math")})
            items.sort(key=lambda x: x.get("updated") or "", reverse=True)
            return items

    def get(self, sid: str) -> dict[str, Any]:
        with self.lock:
            p = self._path(sid)
            if not p.is_file():
                raise NotFound("No such worksheet")
            d = self._read(p)
            if d is None:
                raise NotFound("That worksheet could not be read and was set aside")
            return d

    # ------------------------------------------------------------------ writing
    def create(self, name: str | None = None, workspace: str = "math", settings: dict | None = None) -> dict[str, Any]:
        with self.lock:
            if len(list(self.dir.glob("*.json"))) >= self.max_sessions:
                raise LimitExceeded(f"At most {self.max_sessions} worksheets are kept. Delete some first.")
            sid = new_id()
            doc = {"schema": SCHEMA, "id": sid, "name": self._name(name) or "Untitled worksheet", "created": _now(), "updated": _now(),
                   "workspace": workspace if workspace in WORKSPACES else "math", "settings": settings or {}, "entries": [], "agentsAllowed": False}
            self._write(doc)
            return doc

    @staticmethod
    def _name(name: Any) -> str:
        if name is None:
            return ""
        if not isinstance(name, str):
            raise BadRequest("The name must be text")
        return re.sub(r"[\x00-\x1f]", " ", name).strip()[:MAX_NAME]

    def save(self, sid: str, body: dict[str, Any]) -> dict[str, Any]:
        """Replace the entries (and optionally name, settings, workspace) of a worksheet."""
        with self.lock:
            doc = self.get(sid)
            if "name" in body:
                nm = self._name(body["name"])
                if not nm:
                    raise BadRequest("The name cannot be empty")
                doc["name"] = nm
            if "workspace" in body and body["workspace"] in WORKSPACES:
                doc["workspace"] = body["workspace"]
            if "settings" in body:
                if not isinstance(body["settings"], dict):
                    raise BadRequest("'settings' must be an object")
                doc["settings"] = body["settings"]
            if "agentsAllowed" in body:
                doc["agentsAllowed"] = bool(body["agentsAllowed"])
            if "entries" in body:
                entries = body["entries"]
                if not isinstance(entries, list):
                    raise BadRequest("'entries' must be a list")
                if len(entries) > self.max_entries:
                    raise LimitExceeded(f"A worksheet holds at most {self.max_entries} entries. Start a new one or delete old entries.")
                doc["entries"] = [clean_entry(e, i) for i, e in enumerate(entries)]
            doc["updated"] = _now()
            self._write(doc)
            return doc

    def import_doc(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a new worksheet from an exported ``scical-session/1`` file (always with a fresh id)."""
        if body.get("schema") != SCHEMA:
            raise BadRequest("This is not a SciCal worksheet file (schema scical-session/1 expected)")
        doc = self.create(body.get("name") or "Imported worksheet", body.get("workspace", "math"), body.get("settings") if isinstance(body.get("settings"), dict) else None)
        return self.save(doc["id"], {"entries": body.get("entries") or []})

    def delete(self, sid: str) -> None:
        with self.lock:
            p = self._path(sid)
            if not p.is_file():
                raise NotFound("No such worksheet")
            p.unlink()

    def _write(self, doc: dict[str, Any]) -> None:
        raw = json.dumps(doc, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(raw) > self.max_bytes:
            raise LimitExceeded("This worksheet is too large to save. Remove some entries or export it first.")
        _atomic_write(self._path(doc["id"]), raw)

    # ------------------------------------------------------------------ searching
    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return []
        hits: list[dict[str, Any]] = []
        with self.lock:
            for meta in self.list():
                doc = self.get(meta["id"])
                for e in doc["entries"]:
                    hay = " ".join(str(e.get(k, "")) for k in ("input", "title", "text", "op", "domain")).lower()
                    if q in hay:
                        hits.append({"session": meta["id"], "name": meta["name"], "entry": e["id"], "kind": e["kind"], "input": e.get("input") or e.get("title") or e.get("text") or e.get("op", ""),
                                     "time": e.get("time")})
                        if len(hits) >= limit:
                            return hits
        return hits


def context_lines(entries: list[dict[str, Any]]) -> list[str]:
    """The lines that define state (assignments and function definitions), in order: what a calculation needs replayed."""
    return [e["input"] for e in entries if e.get("kind") == "calc" and e.get("defines") and isinstance(e.get("input"), str)]
