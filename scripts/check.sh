#!/usr/bin/env bash
# ============================================================================
#  scripts/check.sh — diagnose the local runtime. Read-only; changes nothing.
#
#  Reports:
#    * repo root + resolved Python interpreter / venv + version
#    * presence of key dependencies (flask + the app's own config import)
#    * web port + GLM port state (free / in use)
#    * SmartDocs health   (HTTP response on the web port)
#    * GLM health         (POST /chat/completions -> 200) — optional
#
#  Exit code: 0 if the core web stack looks healthy or simply not running;
#  non-zero only when something is clearly broken (e.g. no Python / no Flask).
#  GLM being down is NEVER an error here (it is optional).
# ============================================================================
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$DIR/lib.sh"

load_env
normalize_env

FAIL=0

info "SmartDocs-Agent — environment check"
hr
info "Repo root : $REPO_ROOT"

# --- Python -----------------------------------------------------------------
PY_UNSUPPORTED=0
if PY="$(resolve_python)"; then
  PYVER="$(python_version_of "$PY")"
  ok "Main SmartDocs Python: $PY (v$PYVER)"
  SUP=0; main_python_support "$PYVER" || SUP=$?
  if [ "$SUP" -ge 2 ]; then
    err "UNSUPPORTED Python version $PYVER for the main venv (required: 3.10; tolerated: 3.11)."
    err "paddlepaddle/Pillow-10.2.0 have no wheels for it — requirements.txt CANNOT install."
    err "Recreate the venv:  scripts/setup.sh --reset-venv   (needs python3.10 installed)"
    PY_UNSUPPORTED=1
    FAIL=1
  elif [ "$SUP" -eq 1 ]; then
    warn "Python $PYVER is tolerated but not fully verified — 3.10 is the verified version."
  fi
else
  err "No Python interpreter found. Run scripts/setup.sh."
  FAIL=1
  PY=""
fi

# --- Dependencies (main SmartDocs venv) -------------------------------------
if [ -n "$PY" ]; then
  if "$PY" -c 'import flask' >/dev/null 2>&1; then
    ok "Flask import OK"
  elif [ "$PY_UNSUPPORTED" -eq 1 ]; then
    err "Flask not importable — the venv is INCOMPLETE because of the unsupported"
    err "Python above (pip install failed there). Fix the Python version first;"
    err "the missing-module errors are a consequence, not separate problems."
    FAIL=1
  else
    err "Flask not importable — venv INCOMPLETE. Run scripts/setup.sh to install requirements.txt"
    FAIL=1
  fi
  # Import the app's own config (validates the project is on sys.path + parseable).
  if ( cd "$REPO_ROOT" && "$PY" -c 'import config' >/dev/null 2>&1 ); then
    ok "App config import OK"
  else
    warn "Could not import the app 'config' module (may need full deps / env)."
  fi
  # Pillow version — MUST stay 10.2.0 in the main venv for VietOCR. GLM's
  # Pillow 12.x lives ONLY in GLM-OCR/.venv-sdk (isolated), so no conflict.
  MAIN_PIL="$("$PY" -c 'import PIL; print(PIL.__version__)' 2>/dev/null || echo 'not installed')"
  ok "Main Pillow version  : $MAIN_PIL"
  # VietOCR import — the engine that pins Pillow==10.2.0.
  if "$PY" -c 'import vietocr' >/dev/null 2>&1; then
    ok "VietOCR import       : OK"
  else
    info "VietOCR import       : not available (run scripts/setup.sh)"
  fi
fi

# --- Web port + health ------------------------------------------------------
hr
WEB_PORT_UP=0
if port_in_use "$SMARTDOCS_PORT"; then
  WEB_PORT_UP=1
  ok "Web port $SMARTDOCS_PORT: in use (SmartDocs likely running)"
else
  info "Web port $SMARTDOCS_PORT: free (SmartDocs not running)"
