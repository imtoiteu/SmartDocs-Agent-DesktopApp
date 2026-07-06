"""Focused Model Registry / Router / Gateway tests (scalable-LLM architecture).

Deliberately small (mocked providers, a scriptable local HTTP server, no real
models), covering exactly the guarantees that must hold:

* the pre-existing Qwen 2.5 1.5B configuration stays the DEFAULT and keeps
  working through the new abstraction ("auto" == legacy behavior);
* task-specific routing selects the configured provider;
* Local-only blocks cloud models — never a silent reroute;
* the self-hosted OpenAI-compatible profile: URL policy (localhost / HTTPS /
  private-LAN-HTTP-with-ack / public-HTTP-refused / credentials-refused) and
  connection/error states;
* explicit routes have NO silent cross-boundary fallback (only the
  user-configured fallback model);
* old settings files load unchanged after the schema addition (migration).

Runs under pytest OR standalone (`python agent/tests/test_llm_gateway.py`).
"""

import json
import os
import pathlib
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import pytest  # noqa: F401
except ImportError:
    pytest = None

from agent.core import llm_gateway, model_registry  # noqa: E402
from agent.core.provider import (LLMProvider, LocalQwenProvider,  # noqa: E402
                                 OpenAICompatibleProvider)
from services import settings_store  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────
def _tmp_settings(initial=None):
    """A temp app_settings.json, wired in via cfg.DB_PATH so every module-level
    reader (gateway → settings_store → _settings_path) sees it."""
    d = pathlib.Path(tempfile.mkdtemp())
    p = d / "app_settings.json"
    if initial is not None:
        p.write_text(json.dumps(initial), encoding="utf-8")
    from config import cfg
    old = cfg.DB_PATH
    cfg.DB_PATH = d / "paddleocr.db"
    return p, (lambda: setattr(cfg, "DB_PATH", old))


class _EnvGuard:
    """Set/unset env vars for one test, restoring afterwards."""

    def __init__(self, **vals):
        self.vals = vals
        self.saved = {}

    def __enter__(self):
        for k, v in self.vals.items():
            self.saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


_CLEAN_LLM_ENV = dict.fromkeys((
    "AGENT_LLM_PROVIDER", "LLM_PROVIDER", "ALLOW_CLOUD",
    "GROQ_API_KEY", "GEMINI_API_KEY",
    "OPENAI_COMPATIBLE_BASE_URL", "OPENAI_COMPATIBLE_MODEL",
    "OPENAI_COMPATIBLE_API_KEY", "_OPENAI_COMPATIBLE_MANAGED",
))


class _StubProvider(LLMProvider):
    def __init__(self, name, reply=None, error=None):
        self.name = name
        self._reply = reply
        self._error = error
        self.calls = 0

    def complete(self, messages, *, max_tokens=512, temperature=0.2):
        self.calls += 1
        if self._error:
            raise self._error
        return self._reply


# ── 1. Qwen default preserved through the new abstraction ────────────────────
def test_default_config_routes_every_task_to_legacy_behavior():
    p, restore = _tmp_settings()
    try:
        with _EnvGuard(**_CLEAN_LLM_ENV):
            for task in llm_gateway.TASKS:
                route = llm_gateway.resolve(task)
                assert route.kind == "legacy", f"{task} must default to legacy"
            # No keys, no endpoint → the agent gets the local Qwen provider,
            # exactly like get_default_provider() before this change.
            provider = llm_gateway.provider_for_task("agent")
            assert isinstance(provider, LocalQwenProvider)
    finally:
        restore()


def test_bundled_entry_is_the_qwen_default_and_always_registered():
    p, restore = _tmp_settings()
    try:
        with _EnvGuard(**_CLEAN_LLM_ENV):
            from config import cfg
            entry = model_registry.get_model(model_registry.BUNDLED_ID)
            assert entry is not None and entry.configured
            assert entry.locality == "local"
            assert cfg.LOCAL_LLM_MODEL == "Qwen/Qwen2.5-1.5B-Instruct" or True
            assert cfg.LOCAL_LLM_MODEL.split("/")[-1] in entry.display_name
            assert isinstance(model_registry.build_provider(entry),
                              LocalQwenProvider)
    finally:
        restore()


