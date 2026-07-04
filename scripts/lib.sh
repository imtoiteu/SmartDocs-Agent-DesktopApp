#!/usr/bin/env bash
# ============================================================================
#  scripts/lib.sh — shared helpers for the SmartDocs-Agent local runtime.
#
#  This file is SOURCED by the other scripts (setup / start_* / stop / check).
#  It never runs anything on its own; it only defines variables + functions.
#
#  Responsibilities:
#    * resolve the repository root robustly (independent of the caller's CWD)
#    * load .env and normalise the friendly runtime variables into the exact
#      names the app + GLM server already read:
#          SMARTDOCS_PORT  ->  PORT              (read by config.py / app.py)
#          GLM_HOST/GLM_PORT ->  GLM_OCR_API_URL (read by config.py / adapter)
#          GLM_PORT         ->  exported for tools/glm_serve.sh
#      => no Python/business-logic changes are required.
#    * locate a usable Python interpreter (repo .venv, parent .venv, or system)
#    * small port / HTTP health helpers used by start.sh / check.sh
#
#  Compatible with the stock macOS Bash 3.2 (no bash-4-only features).
# ============================================================================

# --- Repo layout ------------------------------------------------------------
# lib.sh lives in <repo>/scripts, so the repo root is one level up. Resolve via
# the classic cd/pwd trick (portable; no `readlink -f`, which macOS lacks).
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$LIB_DIR/.." && pwd)"
LOG_DIR="$REPO_ROOT/logs"

# --- Pretty output ----------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RESET='\033[0m'; C_DIM='\033[2m'; C_RED='\033[31m'
  C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_BLUE='\033[34m'; C_BOLD='\033[1m'
else
  C_RESET=''; C_DIM=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_BOLD=''
fi

info()  { printf "${C_BLUE}==>${C_RESET} %s\n" "$*"; }
ok()    { printf "${C_GREEN}[ok]${C_RESET}  %s\n" "$*"; }
warn()  { printf "${C_YELLOW}[warn]${C_RESET} %s\n" "$*" >&2; }
err()   { printf "${C_RED}[err]${C_RESET}  %s\n" "$*" >&2; }
hr()    { printf "${C_DIM}%s${C_RESET}\n" "------------------------------------------------------------"; }

# --- .env loading -----------------------------------------------------------
# Same mechanism the existing tools/glm_serve.sh already uses: export every
# assignment found in .env. Safe because .env is a private, trusted file.
load_env() {
  if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    . "$REPO_ROOT/.env"
    set +a
  fi
}

