// SmartDocs desktop shell.
//
// Owns the backend for the whole application session, in one of three
// user-selectable runtime modes (see runtime.rs / desktop/splash launcher):
//   bundled   spawn the packaged PyInstaller sidecar (default)
//   external  spawn desktop_server.py with the Python venv of an existing
//             SmartDocs WebApp checkout (+ the GLM MLX helper when
//             applicable), reusing its models via controlled env vars
//   remote    spawn ONLY the stdlib UI gateway (SMARTDOCS_GATEWAY_ONLY=1)
//             pointed at a SmartDocs server URL — no OCR/LLM/GLM/DB/
//             processing backend ever starts in this mode
//
// In every mode the WebView shows the DesktopApp's own frontend from the
// local UI gateway origin (http://127.0.0.1:<port>); switching modes only
// changes the gateway's upstream. The WebView is never navigated to a
// remote server's HTML interface.
//
// The runtime selector stays reachable independently of any backend: the
// native “Backend Runtime…” menu item (Cmd/Ctrl+,), the Change-backend
// button on error screens, and holding Option/Alt during startup.
//
// Backends: token via stdin → {"event":"ready","port":N} handshake →
// /api/desktop/health poll → navigate. On exit: graceful shutdown endpoint →
// bounded wait → force-kill; the GLM helper gets SIGTERM → bounded wait →
// kill. Only processes this shell spawned are ever touched.
//
// The launch token is generated fresh per launch, passed to Python via stdin,
// injected into the WebView as an initialization script, and never persisted
// or logged.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod runtime;

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder};

use runtime::{BackendMode, RuntimeConfig, StartGuard, StartPlan};

const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(90);
// External runtimes import the full ML stack — allow a slower first health.
const HEALTH_TIMEOUT: Duration = Duration::from_secs(60);
const GRACEFUL_EXIT_WAIT: Duration = Duration::from_secs(8);
const GLM_EXIT_WAIT: Duration = Duration::from_secs(5);
const GLM_DEFAULT_MODEL: &str = "mlx-community/GLM-OCR-bf16";

struct BackendState {
    token: String,
    child: Mutex<Option<Child>>,
    glm: Mutex<Option<Child>>,
    port: Mutex<Option<u16>>,
    active_mode: Mutex<Option<BackendMode>>,
    /// "idle" | "starting" | "running" | "remote" | "error: …" | "stopped"
    status: Mutex<String>,
    starting: StartGuard,
}

/// What the WebView may navigate to: the bundled launcher plus exactly one
/// LOCAL gateway origin. There is deliberately no remote entry — remote
/// servers are reached only through the local gateway's proxy, so the
/// WebView can never land on a remote HTML interface (and a redirect from a
/// private address to a public one is refused here instead of followed).
#[derive(Default)]
struct NavRule {
    local_port: Option<u16>,
}

