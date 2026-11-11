"""Copy the part of SLAI that the phone apps carry: SLAI's own STEM agent and the SLDC / SGEO / SDRW export modules.

    python src-tauri/mobile/stage_slai.py DEST        # DEST gets src/, checkpointing/, logs/ (a folder that can serve as SLAI_ROOT)

What goes in was found by running the real STEM agent with only what an Android Python has (NumPy, PyYAML, colorama, psutil, mpmath) and
recording the SLAI files it loads (88 of them). It is SLAI's own source, unchanged. What is left out is what a phone cannot run or needs no
copy of: the language, quality and safety agents, models, checkpoints and anything that needs torch. Features that need those are reported
as unavailable on the phone, never imitated.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent.parent
SLAI = APP.parent.parent

FILES = ["src/__init__.py", "src/agents/__init__.py", "src/agents/base_agent.py", "src/agents/stem_agent.py", "src/agents/runtime_contracts.py"]
TREES = ["src/agents/base", "src/agents/stem", "src/agents/collaborative", "src/agents/planning", "src/utils", "checkpointing", "logs"]
KEEP = {".py", ".yaml", ".yml", ".json", ".sql"}
SKIP_DIRS = {"__pycache__", "tests", "test", "tests_py", "doc", "docs", "checkpoints", "models", "node_modules"}
MAX_BYTES = 1_000_000


def selection(root: Path) -> list[Path]:
    """Relative paths of the SLAI files to carry. Missing entries are an error: they mean this is not the SLAI the list was made for."""
    out: list[Path] = []
    for rel in FILES:
        if not (root / rel).is_file():
            raise FileNotFoundError(f"{root / rel} is missing; this does not look like the SLAI checkout this list was made for")
        out.append(Path(rel))
    for rel in TREES:
        base = root / rel
        if not base.is_dir():
            raise FileNotFoundError(f"{base} is missing; this does not look like the SLAI checkout this list was made for")
        for p in sorted(base.rglob("*")):
            parts = set(p.relative_to(base).parts[:-1])
            if p.is_file() and p.suffix in KEEP and not (parts & SKIP_DIRS) and p.stat().st_size <= MAX_BYTES:
                out.append(p.relative_to(root))
    return out


def stage(root: Path, dest: Path) -> int:
    shutil.rmtree(dest, ignore_errors=True)
    files = selection(root)
    for rel in files:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dest / rel)
    return len(files)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(f"{stage(SLAI, Path(sys.argv[1]))} SLAI files copied")
