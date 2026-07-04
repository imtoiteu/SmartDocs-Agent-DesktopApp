#!/usr/bin/env bash
# ============================================================================
#  scripts/check_offline.sh — comprehensive OFFLINE / clean-clone readiness.
#
#  Read-only. Reports, for a fresh clone, whether every AI feature is usable
#  now, needs a one-time online setup, or is running on a built-in fallback:
#
#    * main SmartDocs Python path/version + Pillow version + VietOCR import
#    * VietOCR config.yml + weights           (models/vietocr/)
#    * Paddle det/rec cache                    (first-run download otherwise)
#    * Local LLM (chat/rewrite/agent)          (Qwen2.5-1.5B-Instruct REQUIRED;
#                                               a complete HF snapshot, not a
#                                               half-download — 3B is NOT required)
#    * PhoBERT + embeddings                    (fallbacks exist if missing)
#    * Argos offline translation packages      (installed language pairs listed)
#    * GLM .venv-mlx / .venv-sdk               (imports)
#    * GLM self-hosted config: pipeline.layout.model_dir present?
#    * GLM layout model cached PROJECT-LOCALLY? (models/huggingface/hub)
#    * GLM MLX server model cached PROJECT-LOCALLY? (mlx-community/GLM-OCR-bf16)
#
#  The model matrix comes from config.cfg.offline_readiness_report() so the
#  script and the running app agree on exactly what "ready" means.
#
#  Exit code: 0 always for optional/fallback-capable features; non-zero only if
#  the interpreter or Flask itself is missing (a genuinely broken environment).
# ============================================================================
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$DIR/lib.sh"

load_env
normalize_env

FAIL=0

info "SmartDocs-Agent — OFFLINE readiness check"
hr
info "Repo root : $REPO_ROOT"

# --- Environment gate: three DISTINCT failure classes -----------------------
# 1. unsupported Python version  -> recreate the venv (scripts/setup.sh --reset-venv)
# 2. incomplete venv             -> re-run scripts/setup.sh (pip install)
# 3. missing offline MODELS      -> the matrix below (scripts/setup_offline.sh)
# Classes 1/2 stop here: every model row would otherwise be a misleading ❌.
if PY="$(resolve_python)"; then
  PYVER="$(python_version_of "$PY")"
  ok "Main SmartDocs Python: $PY (v$PYVER)"
else
  err "No Python interpreter found. Run scripts/setup.sh."
  exit 1
fi
SUP=0; main_python_support "$PYVER" || SUP=$?
if [ "$SUP" -ge 2 ]; then
  err "UNSUPPORTED Python $PYVER for the main venv (required: 3.10; tolerated: 3.11)."
  err "This is an ENVIRONMENT problem, not a missing-model problem — the model"
  err "checks below would all fail misleadingly, so they are skipped."
  err "Fix:  scripts/setup.sh --reset-venv   then re-run this script."
  exit 1
elif [ "$SUP" -eq 1 ]; then
  warn "Python $PYVER is tolerated but not fully verified — 3.10 is the verified version."
fi
CORE_MISSING="$("$PY" -c '
import importlib
mods = ["flask", "PIL", "yaml", "torch", "transformers"]
missing = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception:
        missing.append(m)
print(" ".join(missing))
' 2>/dev/null || echo 'interpreter-failed')"
if [ -n "$CORE_MISSING" ]; then
  err "Main venv is INCOMPLETE (missing imports: $CORE_MISSING)."
  err "This is an install problem, not a missing-model problem — re-run"
  err "scripts/setup.sh with Python 3.10, then re-run this script."
  exit 1
fi
MAIN_PIL="$("$PY" -c 'import PIL; print(PIL.__version__)' 2>/dev/null || echo 'not installed')"
ok "Main Pillow version  : $MAIN_PIL"
if "$PY" -c 'import vietocr' >/dev/null 2>&1; then
  ok "VietOCR import       : OK"
else
  warn "VietOCR import       : not available — venv incomplete (run scripts/setup.sh)"
fi

