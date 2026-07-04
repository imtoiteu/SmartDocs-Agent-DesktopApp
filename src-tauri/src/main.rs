// SmartDocs desktop shell.
//
// Owns the Python backend for the whole application session:
//   spawn sidecar (token via stdin, data dir via env)
//     → read {"event":"ready","port":N} handshake from its stdout
//     → poll /api/desktop/health (token header) until healthy
//     → navigate the window from the bundled splash to the local backend
//   on exit: POST /api/desktop/shutdown → bounded wait → force-kill.
//
// The launch token is generated fresh per launch, passed to Python via stdin,
// injected into the WebView as an initialization script, and never persisted
// or logged.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder};

const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(90);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const GRACEFUL_EXIT_WAIT: Duration = Duration::from_secs(8);

struct Sidecar {
    child: Mutex<Option<Child>>,
    port: Mutex<Option<u16>>,
    token: String,
}

fn new_token() -> String {
    let mut buf = [0u8; 32];
    getrandom::getrandom(&mut buf).expect("OS RNG unavailable");
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

/// Locate the sidecar executable. Release builds only ever run the bundled
/// resource; dev builds may override via SMARTDOCS_SIDECAR_CMD (used by
/// scripts/dev-desktop.sh to run desktop_server.py from a venv).
fn sidecar_command(app: &tauri::AppHandle) -> Result<Command, String> {
    #[cfg(debug_assertions)]
    if let Ok(raw) = std::env::var("SMARTDOCS_SIDECAR_CMD") {
        let parts: Vec<String> = raw.split_whitespace().map(String::from).collect();
        if let Some((exe, args)) = parts.split_first() {
            let mut cmd = Command::new(exe);
            cmd.args(args);
            return Ok(cmd);
        }
    }

    let exe_name = if cfg!(windows) { "smartdocs-sidecar.exe" } else { "smartdocs-sidecar" };
    let path = app
        .path()
        .resolve(format!("sidecar/{exe_name}"), tauri::path::BaseDirectory::Resource)
        .map_err(|e| format!("cannot resolve sidecar resource: {e}"))?;
    if !path.exists() {
        return Err(format!("sidecar binary not found at {}", path.display()));
    }
    // Bundlers do not reliably preserve the executable bit on resources.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755));
    }
    Ok(Command::new(path))
}

/// Spawn the sidecar and wait for its one-line JSON handshake on stdout.
fn start_sidecar(app: &tauri::AppHandle, token: &str) -> Result<(Child, u16), String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("cannot resolve app data dir: {e}"))?;
    std::fs::create_dir_all(&data_dir)
        .map_err(|e| format!("cannot create {}: {e}", data_dir.display()))?;

    let mut cmd = sidecar_command(app)?;
    cmd.env("SMARTDOCS_DESKTOP", "1")
        .env("SMARTDOCS_TOKEN_STDIN", "1")
        .env("SMARTDOCS_DATA_DIR", &data_dir)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());

    // Kernel-level orphan prevention: if this shell dies for ANY reason
    // (including SIGKILL), the sidecar receives SIGTERM and shuts down.
    #[cfg(target_os = "linux")]
    unsafe {
        use std::os::unix::process::CommandExt;
        cmd.pre_exec(|| {
            libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM);
            Ok(())
        });
    }

    let mut child = cmd.spawn().map_err(|e| format!("failed to start backend: {e}"))?;

    // Hand over the token on stdin — it never appears in argv or the env.
    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(format!("{token}\n").as_bytes())
            .and_then(|_| stdin.flush())
            .map_err(|e| format!("failed to pass token to backend: {e}"))?;
        // stdin drops here → EOF; the sidecar has already read its one line.
    }

    let stdout = child.stdout.take().ok_or("backend stdout unavailable")?;
    let (tx, rx) = mpsc::channel::<serde_json::Value>();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(line.trim()) {
                let ev = v.get("event").and_then(|e| e.as_str()).unwrap_or("");
                if ev == "ready" || ev == "error" {
                    let _ = tx.send(v);
                    return;
                }
            }
            // Non-JSON stdout noise (PyInstaller warnings etc.) is tolerated.
        }
    });

    let hs = rx
        .recv_timeout(HANDSHAKE_TIMEOUT)
        .map_err(|_| "backend produced no startup handshake in time".to_string())?;
    if hs["event"] == "error" {
        let msg = hs["message"].as_str().unwrap_or("unknown backend error").to_string();
        let _ = child.kill();
        return Err(format!("backend refused to start: {msg}"));
    }
    let port = hs["port"].as_u64().filter(|p| (1025..=65535).contains(p)).ok_or_else(|| {
        let _ = child.kill();
        "backend handshake carried no valid port".to_string()
    })? as u16;

    Ok((child, port))
}

