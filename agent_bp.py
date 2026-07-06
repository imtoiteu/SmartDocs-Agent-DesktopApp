"""
SmartDocs Platform — Agent Blueprint (Phase 5, additive HTTP surface)
====================================================================
Exposes the Agent Core, Tools and Skills over login-protected JSON endpoints,
plus a standalone Agent page. Existing routes, services and screens are untouched.

Security
--------
* Tenancy — chat / knowledge_search retrieval is scoped to the caller's own
  documents via ``_owned_file_ids()`` (admins → None = all). Reuses chat_bp's
  single source of truth; the client can never supply ``allowed_file_ids``.
* No raw filesystem paths from clients — the LLM-driven ``/api/agent/run`` uses a
  SAFE tool subset (translate, summarize, chat, knowledge_search) and NEVER the
  path-based OCR tool. Document skills accept a ``file_id`` which is resolved to
  an owned on-disk path via ``app._resolve_owned_file`` (the same IDOR/traversal
  guard every file endpoint uses).
"""

from __future__ import annotations

import logging
from typing import Optional

from flask import Blueprint, request, jsonify, send_from_directory, current_app
from flask_login import login_required, current_user

from config import cfg
from models import (log_activity, AgentConversation, ChatConversation, Document,
                    DocumentArtifact, save_artifact, get_or_create_agent_conversation,
                    get_or_create_conversation, add_message,
                    add_agent_artifacts, rename_agent_conversation,
                    delete_agent_conversation)
from chat_bp import _owned_file_ids, _owned_document_or_error   # reuse tenancy logic

from agent.tools import get_registry, ToolRegistry
from agent.core import AgentCore
from agent.core.llm_gateway import provider_for_task
from agent.skills import get_skill_registry, SkillContext, SkillRegistry
from agent.knowledge import get_knowledge_registry
from agent.memory import ConversationMemory
from agent.results import (collect_doc_outputs, doc_artifact_destinations,
                           citation_destinations, source_document_destination,
                           chat_destination, dedupe_destinations,
                           should_persist_artifact, AGENT_ARTIFACT_META_PREFIX)
from agent.ocr_routing import select_ocr_engine
from agent.progress import get_progress_registry, RUN_ID_RE

logger = logging.getLogger(__name__)
agent_bp = Blueprint("agent", __name__)

# Tools the LLM-driven loop may use over HTTP: text-in/text-out or tenant-scoped
# retrieval only — never the path-based OCR tool (would allow arbitrary file read).
_SAFE_TOOL_NAMES = ("translate", "summarize", "chat", "knowledge_search", "correct")

# Skills the LLM-driven loop may select. NONE — the agent is a pure tool
# orchestrator: it does Document QA via the 'chat' tool, gathers evidence via
# 'knowledge_search', and chains summarize/translate/correct tools itself. Every
# built-in skill (summarize_translate, ocr_digest, research, and the thin atomic
# wrappers) stays registered for rollback but is unexposed to the agent. AgentCore
# omits the skills section entirely when this is empty.
_AGENT_SKILL_NAMES: tuple = ()

# Skills runnable over HTTP (the "Run an action" surface), and whether each needs a
# document (file_id). Atomic, single-purpose capabilities only — summarize / translate
# / correct are thin text-in/text-out wrappers over the same-named tools. OCR is NOT a
# skill here — it is served by the existing OCR pipeline (/api/ocr/all), so its results
# are persisted + RAG-indexed exactly like the normal upload workflow.
#
# Document QA is intentionally NOT a Run Action: conversational document Q&A lives in
# the Chat experience (Document Chat, multi-turn), and the Agent orchestrates retrieval
# itself. docqa / research / knowledge_search / summarize_translate / ocr_digest are
# implementation details kept registered for rollback but unexposed to this surface.
_HTTP_SKILLS = {
    "summarize": {"needs_file": False},
    "translate": {"needs_file": False},
    "correct":   {"needs_file": False},
}

_safe_registry_cache: Optional[ToolRegistry] = None
_safe_skill_registry_cache: Optional[SkillRegistry] = None


def _safe_registry() -> ToolRegistry:
    """A registry containing only the HTTP-safe tools (built from the default)."""
    global _safe_registry_cache
    if _safe_registry_cache is None:
        full = get_registry()
        safe = ToolRegistry()
        for name in _SAFE_TOOL_NAMES:
            safe.register(full.get(name))
        _safe_registry_cache = safe
    return _safe_registry_cache


def _safe_skill_registry() -> SkillRegistry:
    """A registry of only the agent-selectable skills (no raw-path skills)."""
    global _safe_skill_registry_cache
    if _safe_skill_registry_cache is None:
        full = get_skill_registry()
        safe = SkillRegistry()
        for name in _AGENT_SKILL_NAMES:
            safe.register(full.get(name))
        _safe_skill_registry_cache = safe
    return _safe_skill_registry_cache


