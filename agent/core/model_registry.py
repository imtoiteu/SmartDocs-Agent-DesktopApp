"""Model Registry — the platform's inventory of usable LLMs.

One place that answers: which models exist, what each one can do, where it
runs (local / self-hosted / cloud), whether it is usable right now, and how a
provider instance for it is built. The registry is METADATA + construction
only — routing decisions live in ``agent.core.llm_gateway``; loaded torch
weights live in ``services.llm_registry`` (the weights cache this registry
reads states from).

Model profiles (scalable-LLM architecture):

* ``bundled_local``  — the shipped default (Qwen 2.5 1.5B unless LOCAL_LLM_MODEL
                       overrides it). Always registered; the offline fallback.
* ``managed_local``  — additional local HF models the user imported (weights
                       stay OUTSIDE the app bundle; registered by path in
                       settings). Lazily loaded, unloadable.
* ``self_hosted``    — an OpenAI-compatible server (vLLM / llama.cpp /
                       LM Studio / a stronger LAN or private-server box).
* ``groq``/``gemini`` — the existing implicit-cloud providers (keyring keys).

Everything here is import-light: config / services / torch are imported inside
functions only, so this module stays usable in bare test environments.
"""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

TASKS = ("chat", "summarize", "rewrite", "agent")

BUNDLED_ID = "bundled-local"
SELF_HOSTED_ID = "self-hosted"
GROQ_ID = "cloud-groq"
GEMINI_ID = "cloud-gemini"

# Sizing estimate for the bundled 1.5B model (fp32 CPU weights + overhead).
_BUNDLED_EST_GB = 4.0


@dataclass(frozen=True)
class ModelEntry:
    """Display-safe metadata for one registered model/provider. Never holds a key."""

    id: str
    display_name: str
    provider_type: str                  # bundled_local|managed_local|self_hosted|groq|gemini
    locality: str                       # local | self_hosted | cloud
    tasks: tuple = TASKS
    tool_calling: bool = True           # neutral JSON tool protocol (agent) supported
    context_limit: int = 4096           # tokens (estimate; used to budget prompts)
    est_memory_gb: Optional[float] = None
    path: Optional[str] = None          # managed_local: HF snapshot directory
    configured: bool = True             # False → shown but not routable yet

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "provider_type": self.provider_type,
            "locality": self.locality,
            "tasks": list(self.tasks),
            "tool_calling": self.tool_calling,
            "context_limit": self.context_limit,
            "est_memory_gb": self.est_memory_gb,
            "path": self.path,
            "configured": self.configured,
        }


# ── self-hosted URL policy ────────────────────────────────────────────────────
# Mirrors the desktop shell's remote-URL policy (src-tauri runtime.rs) so the
# SAME rules protect the model endpoint: HTTPS always; plain HTTP for loopback
# always; plain HTTP for PRIVATE IP LITERALS only behind the explicit
# insecure-LAN option (no hostname → no DNS → no rebinding surface); embedded
# credentials and public plain-HTTP destinations always refused.

def _is_loopback_host(host: str) -> bool:
    h = (host or "").strip("[]").lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _is_private_lan_ip(host: str) -> bool:
    """A private-range IP LITERAL (RFC1918 / IPv6 unique-local) — not loopback,
    not link-local, and never a hostname."""
    try:
        ip = ipaddress.ip_address((host or "").strip("[]"))
    except ValueError:
        return False
    if ip.is_loopback or ip.is_link_local:
        return False
    if isinstance(ip, ipaddress.IPv4Address):
        return ip.is_private
    return ip in ipaddress.ip_network("fc00::/7")


def check_self_hosted_url(raw: str, allow_insecure_lan: bool = False) -> Tuple[str, str]:
    """Validate a self-hosted base URL. Returns ``(normalized_url, policy)``
    with policy in {"https", "http_local", "http_insecure_lan"}; raises
    ``ValueError`` with an actionable message otherwise."""
    url = (raw or "").strip()
    if not url:
        raise ValueError("Enter the server base URL (e.g. https://host:8000 "
                         "or http://127.0.0.1:8000).")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme {parts.scheme!r} — use http(s)://.")
    if parts.username or parts.password:
        raise ValueError("URLs with embedded credentials are not allowed — "
                         "use the API key field instead.")
    host = parts.hostname or ""
    if not host:
        raise ValueError("The URL has no host.")
    normalized = url.rstrip("/")
    if parts.scheme == "https":
        return normalized, "https"
    if _is_loopback_host(host):
        return normalized, "http_local"
    if _is_private_lan_ip(host):
        if not allow_insecure_lan:
            raise ValueError(
                "Plain HTTP to a private LAN address needs the “Allow insecure "
                "HTTP on private LAN” option — traffic would be unencrypted.")
        return normalized, "http_insecure_lan"
    raise ValueError(
        "Plain HTTP is only allowed for localhost, or for private LAN IP "
        "addresses (10.x / 172.16–31.x / 192.168.x) with the insecure-LAN "
        "option. Use HTTPS for everything else.")


