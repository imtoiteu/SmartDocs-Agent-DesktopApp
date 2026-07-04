# SmartDocs-Agent

An offline-first, document-centric AI platform built on Flask. It combines four OCR
engines, classical + neural AI services (correction, translation, summarization,
RAG chat), and an LLM **agent** that orchestrates those capabilities as tools — all
behind one web UI and HTTP API.

- **OCR**: Legacy PaddleOCR (PP-OCRv5), PaddleOCR Modern (PP-StructureV3 + PP-OCRv6), VietOCR, GLM-OCR
- **AI services**: text correction, translation (Google / Argos), summarization (TF-IDF / PhoBERT / Qwen rewrite), RAG chat
- **Agent**: plans and chains the tools above, with document scoping and durable sessions
- **Storage**: SQLite + an in-memory RAG index, files under `uploads/`

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full technical architecture and
[docs/diagrams/](docs/diagrams/) for editable diagrams.

---

## Quick Start

**Prerequisites:** Python **3.10** and `git`. **Node/npm are *not* required** —
the frontend is plain vendored JavaScript with no build step. macOS, Ubuntu/Linux, and
Windows are supported (see [docs/INSTALLATION.md](docs/INSTALLATION.md) for per-OS details).

> **Python 3.10 is REQUIRED for the main venv** (3.11 tolerated, unverified).
> **3.12/3.13/3.14 do not work**: `paddlepaddle>=3.0.0` and `Pillow==10.2.0`
> (pinned by VietOCR) publish no wheels there, so `pip install -r requirements.txt`
> fails. `scripts/setup.sh` auto-picks `python3.10` and refuses newer interpreters
> (recreate a bad venv with `scripts/setup.sh --reset-venv`). macOS:
> `brew install python@3.10`. This applies only to the **main** venv — the GLM
> venvs (`GLM-OCR/.venv-mlx` / `.venv-sdk`) are separate and may use Python
> 3.10–3.12 (see `scripts/setup_glm.sh`).

### Fastest start — the `scripts/` launchers (recommended)

The scripts resolve the virtualenv and repo paths for you — **you never have to
activate a venv or know where it lives.** Run them from anywhere.

```bash
cd SmartDocs-Agent
scripts/setup.sh        # create/find .venv, install deps, seed .env, make folders
scripts/check.sh        # verify Python, deps, ports, GLM + SmartDocs health
scripts/start.sh        # start the full local stack (GLM too, if enabled/available)
```

Then open **http://localhost:5002** (or the `SMARTDOCS_PORT` you set in `.env`) and log in.

**Offline-first note:** with `OFFLINE=1` (the default) AI models load only from
local caches. The web app, login, upload, document management and basic correction
work immediately, but **chat, AI rewrite, VietOCR, offline translation and GLM OCR
need a one-time online priming**:

```bash
scripts/setup_offline.sh                  # cache local LLM (Qwen 2.5 1.5B — chat/rewrite/agent),
                                          # PhoBERT, embeddings, VietOCR weights+config.yml, Argos
                                          # (wrapper — always uses the main venv Python)
scripts/check_offline.sh                  # report: each feature usable / needs-setup / fallback
```

Full guide: **[docs/OFFLINE_SETUP_EN.md](docs/OFFLINE_SETUP_EN.md)** · **[docs/OFFLINE_SETUP_VI.md](docs/OFFLINE_SETUP_VI.md)**.

Individual services:

```bash
scripts/start_web.sh    # only the web app        (add -b to run in the background)
scripts/start_glm.sh    # only the GLM OCR server  (Apple-Silicon / MLX only, optional)
scripts/stop.sh         # stop background services (web + GLM)
```

**Optional GLM OCR — local MLX mode (Apple Silicon)** — uses the GLM-OCR vendored
inside this repo (`GLM-OCR/`); no external path needed on a clean clone. This is
`GLM_OCR_MODE=local_mlx`, the default on macOS Apple Silicon; on Windows/Linux
GLM defaults to `disabled` and can instead point at an external GLM server or
the MaaS cloud API (see the platform support matrix below and `.env.example`):

