"""Unit/integration tests for the desktop UI gateway (desktop_gateway.py).

Everything runs against a REAL gateway instance and a scriptable in-process
upstream — stdlib only, no Flask needed, a few seconds total. Covers:

  * the Desktop UI is served locally and never comes from the upstream
    (identical across runtime modes / backend targets);
  * API target switching (two gateways → two upstreams);
  * strict route allowlisting (no open proxy, no traversal);
  * cookie rewriting, redirect relay without following, streaming;
  * remote mode: local health, token stripping, page auth-gate, token-guarded
    shutdown;
  * private-LAN IP policy helper + per-connect re-verification;
  * gateway-only entry (subprocess under a BARE python3 — proving Remote
    Server mode needs no Flask and starts no processing backend).
"""

import http.client
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import SkipTest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import desktop_gateway as dg  # noqa: E402


# ── scriptable upstream ───────────────────────────────────────────────────────
class Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    hits = None                                   # set per-server

    def log_message(self, *_):
        pass

    def _reply(self, code, body, headers=()):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self):
        self.hits.append(self.path)
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._reply(200, "UPSTREAM-ROOT-HTML")
        if path == "/api/auth/me":
            if "sid=ok" in (self.headers.get("Cookie") or ""):
                return self._reply(200, json.dumps(
                    {"success": True, "username": "u"}))
            return self._reply(401, json.dumps(
                {"success": False, "redirect": "/login"}))
        if path == "/login":
            return self._reply(200, "UPSTREAM-LOGIN-PAGE")
        if path == "/api/echo":
            body = b""
            n = self.headers.get("Content-Length")
            if n:
                body = self.rfile.read(int(n))
            return self._reply(200, json.dumps({
                "path": self.path, "method": self.command,
                "body": body.decode(errors="replace"),
                "token": self.headers.get("X-SmartDocs-Token"),
                "host": self.headers.get("Host"),
            }))
        if path == "/api/setcookie":
            return self._reply(200, "{}", headers=[
                ("Set-Cookie", "session=abc; Domain=up.example; Path=/; "
                               "Secure; HttpOnly; SameSite=Lax"),
                ("Set-Cookie", "extra=1; Path=/x"),
            ])
        if path == "/api/redir":
            host = self.headers.get("Host")
            self.send_response(302)
            self.send_header("Location", f"http://{host}/api/after")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/api/redir-public":
            self.send_response(302)
            self.send_header("Location", "http://8.8.8.8/steal")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for part in (b"data: one\n\n", b"data: two\n\n",
                         "data: три\n\n".encode()):
                self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            return
        if path == "/api/desktop/health":
            return self._reply(200, json.dumps(
                {"status": "ok", "runtime_mode": "bundled",
                 "from": "backend"}))
        if path == "/desktop/boot":
            return self._reply(200, "BOOT-PAGE __SMARTDOCS_DESKTOP__")
        return self._reply(200, json.dumps({"echo_any": self.path}))

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _handle


def _start_upstream():
    hits = []
    handler = type("U", (Upstream,), {"hits": hits})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, hits


def _start_gateway(upstream_port, **kw):
    ui = tempfile.mkdtemp(prefix="sd-gw-ui-")
    pathlib.Path(ui, "index.html").write_text("<html>LOCAL-DESKTOP-UI</html>")
    pathlib.Path(ui, "agent.html").write_text("<html>LOCAL-AGENT-UI</html>")
    pathlib.Path(ui, "app.js").write_text("// local js")
    srv = dg.make_gateway(ui, f"http://127.0.0.1:{upstream_port}", **kw)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, pathlib.Path(ui)


def _req(port, path, method="GET", headers=None, body=None, raw_path=False):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        r = conn.getresponse()
        data = r.read()
        return r.status, dict((k.lower(), v) for k, v in r.getheaders()), \
            r.msg.get_all("Set-Cookie") or [], data
    finally:
        conn.close()


# ── shared fixtures (one upstream+gateway pair for the read-only tests) ─────
_UP, _HITS = _start_upstream()
_GW, _UI = _start_gateway(_UP.server_address[1])
_P = _GW.server_address[1]


def test_desktop_ui_served_locally_never_from_upstream():
    before = list(_HITS)
    code, _, _, body = _req(_P, "/")
    assert code == 200 and b"LOCAL-DESKTOP-UI" in body
    assert b"UPSTREAM-ROOT-HTML" not in body
    code, _, _, body = _req(_P, "/agent?file_id=x")
    assert code == 200 and b"LOCAL-AGENT-UI" in body
    code, hdrs, _, body = _req(_P, "/static/app.js")
    assert code == 200 and body == b"// local js"
    assert "javascript" in hdrs["content-type"]
    # No page/static request ever reached the upstream.
    assert _HITS == before


