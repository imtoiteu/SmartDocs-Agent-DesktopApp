"""UI contract tests (source-scan) for the Settings / privacy / scope /
citation / lifecycle work. There is no browser test tooling in this repo, so
these pin the load-bearing frontend facts the backend tests can't see:
masked-input handling, no secrets in web storage, confirmation gating, scope
display, clickable citations, retry, and the Settings entry points.

Runs under pytest OR standalone (`python agent/tests/test_ui_contract.py`).
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

APP_JS = (_ROOT / "static" / "app.js").read_text(encoding="utf-8")
AGENT_JS = (_ROOT / "static" / "agent.js").read_text(encoding="utf-8")
INDEX = (_ROOT / "static" / "index.html").read_text(encoding="utf-8")
AGENT_HTML = (_ROOT / "static" / "agent.html").read_text(encoding="utf-8")
I18N = (_ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
CHAT_JS = (_ROOT / "static" / "chat.js").read_text(encoding="utf-8")


# ── Settings section exists and is wired ─────────────────────────────────────
def test_settings_view_wired_into_spa():
    assert 'id="view-settings"' in INDEX
    assert 'data-view="settings"' in INDEX                 # nav entry
    assert "'settings'" in APP_JS and "SettingsView" in APP_JS
    assert "SettingsView.show()" in APP_JS                 # route hook
    for endpoint in ("/api/settings", "/api/settings/privacy",
                     "/api/settings/keys/"):
        assert endpoint in APP_JS, endpoint


def test_api_key_input_is_masked_and_cleared():
    # The key field is a password input, autocomplete off, and the value is
    # cleared immediately after the save request — never kept around.
    assert re.search(r'input\.type\s*=\s*[\'"]password[\'"]', APP_JS)
    assert re.search(r'autocomplete\s*=\s*[\'"]off[\'"]', APP_JS)
    assert re.search(r'input\.value\s*=\s*[\'"][\'"];\s*//[^\n]*never keep', APP_JS)


def test_no_secrets_in_web_storage():
    # Every localStorage key used by the frontend is in the non-secret
    # allowlist; nothing key/token-shaped is ever written to web storage.
    allow = {"smartdocs_lang", "smartdocs_agent_steps"}
    for src, name in ((APP_JS, "app.js"), (AGENT_JS, "agent.js"),
                      (I18N, "i18n.js"), (CHAT_JS, "chat.js")):
        for m in re.finditer(r'localStorage\.setItem\(\s*([^,)]+)', src):
            arg = m.group(1).strip()
            keys = set(re.findall(r'[\'"]([^\'"]+)[\'"]', arg))
            if not keys and arg == "STEPS_STORE_KEY":
                keys = {"smartdocs_agent_steps"}
            if not keys and arg.endswith("_STORAGE_KEY"):  # i18n's this._STORAGE_KEY
                keys = {"smartdocs_lang"}
            assert keys and keys <= allow, f"{name}: unexpected storage key {arg!r}"
        assert "sessionStorage" not in src, name
        for bad in ("api_key", "apiKey", "API_KEY"):
            assert not re.search(rf'localStorage[^;\n]*{bad}', src), (name, bad)


# ── privacy visibility + confirmation ────────────────────────────────────────
def test_local_only_visible_on_translate_and_agent_screens():
    assert "s.local_only" in APP_JS                        # translate badge/pill
    assert "engine_local_only" in APP_JS and "engine_local_only" in I18N
    assert "Local only (no cloud)" in AGENT_JS             # agent status line


def test_cloud_confirmation_gates_agent_runs():
    assert "confirmCloudIfNeeded" in AGENT_JS
    # The gate runs before anything is sent, inside runAgent.
    run_body = AGENT_JS.split("async function runAgent()", 1)[1]
    assert "confirmCloudIfNeeded()" in run_body.split("api(\"/api/agent/run\"")[0]
    assert "cloud_keys_configured" in AGENT_JS and "cloud_ack" in AGENT_JS
    # Settings toggle confirms too (first-time ack text from the server).
    assert "window.confirm" in APP_JS and "ack_message" in APP_JS


# ── readiness → Settings navigation ──────────────────────────────────────────
def test_status_lines_link_to_settings():
    assert "/#settings" in AGENT_JS                        # agent page deep-link
    assert "settingsLink()" in AGENT_JS
    assert "settings_keyring_unavailable" in APP_JS        # unavailable state
    for state in ("not_configured", "testing", "connected", "invalid",
                  "unavailable"):
        assert state in APP_JS, state                      # all five key states


# ── document scope display ───────────────────────────────────────────────────
def test_scope_shown_next_to_run_and_on_result():
    assert 'id="agent-scope"' in AGENT_HTML
    assert "entire document library" in AGENT_JS           # explicit corpus label
    assert "scopeLabel()" in AGENT_JS and "updateScopeLine" in AGENT_JS
    assert '"scope: " + scopeAtRun' in AGENT_JS            # echoed on the result


# ── run lifecycle: progress, timeout/partial, retry ──────────────────────────
def test_lifecycle_states_present():
    assert "progressText" in AGENT_JS                      # step progress (kept)
    assert re.search(r'Running… \(.+secs.+s\)"?', AGENT_JS) or "\" (\" + secs + \"s)\"" in AGENT_JS
    assert "partial result (time limit)" in AGENT_JS       # timeout keeps answer
    assert "offerRetry" in AGENT_JS
    assert "↻ Retry" in AGENT_JS
    # No fake cancel: the backend has no real cancellation for agent runs.
    assert "Cancel run" not in AGENT_JS and "cancelRun" not in AGENT_JS


# ── citations + copy ─────────────────────────────────────────────────────────
def test_citations_named_clickable_and_flagged():
    assert 'setAttribute("role", "link")' in AGENT_JS      # clickable citation
    assert "Open this source document" in AGENT_JS
    assert "documents not consulted" in AGENT_JS           # honesty flag
    assert "partial document context" in AGENT_JS          # truncation flag
    assert "context_truncated" in AGENT_JS


def test_copy_result_action_exists():
    assert "copyText" in AGENT_JS and "📋 Copy" in AGENT_JS
    assert "navigator.clipboard" in AGENT_JS


# ── accessibility touches ────────────────────────────────────────────────────
def test_aria_live_status_regions():
    assert 'aria-live="polite"' in AGENT_HTML
    assert 'aria-live="polite"' in INDEX
    assert "aria-label" in APP_JS                          # key input labelled


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
