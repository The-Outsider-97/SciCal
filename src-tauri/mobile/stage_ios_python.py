"""Collect everything the iOS app bundles besides the Rust code: SciCal's package, its Python dependencies built for iOS, and the web client.

    python3 src-tauri/mobile/stage_ios_python.py --sdk iphoneos          # a real device
    python3 src-tauri/mobile/stage_ios_python.py --sdk iphonesimulator   # the simulator

The result is src-tauri/gen/apple/engine-resources/ with three folders (app, app_packages, scical_client). Add each to the Xcode app target
as a *folder reference* (blue folder), as described in docs/MOBILE_AND_DESKTOP.md. Needs pip 24+ and the network (PyPI and the BeeWare
wheel index for NumPy). Run it with the same Python minor version as the embedded one (3.13).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent.parent
OUT = HERE.parent / "gen" / "apple" / "engine-resources"
INDEX = "https://pypi.anaconda.org/beeware/simple"          # iOS wheels for NumPy and friends
TAGS = {"iphoneos": ["ios_13_0_arm64_iphoneos"], "iphonesimulator": ["ios_13_0_arm64_iphonesimulator", "ios_13_0_x86_64_iphonesimulator"]}
PURE = ["sympy>=1.12", "mpmath>=1.3"]                       # pure Python: the same files work everywhere
NATIVE = ["numpy"]                                          # needs a build made for iOS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdk", choices=sorted(TAGS), required=True)
    args = ap.parse_args()
    if not (APP / "dist" / "index.html").is_file():
        print("Build the web client first: npm run build", file=sys.stderr)
        return 2
    shutil.rmtree(OUT, ignore_errors=True)
    (OUT / "app").mkdir(parents=True)
    shutil.copytree(APP / "scical", OUT / "app" / "scical", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(APP / "dist", OUT / "scical_client")
    if (APP.parent / "assets").is_dir():                 # the SLAI-wide tab icons
        shutil.copytree(APP.parent / "assets", OUT / "scical_client" / "assets")
    else:
        print("WARNING: applications/assets not found; the tab icons will be missing.", file=sys.stderr)
    pk = OUT / "app_packages"
    pk.mkdir()
    base = [sys.executable, "-m", "pip", "install", "--no-deps", "--only-binary=:all:", "--target", str(pk), "--python-version", "3.13"]
    subprocess.run(base + PURE, check=True)
    for tag in TAGS[args.sdk]:
        subprocess.run(base + ["--platform", tag, "--extra-index-url", INDEX] + NATIVE, check=True)
    print(f"\nStaged in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