def _agent_skill_context() -> SkillContext:
    """Base SkillContext for agent-selected skills. Uses the SAFE tool registry
    (so a skill cannot reach the raw OCR tool) and the document knowledge source;
    the per-run tenancy scope (allowed_file_ids) is injected by AgentCore."""
    return SkillContext(tools=_safe_registry(), allowed_file_ids=None,
                        knowledge=get_knowledge_registry().composite(),
                        provider=provider_for_task("agent"))


def _may_write_artifact(doc_id: int, kind: str, source_truncated: bool) -> bool:
    """Apply the non-overwrite policy (agent.results.should_persist_artifact) to
    the document's CURRENT artifact of ``kind``: never clobber a module-produced
    artifact, and a truncated-context run may only fill a gap."""
    art = DocumentArtifact.query.filter_by(document_id=doc_id, kind=kind).first()
    return should_persist_artifact(art is not None,
                                   art.meta if art is not None else None,
                                   source_truncated)


def _persist_doc_outputs(doc, summary=None, translation=None, to_lang="",
                         source_truncated=False) -> list:
    """Persist an agent's NEW derived outputs (summary / translation) as document
    artifacts via ``models.save_artifact`` (upsert by document+kind), so agent work
    is durable and shows up in the normal document viewer (Phase 8 / 13).

    Overwrite-guarded: a summary/translation the user made via the Summarize /
    Translate modules (complete, full-text outputs) is never replaced, and a run
    whose document context was truncated (``source_truncated``) never overwrites
    anything — the agent's answer still carries its output; it just isn't allowed
    to clobber a durable artifact with a partial one.

    Deliberately does NOT touch the canonical 'ocr' text artifact — that stays the
    authoritative RAG/chat/translate/summary input and must not be clobbered by the
    agent path. Best-effort; returns the kinds written. ``doc`` is already
    ownership-checked by the caller.
    """
    trunc_tag = ";truncated=1" if source_truncated else ""
    written = []
    if (summary and _may_write_artifact(doc.id, "summary", source_truncated)
            and save_artifact(doc.id, "summary", summary,
                              meta=AGENT_ARTIFACT_META_PREFIX + trunc_tag)):
        written.append("summary")
    if (translation and _may_write_artifact(doc.id, "translation", source_truncated)
            and save_artifact(doc.id, "translation", translation,
                              meta=f"{AGENT_ARTIFACT_META_PREFIX};to={to_lang}" + trunc_tag)):
        written.append("translation")
    return written


def _persist_skill_artifacts(fid: str, data: dict) -> list:
    """Persist a single skill's derived outputs for an owned document (Phase 8).

    Thin wrapper over ``_persist_doc_outputs`` for the skill-result shape
    (``summary`` / ``translated_summary`` / ``to_lang``). ``fid`` is already
    ownership-checked. Returns the kinds written.
    """
    if not fid or not isinstance(data, dict):
        return []
    doc = Document.query.filter_by(file_id=fid).first()
    if not doc:
        return []
    return _persist_doc_outputs(doc, summary=data.get("summary"),
                                translation=data.get("translated_summary"),
                                to_lang=data.get("to_lang") or "")


def _cited_filenames(citations) -> dict:
    """Map cited file_ids → display filename, for owned docs only (defense in depth;
    citations already come from tenancy-scoped retrieval). Used for result labels.
    """
    fids = {(c or {}).get("file_id") for c in (citations or [])}
    fids.discard(None)
    if not fids:
        return {}
    rows = Document.query.filter(Document.file_id.in_(list(fids))).all()
    is_admin = getattr(current_user, "role", None) == "admin"
    return {d.file_id: d.filename for d in rows
            if d.user_id == current_user.id or is_admin}


def _persist_agent_chat(doc, message: str, result):
    """Persist the agent's retrieval answer as a Chat thread so the user can open
    it in the EXISTING Chat viewer (Phase 13 — RAG destination). A fresh thread is
    created per run (``force_new``) so agent answers never pollute the user's manual
    chat threads. Sources are stored in the {file_id, score, excerpt} shape the chat
    viewer already renders. Best-effort → returns the conversation, or None.
    """
    try:
        document_id = doc.id if doc is not None else None
        label = doc.filename if doc is not None else None
        mode = "doc_current" if document_id is not None else "doc_all"
        conv = get_or_create_conversation(current_user.id, document_id=document_id,
                                          mode=mode, document_label=label,
                                          force_new=True)
        if conv is None:
            return None
        add_message(conv.id, "user", message, mode=mode, set_title_if_empty=True)
        add_message(conv.id, "assistant", result.answer or "",
                    sources=result.citations, mode=mode,
                    engine_used=getattr(result, "provider", None))
        return conv
    except Exception:                          # chat persistence must never break a run
        logger.warning("[AgentBP] agent→chat persistence failed", exc_info=True)
        return None