fi
if command -v curl >/dev/null 2>&1; then
  if smartdocs_health; then
    if [ "$WEB_PORT_UP" -eq 1 ]; then
      ok "SmartDocs health: responding on http://${SMARTDOCS_LOCAL_HOST}:${SMARTDOCS_PORT}/"
    else
      # Contradiction: the port probe said free, yet HTTP just got a response
      # (server started between the two probes, or an IPv6-only listener).
      warn "Web port $SMARTDOCS_PORT was FREE a moment ago but HTTP now responds on"
      warn "http://${SMARTDOCS_LOCAL_HOST}:${SMARTDOCS_PORT}/ — likely it just started. Re-run scripts/check.sh."
    fi
  else
    info "SmartDocs health: not responding (start it with scripts/start_web.sh)"
  fi
else
  warn "curl not found — skipping HTTP health checks."
fi

# --- GLM (optional) ---------------------------------------------------------
# GLM_OCR_MODE (lib.sh; platform-aware default) decides which checks apply:
#   disabled        → nothing to check
#   local_mlx       → BOTH venvs + local server readiness (Apple Silicon)
#   external_server → .venv-sdk only (layout runs locally) + remote URL probe
#   maas_api        → .venv-sdk only + API-key presence (cloud passthrough)
#   ollama          → reserved / unverified
# Two independent venvs (see scripts/setup_glm.sh):
#   .venv-mlx = MLX model server (mlx_vlm/mlx_lm)   — NO torch, NO glmocr
#   .venv-sdk = glmocr CLI / layout detector        — torch + glmocr (UI uses this)
hr
info "GLM OCR (optional):"
echo "    GLM_OCR_MODE     : $GLM_OCR_MODE"
echo "    GLM_OCR_DIR      : $GLM_OCR_DIR"
if [ "$GLM_OCR_MODE" = "disabled" ]; then
  info "GLM OCR              : disabled — Legacy/VietOCR/Modern OCR are unaffected."
  info "                       (enable: GLM_OCR_MODE=local_mlx on macOS Apple Silicon,"
  info "                        or external_server / maas_api on any OS — see .env.example)"
