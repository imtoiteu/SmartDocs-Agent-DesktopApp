"""Knowledge layer tests (Phase 4).

DocumentKnowledge is tested against a fake ``services.chat_service`` injected
into sys.modules, so no heavy RAG stack is imported.

Runs under pytest OR standalone (`python agent/tests/test_knowledge.py`).
"""

import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import pytest  # noqa: F401
except ImportError:
    pytest = None

from agent.knowledge import (  # noqa: E402
    Citation,
    DocumentKnowledge,
    KnowledgeResult,
    KnowledgeSource,
    CompositeKnowledge,
    KnowledgeRegistry,
    merge_citations,
)


class _FakeSource(KnowledgeSource):
    """A KnowledgeSource returning preset citations, for composite/registry tests."""

    def __init__(self, name, citations):
        self.name = name
        self._citations = citations
        self.last_args = None

    def retrieve(self, query, *, top_k=5, allowed_file_ids=None, file_id=None):
        self.last_args = {"query": query, "top_k": top_k,
                          "allowed_file_ids": allowed_file_ids, "file_id": file_id}
        return KnowledgeResult(query=query, citations=list(self._citations), source=self.name)


def _with_fake_chat_service(rows):
    """Return (fake_module, restore_fn). retrieve_chunks records its args."""
    mod = types.ModuleType("services.chat_service")
    captured = {}

    def retrieve_chunks(query, file_id=None, top_k=5, allowed_file_ids=None):
        captured["args"] = {"query": query, "file_id": file_id,
                            "top_k": top_k, "allowed_file_ids": allowed_file_ids}
        return rows

    mod.retrieve_chunks = retrieve_chunks
    mod.captured = captured

    old = sys.modules.get("services.chat_service")

    def restore():
        if old is not None:
            sys.modules["services.chat_service"] = old
        else:
            sys.modules.pop("services.chat_service", None)

    sys.modules["services.chat_service"] = mod
    return mod, restore


def test_citation_excerpt_and_to_dict():
    c = Citation(file_id="f1", text="x" * 250, score=0.5)
    assert c.excerpt(10) == "x" * 10 + "…"
    assert c.to_dict() == {"file_id": "f1", "score": 0.5, "excerpt": "x" * 200 + "…"}


def test_document_knowledge_maps_and_scopes():
    fake, restore = _with_fake_chat_service([(0.91, "alpha", "f1"), (0.80, "beta", "f2")])
    try:
        kr = DocumentKnowledge().retrieve("q", top_k=3, allowed_file_ids={"f1", "f2"})
    finally:
        restore()
    assert isinstance(kr, KnowledgeResult)
    assert [c.file_id for c in kr.citations] == ["f1", "f2"]
    assert [c.text for c in kr.citations] == ["alpha", "beta"]
    assert kr.citations[0].score == 0.91
    # tenancy + top_k passed straight through to the existing RAG
    assert fake.captured["args"]["top_k"] == 3
    assert fake.captured["args"]["allowed_file_ids"] == {"f1", "f2"}
    assert not kr.is_empty()


def test_document_knowledge_empty():
    fake, restore = _with_fake_chat_service([])
    try:
        kr = DocumentKnowledge().retrieve("q")
    finally:
        restore()
    assert kr.is_empty()
    assert kr.context_text() == ""
    assert kr.to_dict()["citations"] == []


def test_context_text_tags_sources():
    kr = KnowledgeResult(query="q", source="documents", citations=[
        Citation(file_id="fA", text="hello world", score=0.9),
        Citation(file_id="fB", text="second snippet", score=0.7),
    ])
    ctx = kr.context_text()
    assert "(file fA)" in ctx and "(file fB)" in ctx
    assert "hello world" in ctx and "second snippet" in ctx


# ── Phase 9: from_dict / merge / registry / composite ───────────────────────────
def test_citation_from_dict_accepts_excerpt_or_text():
    a = Citation.from_dict({"file_id": "f1", "score": "0.9", "excerpt": "hello"})
    assert a.file_id == "f1" and a.text == "hello" and a.score == 0.9
    b = Citation.from_dict({"file_id": "f2", "text": "world"})
    assert b.text == "world" and b.score == 0.0
    # malformed score → 0.0, missing file_id → empty string
    c = Citation.from_dict({"score": "n/a"})
    assert c.file_id == "" and c.score == 0.0


def test_merge_citations_dedupes_keeps_highest_and_ranks():
    cits = [
        Citation("f1", "alpha", 0.70),
        Citation("f2", "beta", 0.80),
        Citation("f1", "alpha", 0.95),   # dup of the first (same file+text) — higher score
        Citation("", "no file", 0.99),   # dropped: no file_id
    ]
    merged = merge_citations(cits)
    assert [c.file_id for c in merged] == ["f1", "f2"]      # ranked by score desc
    assert merged[0].score == 0.95                          # kept the higher dup
    assert merge_citations(cits, top_k=1)[0].file_id == "f1"


def test_knowledge_registry_register_get_names_and_dups():
    reg = KnowledgeRegistry()
    s1 = _FakeSource("docs", [])
    reg.register(s1)
    assert reg.has("docs") and reg.get("docs") is s1 and reg.names() == ["docs"]
    try:
        reg.register(_FakeSource("docs", []))
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate source name must raise")


def test_composite_merges_ranks_and_passes_scope():
    s1 = _FakeSource("docs", [Citation("f1", "alpha", 0.70), Citation("f2", "beta", 0.60)])
    s2 = _FakeSource("notes", [Citation("f1", "alpha", 0.95), Citation("f3", "gamma", 0.50)])
    reg = KnowledgeRegistry(); reg.register(s1); reg.register(s2)
    kr = reg.composite().retrieve("q", top_k=10, allowed_file_ids={"f1"})
    assert [c.file_id for c in kr.citations] == ["f1", "f2", "f3"]   # merged + ranked
    assert kr.citations[0].score == 0.95                            # cross-source dedupe
    assert kr.source == "docs+notes"
    # tenancy + query forwarded to every source
    assert s1.last_args["allowed_file_ids"] == {"f1"}
    assert s2.last_args["query"] == "q"


def test_composite_survives_a_failing_source():
    class Boom(KnowledgeSource):
        name = "boom"
        def retrieve(self, query, *, top_k=5, allowed_file_ids=None, file_id=None):
            raise RuntimeError("down")
    good = _FakeSource("docs", [Citation("f1", "alpha", 0.9)])
    kr = CompositeKnowledge([Boom(), good]).retrieve("q")
    assert [c.file_id for c in kr.citations] == ["f1"]   # bad source skipped, good one kept


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