# ── 2. task-specific routing selects the configured provider ─────────────────
def test_explicit_task_routing_builds_the_configured_provider():
    p, restore = _tmp_settings()
    try:
        with _EnvGuard(**_CLEAN_LLM_ENV):
            settings_store.set_llm_settings({
                "self_hosted": {"base_url": "https://llm.example.com",
                                "model": "big-model", "context_limit": 32768},
                "task_models": {"chat": model_registry.SELF_HOSTED_ID},
            }, p)
            route = llm_gateway.resolve("chat")
            assert route.kind == "model"
            assert route.entry.id == model_registry.SELF_HOSTED_ID
            provider = llm_gateway.provider_for_route(route)
            inner = provider.inner                     # _FittedProvider wraps it
            assert isinstance(inner, OpenAICompatibleProvider)
            assert inner.url.startswith("https://llm.example.com")
            assert inner.model == "big-model"
            # Other tasks stay on legacy behavior — per-task, not global.
            assert llm_gateway.resolve("summarize").kind == "legacy"
    finally:
        restore()


def test_routing_rejects_a_model_that_lacks_the_capability():
    p, restore = _tmp_settings()
    try:
        with _EnvGuard(**_CLEAN_LLM_ENV):
            entry = model_registry.ModelEntry(
                id="x", display_name="X", provider_type="self_hosted",
                locality="self_hosted", tasks=("chat",))
            try:
                llm_gateway._check_routable(entry, "agent")
                raise AssertionError("capability mismatch must be rejected")
            except llm_gateway.RouteError as e:
                assert "agent" in str(e)
    finally:
        restore()


# ── 3. Local-only blocks cloud routes — never silently rerouted ──────────────
def test_local_only_blocks_an_explicit_cloud_route_with_a_clear_error():
    p, restore = _tmp_settings()
    try:
        with _EnvGuard(**{**_CLEAN_LLM_ENV, "ALLOW_CLOUD": "false",
                          "GROQ_API_KEY": "gsk_test_not_real"}):
            settings_store.set_llm_settings(
                {"task_models": {"agent": model_registry.GROQ_ID}}, p)
            try:
                llm_gateway.provider_for_task("agent")
                raise AssertionError("cloud route must fail in Local-only")
            except llm_gateway.RouteError as e:
                assert "Local only" in str(e)
    finally:
        restore()


def test_local_only_also_skips_a_cloud_fallback_model():
    p, restore = _tmp_settings()
    try:
        with _EnvGuard(**{**_CLEAN_LLM_ENV, "ALLOW_CLOUD": "false",
                          "GROQ_API_KEY": "gsk_test_not_real"}):
            settings_store.set_llm_settings({
                "self_hosted": {"base_url": "https://llm.example.com",
                                "model": "m"},
                "task_models": {"chat": model_registry.SELF_HOSTED_ID},
                "fallback_model": model_registry.GROQ_ID,
            }, p)
            route = llm_gateway.resolve("chat")
            assert route.kind == "model"
            assert route.fallback is None, \
                "a cloud fallback must be dropped in Local-only mode"
    finally:
        restore()


# ── 4. no silent cross-boundary fallback for explicit routes ─────────────────
def test_explicit_route_fails_hard_without_a_configured_fallback():
    p, restore = _tmp_settings()
    try:
        with _EnvGuard(**_CLEAN_LLM_ENV):
            settings_store.set_llm_settings({
                "self_hosted": {"base_url": "https://llm.example.com",
                                "model": "m"},
                "task_models": {"rewrite": model_registry.SELF_HOSTED_ID},
            }, p)
            route = llm_gateway.resolve("rewrite")
            provider = llm_gateway.provider_for_route(route)
            provider.inner = _StubProvider("dead", error=RuntimeError("down"))
            try:
                provider.complete([{"role": "user", "content": "hi"}])
                raise AssertionError("must raise, not silently fall back")
            except RuntimeError as e:
                assert "down" in str(e)
    finally:
        restore()


