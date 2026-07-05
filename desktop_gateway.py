"""SmartDocs desktop UI gateway — stdlib-only local HTTP host + API proxy.

The DesktopApp WebView always points at THIS server (127.0.0.1, dynamic
port), in every runtime mode. It:

  • serves the DesktopApp's own frontend (index.html, agent.html, /static/*)
    from the bundled read-only assets — so the Desktop UI never changes when
    the backend target changes, and Remote-Server mode never shows the remote
    WebApp's HTML interface;
  • proxies ONLY the known SmartDocs routes (API, authentication, admin
    pages, uploads/downloads/streaming/citations/artifacts are all under
    /api/) to the selected backend — it is an allowlist, not an open proxy;
  • streams request and response bodies unbuffered (uploads, downloads, SSE);
  • never follows upstream redirects: Location headers pointing at the
    upstream origin are rewritten back to this gateway's origin, anything
    else is passed through for the WebView's navigation allowlist to refuse;
  • rewrites proxied Set-Cookie headers (drops Domain/Secure) so sessions
    bind to the local gateway origin the WebView actually uses;
  • in remote mode: answers /api/desktop/health locally, strips the desktop
    launch token before anything leaves the machine, auth-gates page loads
    via the upstream /api/auth/me (302 → /login when signed out), and
    re-verifies a private-LAN upstream IP before every connection.

Modes of use:
  • bundled/external backends: desktop_server.py runs make_gateway() in a
    thread next to the Flask backend, upstream = http://127.0.0.1:<backend>.
  • remote servers: run_gateway_only() is the WHOLE process (entered from
    desktop_server.py before any Flask/app/DB import — no OCR, LLM, GLM,
    database or document-processing service can start on this path).

No Flask, no third-party imports — stdlib only.
"""

import ipaddress
import json
import mimetypes
import os
import socket
import ssl
import sys
import threading
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

GATEWAY_VERSION = "gateway-1"

# Route allowlist. /api/ covers uploads, downloads, streaming, citations,
# artifacts, settings, agent runs; /login + /logout are the authentication
# pages; /admin/ is the server-rendered admin console; /desktop/boot is the
# local-mode cookie bootstrap. NOTHING else is ever forwarded upstream.
PROXY_PREFIXES = ("/api/", "/admin/")
PROXY_EXACT = ("/login", "/logout", "/admin")
LOCAL_ONLY_PROXY = ("/desktop/boot",)          # meaningless against a remote

# Hop-by-hop headers (RFC 7230 §6.1) never forwarded in either direction.
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "proxy-connection",
}

_CHUNK = 64 * 1024
_CONNECT_TIMEOUT = 10


def _is_private_ip(host):
    """RFC1918 IPv4 or IPv6 unique-local (fc00::/7) — IP literals only."""
    h = host.strip("[]")
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv4Address):
        return ip.is_private and not ip.is_loopback and not ip.is_link_local
    return ip in ipaddress.ip_network("fc00::/7")


def _host_of(header_value):
    """Host header → bare hostname (handles IPv6 brackets and :port)."""
    v = (header_value or "").strip()
    if v.startswith("["):
        return v[1:v.find("]")] if "]" in v else v.strip("[]")
    return v.split(":")[0]


class GatewayConfig:
    """Everything the handler needs, resolved once at startup."""

    def __init__(self, ui_dir, upstream, *, remote=False, insecure_lan=False,
                 runtime_mode="bundled", token=None):
        self.ui_dir = Path(ui_dir).resolve()
        u = urlsplit(upstream)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError(f"invalid upstream URL: {upstream!r}")
        self.scheme = u.scheme
        self.host = u.hostname
        self.port = u.port or (443 if u.scheme == "https" else 80)
        self.netloc = u.netloc
        self.remote = remote
        self.insecure_lan = insecure_lan
        self.runtime_mode = runtime_mode
        self.token = token                  # remote mode: guards /api/desktop/shutdown
        # Origin prefixes rewritten in Location headers back to the gateway.
        self.upstream_origins = {f"{self.scheme}://{self.netloc}"}
        default = 443 if u.scheme == "https" else 80
        if u.port == default or u.port is None:
            host_part = f"[{self.host}]" if ":" in self.host else self.host
            self.upstream_origins.add(f"{self.scheme}://{host_part}")
            self.upstream_origins.add(f"{self.scheme}://{host_part}:{default}")