fn new_token() -> String {
    let mut buf = [0u8; 32];
    getrandom::getrandom(&mut buf).expect("OS RNG unavailable");
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

fn is_windows() -> bool {
    cfg!(windows)
}

fn mlx_supported() -> bool {
    cfg!(all(target_os = "macos", target_arch = "aarch64"))
}

// ── startup runtime-selector override (hold Option/Alt while launching) ─────

/// True when the user is holding Option/Alt at startup (or forces the
/// selector via SMARTDOCS_FORCE_RUNTIME_SELECTOR=1) — the shell then opens
/// the runtime selector instead of auto-starting the saved backend.
fn startup_selector_forced() -> bool {
    if std::env::var("SMARTDOCS_FORCE_RUNTIME_SELECTOR").ok().as_deref() == Some("1") {
        return true;
    }
    platform_alt_down()
}

#[cfg(target_os = "macos")]
fn platform_alt_down() -> bool {
    // kCGEventFlagMaskAlternate on the combined session event state.
    #[link(name = "CoreGraphics", kind = "framework")]
    extern "C" {
        fn CGEventSourceFlagsState(state_id: i32) -> u64;
    }
    const K_CG_EVENT_SOURCE_STATE_COMBINED: i32 = 0;
    const MASK_ALTERNATE: u64 = 1 << 19;
    unsafe { CGEventSourceFlagsState(K_CG_EVENT_SOURCE_STATE_COMBINED) & MASK_ALTERNATE != 0 }
}

#[cfg(windows)]
fn platform_alt_down() -> bool {
    #[link(name = "user32")]
    extern "system" {
        fn GetAsyncKeyState(v_key: i32) -> i16;
    }
    const VK_MENU: i32 = 0x12; // either Alt key
    unsafe { (GetAsyncKeyState(VK_MENU) as u16) & 0x8000 != 0 }
}

#[cfg(all(unix, not(target_os = "macos")))]
fn platform_alt_down() -> bool {
    // X11 keymap via dlopen — no link-time dependency; returns false on
    // Wayland-only/headless systems (menu item, Ctrl+, and the error-screen
    // button remain as recovery paths there).
    type XOpenDisplayFn = unsafe extern "C" fn(*const libc::c_char) -> *mut libc::c_void;
    type XQueryKeymapFn = unsafe extern "C" fn(*mut libc::c_void, *mut libc::c_char) -> libc::c_int;
    type XKeysymToKeycodeFn = unsafe extern "C" fn(*mut libc::c_void, libc::c_ulong) -> libc::c_uchar;
    type XCloseDisplayFn = unsafe extern "C" fn(*mut libc::c_void) -> libc::c_int;
    const XK_ALT_L: libc::c_ulong = 0xFFE9;
    const XK_ALT_R: libc::c_ulong = 0xFFEA;
    unsafe {
        let lib = libc::dlopen(b"libX11.so.6\0".as_ptr().cast(), libc::RTLD_LAZY);
        if lib.is_null() {
            return false;
        }
        let open_p = libc::dlsym(lib, b"XOpenDisplay\0".as_ptr().cast());
        let query_p = libc::dlsym(lib, b"XQueryKeymap\0".as_ptr().cast());
        let code_p = libc::dlsym(lib, b"XKeysymToKeycode\0".as_ptr().cast());
        let close_p = libc::dlsym(lib, b"XCloseDisplay\0".as_ptr().cast());
        if open_p.is_null() || query_p.is_null() || code_p.is_null() || close_p.is_null() {
            libc::dlclose(lib);
            return false;
        }
        let x_open: XOpenDisplayFn = std::mem::transmute(open_p);
        let x_query: XQueryKeymapFn = std::mem::transmute(query_p);
        let x_code: XKeysymToKeycodeFn = std::mem::transmute(code_p);
        let x_close: XCloseDisplayFn = std::mem::transmute(close_p);
        let dpy = x_open(std::ptr::null());
        if dpy.is_null() {
            libc::dlclose(lib);
            return false;
        }
        let mut keys = [0 as libc::c_char; 32];
        x_query(dpy, keys.as_mut_ptr());
        let mut held = false;
        for keysym in [XK_ALT_L, XK_ALT_R] {
            let code = x_code(dpy, keysym);
            if code != 0 {
                let byte = keys[(code / 8) as usize] as u8;
                if byte & (1u8 << (code % 8)) != 0 {
                    held = true;
                }
            }
        }
        x_close(dpy);
        libc::dlclose(lib);
        held
    }
}

fn config_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map_err(|e| format!("cannot resolve app config dir: {e}"))
}

// ── process spawning ─────────────────────────────────────────────────────────

/// Locate the bundled sidecar executable. Release builds only ever run the
/// bundled resource; dev builds may override via SMARTDOCS_SIDECAR_CMD (used
/// by scripts/dev-desktop.sh to run desktop_server.py from a venv).
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

    let exe_name = if is_windows() { "smartdocs-sidecar.exe" } else { "smartdocs-sidecar" };
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

