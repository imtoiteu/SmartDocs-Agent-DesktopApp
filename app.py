import os, sys, uuid, tempfile, secrets, hashlib, copy
from pathlib import Path
from flask import (Flask, request, jsonify, send_from_directory,
                   redirect, url_for, send_file)
from flask_login import LoginManager, login_required, current_user

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

from config import cfg, print_startup_diagnostics   # central cross-platform config
from services import ocr_service, text_service, correction_service, translate_service, summary_service
from services import markdown_normalize   # repair unmatched $$ before persisting OCR markdown
from services import ai_rewrite_service   # imported here so prewarm() runs at startup
from services import smart_ocr_service    # Phase 1 Smart OCR dispatcher (no AI loaded)
from services import chat_service          # persistence-backed auto-index + index rebuild
from models import (db, User, Document, DocumentArtifact, ActivityLog,
                    seed_admin, log_activity, save_artifact)
from auth import auth_bp
from admin_bp import admin_bp
from chat_bp import chat_bp
from agent_bp import agent_bp           # Phase 5: additive Agent HTTP surface

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = cfg.SECRET_KEY or secrets.token_hex(32)
app.config["SQLALCHEMY_DATABASE_URI"] = cfg.SQLALCHEMY_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# Cap request body size (DoS protection): Flask rejects anything larger with 413
# before it is buffered to disk/RAM. Covers /api/upload and all JSON endpoints.
app.config["MAX_CONTENT_LENGTH"] = cfg.MAX_CONTENT_LENGTH
# Session / remember-me cookie hardening. HttpOnly blocks JS theft (XSS); SameSite
# blunts CSRF; Secure is gated on cfg.SESSION_COOKIE_SECURE so the plain-HTTP dev
# server still works (set SESSION_COOKIE_SECURE=1 behind TLS in production).
app.config["SESSION_COOKIE_HTTPONLY"]  = True
app.config["SESSION_COOKIE_SAMESITE"]  = "Lax"
app.config["SESSION_COOKIE_SECURE"]    = cfg.SESSION_COOKIE_SECURE
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
app.config["REMEMBER_COOKIE_SECURE"]   = cfg.SESSION_COOKIE_SECURE
# Never let the browser run a stale index.html / app.js / chat.js. Without this,
# a cached static asset persists indefinitely (the URL never changes) and code
# fixes silently never take effect. Force revalidation on every load.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
APP_VERSION = "2026.06.14.1"

@app.after_request
def _no_cache_static(resp):
    """Disable caching for the SPA shell and its static assets so edits always
    take effect on reload. API JSON is left untouched."""
    ctype = (resp.mimetype or "")
    is_asset = request.path == "/" or request.path.startswith("/static/")
    is_doc = ctype in ("text/html", "text/javascript", "application/javascript", "text/css")
    if is_asset or is_doc:
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "auth.login"
login_manager.login_message = ""

@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))

@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({"success": False, "error": "Authentication required", "redirect": "/login"}), 401
    return redirect(url_for("auth.login"))


from werkzeug.exceptions import RequestEntityTooLarge

@app.errorhandler(RequestEntityTooLarge)
def _too_large(e):
    """Return a clean JSON error when MAX_CONTENT_LENGTH is exceeded (413)."""
    return jsonify({"success": False,
                    "error": f"File too large (max {cfg.MAX_UPLOAD_MB} MB)."}), 413

from settings_bp import settings_bp    # cloud keys (OS credential store) + privacy
from models_bp import models_bp        # Model Registry / Router (Settings → AI models)

app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(agent_bp)       # Phase 5: additive Agent HTTP surface
app.register_blueprint(settings_bp)
app.register_blueprint(models_bp)

# Apply persisted non-secret settings (Local only / Allow cloud) and mirror
# keyring-stored API keys into this process's env — env vars set externally
# always win (developer / backward-compatible configuration). Never raises.
from services import settings_store as _settings_store, secret_store as _secret_store
_settings_store.apply_persisted_settings()
try:
    _secret_store.load_into_env()
except Exception:
    pass                                  # keyring is optional


# ── Display timezone (admin templates) ───────────────────────────────────────
# Timestamps are stored as naive UTC; render them in DISPLAY_TZ (Asia/Ho_Chi_Minh).
from datetime import timezone as _timezone
try:
    from zoneinfo import ZoneInfo
    _DISPLAY_TZ = ZoneInfo(cfg.DISPLAY_TZ)
except Exception:
    _DISPLAY_TZ = _timezone.utc

@app.template_filter("vn_time")
def _vn_time(value, fmt="%Y-%m-%d %H:%M"):
    """Jinja filter: render a stored (naive UTC) datetime in the display timezone."""
    if value is None:
        return ""
    if getattr(value, "tzinfo", None) is None:
        value = value.replace(tzinfo=_timezone.utc)
    return value.astimezone(_DISPLAY_TZ).strftime(fmt)

UPLOAD_FOLDER = cfg.UPLOAD_DIR
IMG_EXTS  = {".jpg", ".jpeg", ".png", ".webp"}
TEXT_EXTS = {".txt", ".docx"}
ALL_EXTS  = IMG_EXTS | {".pdf"} | TEXT_EXTS
_FILE_HASH_CACHE = {}
_FILE_HASH_CACHE_MAX = 256   # bound the cache so it survives across files (A5)
_STANDARD_OCR_CACHE = {}


