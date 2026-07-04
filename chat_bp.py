"""
SmartDocs Platform — AI Chat Blueprint
=======================================
Routes:
  POST   /api/chat/send          — send a message (RAG or general)
  POST   /api/chat/cancel        — interrupt/stop active generation
  POST   /api/chat/index         — index a document for retrieval
  GET    /api/chat/status        — model + embedding readiness
  DELETE /api/chat/index/<fid>   — remove a document from the index cache
"""

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from pathlib import Path
import sys, logging

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))
from config import cfg
from services import chat_service
from models import (db, Document, ChatConversation,
                    get_or_create_conversation, add_message)

chat_bp = Blueprint("chat", __name__)


def _owned_conversation_or_error(conv_id):
    """Fetch a conversation owned by the current user, or return an error tuple.

    Returns (conv, None) on success or (None, (response, status)) on failure,
    mirroring the per-object ownership pattern used for documents (app.py:579).
    """
    conv = ChatConversation.query.get(conv_id)
    if conv is None:
        return None, (jsonify({"success": False, "error": "not found"}), 404)
    if conv.user_id != current_user.id and current_user.role != "admin":
        return None, (jsonify({"success": False, "error": "Permission denied"}), 403)
    return conv, None


def _owned_document_or_error(file_id):
    """Fetch a Document by file_id, enforcing ownership (admins may access any).

    Returns (doc, None) on success or (None, (response, status)) on failure.
    Without this, file_id-keyed chat endpoints let any authenticated user index,
    evict, or RAG-query another user's document by its file_id (IDOR).
    """
    if not file_id:
        return None, (jsonify({"success": False, "error": "file_id required"}), 400)
    doc = Document.query.filter_by(file_id=file_id).first()
    if doc is None:
        return None, (jsonify({"success": False, "error": "not found"}), 404)
    if doc.user_id != current_user.id and current_user.role != "admin":
        return None, (jsonify({"success": False, "error": "Permission denied"}), 403)
    return doc, None


def _owned_file_ids():
    """The set of file_ids owned by the caller, for scoping cross-document
    ('doc_all') retrieval. Admins get None → search everything (matches the
    admin-sees-all document-list policy)."""
    if current_user.role == "admin":
        return None
    return {fid for (fid,) in
            db.session.query(Document.file_id)
            .filter_by(user_id=current_user.id).all()}


# ── Status ─────────────────────────────────────────────────────────────────────
@chat_bp.route("/api/chat/status", methods=["GET"])
@login_required
def chat_status():
    try:
        status = chat_service.get_chat_status()
        emb_mode = chat_service._embedding_engine.mode
        return jsonify({"success": True, "enabled": cfg.ENABLE_CHAT,
                        "embedding_mode": emb_mode, **status})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── Index a document ───────────────────────────────────────────────────────────
@chat_bp.route("/api/chat/index", methods=["POST"])
@login_required
def chat_index():
    """Index OCR/translated/summarized text for a document."""
    data    = request.get_json(force=True)
    file_id = (data.get("file_id") or "").strip()
    text    = (data.get("text") or "").strip()
    label   = data.get("label", file_id)

    if not file_id:
        return jsonify({"success": False, "error": "file_id required"}), 400
    if not text:
        return jsonify({"success": False, "error": "text required"}), 400
    # Ownership: only index text against a document the caller owns (prevents
    # poisoning another user's RAG index by file_id).
    _doc, err = _owned_document_or_error(file_id)
    if err:
        return err

    try:
        n_chunks = chat_service.index_document(file_id, text, source_label=label)
        return jsonify({"success": True, "file_id": file_id, "chunks": n_chunks})
    except Exception as e:
        logger.exception("[ChatBP] index error")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Remove index ───────────────────────────────────────────────────────────────
@chat_bp.route("/api/chat/index/<file_id>", methods=["DELETE"])
@login_required
def chat_remove_index(file_id):
    # Ownership: only evict the caller's own document from the shared index cache.
    _doc, err = _owned_document_or_error(file_id)
    if err:
        return err
    chat_service.remove_document(file_id)
    return jsonify({"success": True})