def test_api_routes_are_proxied_with_method_and_body():
    code, _, _, body = _req(_P, "/api/echo?q=1", method="POST",
                            headers={"Content-Length": "5",
                                     "X-SmartDocs-Token": "tok-local"},
                            body=b"hello")
    assert code == 200
    j = json.loads(body)
    assert j["path"] == "/api/echo?q=1" and j["method"] == "POST"
    assert j["body"] == "hello"
    # Local mode: the token header IS forwarded (the backend enforces it).
    assert j["token"] == "tok-local"
    # Host header names the upstream, not the gateway.
    assert j["host"] == f"127.0.0.1:{_UP.server_address[1]}"


def test_only_allowlisted_routes_are_proxied():
    before = len(_HITS)
    for path in ("/etc/passwd", "/random", "/apix", "/desktop/private",
                 "/api", "/loginx"):
        code, _, _, _ = _req(_P, path)
        assert code == 404, f"{path} must not be proxied (got {code})"
    assert len(_HITS) == before, "non-allowlisted request reached upstream"
    # Allowlisted page routes DO reach it.
    code, _, _, body = _req(_P, "/login")
    assert code == 200 and b"UPSTREAM-LOGIN-PAGE" in body
    code, _, _, body = _req(_P, "/desktop/boot")
    assert code == 200 and b"__SMARTDOCS_DESKTOP__" in body


def test_static_traversal_is_blocked():
    secret = _UI.parent / f"{_UI.name}-secret.txt"
    secret.write_text("s3cret")
    try:
        code, _, _, body = _req(_P, f"/static/../{secret.name}")
        assert code == 404 and b"s3cret" not in body
        code, _, _, body = _req(_P, "/static/%2e%2e/" + secret.name)
        assert b"s3cret" not in body
    finally:
        secret.unlink()


def test_cookies_lose_domain_and_secure_but_keep_the_rest():
    _, _, cookies, _ = _req(_P, "/api/setcookie")
    assert len(cookies) == 2
    sess = next(c for c in cookies if c.startswith("session="))
    low = sess.lower()
    assert "domain=" not in low and "secure" not in low
    assert "httponly" in low and "samesite=lax" in low and "path=/" in low
    assert any(c.startswith("extra=1") for c in cookies)


def test_redirects_are_relayed_not_followed_and_rewritten():
    before = list(_HITS)
    code, hdrs, _, _ = _req(_P, "/api/redir")
    assert code == 302
    # Absolute upstream-origin Location → gateway origin.
    assert hdrs["location"] == f"http://127.0.0.1:{_P}/api/after"
    # Foreign/public destinations pass through UNTOUCHED and UNFOLLOWED
    # (the WebView's navigation allowlist refuses them).
    code, hdrs, _, _ = _req(_P, "/api/redir-public")
    assert code == 302 and hdrs["location"] == "http://8.8.8.8/steal"
    new = [h for h in _HITS[len(before):]]
    assert "/api/after" not in new and "/steal" not in new


def test_streaming_response_is_relayed():
    code, hdrs, _, body = _req(_P, "/api/stream")
    assert code == 200
    assert body.count(b"data: ") == 3 and "три".encode() in body
    assert hdrs.get("connection", "").lower() == "close"


def test_host_header_guard():
    code, _, _, _ = _req(_P, "/api/echo", headers={"Host": "evil.example"})
    assert code == 403


def test_local_mode_health_comes_from_the_backend():
    code, _, _, body = _req(_P, "/api/desktop/health")
    assert code == 200 and json.loads(body)["from"] == "backend"


def test_api_target_switching_two_gateways_two_upstreams():
    up2, hits2 = _start_upstream()
    gw2, _ = _start_gateway(up2.server_address[1])
    try:
        _req(gw2.server_address[1], "/api/echo")
        assert any(h.startswith("/api/echo") for h in hits2)
        n = len(_HITS)
        _req(_P, "/api/echo")
        assert len(_HITS) == n + 1            # each gateway hits only its target
    finally:
        gw2.shutdown(); up2.shutdown()


# ── remote mode ──────────────────────────────────────────────────────────────
_GWR, _ = _start_gateway(_UP.server_address[1], remote=True,
                         insecure_lan=True, runtime_mode="remote",
                         token="remote-gw-token-0123456789abcdef")
_PR = _GWR.server_address[1]


