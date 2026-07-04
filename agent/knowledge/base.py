"""Knowledge layer — retrieval + citation abstractions.

Knowledge is NOT business logic (SmartDocs-Agent/CLAUDE.md → Knowledge Layer).
A ``KnowledgeSource`` answers a query with ranked ``Citation`` objects; it never
generates prose. Sources support retrieval, citation and ranking today, and the
interface leaves room for additional vector stores later.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Citation:
    """A single retrieved, attributable piece of evidence."""

    file_id: str
    text: str
    score: float = 0.0

    def excerpt(self, n: int = 200) -> str:
        t = self.text or ""
        return t[:n] + ("…" if len(t) > n else "")

    def to_dict(self) -> Dict[str, Any]:
        return {"file_id": self.file_id, "score": self.score, "excerpt": self.excerpt()}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Citation":
        """Parse a citation-shaped dict ({file_id, score, text|excerpt}).

        Accepts both the Citation wire form (``excerpt``) and a raw ``text`` —
        the chat service's ``sources`` use the same {file_id, score, excerpt}
        shape, so observations from any retrieval path round-trip cleanly.
        """
        d = d or {}
        try:
            score = float(d.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        return cls(file_id=str(d.get("file_id") or ""),
                   text=str(d.get("text") or d.get("excerpt") or ""),
                   score=score)


@dataclass
class KnowledgeResult:
    query: str
    citations: List[Citation] = field(default_factory=list)
    source: Optional[str] = None

    def is_empty(self) -> bool:
        return not self.citations

    def context_text(self, per_chunk: int = 600) -> str:
        """Concatenate citation snippets into a single context block for a
        downstream summarizer/answerer. Each block is tagged with its file_id."""
        blocks = []
        for i, c in enumerate(self.citations, 1):
            blocks.append(f"[{i}] (file {c.file_id})\n{(c.text or '')[:per_chunk]}")
        return "\n\n".join(blocks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "source": self.source,
            "citations": [c.to_dict() for c in self.citations],
        }


def merge_citations(citations: List[Citation], *, top_k: Optional[int] = None) -> List[Citation]:
    """De-duplicate, then rank citations.

    Two citations are considered the same evidence when they share a ``file_id``
    and the same leading text; the higher-scored one is kept. The survivors are
    returned sorted by score descending (the existing RAG convention: higher =
    more relevant), optionally capped to ``top_k``. Used both to merge across
    KnowledgeSources (CompositeKnowledge) and to consolidate the citations an
    agent gathers across steps.
    """
    best: Dict[tuple, Citation] = {}
    for c in citations:
        if not c.file_id:
            continue
        key = (c.file_id, (c.text or "")[:80])
        cur = best.get(key)
        if cur is None or c.score > cur.score:
            best[key] = c
    ranked = sorted(best.values(), key=lambda c: c.score, reverse=True)
    return ranked[:top_k] if top_k else ranked


class KnowledgeSource(ABC):
    name: str = "knowledge"

    @abstractmethod
    def retrieve(self, query: str, *, top_k: int = 5,
                 allowed_file_ids: Optional[set] = None,
                 file_id: Optional[str] = None) -> KnowledgeResult:
        """Return ranked citations for ``query``.

        ``allowed_file_ids`` scopes retrieval to the caller's own documents
        (None = no restriction). ``file_id`` narrows to a single document.
        """
        raise NotImplementedError