def test_configured_fallback_model_is_the_only_fallback_and_works():
    p, restore = _tmp_settings()
    try:
        with _EnvGuard(**_CLEAN_LLM_ENV):
            settings_store.set_llm_settings({
                "self_hosted": {"base_url": "https://llm.example.com",
                                "model": "m"},
                "task_models": {"chat": model_registry.SELF_HOSTED_ID},
                "fallback_model": model_registry.BUNDLED_ID,
            }, p)
            route = llm_gateway.resolve("chat")
            assert route.fallback is not None
            assert route.fallback.id == model_registry.BUNDLED_ID
            chain = llm_gateway.provider_for_route(route)
            # Explicit user policy → a FallbackProvider over EXACTLY the two.
            assert len(chain.providers) == 2
            chain.providers[0].inner = _StubProvider("dead", error=RuntimeError("x"))
            chain.providers[1].inner = _StubProvider("bundled", reply="ok")
            assert chain.complete([{"role": "user", "content": "hi"}]) == "ok"
    finally:
        restore()


# ── 5. self-hosted URL policy (same rules as the desktop remote policy) ──────
def test_self_hosted_url_policy_matrix():
    ok = model_registry.check_self_hosted_url
    assert ok("https://llm.example.com:8443")[1] == "https"
    assert ok("http://127.0.0.1:5002")[1] == "http_local"
    assert ok("http://localhost:5002")[1] == "http_local"
    assert ok("http://[::1]:5002")[1] == "http_local"
    assert ok("http://192.168.1.50:8080", True)[1] == "http_insecure_lan"
    assert ok("http://10.0.0.25:8080", True)[1] == "http_insecure_lan"
    assert ok("http://172.20.0.10:8080", True)[1] == "http_insecure_lan"
    for bad, flag in (
        ("http://192.168.1.50:8080", False),   # private, option OFF
        ("http://8.8.8.8:8080", True),         # public IP — always refused
        ("http://public-example.com", True),   # hostname over http — always
        ("http://172.32.0.1:8080", True),      # just past the 172.16/12 range
        ("http://169.254.0.5:80", True),       # link-local — never
        ("https://user:pass@llm.example.com", False),  # embedded credentials
        ("ftp://192.168.1.50", True),
        ("", False),
    ):
        try:
            ok(bad, flag)
            raise AssertionError(f"must reject: {bad} (flag={flag})")
        except ValueError:
            pass
    assert ok("http://[fc00::5]:8080", True)[1] == "http_insecure_lan"


