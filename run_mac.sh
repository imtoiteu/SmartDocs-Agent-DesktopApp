#!/usr/bin/env bash
# ============================================================
#  SmartDocs Platform — macOS / Linux Startup Script
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/.venv"   # OCRSoftware/.venv (SmartDocs-Agent sits one level under OCRSoftware)

echo ""
echo "================================================="
echo "  SmartDocs Platform — Starting up"
echo "================================================="

# ── Activate virtual environment ────────────────────────────
if [ -f "$VENV_DIR/bin/activate" ]; then
    echo "  🐍  Activating venv: $VENV_DIR"
    source "$VENV_DIR/bin/activate"
elif [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    echo "  🐍  Activating local venv"
    source "$SCRIPT_DIR/.venv/bin/activate"
else
    echo "  ⚠️  No virtual environment found at $VENV_DIR"
    echo "      Create one with Python 3.10 (REQUIRED — 3.12/3.13/3.14 cannot install paddlepaddle):"
    echo "      python3.10 -m venv .venv && source .venv/bin/activate    # brew install python@3.10"
    echo "      Then install: pip install -r requirements.txt   (or just run scripts/setup.sh)"
    exit 1
fi

# ── Copy .env if missing ────────────────────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ] && [ -f "$SCRIPT_DIR/.env.example" ]; then
    echo "  📄  Creating .env from .env.example"
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
fi

# ── Install / upgrade dependencies ──────────────────────────
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "  📦  Checking dependencies…"
    pip install -q -r "$SCRIPT_DIR/requirements.txt"
fi

# ── Start the app ───────────────────────────────────────────
echo "  🚀  Launching SmartDocs Platform…"
echo ""
cd "$SCRIPT_DIR"
python app.py
