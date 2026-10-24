"""Exports of a worksheet: SLDC (through SLAI's own writer), Markdown, plain text, JSON, CSV and the hand-off file for other SLAI apps."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
from typing import Any

from ..errors import BadRequest, DependencyMissing, SciCalError
from .sessions import SCHEMA

MIME = {"sldc": "application/x-slai-sldc+zip", "md": "text/markdown; charset=utf-8", "txt": "text/plain; charset=utf-8",
        "json": "application/json", "csv": "text/csv; charset=utf-8"}
FORMATS = tuple(MIME)


def safe_name(name: str, ext: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", name or "worksheet").strip(" ._")[:60] or "worksheet"
    return f"{base}.{ext}"


def _val_text(e: dict[str, Any]) -> str:
    r = e.get("result") or e.get("summary") or {}
    if not isinstance(r, dict):
        return ""
    if e.get("kind") != "calc" and not any(isinstance(r.get(k), str) for k in ("headline", "text")) and isinstance(e.get("summary"), dict):
        r = {**e["summary"], **({"ok": False, "error": r["error"]} if r.get("ok") is False else {})}      # the one-line summary stands in for a long result
    if e.get("kind") == "calc":
        if r.get("ok") is False:
            return "Error: " + str((r.get("error") or {}).get("message", ""))
        v = r.get("value") or {}
        return str(v.get("text", "")) if isinstance(v, dict) else ""
    if r.get("ok") is False:
        return "Error: " + str((r.get("error") or {}).get("message", ""))
    for key in ("headline", "text"):
        if isinstance(r.get(key), str):
            return r[key]
    return ""


def _val_latex(e: dict[str, Any]) -> str:
    r = e.get("result") or {}
    v = r.get("value") if isinstance(r, dict) else None
    return str(v.get("latex", "")) if isinstance(v, dict) else ""


def _label(e: dict[str, Any]) -> str:
    if e["kind"] == "calc":
        return e.get("input", "")
    if e["kind"] == "domain":
        return f"{e.get('domain', '')} · {e.get('op', '')}"
    if e["kind"] == "graph":
        layers = (e.get("spec") or {}).get("layers") or []
        return "graph: " + "; ".join(str(l.get("expr") or l.get("x") or l.get("type", "")) for l in layers[:6] if isinstance(l, dict))
    if e["kind"] == "formula":
        return f"formula · {e.get('input', '')}"
    return e.get("title") or e.get("text", "")


def to_text(doc: dict[str, Any]) -> str:
    lines = [doc.get("name", "Worksheet"), "=" * len(doc.get("name", "Worksheet")), ""]
    for i, e in enumerate(doc["entries"], 1):
        if e["kind"] == "note":
            lines += [f"[{i}] Note: {e.get('text', '')}", ""]
            continue
        lines.append(f"[{i}] {_label(e)}")
        out = _val_text(e)
        if out:
            lines.append(f"    = {out}")
        lines.append("")
    return "\n".join(lines)


def to_markdown(doc: dict[str, Any]) -> str:
    lines = [f"# {doc.get('name', 'Worksheet')}", "", f"*SciCal worksheet, exported {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}*", ""]
    for e in doc["entries"]:
        if e["kind"] == "note":
            lines += [e.get("text", ""), ""]
            continue
        lines += ["```", _label(e), "```"]
        latex = _val_latex(e)
        out = _val_text(e)
        if latex:
            lines += [f"$$ {latex} $$"]
        elif out:
            lines += [f"**{out}**"]
        lines.append("")
    return "\n".join(lines)


def to_csv(doc: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["#", "workspace", "kind", "input", "result", "exact", "approximate", "time"])
    for i, e in enumerate(doc["entries"], 1):
        r = e.get("result") or {}
        flags = r.get("flags", {}) if isinstance(r, dict) else {}
        w.writerow([i, _cell(e.get("workspace", "")), _cell(e["kind"]), _cell(_label(e)), _cell(_val_text(e)), flags.get("exact", ""), flags.get("approximate", ""), _cell(e.get("time", ""))])
    return buf.getvalue()


def table_csv(columns: list[Any], rows: list[Any]) -> str:
    if not isinstance(columns, list) or not isinstance(rows, list) or len(rows) > 200_000 or len(columns) > 200:
        raise BadRequest("A table needs a list of columns and a list of rows (at most 200,000)")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([_cell(c) for c in columns])
    for r in rows:
        if not isinstance(r, list):
            raise BadRequest("Each row must be a list")
        w.writerow([_cell(c) for c in r])
    return buf.getvalue()


def _cell(c: Any) -> str:
    s = "" if c is None else str(c)
    if s[:1] in ("=", "+", "-", "@", "\t", "\r") and not re.fullmatch(r"[-+]?\d[\d.,eE+-]*", s):
        return "'" + s                                        # a spreadsheet must not run a formula that came from a worksheet
    return s


def to_sldc(doc: dict[str, Any], sldc: Any) -> bytes:
    """Blocks for SLAI's SLDC 0.1.0 text profile, written and re-validated by ``src.utils.sldc`` itself."""
    blocks: list[dict[str, Any]] = []

    def add(kind: str, text: str, **attrs: Any) -> None:
        b: dict[str, Any] = {"id": f"b{len(blocks) + 1}", "type": kind, "text": text}
        if attrs:
            b["attributes"] = attrs
        blocks.append(b)

    add("heading", doc.get("name", "Worksheet"), level=1)
    for i, e in enumerate(doc["entries"], 1):
        if e["kind"] == "note":
            add("paragraph", e.get("text", "") or " ")
            continue
        add("code", _label(e) or " ")
        out = _val_text(e)
        if out:
            add("paragraph", "= " + out)
    sid = doc.get("id", "x")
    document = {"id": f"scical.{sid}"[:128], "title": doc.get("name", "Worksheet") or "Worksheet", "language": "en", "blocks": blocks,
                "metadata": {"generator": "SLAI SciCal", "schema": SCHEMA}, "provenance": [{"tool": "slai-scical", "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}]}
    try:
        return sldc.dumps_sldc(document)
    except Exception as exc:  # noqa: BLE001 - SLDCError subclasses ValueError
        raise SciCalError(f"SLAI's SLDC writer rejected the worksheet: {exc}") from exc


def export(doc: dict[str, Any], fmt: str, link: Any) -> tuple[bytes, str, str]:
    """Returns (bytes, filename, mime type)."""
    if fmt not in FORMATS:
        raise BadRequest(f"Unknown format '{fmt}'", hint="Formats: " + ", ".join(FORMATS))
    name = doc.get("name", "worksheet")
    if fmt == "sldc":
        data = to_sldc(doc, link.sldc())
    elif fmt == "md":
        data = to_markdown(doc).encode("utf-8")
    elif fmt == "txt":
        data = to_text(doc).encode("utf-8")
    elif fmt == "csv":
        data = ("﻿" + to_csv(doc)).encode("utf-8")
    else:
        data = json.dumps(doc, ensure_ascii=False, indent=1, allow_nan=False).encode("utf-8")
    return data, safe_name(name, fmt), MIME[fmt]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
