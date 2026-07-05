// Backend runtime modes — pure, unit-testable core.
//
// Three modes (persisted in runtime.json inside the Tauri app-config dir):
//   bundled   – the PyInstaller sidecar shipped inside the install (default)
//   external  – an existing SmartDocs WebApp checkout: its venv Python runs
//               the DesktopApp entry point (desktop_server.py), reusing the
//               WebApp's models and GLM runtimes via controlled env vars
//   remote    – a SmartDocs server URL; only the lightweight local UI
//               gateway runs (no OCR/LLM/GLM/DB/processing backend)
//
// Everything here is deliberately free of Tauri/process side effects so the
// mode selection, layout validation, URL policy and env planning can be
// tested on any platform with plain `cargo test`.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BackendMode {
    Bundled,
    External,
    Remote,
}

impl BackendMode {
    pub fn as_str(&self) -> &'static str {
        match self {
            BackendMode::Bundled => "bundled",
            BackendMode::External => "external",
            BackendMode::Remote => "remote",
        }
    }
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "bundled" => Some(BackendMode::Bundled),
            "external" => Some(BackendMode::External),
            "remote" => Some(BackendMode::Remote),
            _ => None,
        }
    }
}

/// Persisted runtime selection. Contains NO secrets — only the mode, the
/// chosen WebApp directory, the server URL, the GLM preference and the
/// insecure-LAN preference + its acknowledgement state. Authentication
/// tokens/credentials never live here (cloud keys stay in the OS credential
/// store; server sign-in is a session cookie inside the WebView).
#[derive(Clone, Debug)]
pub struct RuntimeConfig {
    pub mode: BackendMode,
    pub external_path: Option<String>,
    pub remote_url: Option<String>,
    pub glm_enabled: bool,
    /// Opt-in: plain HTTP to private-LAN IP literals (OFF by default).
    pub allow_insecure_lan: bool,
    /// The user confirmed the insecure-LAN warning once.
    pub insecure_lan_ack: bool,
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        RuntimeConfig {
            mode: BackendMode::Bundled,
            external_path: None,
            remote_url: None,
            glm_enabled: true,
            allow_insecure_lan: false,
            insecure_lan_ack: false,
        }
    }
}

impl RuntimeConfig {
    pub fn file_path(config_dir: &Path) -> PathBuf {
        config_dir.join("runtime.json")
    }

    /// Load from runtime.json; any missing/corrupt file falls back to the
    /// bundled default (never an error — the app must always start).
    pub fn load(config_dir: &Path) -> Self {
        let raw = match std::fs::read_to_string(Self::file_path(config_dir)) {
            Ok(s) => s,
            Err(_) => return Self::default(),
        };
        Self::from_json(&raw).unwrap_or_default()
    }

    pub fn from_json(raw: &str) -> Option<Self> {
        let v: serde_json::Value = serde_json::from_str(raw).ok()?;
        let mode = BackendMode::parse(v.get("mode")?.as_str()?)?;
        let s = |k: &str| {
            v.get(k)
                .and_then(|x| x.as_str())
                .map(str::trim)
                .filter(|x| !x.is_empty())
                .map(String::from)
        };
        let b = |k: &str, default: bool| {
            v.get(k).and_then(|x| x.as_bool()).unwrap_or(default)
        };
        Some(RuntimeConfig {
            mode,
            external_path: s("external_path"),
            remote_url: s("remote_url"),
            glm_enabled: b("glm_enabled", true),
            allow_insecure_lan: b("allow_insecure_lan", false),
            insecure_lan_ack: b("insecure_lan_ack", false),
        })
    }

    pub fn to_json(&self) -> serde_json::Value {
        serde_json::json!({
            "mode": self.mode.as_str(),
            "external_path": self.external_path,
            "remote_url": self.remote_url,
            "glm_enabled": self.glm_enabled,
            "allow_insecure_lan": self.allow_insecure_lan,
            "insecure_lan_ack": self.insecure_lan_ack,
        })
    }

