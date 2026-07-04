# Running SmartDocs-Agent (English)

This is the practical guide to running SmartDocs-Agent locally with the
`scripts/` launchers. The scripts resolve the Python virtualenv and repository
paths automatically — **you never have to activate a venv or `cd` anywhere.**

> GLM OCR is **optional** and runs only on Apple Silicon (MLX). The web app and
> the Legacy / VietOCR / Modern OCR engines work fine without it.
> **Linux / Windows:** see [INSTALLATION.md](INSTALLATION.md) and the platform
> support matrix in the README — everything below except the GLM MLX server
> applies there too (Windows needs Git Bash or WSL for `scripts/*.sh`).

---

## 0. Clean-clone quick path (macOS Apple Silicon)

The complete from-zero sequence — clone to running app. Run each step online
once; afterwards the app works fully offline.

**Prerequisite — Python 3.10.** The main venv REQUIRES Python 3.10
(3.12/3.13/3.14 cannot install `paddlepaddle`/`Pillow 10.2.0`; `setup.sh`
rejects them instead of creating a broken venv):

```bash
brew install python@3.10
```

```bash
git clone <repo-url> SmartDocs-Agent
cd SmartDocs-Agent
chmod +x scripts/*.sh tools/*.sh        # git usually preserves this; belt & braces
cp .env.example .env                    # defaults are fine for local testing

scripts/setup.sh                        # 1. main venv + requirements + folders
scripts/setup_glm.sh --precache-layout  # 2. GLM venvs + layout model (Apple Silicon)
scripts/setup_offline.sh                # 3. ALL offline AI models (Qwen 1.5B, PhoBERT,
                                        #    embeddings, VietOCR weights+config, Argos, Paddle)
scripts/check.sh                        # 4. environment / runtime check
scripts/check_offline.sh                # 5. model readiness + REAL Argos translation smoke test

scripts/start_glm.sh -b                 # 6. GLM MLX server in background (logs/glm.log)
scripts/start.sh                        # 7. web app (foreground) → http://localhost:5002
```

Log in with the first-run seeded accounts — **change them immediately**:
`admin / admin123` (admin) or `user / user123` (user); manage in `/admin`.

**After these steps, all of the following must work** (this is the clean-clone
acceptance list):

- login, upload, document management
- PaddleOCR **Legacy** and **Modern** OCR (models cached by step 3)
- **VietOCR** OCR (weights + `models/vietocr/config.yml` from step 3)
- **GLM OCR** (MLX server from step 6 + layout model from step 2)
- AI **Chat**, **AI Rewrite** and the **Agent** on the local **Qwen 2.5 1.5B** (no
  3B download must ever be triggered)
- **online** translation (Google, needs internet) and **offline** translation
  (Argos — step 5 already smoke-tested en→vi and vi→en for real)
- summarization (PhoBERT + extractive fallback), semantic RAG embeddings

If any line of `scripts/check_offline.sh` is ❌, its message names the exact
re-run command — fix before testing the UI.

---

## 1. One-time setup

```bash
scripts/setup.sh
```

This:

- finds an existing virtualenv (`./.venv`, or the parent `../.venv`), or creates
  `./.venv` if none exists — it never clobbers a working venv;
