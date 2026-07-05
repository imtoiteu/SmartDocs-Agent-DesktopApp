# SmartDocs Desktop

Cross-platform desktop packaging of **SmartDocs-Agent** — the offline-first,
document-centric AI platform (OCR, translation, summarization, RAG chat, and an
LLM agent) — as a native app: a **Tauri v2** shell rendering the existing web
UI in the OS WebView, backed by the existing Python backend running as a
**PyInstaller sidecar** bound to `127.0.0.1`.

The web application itself is unchanged; its own documentation lives in
[docs/WEBAPP_README.md](docs/WEBAPP_README.md). This repository was imported
from [SmartDocs-Agent-WebApp](https://github.com/imtoiteu/SmartDocs-Agent-WebApp)
(commit `ce3589a`) and evolves independently.

---

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│ SmartDocs.app / .deb / .msi          (Tauri v2, Rust)      │
│                                                            │
│  native WebView ──── http://127.0.0.1:<dynamic port> ────┐ │
│  (existing SmartDocs UI)                                 │ │
│                                                          ▼ │
│  Rust shell ── owns ──► smartdocs-sidecar (PyInstaller)    │
│   • per-launch token    • Flask app, 127.0.0.1 ONLY        │
│   • spawn + handshake   • dynamic free port                │
│   • health-check gate   • token required on every /api     │
│   • graceful shutdown   • per-user data dir (env-mapped)   │
└────────────────────────────────────────────────────────────┘
```

Full lifecycle, token, and security details: [docs/DESKTOP_ARCHITECTURE.md](docs/DESKTOP_ARCHITECTURE.md).

## Backend runtime modes

Settings → Backend runtime (or the launcher screen that appears when a
backend fails to start) selects where processing runs. The selection is
persisted in `runtime.json` inside the per-user app-config directory and
applies to installed builds, not just `tauri dev`.

| Mode | What runs | Notes |
|---|---|---|
| **Bundled Core** (default) | The PyInstaller sidecar inside the install | Fully local; heavy ML engines not included — they report "not available". |
| **Existing WebApp runtime** | `desktop_server.py` executed by the **venv Python of a SmartDocs WebApp checkout** you select | Select Folder → Validate Runtime checks the venv interpreter (`.venv/bin/python`, Windows `.venv\Scripts\python.exe`, or the sibling `../.venv` layout), backend sources, `models/`, and the GLM runtimes. Models/HF/Argos/VietOCR caches come from the WebApp via `MODEL_DIR`; GLM via `GLM_OCR_DIR`/`GLM_SDK_PYTHON`/`GLM_MLX_PYTHON`. On Apple Silicon macOS the GLM MLX model server is started and stopped automatically with the app (`GLM_OCR_API_URL` points at it). **DesktopApp documents/settings stay in the app's own data dir** — the WebApp's database/uploads are never touched. |
| **Remote server** | Only the local **UI gateway** (`SMARTDOCS_GATEWAY_ONLY=1`) — no OCR/LLM/GLM/DB/processing service | The Desktop UI stays local; the gateway proxies the allowlisted routes to your server. HTTPS required; plain HTTP works for `localhost`/`127.0.0.1`, and — only with **Allow insecure HTTP on private LAN** enabled and its warning confirmed — for private IP literals (`10.x`, `172.16–31.x`, `192.168.x`, IPv6 unique-local). Public IPs/hostnames over HTTP and URLs with embedded credentials are always refused; a persistent “Insecure LAN connection” chip shows while connected insecurely. Test Connection classifies: reachable / sign-in required / unreachable / TLS-certificate problem / not a SmartDocs server. |

**The Desktop UI is the same in every mode.** The WebView only ever loads the
local UI gateway (`desktop_gateway.py`, stdlib-only): it serves the
DesktopApp's own frontend and proxies exactly the known SmartDocs routes
(`/api/…` incl. uploads/downloads/streaming/citations/artifacts, `/login`,
`/logout`, `/admin/…`) to the selected backend — an allowlist, not an open
proxy. Switching modes changes only the gateway's upstream; the WebView is
never navigated to a remote server's HTML interface, and redirects toward
foreign origins are refused rather than followed.

**The runtime selector is always reachable**, independent of any backend:
the native **Backend Runtime…** menu item (⌘, on macOS, Ctrl+, elsewhere),
the **Change backend…** button on every connection-error screen, and holding
**Option/Alt during startup**. If the saved backend is invalid or
unreachable the selector opens automatically with the saved configuration
intact — correct it, retry, or switch; deleting `runtime.json` is never
required.

Mode management lives on the app's bundled launcher page (the only origin
allowed to call the shell's runtime commands); the in-app Settings panel
shows the active mode and links to it. Duplicate launches are refused at
three levels (single-instance plugin, shell start guard, per-data-dir PID
lock), and only processes the shell itself spawned are ever stopped.

## Development

Prerequisites: Rust (stable), Node 20+, Python 3.12, and on Linux the Tauri v2
system packages (`libwebkit2gtk-4.1-dev`, `librsvg2-dev`, …).

```bash
npm install                    # Tauri CLI
scripts/build-sidecar.sh       # sidecar venv + PyInstaller one-dir build
scripts/dev-desktop.sh         # tauri dev against desktop_server.py (no freeze step)
scripts/test-desktop.sh        # unit suites + integration tests vs a real sidecar
```

`desktop_server.py` can also run standalone (see its docstring) — it never
opens a browser and prints a one-line JSON handshake on stdout.

## Building packages

PyInstaller does not cross-compile: each OS builds its own sidecar and bundle.
The GitHub Actions matrix in
[.github/workflows/desktop-build.yml](.github/workflows/desktop-build.yml)
builds all three natively. Icons are generated once per clone:
`node desktop/gen-icon.js && npx tauri icon desktop/icon.png`.

### macOS  (full guide: [docs/MACOS_BUILD.md](docs/MACOS_BUILD.md))

```bash
brew install rustup node@20 python@3.12 && rustup-init -y
npm install
PYTHON=python3.12 scripts/build-sidecar.sh
npx tauri build --bundles app,dmg
# → src-tauri/target/release/bundle/macos/SmartDocs.app
# → src-tauri/target/release/bundle/dmg/SmartDocs_0.1.0_aarch64.dmg
```

### Linux  (built + sidecar-tested on Ubuntu 24.04; GUI validation pending)

```bash
sudo apt-get install libwebkit2gtk-4.1-dev librsvg2-dev build-essential \
     libxdo-dev libssl-dev libayatana-appindicator3-dev
npm install
scripts/build-sidecar.sh
npx tauri build --bundles deb        # add: --bundles deb,appimage for AppImage
# → src-tauri/target/release/bundle/deb/SmartDocs_0.1.0_amd64.deb
```

### Windows  (PREPARED, NOT YET VALIDATED on a real Windows machine)

```powershell
# Prereqs: Rust (rustup), Node 20, Python 3.12, WebView2 runtime (Win 11: preinstalled)
npm install
powershell -ExecutionPolicy Bypass -File scripts\build-sidecar.ps1
npx tauri build --bundles msi,nsis
# → src-tauri\target\release\bundle\msi\SmartDocs_0.1.0_x64_en-US.msi
# → src-tauri\target\release\bundle\nsis\SmartDocs_0.1.0_x64-setup.exe
```

## Data locations

The installation directory is read-only. All writable state lives in the
per-user app-data directory resolved natively by Tauri and passed to the
sidecar via `SMARTDOCS_DATA_DIR`:

| OS      | Location                                              |
|---------|--------------------------------------------------------|
| Linux   | `~/.local/share/com.smartdocs.desktop/`                |
| macOS   | `~/Library/Application Support/com.smartdocs.desktop/` |
| Windows | `%APPDATA%\com.smartdocs.desktop\`                     |

Inside: `smartdocs.db` (SQLite), `uploads/`, `models/` (HF/Argos caches derive
from it), `app_settings.json`. Data survives application updates. Cloud API
keys are **never** stored there — they stay in the OS credential store
(Keychain / Credential Manager / Secret Service) via the existing keyring
integration.

## Security model

- Backend binds `127.0.0.1` only, on a dynamically chosen port.
- A random per-launch token is generated in the Rust shell, handed to Python
  via **stdin**, and injected into the WebView as an initialization script.
  It is never persisted, never logged, never in argv or the URL.
- Every `/api` request must carry `X-SmartDocs-Token`; requests without it get
  `401`. Page sessions are established through a token-authenticated bootstrap
  (`/desktop/boot` → `/api/desktop/session`).
- Desktop mode does **not** seed the web app's default `admin/admin123`
  account; it provisions a `desktop` user with a random unusable password.
- Host-header allowlist (DNS-rebinding hardening), WebView navigation
  allowlist (splash + exactly the backend origin), minimal Tauri capabilities,
  no shell/fs/http permissions exposed to page code.
- One backend per data dir (PID lockfile) + single app instance
  (tauri-plugin-single-instance). On close: graceful shutdown endpoint →
  bounded wait → force-kill. No orphans.

## Platform limitations

- **Bundled today (core)**: web UI, agent, documents, settings, keyring keys,
  privacy modes, uploads, chat/RAG plumbing. **Not bundled yet**: the heavy ML
  stacks (PaddleOCR, torch/transformers, VietOCR, Argos, faiss) — services
  degrade to their existing "engine not available" statuses. Bundling them is
  per-platform follow-up (note: the full stack pins Python 3.10; the core
  sidecar uses 3.12).
- **macOS/Windows are unverified**: built via CI definitions but not yet run
  on real machines — Keychain/Credential Manager behavior, signing,
  notarization, and installer UX all need native validation.
- Linux packaged build is produced and smoke-tested (see
  `desktop/tests/test_sidecar_integration.py`).

## Troubleshooting

- *Window shows "Could not start the SmartDocs backend"* — run the sidecar
  directly to see stderr:
  `desktop/sidecar/dist/smartdocs-sidecar/smartdocs-sidecar` with
  `SMARTDOCS_DESKTOP_TOKEN=<32+ chars>` and `SMARTDOCS_DATA_DIR=/tmp/sd-test`.
- *"another SmartDocs sidecar is already running"* — a live process holds
  `<data dir>/smartdocs-sidecar.lock`; stale locks from crashes are reclaimed
  automatically.
- *Port already in use* — impossible by design (the OS picks a free port);
  if the UI can't connect, check a firewall isn't filtering loopback.
- Dev shell logs: sidecar stderr is inherited by the Tauri process console.