def _token_equal(a, b):
    if not a or not b or len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SmartDocsGateway"
    cfg = None                                          # set by make_gateway

    # ── plumbing ─────────────────────────────────────────────────────────────
    def log_message(self, fmt, *args):                  # quiet by default
        if os.environ.get("SMARTDOCS_GATEWAY_LOG"):
            sys.stderr.write("[gateway] " + (fmt % args) + "\n")

    def _send_simple(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, code, obj):
        self._send_simple(code, json.dumps(obj))

    # ── request entry ────────────────────────────────────────────────────────
    def _handle(self):
        # DNS-rebinding guard: only local host names reach the gateway.
        host = _host_of(self.headers.get("Host", "")).lower()
        if host not in ("127.0.0.1", "localhost", "::1"):
            return self._json(403, {"success": False, "error": "Forbidden host"})

        path = self.path.split("?", 1)[0]

        # Gateway-local endpoints (remote mode: there is no local backend).
        if self.cfg.remote and path == "/api/desktop/health":
            return self._json(200, {
                "status": "ok", "version": GATEWAY_VERSION,
                "runtime_mode": self.cfg.runtime_mode,
                "insecure_lan": self.cfg.insecure_lan,
                "processing": False,
            })
        if self.cfg.remote and path == "/api/desktop/shutdown":
            if self.command != "POST":
                return self._json(405, {"success": False, "error": "POST only"})
            tok = self.headers.get("X-SmartDocs-Token", "")
            if not _token_equal(tok, self.cfg.token or ""):
                return self._json(401, {"success": False,
                                        "error": "Desktop token required"})
            threading.Timer(0.3, self.server.shutdown).start()
            return self._json(200, {"success": True, "shutting_down": True})

        # Local Desktop UI (identical in every runtime mode).
        if path in ("/", "/agent"):
            return self._serve_page(path)
        if path.startswith("/static/"):
            return self._serve_static(path[len("/static/"):])
        if path == "/desktop/runtime-settings":
            # Normally intercepted by the shell before the request is made;
            # this fallback keeps the link meaningful anywhere else.
            return self._send_simple(
                200,
                "<!doctype html><meta charset='utf-8'>"
                "<body style='font-family:system-ui;background:#0f1115;"
                "color:#e6e9ef;display:grid;place-items:center;height:100vh'>"
                "<p>Open <b>Backend Runtime…</b> from the application menu "
                "(Cmd/Ctrl+,).</p>",
                ctype="text/html; charset=utf-8")

        # Allowlisted upstream routes.
        allowed = path.startswith(PROXY_PREFIXES) or path in PROXY_EXACT
        if not allowed and not self.cfg.remote and path in LOCAL_ONLY_PROXY:
            allowed = True
        if allowed:
            return self._proxy()

        self._json(404, {"success": False, "error": "Not found"})

    # ── local UI serving ─────────────────────────────────────────────────────
    def _serve_page(self, path):
        # Remote mode: mirror the backend's @login_required page gate so a
        # signed-out user lands on the (proxied) login page instead of a
        # broken SPA. Local modes establish the session via /desktop/boot
        # before the first page load, so no gate is needed there.
        if self.cfg.remote and self.command in ("GET", "HEAD"):
            state = self._upstream_auth_state()
            if state == "unauthenticated":
                self.send_response(302)
                self.send_header("Location", "/login")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if state == "unreachable":
                return self._error_page(
                    "The SmartDocs server is not reachable right now.")
        name = "agent.html" if path == "/agent" else "index.html"
        self._serve_file(self.cfg.ui_dir / name)

    def _serve_static(self, rel):
        base = self.cfg.ui_dir
        target = (base / rel).resolve()
        # Containment check — traversal (“..”, absolute, symlink escape) → 404.
        if base != target and base not in target.parents:
            return self._json(404, {"success": False, "error": "Not found"})
        self._serve_file(target)

    def _serve_file(self, p):
        try:
            data = p.read_bytes()
        except (OSError, ValueError):
            return self._json(404, {"success": False, "error": "Not found"})
        ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",
                                                  "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _error_page(self, msg):
        html = (
            "<!doctype html><meta charset='utf-8'><title>SmartDocs</title>"
            "<body style='font-family:system-ui;background:#0f1115;color:#e6e9ef;"
            "display:grid;place-items:center;height:100vh;text-align:center'>"
            f"<div><p>{msg}</p>"
            "<p><a href='/desktop/runtime-settings' style='color:#4c8bf5'>"
            "Change backend…</a></p></div>"
        )
        self._send_simple(502, html, ctype="text/html; charset=utf-8")

    def _upstream_auth_state(self):
        """'ok' | 'unauthenticated' | 'unreachable' via upstream /api/auth/me."""
        try:
            conn = self._connect()
        except OSError:
            return "unreachable"
        try:
            headers = {"Host": self.cfg.netloc, "Accept": "application/json"}
            cookie = self.headers.get("Cookie")
            if cookie:
                headers["Cookie"] = cookie
            conn.request("GET", "/api/auth/me", headers=headers)
            resp = conn.getresponse()
            resp.read()
            return "ok" if resp.status == 200 else "unauthenticated"
        except OSError:
            return "unreachable"
        finally:
            conn.close()

    # ── proxying ─────────────────────────────────────────────────────────────
    def _connect(self):
        """New upstream connection. Private-LAN HTTP upstreams get their IP
        literal re-verified before every connect (defense in depth; the URL
        policy already rejects non-private destinations)."""
        host, port = self.cfg.host, self.cfg.port
        if self.cfg.scheme == "https":
            ctx = ssl.create_default_context()
            conn = http.client.HTTPSConnection(
                host, port, timeout=_CONNECT_TIMEOUT, context=ctx)
        else:
            local = host in ("127.0.0.1", "localhost", "::1")
            if not local and not _is_private_ip(host):
                raise OSError(f"refusing plain-HTTP upstream {host!r}: "
                              "not a private LAN address")
            conn = http.client.HTTPConnection(host, port,
                                              timeout=_CONNECT_TIMEOUT)
        conn.connect()
        # Long API calls (OCR runs) and SSE streams outlive any sane connect
        # timeout — switch the established socket to blocking reads.
        conn.sock.settimeout(None)
        return conn

    def _proxy(self):
        cfg = self.cfg
        # Request headers: drop hop-by-hop, rewrite Host; in remote mode the
        # desktop launch token never leaves this machine.
        headers = {}
        for k, v in self.headers.items():
            lk = k.lower()
            if lk in _HOP_BY_HOP or lk == "host":
                continue
            if cfg.remote and lk == "x-smartdocs-token":
                continue
            headers[k] = v
        headers["Host"] = cfg.netloc
        headers["Connection"] = "close"

        body = None
        length = self.headers.get("Content-Length")
        if length is not None:
            try:
                n = int(length)
            except ValueError:
                return self._json(400, {"success": False,
                                        "error": "bad Content-Length"})
            body = _BoundedReader(self.rfile, n)
            headers["Content-Length"] = str(n)
        elif (self.headers.get("Transfer-Encoding") or "").lower() == "chunked":
            return self._json(411, {"success": False,
                                    "error": "Length required"})

        try:
            conn = self._connect()
        except OSError as e:
            return self._json(502, {"success": False, "gateway": True,
                                    "error": f"backend unreachable: {e}"})
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
        except OSError as e:
            conn.close()
            return self._json(502, {"success": False, "gateway": True,
                                    "error": f"backend request failed: {e}"})

        try:
            self._relay_response(resp)
        finally:
            conn.close()

    def _relay_response(self, resp):
        cfg = self.cfg
        local_origin = f"http://{self.headers.get('Host', '127.0.0.1')}"

        self.send_response(resp.status, resp.reason)
        has_length = False
        for k, v in resp.getheaders():
            lk = k.lower()
            if lk in _HOP_BY_HOP:
                continue
            if lk == "set-cookie":
                continue                                # handled below
            if lk == "location":
                v = _rewrite_location(v, cfg.upstream_origins, local_origin)
            if lk == "content-length":
                has_length = True
            self.send_header(k, v)
        for c in resp.msg.get_all("Set-Cookie") or []:
            self.send_header("Set-Cookie", _rewrite_cookie(c))

        no_body = (self.command == "HEAD" or resp.status in (204, 304)
                   or 100 <= resp.status < 200)
        if not has_length and not no_body:
            # Unknown length (chunked/EOF upstream): stream, then close.
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if no_body:
            resp.read()
            return
        try:
            while True:
                chunk = resp.read1(_CHUNK)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()                       # SSE: no buffering
        except (BrokenPipeError, ConnectionResetError):
            pass                                         # client went away

    # All methods funnel through the same allowlist + proxy.
    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _handle


