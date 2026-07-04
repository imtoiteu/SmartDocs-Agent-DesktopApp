"""Result destinations (Phase 13 — Agent as orchestration layer).

Maps an agent run's outputs to the EXISTING SmartDocs module pages, so the agent
orchestrates and the user views each result in the UI that was already built for
that feature (OCR / Translate / Summarize / Chat). The agent page never duplicates
those viewers — it only surfaces a "View Result" link per destination.

A *destination* is a small, JSON-serialisable descriptor::

    {"module": "summarize", "kind": "summary", "file_id": "<uuid>",
     "route": "#summarize/<uuid>", "label": "Summary · invoice.pdf"}

``route`` is the SPA hash the agent page links to (``location.href = "/" + route``)
— the existing hash router (#ocr/#chat already; #translate/#summarize added in
Phase 13) opens the real module viewer, deep-link and reload safe.

These are PURE functions (no Flask / no DB): the persistence layer (agent_bp)
stays thin and this mapping stays unit-testable. Crucially, destinations are
DERIVED from what the run actually produced/persisted — a file_id is never chosen
by the LLM, preserving the file-ownership invariant.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Which existing module page renders each persisted document-artifact kind, and a
# human label for it. Only summary/translation are document-viewable agent outputs
# (correction is an internal step, not a destination — it is not in the module set).
_MODULE_BY_KIND = {"summary": "summarize", "translation": "translate"}
_LABEL_BY_KIND = {"summary": "Summary", "translation": "Translation"}

# Meta prefix the agent stamps on artifacts it persists (agent_bp). The
# Summarize/Translate modules write different metas ("mode=…", "to=…"), so this
# prefix is what lets the non-overwrite policy tell agent output apart.
AGENT_ARTIFACT_META_PREFIX = "source=agent"


def should_persist_artifact(artifact_exists: bool, existing_meta,
                            source_truncated: bool = False) -> bool:
    """Whether the agent may write (create or overwrite) a summary/translation
    artifact for a document.

    Policy: the agent must never clobber an artifact it did not produce — the
    Summarize/Translate modules generate complete outputs from the full text,
    while the agent works from a capped document context. And a run whose
    context WAS truncated may only fill a gap, never replace anything (not even
    the agent's own earlier, possibly complete, output).

    ``artifact_exists`` / ``existing_meta`` describe the current artifact of
    that kind (meta may legitimately be None on an existing artifact, which is
    why existence is a separate flag).
    """
    if not artifact_exists:
        return True
    if source_truncated:
        return False
    return str(existing_meta or "").startswith(AGENT_ARTIFACT_META_PREFIX)


def collect_doc_outputs(result: Any) -> Dict[str, Any]:
    """Scan an ``AgentResult``'s step observations for derived text a document
    module can display: the first summary and the first translation found.

    Handles both the tool shapes (``summarize`` → ``data.summary``; ``translate``
    → ``data.translated``) and the skill shapes (``…`` → ``data.summary`` /
    ``data.translated_summary`` / ``data.to_lang``). ``to_lang`` falls back to the
    translate step's own arguments when the observation omits it.
    """
    summary: Optional[str] = None
    translation: Optional[str] = None
    to_lang: str = ""
    for step in getattr(result, "steps", None) or []:
        obs = getattr(step, "observation", None) or {}
        data = obs.get("data") or {}
        args = getattr(step, "arguments", None) or {}
        if summary is None and data.get("summary"):
            summary = data.get("summary")
        candidate = data.get("translated") or data.get("translated_summary")
        if translation is None and candidate:
            translation = candidate
            to_lang = data.get("to_lang") or args.get("to_lang") or ""
    return {"summary": summary, "translation": translation, "to_lang": to_lang}


def doc_artifact_destinations(written_kinds: Optional[List[str]], file_id: str,
                             doc_label: Optional[str] = None) -> List[dict]:
    """Destinations for persisted document artifacts (summary / translation)."""
    out: List[dict] = []
    name = doc_label or file_id
    for kind in written_kinds or []:
        module = _MODULE_BY_KIND.get(kind)
        if not module:
            continue
        out.append({
            "module": module, "kind": kind, "file_id": file_id,
            "route": f"#{module}/{file_id}",
            "label": f"{_LABEL_BY_KIND[kind]} · {name}",
        })
    return out


def citation_destinations(citations: Optional[List[dict]],
                          labels: Optional[Dict[str, str]] = None) -> List[dict]:
    """One OCR-viewer destination per unique cited source document, in first-seen
    order. Citations without a ``file_id`` are ignored.
    """
    out: List[dict] = []
    seen = set()
    labels = labels or {}
    for c in citations or []:
        fid = (c or {}).get("file_id")
        if not fid or fid in seen:
            continue
        seen.add(fid)
        out.append({
            "module": "ocr", "kind": "ocr", "file_id": fid,
            "route": f"#ocr/{fid}",
            "label": f"Source · {labels.get(fid, fid)}",
            # Marks a corpus-wide retrieval hit (vs a document the session itself
            # produced), so the UI can list it under "Sources" rather than the
            # session's own "Artifacts", and persistence can tag it (Phase 17).
            "origin": "citation",
        })
    return out


# Human label for the source-document card, keyed by the artifact that actually
# backs the document — a real OCR run vs. plain extracted text. This is what stops
# a DOCX/TXT (text-extracted) from being mislabelled as an "OCR" result.
_SOURCE_LABEL = {"ocr": "OCR Result", "text": "Extracted Text"}


def source_document_destination(file_id: str, doc_label: Optional[str] = None,
                                has_ocr: bool = True) -> dict:
    """Destination opening the source document in the existing OCR viewer.

    The module + label reflect what actually backs the document: a real OCR run
    (images / scanned PDFs → ``ocr``) versus plain extracted text (DOCX / TXT /
    read-text → ``text``), so a text document is never mislabelled as OCR. The OCR
    viewer is artifact-driven and renders both, so the SPA route is shared.
    """
    kind = "ocr" if has_ocr else "text"
    return {
        "module": kind, "kind": kind, "file_id": file_id,
        "route": f"#ocr/{file_id}",
        "label": f"{_SOURCE_LABEL[kind]} · {doc_label or file_id}",
    }


def chat_destination(conversation_id: Any, title: Optional[str] = None) -> dict:
    """Destination opening a persisted Chat conversation in the existing Chat view."""
    return {
        "module": "chat", "kind": "conversation",
        "conversation_id": conversation_id,
        "route": f"#chat/{conversation_id}",
        "label": "Conversation · " + (title or f"#{conversation_id}"),
    }


def dedupe_destinations(destinations: List[dict]) -> List[dict]:
    """Drop destinations that point at the same route, keeping first-seen order
    (e.g. the scoped document's OCR view and a citation to the same doc)."""
    out: List[dict] = []
    seen = set()
    for d in destinations or []:
        route = (d or {}).get("route")
        if not route or route in seen:
            continue
        seen.add(route)
        out.append(d)
    return out
