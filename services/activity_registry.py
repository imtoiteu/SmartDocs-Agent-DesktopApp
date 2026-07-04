"""Process-wide registry of in-flight heavy operations (DIAGNOSTIC).

A/B tests proved the chat slowdown is concurrent CPU contention. The chat
generation lock already serialises chat + AI-Rewrite + summary (shared B1 model),
so those can't overlap a generation. The remaining CPU-heavy operations that CAN
run concurrently — and are mostly native-threaded (PaddleOCR, Argos/CTranslate2,
numpy/sklearn embedding) so per-thread CPU attribution can't name them — register
here while they run. The chat contention probe logs this snapshot so we can see
exactly which logical task was burning CPU during a slow generation.

Purely observational: `track()` only records a label + start time.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from itertools import count
from typing import List, Tuple

_active: dict = {}                  # id -> (label, start_ts)
_lock   = threading.Lock()
_ids    = count()


@contextmanager
def track(label: str):
    """Register `label` as in-flight for the duration of the with-block."""
    tid = next(_ids)
    with _lock:
        _active[tid] = (label, time.time())
    try:
        yield
    finally:
        with _lock:
            _active.pop(tid, None)


def snapshot() -> List[Tuple[str, float]]:
    """Return [(label, age_seconds), …] for every operation currently in flight."""
    now = time.time()
    with _lock:
        return [(label, now - ts) for (label, ts) in _active.values()]
