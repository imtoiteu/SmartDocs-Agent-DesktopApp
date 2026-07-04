#!/usr/bin/env bash
#
# glm_serve.sh — start the local GLM-OCR model server (MLX, Apple Silicon).
#
# GLM-OCR is a vision OCR model served as a long-lived, OpenAI-compatible HTTP
# server. SmartDocs' "GLM OCR" engine is a CLIENT of this server — it does NOT
# spawn it. Start this once (it holds the model resident between requests); the
# SmartDocs adapter health-checks the port and errors clearly if it is down.
#
# Usage:
#   tools/glm_serve.sh            # serve on :8080 (matches mlx_config.yaml)
#   GLM_PORT=9090 tools/glm_serve.sh
#   GLM_PRELOAD=false tools/glm_serve.sh   # lazy: load model on first request
#
# The model ($GLM_MODEL, default mlx-community/GLM-OCR-bf16) is loaded from the
# PROJECT-LOCAL HF cache (<MODEL_DIR>/huggingface/hub) and PRELOADED at startup
# by default, so the port only opens once inference is actually ready.
# Override paths with GLM_ROOT / GLM_MLX_PYTHON if your checkout differs.
set -euo pipefail

# SmartDocs-Agent root = one level up from tools/
AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load .env so GLM_ROOT / GLM_MLX_PYTHON set there are picked up automatically
if [[ -f "$AGENT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$AGENT_DIR/.env"
  set +a
fi

# GLM directory (clean-clone friendly): explicit GLM_OCR_DIR / GLM_ROOT wins,
# otherwise the vendored copy inside THIS repo (<repo>/GLM-OCR).
GLM_OCR_DIR="${GLM_OCR_DIR:-${GLM_ROOT:-$AGENT_DIR/GLM-OCR}}"
GLM_ROOT="$GLM_OCR_DIR"
GLM_MLX_PYTHON="${GLM_MLX_PYTHON:-$GLM_ROOT/.venv-mlx/bin/python}"
GLM_PORT="${GLM_PORT:-8080}"
GLM_MODEL="${GLM_MODEL:-mlx-community/GLM-OCR-bf16}"

if [[ -z "$GLM_ROOT" ]] || [[ ! -x "$GLM_MLX_PYTHON" ]]; then
  echo "ERROR: MLX python not found at ${GLM_MLX_PYTHON:-<unresolved>}" >&2
  echo "       Create the repo-local GLM venv:  scripts/setup_glm.sh" >&2
  echo "       Or set GLM_OCR_DIR / GLM_MLX_PYTHON in .env for an external checkout." >&2
  echo "       Default layout: <repo>/GLM-OCR/.venv-mlx/bin/python" >&2
  exit 1
fi

# ── Project-local Hugging Face cache ─────────────────────────────────────────
# mlx_vlm.server resolves models through huggingface_hub (snapshot_download /
# scan_cache_dir), which reads HF_HUB_CACHE at import time. SmartDocs keeps ALL
# models in the project-local hub (<MODEL_DIR>/huggingface/hub) so the project
# folder stays portable/offline — export the redirect BEFORE starting the
# server so $GLM_MODEL is downloaded/loaded from there, NOT ~/.cache/huggingface.
# Legacy fallback: a model that exists ONLY in the global cache (downloaded by
# an older server run) keeps working un-redirected — migrate it project-local
# with 'scripts/setup_glm.sh --precache-mlx'.
MODEL_DIR="${MODEL_DIR:-$AGENT_DIR/models}"
case "$MODEL_DIR" in /*) ;; *) MODEL_DIR="$AGENT_DIR/${MODEL_DIR#./}" ;; esac
PROJ_HF_HOME="$MODEL_DIR/huggingface"
PROJ_HF_HUB="$PROJ_HF_HOME/hub"
GLOBAL_HF_HUB="$HOME/.cache/huggingface/hub"
GLM_MODEL_REPO_DIR="models--$(printf '%s' "$GLM_MODEL" | sed 's|/|--|g')"

# "Complete in <hub>": one snapshot revision whose config.json AND at least one
# .safetensors weight RESOLVE (-e follows symlinks, so the dangling links of an
# aborted download do not count).
glm_model_complete_in() {
  local d w
  for d in "$1/$GLM_MODEL_REPO_DIR/snapshots"/*/; do
    if [ -e "${d}config.json" ]; then
      for w in "${d}"*.safetensors; do
        [ -e "$w" ] && return 0
      done
    fi
  done
  return 1
}

if glm_model_complete_in "$PROJ_HF_HUB"; then
  export HF_HOME="$PROJ_HF_HOME" HF_HUB_CACHE="$PROJ_HF_HUB" TRANSFORMERS_CACHE="$PROJ_HF_HUB"
  HF_CACHE_NOTE="$PROJ_HF_HUB (project-local; model cached)"
elif glm_model_complete_in "$GLOBAL_HF_HUB"; then
  HF_CACHE_NOTE="$GLOBAL_HF_HUB (LEGACY global cache — model not project-local yet;
             migrate it with: scripts/setup_glm.sh --precache-mlx)"
else
  mkdir -p "$PROJ_HF_HUB"
  export HF_HOME="$PROJ_HF_HOME" HF_HUB_CACHE="$PROJ_HF_HUB" TRANSFORMERS_CACHE="$PROJ_HF_HUB"
  HF_CACHE_NOTE="$PROJ_HF_HUB (project-local; model NOT cached — first start
             downloads it HERE, needs internet once; or pre-cache with
             scripts/setup_glm.sh --precache-mlx)"
fi

# ── Preload ───────────────────────────────────────────────────────────────────
# GLM_PRELOAD=true (default): pass --model so mlx_vlm.server loads $GLM_MODEL at
# STARTUP (inside the FastAPI lifespan) — the port only opens once the model is
# ready for inference, so "listening" is a truthful readiness signal and clients
# never hit a half-started server. GLM_PRELOAD=false restores lazy loading
# (first request loads the model; readiness then comes from GET /health).
GLM_PRELOAD="${GLM_PRELOAD:-true}"
case "$(printf '%s' "$GLM_PRELOAD" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on) GLM_PRELOAD="true" ;;
  *)             GLM_PRELOAD="false" ;;
esac

echo "Starting GLM-OCR MLX server ($GLM_MODEL) on :$GLM_PORT …"
echo "  GLM_ROOT : $GLM_ROOT"
echo "  python   : $GLM_MLX_PYTHON"
echo "  HF cache : $HF_CACHE_NOTE"
echo "  preload  : $GLM_PRELOAD"
echo "  (Ctrl-C to stop. The model is held resident between requests.)"
if [ "$GLM_PRELOAD" = "true" ]; then
  exec "$GLM_MLX_PYTHON" -m mlx_vlm.server --trust-remote-code --port "$GLM_PORT" --model "$GLM_MODEL"
else
  exec "$GLM_MLX_PYTHON" -m mlx_vlm.server --trust-remote-code --port "$GLM_PORT"
fi
