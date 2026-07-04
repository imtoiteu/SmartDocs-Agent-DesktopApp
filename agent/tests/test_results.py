"""Result-destination mapping tests (Phase 13 — Agent as orchestration layer).

Pure logic only (no Flask/DB): collecting derived outputs from an AgentResult and
mapping persisted artifacts / citations / chat threads to existing-module routes.

Runs under pytest OR standalone (`python agent/tests/test_results.py`).
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

from agent.core.agent import AgentResult, AgentStep  # noqa: E402
from agent.results import (  # noqa: E402
    collect_doc_outputs, doc_artifact_destinations, citation_destinations,
    source_document_destination, chat_destination, dedupe_destinations,
    should_persist_artifact, AGENT_ARTIFACT_META_PREFIX,
)


def _step(tool, data, kind="tool", arguments=None):
    return AgentStep(kind=kind, tool=tool, arguments=arguments or {},
                     observation={"ok": True, "data": data, "error": None, "meta": {}})


# ── collect_doc_outputs ──────────────────────────────────────────────────────
def test_collect_from_tool_observations():
    res = AgentResult(answer="done", steps=[
        _step("summarize", {"summary": "S"}),
        _step("translate", {"translated": "T"}, arguments={"to_lang": "vi"}),
    ])
    out = collect_doc_outputs(res)
    assert out == {"summary": "S", "translation": "T", "to_lang": "vi"}


def test_collect_from_skill_observation():
    res = AgentResult(answer="done", steps=[
        _step("summarize_translate",
              {"summary": "S", "translated_summary": "T", "to_lang": "en"}, kind="skill"),
    ])
    out = collect_doc_outputs(res)
    assert out == {"summary": "S", "translation": "T", "to_lang": "en"}


def test_collect_takes_first_of_each_and_handles_none():
    res = AgentResult(answer="done", steps=[
        _step("summarize", {"summary": "first"}),
        _step("summarize", {"summary": "second"}),   # ignored — first wins
        _step("correct", {"corrected": "X"}),         # not a doc destination
    ])
    out = collect_doc_outputs(res)
    assert out["summary"] == "first"
    assert out["translation"] is None and out["to_lang"] == ""


def test_collect_empty_result():
    assert collect_doc_outputs(AgentResult(answer="hi", steps=[])) == {
        "summary": None, "translation": None, "to_lang": ""}


# ── doc_artifact_destinations ────────────────────────────────────────────────
def test_doc_artifact_destinations_routes_and_labels():
    dests = doc_artifact_destinations(["summary", "translation"], "fid-1", "invoice.pdf")
    assert [d["module"] for d in dests] == ["summarize", "translate"]
    assert dests[0]["route"] == "#summarize/fid-1"
    assert dests[1]["route"] == "#translate/fid-1"
    assert dests[0]["label"] == "Summary · invoice.pdf"
    assert all(d["file_id"] == "fid-1" for d in dests)


def test_doc_artifact_destinations_falls_back_to_file_id_label():
    dests = doc_artifact_destinations(["summary"], "fid-2")
    assert dests[0]["label"] == "Summary · fid-2"


def test_doc_artifact_destinations_ignores_unknown_kinds_and_empty():
    assert doc_artifact_destinations(["ocr", "bogus"], "f") == []
    assert doc_artifact_destinations([], "f") == []
    assert doc_artifact_destinations(None, "f") == []


# ── citation_destinations ────────────────────────────────────────────────────
def test_citation_destinations_dedup_and_order_and_labels():
    cites = [{"file_id": "a", "score": 1}, {"file_id": "b"}, {"file_id": "a"}]
    dests = citation_destinations(cites, labels={"a": "A.pdf"})
    assert [d["file_id"] for d in dests] == ["a", "b"]      # deduped, first-seen order
    assert dests[0]["route"] == "#ocr/a" and dests[0]["label"] == "Source · A.pdf"
    assert dests[1]["label"] == "Source · b"               # no label → file_id


def test_citation_destinations_skips_missing_file_id():
    assert citation_destinations([{"score": 1}, {}, None]) == []
    assert citation_destinations(None) == []


# ── source_document_destination ──────────────────────────────────────────────
def test_source_document_destination_ocr_vs_text():
    # OCR-backed (image / scanned PDF) → "OCR Result".
    d = source_document_destination("fid-9", "scan.png", has_ocr=True)
    assert d == {"module": "ocr", "kind": "ocr", "file_id": "fid-9",
                 "route": "#ocr/fid-9", "label": "OCR Result · scan.png"}
    # Text-backed (DOCX / TXT) → "Extracted Text", NOT mislabelled as OCR.
    t = source_document_destination("fid-7", "memo.docx", has_ocr=False)
    assert t == {"module": "text", "kind": "text", "file_id": "fid-7",
                 "route": "#ocr/fid-7", "label": "Extracted Text · memo.docx"}
    # Default is the OCR branch; label falls back to file_id when unnamed.
    assert source_document_destination("fid-9")["label"] == "OCR Result · fid-9"


# ── chat_destination ─────────────────────────────────────────────────────────
def test_chat_destination():
    d = chat_destination(7, "Quarterly report")
    assert d == {"module": "chat", "kind": "conversation", "conversation_id": 7,
                 "route": "#chat/7", "label": "Conversation · Quarterly report"}
    assert chat_destination(9)["label"] == "Conversation · #9"


# ── should_persist_artifact (non-overwrite policy; review P4) ────────────────
def test_persist_fills_gap_when_no_artifact_exists():
    # No artifact of that kind yet → the agent may write, truncated or not.
    assert should_persist_artifact(False, None) is True
    assert should_persist_artifact(False, None, source_truncated=True) is True


def test_persist_never_overwrites_module_artifact():
    # Summarize/Translate module metas (and legacy None metas) are not agent's —
    # a complete module output must never be replaced by an agent run.
    for meta in ("mode=short;summary_mode=fast", "to=vi;engine=argos", None, ""):
        assert should_persist_artifact(True, meta) is False, repr(meta)
        assert should_persist_artifact(True, meta, source_truncated=True) is False


def test_persist_may_refresh_agents_own_artifact_with_full_context():
    assert should_persist_artifact(True, AGENT_ARTIFACT_META_PREFIX) is True
    assert should_persist_artifact(True, "source=agent;to=vi") is True
    assert should_persist_artifact(True, "source=agent;truncated=1") is True


def test_persist_truncated_context_never_overwrites_anything():
    # Even the agent's own earlier artifact survives a truncated-context run.
    assert should_persist_artifact(True, "source=agent",
                                   source_truncated=True) is False
    assert should_persist_artifact(True, "source=agent;truncated=1",
                                   source_truncated=True) is False


# ── dedupe_destinations ──────────────────────────────────────────────────────
def test_dedupe_destinations_keeps_first_seen_route():
    a = source_document_destination("f", "scan.png")        # #ocr/f (scoped doc)
    b = citation_destinations([{"file_id": "f"}])[0]         # #ocr/f (same route, citation)
    c = chat_destination(3)
    out = dedupe_destinations([a, b, c])
    assert [d["route"] for d in out] == ["#ocr/f", "#chat/3"]
    assert out[0]["label"] == "OCR Result · scan.png"       # first-seen kept
    assert dedupe_destinations([]) == []
    assert dedupe_destinations([{"no": "route"}]) == []


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
