"""Authentication blueprint — login / logout / session / user info."""
from functools import wraps
from flask import (Blueprint, request, jsonify, redirect,
                   url_for, render_template, abort)
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, log_activity

auth_bp = Blueprint("auth", __name__)


# ── Admin guard ──────────────────────────────────────────
def admin_required(fn):
    """Decorator: requires admin role. Apply AFTER @login_required."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if current_user.role != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


# ── Login ────────────────────────────────────────────────
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        if request.is_json:
            data = request.get_json(force=True)
        else:
            data = request.form

        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()

        if not username or not password:
            error = "Username and password are required."
        else:
            user = User.query.filter(
                (User.username == username) | (User.email == username)
            ).first()

            if user and user.is_active and user.check_password(password):
                login_user(user, remember=True)
                log_activity("login", f"User logged in: {user.username}", user_id=user.id)
                if request.is_json:
                    return jsonify({"success": True,
                                    "username": user.username, "role": user.role})
                return redirect(url_for("index"))
            else:
                error = "Invalid username or password."

        if request.is_json:
            return jsonify({"success": False, "error": error}), 401

    return render_template("login.html", error=error)


# ── Logout ───────────────────────────────────────────────
@auth_bp.route("/logout")
@login_required
def logout():
    log_activity("logout", f"User logged out: {current_user.username}")
    logout_user()
    return redirect(url_for("auth.login"))


# ── Current user info (SPA navbar) ───────────────────────
@auth_bp.route("/api/auth/me")
@login_required
def me():
    return jsonify({
        "id":       current_user.id,
        "username": current_user.username,
        "email":    current_user.email,
        "role":     current_user.role,
    })


# ── Language Preference ──────────────────────────────────
@auth_bp.route("/api/set-lang", methods=["POST"])
def set_lang():
    from flask import session
    data = request.get_json(force=True, silent=True) or {}
    lang = data.get("lang", "vi")
    session["lang"] = lang
    return jsonify({"success": True, "lang": lang})


# ── Admin: user list (JSON) ───────────────────────────────
@auth_bp.route("/api/admin/users")
@login_required
@admin_required
def admin_users_api():
    users = User.query.order_by(User.created_at).all()
    return jsonify({"success": True, "users": [u.to_dict() for u in users]})



# ── 403 handler ───────────────────────────────────────────
@auth_bp.app_errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403
