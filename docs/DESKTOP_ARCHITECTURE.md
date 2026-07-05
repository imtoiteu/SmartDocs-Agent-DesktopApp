# SmartDocs Desktop — Architecture

How the Tauri shell, the WebView, and the localhost Python sidecar fit
together, and who owns what. Complements
[DESKTOP_MIGRATION_PLAN.md](DESKTOP_MIGRATION_PLAN.md) (the original plan) and
the README's security-model summary.

## Components

| Component | Code | Role |
|---|---|---|
| Shell | `src-tauri/src/main.rs` | Native window, process lifecycle, token, health gate |
| Runtime modes | `src-tauri/src/runtime.rs` | Pure core: mode config (`runtime.json`), external-runtime validation, remote URL policy, launch planning, start guard — unit-tested via `cargo test` |
| Launcher | `desktop/splash/` | Bundled Tauri asset: splash + Backend-runtime settings (the only origin allowed to invoke the shell's runtime commands) |
| Sidecar entry | `desktop_server.py` | Desktop-specific Flask wiring (unchanged `app.py` underneath); also shipped as a `desktop-shim/` resource so an external WebApp venv can run it |
| Desktop helpers | `services/desktop_mode.py` | stdlib-only: token, handshake, data dirs, singleton lock |
| Packaging | `desktop/sidecar/smartdocs-sidecar.spec` | PyInstaller one-dir build |

## Backend runtime modes

`runtime.json` (app-config dir; no secrets) selects one of three modes; the
launcher page manages it via Tauri IPC commands (`runtime_get_state`,
`runtime_pick_folder`, `runtime_validate`, `runtime_test_remote`,
`runtime_apply`, `runtime_resume`). Tauri's ACL rejects app commands from
any non-bundled origin, so neither the local backend pages nor a remote
server can ever call them.

- **bundled** — the PyInstaller sidecar resource (unchanged behavior).
- **external** — the validated venv interpreter of a selected SmartDocs
  WebApp checkout runs the `desktop-shim/desktop_server.py` resource with
  `cwd`/`PYTHONPATH` at the checkout. Controlled env: `MODEL_DIR` (HF/Argos/
  VietOCR caches derive from it in `config.py`), `GLM_OCR_DIR`,
  `GLM_SDK_PYTHON`, `GLM_MLX_PYTHON`, `ENABLE_GLM`, `GLM_OCR_API_URL`.
  `DB_PATH`/`UPLOAD_DIR` are NOT pointed at the WebApp — DesktopApp data
  stays in its own data dir. On Apple Silicon macOS the shell also owns a
  GLM MLX helper (`python -m mlx_vlm.server --trust-remote-code --port N
  --model …`, mirroring `tools/glm_serve.sh`), stopped with SIGTERM → 5 s →
  kill on exit. Token/handshake/health/shutdown are identical to bundled
  mode. No shell strings anywhere — validated executables + argument lists.
- **remote** — no local process at all (`StartPlan::Navigate` carries only a
  URL by construction). HTTPS is required except for localhost/127.0.0.1/::1;
  URLs with embedded credentials are refused. Test Connection fingerprints
  the server via the unauthenticated 401 JSON envelope of `/api/auth/me` and
  classifies: ok / auth_required / unreachable / tls_error / incompatible.
  The navigation allowlist pins exactly the configured origin.

Error messages for external/remote modes never reference bundle-internal
paths (the sidecar resource is only resolved in bundled mode).

## Startup sequence

```
Tauri main()
 1. generate 64-hex-char launch token (OS RNG)                    [Rust]
 2. create "main" window → bundled splash (tauri://localhost)
    with initialization_script carrying the token
 3. resolve app_data_dir, create it
 4. spawn sidecar:
      env  SMARTDOCS_DESKTOP=1  SMARTDOCS_TOKEN_STDIN=1  SMARTDOCS_DATA_DIR=…
      stdin ← token + "\n"                       (never argv, never env)
 5. sidecar (desktop_server.py):
      apply_data_dirs()   SMARTDOCS_DATA_DIR → DB_PATH/UPLOAD_DIR/MODEL_DIR
                          (BEFORE config import; explicit env still wins)
      read token from stdin; refuse if missing/short        → error handshake
      SingletonLock       refuse duplicate per data dir     → error handshake
      import app          (unchanged Flask app)
      install hooks       token guard, request_loader, desktop routes
      make_server("127.0.0.1", 0)               ← dynamic port, loopback only
      stdout ← {"event":"ready","port":N,"pid":P,"version":V}
 6. shell reads handshake (90 s bound), then polls
    GET /api/desktop/health with the token (30 s bound)
 7. window.navigate → http://127.0.0.1:<port>/desktop/boot
 8. boot page JS: POST /api/desktop/session (token header)
    → Flask-Login session cookie for the auto-provisioned "desktop" user
    → location.replace("/")  — the unchanged SmartDocs UI, same-origin
```

Step 8 exists because page loads and `<img>`/asset subresources cannot carry
custom headers; the cookie covers them, while **every `/api` request still
requires the token header** (added by the injected fetch/XHR patch, which the
shell re-injects on every navigation).

## Request authentication (desktop mode)

| Request | Auth |
|---|---|
| `/api/*` | `X-SmartDocs-Token` header, constant-time compare — else 401 |
| `/api/*` user identity | Flask-Login `request_loader` maps a valid token to the `desktop` user |
| Pages (`/`, `/agent`, `/admin/`) + subresources | session cookie from the boot exchange |
| `/desktop/boot` | unauthenticated, static, secret-free |
| any request | Host must be `127.0.0.1`/`localhost`/`::1` (DNS-rebinding guard) |

Web deployments are untouched: all of this is installed only by
`desktop_server.py`; `python app.py` behaves exactly as before.

## Lifecycle ownership

The Rust shell owns the sidecar for the whole session:

- **Close / exit / update-restart** → `stop_sidecar()`:
  `POST /api/desktop/shutdown` (token) → up to 8 s for a clean exit →
  `kill()`. Runs on `RunEvent::ExitRequested` and `RunEvent::Exit`;
  idempotent (the Child handle is `take()`n).
- **Crash of the sidecar** → splash shows the error; no zombie (the reader
  thread ends, cleanup still runs at exit).
- **Crash of the shell** → the sidecar's PID lockfile goes stale; the next
  launch reclaims it (liveness-checked), so no duplicate and no lockout.
- **Duplicate app launches** → tauri-plugin-single-instance focuses the
  existing window; a manually launched second sidecar exits with code 3.

The sidecar shuts down from either direction: the HTTP endpoint (shell-owned)
or SIGTERM/SIGINT — both funnel into `werkzeug.serving.make_server().shutdown()`.

## Packaging

- PyInstaller **one-dir** (`desktop/sidecar/smartdocs-sidecar.spec`): faster
  startup than one-file and no temp-dir unpack; `static/` + `templates/` ship
  as read-only data inside the bundle; ML stacks are excluded (lazy imports
  degrade gracefully — see README "Platform limitations").
- The sidecar directory is attached to the Tauri bundle as a **resource**
  (`bundle.resources`), not `externalBin` (which supports single files only).
  The shell restores the executable bit at spawn time on Unix (bundlers do
  not reliably preserve modes on resources).
- Builds are native per OS (`.github/workflows/desktop-build.yml`);
  PyInstaller cannot cross-compile.

## Deviations from the mandated architecture

One: the main UI is **served by the sidecar over 127.0.0.1** and the bundled
Tauri asset is only the splash/bootstrap, rather than the whole frontend being
served from Tauri assets. Concrete blockers, verified in the baseline code:

1. `/admin/` is server-rendered Jinja (`templates/`) — it cannot exist as a
   static asset.
2. The frontend is multi-page with absolute-path navigations
   (`window.location.href = '/agent?file_id=…'` in `static/app.js`), which do
   not resolve under the asset protocol without rewriting the frontend —
   prohibited ("do not rewrite the working frontend").
3. Cookie-based Flask-Login sessions and dynamic subresources would be
   third-party cross-origin from a `tauri://` page; WebKit's cookie policies
   make that unreliable.

The spirit of the mandate is preserved: the UI is bundled read-only inside
the package, loads only from the loopback origin (navigation-allowlisted),
and the API base URL still reaches the frontend through a controlled Tauri
mechanism (the shell navigates the window; the token arrives via
initialization script).
