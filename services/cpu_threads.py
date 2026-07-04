"""Restore torch CPU parallelism before each LLM generation.

PaddleOCR resets torch's intra-op thread count to 1 — paddle and torch share an
OpenMP/libomp runtime, and loading/running paddle collapses the pool. After any OCR
runs, every subsequent CPU generation is single-threaded (~3-4x slower on both
prefill and decode). Confirmed live + isolated: `torch.get_num_threads()` goes 4→1
after OCR, and `torch.set_num_threads()` restores full speed.

This module captures torch's baseline thread count at import (which happens at app
startup, BEFORE any OCR/paddle import) and exposes `restore()`, called before each
chat / AI-rewrite generation to undo the collapse.

Target precedence: env LLM_TORCH_THREADS (or legacy CHAT_FORCE_TORCH_THREADS) →
captured pre-paddle baseline.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("smartdocs.chat")

_baseline: int | None = None


def _capture_baseline() -> "int | None":
    """Record torch's default thread count once, before paddle can lower it."""
    global _baseline
    if _baseline is None:
        try:
            import torch
            _baseline = torch.get_num_threads()
            logger.info(f"[CPUThreads] captured baseline torch threads = {_baseline}")
        except Exception as e:          # torch missing/not ready — restore() becomes a no-op
            logger.debug(f"[CPUThreads] could not capture baseline: {e}")
    return _baseline


def _target() -> "int | None":
    raw = os.getenv("LLM_TORCH_THREADS") or os.getenv("CHAT_FORCE_TORCH_THREADS")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            logger.warning(f"[CPUThreads] ignoring invalid LLM_TORCH_THREADS={raw!r}")
    return _baseline


def restore(tag: str = "gen") -> "int | None":
    """Restore torch's intra-op threads to the target if something lowered it.

    Safe to call before every generation: it only sets threads when the current
    count differs from the target (i.e. when paddle has collapsed the pool).
    Returns the resulting thread count (or None if torch is unavailable).
    """
    try:
        import torch
    except Exception:
        return None
    target = _target()
    if not target:
        return None
    cur = torch.get_num_threads()
    if cur != target:
        torch.set_num_threads(target)
        logger.warning(
            f"[CPUThreads] {tag}: torch threads {cur} → {torch.get_num_threads()} "
            f"(restored after paddle/OMP collapse)"
        )
    return torch.get_num_threads()


# Capture at import time — app startup imports the LLM services before any OCR,
# so this is torch's genuine pre-paddle baseline.
_capture_baseline()