# --- Model readiness matrix (single source of truth: config.py) -------------
hr
if ! ( cd "$REPO_ROOT" && "$PY" -c 'from config import cfg; print(cfg.offline_readiness_report())' 2>/dev/null ); then
  warn "Could not import the app config to compute model readiness."
  warn "(Needs the main venv deps installed — run scripts/setup.sh.)"
fi

# --- VietOCR deep validation --------------------------------------------------
# The matrix above already validates config.yml STRUCTURE (via config.py).
# This goes further: imports vietocr's Predictor, loads config.yml through the
# real Cfg.load_config_from_file() runtime path, and cross-checks the weights
# path inside the config — catching an empty/half-written config.yml that mere
# file-existence checks reported as ✅.
hr
if "$PY" -c 'import vietocr' >/dev/null 2>&1; then
  VIETOCR_CHECK="$(cd "$REPO_ROOT" && "$PY" - 2>&1 <<'PYEOF'
import sys
sys.path.insert(0, ".")
from pathlib import Path
from config import cfg, validate_vietocr_config
p = cfg.MODEL_DIR / "vietocr" / "config.yml"
ok, why = validate_vietocr_config(p)
if not ok:
    print(f"INVALID: {why}")
    sys.exit(1)
from vietocr.tool.predictor import Predictor          # noqa: F401 (import must work)
from vietocr.tool.config import Cfg
c = Cfg.load_config_from_file(str(p))
missing = [k for k in ("vocab","device","weights","backbone","cnn","transformer","seq_modeling","dataset","predictor") if c.get(k) is None]
if missing:
    print("INVALID: keys None after load: " + ", ".join(missing))
    sys.exit(1)
w = str(cfg.VIETOCR_WEIGHTS or c.get("weights") or "")
if not w.startswith("http") and not Path(w).exists():
    print(f"INVALID: weights not found: {w}")
    sys.exit(1)
print("config.yml loads via Cfg + Predictor importable + weights present")
PYEOF
)"
  if [ $? -eq 0 ]; then
    ok  "VietOCR deep check    : $VIETOCR_CHECK"
  else
    warn "VietOCR deep check    : $VIETOCR_CHECK — run scripts/setup_offline.sh (online)"
  fi
else
  info "VietOCR deep check    : skipped (vietocr not importable in main venv)"
fi

# --- Argos runtime validation + REAL translation smoke test --------------------
# The matrix above counts packages via metadata.json on disk. This goes through
# the EXACT app runtime path instead: services/translate_service.py (which
# applies the stanza-compat shims and the deterministic sentencizer) and actually
# translates "hello" en→vi and "xin chào" vi→en. Argos offline is reported
# USABLE only if that real translation succeeds. Offline-safe; 180s alarm cap
# per direction (first call loads the ctranslate2 model, so it takes a while).
if "$PY" -c 'import argostranslate' >/dev/null 2>&1; then
  ARGOS_RT="$(cd "$REPO_ROOT" && "$PY" - 2>&1 <<'PYEOF'
import signal, socket, sys
sys.path.insert(0, ".")
socket.setdefaulttimeout(10)              # fail fast if anything touches the net
from services import translate_service as ts   # the same module /api/translate uses
from config import cfg
pkg_dir = cfg.ARGOS_DIR / "packages"
on_disk = cfg._argos_installed_pairs()
loadable = sorted(f"{f}→{t}" for f, t in ts._get_installed_pairs())
if on_disk and not loadable:
    print(f"MISMATCH: {len(on_disk)} package(s) on disk in {pkg_dir} but argostranslate loads NONE")
    sys.exit(1)
if not loadable:
    print(f"no packages loadable from {pkg_dir} — offline translation NOT usable")
    sys.exit(1)