def _doc_text(doc) -> str:
    """The document's extracted text for the agent to act on — the canonical OCR
    artifact, falling back to plain extracted 'text'. '' when none yet."""
    art = (DocumentArtifact.query.filter_by(document_id=doc.id, kind="ocr").first()
           or DocumentArtifact.query.filter_by(document_id=doc.id, kind="text").first())
    return ((art.content if art else "") or "").strip()


def _ensure_indexed(doc) -> bool:
    """Make ``doc`` queryable for RAG, REUSING its persisted OCR / extracted text
    (never re-runs OCR). Returns True if the document is — or becomes — present in
    the in-memory index.

    Indexing is SYNCHRONOUS, so retrieval running immediately afterwards is
    guaranteed to find the document: the auto-index after OCR / read-text is a
    background thread that may not have finished yet, and a scoped retrieval over an
    unindexed file_id finds nothing. Best-effort — returns False when no text exists
    yet (caller must produce it) or indexing fails. ``doc`` is ownership-checked by
    the caller."""
    from services import chat_service
    fid = doc.file_id
    if chat_service.is_indexed(fid):
        return True
    text = _doc_text(doc)
    if not text:
        return False
    try:
        chat_service.index_document(fid, text, source_label="ensure-indexed")
    except Exception:                          # indexing must never break the caller
        logger.warning(f"[AgentBP] ensure-indexed failed for {fid}", exc_info=True)
        return False
    return chat_service.is_indexed(fid)


def _source_doc_kind(doc):
    """Which artifact actually backs the document, for the source-document card:
    'ocr' (a real OCR run — images / scanned PDFs), 'text' (plain extracted text —
    DOCX / TXT / read-text), or None (nothing persisted yet). The single source of
    truth shared by the run path AND the ingest path so they label identically and
    a text document is never surfaced as an 'OCR' result."""
    if DocumentArtifact.query.filter_by(document_id=doc.id, kind="ocr").first():
        return "ocr"
    if DocumentArtifact.query.filter_by(document_id=doc.id, kind="text").first():
        return "text"
    return None


# How much of a scoped document's text to feed the agent's context, so the LLM can
# summarize/translate/answer about "this document" via the existing text tools
# without the user ever typing a file_id. Capped to keep prompts (and Groq TPM) sane.
_DOC_CONTEXT_MAX_CHARS = 6000

# Newest session turns fed back to the agent as context. Matches the Chat
# feature's history window (chat_service._MAX_HISTORY_MESSAGES); older turns stay
# stored and visible in the transcript — they just don't ride along in the prompt.
_MAX_HISTORY_TURNS = 12

# Default steps for a run when the client sends none. MUST match the agent
# page's visible default (static/agent.html #steps value / agent.js fallback) —
# test_progress_and_defaults.py pins all three together.
_DEFAULT_MAX_STEPS = 3


def _document_context_message(doc):
    """A synthetic user turn carrying the scoped document's text, plus whether the
    text had to be truncated to fit — ``(message, truncated)``, or ``(None, False)``
    when the document has no text yet. The truncated flag feeds the artifact
    non-overwrite policy: a partial-context output must never replace a complete
    artifact. Lets the agent operate on the attached document by reference."""
    text = _doc_text(doc)
    if not text:
        return None, False
    truncated = len(text) > _DOC_CONTEXT_MAX_CHARS
    if truncated:
        text = text[:_DOC_CONTEXT_MAX_CHARS] + "\n…(truncated)"
    note = (f'The user attached a document named "{doc.filename}". When the user '
            f'refers to "this document"/"this file"/"it", use the text below as the '
            f'content to summarize, translate, correct or answer about'
            + (" (note: the text was truncated)." if truncated else ".")
            + f"\n\n--- BEGIN DOCUMENT ---\n{text}\n--- END DOCUMENT ---")
    return {"role": "user", "content": note}, truncated


