# Offline / Clean-Clone Setup (English)

SmartDocs-Agent is **offline-first**: with `OFFLINE=1` (the default) every AI
model is loaded **only** from local caches — nothing is downloaded at runtime.
That means a fresh clone must be **primed once while online** before those
features work. This guide lists exactly which models each feature needs, how to
cache them, and how to verify readiness.

> The web app, login, upload, document management and **basic text correction**
> work immediately with no model downloads. Everything below is about the AI
> features (OCR engines beyond Paddle, chat, rewrite, translation, GLM).

---

## TL;DR — one-time priming of a clean clone

```bash
scripts/setup.sh                        # main venv + deps + .env + folders
scripts/setup_offline.sh                # download ALL offline models (online, once)
scripts/setup_glm.sh --precache         # (Apple Silicon only) GLM venvs + layout model + MLX server model
scripts/check_offline.sh                # verify: every feature usable / needs-setup / fallback
scripts/start.sh                        # run the stack
```

> **Always use `scripts/setup_offline.sh`, not `python tools/setup_offline.py`.**
> A bare `python` often resolves to the SYSTEM interpreter, which has none of the
> app's dependencies — the run then "succeeds" for pure downloads but silently
> skips VietOCR `config.yml`, Argos and embeddings with `No module named 'vietocr'
> / 'PIL' / …`. The wrapper resolves the main SmartDocs venv exactly the way
> `scripts/check.sh` does (`$SMARTDOCS_PYTHON` → `<repo>/.venv` → `<repo>/../.venv`)
> and refuses to run with anything else. `tools/setup_offline.py` itself also
> prints which Python it runs under and whether `PIL` / `vietocr` /
> `argostranslate` / `sentence_transformers` import — and warns loudly if the
> interpreter looks wrong. All four are provided by `requirements.txt` in the
> main venv.

---

## What each feature needs

| Feature | Needs (local) | Cached by | Missing → |
|---|---|---|---|
| Legacy / Modern Paddle OCR | PaddleX model cache in `~/.paddlex/official_models/` (override: `PADDLE_PDX_CACHE_HOME`) | `setup_offline.py` (Legacy/VietOCR pipeline; Modern via `tools/warmup_modern_models.py`) or first online OCR run | ⚠️ downloads on first run (needs internet once) |
| **VietOCR** | `models/vietocr/config.yml` **+** `vgg_transformer.pth` | `setup_offline.py` | OCR returns a clear "run setup_offline" error |
| **GLM OCR** | `.venv-sdk` + `mlx_config.yaml` (`pipeline.layout.model_dir`) + PP-DocLayoutV3 **and** `mlx-community/GLM-OCR-bf16` in `models/huggingface/hub/` + MLX server | `setup_glm.sh --precache` (= `--precache-layout` + `--precache-mlx`) | "pipeline.layout.model_dir is required" / server-not-running toast / first start downloads the server model |
| **AI Chat / AI Rewrite / Agent** | local **Qwen 2.5 1.5B** (the default, `CHAT_MODEL` = `QWEN_MODEL` = `FALLBACK_CHAT_MODEL`) | `setup_offline.py` | "No chat model could be loaded" |
| PhoBERT summarization | `vinai/phobert-base-v2` | `setup_offline.py` | **falls back** to extractive TF-IDF (still works) |
| RAG embeddings | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | `setup_offline.py` | **falls back** to char-hash retrieval (still works) |
| **Offline translation** | Argos packages in `models/argos/packages/` | `setup_offline.py` | online Google translate still works |

Notes:

- **Default local LLM = Qwen 2.5 1.5B-Instruct.** Chat, AI rewrite and the agent's
  local provider all use it, so `setup_offline.py` downloads it **once**. Larger
  models (e.g. 3B) are **not** the default and are **not** downloaded unless you set
  `CHAT_MODEL`/`QWEN_MODEL` in `.env` — the 3B model is optional and opt-in. A
  missing 3B never makes chat/rewrite report themselves as broken.