    pub fn save(&self, config_dir: &Path) -> Result<(), String> {
        std::fs::create_dir_all(config_dir)
            .map_err(|e| format!("cannot create {}: {e}", config_dir.display()))?;
        let path = Self::file_path(config_dir);
        std::fs::write(&path, self.to_json().to_string())
            .map_err(|e| format!("cannot write {}: {e}", path.display()))
    }
}

// ── external runtime validation ──────────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct Component {
    pub name: &'static str,
    /// "ok" | "missing" | "unsupported"
    pub status: &'static str,
    pub required: bool,
    pub detail: String,
}

#[derive(Clone, Debug, Default)]
pub struct ValidationReport {
    pub ok: bool,
    pub python: Option<PathBuf>,
    pub glm_sdk_python: Option<PathBuf>,
    pub glm_mlx_python: Option<PathBuf>,
    pub components: Vec<Component>,
}

impl ValidationReport {
    pub fn to_json(&self) -> serde_json::Value {
        serde_json::json!({
            "ok": self.ok,
            "python": self.python.as_ref().map(|p| p.display().to_string()),
            "glm_sdk_python": self.glm_sdk_python.as_ref().map(|p| p.display().to_string()),
            "glm_mlx_python": self.glm_mlx_python.as_ref().map(|p| p.display().to_string()),
            "components": self.components.iter().map(|c| serde_json::json!({
                "name": c.name, "status": c.status,
                "required": c.required, "detail": c.detail,
            })).collect::<Vec<_>>(),
        })
    }
}

/// The interpreter inside a venv, per-platform.
pub fn venv_python(venv: &Path, windows: bool) -> PathBuf {
    if windows {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    }
}

fn existing_python(venv: &Path, windows: bool) -> Option<PathBuf> {
    let p = venv_python(venv, windows);
    if p.is_file() {
        return Some(p);
    }
    if !windows {
        let p3 = venv.join("bin").join("python3");
        if p3.is_file() {
            return Some(p3);
        }
    }
    None
}

/// Resolve the WebApp's Python: `<root>/.venv`, else the sibling layout
/// `<root>/../.venv` (the documented scripts/lib.sh resolution order).
pub fn find_runtime_python(root: &Path, windows: bool) -> Option<PathBuf> {
    if let Some(p) = existing_python(&root.join(".venv"), windows) {
        return Some(p);
    }
    root.parent()
        .and_then(|parent| existing_python(&parent.join(".venv"), windows))
}

