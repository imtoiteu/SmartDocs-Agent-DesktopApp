#!/usr/bin/env bash
# Packaged-app smoke test (Linux, headless).
#
# Runs the REAL desktop binary from an extracted .deb under Xvfb + a private
# dbus session, then verifies from the outside:
#   1. the shell spawns exactly one sidecar
#   2. the sidecar listens on 127.0.0.1 (loopback only)
#   3. /api/* without the launch token → 401  (token protection is live)
#   4. /desktop/boot → 200                    (UI bootstrap reachable)
#   5. SIGTERM → shell AND sidecar exit, lock removed — no orphans
#
# Usage: scripts/smoke-gui-linux.sh [path/to/SmartDocs_*.deb]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEB="${1:-$(ls "$ROOT"/src-tauri/target/release/bundle/deb/SmartDocs_*.deb 2>/dev/null | head -1)}"
[ -f "$DEB" ] || { echo "FAIL no .deb found (build first)"; exit 1; }

WORK="$(mktemp -d)"
trap 'kill -9 "${APP_PID:-0}" 2>/dev/null; rm -rf "$WORK"' EXIT
dpkg-deb -x "$DEB" "$WORK/root" || { echo "FAIL cannot extract $DEB"; exit 1; }
BIN="$WORK/root/usr/bin/smartdocs-desktop"
[ -x "$BIN" ] || { echo "FAIL packaged binary missing"; exit 1; }

export XDG_DATA_HOME="$WORK/data"
export WEBKIT_DISABLE_COMPOSITING_MODE=1
DATA_DIR="$XDG_DATA_HOME/com.smartdocs.desktop"

dbus-run-session -- xvfb-run -a "$BIN" >"$WORK/app.log" 2>&1 &
APP_PID=$!
echo "launched packaged app (pid $APP_PID)"

# ── wait for the sidecar to appear and listen ────────────────────────────────
SIDECAR_PID=""
for _ in $(seq 1 90); do
  SIDECAR_PID=$(pgrep -f "$WORK/root/usr/lib/SmartDocs/sidecar/smartdocs-sidecar" | head -1)
  [ -n "$SIDECAR_PID" ] && [ -f "$DATA_DIR/smartdocs-sidecar.lock" ] && break
  kill -0 "$APP_PID" 2>/dev/null || { echo "FAIL app exited early"; tail -20 "$WORK/app.log"; exit 1; }
  sleep 1
done
[ -n "$SIDECAR_PID" ] || { echo "FAIL sidecar never spawned"; tail -20 "$WORK/app.log"; exit 1; }
echo "PASS sidecar spawned (pid $SIDECAR_PID)"

N_SIDECARS=$(pgrep -fc "$WORK/root/usr/lib/SmartDocs/sidecar/smartdocs-sidecar")
[ "$N_SIDECARS" = "1" ] && echo "PASS exactly one sidecar" || { echo "FAIL $N_SIDECARS sidecars"; exit 1; }

PORT=""
for _ in $(seq 1 60); do
  PORT=$(ss -ltnp 2>/dev/null | grep "pid=$SIDECAR_PID," | grep -oE '127\.0\.0\.1:[0-9]+' | head -1 | cut -d: -f2)
  [ -n "$PORT" ] && break
  sleep 1
done
[ -n "$PORT" ] || { echo "FAIL sidecar not listening on loopback"; exit 1; }
echo "PASS sidecar listening on 127.0.0.1:$PORT"

ss -ltnp 2>/dev/null | grep "pid=$SIDECAR_PID," | grep -qE '(0\.0\.0\.0|\[::\]):' \
  && { echo "FAIL wildcard binding detected"; exit 1; } || echo "PASS loopback-only binding"

CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/desktop/health")
[ "$CODE" = "401" ] && echo "PASS /api without token → 401" || { echo "FAIL expected 401, got $CODE"; exit 1; }

CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/desktop/boot")
[ "$CODE" = "200" ] && echo "PASS /desktop/boot → 200" || { echo "FAIL boot page gave $CODE"; exit 1; }

# ── clean shutdown, no orphans ───────────────────────────────────────────────
kill -TERM "$APP_PID"
DEAD=""
for _ in $(seq 1 20); do
  if ! kill -0 "$APP_PID" 2>/dev/null && ! kill -0 "$SIDECAR_PID" 2>/dev/null; then DEAD=1; break; fi
  sleep 1
done
[ -n "$DEAD" ] && echo "PASS shell + sidecar both exited after SIGTERM (no orphan)" \
  || { echo "FAIL orphaned process after SIGTERM"; exit 1; }
[ ! -f "$DATA_DIR/smartdocs-sidecar.lock" ] && echo "PASS lock released" || { echo "FAIL lock left behind"; exit 1; }
[ -f "$DATA_DIR/smartdocs.db" ] && echo "PASS data dir populated ($DATA_DIR)" || { echo "FAIL no database created"; exit 1; }

echo "SMOKE-OK"