- **GLM layout model lives in the PROJECT-LOCAL HF cache** (`models/huggingface/hub/`),
  same as every other model. `glm_adapter.py` exports that cache to the `glmocr`
  subprocess, so `setup_glm.sh --precache-layout` caches the checkpoint there
  (migrating a copy from `~/.cache/huggingface` left by older versions instead of
  re-downloading); afterwards runtime works with `HF_HUB_OFFLINE=1`. A layout model
  that exists only in the global cache still works (legacy fallback) but is flagged
  by `check_offline.sh` for re-priming.
- **The GLM MLX server model (`mlx-community/GLM-OCR-bf16`) is project-local too.**
  `tools/glm_serve.sh` exports the project hub before starting `mlx_vlm.server` and
  **preloads** the model at startup — the port only opens once inference is actually
  ready, so "listening" is a truthful readiness signal. Pre-cache it while online
  with `setup_glm.sh --precache-mlx` (a copy already in `~/.cache/huggingface` is
  migrated, not re-downloaded); without pre-caching, the **first** server start
  downloads it (internet needed once). While a cold server is still loading, GLM
  OCR in the UI answers *"GLM server is still loading the OCR model. Please wait
  and retry."* instead of a fatal connection error, and `scripts/check.sh` shows
  "GLM server starting/loading model". `GLM_PRELOAD=false` restores lazy loading.

---

## GLM self-hosted layout config

`glmocr` self-hosted mode **requires** `pipeline.layout.model_dir`. `setup_glm.sh`
writes it into `GLM-OCR/mlx_config.yaml`:

```yaml
pipeline:
  maas: { enabled: false }
  ocr_api: { api_host: localhost, api_port: 8080, model: mlx-community/GLM-OCR-bf16, api_mode: openai, verify_ssl: false }
  layout:
    model_dir: PaddlePaddle/PP-DocLayoutV3_safetensors   # HF id or local dir
    device: cpu
```

- Override the checkpoint with `GLM_LAYOUT_MODEL_DIR` in `.env` (HF id or absolute
  local directory).
- If an **older** `mlx_config.yaml` (generated before this fix) lacks
  `layout.model_dir`, `setup_glm.sh` regenerates it (backing up the old one to
  `mlx_config.yaml.bak`).

---

## Verifying readiness

```bash
scripts/check_offline.sh
```

Reports, per feature: **usable now**, **needs online setup**, or **running on a
fallback** — plus the main Python/Pillow, VietOCR config/weights, Paddle cache,
both GLM venvs, the `pipeline.layout.model_dir` value, and **two separate GLM
model rows** (the PP-DocLayoutV3 layout detector and the MLX server model), each
checked in the project-local hub. It changes nothing — the GLM server state probe
uses `GET /health` (never a request that would trigger a model load).

`scripts/check.sh` covers the runtime/venv side and points here for the model matrix.

The readiness check is **completeness-aware**: a model counts as ready only when a
full HF snapshot (config + weights) resolves in the app's **project-local** cache
(`models/huggingface/hub/`) — a half-finished or aborted download reports **missing**,
not ✅, so the check can't disagree with what the app can actually load. A model
that exists only in the global `~/.cache/huggingface` does NOT count — the app
never loads from there. (This includes both GLM models; a copy found only in the
global cache is reported as needing `scripts/setup_glm.sh --precache-layout` /
`--precache-mlx`.)

---

## Troubleshooting

- **GLM OCR fails with `Failed to connect to API server at http://localhost:8080/v1/chat/completions within 30 seconds`**
  while `logs/glm.log` shows `Loading model from: mlx-community/GLM-OCR-bf16` /
  `Fetching 9 files: …%` — the MLX server was **cold-starting**: the port was
  already listening while the model was still loading (or first-run downloading),
  and the glmocr SDK's 30 s connect window expired. Fixed on three levels:
  `tools/glm_serve.sh` now **preloads** the model at startup (the port only opens
  once inference is ready), the UI answers *"GLM server is still loading the OCR
  model. Please wait and retry."* instead of that raw error, and
  `scripts/check.sh` reports "GLM server starting/loading model; wait or check
  logs/glm.log". Avoid the cold-start download entirely by pre-caching once
  while online:
  ```bash
  scripts/setup_glm.sh --precache-mlx
  ```
