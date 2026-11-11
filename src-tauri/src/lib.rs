//! SLAI SciCal as a Tauri 2 app.
//!
//! The calculator's engine is Python (see `scical/`) and its screen is the web client in `dist/`. This crate only does two things:
//!
//! * **Desktop (Windows, and macOS/Linux when built there):** start the engine as a child process, wait for its `SCICAL_READY {...}` line,
//!   then point the window at the engine's loopback address. When the app closes, the engine's standard input closes and it exits.
//! * **Android and iOS:** the engine runs inside the app process (Chaquopy on Android, embedded CPython on iOS). The native host code in
//!   `mobile/android` and `mobile/ios` starts it and loads the web view itself, so nothing is needed here.
//!
//! The page the window shows (the engine's own) never calls Tauri, so no Tauri permissions are granted to it (see `capabilities/`).

#[cfg(desktop)]
mod desktop;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default();

    #[cfg(desktop)]
    let builder = builder.setup(|app| {
        desktop::start_engine(app.handle().clone());
        Ok(())
    });

    builder
        .build(tauri::generate_context!())
        .expect("error while building SciCal")
        .run(|app, event| {
            #[cfg(desktop)]
            {
                if let tauri::RunEvent::Exit = event {
                    desktop::stop_engine(app);
                }
            }
            #[cfg(not(desktop))]
            {
                let _ = (app, event);
            }
        });
}
