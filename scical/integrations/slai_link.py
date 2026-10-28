"""Connection to the SLAI checkout and to Documaster's agent gateway.

SciCal consumes SLAI through public modules only:

* ``src.utils.sldc``            the authoritative SLDC implementation (SciCal writes worksheets with ``dumps_sldc``)
* ``slai-handoff/1``            the small JSON file the SLAI apps use to pass work to each other
* ``documaster/slai``           Documaster's ``AgentGateway`` and the Privacy gate, loaded under an alias package so its ``slai``
                                package never clashes with anything of ours; nothing of Documaster's is copied or modified
* ``src.agents.agent_factory``  the real STEM agent, for the optional numerical cross-check

If the checkout is missing SciCal still calculates, graphs and exports Markdown, text, CSV and JSON; it says which features it lost.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

from ..errors import BadRequest, DependencyMissing
from ..services.fsutil import atomic_write_text

ALIAS = "documaster_slai"
SCHEMA = "slai-handoff/1"
_ROOT: Path | None = None


def looks_like_slai_root(path: Path) -> bool:
    return (path / "src" / "utils" / "sldc.py").is_file()


def find_slai_root(explicit: str | os.PathLike[str] | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("SLAI_ROOT"):
        candidates.append(Path(os.environ["SLAI_ROOT"]))
    candidates.extend(Path(__file__).resolve().parents)
    for c in candidates:
        try:
            if looks_like_slai_root(c):
                return c.resolve()
        except OSError:
            continue
    return None


def activate(root: Path | None) -> Path | None:
    """Make ``import src...`` work. The SLAI root goes last on ``sys.path`` so SciCal's own packages win."""
    global _ROOT
    if root is None:
        return None
    if str(root) not in sys.path:
        sys.path.append(str(root))
    _ROOT = root
    return root


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


