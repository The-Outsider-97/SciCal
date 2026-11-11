@echo off
rem Builds the SLAI SciCal installer for Windows. Double-click this file, or run it from a terminal.
rem It needs Node.js, Python 3.10+ and Rust (with the Visual Studio C++ Build Tools). The first run takes several minutes.
setlocal
cd /d "%~dp0"
echo.
echo === SLAI SciCal: building the Windows installer ===
echo.

call npm.cmd install || goto :fail
call npm.cmd run build || goto :fail

if not exist ".venv-engine\Scripts\python.exe" (
  python -m venv .venv-engine || goto :fail
)
".venv-engine\Scripts\python.exe" -m pip install --quiet -r requirements.txt pyinstaller || goto :fail
".venv-engine\Scripts\python.exe" tools\build_engine.py || goto :fail

call npm.cmd run tauri -- build || goto :fail

echo.
echo === Done. The installer is in src-tauri\target\release\bundle\nsis ===
start "" "src-tauri\target\release\bundle\nsis"
pause
exit /b 0

:fail
echo.
echo === The build stopped. Read the last lines above; if you send them to me I will fix it. ===
pause
exit /b 1
