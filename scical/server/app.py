"""The application object: everything the HTTP layer needs, created once."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .. import APP_NAME, __version__
from ..integrations.assist import Assistant
from ..integrations.slai_link import SlaiLink, activate, find_slai_root
from ..services.fsutil import atomic_write_text
from ..services.sessions import SessionStore
from ..services.workers import Pool
from .config import Settings

PREF_SCHEMA: dict[str, tuple[type, Any]] = {
    "theme": (str, ("system", "light", "dark", "contrast")), "angle": (str, ("rad", "deg", "grad")), "digits": (int, (1, 100)),
    "notation": (str, ("auto", "fixed", "sci", "eng")), "result": (str, ("auto", "exact", "approx")), "thousands": (bool, None),
    "units": (bool, None), "fontScale": (float, (0.8, 1.6)), "reducedMotion": (bool, None), "workspace": (str, ("math", "chemistry", "biology", "measurement")),
    "lastSession": (str, None), "complex": (bool, None), "keypad": (str, ("basic", "scientific", "functions", "units")),
}


class Prefs:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {}
        self.recovered: str | None = None
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data = self.clean(raw, strict=False)
            except (OSError, ValueError):
                self.recovered = "The preferences file could not be read and was reset."

    @staticmethod
    def clean(raw: dict[str, Any], strict: bool = True) -> dict[str, Any]:
        from ..errors import BadRequest
        out: dict[str, Any] = {}
        for k, v in raw.items():
            spec = PREF_SCHEMA.get(k)
            if spec is None:
                if strict:
                    raise BadRequest(f"Unknown preference '{k}'")
                continue
            typ, allowed = spec
            ok = isinstance(v, bool) if typ is bool else isinstance(v, (int, float)) and not isinstance(v, bool) if typ in (int, float) else isinstance(v, str)
            if ok and typ is int:
                v = int(v)
            if ok and typ is float:
                v = float(v)
            if ok and typ is not bool and allowed is not None:
                ok = (allowed[0] <= v <= allowed[1]) if typ in (int, float) else v in allowed
            if ok and typ is str and allowed is None:
                ok = len(v) <= 64
            if not ok:
                if strict:
                    raise BadRequest(f"Preference '{k}' has an invalid value")
                continue
            out[k] = v
        return out

    def update(self, raw: dict[str, Any]) -> dict[str, Any]:
        self.data.update(self.clean(raw))
        atomic_write_text(self.path, json.dumps(self.data))
        return self.data


class SciCalApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_dirs()
        if settings.slai_root is None:
            settings.slai_root = find_slai_root(None)
        activate(settings.slai_root)
        self.started = time.time()
        self.link = SlaiLink(settings.slai_root, settings.data_dir, settings.agents, settings.agent_timeout_s)
        self.assistant = Assistant(settings.agents, self.link)
        self.store = SessionStore(settings.sessions_dir, settings.max_sessions, settings.max_entries, settings.max_session_bytes)
        self.prefs = Prefs(settings.prefs_path)
        self.pool = Pool(settings.workers or None, settings.task_timeout_s).start()
        self.startup_notes: list[str] = list(self.store.recovered)
        if self.prefs.recovered:
            self.startup_notes.append(self.prefs.recovered)

    def compute(self, task: dict[str, Any], job_id: str | None = None, timeout: float | None = None) -> dict[str, Any]:
        return self.pool.submit(task, job_id or uuid.uuid4().hex, timeout)

    def status(self) -> dict[str, Any]:
        return {"app": APP_NAME, "version": __version__, "uptimeS": round(time.time() - self.started), "platform": sys.platform, "python": sys.version.split()[0],
                "settings": self.settings.public(), "pool": self.pool.status(), "slai": self.link.status(), "dataDir": str(self.settings.data_dir),
                "startupNotes": self.startup_notes, "prefs": self.prefs.data}

    def close(self) -> None:
        self.pool.close()
        self.link.close()
