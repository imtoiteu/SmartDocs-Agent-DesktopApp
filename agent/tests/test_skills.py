"""Skills layer tests (Phase 4).

Skills are exercised with stub tools (a real ToolRegistry of fakes) and a stub
knowledge source — deterministic, no model loading.

Runs under pytest OR standalone (`python agent/tests/test_skills.py`).
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

from agent.knowledge import Citation, KnowledgeResult  # noqa: E402
from agent.skills import (  # noqa: E402
    SkillContext,
    SkillResult,
    build_default_skill_registry,
    get_skill_registry,
)
from agent.skills.summarize_translate import SummarizeTranslateSkill  # noqa: E402
from agent.skills.ocr_digest import OcrDigestSkill  # noqa: E402
from agent.skills.research import ResearchSkill  # noqa: E402
from agent.skills.summarize import SummarizeSkill  # noqa: E402
from agent.skills.translate import TranslateSkill  # noqa: E402
from agent.skills.correct import CorrectSkill  # noqa: E402
from agent.skills.docqa import DocQaSkill  # noqa: E402
from agent.tools import Tool, ToolRegistry, ToolResult  # noqa: E402


# ── test doubles ────────────────────────────────────────────────────────────────
class FakeTool(Tool):
    description = "fake"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, name, fn):
        self.name = name
        self._fn = fn
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._fn(kwargs)


def ok_tool(name, data):
    return FakeTool(name, lambda kw: ToolResult.success(data))


def fail_tool(name, err):
    return FakeTool(name, lambda kw: ToolResult.failure(err))


def _reg(*tools):
    r = ToolRegistry()
    for t in tools:
        r.register(t)
    return r


class FakeKnowledge:
    name = "fake"

    def __init__(self, citations):
        self._c = citations
        self.captured = None

    def retrieve(self, query, *, top_k=5, allowed_file_ids=None, file_id=None):
        self.captured = {"query": query, "top_k": top_k,
                         "allowed_file_ids": allowed_file_ids, "file_id": file_id}
        return KnowledgeResult(query=query, source="fake", citations=self._c)


# ── summarize_translate ─────────────────────────────────────────────────────────
def test_summarize_translate_success():
    ctx = SkillContext(tools=_reg(
        ok_tool("summarize", {"summary": "S"}),
        ok_tool("translate", {"translated": "T"}),
    ))
    res = SummarizeTranslateSkill().run(ctx, text="hello", to_lang="vi")
    assert res.ok
    assert res.data == {"summary": "S", "translated_summary": "T", "to_lang": "vi"}
    assert [s["tool"] for s in res.steps] == ["summarize", "translate"]


def test_summarize_translate_partial_when_translate_fails():
    ctx = SkillContext(tools=_reg(
        ok_tool("summarize", {"summary": "S"}),
        fail_tool("translate", "boom"),
    ))
    res = SummarizeTranslateSkill().run(ctx, text="hello", to_lang="vi")
    assert res.ok is False
    assert res.data["summary"] == "S"           # partial result preserved
    assert "translate failed" in res.error


def test_summarize_translate_aborts_if_summarize_fails():
    ctx = SkillContext(tools=_reg(
        fail_tool("summarize", "nope"),
        ok_tool("translate", {"translated": "T"}),
    ))
    res = SummarizeTranslateSkill().run(ctx, text="hello")
    assert res.ok is False and "summarize failed" in res.error
    assert len(res.steps) == 1                   # translate never attempted


def test_summarize_translate_summary_only_when_no_language():
    # No to_lang → summarize-only: translate is never called (fix #1).
    ctx = SkillContext(tools=_reg(
        ok_tool("summarize", {"summary": "S"}),
        ok_tool("translate", {"translated": "T"}),
    ))
    res = SummarizeTranslateSkill().run(ctx, text="hello")
    assert res.ok
    assert res.data == {"summary": "S"}          # no translated_summary / to_lang
    assert [s["tool"] for s in res.steps] == ["summarize"]


# ── atomic single-tool actions (summarize / translate / correct) ─────────────────
def test_summarize_skill_wraps_summarize_tool():
    ctx = SkillContext(tools=_reg(ok_tool("summarize", {"summary": "S"})))
    res = SummarizeSkill().run(ctx, text="hello")
    assert res.ok and res.data == {"summary": "S"}
    assert [s["tool"] for s in res.steps] == ["summarize"]


def test_summarize_skill_forwards_summary_mode_to_tool():
    # The Summarize Run Action exposes Fast vs AI Rewrite; the skill must forward the
    # chosen summary_mode to the summarize tool (the layer the HTTP endpoint calls).
    tool = ok_tool("summarize", {"summary": "S"})
    res = SummarizeSkill().run(SkillContext(tools=_reg(tool)),
                               text="hi", summary_mode="ai_rewrite")
    assert res.ok
    assert tool.calls[0]["summary_mode"] == "ai_rewrite"


def test_translate_skill_wraps_translate_tool():
    ctx = SkillContext(tools=_reg(ok_tool("translate", {"translated": "T"})))
    res = TranslateSkill().run(ctx, text="hello", to_lang="vi")
    assert res.ok and res.data == {"translated": "T", "to_lang": "vi"}
    assert [s["tool"] for s in res.steps] == ["translate"]


def test_translate_skill_fails_when_tool_fails():
    ctx = SkillContext(tools=_reg(fail_tool("translate", "boom")))
    res = TranslateSkill().run(ctx, text="hello", to_lang="vi")
    assert res.ok is False and "translate failed" in res.error


def test_correct_skill_wraps_correct_tool():
    ctx = SkillContext(tools=_reg(ok_tool("correct", {"corrected": "C", "changes": 2})))
    res = CorrectSkill().run(ctx, text="raw  txt")
    assert res.ok and res.data == {"corrected": "C", "changes": 2}
    assert [s["tool"] for s in res.steps] == ["correct"]


# ── ocr_digest ──────────────────────────────────────────────────────────────────
def test_ocr_digest_joins_lines_and_summarizes():
    ocr = ok_tool("ocr", {"results": [{"text": "hello"}, {"text": "world"}]})
    summ = ok_tool("summarize", {"summary": "S"})
    ctx = SkillContext(tools=_reg(ocr, summ))
    res = OcrDigestSkill().run(ctx, image_path="/tmp/x.png")
    assert res.ok
    assert res.data["text"] == "hello world"
    assert res.data["summary"] == "S"
    assert "translated_summary" not in res.data  # no to_lang given


def test_ocr_digest_with_translate():
    ctx = SkillContext(tools=_reg(
        ok_tool("ocr", {"text": "full text"}),
        ok_tool("summarize", {"summary": "S"}),
        ok_tool("translate", {"translated": "T"}),
    ))
    res = OcrDigestSkill().run(ctx, image_path="/tmp/x.png", to_lang="vi")
    assert res.ok
    assert res.data["translated_summary"] == "T" and res.data["to_lang"] == "vi"


def test_ocr_digest_no_text_fails():
    ctx = SkillContext(tools=_reg(
        ok_tool("ocr", {"results": []}),
        ok_tool("summarize", {"summary": "S"}),
    ))
    res = OcrDigestSkill().run(ctx, image_path="/tmp/x.png")
    assert res.ok is False and "no text" in res.error.lower()


# ── research (Skills ↔ Knowledge ↔ Tools) ───────────────────────────────────────
def test_research_retrieves_then_digests_and_scopes_tenancy():
    kn = FakeKnowledge([Citation("f1", "alpha text", 0.9), Citation("f2", "beta text", 0.8)])
    ctx = SkillContext(
        tools=_reg(ok_tool("summarize", {"summary": "brief"})),
        allowed_file_ids={"f1", "f2"},
        knowledge=kn,
    )
    res = ResearchSkill().run(ctx, query="what is x?", top_k=2)
    assert res.ok
    assert res.data["answer"] == "brief"
    assert [c["file_id"] for c in res.data["citations"]] == ["f1", "f2"]
    # tenancy + top_k forwarded to the knowledge source
    assert kn.captured["allowed_file_ids"] == {"f1", "f2"}
    assert kn.captured["top_k"] == 2
    assert kn.captured["file_id"] is None        # no scope → whole library


def test_research_scopes_to_owned_file_id():
    # An owned file_id scope is forwarded to retrieval (fix #3).
    kn = FakeKnowledge([Citation("f1", "alpha text", 0.9)])
    ctx = SkillContext(tools=_reg(ok_tool("summarize", {"summary": "b"})),
                       allowed_file_ids={"f1", "f2"}, knowledge=kn)
    res = ResearchSkill().run(ctx, query="q", file_id="f1")
    assert res.ok and kn.captured["file_id"] == "f1"


def test_research_drops_unowned_file_id_scope():
    # A file_id the caller doesn't own is ignored (tenancy guard), not searched.
    kn = FakeKnowledge([Citation("f1", "alpha text", 0.9)])
    ctx = SkillContext(tools=_reg(ok_tool("summarize", {"summary": "b"})),
                       allowed_file_ids={"f1"}, knowledge=kn)
    res = ResearchSkill().run(ctx, query="q", file_id="not-mine")
    assert res.ok and kn.captured["file_id"] is None


# ── docqa (chat-based Document QA, single-shot) ───────────────────────────────────
def test_docqa_answers_via_chat_whole_library():
    chat = ok_tool("chat", {"answer": "A", "sources": [
        {"file_id": "f1", "score": 0.9, "excerpt": "x"}]})
    ctx = SkillContext(tools=_reg(chat), allowed_file_ids={"f1", "f2"})
    res = DocQaSkill().run(ctx, query="what is x?")
    assert res.ok
    assert res.data["answer"] == "A"
    assert res.data["citations"] == [{"file_id": "f1", "score": 0.9, "excerpt": "x"}]
    call = chat.calls[0]
    assert call["mode"] == "doc_all" and call["file_id"] is None       # no scope → library
    assert call["allowed_file_ids"] == {"f1", "f2"}                    # tenancy forwarded
    assert "history" not in call                                       # single-shot


def test_docqa_scopes_to_owned_file_id():
    chat = ok_tool("chat", {"answer": "A", "sources": []})
    ctx = SkillContext(tools=_reg(chat), allowed_file_ids={"f1"})
    res = DocQaSkill().run(ctx, query="q", file_id="f1")
    assert res.ok
    assert chat.calls[0]["file_id"] == "f1" and chat.calls[0]["mode"] == "doc_current"


def test_docqa_drops_unowned_file_id_to_library():
    chat = ok_tool("chat", {"answer": "A", "sources": []})
    ctx = SkillContext(tools=_reg(chat), allowed_file_ids={"f1"})
    res = DocQaSkill().run(ctx, query="q", file_id="not-mine")
    assert res.ok
    assert chat.calls[0]["file_id"] is None and chat.calls[0]["mode"] == "doc_all"


def test_docqa_fails_when_chat_fails():
    ctx = SkillContext(tools=_reg(fail_tool("chat", "boom")), allowed_file_ids=None)
    res = DocQaSkill().run(ctx, query="q")
    assert res.ok is False and "chat failed" in res.error


def test_research_empty_knowledge():
    kn = FakeKnowledge([])
    ctx = SkillContext(tools=_reg(ok_tool("summarize", {"summary": "x"})), knowledge=kn)
    res = ResearchSkill().run(ctx, query="q")
    assert res.ok and res.data["answer"] == "No relevant documents found."
    assert res.data["citations"] == []


def test_research_requires_knowledge_source():
    ctx = SkillContext(tools=_reg(ok_tool("summarize", {"summary": "x"})), knowledge=None)
    res = ResearchSkill().run(ctx, query="q")
    assert res.ok is False and "knowledge" in res.error.lower()


# ── skill registry ──────────────────────────────────────────────────────────────
def test_default_skill_registry():
    reg = build_default_skill_registry()
    assert set(reg.names()) == {"summarize_translate", "ocr_digest", "research",
                                "summarize", "translate", "correct", "docqa"}
    for spec in reg.specs():
        assert spec["description"] and spec["parameters"]["type"] == "object"


def test_get_skill_registry_singleton():
    assert get_skill_registry() is get_skill_registry()


def test_skill_registry_unknown_returns_failure():
    reg = build_default_skill_registry()
    ctx = SkillContext(tools=ToolRegistry())
    res = reg.run("nope", ctx)
    assert res.ok is False and "Unknown skill" in res.error


def test_skill_registry_captures_exceptions():
    from agent.skills.base import Skill, SkillRegistry

    class Boom(Skill):
        name = "boom"
        description = "d"
        parameters = {"type": "object", "properties": {}}

        def run(self, ctx, **_):
            raise RuntimeError("kaboom")

    reg = SkillRegistry()
    reg.register(Boom())
    res = reg.run("boom", SkillContext(tools=ToolRegistry()))
    assert res.ok is False and "kaboom" in res.error and res.meta["skill"] == "boom"


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