print(f"{len(loadable)} pair(s) loadable from {pkg_dir}: {', '.join(loadable)}")
signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("translation timed out")))
failures = []
for text, fc, tc in (("hello", "en", "vi"), ("xin chào", "vi", "en")):
    if f"{fc}→{tc}" not in loadable:
        failures.append(f"{fc}→{tc}: package not loadable")
        continue
    try:
        signal.alarm(180)
        out = ts._translate_offline(text, fc, tc)
        signal.alarm(0)
        print(f"smoke {fc}→{tc}: {text!r} → {out.strip()!r}")
    except Exception as e:
        signal.alarm(0)
        failures.append(f"{fc}→{tc}: {e}")
if failures:
    print("Argos offline usable: NO — " + " | ".join(failures))
    sys.exit(1)
print("Argos offline usable: YES (real en→vi and vi→en translation succeeded)")
PYEOF
)"
  if [ $? -eq 0 ]; then
    printf '%s\n' "$ARGOS_RT" | while IFS= read -r line; do ok "Argos runtime : $line"; done
  else
    printf '%s\n' "$ARGOS_RT" | while IFS= read -r line; do warn "Argos runtime : $line"; done
    warn "  (the translation UI will fail the same way — see server log / re-run scripts/setup_offline.sh)"
  fi
else
  info "Argos runtime check  : skipped (argostranslate not importable in main venv)"
fi

# --- GLM venvs (optional) ----------------------------------------------------
# Which caches the current GLM_OCR_MODE actually needs (lib.sh derives the
# platform-aware default: local_mlx on macOS Apple Silicon, disabled elsewhere):
#   local_mlx       → layout model + MLX server model (both project-local)
#   external_server → layout model only (OCR runs on the remote server)
#   maas_api        → none (cloud passthrough)
#   disabled/ollama → none
hr
info "GLM OCR (optional):"
echo "    GLM_OCR_MODE     : $GLM_OCR_MODE"
case "$GLM_OCR_MODE" in
  local_mlx)       info "Caches this mode needs: layout model + MLX server model (rows below)" ;;
  external_server) info "Caches this mode needs: layout model only (OCR runs on the remote server)" ;;
  maas_api)        info "Caches this mode needs: none (cloud passthrough — rows below are informational)" ;;
  disabled)        info "Caches this mode needs: none (GLM OCR disabled — rows below are informational)" ;;
  ollama)          info "Caches this mode needs: n/a (mode reserved / NOT verified in SmartDocs)" ;;
esac
echo "    GLM_OCR_DIR      : $GLM_OCR_DIR"
MLX_PY="$GLM_OCR_DIR/.venv-mlx/bin/python"
SDK_PY="$GLM_OCR_DIR/.venv-sdk/bin/python"
if [ -x "$MLX_PY" ]; then
  if "$MLX_PY" -c "import mlx_vlm, mlx_lm, transformers" >/dev/null 2>&1; then
    ok  ".venv-mlx imports    : OK (mlx_vlm, mlx_lm, transformers)"
  else
    info ".venv-mlx imports    : not available (Apple-Silicon only / re-run scripts/setup_glm.sh)"
  fi
else
  info ".venv-mlx python     : missing — create with scripts/setup_glm.sh"
fi
if [ -x "$SDK_PY" ]; then
  if "$SDK_PY" -c "import torch, glmocr; from glmocr.layout.layout_detector import PPDocLayoutDetector" >/dev/null 2>&1; then
    ok  ".venv-sdk imports    : OK (torch, glmocr, PPDocLayoutDetector)"
  else
    warn ".venv-sdk imports    : FAILED — run scripts/setup_glm.sh"
  fi
else
  info ".venv-sdk python     : missing — GLM OCR needs it; run scripts/setup_glm.sh"
fi

# --- GLM self-hosted config: the pipeline.layout.model_dir that broke OCR ----
GLM_CFG="${GLM_CONFIG_YAML:-$GLM_OCR_DIR/mlx_config.yaml}"
echo "    GLM config       : $GLM_CFG"
if [ -f "$GLM_CFG" ]; then
  if grep -Eq '^[[:space:]]*model_dir:[[:space:]]*[^[:space:]]' "$GLM_CFG"; then
    MDL_LINE="$(grep -E '^[[:space:]]*model_dir:' "$GLM_CFG" | head -1 | sed 's/^[[:space:]]*//')"
    ok  "GLM layout config    : OK ($MDL_LINE)"
  else
    warn "GLM layout config    : pipeline.layout.model_dir MISSING — re-run scripts/setup_glm.sh"
    warn "  (this is the 'pipeline.layout.model_dir is required' UI error)"
  fi
