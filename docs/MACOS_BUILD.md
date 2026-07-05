# Building SmartDocs Desktop on macOS

Step-by-step for building and testing the desktop app natively on a MacBook
(Apple Silicon). Everything here runs on YOUR machine — the Linux VPS cannot
produce or validate macOS artifacts.

## 1. Prerequisites

```bash
xcode-select --install                # Command Line Tools (clang, codesign)
brew install rustup node@20 python@3.12
rustup-init -y                        # stable toolchain, then restart the shell
rustc --version                       # expect 1.7x+ stable, aarch64-apple-darwin
node --version                        # expect v20.x
python3.12 --version
```

No global PyInstaller/Tauri installs needed — everything is project-local.

## 2. Clone and prepare

```bash
git clone https://github.com/imtoiteu/SmartDocs-Agent-DesktopApp.git
cd SmartDocs-Agent-DesktopApp
npm install                           # @tauri-apps/cli (local devDependency)
node desktop/gen-icon.js              # writes desktop/icon.png
npx tauri icon desktop/icon.png      # derives icon.icns etc. into src-tauri/icons/
```

## 3. Build the Python sidecar (native arm64)

```bash
PYTHON=python3.12 scripts/build-sidecar.sh
```

What it does: creates `desktop/sidecar/venv`, installs
`desktop/sidecar/requirements-core.txt` + PyInstaller, sanity-checks
`import app`, then freezes to `desktop/sidecar/dist/smartdocs-sidecar/`
(one-directory bundle, ~300 MB).

Quick native verification of the frozen sidecar (recommended, ~1 min):

```bash
python3 desktop/tests/test_sidecar_integration.py
# expects: 9/9 passed  (it auto-finds the packaged binary)
```

## 4. Development run (optional, before packaging)

```bash
scripts/dev-desktop.sh                # tauri dev + desktop_server.py from the venv
```

A window should open on the splash, then switch to the SmartDocs UI.

## 5. Package the .app / .dmg

```bash
npx tauri build --bundles app,dmg
```

Expected artifacts:

```
src-tauri/target/release/bundle/macos/SmartDocs.app
src-tauri/target/release/bundle/dmg/SmartDocs_0.1.0_aarch64.dmg
```

## 6. Smoke test on macOS

1. Open `SmartDocs.app`. Expect the splash ("Starting local backend…") then
   the SmartDocs UI. First launch of an unsigned app: right-click → Open, or
   `xattr -dr com.apple.quarantine SmartDocs.app` (Gatekeeper).
2. `lsof -iTCP -sTCP:LISTEN -P | grep smartdocs` — the sidecar must show
   `127.0.0.1:<port>` only (never `*:<port>`).
3. In the app: Settings → save a cloud API key → confirm the macOS **Keychain
   prompt** appears and the key shows masked (`••••xxxx`). Open Keychain
   Access and verify a "SmartDocs" item exists.
4. Upload a small text/docx file, run a summary — verifies UI → backend flow.
5. Quit the app (⌘Q) → `pgrep -f smartdocs-sidecar` must print nothing.
6. Relaunch → previous documents/settings still present
   (`~/Library/Application Support/com.smartdocs.desktop/`).

## 6b. Manual tests — runtime modes, sidebar, Local-only (macOS)

These were implemented and unit/integration-tested on Linux only; validate
the real behavior here.

**Sidebar / top bar**
1. The left sidebar shows Home…SmartDocs AI + Agent, with Settings/Admin in
   the bottom section; the top bar shows only title, chips, language, user.
2. Collapse (⇤) → icon-only ~68 px rail with tooltips; relaunch → the
   collapsed preference is remembered.
3. Shrink the window below ~860 px → the sidebar becomes a ☰ overlay drawer;
   Esc and backdrop close it. Tab/Arrow keys walk the items; Enter activates.
4. Sign in as a non-admin (web mode) → no Admin item.

**Local only (Settings → Privacy)**
5. Click "Switch to Local only" → the badge, button label, `aria-pressed`,
   the top-bar 🔒 chip and the provider rows (disabled inputs, "Local only"
   badges) ALL flip immediately; reload → state restored.
6. Switch back to cloud → the disclosure confirm appears only the FIRST time
   ever; controls re-enable; chip flips to ☁.
7. While Local only: translate with engine "online" must refuse; saving or
   testing a cloud key must be refused by the backend (409), not just
   disabled in the UI.

