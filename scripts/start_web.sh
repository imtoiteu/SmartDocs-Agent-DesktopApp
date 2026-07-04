#!/usr/bin/env bash
# ============================================================================
#  scripts/start_web.sh — start ONLY the SmartDocs Flask web app.
#
#  Resolves the venv automatically (repo .venv -> parent .venv -> system
#  python3) so the user never has to activate anything. Reads .env for the
#  port (SMARTDOCS_PORT / PORT). The GLM OCR engine is optional and is NOT
#  started here — the other OCR engines work without it.
#
#  Usage:
#    scripts/start_web.sh          # run in the foreground (Ctrl-C to stop)
#    scripts/start_web.sh -b       # run in the background (logs/web.log, PID file)
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

PY="$(resolve_python)" || { err "No Python interpreter found. Run scripts/setup.sh first."; exit 1; }

if ! "$PY" -c 'import flask' >/dev/null 2>&1; then
  err "Flask is not installed in $PY."
  err "Run scripts/setup.sh to create the venv and install dependencies."
  exit 1
fi

if port_in_use "$SMARTDOCS_PORT"; then
  warn "Port $SMARTDOCS_PORT is already in use — is SmartDocs already running?"
  warn "Use scripts/stop.sh to stop it, or set SMARTDOCS_PORT to a free port."
  exit 1
fi

info "Starting SmartDocs web app"
info "  python : $PY"
info "  url    : http://${SMARTDOCS_LOCAL_HOST}:${SMARTDOCS_PORT}"

cd "$REPO_ROOT"
if [ "$BACKGROUND" -eq 1 ]; then
  nohup "$PY" "$REPO_ROOT/app.py" >>"$LOG_DIR/web.log" 2>&1 &
  echo $! > "$WEB_PID_FILE"
  ok "SmartDocs started in background (PID $(cat "$WEB_PID_FILE")) — logs: logs/web.log"
else
  # Foreground: exec replaces this shell so Ctrl-C goes straight to Flask.
  exec "$PY" "$REPO_ROOT/app.py"
fi
