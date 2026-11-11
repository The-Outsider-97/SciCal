//! Desktop engine launcher: start, wait until ready, show it, and stop it again.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use serde::Deserialize;
use tauri::{AppHandle, Manager};

/// The port SciCal prefers, so the web view keeps the same address (and the same browser storage) from one run to the next.
/// If something else holds it the engine takes any free port (`--port-fallback`).
const PREFERRED_PORT: u16 = 47868;
const START_TIMEOUT: Duration = Duration::from_secs(90);

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(Deserialize)]
struct Ready {
    url: String,
}

struct Engine {
    child: Child,
    _stdin: Option<ChildStdin>, // kept open: closing it (when this process ends, however it ends) tells the engine to stop
}

static ENGINE: Mutex<Option<Engine>> = Mutex::new(None);

/// Where the engine lives. A release build ships it as a resource folder made by `tools/build-engine.ps1` (a frozen Python with the
/// web client inside). A debug build (`tauri dev`) runs the checkout's own Python instead.
fn command(app: &AppHandle) -> Result<Command, String> {
    let common = [
        "--no-browser",
        "--ready-line",
        "--exit-on-stdin-close",
        "--port-fallback",
        "--port",
    ];
    let port = PREFERRED_PORT.to_string();
    if cfg!(debug_assertions) || std::env::var_os("SCICAL_DEV_PYTHON").is_some() {
        let python = std::env::var("SCICAL_DEV_PYTHON").unwrap_or_else(|_| if cfg!(windows) { "python".into() } else { "python3".into() });
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
        let mut c = Command::new(python);
        c.current_dir(root).args(["-m", "scical"]).args(common).arg(&port);
        return Ok(c);
    }
    let dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("no resource folder: {e}"))?
        .join("engine");
    let exe = dir.join(if cfg!(windows) { "scical-engine.exe" } else { "scical-engine" });
    if !exe.is_file() {
        return Err(format!("The SciCal engine is missing: {}", exe.display()));
    }
    let mut c = Command::new(exe);
    c.current_dir(&dir).args(common).arg(&port).arg("--client-dir").arg(dir.join("client"));
    Ok(c)
}

pub fn start_engine(app: AppHandle) {
    std::thread::spawn(move || {
        let outcome = launch(&app);
        if let Err(message) = outcome {
            show_error(&app, &message);
        }
    });
}

fn launch(app: &AppHandle) -> Result<(), String> {
    let mut cmd = command(app)?;
    cmd.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = cmd.spawn().map_err(|e| format!("Could not start the SciCal engine: {e}"))?;
    let stdout = child.stdout.take().ok_or("The engine has no output")?;
    let stdin = child.stdin.take();
    *ENGINE.lock().unwrap() = Some(Engine { child, _stdin: stdin });

    // Read lines until the READY line; keep draining afterwards so the engine never blocks on a full pipe.
    let (tx, rx) = std::sync::mpsc::channel::<Ready>();
    std::thread::spawn(move || {
        let mut sent = false;
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if !sent {
                if let Some(json) = line.strip_prefix("SCICAL_READY ") {
                    if let Ok(ready) = serde_json::from_str::<Ready>(json) {
                        let _ = tx.send(ready);
                        sent = true;
                    }
                }
            }
        }
    });
    let ready = rx
        .recv_timeout(START_TIMEOUT)
        .map_err(|_| "The SciCal engine did not start in time. Check that the app was installed completely.".to_string())?;

    let window = app.get_webview_window("main").ok_or("The main window is missing")?;
    let target = serde_json::to_string(&ready.url).map_err(|e| e.to_string())?;
    window.eval(&format!("window.location.replace({target})")).map_err(|e| format!("Could not open the SciCal window: {e}"))?;
    Ok(())
}

fn show_error(app: &AppHandle, message: &str) {
    if let Some(window) = app.get_webview_window("main") {
        let text = serde_json::to_string(message).unwrap_or_else(|_| "\"SciCal could not start.\"".into());
        let _ = window.eval(&format!("window.scicalFailed && window.scicalFailed({text})"));
    }
}

pub fn stop_engine(_app: &AppHandle) {
    if let Some(mut engine) = ENGINE.lock().unwrap().take() {
        drop(engine._stdin.take()); // the engine sees the end of its input and shuts down on its own
        for _ in 0..20 {
            if matches!(engine.child.try_wait(), Ok(Some(_))) {
                return;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        let _ = engine.child.kill();
    }
}