**Runtime modes (Settings → Backend runtime → Manage…)**
8. Bundled Core: default behavior unchanged (steps 1-6 above).
9. Existing WebApp runtime: Select Folder → your SmartDocs-Agent checkout →
   Validate Runtime (expect ✔ python/app.py/services/static + models +
   GLM runtimes) → Apply & restart. Expect: the app restarts onto the WebApp
   venv backend; OCR engines/models that exist in the WebApp now work;
   `pgrep -f mlx_vlm.server` shows the auto-started GLM helper (if enabled);
   GLM OCR runs; documents created here do NOT appear in the WebApp's own
   database (separate data dirs). ⌘Q → backend AND mlx_vlm.server both gone.
10. Remote server: enter your server URL → Test Connection (expect
    "sign-in required" for a real server; a plain-HTTP non-local URL must be
    refused unless it is a private LAN IP with the insecure option enabled;
    a non-SmartDocs URL must say incompatible) → Apply → the app shows the
    DESKTOP UI (not the server's web pages) with the login page proxied
    through 127.0.0.1; `pgrep -f smartdocs-sidecar` shows ONE gateway-only
    process and `pgrep -f mlx_vlm` nothing. Sign in, upload, run a summary —
    all data lives on the server.
11. From the running app: Settings → "Manage backend runtime…" must return
    to the launcher screen.

**Runtime-selector recovery + insecure LAN**
12. Menu bar → Backend → "Backend Runtime…" and ⌘, both open the selector
    while the app is running; "Back to app" returns.
13. Quit; relaunch while HOLDING Option → the selector appears instead of
    the saved backend starting; Esc/Back resumes nothing (no backend yet),
    Apply starts one. runtime.json was not modified by just looking.
14. Configure remote mode against a stopped/unreachable server → on launch
    the selector opens automatically with the error and the saved URL still
    filled in; fix the URL and Apply without deleting anything.
15. Remote URL `http://<LAN-IP>:5002` with the insecure checkbox OFF →
    refused with an actionable message. Enable "Allow insecure HTTP on
    private LAN" → Apply → the warning appears ONCE; confirm → connects;
    the top bar shows the red "Insecure LAN connection" chip persistently;
    relaunch → no re-confirmation. `http://8.8.8.8:5002` and
    `http://user:pw@…` must always be refused.
16. In remote mode the UI must still be the DesktopApp interface: sidebar,
    top-bar chips, language switcher — never the server's own web layout.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| "backend refused to start: another … already running" | stale lock after a crash is auto-reclaimed; if it persists, delete `~/Library/Application Support/com.smartdocs.desktop/smartdocs-sidecar.lock` |
| Splash shows "Could not start the SmartDocs backend" | run the sidecar by hand to see the error: `SMARTDOCS_DESKTOP_TOKEN=$(python3 -c 'import secrets;print(secrets.token_hex(32))') SMARTDOCS_DATA_DIR=/tmp/sd desktop/sidecar/dist/smartdocs-sidecar/smartdocs-sidecar` |
| PyInstaller "library not found" on freeze | ensure the venv is arm64 (`file desktop/sidecar/venv/bin/python`); don't mix Rosetta/x86 brew |
| Gatekeeper blocks the app | unsigned build — right-click → Open once, or sign/notarize (not configured yet) |
| Keychain prompt never appears | the `keyring` package must be in the sidecar build — check `desktop/sidecar/requirements-core.txt` was installed before freezing |

## 8. What is still UNVERIFIED on macOS (validate here)

- Everything in §6b: external WebApp runtime launch, the GLM MLX helper
  start/stop, remote-server mode against a real server, the native folder
  picker dialog, and the sidebar/Local-only behavior in a real WKWebView
- The UI gateway under WKWebView: login through the proxy (cookie
  handling), uploads/downloads/streaming through the proxy, admin pages
- The native menu item + ⌘, accelerator, and Option-held-at-startup
  detection (CGEventSourceFlagsState) on real macOS
- Insecure-LAN flow against a real LAN server (warning-once, persistent
  chip, refusal matrix)
- Rust changes in main.rs/runtime.rs have never been compiled on this
  Linux box (cargo builds are prohibited here) — `cargo test
  --manifest-path src-tauri/Cargo.toml` runs in CI and on your Mac

- PyInstaller freeze on arm64 (spec was only exercised on Linux x86_64)
- macOS **Keychain** behavior of the keyring integration (prompts, ACLs)
- `.app`/`.dmg` bundling, Gatekeeper/quarantine handling, signing, notarization
- WKWebView rendering of the SmartDocs UI (Linux used WebKitGTK)
- ⌘Q / window-close → sidecar termination on macOS (PDEATHSIG is Linux-only;
  macOS relies on the Tauri exit events + graceful/forced shutdown ladder)
- App-data location + persistence across updates under
  `~/Library/Application Support/com.smartdocs.desktop/`
- Full-ML sidecar (paddle/torch) packaging — not attempted on any OS; the core
  build ships without OCR/LLM engines (they report "not available" in the UI)