# ── Cancel / stop generation ───────────────────────────────────────────────────
@chat_bp.route("/api/chat/cancel", methods=["POST"])
@login_required
def chat_cancel():
    """
    Signal the backend to stop the active model.generate() at the next token.
    Safe to call even when no generation is running.
    Returns immediately — the actual stop happens within 1 token cycle (~0.1–0.5s).
    """
    was_generating = chat_service.cancel_generation()
    logger.info(f"[ChatBP] /api/chat/cancel — was_generating={was_generating}")
    return jsonify({"success": True, "was_generating": was_generating})


# ── Send message ───────────────────────────────────────────────────────────────
@chat_bp.route("/api/chat/send", methods=["POST"])
@login_required
def chat_send():
    """
    Body:
      query   : str   — user question (required)
      file_id : str   — active document file_id (optional)
      mode    : str   — "doc_current" | "general"
      history : list  — [{role, content}, …] last N turns

    Only two user-facing chat modes are supported: Document Chat (one document,
    "doc_current") and General Chat ("general"). The legacy "all documents" mode is
    intentionally not offered; any "doc_all" request folds to "doc_current" so old
    threads reopen gracefully. The Agent still does cross-document retrieval via tools.
    """
    # Feature switch (cross-platform): a clear JSON answer, never a crash.
    if not cfg.ENABLE_CHAT:
        return jsonify({
            "success": False, "disabled": True,
            "error": "AI Chat is disabled on this installation "
                     "(ENABLE_CHAT=false or LLM_PROVIDER=disabled in .env).",
        }), 503

    data            = request.get_json(force=True)
    query           = (data.get("query") or "").strip()
    file_id         = (data.get("file_id") or "").strip() or None
    mode            = data.get("mode", "doc_current")
    conversation_id = data.get("conversation_id")
    new_thread      = bool(data.get("new_thread"))

    if not query:
        return jsonify({"success": False, "error": "query required"}), 400
    if mode not in ("doc_current", "general"):
        mode = "doc_current"

    import time
    t_req = time.time()

    # ── Resolve the persisted conversation (hybrid model) ────────────────────
    # A general-mode turn is never document-linked, even if a file is open.
    # Ownership: a supplied file_id must belong to the caller — otherwise a user
    # could RAG-query another user's document by passing its file_id.
    doc = None
    if file_id:
        doc, err = _owned_document_or_error(file_id)
        if err:
            return err
    document_id    = doc.id if (doc and mode != "general") else None
    document_label = doc.filename if (doc and mode != "general") else None
    # If a conversation_id is supplied, verify ownership before using it.
    if conversation_id is not None:
        owned, err = _owned_conversation_or_error(conversation_id)
        if err:
            return err
    conv = get_or_create_conversation(
        user_id=current_user.id, document_id=document_id,
        conversation_id=conversation_id, mode=mode, document_label=document_label,
        force_new=new_thread,
    )

    # Server-side history is the source of truth: load this thread's turns.
    history = []
    if conv is not None:
        history = [{"role": m.role, "content": m.content} for m in conv.messages]

    logger.info(f"[ChatBP] ━━━ Incoming /api/chat/send ━━━")
    logger.info(f"[ChatBP]   user    = {current_user.id}")
    logger.info(f"[ChatBP]   conv    = {conv.id if conv else None}")
    logger.info(f"[ChatBP]   mode    = {mode}")
    logger.info(f"[ChatBP]   file_id = {file_id}")
    logger.info(f"[ChatBP]   query   = {query[:100]!r}")
    logger.info(f"[ChatBP]   history = {len(history)} turn(s)")

    # Kick off model load if not already started
    chat_service.start_loading()
    status = chat_service.get_chat_status()
    logger.info(f"[ChatBP]   model_ready={status['model_ready']}  loading={status['model_loading']}  model={status.get('model_name')}")

    if status["model_loading"] and not status["model_ready"]:
        logger.info("[ChatBP]   → Model still loading — returning 202 warming_up")
        return jsonify({
            "success":    False,
            "warming_up": True,
            "error":      "AI Chat model is loading. Please wait and try again.",
            "retry_after": 15,
        }), 202

    # Persist the user turn first (sets the auto-title on a new thread) so it is
    # never lost even if generation fails or is cancelled.
    if conv is not None:
        add_message(conv.id, "user", query, mode=mode, set_title_if_empty=True)

    try:
        result = chat_service.chat(
            query=query,
            file_id=file_id,
            mode=mode,
            history=history,
            # Scope 'doc_all' retrieval to the caller's own documents so the shared
            # in-memory index can't leak other users' content cross-tenant.
            allowed_file_ids=_owned_file_ids(),
        )
        # Persist the assistant turn (with its retrieval sources).
        if conv is not None:
            add_message(conv.id, "assistant", result.get("answer", ""),
                        sources=result.get("sources"), mode=mode,
                        engine_used=result.get("engine_used"))
        t_total = time.time() - t_req
        logger.info(
            f"[ChatBP] ✓ Response sent  user={current_user.id}  "
            f"conv={conv.id if conv else None}  "
            f"mode={mode}  chunks={result.get('chunks_found')}  "
            f"engine={result.get('engine_used')}  "
            f"elapsed={result.get('elapsed_s', '?')}s  "
            f"cancelled={result.get('cancelled', False)}"
        )
        extra = {}
        if conv is not None:
            # Re-fetch so the title reflects any auto-title just applied.
            extra = {"conversation_id": conv.id, "title": conv.title}
        return jsonify({"success": True, **result, **extra})
    except RuntimeError as e:
        logger.error(f"[ChatBP] ✗ RuntimeError after {time.time()-t_req:.1f}s: {e}")
        return jsonify({"success": False, "error": str(e), "model_error": True}), 503
    except Exception as e:
        logger.exception(f"[ChatBP] ✗ Unexpected error after {time.time()-t_req:.1f}s")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Conversation history (persistence) ───────────────────────────────────────
