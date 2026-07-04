"""RAG index restart/warm-rebuild tests (review P9).

The vector store is in-memory and lost on backend restart; startup runs
``chat_service.rebuild_indexes_from_db`` (wired in app.py __main__, which the
scripts/ launchers use). These tests cover its testable parts plus real
``retrieve_chunks`` scoping around a SIMULATED restart: the embedding engine and
per-document indexes are replaced with deterministic fakes (no numpy/torch), so
the cache/targeting/tenancy logic runs for real.

Runs under pytest OR standalone (`python agent/tests/test_rag_restart.py`).
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

from services import chat_service  # noqa: E402
from services.chat_service import pick_rebuild_texts, rebuild_index_from_pairs  # noqa: E402


# ── deterministic fakes (no numpy) ────────────────────────────────────────────
class FakeIndex:
    """Stands in for DocumentIndex: returns its chunks with fixed scores."""

    def __init__(self, chunks, score=0.9):
        self.chunks = list(chunks)
        self.score = score

    def search(self, query_emb, top_k=5):
        return [(self.score, c) for c in self.chunks[:top_k]]


class FakeEmbed:
    mode = "fake"

    def embed(self, texts, _label=""):
        return [0.0] * len(texts)          # opaque to FakeIndex.search


def _fake_indexer(cache):
    """An index_document stand-in that installs a FakeIndex into ``cache``."""
    def index(file_id, text, source_label=""):
        cache[file_id] = FakeIndex([text])
        return 1
    return index


class _Patched:
    """Swap chat_service's embedding engine + index cache for a test, restoring
    the real ones afterwards (the shared module state must never leak)."""

    def __enter__(self):
        self._engine = chat_service._embedding_engine
        self._cache_snapshot = dict(chat_service._index_cache)
        chat_service._embedding_engine = FakeEmbed()
        chat_service._index_cache.clear()
        return chat_service._index_cache

    def __exit__(self, *exc):
        chat_service._embedding_engine = self._engine
        chat_service._index_cache.clear()
        chat_service._index_cache.update(self._cache_snapshot)
        return False


# ── pick_rebuild_texts (one text per doc, ocr preferred) ─────────────────────
def test_pick_prefers_ocr_over_text_regardless_of_row_order():
    rows = [("f1", "text", "extracted"), ("f1", "ocr", "ocr-content"),
            ("f2", "ocr", "ocr-2"), ("f2", "text", "text-2")]
    assert pick_rebuild_texts(rows) == [("f1", "ocr-content"), ("f2", "ocr-2")]


def test_pick_skips_empty_and_unknown_kinds():
    rows = [("f1", "ocr", "   "), ("f1", "text", "fallback"),
            ("f2", "summary", "not-a-source"), ("", "ocr", "no-id"),
            ("f3", "text", None)]
    assert pick_rebuild_texts(rows) == [("f1", "fallback")]


def test_pick_preserves_first_seen_order():
    rows = [("b", "text", "B"), ("a", "ocr", "A"), ("b", "ocr", "B-ocr")]
    assert pick_rebuild_texts(rows) == [("b", "B-ocr"), ("a", "A")]


# ── rebuild_index_from_pairs (best-effort per document) ───────────────────────
def test_rebuild_counts_and_survives_a_bad_document():
    seen = []

    def index(file_id, text, source_label=""):
        if file_id == "bad":
            raise ValueError("boom")
        seen.append((file_id, source_label))
        return 1

    n = rebuild_index_from_pairs(
        [("a", "ta"), ("bad", "tb"), ("c", "tc")], _index=index)
    assert n == 2
    assert seen == [("a", "rebuild"), ("c", "rebuild")]


# ── simulated restart: corpus-wide retrieval before / after ──────────────────
def test_corpus_retrieval_before_restart_empty_after_restart_restored_by_rebuild():
    with _Patched() as cache:
        indexer = _fake_indexer(cache)
        # Live indexing (as after OCR/upload): corpus-wide retrieval works.
        indexer("doc-1", "alpha content")
        indexer("doc-2", "beta content")
        assert chat_service.is_indexed("doc-1")
        rows = chat_service.retrieve_chunks("q", allowed_file_ids={"doc-1", "doc-2"})
        assert {fid for _, _, fid in rows} == {"doc-1", "doc-2"}

        # RESTART: the in-memory cache is gone → retrieval finds nothing.
        cache.clear()
        assert not chat_service.is_indexed("doc-1")
        assert chat_service.retrieve_chunks(
            "q", allowed_file_ids={"doc-1", "doc-2"}) == []

        # Warm rebuild from persisted (file_id, kind, content) rows — the same
        # path rebuild_indexes_from_db takes after its DB query.
        pairs = pick_rebuild_texts([("doc-1", "ocr", "alpha content"),
                                    ("doc-2", "text", "beta content")])
        assert rebuild_index_from_pairs(pairs, _index=indexer) == 2
        rows = chat_service.retrieve_chunks("q", allowed_file_ids={"doc-1", "doc-2"})
        assert {fid for _, _, fid in rows} == {"doc-1", "doc-2"}


# ── tenancy during / after restoration ────────────────────────────────────────
def test_restored_index_still_scoped_by_allowed_file_ids():
    with _Patched() as cache:
        indexer = _fake_indexer(cache)
        # The rebuild restores EVERY user's documents into the shared cache —
        # ownership must still be enforced at query time, exactly as live.
        pairs = pick_rebuild_texts([("alice-1", "ocr", "alice doc one"),
                                    ("alice-2", "text", "alice doc two"),
                                    ("bob-1", "ocr", "bob secret doc")])
        rebuild_index_from_pairs(pairs, _index=indexer)

        rows = chat_service.retrieve_chunks("q", allowed_file_ids={"alice-1", "alice-2"})
        fids = {fid for _, _, fid in rows}
        assert fids == {"alice-1", "alice-2"}
        assert "bob-1" not in fids                    # never another user's doc

        # A scope covering nothing indexed → empty, not a widened search.
        assert chat_service.retrieve_chunks("q", allowed_file_ids=set()) == []


def test_document_scoped_targeting_unchanged_after_restore():
    with _Patched() as cache:
        indexer = _fake_indexer(cache)
        rebuild_index_from_pairs([("doc-1", "one"), ("doc-2", "two")],
                                 _index=indexer)
        # file_id targeting searches exactly that one document (the documented
        # single-doc path the ownership guards sit in front of).
        rows = chat_service.retrieve_chunks("q", file_id="doc-1")
        assert {fid for _, _, fid in rows} == {"doc-1"}


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