- **enforces Python 3.10 for the main venv** (3.11 tolerated with a warning).
  New venvs are created from `python3.10` → `/opt/homebrew/bin/python3.10` →
  `/usr/local/bin/python3.10` → `python3.11`; it never silently falls back to a
  newer `python3` (3.12–3.14 can't install `paddlepaddle`/`Pillow 10.2.0`). If
  no supported Python exists it stops with `brew install python@3.10` — no
  broken venv is created. An existing `./.venv` on an unsupported Python is
  recreated with `scripts/setup.sh --reset-venv` (a venv outside the repo is
  never auto-deleted — remove it yourself);
- installs `requirements.txt` into it — **fail-fast**: if pip fails, setup stops
  immediately and later steps must not be run;
- verifies the core imports (flask, PIL, yaml, torch, transformers, vietocr,
  argostranslate, sentence_transformers) before declaring "Setup complete";
- creates `.env` from `.env.example` if you don't have one yet;
- creates the runtime folders `logs/`, `uploads/`, `artifacts/`.

> The GLM venvs are separate: `scripts/setup_glm.sh` accepts Python 3.10–3.12
> for `GLM-OCR/.venv-mlx` / `.venv-sdk`. Do **not** use Python 3.14 anywhere.

## 2. Check the environment

```bash
scripts/check.sh
```

Reports Python + venv, key dependencies, the state of the web and GLM ports, and
live health for both SmartDocs and (optionally) the GLM server. It changes
nothing and never fails just because GLM is down.

For **AI model / offline readiness** (chat, AI rewrite, VietOCR config+weights,
Argos, GLM layout) run the companion diagnostic:

```bash
scripts/check_offline.sh
```

It prints, per feature, whether it is usable now, needs a one-time online setup,
or is running on a built-in fallback.

## 2b. Offline AI models (one-time, needs internet)

With `OFFLINE=1` (the default) AI models load only from local caches. The web
app, login, upload, document management and basic correction work immediately,
but **chat, AI rewrite, VietOCR, offline translation and GLM OCR** must be primed
once while online. Run the wrapper (it resolves the main venv Python automatically):

```bash
scripts/setup_offline.sh                    # always uses the main venv Python
```

This caches: the **default local LLM Qwen 2.5 1.5B** (used for chat, AI rewrite
and the agent), PhoBERT, the RAG embedding model, the PaddleOCR models, the
VietOCR weights **and** `models/vietocr/config.yml`, and the Argos translation
packages. Larger models (e.g. 3B) are downloaded only if you opt in via `.env`.
Full guide: **[OFFLINE_SETUP_EN.md](OFFLINE_SETUP_EN.md)**.

## 3. Start

### Full stack (recommended)

```bash
scripts/start.sh
```

- Starts the GLM server in the background **if** `ENABLE_GLM=true` and the MLX
  venv is present; otherwise prints a clear warning and continues without it.
- Starts the web app in the foreground. Press **Ctrl-C** to stop the web app
  (and the GLM server, if this command started it).

Open **http://localhost:5002** (or your `SMARTDOCS_PORT`) and log in.

### Individual services

```bash
scripts/start_web.sh        # only the web app (foreground)
scripts/start_web.sh -b     # only the web app (background -> logs/web.log)

scripts/start_glm.sh        # only the GLM server (foreground)
scripts/start_glm.sh -b     # only the GLM server (background -> logs/glm.log)
```

## 4. Stop

```bash
scripts/stop.sh             # stop background web + GLM (only what the scripts started)
scripts/stop.sh web         # stop only the web app
scripts/stop.sh glm         # stop only the GLM server
scripts/stop.sh --force     # ALSO kill whatever holds the port (use with care)
```

By default `stop.sh` only stops processes it started itself (tracked via PID
files in `logs/`). It will **not** kill an unrelated process that merely happens
to hold the port — important on shared machines. Pass `--force` to also stop a
stale/untracked process on the configured port. Foreground services (started
without `-b`) are stopped with **Ctrl-C**.

---

## Configuration (`.env`)

Copy `.env.example` to `.env` and edit. The runtime knobs the scripts use:

| Variable         | Default                          | Meaning                                            |
|------------------|----------------------------------|----------------------------------------------------|
| `SMARTDOCS_PORT` | `5002`                           | Web app port (scripts map it to the app's `PORT`). |
| `GLM_PORT`       | `8080`                           | GLM model server port.                             |
| `GLM_MODEL`      | `mlx-community/GLM-OCR-bf16`     | Model label used by the health probe.              |
| `ENABLE_GLM`     | `true`                           | Whether `start.sh` tries to launch GLM.            |

Everything else in `.env` (models, devices, API keys, offline mode) is read
directly by the app — see the comments in `.env.example`.

---

## Testing with and without GLM

**Without GLM** (any machine, including non-Mac):

```bash
ENABLE_GLM=false scripts/start.sh
```

The app starts normally. In the UI, Legacy PaddleOCR, PaddleOCR Modern, and
VietOCR all work. Selecting the **GLM OCR** engine shows a clear error toast
telling you to start the GLM server — nothing crashes.

**With GLM** (Apple Silicon only) — clean-clone setup, no external paths:

```bash
scripts/setup.sh                        # main SmartDocs venv (keeps Pillow 10.2.0 for VietOCR)
scripts/setup_glm.sh --precache-layout  # creates BOTH GLM venvs (Py 3.10–3.12) + mlx_config.yaml
                                        #   .venv-mlx  (MLX server, from glm-mlx-lock.txt)
                                        #   .venv-sdk  (glmocr CLI + torch, from glm-sdk-lock.txt)
                                        # writes pipeline.layout.model_dir and caches PP-DocLayoutV3
scripts/check.sh                        # expect ".venv-mlx imports: OK" and ".venv-sdk imports: OK"
scripts/check_offline.sh                # expect "GLM layout config: OK" + layout model cached
scripts/start_glm.sh -b                 # start the model server (first run loads the model)
scripts/start.sh                        # full stack; then expect "GLM health: 200"
```

`glmocr` self-hosted mode **requires** `pipeline.layout.model_dir`. `setup_glm.sh`
writes it into `mlx_config.yaml` (default `PaddlePaddle/PP-DocLayoutV3_safetensors`,
override with `GLM_LAYOUT_MODEL_DIR`). `--precache-layout` downloads that checkpoint
into the **default** HF cache — where `glm_adapter.py` looks — so it works offline.
Without it, GLM OCR fails with *"pipeline.layout.model_dir is required for
self-hosted layout detection"*.

**Why three separate Python environments.** The SmartDocs UI does **not** import
GLM-OCR in-process. `services/ocr_engines/glm_adapter.py` runs `glmocr.cli` as a
**subprocess** using `GLM-OCR/.venv-sdk/bin/python` (resolved by `config.py`,
which prefers `.venv-sdk`, then `.venv-mlx`). This keeps three envs isolated:

| Environment | Role | Pillow |
|---|---|---|
| main SmartDocs venv | Flask + Legacy/VietOCR/Modern OCR | **10.2.0** (VietOCR pins it) |
| `GLM-OCR/.venv-mlx` | MLX model server (`mlx_vlm`) — no torch, no glmocr | 12.x |
| `GLM-OCR/.venv-sdk` | glmocr CLI / layout detector (torch + editable glmocr) | 12.x |

Because glmocr's Pillow 12.x lives only in `.venv-sdk`, it never collides with
VietOCR's `Pillow==10.2.0` in the main venv. `setup_glm.sh` requires Python
3.10/3.11/3.12 (rejects 3.13/3.14 unless you pass `--force`).

GLM path resolution is repo-local by default:

- `GLM_OCR_DIR` defaults to `<repo>/GLM-OCR` (the vendored copy).
- The GLM interpreter is the first that exists of
  `<repo>/GLM-OCR/.venv-mlx/bin/python` or `.../.venv-sdk/bin/python`.
- To use an **external** GLM-OCR checkout instead, set `GLM_OCR_DIR=/your/path`
  (and optionally `GLM_SDK_PYTHON` / `GLM_MLX_PYTHON`) in `.env`. Nothing is
  hardcoded to any machine.

Then in the UI: OCR tab → upload an image → pick **🧠 GLM OCR (Structured)** →
Run OCR.

---

## Troubleshooting

- **`UNSUPPORTED Python …` / `No matching distribution found for paddlepaddle`** —
  the venv was created with Python 3.12/3.13/3.14. Install 3.10
  (`brew install python@3.10`) and recreate: `scripts/setup.sh --reset-venv`.
- **`Main venv is incomplete (missing imports: …)`** — `pip install` didn't
  finish (or ran on the wrong Python). Re-run `scripts/setup.sh` with Python
  3.10 and make sure it ends with "Setup complete".
- **`Flask is not installed`** — run `scripts/setup.sh`.
- **`Port 5002 already in use`** — SmartDocs is already running; `scripts/stop.sh`,
  or set a different `SMARTDOCS_PORT`.
- **GLM health not 200** — make sure `scripts/start_glm.sh` is running and the
  model finished loading (watch `logs/glm.log`). GLM is Apple-Silicon only.
- **Logs** — background services write to `logs/web.log` and `logs/glm.log`.
