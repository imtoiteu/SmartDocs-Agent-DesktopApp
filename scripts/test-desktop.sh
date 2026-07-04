#!/usr/bin/env bash
# Full desktop test pass:
#   1. existing agent/backend suites (standalone runners, no pytest needed)
#   2. sidecar integration tests against a real sidecar process
#      (packaged binary if built, else desktop_server.py from the venv)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAILED=0

echo "── agent + desktop unit suites ──────────────────────────────"
for f in agent/tests/test_*.py; do
  python3 "$f" >/tmp/sd-test-out 2>&1
  rc=$?
  tail -1 /tmp/sd-test-out | sed "s|^|$f: |"
  [ $rc -ne 0 ] && { FAILED=1; cat /tmp/sd-test-out; }
done

echo "── sidecar integration ──────────────────────────────────────"
PKG="$ROOT/desktop/sidecar/dist/smartdocs-sidecar/smartdocs-sidecar"
VENV_PY="$ROOT/desktop/sidecar/venv/bin/python"
if [ -x "$PKG" ]; then
  export SMARTDOCS_SIDECAR_CMD="$PKG"
elif [ -x "$VENV_PY" ]; then
  export SMARTDOCS_SIDECAR_PYTHON="$VENV_PY"
fi
python3 desktop/tests/test_sidecar_integration.py || FAILED=1

exit $FAILED
