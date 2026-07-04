# SmartDocs-Agent — Installation Guide

This guide covers installing and running SmartDocs-Agent for **development / local use**.
For production servers see [DEPLOYMENT.md](./DEPLOYMENT.md).

Everything here is verified against the repository (`requirements.txt`, `config.py`,
`agent/core/provider.py`, `services/ai_rewrite_service.py`, the run scripts, and
`tools/`). Items that could not be confirmed from source are marked **UNKNOWN**.

---

## 1. Prerequisites & platform support

| Requirement | Detail |
|---|---|
| **Python** | **3.10** is the verified version in this repo (the project venv runs CPython 3.10.17). No version is pinned in code. 3.11 is *likely* compatible; 3.13 is **UNKNOWN**. Use 3.10 if unsure. |
| **git** | To clone the repository. |
| **Node / npm** | **Not required.** The frontend is plain vendored JavaScript (`static/`, with `marked`/`katex` under `static/vendor/`). There is no `package.json`, bundler, or build step. |
| **Disk** | Several GB for Python wheels (torch, paddle) plus AI model weights. ~10 GB is a safe rule of thumb (approximate). |
| **RAM** | 8 GB minimum for CPU operation (enough for the default 1.5B local LLM); 16 GB recommended only if you opt into a larger chat model (e.g. 3B) and run OCR concurrently (approximate — not a hard requirement in code). |
| **OS** | macOS (Apple Silicon & Intel), Ubuntu/Linux, Windows. The **GLM-OCR** engine additionally needs Apple Silicon + MLX (see §6). |

The other three OCR engines and all AI services are cross-platform.

---

## 2. macOS (Apple Silicon & Intel)

```bash
# 1. Python 3.10 (Homebrew). Apple Silicon and Intel both supported.
brew install python@3.10 git

# 2. Clone + enter the project
cd /path/to/OCRSoftware/SmartDocs-Agent     # repo lives under an OCRSoftware/ parent

# 3. Virtual environment
python3.10 -m venv .venv
source .venv/bin/activate

# 4. Install dependencies (torch + MPS works out of the box on Apple Silicon)
pip install --upgrade pip
pip install -r requirements.txt

# 5. Environment file
cp .env.example .env

# 6. Run (first launch creates + seeds the SQLite DB)
python app.py
```

Notes:
- On Apple Silicon, `torch` MPS works for embeddings/OCR, but the Qwen generation models
  default to **CPU** (`QWEN_DEVICE`/`CHAT_DEVICE` default to `cpu` when the global device is
  `mps`/`cpu`, per `config.py`). This is intentional — MPS generation can crash on large
  tensors (documented in `services/ai_rewrite_service.py`).
- `paddle-slim` is intentionally **not** installed on macOS (`platform_system != "Darwin"`
  marker in `requirements.txt`); the OCR engines do not require it on macOS.
- Intel Macs have no GPU acceleration here → CPU only (slower LLM responses, fully functional).

---

## 3. Ubuntu / Linux

```bash
# 1. System packages
sudo apt-get update
sudo apt-get install -y python3.10 python3.10-venv python3-pip git \
    libgl1 libglib2.0-0          # OpenCV runtime needed by PaddleOCR on headless servers

# 2. Project + venv
cd /path/to/SmartDocs-Agent
python3.10 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# 3a. CPU-only install (default)
pip install -r requirements.txt

# 3b. NVIDIA GPU (optional): install a CUDA torch build BEFORE/over the requirements.
#     (requirements.txt installs the CPU torch by default.)
pip install -r requirements.txt
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
#     For GPU PaddleOCR you also need a GPU paddle build (paddlepaddle-gpu) matching your
#     CUDA version — see the PaddlePaddle install docs. Exact package/version: UNKNOWN here.

# 4. Env + run
cp .env.example .env
python app.py
```

Notes:
- `libgl1 libglib2.0-0` resolve the common `ImportError: libGL.so.1` from OpenCV (a PaddleOCR
  dependency) on headless Linux. Install them if OCR import fails.
- To use a GPU, also set `DEVICE=cuda` in `.env`.

**GLM OCR on Linux** — the local **MLX server is NOT supported** (the `mlx` /
`mlx-vlm` wheels exist only for macOS/arm64). Everything else runs. Options:

- **Run without GLM (recommended):** set `ENABLE_GLM=false` in `.env` so
  `scripts/start.sh` doesn't attempt the server. (Leaving it `true` is harmless —
  the script warns and continues; only the GLM engine button in the UI errors.)
  PaddleOCR Legacy/Modern and VietOCR are unaffected.
- **Use an external GLM server (UNVERIFIED on Linux):** point the app at a GLM
  OCR HTTP server running elsewhere (e.g. an Apple-Silicon Mac on the LAN):
  ```bash
  # .env
  GLM_OCR_API_URL=http://<glm-host>:8080
  # GLM_OCR_DIR=/path/to/GLM-OCR             # only if the vendored dir moved
  # GLM_SDK_PYTHON=/path/to/.venv-sdk/bin/python
  ```
  The adapter still shells out to the local `glmocr` CLI (`GLM-OCR/.venv-sdk`,
  plain torch — `scripts/setup_glm.sh` builds it and skips the MLX-only steps on
  non-Apple hosts), which then calls the remote server. This path is expected to
  work but has not been validated end-to-end on Linux.

---

## 4. Windows

```bat
:: 1. Install Python 3.10 (python.org or Microsoft Store) and Git for Windows.
::    A "Microsoft Visual C++ Redistributable" may be required by paddle/torch wheels.

:: 2. Project + venv
cd C:\path\to\SmartDocs-Agent
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip

:: 3a. CPU-only (default)
pip install -r requirements.txt

:: 3b. NVIDIA GPU (optional)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

:: 4. Env + run
copy .env.example .env
python app.py
```

Or simply run `run_windows.bat`, which activates the venv, copies `.env`, installs deps, and
starts the app.

Notes:
- **Python 3.10** is the verified version (same as macOS/Linux).
- **Shells:** the `scripts/*.sh` launchers are **bash** scripts — on Windows they
  require **Git Bash** or **WSL**. Two supported approaches:
  - **WSL (recommended for the scripted flow):** inside WSL, follow the Linux
    section above verbatim (`scripts/setup.sh`, `scripts/setup_offline.sh`, …).
  - **Native PowerShell/cmd:** use the manual steps above or `run_windows.bat`;
    there is no `.sh` wrapper, so prime offline models with the venv's Python
    directly:
    ```bat
    .venv\Scripts\activate
    python tools\setup_offline.py
    ```
    (`tools/setup_offline.py` prints which interpreter it runs under and warns
    if it looks wrong.)
- **GLM OCR is not supported natively on Windows** — the MLX server needs Apple
  Silicon. Set `ENABLE_GLM=false` in `.env` (only relevant if you use the bash
  scripts; the native app simply reports the GLM engine unavailable when
  selected). An **external** GLM server (`GLM_OCR_API_URL=http://<glm-host>:8080`)
  is the same UNVERIFIED path as described in the Linux section.
- Paths in `.env` accept Windows form (e.g. `MODEL_DIR=C:\smartdocs\models`);
  the defaults (relative `./models` etc.) work unchanged.
- All other engines and AI services run on Windows (CPU, or CUDA with a GPU torch
  build) — expected from the codebase, not regularly tested (see the platform
  matrix in the README).

---

## 5. Environment Setup

### Database initialization

The app uses **SQLite** (`paddleocr.db` by default, or `DB_PATH`). On the **first**
`python app.py`, the `__main__` block calls `seed_admin(app)` which runs `db.create_all()`
and seeds two accounts ([models.py](../models.py)):

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | admin |
| `user`  | `user123`  | user |

**Change these immediately** via the Admin console at `/admin`. There is no separate
migration step — the schema is created by `db.create_all()` (no Alembic).

> Deployment caveat: `seed_admin` runs **only** under `python app.py` (`__main__`). If you
> start the app with a WSGI server (gunicorn), you must initialize the DB yourself first —
> see [DEPLOYMENT.md](./DEPLOYMENT.md).

### Environment variables

Copy `.env.example` → `.env` and override what you need. The app works with defaults if
`.env` is absent. Every variable below is actually read in code (no invented variables).

**Core**