def _run_result_destinations(doc, message: str, result,
                             source_truncated: bool = False) -> list:
    """Build the 'View Result' destinations for a finished agent run (Phase 13/14).

    Derived entirely from what the run produced/persisted — the LLM never chooses a
    file_id or route, preserving the file-ownership invariant:
      * the scoped document itself (when it has OCR) → OCR viewer;
      * document-scoped summary/translation → Summarize / Translate viewers;
      * each cited source document → OCR viewer;
      * the answer (when it has citations) → a persisted Chat conversation.
    Routes are de-duplicated (e.g. the scoped doc may also appear as a citation).
    """
    results = []
    if doc is not None:
        outs = collect_doc_outputs(result)
        written = _persist_doc_outputs(doc, summary=outs["summary"],
                                       translation=outs["translation"],
                                       to_lang=outs["to_lang"],
                                       source_truncated=source_truncated)
        # Surface the source document in the existing viewer when it has any backing
        # text, labelled by what actually backs it — a real OCR run vs. plain
        # extracted text (so a DOCX/TXT is "Extracted Text", never "OCR").
        src_kind = _source_doc_kind(doc)
        if src_kind:
            results.append(source_document_destination(
                doc.file_id, doc.filename, has_ocr=(src_kind == "ocr")))
        results += doc_artifact_destinations(written, doc.file_id, doc.filename)
    citations = getattr(result, "citations", None) or []
    if citations:
        results += citation_destinations(citations, _cited_filenames(citations))
        conv = _persist_agent_chat(doc, message, result)
        if conv is not None:
            results.append(chat_destination(conv.id, conv.title))
    return dedupe_destinations(results)


def _chat_id_from_route(route):
    """Parse the chat conversation id out of a '#chat/<id>' route, or None."""
    if not route or "#chat/" not in route:
        return None
    try:
        return int(route.rsplit("/", 1)[-1])
    except (TypeError, ValueError):
        return None


def _annotate_artifact_availability(messages: list) -> None:
    """Mark each persisted artifact as still-openable (F6), mutating the message
    dicts in place. A card whose target document / chat was deleted (or is no
    longer owned) gets ``available=False`` so the UI can disable it instead of
    opening an empty or broken viewer. Best-effort and fail-open: on any error the
    artifacts are left without the flag (treated as available, the prior behaviour).
    """
    try:
        arts = [a for m in (messages or []) for a in (m.get("artifacts") or [])]
        if not arts:
            return
        is_admin = getattr(current_user, "role", None) == "admin"

        fids = {a.get("file_id") for a in arts if a.get("file_id")}
        owned_fids = set()
        if fids:
            rows = Document.query.filter(Document.file_id.in_(list(fids))).all()
            owned_fids = {d.file_id for d in rows
                          if d.user_id == current_user.id or is_admin}

        chat_ids = {cid for a in arts
                    if (cid := _chat_id_from_route(a.get("route"))) is not None}
        owned_chat_ids = set()
        if chat_ids:
            crows = ChatConversation.query.filter(
                ChatConversation.id.in_(list(chat_ids))).all()
            owned_chat_ids = {c.id for c in crows
                              if c.user_id == current_user.id or is_admin}

        for a in arts:
            cid = _chat_id_from_route(a.get("route"))
            if cid is not None:
                a["available"] = cid in owned_chat_ids
            elif a.get("file_id"):
                a["available"] = a.get("file_id") in owned_fids
            else:
                a["available"] = True            # label-only chip (no link to check)
    except Exception:                            # never break a reopen over this
        logger.warning("[AgentBP] artifact availability annotation failed",
                       exc_info=True)


def _owned_agent_conversation_or_error(conv_id):
    """Fetch an agent session owned by the caller, or return an error tuple.

    Returns (conv, None) on success or (None, (response, status)) on failure,
    mirroring chat_bp._owned_conversation_or_error (admins may access any).
    """
    conv = AgentConversation.query.get(conv_id)
    if conv is None:
        return None, (jsonify({"success": False, "error": "not found"}), 404)
    if conv.user_id != current_user.id and current_user.role != "admin":
        return None, (jsonify({"success": False, "error": "Permission denied"}), 403)
    return conv, None


# ── Introspection ───────────────────────────────────────────────────────────────
@agent_bp.route("/api/agent/tools", methods=["GET"])
@login_required
def agent_tools():
    return jsonify({"success": True, "tools": _safe_registry().specs()})


@agent_bp.route("/api/agent/ocr-engine", methods=["GET"])
@login_required
def agent_ocr_engine():
    """Resolve which OCR engine a request maps to (default GLM; Vietnamese → VietOCR;
    explicit always wins). Lets the agent page pick the engine for upload OCR without
    duplicating the routing rules client-side. Query: ?message=…&engine=…(optional)."""
    res = select_ocr_engine(request.args.get("message") or "",
                            request.args.get("engine"))
    return jsonify({"success": True, **res})


def _supported_languages() -> list:
    """Target language codes the translator supports offline — the single source
    of truth lives in ``translate_service``. Used to populate the skill UI's
    language picker so users choose a supported language instead of typing a
    free-text code that would silently fail. Falls back to the known set."""
    try:
        from services import translate_service
        return sorted(translate_service._ARGOS_CODES)
    except Exception:
        return ["de", "en", "es", "fr", "ja", "ko", "vi", "zh"]


