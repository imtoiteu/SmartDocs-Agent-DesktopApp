"""Run-progress registry tests + UI/API default alignment (review UI items).

The registry is pure (no Flask) with an injectable clock; the alignment test
pins the agent page's visible max_steps default, the JS fallback and the API
default (agent_bp._DEFAULT_MAX_STEPS) to the same number by scanning the three
sources — they must never drift apart again.

Runs under pytest OR standalone (`python agent/tests/test_progress_and_defaults.py`).
"""

import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import pytest  # noqa: F401
except ImportError:
    pytest = None

from agent.progress import RunProgressRegistry, RUN_ID_RE, get_progress_registry  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# ── registry basics ───────────────────────────────────────────────────────────
def test_start_update_get_roundtrip():
    reg = RunProgressRegistry(clock=FakeClock())
    reg.start("run-abc123", user_id=1, max_steps=3)
    reg.update("run-abc123", phase="acting", step=2, name="chat", kind="tool")
    p = reg.get("run-abc123", user_id=1)
    assert p == {"phase": "acting", "step": 2, "max_steps": 3,
                 "name": "chat", "kind": "tool"}


def test_get_is_owner_scoped():
    reg = RunProgressRegistry(clock=FakeClock())
    reg.start("run-abc123", user_id=1, max_steps=3)
    assert reg.get("run-abc123", user_id=2) is None      # another user: invisible
    assert reg.get("run-abc123", user_id=1) is not None
    assert reg.get("unknown-run", user_id=1) is None


def test_private_fields_never_leak_or_get_overwritten():
    reg = RunProgressRegistry(clock=FakeClock())
    reg.start("run-abc123", user_id=1, max_steps=3)
    reg.update("run-abc123", _user_id=2, phase="thinking")   # attempted hijack
    p = reg.get("run-abc123", user_id=1)
    assert p is not None and p["phase"] == "thinking"
    assert not any(k.startswith("_") for k in p)             # internals hidden
    assert reg.get("run-abc123", user_id=2) is None          # owner unchanged


def test_malformed_run_ids_ignored():
    reg = RunProgressRegistry(clock=FakeClock())
    for bad in ("", "ab", "x" * 65, "../etc", "run id", "run/1"):
        reg.start(bad, user_id=1, max_steps=3)
        assert reg.get(bad, user_id=1) is None, repr(bad)
    assert RUN_ID_RE.match("r1k2j3-_X") is not None


def test_finish_marks_done_and_ttl_prunes():
    clock = FakeClock()
    reg = RunProgressRegistry(ttl_s=600, clock=clock)
    reg.start("run-abc123", user_id=1, max_steps=3)
    reg.finish("run-abc123")
    assert reg.get("run-abc123", user_id=1)["phase"] == "done"
    clock.now += 601                                        # past the TTL
    assert reg.get("run-abc123", user_id=1) is None         # expired on read
    reg.start("run-def456", user_id=1, max_steps=3)         # prune-on-start ran
    assert reg.get("run-abc123", user_id=1) is None


def test_update_unknown_run_is_noop():
    reg = RunProgressRegistry(clock=FakeClock())
    reg.update("never-started", phase="acting")             # must not raise
    assert reg.get("never-started", user_id=1) is None


def test_default_registry_singleton():
    assert get_progress_registry() is get_progress_registry()


# ── max_steps default alignment (UI ↔ JS ↔ API) ───────────────────────────────
def test_max_steps_default_aligned_across_ui_and_api():
    bp = (_ROOT / "agent_bp.py").read_text(encoding="utf-8")
    html = (_ROOT / "static" / "agent.html").read_text(encoding="utf-8")
    js = (_ROOT / "static" / "agent.js").read_text(encoding="utf-8")

    api_default = int(re.search(r"_DEFAULT_MAX_STEPS\s*=\s*(\d+)", bp).group(1))
    ui_default = int(re.search(
        r'id="steps"[^>]*\bvalue="(\d+)"', html).group(1))
    js_fallback = int(re.search(
        r'parseInt\(\$\("steps"\)\.value,\s*10\)\s*\|\|\s*(\d+)', js).group(1))

    assert api_default == ui_default == js_fallback, (
        f"max_steps defaults drifted: api={api_default} ui={ui_default} "
        f"js={js_fallback}")
    # And the route actually uses the constant (not a re-hardcoded literal).
    assert re.search(r'data\.get\("max_steps"\)\s*or\s*_DEFAULT_MAX_STEPS', bp)


if __name__ == "__main__":
    import traceback
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn(); print(f"PASS  {name}")
        except Exception:
            failed += 1; print(f"FAIL  {name}"); traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
