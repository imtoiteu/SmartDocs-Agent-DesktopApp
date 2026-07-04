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
    """Startup hook: overlay the persisted UI toggle onto the config default —
    unless ALLOW_CLOUD was set externally, which always wins. Never raises."""
    try:
        if env_allow_cloud_is_explicit():
            return
        persisted = get_allow_cloud(path)
        if persisted is not None:
            _apply_runtime(persisted)
    except Exception:
        logger.warning("[Settings] applying persisted settings failed", exc_info=True)
