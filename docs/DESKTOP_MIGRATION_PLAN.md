# DesktopApp Migration Plan

Target repository: **https://github.com/imtoiteu/SmartDocs-Agent-DesktopApp.git**

This is a **plan only** — nothing here is implemented, and no DesktopApp code
lives in this repository. It complements [DESKTOP_BUILD.md](DESKTOP_BUILD.md)
(which explains *why* Tauri and how the `scripts/` launchers were shaped for a
shell) by defining *what moves to the new repo and how the desktop app should
behave per OS*.

> Migration rules (per project policy): SmartDocs-Agent stays the stable,
> runnable baseline. The DesktopApp repo is built **alongside** it — nothing is
> deleted or moved out of this repo; code is *copied* and then evolves there.

---

## 1. What to copy into the DesktopApp repo

Copy (initial import, then track upstream manually or via subtree):

| From this repo | Purpose in DesktopApp |
|---|---|
| `app.py`, `config.py`, `models.py`, `auth.py`, `*_bp.py` | the backend, unchanged |
| `services/`, `agent/`, `tools/` | OCR engines + AI services + agent |
| `static/`, `templates/` | the UI the webview loads |
| `scripts/`, `requirements*/`, `.env.example` | runtime launchers + dependency locks |
| `GLM-OCR/` (vendored SDK) | needed only for GLM modes; optional at first |
| `docs/OFFLINE_SETUP_*.md`, `docs/OCR_ENGINES.md`, `README.md` (adapted) | user docs |

Do **NOT** copy (and keep git-ignored in the new repo, same as here):
`models/`, `.venv*`, `GLM-OCR/.venv-*`, `logs/`, `uploads/`, `*.db`, `.env`,
any API keys, user files, or generated OCR outputs.

New in the DesktopApp repo: the wrapper project itself (e.g. `desktop/` with
the Tauri `src-tauri/` shell + a thin settings UI), CI build workflows, and
packaging assets (icons, signing config).

## 2. Recommended wrapper

**Tauri** (see DESKTOP_BUILD.md §"Recommended approach" for the comparison).
SmartDocs already serves its whole UI over HTTP, so the desktop layer is only:
a webview pointed at `http://127.0.0.1:${SMARTDOCS_PORT}` + process control for
the backend. Electron remains the fallback if the team prefers a JS-only shell.

## 3. Backend start/stop

Phase 1 (works today, macOS/Linux + Windows-with-Git-Bash):

- start: run `scripts/start_web.sh -b` (and, only when `GLM_OCR_MODE=local_mlx`,
  offer `scripts/start_glm.sh -b` as a toggle);
- readiness: poll `GET /` until any HTTP response (same probe as `check.sh`),
  then show the webview;
- stop: `scripts/stop.sh` on app quit (PID files under `logs/`).

Phase 2 (native Windows, no bash): the shell spawns the venv Python directly
(`.venv/Scripts/python.exe app.py`) as a Tauri sidecar with the same env vars
the scripts export (`PORT`, `MODEL_DIR`, …). Phase 3 (separate milestone):
bundle Python with PyInstaller so end users install nothing.

## 4. Model setup in the app

First-run wizard driven by the existing read-only status surfaces — no new
backend logic needed:

- `config.check_offline_readiness()` / `scripts/check_offline.sh` — which
  models are missing and the exact setup command per feature;
- `/api/llm/status` — LLM provider/model/device/loaded + `setup_hint`;
- `/api/chat/status`, `/api/summarize/status`, `/api/translate/status`.

The wizard runs `scripts/setup_offline.sh` (and on Apple Silicon optionally
`scripts/setup_glm.sh --precache`) with live log streaming, into a `MODEL_DIR`
pointed at the OS app-data directory (`.env` knob — already supported).

## 5. Per-OS GLM modes (already implemented in this repo)

The desktop settings pane only needs to expose `GLM_OCR_MODE` — the backend
handles the rest (platform-aware defaults in `config.py`/`scripts/lib.sh`,
clear non-crash messages for unsupported combinations):

- **macOS Apple Silicon** → default `local_mlx`; offer a "Start GLM server"
  toggle + precache button.
- **Linux/Windows** → default `disabled`; settings offer `external_server`
  (URL + optional model/key) or `maas_api` (key). Never offer `local_mlx`;
  `ollama` stays hidden until verified.

## 6. Logs

Everything already lands in `logs/` (`web.log`, `glm.log`, PID files). The
shell exposes a "View logs" screen that tails those files, plus "Open logs
folder". Crash handling: if the backend process dies, surface the last ~50 log
lines in the error dialog instead of a bare "connection refused".

## 7. Missing models / degraded features

Never block the whole app. The backend already degrades per feature and every
gated route answers structured JSON (`success:false` + message + `disabled` or
`warming_up` flags). The shell maps those onto per-feature banners with a
"Fix it" button that opens the setup wizard at the right step (the hint text
comes from the API, e.g. `/api/llm/status.setup_hint`).

## 8. Building per OS (later milestones)

1. **macOS (arm64)**: Tauri bundle + notarisation; GLM local MLX supported.
2. **Windows (x64)**: Tauri MSI/NSIS; backend as sidecar (Phase 2 above);
   PaddleOCR/VietOCR local, GLM via `external_server`/`maas_api` only.
3. **Linux (AppImage/deb)**: same feature set as Windows; document the
   vLLM/SGLang server recipe for GPU boxes as a separate, server-side guide.

Each build must run the same validation: backend starts, routes register, OCR
(Paddle) round-trips, `check_offline.sh` matrix renders in the wizard.

## 9. Explicitly out of scope for the first milestone

Auto-update, tray icons, bundled Python, GLM `sdk_server` protocol and Ollama
mode (both reserved/unverified in the backend), and any in-place changes to
this repository beyond what the DesktopApp needs upstreamed.
