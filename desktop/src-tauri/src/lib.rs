use base64::{engine::general_purpose, Engine as _};
use std::fs;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, WindowEvent,
};

/// 将前端传来的 data URL（base64 PNG）保存到 ~/Pictures/Ethan/<filename>。
/// 返回保存后的完整路径，供前端"打开文件夹"按钮使用。
#[tauri::command]
fn save_share_image(app: tauri::AppHandle, data_url: String, filename: String) -> Result<String, String> {
    let comma = data_url.find(',').ok_or_else(|| "Invalid data URL: missing comma".to_string())?;
    let b64 = &data_url[comma + 1..];
    let bytes = general_purpose::STANDARD
        .decode(b64)
        .map_err(|e| format!("Base64 decode failed: {e}"))?;

    let pictures_dir = app
        .path()
        .picture_dir()
        .map_err(|e| format!("Cannot resolve pictures dir: {e}"))?;
    let ethan_dir = pictures_dir.join("Ethan");
    fs::create_dir_all(&ethan_dir).map_err(|e| format!("Create dir failed: {e}"))?;

    let file_path = ethan_dir.join(&filename);
    fs::write(&file_path, &bytes).map_err(|e| format!("Write file failed: {e}"))?;

    Ok(file_path.to_string_lossy().to_string())
}

/// 在系统文件管理器中定位到指定文件（macOS: open -R, Windows: explorer /select, Linux: 打开父目录）。
#[tauri::command]
fn reveal_item_in_dir(path: String) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .args(["-R", &path])
            .spawn()
            .map_err(|e| format!("open -R failed: {e}"))?;
        Ok(())
    }
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("explorer")
            .arg(format!("/select,{path}"))
            .spawn()
            .map_err(|e| format!("explorer /select failed: {e}"))?;
        Ok(())
    }
    #[cfg(target_os = "linux")]
    {
        let p = std::path::Path::new(&path);
        let target = p.parent().unwrap_or(p);
        std::process::Command::new("xdg-open")
            .arg(target)
            .spawn()
            .map_err(|e| format!("xdg-open failed: {e}"))?;
        Ok(())
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![save_share_image, reveal_item_in_dir])
        .setup(|app| {
    let _ = app.get_webview_window("main").map(|w| w.set_title(""));
            // Build tray menu
            let show_item = MenuItem::with_id(app, "show", "Show Window", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

            // Create tray icon
            TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    // Left click on tray icon shows the window
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        // Intercept close: hide window instead of exiting
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                // Prevent the window from being destroyed
                api.prevent_close();
                // Just hide it
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
