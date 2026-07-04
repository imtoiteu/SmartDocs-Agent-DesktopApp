"""Integration tests against a REAL desktop sidecar process.

Covers the runtime guarantees the pure-logic tests can't: 127.0.0.1-only
binding, dynamic port selection, the stdout handshake, token rejection (401),
health, duplicate-instance refusal, graceful shutdown (endpoint + SIGTERM),
crash recovery after SIGKILL (stale-lock reclaim), port release, and
persistence of settings/DB across restarts.

Sidecar resolution order:
  1. $SMARTDOCS_SIDECAR_CMD          (space-split command line)
  2. packaged binary                 desktop/sidecar/dist/smartdocs-sidecar/smartdocs-sidecar
  3. $SMARTDOCS_SIDECAR_PYTHON desktop_server.py   (a venv python with Flask)

Needs a runnable sidecar (Flask etc.); if none is available the suite reports
SKIPPED and exits 0 — it is run for real by scripts/test-desktop.sh and CI.
Stdlib only; standalone runner (`python desktop/tests/test_sidecar_integration.py`).
"""

import json
import os
import pathlib
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

_ROOT = pathlib.Path(__file__).resolve().parents[2]
TOK = "integration-test-token-0123456789abcdef"
HANDSHAKE_TIMEOUT = 120          # cold start of a packaged binary
EXIT_TIMEOUT = 15


def _sidecar_cmd():
    env_cmd = os.environ.get("SMARTDOCS_SIDECAR_CMD", "").strip()
    if env_cmd:
        return shlex.split(env_cmd)
    packaged = _ROOT / "desktop" / "sidecar" / "dist" / "smartdocs-sidecar" / "smartdocs-sidecar"
    if packaged.exists():
        return [str(packaged)]
    py = os.environ.get("SMARTDOCS_SIDECAR_PYTHON", "").strip()
    if py and pathlib.Path(py).exists():
        return [py, str(_ROOT / "desktop_server.py")]
    return None


