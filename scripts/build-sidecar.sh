#!/usr/bin/env bash
# Build the PyInstaller sidecar (one-dir) into desktop/sidecar/dist/.
# Deterministic: own venv, pinned entry spec, no system site-packages.
# Must run on the TARGET OS — PyInstaller does not cross-compile.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIDECAR="$ROOT/desktop/sidecar"
PY="${PYTHON:-python3}"

cd "$SIDECAR"

if [ ! -d venv ]; then
  "$PY" -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate 2>/dev/null || source venv/Scripts/activate

python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements-core.txt "pyinstaller>=6.0"

# Sanity: the backend must import cleanly with the core dependency set before
# we spend time freezing it.
(cd "$ROOT" && SMARTDOCS_DATA_DIR="$(mktemp -d)" python -c "import app; print('import app: OK')")

pyinstaller --clean --noconfirm smartdocs-sidecar.spec

BIN="dist/smartdocs-sidecar/smartdocs-sidecar"
[ -f "$BIN" ] || BIN="dist/smartdocs-sidecar/smartdocs-sidecar.exe"
echo "sidecar built: $SIDECAR/$BIN"
