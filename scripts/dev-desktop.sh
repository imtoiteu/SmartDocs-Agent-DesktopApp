#!/usr/bin/env bash
# Development loop: run the Tauri shell against desktop_server.py from the
# sidecar venv (no PyInstaller build needed). Requires: npm i, and the venv
# created by scripts/build-sidecar.sh (or any venv with requirements-core).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$ROOT/desktop/sidecar/venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
  echo "sidecar venv missing — run scripts/build-sidecar.sh first" >&2
  exit 1
fi

# Dev builds of the shell honor SMARTDOCS_SIDECAR_CMD (release builds do not).
export SMARTDOCS_SIDECAR_CMD="$VENV_PY $ROOT/desktop_server.py"
cd "$ROOT"
exec npx tauri dev "$@"
