"""Models Blueprint — the Model Registry / Router HTTP surface.

Settings → AI models talks to these endpoints: the model inventory (with
per-model readiness states), task routing (which model answers Chat /
Summarization / Rewrite / Agent), the self-hosted OpenAI-compatible endpoint
(URL policy identical to the desktop shell's remote-server policy: HTTPS
always, plain HTTP for localhost, private-LAN IP literals only behind the
explicit insecure-LAN confirmation), managed-local model import/removal, and
unloading resident weights.

Never returns a key; never triggers a model load (states are read-only).
"""

from __future__ import annotations

import logging

from flask import Blueprint, request, jsonify
from flask_login import login_required

from agent.core import llm_gateway, model_registry
from models import log_activity
from services import secret_store, settings_store

logger = logging.getLogger(__name__)
models_bp = Blueprint("models", __name__)

_INSECURE_ACK_MSG = ("Everything sent to this server — prompts and document "
                     "text — will travel unencrypted over the local network. "
                     "Anyone on the same network could read or alter it. "
                     "Confirm to continue.")


def _models_payload() -> dict:
    hw = model_registry.hardware_snapshot()
    models = []
    for entry in model_registry.list_models():
        d = entry.to_dict()
        d["state"] = model_registry.model_state(entry)
        d["memory_warning"] = model_registry.memory_warning(entry, hw)
        models.append(d)
    sh = model_registry.self_hosted_config()
    return {
        "success": True,
        "models": models,
        "routing": llm_gateway.routing_config(),
        "tasks": list(llm_gateway.TASKS),
        "self_hosted": {                          # never the API key
            "base_url": sh.get("base_url") or "",
            "model": sh.get("model") or "",
            "context_limit": sh.get("context_limit"),
            "timeout_s": sh.get("timeout_s"),
            "allow_insecure_lan": bool(sh.get("allow_insecure_lan")),
            "insecure_lan_ack": bool(sh.get("insecure_lan_ack")),
            "env_locked": bool(sh.get("env_locked")),
            "configured": bool(sh.get("configured")),
            "key": secret_store.provider_status("self_hosted"),
        },
        "hardware": hw,
    }


@models_bp.route("/api/models", methods=["GET"])
@login_required
def get_models():
    return jsonify(_models_payload())


@models_bp.route("/api/models/routing", methods=["PUT"])
@login_required
def set_routing():
    """Body: {task_models?: {task: model_id|"auto"}, fallback_model?: id|null}.
    Every explicit choice is validated NOW (exists, capability, Local-only) so
    a bad route fails here with a clear message, not later mid-request."""
    data = request.get_json(silent=True) or {}
    patch: dict = {}
    if "task_models" in data:
        tm = data.get("task_models") or {}
        if not isinstance(tm, dict):
            return jsonify({"success": False, "error": "task_models must be an object."}), 400
        for task, model_id in tm.items():
            if task not in llm_gateway.TASKS:
                return jsonify({"success": False, "error": f"Unknown task: {task}"}), 400
            model_id = (model_id or llm_gateway.AUTO).strip()
            if model_id != llm_gateway.AUTO:
                entry = model_registry.get_model(model_id)
                if entry is None:
                    return jsonify({"success": False,
                                    "error": f"Unknown model: {model_id}"}), 400
                try:
                    llm_gateway._check_routable(entry, task)
                except llm_gateway.RouteError as e:
                    return jsonify({"success": False, "error": str(e)}), 409
            tm[task] = model_id
        patch["task_models"] = tm
    if "fallback_model" in data:
        fb = data.get("fallback_model")
        if fb and fb != llm_gateway.AUTO and model_registry.get_model(fb) is None:
            return jsonify({"success": False, "error": f"Unknown model: {fb}"}), 400
        patch["fallback_model"] = fb or None
    try:
        settings_store.set_llm_settings(patch)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    log_activity("models_routing", ", ".join(
        f"{k}={v}" for k, v in (patch.get("task_models") or {}).items()))
    return jsonify(_models_payload())