def _safe_basename(filename: str) -> str:
    """Sanitize a user-supplied filename for STORAGE/DISPLAY only.

    The on-disk path is always server-generated ({uuid}{suffix}), so this value
    never builds a filesystem path — it just strips directory components and
    CR/LF/control characters so a crafted name can't smuggle path separators into
    later code or inject a Content-Disposition header on download.

    Unicode is intentionally preserved: werkzeug.secure_filename() transliterates
    then drops non-ASCII, which corrupts Vietnamese filenames
    (e.g. 'Tài liệu.pdf' → 'Tai_lieu.pdf', '正常.png' → 'png') — unacceptable for a
    Vietnamese-focused product. secure_filename is the right tool when the name
    becomes a path; here it does not, so we sanitize without lossy ASCII folding.
    """
    name = str(filename or "").replace("\\", "/").split("/")[-1]   # drop any dir part
    name = "".join(ch for ch in name if ch.isprintable() and ch not in "\r\n\t").strip()
    return name[:255] or "upload"


def _resolve_owned_file(fid):
    """Resolve a user-supplied file_id to its on-disk Path, enforcing ownership.

    Returns (path, None) on success, or (None, (response, status)) on error.
    Closes two issues that affected every file_id-keyed endpoint:

      • IDOR / missing ownership — the id must map to a Document owned by the
        caller (admins may access any), mirroring the /api/documents/<id> guards.
      • Path traversal — we never glob the RAW file_id. A value like '../' or
        '../paddleocr' escapes UPLOAD_FOLDER (pathlib.glob honours '..'), e.g.
        glob('../.*') → '.env' and glob('../paddleocr.*') → 'paddleocr.db'.
        Instead we look the id up in the DB and glob by the stored,
        server-generated UUID, so a traversal string matches no Document and 404s.
    """
    if not fid or not isinstance(fid, str):
        return None, (jsonify({"success": False, "error": "file_id required"}), 400)
    doc = Document.query.filter_by(file_id=fid).first()
    if doc is None:
        return None, (jsonify({"success": False, "error": "File not found"}), 404)
    if doc.user_id != current_user.id and current_user.role != "admin":
        return None, (jsonify({"success": False, "error": "Permission denied"}), 403)
    matches = list(UPLOAD_FOLDER.glob(f"{doc.file_id}.*"))
    if not matches:
        return None, (jsonify({"success": False, "error": "File missing from disk"}), 404)
    return matches[0], None


# ── Pages ────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    return send_from_directory("static", "index.html")


# ── Upload (records Document) ────────────────────────────
@app.route("/api/upload", methods=["POST"])
@login_required
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"success": False, "error": "No file"}), 400
    # Sanitize the display name (strips dirs/control chars, keeps Unicode); the
    # extension is derived from the sanitized name and checked against an allowlist.
    safe_name = _safe_basename(f.filename)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALL_EXTS:
        return jsonify({"success": False, "error": f"Unsupported type: {suffix}"}), 400

    # On-disk name is server-generated (UUID + allowlisted suffix), never derived
    # from user input — so the save path is traversal-proof by construction.
    fid  = str(uuid.uuid4())
    path = UPLOAD_FOLDER / f"{fid}{suffix}"
    f.save(str(path))

    is_pdf     = suffix == ".pdf"
    is_img     = suffix in IMG_EXTS
    page_count = ocr_service.pdf_page_count(str(path)) if is_pdf else 1
    file_size  = path.stat().st_size

    doc = Document(user_id=current_user.id, filename=safe_name,
                   file_id=fid, file_type=suffix, file_size=file_size,
                   page_count=page_count, status="uploaded")
    db.session.add(doc); db.session.commit()
    log_activity("upload", f"{safe_name} ({suffix}, {file_size}B)")

    return jsonify({
        "success": True, "file_id": fid, "filename": safe_name,
        "size": file_size, "suffix": suffix, "doc_id": doc.id,
        "is_pdf": is_pdf, "is_image": is_img, "page_count": page_count,
    })


# ── Read text ────────────────────────────────────────────
@app.route("/api/read-text", methods=["POST"])
@login_required
def read_text():
    data = request.get_json(force=True)
    fid  = data.get("file_id")
    path, err = _resolve_owned_file(fid)
    if err:
        return err
    try:
        text = text_service.read_file(str(path))
        # A2/F2: persist the extracted text and make it queryable server-side.
        _persist_and_index(fid, "text", text)
        return jsonify({"success": True, "text": text})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── OCR ──────────────────────────────────────────────
def _mark_ocr_done(fid):
    doc = Document.query.filter_by(file_id=fid).first()
    if doc and doc.status == "uploaded":
        doc.status = "ocr_done"; db.session.commit()


def _persist_and_index(fid, kind, text, meta=None, do_index=True):
    """Persist derived text for a document (A2) and optionally auto-index it (F2).

    Best-effort: a failure here never breaks the originating request.
    `do_index` should be True only for a *complete* document text (so the per-file
    RAG index is not clobbered by partial fragments).
    """
    if not fid or not text or not text.strip():
        return
    try:
        doc = Document.query.filter_by(file_id=fid).first()
        if doc:
            save_artifact(doc.id, kind, text, meta)
    except Exception:
        pass
    if do_index:
        chat_service.index_document_async(fid, text, source_label=kind)