class _BoundedReader:
    """File-like over rfile limited to Content-Length bytes (upload relay)."""

    def __init__(self, fp, remaining):
        self.fp = fp
        self.remaining = remaining

    def read(self, n=-1):
        if self.remaining <= 0:
            return b""
        if n is None or n < 0 or n > self.remaining:
            n = self.remaining
        data = self.fp.read(n)
        self.remaining -= len(data)
        return data


def _rewrite_location(value, upstream_origins, local_origin):
    """Absolute redirects to the upstream origin come back to the gateway
    origin; everything else is passed through untouched (the WebView's
    navigation allowlist refuses foreign origins — redirects from a private
    upstream to a public destination are therefore never followed)."""
    for origin in upstream_origins:
        if value == origin or value.startswith(origin + "/"):
            return local_origin + value[len(origin):]
    return value


def _rewrite_cookie(value):
    """Drop Domain (bind to the gateway origin) and Secure (the WebView side
    of the hop is loopback HTTP by design; a remote upstream is still reached
    over TLS). Everything else (Path, HttpOnly, SameSite, …) passes through."""
    parts = [p for p in value.split(";")
             if p.strip().lower() != "secure"
             and not p.strip().lower().startswith("domain=")]
    return ";".join(parts)


def make_gateway(ui_dir, upstream, *, remote=False, insecure_lan=False,
                 runtime_mode="bundled", token=None):
    """Build (but do not run) the gateway server on 127.0.0.1:<dynamic>."""
    cfg = GatewayConfig(ui_dir, upstream, remote=remote,
                        insecure_lan=insecure_lan, runtime_mode=runtime_mode,
                        token=token)
    handler = type("BoundGatewayHandler", (GatewayHandler,), {"cfg": cfg})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    return srv