/// The DesktopApp backend entry point shipped as a plain-Python resource
/// (desktop-shim/), for running against an external WebApp runtime.
fn shim_entry(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    if let Ok(p) = app
        .path()
        .resolve("desktop-shim/desktop_server.py", tauri::path::BaseDirectory::Resource)
    {
        if p.is_file() {
            return Ok(p);
        }
    }
    // Dev runs: use the repo copy next to src-tauri.
    #[cfg(debug_assertions)]
    {
        let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("desktop_server.py");
        if dev.is_file() {
            return Ok(dev);
        }
    }
    Err("desktop backend entry (desktop-shim) is missing from this install".into())
}

/// Build the external-runtime backend command: ONLY the validated venv
/// interpreter from inside the selected directory tree, with an explicit
/// argument list — never a shell string.
fn external_command(
    app: &tauri::AppHandle,
    root: &std::path::Path,
    python: &std::path::Path,
    report: &runtime::ValidationReport,
    glm_enabled: bool,
    glm_port: Option<u16>,
) -> Result<Command, String> {
    let entry = shim_entry(app)?;
    let mut cmd = Command::new(python);
    cmd.arg(entry).current_dir(root);
    for (k, v) in runtime::plan_external_env(root, report, glm_enabled, glm_port) {
        cmd.env(k, v);
    }
    Ok(cmd)
}

#[cfg(target_os = "linux")]
fn set_pdeathsig(cmd: &mut Command) {
    // Kernel-level orphan prevention: if this shell dies for ANY reason
    // (including SIGKILL), the child receives SIGTERM and shuts down.
    use std::os::unix::process::CommandExt;
    unsafe {
        cmd.pre_exec(|| {
            libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM);
            Ok(())
        });
    }
}
#[cfg(not(target_os = "linux"))]
fn set_pdeathsig(_cmd: &mut Command) {}

/// Spawn a backend process and wait for its one-line JSON handshake.
fn spawn_backend(
    mut cmd: Command,
    app: &tauri::AppHandle,
    token: &str,
    mode: BackendMode,
) -> Result<(Child, u16), String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("cannot resolve app data dir: {e}"))?;
    std::fs::create_dir_all(&data_dir)
        .map_err(|e| format!("cannot create {}: {e}", data_dir.display()))?;

    cmd.env("SMARTDOCS_DESKTOP", "1")
        .env("SMARTDOCS_TOKEN_STDIN", "1")
        .env("SMARTDOCS_DATA_DIR", &data_dir)
        .env("SMARTDOCS_RUNTIME_MODE", mode.as_str())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());
    set_pdeathsig(&mut cmd);

    let mut child = cmd.spawn().map_err(|e| format!("failed to start backend: {e}"))?;

    // Hand over the token on stdin — it never appears in argv or the env.
    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(format!("{token}\n").as_bytes())
            .and_then(|_| stdin.flush())
            .map_err(|e| format!("failed to pass token to backend: {e}"))?;
        // stdin drops here → EOF; the backend has already read its one line.
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

/// Reserve a free loopback port for the GLM helper (bind :0, read, release).
fn free_port() -> Result<u16, String> {
    std::net::TcpListener::bind(("127.0.0.1", 0))
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .map_err(|e| format!("cannot allocate a local port: {e}"))
}