/// Validate a user-selected directory as a SmartDocs WebApp installation.
/// `windows` and `mlx_supported` are parameters (not cfg!) so every platform
/// layout is testable from Linux.
pub fn validate_external_runtime(
    root: &Path,
    windows: bool,
    mlx_supported: bool,
    glm_enabled: bool,
) -> ValidationReport {
    let mut rep = ValidationReport::default();

    if !root.is_dir() {
        rep.components.push(Component {
            name: "directory",
            status: "missing",
            required: true,
            detail: format!("{} is not a directory", root.display()),
        });
        return rep;
    }

    // 1. venv Python (repo .venv, else sibling ../.venv)
    match find_runtime_python(root, windows) {
        Some(p) => {
            rep.components.push(Component {
                name: "python",
                status: "ok",
                required: true,
                detail: p.display().to_string(),
            });
            rep.python = Some(p);
        }
        None => rep.components.push(Component {
            name: "python",
            status: "missing",
            required: true,
            detail: format!(
                "no venv interpreter at {} (or the sibling ../.venv) — run the \
                 WebApp's setup first",
                venv_python(&root.join(".venv"), windows).display()
            ),
        }),
    }

    // 2. backend source files
    for (name, rel, is_dir) in [
        ("app.py", "app.py", false),
        ("config.py", "config.py", false),
        ("services/", "services", true),
        ("static/", "static", true),
    ] {
        let p = root.join(rel);
        let ok = if is_dir { p.is_dir() } else { p.is_file() };
        rep.components.push(Component {
            name,
            status: if ok { "ok" } else { "missing" },
            required: true,
            detail: if ok {
                String::new()
            } else {
                format!("expected {}", p.display())
            },
        });
    }

    // 3. model directory (optional but strongly recommended)
    let models = root.join("models");
    rep.components.push(Component {
        name: "models/",
        status: if models.is_dir() { "ok" } else { "missing" },
        required: false,
        detail: if models.is_dir() {
            models.display().to_string()
        } else {
            "no models directory — OCR/AI models will be unavailable until \
             the WebApp's model setup has been run"
                .into()
        },
    });

    // 4. GLM runtimes (optional). SDK CLI venv resolution mirrors config.py:
    //    prefer .venv-sdk, else the unified .venv-mlx.
    let glm_root = root.join("GLM-OCR");
    if glm_root.is_dir() {
        let sdk = existing_python(&glm_root.join(".venv-sdk"), windows)
            .or_else(|| existing_python(&glm_root.join(".venv-mlx"), windows));
        rep.components.push(Component {
            name: "GLM SDK runtime",
            status: if sdk.is_some() { "ok" } else { "missing" },
            required: false,
            detail: match &sdk {
                Some(p) => p.display().to_string(),
                None => "GLM-OCR/.venv-sdk not installed (scripts/setup_glm.sh) — \
                         the GLM OCR engine will report unavailable"
                    .into(),
            },
        });
        rep.glm_sdk_python = sdk;

        // MLX model server: Apple-Silicon macOS only.
        if !mlx_supported {
            rep.components.push(Component {
                name: "GLM MLX server",
                status: "unsupported",
                required: false,
                detail: "requires Apple Silicon macOS — not started on this platform".into(),
            });
        } else if glm_enabled {
            let mlx = existing_python(&glm_root.join(".venv-mlx"), windows);
            rep.components.push(Component {
                name: "GLM MLX server",
                status: if mlx.is_some() { "ok" } else { "missing" },
                required: false,
                detail: match &mlx {
                    Some(p) => p.display().to_string(),
                    None => "GLM-OCR/.venv-mlx not installed (scripts/setup_glm.sh)".into(),
                },
            });
            rep.glm_mlx_python = mlx;
        }
    } else {
        rep.components.push(Component {
            name: "GLM-OCR/",
            status: "missing",
            required: false,
            detail: "no GLM-OCR directory — GLM engine unavailable in this runtime".into(),
        });
    }

    rep.ok = rep
        .components
        .iter()
        .all(|c| !c.required || c.status == "ok");
    rep
}

// ── remote URL policy ─────────────────────────────────────────────────────────

fn is_local_host(host: &str) -> bool {
    let h = host.trim_start_matches('[').trim_end_matches(']');
    h.eq_ignore_ascii_case("localhost") || h == "127.0.0.1" || h == "::1"
}

/// RFC1918 IPv4 (10/8, 172.16/12, 192.168/16) or IPv6 unique-local (fc00::/7).
fn is_private_lan_ip(host: &str) -> bool {
    let h = host.trim_start_matches('[').trim_end_matches(']');
    if let Ok(v4) = h.parse::<std::net::Ipv4Addr>() {
        return v4.is_private();
    }
    if let Ok(v6) = h.parse::<std::net::Ipv6Addr>() {
        return (v6.segments()[0] & 0xfe00) == 0xfc00;
    }
    false
}

/// How a validated remote URL will be reached.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RemotePolicy {
    /// TLS — always allowed, never downgraded.
    Https,
    /// Plain HTTP to localhost/127.0.0.1/::1 — always allowed (development).
    HttpLocal,
    /// Plain HTTP to a private-LAN IP literal — allowed only with the
    /// explicit opt-in AND a confirmed warning; shown as insecure in the UI.
    HttpInsecureLan,
}

