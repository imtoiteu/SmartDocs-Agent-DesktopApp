"""SmartDocs desktop sidecar — the process the Tauri shell owns.

Differences from `python app.py` (the web entry, which is unchanged):
  • binds 127.0.0.1 ONLY, on a dynamically chosen free port (never 0.0.0.0);
  • prints a one-line JSON handshake to stdout when ready (stderr is for logs);
  • requires the per-launch token (X-SmartDocs-Token) on every /api request;
  • authenticates token-bearing requests as an auto-provisioned local desktop
    user (random unusable password) instead of seeding admin/admin123 —
    default credentials on a listening localhost port would defeat the token;
  • adds /api/desktop/health, /api/desktop/session, /api/desktop/shutdown and
    the unauthenticated /desktop/boot bootstrap page;
  • shuts down cleanly on SIGTERM/SIGINT or the shutdown endpoint;
  • refuses to start twice on the same data dir (SingletonLock);
  • never opens a browser.

Run standalone for development (full venv required):
    SMARTDOCS_DESKTOP_TOKEN=$(python3 -c 'import secrets;print(secrets.token_hex(32))') \
    SMARTDOCS_DATA_DIR=~/.local/share/SmartDocs python3 desktop_server.py
"""

import os
import signal
import sys
import threading
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

# stdlib-only; safe before config. Two layouts exist:
#   repo / PyInstaller sidecar  → services/desktop_mode.py
#   desktop-shim (external WebApp runtime: this file + desktop_mode.py are
#   bundled as Tauri resources; `services` resolves to the WebApp's package,
#   which has no desktop_mode) → sibling desktop_mode.py
try:
    from services import desktop_mode as dm
except ImportError:
    import desktop_mode as dm

_BOOT_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>SmartDocs</title></head>
<body style="margin:0;display:grid;place-items:center;height:100vh;
             font-family:system-ui,sans-serif;background:#0f1115;color:#e6e9ef">
<div id="m">Starting SmartDocs…</div>
<script>
(function () {
  var d = window.__SMARTDOCS_DESKTOP__ || {};
  var m = document.getElementById("m");
  if (!d.token) { m.textContent = "Desktop bootstrap failed: no launch token."; return; }
  fetch("/api/desktop/session", { method: "POST",
        headers: { "X-SmartDocs-Token": d.token } })
    .then(function (r) {
      if (r.ok) { location.replace("/"); }
      else { m.textContent = "Desktop session bootstrap failed (" + r.status + ")."; }
    })
    .catch(function () { m.textContent = "SmartDocs backend not reachable."; });
})();
</script></body></html>"""


def _ensure_desktop_user(app):
    """Create (once) and return the id of the local desktop account.

    Random password hash: the account is only ever entered via the launch
    token (request_loader / the boot session), never via the login form.
    """
    import secrets as _secrets
    from werkzeug.security import generate_password_hash
    from models import db, User

    with app.app_context():
        db.create_all()
        u = User.query.filter_by(username="desktop").first()
        if u is None:
            u = User(username="desktop", email="desktop@smartdocs.local",
                     role="admin", is_active=True)
            u.password_hash = generate_password_hash(_secrets.token_hex(32))
            db.session.add(u)
            db.session.commit()
        return u.id


def install_desktop_hooks(app, login_manager, token, shutdown_cb, version):
    from flask import jsonify, request
    from flask_login import login_user
    from models import User

    uid = _ensure_desktop_user(app)

    @login_manager.request_loader
    def _desktop_token_user(req):
        if dm.token_ok(req.headers.get(dm.TOKEN_HEADER, ""), token):
            return User.query.get(uid)
        return None

    @app.before_request
    def _desktop_guard():
        if request.method == "OPTIONS":
            return None
        # DNS-rebinding hardening: only local host names reach the app.
        host = (request.host or "").split(":")[0].strip("[]").lower()
        if host not in ("127.0.0.1", "localhost", "::1"):
            return jsonify({"success": False, "error": "Forbidden host"}), 403
        if request.path.startswith("/api/"):
            if not dm.token_ok(request.headers.get(dm.TOKEN_HEADER, ""), token):
                return jsonify({"success": False,
                                "error": "Desktop token required"}), 401
        return None

    @app.route("/desktop/boot")
    def _desktop_boot():                     # unauthenticated, secret-free
        return _BOOT_HTML

    @app.route("/api/desktop/health")
    def _desktop_health():                   # token enforced by _desktop_guard
        return jsonify({
            "status": "ok", "version": version,
            # Which runtime mode the shell launched us in — the UI's top-bar
            # runtime chip reads this (never trusts page-injected state).
            "runtime_mode": os.environ.get("SMARTDOCS_RUNTIME_MODE", "bundled"),
        })

    @app.route("/api/desktop/session", methods=["POST"])
    def _desktop_session():
        # Token already verified by the guard; establish the cookie session so
        # plain page loads (/, /agent, /admin/) and their subresources work.
        login_user(User.query.get(uid), remember=False)
        return jsonify({"success": True})

    @app.route("/api/desktop/shutdown", methods=["POST"])
    def _desktop_shutdown():
        # Small delay so this response reaches the client before the server
        # stops — an immediate shutdown races the response flush and the
        # caller sees a dropped connection instead of the 200.
        threading.Timer(0.3, shutdown_cb).start()
        return jsonify({"success": True, "shutting_down": True})


def main() -> int:
    os.environ[dm.DESKTOP_ENV] = "1"
    os.environ["HOST"] = "127.0.0.1"         # never 0.0.0.0 in desktop mode
    dm.apply_data_dirs()                     # BEFORE config import (mkdirs, caches)

    token = dm.read_token()
    if not token or len(token) < dm.MIN_TOKEN_LEN:
        print(dm.error_handshake("missing or too-short launch token"), flush=True)
        return 2

    root = dm.data_dir() or dm.default_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    lock = dm.SingletonLock(root)
    if not lock.acquire():
        print(dm.error_handshake("another SmartDocs sidecar is already running "
                                 "for this data directory"), flush=True)
        return 3

    try:
        # Heavy import — config resolves paths from the env prepared above.
        from app import app, APP_VERSION, login_manager
        from services import ai_rewrite_service, chat_service
        from werkzeug.serving import make_server

        srv_box = {}

        def shutdown():
            srv = srv_box.get("srv")
            if srv is not None:
                srv.shutdown()

        install_desktop_hooks(app, login_manager, token, shutdown, APP_VERSION)

        srv = make_server("127.0.0.1", 0, app, threaded=True)   # dynamic port
        srv_box["srv"] = srv

        # shutdown() must not run on the main thread: the handler interrupts
        # serve_forever, and BaseServer.shutdown() blocks until that same
        # loop exits — calling it inline deadlocks the process.
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_a: threading.Thread(
                target=shutdown, daemon=True).start())

        # Same background warmups as the web entry (both are best-effort and
        # degrade to no-ops when the optional ML stack isn't bundled).
        try:
            with app.app_context():
                ai_rewrite_service.prewarm()
        except Exception:
            pass
        try:
            chat_service.rebuild_indexes_from_db(app)
        except Exception:
            pass

        print(dm.ready_handshake(srv.server_port, os.getpid(), APP_VERSION),
              flush=True)
        srv.serve_forever()                  # returns after shutdown()
        return 0
    except Exception as exc:                # never leak the token in errors
        print(dm.error_handshake(f"startup failed: {type(exc).__name__}: {exc}"),
              flush=True)
        raise
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
