"""Cloud API-key storage backed by the OS credential store (Settings item 1).

Secrets live in the operating system's keyring (macOS Keychain / Windows
Credential Manager / Secret Service on Linux) via the ``keyring`` package —
NEVER in localStorage, the app database, plaintext config files, or logs.
Environment variables keep working and always WIN over the keyring (developer /
backward-compatible configuration); a key stored here is mirrored into this
process's environment only, so the existing provider chains (which read
``os.environ``) pick it up without persistence anywhere insecure.

All read paths return MASKED values for display; the full key is never sent
back to a client and never logged (``mask()`` keeps only the last 4 chars).
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_SERVICE = "SmartDocs"                      # keyring service name

# Supported cloud providers → the env var each one is configured through.
# These are the two implicit-cloud LLM providers the app actually uses.
PROVIDERS: Dict[str, str] = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

_lock = threading.Lock()
# Env vars WE set from the keyring (vs set externally by the user/.env). Only
# managed vars may be overwritten/removed when the stored key changes.
_managed_env: set = set()


def _keyring():
    """The keyring module, imported lazily (optional dependency)."""
    import keyring  # noqa: PLC0415
    return keyring


def keyring_available() -> Tuple[bool, str]:
    """(available, backend-name-or-reason). A fail/null backend counts as
    unavailable — storing a secret must never silently no-op."""
    try:
        kr = _keyring()
        backend = kr.get_keyring()
        name = f"{type(backend).__module__}.{type(backend).__name__}"
        if "fail" in name.lower() or "null" in name.lower():
            return False, name
        return True, name
    except Exception as e:                  # not installed / no backend
        return False, f"{type(e).__name__}: {e}"


def mask(key: Optional[str]) -> str:
    """Display form of a key: last 4 chars only, never the full value."""
    if not key:
        return ""
    key = str(key)
    if len(key) <= 4:
        return "••••"
    return "••••" + key[-4:]


def key_source(provider: str) -> Optional[str]:
    """Where the effective key comes from: 'env' (external), 'keyring', or None."""
    var = PROVIDERS.get(provider)
    if not var:
        return None
    if os.environ.get(var) and var not in _managed_env:
        return "env"
    try:
        if _keyring().get_password(_SERVICE, var):
            return "keyring"
    except Exception:
        pass
    if os.environ.get(var):                 # managed leftover (keyring gone)
        return "keyring"
    return None


def get_key(provider: str) -> Optional[str]:
    """The effective API key: externally-set env var wins, else the keyring.
    For internal use only — callers must never echo this to a client or log."""
    var = PROVIDERS.get(provider)
    if not var:
        return None
    env_val = os.environ.get(var)
    if env_val and var not in _managed_env:
        return env_val
    try:
        stored = _keyring().get_password(_SERVICE, var)
        if stored:
            return stored
    except Exception as e:
        logger.warning(f"[Secrets] keyring read failed for {provider}: {e}")
    return env_val or None


def set_key(provider: str, key: str) -> None:
    """Store/update a provider key in the OS credential store and mirror it
    into this process's environment (unless an external env var already wins).
    Raises on unknown provider, empty key, or unusable keyring."""
    var = PROVIDERS.get(provider)
    if not var:
        raise ValueError(f"Unknown provider: {provider!r}")
    key = (key or "").strip()
    if not key:
        raise ValueError("API key must not be empty")
    ok, backend = keyring_available()
    if not ok:
        raise RuntimeError(f"OS credential store unavailable ({backend})")
    with _lock:
        _keyring().set_password(_SERVICE, var, key)
        if not os.environ.get(var) or var in _managed_env:
            os.environ[var] = key
            _managed_env.add(var)
    logger.info(f"[Secrets] stored key for {provider} ({mask(key)}) in {backend}")


def delete_key(provider: str) -> None:
    """Remove a provider key from the credential store (and from the process
    env if we put it there). Missing keys are a no-op, not an error."""
    var = PROVIDERS.get(provider)
    if not var:
        raise ValueError(f"Unknown provider: {provider!r}")
    with _lock:
        try:
            _keyring().delete_password(_SERVICE, var)
        except Exception:
            pass                            # not stored / backend quirk → no-op
        if var in _managed_env:
            os.environ.pop(var, None)
            _managed_env.discard(var)
    logger.info(f"[Secrets] removed stored key for {provider}")


def load_into_env() -> int:
    """Startup hook: mirror keyring-stored keys into the process env for vars
    not already set externally, so provider chains work unchanged. Returns how
    many were loaded. Never raises (keyring is optional)."""
    loaded = 0
    for provider, var in PROVIDERS.items():
        if os.environ.get(var):
            continue                        # external config wins
        try:
            stored = _keyring().get_password(_SERVICE, var)
        except Exception:
            return loaded                   # no keyring at all — stop quietly
        if stored:
            with _lock:
                os.environ[var] = stored
                _managed_env.add(var)
            loaded += 1
            logger.info(f"[Secrets] loaded {provider} key from OS credential store")
    return loaded


# Cheap read-only endpoints used to validate a key ("Test connection").
# Overridable so tests can point them at a local fake server.
TEST_URLS: Dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1/models",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
}


def test_key(provider: str, api_key: Optional[str] = None,
             timeout: float = 10.0) -> Dict[str, str]:
    """Validate a key against the provider's model-list endpoint (read-only,
    no document content is sent). Uses the stored/env key when ``api_key`` is
    not given (so a just-typed key can be tested BEFORE saving). Returns
    {"state": "connected" | "invalid" | "error" | "not_configured",
     "detail": short human text} — never the key itself.
    """
    import requests  # lazy

    if provider not in PROVIDERS:
        return {"state": "error", "detail": f"Unknown provider: {provider}"}
    key = (api_key or "").strip() or get_key(provider)
    if not key:
        return {"state": "not_configured", "detail": "No API key to test."}
    url = TEST_URLS[provider]
    headers = ({"Authorization": f"Bearer {key}"} if provider == "groq"
               else {"x-goog-api-key": key})
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except Exception as e:
        return {"state": "error",
                "detail": f"Could not reach {provider}: {type(e).__name__}"}
    if resp.status_code == 200:
        return {"state": "connected", "detail": "Key accepted."}
    if resp.status_code in (401, 403, 400):
        return {"state": "invalid",
                "detail": f"Key rejected (HTTP {resp.status_code})."}
    return {"state": "error",
            "detail": f"{provider} answered HTTP {resp.status_code}."}


def provider_status(provider: str) -> Dict[str, object]:
    """Display-safe status for one provider: configured?, masked hint, source.
    Never includes the key itself."""
    key = get_key(provider)
    return {
        "provider": provider,
        "configured": bool(key),
        "masked": mask(key),
        "source": key_source(provider),
    }
