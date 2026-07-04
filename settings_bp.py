"""Settings Blueprint — cloud API keys + privacy mode (UI items 1/2/3).

Thin HTTP layer over ``services.secret_store`` (OS-credential-store keys,
masked everywhere) and ``services.settings_store`` (non-secret persisted
settings). Rules enforced here:

* Local-only mode blocks saving and TESTING cloud keys (nothing may leave the
  machine) — removing a key stays allowed.
* Enabling cloud processing the first time requires an explicit confirmation
  (``ack``) acknowledging that document text and prompts may be sent to the
  configured provider.
* Responses carry masked hints and short human messages only — never a key,
  never a raw backend exception.
"""

from __future__ import annotations

import logging

from flask import Blueprint, request, jsonify
from flask_login import login_required

from config import cfg
from models import log_activity
from services import secret_store, settings_store

logger = logging.getLogger(__name__)
settings_bp = Blueprint("settings", __name__)

_LOCAL_ONLY_MSG = ("Local only is enabled — cloud API keys are not used, "
                   "validated or requested in this mode. Enable cloud "
                   "processing first (Settings → Privacy).")

_CLOUD_ACK_MSG = ("Allowing cloud processing means document text, retrieval "
                  "excerpts and prompts may be sent to the configured cloud "
                  "provider (e.g. Groq or Gemini). Confirm to continue.")


def _settings_payload() -> dict:
    kr_ok, kr_backend = secret_store.keyring_available()
    return {
        "success": True,
        "privacy": {
            "allow_cloud": bool(cfg.ALLOW_CLOUD),
            "processing_mode": "cloud_allowed" if cfg.ALLOW_CLOUD else "local_only",
            "env_locked": settings_store.env_allow_cloud_is_explicit(),
            "cloud_ack": settings_store.get_cloud_ack(),
            "ack_message": _CLOUD_ACK_MSG,
        },
        "keyring": {"available": kr_ok, "backend": kr_backend},
        "providers": [secret_store.provider_status(p)
                      for p in secret_store.PROVIDERS],
    }


@settings_bp.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    return jsonify(_settings_payload())


@settings_bp.route("/api/settings/privacy", methods=["PUT"])
@login_required
def set_privacy():
    """Body: {allow_cloud: bool, ack?: bool}. First-time enabling requires the
    explicit ack (the UI shows the confirmation text from GET /api/settings)."""
    data = request.get_json(silent=True) or {}
    allow = bool(data.get("allow_cloud"))
    if allow and not settings_store.get_cloud_ack():
        if not data.get("ack"):
            return jsonify({"success": False, "needs_ack": True,
                            "message": _CLOUD_ACK_MSG}), 409
        settings_store.set_cloud_ack()
    try:
        settings_store.set_allow_cloud(allow)
    except ValueError as e:                 # env-locked — explain, don't lie
        return jsonify({"success": False, "error": str(e)}), 409
    except Exception:
        logger.error("[Settings] privacy toggle failed", exc_info=True)
        return jsonify({"success": False,
                        "error": "Could not save the setting."}), 500
    log_activity("settings_privacy", f"allow_cloud={allow}")
    return jsonify(_settings_payload())


@settings_bp.route("/api/settings/keys/<provider>", methods=["POST"])
@login_required
def save_key(provider):
    """Body: {api_key}. Stores via the OS credential store; masked echo only."""
    if provider not in secret_store.PROVIDERS:
        return jsonify({"success": False, "error": "Unknown provider."}), 400
    if not cfg.ALLOW_CLOUD:
        return jsonify({"success": False, "error": _LOCAL_ONLY_MSG}), 409
    api_key = ((request.get_json(silent=True) or {}).get("api_key") or "").strip()
    if not api_key:
        return jsonify({"success": False, "error": "API key required."}), 400
    try:
        secret_store.set_key(provider, api_key)
    except RuntimeError:                    # keyring unavailable
        return jsonify({
            "success": False, "state": "unavailable",
            "error": "The OS credential store is unavailable on this system, "
                     "so the key was NOT saved. Use the environment variable "
                     f"{secret_store.PROVIDERS[provider]} in .env instead.",
        }), 503
    except Exception:
        logger.error(f"[Settings] saving {provider} key failed", exc_info=True)
        return jsonify({"success": False,
                        "error": "Could not save the key."}), 500
    log_activity("settings_key_saved", f"provider={provider}")   # never the key
    return jsonify({"success": True,
                    "provider": secret_store.provider_status(provider)})


@settings_bp.route("/api/settings/keys/<provider>", methods=["DELETE"])
@login_required
def delete_key(provider):
    """Remove a stored key. Allowed even in Local-only mode (privacy-positive)."""
    if provider not in secret_store.PROVIDERS:
        return jsonify({"success": False, "error": "Unknown provider."}), 400
    try:
        secret_store.delete_key(provider)
    except Exception:
        logger.error(f"[Settings] deleting {provider} key failed", exc_info=True)
        return jsonify({"success": False,
                        "error": "Could not remove the key."}), 500
    log_activity("settings_key_removed", f"provider={provider}")
    return jsonify({"success": True,
                    "provider": secret_store.provider_status(provider)})


@settings_bp.route("/api/settings/keys/<provider>/test", methods=["POST"])
@login_required
def test_key(provider):
    """Body: {api_key?} — tests the given key (before saving) or the stored/env
    one. Read-only call to the provider's model list; no document content."""
    if provider not in secret_store.PROVIDERS:
        return jsonify({"success": False, "error": "Unknown provider."}), 400
    if not cfg.ALLOW_CLOUD:
        return jsonify({"success": False, "state": "blocked",
                        "error": _LOCAL_ONLY_MSG}), 409
    api_key = ((request.get_json(silent=True) or {}).get("api_key") or "").strip()
    try:
        res = secret_store.test_key(provider, api_key or None)
    except Exception:
        logger.error(f"[Settings] testing {provider} key failed", exc_info=True)
        return jsonify({"success": False, "state": "error",
                        "error": "Connection test failed."}), 500
    log_activity("settings_key_test", f"provider={provider} state={res['state']}")
    return jsonify({"success": res["state"] == "connected", **res})
