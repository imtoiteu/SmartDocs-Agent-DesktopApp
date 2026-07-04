"""Disable PaddlePaddle's glog FailureSignalHandler before any Paddle init.

PaddlePaddle installs a Google-glog ``FailureSignalHandler`` that hijacks
SIGSEGV/SIGABRT. In the main SmartDocs venv, Paddle and PyTorch are loaded in the
SAME process (Flask + Paddle OCR + Torch-based Qwen chat/rewrite). When a fault
occurs on a Paddle threadpool worker, that handler runs and tries to symbolize a
stack — turning a condition Python would otherwise handle into a fatal crash
("Python quit unexpectedly" on macOS). Calling ``paddle.disable_signal_handler()``
lets Python handle signals normally.

See docs/MACOS_CRASH_NOTES.md. Idempotent, best-effort, and never raises — safe to
call from every Paddle-using adapter's lazy init path.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_applied = False


def disable_paddle_signal_handler() -> None:
    """Call ``paddle.disable_signal_handler()`` once, if available. No-op on repeat
    calls, if paddle is not importable, or if the API is missing/raises."""
    global _applied
    if _applied:
        return
    _applied = True
    try:
        import paddle
    except Exception:
        return
    fn = getattr(paddle, "disable_signal_handler", None)
    if not callable(fn):
        logger.debug("[PaddleGuard] paddle.disable_signal_handler unavailable; skipping")
        return
    try:
        fn()
        logger.debug("[PaddleGuard] paddle.disable_signal_handler() applied")
    except Exception as e:  # never let the guard break OCR
        logger.debug("[PaddleGuard] disable_signal_handler failed: %s", e)