- **Models were downloaded into `~/.cache/huggingface` instead of `models/`** (the
  app then says a model is missing although `setup_offline` "succeeded") — this was
  a cache mismatch: HF libraries freeze their cache path at import time, and an
  early import beat the project-local redirect. Fixed: `setup_offline.py` now
  forces `HF_HOME`/`HF_HUB_CACHE` to `models/huggingface(/hub)` before ANY HF
  import, downloads with an explicit `cache_dir`, and **[7/7] validates** every
  model with `local_files_only=True` from the project cache — it never prints
  `OFFLINE-READY` without that validation passing. Just re-run:
  ```bash
  scripts/setup_offline.sh
  ```
  Models already complete in the global cache are **copied** into
  `models/huggingface/hub/` automatically (snapshots/blobs/refs preserved) — no
  re-download. Both GLM models are project-local too (`setup_glm.sh --precache`
  migrates them the same way), so once `scripts/check_offline.sh` is all-green
  the global `~/.cache/huggingface` is no longer needed by SmartDocs and may be
  reclaimed entirely.
- **`UNSUPPORTED Python …` / `Main venv is incomplete (missing imports: …)`** —
  `setup_offline.sh` now refuses to download anything when the environment is
  broken. The main venv REQUIRES **Python 3.10** (3.11 tolerated); 3.12–3.14
  cannot install `paddlepaddle`/`Pillow 10.2.0` at all. Fix the venv first:
  ```bash
  brew install python@3.10          # macOS, if 3.10 is missing
  scripts/setup.sh --reset-venv     # recreate ./.venv with a supported Python
  scripts/setup_offline.sh          # then prime the models
  ```
  These are **environment** errors, not missing-model errors — none of the
  per-model rows mean anything until the venv is complete.
- **Setup printed `No module named 'vietocr' / 'PIL' / 'argostranslate' / 'sentence_transformers'`** —
  you ran the tool with the wrong (system) Python. Use the wrapper:
  ```bash
  scripts/setup_offline.sh
  ```
- **`check_offline.sh` shows a required model missing right after setup** — the
  download was interrupted (or a hard crash aborted `setup_offline.py` mid-run).
  Just re-run it; completed assets are skipped:
  ```bash
  scripts/setup_offline.sh
  ```
  `setup_offline.py` runs the crash-prone PaddleOCR step **last**, so VietOCR,
  Argos and the Qwen/PhoBERT/embedding models are already on disk even if Paddle
  misbehaves on that machine.
- **"No chat model could be loaded" but the check said ✅ previously** — you were
  on the old check that only tested directory existence. Re-pull, re-run
  `check_offline.sh`; if it now shows the Local LLM missing, run `setup_offline.py`.
- **VietOCR fails with `'NoneType' object is not iterable`** — the old symptom of an
  **empty or invalid** `models/vietocr/config.yml` (vietocr's config loader crashes
  that way on a file that parses to nothing). `scripts/setup_offline.sh` now
  validates an existing config.yml and **regenerates** it (backup: `config.yml.bak`)
  using vietocr's own `Cfg.load_config_from_name()`, then verifies the result by
  actually instantiating the Predictor. The runtime and `check_offline.sh` also
  validate content now — an invalid file reports the precise reason, never ✅.
- **"Offline translation … not installed" while packages exist on disk** — the
  error and `/api/translate/status` now name the exact missing pair, the installed
  pairs, and the package directory (`models/argos/packages`). If packages exist on
  disk but argostranslate can't load them, the status says so explicitly — restart
  the app (or hit the status endpoint) and check the server log for the underlying
  loader error.
- **Argos offline translation missing / a pair won't install** — each pair installs
  independently, so others still succeed. Install the core pair manually:
  ```bash
  argospm install translate-en_vi
  argospm install translate-vi_en
  # …or drop the .argosmodel files into models/argos/packages/
  ```
  Online Google translate keeps working regardless.

---

## Fully offline afterwards

Once primed, set (or keep) `OFFLINE=1` in `.env`. The app loads HuggingFace,
Argos and Stanza models only from `MODEL_DIR` and never reaches the network. Copy
the whole project folder (including `models/` — both GLM models, the layout
detector and the MLX server model, are in there too now) to an air-gapped machine
to run without internet; only the PaddleX cache (`~/.paddlex/official_models`)
lives outside the project folder.
