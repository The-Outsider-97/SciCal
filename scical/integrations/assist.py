"""The optional assistant. Calculating, graphing and exporting never depend on it.

=========================  ===============================================  =================================================
feature                    SLAI agents used (via Documaster's gateway)      what you get when no agent is available
=========================  ===============================================  =================================================
Explain a result           Privacy (gate), Safety (review), Language        The worked steps SciCal computed itself
                           (plain-language restatement, checked against
                           the numbers)
Understand a sentence      Language (intent label, to order the proposals)  Rule-based proposals, in rule order
Cross-check a data set     STEM (independent statistics routines)           Nothing: SciCal says the cross-check was not run
=========================  ===============================================  =================================================

Rules, enforced here and not by the page:

* content of a worksheet is sent to an agent only if the person allowed agents **for that worksheet**; ``--agents none`` switches it all off;
* the Privacy agent decides on every use (if it is unavailable, text that looks like personal data is not sent); the Safety agent reviews
  the text before the Language agent sees it, and a "block" stops the request;
* an agent's explanation is shown only if every number in it appears in the facts SciCal gave it; otherwise it is discarded and the reason shown;
* the result always says who produced it and is labelled machine-written; a missing agent is reported, never imitated;
* an agent never computes the answer: SciCal's exact engine did that before any agent is asked.
"""
from __future__ import annotations

import math
import re
from typing import Any

from ..errors import BadRequest
from .slai_link import SlaiLink

NUMBER = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:[.,]\d+)*(?:[eE][-+]?\d+)?")
INTENTS = ["calculate", "convert units", "solve equation", "calculus", "graph a function", "chemistry", "biology", "measurement and statistics"]
INTENT_WORKSPACE = {"calculate": "math", "convert units": "math", "solve equation": "math", "calculus": "math", "graph a function": "graph", "chemistry": "chemistry",
                    "biology": "biology", "measurement and statistics": "measurement"}


def _norm_numbers(text: str) -> set[str]:
    out = set()
    for m in NUMBER.findall(text):
        t = m.replace(",", "").lstrip("+")
        try:
            f = float(t)
        except ValueError:
            continue
        out.add(f"{f:.6g}")
    return out


def facts_of(entry: dict[str, Any]) -> dict[str, Any]:
    """The plain facts about one entry that an explanation may use: input, result text, flags, step lines, warnings. Nothing else."""
    r = entry.get("result") or {}
    lines: list[str] = []
    steps = r.get("steps") or []
    for s in steps[:30]:
        if isinstance(s, dict):
            if "expr" in s:
                lines.append(f"{s['expr']} = {s.get('value', '')}")
            else:
                lines.append(f"{s.get('title', '')}: {s.get('detail', '')}".strip(": "))
    warnings = []
    for w in r.get("warnings") or []:
        warnings.append(w.get("message") if isinstance(w, dict) else str(w))
    value = ""
    if entry.get("kind") == "calc":
        v = r.get("value") or {}
        value = v.get("text", "") if isinstance(v, dict) else ""
    else:
        for k in ("headline", "text"):
            if isinstance(r.get(k), str):
                value = r[k]
    return {"input": entry.get("input") or f"{entry.get('domain', '')} {entry.get('op', '')}", "result": value, "flags": r.get("flags") or {}, "steps": lines, "warnings": warnings}


def local_explanation(entry: dict[str, Any]) -> list[dict[str, str]]:
    """The deterministic explanation: what was computed, in which form, with the engine's own steps and cautions."""
    f = facts_of(entry)
    out: list[dict[str, str]] = []
    flags = f["flags"]
    if f["input"]:
        out.append({"title": "What was asked", "detail": str(f["input"])})
    if f["result"]:
        out.append({"title": "Result", "detail": str(f["result"])})
    if flags:
        if flags.get("exact"):
            out.append({"title": "Exactness", "detail": "This is an exact result: no rounding was applied; any decimal shown is only a display of it."})
        elif flags.get("approximate"):
            out.append({"title": "Exactness", "detail": "This result is approximate (a decimal input or a numerical method was involved), so digits beyond those shown are not reliable."})
        if flags.get("symbolic"):
            out.append({"title": "Symbolic", "detail": "The result still contains variables, so it is a formula, not a number."})
    for i, s in enumerate(f["steps"], 1):
        out.append({"title": f"Step {i}", "detail": s})
    for w in f["warnings"]:
        out.append({"title": "Note", "detail": w})
    return out