/// Start the GLM MLX model server helper (Apple Silicon macOS, external mode
/// only). Mirrors tools/glm_serve.sh: with --model the port only opens once
/// the model is loaded, so the adapter's own probes are a truthful readiness
/// signal — the shell does not block the UI on it.
fn spawn_glm_helper(
    root: &std::path::Path,
    mlx_python: &std::path::Path,
    port: u16,
) -> Result<Child, String> {
    let mut cmd = Command::new(mlx_python);
    cmd.arg("-m")
        .arg("mlx_vlm.server")
        .arg("--trust-remote-code")
        .arg("--port")
        .arg(port.to_string())
        .arg("--model")
        .arg(GLM_DEFAULT_MODEL)
        .current_dir(root.join("GLM-OCR"))
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    for (k, v) in runtime::glm_helper_env(root) {
        cmd.env(k, v);
    }
    set_pdeathsig(&mut cmd);
    cmd.spawn().map_err(|e| format!("failed to start GLM helper: {e}"))
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

// ── remote server probing ────────────────────────────────────────────────────

/// Classify a SmartDocs server URL without any credentials. The WebApp has no
/// unauthenticated health endpoint, but its 401 JSON envelope on /api/auth/me
/// ({"success":false,…,"redirect":"/login"}) is a reliable fingerprint.
fn probe_remote(url: &Url) -> serde_json::Value {
    let probe = url.join("api/auth/me").map(|u| u.to_string());
    let probe = match probe {
        Ok(p) => p,
        Err(_) => return serde_json::json!({"state":"invalid_url","message":"URL cannot be probed"}),
    };
    let verdict = |state: &str, message: String| serde_json::json!({
        "state": state, "message": message, "https": url.scheme() == "https",
    });
    let fingerprint = |body: String, code: u16| -> serde_json::Value {
        let v: Option<serde_json::Value> = serde_json::from_str(&body).ok();
        let is_smartdocs = v
            .as_ref()
            .map(|j| j.get("success").is_some() && (j.get("redirect").is_some() || j.get("username").is_some() || j.get("error").is_some()))
            .unwrap_or(false);
        if !is_smartdocs {
            return verdict(
                "incompatible",
                format!("the server answered (HTTP {code}) but does not look like a \
                         SmartDocs API — wrong URL or incompatible server version"),
            );
        }
        if code == 200 {
            verdict("ok", "SmartDocs server reachable".into())
        } else {
            verdict(
                "auth_required",
                "SmartDocs server reachable — you will sign in when it opens".into(),
            )
        }
    };
    match ureq::get(&probe).timeout(Duration::from_secs(8)).call() {
        Ok(r) => {
            let code = r.status();
            let body = r.into_string().unwrap_or_default();
            fingerprint(body, code)
        }
        Err(ureq::Error::Status(code, r)) => {
            let body = r.into_string().unwrap_or_default();
            fingerprint(body, code)
        }
        Err(ureq::Error::Transport(t)) => {
            let msg = t.to_string();
            let lower = msg.to_lowercase();
            if lower.contains("certificate") || lower.contains("tls") || lower.contains("handshake") {
                verdict("tls_error", format!("TLS/certificate problem: {msg}"))
            } else {
                verdict("unreachable", format!("server unreachable: {msg}"))
            }
        }
    }
}

// ── injected page bridge ─────────────────────────────────────────────────────

/// Injected into every page this window loads (splash and the local gateway
/// origin). Adds the launch token to /api requests on the app's own origins
/// only. In remote mode the gateway strips this header before forwarding, so
/// the token never leaves the machine.
fn init_script(token: &str) -> String {
    format!(
        r#"(function () {{
  var host = location.hostname, proto = location.protocol;
  var trusted = host === "127.0.0.1" || host === "localhost" ||
                host === "tauri.localhost" || proto === "tauri:";
  if (!trusted) return;
  var TOKEN = "{token}";
  Object.defineProperty(window, "__SMARTDOCS_DESKTOP__", {{
    value: Object.freeze({{ desktop: true, token: TOKEN,
                            runtimeSettings: "/desktop/runtime-settings" }}),
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

/// Open the launcher's runtime selector (optionally carrying the error that
/// brought the user there). Recovery guarantee: a failed/invalid saved
/// backend never traps the user — the selector appears with the current
/// configuration intact, ready to be corrected, retried, or switched.
fn open_runtime_selector(app: &tauri::AppHandle, error: Option<&str>) {
    navigate(app, launcher_url("#runtime"));
    if let Some(w) = app.get_webview_window("main") {
        let msg = serde_json::to_string(error.unwrap_or("")).unwrap_or_default();
        let _ = w.eval(&format!("window.__openRuntime && window.__openRuntime({msg});"));
    }
}

/// The bundled launcher page (splash + runtime settings), per-platform origin.
fn launcher_url(fragment: &str) -> Url {
    let base = if is_windows() {
        format!("http://tauri.localhost/index.html{fragment}")
    } else {
        format!("tauri://localhost/index.html{fragment}")
    };
    base.parse().expect("valid launcher url")
}

fn navigate(app: &tauri::AppHandle, url: Url) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.navigate(url);
    }
}

// ── lifecycle ────────────────────────────────────────────────────────────────

/// Graceful → forced shutdown ladder for everything WE spawned. Idempotent
/// (children are take()n); never touches processes this shell did not start.
fn stop_all(state: &BackendState) {
    // GLM helper first (it depends on nothing).
    if let Some(mut glm) = state.glm.lock().unwrap().take() {
        #[cfg(unix)]
        unsafe {
            libc::kill(glm.id() as i32, libc::SIGTERM);
        }
        let deadline = Instant::now() + GLM_EXIT_WAIT;
        loop {
            match glm.try_wait() {
                Ok(Some(_)) => break,
                Ok(None) if Instant::now() < deadline => {
                    std::thread::sleep(Duration::from_millis(150))
                }
                _ => {
                    let _ = glm.kill();
                    let _ = glm.wait();
                    break;
                }
            }
        }
    }

    let Some(mut child) = state.child.lock().unwrap().take() else {
        *state.status.lock().unwrap() = "stopped".into();
        return;
    };
    if let Some(port) = *state.port.lock().unwrap() {
        let _ = ureq::post(&format!("http://127.0.0.1:{port}/api/desktop/shutdown"))
            .set("X-SmartDocs-Token", &state.token)
            .timeout(Duration::from_secs(3))
            .call();
    }
    let deadline = Instant::now() + GRACEFUL_EXIT_WAIT;
    let mut exited = false;
    while Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(_)) => {
                exited = true;
                break;
            }
            Ok(None) => std::thread::sleep(Duration::from_millis(150)),
            Err(_) => break,
        }
    }
    if !exited {
        let _ = child.kill(); // bounded escalation — no orphans
        let _ = child.wait();
    }
    *state.port.lock().unwrap() = None;
    *state.status.lock().unwrap() = "stopped".into();
}

/// Start (or restart) the configured backend. Refuses to run twice
/// concurrently; always releases the guard.
fn start_backend(
    handle: tauri::AppHandle,
    state: Arc<BackendState>,
    nav: Arc<Mutex<NavRule>>,
) {
    if !state.starting.try_acquire() {
        return; // a start/restart is already in flight — no duplicates
    }
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        run_start(&handle, &state, &nav)
    }));
    state.starting.release();
    if let Err(_panic) = result {
        *state.status.lock().unwrap() = "error: internal startup failure".into();
        splash_status(&handle, "Internal startup failure.", true);
    }
}

