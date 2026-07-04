"""Settings backend tests (UI items 1/2): OS-credential-store key handling with
a FAKE keyring module (masking, save/load/update/remove, env precedence,
redaction), connection testing against a real local HTTP server, and the
persisted non-secret privacy settings (allow_cloud / cloud_ack / env lock).

Runs under pytest OR standalone (`python agent/tests/test_settings_backend.py`).
"""

import json
import os
import pathlib
import socket
import sys
import tempfile
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import pytest  # noqa: F401
except ImportError:
    pytest = None


# ── fake keyring module (installed BEFORE secret_store touches it) ────────────
class _FakeBackend:
    pass


def _install_fake_keyring(store=None, fail=False):
    kr = types.ModuleType("keyring")
    kr._store = store if store is not None else {}

    class _FailBackend:                       # name contains "fail" → unavailable
        pass

    def get_keyring():
        return _FailBackend() if fail else _FakeBackend()

    def set_password(service, name, value):
        kr._store[(service, name)] = value

    def get_password(service, name):
        return kr._store.get((service, name))

    def delete_password(service, name):
        if (service, name) not in kr._store:
            raise RuntimeError("no such secret")
        del kr._store[(service, name)]

    kr.get_keyring = get_keyring
    kr.set_password = set_password
    kr.get_password = get_password
    kr.delete_password = delete_password
    sys.modules["keyring"] = kr
    return kr


_KR = _install_fake_keyring()

from services import secret_store, settings_store  # noqa: E402
from config import cfg  # noqa: E402


def _reset(*vars_):
    """Clear env vars + managed set between tests."""
    for v in vars_ or ("GROQ_API_KEY", "GEMINI_API_KEY"):
        os.environ.pop(v, None)
    secret_store._managed_env.clear()
    _KR._store.clear()


# ── masking / redaction ───────────────────────────────────────────────────────
def test_mask_never_reveals_key():
    assert secret_store.mask("") == ""
    assert secret_store.mask(None) == ""
    assert secret_store.mask("ab") == "••••"
    assert secret_store.mask("abcd") == "••••"
    m = secret_store.mask("gsk_super_secret_value_1234")
    assert m == "••••1234"
    assert "secret" not in m and "gsk_" not in m


def test_provider_status_is_fully_redacted():
    _reset()
    secret_store.set_key("groq", "gsk_totally_secret_ABCD")
    status = secret_store.provider_status("groq")
    blob = json.dumps(status)
    assert "gsk_totally_secret_ABCD" not in blob
    assert status["configured"] is True and status["masked"] == "••••ABCD"
    assert status["source"] == "keyring"
    _reset()


# ── save / load / update / remove ─────────────────────────────────────────────
def test_set_get_update_delete_roundtrip():
    _reset()
    secret_store.set_key("groq", "key-one")
    assert secret_store.get_key("groq") == "key-one"
    assert os.environ.get("GROQ_API_KEY") == "key-one"     # mirrored for chains
    secret_store.set_key("groq", "key-two")                # update
    assert secret_store.get_key("groq") == "key-two"
    assert os.environ.get("GROQ_API_KEY") == "key-two"
    secret_store.delete_key("groq")
    assert secret_store.get_key("groq") is None
    assert "GROQ_API_KEY" not in os.environ               # managed var removed
    secret_store.delete_key("groq")                        # missing → no-op
    _reset()


def test_env_var_always_wins_and_is_never_clobbered():
    _reset()
    os.environ["GROQ_API_KEY"] = "env-key"                 # external config
    _KR._store[("SmartDocs", "GROQ_API_KEY")] = "keyring-key"
    assert secret_store.get_key("groq") == "env-key"
    assert secret_store.key_source("groq") == "env"
    secret_store.set_key("groq", "new-keyring-key")        # stored, env untouched
    assert os.environ["GROQ_API_KEY"] == "env-key"
    secret_store.delete_key("groq")                        # env survives removal
    assert os.environ["GROQ_API_KEY"] == "env-key"
    _reset()


def test_load_into_env_on_startup():
    _reset()
    _KR._store[("SmartDocs", "GEMINI_API_KEY")] = "stored-gem"
    os.environ["GROQ_API_KEY"] = "env-groq"                # external — untouched
    n = secret_store.load_into_env()
    assert n == 1
    assert os.environ["GEMINI_API_KEY"] == "stored-gem"
    assert os.environ["GROQ_API_KEY"] == "env-groq"
    assert secret_store.key_source("gemini") == "keyring"
    _reset()


def test_set_key_validates_and_needs_keyring():
    _reset()
    for bad in ("nope", ""):
        try:
            secret_store.set_key(bad, "k") if bad else secret_store.set_key("groq", "")
        except ValueError:
            pass
        else:
            raise AssertionError(f"must reject {bad!r}")
    _install_fake_keyring(fail=True)                       # fail backend
    try:
        secret_store.set_key("groq", "k")
    except RuntimeError as e:
        assert "unavailable" in str(e)
    else:
        raise AssertionError("fail backend must raise RuntimeError")
    finally:
        _install_fake_keyring(store=_KR._store)            # restore working fake
    ok, name = secret_store.keyring_available()
    assert ok is True and "_FakeBackend" in name
    _reset()


