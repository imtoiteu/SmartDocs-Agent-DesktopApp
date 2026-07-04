#!/usr/bin/env bash
# ============================================================================
#  scripts/start_glm.sh — start ONLY the GLM-OCR MLX model server.
#
#  Thin, robust wrapper around the existing tools/glm_serve.sh (which is the
#  verified-working launch command on the MacBook). This script just resolves
#  paths, loads .env, and passes GLM_PORT through — it does NOT change how the
#  server is invoked.
#
#  GLM-OCR is OPTIONAL and Apple-Silicon / MLX only. If the MLX venv is not
#  present (e.g. on the VPS or a non-Mac host) this exits with a clear message;
#  the SmartDocs web app still runs fine without it — only the GLM OCR engine
#  is unavailable.
#
#  Usage:
#    scripts/start_glm.sh          # run in the foreground (Ctrl-C to stop)
#    scripts/start_glm.sh -b       # run in the background (logs/glm.log, PID file)
# ============================================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$DIR/lib.sh"

load_env
normalize_env
ensure_dirs

BACKGROUND=0
case "${1:-}" in -b|--background) BACKGROUND=1 ;; esac

# This script manages the LOCAL MLX server only. On Windows/Linux the default
# mode is "disabled" (lib.sh) — external_server / maas_api need no local server.
if [ "$GLM_OCR_MODE" != "local_mlx" ]; then
  err "GLM_OCR_MODE=$GLM_OCR_MODE — start_glm.sh only manages the LOCAL MLX server (GLM_OCR_MODE=local_mlx)."
  err "GLM local MLX is only supported on macOS Apple Silicon. Use external_server, maas_api, or disable GLM."
  err "(On Apple Silicon, set GLM_OCR_MODE=local_mlx in .env to run the server here.)"
  exit 1
fi
if ! is_apple_silicon; then
  warn "This host is not macOS Apple Silicon — the MLX server normally cannot run here"
  warn "(mlx/mlx-vlm wheels are macOS/arm64 only); expect the steps below to fail."
fi

GLM_SERVE="$REPO_ROOT/tools/glm_serve.sh"
if [ ! -x "$GLM_SERVE" ]; then
  err "tools/glm_serve.sh not found or not executable at $GLM_SERVE"
  exit 1
fi

if port_in_use "$GLM_PORT"; then
  warn "Port $GLM_PORT already in use — the GLM server may already be running."
  case "$(glm_ready_state)" in
    ready:*)
      ok "GLM server is already up with the model loaded on $GLM_OCR_API_URL"
      exit 0 ;;
    loading|no-model)
      ok "GLM server is already running on $GLM_OCR_API_URL but the model is not"
      ok "loaded yet — it is loading (or loads on first request). Watch logs/glm.log."
      exit 0 ;;
    *)
      err "Something is on port $GLM_PORT but not answering as GLM. Free it or set GLM_PORT."
      exit 1 ;;
  esac
fi

info "Starting GLM-OCR MLX server"
info "  port  : $GLM_PORT"
info "  model : $GLM_MODEL"
info "  serve : $GLM_SERVE"

# GLM_PORT is exported (normalize_env); tools/glm_serve.sh reads it from the env.
if [ "$BACKGROUND" -eq 1 ]; then
  nohup "$GLM_SERVE" >>"$LOG_DIR/glm.log" 2>&1 &
  echo $! > "$GLM_PID_FILE"
  GPID="$(read_pid "$GLM_PID_FILE")"
  ok "GLM server process started (PID $GPID) — logs: logs/glm.log"

  # Three DISTINCT startup facts — never claim "ready" from a mere port probe:
  #   1. process started        (PID alive)
  #   2. HTTP server listening  (port open)
  #   3. model loaded / READY   (glm_ready_state == ready:<model>)
  # With the default preload (tools/glm_serve.sh passes --model) the port only
  # opens once the model is loaded, so 2 usually implies 3. The wait is bounded:
  # a first-ever ONLINE start downloads the model and can exceed it — that is
  # reported as "still starting", not as failure. GLM_START_WAIT=0 skips waiting.
  WAIT="${GLM_START_WAIT:-90}"
  if [ "$WAIT" -le 0 ] 2>/dev/null; then
    info "Not waiting for readiness (GLM_START_WAIT=0) — check later with: scripts/check.sh"
    exit 0
  fi
  info "Waiting up to ${WAIT}s for readiness (a first online start downloads the model — may take longer)…"
  LISTENING=0
  ELAPSED=0
  while [ "$ELAPSED" -lt "$WAIT" ]; do
    if ! pid_alive "$GPID"; then
      err "GLM server process exited during startup — last lines of logs/glm.log:"
      tail -5 "$LOG_DIR/glm.log" 2>/dev/null | sed 's/^/         /' >&2
      err "(A preload failure with OFFLINE model missing? Pre-cache it online:"
      err " scripts/setup_glm.sh --precache-mlx)"
      rm -f "$GLM_PID_FILE"
      exit 1
    fi
    STATE="$(glm_ready_state)"
    case "$STATE" in
      ready:*)
        [ "$LISTENING" -eq 1 ] || info "HTTP server listening on port $GLM_PORT"
        ok "GLM server READY for inference (model loaded: ${STATE#ready:})"
        exit 0 ;;
      loading|no-model|unknown)
        if [ "$LISTENING" -eq 0 ]; then
          LISTENING=1
          info "HTTP server listening on port $GLM_PORT — model still loading…"
        fi ;;
    esac
    sleep 3
    ELAPSED=$((ELAPSED + 3))
  done
  warn "GLM server process is up but the model is NOT loaded yet (still loading/downloading)."
  warn "This is not an error — follow logs/glm.log and re-check with: scripts/check.sh"
else
  exec "$GLM_SERVE"
fi
