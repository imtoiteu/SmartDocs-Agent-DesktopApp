"""Admin Control Center blueprint."""
from functools import wraps
from pathlib import Path
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, abort, jsonify)
from flask_login import login_required, current_user
from models import db, User, Document, ActivityLog, log_activity

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
UPLOAD_FOLDER = Path(__file__).parent / "uploads"


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


# ── Dashboard ─────────────────────────────────────────────
@admin_bp.route("/")
@login_required
@admin_required
def dashboard():
    ai_actions = ["ocr", "translate", "correct", "summarize"]
    stats = {
        "total_users":  User.query.count(),
        "active_users": User.query.filter_by(is_active=True).count(),
        "total_files":  Document.query.count(),
        "ai_tasks":     ActivityLog.query.filter(ActivityLog.action.in_(ai_actions)).count(),
    }
    recent = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(20).all()
    return render_template("admin/dashboard.html", stats=stats, recent=recent)


# ── Users ─────────────────────────────────────────────────
@admin_bp.route("/users")
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.created_at).all()
    doc_counts = {u.id: Document.query.filter_by(user_id=u.id).count() for u in all_users}
    return render_template("admin/users.html", users=all_users, doc_counts=doc_counts)


@admin_bp.route("/users/create", methods=["POST"])
@login_required
@admin_required
def create_user():
    username = request.form.get("username", "").strip()
    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    role     = request.form.get("role", "user")
    if not username or not email or not password:
        flash("All fields are required.", "error"); return redirect(url_for("admin.users"))
    if User.query.filter((User.username == username) | (User.email == email)).first():
        flash("Username or email already exists.", "error"); return redirect(url_for("admin.users"))
    u = User(username=username, email=email, role=role, is_active=True)
    u.set_password(password); db.session.add(u); db.session.commit()
    log_activity("admin_create_user", f"Created user: {username}")
    flash(f'User "{username}" created successfully.', "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:uid>/edit", methods=["POST"])
@login_required
@admin_required
def edit_user(uid):
    u = User.query.get_or_404(uid)
    new_username = request.form.get("username", "").strip()
    new_email    = request.form.get("email", "").strip()
    new_role     = request.form.get("role", u.role)
    if new_username: u.username = new_username
    if new_email:    u.email    = new_email
    u.role = new_role; db.session.commit()
    log_activity("admin_edit_user", f"Edited user #{uid}: {u.username}")
    flash(f'User "{u.username}" updated.', "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:uid>/reset-password", methods=["POST"])
@login_required
@admin_required
def reset_password(uid):
    u = User.query.get_or_404(uid)
    pw = request.form.get("password", "").strip()
    if not pw:
        flash("New password cannot be empty.", "error"); return redirect(url_for("admin.users"))
    u.set_password(pw); db.session.commit()
    log_activity("admin_reset_password", f"Reset password for: {u.username}")
    flash(f'Password reset for "{u.username}".', "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:uid>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_user(uid):
    u = User.query.get_or_404(uid)
    if u.id == current_user.id:
        flash("Cannot change your own status.", "error"); return redirect(url_for("admin.users"))
    u.is_active = not u.is_active; db.session.commit()
    verb = "enabled" if u.is_active else "disabled"
    log_activity(f"admin_{verb}_user", f'{verb.capitalize()} user: {u.username}')
    flash(f'User "{u.username}" {verb}.', "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:uid>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(uid):
    u = User.query.get_or_404(uid)
    if u.id == current_user.id:
        flash("Cannot delete your own account.", "error"); return redirect(url_for("admin.users"))
    username = u.username
    # Nullify logs so they persist
    ActivityLog.query.filter_by(user_id=uid).update({"user_id": None}); db.session.flush()
    # Delete files from disk
    for doc in list(u.documents):
        for f in UPLOAD_FOLDER.glob(f"{doc.file_id}.*"):
            try: f.unlink()
            except: pass
        db.session.delete(doc)
    db.session.flush(); db.session.delete(u); db.session.commit()
    log_activity("admin_delete_user", f"Deleted user: {username}")
    flash(f'User "{username}" deleted.', "success")
    return redirect(url_for("admin.users"))


# ── Activity Logs ─────────────────────────────────────────
@admin_bp.route("/logs")
@login_required
@admin_required
def logs():
    page    = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    action = request.args.get("action", "")
    user_f = request.args.get("user", "")
    search = request.args.get("q", "").strip()
    
    q = ActivityLog.query
    if action: q = q.filter_by(action=action)
    if user_f:
        u = User.query.filter_by(username=user_f).first()
        if u: q = q.filter_by(user_id=u.id)
    if search:
        q = q.filter(ActivityLog.action.ilike(f"%{search}%") | 
                     ActivityLog.detail.ilike(f"%{search}%") |
                     ActivityLog.ip_address.ilike(f"%{search}%"))
                     
    paged   = q.order_by(ActivityLog.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    actions = [a[0] for a in db.session.query(ActivityLog.action).distinct().all()]
    all_users = User.query.order_by(User.username).all()
    return render_template("admin/logs.html", logs=paged, action_filter=action,
                           user_filter=user_f, search_query=search,
                           actions=sorted(actions), all_users=all_users)


# ── File Oversight ────────────────────────────────────────
@admin_bp.route("/files")
@login_required
@admin_required
def files():
    page   = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    user_f = request.args.get("user", "")
    type_f = request.args.get("type", "")
    stat_f = request.args.get("status", "")
    search = request.args.get("q", "").strip()
    
    q = Document.query
    if user_f:
        u = User.query.filter_by(username=user_f).first()
        if u: q = q.filter_by(user_id=u.id)
    
    if type_f:
        if type_f == "image":
            q = q.filter(Document.file_type.in_(['.jpg', '.jpeg', '.png', '.webp']))
        elif type_f == "pdf":
            q = q.filter_by(file_type=".pdf")
        elif type_f == "text":
            q = q.filter(Document.file_type.notin_(['.jpg', '.jpeg', '.png', '.webp', '.pdf']))
            
    if stat_f:
        q = q.filter_by(status=stat_f)
        
    if search:
        q = q.filter(Document.filename.ilike(f"%{search}%"))
            
    paged = q.order_by(Document.upload_date.desc()).paginate(page=page, per_page=per_page, error_out=False)
    all_users = User.query.order_by(User.username).all()
    
    return render_template("admin/files.html", paged=paged, all_users=all_users, 
                           user_filter=user_f, type_filter=type_f, 
                           status_filter=stat_f, search_query=search)