def _build_ocr_layout(pages, selected_engine, effective_engine):
    """Build a compact, persistable snapshot of the OCR result for a document.

    Captures everything the viewer needs to rebuild the overlay + stats WITHOUT
    re-running OCR — boxes, per-region confidence, image dimensions, timing and
    status — per page. The (large) page image is intentionally excluded; it is
    re-rendered from the source file on open.
    """
    out_pages = []
    for p in (pages or []):
        out_pages.append({
            "page_num":         p.get("page_num", 1),
            "results":          [
                {"text": r.get("text", ""), "box": r.get("box"),
                 "confidence": r.get("confidence")}
                for r in (p.get("results") or [])
            ],
            "img_width":        p.get("img_width"),
            "img_height":       p.get("img_height"),
            "elapsed_ms":       p.get("elapsed_ms") or p.get("processing_time_ms"),
            "inference_status": p.get("inference_status"),
        })
    return {
        "engine":          effective_engine,
        "selected_engine": selected_engine,
        "page_count":      len(out_pages),
        "pages":           out_pages,
    }


def _persist_ocr_layout(fid, layout):
    """Persist the structured OCR layout snapshot (kind='ocr_layout'). Best-effort.

    Stored as JSON in document_artifacts; NOT RAG-indexed (that's the text artifact's
    job). Reused by the viewer to restore full OCR state when reopening a document.
    """
    if not fid or not layout or not layout.get("pages"):
        return
    try:
        doc = Document.query.filter_by(file_id=fid).first()
        if doc:
            import json
            save_artifact(doc.id, "ocr_layout", json.dumps(layout, ensure_ascii=False),
                          meta=f"engine={layout.get('engine','?')}")
    except Exception:
        pass


def _persist_ocr_structured(fid, pages):
    """Persist PaddleOCR Modern (PP-StructureV3) structured representations. Best-effort.

    Only writes the artifacts that are actually present on the result(s) — legacy engines
    produce none of these, so nothing is written for them. Never raises and never touches
    the plain-text 'ocr' artifact (that stays the canonical input for chat/translate/summary).
    """
    if not fid or not pages:
        return
    try:
        doc = Document.query.filter_by(file_id=fid).first()
        if not doc:
            return
        import json
        md_parts, html_parts, tables, blocks = [], [], [], []
        pages_json, images = [], []
        for p in (pages or []):
            if p.get("markdown"):      md_parts.append(p["markdown"])
            if p.get("html"):          html_parts.append(p["html"])
            if p.get("tables_html"):   tables.extend(p["tables_html"])
            if p.get("layout_blocks"): blocks.extend(p["layout_blocks"])
            # Structured JSON for the viewer's JSON tab: GLM's raw_json is a list of
            # per-page region-lists; otherwise fall back to results + layout blocks.
            rj = p.get("raw_json")
            if isinstance(rj, list):
                pages_json.extend(rj)
            elif rj is not None:
                pages_json.append(rj)
            else:
                pages_json.append({"results": p.get("results") or [],
                                   "layout_blocks": p.get("layout_blocks") or []})
            # Extracted images (base64), tagged with the SmartDocs page number.
            pg = p.get("page_num") or 1
            for im in (p.get("images") or []):
                im2 = dict(im); im2["page"] = pg
                images.append(im2)
        if md_parts:
            # Repair unmatched/empty $$ delimiters that some OCR engines (e.g. the
            # GLM-OCR VLM) occasionally emit, so malformed math never reaches the
            # renderer. No-op for well-formed markdown.
            md = markdown_normalize.repair_unmatched_display_math("\n\n".join(md_parts))
            save_artifact(doc.id, "ocr_markdown", md)
        if html_parts:
            save_artifact(doc.id, "ocr_html", "\n".join(html_parts))
        if tables:
            save_artifact(doc.id, "ocr_tables", json.dumps(tables, ensure_ascii=False))
        if blocks:
            save_artifact(doc.id, "ocr_blocks", json.dumps(blocks, ensure_ascii=False))
        if pages_json:
            save_artifact(doc.id, "ocr_json", json.dumps(pages_json, ensure_ascii=False))
        if images:
            save_artifact(doc.id, "ocr_images", json.dumps(images, ensure_ascii=False))
    except Exception:
        pass


def _ocr_pages_to_text(pages):
    """Join OCR result lines across pages into a single plain-text document."""
    parts = []
    for p in pages:
        lines = [str(r.get("text") or "") for r in (p.get("results") or [])]
        page_text = "\n".join(l for l in lines if l.strip())
        if page_text:
            parts.append(page_text)
    return "\n\n".join(parts)


def _compute_file_hash(path: Path) -> str:
    stat = path.stat()
    cache_key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    cached = _FILE_HASH_CACHE.get(cache_key)
    if cached:
        return cached

    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(chunk)
    digest = sha.hexdigest()
    # Bounded LRU-style eviction: keep recent file hashes instead of wiping the
    # whole cache on every new digest (which made this an effective size-1 cache).
    if len(_FILE_HASH_CACHE) >= _FILE_HASH_CACHE_MAX:
        _FILE_HASH_CACHE.pop(next(iter(_FILE_HASH_CACHE)))
    _FILE_HASH_CACHE[cache_key] = digest
    return digest


