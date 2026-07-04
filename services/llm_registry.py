"""
Shared loaded-LLM registry (B1).
================================
Both the AI-Rewrite service (`ai_rewrite_service`) and the AI-Chat service
(`chat_service`) load Qwen2.5 models. In the default configuration (`.env`:
both Qwen2.5-1.5B on CPU) loading them independently keeps TWO identical copies
of the weights in RAM.

This registry loads each distinct `(model_id, device, dtype)` exactly once and
hands the same `(tokenizer, model, device)` to every caller, so identical
configurations share one copy. It also vends a per-key **generation lock** so
that two services sharing one model serialize their `model.generate()` calls
(running two forward passes through the same module concurrently is unsafe).

When the two services are configured differently (different model / device /
dtype) the keys differ: they load separately and get independent generation
locks — i.e. no behavioural change versus before.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

_registry_lock = threading.Lock()
_entries: dict = {}     # key -> {"lock": Lock, "value": (tok, mdl, device) | None}
_gen_locks: dict = {}   # key -> Lock (serializes generate() for a shared model)


def _key(model_id, device, dtype):
    return (str(model_id), str(device), str(dtype))


def peek(model_id, device, dtype) -> Optional[Tuple]:
    """Return the cached (tok, mdl, device) if already loaded, else None. Non-blocking."""
    with _registry_lock:
        e = _entries.get(_key(model_id, device, dtype))
        return e["value"] if e else None


def generation_lock(model_id, device, dtype) -> threading.Lock:
    """Return the shared generation lock for a model key (created on first use).

    Two callers that resolve to the same (model, device, dtype) get the SAME lock
    and therefore serialize generation against one another. Different keys get
    different locks and run independently.
    """
    k = _key(model_id, device, dtype)
    with _registry_lock:
        lk = _gen_locks.get(k)
        if lk is None:
            lk = threading.Lock()
            _gen_locks[k] = lk
        return lk


def load_or_get(model_id, device, dtype, loader: Callable[[], Tuple]) -> Tuple:
    """Return (tok, mdl, device), invoking `loader()` at most once per key.

    `loader` is a zero-arg callable returning (tokenizer, model, device).
    Concurrent callers for the same key block on a per-key lock; the first runs
    the loader, the rest receive the cached instance.
    """
    k = _key(model_id, device, dtype)
    with _registry_lock:
        e = _entries.get(k)
        if e is None:
            e = {"lock": threading.Lock(), "value": None}
            _entries[k] = e

    if e["value"] is not None:
        logger.info(f"[LLMRegistry] reuse already-loaded model {k}")
        return e["value"]

    with e["lock"]:
        if e["value"] is None:
            logger.info(f"[LLMRegistry] loading model {k}")
            e["value"] = loader()
        else:
            logger.info(f"[LLMRegistry] reuse model {k} (loaded while waiting)")
    return e["value"]