class SlaiLink:
    def __init__(self, root: Path | None, data_dir: Path, agents_mode: str = "auto", agent_timeout_s: float = 60.0) -> None:
        self.root = root
        self.data_dir = data_dir
        self.agents_mode = agents_mode
        self.agent_timeout_s = agent_timeout_s
        self.documaster_ok = False
        self.documaster_reason: str | None = None
        self.services: Any = None
        self._lock = threading.Lock()
        self._loaded = False

    # ------------------------------------------------------------------ SLDC
    def sldc(self) -> ModuleType:
        if self.root is None:
            raise DependencyMissing("The SLAI checkout was not found, so SLDC export is unavailable. Start SciCal inside the SLAI folder, "
                                    "set SLAI_ROOT, or pass --slai-root. Markdown, text, CSV and JSON exports still work.")
        try:
            return importlib.import_module("src.utils.sldc")
        except ImportError as exc:
            raise DependencyMissing("The SLDC module (src/utils/sldc.py) could not be imported.", details={"import_error": str(exc)}) from exc

    def _facade(self, module: str, what: str) -> ModuleType:
        if self.root is None:
            raise DependencyMissing(f"The SLAI checkout was not found, so {what} export is unavailable. Start SciCal inside the SLAI folder, set SLAI_ROOT, or pass --slai-root.")
        try:
            return importlib.import_module(f"src.utils.{module}")
        except ImportError as exc:
            raise DependencyMissing(f"The {what} module (src/utils/{module}.py) could not be imported.", details={"import_error": str(exc)}) from exc

    def sgeo(self) -> ModuleType:
        """SLAI's SGEO facade (3D models). SciCal builds ``SGEODocument`` objects with it and saves them with its writer; it has no serializer of its own."""
        return self._facade("sgeo", "SGEO")

    def sdrw(self) -> ModuleType:
        """SLAI's SDRW facade (2D drawings), used the same way."""
        return self._facade("sdrw", "SDRW")

    def spatial_info(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, getter in (("sgeo", self.sgeo), ("sdrw", self.sdrw)):
            try:
                m = getter()
                out[key] = {"available": True, "formatVersion": getattr(m, "FORMAT_VERSION", None), "schema": getattr(m, "SCHEMA", None)}
            except DependencyMissing as exc:
                out[key] = {"available": False, "reason": exc.message}
        return out

    def sldc_info(self) -> dict[str, Any]:
        try:
            m = self.sldc()
            return {"available": True, "formatVersion": getattr(m, "FORMAT_VERSION", None), "legacyVersion": getattr(m, "LEGACY_VERSION", None)}
        except DependencyMissing as exc:
            return {"available": False, "reason": exc.message}

    # ------------------------------------------------------------------ hand-off
    def write_handoff(self, handoff_dir: Path, target: str, document: dict[str, Any], note: str | None = None) -> Path:
        if target not in ("reader", "documaster", "writer"):
            raise BadRequest("target must be reader, documaster or writer")
        handoff_dir.mkdir(parents=True, exist_ok=True)
        payload = {"schema": SCHEMA, "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z", "source": "slai-scical", "target": target,
                   "document": document, "position": None, "selection": None}
        if note:
            payload["note"] = note
        path = handoff_dir / f"scical-to-{target}-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}.json"
        atomic_write_text(path, json.dumps(payload, indent=2))
        return path

    def targets(self) -> dict[str, Any]:
        base = self.root / "applications" if self.root else None
        return {"reader": {"present": bool(base and (base / "Reader" / "slai_reader" / "__main__.py").is_file()), "running": port_open(8767)},
                "documaster": {"present": bool(base and (base / "Documaster" / "slai" / "__main__.py").is_file()), "running": port_open(8766)}}

    # ------------------------------------------------------------------ Documaster agent gateway
    def locate_documaster(self) -> Path | None:
        if self.root is None:
            return None
        pkg = self.root / "applications" / "Documaster" / "slai"
        return pkg if (pkg / "__init__.py").is_file() else None

    def load(self) -> "SlaiLink":
        with self._lock:
            if self._loaded:
                return self
            self._loaded = True
            if self.agents_mode == "none":
                self.documaster_reason = "Agents are switched off (SciCal was started with --agents none)."
                return self
            pkg = self.locate_documaster()
            if pkg is None:
                self.documaster_reason = "Documaster was not found under applications/Documaster of the SLAI checkout"
                return self
            try:
                if ALIAS not in sys.modules:
                    spec = importlib.util.spec_from_file_location(ALIAS, pkg / "__init__.py", submodule_search_locations=[str(pkg)])
                    assert spec and spec.loader
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[ALIAS] = module
                    spec.loader.exec_module(module)
                bridge = importlib.import_module(f"{ALIAS}.bridge")
                bridge.activate(self.root)
                config = importlib.import_module(f"{ALIAS}.config")
                services = importlib.import_module(f"{ALIAS}.services")
                settings = config.Settings(agents=self.agents_mode, data_dir=self.data_dir / "documaster", agent_timeout_s=self.agent_timeout_s, agent_read_default=False)
                settings.slai_root = self.root
                settings.data_dir.mkdir(parents=True, exist_ok=True)
                self.services = services.Services.create(settings)
                self.documaster_ok = True
            except Exception as exc:  # noqa: BLE001
                sys.modules.pop(ALIAS, None)
                for name in [n for n in sys.modules if n.startswith(ALIAS + ".")]:
                    sys.modules.pop(name, None)
                self.documaster_reason = f"Documaster's agent gateway could not be loaded: {type(exc).__name__}: {str(exc)[:300]}"
            return self

    def module(self, dotted: str) -> ModuleType:
        if not self.documaster_ok:
            raise DependencyMissing(self.documaster_reason or "Documaster's agent gateway is not available")
        return importlib.import_module(f"{ALIAS}.{dotted}")

    def status(self) -> dict[str, Any]:
        return {"slaiRoot": str(self.root) if self.root else None, "sldc": self.sldc_info(), "spatial": self.spatial_info(), "agentGateway": {"available": self.documaster_ok, "reason": self.documaster_reason},
                "apps": self.targets()}

    def close(self) -> None:
        if self.services is not None:
            try:
                self.services.agents.close()
            except Exception:  # noqa: BLE001
                pass
