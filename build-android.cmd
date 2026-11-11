@echo off
rem Builds the SLAI SciCal Android app (an .apk for a phone). Double-click this file, or run it from a terminal.
rem Needs: Android Studio installed (https://developer.android.com/studio) with its SDK and NDK, Node.js, Python 3.13 and Rust.
rem In Android Studio: Settings > Languages & Frameworks > Android SDK > SDK Tools > tick "NDK (Side by side)" and "Android SDK Command-line Tools", Apply.
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo.
echo === SLAI SciCal: building the Android app ===
echo.

rem --- find Java (the one that comes with Android Studio)
if not defined JAVA_HOME (
  if exist "%ProgramFiles%\Android\Android Studio\jbr\bin\java.exe" set "JAVA_HOME=%ProgramFiles%\Android\Android Studio\jbr"
)
if not defined JAVA_HOME (
  echo Android Studio was not found in "%ProgramFiles%\Android\Android Studio".
  echo Install it from https://developer.android.com/studio , open it once so it downloads the Android SDK, then run this file again.
  echo If it is installed somewhere else, set JAVA_HOME to its "jbr" folder first.
  goto :fail
)
set "PATH=%JAVA_HOME%\bin;%PATH%"

rem --- find the Android SDK and NDK
if not defined ANDROID_HOME set "ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk"
if not exist "%ANDROID_HOME%\platforms" (
  echo The Android SDK was not found in "%ANDROID_HOME%". Open Android Studio once so it installs it, or set ANDROID_HOME.
  goto :fail
)
if not defined NDK_HOME (
  if exist "%ANDROID_HOME%\ndk" (
    for /f "delims=" %%i in ('dir /b /ad /o-n "%ANDROID_HOME%\ndk"') do if not defined NDK_HOME set "NDK_HOME=%ANDROID_HOME%\ndk\%%i"
  )
)
if not defined NDK_HOME (
  echo The Android NDK was not found. In Android Studio: Settings ^> Languages ^& Frameworks ^> Android SDK ^> SDK Tools ^> tick "NDK (Side by side)" ^> Apply. Then run this file again.
  goto :fail
)
echo Java : %JAVA_HOME%
echo SDK  : %ANDROID_HOME%
echo NDK  : %NDK_HOME%
echo.

call rustup target add aarch64-linux-android || goto :fail
call npm.cmd install || goto :fail
call npm.cmd run build || goto :fail

if not exist "src-tauri\gen\android\app\build.gradle.kts" (
  call npm.cmd run tauri -- android init || goto :fail
)
python src-tauri\mobile\patch_android.py || goto :fail
call npm.cmd run tauri -- android build --apk --debug --target aarch64 || goto :fail

echo.
echo === Done. The .apk is in src-tauri\gen\android\app\build\outputs\apk ===
echo Copy it to your phone and open it (allow "install unknown apps" when asked), or install it with: adb install -r path\to\app-universal-debug.apk
start "" "src-tauri\gen\android\app\build\outputs\apk"
pause
exit /b 0

:fail
echo.
echo === The build stopped. Read the last lines above; if you send them to me I will fix it. ===
pause
exit /b 1
