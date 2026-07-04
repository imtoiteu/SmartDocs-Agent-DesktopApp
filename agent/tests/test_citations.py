"""AgentCore citation-threading tests (Phase 9).

The agent gathers citation-shaped evidence from tool/skill observations
(knowledge_search & research expose data.citations; chat exposes data.sources)
and surfaces a merged, de-duplicated, ranked list on AgentResult.citations.
Deterministic — scripted FakeProvider + stub tools, no model loading.

Runs under pytest OR standalone (`python agent/tests/test_citations.py`).
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

from agent.core import AgentCore, LLMProvider                  # noqa: E402
from agent.tools import Tool, ToolRegistry, ToolResult         # noqa: E402
from agent.skills import Skill, SkillContext, SkillRegistry, SkillResult  # noqa: E402


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, messages, *, max_tokens=512, temperature=0.2):
        return self.responses.pop(0) if self.responses else '{"final": "(exhausted)"}'


class KnowTool(Tool):
    name = "knowledge_search"
    description = "k"
    parameters = {"type": "object", "properties": {}}

    def run(self, **_):
        return ToolResult.success({"query": "q", "source": "documents", "citations": [
            {"file_id": "f1", "score": 0.90, "excerpt": "alpha"},
            {"file_id": "f2", "score": 0.70, "excerpt": "beta"},
        ]})


class ChatToolStub(Tool):
    name = "chat"
    description = "c"
    parameters = {"type": "object", "properties": {}}

    def run(self, **_):
        return ToolResult.success({"answer": "a", "sources": [
            {"file_id": "f1", "score": 0.95, "excerpt": "alpha"},   # dup of KnowTool's f1
            {"file_id": "f3", "score": 0.60, "excerpt": "gamma"},
        ]})


class PlainTool(Tool):
    name = "translate"
    description = "t"
    parameters = {"type": "object", "properties": {}}

    def run(self, **_):
        return ToolResult.success({"translated": "x"})   # no citations/sources


def _registry(*ts):
    r = ToolRegistry()
    for t in ts:
        r.register(t)
    return r


def test_citations_threaded_from_knowledge_search():
    fp = FakeProvider(['{"tool": "knowledge_search", "arguments": {"query": "q"}}',
                       '{"final": "done"}'])
    res = AgentCore(registry=_registry(KnowTool()), provider=fp, max_steps=3).run("q")
    assert [c["file_id"] for c in res.citations] == ["f1", "f2"]
    assert res.citations[0]["score"] == 0.90
    assert "excerpt" in res.citations[0]


def test_citations_merged_and_deduped_across_steps():
    fp = FakeProvider([
        '{"tool": "knowledge_search", "arguments": {"query": "q"}}',
        '{"tool": "chat", "arguments": {"query": "q"}}',
        '{"final": "done"}',
    ])
    res = AgentCore(registry=_registry(KnowTool(), ChatToolStub()),
                    provider=fp, max_steps=4).run("q")
    # f1 appears in both; the higher (0.95, from chat) wins, then f2, then f3.
    assert [c["file_id"] for c in res.citations] == ["f1", "f2", "f3"]
    assert res.citations[0]["score"] == 0.95
    assert res.to_dict()["citations"] == res.citations


def test_citations_capped_to_retrieval_breadth():
    # A corpus-wide / repeated retrieval can surface many documents; the Sources set
    # must stay one retrieval's worth (the top-scoring chunks actually retrieved) and
    # never grow into the user's whole library.
    class BroadKnowTool(Tool):
        name = "knowledge_search"
        description = "k"
        parameters = {"type": "object", "properties": {}}

        def run(self, **_):
            return ToolResult.success({"query": "q", "citations": [
                {"file_id": f"f{i}", "score": round(0.99 - i * 0.05, 3),
                 "excerpt": f"chunk {i}"} for i in range(8)   # 8 distinct docs
            ]})

    fp = FakeProvider(['{"tool": "knowledge_search", "arguments": {"query": "q"}}',
                       '{"final": "done"}'])
    res = AgentCore(registry=_registry(BroadKnowTool()), provider=fp, max_steps=3).run("q")
    assert len(res.citations) == 5                                  # capped, not 8
    assert [c["file_id"] for c in res.citations] == ["f0", "f1", "f2", "f3", "f4"]  # top by score


def test_no_retrieval_means_no_citations():
    fp = FakeProvider(['{"final": "hi"}'])
    res = AgentCore(registry=_registry(KnowTool()), provider=fp, max_steps=2).run("q")
    assert res.citations == []


def test_plain_tool_contributes_no_citations():
    fp = FakeProvider(['{"tool": "translate", "arguments": {}}', '{"final": "done"}'])
    res = AgentCore(registry=_registry(PlainTool()), provider=fp, max_steps=3).run("q")
    assert res.citations == []


def test_citations_from_a_skill_observation():
    class ResearchStub(Skill):
        name = "research"
        description = "r"
        parameters = {"type": "object", "properties": {}}

        def run(self, ctx, **_):
            return SkillResult.success({"answer": "a", "citations": [
                {"file_id": "f9", "score": 0.8, "excerpt": "delta"}]})

    fp = FakeProvider(['{"skill": "research", "arguments": {"query": "q"}}',
                       '{"final": "done"}'])
    core = AgentCore(registry=_registry(PlainTool()), provider=fp, max_steps=3,
                     skills=SkillRegistry(), skill_context=SkillContext(tools=ToolRegistry()))
    core.skills.register(ResearchStub())
    res = core.run("q")
    assert [c["file_id"] for c in res.citations] == ["f9"]


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