@agent_bp.route("/api/agent/index-status", methods=["GET"])
@login_required
def agent_index_status():
    """Report whether an owned document is in the RAG index yet. The auto-index
    after OCR / read-text runs asynchronously, so the UI polls this to wait out
    that window before the first retrieval — an 'upload then immediately ask' flow
    must not miss the just-uploaded document. Query: ?file_id=…"""
    fid = (request.args.get("file_id") or "").strip()
    doc, err = _owned_document_or_error(fid)
    if err:
        return err
    from services import chat_service
    return jsonify({"success": True, "indexed": chat_service.is_indexed(fid)})


@agent_bp.route("/api/agent/ensure-indexed", methods=["POST"])
@login_required
def agent_ensure_indexed():
    """Make an owned document queryable for Document Chat — REUSING its existing OCR.

    Document Chat must be scoped to exactly one document, so the document has to be
    in the RAG index before the first question (``retrieve_chunks`` silently widens to
    an all-documents search when a file_id isn't indexed). This:
      * reports ``indexed`` when the document is already in the in-memory index;
      * otherwise re-indexes it from the persisted OCR / extracted-text artifact
        (cheap; never re-runs OCR), satisfying "reuse the existing OCR output";
      * reports ``needs_ocr`` when no text exists yet, so the caller runs the OCR /
        text-extraction pipeline first.
    Ownership-checked — the client never bypasses tenancy via a raw file_id.
    """
    data = request.get_json(silent=True) or {}
    fid = (data.get("file_id") or "").strip()
    doc, err = _owned_document_or_error(fid)
    if err:
        return err
    if _ensure_indexed(doc):
        return jsonify({"success": True, "indexed": True})
    # No OCR / extracted text yet — the caller must produce it first (run OCR / extract).
    return jsonify({"success": True, "indexed": False, "needs_ocr": True})


@agent_bp.route("/api/agent/progress/<run_id>", methods=["GET"])
@login_required
def agent_progress(run_id):
    """Live progress for an in-flight agent run (owner-scoped). ``progress`` is
    null for an unknown / expired / foreign run — the client just keeps its
    generic spinner text in that case."""
    prog = get_progress_registry().get(run_id, current_user.id)
    return jsonify({"success": True, "progress": prog})


@agent_bp.route("/api/agent/skills", methods=["GET"])
@login_required
def agent_skills():
    out = []
    for spec in get_skill_registry().specs():
        cfg_ = _HTTP_SKILLS.get(spec["name"])
        out.append({**spec,
                    "http_runnable": cfg_ is not None,
                    "needs_file": bool(cfg_ and cfg_["needs_file"])})
    return jsonify({"success": True, "skills": out,
                    "languages": _supported_languages()})


# ── Agent sessions (durable memory; Phase 6) ─────────────────────────────────────
@agent_bp.route("/api/agent/conversations", methods=["GET"])
@login_required
def agent_conversations():
    """List the caller's agent sessions, newest-activity first."""
    convs = (AgentConversation.query
             .filter_by(user_id=current_user.id)
             .order_by(AgentConversation.updated_at.desc())
             .all())
    return jsonify({"success": True,
                    "conversations": [c.to_dict() for c in convs]})


@agent_bp.route("/api/agent/conversations/<int:conv_id>", methods=["GET"])
@login_required
def agent_conversation(conv_id):
    """Return one owned agent session with its full message history."""
    conv, err = _owned_agent_conversation_or_error(conv_id)
    if err:
        return err
    msgs = [m.to_dict() for m in conv.messages]
    _annotate_artifact_availability(msgs)        # flag cards whose target is gone (F6)
    return jsonify({"success": True,
                    "conversation": conv.to_dict(),
                    "messages": msgs})


@agent_bp.route("/api/agent/conversations/<int:conv_id>", methods=["PATCH"])
@login_required
def agent_conversation_rename(conv_id):
    """Rename an owned agent session (title only). Body: {title}."""
    conv, err = _owned_agent_conversation_or_error(conv_id)
    if err:
        return err
    title = ((request.get_json(silent=True) or {}).get("title") or "").strip()
    if not title:
        return jsonify({"success": False, "error": "title required"}), 400
    ok = rename_agent_conversation(conv, title)
    return jsonify({"success": ok, "conversation": conv.to_dict()})


@agent_bp.route("/api/agent/conversations/<int:conv_id>", methods=["DELETE"])
@login_required
def agent_conversation_delete(conv_id):
    """Delete an owned agent session: its history + file/artifact references only.
    The underlying document artifacts (OCR/summary/translation) are NOT touched."""
    conv, err = _owned_agent_conversation_or_error(conv_id)
    if err:
        return err
    ok = delete_agent_conversation(conv)
    log_activity("agent_session_delete", f"conv={conv_id} ok={ok}")
    return jsonify({"success": ok})


