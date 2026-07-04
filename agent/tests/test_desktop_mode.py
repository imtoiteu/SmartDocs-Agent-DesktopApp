"""Tests for services/desktop_mode.py — the stdlib-only desktop sidecar
helpers (token handling, handshake protocol, data-dir mapping, per-platform
path resolution, singleton lock). Flask-facing behavior (401s, health,
shutdown, persistence) is covered by desktop/tests/test_sidecar_integration.py
against a real sidecar process.

Runs under pytest OR standalone (`python agent/tests/test_desktop_mode.py`).
"""

import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import pytest  # noqa: F401
except ImportError:
    pytest = None

from services import desktop_mode as dm

TOK = "a" * 32


# ── token handling ───────────────────────────────────────────────────────────
def test_token_ok_matches_only_exact_token():
    assert dm.token_ok(TOK, TOK)
    assert not dm.token_ok(TOK[:-1] + "b", TOK)
    assert not dm.token_ok("", TOK)
    assert not dm.token_ok(None, TOK)
    assert not dm.token_ok(TOK, "")
    assert not dm.token_ok("short", "short")          # < MIN_TOKEN_LEN


def test_read_token_env_wins_and_is_stripped():
    env = {dm.TOKEN_ENV: f"  {TOK}\n"}
    assert dm.read_token(environ=env) == TOK


def test_read_token_stdin_mode_reads_one_line():
    env = {dm.TOKEN_STDIN_ENV: "1"}
    assert dm.read_token(environ=env, stdin=io.StringIO(TOK + "\nrest")) == TOK
    assert dm.read_token(environ=env, stdin=io.StringIO("\n")) is None
    assert dm.read_token(environ={}) is None           # neither env nor stdin mode


# ── handshake protocol ───────────────────────────────────────────────────────
def test_ready_handshake_is_single_json_line_without_secrets():
    line = dm.ready_handshake(54321, 999, "2026.06.14.1")
    assert "\n" not in line
    obj = json.loads(line)
    assert obj == {"event": "ready", "port": 54321, "pid": 999,
                   "version": "2026.06.14.1"}


def test_error_handshake_parses_and_carries_message():
    obj = json.loads(dm.error_handshake("boom"))
    assert obj["event"] == "error" and obj["message"] == "boom"


# ── data-dir mapping (SMARTDOCS_DATA_DIR → config env vars) ──────────────────
def test_apply_data_dirs_maps_all_writable_paths():
    with tempfile.TemporaryDirectory() as td:
        env = {dm.DATA_DIR_ENV: td}
        applied = dm.apply_data_dirs(environ=env)
        assert set(applied) == {"DB_PATH", "UPLOAD_DIR", "MODEL_DIR"}
        for key, leaf in (("DB_PATH", "smartdocs.db"),
                          ("UPLOAD_DIR", "uploads"),
                          ("MODEL_DIR", "models")):
            assert env[key] == str(pathlib.Path(td) / leaf), key


def test_apply_data_dirs_never_overrides_explicit_env():
    with tempfile.TemporaryDirectory() as td:
        env = {dm.DATA_DIR_ENV: td, "DB_PATH": "/custom/my.db"}
        applied = dm.apply_data_dirs(environ=env)
        assert env["DB_PATH"] == "/custom/my.db"       # explicit config wins
        assert "DB_PATH" not in applied
        assert "UPLOAD_DIR" in applied                 # unset keys still mapped


def test_apply_data_dirs_noop_without_data_dir():
    env = {}
    assert dm.apply_data_dirs(environ=env) == {}
    assert "DB_PATH" not in env


# ── per-platform default data dirs (dev runs without the Tauri shell) ────────
def test_default_data_dir_per_platform():
    home = "/home/u"
    assert dm.default_data_dir("linux", home) == pathlib.Path(
        "/home/u/.local/share/SmartDocs")
    assert dm.default_data_dir("darwin", home) == pathlib.Path(
        "/home/u/Library/Application Support/SmartDocs")
    assert dm.default_data_dir("win32", "C:/Users/u",
                               appdata="C:/Users/u/AppData/Roaming") == \
        pathlib.Path("C:/Users/u/AppData/Roaming/SmartDocs")


# ── singleton lock ───────────────────────────────────────────────────────────
def test_singleton_lock_blocks_second_acquire_and_releases():
    with tempfile.TemporaryDirectory() as td:
        a, b = dm.SingletonLock(pathlib.Path(td)), dm.SingletonLock(pathlib.Path(td))
        assert a.acquire()
        assert not b.acquire()                         # held by a live pid (us)
        a.release()
        assert b.acquire()
        b.release()


def test_singleton_lock_reclaims_stale_pid():
    with tempfile.TemporaryDirectory() as td:
        lock_path = pathlib.Path(td) / "smartdocs-sidecar.lock"
        # A real-but-dead PID: spawn a short-lived process and wait for it.
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        lock_path.write_text(str(proc.pid))
        lk = dm.SingletonLock(pathlib.Path(td))
        assert lk.acquire()                            # stale lock reclaimed
        assert lock_path.read_text() == str(os.getpid())
        lk.release()


def test_singleton_lock_garbage_pidfile_is_reclaimed():
    with tempfile.TemporaryDirectory() as td:
        (pathlib.Path(td) / "smartdocs-sidecar.lock").write_text("not-a-pid")
        lk = dm.SingletonLock(pathlib.Path(td))
        assert lk.acquire()
        lk.release()


if __name__ == "__main__":
    import traceback
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn(); print(f"PASS  {name}")
        except Exception:
            failed += 1; print(f"FAIL  {name}"); traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