/// Remote-server URL policy.
///
/// * HTTPS: always accepted (and never silently downgraded to HTTP).
/// * HTTP: accepted for localhost/127.0.0.1/::1 unconditionally. With
///   `allow_insecure_lan`, additionally accepted for PRIVATE-RANGE IP
///   LITERALS ONLY (10/8, 172.16/12, 192.168/16, IPv6 unique-local). Plain
///   HTTP to hostnames is rejected even with the option on: an IP literal is
///   its own resolved destination, so there is no DNS step for a rebinding
///   attack to subvert, and public IPs/hostnames can never slip through.
/// * URLs with embedded credentials are refused outright.
pub fn check_remote_url(raw: &str, allow_insecure_lan: bool) -> Result<(tauri::Url, RemotePolicy), String> {
    let url: tauri::Url = raw
        .trim()
        .parse()
        .map_err(|_| "not a valid URL (expected e.g. https://smartdocs.example.com)".to_string())?;
    if url.host_str().unwrap_or("").is_empty() {
        return Err("URL has no host".into());
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err("credentials embedded in the URL are not allowed".into());
    }
    let host = url.host_str().unwrap_or("").to_string();
    let policy = match url.scheme() {
        "https" => RemotePolicy::Https,
        "http" if is_local_host(&host) => RemotePolicy::HttpLocal,
        "http" if is_private_lan_ip(&host) => {
            if !allow_insecure_lan {
                return Err(
                    "plain HTTP to a private LAN address requires enabling \
                     “Allow insecure HTTP on private LAN” — or use https://"
                        .into(),
                );
            }
            RemotePolicy::HttpInsecureLan
        }
        "http" => {
            return Err(
                "plain HTTP is only allowed for localhost or a private LAN IP \
                 address (10.x, 172.16–31.x, 192.168.x) — public addresses and \
                 hostnames require https://"
                    .into(),
            )
        }
        s => return Err(format!("unsupported scheme \"{s}\" — use http(s)://")),
    };
    Ok((url, policy))
}

// ── launch planning ───────────────────────────────────────────────────────────

/// What the shell must do for a config — computed WITHOUT side effects.
/// `ServeRemote` (remote mode) carries only the validated upstream URL and
/// its policy: the shell starts the lightweight local UI gateway pointed at
/// that URL — never OCR/LLM/GLM/database/document-processing services and
/// never the bundled processing backend (the gateway entry path exits before
/// any of that could be imported).
#[derive(Debug)]
pub enum StartPlan {
    SpawnBundled,
    SpawnExternal {
        root: PathBuf,
        python: PathBuf,
        report: ValidationReport,
    },
    ServeRemote {
        upstream: tauri::Url,
        policy: RemotePolicy,
    },
}

/// Error sentinel for a private-LAN HTTP URL that is allowed by the option
/// but has not had its warning confirmed yet. The launcher recognizes the
/// prefix and shows the confirmation UI instead of a plain error.
pub const INSECURE_ACK_REQUIRED: &str = "insecure-lan-ack-required";

pub fn start_plan(
    cfg: &RuntimeConfig,
    windows: bool,
    mlx_supported: bool,
) -> Result<StartPlan, String> {
    match cfg.mode {
        BackendMode::Bundled => Ok(StartPlan::SpawnBundled),
        BackendMode::External => {
            let root = PathBuf::from(
                cfg.external_path
                    .as_deref()
                    .ok_or("no WebApp runtime directory selected")?,
            );
            let report =
                validate_external_runtime(&root, windows, mlx_supported, cfg.glm_enabled);
            if !report.ok {
                let missing: Vec<&str> = report
                    .components
                    .iter()
                    .filter(|c| c.required && c.status != "ok")
                    .map(|c| c.name)
                    .collect();
                return Err(format!(
                    "the selected runtime is not a usable SmartDocs installation \
                     (missing: {})",
                    missing.join(", ")
                ));
            }
            let python = report.python.clone().expect("ok report has python");
            Ok(StartPlan::SpawnExternal { root, python, report })
        }
        BackendMode::Remote => {
            let (url, policy) = check_remote_url(
                cfg.remote_url
                    .as_deref()
                    .ok_or("no server URL configured")?,
                cfg.allow_insecure_lan,
            )?;
            if policy == RemotePolicy::HttpInsecureLan && !cfg.insecure_lan_ack {
                return Err(format!(
                    "{INSECURE_ACK_REQUIRED}: connecting over unencrypted HTTP \
                     to a private LAN address requires confirming the warning"
                ));
            }
            Ok(StartPlan::ServeRemote { upstream: url, policy })
        }
    }
}

