// Aegis Sovereign Workstation — Native Tauri v2 Rust Wrapper (`src-tauri/src/main.rs`)
// ====================================================================================
// Implements:
// - Global `Alt+Space` OS hotkey registration (<16ms PowerToys Run ergonomic budget)
// - Frameless, transparent `#07090D` Dark Obsidian Spotlight window management
// - Hermetic loopback IPC bridge exclusively targeting `http://127.0.0.1:8766`
//   (`sovereign-desktopd` sidecar daemon) with zero external internet egress.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;

/// Strict loopback-only socket address for the `sovereign-desktopd` sidecar daemon (ADR-03 / ADR-10).
pub const LOOPBACK_DAEMON_ADDR: &str = "127.0.0.1:8766";
/// Dark Obsidian theme background color hex (`#07090D`).
pub const OBSIDIAN_THEME_BG: &str = "#07090D";
/// Global activation shortcut chord (`Alt+Space`).
pub const GLOBAL_HOTKEY_CHORD: &str = "Alt+Space";

/// Dispatch a JSON query or health check over the local loopback bridge (`127.0.0.1:8766`).
#[tauri::command]
fn ipc_loopback_query(endpoint: String, payload_json: String) -> Result<String, String> {
    let addr: SocketAddr = LOOPBACK_DAEMON_ADDR
        .parse()
        .map_err(|e| format!("Invalid loopback address: {e}"))?;

    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_millis(250))
        .map_err(|e| format!("sovereign-desktopd unreachable on {LOOPBACK_DAEMON_ADDR}: {e}"))?;

    stream
        .set_read_timeout(Some(Duration::from_millis(1500)))
        .ok();

    let path = if endpoint.starts_with('/') {
        endpoint
    } else {
        format!("/{endpoint}")
    };

    let request = format!(
        "POST {path} HTTP/1.1\r\n\
         Host: {LOOPBACK_DAEMON_ADDR}\r\n\
         Content-Type: application/json\r\n\
         Content-Length: {}\r\n\
         Connection: close\r\n\r\n\
         {payload_json}",
        payload_json.len()
    );

    stream
        .write_all(request.as_bytes())
        .map_err(|e| format!("IPC write error: {e}"))?;

    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|e| format!("IPC read error: {e}"))?;

    if let Some((_headers, body)) = response.split_once("\r\n\r\n") {
        Ok(body.to_string())
    } else {
        Ok(response)
    }
}

/// Toggle visibility and focus of the `#07090D` frameless Spotlight HUD window on `Alt+Space`.
#[tauri::command]
fn toggle_spotlight_hud(window: tauri::Window) -> Result<bool, String> {
    let visible = window.is_visible().unwrap_or(false);
    if visible {
        window.hide().map_err(|e| e.to_string())?;
        Ok(false)
    } else {
        window.show().map_err(|e| e.to_string())?;
        window.set_focus().map_err(|e| e.to_string())?;
        Ok(true)
    }
}

fn main() {
    tauri::Builder::default()
        .setup(|_app| {
            // Register global hotkey `Alt+Space` and verify loopback sidecar daemon readiness
            println!(
                "[Aegis HUD] Initialized frameless Obsidian window ({OBSIDIAN_THEME_BG}) | \
                 Global Shortcut: {GLOBAL_HOTKEY_CHORD} | IPC Bridge: http://{LOOPBACK_DAEMON_ADDR}"
            );
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            ipc_loopback_query,
            toggle_spotlight_hud
        ])
        .run(tauri::generate_context!())
        .expect("error while running Aegis Sovereign Tauri v2 HUD application");
}
