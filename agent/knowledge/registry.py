"""Knowledge registry + composite retrieval (Phase 9).

Generalizes the KnowledgeSource abstraction: several named sources can be
registered, and ``CompositeKnowledge`` retrieves from all of them and returns one
merged, de-duplicated, score-ranked citation list (via ``merge_citations``).

Today only ``DocumentKnowledge`` (the existing RAG over the user's documents) is
registered. Adding a docs/domain source later is a one-line registration — the
knowledge tool and skills retrieve through the composite, so they widen
automatically without further changes. No retrieval logic is duplicated here.
"""

from __future__ import annotations

from typing import List, Optional

from .base import KnowledgeResult, KnowledgeSource, merge_citations


class CompositeKnowledge(KnowledgeSource):
    """Fan a query out to several sources and return merged, ranked citations."""

    name = "composite"

    def __init__(self, sources: List[KnowledgeSource]) -> None:
        self._sources = list(sources)

    def retrieve(self, query: str, *, top_k: int = 5,
                 allowed_file_ids: Optional[set] = None,
                 file_id: Optional[str] = None) -> KnowledgeResult:
        all_citations = []
        names = []
        for src in self._sources:
            try:
                r = src.retrieve(query, top_k=top_k,
                                 allowed_file_ids=allowed_file_ids, file_id=file_id)
            except Exception:                       # one bad source must not break retrieval
                continue
            all_citations.extend(r.citations)
            names.append(src.name)
        merged = merge_citations(all_citations, top_k=top_k)
        return KnowledgeResult(query=query, citations=merged,
                               source="+".join(names) or self.name)


class KnowledgeRegistry:
    """Holds named KnowledgeSources and builds a CompositeKnowledge over them."""

    def __init__(self) -> None:
        self._sources = {}

    def register(self, source: KnowledgeSource) -> KnowledgeSource:
        name = getattr(source, "name", "")
        if not name:
            raise ValueError("KnowledgeSource must define a non-empty .name")
        if name in self._sources:
            raise ValueError(f"Knowledge source {name!r} is already registered")
        self._sources[name] = source
        return source

    def has(self, name: str) -> bool:
        return name in self._sources

    def get(self, name: str) -> KnowledgeSource:
        if name not in self._sources:
            raise KeyError(f"Unknown knowledge source: {name!r}. Available: {self.names()}")
        return self._sources[name]

    def names(self) -> List[str]:
        return sorted(self._sources)

    def sources(self) -> List[KnowledgeSource]:
        return [self._sources[n] for n in self.names()]

    def composite(self) -> CompositeKnowledge:
        return CompositeKnowledge(self.sources())


# ── default registry (lazy singleton) ──────────────────────────────────────────
_DEFAULT_KNOWLEDGE_REGISTRY: Optional[KnowledgeRegistry] = None


def build_default_knowledge_registry() -> KnowledgeRegistry:
    """Registry with the built-in sources. Importing/building it loads no heavy
    stack — DocumentKnowledge imports the RAG service lazily inside retrieve()."""
    from .document_knowledge import DocumentKnowledge

    reg = KnowledgeRegistry()
    reg.register(DocumentKnowledge())
    return reg


def get_knowledge_registry() -> KnowledgeRegistry:
    global _DEFAULT_KNOWLEDGE_REGISTRY
    if _DEFAULT_KNOWLEDGE_REGISTRY is None:
        _DEFAULT_KNOWLEDGE_REGISTRY = build_default_knowledge_registry()
    return _DEFAULT_KNOWLEDGE_REGISTRY
