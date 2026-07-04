"""Knowledge layer — retrieval + citation over SmartDocs documents."""

from .base import Citation, KnowledgeResult, KnowledgeSource, merge_citations
from .document_knowledge import DocumentKnowledge
from .registry import (
    CompositeKnowledge,
    KnowledgeRegistry,
    build_default_knowledge_registry,
    get_knowledge_registry,
)

__all__ = [
    "Citation",
    "KnowledgeResult",
    "KnowledgeSource",
    "merge_citations",
    "DocumentKnowledge",
    "CompositeKnowledge",
    "KnowledgeRegistry",
    "build_default_knowledge_registry",
    "get_knowledge_registry",
]
