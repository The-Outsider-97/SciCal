"""Add SciCal's embedded Python engine to the Xcode project that `tauri ios init` generated. Run on the Mac.

    npx tauri ios init
    python3 src-tauri/mobile/patch_ios.py

It copies the engine host (SciCalEngine.h/.m) next to the app's main.mm, makes main.mm start the engine before the Tauri app, and
allows plain HTTP to the loopback address in Info.plist. The Python runtime itself and the bundle folders are added in Xcode: see the
"iOS" section of docs/MOBILE_AND_DESKTOP.md. Safe to run again.
"""
from __future__ import annotations

import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APPLE = HERE.parent / "gen" / "apple"


def fail(message: str) -> None:
    print("\nSTOPPED: " + message, file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    if not APPLE.is_dir():
        fail("src-tauri/gen/apple not found. Run 'npx tauri ios init' first (on a Mac).")
    mains = sorted((APPLE / "Sources").glob("*/main.mm"))
    if not mains:
        fail("no Sources/*/main.mm in gen/apple. Newer Tauri templates may differ: call [SciCalEngine start]; before the Tauri app starts, by hand.")
    main_mm = mains[0]
    target = main_mm.parent
    shutil.copy(HERE / "ios" / "SciCalEngine.h", target / "SciCalEngine.h")
    shutil.copy(HERE / "ios" / "SciCalEngine.m", target / "SciCalEngine.m")

    text = main_mm.read_text(encoding="utf-8")
    if "SciCalEngine" not in text:
        if "start_app" not in text:
            fail(f"{main_mm} has no start_app call. Add [SciCalEngine start]; before the Tauri app is started.")
        text = '#import "SciCalEngine.h"\n' + text
        text = re.sub(r"(\n[ \t]*)((?:ffi::)?start_app\s*\(\s*\)\s*;)", r"\1[SciCalEngine start];\1\2", text, count=1)
        main_mm.write_text(text, encoding="utf-8")

    plists = [p for p in APPLE.glob("*_iOS/Info.plist")] or [p for p in APPLE.glob("**/Info.plist") if "build" not in p.parts]
    if not plists:
        fail("no Info.plist found in gen/apple. Add NSAppTransportSecurity > NSAllowsLocalNetworking = YES by hand.")
    for path in plists:
        with path.open("rb") as f:
            data = plistlib.load(f)
        ats = data.setdefault("NSAppTransportSecurity", {})
        ats["NSAllowsLocalNetworking"] = True
        with path.open("wb") as f:
            plistlib.dump(data, f)

    if shutil.which("xcodegen"):
        subprocess.run(["xcodegen", "generate"], cwd=APPLE, check=False)        # picks the two new files up
    else:
        print("xcodegen is not installed; if Xcode does not list SciCalEngine.m, add it to the app target by hand.")
    print("iOS project prepared. Next: the Python runtime and bundle folders (docs/MOBILE_AND_DESKTOP.md, section iOS).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