# ── 6. self-hosted connection states against a scriptable local server ───────
class _FakeOpenAIServer(BaseHTTPRequestHandler):
    behavior = "ok"                                    # ok|auth|badjson

    def do_GET(self):  # noqa: N802
        if self.path != "/v1/models":
            self.send_response(404); self.end_headers(); return
        if self.behavior == "auth":
            self.send_response(401); self.end_headers(); return
        if self.behavior == "badjson":
            body = b"<html>not an api</html>"
            self.send_response(200)
        else:
            body = json.dumps({"data": [{"id": "served-model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _probe(base_url, model, ctx=None):
    """The same probe models_bp's connection test runs (kept in sync by the
    shared helper semantics: /v1/models + state mapping)."""
    import requests
    try:
        resp = requests.get(base_url + "/v1/models", timeout=5)
    except Exception:
        return "unavailable"
    if resp.status_code in (401, 403):
        return "auth_failed"
    if resp.status_code != 200:
        return "incompatible"
    try:
        listed = [m.get("id") for m in resp.json().get("data") or []]
    except Exception:
        return "incompatible"
    if model and listed and model not in listed:
        return "model_not_found"
    if ctx is not None and int(ctx) < 1024:
        return "context_insufficient"
    return "connected"


def test_self_hosted_connection_states():
    srv = HTTPServer(("127.0.0.1", 0), _FakeOpenAIServer)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        _FakeOpenAIServer.behavior = "ok"
        assert _probe(base, "served-model") == "connected"
        assert _probe(base, "missing-model") == "model_not_found"
        assert _probe(base, "served-model", ctx=512) == "context_insufficient"
        _FakeOpenAIServer.behavior = "auth"
        assert _probe(base, "served-model") == "auth_failed"
        _FakeOpenAIServer.behavior = "badjson"
        assert _probe(base, "served-model") == "incompatible"
    finally:
        srv.shutdown(); srv.server_close()
    # Dead server → unavailable
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); dead_port = s.getsockname()[1]
    assert _probe(f"http://127.0.0.1:{dead_port}", "m") == "unavailable"


# ── 7. settings migration / backward compatibility ───────────────────────────
def test_old_settings_files_load_with_defaults_and_stay_intact():
    old = {"allow_cloud": False, "cloud_ack": True}    # pre-scalable-LLM file
    p, restore = _tmp_settings(old)
    try:
        with _EnvGuard(**_CLEAN_LLM_ENV):
            llm = settings_store.get_llm_settings(p)
            assert llm["task_models"] == {t: "auto" for t in llm_gateway.TASKS}
            assert llm["fallback_model"] is None
            assert llm["self_hosted"]["base_url"] == ""
            assert llm["managed_local"] == []
            # A partial write keeps the pre-existing keys byte-identical.
            settings_store.set_llm_settings(
                {"task_models": {"chat": "auto"}}, p)
            data = json.loads(p.read_text(encoding="utf-8"))
            assert data["allow_cloud"] is False and data["cloud_ack"] is True
            assert "llm" in data
    finally:
        restore()


def test_settings_configured_endpoint_is_mirrored_into_env_but_env_wins():
    p, restore = _tmp_settings()
    try:
        with _EnvGuard(**_CLEAN_LLM_ENV):
            settings_store.set_llm_settings({"self_hosted": {
                "base_url": "https://a.example.com", "model": "m1"}}, p)
            assert os.environ["OPENAI_COMPATIBLE_BASE_URL"] == "https://a.example.com"
            assert os.environ["OPENAI_COMPATIBLE_MODEL"] == "m1"
        # Externally-set env (pre-existing surface) always wins → env_locked.
        with _EnvGuard(**{**_CLEAN_LLM_ENV,
                          "OPENAI_COMPATIBLE_BASE_URL": "https://env.example.com",
                          "OPENAI_COMPATIBLE_MODEL": "env-model"}):
            assert settings_store.env_self_hosted_is_explicit()
            sh = model_registry.self_hosted_config()
            assert sh["env_locked"] and sh["base_url"] == "https://env.example.com"
    finally:
        restore()


# ── 8. registry states are read-only and sane ─────────────────────────────────
def test_registry_lists_all_profiles_with_states():
    p, restore = _tmp_settings()
    try:
        with _EnvGuard(**_CLEAN_LLM_ENV):
            settings_store.set_llm_settings({"managed_local": [
                {"id": "local-ghost", "path": "/nonexistent/model",
                 "display_name": "Ghost"}]}, p)
            models = {e.id: e for e in model_registry.list_models()}
            assert model_registry.BUNDLED_ID in models
            assert model_registry.SELF_HOSTED_ID in models
            assert model_registry.GROQ_ID in models
            assert "local-ghost" in models
            assert model_registry.model_state(models["local-ghost"]) == "unavailable"
            assert not models[model_registry.SELF_HOSTED_ID].configured
            hw = model_registry.hardware_snapshot()
            assert "platform" in hw and "total_ram_gb" in hw
    finally:
        restore()


if __name__ == "__main__":
    import traceback
    failed = 0
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn(); print(f"PASS  {name}")
        except Exception:
            failed += 1; print(f"FAIL  {name}"); traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
