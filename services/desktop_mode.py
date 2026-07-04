"""Desktop (Tauri sidecar) mode — pure helpers.

This module is stdlib-only so it can be imported and tested without Flask or
any ML dependency. Everything Flask-facing lives in desktop_server.py, which
is only executed inside the packaged sidecar (or a dev venv with full deps).

Contract with the Tauri shell (src-tauri/src/main.rs):
  • The shell generates a per-launch token and passes it via stdin (one line,
    SMARTDOCS_TOKEN_STDIN=1) or the SMARTDOCS_DESKTOP_TOKEN env var (dev).
  • The shell sets SMARTDOCS_DATA_DIR to the per-user app-data directory it
    resolved natively; apply_data_dirs() maps that onto the env vars config.py
    already understands (DB_PATH / UPLOAD_DIR / MODEL_DIR) BEFORE config is
    imported, so the packaged install directory is never written to.
  • The sidecar prints exactly one machine-readable JSON handshake line to
    stdout ("ready" with the dynamically bound port, or "error"); all logging
    goes to stderr. The token never appears in the handshake or in logs.
"""

import hmac
import json
import os
import sys
from pathlib import Path

DESKTOP_ENV = "SMARTDOCS_DESKTOP"                # "1" → desktop mode active
TOKEN_ENV = "SMARTDOCS_DESKTOP_TOKEN"            # dev/backward-compatible path
TOKEN_STDIN_ENV = "SMARTDOCS_TOKEN_STDIN"        # "1" → read token from stdin
DATA_DIR_ENV = "SMARTDOCS_DATA_DIR"              # per-user writable root
TOKEN_HEADER = "X-SmartDocs-Token"
MIN_TOKEN_LEN = 16                               # reject trivially weak tokens

# SMARTDOCS_DATA_DIR → env vars config.py resolves (explicit env always wins,
# preserving the documented .env override behavior).
_DATA_ENV_MAP = (
    ("DB_PATH", "smartdocs.db"),        # SQLite DB (settings JSON lands beside it)
    ("UPLOAD_DIR", "uploads"),          # user documents
    ("MODEL_DIR", "models"),            # HF / argos caches all derive from this
)


def is_desktop(environ=None) -> bool:
    env = os.environ if environ is None else environ
    return env.get(DESKTOP_ENV, "") == "1"


def read_token(environ=None, stdin=None):
    """Return the launch token, or None.

    Priority: SMARTDOCS_DESKTOP_TOKEN env var (dev convenience), else — when
    SMARTDOCS_TOKEN_STDIN=1 — the first line of stdin (how the Tauri shell
    hands it over without exposing it in the process environment).
    """
    env = os.environ if environ is None else environ
    tok = (env.get(TOKEN_ENV) or "").strip()
    if tok:
        return tok
    if env.get(TOKEN_STDIN_ENV, "") == "1":
        stream = sys.stdin if stdin is None else stdin
        try:
            line = stream.readline()
        except Exception:
            return None
        tok = (line or "").strip()
        return tok or None
    return None


def token_ok(candidate, expected) -> bool:
    """Constant-time token comparison; empty/short values never match."""
    if not candidate or not expected or len(expected) < MIN_TOKEN_LEN:
        return False
    return hmac.compare_digest(str(candidate), str(expected))


def data_dir(environ=None):
    env = os.environ if environ is None else environ
    raw = (env.get(DATA_DIR_ENV) or "").strip()
    return Path(raw) if raw else None


def default_data_dir(system=None, home=None, appdata=None) -> Path:
    """Per-platform app-data default, for dev runs without the Tauri shell.

    Packaged runs never hit this: Tauri resolves the platform directory
    natively and passes it via SMARTDOCS_DATA_DIR. Mirrors Tauri's own
    app-data conventions (identifier "SmartDocs").
    """
    system = system or sys.platform
    home = Path(home) if home else Path.home()
    if system.startswith("darwin"):
        return home / "Library" / "Application Support" / "SmartDocs"
    if system.startswith("win"):
        base = Path(appdata) if appdata else (
            Path(os.environ.get("APPDATA") or (home / "AppData" / "Roaming")))
        return base / "SmartDocs"
    xdg = os.environ.get("XDG_DATA_HOME", "")
    base = Path(xdg) if xdg else home / ".local" / "share"
    return base / "SmartDocs"


def apply_data_dirs(environ=None):
    """Map SMARTDOCS_DATA_DIR onto DB_PATH/UPLOAD_DIR/MODEL_DIR.

    Must run BEFORE `from config import cfg` (config mkdirs and hard-sets the
    HF/argos cache env from MODEL_DIR at import time). Explicitly-set env vars
    win, exactly like .env-based configuration. Returns {env_key: value}
    for what was applied.
    """
    env = os.environ if environ is None else environ
    root = data_dir(env)
    if root is None:
        return {}
    root.mkdir(parents=True, exist_ok=True)
    applied = {}
    for key, leaf in _DATA_ENV_MAP:
        if (env.get(key) or "").strip():
            continue                     # explicit configuration wins
        value = str(root / leaf)
        env[key] = value
        applied[key] = value
    return applied


def ready_handshake(port, pid, version="") -> str:
    """The single stdout line the Tauri shell waits for. Never contains secrets."""
    return json.dumps({"event": "ready", "port": int(port), "pid": int(pid),
                       "version": str(version)}, separators=(",", ":"))


def error_handshake(message) -> str:
    return json.dumps({"event": "error", "message": str(message)},
                      separators=(",", ":"))


class SingletonLock:
    """PID-file lock preventing duplicate sidecars on the same data dir.

    Defense-in-depth below the Tauri single-instance plugin: even a manually
    launched second sidecar refuses to start. A lock whose PID is no longer
    alive is stale (crash leftover) and is reclaimed.
    """

    def __init__(self, directory: Path, name: str = "smartdocs-sidecar.lock"):
        self.path = Path(directory) / name
        self._held = False

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True                  # exists, owned by someone else
        except (OSError, ValueError):
            return True                  # unknown (e.g. Windows quirk) → conservative

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):               # second pass after removing a stale lock
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as fh:
                    fh.write(str(os.getpid()))
                self._held = True
                return True
            except FileExistsError:
                try:
                    old = int(self.path.read_text().strip() or "0")
                except (OSError, ValueError):
                    old = 0
                if self._pid_alive(old):
                    return False         # held by a live process (maybe ours)
                try:
                    self.path.unlink()   # stale — reclaim
                except OSError:
                    return False
        return False

    def release(self):
        if self._held:
            try:
                self.path.unlink()
            except OSError:
                pass
            self._held = False