# ── self-hosted connection probe ──────────────────────────────────────────────

def probe_self_hosted_server(base_url: str, model: str = "",
                             context_limit=None, api_key: str = "",
                             timeout: float = 10) -> dict:
    """Probe an OpenAI-compatible server. Returns ``{state, detail, models}``
    with state in {connected, unavailable, timeout, auth_failed, incompatible,
    model_not_found, context_insufficient}.

    Prefers the read-only ``/v1/models`` list (also used to suggest model
    names). Servers without it (404/405/501) are probed with a minimal
    1-token chat completion instead — "ping", never document content — which
    needs the model name. The URL must already have passed
    ``check_self_hosted_url``; policy is the caller's concern.
    """
    import requests  # lazy

    base = base_url[:-3] if base_url.endswith("/v1") else base_url
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        resp = requests.get(f"{base}/v1/models", headers=headers, timeout=timeout)
    except requests.exceptions.Timeout:
        return {"state": "timeout", "models": [],
                "detail": f"The server did not answer within {timeout:g}s."}
    except Exception as e:
        return {"state": "unavailable", "models": [],
                "detail": f"Could not reach the server: {type(e).__name__}"}
    if resp.status_code in (401, 403):
        return {"state": "auth_failed", "models": [],
                "detail": f"Authentication failed (HTTP {resp.status_code})."}
    if resp.status_code in (404, 405, 501):
        if not model:
            return {"state": "incompatible", "models": [], "detail":
                    "The server has no /v1/models list. Enter the model name "
                    "so the test can try a minimal chat completion instead."}
        return _probe_chat_completion(base, model, headers, timeout,
                                      context_limit)
    if resp.status_code != 200:
        return {"state": "incompatible", "models": [],
                "detail": f"The server answered HTTP {resp.status_code} for "
                          "/v1/models — not an OpenAI-compatible API?"}
    try:
        listed = [m.get("id") for m in (resp.json() or {}).get("data") or []]
    except Exception:
        return {"state": "incompatible", "models": [], "detail":
                "The /v1/models response is not the OpenAI-compatible format."}
    listed = [str(x) for x in listed if x][:50]
    if model and listed and model not in listed:
        return {"state": "model_not_found", "models": listed,
                "detail": f"The server does not list model {model!r}. "
                          f"Available: {', '.join(listed[:5])}…"}
    ctx_state = _context_check(context_limit)
    if ctx_state:
        ctx_state["models"] = listed
        return ctx_state
    return {"state": "connected", "models": listed,
            "detail": "Server reachable and OpenAI-compatible."}


def _probe_chat_completion(base: str, model: str, headers: dict,
                           timeout: float, context_limit=None) -> dict:
    """Fallback probe: a 1-token "ping" completion (no document content)."""
    import requests  # lazy

    try:
        resp = requests.post(
            f"{base}/v1/chat/completions",
            json={"model": model, "max_tokens": 1, "temperature": 0,
                  "messages": [{"role": "user", "content": "ping"}]},
            headers=headers, timeout=timeout)
    except requests.exceptions.Timeout:
        return {"state": "timeout", "models": [],
                "detail": f"The server did not answer within {timeout:g}s."}
    except Exception as e:
        return {"state": "unavailable", "models": [],
                "detail": f"Could not reach the server: {type(e).__name__}"}
    if resp.status_code in (401, 403):
        return {"state": "auth_failed", "models": [],
                "detail": f"Authentication failed (HTTP {resp.status_code})."}
    if resp.status_code in (400, 404, 422):
        # OpenAI-compatible servers answer these for an unknown model name.
        return {"state": "model_not_found", "models": [],
                "detail": f"The server rejected model {model!r} "
                          f"(HTTP {resp.status_code})."}
    if resp.status_code != 200:
        return {"state": "incompatible", "models": [],
                "detail": f"The server answered HTTP {resp.status_code} for a "
                          "minimal chat completion — not OpenAI-compatible?"}
    try:
        if not (resp.json() or {}).get("choices"):
            raise ValueError
    except Exception:
        return {"state": "incompatible", "models": [], "detail":
                "The chat-completion response is not the OpenAI-compatible "
                "format."}
    ctx_state = _context_check(context_limit)
    if ctx_state:
        return ctx_state
    return {"state": "connected", "models": [], "detail":
            "Server reachable (verified with a minimal chat completion — "
            "it has no /v1/models list)."}


