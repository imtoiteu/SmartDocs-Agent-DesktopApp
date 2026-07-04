"""Agent Core orchestration tests (Phase 3).

These verify the loop mechanics deterministically with a scripted FakeProvider —
no model loading. Tool execution goes through a real ToolRegistry with stub
tools, so the registry/tool contract is exercised end to end.

Runs under pytest (`pytest agent/tests/`) OR standalone
(`python agent/tests/test_agent_core.py`).
"""

import contextlib
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import pytest  # noqa: F401
except ImportError:
    pytest = None

from agent.core import AgentCore, AgentResult, LLMProvider  # noqa: E402
from agent.tools import Tool, ToolRegistry, ToolResult  # noqa: E402


# ── test doubles ────────────────────────────────────────────────────────────────
class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []          # list of role-sequences, one per complete()
        self.calls_content = []  # the last message's content, one per complete()

    def complete(self, messages, *, max_tokens=512, temperature=0.2):
        self.calls.append([m["role"] for m in messages])
        self.calls_content.append(messages[-1].get("content") or "")
        return self.responses.pop(0) if self.responses else '{"final": "(exhausted)"}'


class EchoTool(Tool):
    name = "echo"
    description = "Echo the args back."
    parameters = {"type": "object", "properties": {"x": {"type": "integer"}}}

    def run(self, **kwargs):
        return ToolResult.success({"echo": kwargs})


class CaptureTool(Tool):
    """A tool whose name is set per-instance, capturing the kwargs it received."""
    description = "capture"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, name):
        self.name = name
        self.last_kwargs = None

    def run(self, **kwargs):
        self.last_kwargs = kwargs
        return ToolResult.success({"ok": True})


def _registry(*tools):
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


# ── tests ───────────────────────────────────────────────────────────────────────
def test_direct_final_answer():
    core = AgentCore(registry=_registry(EchoTool()),
                     provider=FakeProvider(['{"final": "hello"}']), max_steps=3)
    res = core.run("hi")
    assert isinstance(res, AgentResult)
    assert res.answer == "hello" and res.completed
    assert res.tool_calls() == []
    assert res.provider == "fake"


def test_tool_then_final():
    fp = FakeProvider(['{"tool": "echo", "arguments": {"x": 7}}', '{"final": "done"}'])
    core = AgentCore(registry=_registry(EchoTool()), provider=fp, max_steps=3)
    res = core.run("do it")
    assert res.tool_calls() == ["echo"]
    assert res.answer == "done" and res.completed
    tool_step = [s for s in res.steps if s.kind == "tool"][0]
    assert tool_step.observation["ok"] is True
    assert tool_step.observation["data"]["echo"] == {"x": 7}


def test_plain_text_is_treated_as_final():
    core = AgentCore(registry=_registry(EchoTool()),
                     provider=FakeProvider(["I think the answer is 42."]), max_steps=2)
    res = core.run("q")
    assert res.answer == "I think the answer is 42." and res.completed
    assert res.tool_calls() == []


def test_json_in_code_fence_is_parsed():
    core = AgentCore(registry=_registry(EchoTool()),
                     provider=FakeProvider(['```json\n{"final": "x"}\n```']), max_steps=2)
    res = core.run("q")
    assert res.answer == "x"


def test_json_with_braces_inside_string_value():
    core = AgentCore(registry=_registry(EchoTool()),
                     provider=FakeProvider(['Sure: {"final": "has {braces} inside"}']),
                     max_steps=2)
    res = core.run("q")
    assert res.answer == "has {braces} inside"


def test_unknown_tool_becomes_failure_observation_then_recovers():
    fp = FakeProvider(['{"tool": "nope", "arguments": {}}', '{"final": "recovered"}'])
    core = AgentCore(registry=_registry(EchoTool()), provider=fp, max_steps=3)
    res = core.run("q")
    obs = [s for s in res.steps if s.kind == "tool"][0].observation
    assert obs["ok"] is False and "Unknown tool" in obs["error"]
    assert res.answer == "recovered"


def test_tenancy_injected_for_chat_tool_only():
    chat = CaptureTool("chat")
    fp = FakeProvider(['{"tool": "chat", "arguments": {"query": "hi"}}', '{"final": "ok"}'])
    core = AgentCore(registry=_registry(chat), provider=fp, max_steps=3)
    core.run("ask", allowed_file_ids={"a", "b"})
    assert chat.last_kwargs.get("allowed_file_ids") == {"a", "b"}
    assert chat.last_kwargs.get("query") == "hi"


def test_tenancy_not_injected_for_non_tenancy_tool():
    cap = CaptureTool("echo")  # not in tenancy_tools
    fp = FakeProvider(['{"tool": "echo", "arguments": {"x": 1}}', '{"final": "ok"}'])
    core = AgentCore(registry=_registry(cap), provider=fp, max_steps=3)
    core.run("q", allowed_file_ids={"a"})
    assert "allowed_file_ids" not in cap.last_kwargs


def test_tenancy_not_injected_when_none():
    chat = CaptureTool("chat")
    fp = FakeProvider(['{"tool": "chat", "arguments": {"query": "hi"}}', '{"final": "ok"}'])
    core = AgentCore(registry=_registry(chat), provider=fp, max_steps=3)
    core.run("ask")  # no allowed_file_ids
    assert "allowed_file_ids" not in chat.last_kwargs


