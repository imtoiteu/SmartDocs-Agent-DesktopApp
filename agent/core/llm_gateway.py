"""LLM Gateway + Model Router — one routing decision for every LLM consumer.

Chat / Document QA, Summarization, AI Rewrite, and Agent planning/synthesis
all ask THIS module which model handles a task, instead of each keeping its
own selection logic. Rules:

* Every task defaults to ``"auto"``, which reproduces the exact pre-existing
  behavior of that consumer (legacy chains, env-var driven) — existing users
  and configurations see NO change until they pick a model in Settings.
* An explicitly routed model is used as-is. There is NO silent fallback across
  the local / self-hosted / cloud boundaries: the only fallback for an
  explicit route is the user-configured ``fallback_model`` (explicit policy).
* A cloud model is never routed while Local-only is enabled — the route fails
  with an actionable error instead (``RouteError``).
* Capability-based checks: the task must be in the model's ``tasks`` and the
  prompt is fitted to the model's ``context_limit`` (adapt) before sending.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from . import model_registry as registry
from .provider import (LLMProvider, FallbackProvider, Message,
                       cloud_allowed, fit_messages_to_char_budget,
                       get_default_provider, _CHARS_PER_TOKEN)

logger = logging.getLogger(__name__)

TASKS = registry.TASKS
AUTO = "auto"


class RouteError(RuntimeError):
    """A routing decision that cannot be honored — the message is actionable
    and safe to show to the user (never a secret, never a stack trace)."""


@dataclass(frozen=True)
class Route:
    task: str
    kind: str                                   # "legacy" | "model"
    entry: Optional[registry.ModelEntry] = None
    fallback: Optional[registry.ModelEntry] = None


def routing_config() -> dict:
    """{"task_models": {task: model_id|"auto"}, "fallback_model": id|None}."""
    from services import settings_store
    llm = settings_store.get_llm_settings()
    return {"task_models": dict(llm.get("task_models") or {}),
            "fallback_model": llm.get("fallback_model")}


def _check_routable(entry: registry.ModelEntry, task: str) -> None:
    if task not in entry.tasks:
        raise RouteError(
            f"{entry.display_name} does not support the {task} task — choose "
            "another model in Settings → AI models.")
    if entry.locality == "cloud" and not cloud_allowed():
        raise RouteError(
            f"{entry.display_name} is a cloud provider and Local only is "
            "enabled — nothing is sent to the cloud in this mode. Pick a "
            "local or self-hosted model, or allow cloud processing in "
            "Settings → Privacy.")
    if not entry.configured:
        raise RouteError(
            f"{entry.display_name} is not configured yet — finish its setup "
            "in Settings → AI models.")


def resolve(task: str) -> Route:
    """The routing decision for a task. ``auto`` → legacy behavior; an explicit
    model id is validated (exists, capability, Local-only, configured) and
    NEVER silently replaced."""
    if task not in TASKS:
        raise RouteError(f"Unknown LLM task: {task!r}")
    cfg = routing_config()
    selection = (cfg["task_models"].get(task) or AUTO).strip()
    if selection == AUTO:
        return Route(task=task, kind="legacy")

    entry = registry.get_model(selection)
    if entry is None:
        raise RouteError(
            f"The model configured for {task} ({selection}) is no longer "
            "available — pick another in Settings → AI models.")
    _check_routable(entry, task)

    fallback = None
    fb_id = cfg.get("fallback_model")
    if fb_id and fb_id != AUTO and fb_id != entry.id:
        fb = registry.get_model(fb_id)
        if fb is not None:
            try:
                _check_routable(fb, task)
                fallback = fb
            except RouteError as e:
                # A blocked fallback never blocks the primary — and never
                # routes anyway (that would be the silent cloud path).
                logger.info("[Gateway] fallback %s skipped for %s: %s",
                            fb_id, task, e)
    return Route(task=task, kind="model", entry=entry, fallback=fallback)


class _FittedProvider(LLMProvider):
    """Adapt prompts to the routed model's context limit before sending —
    newest-content-first fitting, same policy as the local provider."""

    def __init__(self, inner: LLMProvider, context_limit: int) -> None:
        self.inner = inner
        self.max_chars = max(int(context_limit), 256) * _CHARS_PER_TOKEN
        self.name = getattr(inner, "name", "provider")

    def complete(self, messages: List[Message], *, max_tokens: int = 512,
                 temperature: float = 0.2) -> str:
        fitted = fit_messages_to_char_budget(list(messages), self.max_chars)
        out = self.inner.complete(fitted, max_tokens=max_tokens,
                                  temperature=temperature)
        self.name = getattr(self.inner, "name", self.name)
        return out


def provider_for_route(route: Route) -> LLMProvider:
    """Build the provider (plus the explicit fallback, when configured) for a
    resolved model route."""
    assert route.kind == "model" and route.entry is not None
    try:
        primary: LLMProvider = _FittedProvider(
            registry.build_provider(route.entry), route.entry.context_limit)
    except ValueError as e:
        raise RouteError(str(e)) from e
    if route.fallback is None:
        return primary
    try:
        fb = _FittedProvider(registry.build_provider(route.fallback),
                             route.fallback.context_limit)
    except ValueError:
        return primary
    return FallbackProvider([primary, fb])


def provider_for_task(task: str) -> LLMProvider:
    """The single entry point consumers use. ``auto`` → the pre-existing
    default chain (unchanged behavior); explicit → the routed model only."""
    route = resolve(task)
    if route.kind == "legacy":
        return get_default_provider()
    return provider_for_route(route)


def complete(task: str, messages: List[Message], *, max_tokens: int = 512,
             temperature: float = 0.2) -> Tuple[str, str]:
    """Convenience: route + complete. Returns ``(text, engine_name)``."""
    provider = provider_for_task(task)
    text = provider.complete(messages, max_tokens=max_tokens,
                             temperature=temperature)
    return text or "", getattr(provider, "name", "provider")
