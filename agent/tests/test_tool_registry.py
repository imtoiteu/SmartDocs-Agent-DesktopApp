"""Tool Registry + Tool contract tests (Phase 2).

These are intentionally lightweight: they exercise registration, introspection,
dispatch and error handling WITHOUT loading any OCR/LLM models. Building the
default registry must not import the heavy service stack — that is part of the
contract (services are imported lazily inside each tool's run()).

Runs under pytest (`pytest agent/tests/`) when available, OR standalone
(`python agent/tests/test_tool_registry.py`) when pytest is not installed.
"""

import contextlib
import pathlib
import sys
import types

# Make the SmartDocs-Agent root importable whether run via pytest or directly.
_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import pytest  # noqa: F401

    raises = pytest.raises
except ImportError:  # pytest not installed → minimal shim so the file still runs
    @contextlib.contextmanager
    def raises(exc):
        try:
            yield
        except exc:
            return
        else:
            raise AssertionError(f"Expected {exc.__name__} to be raised")

from agent.tools import (  # noqa: E402
    Tool,
    ToolResult,
    ToolRegistry,
    build_default_registry,
    get_registry,
)

CORE_TOOLS = {"ocr", "translate", "summarize", "chat", "knowledge_search", "correct"}


# ── default registry / built-in tools ───────────────────────────────────────────
def test_default_registry_registers_the_core_tools():
    reg = build_default_registry()
    assert set(reg.names()) == CORE_TOOLS


def test_get_registry_is_a_singleton():
    assert get_registry() is get_registry()


def test_specs_are_function_call_shaped():
    reg = build_default_registry()
    specs = reg.specs()
    assert {s["name"] for s in specs} == CORE_TOOLS
    for spec in specs:
        assert spec["description"], f"{spec['name']} missing description"
        assert spec["parameters"]["type"] == "object"
        assert "properties" in spec["parameters"]


def test_required_params_declared():
    reg = build_default_registry()
    required = {s["name"]: s["parameters"].get("required", []) for s in reg.specs()}
    assert required["ocr"] == ["image_path"]
    assert required["translate"] == ["text"]
    assert required["summarize"] == ["text"]
    assert required["chat"] == ["query"]
    assert required["knowledge_search"] == ["query"]
    assert required["correct"] == ["text"]


def test_correct_tool_runs_via_registry():
    # The correction tool wraps the existing correction_service (basic cleanup
    # always runs; English spelling is best-effort). No heavy model load.
    reg = build_default_registry()
    res = reg.run("correct", text="this  is  a tst .")
    assert res.ok and "corrected" in res.data
    assert isinstance(res.data["corrected"], str)


def test_chat_does_not_expose_allowed_file_ids():
    # Security: the LLM must never choose the tenancy scope; the platform injects it.
    reg = build_default_registry()
    chat_spec = next(s for s in reg.specs() if s["name"] == "chat")
    assert "allowed_file_ids" not in chat_spec["parameters"]["properties"]


def test_building_registry_does_not_import_heavy_services():
    for mod in ("torch", "paddleocr", "transformers"):
        sys.modules.pop(mod, None)
    build_default_registry()
    assert "torch" not in sys.modules
    assert "paddleocr" not in sys.modules
    assert "transformers" not in sys.modules


# ── lookup / dispatch / error handling ──────────────────────────────────────────
def test_unknown_tool_returns_failure_not_raise():
    reg = build_default_registry()
    result = reg.run("does_not_exist")
    assert result.ok is False
    assert "Unknown tool" in (result.error or "")
    assert result.meta["tool"] == "does_not_exist"


def test_get_unknown_tool_raises():
    reg = build_default_registry()
    with raises(KeyError):
        reg.get("nope")


def test_duplicate_registration_raises():
    reg = ToolRegistry()

    class T(Tool):
        name = "dup"
        description = "d"
        parameters = {"type": "object", "properties": {}}

        def run(self, **_):
            return ToolResult.success({})

    reg.register(T())
    with raises(ValueError):
        reg.register(T())


def test_tool_exception_is_captured_as_failure_with_meta():
    reg = ToolRegistry()

    class Boom(Tool):
        name = "boom"
        description = "d"
        parameters = {"type": "object", "properties": {}}

        def run(self, **_):
            raise RuntimeError("kaboom")

    reg.register(Boom())
    result = reg.run("boom")
    assert result.ok is False
    assert "kaboom" in (result.error or "")
    assert result.meta["tool"] == "boom"
    assert "elapsed_ms" in result.meta