# ── Agent run (LLM-driven, safe tool subset) ─────────────────────────────────────
@agent_bp.route("/api/agent/run", methods=["POST"])
@login_required
def agent_run():
    """Body: {message, conversation_id?, history?, max_steps?, file_id?}.

    Durable memory (Phase 6): when a ``conversation_id`` is supplied (or once one
    is created for a fresh request) the session's prior turns are loaded from
    storage and the new turn is persisted, so the agent has multi-turn context
    across separate requests. The owned session id is returned for the client to
    send back on the next turn.

    Orchestration → results (Phase 13): an optional ``file_id`` scopes the run to a
    document the caller owns. After the run, derived outputs are persisted via the
    existing artifact pipeline and a ``results`` list of "View Result" destinations
    (existing-module routes) is returned, so the agent orchestrates and the user
    views each result in the UI already built for that feature.
    """
    # Feature switch (cross-platform): a clear JSON answer, never a crash.
    if not cfg.ENABLE_AGENT:
        return jsonify({
            "success": False, "disabled": True,
            "error": "The Agent is disabled on this installation "
                     "(ENABLE_AGENT=false or LLM_PROVIDER=disabled in .env).",
        }), 503

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    client_history = data.get("history")
    if not isinstance(client_history, list):
        client_history = []
    try:
        max_steps = int(data.get("max_steps") or _DEFAULT_MAX_STEPS)
    except (TypeError, ValueError):
        max_steps = _DEFAULT_MAX_STEPS
    max_steps = max(1, min(max_steps, 6))

    if not message:
        return jsonify({"success": False, "error": "message required"}), 400

    # ── Optional document scope (ownership-checked; the LLM never sees a path) ──
    fid = (data.get("file_id") or "").strip()
    doc = None
    if fid:
        doc, err = _owned_document_or_error(fid)
        if err:
            return err

    # ── Resolve the durable session (ownership-checked) ───────────────────────
    # A NEW session is created LAZILY, only when there is something to persist (a
    # produced turn or a recorded failure). A run that errors before producing
    # anything therefore never leaves an empty "ghost" session in the sidebar (F5).
    conv_id = data.get("conversation_id")
    conv = None
    if conv_id is not None:
        conv, err = _owned_agent_conversation_or_error(conv_id)
        if err:
            return err

    memory = ConversationMemory()
    # Prefer stored history; fall back to client-supplied history only on a brand
    # new session (backward-compatible with the prior stateless contract). The
    # window is BOUNDED — a long-lived session must not replay itself whole into
    # every prompt (local models truncate; cloud models bill/ratelimit by token).
    history = memory.load_history(conv.id, limit=_MAX_HISTORY_TURNS) if conv else []
    if not history and client_history:
        history = client_history[-_MAX_HISTORY_TURNS:]

    # Attach the scoped document's text (ephemeral, not persisted to memory) right
    # before the user's request, so the agent can act on "this document" via the
    # existing text tools — the user never types a file_id. doc_ctx_truncated
    # gates artifact persistence: a partial context must not clobber artifacts.
    doc_ctx_truncated = False
    if doc is not None:
        ctx_msg, doc_ctx_truncated = _document_context_message(doc)
        if ctx_msg:
            history = list(history) + [ctx_msg]

    # Retrieval scope. A document-scoped run must derive BOTH its answer and its
    # Sources from the SAME selected document, so retrieval is restricted to that one
    # file_id — never a corpus-wide search over the whole library (which is what made
    # unrelated documents appear in Sources). The document is indexed SYNCHRONOUSLY
    # first so the scoped retrieval actually finds it (the auto-index after OCR is a
    # background thread and may not have finished yet). A run with no document scope
    # keeps the full owned-library scope (cross-document retrieval is intended there).
    if doc is not None:
        _ensure_indexed(doc)
        allowed_ids = {fid}
    else:
        allowed_ids = _owned_file_ids()

    # Live progress (optional): the client may send an opaque run_id and poll
    # /api/agent/progress/<run_id> while this request is in flight. Malformed or
    # missing ids simply disable progress — never an error.
    run_id = str(data.get("run_id") or "").strip()
    progress = get_progress_registry() if RUN_ID_RE.match(run_id) else None
    if progress:
        progress.start(run_id, current_user.id, max_steps)

    core = AgentCore(registry=_safe_registry(),
                     provider=provider_for_task("agent"),
                     max_steps=max_steps,
                     skills=_safe_skill_registry(),
                     skill_context=_agent_skill_context(),
                     enable_planning=True,
                     time_budget_s=(cfg.AGENT_MAX_SECONDS
                                    if cfg.AGENT_MAX_SECONDS > 0 else None),
                     on_progress=((lambda ev: progress.update(run_id, **ev))
                                  if progress else None))
    try:
        result = core.run(message, history=history, allowed_file_ids=allowed_ids)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[AgentBP] /api/agent/run failed: {exc}", exc_info=True)
        # Record the failure honestly in the session (creating it lazily if this was
        # a brand-new request) so the user sees what happened instead of a vanished
        # or empty session, and the assistant turn never silently "changes" (F5).
        conv = conv or get_or_create_agent_conversation(current_user.id)
        if conv:
            memory.append_turn(conv.id, "user", message)
            memory.append_turn(conv.id, "assistant",
                               "⚠️ The agent run failed, so no result was produced. "
                               "Please try again.")
        return jsonify({"success": False, "error": "Agent run failed.",
                        "conversation_id": (conv.id if conv else None)}), 500
    finally:
        if progress:
            progress.finish(run_id)            # a final poll sees phase="done"

    # Build the existing-module "View Result" destinations + persist derived outputs
    # (best-effort; never breaks the response). Done before persisting the turn so the
    # destinations can be stored as the assistant turn's artifact references.
    try:
        results = _run_result_destinations(doc, message, result,
                                           source_truncated=doc_ctx_truncated)
    except Exception:                          # destination building is non-critical
        logger.warning("[AgentBP] building run results failed", exc_info=True)
        results = []

    # Persist the turn AND its durable file/artifact references (Phase 16), so
    # reopening the session restores the source file (on the user turn) and the
    # "View Result" links (on the assistant turn) without re-running the workflow.
    # tool_calls + skill_calls together form the capability trace for this turn.
    # The session is created lazily here for a brand-new request — so only a run
    # that actually produced a turn creates a session (F5).
    conv = conv or get_or_create_agent_conversation(current_user.id)
    if conv:
        user_mid = memory.append_turn(conv.id, "user", message)
        asst_mid = memory.append_turn(conv.id, "assistant", result.answer,
                                      tool_calls=(result.tool_calls() + result.skill_calls()),
                                      provider=result.provider)
        if doc is not None:
            # Source chip links to the viewer whenever any backing text exists (the
            # viewer renders OCR and extracted text alike); module reflects which.
            src_kind = _source_doc_kind(doc)
            add_agent_artifacts(conv.id, user_mid, [{
                "kind": "source", "module": (src_kind or "ocr"), "file_id": doc.file_id,
                "route": (f"#ocr/{doc.file_id}" if src_kind else None),
                "label": doc.filename}])
        if results:
            # Corpus-wide retrieval hits are tagged 'citation' (vs the session's own
            # produced 'result' artifacts) so reopen can list them under "Sources",
            # not the session's "Artifacts" (F4).
            add_agent_artifacts(conv.id, asst_mid, [{
                "kind": ("citation" if d.get("origin") == "citation" else "result"),
                "module": d.get("module"), "route": d.get("route"),
                "file_id": d.get("file_id"), "label": d.get("label")} for d in results])

    # OCR engine this request maps to (default GLM; Vietnamese → VietOCR; explicit
    # wins). Recorded in the run metadata and shown in the result details.
    ocr_engine = select_ocr_engine(message, data.get("ocr_engine"))

    log_activity("agent_run",
                 f"conv={getattr(conv, 'id', None)} tools={result.tool_calls()} "
                 f"skills={result.skill_calls()} steps={len(result.steps)} "
                 f"results={[r.get('route') for r in results]} "
                 f"ocr_engine={ocr_engine['engine']}")
    return jsonify({"success": True,
                    "conversation_id": (conv.id if conv else None),
                    "results": results,
                    "ocr_engine": ocr_engine,
                    # Source-coverage honesty (UI item 6): the scoped document's
                    # text did not fully fit the context window.
                    "context_truncated": doc_ctx_truncated,
                    **result.to_dict()})