def _source_state(path: Path) -> str:
    stat = path.stat()
    return f"{path.suffix.lower()}:{stat.st_size}:{stat.st_mtime_ns}"


def _resolve_selected_engine(path: Path, requested_engine: str | None = None) -> tuple[str, str]:
    selected = ocr_service.normalize_engine_name(requested_engine or cfg.OCR_ENGINE)
    effective = selected
    if selected == "vietocr" and path.suffix.lower() == ".pdf":
        effective = "paddleocr"
    return selected, effective


def _standard_cache_key_with_engine(path: Path, page: int, engine_name: str) -> tuple:
    return (_compute_file_hash(path), page, _source_state(path), engine_name)


def _get_cached_standard_result(path: Path, page: int, engine_name: str):
    cached = _STANDARD_OCR_CACHE.get(_standard_cache_key_with_engine(path, page, engine_name))
    if cached is None:
        return None
    return copy.deepcopy(cached)


def _store_standard_result(path: Path, page: int, engine_name: str, result: dict):
    key = _standard_cache_key_with_engine(path, page, engine_name)
    _STANDARD_OCR_CACHE[key] = copy.deepcopy(result)


def _ocr_error_response(effective_engine, exc, selected_engine=None):
    """Turn an OCR engine exception into the standard JSON failure shape the SPA
    understands (it checks ``data.success``). Returned via ``jsonify`` with an
    HTTP 200 so the frontend parses JSON and shows the real message instead of
    choking on a Flask HTML 500 page (the "Unexpected token '<'" symptom).

    Engines that already return a structured ``{success: False}`` (e.g. GLM) never
    reach here; this is the safety net for engines that raise (e.g. VietOCR when
    its local config/weights are missing)."""
    msg = str(exc).strip() or exc.__class__.__name__
    return {
        "success": False,
        "error": f"{effective_engine} OCR failed: {msg}",
        "results": [],
        "ocr_engine": effective_engine,
        "selected_engine": selected_engine or effective_engine,
        "inference_status": "error",
    }


def _run_page_ocr(path: Path, page: int, apply_ai: bool, image_path_for_ocr: str, engine_name: str):
    if not apply_ai:
        standard_result = smart_ocr_service.run_ocr_pipeline(
            image_path_for_ocr,
            engine_name=engine_name,
            apply_ai=False
        )
        _store_standard_result(path, page, engine_name, standard_result)
        standard_result["ai_enhancement"] = False
        return standard_result

    standard_result = _get_cached_standard_result(path, page, engine_name)
    had_cached_standard = standard_result is not None
    if standard_result is None:
        standard_result = smart_ocr_service.run_ocr_pipeline(
            image_path_for_ocr,
            engine_name=engine_name,
            apply_ai=False
        )
        _store_standard_result(path, page, engine_name, standard_result)

    flow = "reuse_standard_output" if had_cached_standard else "full_pipeline"
    return smart_ocr_service.run_smart_ocr_from_standard_result(
        standard_result,
        flow=flow,
    )

@app.route("/api/ocr/page", methods=["POST"])
@login_required
def ocr_page():
    data     = request.get_json(force=True)
    fid      = data.get("file_id")
    page     = int(data.get("page", 1))
    apply_ai = data.get("ai_enhancement", False)
    path, err = _resolve_owned_file(fid)
    if err:
        return err
    suffix = path.suffix.lower()
    try:
        selected_engine, effective_engine = _resolve_selected_engine(path, data.get("engine"))
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    engine_fallback = selected_engine != effective_engine
    if suffix == ".pdf":
        pil = ocr_service.pdf_page_to_pil(str(path), page)
        if data.get("preview_only"):
            return jsonify({
                "success": True,
                "page_image_b64": ocr_service.pil_to_b64(pil, "PNG"),
                "img_width": pil.width,
                "img_height": pil.height,
                "results": [],
                "preview_only": True
            })
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=UPLOAD_FOLDER) as t:
            pil.save(t.name, format="PNG"); tmp = t.name
        try:
            res = _run_page_ocr(path, page, apply_ai, tmp, effective_engine)
        except Exception as e:
            app.logger.exception("OCR failed (pdf) engine=%s", effective_engine)
            return jsonify(_ocr_error_response(effective_engine, e, selected_engine))
        finally:
            try: os.unlink(tmp)
            except: pass
        res["page_image_b64"] = ocr_service.pil_to_b64(pil, "PNG")
    else:
        from PIL import Image
        pil = Image.open(str(path))
        # Preview-only for images: return the page image WITHOUT running OCR or
        # persisting. Otherwise opening a document would re-OCR with the current
        # (default) engine and overwrite the stored artifact — clobbering a prior
        # VietOCR result. Mirrors the PDF preview branch above.
        if data.get("preview_only"):
            return jsonify({
                "success": True,
                "page_image_b64": ocr_service.pil_to_b64(pil, "JPEG" if suffix in {".jpg",".jpeg"} else "PNG"),
                "img_width": pil.width,
                "img_height": pil.height,
                "results": [],
                "preview_only": True
            })
        try:
            res = _run_page_ocr(path, page, apply_ai, str(path), effective_engine)
        except Exception as e:
            app.logger.exception("OCR failed (image) engine=%s", effective_engine)
            return jsonify(_ocr_error_response(effective_engine, e, selected_engine))
        res["page_image_b64"] = ocr_service.pil_to_b64(pil, "JPEG" if suffix in {".jpg",".jpeg"} else "PNG")
    res["selected_engine"] = selected_engine
    res["ocr_engine"] = res.get("ocr_engine", effective_engine)
    res["processing_time_ms"] = res.get("elapsed_ms")
    if engine_fallback:
        res["inference_status"] = "fallback_to_paddle_for_pdf"
    else:
        res["inference_status"] = res.get("inference_status", "ok")
    _mark_ocr_done(fid)
    # A2/F2: for single-page images this page IS the whole document, so persist its
    # text and auto-index it. For PDFs we wait for /api/ocr/all (full document) to
    # avoid persisting/indexing a partial page.
    if suffix != ".pdf":
        page_text = "\n".join(
            str(r.get("text") or "") for r in (res.get("results") or []) if str(r.get("text") or "").strip()
        )
        _persist_and_index(fid, "ocr", page_text, meta=f"engine={res.get('ocr_engine','?')}")
        # Persist the structured snapshot so the viewer can fully restore on reopen.
        _persist_ocr_layout(fid, _build_ocr_layout([res], selected_engine, effective_engine))
        # Persist richer representations (markdown/html/tables/blocks) when the engine
        # provides them (PaddleOCR Modern). No-op for legacy engines.
        _persist_ocr_structured(fid, [res])
    detail = (
        f"Page {page} of file_id={fid} [ai={apply_ai}] "
        f"[selected_engine={selected_engine}] [processing_time_ms={res.get('processing_time_ms','?')}] "
        f"[inference_status={res.get('inference_status','?')}]"
    )
    if apply_ai:
        detail += f" [smart_flow={res.get('smart_flow','?')}]"
        detail += f" [engine={res.get('smart_engine','?')}]"
        if res.get("smart_fallback_reason"):
            detail += f" [fallback={res['smart_fallback_reason']}]"
    log_activity("ocr", detail)
    res["page_num"] = page; return jsonify(res)
    
