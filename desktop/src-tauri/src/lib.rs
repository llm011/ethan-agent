use base64::{engine::general_purpose, Engine as _};
use serde::Deserialize;
use std::fs;
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Emitter, Manager, WindowEvent,
};
use tauri_plugin_autostart::MacosLauncher;
use tauri_plugin_deep_link::DeepLinkExt;

#[derive(Debug, Default, Deserialize)]
struct EthanConfig {
    #[serde(default)]
    server: EthanServerConfig,
}

#[derive(Debug, Default, Deserialize)]
struct EthanServerConfig {
    host: Option<String>,
    port: Option<u16>,
}

/// 配置里的监听地址不能直接拿来当客户端地址：0.0.0.0 / :: 是 bind 地址，不可连接。
/// IPv6 literal 放进 URL authority 时必须带中括号。
fn client_host(host: &str) -> String {
    let host = host.trim();
    match host {
        "" | "0.0.0.0" | "::" | "[::]" => "127.0.0.1".to_string(),
        value if value.starts_with('[') && value.ends_with(']') => value.to_string(),
        value if value.contains(':') => format!("[{value}]"),
        value => value.to_string(),
    }
}

fn configured_non_empty(value: Option<String>) -> Option<String> {
    value.and_then(|value| {
        let trimmed = value.trim();
        (!trimmed.is_empty()).then(|| trimmed.to_string())
    })
}

/// 返回桌面端应连接的 Ethan Server URL。
///
/// 与后端的优先级对齐：环境变量覆盖 config.yaml，最后才是 Ethan 自己的默认值。
/// 本命令在 Rust 侧读用户目录，避免 WebView 再复制一个写死端口。
#[tauri::command]
fn get_ethan_server_url() -> String {
    let env_host = std::env::var("ETHAN_SERVER_HOST").ok().and_then(|value| configured_non_empty(Some(value)));
    let env_port = std::env::var("ETHAN_SERVER_PORT")
        .ok()
        .and_then(|value| value.parse::<u16>().ok());

    let config_path = std::env::var_os("ETHAN_DATA_DIR")
        .map(std::path::PathBuf::from)
        .or_else(|| dirs::home_dir().map(|home| home.join(".ethan")))
        .map(|dir| dir.join("config.yaml"));
    let config = config_path
        .as_deref()
        .and_then(|path| fs::read_to_string(path).ok())
        .and_then(|content| serde_yaml::from_str::<EthanConfig>(&content).ok())
        .unwrap_or_default();

    let host = env_host
        .or_else(|| configured_non_empty(config.server.host))
        .unwrap_or_else(|| "0.0.0.0".to_string());
    let port = env_port.or(config.server.port).unwrap_or(8900);
    format!("http://{}:{}", client_host(&host), port)
}

/// 返回 ~/Pictures/Ethan 的规范路径，确保目录存在。
fn ethan_pictures_dir(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    let pictures_dir = app
        .path()
        .picture_dir()
        .map_err(|e| format!("Cannot resolve pictures dir: {e}"))?;
    let ethan_dir = pictures_dir.join("Ethan");
    fs::create_dir_all(&ethan_dir).map_err(|e| format!("Create dir failed: {e}"))?;
    Ok(ethan_dir)
}

/// 将前端传来的 data URL（base64 PNG）保存到 ~/Pictures/Ethan/<filename>。
/// 返回保存后的完整路径，供前端"打开文件夹"按钮使用。
///
/// 安全：filename 仅取其 file_name 部分，剥离任何路径前缀，防止路径穿越。
#[tauri::command]
fn save_share_image(app: tauri::AppHandle, data_url: String, filename: String) -> Result<String, String> {
    let comma = data_url.find(',').ok_or_else(|| "Invalid data URL: missing comma".to_string())?;
    let b64 = &data_url[comma + 1..];
    let bytes = general_purpose::STANDARD
        .decode(b64)
        .map_err(|e| format!("Base64 decode failed: {e}"))?;

    let ethan_dir = ethan_pictures_dir(&app)?;

    // 仅取 file_name，剥离任何目录前缀，防止 ../../etc/passwd 之类的路径穿越
    let safe_filename = std::path::Path::new(&filename)
        .file_name()
        .ok_or_else(|| "Invalid filename".to_string())?;
    let file_path = ethan_dir.join(safe_filename);
    fs::write(&file_path, &bytes).map_err(|e| format!("Write file failed: {e}"))?;

    Ok(file_path.to_string_lossy().to_string())
}

