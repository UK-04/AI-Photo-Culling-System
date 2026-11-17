//! The desktop shell. It does three things:
//!   1. starts the Python engine (a bundled sidecar binary) on a free local port with a
//!      one-time token, and stops it when the app quits;
//!   2. tells the web UI where the engine is (`engine_info`);
//!   3. provides the native menu and forwards its items to the UI as "menu" events.

use std::net::TcpListener;
use std::sync::Mutex;

use serde::Serialize;
use tauri::menu::{MenuBuilder, MenuItemBuilder, SubmenuBuilder};
use tauri::{Emitter, Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

#[derive(Clone, Serialize)]
struct EngineInfo {
    port: u16,
    token: String,
}

#[derive(Default)]
struct EngineState {
    info: Mutex<Option<EngineInfo>>,
    child: Mutex<Option<CommandChild>>,
}

/// Where the engine is listening, or `null` while it is still starting.
#[tauri::command]
fn engine_info(state: State<'_, EngineState>) -> Option<EngineInfo> {
    state.info.lock().ok().and_then(|guard| guard.clone())
}

fn free_port() -> std::io::Result<u16> {
    Ok(TcpListener::bind(("127.0.0.1", 0))?.local_addr()?.port())
}

fn start_engine(app: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let state = app.state::<EngineState>();

    // Development: `CULLER_DEV_ENGINE=8765:mytoken npm run tauri dev` uses an engine you
    // started yourself with `culler serve --port 8765 --token mytoken`.
    if let Ok(dev) = std::env::var("CULLER_DEV_ENGINE") {
        if let Some((port, token)) = dev.split_once(':') {
            *state.info.lock().unwrap() = Some(EngineInfo { port: port.parse()?, token: token.to_string() });
            return Ok(());
        }
    }

    let port = free_port()?;
    let token = uuid::Uuid::new_v4().simple().to_string();
    let pid = std::process::id().to_string();
    let (mut events, child) = app
        .shell()
        .sidecar("culler-engine")?
        .args([
            "serve", "--port", &port.to_string(), "--token", &token,
            // Two independent ways for the engine to notice the app is gone, so it can never be orphaned.
            "--parent-pid", &pid, "--watch-stdin",
        ])
        .spawn()?;

    *state.child.lock().unwrap() = Some(child);
    *state.info.lock().unwrap() = Some(EngineInfo { port, token });

    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stderr(line) => eprintln!("[engine] {}", String::from_utf8_lossy(&line).trim_end()),
                CommandEvent::Terminated(status) => {
                    eprintln!("[engine] exited: {:?}", status.code);
                    let state = handle.state::<EngineState>();
                    *state.info.lock().unwrap() = None;
                    let _ = handle.emit("engine-exited", status.code);
                    break;
                }
                _ => {}
            }
        }
    });
    Ok(())
}

fn stop_engine(app: &tauri::AppHandle) {
    let state = app.state::<EngineState>();
    let child = state.child.lock().ok().and_then(|mut guard| guard.take());
    if let Some(child) = child {
        let _ = child.kill();
    }
}

fn build_menu(app: &tauri::AppHandle) -> tauri::Result<()> {
    let item = |id: &str, text: &str, key: Option<&str>| {
        let builder = MenuItemBuilder::with_id(id, text);
        match key {
            Some(k) => builder.accelerator(k).build(app),
            None => builder.build(app),
        }
    };

    let app_menu = SubmenuBuilder::new(app, "Culler")
        .about(None)
        .separator()
        .services()
        .separator()
        .hide()
        .hide_others()
        .show_all()
        .separator()
        .quit()
        .build()?;
    let file = SubmenuBuilder::new(app, "File")
        .item(&item("open_folder", "Open Folder…", Some("CmdOrCtrl+O"))?)
        .item(&item("open_photos", "Select Photos…", Some("CmdOrCtrl+Shift+O"))?)
        .item(&item("rescan", "Rescan Folder", Some("CmdOrCtrl+R"))?)
        .separator()
        .item(&item("export", "Export…", Some("CmdOrCtrl+E"))?)
        .separator()
        .close_window()
        .build()?;
    // Undo/redo are custom items: they undo culling decisions, not text edits.
    let edit = SubmenuBuilder::new(app, "Edit")
        .item(&item("undo", "Undo", Some("CmdOrCtrl+Z"))?)
        .item(&item("redo", "Redo", Some("CmdOrCtrl+Shift+Z"))?)
        .separator()
        .cut()
        .copy()
        .paste()
        .select_all()
        .build()?;
    let view = SubmenuBuilder::new(app, "View")
        .item(&item("toggle_inspector", "Show or Hide Inspector", Some("CmdOrCtrl+Alt+I"))?)
        .separator()
        .fullscreen()
        .build()?;
    let window = SubmenuBuilder::new(app, "Window").minimize().maximize().build()?;
    let help = SubmenuBuilder::new(app, "Help")
        .item(&item("shortcuts", "Keyboard Shortcuts", None)?)
        .build()?;

    let menu = MenuBuilder::new(app).items(&[&app_menu, &file, &edit, &view, &window, &help]).build()?;
    app.set_menu(menu)?;
    app.on_menu_event(|app, event| {
        let _ = app.emit("menu", event.id().as_ref());
    });
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(EngineState::default())
        .invoke_handler(tauri::generate_handler![engine_info])
        .setup(|app| {
            build_menu(app.handle())?;
            if let Err(err) = start_engine(app.handle()) {
                eprintln!("could not start the engine: {err}");
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the app")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop_engine(app);
            }
        });
}