def run_gateway_only(dm):
    """Remote-mode entry: the entire process is this gateway. Called from
    desktop_server.main() BEFORE any Flask/app/config/DB import — this path
    starts no OCR, LLM, GLM, database or document-processing service.

    `dm` is services.desktop_mode (stdlib-only), passed in for the handshake
    helpers and stdin token reading, keeping this module import-free."""
    upstream = os.environ.get("SMARTDOCS_GATEWAY_UPSTREAM", "").strip()
    if not upstream:
        print(dm.error_handshake("no upstream server configured"), flush=True)
        return 2
    token = dm.read_token()                  # guards the shutdown endpoint
    ui_dir = os.environ.get("SMARTDOCS_UI_DIR", "").strip()
    if not ui_dir:
        frozen = getattr(sys, "_MEIPASS", None)
        base = Path(frozen) if frozen else Path(__file__).resolve().parent
        ui_dir = str(base / "static")
    if not (Path(ui_dir) / "index.html").is_file():
        print(dm.error_handshake(f"desktop UI assets missing at {ui_dir}"),
              flush=True)
        return 2

    try:
        srv = make_gateway(
            ui_dir, upstream, remote=True,
            insecure_lan=os.environ.get("SMARTDOCS_GATEWAY_INSECURE") == "1",
            runtime_mode=os.environ.get("SMARTDOCS_RUNTIME_MODE", "remote"),
            token=token)
    except (ValueError, OSError) as e:
        print(dm.error_handshake(f"gateway failed to start: {e}"), flush=True)
        return 2

    import signal
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_a: threading.Thread(
            target=srv.shutdown, daemon=True).start())

    print(dm.ready_handshake(srv.server_address[1], os.getpid(),
                             GATEWAY_VERSION), flush=True)
    srv.serve_forever()
    srv.server_close()
    return 0