@models_bp.route("/api/models/self-hosted", methods=["PUT"])
@login_required
def set_self_hosted():
    """Body: {base_url, model, context_limit?, timeout_s?, allow_insecure_lan?,
    ack?}. URL policy enforced here; a first plain-HTTP-LAN save needs the
    explicit ack (409 needs_ack — same flow as the cloud-privacy ack)."""
    if settings_store.env_self_hosted_is_explicit():
        return jsonify({"success": False, "error":
                        "OPENAI_COMPATIBLE_BASE_URL is set in the environment/"
                        ".env and overrides these settings. Remove it there to "
                        "configure the server from Settings."}), 409
    data = request.get_json(silent=True) or {}
    base_url = (data.get("base_url") or "").strip()
    model = (data.get("model") or "").strip()
    allow_lan = bool(data.get("allow_insecure_lan"))
    sh: dict = {"base_url": base_url, "model": model,
                "allow_insecure_lan": allow_lan}

    routes_reset: list = []
    route_patch: dict = {}
    if base_url:
        try:
            normalized, policy = model_registry.check_self_hosted_url(
                base_url, allow_insecure_lan=allow_lan)
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        sh["base_url"] = normalized
        if policy == "http_insecure_lan":
            stored = settings_store.get_llm_settings().get("self_hosted") or {}
            if not (data.get("ack") or stored.get("insecure_lan_ack")):
                return jsonify({"success": False, "needs_ack": True,
                                "message": _INSECURE_ACK_MSG}), 409
            sh["insecure_lan_ack"] = True
        if not model:
            return jsonify({"success": False,
                            "error": "Enter the model name the server serves."}), 400
    else:
        # Clear/disable: routes still pointing at the now-unconfigured server
        # would fail on every request — return them to Automatic and SAY so
        # (the UI confirms the clear and reports the reset; never silent).
        llm = settings_store.get_llm_settings()
        task_models = dict(llm.get("task_models") or {})
        for task, mid in task_models.items():
            if mid == model_registry.SELF_HOSTED_ID:
                task_models[task] = llm_gateway.AUTO
                routes_reset.append(task)
        if routes_reset:
            route_patch["task_models"] = task_models
        if llm.get("fallback_model") == model_registry.SELF_HOSTED_ID:
            route_patch["fallback_model"] = None
            routes_reset.append("fallback")

    for field, lo, hi in (("context_limit", 256, 2_000_000),
                          ("timeout_s", 5, 3600)):
        if data.get(field) is not None:
            try:
                val = int(data[field])
            except (TypeError, ValueError):
                return jsonify({"success": False,
                                "error": f"{field} must be a number."}), 400
            if not lo <= val <= hi:
                return jsonify({"success": False,
                                "error": f"{field} must be between {lo} and {hi}."}), 400
            sh[field] = val

    try:
        settings_store.set_llm_settings({"self_hosted": sh, **route_patch})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    log_activity("models_self_hosted",
                 f"configured={bool(base_url and model)}" +
                 (f" routes_reset={','.join(routes_reset)}" if routes_reset else ""))
    payload = _models_payload()
    payload["routes_reset"] = routes_reset
    return jsonify(payload)


@models_bp.route("/api/models/self-hosted/test", methods=["POST"])
@login_required
def test_self_hosted():
    """Connection test (never document content). Body may override {base_url,
    model, allow_insecure_lan, api_key, context_limit} to test BEFORE saving.
    Prefers the read-only /v1/models list (echoed back as name suggestions);
    servers without it get a minimal 1-token chat completion. States:
    connected | unavailable | timeout | auth_failed | incompatible |
    model_not_found | context_insufficient | policy_blocked.
    Self-hosted is available in Local-only mode by definition."""
    data = request.get_json(silent=True) or {}
    stored = model_registry.self_hosted_config()
    base_url = (data.get("base_url") or stored.get("base_url") or "").strip()
    model = (data.get("model") or stored.get("model") or "").strip()
    allow_lan = bool(data.get("allow_insecure_lan",
                              stored.get("allow_insecure_lan")))
    if not base_url:
        return jsonify({"success": False, "state": "unavailable",
                        "detail": "No server URL configured."})
    try:
        normalized, policy = model_registry.check_self_hosted_url(
            base_url, allow_insecure_lan=allow_lan)
    except ValueError as e:
        return jsonify({"success": False, "state": "policy_blocked",
                        "detail": str(e)}), 400

    key = ((data.get("api_key") or "").strip()
           or secret_store.get_key("self_hosted") or "")
    result = model_registry.probe_self_hosted_server(
        normalized, model=model, api_key=key,
        context_limit=data.get("context_limit", stored.get("context_limit")))
    result["success"] = result["state"] == "connected"
    result["policy"] = policy
    log_activity("models_self_hosted_test",
                 f"state={result['state']} policy={policy}")
    return jsonify(result)


