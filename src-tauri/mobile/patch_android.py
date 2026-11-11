"""Add SciCal's Python engine (Chaquopy) to the Android project that `tauri android init` generated.

    npx tauri android init          # once; creates src-tauri/gen/android
    python src-tauri/mobile/patch_android.py

Safe to run again: it refreshes the copied files and changes each Gradle/manifest line only once. If a generated file does not look the
way this script expects (a newer Tauri template), it stops and says which edit to make by hand instead of guessing.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAURI = HERE.parent
APP = TAURI.parent
ANDROID = TAURI / "gen" / "android"
CHAQUOPY = "17.0.0"             # com.chaquo.python:gradle; the Python version below must be one that release supports
PYTHON = "3.13"                  # must match the Python on the PATH that Gradle uses to build (Chaquopy "buildPython")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "tests_*")


def fail(message: str) -> None:
    print("\nSTOPPED: " + message, file=sys.stderr)
    raise SystemExit(1)


def read(path: Path) -> str:
    if not path.is_file():
        fail(f"{path} not found. Run 'npx tauri android init' first.")
    return path.read_text(encoding="utf-8")


def package_of(app: Path) -> str:
    m = re.search(r'namespace\s*=\s*"([^"]+)"', read(app / "build.gradle.kts"))
    if not m:
        fail("could not find the app's namespace in app/build.gradle.kts")
    return m.group(1)


def main() -> int:
    app = ANDROID / "app"
    if not (app / "build.gradle.kts").is_file():
        fail("src-tauri/gen/android/app/build.gradle.kts not found. Run 'npx tauri android init' first.")
    pkg = package_of(app)
    if pkg != "app.slai.scical":
        fail(f"the Android package is {pkg!r} but the Kotlin files here use app.slai.scical. Keep the identifier in tauri.conf.json as app.slai.scical.")
    if not (APP / "dist" / "index.html").is_file():
        fail("the web client is not built. Run 'npm run build' in the SciCal folder first.")

    # 1. the Python code, the web client and the host code
    py = app / "src" / "main" / "python"
    shutil.rmtree(py / "scical", ignore_errors=True)
    shutil.copytree(APP / "scical", py / "scical", ignore=IGNORE)
    assets = app / "src" / "main" / "assets" / "scical_client"
    shutil.rmtree(assets, ignore_errors=True)
    shutil.copytree(APP / "dist", assets)
    if (APP.parent / "assets").is_dir():                 # the SLAI-wide tab icons
        shutil.copytree(APP.parent / "assets", assets / "assets")
    else:
        print("WARNING: applications/assets not found; the tab icons will be missing.")
    version = re.search(r'"version":\s*"([^"]+)"', (TAURI / "tauri.conf.json").read_text(encoding="utf-8")).group(1)
    stamp = f"{version}+{int((APP / 'dist' / 'index.html').stat().st_mtime)}"
    (assets / "version.txt").write_text(stamp, encoding="utf-8")
    kotlin = app / "src" / "main" / "java" / Path(*pkg.split("."))
    kotlin.mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / "android" / "EngineHost.kt", kotlin / "EngineHost.kt")
    shutil.copy(HERE / "android" / "MainActivity.kt", kotlin / "MainActivity.kt")
    xml = app / "src" / "main" / "res" / "xml"
    xml.mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / "android" / "network_security_config.xml", xml / "network_security_config.xml")

    # 2. the manifest: allow plain HTTP to the loopback address only
    manifest = app / "src" / "main" / "AndroidManifest.xml"
    text = read(manifest)
    if "networkSecurityConfig" not in text:
        new = text.replace("<application", '<application\n        android:networkSecurityConfig="@xml/network_security_config"', 1)
        if new == text:
            fail("no <application> tag in AndroidManifest.xml. Add android:networkSecurityConfig=\"@xml/network_security_config\" to it.")
        manifest.write_text(new, encoding="utf-8")

    # 3. Gradle: the Chaquopy plugin
    root = ANDROID / "build.gradle.kts"
    text = read(root)
    if "com.chaquo.python" not in text:
        new = re.sub(r"(buildscript\s*\{.*?dependencies\s*\{)", r'\1\n        classpath("com.chaquo.python:gradle:%s")' % CHAQUOPY, text, count=1, flags=re.S)
        if new == text:
            fail(f'could not edit build.gradle.kts. Add classpath("com.chaquo.python:gradle:{CHAQUOPY}") to its buildscript dependencies.')
        root.write_text(new, encoding="utf-8")

    gradle = app / "build.gradle.kts"
    text = read(gradle)
    if 'id("com.chaquo.python")' not in text:
        # Chaquopy documents that its plugin is applied after the Android one
        new = re.sub(r'(id\("com\.android\.application"\)[^\n]*)', r'\1\n    id("com.chaquo.python")', text, count=1)
        if new == text:
            fail('could not edit app/build.gradle.kts. Add id("com.chaquo.python") to its plugins block.')
        text = new
    if "chaquopy {" not in text:
        block = f'''
// ---- SciCal engine (added by src-tauri/mobile/patch_android.py) ----
chaquopy {{
    defaultConfig {{
        version = "{PYTHON}"
        pip {{
            install("sympy>=1.12")
            install("mpmath>=1.3")
            install("numpy")
        }}
        extractPackages("scical")      // the engine reads its data files (elements, constants) from disk
    }}
}}
'''
        text = text.rstrip() + "\n" + block
        # Tauri's own product flavours already choose the CPU types; build one at a time (--target aarch64 or x86_64) so Chaquopy only
        # needs the wheels for that one.
    gradle.write_text(text, encoding="utf-8")

    print("Android project prepared. Build with:  npx tauri android build --apk --target aarch64   (or: npx tauri android dev)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