def _context_check(context_limit) -> Optional[dict]:
    try:
        if context_limit is not None and int(context_limit) < 1024:
            return {"state": "context_insufficient", "models": [],
                    "detail": f"A context limit of {context_limit} tokens is "
                              "too small for document tasks (minimum ~1024)."}
    except (TypeError, ValueError):
        pass
    return None


# ── hardware snapshot (recommendation input only, never a hard gate) ─────────

def hardware_snapshot() -> dict:
    """Best-effort platform/memory facts for sizing recommendations. Values may
    be None where detection is impractical — callers must treat this as a hint,
    not truth (the work runs where the user says it runs)."""
    import platform as _pf

    total = available = None
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        total, available = vm.total, vm.available
    except Exception:
        try:
            page = os.sysconf("SC_PAGE_SIZE")
            total = page * os.sysconf("SC_PHYS_PAGES")
            available = page * os.sysconf("SC_AVPHYS_PAGES")
        except (ValueError, OSError, AttributeError):
            pass
    to_gb = (lambda b: round(b / (1024 ** 3), 1) if b else None)
    return {
        "platform": _pf.system(),
        "machine": _pf.machine(),
        "cpu_count": os.cpu_count(),
        "total_ram_gb": to_gb(total),
        "available_ram_gb": to_gb(available),
    }


def memory_warning(entry: ModelEntry, hw: Optional[dict] = None) -> Optional[str]:
    """A human warning when a LOCAL model likely exceeds available memory —
    advisory only (detection can be wrong; the user may know better)."""
    if entry.locality != "local" or not entry.est_memory_gb:
        return None
    hw = hw or hardware_snapshot()
    avail = hw.get("available_ram_gb")
    if avail is not None and entry.est_memory_gb > avail:
        return (f"{entry.display_name} is estimated to need "
                f"~{entry.est_memory_gb:g} GB but only ~{avail:g} GB of memory "
                "appears to be available — loading it may fail or thrash. "
                "This is an estimate, not a hard limit.")
    return None


# ── registry enumeration ──────────────────────────────────────────────────────

def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug or "model"


def _llm_settings() -> dict:
    from services import settings_store
    return settings_store.get_llm_settings()


def self_hosted_config() -> dict:
    """The effective self-hosted endpoint config. Environment variables set
    EXTERNALLY (.env — the pre-existing configuration surface) win over the
    Settings values, exactly like ALLOW_CLOUD; ``env_locked`` tells the UI."""
    from services import settings_store
    stored = dict(_llm_settings().get("self_hosted") or {})
    env_locked = settings_store.env_self_hosted_is_explicit()
    if env_locked:
        stored["base_url"] = (os.environ.get("OPENAI_COMPATIBLE_BASE_URL") or "").strip()
        stored["model"] = (os.environ.get("OPENAI_COMPATIBLE_MODEL") or "").strip()
    stored["env_locked"] = env_locked
    stored["configured"] = bool(stored.get("base_url") and stored.get("model"))
    return stored


def list_models() -> List[ModelEntry]:
    """Every registered model, configured or not (the UI shows both; the
    router only accepts configured ones)."""
    entries: List[ModelEntry] = [_bundled_entry()]
    entries.extend(_managed_entries())

    sh = self_hosted_config()
    entries.append(ModelEntry(
        id=SELF_HOSTED_ID,
        display_name=(f"Self-hosted — {sh['model']}" if sh["configured"]
                      else "Self-hosted server (not configured)"),
        provider_type="self_hosted",
        locality="self_hosted",
        context_limit=int(sh.get("context_limit") or 8192),
        configured=sh["configured"],
    ))

    from services import secret_store
    entries.append(ModelEntry(
        id=GROQ_ID,
        display_name="Groq (cloud)",
        provider_type="groq",
        locality="cloud",
        context_limit=32768,
        configured=bool(secret_store.get_key("groq")),
    ))
    entries.append(ModelEntry(
        id=GEMINI_ID,
        display_name="Google Gemini (cloud)",
        provider_type="gemini",
        locality="cloud",
        context_limit=131072,
        configured=bool(secret_store.get_key("gemini")),
    ))
    return entries