class Assistant:
    def __init__(self, mode: str, link: SlaiLink) -> None:
        self.mode = mode
        self.link = link
        self._consent: Any = None

    # ------------------------------------------------------------------ state
    def usable(self) -> tuple[bool, str | None]:
        if self.mode == "none":
            return False, "Agents are switched off (SciCal was started with --agents none)."
        self.link.load()
        if not self.link.documaster_ok:
            return False, f"The agent gateway is not available: {self.link.documaster_reason}"
        return True, None

    def status(self) -> dict[str, Any]:
        ok, why = self.usable()
        roles: dict[str, Any] = {}
        if ok:
            gw = self.link.services.agents
            for role in ("privacy", "safety", "language"):
                slot = gw.slots[role]
                roles[role] = {"state": slot.state, "class": slot.cls or None, "error": slot.error, "tested": slot.test}
        return {"mode": self.mode, "gateway": ok, "reason": why, "roles": roles,
                "notUsed": {"reasoning": "answers come from the exact engine; an agent never decides a result", "knowledge": "SciCal is not a knowledge base",
                            "planning": "no multi-step plan is needed", "quality": "no extraction to review", "observability": "no telemetry is sent",
                            "handler": "errors are shown as they are"},
                "stem": "optional numerical cross-check of data sets (see /api/assist/crosscheck)"}

    def probe(self) -> dict[str, Any]:
        ok, _ = self.usable()
        if ok:
            self.link.services.agents.status(probe=True)
        return self.status()

    def _calls(self) -> Any:
        return self.link.module("analysis.agent_calls")

    def _consent_obj(self) -> Any:
        if self._consent is None:
            self._consent = self._calls().Consent(default=False)
        return self._consent

    def set_consent(self, session_id: str, allow: bool) -> dict[str, Any]:
        ok, why = self.usable()
        note = None
        if ok:
            c = self._consent_obj()
            note = c.grant(self.link.services, session_id).public() if allow else (c.revoke(self.link.services, session_id) or None)
        return {"allowed": bool(allow), "privacyAgent": note, "agentsUsable": ok, "reason": why}

    # ------------------------------------------------------------------ the gate
    def _gate(self, session_id: str, allowed: bool, text: str) -> dict[str, Any]:
        notes: list[dict[str, Any]] = []
        ok, why = self.usable()
        if not ok:
            return {"forward": False, "reason": why, "notes": notes}
        if not allowed:
            return {"forward": False, "reason": "Agents are not allowed to read this worksheet. Turn on 'Let SLAI agents read this worksheet' to use them.", "notes": notes}
        calls = self._calls()
        consent = self._consent_obj()
        if not consent.is_explicit(session_id):
            consent.grant(self.link.services, session_id)
        pii = self.link.module("analysis.pii").scan_text(text[:20000])
        gate = calls.privacy_gate(self.link.services, consent, session_id, text, len(pii))
        if gate.get("note") is not None:
            notes.append(gate["note"].public())
        if not gate["forward"]:
            return {"forward": False, "reason": gate["reason"], "notes": notes}
        safety = calls.safety_review(self.link.services, text)
        notes.append(safety.public())
        if calls.safety_blocks(safety):
            return {"forward": False, "reason": "The Safety agent flagged this text, so it was not sent to the language agent.", "notes": notes}
        return {"forward": True, "reason": None, "notes": notes}

    # ------------------------------------------------------------------ explain
    def explain(self, session_id: str, allowed: bool, entry: dict[str, Any]) -> dict[str, Any]:
        local = local_explanation(entry)
        facts = facts_of(entry)
        result: dict[str, Any] = {"feature": "explain", "local": local, "label": "Worked out by SciCal's own engine.", "agent": None, "notes": []}
        source = "\n".join(f"{x['title']}: {x['detail']}" for x in local)
        gate = self._gate(session_id, allowed, source)
        result["notes"] = gate["notes"]
        if not gate["forward"]:
            result["agentSkipped"] = gate["reason"]
            return result
        prompt = ("Explain this calculation to a student in two or three short sentences. Use only the facts below and do not add any other numbers.\n\n" + source)[:3000]
        note = self._run_language(prompt)
        result["notes"] = gate["notes"] + [note.public()]
        if note.status != "used":
            result["agentSkipped"] = note.reason
            return result
        text = note.output if isinstance(note.output, str) else (note.output or {}).get("text") if isinstance(note.output, dict) else None
        if not isinstance(text, str) or len(text.split()) < 4:
            result["agentSkipped"] = "The language agent returned no usable explanation."
            return result
        allowed_numbers = _norm_numbers(source)
        extra = sorted(n for n in _norm_numbers(text) if n not in allowed_numbers and n not in {"1", "2", "3", "10"})
        if extra:
            result["agentSkipped"] = ("The language agent's explanation was discarded because it contains numbers that are not in the calculation: "
                                      + ", ".join(extra[:6]) + ".")
            return result
        result["agent"] = {"text": text.strip(), "label": f"Machine-written by the SLAI language agent ({note.agent}). Every number in it appears in the calculation above.",
                           "agentName": note.agent}
        return result

    def _run_language(self, prompt: str) -> Any:
        calls = self._calls()
        return calls._run(self.link.services, "language", lambda a: a.generate_text(prompt, max_length=160), 60)

    # ------------------------------------------------------------------ intent
    def rank_intent(self, session_id: str, allowed: bool, query: str, proposals: list[dict[str, Any]]) -> dict[str, Any]:
        if len(proposals) < 2:
            return {"ordered": proposals, "note": None}
        gate = self._gate(session_id, allowed, query)
        if not gate["forward"]:
            return {"ordered": proposals, "note": gate["reason"], "notes": gate["notes"]}
        note = self._calls().classify_intent(self.link.services, query, INTENTS)
        if note.status != "used" or not isinstance(note.output, dict):
            return {"ordered": proposals, "note": note.reason, "notes": gate["notes"] + [note.public()]}
        ws = INTENT_WORKSPACE.get(note.output.get("label", ""))
        ordered = sorted(proposals, key=lambda p: 0 if p.get("workspace") == ws else 1)
        return {"ordered": ordered, "note": f"Ordered by the SLAI language agent ({note.agent}); it only chooses the order, SciCal's rules wrote each proposal.",
                "notes": gate["notes"] + [note.public()]}

    # ------------------------------------------------------------------ STEM cross-check
    def crosscheck(self, kind: str, params: dict[str, Any], ours: dict[str, float]) -> dict[str, Any]:
        """Ask the SLAI STEM agent for the same statistics and compare. ``ours`` maps statistic -> the value SciCal computed."""
        if kind != "statistics":
            raise BadRequest("Only data-set statistics can be cross-checked")
        ok, why = self.usable()
        if not ok:
            return {"ran": False, "reason": why}
        values = params.get("values")
        if not (isinstance(values, list) and 2 <= len(values) <= 5000 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)):
            raise BadRequest("The cross-check needs 2 to 5000 finite numbers")
        gw = self.link.services.agents
        try:
            gw._init_factory()
            if gw.factory is None:
                return {"ran": False, "reason": gw.fatal or "AgentFactory is not available"}
            agent = getattr(self, "_stem", None) or gw.factory.create("stem", shared_memory=gw.shared_memory)
            self._stem = agent
        except Exception as exc:  # noqa: BLE001
            return {"ran": False, "reason": f"The STEM agent could not be created: {type(exc).__name__}: {str(exc)[:240]}"}
        ops = {"mean": ("mean", {}), "standardDeviation": ("standard_deviation", {"ddof": 1}), "median": ("median", {})}
        rows = []
        for name, (op, kw) in ops.items():
            if name not in ours:
                continue
            try:
                resp = agent.perform_task({"domain": "statistics", "operation": op, "args": [list(values)], "kwargs": kw})
            except Exception as exc:  # noqa: BLE001
                rows.append({"statistic": name, "status": "failed", "reason": f"{type(exc).__name__}: {str(exc)[:160]}"})
                continue
            res = resp.get("result") if isinstance(resp, dict) else None
            val = float(res) if isinstance(res, (int, float)) and not isinstance(res, bool) else None
            if val is None:
                rows.append({"statistic": name, "status": "unrecognised", "reason": "The STEM agent answered in a form SciCal does not read.", "raw": str(res)[:120]})
                continue
            diff = abs(val - ours[name])
            rel = diff / max(abs(ours[name]), 1e-300)
            rows.append({"statistic": name, "scical": ours[name], "stemAgent": val, "agree": bool(rel < 1e-9 or diff < 1e-12), "relativeDifference": rel})
        return {"ran": True, "rows": rows, "label": "Independent numerical routines of the SLAI STEM agent; it only checks, SciCal's value is the one shown."}
