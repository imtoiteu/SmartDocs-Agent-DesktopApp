"""Run progress registry — live feedback for long agent runs (review UI item).

While ``/api/agent/run`` is in flight the browser has no signal beyond a
spinner; on a CPU-only install a run can take minutes. The blueprint records
each run's current phase here (via ``AgentCore``'s ``on_progress`` callback)
and the page polls ``GET /api/agent/progress/<run_id>`` to show "Step 2/3:
running chat…" instead of silence.

Pure and in-memory (no Flask / no DB): entries are owner-scoped (``get`` only
returns a run to the user who started it) and TTL-pruned so abandoned runs
never accumulate. The clock is injectable for tests.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, Optional

# Client-generated run ids: opaque short tokens only (never a path / never
# user-visible content). Anything else is ignored — progress is optional.
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


class RunProgressRegistry:
    """Thread-safe {run_id → progress dict}, owner-scoped, TTL-pruned."""

    def __init__(self, ttl_s: float = 600.0, clock=time.monotonic) -> None:
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_s
        self._clock = clock

    def _prune_locked(self) -> None:
        now = self._clock()
        stale = [rid for rid, r in self._runs.items()
                 if now - r["_updated"] > self._ttl]
        for rid in stale:
            del self._runs[rid]

    def start(self, run_id: str, user_id, max_steps: int) -> None:
        if not run_id or not RUN_ID_RE.match(run_id):
            return
        with self._lock:
            self._prune_locked()
            self._runs[run_id] = {
                "_user_id": user_id,
                "_updated": self._clock(),
                "phase": "starting",
                "step": 0,
                "max_steps": int(max_steps),
            }

    def update(self, run_id: str, **fields) -> None:
        """Merge progress fields into a known run; unknown run ids are ignored
        (progress must never break a run). Private keys cannot be overwritten."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            for k, v in fields.items():
                if not str(k).startswith("_"):
                    run[k] = v
            run["_updated"] = self._clock()

    def finish(self, run_id: str) -> None:
        self.update(run_id, phase="done")

    def get(self, run_id: str, user_id) -> Optional[Dict[str, Any]]:
        """The run's public progress dict, or None when unknown, expired, or
        owned by a different user (owner-scoped, like every agent resource)."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run["_user_id"] != user_id:
                return None
            if self._clock() - run["_updated"] > self._ttl:
                del self._runs[run_id]
                return None
            return {k: v for k, v in run.items() if not k.startswith("_")}


_default_registry: Optional[RunProgressRegistry] = None


def get_progress_registry() -> RunProgressRegistry:
    """Process-wide default registry (lazy singleton)."""
    global _default_registry
    if _default_registry is None:
        _default_registry = RunProgressRegistry()
    return _default_registry