# ── Document ingest as a session turn (F1) ───────────────────────────────────────
@agent_bp.route("/api/agent/ingest", methods=["POST"])
@login_required
def agent_ingest():
    """Record an agent-page document upload (and any OCR run at upload time) as a
    durable turn in the session, so the source file and the "View OCR Result" card
    become part of the conversation history and survive reopen — instead of living
    only in the transient upload-status banner (F1). Does NOT run the LLM.

    Body: {file_id, conversation_id?, ocr?: bool, engine_label?: str}. The session
    is created lazily when no ``conversation_id`` is supplied. ``file_id`` is
    ownership-checked (the same IDOR guard every file endpoint uses).
    """
    data = request.get_json(silent=True) or {}
    fid = (data.get("file_id") or "").strip()
    doc, err = _owned_document_or_error(fid)
    if err:
        return err

    conv_id = data.get("conversation_id")
    if conv_id is not None:
        conv, err = _owned_agent_conversation_or_error(conv_id)
        if err:
            return err
    else:
        conv = get_or_create_agent_conversation(current_user.id)
    if conv is None:
        return jsonify({"success": False, "error": "session unavailable"}), 500

    # Same artifact detection as the run path (single source of truth): 'ocr' for a
    # real OCR run, 'text' for extracted DOCX/TXT, None if nothing persisted yet.
    src_kind = _source_doc_kind(doc)
    has_ocr = src_kind == "ocr"
    ran_ocr = bool(data.get("ocr")) and has_ocr
    engine_label = (data.get("engine_label") or "").strip()

    note = f"Uploaded {doc.filename}"
    if ran_ocr:
        note += " and ran OCR" + (f" ({engine_label})" if engine_label else "")
    note += "."
    mid = ConversationMemory().append_turn(conv.id, "user", note)

    # Source file chip (links to the viewer whenever any backing text exists), plus
    # a persistent result card labelled by what actually backs the document — "OCR
    # Result" vs. "Extracted Text" — so the upload is a reproducible part of the
    # session and a DOCX/TXT is never mislabelled as OCR.
    items = [{"kind": "source", "module": (src_kind or "ocr"), "file_id": doc.file_id,
              "route": (f"#ocr/{doc.file_id}" if src_kind else None),
              "label": doc.filename}]
    if src_kind:
        dest = source_document_destination(doc.file_id, doc.filename, has_ocr=has_ocr)
        items.append({"kind": "result", "module": dest["module"], "file_id": dest["file_id"],
                      "route": dest["route"], "label": dest["label"]})
    add_agent_artifacts(conv.id, mid, items)
    log_activity("agent_ingest", f"conv={conv.id} fid={fid} src={src_kind} ocr={ran_ocr}")
    return jsonify({"success": True, "conversation_id": conv.id,
                    "has_ocr": has_ocr, "source_kind": src_kind})