def _bundled_entry() -> ModelEntry:
    from config import cfg
    return ModelEntry(
        id=BUNDLED_ID,
        display_name=f"Bundled local — {cfg.LOCAL_LLM_MODEL.split('/')[-1]}",
        provider_type="bundled_local",
        locality="local",
        context_limit=4096,                 # matches LocalQwenProvider's budget
        est_memory_gb=_BUNDLED_EST_GB,
    )


def _managed_entries() -> List[ModelEntry]:
    out: List[ModelEntry] = []
    for item in _llm_settings().get("managed_local") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        out.append(ModelEntry(
            id=str(item["id"]),
            display_name=str(item.get("display_name") or item["id"]),
            provider_type="managed_local",
            locality="local",
            context_limit=int(item.get("context_limit") or 4096),
            est_memory_gb=item.get("est_memory_gb"),
            path=str(item.get("path") or "") or None,
            configured=bool(item.get("path")),
        ))
    return out


def get_model(model_id: str) -> Optional[ModelEntry]:
    for entry in list_models():
        if entry.id == model_id:
            return entry
    return None


# ── model state ───────────────────────────────────────────────────────────────

def model_state(entry: ModelEntry) -> str:
    """installed | unavailable | loading | ready | failed — read-only (never
    triggers a load; reuses existing status snapshots + the weights cache)."""
    if entry.locality != "local":
        return "installed" if entry.configured else "unavailable"
    try:
        from services import llm_registry
        if any(k[0] in (_local_key_ids(entry)) for k in llm_registry.loaded_keys()):
            return "ready"
    except Exception:
        pass
    if entry.provider_type == "bundled_local":
        try:
            from services import ai_rewrite_service
            st = ai_rewrite_service.get_ai_status()
            if st.get("local"):
                return "ready"
            if st.get("local_loading"):
                return "loading"
            if st.get("local_error"):
                return "failed"
        except Exception:
            pass
        try:
            from config import cfg
            return "installed" if cfg._has_hf_model(cfg.LOCAL_LLM_MODEL) else "unavailable"
        except Exception:
            return "installed"
    # managed_local: installed when the snapshot directory looks like a model
    if entry.path and os.path.isdir(entry.path) and \
            os.path.isfile(os.path.join(entry.path, "config.json")):
        return "installed"
    return "unavailable"


def _local_key_ids(entry: ModelEntry) -> tuple:
    """The llm_registry key model-ids this entry may be loaded under."""
    if entry.provider_type == "managed_local":
        return (entry.path or entry.id,)
    try:
        from config import cfg
        return (cfg.QWEN_MODEL, cfg.CHAT_MODEL, cfg.LOCAL_LLM_MODEL)
    except Exception:
        return ()


# ── provider construction ─────────────────────────────────────────────────────

def build_provider(entry: ModelEntry):
    """An ``LLMProvider`` for a registry entry. Raises ValueError when the
    entry is not configured (the router turns that into an actionable error)."""
    from agent.core import provider as P

    if not entry.configured:
        raise ValueError(f"{entry.display_name} is not configured.")
    if entry.provider_type == "bundled_local":
        return P.LocalQwenProvider()
    if entry.provider_type == "managed_local":
        return P.ManagedLocalProvider(entry.id, entry.path or "",
                                      context_limit=entry.context_limit)
    if entry.provider_type == "self_hosted":
        sh = self_hosted_config()
        key = (os.environ.get("OPENAI_COMPATIBLE_API_KEY") or "").strip()
        return P.OpenAICompatibleProvider(
            sh["base_url"], sh["model"], key,
            timeout=int(sh.get("timeout_s") or 120))
    if entry.provider_type == "groq":
        from services import secret_store
        return P.GroqProvider(secret_store.get_key("groq") or "",
                              (os.environ.get("GROQ_MODEL") or P.DEFAULT_GROQ_MODEL).strip())
    if entry.provider_type == "gemini":
        from services import secret_store
        return P.GeminiProvider(secret_store.get_key("gemini") or "",
                                (os.environ.get("GEMINI_MODEL") or P.DEFAULT_GEMINI_MODEL).strip())
    raise ValueError(f"Unknown provider type: {entry.provider_type}")
