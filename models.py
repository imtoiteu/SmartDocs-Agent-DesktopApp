"""Database models for PaddleOCR Studio."""
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def iso_utc(dt):
    """Serialize a stored (naive UTC) datetime as an explicit-UTC ISO string.

    All DateTime columns are written with ``datetime.utcnow`` (naive UTC). Without
    a timezone marker the client's ``new Date()`` parses them as browser-local,
    which is the timezone-display bug. Tagging them ``+00:00`` makes the wire
    format unambiguous so the frontend/admin can convert to Asia/Ho_Chi_Minh.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id           = db.Column(db.Integer, primary_key=True)
    username     = db.Column(db.String(80),  unique=True, nullable=False)
    email        = db.Column(db.String(120), unique=True, nullable=False)
    password_hash= db.Column(db.String(256), nullable=False)
    role         = db.Column(db.String(20),  nullable=False, default="user")  # 'admin' | 'user'
    is_active    = db.Column(db.Boolean, nullable=False, default=True)
    created_at   = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "id":         self.id,
            "username":   self.username,
            "email":      self.email,
            "role":       self.role,
            "is_active":  self.is_active,
            "created_at": iso_utc(self.created_at),
        }

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class Document(db.Model):
    __tablename__ = "documents"
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    filename    = db.Column(db.String(255), nullable=False)
    file_id     = db.Column(db.String(36),  unique=True, nullable=False)
    file_type   = db.Column(db.String(10),  nullable=False)
    file_size   = db.Column(db.BigInteger,  nullable=False, default=0)
    page_count  = db.Column(db.Integer,     nullable=False, default=1)
    upload_date = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
    status      = db.Column(db.String(20),  nullable=False, default="uploaded")
    owner       = db.relationship("User", backref=db.backref("documents", lazy=True))

    def to_dict(self, include_owner=False):
        d = {
            "id": self.id, "filename": self.filename,
            "file_id": self.file_id, "file_type": self.file_type,
            "file_size": self.file_size, "page_count": self.page_count,
            "upload_date": iso_utc(self.upload_date), "status": self.status,
        }
        if include_owner:
            d["owner"] = self.owner.username
        return d


class DocumentArtifact(db.Model):
    """Persisted derived text for a document (A2).

    One row per (document, kind). `kind` is one of:
      'ocr'         — full extracted OCR text (plain text; consumed by chat/translate/summary)
      'ocr_markdown'— Markdown reconstruction (PaddleOCR Modern / PP-StructureV3 only)
      'ocr_html'    — HTML reconstruction (PaddleOCR Modern only)
      'ocr_tables'  — JSON list of detected tables as HTML (PaddleOCR Modern only)
      'ocr_blocks'  — JSON layout blocks: label/content/bbox/order (PaddleOCR Modern only)
      'ocr_json'    — JSON structured per-page OCR output for the viewer JSON tab (GLM/Modern; results fallback)
      'ocr_images'  — JSON list of base64 visual artifacts (layout overlays + cropped regions; GLM/Modern)
      'ocr_layout'  — JSON snapshot of boxes/conf for the viewer overlay (all engines)
      'text'        — text read directly from TXT/DOCX/PDF
      'translation' — latest translation output
      'summary'     — latest summary output
    Stored so the app does not have to re-run OCR / models when a document is
    reopened, and so the RAG index can be rebuilt after a restart.
    """
    __tablename__ = "document_artifacts"
    id          = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    kind        = db.Column(db.String(20),  nullable=False)
    content     = db.Column(db.Text,        nullable=False)
    meta        = db.Column(db.String(200), nullable=True)   # e.g. 'to=vi;engine=argos'
    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                            onupdate=datetime.utcnow)
    # No passive_deletes: SQLite does not enforce FKs by default, so rely on
    # SQLAlchemy's ORM-level cascade to remove artifacts when a Document is deleted.
    document    = db.relationship(
        "Document",
        backref=db.backref("artifacts", lazy=True, cascade="all, delete-orphan"),
    )
    __table_args__ = (
        db.UniqueConstraint("document_id", "kind", name="uq_artifact_doc_kind"),
    )

    def to_dict(self):
        return {
            "kind": self.kind, "content": self.content, "meta": self.meta,
            "updated_at": iso_utc(self.updated_at),
        }


class ChatConversation(db.Model):
    """A persisted AI-chat thread owned by a user (chat persistence).

    Hybrid model: the first message on a document auto-creates a default thread;
    users may also branch additional threads via "New chat". A thread is a
    *document* chat when ``document_id`` is set and a *general* assistant chat
    when it is ``NULL``. ``document_label`` snapshots the filename so a doc-linked
    thread keeps a readable label even after its Document is deleted (the FK is
    nullified on delete, the thread and its messages are retained).
    """
    __tablename__ = "chat_conversations"
    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                               nullable=False, index=True)
    document_id    = db.Column(db.Integer, db.ForeignKey("documents.id", ondelete="SET NULL"),
                               nullable=True, index=True)
    document_label = db.Column(db.String(255), nullable=True)
    title          = db.Column(db.String(200), nullable=False, default="New conversation")
    last_mode      = db.Column(db.String(20),  nullable=False, default="doc_current")
    created_at     = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at     = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                               onupdate=datetime.utcnow)

    user     = db.relationship("User", backref=db.backref("conversations", lazy=True,
                                                           passive_deletes=True))
    # No delete cascade on the Document side: deleting a Document nullifies
    # document_id (SET NULL) and keeps the conversation. Messages cascade from
    # the conversation, not the document.
    document = db.relationship("Document", backref=db.backref("conversations", lazy=True))
    messages = db.relationship("ChatMessage", lazy=True,
                               cascade="all, delete-orphan",
                               order_by="ChatMessage.created_at",
                               backref=db.backref("conversation", lazy=True))

    __table_args__ = (
        db.Index("ix_conv_user_updated",  "user_id", "updated_at"),
        db.Index("ix_conv_user_document", "user_id", "document_id"),
    )

    def to_dict(self, include_count=True):
        d = {
            "id":             self.id,
            "title":          self.title,
            "document_id":    self.document_id,
            "file_id":        self.document.file_id if self.document else None,
            "document_label": self.document_label,
            "last_mode":      self.last_mode,
            "is_general":     self.document_id is None,
            "created_at":     iso_utc(self.created_at),
            "updated_at":     iso_utc(self.updated_at),
        }
        if include_count:
            d["message_count"] = len(self.messages)
        return d


class ChatMessage(db.Model):
    """A single turn within a ChatConversation."""
    __tablename__ = "chat_messages"
    id              = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer,
                                db.ForeignKey("chat_conversations.id", ondelete="CASCADE"),
                                nullable=False, index=True)
    role            = db.Column(db.String(16),  nullable=False)   # 'user' | 'assistant'
    content         = db.Column(db.Text,        nullable=False)
    sources         = db.Column(db.Text,        nullable=True)    # JSON-encoded sources[]
    mode            = db.Column(db.String(20),  nullable=True)
    engine_used     = db.Column(db.String(40),  nullable=True)
    created_at      = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def to_dict(self):
        import json
        try:
            src = json.loads(self.sources) if self.sources else []
        except Exception:
            src = []
        return {
            "id":          self.id,
            "role":        self.role,
            "content":     self.content,
            "sources":     src,
            "mode":        self.mode,
            "engine_used": self.engine_used,
            "created_at":  iso_utc(self.created_at),
        }


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"
    id         = db.Column(db.Integer,  primary_key=True)
    user_id    = db.Column(db.Integer,  db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action     = db.Column(db.String(50),  nullable=False)
    detail     = db.Column(db.String(500), nullable=True)
    ip_address = db.Column(db.String(45),  nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user       = db.relationship("User", backref=db.backref("logs", lazy=True, passive_deletes=True))

    def to_dict(self):
        return {
            "id": self.id, "action": self.action, "detail": self.detail,
            "ip_address": self.ip_address, "created_at": iso_utc(self.created_at),
            "username": self.user.username if self.user else "(deleted)",
        }


def log_activity(action: str, detail: str = None, user_id=None):
    """Non-blocking activity logger — never raises."""
    try:
        from flask_login import current_user
        from flask import request
        uid = user_id
        if uid is None:
            try: uid = current_user.id if current_user.is_authenticated else None
            except Exception: pass
        ip = None
        try: ip = request.remote_addr
        except Exception: pass
        entry = ActivityLog(user_id=uid, action=action, detail=detail, ip_address=ip)
        db.session.add(entry)
        db.session.commit()
    except Exception:
        pass


def save_artifact(document_id: int, kind: str, content: str, meta: str = None):
    """Upsert the latest artifact of `kind` for a document (A2). Best-effort; never raises.

    Returns the artifact id, or None on empty content / failure.
    """
    if not content or not str(content).strip():
        return None
    try:
        art = DocumentArtifact.query.filter_by(document_id=document_id, kind=kind).first()
        if art is None:
            art = DocumentArtifact(document_id=document_id, kind=kind,
                                   content=content, meta=meta)
            db.session.add(art)
        else:
            art.content = content
            art.meta = meta
            art.updated_at = datetime.utcnow()
        db.session.commit()
        return art.id
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


def derive_title(text: str, max_words: int = 6, max_chars: int = 60) -> str:
    """Auto-title a conversation from its first user message."""
    s = " ".join((text or "").split())
    if not s:
        return "New conversation"
    words = s.split(" ")[:max_words]
    title = " ".join(words)
    if len(title) > max_chars:
        title = title[:max_chars].rstrip()
    if len(words) < len(s.split(" ")) or len(title) < len(s):
        title += "…"
    return title


def get_or_create_conversation(user_id: int, document_id=None,
                               conversation_id=None, mode: str = "doc_current",
                               document_label: str = None, force_new: bool = False):
    """Resolve the target conversation for a chat turn (hybrid model).

    1. If ``conversation_id`` is given and owned by the user, reuse it.
    2. Else, unless ``force_new``, reuse the user's existing default thread for
       this ``document_id`` (or general thread when ``document_id`` is None) so a
       returning user continues where they left off.
    3. Else (``force_new`` — i.e. the "New chat" button — or no thread yet)
       create a fresh thread, snapshotting ``document_label``. This is what lets
       a document have more than one conversation.

    Returns the ChatConversation (committed), or None on failure.
    """
    try:
        if conversation_id:
            conv = ChatConversation.query.filter_by(id=conversation_id,
                                                    user_id=user_id).first()
            if conv:
                return conv
        if not force_new:
            # Reuse the most-recent matching default thread for this scope.
            conv = (ChatConversation.query
                    .filter_by(user_id=user_id, document_id=document_id)
                    .order_by(ChatConversation.updated_at.desc())
                    .first())
            if conv:
                return conv
        conv = ChatConversation(user_id=user_id, document_id=document_id,
                                document_label=document_label,
                                last_mode=mode, title="New conversation")
        db.session.add(conv)
        db.session.commit()
        return conv
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


def add_message(conversation_id: int, role: str, content: str,
                sources=None, mode: str = None, engine_used: str = None,
                set_title_if_empty: bool = False):
    """Append a message to a conversation and bump its updated_at. Never raises.

    When ``set_title_if_empty`` and the conversation still has the placeholder
    title, derive a title from this message's content.
    """
    import json as _json
    try:
        conv = ChatConversation.query.get(conversation_id)
        if conv is None:
            return None
        src = None
        if sources:
            try:
                src = _json.dumps(sources, ensure_ascii=False)
            except Exception:
                src = None
        msg = ChatMessage(conversation_id=conversation_id, role=role,
                          content=content, sources=src, mode=mode,
                          engine_used=engine_used)
        db.session.add(msg)
        if mode:
            conv.last_mode = mode
        if set_title_if_empty and (not conv.title or conv.title == "New conversation"):
            conv.title = derive_title(content)
        conv.updated_at = datetime.utcnow()
        db.session.commit()
        return msg.id
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


# ── Agent session memory (Phase 6, additive; isolated from chat) ──────────────
# Deliberately SEPARATE tables from ChatConversation/ChatMessage so agent memory
# stays isolated from chat business logic and never appears in the chat sidebar.
# New tables are created automatically by ``db.create_all()`` — existing chat
# tables and data are untouched (the schema is create_all-only; there is no
# column-altering migration path).
class AgentConversation(db.Model):
    """A persisted Agent session, owned by a user (Phase 6)."""
    __tablename__ = "agent_conversations"
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    title       = db.Column(db.String(200), nullable=False, default="New session")
    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                            onupdate=datetime.utcnow)

    user     = db.relationship("User", backref=db.backref("agent_conversations",
                                                          lazy=True, passive_deletes=True))
    messages = db.relationship("AgentMessage", lazy=True,
                               cascade="all, delete-orphan",
                               order_by="AgentMessage.created_at",
                               backref=db.backref("conversation", lazy=True))

    __table_args__ = (db.Index("ix_agentconv_user_updated", "user_id", "updated_at"),)

    def to_dict(self, include_count=True):
        d = {"id": self.id, "title": self.title,
             "created_at": iso_utc(self.created_at),
             "updated_at": iso_utc(self.updated_at)}
        if include_count:
            d["message_count"] = len(self.messages)
        return d


class AgentMessage(db.Model):
    """A single turn within an AgentConversation."""
    __tablename__ = "agent_messages"
    id              = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer,
                                db.ForeignKey("agent_conversations.id", ondelete="CASCADE"),
                                nullable=False, index=True)
    role            = db.Column(db.String(16),  nullable=False)   # 'user' | 'assistant'
    content         = db.Column(db.Text,        nullable=False)
    tool_calls      = db.Column(db.Text,        nullable=True)    # JSON list of tool names
    provider        = db.Column(db.String(40),  nullable=True)
    created_at      = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Persisted file/artifact references for this turn (Phase 16). Lives in its own
    # table (no column added to agent_messages → zero migration on create_all).
    artifacts = db.relationship("AgentArtifact", lazy=True,
                                cascade="all, delete-orphan",
                                order_by="AgentArtifact.id",
                                backref=db.backref("message", lazy=True))

    def to_dict(self):
        import json
        try:
            tc = json.loads(self.tool_calls) if self.tool_calls else []
        except Exception:
            tc = []
        return {"id": self.id, "role": self.role, "content": self.content,
                "tool_calls": tc, "provider": self.provider,
                "artifacts": [a.to_dict() for a in self.artifacts],
                "created_at": iso_utc(self.created_at)}


class AgentArtifact(db.Model):
    """A durable file / generated-artifact reference attached to an agent turn
    (Phase 16). Persisting these makes a session fully reproducible: reopening it
    restores the source file shown on the user turn and the "View Result" links on
    the assistant turn, without re-running the workflow.

    This is a REFERENCE only (module + SPA route + label) — the real outputs live
    in ``document_artifacts`` / ``chat_*``. Deleting a session removes these rows,
    never the underlying document artifacts.
    """
    __tablename__ = "agent_artifacts"
    id              = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer,
                                db.ForeignKey("agent_conversations.id", ondelete="CASCADE"),
                                nullable=False, index=True)
    message_id      = db.Column(db.Integer,
                                db.ForeignKey("agent_messages.id", ondelete="CASCADE"),
                                nullable=True, index=True)
    kind            = db.Column(db.String(20), nullable=False)   # 'source' | 'result'
    module          = db.Column(db.String(20), nullable=True)    # ocr/summarize/translate/chat
    route           = db.Column(db.String(255), nullable=True)   # SPA hash, e.g. #ocr/<file_id>
    file_id         = db.Column(db.String(36), nullable=True)
    label           = db.Column(db.String(300), nullable=False, default="")
    created_at      = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {"kind": self.kind, "module": self.module, "route": self.route,
                "file_id": self.file_id, "label": self.label}


def get_or_create_agent_conversation(user_id: int, conversation_id=None, title: str = None):
    """Resolve the target agent session, or create a fresh one.

    Ownership is enforced: a ``conversation_id`` not owned by ``user_id`` is
    ignored and a new session is created. Returns the AgentConversation
    (committed) or None on failure.
    """
    try:
        if conversation_id:
            conv = AgentConversation.query.filter_by(id=conversation_id,
                                                     user_id=user_id).first()
            if conv:
                return conv
        conv = AgentConversation(user_id=user_id, title=title or "New session")
        db.session.add(conv)
        db.session.commit()
        return conv
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


def add_agent_message(conversation_id: int, role: str, content: str,
                      tool_calls=None, provider: str = None,
                      set_title_if_empty: bool = False):
    """Append a turn to an agent session and bump its updated_at. Never raises."""
    import json as _json
    try:
        conv = AgentConversation.query.get(conversation_id)
        if conv is None:
            return None
        tc = None
        if tool_calls:
            try:
                tc = _json.dumps(tool_calls, ensure_ascii=False)
            except Exception:
                tc = None
        msg = AgentMessage(conversation_id=conversation_id, role=role,
                           content=content, tool_calls=tc, provider=provider)
        db.session.add(msg)
        if set_title_if_empty and (not conv.title or conv.title == "New session"):
            conv.title = derive_title(content)
        conv.updated_at = datetime.utcnow()
        db.session.commit()
        return msg.id
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


def add_agent_artifacts(conversation_id: int, message_id, items) -> int:
    """Persist file/artifact references for an agent turn (Phase 16). Best-effort.

    ``items`` is a list of dicts with keys {kind, module, route, file_id, label}.
    Returns the number written.
    """
    if not items:
        return 0
    try:
        n = 0
        for it in items:
            if not isinstance(it, dict):
                continue
            db.session.add(AgentArtifact(
                conversation_id=conversation_id, message_id=message_id,
                kind=(it.get("kind") or "result"), module=it.get("module"),
                route=it.get("route"), file_id=it.get("file_id"),
                label=(it.get("label") or "")[:300]))
            n += 1
        db.session.commit()
        return n
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return 0


def rename_agent_conversation(conv, title: str) -> bool:
    """Rename an agent session (title only). ``conv`` is an already-owned
    AgentConversation. Returns True on success."""
    try:
        new = (title or "").strip()[:200]
        if not new:
            return False
        conv.title = new
        conv.updated_at = datetime.utcnow()
        db.session.commit()
        return True
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return False


def delete_agent_conversation(conv) -> bool:
    """Delete an agent session and ITS history/references only — never the
    underlying document artifacts (those live in ``document_artifacts`` and are
    untouched). ``conv`` is an already-owned AgentConversation."""
    try:
        AgentArtifact.query.filter_by(conversation_id=conv.id).delete(
            synchronize_session=False)
        db.session.delete(conv)          # cascades agent_messages (delete-orphan)
        db.session.commit()
        return True
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return False


_SEED_USERS = [
    {"username": "admin", "email": "admin@paddleocr.local",  "password": "admin123", "role": "admin"},
    {"username": "user",  "email": "user@paddleocr.local",   "password": "user123",  "role": "user"},
]


def seed_admin(app):
    """Create default seed accounts if they don't already exist."""
    with app.app_context():
        db.create_all()
        created = []
        for s in _SEED_USERS:
            if not User.query.filter_by(username=s["username"]).first():
                u = User(username=s["username"], email=s["email"],
                         role=s["role"], is_active=True)
                u.set_password(s["password"])
                db.session.add(u)
                created.append(s)
        if created:
            db.session.commit()
            print("=" * 52)
            for s in created:
                label = "Admin" if s["role"] == "admin" else "User "
                print(f"  ✅ [{label}]  {s['username']} / {s['password']}")
            print("  ⚠️  Change default passwords after first login!")
            print("=" * 52)
