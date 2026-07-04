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

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| "backend refused to start: another … already running" | stale lock after a crash is auto-reclaimed; if it persists, delete `~/Library/Application Support/com.smartdocs.desktop/smartdocs-sidecar.lock` |
| Splash shows "Could not start the SmartDocs backend" | run the sidecar by hand to see the error: `SMARTDOCS_DESKTOP_TOKEN=$(python3 -c 'import secrets;print(secrets.token_hex(32))') SMARTDOCS_DATA_DIR=/tmp/sd desktop/sidecar/dist/smartdocs-sidecar/smartdocs-sidecar` |
| PyInstaller "library not found" on freeze | ensure the venv is arm64 (`file desktop/sidecar/venv/bin/python`); don't mix Rosetta/x86 brew |
| Gatekeeper blocks the app | unsigned build — right-click → Open once, or sign/notarize (not configured yet) |
| Keychain prompt never appears | the `keyring` package must be in the sidecar build — check `desktop/sidecar/requirements-core.txt` was installed before freezing |

## 8. What is still UNVERIFIED on macOS (validate here)

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