/// 在系统文件管理器中定位到指定文件（macOS: open -R, Windows: explorer /select, Linux: 打开父目录）。
///
/// 安全：仅允许定位 ~/Pictures/Ethan 目录下的文件，防止前端越权探测宿主机其他路径。
#[tauri::command]
fn reveal_item_in_dir(app: tauri::AppHandle, path: String) -> Result<(), String> {
    let ethan_dir = ethan_pictures_dir(&app)?;
    let canonical_ethan = fs::canonicalize(&ethan_dir)
        .map_err(|e| format!("Canonicalize ethan dir failed: {e}"))?;
    let canonical_target = fs::canonicalize(&path)
        .map_err(|e| format!("Canonicalize target path failed: {e}"))?;
    if !canonical_target.starts_with(&canonical_ethan) {
        return Err("Permission denied: path out of bounds".to_string());
    }

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
        // explorer.exe /select,<path> 对含空格路径敏感，使用原始绝对路径
        // （Tauri 传入的通常是绝对路径）。Rust 的 Command 会原样传递参数，
        // 不做 shell 转义，因此空格安全。
        std::process::Command::new("explorer")
            .arg(format!("/select,{}", path))
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

/// 读取 macOS 系统代理设置，写入环境变量。
/// GUI 应用从 Dock/Finder 启动时不继承终端的 shell 环境变量，
/// 而 reqwest（Tauri updater 内部使用）只读环境变量不读系统代理，
/// 需要手动桥接，否则在国内直连 GitHub 会超时。
#[cfg(target_os = "macos")]
fn setup_proxy_env() {
    use std::process::Command;
    let Ok(output) = Command::new("scutil").arg("--proxy").output() else {
        return;
    };
    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut https_enabled = false;
    let mut host = String::new();
    let mut port = String::new();
    for line in stdout.lines() {
        let line = line.trim();
        if let Some(v) = line.strip_prefix("HTTPSEnable :") {
            https_enabled = v.trim() == "1";
        }
        if let Some(v) = line.strip_prefix("HTTPSProxy :") {
            host = v.trim().to_string();
        }
        if let Some(v) = line.strip_prefix("HTTPSPort :") {
            port = v.trim().to_string();
        }
    }
    if https_enabled && !host.is_empty() && !port.is_empty() {
        let proxy = format!("http://{}:{}", host, port);
        std::env::set_var("HTTP_PROXY", &proxy);
        std::env::set_var("HTTPS_PROXY", &proxy);
        std::env::set_var("http_proxy", &proxy);
        std::env::set_var("https_proxy", &proxy);
    }
}

#[cfg(not(target_os = "macos"))]
fn setup_proxy_env() {}

#[tauri::command]
fn set_countdown_always_on_top(app: tauri::AppHandle, on_top: bool) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("countdown") {
        window.set_always_on_top(on_top).map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn close_countdown_window(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("countdown") {
        window.hide().map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn open_countdown_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("countdown") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

#[tauri::command]
fn open_countdown_window_cmd(app: tauri::AppHandle) {
    open_countdown_window(&app);
}

pub fn run() {
    setup_proxy_env();
    let builder = tauri::Builder::default();

    // 单实例锁：第二个实例启动时聚焦已有窗口（macOS 由 Reopen 事件原生处理）
    #[cfg(not(target_os = "macos"))]
    let builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
        if let Some(window) = app.get_webview_window("main") {
            let _ = window.show();
            let _ = window.set_focus();
        }
    }));

    builder
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_window_state::Builder::new().build())
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(MacosLauncher::LaunchAgent, None))
        .invoke_handler(tauri::generate_handler![get_ethan_server_url, save_share_image, reveal_item_in_dir, set_countdown_always_on_top, close_countdown_window, open_countdown_window_cmd])
        .setup(|app| {
            let _ = app.get_webview_window("main").map(|w| w.set_title(""));

            // 注册 deep-link 处理器：收到 ethan:// URL 时转发给前端
            let handle = app.handle().clone();
            app.deep_link().on_open_url(move |event| {
                for url in event.urls() {
                    let _ = handle.emit("deep-link-url", url.to_string());
                }
            });

            // Build tray menu
            let show_item = MenuItem::with_id(app, "show", "Show Window", true, None::<&str>)?;
            let countdown_item = MenuItem::with_id(app, "countdown", "Start Countdown", true, None::<&str>)?;
            let update_item = MenuItem::with_id(app, "check_update", "Check for Updates", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &countdown_item, &update_item, &quit_item])?;

            // Create tray icon
            TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "countdown" => {
                        open_countdown_window(app);
                    }
                    "check_update" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                            let _ = window.emit("tray-check-update", ());
                        }
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|_tray, _event| {})
                .build(app)?;

            Ok(())
        })
        // Intercept close: hide window instead of exiting
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let label = window.label();
                if label == "main" || label == "countdown" {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // macOS: dock icon 点击时重新显示窗口（Reopen variant 仅 macOS 存在）
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Reopen { .. } = event {
                if let Some(window) = app_handle.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
            // 避免 unused variable 警告
            let _ = app_handle;
            let _ = event;
        });
}
