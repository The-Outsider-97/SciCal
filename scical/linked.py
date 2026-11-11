"""Run SciCal inside the SLAI Python environment: the installed app is a launcher for the SLAI checkout it was built from.

The packaged Windows engine is a frozen Python with only SciCal's own libraries. SLAI's STEM agent, the SLDC/SGEO exports and the other
SLAI features need SLAI's own packages (NumPy, SciPy, ...), which cannot all be frozen into the app. So when the installer was built from
inside a SLAI checkout, it remembers where that checkout is (``slai_root.txt`` next to the engine). At start-up the frozen program looks
for the checkout's Python environment (``venv``), and starts SciCal there, with every feature, SLAI agents included. The person never has to choose.

There is no quiet fallback to a SLAI-less engine: when the SLAI environment cannot be used, SciCal says exactly what is missing.
``SCICAL_FROZEN_ONLY=1`` (development only) runs the frozen engine on its own.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

NOTE = "slai_root.txt"
CREATE_NO_WINDOW = 0x08000000


def _is_slai_root(path: Path) -> bool:
    return (path / "src" / "utils" / "sldc.py").is_file()


def baked_root(base: Path | None = None, env: Mapping[str, str] | None = None) -> Path | None:
    """The SLAI checkout the installer was built from (or ``SLAI_ROOT``), if it still exists."""
    env = os.environ if env is None else env
    base = base or Path(sys.executable).resolve().parent
    candidates: list[str] = []
    if env.get("SLAI_ROOT"):
        candidates.append(env["SLAI_ROOT"])
    note = base / NOTE
    try:
        if note.is_file():
            candidates.append(note.read_text(encoding="utf-8").strip())
    except OSError:
        pass
    for c in candidates:
        try:
            p = Path(c).expanduser()
            if c and _is_slai_root(p):
                return p.resolve()
        except OSError:
            continue
    return None


def venv_python(root: Path) -> Path | None:
    for rel in ("venv/Scripts/python.exe", ".venv/Scripts/python.exe", "venv/bin/python", ".venv/bin/python"):
        p = root / rel
        if p.is_file():
            return p
    return None


class LinkedError(Exception):
    """The SLAI environment cannot run SciCal; the message says what to do."""


def find_linked(base: Path | None = None, env: Mapping[str, str] | None = None) -> tuple[Path, Path, Path]:
    """``(python, slai_root, scical_folder)`` for running SciCal in the SLAI checkout's own environment. Raises ``LinkedError`` if it cannot."""
    env = os.environ if env is None else env
    root = baked_root(base, env)
    if root is None:
        raise LinkedError("SciCal could not find your SLAI folder. It was installed from a SLAI checkout that is no longer there (or has moved). "
                          "Rebuild the installer from the SLAI folder (build-windows.cmd), or set the SLAI_ROOT environment variable to the SLAI folder.")
    app = root / "applications" / "SciCal"
    if not (app / "scical" / "__main__.py").is_file():
        raise LinkedError(f"SciCal's code was not found in {app}. Rebuild the installer from the SLAI folder.")
    py = venv_python(root)
    if py is None:
        raise LinkedError(f"SLAI's Python environment (a 'venv' folder) was not found in {root}. SciCal runs inside it so the SLAI agents and exports work.")
    try:
        done = subprocess.run([str(py), "-c", "import sympy, mpmath, numpy"], cwd=str(app), capture_output=True, text=True, timeout=90,
                              creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LinkedError(f"SLAI's Python ({py}) could not be started: {exc}") from exc
    if done.returncode != 0:
        last = (done.stderr or "").strip().splitlines()[-1:] or ["unknown error"]
        raise LinkedError(f"SLAI's Python environment is missing a package SciCal needs ({last[0]}). In the SLAI folder run: venv\\Scripts\\python -m pip install -r applications\\SciCal\\requirements.txt")
    return py, root, app


def log_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if os.name == "nt":
        base = Path(env.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "SLAI" / "SciCal"
    else:
        base = Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "slai" / "scical"
    return base / "engine.log"


def run_linked(argv: Sequence[str], base: Path | None = None, env: Mapping[str, str] | None = None) -> int:
    """Start SciCal in the SLAI environment and wait for it; returns its exit code. The engine's ``SCICAL_READY`` line is passed on, so the app
    that started us sees it as before. Raises ``LinkedError`` when the environment cannot be used."""
    py, root, app = find_linked(base, env)
    args = list(argv)
    if "--worker-mode" not in args:                         # the desktop app calculates inside the engine (as StringLab does): nothing extra to start
        args += ["--worker-mode", "thread"]
    try:                                                    # what the engine prints on stderr goes to a log file the person can open
        log_file = log_path(env)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        if log_file.exists() and log_file.stat().st_size > 1_000_000:
            log_file.replace(log_file.with_suffix(".old"))
        err = open(log_file, "a", encoding="utf-8", errors="replace")
    except OSError:
        err = subprocess.DEVNULL
    child_env = dict(os.environ if env is None else env)
    child_env.update(SLAI_ROOT=str(root), PYTHONUNBUFFERED="1", PYTHONUTF8="1",
                     PYTHONPATH=os.pathsep.join(p for p in (str(app), child_env.get("PYTHONPATH", "")) if p))
    try:
        proc = subprocess.Popen([str(py), "-m", "scical", *args], cwd=str(app), env=child_env, stdout=subprocess.PIPE, stderr=err, text=True,
                                encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except OSError as exc:
        raise LinkedError(f"SLAI's Python ({py}) could not be started: {exc}") from exc
    ready = False
    assert proc.stdout is not None
    for line in proc.stdout:
        ready = ready or line.startswith("SCICAL_READY")
        sys.stdout.write(line)
        sys.stdout.flush()
    code = proc.wait()
    if not ready and code != 0:
        raise LinkedError(f"SciCal stopped while starting in the SLAI environment ({py}, exit code {code}). Details: {log_path(env)}")
    return code
