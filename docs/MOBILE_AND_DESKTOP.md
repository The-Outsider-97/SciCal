# SciCal as a Windows program and a phone app (Tauri 2)

SciCal keeps one engine (Python) and one screen (the web client). The apps are thin shells around those two parts, built with
[Tauri 2](https://v2.tauri.app/):

| Platform | Window | Where the Python engine runs | How the window finds it |
|---|---|---|---|
| **Windows** | Tauri (WebView2) | the app starts `engine/scical-engine.exe`, a small launcher (PyInstaller) that runs SciCal **inside the Python environment (`venv`) of the SLAI checkout it was built from**, so the SLAI agents, STEM Lab and exports work | the app reads one `SCICAL_READY {…}` line from the engine, then loads that address |
| **Android** | Tauri (system WebView) | **inside the app**, with [Chaquopy](https://chaquo.com/chaquopy/) (CPython 3.13) | `EngineHost.kt` starts it, then loads the address into the web view |
| **iOS** | Tauri (WKWebView) | **inside the app**, embedded CPython from [BeeWare's Python-Apple-support](https://github.com/beeware/Python-Apple-support) | `SciCalEngine.m` starts it, then loads the address into the web view |

The engine listens on `127.0.0.1` only. A random access token, known only to the app that started it, is needed for every request, and
the engine's strict Content-Security-Policy and Host/Origin checks are unchanged. The page it shows never calls Tauri, so the Tauri
window is granted no permissions at all (`src-tauri/capabilities/default.json`).

Your worksheets and settings stay where they are today on Windows (`%LOCALAPPDATA%\SLAI\SciCal`), so the program and the browser version
share them. On a phone they live in the app's private storage.

## What has and has not been checked

I could not build any of the three apps where this was written: the sandbox has no access to crates.io, the Android SDK or Maven, has
no Windows, and iOS needs a Mac. So, plainly:

| Part | Status |
|---|---|
| The Python engine in **thread mode** (used on phones): calculations, timeouts, cancel, runaway-loop stop | **Tested** (`tests/test_embedded.py`) |
| The embedded server API (`scical.embed`) the phone hosts call | **Tested** |
| The desktop launcher protocol: `SCICAL_READY` line, port fallback, exit when the app's pipe closes | **Tested** (starts the real engine) |
| The web client in a phone-sized screen (bottom tab bar, safe areas, touch) | **Tested** in Chromium with a phone profile (`tests_e2e/test_e2e_motion.py`) |
| `patch_android.py` and `patch_ios.py` | Run against **mock copies** of Tauri's generated projects, twice each (so re-running is safe) |
| Rust shell (`src-tauri/src`), `tauri.conf.json`, resources, capabilities | **Not compiled.** Written against the Tauri 2 API; expect to fix small compile errors on the first build |
| PyInstaller freeze of the engine | **Not run** (PyInstaller could not be installed here) |
| Chaquopy build, Kotlin host | **Not built** |
| Embedded CPython on iOS, Objective-C host | **Not built**; this is the least certain part |
| Anything on a real device | **Not tried** |

If a step fails, the message points at the file and the line to change; the places most likely to need a small adjustment are listed
under "If something does not build" at the end.

## Differences you will notice on a phone

* **Calculation limits.** Windows runs each calculation in a worker process that is killed if it runs too long. Phones cannot start
  worker processes, so calculations run in threads. A runaway calculation in pure Python (SymPy) is stopped at once; one that is stuck
  inside a single huge native operation (an enormous integer power) cannot be, and after three such cases SciCal asks you to restart
  it. There is also no memory cap. Both are the price of running inside the app.
* **No SLAI assistant.** The optional SLAI agents, the SLDC export and the STEM facade need a SLAI checkout on the same machine, so
  they are off on phones. Everything else works the same.
* **Saving files.** On iOS the Save/PNG buttons open the share sheet (Save to Files, Mail, …). On Android the system web view cannot
  save a downloaded blob, so exports are written to the app's Documents folder
  (`Android/data/app.slai.scical/files/Documents`), which is reachable from a computer or a file manager that shows app folders.
  A share-sheet button for Android is the natural next step.
* **Background.** The engine lives as long as the app process. If the system ends the process in the background, the app starts a new
  engine next time (your worksheets are saved on disk, so nothing is lost).

## 1. Windows

**The short way:** double-click `build-windows.cmd` in the SciCal folder. It does everything below and opens the folder with the installer (`SLAI SciCal_..._x64-setup.exe`). Run that file to install SciCal like any other program.

The individual steps, if you want them:

You need: Windows 10/11, **Rust** (rustup, with the MSVC toolchain), **Visual Studio Build Tools** with "Desktop development with C++",
**Node.js 20+**, and **Python 3.13** (3.10+ works) on the PATH. WebView2 is part of Windows 11; the installer fetches it on Windows 10.

```powershell
cd path\to\SciCal
npm install
python -m pip install -r requirements.txt pyinstaller

# Try it first: a debug window that runs the engine from this folder
npm run app:dev

# The installer: freezes the engine, then builds the app
npm run app:build:windows
```

If PowerShell says "npx.ps1 cannot be loaded ... not digitally signed", use `npm.cmd run tauri -- build` (or `npx.cmd tauri build`) instead of `npx`; it is only PowerShell's script policy.

The installers appear in `src-tauri\target\release\bundle\nsis\` (`.exe`) and `...\msi\`. The first build downloads and compiles the
Rust crates and takes several minutes.

Notes:

* **SLAI is part of the Windows app.** `build_engine.py` must run inside a SLAI checkout (`applications/SciCal`); it writes the checkout's location to `engine\slai_root.txt`. At start-up the launcher runs `python -m scical` from `<SLAI>\venv`. There is no silent fallback to a SLAI-less engine: if the checkout moved, `venv` is missing, or a package is missing, the app's window says exactly that. After moving the SLAI folder, rebuild the installer (or set `SLAI_ROOT`). The app calculates inside the engine (threads, `--worker-mode thread`, like StringLab) so there is nothing extra to start; the engine's messages go to `%LOCALAPPDATA%\SLAI\SciCal\engine.log`.
* The engine folder `src-tauri\engine\` is made by `python tools\build_engine.py` (PyInstaller, one folder, with the web client inside).
  To test the frozen engine on its own: `src-tauri\engine\scical-engine.exe --no-browser --port-fallback --ready-line` prints a ready
  line with the address.
* The app prefers port **47868** so the window keeps the same address (and the same stored favourites) from run to run; if that port is
  taken the engine uses any free one.
* To use the SLAI features (SLDC export, STEM facade), set the environment variable `SLAI_ROOT` to your SLAI checkout before starting
  the app; the engine inherits it.
* The installer is **unsigned**, so Windows SmartScreen shows a warning until you sign it (`bundle.windows.certificateThumbprint` in
  `tauri.conf.json`).

## 2. Android

You need Android Studio (SDK Platform 34+, **NDK (Side by side)**, Command-line tools), `JAVA_HOME` pointing at Android Studio's JDK,
`ANDROID_HOME`, `NDK_HOME`, Rust with the Android targets, Node 20+, and **Python 3.13 on the PATH** (Chaquopy needs a Python of the same
version on the build computer).

```powershell
rustup target add aarch64-linux-android armv7-linux-androideabi i686-linux-android x86_64-linux-android
cd path\to\SciCal
npm install
npm run build
npx tauri android init                       # creates src-tauri/gen/android
python src-tauri/mobile/patch_android.py     # adds Chaquopy, the engine host, the web client and the Python code

npx tauri android dev                        # phone connected by USB (debugging on) or an emulator
npx tauri android build --apk --target aarch64   # a real phone (arm64); use --target x86_64 for the emulator
```

Build one CPU type at a time (`--target`), because Chaquopy downloads NumPy for each one. Run `patch_android.py` again whenever the
Python code or the web client changes (it refreshes the copies). A release build must be signed with your keystore, as for any Android
app (see Tauri's "Android code signing" page); the debug build installs as is.

`minSdk` is 26 in `tauri.conf.json`; Chaquopy needs 24 or newer.

## 3. iOS (needs a Mac)

You need Xcode (with the iOS SDK and simulators), an Apple developer team (a free account works for your own device),
`brew install xcodegen`, Rust with the iOS targets, Node 20+, and Python 3.13.

```bash
rustup target add aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios
cd path/to/SciCal
npm install && npm run build
export APPLE_DEVELOPMENT_TEAM=YOURTEAMID
npx tauri ios init                             # creates src-tauri/gen/apple
python3 src-tauri/mobile/patch_ios.py          # engine host + Info.plist (loopback HTTP allowed)
python3 src-tauri/mobile/stage_ios_python.py --sdk iphonesimulator     # or iphoneos for a device
```

Then, once, in Xcode (`open src-tauri/gen/apple/*.xcodeproj`), on the app target:

1. Download `Python-3.13-iOS-support.bN.tar.gz` from the Python-Apple-support releases and unpack it; drag **`Python.xcframework`** into
   *Frameworks, Libraries, and Embedded Content* (Embed & Sign).
2. Drag the three folders from `src-tauri/gen/apple/engine-resources/` (`app`, `app_packages`, `scical_client`) into the project as
   **folder references** (blue folders), target membership on.
3. Add a **Run Script** build phase (after *Copy Bundle Resources*) that puts the Python standard library in the app and turns native
   modules (NumPy) into signed frameworks, as the support package's README describes:
   ```bash
   set -e
   source "$PROJECT_DIR/path/to/Python.xcframework/build/utils.sh"
   install_python Python.xcframework app app_packages
   ```
4. Build Settings: set **User Script Sandboxing** to *No*.

Then run `npx tauri ios dev` (simulator) or build and archive from Xcode. NumPy needs an iOS build; `stage_ios_python.py` takes it from the
BeeWare wheel index. SymPy and mpmath are pure Python.

## 4. Updating

* Changing the web client: `npm run build`, then rebuild the app (Android and iOS: run the patch/stage script again first).
* Changing the Python engine: the same, plus `python tools/build_engine.py` on Windows (done by `npm run app:build:windows`).
* The version is in `package.json`, `src-tauri/tauri.conf.json` and `src-tauri/Cargo.toml`; keep them equal.

## If something does not build

* **`tauri.conf.json` resources.** `src-tauri/tauri.windows.conf.json` maps the folder with `"engine/": "engine/"`. If your Tauri version
  rejects that form, use `"resources": ["engine/**/*"]` and change `dir.join("engine")` in `src-tauri/src/desktop.rs` to match where
  the files land.
* **`window.eval` / `get_webview_window`** (`desktop.rs`). These are Tauri 2 names; on a very early 2.0 build they may differ.
* **Chaquopy versions.** `patch_android.py` uses Chaquopy 17.0.0 with Python 3.13; both are constants at the top of the script. If
  Gradle reports no NumPy wheel, set `PYTHON` to a version Chaquopy's repository has NumPy for, and use the same Python on your PATH.
* **Android cleartext error (`ERR_CLEARTEXT_NOT_PERMITTED`).** The manifest edit adds `android:networkSecurityConfig`; check that
  `res/xml/network_security_config.xml` exists and the attribute is on the `<application>` tag.
* **A white or "Starting…" window that never changes.** The engine did not start. Windows: run `scical-engine.exe --no-browser
  --ready-line` in a console and read the error. Android: `adb logcat -s SciCalEngine`. iOS: the Xcode console. The start-up page
  shows the engine's error text when it has one.
* **iOS: `Python/Python.h` not found, or a native module cannot be imported.** Step 1 or 3 above is missing.
