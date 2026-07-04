"""Agent Core planning + skill-selection tests (Phase 7).

Deterministic, no model loading: a scripted FakeProvider drives the loop and a
stub CaptureSkill records what the agent dispatched. These cover the new opt-in
paths only; backward compatibility (planning off, skills None) is covered by
test_agent_core.py, which is unchanged.

Runs under pytest OR standalone (`python agent/tests/test_planning.py`).
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

from agent.core import AgentCore, LLMProvider                       # noqa: E402
from agent.tools import Tool, ToolRegistry, ToolResult              # noqa: E402
from agent.skills import Skill, SkillContext, SkillRegistry, SkillResult  # noqa: E402


# ── test doubles ────────────────────────────────────────────────────────────────
class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def complete(self, messages, *, max_tokens=512, temperature=0.2):
        self.calls += 1
        return self.responses.pop(0) if self.responses else '{"final": "(exhausted)"}'


class EchoTool(Tool):
    name = "echo"
    description = "Echo args back."
    parameters = {"type": "object", "properties": {"x": {"type": "integer"}}}

    def run(self, **kwargs):
        return ToolResult.success({"echo": kwargs})


class CaptureSkill(Skill):
    description = "capture skill"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, name):
        self.name = name
        self.last_ctx = None
        self.last_kwargs = None

    def run(self, ctx, **kwargs):
        self.last_ctx = ctx
        self.last_kwargs = kwargs
        return SkillResult.success({"captured": kwargs})


def _tools(*ts):
    r = ToolRegistry()
    for t in ts:
        r.register(t)
    return r


def _skills(*ss):
    r = SkillRegistry()
    for s in ss:
        r.register(s)
    return r


def _ctx(tools=None, allowed=None):
    return SkillContext(tools=tools or ToolRegistry(), allowed_file_ids=allowed,
                        knowledge=None, provider=None)


# ── planning ──────────────────────────────────────────────────────────────────
def test_planning_adds_plan_then_executes():
    fp = FakeProvider([
        "I will call echo, then answer.",           # planning pass (plain text)
        '{"tool": "echo", "arguments": {"x": 1}}',  # step 1
        '{"final": "done"}',                        # step 2
    ])
    core = AgentCore(registry=_tools(EchoTool()), provider=fp,
                     max_steps=3, enable_planning=True)
    res = core.run("go")
    assert res.plan == "I will call echo, then answer."
    assert res.tool_calls() == ["echo"]
    assert res.answer == "done" and res.completed
    assert fp.calls == 3                             # plan + 2 loop calls


def test_planning_robust_when_model_emits_json():
    # Model ignores the planning instruction and emits JSON → no usable plan,
    # the run still proceeds without crashing.
    fp = FakeProvider(['{"unexpected": 1}', '{"final": "answer"}'])
    core = AgentCore(registry=_tools(EchoTool()), provider=fp,
                     max_steps=2, enable_planning=True)
    res = core.run("q")
    assert res.plan is None
    assert res.answer == "answer"


def test_planning_off_makes_no_extra_call():
    fp = FakeProvider(['{"final": "x"}'])
    core = AgentCore(registry=_tools(EchoTool()), provider=fp, max_steps=2)
    res = core.run("q")
    assert res.plan is None and res.answer == "x"
    assert fp.calls == 1                             # no planning call


# ── skill selection ──────────────────────────────────────────────────────────
def test_skill_is_dispatched_and_traced():
    sk = CaptureSkill("summarize_translate")
    fp = FakeProvider([
        '{"skill": "summarize_translate", "arguments": {"text": "hi", "to_lang": "vi"}}',
        '{"final": "ok"}',
    ])
    core = AgentCore(registry=_tools(EchoTool()), provider=fp, max_steps=3,
                     skills=_skills(sk), skill_context=_ctx())
    res = core.run("summarize and translate")
    assert res.skill_calls() == ["summarize_translate"]
    assert res.tool_calls() == []
    assert sk.last_kwargs == {"text": "hi", "to_lang": "vi"}
    skill_step = [s for s in res.steps if s.kind == "skill"][0]
    assert skill_step.observation["ok"] is True
    assert res.answer == "ok"


def test_skill_receives_tenancy_via_context():
    sk = CaptureSkill("research")
    fp = FakeProvider(['{"skill": "research", "arguments": {"query": "q"}}',
                       '{"final": "ok"}'])
    core = AgentCore(registry=_tools(EchoTool()), provider=fp, max_steps=3,
                     skills=_skills(sk), skill_context=_ctx(allowed=None))
    core.run("research q", allowed_file_ids={"f1", "f2"})
    # The per-run context carries the caller's scope; the LLM never chose it.
    assert sk.last_ctx is not None
    assert sk.last_ctx.allowed_file_ids == {"f1", "f2"}


# ── leniency for the weak model putting a name in the wrong slot ───────────────
def test_tool_name_in_skill_slot_falls_back_to_tool():
    fp = FakeProvider(['{"skill": "echo", "arguments": {"x": 5}}', '{"final": "ok"}'])
    core = AgentCore(registry=_tools(EchoTool()), provider=fp, max_steps=3,
                     skills=_skills(CaptureSkill("research")), skill_context=_ctx())
    res = core.run("q")
    assert res.tool_calls() == ["echo"] and res.skill_calls() == []


def test_skill_name_in_tool_slot_falls_back_to_skill():
    sk = CaptureSkill("summarize_translate")
    fp = FakeProvider(['{"tool": "summarize_translate", "arguments": {"text": "x"}}',
                       '{"final": "ok"}'])
    core = AgentCore(registry=_tools(EchoTool()), provider=fp, max_steps=3,
                     skills=_skills(sk), skill_context=_ctx())
    res = core.run("q")
    assert res.skill_calls() == ["summarize_translate"] and res.tool_calls() == []


def test_empty_skill_registry_omits_skills_section():
    # A pure-tool agent (no agent-selectable skills) must not advertise a skills
    # section or the skill action — only tools. Guards the docqa unification, where
    # _AGENT_SKILL_NAMES became empty.
    core = AgentCore(registry=_tools(EchoTool()), provider=FakeProvider([]),
                     skills=SkillRegistry(), skill_context=_ctx())
    p = core._system_prompt()
    assert "Available skills" not in p
    assert "to run a skill" not in p
    assert "echo" in p                       # tools are still advertised


def test_skill_action_with_skills_disabled_is_unknown_tool():
    # skills=None → a {"skill": ...} action is treated as an (unknown) tool call,
    # surfaced as a failure observation the model can recover from.
    fp = FakeProvider(['{"skill": "research", "arguments": {}}', '{"final": "recovered"}'])
    core = AgentCore(registry=_tools(EchoTool()), provider=fp, max_steps=3)
    res = core.run("q")
    obs = [s for s in res.steps if s.kind == "tool"][0].observation
    assert obs["ok"] is False and "Unknown tool" in obs["error"]
    assert res.answer == "recovered"


def test_to_dict_includes_plan_and_skill_calls():
    sk = CaptureSkill("research")
    fp = FakeProvider(["plan text", '{"skill": "research", "arguments": {"query": "q"}}',
                       '{"final": "ok"}'])
    core = AgentCore(registry=_tools(EchoTool()), provider=fp, max_steps=3,
                     skills=_skills(sk), skill_context=_ctx(), enable_planning=True)
    d = core.run("q").to_dict()
    assert d["plan"] == "plan text"
    assert d["skill_calls"] == ["research"]
    assert d["tool_calls"] == []
    assert d["steps"][0]["kind"] == "skill"


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