```bash
scripts/setup.sh                       # main SmartDocs venv (keeps Pillow 10.2.0 for VietOCR)
scripts/setup_glm.sh --precache        # BOTH GLM venvs + layout.model_dir + cache PP-DocLayoutV3 + GLM-OCR-bf16
scripts/check.sh                       # verify both venvs' imports, Pillow, ports, server readiness
scripts/check_offline.sh               # verify GLM layout config + BOTH GLM model caches
scripts/start_glm.sh -b                # start the GLM model server in the background
scripts/start.sh                       # full stack
```

> `--precache` caches BOTH GLM models into the **project-local** HF cache
> (`models/huggingface/hub` — the same cache as every other model):
> the PP-DocLayoutV3 layout checkpoint (`--precache-layout`; `glm_adapter.py`
> points glmocr there) and the MLX server's own model
> `mlx-community/GLM-OCR-bf16` (`--precache-mlx`; `tools/glm_serve.sh` points
> `mlx_vlm.server` there). Copies already in `~/.cache/huggingface` from older
> runs are migrated, not re-downloaded. Without a cached layout model + a
> `pipeline.layout.model_dir` in `mlx_config.yaml`, GLM OCR fails with
> *"pipeline.layout.model_dir is required for self-hosted layout detection"*;
> without a cached MLX model the FIRST server start downloads it (internet once).
>
> The server **preloads** its model at startup (port opens only when inference
> is ready — `GLM_PRELOAD=false` for lazy loading). While a cold server is still
> loading, the UI answers *"GLM server is still loading the OCR model. Please
> wait and retry."* and `scripts/check.sh` reports the loading state instead of
> pretending a listening port means ready.

**Three isolated Python environments** (this is the key to why GLM works without
breaking VietOCR):

| Env | Purpose | Pillow | Notes |
|---|---|---|---|
| main SmartDocs venv | Flask app + Legacy/VietOCR/Modern OCR | **10.2.0** (VietOCR pins it) | never imports glmocr |
| `GLM-OCR/.venv-mlx` | MLX **model server** (`mlx_vlm`) | 12.x | no torch, no glmocr; Apple Silicon |
| `GLM-OCR/.venv-sdk` | glmocr **CLI / layout** — what the UI drives | 12.x | torch + editable glmocr |

The SmartDocs UI never imports GLM-OCR in-process. `services/ocr_engines/glm_adapter.py`
runs `glmocr.cli` as a **subprocess** using `GLM-OCR/.venv-sdk/bin/python`, so
GLM's Pillow 12.x stays isolated and can't collide with the main venv's 10.2.0.

Reproducible dependency files:

- `requirements/glm-mlx-lock.txt` — pinned freeze for `.venv-mlx` (MLX server).
- `requirements/glm-sdk-lock.txt` — pinned freeze for `.venv-sdk` (torch + layout
  deps); `glmocr` itself is added by an editable install of the vendored `GLM-OCR/`.

`setup_glm.sh` requires Python 3.10/3.11/3.12 (rejects 3.13/3.14 unless `--force`).
To use an external GLM-OCR checkout, set `GLM_OCR_DIR=/path/to/GLM-OCR` in `.env`.
GLM stays optional: `ENABLE_GLM=false scripts/start.sh` runs SmartDocs without it,
and the other three OCR engines never depend on it.

Full guides: **[docs/RUN_EN.md](docs/RUN_EN.md)** · **[docs/RUN_VI.md](docs/RUN_VI.md)**.
Desktop-app packaging plan: **[docs/DESKTOP_BUILD.md](docs/DESKTOP_BUILD.md)**.

### Manual start (equivalent, no scripts)

```bash
# 1. Get the code and enter the project
cd SmartDocs-Agent

# 2. Create and activate a virtual environment — MUST be Python 3.10
python3.10 -m venv .venv           # macOS: brew install python@3.10 first
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies (~several GB incl. torch + paddle)
pip install -r requirements.txt

# 4. Create your env file (safe defaults; edit later for API keys / models)
cp .env.example .env

# 5. Run — first launch creates and seeds the SQLite database
python app.py
```

Then open **http://localhost:5002** (or the `SMARTDOCS_PORT` / `PORT` you set in `.env`) and log in.

