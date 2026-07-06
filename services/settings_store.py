"""Persisted NON-SECRET user settings (Settings items 2/7).

A tiny JSON file next to the database holds settings that must survive a
restart but are not secrets (secrets live in the OS credential store — see
``services.secret_store``). Currently:

* ``allow_cloud``  — the "Local only / Allow cloud processing" switch chosen in
                     the UI. An explicitly-set ALLOW_CLOUD env var still WINS
                     (developer / backward-compatible configuration).
* ``cloud_ack``    — the user has confirmed, once, that cloud processing sends
                     document text and prompts to the configured provider.

The resolved value is mirrored into ``os.environ["ALLOW_CLOUD"]`` and
``cfg.ALLOW_CLOUD`` so every existing consumer (provider chain, translation,
AI rewrite) follows the toggle without re-reading anything.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _settings_path() -> Path:
    from config import cfg
    return Path(cfg.DB_PATH).parent / "app_settings.json"


def _read(path: Optional[Path] = None) -> dict:
    p = path or _settings_path()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:                  # corrupt file → defaults, not a crash
        logger.warning(f"[Settings] unreadable {p}: {e}")
        return {}


def _write(data: dict, path: Optional[Path] = None) -> None:
    p = path or _settings_path()
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp.replace(p)                          # atomic on POSIX/NTFS


def env_allow_cloud_is_explicit() -> bool:
    """True when ALLOW_CLOUD was set externally (env/.env) — that always wins
    over the UI toggle, and the UI shows the setting as env-locked."""
    return (os.environ.get("ALLOW_CLOUD") or "").strip() != "" \
        and os.environ.get("_ALLOW_CLOUD_MANAGED") != "1"


def get_allow_cloud(path: Optional[Path] = None) -> Optional[bool]:
    """The persisted UI choice, or None when the user never toggled it."""
    val = _read(path).get("allow_cloud")
    return val if isinstance(val, bool) else None


def get_cloud_ack(path: Optional[Path] = None) -> bool:
    return _read(path).get("cloud_ack") is True


def set_cloud_ack(path: Optional[Path] = None) -> None:
    with _lock:
        data = _read(path)
        data["cloud_ack"] = True
        _write(data, path)


def _apply_runtime(allow: bool) -> None:
    """Mirror the resolved value into cfg + this process's env so every
    consumer (cfg.ALLOW_CLOUD readers AND provider.cloud_allowed()) agrees."""
    from config import cfg
    cfg.ALLOW_CLOUD = bool(allow)
    os.environ["ALLOW_CLOUD"] = "true" if allow else "false"
    os.environ["_ALLOW_CLOUD_MANAGED"] = "1"    # marks it as ours, not external


def set_allow_cloud(allow: bool, path: Optional[Path] = None) -> None:
    """Persist the UI toggle and apply it immediately. Refused (ValueError)
    when ALLOW_CLOUD is env-locked — the UI shows why instead of lying."""
    if env_allow_cloud_is_explicit():
        raise ValueError(
            "ALLOW_CLOUD is set in the environment/.env and overrides the UI "
            "toggle. Remove it from .env to control this from Settings.")
    with _lock:
        data = _read(path)
        data["allow_cloud"] = bool(allow)
        _write(data, path)
    _apply_runtime(bool(allow))
    logger.info(f"[Settings] allow_cloud → {allow}")


def apply_persisted_settings(path: Optional[Path] = None) -> None:
    """Startup hook: overlay the persisted UI toggles onto the config defaults —
    unless the matching env var was set externally, which always wins. Never
    raises."""
    try:
        if not env_allow_cloud_is_explicit():
            persisted = get_allow_cloud(path)
            if persisted is not None:
                _apply_runtime(persisted)
    except Exception:
        logger.warning("[Settings] applying persisted settings failed", exc_info=True)
    try:
        _apply_llm_runtime(get_llm_settings(path))
    except Exception:
        logger.warning("[Settings] applying LLM settings failed", exc_info=True)


# ── LLM model settings (Model Registry / Router configuration) ───────────────
# Non-secret model configuration: task routing, the self-hosted endpoint
# (URL/model/limits — the API key stays in the OS credential store, see
# secret_store), and imported managed-local models. Missing keys fall back to
# defaults on read (the settings-schema migration: old files stay valid and
# untouched until the user changes something; unknown keys are preserved).

LLM_DEFAULTS: dict = {
    "task_models": {"chat": "auto", "summarize": "auto",
                    "rewrite": "auto", "agent": "auto"},
    "fallback_model": None,
    "self_hosted": {"base_url": "", "model": "", "context_limit": 8192,
                    "timeout_s": 120, "allow_insecure_lan": False,
                    "insecure_lan_ack": False},
    "managed_local": [],
}


def _merged_llm(data: dict) -> dict:
    """The stored ``llm`` section deep-merged over the defaults."""
    stored = data.get("llm") if isinstance(data.get("llm"), dict) else {}
    out = json.loads(json.dumps(LLM_DEFAULTS))        # deep copy
    for key, val in stored.items():
        if key in ("task_models", "self_hosted") and isinstance(val, dict):
            out[key].update(val)
        elif key == "managed_local" and isinstance(val, list):
            out[key] = val
        else:
            out[key] = val
    return out


def get_llm_settings(path: Optional[Path] = None) -> dict:
    return _merged_llm(_read(path))


def env_self_hosted_is_explicit() -> bool:
    """True when OPENAI_COMPATIBLE_BASE_URL comes from outside (.env/env) —
    the pre-existing configuration surface, which always wins over Settings."""
    return (os.environ.get("OPENAI_COMPATIBLE_BASE_URL") or "").strip() != "" \
        and os.environ.get("_OPENAI_COMPATIBLE_MANAGED") != "1"


def _apply_llm_runtime(llm: dict) -> None:
    """Mirror the Settings-configured self-hosted endpoint into this process's
    env (+cfg) so every pre-existing consumer of OPENAI_COMPATIBLE_* follows it
    without changes — unless the env was set externally, which wins."""
    if env_self_hosted_is_explicit():
        return
    sh = llm.get("self_hosted") or {}
    base = (sh.get("base_url") or "").strip()
    model = (sh.get("model") or "").strip()
    if base and model:
        os.environ["OPENAI_COMPATIBLE_BASE_URL"] = base
        os.environ["OPENAI_COMPATIBLE_MODEL"] = model
        os.environ["_OPENAI_COMPATIBLE_MANAGED"] = "1"
    elif os.environ.get("_OPENAI_COMPATIBLE_MANAGED") == "1":
        os.environ.pop("OPENAI_COMPATIBLE_BASE_URL", None)
        os.environ.pop("OPENAI_COMPATIBLE_MODEL", None)
        os.environ.pop("_OPENAI_COMPATIBLE_MANAGED", None)
    try:
        from config import cfg
        cfg.OPENAI_COMPATIBLE_BASE_URL = os.environ.get("OPENAI_COMPATIBLE_BASE_URL", "")
        cfg.OPENAI_COMPATIBLE_MODEL = os.environ.get("OPENAI_COMPATIBLE_MODEL", "")
    except Exception:
        pass


def set_llm_settings(patch: dict, path: Optional[Path] = None) -> dict:
    """Merge a partial update into the ``llm`` section, persist, and apply it
    immediately. Only known top-level keys are accepted; everything else in
    the settings file is preserved. Returns the effective settings."""
    if not isinstance(patch, dict):
        raise ValueError("Expected a settings object.")
    unknown = set(patch) - set(LLM_DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown LLM settings: {', '.join(sorted(unknown))}")
    with _lock:
        data = _read(path)
        merged = _merged_llm(data)
        for key, val in patch.items():
            if key in ("task_models", "self_hosted") and isinstance(val, dict):
                merged[key].update(val)
            else:
                merged[key] = val
        data["llm"] = merged
        _write(data, path)
    _apply_llm_runtime(merged)
    logger.info("[Settings] llm settings updated (%s)", ", ".join(sorted(patch)))
    return merged