fn run_start(
    handle: &tauri::AppHandle,
    state: &Arc<BackendState>,
    nav: &Arc<Mutex<NavRule>>,
) {
    let cfg_dir = match config_dir(handle) {
        Ok(d) => d,
        Err(e) => {
            *state.status.lock().unwrap() = format!("error: {e}");
            splash_status(handle, &e, true);
            return;
        }
    };
    let cfg = RuntimeConfig::load(&cfg_dir);
    *state.active_mode.lock().unwrap() = Some(cfg.mode);
    *state.status.lock().unwrap() = "starting".into();

    let fail = |msg: String| {
        *state.status.lock().unwrap() = format!("error: {msg}");
        splash_status(handle, &msg, true);
        // Never trap the user on a failed backend: surface the selector with
        // the saved configuration preserved for correction/retry.
        open_runtime_selector(handle, Some(&msg));
    };

    let plan = match runtime::start_plan(&cfg, is_windows(), mlx_supported()) {
        Ok(p) => p,
        Err(e) => return fail(e),
    };

    match plan {
        StartPlan::ServeRemote { upstream, policy } => {
            splash_status(handle, "Checking the SmartDocs server…", false);
            let probe = probe_remote(&upstream);
            let st = probe["state"].as_str().unwrap_or("unreachable");
            if st != "ok" && st != "auth_required" {
                return fail(
                    probe["message"].as_str().unwrap_or("server check failed").to_string(),
                );
            }
            splash_status(handle, "Starting the SmartDocs desktop UI…", false);
            // The gateway-only entry: same sidecar binary, but the env flag
            // routes desktop_server.py into desktop_gateway BEFORE any
            // Flask/app/DB import — no processing service can start.
            let mut cmd = match sidecar_command(handle) {
                Ok(c) => c,
                Err(e) => return fail(format!("Could not start the desktop UI. {e}")),
            };
            cmd.env("SMARTDOCS_GATEWAY_ONLY", "1")
                .env("SMARTDOCS_GATEWAY_UPSTREAM", upstream.as_str())
                .env(
                    "SMARTDOCS_GATEWAY_INSECURE",
                    if policy == runtime::RemotePolicy::HttpInsecureLan { "1" } else { "0" },
                );
            finish_local_start(handle, state, nav, cmd, BackendMode::Remote);
        }
        StartPlan::SpawnBundled => {
            splash_status(handle, "Starting local backend…", false);
            let cmd = match sidecar_command(handle) {
                Ok(c) => c,
                Err(e) => return fail(format!("Could not start the SmartDocs backend. {e}")),
            };
            finish_local_start(handle, state, nav, cmd, BackendMode::Bundled);
        }
        StartPlan::SpawnExternal { root, python, report } => {
            splash_status(handle, "Starting the SmartDocs WebApp runtime…", false);
            // GLM MLX helper first (loads slowly; the backend's adapter
            // health-checks it per request, so no UI blocking on it).
            let mut glm_port = None;
            if mlx_supported() && cfg.glm_enabled {
                if let Some(mlx) = report.glm_mlx_python.clone() {
                    match free_port().and_then(|p| spawn_glm_helper(&root, &mlx, p).map(|c| (p, c))) {
                        Ok((p, child)) => {
                            *state.glm.lock().unwrap() = Some(child);
                            glm_port = Some(p);
                        }
                        Err(e) => eprintln!("[shell] GLM helper not started: {e}"),
                    }
                }
            }
            let cmd = match external_command(handle, &root, &python, &report,
                                             cfg.glm_enabled, glm_port) {
                Ok(c) => c,
                Err(e) => return fail(e),
            };
            finish_local_start(handle, state, nav, cmd, BackendMode::External);
        }
    }
}