else
  if [ -d "$GLM_OCR_DIR" ]; then
    ok  "GLM-OCR dir exists   : yes ($( [ -f "$GLM_OCR_DIR/pyproject.toml" ] && echo 'vendored SDK present' || echo 'dir present'))"
  else
    warn "GLM-OCR dir exists   : NO — run scripts/setup_glm.sh or set GLM_OCR_DIR"
  fi

  # ── .venv-mlx (MLX model server — only the local_mlx mode needs it) ──
  if [ "$GLM_OCR_MODE" = "local_mlx" ]; then
    is_apple_silicon || warn "GLM local MLX is only supported on macOS Apple Silicon. Use external_server, maas_api, or disable GLM."
    MLX_PY="$GLM_OCR_DIR/.venv-mlx/bin/python"
    if [ -x "$MLX_PY" ]; then
      MLX_VER="$("$MLX_PY" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null || echo '?')"
      ok  ".venv-mlx python     : $MLX_PY (v$MLX_VER)"
      if "$MLX_PY" -c "import mlx_vlm, mlx_lm, transformers" >/dev/null 2>&1; then
        ok  ".venv-mlx imports    : OK (mlx_vlm, mlx_lm, transformers)"
      else
        info ".venv-mlx imports    : not available (Apple-Silicon only, or re-run scripts/setup_glm.sh)"
      fi
    else
      info ".venv-mlx python     : missing ($MLX_PY) — create with scripts/setup_glm.sh"
    fi
  fi

  # ── .venv-sdk (glmocr CLI / layout — every non-disabled mode uses it) ──
  SDK_PY="$GLM_OCR_DIR/.venv-sdk/bin/python"
  if [ -x "$SDK_PY" ]; then
    SDK_VER="$("$SDK_PY" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null || echo '?')"
    ok  ".venv-sdk python     : $SDK_PY (v$SDK_VER)"
    if "$SDK_PY" -c "import torch; import glmocr; from glmocr.layout.layout_detector import PPDocLayoutDetector" >/dev/null 2>&1; then
      ok  ".venv-sdk imports    : OK (torch, glmocr, PPDocLayoutDetector)"
    else
      warn ".venv-sdk imports    : FAILED — run scripts/setup_glm.sh"
      "$SDK_PY" -c "import torch; import glmocr; from glmocr.layout.layout_detector import PPDocLayoutDetector" 2>&1 | tail -3 | sed 's/^/         ↳ /' >&2
      FAIL=1
    fi
  else
    warn ".venv-sdk python     : MISSING ($SDK_PY) — GLM OCR from the UI will fail; run scripts/setup_glm.sh"
  fi

  case "$GLM_OCR_MODE" in
    local_mlx)
      if port_in_use "$GLM_PORT"; then
        ok  "GLM port $GLM_PORT       : in use"
      else
        info "GLM port $GLM_PORT       : free (server not running — optional)"
      fi
      if command -v curl >/dev/null 2>&1; then
        # Three distinct facts, NOT one: port listening ≠ model loaded. A cold GLM
        # server can hold the port while it still loads (or first-run downloads)
        # the MLX model — OCR requests fail until it finishes.
        GLM_STATE="$(glm_ready_state)"
        case "$GLM_STATE" in
          ready:*)
            ok  "GLM health           : READY — model loaded (${GLM_STATE#ready:}) on ${GLM_OCR_API_URL}" ;;
          loading)
            warn "GLM server starting/loading model; wait or check logs/glm.log"
            warn "  (port ${GLM_PORT} is listening but inference is not available yet)" ;;
          no-model)
            info "GLM health           : server up on ${GLM_OCR_API_URL} but NO model loaded yet"
            info "                       (lazy mode — the first OCR request loads it; preload is the default via GLM_PRELOAD=true)" ;;
          unknown)
            # /health missing (older mlx_vlm?) — fall back to the deep inference
            # probe. NOTE: on a cold lazy server this triggers the model load.
            if glm_health; then
              ok  "GLM health           : 200 on ${GLM_OCR_API_URL} (model: ${GLM_MODEL})"
            else
              warn "GLM health           : something answers on ${GLM_OCR_API_URL} but not like the GLM server (check what runs on port ${GLM_PORT})"
            fi ;;
          down)
            info "GLM health           : not responding on ${GLM_OCR_API_URL} (start: scripts/start_glm.sh -b)" ;;
        esac
      fi ;;
    external_server)
      echo "    GLM_OCR_API_URL  : $GLM_OCR_API_URL (protocol: $GLM_EXTERNAL_PROTOCOL)"
      if [ "$GLM_EXTERNAL_PROTOCOL" = "sdk_server" ]; then
        warn "GLM external         : protocol sdk_server is RESERVED (not implemented) — use openai_compatible"
      fi
      if command -v curl >/dev/null 2>&1; then
        # /health lives at the server root on vLLM / SGLang / mlx_vlm / the SDK
        # server — probe scheme://host:port even when the URL carries a path.
        GLM_BASE_URL="$(printf '%s' "$GLM_OCR_API_URL" | sed -E 's#^(https?://[^/]+).*#\1#')"
        CODE="$(http_status "$GLM_BASE_URL/health")"
        if [ "$CODE" = "000" ]; then
          warn "GLM external         : $GLM_BASE_URL not reachable — check GLM_OCR_API_URL / network / remote server"
        else
          ok  "GLM external         : $GLM_BASE_URL reachable (GET /health → HTTP $CODE)"
        fi
      fi ;;
    maas_api)
      if [ -n "${GLM_MAAS_API_KEY:-}${ZHIPU_API_KEY:-}" ]; then
        ok  "GLM MaaS             : API key set (cloud passthrough — needs internet at OCR time)"
      else
        warn "GLM MaaS             : NO API key — set GLM_MAAS_API_KEY (or ZHIPU_API_KEY) in .env"
      fi ;;
    ollama)
      warn "GLM via Ollama       : reserved / NOT verified — GLM OCR will refuse requests (use external_server or maas_api)" ;;
    *)
      warn "GLM_OCR_MODE         : unknown value '$GLM_OCR_MODE' (valid: local_mlx external_server maas_api ollama disabled)" ;;
  esac
fi

hr
info "For AI model / offline readiness (chat, rewrite, VietOCR config, Argos,"
info "GLM layout), run:  scripts/check_offline.sh"
hr
if [ "$FAIL" -eq 0 ]; then
  ok "Core environment looks good."
else
  err "One or more core checks failed (see above)."
fi
exit "$FAIL"
