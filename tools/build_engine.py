"""Build the desktop engine: SciCal's Python service frozen into one folder, with the web client inside.

    python tools/build_engine.py            # build and place the result in src-tauri/engine
    python tools/build_engine.py --out DIR  # build somewhere else (to try it without Tauri)

Run it on the operating system you are building for (a Windows engine is built on Windows). It needs Python 3.10+ with
`pip install -r requirements.txt pyinstaller`, and the web client built (`npm run build`); this script builds the client itself when
Node.js is installed and `dist/` is missing.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*cmd: str, cwd: Path = ROOT) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "src-tauri" / "engine"), help="where the finished engine folder goes")
    args = ap.parse_args()
    out = Path(args.out).resolve()

    if not (ROOT / "dist" / "index.html").is_file():
        if shutil.which("node") is None:
            print("The web client is not built and Node.js is not installed. Run 'npm install && npm run build' first.", file=sys.stderr)
            return 2
        run("node", "tools/build-static.mjs")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is missing. Run: python -m pip install -r requirements.txt pyinstaller", file=sys.stderr)
        return 2

    work = ROOT / "build" / "engine"
    shutil.rmtree(work, ignore_errors=True)
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "scical-engine",
        "--distpath", str(work / "out"), "--workpath", str(work / "work"), "--specpath", str(work),
        "--paths", str(ROOT),
        "--collect-submodules", "scical", "--collect-data", "scical",
        "--collect-submodules", "sympy", "--collect-data", "sympy",
        "--collect-submodules", "mpmath", "--collect-data", "mpmath",
        "--hidden-import", "numpy",
        "--exclude-module", "tkinter", "--exclude-module", "matplotlib", "--exclude-module", "scipy", "--exclude-module", "pytest",
        str(ROOT / "tools" / "engine_entry.py"))
    built = work / "out" / "scical-engine"
    if not built.is_dir():
        print("PyInstaller did not produce the engine folder.", file=sys.stderr)
        return 1
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(built, out)
    shutil.copytree(ROOT / "dist", out / "client")
    print(f"\nThe engine is in {out}\nTry it:  {out / ('scical-engine.exe' if sys.platform.startswith('win') else 'scical-engine')} --no-browser --port-fallback --ready-line")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