else
  info "GLM layout config    : $GLM_CFG not present (run scripts/setup_glm.sh)"
fi

# --- GLM layout model cache (PROJECT-LOCAL hub, where the adapter looks) -----
# Same models/huggingface/hub as every other model; glm_adapter.py exports it to
# the glmocr child. A copy ONLY in ~/.cache/huggingface came from an older
# --precache-layout run and must be re-primed to be project-local/portable.
PROJ_HUB="$(project_hf_hub)"
DEF_HUB="${HOME}/.cache/huggingface/hub"
if compgen -G "$PROJ_HUB/models--PaddlePaddle--PP-DocLayout*" >/dev/null 2>&1; then
  ok  "GLM layout model     : cached in $PROJ_HUB (project-local)"
elif compgen -G "$DEF_HUB/models--PaddlePaddle--PP-DocLayout*" >/dev/null 2>&1; then
  warn "GLM layout model     : Found in global cache but missing from project-local cache."
  warn "                       Run scripts/setup_glm.sh --precache-layout."
else
  info "GLM layout model     : not cached — 'scripts/setup_glm.sh --precache-layout' (online)"
fi

# --- GLM MLX server model (the model mlx_vlm.server itself loads) ------------
# Distinct from the layout detector above: this is the vision OCR model the
# MLX server holds resident (default mlx-community/GLM-OCR-bf16). Same
# project-local-hub policy — tools/glm_serve.sh exports HF_HUB_CACHE there, so
# only a project-local copy makes the server start offline-clean.
GLM_MLX_REPO_DIR="models--$(printf '%s' "$GLM_MODEL" | sed 's|/|--|g')"
if compgen -G "$PROJ_HUB/$GLM_MLX_REPO_DIR" >/dev/null 2>&1; then
  ok  "GLM MLX server model : $GLM_MODEL — cached in $PROJ_HUB (project-local)"
elif compgen -G "$DEF_HUB/$GLM_MLX_REPO_DIR" >/dev/null 2>&1; then
  warn "GLM MLX server model : Found in global cache but missing from project-local cache."
  warn "                       Run scripts/setup_glm.sh --precache-mlx."
else
  info "GLM MLX server model : $GLM_MODEL not cached — 'scripts/setup_glm.sh --precache-mlx'"
  info "                       (online; the first 'scripts/start_glm.sh' also downloads it project-locally)"
fi

# --- GLM port + readiness -----------------------------------------------------
# Port listening ≠ model loaded: a cold server holds the port while the MLX
# model is still loading/downloading (glm_ready_state distinguishes the two).
GLM_STATE="$(glm_ready_state)"
case "$GLM_STATE" in
  ready:*) ok  "GLM server           : READY — model loaded (${GLM_STATE#ready:})" ;;
  loading) warn "GLM server           : port $GLM_PORT listening but the model is still loading — wait or check logs/glm.log" ;;
  no-model) info "GLM server           : up, no model loaded yet (loads on first request)" ;;
  unknown) warn "GLM server           : something on port $GLM_PORT does not answer like the GLM server" ;;
  down)    info "GLM port $GLM_PORT       : free (server not running — optional)" ;;
esac

hr
ok "Offline readiness report complete."
echo
echo "To make a clean clone fully offline-ready:"
echo "  scripts/setup_offline.sh               # Qwen(chat+rewrite), PhoBERT, embeddings, Paddle, VietOCR(+config.yml), Argos"
echo "                                          # (wrapper — always uses the main venv Python; do NOT use bare 'python')"
echo "  scripts/setup_glm.sh --precache          # (Apple Silicon) GLM venvs + layout model + MLX server model"
exit "$FAIL"