def test_max_steps_then_synthesis_marks_incomplete():
    fp = FakeProvider([
        '{"tool": "echo", "arguments": {}}',
        '{"tool": "echo", "arguments": {}}',
        "final synthesized answer",  # synthesis pass (plain text)
    ])
    core = AgentCore(registry=_registry(EchoTool()), provider=fp, max_steps=2)
    res = core.run("q")
    assert res.completed is False
    assert res.answer == "final synthesized answer"
    assert len(res.tool_calls()) == 2


def test_result_to_dict_shape():
    fp = FakeProvider(['{"tool": "echo", "arguments": {"x": 1}}', '{"final": "ok"}'])
    core = AgentCore(registry=_registry(EchoTool()), provider=fp, max_steps=3)
    d = core.run("q").to_dict()
    assert d["answer"] == "ok" and d["completed"] is True
    assert d["timed_out"] is False
    assert d["tool_calls"] == ["echo"]
    assert d["steps"][0]["tool"] == "echo"


# ── wall-clock time budget (review P5) ───────────────────────────────────────
class SlowProvider(FakeProvider):
    """FakeProvider that burns wall-clock time on each completion."""

    def __init__(self, responses, delay_s):
        super().__init__(responses)
        self.delay_s = delay_s

    def complete(self, messages, *, max_tokens=512, temperature=0.2):
        import time
        time.sleep(self.delay_s)
        return super().complete(messages, max_tokens=max_tokens,
                                temperature=temperature)


def test_time_budget_stops_loop_and_synthesizes():
    # Each step takes ~50ms; the budget allows roughly one. The run must stop
    # early, do ONE synthesis pass, and be marked timed_out + incomplete.
    fp = SlowProvider(
        ['{"tool": "echo", "arguments": {}}'] * 10 + ["synthesized under time"],
        delay_s=0.05)
    core = AgentCore(registry=_registry(EchoTool()), provider=fp,
                     max_steps=6, time_budget_s=0.06)
    res = core.run("q")
    assert res.timed_out is True and res.completed is False
    assert res.answer  # a real answer was still produced
    assert len(res.tool_calls()) < 6                # stopped before max_steps
    assert res.steps[-1].kind == "final"
    assert res.to_dict()["timed_out"] is True


def test_time_budget_expired_before_first_step_still_answers():
    fp = FakeProvider(["best effort answer"])
    core = AgentCore(registry=_registry(EchoTool()), provider=fp,
                     max_steps=3, time_budget_s=0.0)   # already expired
    res = core.run("q")
    assert res.timed_out is True and res.completed is False
    assert res.answer == "best effort answer"
    assert res.tool_calls() == []                   # no tool was started
    # The synthesis instruction says time ran out.
    assert "Time is up" in fp.calls_content[-1]


def test_no_time_budget_keeps_old_contract():
    fp = FakeProvider(['{"tool": "echo", "arguments": {}}', '{"final": "ok"}'])
    core = AgentCore(registry=_registry(EchoTool()), provider=fp, max_steps=3)
    res = core.run("q")
    assert res.timed_out is False and res.completed is True


# ── on_progress events (run progress feedback) ───────────────────────────────
def test_on_progress_emits_thinking_and_acting():
    events = []
    fp = FakeProvider(['{"tool": "echo", "arguments": {}}', '{"final": "ok"}'])
    core = AgentCore(registry=_registry(EchoTool()), provider=fp, max_steps=3,
                     on_progress=events.append)
    res = core.run("q")
    assert res.answer == "ok"
    phases = [e["phase"] for e in events]
    assert phases == ["thinking", "acting", "thinking"]
    acting = events[1]
    assert acting == {"phase": "acting", "step": 1, "max_steps": 3,
                      "kind": "tool", "name": "echo"}
    assert events[2]["step"] == 2                    # the final-answer step


def test_on_progress_planning_and_synthesis_phases():
    events = []
    fp = FakeProvider(["a short plan",                       # planning pass
                       '{"tool": "echo", "arguments": {}}',  # step 1 (max_steps=1)
                       "synthesized"])                       # synthesis pass
    core = AgentCore(registry=_registry(EchoTool()), provider=fp, max_steps=1,
                     enable_planning=True, on_progress=events.append)
    res = core.run("q")
    assert res.plan == "a short plan" and res.completed is False
    phases = [e["phase"] for e in events]
    assert phases[0] == "planning" and phases[-1] == "synthesis"


def test_on_progress_raising_callback_never_breaks_run():
    def boom(_event):
        raise RuntimeError("observer crashed")
    fp = FakeProvider(['{"final": "still fine"}'])
    core = AgentCore(registry=_registry(EchoTool()), provider=fp, max_steps=2,
                     on_progress=boom)
    assert core.run("q").answer == "still fine"


def test_no_on_progress_keeps_old_contract():
    fp = FakeProvider(['{"final": "ok"}'])
    core = AgentCore(registry=_registry(EchoTool()), provider=fp, max_steps=2)
    assert core.run("q").answer == "ok"


# ── retrieval grounding instruction (review P6) ──────────────────────────────
def test_system_prompt_requires_grounding_or_disclosure():
    core = AgentCore(registry=_registry(EchoTool()),
                     provider=FakeProvider([]), max_steps=1)
    sp = core._system_prompt()
    assert "Grounding" in sp
    assert "retrieve evidence FIRST" in sp
    assert "say so explicitly" in sp
    # The instruction names the retrieval tools it expects the agent to use.
    assert "knowledge_search" in sp and "chat" in sp


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