fn finish_local_start(
    handle: &tauri::AppHandle,
    state: &Arc<BackendState>,
    nav: &Arc<Mutex<NavRule>>,
    cmd: Command,
    mode: BackendMode,
) {
    match spawn_backend(cmd, handle, &state.token, mode) {
        Ok((child, port)) => {
            *state.child.lock().unwrap() = Some(child);
            *state.port.lock().unwrap() = Some(port);
            nav.lock().unwrap().local_port = Some(port);
            splash_status(handle, "Waiting for the backend…", false);
            match wait_healthy(port, &state.token) {
                Ok(()) => {
                    *state.status.lock().unwrap() = if mode == BackendMode::Remote {
                        "remote".into()
                    } else {
                        "running".into()
                    };
                    // Local backends bootstrap the cookie session on
                    // /desktop/boot; remote mode signs in through the
                    // gateway-proxied /login instead.
                    let entry = if mode == BackendMode::Remote { "" } else { "desktop/boot" };
                    let url: Url = format!("http://127.0.0.1:{port}/{entry}")
                        .parse()
                        .expect("valid entry url");
                    navigate(handle, url);
                }
                Err(e) => {
                    let msg = format!("Backend failed its health check. {e}");
                    *state.status.lock().unwrap() = format!("error: {msg}");
                    splash_status(handle, &msg, true);
                    stop_all(state);
                    open_runtime_selector(handle, Some(&msg));
                }
            }
        }
        Err(e) => {
            let msg = format!("Could not start the SmartDocs backend. {e}");
            *state.status.lock().unwrap() = format!("error: {msg}");
            splash_status(handle, &msg, true);
            stop_all(state); // reap the GLM helper if it was already up
            open_runtime_selector(handle, Some(&msg));
        }
    }
}