/// Controlled env-var set for the external backend: model / HF / Argos /
/// VietOCR caches derive from MODEL_DIR inside the WebApp checkout (config.py
/// hard-sets HF_HOME, HF_HUB_CACHE, TRANSFORMERS_CACHE, ARGOS_PACKAGES_DIR
/// and the VietOCR weights default from it at import); GLM paths are passed
/// explicitly. DB_PATH/UPLOAD_DIR are NOT set here — they default to the
/// DesktopApp data dir (SMARTDOCS_DATA_DIR), keeping DesktopApp data separate
/// from the WebApp's database/uploads.
pub fn plan_external_env(
    root: &Path,
    report: &ValidationReport,
    glm_enabled: bool,
    glm_port: Option<u16>,
) -> Vec<(String, String)> {
    let mut env: Vec<(String, String)> = vec![
        ("PYTHONPATH".into(), root.display().to_string()),
        ("MODEL_DIR".into(), root.join("models").display().to_string()),
        (
            "GLM_OCR_DIR".into(),
            root.join("GLM-OCR").display().to_string(),
        ),
        (
            "ENABLE_GLM".into(),
            if glm_enabled { "true" } else { "false" }.into(),
        ),
    ];
    if let Some(p) = &report.glm_sdk_python {
        env.push(("GLM_SDK_PYTHON".into(), p.display().to_string()));
    }
    if let Some(p) = &report.glm_mlx_python {
        env.push(("GLM_MLX_PYTHON".into(), p.display().to_string()));
    }
    if let Some(port) = glm_port {
        env.push((
            "GLM_OCR_API_URL".into(),
            format!("http://127.0.0.1:{port}"),
        ));
    }
    env
}

/// HF cache env for the GLM MLX helper — mirrors tools/glm_serve.sh, which
/// exports the project-local cache so the model resolves from the WebApp's
/// MODEL_DIR instead of ~/.cache/huggingface.
pub fn glm_helper_env(root: &Path) -> Vec<(String, String)> {
    let hf = root.join("models").join("huggingface");
    vec![
        ("HF_HOME".into(), hf.display().to_string()),
        ("HF_HUB_CACHE".into(), hf.join("hub").display().to_string()),
        (
            "TRANSFORMERS_CACHE".into(),
            hf.join("hub").display().to_string(),
        ),
    ]
}

// ── start guard (duplicate-launch prevention at the shell level) ─────────────

/// Only one start/restart sequence may run at a time; a second Apply while a
/// backend is starting is refused instead of spawning a duplicate.
pub struct StartGuard(AtomicBool);

impl StartGuard {
    pub const fn new() -> Self {
        StartGuard(AtomicBool::new(false))
    }
    pub fn try_acquire(&self) -> bool {
        self.0
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_ok()
    }
    pub fn release(&self) {
        self.0.store(false, Ordering::SeqCst);
    }
}

// ── tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::sync::atomic::AtomicUsize;

    static DIR_SEQ: AtomicUsize = AtomicUsize::new(0);

    /// Std-only unique temp dir (no tempfile dev-dependency needed).
    fn tmpdir(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!(
            "sd-runtime-test-{}-{}-{}",
            std::process::id(),
            tag,
            DIR_SEQ.fetch_add(1, Ordering::SeqCst)
        ));
        fs::create_dir_all(&d).unwrap();
        d
    }

    fn touch(p: &Path) {
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(p, "x").unwrap();
    }

    /// A minimal valid WebApp layout for the given platform flavor.
    fn fake_webapp(windows: bool, with_glm: bool) -> PathBuf {
        let root = tmpdir("webapp");
        touch(&venv_python(&root.join(".venv"), windows));
        touch(&root.join("app.py"));
        touch(&root.join("config.py"));
        fs::create_dir_all(root.join("services")).unwrap();
        fs::create_dir_all(root.join("static")).unwrap();
        fs::create_dir_all(root.join("models")).unwrap();
        if with_glm {
            touch(&venv_python(&root.join("GLM-OCR").join(".venv-sdk"), windows));
            touch(&venv_python(&root.join("GLM-OCR").join(".venv-mlx"), windows));
        }
        root
    }

    // — config persistence: save → load round-trip, defaults, corruption —

    #[test]
    fn config_round_trip_persists_mode_and_paths() {
        let dir = tmpdir("cfg");
        let cfg = RuntimeConfig {
            mode: BackendMode::External,
            external_path: Some("/opt/smartdocs".into()),
            glm_enabled: false,
            ..RuntimeConfig::default()
        };
        cfg.save(&dir).unwrap();
        let loaded = RuntimeConfig::load(&dir);
        assert_eq!(loaded.mode, BackendMode::External);
        assert_eq!(loaded.external_path.as_deref(), Some("/opt/smartdocs"));
        assert_eq!(loaded.remote_url, None);
        assert!(!loaded.glm_enabled);
        // No secrets in the persisted file.
        let raw = fs::read_to_string(RuntimeConfig::file_path(&dir)).unwrap();
        assert!(!raw.to_lowercase().contains("token"));
    }

    #[test]
    fn config_round_trip_persists_insecure_lan_preference_and_ack() {
        let dir = tmpdir("cfg-lan");
        let cfg = RuntimeConfig {
            mode: BackendMode::Remote,
            remote_url: Some("http://192.168.1.50:5002".into()),
            allow_insecure_lan: true,
            insecure_lan_ack: true,
            ..RuntimeConfig::default()
        };
        cfg.save(&dir).unwrap();
        let loaded = RuntimeConfig::load(&dir);
        assert!(loaded.allow_insecure_lan);
        assert!(loaded.insecure_lan_ack);
        // Old runtime.json files (without the new keys) default to OFF.
        fs::write(
            RuntimeConfig::file_path(&dir),
            r#"{"mode":"remote","remote_url":"https://x.example.com"}"#,
        )
        .unwrap();
        let old = RuntimeConfig::load(&dir);
        assert!(!old.allow_insecure_lan);
        assert!(!old.insecure_lan_ack);
    }

    #[test]
    fn config_missing_or_corrupt_falls_back_to_bundled() {
        let dir = tmpdir("cfg-missing");
        assert_eq!(RuntimeConfig::load(&dir).mode, BackendMode::Bundled);
        fs::write(RuntimeConfig::file_path(&dir), "{not json").unwrap();
        assert_eq!(RuntimeConfig::load(&dir).mode, BackendMode::Bundled);
        fs::write(RuntimeConfig::file_path(&dir), r#"{"mode":"bogus"}"#).unwrap();
        assert_eq!(RuntimeConfig::load(&dir).mode, BackendMode::Bundled);
    }

    // — external runtime validation on mocked platform layouts —

    #[test]
    fn validates_unix_layout() {
        let root = fake_webapp(false, true);
        let rep = validate_external_runtime(&root, false, true, true);
        assert!(rep.ok, "components: {:?}", rep.components);
        assert!(rep.python.as_ref().unwrap().ends_with("bin/python"));
        assert!(rep.glm_sdk_python.is_some());
        assert!(rep.glm_mlx_python.is_some());
    }

    #[test]
    fn validates_windows_layout() {
        let root = fake_webapp(true, false);
        let rep = validate_external_runtime(&root, true, false, true);
        assert!(rep.ok, "components: {:?}", rep.components);
        assert!(rep
            .python
            .as_ref()
            .unwrap()
            .ends_with("Scripts/python.exe"));
        // MLX unsupported off Apple Silicon — reported, never fatal.
        assert!(rep
            .components
            .iter()
            .any(|c| c.name == "GLM MLX server" && c.status == "unsupported"));
    }

    #[test]
    fn missing_venv_and_sources_are_actionable_errors() {
        let root = tmpdir("empty");
        let rep = validate_external_runtime(&root, false, false, true);
        assert!(!rep.ok);
        let missing: Vec<&str> = rep
            .components
            .iter()
            .filter(|c| c.required && c.status == "missing")
            .map(|c| c.name)
            .collect();
        assert!(missing.contains(&"python"));
        assert!(missing.contains(&"app.py"));
    }

    #[test]
    fn parent_venv_layout_is_accepted() {
        // The documented MacBook layout: OCRSoftware/.venv beside the repo.
        let parent = tmpdir("parent");
        let root = parent.join("SmartDocs-Agent");
        touch(&venv_python(&parent.join(".venv"), false));
        touch(&root.join("app.py"));
        touch(&root.join("config.py"));
        fs::create_dir_all(root.join("services")).unwrap();
        fs::create_dir_all(root.join("static")).unwrap();
        let rep = validate_external_runtime(&root, false, false, true);
        assert!(rep.ok, "components: {:?}", rep.components);
        assert!(rep.python.as_ref().unwrap().starts_with(&parent));
    }

    #[test]
    fn missing_models_is_reported_but_not_fatal() {
        let root = fake_webapp(false, false);
        fs::remove_dir_all(root.join("models")).unwrap();
        let rep = validate_external_runtime(&root, false, false, true);
        assert!(rep.ok);
        assert!(rep
            .components
            .iter()
            .any(|c| c.name == "models/" && c.status == "missing" && !c.required));
    }

    // — remote URL policy —

    #[test]
    fn https_required_for_non_local() {
        assert!(check_remote_url("https://docs.example.com", false).is_ok());
        assert!(check_remote_url("http://docs.example.com", false).is_err());
        assert!(check_remote_url("http://192.168.1.10:5001", false).is_err());
        assert!(check_remote_url("http://127.0.0.1:5001", false).is_ok());
        assert!(check_remote_url("http://localhost:5001", false).is_ok());
        assert!(check_remote_url("http://[::1]:5001", false).is_ok());
        assert!(check_remote_url("ftp://example.com", false).is_err());
        assert!(check_remote_url("not a url", false).is_err());
        assert!(check_remote_url("https://user:pw@example.com", false).is_err());
    }

    #[test]
    fn insecure_lan_option_gates_private_http_only() {
        let ok = |raw: &str| check_remote_url(raw, true).map(|(_, p)| p);
        // Loopback HTTP never needed the option.
        assert_eq!(ok("http://127.0.0.1:5002").unwrap(), RemotePolicy::HttpLocal);
        assert_eq!(ok("http://localhost:5002").unwrap(), RemotePolicy::HttpLocal);
        // Private ranges: allowed WITH the option…
        assert_eq!(ok("http://192.168.1.50:5002").unwrap(), RemotePolicy::HttpInsecureLan);
        assert_eq!(ok("http://10.0.0.25:5002").unwrap(), RemotePolicy::HttpInsecureLan);
        assert_eq!(ok("http://172.20.0.10:5002").unwrap(), RemotePolicy::HttpInsecureLan);
        assert_eq!(ok("http://[fc00::1]:5002").unwrap(), RemotePolicy::HttpInsecureLan);
        // …and refused without it.
        assert!(check_remote_url("http://192.168.1.50:5002", false).is_err());
        // 172.16/12 boundaries: 172.15.x and 172.32.x are PUBLIC.
        assert!(ok("http://172.15.0.1:5002").is_err());
        assert!(ok("http://172.32.0.1:5002").is_err());
        // Public IPs, hostnames and link-local v6 stay rejected with the
        // option ON — it widens nothing but RFC1918/ULA literals.
        assert!(ok("http://8.8.8.8:5002").is_err());
        assert!(ok("http://public-example.com").is_err());
        assert!(ok("http://nas.local:5002").is_err());
        assert!(ok("http://[fe80::1]:5002").is_err());
        // Credentials still refused; https never affected by the flag.
        assert!(ok("http://user:pw@192.168.1.50:5002").is_err());
        assert_eq!(ok("https://docs.example.com").unwrap(), RemotePolicy::Https);
    }

    // — start planning —

    #[test]
    fn remote_mode_plans_ui_gateway_only_never_a_processing_backend() {
        let cfg = RuntimeConfig {
            mode: BackendMode::Remote,
            external_path: Some("/should/never/be/touched".into()),
            remote_url: Some("https://docs.example.com".into()),
            ..RuntimeConfig::default()
        };
        match start_plan(&cfg, false, false).unwrap() {
            StartPlan::ServeRemote { upstream, policy } => {
                // The plan carries only the URL — no interpreter, no paths,
                // no validation report: nothing a processing backend needs.
                assert_eq!(upstream.host_str(), Some("docs.example.com"));
                assert_eq!(policy, RemotePolicy::Https);
            }
            other => panic!("remote mode must plan the UI gateway only, got {other:?}"),
        }
    }

    #[test]
    fn insecure_lan_start_requires_the_confirmed_ack() {
        let mut cfg = RuntimeConfig {
            mode: BackendMode::Remote,
            remote_url: Some("http://192.168.1.50:5002".into()),
            allow_insecure_lan: true,
            insecure_lan_ack: false,
            ..RuntimeConfig::default()
        };
        let err = start_plan(&cfg, false, false).unwrap_err();
        assert!(err.starts_with(INSECURE_ACK_REQUIRED), "{err}");
        cfg.insecure_lan_ack = true;
        match start_plan(&cfg, false, false).unwrap() {
            StartPlan::ServeRemote { policy, .. } => {
                assert_eq!(policy, RemotePolicy::HttpInsecureLan)
            }
            other => panic!("expected gateway plan, got {other:?}"),
        }
    }

    #[test]
    fn external_mode_plans_validated_interpreter_only() {
        let root = fake_webapp(false, false);
        let cfg = RuntimeConfig {
            mode: BackendMode::External,
            external_path: Some(root.display().to_string()),
            ..RuntimeConfig::default()
        };
        match start_plan(&cfg, false, false).unwrap() {
            StartPlan::SpawnExternal { python, .. } => {
                // Only the validated venv interpreter inside the selected
                // directory tree is ever launched — no shell strings.
                assert!(python.starts_with(std::env::temp_dir()));
                assert!(python.ends_with("bin/python"));
            }
            other => panic!("expected external spawn, got {other:?}"),
        }
    }

    #[test]
    fn invalid_external_dir_is_a_start_error() {
        let cfg = RuntimeConfig {
            mode: BackendMode::External,
            external_path: Some(tmpdir("nope").display().to_string()),
            ..RuntimeConfig::default()
        };
        let err = start_plan(&cfg, false, false).unwrap_err();
        assert!(err.contains("missing"), "{err}");
    }

    // — env planning —

    #[test]
    fn external_env_reuses_webapp_models_but_not_its_data() {
        let root = fake_webapp(false, true);
        let rep = validate_external_runtime(&root, false, true, true);
        let env = plan_external_env(&root, &rep, true, Some(18080));
        let get = |k: &str| {
            env.iter()
                .find(|(n, _)| n == k)
                .map(|(_, v)| v.clone())
        };
        assert_eq!(get("MODEL_DIR").unwrap(), root.join("models").display().to_string());
        assert_eq!(get("ENABLE_GLM").unwrap(), "true");
        assert_eq!(get("GLM_OCR_API_URL").unwrap(), "http://127.0.0.1:18080");
        assert!(get("GLM_SDK_PYTHON").is_some());
        // Data separation: the WebApp's DB/uploads are never pointed at.
        assert!(get("DB_PATH").is_none());
        assert!(get("UPLOAD_DIR").is_none());
    }

    // — duplicate-launch guard —

    #[test]
    fn start_guard_refuses_concurrent_start() {
        let g = StartGuard::new();
        assert!(g.try_acquire());
        assert!(!g.try_acquire(), "second start must be refused");
        g.release();
        assert!(g.try_acquire());
    }
}