@models_bp.route("/api/models/managed", methods=["POST"])
@login_required
def add_managed():
    """Import a compatible local model already on disk (Managed Local): body
    {path, display_name?, context_limit?, est_memory_gb?}. Registers metadata
    only — weights stay where they are (outside the app bundle), loading stays
    lazy. A likely-too-big model gets a warning, not a refusal."""
    import os

    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path or not os.path.isdir(path):
        return jsonify({"success": False,
                        "error": "Enter the folder of a downloaded model."}), 400
    if not os.path.isfile(os.path.join(path, "config.json")):
        return jsonify({"success": False, "error":
                        "That folder does not look like a Hugging Face model "
                        "(no config.json)."}), 400
    display = (data.get("display_name") or os.path.basename(path.rstrip("/\\"))).strip()
    model_id = "local-" + model_registry.slugify(display)
    items = settings_store.get_llm_settings().get("managed_local") or []
    if any(i.get("id") == model_id for i in items) or \
            model_registry.get_model(model_id) is not None:
        return jsonify({"success": False,
                        "error": f"A model named {model_id} already exists."}), 409
    item = {"id": model_id, "path": path, "display_name": display}
    for field in ("context_limit", "est_memory_gb"):
        if data.get(field) is not None:
            try:
                item[field] = float(data[field]) if field == "est_memory_gb" \
                    else int(data[field])
            except (TypeError, ValueError):
                return jsonify({"success": False,
                                "error": f"{field} must be a number."}), 400
    settings_store.set_llm_settings({"managed_local": items + [item]})
    log_activity("models_managed_added", model_id)
    return jsonify(_models_payload())


@models_bp.route("/api/models/managed/<model_id>", methods=["DELETE"])
@login_required
def remove_managed(model_id):
    """Unregister a managed model (weights on disk are NOT deleted). Resident
    weights are released first when possible."""
    items = settings_store.get_llm_settings().get("managed_local") or []
    kept = [i for i in items if i.get("id") != model_id]
    if len(kept) == len(items):
        return jsonify({"success": False, "error": "Unknown model."}), 404
    entry = model_registry.get_model(model_id)
    try:
        if entry is not None and entry.path:
            from services import llm_registry
            llm_registry.unload(entry.path)
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 409
    settings_store.set_llm_settings({"managed_local": kept})
    log_activity("models_managed_removed", model_id)
    return jsonify(_models_payload())


@models_bp.route("/api/models/<model_id>/unload", methods=["POST"])
@login_required
def unload_model(model_id):
    """Release a MANAGED model's resident weights. The bundled model is owned
    by the Chat/Rewrite services (which keep their own references), so
    unloading it here would not actually free memory — refused honestly."""
    entry = model_registry.get_model(model_id)
    if entry is None:
        return jsonify({"success": False, "error": "Unknown model."}), 404
    if entry.provider_type != "managed_local" or not entry.path:
        return jsonify({"success": False, "error":
                        "Only imported (managed) models can be unloaded here — "
                        "the bundled model stays resident while Chat/Rewrite "
                        "are enabled."}), 400
    from services import llm_registry
    try:
        released = llm_registry.unload(entry.path)
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 409
    log_activity("models_unloaded", f"{model_id} entries={released}")
    return jsonify(_models_payload())