def test_bare_dict_return_is_wrapped_in_toolresult():
    reg = ToolRegistry()

    class Bare(Tool):
        name = "bare"
        description = "d"
        parameters = {"type": "object", "properties": {}}

        def run(self, **_):
            return {"hello": "world"}  # not a ToolResult on purpose

    reg.register(Bare())
    result = reg.run("bare")
    assert isinstance(result, ToolResult)
    assert result.ok is True
    assert result.data == {"hello": "world"}


def test_toolresult_helpers_and_serialisation():
    ok = ToolResult.success({"a": 1}, engine="x", skip_me=None)
    assert ok.to_dict() == {"ok": True, "data": {"a": 1}, "error": None, "meta": {"engine": "x"}}
    bad = ToolResult.failure("boom")
    assert bad.ok is False and bad.error == "boom"


# ── tenancy guard on the retrieval tools (chat / knowledge_search) ───────────────
# These verify the defense-in-depth guard that drops a file_id the caller does not
# own (RAG retrieval bypasses the allowed-id filter when a specific file_id is set).
# Heavy services are faked so no model is loaded.
@contextlib.contextmanager
def _fake_chat_service():
    """Install a fake ``services.chat_service`` recording the file_id it receives."""
    captured = {}

    def chat(query, file_id=None, mode="doc_current", history=None, allowed_file_ids=None):
        captured.update(file_id=file_id, mode=mode, allowed_file_ids=allowed_file_ids)
        return {"answer": "ok", "sources": [], "engine_used": "fake"}

    fake = types.ModuleType("services.chat_service")
    fake.chat = chat
    import services as services_pkg                      # cheap: empty __init__
    saved_mod = sys.modules.get("services.chat_service")
    saved_attr = getattr(services_pkg, "chat_service", None)
    sys.modules["services.chat_service"] = fake
    services_pkg.chat_service = fake
    try:
        yield captured
    finally:
        if saved_mod is not None:
            sys.modules["services.chat_service"] = saved_mod
        else:
            sys.modules.pop("services.chat_service", None)
        if saved_attr is not None:
            services_pkg.chat_service = saved_attr
        else:
            delattr(services_pkg, "chat_service")


@contextlib.contextmanager
def _fake_knowledge_registry():
    """Patch ``agent.knowledge.get_knowledge_registry`` to record the file_id."""
    import agent.knowledge as kn
    from agent.knowledge import KnowledgeResult
    captured = {}

    class _Comp:
        def retrieve(self, query, *, top_k=5, allowed_file_ids=None, file_id=None):
            captured.update(file_id=file_id, allowed_file_ids=allowed_file_ids)
            return KnowledgeResult(query=query, source="fake", citations=[])

    class _Reg:
        def composite(self):
            return _Comp()

    saved = kn.get_knowledge_registry
    kn.get_knowledge_registry = lambda: _Reg()
    try:
        yield captured
    finally:
        kn.get_knowledge_registry = saved


def test_chat_tool_drops_unowned_file_id():
    from agent.tools.chat_tool import ChatTool
    with _fake_chat_service() as cap:
        ChatTool().run(query="q", file_id="not-mine", mode="doc_current",
                       allowed_file_ids={"f1", "f2"})
    assert cap["file_id"] is None


def test_chat_tool_keeps_owned_file_id():
    from agent.tools.chat_tool import ChatTool
    with _fake_chat_service() as cap:
        ChatTool().run(query="q", file_id="f1", mode="doc_current",
                       allowed_file_ids={"f1", "f2"})
    assert cap["file_id"] == "f1"


def test_chat_tool_admin_scope_keeps_file_id():
    # allowed_file_ids None (admin) → no restriction; the file_id is preserved.
    from agent.tools.chat_tool import ChatTool
    with _fake_chat_service() as cap:
        ChatTool().run(query="q", file_id="anything", mode="doc_current",
                       allowed_file_ids=None)
    assert cap["file_id"] == "anything"


def test_knowledge_search_tool_drops_unowned_file_id():
    from agent.tools.knowledge_tool import KnowledgeSearchTool
    with _fake_knowledge_registry() as cap:
        KnowledgeSearchTool().run(query="q", file_id="not-mine",
                                  allowed_file_ids={"f1"})
    assert cap["file_id"] is None


def test_knowledge_search_tool_keeps_owned_file_id():
    from agent.tools.knowledge_tool import KnowledgeSearchTool
    with _fake_knowledge_registry() as cap:
        KnowledgeSearchTool().run(query="q", file_id="f1",
                                  allowed_file_ids={"f1"})
    assert cap["file_id"] == "f1"


# ── standalone runner (used when pytest is unavailable) ──────────────────────────
if __name__ == "__main__":
    import traceback

    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