> **First-run accounts (CHANGE IMMEDIATELY):** `admin / admin123` and `user / user123`.
> These are seeded on first launch ([models.py](models.py)). Reset passwords in the Admin
> console (`/admin`) before exposing the app to anyone.

**Convenience launchers** (create `.venv`, copy `.env`, install deps, then start):

```bash
bash run_mac.sh         # macOS / Linux
run_windows.bat         # Windows
```

> Note: the launch scripts look for a virtualenv at `../.venv` (the repo's parent) first,
> then a local `.venv`. Either works.

### What works out of the box vs. needs setup

| Capability | Works immediately | Needs extra setup |
|---|---|---|
| Legacy PaddleOCR, PaddleOCR Modern | ✅ (models fetched on first online OCR run) | pre-cache via `scripts/setup_offline.sh` for offline |
| VietOCR | — | `scripts/setup_offline.sh` — needs `vgg_transformer.pth` **and** `models/vietocr/config.yml` (both created by it) |
| GLM-OCR engine | — | local MLX (`scripts/setup_glm.sh --precache` + server) is **Apple Silicon only**; other OSes: `GLM_OCR_MODE=external_server` / `maas_api` (see matrix below) |
| Correction (rule-based), extractive summarization, text reading | ✅ | — |
| Translation (online) | ✅ (needs internet) | — |
| Translation (offline / Argos) | — | `scripts/setup_offline.sh` (Argos packages in `MODEL_DIR`) |
| RAG chat / AI rewrite / agent (local **Qwen 2.5 1.5B**, the default) | — with `OFFLINE=1` | `scripts/setup_offline.sh` caches the 1.5B model (larger models opt-in via `.env`) |
| Agent with cloud LLMs (Groq / Gemini) | — | API keys in `.env` (falls back to local Qwen) |

Verify readiness anytime with **`scripts/check_offline.sh`**.

### Platform support matrix

Development happens on macOS Apple Silicon and Linux; those columns are verified.
Windows columns are *expected* from the codebase (CPU torch/paddle wheels,
`run_windows.bat`, `platform_system` markers in `requirements.txt`) but not
regularly tested — prefer **WSL** on Windows for the scripted flow.

GLM OCR is **not** macOS-only: the *local MLX server* is, but `GLM_OCR_MODE`
(see `.env.example`) also supports connecting to an **external GLM-OCR
backend** (vLLM / SGLang / a Mac's MLX server over LAN) or the **Zhipu MaaS
cloud API** from any OS.

| Feature | macOS Apple Silicon | Linux | Windows | Notes |
|---|---|---|---|---|
| Web app / backend (Flask + SPA) | ✅ | ✅ | ✅ expected | `scripts/*.sh` need Git Bash/WSL on Windows; native: `run_windows.bat` or manual venv |
| Desktop wrapper (Tauri/Electron) | 🔜 plan | 🔜 plan | 🔜 plan | [docs/DESKTOP_MIGRATION_PLAN.md](docs/DESKTOP_MIGRATION_PLAN.md) — plan only, not implemented |
| PaddleOCR (Legacy + Modern) | ✅ | ✅ | ✅ expected | models auto-cache to `~/.paddlex/official_models/` on first online OCR run |
| VietOCR | ✅ | ✅ | ✅ expected | needs `scripts/setup_offline.sh` (weights + `config.yml`) |
| Argos offline translation | ✅ | ✅ | ✅ expected | packages in `models/argos/packages/` via `scripts/setup_offline.sh` |
| Qwen local HF chat / AI rewrite / agent | ✅ (CPU) | ✅ (CPU / CUDA) | ✅ expected (CPU / CUDA) | `LOCAL_LLM_MODEL` default Qwen2.5-1.5B-Instruct; larger models opt-in via `.env` |
| OpenAI-compatible LLM endpoint | ✅ | ✅ | ✅ expected | `LLM_PROVIDER=openai_compatible` + `OPENAI_COMPATIBLE_*` (vLLM/llama.cpp/LM Studio); wired into the agent chain today |
| GLM OCR — **local MLX server** (`local_mlx`) | ✅ | ❌ | ❌ | `mlx`/`mlx-vlm` wheels are **macOS/arm64 only**; on other OSes the default is `GLM_OCR_MODE=disabled` and the app just runs without GLM |
| GLM OCR — external server (`external_server`) | ✅ | ⚠️ unverified | ⚠️ unverified | `openai_compatible` protocol; the `glmocr` CLI venv (`GLM-OCR/.venv-sdk`, plain torch) + layout model are still needed locally |
| GLM OCR — served via **vLLM** | n/a (server side) | ⚠️ unverified (NVIDIA GPU) | ⚠️ via WSL, unverified | deploy GLM-OCR separately with vLLM, then SmartDocs connects as a client (`external_server`) |
| GLM OCR — served via **SGLang** | n/a (server side) | ⚠️ unverified (NVIDIA GPU) | ⚠️ via WSL, unverified | same client model as vLLM (`external_server`) |
| GLM OCR — MaaS / cloud API (`maas_api`) | ⚠️ unverified | ⚠️ unverified | ⚠️ unverified | Zhipu `layout_parsing` API; needs `GLM_MAAS_API_KEY` + internet; implemented via `glmocr --mode maas`, not yet tested end-to-end |
| GLM OCR — Ollama (`ollama`) | ❌ reserved | ❌ reserved | ❌ reserved | **not verified** — the adapter refuses the mode with a clear message until the integration is tested |
| Embeddings / RAG | ✅ | ✅ | ✅ expected | char-hash retrieval fallback if the model is missing |
| Offline model setup (`setup_offline.sh` / `--precache`) | ✅ | ✅ | ✅ via Git Bash/WSL expected | one-time online priming into `MODEL_DIR`; fully offline afterwards |

**Per-OS guidance:**

- **macOS Apple Silicon** — the fully-verified baseline. Local GLM MLX **is
  supported**: `scripts/setup_glm.sh --precache` + `scripts/start_glm.sh -b`
  (`GLM_OCR_MODE=local_mlx` is the default here).
- **Linux** — do **not** use local MLX (no wheels; the default is
  `GLM_OCR_MODE=disabled`). Use PaddleOCR/VietOCR locally for OCR. For GLM,
  deploy GLM-OCR separately on an NVIDIA-GPU box via **vLLM or SGLang** and
  connect SmartDocs as a client: `GLM_OCR_MODE=external_server` +
  `GLM_OCR_API_URL=http://<server>:<port>`.
- **Windows** — do **not** use local MLX. Use PaddleOCR/VietOCR locally;
  connect to a GLM-OCR server over LAN (`external_server`) or, when internet
  and an API key are acceptable, use `maas_api`. Running the GLM server itself
  under WSL with a GPU is an advanced, **unverified** route.

Full instructions: **[docs/INSTALLATION.md](docs/INSTALLATION.md)** (per-OS setup).
GLM backend modes in depth: **[docs/OCR_ENGINES.md](docs/OCR_ENGINES.md)**.
Clean-clone walkthrough: **[docs/RUN_EN.md](docs/RUN_EN.md)** · **[docs/RUN_VI.md](docs/RUN_VI.md)**.
Production deployment: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

---

## Running tests

```bash
pytest                 # full suite (root test_*.py + agent/tests)
pytest agent/tests     # agent layer only
```

## Repository layout

```text
app.py                  Flask app + OCR/upload/document routes (entrypoint)
auth.py  admin_bp.py    Auth + admin blueprints
chat_bp.py agent_bp.py  Chat (RAG) + Agent blueprints
config.py               Central configuration (reads .env)
models.py               SQLAlchemy models + DB helpers (SQLite)
services/               OCR engines + AI services (correction/translate/summary/chat)
agent/                  Agent core, LLM providers, tools, skills, knowledge, memory
static/  templates/     Frontend SPA + Jinja admin pages
tools/                  Offline-setup / model-download / GLM-serve / benchmark helpers
docs/                   Architecture, diagrams, installation, deployment
uploads/                User-uploaded files (UUID-named)
requirements.txt        Python dependencies
run_mac.sh run_windows.bat  Convenience launchers
```