fn wait_healthy(port: u16, token: &str) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{port}/api/desktop/health");
    let deadline = Instant::now() + HEALTH_TIMEOUT;
    while Instant::now() < deadline {
        let resp = ureq::get(&url)
            .set("X-SmartDocs-Token", token)
            .timeout(Duration::from_secs(2))
            .call();
        if let Ok(r) = resp {
            if r.status() == 200 {
                return Ok(());
            }
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    Err("backend did not become healthy in time".into())
}

/// Injected into every page this window loads (splash and the local backend).
/// Adds the launch token to /api requests on the app's own origins only.
fn init_script(token: &str) -> String {
    format!(
        r#"(function () {{
  var host = location.hostname, proto = location.protocol;
  var trusted = host === "127.0.0.1" || host === "localhost" ||
                host === "tauri.localhost" || proto === "tauri:";
  if (!trusted) return;
  var TOKEN = "{token}";
  Object.defineProperty(window, "__SMARTDOCS_DESKTOP__", {{
    value: Object.freeze({{ desktop: true, token: TOKEN }}),
    writable: false, configurable: false
  }});
  var isApi = function (u) {{
    return typeof u === "string" &&
      (u.indexOf("/api/") === 0 || u.indexOf(location.origin + "/api/") === 0);
  }};
  var origFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {{
    try {{
      var url = (typeof input === "string") ? input : ((input && input.url) || "");
      if (isApi(url)) {{
        init = init || {{}};
        var h = new Headers(init.headers || (input && input.headers) || undefined);
        h.set("X-SmartDocs-Token", TOKEN);
        init.headers = h;
      }}
    }} catch (e) {{}}
    return origFetch(input, init);
  }};
  var xo = XMLHttpRequest.prototype.open, xs = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) {{
    this.__sdApi = isApi(u);
    return xo.apply(this, arguments);
  }};
  XMLHttpRequest.prototype.send = function () {{
    if (this.__sdApi) {{ try {{ this.setRequestHeader("X-SmartDocs-Token", TOKEN); }} catch (e) {{}} }}
    return xs.apply(this, arguments);
  }};
}})();"#
    )
}

fn splash_status(app: &tauri::AppHandle, msg: &str, error: bool) {
    if let Some(w) = app.get_webview_window("main") {
        let f = if error { "__splashError" } else { "__splashStatus" };
        let _ = w.eval(&format!("window.{f} && window.{f}({});",
                                serde_json::to_string(msg).unwrap_or_default()));
    }
}

/// Graceful → forced shutdown ladder. Idempotent (child is take()n).
fn stop_sidecar(state: &Sidecar) {
    let Some(mut child) = state.child.lock().unwrap().take() else { return };
    if let Some(port) = *state.port.lock().unwrap() {
        let _ = ureq::post(&format!("http://127.0.0.1:{port}/api/desktop/shutdown"))
            .set("X-SmartDocs-Token", &state.token)
            .timeout(Duration::from_secs(3))
            .call();
    }
    let deadline = Instant::now() + GRACEFUL_EXIT_WAIT;
    while Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(_)) => return, // exited gracefully
            Ok(None) => std::thread::sleep(Duration::from_millis(150)),
            Err(_) => break,
        }
    }
    let _ = child.kill(); // bounded escalation — no orphans
    let _ = child.wait();
}

fn main() {
    let token = new_token();
    let sidecar = Arc::new(Sidecar {
        child: Mutex::new(None),
        port: Mutex::new(None),
        token: token.clone(),
    });

    let nav_port: Arc<Mutex<Option<u16>>> = Arc::new(Mutex::new(None));

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .manage(sidecar.clone())
        .setup({
            let sidecar = sidecar.clone();
            let nav_port = nav_port.clone();
            move |app| {
                let allow_port = nav_port.clone();
                let window = WebviewWindowBuilder::new(
                    app,
                    "main",
                    WebviewUrl::App("index.html".into()),
                )
                .title("SmartDocs")
                .inner_size(1280.0, 860.0)
                .min_inner_size(760.0, 560.0)
                .initialization_script(&init_script(&sidecar.token))
                .on_navigation(move |url: &Url| {
                    // Allowlist: the bundled splash and exactly our backend.
                    match url.scheme() {
                        "tauri" => true,
                        "http" | "https" => {
                            let host = url.host_str().unwrap_or("");
                            if host == "tauri.localhost" {
                                return true; // Windows asset origin
                            }
                            host == "127.0.0.1"
                                && url.port() == *allow_port.lock().unwrap()
                        }
                        _ => false,
                    }
                })
                .build()?;

                let handle = app.handle().clone();
                let sidecar = sidecar.clone();
                let nav_port = nav_port.clone();
                std::thread::spawn(move || {
                    splash_status(&handle, "Starting local backend…", false);
                    match start_sidecar(&handle, &sidecar.token) {
                        Ok((child, port)) => {
                            *sidecar.child.lock().unwrap() = Some(child);
                            *sidecar.port.lock().unwrap() = Some(port);
                            *nav_port.lock().unwrap() = Some(port);
                            splash_status(&handle, "Waiting for backend…", false);
                            match wait_healthy(port, &sidecar.token) {
                                Ok(()) => {
                                    let boot: Url =
                                        format!("http://127.0.0.1:{port}/desktop/boot")
                                            .parse()
                                            .expect("valid boot url");
                                    if let Some(w) = handle.get_webview_window("main") {
                                        let _ = w.navigate(boot);
                                    }
                                }
                                Err(e) => {
                                    splash_status(&handle, &format!(
                                        "Backend failed its health check.\n{e}"), true);
                                    stop_sidecar(&sidecar);
                                }
                            }
                        }
                        Err(e) => splash_status(&handle, &format!(
                            "Could not start the SmartDocs backend.\n{e}"), true),
                    }
                });

                let _ = window; // window lives in the app; nothing else to do
                Ok(())
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building SmartDocs desktop");

    // SIGINT/SIGTERM (logout, kill, Ctrl-C in dev) funnel into Tauri's exit
    // flow so RunEvent::Exit fires and the sidecar is stopped cleanly.
    {
        let handle = app.handle().clone();
        let _ = ctrlc::set_handler(move || handle.exit(0));
    }

    let sidecar_for_events = sidecar.clone();
    app.run(move |_handle, event| match event {
        RunEvent::ExitRequested { .. } | RunEvent::Exit => {
            stop_sidecar(&sidecar_for_events);
        }
        _ => {}
    });
}