@app.route("/api/ocr/reconstruct-region", methods=["POST"])
@login_required
def reconstruct_region():
    data       = request.get_json(force=True)
    fid        = data.get("file_id")
    page       = int(data.get("page", 1))
    results    = data.get("results", [])
    img_width  = data.get("img_width", 0)
    img_height = data.get("img_height", 0)
    
    if not results:
        return jsonify({"success": True, "text": ""})

    path, err = _resolve_owned_file(fid)
    if err:
        return err

    suffix = path.suffix.lower()
    image_path = str(path)
    tmp = None
    
    try:
        if suffix == ".pdf":
            # Re-render page to temp file for LayoutParser inference
            pil = ocr_service.pdf_page_to_pil(str(path), page)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=UPLOAD_FOLDER) as t:
                pil.save(t.name, format="PNG"); tmp = t.name
            image_path = tmp
            
        ordered = ocr_service.layout_service.reconstruct_layout(
            results, img_width, img_height, image=image_path
        )
        text = "\n".join([r["text"] for r in ordered])
        return jsonify({"success": True, "text": text})
    finally:
        if tmp and os.path.exists(tmp):
            try: os.unlink(tmp)
            except: pass

@app.route("/api/ocr/all", methods=["POST"])
@login_required
def ocr_all():
    data     = request.get_json(force=True)
    fid      = data.get("file_id")
    apply_ai = data.get("ai_enhancement", False)
    ocr_mode = "smart" if apply_ai else "standard"
    path, err = _resolve_owned_file(fid)
    if err:
        return err
    suffix = path.suffix.lower(); pages = []
    # OCR is for images / PDFs only. Reject anything else with a clear 400 instead of
    # failing deep in the pipeline (Image.open on a DOCX/TXT). The existing SPA OCR
    # flow only sends images/PDFs; this mirrors the agent OCR action's guard.
    if suffix not in IMG_EXTS and suffix != ".pdf":
        return jsonify({"success": False,
                        "error": f"OCR supports images and PDFs only (got '{suffix}')."}), 400
    try:
        selected_engine, effective_engine = _resolve_selected_engine(path, data.get("engine"))
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    engine_fallback = selected_engine != effective_engine
    if suffix == ".pdf":
        total = ocr_service.pdf_page_count(str(path))
        for p in range(1, total + 1):
            pil = ocr_service.pdf_page_to_pil(str(path), p)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=UPLOAD_FOLDER) as t:
                pil.save(t.name, format="PNG"); tmp = t.name
            try:
                res = _run_page_ocr(path, p, apply_ai, tmp, effective_engine)
            except Exception as e:
                app.logger.exception("OCR-All failed (pdf page %s) engine=%s", p, effective_engine)
                return jsonify(_ocr_error_response(effective_engine, e, selected_engine))
            finally:
                try: os.unlink(tmp)
                except: pass
            res["page_image_b64"] = ocr_service.pil_to_b64(pil, "PNG")
            res["selected_engine"] = selected_engine
            res["ocr_engine"] = res.get("ocr_engine", effective_engine)
            res["processing_time_ms"] = res.get("elapsed_ms")
            if engine_fallback:
                res["inference_status"] = "fallback_to_paddle_for_pdf"
            else:
                res["inference_status"] = res.get("inference_status", "ok")
            res["page_num"] = p; pages.append(res)
    else:
        from PIL import Image
        pil = Image.open(str(path))
        try:
            res = _run_page_ocr(path, 1, apply_ai, str(path), effective_engine)
        except Exception as e:
            app.logger.exception("OCR-All failed (image) engine=%s", effective_engine)
            return jsonify(_ocr_error_response(effective_engine, e, selected_engine))
        res["page_image_b64"] = ocr_service.pil_to_b64(pil, "PNG")
        res["selected_engine"] = selected_engine
        res["ocr_engine"] = res.get("ocr_engine", effective_engine)
        res["processing_time_ms"] = res.get("elapsed_ms")
        res["inference_status"] = res.get("inference_status", "ok")
        res["page_num"] = 1; pages.append(res)
    _mark_ocr_done(fid)
    # A2/F2: persist the full-document OCR text and auto-index it for RAG.
    _persist_and_index(fid, "ocr", _ocr_pages_to_text(pages),
                       meta=f"engine={effective_engine};mode={ocr_mode};pages={len(pages)}")
    # Persist the structured snapshot (all pages) so the viewer can fully restore.
    _persist_ocr_layout(fid, _build_ocr_layout(pages, selected_engine, effective_engine))
    # Persist richer representations (markdown/html/tables/blocks) when present (Modern).
    _persist_ocr_structured(fid, pages)
    total_ms = sum(p.get("processing_time_ms") or 0 for p in pages)
    statuses = sorted({p.get("inference_status", "?") for p in pages})
    detail = (
        f"OCR-All {len(pages)} pages, file_id={fid} [mode={ocr_mode}] "
        f"[selected_engine={selected_engine}] [processing_time_ms={total_ms}] "
        f"[inference_status={','.join(statuses)}]"
    )
    if ocr_mode == "smart":
        flows = sorted({p.get("smart_flow", "?") for p in pages})
        engines = sorted({p.get("smart_engine", "?") for p in pages})
        fallbacks = sorted({p.get("smart_fallback_reason") for p in pages if p.get("smart_fallback_reason")})
        detail += f" [smart_flows={','.join(flows)}]"
        detail += f" [engines={','.join(engines)}]"
        if fallbacks:
            detail += f" [fallbacks={','.join(fallbacks)}]"
    log_activity("ocr", detail)
    return jsonify({"success": True, "pages": pages, "ocr_mode": ocr_mode})