# ── connection testing (real local HTTP; key never in the response) ──────────
class _FakeProviderAPI(BaseHTTPRequestHandler):
    behavior = 200

    def do_GET(self):
        code = type(self).behavior
        self.send_response(code)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


def _serve():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = HTTPServer(("127.0.0.1", port), _FakeProviderAPI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}/models"


def test_connection_test_states():
    _reset()
    srv, url = _serve()
    old = dict(secret_store.TEST_URLS)
    secret_store.TEST_URLS.update({"groq": url, "gemini": url})
    try:
        assert secret_store.test_key("groq")["state"] == "not_configured"
        _FakeProviderAPI.behavior = 200
        assert secret_store.test_key("groq", "typed-key")["state"] == "connected"
        _FakeProviderAPI.behavior = 401
        assert secret_store.test_key("groq", "bad-key")["state"] == "invalid"
        _FakeProviderAPI.behavior = 500
        assert secret_store.test_key("gemini", "k")["state"] == "error"
        secret_store.TEST_URLS["groq"] = "http://127.0.0.1:1/models"
        res = secret_store.test_key("groq", "k")
        assert res["state"] == "error" and "k" not in json.dumps(res)
        assert secret_store.test_key("nope", "k")["state"] == "error"
    finally:
        secret_store.TEST_URLS.update(old)
        srv.shutdown()
    _reset()


# ── persisted non-secret settings (privacy toggle + ack) ─────────────────────
def _tmp_settings():
    return pathlib.Path(tempfile.mkdtemp(prefix="sdset-")) / "app_settings.json"


def test_allow_cloud_persist_roundtrip_and_runtime_apply():
    p = _tmp_settings()
    saved = (cfg.ALLOW_CLOUD, os.environ.get("ALLOW_CLOUD"),
             os.environ.get("_ALLOW_CLOUD_MANAGED"))
    os.environ.pop("ALLOW_CLOUD", None)
    os.environ.pop("_ALLOW_CLOUD_MANAGED", None)
    try:
        assert settings_store.get_allow_cloud(p) is None    # never toggled
        settings_store.set_allow_cloud(False, p)
        assert settings_store.get_allow_cloud(p) is False
        assert cfg.ALLOW_CLOUD is False                     # applied live
        assert os.environ["ALLOW_CLOUD"] == "false"         # provider layer agrees
        from agent.core.provider import cloud_allowed
        assert cloud_allowed() is False
        settings_store.set_allow_cloud(True, p)
        assert cfg.ALLOW_CLOUD is True and cloud_allowed() is True
        # The file never contains anything secret-shaped — just the two flags.
        data = json.loads(p.read_text())
        assert set(data) <= {"allow_cloud", "cloud_ack"}
    finally:
        cfg.ALLOW_CLOUD = saved[0]
        for var, val in (("ALLOW_CLOUD", saved[1]), ("_ALLOW_CLOUD_MANAGED", saved[2])):
            os.environ.pop(var, None)
            if val is not None:
                os.environ[var] = val


def test_allow_cloud_env_locked_refuses_ui_toggle():
    p = _tmp_settings()
    saved = os.environ.get("ALLOW_CLOUD")
    os.environ["ALLOW_CLOUD"] = "true"                      # external / .env
    os.environ.pop("_ALLOW_CLOUD_MANAGED", None)
    try:
        assert settings_store.env_allow_cloud_is_explicit() is True
        try:
            settings_store.set_allow_cloud(False, p)
        except ValueError as e:
            assert ".env" in str(e)
        else:
            raise AssertionError("env-locked toggle must be refused")
    finally:
        os.environ.pop("ALLOW_CLOUD", None)
        if saved is not None:
            os.environ["ALLOW_CLOUD"] = saved


def test_cloud_ack_roundtrip_and_apply_persisted():
    p = _tmp_settings()
    saved = (cfg.ALLOW_CLOUD, os.environ.get("ALLOW_CLOUD"))
    os.environ.pop("ALLOW_CLOUD", None)
    os.environ.pop("_ALLOW_CLOUD_MANAGED", None)
    try:
        assert settings_store.get_cloud_ack(p) is False
        settings_store.set_cloud_ack(p)
        assert settings_store.get_cloud_ack(p) is True
        settings_store.set_allow_cloud(False, p)
        cfg.ALLOW_CLOUD = True                              # simulate fresh boot
        settings_store.apply_persisted_settings(p)          # overlay persisted
        assert cfg.ALLOW_CLOUD is False
    finally:
        cfg.ALLOW_CLOUD = saved[0]
        os.environ.pop("ALLOW_CLOUD", None)
        os.environ.pop("_ALLOW_CLOUD_MANAGED", None)
        if saved[1] is not None:
            os.environ["ALLOW_CLOUD"] = saved[1]


def test_corrupt_settings_file_falls_back_to_defaults():
    p = _tmp_settings()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert settings_store.get_allow_cloud(p) is None
    assert settings_store.get_cloud_ack(p) is False


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