// ── IPC commands (callable ONLY from the bundled launcher page: Tauri's ACL
//    rejects app commands from remote origins, and the local backend origin
//    is remote in ACL terms) ──────────────────────────────────────────────────

#[tauri::command]
fn runtime_get_state(
    app: tauri::AppHandle,
    state: tauri::State<'_, Arc<BackendState>>,
) -> serde_json::Value {
    let cfg = config_dir(&app).map(|d| RuntimeConfig::load(&d)).unwrap_or_default();
    serde_json::json!({
        "config": cfg.to_json(),
        "status": state.status.lock().unwrap().clone(),
        "active_mode": (*state.active_mode.lock().unwrap()).map(|m| m.as_str()),
        "port": *state.port.lock().unwrap(),
        "platform": {
            "os": std::env::consts::OS,
            "arch": std::env::consts::ARCH,
            "windows": is_windows(),
            "mlx_supported": mlx_supported(),
        },
    })
}

#[tauri::command]
async fn runtime_pick_folder(app: tauri::AppHandle) -> Option<String> {
    use tauri_plugin_dialog::DialogExt;
    app.dialog()
        .file()
        .blocking_pick_folder()
        .and_then(|p| p.into_path().ok())
        .map(|p| p.display().to_string())
}

#[tauri::command]
fn runtime_validate(path: String) -> serde_json::Value {
    runtime::validate_external_runtime(
        std::path::Path::new(&path),
        is_windows(),
        mlx_supported(),
        true,
    )
    .to_json()
}

#[tauri::command]
async fn runtime_test_remote(url: String, allow_insecure_lan: Option<bool>) -> serde_json::Value {
    match runtime::check_remote_url(&url, allow_insecure_lan.unwrap_or(false)) {
        Ok((u, policy)) => {
            let mut v = probe_remote(&u);
            v["insecure_lan"] =
                (policy == runtime::RemotePolicy::HttpInsecureLan).into();
            v
        }
        Err(e) => serde_json::json!({"state": "invalid_url", "message": e}),
    }
}

#[tauri::command]
fn runtime_apply(
    app: tauri::AppHandle,
    state: tauri::State<'_, Arc<BackendState>>,
    nav: tauri::State<'_, Arc<Mutex<NavRule>>>,
    config: serde_json::Value,
) -> Result<(), String> {
    let cfg = RuntimeConfig::from_json(&config.to_string())
        .ok_or("invalid runtime configuration")?;
    // Fail early with a precise reason instead of a doomed restart.
    runtime::start_plan(&cfg, is_windows(), mlx_supported()).map_err(|e| e.to_string())?;
    cfg.save(&config_dir(&app)?)?;

    let state = state.inner().clone();
    let nav = nav.inner().clone();
    std::thread::spawn(move || {
        stop_all(&state);
        navigate(&app, launcher_url(""));
        start_backend(app, state, nav);
    });
    Ok(())
}

/// Return to whatever backend is currently active (launcher “Cancel”).
#[tauri::command]
fn runtime_resume(
    app: tauri::AppHandle,
    state: tauri::State<'_, Arc<BackendState>>,
) -> Result<(), String> {
    if let Some(port) = *state.port.lock().unwrap() {
        let entry = match *state.active_mode.lock().unwrap() {
            Some(BackendMode::Remote) => "",
            _ => "desktop/boot",
        };
        navigate(&app, format!("http://127.0.0.1:{port}/{entry}").parse().unwrap());
        return Ok(());
    }
    Err("no backend is running".into())
}

// ── main ─────────────────────────────────────────────────────────────────────