| Variable | Default | Purpose |
|---|---|---|
| `OFFLINE` | `1` | `1` = load HF/Argos/Stanza models only from `MODEL_DIR`; `0` = allow HF downloads. (Does **not** govern PaddleOCR's own model downloads.) |
| `MODEL_DIR` | `./models` | Root for local HuggingFace models + Argos packages. |
| `DEVICE` | `auto` | `auto`→CUDA→MPS→CPU. Options: `auto\|cpu\|cuda\|mps`. |
| `DTYPE` | (auto) | `float32\|float16\|bfloat16`. |
| `HOST` | `0.0.0.0` | Bind address. |
| `PORT` | `5001` | Bind port. |
| `SECRET_KEY` | (random) | Flask session key. **Set a fixed value** so sessions survive restarts. |
| `MAX_UPLOAD_MB` | `50` | Max upload size. |
| `SESSION_COOKIE_SECURE` | `0` | Set `1` only behind HTTPS. |
| `DISPLAY_TZ` | `Asia/Ho_Chi_Minh` | Timestamp display timezone. |
| `UPLOAD_DIR` | `./uploads` | Upload storage path. |
| `DB_PATH` | `./paddleocr.db` | SQLite database file. |

**OCR**

| Variable | Default | Purpose |
|---|---|---|
| `OCR_ENGINE` | `paddle` | UI default engine: `paddle\|vietocr`. (Modern + GLM are per-request in the UI.) |
| `VIETOCR_DEVICE` | (see config) | VietOCR device. |
| `VIETOCR_CONFIG` | `vgg_transformer` | VietOCR config name. |
| `VIETOCR_WEIGHTS` | (auto) | Path to VietOCR weights (else `MODEL_DIR/vietocr/<config>.pth`). |
| `GLM_ROOT`, `GLM_SDK_PYTHON`, `GLM_MLX_PYTHON`, `GLM_CONFIG_YAML` | (see §6) | GLM-OCR external paths. |
| `GLM_OCR_API_URL` | `http://localhost:8080` | GLM MLX server URL. |
| `GLM_TIMEOUT` | `300` | GLM subprocess timeout (s). |

**Local AI models** (must be present in `MODEL_DIR` when `OFFLINE=1`)

| Variable | Default |
|---|---|
| `QWEN_MODEL` | `Qwen/Qwen2.5-1.5B-Instruct` (AI rewrite / OCR cleanup) |
| `QWEN_DEVICE` | `cpu` (when global `DEVICE` is `mps`/`cpu`) |
| `CHAT_MODEL` | `Qwen/Qwen2.5-1.5B-Instruct` (RAG chat — default local LLM; larger models like 3B are opt-in) |
| `FALLBACK_CHAT_MODEL` | `Qwen/Qwen2.5-1.5B-Instruct` |
| `CHAT_DEVICE` | `cpu` (when global `DEVICE` is `mps`/`cpu`) |
| `PHOBERT_MODEL` | `vinai/phobert-base-v2` (Vietnamese summarization) |

**Agent LLM providers** — see §7.

---

## 6. OCR Engine Setup

Four engines are registered (`services/ocr_engines/router.py`). The default is `paddle`
(Legacy). Engines are selectable per request in the OCR UI.

### 6.1 Legacy PaddleOCR — PP-OCRv5
- Package: `paddleocr` (pinned `>=3.7.0,<3.8.0`), `paddlepaddle`.
- Models: PaddleOCR downloads its model files on **first use** and caches them locally.
  This needs internet **once**. `OFFLINE` does not control PaddleOCR's own downloader.
- No extra setup beyond `pip install -r requirements.txt`.

### 6.2 PaddleOCR Modern — PP-StructureV3 + PP-OCRv6
- Packages: `paddlex[ocr-core]`, `paddleocr`, `paddlepaddle`. Produces markdown/HTML/tables/blocks.
- Pre-fetch the larger model set while online with the provided helper:
  ```bash
  python tools/warmup_modern_models.py
  ```
  (Per its docstring, it points PaddleX at HuggingFace and fetches the PP-StructureV3 /
  PP-OCRv6 models so the Modern engine then runs offline.)

### 6.3 VietOCR (Vietnamese, images only)
- Package: `vietocr`. Hybrid: PaddleOCR detection + VietOCR recognition. **Images only**
  (rejects PDFs in `services/ocr_engines/vietocr_adapter.py`).
- Weights: expects `MODEL_DIR/vietocr/config.yml` and a weights file (default
  `MODEL_DIR/vietocr/vgg_transformer.pth`, or `VIETOCR_WEIGHTS`). The adapter raises a clear
  error if these are missing.
- `scripts/setup_offline.sh` (wrapper for `tools/setup_offline.py`, always using the main venv Python) is the intended helper to populate `MODEL_DIR` (incl. VietOCR);
  the exact set of files it fetches is **UNKNOWN** without running it — inspect the script.

### 6.4 GLM-OCR (OPTIONAL · Apple Silicon / MLX only)
GLM-OCR is a **client** of a separately-run local model server; SmartDocs does not spawn it.

Requirements:
- The external **GLM-OCR** repository (a sibling checkout; `GLM_ROOT`, default
  `<repo-parent>/GLM-OCR/GLM-OCR`), with its own Python venvs:
  - `GLM_SDK_PYTHON` — the GLM SDK/CLI venv (runs `glmocr.cli parse`).
  - `GLM_MLX_PYTHON` — the **MLX** venv that serves the model (Apple Silicon).
- A running MLX server (OpenAI-compatible, default `http://localhost:8080`). Start it with:
  ```bash
  tools/glm_serve.sh        # runs: mlx_vlm.server --trust-remote-code --port 8080
  ```
- Health check:
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/chat/completions \
    -X POST -H "Content-Type: application/json" \
    -d '{"model":"mlx-community/GLM-OCR-bf16","messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}],"max_tokens":3}'
  # expect: 200
  ```
- **Platform**: MLX is Apple-Silicon-only, so GLM-OCR as wired here is **macOS Apple Silicon
  only**. Linux/Windows support is **UNKNOWN / not provided** by this setup. If the server is
  down, only the GLM engine errors (with a clear toast); the other three keep working.

### Optional OCR components
- `layoutparser` — improves reading-order reconstruction for Legacy/VietOCR. The code runs
  without it (`services/layout_service.py` falls back to pure geometry if absent).
- `faiss-cpu` — vector search for RAG. Falls back to NumPy cosine if missing.
- `underthesea` — Vietnamese sentence tokenization (recommended, optional).

### Hardware recommendations
- **CPU-only**: fully functional everywhere; LLM/chat responses are slower.
- **Apple Silicon**: MPS used for OCR/embeddings; Qwen generation runs on CPU by design.
- **NVIDIA CUDA (Linux/Windows)**: set `DEVICE=cuda`, install a CUDA `torch` build and a GPU
  `paddlepaddle` build. Speeds up OCR and LLM generation.

---

## 7. AI Provider Setup (Agent)

The agent's LLM access is a model-neutral provider chain (`agent/core/provider.py`),
selected by `AGENT_LLM_PROVIDER`:

| `AGENT_LLM_PROVIDER` | Behavior |
|---|---|
| `auto` (default) | Build a fallback chain **Groq → Gemini → Local Qwen** (only the providers whose API keys are set are included; Local Qwen is always last). |
| `local` | Use only the local Qwen model. |
| `groq` | Groq, then Local Qwen fallback. |
| `gemini` | Gemini, then Local Qwen fallback. |

### Groq
```ini
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile      # default
```

### Gemini
```ini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.0-flash           # default
```

### Local Qwen (always-available fallback)
- No key needed. Uses the locally loaded Qwen model via `services/ai_rewrite_service.py`
  (`QWEN_MODEL`, default `Qwen/Qwen2.5-1.5B-Instruct`).
- The RAG `chat` surface uses the same default local LLM (`CHAT_MODEL`, default
  `Qwen/Qwen2.5-1.5B-Instruct`); `scripts/setup_offline.sh` already caches it. To
  opt into a larger chat model, set `CHAT_MODEL` in `.env`, then:
  ```bash
  python tools/download_chat_model.py   # fetches the configured CHAT_MODEL into models/huggingface/
  ```

### Fallback behavior (verified in `agent/core/provider.py`)
- `FallbackProvider` tries providers in priority order and degrades to the next on any raised
  exception (e.g. 429 / auth / network), ending at the always-available Local Qwen.
- It is **sticky**: once a later provider succeeds after earlier failures, the earlier ones
  are skipped for the rest of that process's life.
- An empty-string completion counts as success (does **not** trigger fallback).

### AI Rewrite cloud fallback (separate from the agent)
The abstractive summarization "AI rewrite" path (`services/ai_rewrite_service.py`) can fall
back to a cloud API only if the local Qwen rewrite model is unavailable. Keys checked:
`OPENAI_API_KEY` (gpt-4o-mini), `GROQ_API_KEY` (llama-3.1-8b-instant),
`OPENROUTER_API_KEY` (llama-3.1-8b-instruct:free). All optional.

> Keep API keys in `.env` only. `.gitignore` ignores `.env` / `.env.*` (but keeps
> `.env.example`), so real keys are never committed.

---

## 8. Development Setup

### Local workflow
```bash
source .venv/bin/activate
python app.py            # dev server (Flask, threaded=True, debug=False)
```
The dev server pre-warms the AI rewrite model in a background thread and rebuilds the
in-memory RAG index from persisted OCR/text artifacts on startup.

### Running the web application
- Default URL: `http://localhost:5001` (or your `PORT`).
- Optional GLM engine: start `tools/glm_serve.sh` in a separate terminal first (§6.4).

### Running tests
```bash
pytest                 # full suite: root test_*.py + agent/tests/
pytest agent/tests     # agent layer (core, tools, skills, knowledge, memory, providers)
```
There is no `pytest.ini`/`pyproject.toml`; tests run from the project root with the default
pytest discovery. (No coverage/CI config is present in the repo.)

### Helper scripts (`tools/`)
| Script | Purpose (from its docstring) |
|---|---|
| `setup_offline.py` | Run once online to download all required models into `MODEL_DIR` for offline use. **Run via `scripts/setup_offline.sh`** (resolves the main venv Python). |
| `download_chat_model.py` | Download the configured `CHAT_MODEL` (default 1.5B; set a larger id in `.env` to opt in) into `models/huggingface/`. |
| `warmup_modern_models.py` | Fetch the PaddleOCR Modern (PP-StructureV3/PP-OCRv6) models online once. |
| `glm_serve.sh` | Start the local GLM-OCR MLX server on `:8080`. |
| `ab_harness.py`, `eval_model.py` | Provider/model benchmarking (developer tools). |

### Common troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `ImportError: libGL.so.1` (Linux) | Install `libgl1 libglib2.0-0` (§3). |
| OCR fails only for the **GLM** engine; others fine | MLX server not running → `tools/glm_serve.sh`; verify with the curl health check (§6.4). |
| VietOCR raises "weights/config missing" | Place `config.yml` + `vgg_transformer.pth` in `MODEL_DIR/vietocr/` or set `VIETOCR_WEIGHTS`; run `scripts/setup_offline.sh`. |
| Models try to download but you're offline | `OFFLINE=1` only covers HF/Argos/Stanza. Pre-fetch PaddleOCR models online once (`tools/warmup_modern_models.py`) and Qwen via `tools/download_chat_model.py`. |
| Chat/summarize returns HTTP 202 "warming up" | The local model is still loading in the background; retry after a few seconds. |
| Sessions drop on every restart | `SECRET_KEY` is unset (random per process). Set a fixed `SECRET_KEY`. |
| Login fails with seeded creds | They may have been changed; reset via `/admin` (as another admin) or recreate the DB (deletes data). |
| App starts under gunicorn but DB is empty / login fails | `seed_admin` runs only under `python app.py`. Initialize the DB first — see [DEPLOYMENT.md](./DEPLOYMENT.md). |
| Slow LLM responses after OCR | Known: PaddleOCR collapses torch CPU threads; the code restores them per generation. You can tune `LLM_TORCH_THREADS`. |

---

## 9. What this install does **not** require
- **No Node.js / npm** (no frontend build).
- **No external database server** (SQLite file).
- **No message broker / queue / Redis** — single-process, in-memory RAG index.
- **No `gunicorn`/`waitress`** for development (`python app.py` is sufficient). Production
  WSGI is covered in [DEPLOYMENT.md](./DEPLOYMENT.md).