# ── Skill run (whitelisted; document skills resolve file_id server-side) ──────────
@agent_bp.route("/api/agent/skill/<name>", methods=["POST"])
@login_required
def agent_skill(name):
    """Body: {args: {...}, file_id?: str}. file_id is required for document skills."""
    if name not in _HTTP_SKILLS:
        return jsonify({"success": False,
                        "error": f"Skill '{name}' is not available over HTTP."}), 400

    data = request.get_json(silent=True) or {}
    args = data.get("args")
    if not isinstance(args, dict):
        args = {}
    # Defense-in-depth: clients cannot smuggle tenancy or raw paths through args.
    args.pop("allowed_file_ids", None)
    args.pop("image_path", None)

    fid = None
    if _HTTP_SKILLS[name]["needs_file"]:
        fid = (data.get("file_id") or "").strip()
        import app as _app  # lazy import avoids a circular import at module load
        path, err = _app._resolve_owned_file(fid)
        if err:
            return err
        args["image_path"] = str(path)

    ctx = SkillContext(tools=get_registry(),
                       allowed_file_ids=_owned_file_ids(),
                       knowledge=get_knowledge_registry().composite(),
                       provider=provider_for_task("agent"))
    try:
        result = get_skill_registry().run(name, ctx, **args)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[AgentBP] /api/agent/skill/{name} failed: {exc}", exc_info=True)
        return jsonify({"success": False, "error": "Skill run failed."}), 500

    # Persist the skill's derived outputs as document artifacts (best-effort).
    persisted = _persist_skill_artifacts(fid, result.data) if (result.ok and fid) else []

    # "View Result" destinations into the existing module pages (Phase 13). Doc
    # artifacts → Summarize/Translate; any citations → OCR source viewers.
    results = []
    try:
        if persisted and fid:
            _doc = Document.query.filter_by(file_id=fid).first()
            results += doc_artifact_destinations(
                persisted, fid, _doc.filename if _doc else None)
        cites = (result.data or {}).get("citations") if result.ok else None
        if cites:
            results += citation_destinations(cites, _cited_filenames(cites))
    except Exception:
        logger.warning("[AgentBP] building skill results failed", exc_info=True)
        results = []

    log_activity("agent_skill", f"{name} ok={result.ok} persisted={persisted} "
                 f"results={[r.get('route') for r in results]}")
    return jsonify({"success": result.ok, "persisted_artifacts": persisted,
                    "results": results, **result.to_dict()})


# ── Standalone Agent page (additive; existing SPA untouched) ──────────────────────
@agent_bp.route("/agent", methods=["GET"])
@login_required
def agent_page():
    return send_from_directory(current_app.static_folder, "agent.html")
