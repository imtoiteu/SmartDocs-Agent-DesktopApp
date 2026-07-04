# Desktop Build — Plan & Next Steps

This document describes how to wrap the current SmartDocs-Agent local runtime in
a desktop application (Tauri or Electron) **later**. Nothing here is implemented
yet — it is a plan. The concrete migration plan for the dedicated
[SmartDocs-Agent-DesktopApp](https://github.com/imtoiteu/SmartDocs-Agent-DesktopApp)
repository lives in [DESKTOP_MIGRATION_PLAN.md](DESKTOP_MIGRATION_PLAN.md). The immediate goal was a clean local runtime that a desktop
shell can drive; that is what the `scripts/` launchers now provide.

> Scope note (per project rules): this is **additive**. A desktop wrapper sits on
> top of the existing Flask app and OCR engines — it does not replace them, and
> the MacBook manual workflow keeps working unchanged.

---

## What the desktop shell needs (already in place)

The runtime was reorganised specifically so a desktop app can start/stop it
without embedding any Python knowledge:

- **`scripts/start_web.sh -b`** — launch the Flask backend in the background,
  writing a PID to `logs/web.pid` and logs to `logs/web.log`.
- **`scripts/start_glm.sh -b`** — optionally launch the GLM OCR server the same
  way (`logs/glm.pid` / `logs/glm.log`). Apple Silicon only; safe to skip.
- **`scripts/stop.sh`** — stop whatever the scripts started (uses the PID files).
- **`scripts/check.sh`** — health/readiness probe the shell can poll before it
  opens the window (returns non-zero only on a genuinely broken core env).
- **`.env`** — single source of truth for ports (`SMARTDOCS_PORT`, `GLM_PORT`)
  and `ENABLE_GLM`.

The shell's job is therefore: run `check.sh`/`setup.sh` on first launch, start
the backend, poll health, then load `http://localhost:${SMARTDOCS_PORT}` in a
webview. On quit, call `stop.sh`.

---

## Recommended approach: Tauri (preferred) or Electron

| | **Tauri** (recommended) | **Electron** |
|---|---|---|
| Bundle size | Small (uses the OS webview) | Large (ships Chromium) |
| Language | Rust shell + web frontend | Node/JS shell + web frontend |
| Sidecar process mgmt | First-class (`sidecar`, `Command`) | `child_process` |
| Fit here | Great — we only need a webview + process control | Works, heavier |

Recommendation: **Tauri**, because SmartDocs already serves its own UI over HTTP
— the desktop layer only needs a webview plus the ability to spawn/kill the
backend. There is no need to ship a second browser engine.

---

## Suggested next steps (when we build it)

1. **Prototype outside this repo first.** Create a sibling `SmartDocs-Desktop/`
   (do not add a Node toolchain to this Python repo yet). `build/`, `dist/` and
   `node_modules/` are already git-ignored here for when a wrapper lands.

2. **Backend as a managed sidecar.**
   - Simplest: have the shell run `scripts/start_web.sh -b` on startup and
     `scripts/stop.sh` on exit (works today, no packaging of Python required).
   - Fuller offline app: bundle the Python runtime with **PyInstaller** and
     register that binary as a Tauri sidecar so end users need no Python install.
     This is the larger effort and should be a separate milestone.

3. **Wait for readiness.** After starting the backend, poll
   `GET http://127.0.0.1:${SMARTDOCS_PORT}/` (any HTTP response = up) — the same
   check `scripts/check.sh` uses — before showing the webview.

4. **Keep GLM optional in the UI.** The shell may offer a "Start GLM OCR" toggle
   that calls `scripts/start_glm.sh -b`. If the host is not Apple Silicon, keep
   it disabled with a tooltip; the rest of the app is unaffected.

5. **Config surface.** Expose `SMARTDOCS_PORT`, `GLM_PORT`, `ENABLE_GLM` in a
   settings pane that writes `.env`. Pick a free port at runtime if the default
   is taken.

6. **Data locations.** For a packaged app, point `UPLOAD_DIR`, `DB_PATH`, and
   `MODEL_DIR` (all already configurable via `.env`) at the OS app-data
   directory rather than the repo folder.

7. **Packaging & signing.** Only after the above works end-to-end: Tauri bundle
   per-OS, code signing/notarisation (macOS), and auto-update — each its own task.

---

## Explicitly out of scope for now

- Bundling/free-threading the Python runtime into the installer.
- Native menus, tray icons, auto-update.
- Cross-compiling the GLM MLX server (it is Apple-Silicon specific and remains an
  optional, separately-started service).

Keep the first desktop milestone thin: **a webview that starts the existing
backend via the scripts and points at the local URL.** Everything else is
incremental.