def _clean_env(data_dir):
    """Minimal, deterministic environment: nothing inherited that could flip
    privacy mode (ALLOW_CLOUD), point at real keys, or shadow data paths."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "SMARTDOCS_DATA_DIR": str(data_dir),
        "SMARTDOCS_TOKEN_STDIN": "1",
    }
    return env


class Sidecar:
    def __init__(self, data_dir, token=TOK):
        cmd = _sidecar_cmd()
        assert cmd, "no runnable sidecar"
        self.stderr_path = pathlib.Path(data_dir) / "sidecar-stderr.log"
        self._stderr_fh = open(self.stderr_path, "ab")
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self._stderr_fh, env=_clean_env(data_dir), cwd=str(_ROOT))
        self.proc.stdin.write((token + "\n").encode())
        self.proc.stdin.flush()
        self.handshake = self._read_handshake()
        self.port = self.handshake.get("port")

    def _read_handshake(self):
        box = {}

        def reader():
            for raw in self.proc.stdout:
                line = raw.decode(errors="replace").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue             # tolerate stray non-JSON noise
                if obj.get("event") in ("ready", "error"):
                    box["hs"] = obj
                    return

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(HANDSHAKE_TIMEOUT)
        if "hs" not in box:
            self.kill()
            tail = self.stderr_tail()
            raise AssertionError(f"no handshake within {HANDSHAKE_TIMEOUT}s; "
                                 f"stderr tail:\n{tail}")
        return box["hs"]

    def stderr_tail(self, n=20):
        try:
            return "\n".join(
                self.stderr_path.read_text(errors="replace").splitlines()[-n:])
        except OSError:
            return "<no stderr captured>"

    def http(self, path, method="GET", token=None, body=None, timeout=15):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if token:
            req.add_header("X-SmartDocs-Token", token)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")
        except (ConnectionError, urllib.error.URLError) as e:
            if path == "/api/desktop/shutdown":
                return 0, ""            # shutdown may drop the connection; the
                                        # real assertion is the exit code below
            raise

    def wait_exit(self, timeout=EXIT_TIMEOUT):
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def terminate(self):
        if self.proc.poll() is None:
            self.proc.terminate()

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=10)
        try:
            self._stderr_fh.close()
        except OSError:
            pass


def _loopback_bindings(port):
    """Parse /proc/net/tcp{,6} for LISTEN sockets on `port`.
    Returns the set of local addresses (hex) listening on that port."""
    found = set()
    for proc_file, width in (("/proc/net/tcp", 8), ("/proc/net/tcp6", 32)):
        try:
            lines = pathlib.Path(proc_file).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) < 4 or parts[3] != "0A":     # 0A = LISTEN
                continue
            addr, _, hexport = parts[1].partition(":")
            if int(hexport, 16) == port:
                found.add(addr)
    return found


# ── tests (each gets a fresh temp data dir) ──────────────────────────────────
def test_handshake_dynamic_port_and_two_parallel_instances():
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        a = Sidecar(d1)
        try:
            assert a.handshake["event"] == "ready", a.handshake
            assert isinstance(a.port, int) and a.port > 1024
            assert a.handshake.get("pid") == a.proc.pid
            b = Sidecar(d2)                    # different data dir → allowed
            try:
                assert b.handshake["event"] == "ready"
                assert b.port != a.port        # dynamically chosen, not fixed
            finally:
                b.kill()
        finally:
            a.kill()


def test_binds_loopback_only():
    with tempfile.TemporaryDirectory() as d:
        s = Sidecar(d)
        try:
            addrs = _loopback_bindings(s.port)
            assert addrs, f"no LISTEN socket found for port {s.port}"
            # IPv4 loopback is 0100007F; anything else (0.0.0.0, ::, ::1-mapped
            # wildcards) is a fail.
            assert addrs <= {"0100007F"}, f"non-loopback binding(s): {addrs}"
        finally:
            s.kill()


def test_api_requires_token():
    with tempfile.TemporaryDirectory() as d:
        s = Sidecar(d)
        try:
            code, _ = s.http("/api/desktop/health")
            assert code == 401
            code, _ = s.http("/api/desktop/health", token="wrong-" + "x" * 32)
            assert code == 401
            code, body = s.http("/api/desktop/health", token=TOK)
            assert code == 200 and json.loads(body)["status"] == "ok"
            code, _ = s.http("/api/documents")            # any /api route
            assert code == 401
            code, body = s.http("/api/documents", token=TOK)
            assert code == 200 and json.loads(body)["success"] is True
        finally:
            s.kill()


def test_boot_page_is_open_and_secret_free():
    with tempfile.TemporaryDirectory() as d:
        s = Sidecar(d)
        try:
            code, body = s.http("/desktop/boot")
            assert code == 200
            assert TOK not in body                        # never echoes tokens
            assert "__SMARTDOCS_DESKTOP__" in body        # reads injected token
        finally:
            s.kill()


def test_duplicate_instance_refused():
    with tempfile.TemporaryDirectory() as d:
        a = Sidecar(d)
        try:
            b = Sidecar.__new__(Sidecar)                  # spawn manually to
            b.__init__(d)                                 # reuse same data dir
            try:
                assert b.handshake["event"] == "error", b.handshake
                assert "already running" in b.handshake["message"]
                assert b.proc.wait(timeout=10) == 3
            finally:
                b.kill()
        finally:
            a.kill()


def test_graceful_shutdown_endpoint_and_port_release():
    with tempfile.TemporaryDirectory() as d:
        s = Sidecar(d)
        code, body = s.http("/api/desktop/shutdown", method="POST", token=TOK)
        assert code == 200 and json.loads(body)["shutting_down"] is True
        assert s.wait_exit() == 0, "sidecar did not exit cleanly"
        with socket.socket() as sock:                     # port actually freed
            assert sock.connect_ex(("127.0.0.1", s.port)) != 0
        assert not (pathlib.Path(d) / "smartdocs-sidecar.lock").exists()


def test_sigterm_clean_exit():
    with tempfile.TemporaryDirectory() as d:
        s = Sidecar(d)
        s.proc.send_signal(signal.SIGTERM)
        assert s.wait_exit() == 0
        assert not (pathlib.Path(d) / "smartdocs-sidecar.lock").exists()


def test_sigkill_then_restart_reclaims_stale_lock():
    with tempfile.TemporaryDirectory() as d:
        s = Sidecar(d)
        s.proc.kill()                                     # simulated crash
        s.proc.wait(timeout=10)
        assert (pathlib.Path(d) / "smartdocs-sidecar.lock").exists()
        s2 = Sidecar(d)                                   # recovery start
        try:
            assert s2.handshake["event"] == "ready"
        finally:
            s2.kill()


def test_settings_and_db_persist_across_restart():
    with tempfile.TemporaryDirectory() as d:
        s = Sidecar(d)
        code, _ = s.http("/api/settings/privacy", method="PUT", token=TOK,
                         body={"allow": False})
        assert code == 200
        assert (pathlib.Path(d) / "smartdocs.db").exists()
        s.http("/api/desktop/shutdown", method="POST", token=TOK)
        assert s.wait_exit() == 0

        s2 = Sidecar(d)
        try:
            code, body = s2.http("/api/settings", token=TOK)
            assert code == 200
            payload = json.loads(body)
            assert payload["privacy"]["allow_cloud"] is False   # survived restart
        finally:
            s2.kill()


if __name__ == "__main__":
    import traceback
    if _sidecar_cmd() is None:
        print("SKIPPED: no runnable sidecar (set SMARTDOCS_SIDECAR_CMD or "
              "SMARTDOCS_SIDECAR_PYTHON, or build the packaged sidecar).")
        sys.exit(0)
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
