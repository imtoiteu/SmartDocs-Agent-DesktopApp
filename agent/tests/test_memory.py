"""Tests for the agent memory layer (Phase 6).

Runs under pytest OR standalone (``python agent/tests/test_memory.py``). These
tests are DB-free: they exercise the ``AgentMemory`` contract via
``InMemoryAgentMemory`` and the ``ConversationMemory`` None-guards (which
short-circuit before any ``models`` import). The DB-backed path is verified live
against the running app, matching the project's verification pattern.
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import pytest  # noqa: F401
except ImportError:
    pytest = None

from agent.memory import AgentMemory, InMemoryAgentMemory, ConversationMemory


def test_import_agent_is_model_free():
    # Importing the agent package (incl. memory) must not pull in the DB stack.
    import importlib
    import agent  # noqa: F401
    importlib.import_module("agent.memory")
    assert "models" not in sys.modules, "agent import must stay model-free"


def test_inmemory_roundtrip_and_order():
    m = InMemoryAgentMemory()
    assert m.load_history(1) == []                      # unknown id → empty
    m.append_turn(1, "user", "hello")
    m.append_turn(1, "assistant", "hi there", tool_calls=["translate"], provider="local-qwen")
    hist = m.load_history(1)
    assert hist == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


def test_inmemory_history_excludes_metadata():
    m = InMemoryAgentMemory()
    m.append_turn(7, "assistant", "x", tool_calls=["summarize"], provider="p")
    # load_history yields only role/content (the LLM message shape).
    assert m.load_history(7) == [{"role": "assistant", "content": "x"}]


def test_inmemory_isolated_by_conversation():
    m = InMemoryAgentMemory()
    m.append_turn(1, "user", "a")
    m.append_turn(2, "user", "b")
    assert m.load_history(1) == [{"role": "user", "content": "a"}]
    assert m.load_history(2) == [{"role": "user", "content": "b"}]


def test_none_conversation_is_noop_everywhere():
    # Both implementations treat a None conversation id as "no session".
    for m in (InMemoryAgentMemory(), ConversationMemory()):
        assert m.load_history(None) == []
        m.append_turn(None, "user", "ignored")          # must not raise / touch DB
    assert "models" not in sys.modules, "None-guard must short-circuit before DB import"


def test_subclassing_contract():
    assert issubclass(InMemoryAgentMemory, AgentMemory)
    assert issubclass(ConversationMemory, AgentMemory)
    assert ConversationMemory().name == "agent-db"


def test_load_history_limit_keeps_newest_turns():
    # Bounded context (review P3): limit returns only the NEWEST turns, still in
    # chronological order; None keeps everything (the prior contract).
    m = InMemoryAgentMemory()
    for i in range(6):
        m.append_turn(1, "user" if i % 2 == 0 else "assistant", f"t{i}")
    assert [t["content"] for t in m.load_history(1, limit=2)] == ["t4", "t5"]
    assert [t["content"] for t in m.load_history(1, limit=100)] == [
        f"t{i}" for i in range(6)]
    assert [t["content"] for t in m.load_history(1)] == [f"t{i}" for i in range(6)]
    assert m.load_history(1, limit=0) == []
    assert m.load_history(None, limit=2) == []          # None-guard unaffected


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