fn main() {
    let token = new_token();
    let state = Arc::new(BackendState {
        token: token.clone(),
        child: Mutex::new(None),
        glm: Mutex::new(None),
        port: Mutex::new(None),
        active_mode: Mutex::new(None),
        status: Mutex::new("idle".into()),
        starting: StartGuard::new(),
    });
    let nav: Arc<Mutex<NavRule>> = Arc::new(Mutex::new(NavRule::default()));

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .manage(state.clone())
        .manage(nav.clone())
        .invoke_handler(tauri::generate_handler![
            runtime_get_state,
            runtime_pick_folder,
            runtime_validate,
            runtime_test_remote,
            runtime_apply,
            runtime_resume,
        ])
        .setup({
            let state = state.clone();
            let nav = nav.clone();
            move |app| {
                let nav_rule = nav.clone();
                let nav_handle = app.handle().clone();
                let window = WebviewWindowBuilder::new(
                    app,
                    "main",
                    WebviewUrl::App("index.html".into()),
                )
                .title("SmartDocs")
                .inner_size(1280.0, 860.0)
                .min_inner_size(760.0, 560.0)
                .initialization_script(&init_script(&state.token))
                .on_navigation(move |url: &Url| {
                    // Allowlist: the bundled launcher and exactly the active
                    // LOCAL gateway origin. Remote servers are only ever
                    // reached through the gateway's proxy, so no remote (or
                    // redirect-target) origin is ever navigable.
                    match url.scheme() {
                        "tauri" => true,
                        "http" | "https" => {
                            let host = url.host_str().unwrap_or("");
                            if host == "tauri.localhost" {
                                return true; // Windows asset origin
                            }
                            let rule = nav_rule.lock().unwrap();
                            if let Some(p) = rule.local_port {
                                if host == "127.0.0.1" && url.port() == Some(p) {
                                    if url.path() == "/desktop/runtime-settings" {
                                        // In-app “Manage backend runtime” link:
                                        // open the bundled launcher instead.
                                        let h = nav_handle.clone();
                                        std::thread::spawn(move || {
                                            navigate(&h, launcher_url("#runtime"));
                                        });
                                        return false;
                                    }
                                    return true;
                                }
                            }
                            false
                        }
                        _ => false,
                    }
                })
                .build()?;

                // Native, backend-independent access to the runtime selector:
                // “Backend Runtime…” with Cmd+, (macOS) / Ctrl+, (Win/Linux),
                // appended to the platform's default menu (edit/copy/paste
                // etc. stay intact).
                {
                    use tauri::menu::{Menu, MenuItemBuilder, SubmenuBuilder};
                    let item = MenuItemBuilder::with_id("backend-runtime", "Backend Runtime…")
                        .accelerator("CmdOrCtrl+,")
                        .build(app)?;
                    let submenu = SubmenuBuilder::new(app, "Backend").item(&item).build()?;
                    let menu = Menu::default(app.handle())?;
                    menu.append(&submenu)?;
                    app.set_menu(menu)?;
                }

                let handle = app.handle().clone();
                let state = state.clone();
                let nav = nav.clone();
                if startup_selector_forced() {
                    // Option/Alt held during launch: open the selector
                    // instead of auto-starting the saved backend. runtime.json
                    // is left untouched — the user corrects or confirms it
                    // from here and applies.
                    *state.status.lock().unwrap() = "idle".into();
                    std::thread::spawn(move || {
                        std::thread::sleep(Duration::from_millis(200));
                        open_runtime_selector(&handle, None);
                    });
                } else {
                    std::thread::spawn(move || start_backend(handle, state, nav));
                }

                let _ = window; // window lives in the app; nothing else to do
                Ok(())
            }
        })
        .on_menu_event(|app, event| {
            if event.id().0 == "backend-runtime" {
                open_runtime_selector(app, None);
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building SmartDocs desktop");

    // SIGINT/SIGTERM (logout, kill, Ctrl-C in dev) funnel into Tauri's exit
    // flow so RunEvent::Exit fires and the backend is stopped cleanly.
    {
        let handle = app.handle().clone();
        let _ = ctrlc::set_handler(move || handle.exit(0));
    }

    let state_for_events = state.clone();
    app.run(move |_handle, event| match event {
        RunEvent::ExitRequested { .. } | RunEvent::Exit => {
            stop_all(&state_for_events);
        }
        _ => {}
    });
}