@chat_bp.route("/api/chat/conversations", methods=["GET"])
@login_required
def list_conversations():
    """List the current user's conversations, newest-activity first.

    Optional ?document_id= filters to one document's threads. The client groups
    the flat list by document_id into the sidebar tree.
    """
    q = (ChatConversation.query
         .options(joinedload(ChatConversation.document))  # ensure file_id, avoid N+1
         .filter_by(user_id=current_user.id))
    doc_id = request.args.get("document_id")
    if doc_id:
        try:
            q = q.filter_by(document_id=int(doc_id))
        except (TypeError, ValueError):
            pass
    convs = q.order_by(ChatConversation.updated_at.desc()).all()
    return jsonify({"success": True,
                    "conversations": [c.to_dict() for c in convs]})


@chat_bp.route("/api/chat/conversations/<int:conv_id>", methods=["GET"])
@login_required
def get_conversation(conv_id):
    """Full ordered message list for reopening a thread."""
    conv, err = _owned_conversation_or_error(conv_id)
    if err:
        return err
    return jsonify({"success": True,
                    "conversation": conv.to_dict(),
                    "messages": [m.to_dict() for m in conv.messages]})


@chat_bp.route("/api/chat/conversations", methods=["POST"])
@login_required
def create_conversation():
    """Explicitly create a thread for '+ New chat'.

    Optional file_id pre-links a document; the thread starts empty (its title is
    derived from the first message sent into it).
    """
    data    = request.get_json(force=True) or {}
    file_id = (data.get("file_id") or "").strip() or None
    mode    = data.get("mode", "doc_current")
    if mode not in ("doc_current", "general"):
        mode = "doc_current"
    doc = Document.query.filter_by(file_id=file_id).first() if file_id else None
    document_id    = doc.id if (doc and mode != "general") else None
    document_label = doc.filename if (doc and mode != "general") else None
    conv = ChatConversation(user_id=current_user.id, document_id=document_id,
                            document_label=document_label, last_mode=mode,
                            title="New conversation")
    db.session.add(conv)
    db.session.commit()
    return jsonify({"success": True, "conversation": conv.to_dict()})


@chat_bp.route("/api/chat/conversations/<int:conv_id>", methods=["PATCH"])
@login_required
def rename_conversation(conv_id):
    """Rename a conversation."""
    conv, err = _owned_conversation_or_error(conv_id)
    if err:
        return err
    data  = request.get_json(force=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"success": False, "error": "title required"}), 400
    conv.title = title[:200]
    db.session.commit()
    return jsonify({"success": True, "conversation": conv.to_dict()})


@chat_bp.route("/api/chat/conversations/<int:conv_id>", methods=["DELETE"])
@login_required
def delete_conversation(conv_id):
    """Delete a conversation; ORM cascade removes its messages."""
    conv, err = _owned_conversation_or_error(conv_id)
    if err:
        return err
    db.session.delete(conv)
    db.session.commit()
    return jsonify({"success": True})