# ── AI Tools ─────────────────────────────────────────────
@app.route("/api/correct", methods=["POST"])
@login_required
def correct():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text: return jsonify({"success": False, "error": "No text"}), 400
    try:
        res = correction_service.correct(text)
        log_activity("correct", f"{len(text)} chars")
        return jsonify({"success": True, **res})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/translate/status")
@login_required
def translate_status():
    """Probe which translation engines are available.
    Pass ?force=1 to bypass the 30-second cache and re-probe immediately."""
    try:
        force  = request.args.get("force", "0") == "1"
        status = translate_service.get_engine_status(force=force)
        return jsonify({"success": True, **status})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/translate", methods=["POST"])
@login_required
def translate():
    data   = request.get_json(force=True)
    text   = (data.get("text") or "").strip()
    engine = data.get("engine", "auto")
    if not text: return jsonify({"success": False, "error": "No text"}), 400
    try:
        res = translate_service.translate(
            text, data.get("from_lang", "auto"), data.get("to_lang", "vi"), engine=engine
        )
        log_activity("translate", f"{len(text)} chars → {data.get('to_lang','vi')} [{res.get('engine_used','?')}]")
        # A2: persist the translation when the client associates it with a document
        # (optional file_id). No auto-index — the OCR/source text owns the RAG index.
        _persist_and_index(
            data.get("file_id"), "translation", res.get("translated", ""),
            meta=f"to={data.get('to_lang','vi')};engine={res.get('engine_used','?')}", do_index=False,
        )
        return jsonify({"success": True, **res})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/summarize", methods=["POST"])
@login_required
def summarize():
    data         = request.get_json(force=True)
    text         = (data.get("text") or "").strip()
    mode         = data.get("mode", "short")
    engine       = data.get("engine", "auto")
    summary_mode = data.get("summary_mode", "fast")
    if not text: return jsonify({"success": False, "error": "No text"}), 400

    # Feature switch (cross-platform): a clear JSON answer, never a crash.
    # Extractive ("fast") summarization stays available — only AI Rewrite is gated.
    if summary_mode == "ai_rewrite" and not cfg.ENABLE_REWRITE:
        return jsonify({
            "success": False, "disabled": True,
            "error": "AI Rewrite is disabled on this installation "
                     "(ENABLE_REWRITE=false or LLM_PROVIDER=disabled in .env). "
                     "Fast (extractive) summarization still works.",
        }), 503

    # If AI Rewrite requested but model is still loading, return informative state
    if summary_mode == "ai_rewrite":
        ai_status = ai_rewrite_service.get_ai_status()
        if ai_status.get("local_loading") and not ai_status.get("local") and not ai_status.get("api"):
            return jsonify({
                "success":      False,
                "warming_up":   True,
                "error":        "AI model is warming up. Please wait ~30s and try again.",
                "retry_after":  15,
            }), 202

    try:
        res = summary_service.summarize(text, mode, engine=engine, summary_mode=summary_mode)
        log_activity("summarize", f"{len(text)} chars, mode={mode}, summary_mode={summary_mode}, engine={res.get('engine_used','?')}, lang={res.get('lang','?')}")
        # A2: persist the summary when associated with a document (optional file_id).
        _persist_and_index(
            data.get("file_id"), "summary", res.get("summary", ""),
            meta=f"mode={mode};summary_mode={summary_mode}", do_index=False,
        )
        return jsonify({"success": True, **res})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/summarize/status", methods=["GET"])
