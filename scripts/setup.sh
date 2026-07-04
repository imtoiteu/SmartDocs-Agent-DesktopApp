#!/usr/bin/env bash
# ============================================================================
#  scripts/setup.sh — one-time (idempotent) local environment setup.
#
#    * finds or creates a Python virtualenv (never clobbers an existing one)
#    * installs requirements.txt into it
#    * seeds .env from .env.example if missing
#    * creates the runtime folders the app writes to (logs/ uploads/ artifacts/)
#
#  Safe to re-run. Does NOT touch the GLM-OCR MLX venv (that is Apple-Silicon
#  only and lives in the external GLM-OCR checkout).
# ============================================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$DIR/lib.sh"

load_env
normalize_env
ensure_dirs

# --- Flags -------------------------------------------------------------------
#   --reset-venv : delete + recreate the REPO-LOCAL ./.venv (only that one) when
#                  it exists but uses an unsupported Python. Never touches a
#                  parent ../.venv or an explicit $SMARTDOCS_PYTHON venv.
RESET_VENV=0
for arg in "$@"; do
  case "$arg" in
    --reset-venv) RESET_VENV=1 ;;
    -h|--help)
      echo "Usage: scripts/setup.sh [--reset-venv]"
      echo "  --reset-venv  recreate ./.venv if it uses an unsupported Python"
      exit 0 ;;
    *) err "Unknown option: $arg (supported: --reset-venv)"; exit 1 ;;
  esac
done

info "SmartDocs-Agent setup"
hr
info "Repo root: $REPO_ROOT"

# Print how to get a supported interpreter on this OS, then exit 1.
no_supported_python_die() {
  err "No supported Python found for the main SmartDocs venv."
  err "The main venv REQUIRES Python 3.10 (3.11 tolerated). 3.12/3.13/3.14 are"
  err "rejected: paddlepaddle>=3.0.0 and Pillow==10.2.0 have no wheels there."
  case "$(uname -s)" in
    Darwin) err "Install Python 3.10 first:  brew install python@3.10" ;;
    *)      err "Install Python 3.10 first, e.g.:  sudo apt install python3.10 python3.10-venv" ;;
  esac
  err "Then re-run scripts/setup.sh. No .venv was created."
  exit 1
}

# --- 1. Resolve or create the virtualenv -----------------------------------
VENV_PY=""
if VENV_PY="$(venv_python)"; then
  VENV_DIR="$(cd "$(dirname "$VENV_PY")/.." && pwd)"
  PYVER="$(python_version_of "$VENV_PY")"
  SUP=0; main_python_support "$PYVER" || SUP=$?
  if [ "$SUP" -ge 2 ]; then
    err "Existing virtualenv uses UNSUPPORTED Python $PYVER: $VENV_DIR"
    err "The main venv requires Python 3.10 (3.11 tolerated) — with $PYVER,"
    err "'pip install -r requirements.txt' fails (no paddlepaddle/Pillow wheels)."
    if [ "$RESET_VENV" -eq 1 ] && [ "$VENV_DIR" = "$REPO_ROOT/.venv" ]; then
      warn "--reset-venv: deleting $VENV_DIR and recreating with a supported Python…"
      rm -rf "$REPO_ROOT/.venv"
      VENV_PY=""
    else
      if [ "$VENV_DIR" = "$REPO_ROOT/.venv" ]; then
        err "Fix with:  scripts/setup.sh --reset-venv"
        err "   (or)    rm -rf \"$VENV_DIR\"  &&  scripts/setup.sh"
      else
        # Parent ../.venv or $SMARTDOCS_PYTHON — possibly shared; NEVER auto-delete.
        err "This venv is outside the repo — remove/replace it yourself, e.g.:"
        err "    rm -rf \"$VENV_DIR\"  &&  scripts/setup.sh"
        err "(--reset-venv only ever recreates the repo-local ./.venv)"
      fi
      exit 1
    fi
  else
    ok "Using existing virtualenv: $VENV_DIR (Python $PYVER)"
    [ "$SUP" -eq 1 ] && warn "Python $PYVER is tolerated but not fully verified — 3.10 is the verified version."
  fi
fi