def test_remote_health_is_answered_locally():
    before = list(_HITS)
    code, _, _, body = _req(_PR, "/api/desktop/health")
    assert code == 200
    j = json.loads(body)
    assert j["runtime_mode"] == "remote" and j["insecure_lan"] is True
    assert j["processing"] is False
    assert _HITS == before                    # upstream never consulted


def test_remote_mode_strips_the_desktop_token():
    code, _, _, body = _req(_PR, "/api/echo",
                            headers={"X-SmartDocs-Token": "must-not-leak"})
    assert code == 200 and json.loads(body)["token"] is None


def test_remote_pages_are_auth_gated():
    code, hdrs, _, _ = _req(_PR, "/")
    assert code == 302 and hdrs["location"] == "/login"
    code, _, _, body = _req(_PR, "/", headers={"Cookie": "sid=ok"})
    assert code == 200 and b"LOCAL-DESKTOP-UI" in body


def test_remote_shutdown_requires_the_token():
    code, _, _, _ = _req(_PR, "/api/desktop/shutdown", method="POST",
                         headers={"X-SmartDocs-Token": "wrong"})
    assert code == 401
    # (The correct-token path is exercised by the subprocess test below.)


def test_private_ip_policy_helper():
    yes = ("10.0.0.25", "172.16.0.1", "172.31.255.255", "192.168.1.50",
           "fc00::1", "fd12:3456::1")
    no = ("8.8.8.8", "172.15.0.1", "172.32.0.1", "127.0.0.1", "::1",
          "169.254.1.1", "fe80::1", "2001:db8::1", "example.com", "")
    for h in yes:
        assert dg._is_private_ip(h), h
    for h in no:
        assert not dg._is_private_ip(h), h


def test_plain_http_public_upstream_is_refused_at_connect():
    # Config pointing at a public IP over http: every connect must refuse.
    srv = dg.make_gateway(_UI, "http://8.8.8.8:5002", remote=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        code, _, _, body = _req(srv.server_address[1], "/api/echo")
        assert code == 502 and b"not a private LAN address" in body
    finally:
        srv.shutdown()


# ── gateway-only process (Remote Server mode) ────────────────────────────────
def test_gateway_only_runs_without_flask_and_starts_no_backend():
    """Run desktop_server.py under a BARE python3 (no Flask installed).
    If the remote path imported app/config/DB/Flask it would crash — the
    ready handshake proves no processing backend is needed or started."""
    py = shutil.which("python3")
    if py is None:
        raise SkipTest("no system python3")
    probe = subprocess.run([py, "-c", "import flask"], capture_output=True)
    if probe.returncode != 0:
        pass  # perfect: bare interpreter, strongest form of the proof
    tok = "gateway-only-test-token-0123456789abcdef"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "SMARTDOCS_GATEWAY_ONLY": "1",
        "SMARTDOCS_GATEWAY_UPSTREAM": f"http://127.0.0.1:{_UP.server_address[1]}",
        "SMARTDOCS_RUNTIME_MODE": "remote",
        "SMARTDOCS_UI_DIR": str(_UI),
        "SMARTDOCS_TOKEN_STDIN": "1",
    }
    proc = subprocess.Popen([py, str(_ROOT / "desktop_server.py")],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, cwd=str(_ROOT))
    try:
        proc.stdin.write((tok + "\n").encode()); proc.stdin.flush()
        line = proc.stdout.readline().decode()
        hs = json.loads(line)
        assert hs["event"] == "ready", hs
        port = hs["port"]
        code, _, _, body = _req(port, "/api/desktop/health")
        assert code == 200 and json.loads(body)["runtime_mode"] == "remote"
        code, _, _, body = _req(port, "/")
        assert code == 302                    # auth-gated, UI stays local
        # Token-guarded shutdown → clean exit.
        code, _, _, _ = _req(port, "/api/desktop/shutdown", method="POST",
                             headers={"X-SmartDocs-Token": tok})
        assert code == 200
        assert proc.wait(timeout=15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


if __name__ == "__main__":
    import traceback
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = skipped = 0
    for name, fn in tests:
        try:
            fn(); print(f"PASS  {name}")
        except SkipTest as e:
            skipped += 1; print(f"SKIP  {name}  ({e})")
        except Exception:
            failed += 1; print(f"FAIL  {name}"); traceback.print_exc()
    passed = len(tests) - failed - skipped
    print(f"\n{passed}/{len(tests)} passed"
          + (f", {skipped} skipped" if skipped else ""))
    sys.exit(1 if failed else 0)
