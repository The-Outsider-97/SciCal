"""Runtime settings. Every value has a safe default; environment variables and command-line flags override it."""
from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path

MIB = 1024 * 1024


def _default_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "SLAI" / "SciCal"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "slai" / "scical"


def _default_output_dir() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.exists() else Path.home()) / "SLAI SciCal"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def default_assets_dir() -> Path:
    """The SLAI-wide asset folder, ``applications/assets``: icons are served from there and never copied."""
    return Path(__file__).resolve().parents[3] / "assets" if (Path(__file__).resolve().parents[3] / "assets").is_dir() else Path(__file__).resolve().parents[2] / "assets"


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8768                                  # Documaster 8766, Reader 8767
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    slai_root: Path | None = None
    data_dir: Path = field(default_factory=_default_data_dir)
    output_dir: Path = field(default_factory=_default_output_dir)
    assets_dir: Path = field(default_factory=default_assets_dir)
    workers: int = field(default_factory=lambda: _env_int("SCICAL_WORKERS", 0))
    task_timeout_s: float = field(default_factory=lambda: float(_env_int("SCICAL_TIMEOUT_S", 30)))
    max_body_bytes: int = 8 * MIB
    max_sessions: int = 200
    max_entries: int = 2000
    max_session_bytes: int = 6 * MIB
    # SLAI agents are optional. ``auto`` uses them when they load, ``none`` never creates one, ``strict`` turns an agent that cannot be
    # created into an error. Whatever the mode, the content of a worksheet is only passed to an agent after the person allowed it for
    # that worksheet, and the Privacy agent has agreed.
    agents: str = "auto"
    agent_timeout_s: float = field(default_factory=lambda: float(_env_int("SCICAL_AGENT_TIMEOUT_S", 60)))
    open_browser: bool = True

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def prefs_path(self) -> Path:
        return self.data_dir / "prefs.json"

    @property
    def handoff_dir(self) -> Path:
        return self.data_dir.parent / "handoff"       # shared by SLAI applications: <SLAI data>/handoff

    @property
    def is_windows(self) -> bool:
        return sys.platform.startswith("win")

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.sessions_dir, self.handoff_dir):
            path.mkdir(parents=True, exist_ok=True)

    def public(self) -> dict:
        return {"output_dir": str(self.output_dir), "agents": self.agents, "task_timeout_s": self.task_timeout_s,
                "max_entries": self.max_entries, "workers": self.workers or None}
