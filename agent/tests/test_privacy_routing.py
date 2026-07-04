"""Privacy (Local only, review P7) + provider routing (review P8) tests for the
services: translation engine=auto, AI rewrite backends, and Document QA (chat)
inference routing. Heavy backends are replaced with fakes; the OpenAI-compatible
endpoint is a REAL local HTTP server speaking the chat-completions shape, so the
provider request path (URL composition, headers, JSON) is exercised end to end.

Runs under pytest OR standalone (`python agent/tests/test_privacy_routing.py`).
"""

import json
import pathlib
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import pytest  # noqa: F401
except ImportError:
    pytest = None

import os  # noqa: E402

from config import cfg  # noqa: E402
from services import translate_service, ai_rewrite_service, chat_service  # noqa: E402
from services.ai_rewrite_service import NoAIAvailableError  # noqa: E402


# ── fake OpenAI-compatible endpoint (real local HTTP) ─────────────────────────
class _FakeOpenAIHandler(BaseHTTPRequestHandler):
    answer = "A rewritten local answer."
    requests_seen = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        type(self).requests_seen.append(
            {"path": self.path, "body": json.loads(body or b"{}"),
             "auth": self.headers.get("Authorization")})
        payload = json.dumps(
            {"choices": [{"message": {"content": type(self).answer}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):                     # keep test output clean
        pass


def _start_fake_openai():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = HTTPServer(("127.0.0.1", port), _FakeOpenAIHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}"


_SRV, _OC_URL = _start_fake_openai()


def _set_env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    for k, v in kv.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    def restore():
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return restore


def _set_attrs(obj, **kv):
    old = {k: getattr(obj, k) for k in kv}
    for k, v in kv.items():
        setattr(obj, k, v)

    def restore():
        for k, v in old.items():
            setattr(obj, k, v)
    return restore


# ── translation: engine=auto vs Local only ────────────────────────────────────
def _translate_with_fakes(engine, allow_cloud):
    calls = {"online": 0, "offline": 0}

    def fake_online(text, f, t):
        calls["online"] += 1
        return "ONLINE:" + text

    def fake_offline(text, f, t):
        calls["offline"] += 1
        return "OFFLINE:" + text

    r1 = _set_attrs(translate_service,
                    _translate_online=fake_online,
                    _translate_offline=fake_offline,
                    check_online_available=lambda timeout=2.0: True)
    r2 = _set_attrs(cfg, ALLOW_CLOUD=allow_cloud)
    try:
        res = translate_service.translate("hello", "en", "vi", engine=engine)
        return res, calls
    finally:
        r1(); r2()


def test_translate_auto_uses_online_when_cloud_allowed():
    res, calls = _translate_with_fakes("auto", allow_cloud=True)
    assert res["engine_used"] == "online" and res["translated"] == "ONLINE:hello"
    assert calls == {"online": 1, "offline": 0}


def test_translate_auto_forced_offline_in_local_only():
    # Local only: auto resolves to offline — the online API is never touched
    # (no connectivity probe, no request), even though it would be reachable.
    res, calls = _translate_with_fakes("auto", allow_cloud=False)
    assert res["engine_used"] == "offline" and res["translated"] == "OFFLINE:hello"
    assert calls == {"online": 0, "offline": 1}


def test_translate_explicit_online_rejected_in_local_only():
    try:
        _translate_with_fakes("online", allow_cloud=False)
    except RuntimeError as e:
        assert "Local-only" in str(e)
    else:
        raise AssertionError("engine=online must be rejected in Local-only mode")


def test_translate_explicit_offline_unaffected_by_local_only():
    res, calls = _translate_with_fakes("offline", allow_cloud=False)
    assert res["engine_used"] == "offline" and calls["online"] == 0


def test_translate_status_reports_local_only_without_probing():
    # The engine-status probe (drives the UI badge/pills) must report online as
    # unavailable BY POLICY in Local-only mode — and must not even probe
    # connectivity (nothing may leave the machine).
    calls = {"online": 0}

    def fake_online_check(timeout=5.0):
        calls["online"] += 1
        return True

    r1 = _set_attrs(translate_service,
                    check_online_available=fake_online_check,
                    check_offline_available=lambda: True,
                    _get_installed_pairs=lambda: [("en", "vi")])
    r2 = _set_attrs(cfg, ALLOW_CLOUD=False,
                    _argos_installed_pairs=lambda: [])
    try:
        s = translate_service.get_engine_status(force=True)
        assert s["local_only"] is True and s["online"] is False
        assert calls["online"] == 0                       # no probe went out
        assert s["offline"] is True                       # offline unaffected
        r2()
        r2 = _set_attrs(cfg, ALLOW_CLOUD=True,
                        _argos_installed_pairs=lambda: [])
        s = translate_service.get_engine_status(force=True)
        assert s["local_only"] is False and s["online"] is True
        assert calls["online"] == 1                       # probed when allowed
    finally:
        r1(); r2()
        translate_service._status_cache = {}              # don't poison later reads


# ── AI rewrite: backend order + Local only gate (P7/P8) ───────────────────────
def _no_local(*a, **k):
    raise NoAIAvailableError("no local model (test)")


def test_rewrite_run_api_gated_in_local_only():
    # Keys are set, but Local only must fail the implicit-cloud path BEFORE any
    # network call — same error type as "no keys" (extractive-fallback contract).
    re_env = _set_env(GROQ_API_KEY="gk", OPENAI_API_KEY=None, OPENROUTER_API_KEY=None)
    rc = _set_attrs(cfg, ALLOW_CLOUD=False)
    try:
        ai_rewrite_service._run_api(["some sentence"], "short", "english")
    except NoAIAvailableError as e:
        assert "Local-only" in str(e)
    else:
        raise AssertionError("_run_api must raise NoAIAvailableError in Local-only")
    finally:
        re_env(); rc()


def test_rewrite_cloud_only_config_uses_endpoint_without_local_model():
    # LLM_PROVIDER=openai_compatible + endpoint configured + NO local model:
    # the endpoint answers (P8) — first in the backend order, so no local wait.
    _FakeOpenAIHandler.requests_seen.clear()
    re_env = _set_env(OPENAI_COMPATIBLE_BASE_URL=_OC_URL,
                      OPENAI_COMPATIBLE_MODEL="test-model",
                      OPENAI_COMPATIBLE_API_KEY="sk-t")
    ra = _set_attrs(ai_rewrite_service, _run_local=_no_local)
    rc = _set_attrs(cfg, LLM_PROVIDER="openai_compatible", ALLOW_CLOUD=True)
    try:
        text, engine = ai_rewrite_service.ai_rewrite(["Sentence one."], "short")
        assert text == "A rewritten local answer."
        assert engine == "ai_api:openai-compatible:test-model"
        req = _FakeOpenAIHandler.requests_seen[-1]
        assert req["path"] == "/v1/chat/completions"
        assert req["body"]["model"] == "test-model"
        assert req["auth"] == "Bearer sk-t"
    finally:
        re_env(); ra(); rc()


def test_rewrite_local_first_by_default():
    re_env = _set_env(OPENAI_COMPATIBLE_BASE_URL=_OC_URL,
                      OPENAI_COMPATIBLE_MODEL="test-model")
    ra = _set_attrs(ai_rewrite_service,
                    _run_local=lambda s, st, lg: ("Local rewrite.", "ai_local:cpu"))
    rc = _set_attrs(cfg, LLM_PROVIDER="local_hf", ALLOW_CLOUD=True)
    try:
        text, engine = ai_rewrite_service.ai_rewrite(["Sentence one."], "short")
        assert (text, engine) == ("Local rewrite.", "ai_local:cpu")
    finally:
        re_env(); ra(); rc()


def test_rewrite_local_unavailable_falls_back_to_endpoint():
    # Default provider config, local model missing → the self-hosted endpoint
    # is tried BEFORE the implicit cloud APIs (which stay last / gated).
    re_env = _set_env(OPENAI_COMPATIBLE_BASE_URL=_OC_URL,
                      OPENAI_COMPATIBLE_MODEL="test-model",
                      GROQ_API_KEY=None, OPENAI_API_KEY=None, OPENROUTER_API_KEY=None)
    ra = _set_attrs(ai_rewrite_service, _run_local=_no_local)
    rc = _set_attrs(cfg, LLM_PROVIDER="local_hf", ALLOW_CLOUD=False)
    try:
        text, engine = ai_rewrite_service.ai_rewrite(["Sentence one."], "short")
        assert text == "A rewritten local answer."
        assert engine.startswith("ai_api:openai-compatible:")
    finally:
        re_env(); ra(); rc()


def test_rewrite_local_only_no_backends_raises():
    re_env = _set_env(OPENAI_COMPATIBLE_BASE_URL=None, OPENAI_COMPATIBLE_MODEL=None,
                      GROQ_API_KEY="gk", OPENAI_API_KEY=None, OPENROUTER_API_KEY=None)
    ra = _set_attrs(ai_rewrite_service, _run_local=_no_local)
    rc = _set_attrs(cfg, LLM_PROVIDER="local_hf", ALLOW_CLOUD=False)
    try:
        ai_rewrite_service.ai_rewrite(["Sentence one."], "short")
    except NoAIAvailableError:
        pass
    else:
        raise AssertionError("no local, no endpoint, cloud gated → must raise")
    finally:
        re_env(); ra(); rc()


# ── Document QA (chat) inference routing (P8) ─────────────────────────────────
def _local_ok(messages, force_cpu=False):
    return "LOCAL-ANSWER", "chat_local", False


def _local_unavailable(messages, force_cpu=False):
    raise RuntimeError("Chat model unavailable (test)")


def test_chat_local_config_uses_local_model():
    ra = _set_attrs(chat_service, _run_inference=_local_ok)
    rc = _set_attrs(cfg, LLM_PROVIDER="local_hf")
    re_env = _set_env(OPENAI_COMPATIBLE_BASE_URL=None, OPENAI_COMPATIBLE_MODEL=None)
    try:
        res = chat_service.chat("hi", mode="general")
        assert res["answer"] == "LOCAL-ANSWER" and res["engine_used"] == "chat_local"
    finally:
        ra(); rc(); re_env()


def test_chat_cloud_only_config_answers_via_endpoint_without_local_model():
    # LLM_PROVIDER=openai_compatible → Document QA works with NO local model:
    # the local path must not even be attempted.
    def _local_forbidden(messages, force_cpu=False):
        raise AssertionError("local model must not be touched in endpoint mode")
    _FakeOpenAIHandler.requests_seen.clear()
    ra = _set_attrs(chat_service, _run_inference=_local_forbidden)
    rc = _set_attrs(cfg, LLM_PROVIDER="openai_compatible")
    re_env = _set_env(OPENAI_COMPATIBLE_BASE_URL=_OC_URL,
                      OPENAI_COMPATIBLE_MODEL="test-model",
                      OPENAI_COMPATIBLE_API_KEY=None)
    try:
        res = chat_service.chat("what is in my documents?", mode="general")
        assert res["answer"] == "A rewritten local answer."
        assert res["engine_used"] == "openai-compatible:test-model"
        assert res["cancelled"] is False
        req = _FakeOpenAIHandler.requests_seen[-1]
        assert req["auth"] is None                 # no key → no auth header
        assert req["body"]["messages"][-1]["content"] == "what is in my documents?"
    finally:
        ra(); rc(); re_env()


def test_chat_local_unavailable_falls_back_to_endpoint():
    ra = _set_attrs(chat_service, _run_inference=_local_unavailable)
    rc = _set_attrs(cfg, LLM_PROVIDER="local_hf")
    re_env = _set_env(OPENAI_COMPATIBLE_BASE_URL=_OC_URL,
                      OPENAI_COMPATIBLE_MODEL="test-model")
    try:
        res = chat_service.chat("hi", mode="general")
        assert res["answer"] == "A rewritten local answer."
        assert res["engine_used"] == "openai-compatible:test-model"
    finally:
        ra(); rc(); re_env()


def test_chat_local_unavailable_without_endpoint_keeps_error_contract():
    ra = _set_attrs(chat_service, _run_inference=_local_unavailable)
    rc = _set_attrs(cfg, LLM_PROVIDER="local_hf")
    re_env = _set_env(OPENAI_COMPATIBLE_BASE_URL=None, OPENAI_COMPATIBLE_MODEL=None)
    try:
        chat_service.chat("hi", mode="general")
    except RuntimeError as e:
        assert "unavailable" in str(e)             # the original error, unchanged
    else:
        raise AssertionError("no local model + no endpoint must still raise")
    finally:
        ra(); rc(); re_env()


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
    _SRV.shutdown()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