if [ -z "$VENV_PY" ]; then
  if ! BASE_PY="$(find_supported_main_python)"; then
    no_supported_python_die
  fi
  BASE_VER="$(python_version_of "$BASE_PY")"
  SUP=0; main_python_support "$BASE_VER" || SUP=$?
  [ "$SUP" -eq 1 ] && warn "No python3.10 found; using tolerated Python $BASE_VER ($BASE_PY). 3.10 is the verified version."
  info "Creating virtualenv at $REPO_ROOT/.venv with $BASE_PY (v$BASE_VER)"
  "$BASE_PY" -m venv "$REPO_ROOT/.venv"
  VENV_PY="$REPO_ROOT/.venv/bin/python"
  ok "Created virtualenv: $REPO_ROOT/.venv"
fi

PYVER="$(python_version_of "$VENV_PY")"
info "Python: $VENV_PY (v$PYVER)"

# --- 2. Install dependencies (FAIL-FAST: a failed install stops setup) -------
if [ -f "$REPO_ROOT/requirements.txt" ]; then
  info "Upgrading pip and installing requirements.txt (this can take a while)…"
  "$VENV_PY" -m pip install --upgrade pip >/dev/null
  if ! "$VENV_PY" -m pip install -r "$REPO_ROOT/requirements.txt"; then
    err "'pip install -r requirements.txt' FAILED — setup is INCOMPLETE and stops here."
    err "Nothing after this step ran; do NOT proceed to setup_offline/start."
    err "Most common cause: unsupported Python (this venv: $PYVER; required: 3.10)."
    err "Fix, then re-run scripts/setup.sh (use --reset-venv to recreate ./.venv)."
    exit 1
  fi
  ok "Dependencies installed"
else
  warn "requirements.txt not found — skipping dependency install"
fi

# GLM-OCR SDK deps: the Flask/UI path imports the vendored GLM-OCR SDK
# in-process, so the MAIN venv needs its runtime deps (PyMuPDF, wordfreq, …).
# Additive over requirements.txt — see requirements/glm-sdk.txt.
GLM_SDK_REQ="$REPO_ROOT/requirements/glm-sdk.txt"
if [ -f "$GLM_SDK_REQ" ]; then
  info "Installing GLM-OCR SDK deps (requirements/glm-sdk.txt) into the main venv…"
  if ! "$VENV_PY" -m pip install -r "$GLM_SDK_REQ"; then
    err "'pip install -r requirements/glm-sdk.txt' FAILED — setup is INCOMPLETE and stops here."
    exit 1
  fi
  ok "GLM-OCR SDK deps installed"
else
  warn "requirements/glm-sdk.txt not found — GLM OCR from the UI may hit missing modules"
fi

# --- 3. Seed .env -----------------------------------------------------------
if [ ! -f "$REPO_ROOT/.env" ] && [ -f "$REPO_ROOT/.env.example" ]; then
  cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
  ok "Created .env from .env.example (edit it to set ports / API keys)"
elif [ -f "$REPO_ROOT/.env" ]; then
  ok ".env already present — left untouched"
fi

# --- 4. Runtime folders -----------------------------------------------------
mkdir -p "$REPO_ROOT/logs" "$REPO_ROOT/uploads" "$REPO_ROOT/artifacts"
ok "Runtime folders ready: logs/ uploads/ artifacts/"

# --- 5. Sanity gate: 'Setup complete' must mean the venv actually works ------
MISSING="$("$VENV_PY" -c '
import importlib
mods = ["flask", "PIL", "yaml", "torch", "transformers", "vietocr",
        "argostranslate", "sentence_transformers"]
missing = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception:
        missing.append(m)
print(" ".join(missing))
' 2>/dev/null || echo 'interpreter-failed')"
if [ -n "$MISSING" ]; then
  err "Setup finished installing, but the venv is INCOMPLETE — missing imports: $MISSING"
  err "Re-run scripts/setup.sh with Python 3.10 (current: $PYVER)."
  exit 1
fi
ok "Core imports verified (flask, PIL, yaml, torch, transformers, vietocr, argostranslate, sentence_transformers)"

hr
ok "Setup complete."
echo
echo "Next:"
echo "  scripts/check.sh       # verify environment, ports, GLM SDK/MLX imports, health"
echo "  scripts/setup_glm.sh   # (optional, Apple Silicon) create the GLM MLX server venv"
echo "  scripts/start.sh       # start the full local stack (GLM if enabled)"
echo "  scripts/start_web.sh   # start only the web app"