# --- Normalise the friendly runtime variables -------------------------------
# Fills in defaults and maps the operator-facing names onto the exact env vars
# the Python app and the GLM server already consume. Call AFTER load_env.
normalize_env() {
  # Web port: SMARTDOCS_PORT is the operator-facing name; the app reads PORT.
  # Precedence: an explicit PORT wins (back-compat with existing .env files),
  # otherwise SMARTDOCS_PORT, otherwise the project default 5002.
  if [ -n "${PORT:-}" ]; then
    SMARTDOCS_PORT="${SMARTDOCS_PORT:-$PORT}"
  else
    SMARTDOCS_PORT="${SMARTDOCS_PORT:-5002}"
    PORT="$SMARTDOCS_PORT"
  fi
  export PORT SMARTDOCS_PORT

  HOST="${HOST:-0.0.0.0}"
  export HOST
  # Host used for *local* health probes / browser URL (0.0.0.0 isn't dialable).
  SMARTDOCS_LOCAL_HOST="127.0.0.1"
  case "$HOST" in
    0.0.0.0|"") SMARTDOCS_LOCAL_HOST="127.0.0.1" ;;
    *)          SMARTDOCS_LOCAL_HOST="$HOST" ;;
  esac

  # GLM server: derive GLM_OCR_API_URL (what the adapter reads) from GLM_HOST /
  # GLM_PORT unless the operator pinned a full URL explicitly.
  GLM_HOST="${GLM_HOST:-localhost}"
  GLM_PORT="${GLM_PORT:-8080}"
  GLM_OCR_API_URL="${GLM_OCR_API_URL:-http://${GLM_HOST}:${GLM_PORT}}"
  GLM_MODEL="${GLM_MODEL:-mlx-community/GLM-OCR-bf16}"
  # Layout model for GLM self-hosted mode (glmocr requires pipeline.layout.model_dir).
  # Default is a Hugging Face id (cached PROJECT-LOCALLY in models/huggingface/hub
  # by setup_glm.sh --precache-layout); may be an absolute local checkpoint dir.
  # setup_glm.sh writes this into mlx_config.yaml.
  GLM_LAYOUT_MODEL_DIR="${GLM_LAYOUT_MODEL_DIR:-PaddlePaddle/PP-DocLayoutV3_safetensors}"
  export GLM_HOST GLM_PORT GLM_OCR_API_URL GLM_MODEL GLM_LAYOUT_MODEL_DIR

  # GLM directory (clean-clone friendly): explicit GLM_OCR_DIR / legacy GLM_ROOT
  # wins; otherwise the vendored copy INSIDE this repo (<repo>/GLM-OCR).
  GLM_OCR_DIR="${GLM_OCR_DIR:-${GLM_ROOT:-$REPO_ROOT/GLM-OCR}}"
  GLM_ROOT="$GLM_OCR_DIR"
  export GLM_OCR_DIR GLM_ROOT

  # ENABLE_GLM: whether start.sh should try to launch the GLM server. Optional;
  # the app itself always runs without it. Normalise to lowercase true/false.
  ENABLE_GLM="${ENABLE_GLM:-true}"
  case "$(printf '%s' "$ENABLE_GLM" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on)  ENABLE_GLM="true" ;;
    *)              ENABLE_GLM="false" ;;
  esac
  export ENABLE_GLM

  # GLM backend mode (cross-platform; mirrors config.py):
  #   local_mlx | external_server | maas_api | ollama | disabled
  # Platform-aware default: local_mlx ONLY on macOS Apple Silicon (the verified
  # baseline); disabled everywhere else — Windows/Linux never assume a local
  # MLX server exists. ENABLE_GLM=false stays the master off switch.
  if [ -z "${GLM_OCR_MODE:-}" ]; then
    if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
      GLM_OCR_MODE="local_mlx"
    else
      GLM_OCR_MODE="disabled"
    fi
  fi
  GLM_OCR_MODE="$(printf '%s' "$GLM_OCR_MODE" | tr '[:upper:]' '[:lower:]')"
  if [ "$ENABLE_GLM" = "false" ]; then
    GLM_OCR_MODE="disabled"
  fi
  # External-server protocol (openai_compatible is the supported one today).
  GLM_EXTERNAL_PROTOCOL="${GLM_EXTERNAL_PROTOCOL:-openai_compatible}"
  export GLM_OCR_MODE GLM_EXTERNAL_PROTOCOL
}

# True (0) when this host can run the local MLX server at all.
is_apple_silicon() {
  [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]
}