@login_required
def summarize_status():
    """Return AI model availability — called by UI when user switches to AI Rewrite mode."""
    try:
        status = ai_rewrite_service.get_ai_status()
        return jsonify({"success": True, **status})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "ready": False}), 200


@app.route("/api/llm/status", methods=["GET"])
@login_required
def llm_status():
    """Cross-platform LLM status for the UI / desktop shell.

    One place that answers: which provider is configured, which model on which
    device, whether it is loaded / loading / failed, and — when something is
    missing — the exact setup step to run. Read-only: never triggers a model
    load (it reuses the existing status snapshots of the rewrite/chat services
    and pure-filesystem cache checks from config).
    """
    try:
        rewrite = ai_rewrite_service.get_ai_status()
        chat = chat_service.get_chat_status()
        oc_configured = bool(cfg.OPENAI_COMPATIBLE_BASE_URL
                             and cfg.OPENAI_COMPATIBLE_MODEL)
        local_cached = cfg._has_hf_model(cfg.LOCAL_LLM_MODEL)

        hint = None
        if cfg.LLM_PROVIDER == "disabled":
            hint = ("LLM features are disabled (LLM_PROVIDER=disabled). "
                    "Set LLM_PROVIDER=local_hf or openai_compatible in .env.")
        elif cfg.LLM_PROVIDER == "openai_compatible" and not oc_configured:
            hint = ("LLM_PROVIDER=openai_compatible but the endpoint is not "
                    "configured — set OPENAI_COMPATIBLE_BASE_URL and "
                    "OPENAI_COMPATIBLE_MODEL in .env.")
        elif cfg.LLM_PROVIDER == "local_hf" and not local_cached:
            hint = (f"Local model {cfg.LOCAL_LLM_MODEL} is not cached — run "
                    "scripts/setup_offline.sh once while online "
                    "(models land in MODEL_DIR, offline afterwards).")

        return jsonify({
            "success":  True,
            "provider": cfg.LLM_PROVIDER,
            # Privacy switch (P7): the active processing mode, surfaced so the
            # UI/desktop shell can show whether cloud AI/translation is in play.
            "allow_cloud": cfg.ALLOW_CLOUD,
            "processing_mode": "cloud_allowed" if cfg.ALLOW_CLOUD else "local_only",
            # For the first-cloud-use confirmation: is any cloud key configured,
            # and has the user already acknowledged cloud processing?
            "cloud_keys_configured": any(
                _secret_store.get_key(p) for p in _secret_store.PROVIDERS),
            "cloud_ack": _settings_store.get_cloud_ack(),
            "profile":  cfg.LOCAL_LLM_PROFILE,
            "enabled":  {"chat": cfg.ENABLE_CHAT, "agent": cfg.ENABLE_AGENT,
                         "rewrite": cfg.ENABLE_REWRITE},
            "local": {
                "model":          cfg.LOCAL_LLM_MODEL,
                "device_config":  cfg.QWEN_DEVICE,
                "cached":         local_cached,
                "rewrite_loaded": rewrite.get("local"),
                "rewrite_loading": rewrite.get("local_loading"),
                "rewrite_device": rewrite.get("local_device"),
                "rewrite_error":  rewrite.get("local_error"),
                "chat_loaded":    chat.get("model_ready"),
                "chat_loading":   chat.get("model_loading"),
                "chat_model":     chat.get("model_name") or cfg.CHAT_MODEL,
                "chat_error":     chat.get("model_error"),
            },
            "openai_compatible": {
                "configured": oc_configured,
                "base_url":   cfg.OPENAI_COMPATIBLE_BASE_URL,
                "model":      cfg.OPENAI_COMPATIBLE_MODEL,
                # NOTE: the API key is deliberately never returned.
            },
            "setup_hint": hint,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ── Document Management ───────────────────────────────────
@app.route("/api/documents")
@login_required
def list_documents():
    is_admin = current_user.role == "admin"
    q = Document.query if is_admin else Document.query.filter_by(user_id=current_user.id)
    
    # 1. Get params
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 10, type=int)
    doc_filter = request.args.get("filter", "all")
    search = request.args.get("search", "").lower()

    # 2. Apply Filters
    if doc_filter == "image":
        IMG_EXTS = ['.jpg', '.jpeg', '.png', '.webp']
        q = q.filter(Document.file_type.in_(IMG_EXTS))
    elif doc_filter == "pdf":
        q = q.filter(Document.file_type == ".pdf")
    elif doc_filter == "text":
        q = q.filter(Document.file_type.in_(['.txt', '.docx']))
    
    # 3. Apply Search
    if search:
        from sqlalchemy import or_
        if is_admin:
            q = q.join(User).filter(or_(Document.filename.ilike(f"%{search}%"), User.username.ilike(f"%{search}%")))
        else:
            q = q.filter(Document.filename.ilike(f"%{search}%"))

    # 4. Paginate
    p = q.order_by(Document.upload_date.desc()).paginate(page=page, per_page=page_size, error_out=False)

    # G1: attach the set of persisted artifact kinds for this page's documents in a
    # single bulk query, so the UI can show "processed" badges and reuse prior results.
    page_ids = [d.id for d in p.items]
    kinds_map = {}
    if page_ids:
        for did, kind in (db.session.query(DocumentArtifact.document_id, DocumentArtifact.kind)
                          .filter(DocumentArtifact.document_id.in_(page_ids)).all()):
            kinds_map.setdefault(did, set()).add(kind)
    documents_out = []
    for d in p.items:
        dd = d.to_dict(include_owner=is_admin)
        dd["artifact_kinds"] = sorted(kinds_map.get(d.id, ()))
        documents_out.append(dd)

    # 5. Stats (full counts for current scope, independent of search/filter if desired, 
    # but here we match the frontend expectations which usually show counts for the whole tab)
    base_q = Document.query if is_admin else Document.query.filter_by(user_id=current_user.id)
    IMG_EXTS = ['.jpg', '.jpeg', '.png', '.webp']
    stats = {
        "total": base_q.count(),
        "images": base_q.filter(Document.file_type.in_(IMG_EXTS)).count(),
        "pdfs": base_q.filter(Document.file_type == ".pdf").count(),
        "texts": base_q.filter(Document.file_type.in_(['.txt', '.docx'])).count()
    }

    return jsonify({
        "success": True, 
        "is_admin": is_admin,
        "documents": documents_out,
        "stats": stats,
        "pagination": {
            "total_items": p.total,
            "total_pages": p.pages,
            "current_page": p.page,
            "page_size": p.per_page,
            "has_next": p.has_next,
            "has_prev": p.has_prev
        }
    })

@app.route("/api/documents/<int:doc_id>/text")
@login_required
def document_text(doc_id):
    """A2: return persisted derived text (ocr/text/translation/summary) for a document,
    so the UI can reuse prior results instead of re-running OCR/translation/summary."""
    doc = Document.query.get_or_404(doc_id)
    if doc.user_id != current_user.id and current_user.role != "admin":
        return jsonify({"success": False, "error": "Permission denied"}), 403
    # Exclude 'ocr_images' (potentially large base64 blobs) from this bulk payload —
    # the viewer fetches them lazily via /ocr-images only when the Images tab is opened.
    artifacts = {a.kind: a.to_dict() for a in doc.artifacts if a.kind != "ocr_images"}
    return jsonify({"success": True, "doc_id": doc_id, "file_id": doc.file_id,
                    "artifacts": artifacts})

@app.route("/api/documents/<int:doc_id>/ocr-images")
@login_required
def document_ocr_images(doc_id):
    """Lazily return the persisted 'ocr_images' artifact (base64 layout overlays +
    cropped regions) for the Extracted Images tab when a saved document is reopened."""
    doc = Document.query.get_or_404(doc_id)
    if doc.user_id != current_user.id and current_user.role != "admin":
        return jsonify({"success": False, "error": "Permission denied"}), 403
    art = next((a for a in doc.artifacts if a.kind == "ocr_images"), None)
    images = []
    if art:
        import json
        try: images = json.loads(art.content)
        except Exception: images = []
    return jsonify({"success": True, "images": images})

@app.route("/api/documents/<int:doc_id>", methods=["DELETE"])
@login_required
def delete_document(doc_id):
    doc = Document.query.get_or_404(doc_id)
    if doc.user_id != current_user.id and current_user.role != "admin":
        return jsonify({"success": False, "error": "Permission denied"}), 403
    for f in UPLOAD_FOLDER.glob(f"{doc.file_id}.*"):
        try: f.unlink()
        except: pass
    # Drop the document from the in-memory RAG index too (B4/F2 hygiene).
    try: chat_service.remove_document(doc.file_id)
    except Exception: pass
    log_activity("delete_doc", f"Deleted: {doc.filename} (doc #{doc_id})")
    db.session.delete(doc); db.session.commit()   # artifacts cascade-delete (A2)
    return jsonify({"success": True})

@app.route("/api/documents/<int:doc_id>/download")
@login_required
def download_document(doc_id):
    doc = Document.query.get_or_404(doc_id)
    if doc.user_id != current_user.id and current_user.role != "admin":
        return jsonify({"success": False, "error": "Permission denied"}), 403
    matches = list(UPLOAD_FOLDER.glob(f"{doc.file_id}.*"))
    if not matches: return jsonify({"success": False, "error": "File missing from disk"}), 404
    return send_file(str(matches[0]), as_attachment=True, download_name=doc.filename)


# ── Boot ─────────────────────────────────────────────
if __name__ == "__main__":
    seed_admin(app)
    # Pre-warm AI model in background so it's ready when users need it
    with app.app_context():
        ai_rewrite_service.prewarm()
    # B4: rebuild the in-memory RAG index from persisted text (background thread)
    chat_service.rebuild_indexes_from_db(app)
    print(cfg.summary())
    print(f"  🚀  SmartDocs Platform  —  http://{cfg.HOST}:{cfg.PORT}")
    print(f"  🤖  AI Rewrite model loading in background…")
    print("=" * 56 + "\n")
    app.run(host=cfg.HOST, port=cfg.PORT, debug=False, threaded=True)
