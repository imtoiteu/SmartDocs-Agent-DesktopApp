#!/usr/bin/env bash
# ============================================================================
#  scripts/stop.sh — stop the local SmartDocs services started by these scripts.
#
#  Stops, in order:
#    * the web app   (PID from logs/web.pid, else whatever holds SMARTDOCS_PORT)
#    * the GLM server (PID from logs/glm.pid, else whatever holds GLM_PORT)
#
#  Only touches background processes started via the -b flag or start.sh. A
#  foreground `start_web.sh` is stopped with Ctrl-C, not this script.
#
#  By default stop.sh ONLY stops processes it started itself (tracked via the
#  PID files in logs/). It will NOT kill an unrelated process that merely happens
#  to hold the port — important on shared machines. Use --force to also stop
#  whatever is holding the configured port when no PID file is present.
#
#  Usage:
#    scripts/stop.sh              # stop tracked web + GLM (PID files only)
#    scripts/stop.sh web          # stop only the tracked web app
#    scripts/stop.sh glm          # stop only the tracked GLM server
#    scripts/stop.sh --force      # ALSO kill whatever holds the port (careful!)
# ============================================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$DIR/lib.sh"

load_env
normalize_env
ensure_dirs

TARGET="all"
FORCE=0
for arg in "$@"; do
  case "$arg" in
    -f|--force) FORCE=1 ;;
    web|glm|all) TARGET="$arg" ;;
    *) err "Unknown argument '$arg' (expected: web | glm | all | --force)"; exit 1 ;;
  esac
done

# Stop a service. Kills the PID-file process (which we started). Only touches a
# port-holding process we did NOT start when --force is given. Args: label pidfile port
stop_service() {
  local label="$1" pidfile="$2" port="$3"
  local stopped=0
  local pid; pid="$(read_pid "$pidfile")"

  if pid_alive "$pid"; then
    info "Stopping $label (PID $pid)…"
    kill "$pid" >/dev/null 2>&1 || true
    # Give it up to ~5s to exit, then SIGKILL.
    local i=0
    while pid_alive "$pid" && [ "$i" -lt 10 ]; do sleep 0.5; i=$((i+1)); done
    if pid_alive "$pid"; then
      warn "$label did not exit — sending SIGKILL"
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
    stopped=1
  fi
  rm -f "$pidfile"

  # Port still held by a process we did NOT start (no/other PID file).
  if port_in_use "$port"; then
    local held=""
    command -v lsof >/dev/null 2>&1 && held="$(lsof -ti "tcp:${port}" 2>/dev/null || true)"
    if [ "$FORCE" -eq 1 ] && [ -n "$held" ]; then
      warn "$label: --force — stopping process(es) on port $port: $held"
      # shellcheck disable=SC2086
      kill $held >/dev/null 2>&1 || true
      stopped=1
    else
      warn "$label: port $port is still in use by PID(s) ${held:-unknown} that these"
      warn "  scripts did not start. NOT touching it. If it is a stale SmartDocs"
      warn "  instance you want gone, re-run with --force, or stop it manually."
    fi
  fi

  if [ "$stopped" -eq 1 ]; then ok "$label stopped"; else info "$label was not running (nothing tracked)"; fi
}

case "$TARGET" in
  web) stop_service "SmartDocs web app" "$WEB_PID_FILE" "$SMARTDOCS_PORT" ;;
  glm) stop_service "GLM server" "$GLM_PID_FILE" "$GLM_PORT" ;;
  all)
    stop_service "SmartDocs web app" "$WEB_PID_FILE" "$SMARTDOCS_PORT"
    stop_service "GLM server" "$GLM_PID_FILE" "$GLM_PORT"
    ;;
esac