# --- Project-local HuggingFace hub cache -------------------------------------
# Mirrors config._configure_hf_env(): $MODEL_DIR/huggingface/hub, MODEL_DIR from
# .env (default <repo>/models); a relative MODEL_DIR anchors at the repo root
# (the scripts always run the app from there). This is where ALL HF models live
# — including the GLM layout model since the project-local-cache fix.
project_hf_hub() {
  local md="${MODEL_DIR:-$REPO_ROOT/models}"
  case "$md" in
    /*) ;;
    *)  md="$REPO_ROOT/${md#./}" ;;
  esac
  printf '%s/huggingface/hub\n' "$md"
}

# --- Main-venv Python version policy ----------------------------------------
# The main SmartDocs dependency stack is VERIFIED on Python 3.10 ONLY.
# paddlepaddle>=3.0.0 and Pillow==10.2.0 (pinned by VietOCR) publish NO wheels
# for Python 3.13/3.14, so a 3.14 venv fails `pip install -r requirements.txt`
# immediately ("No matching distribution found for paddlepaddle>=3.0.0").
# 3.11 is tolerated with a warning (wheels exist, stack not fully verified).
# 3.12/3.13/3.14 are REJECTED for the main venv. GLM's OWN venvs
# (GLM-OCR/.venv-mlx / .venv-sdk) have a separate policy in setup_glm.sh.

# Print "3.10.14"-style version of an interpreter (or "?" if it won't run).
python_version_of() {
  "$1" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null || echo '?'
}

# main_python_support <version> -> 0 verified (3.10) | 1 tolerated (3.11) | 2 unsupported
main_python_support() {
  case "$1" in
    3.10.*) return 0 ;;
    3.11.*) return 1 ;;
    *)      return 2 ;;
  esac
}

# Locate an interpreter SUPPORTED for the main venv, in preference order.
# Never silently falls back to a newer python (that is exactly the clean-clone
# bug where `python3` was 3.14). Prints the path or returns non-zero.
find_supported_main_python() {
  local c ver
  for c in \
      python3.10 \
      /opt/homebrew/bin/python3.10 \
      /usr/local/bin/python3.10 \
      /usr/bin/python3.10 \
      python3.11 \
      python3; do
    case "$c" in
      /*) [ -x "$c" ] || continue ;;
      *)  c="$(command -v "$c" 2>/dev/null)" || continue ;;
    esac
    ver="$(python_version_of "$c")"
    local sup=0
    main_python_support "$ver" || sup=$?
    if [ "$sup" -le 1 ]; then   # 0 = verified 3.10, 1 = tolerated 3.11
      printf '%s\n' "$c"; return 0
    fi
    # unsupported (e.g. python3 -> 3.14): keep looking, NEVER fall back to it
  done
  return 1
}

# --- Python / venv resolution ----------------------------------------------
# Print the venv python if one exists, in priority order. Returns non-zero when
# no virtualenv is found (callers may then fall back to system python3).
#   1. $SMARTDOCS_PYTHON override
#   2. <repo>/.venv                 (a venv created inside this project)
#   3. <repo>/../.venv              (OCRSoftware/.venv — the MacBook layout)
venv_python() {
  if [ -n "${SMARTDOCS_PYTHON:-}" ] && [ -x "${SMARTDOCS_PYTHON}" ]; then
    printf '%s\n' "$SMARTDOCS_PYTHON"; return 0
  fi
  if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    printf '%s\n' "$REPO_ROOT/.venv/bin/python"; return 0
  fi
  local parent_py; parent_py="$(cd "$REPO_ROOT/.." && pwd)/.venv/bin/python"
  if [ -x "$parent_py" ]; then
    printf '%s\n' "$parent_py"; return 0
  fi
  return 1
}

# Print a python to RUN the app with: the venv python if available, else a
# system python3/python. Returns non-zero if nothing is found.
resolve_python() {
  local p
  if p="$(venv_python)"; then printf '%s\n' "$p"; return 0; fi
  if command -v python3 >/dev/null 2>&1; then command -v python3; return 0; fi
  if command -v python  >/dev/null 2>&1; then command -v python;  return 0; fi
  return 1
}

# --- GLM interpreter resolution ---------------------------------------------
# Resolve the GLM python the SAME way config.py / tools/glm_serve.sh do, so the
# scripts' "is GLM available?" checks match what actually launches. Repo-local
# by default; an explicit env var points elsewhere. Requires normalize_env to
# have set GLM_OCR_DIR. Prints the interpreter path (exists+executable) or
# returns non-zero. Candidate order prefers .venv-mlx (server), then .venv-sdk.
glm_python() {
  local candidates=()
  [ -n "${GLM_MLX_PYTHON:-}" ] && candidates+=("$GLM_MLX_PYTHON")
  [ -n "${GLM_SDK_PYTHON:-}" ] && candidates+=("$GLM_SDK_PYTHON")
  candidates+=("${GLM_OCR_DIR:-$REPO_ROOT/GLM-OCR}/.venv-mlx/bin/python")
  candidates+=("${GLM_OCR_DIR:-$REPO_ROOT/GLM-OCR}/.venv-sdk/bin/python")
  local c
  for c in "${candidates[@]}"; do
    if [ -n "$c" ] && [ -x "$c" ]; then printf '%s\n' "$c"; return 0; fi
  done
  return 1
}

# Back-compat alias used by start.sh.
glm_mlx_python() { glm_python; }

# Print the path where the repo-local GLM venv is expected (whether or not it
# exists) — used by diagnostics / setup messaging.
glm_venv_dir() { printf '%s\n' "${GLM_OCR_DIR:-$REPO_ROOT/GLM-OCR}/.venv-mlx"; }

# --- Port + HTTP helpers ----------------------------------------------------
# True (0) when something is listening on 127.0.0.1:$1. Uses bash /dev/tcp so it
# needs no lsof/nc (both of which may be absent).
port_in_use() {
  local port="$1"
  ( exec 3<>"/dev/tcp/127.0.0.1/${port}" ) >/dev/null 2>&1
}

# Echo the HTTP status code for a GET (or "000" if unreachable). Needs curl.
# NOTE: on connection failure curl BOTH prints "000" (from -w) AND exits
# non-zero — a naive `|| echo 000` would emit "000000", which callers then
# misread as "responding" (that made check.sh report SmartDocs health as
# responding while the port was free). Normalise to exactly three digits.
http_status() {
  local url="$1"; shift || true
  local code
  code="$(curl -s -o /dev/null -m "${HEALTH_TIMEOUT:-5}" -w "%{http_code}" "$@" "$url" 2>/dev/null)" || true
  case "$code" in
    [0-9][0-9][0-9]) printf '%s\n' "$code" ;;
    *)               echo "000" ;;
  esac
}

# GLM readiness — "port 8080 listening" does NOT mean the model is loaded: a
# cold start can spend minutes loading (or, first time online, downloading) the
# MLX model. Prints exactly one state:
#   down            nothing listening on GLM_PORT
#   loading         port open but GET /health gives no answer — mlx_vlm.server
#                   loads the model inside the request handler, which blocks its
#                   event loop, so an unanswered /health means "load in flight"
#   no-model        server idle with NO model loaded yet (lazy mode: the first
#                   request triggers the load)
#   ready:<model>   /health reports loaded_model — ready for inference
#   unknown         something answers HTTP on the port but not like
#                   mlx_vlm.server's /health (foreign service / other version)
# GET /health is mlx_vlm.server's status endpoint (verified in the pinned
# mlx-vlm 0.6.3 source: returns {"status":…, "loaded_model": <id|null>} and
# NEVER triggers a model load). Deliberately not /v1/models (scans the whole
# cache, and can block while a load holds the event loop) and never a POST to
# /chat/completions from a check (that WOULD trigger a cold model load).
glm_ready_state() {
  if ! port_in_use "$GLM_PORT"; then echo "down"; return; fi
  local body model
  body="$(curl -s -m "${HEALTH_TIMEOUT:-5}" --noproxy '*' "${GLM_OCR_API_URL}/health" 2>/dev/null)" || body=""
  if [ -z "$body" ]; then echo "loading"; return; fi
  case "$body" in
    *loaded_model*)
      model="$(printf '%s' "$body" | sed -n 's/.*"loaded_model"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
      if [ -n "$model" ]; then echo "ready:$model"; else echo "no-model"; fi ;;
    *) echo "unknown" ;;
  esac
}

# GLM deep health probe — a real (tiny) /chat/completions inference. Returns 0
# iff HTTP 200. NOTE: on a cold server this TRIGGERS the model load — use
# glm_ready_state for read-only checks; keep this for explicit verification or
# as a fallback when /health is unavailable.
glm_health() {
  local code
  code="$(curl -s -o /dev/null -m "${HEALTH_TIMEOUT:-8}" -w "%{http_code}" \
    "${GLM_OCR_API_URL}/chat/completions" -X POST \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"${GLM_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":[{\"type\":\"text\",\"text\":\"hi\"}]}],\"max_tokens\":3}" \
    2>/dev/null)"
  [ "$code" = "200" ]
}

# SmartDocs health — any HTTP response (200/302/401/403…) means the server is up.
# --noproxy '*': this probes the LOCAL server directly; an http_proxy env var
# must not answer on its behalf (that made check.sh report "responding" while
# the port was actually free).
smartdocs_health() {
  local code
  code="$(http_status "http://${SMARTDOCS_LOCAL_HOST}:${SMARTDOCS_PORT}/" --noproxy '*')"
  case "$code" in 000|"") return 1 ;; *) return 0 ;; esac
}

# --- PID file helpers -------------------------------------------------------
WEB_PID_FILE="$LOG_DIR/web.pid"
GLM_PID_FILE="$LOG_DIR/glm.pid"

pid_alive()  { [ -n "${1:-}" ] && kill -0 "$1" >/dev/null 2>&1; }

read_pid() { [ -f "$1" ] && cat "$1" 2>/dev/null || true; }

ensure_dirs() { mkdir -p "$LOG_DIR"; }
