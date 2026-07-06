"""UI contract — Settings scrollability + self-hosted LLM configuration UX.

Source-scan tests (stdlib only, no browser) pinning the two regressions this
change fixes and the guarantees around them:

  * the Settings view scrolls (it inherits ``.view { overflow: hidden }``, so
    without its own ``overflow-y: auto`` everything below the fold — the
    self-hosted form, key panel — was unreachable), with the panels themselves
    NOT scrolling (no inner/outer double-scrollbar);
  * the self-hosted OpenAI-compatible server has a visible, complete form:
    base URL, model name (with server-provided suggestions), API key
    (OS credential store only), context limit, timeout, insecure-LAN option,
    and Test / Save / Clear actions;
  * every connection-test state the backend can answer has a UI label,
    including the new ``timeout`` and ``policy_blocked``;
  * the API key never rides along in the settings JSON — it goes through the
    keyring endpoint (``settingsSaveKey('self_hosted', …)``) and the input is
    emptied immediately;
  * clearing the server resets routes that pointed at it to Automatic and
    says so (never a silent provider change).

Behavioral coverage for the probe itself lives in test_llm_gateway.py.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
I18N = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
MODELS_BP = (ROOT / "models_bp.py").read_text(encoding="utf-8")


# ── A. Settings scrolling ─────────────────────────────────────────────────────
def test_settings_view_is_the_single_scroller():
    # The fix itself: the view opts back into vertical scrolling…
    assert re.search(r"#view-settings\s*{[^}]*overflow-y:\s*auto", CSS), \
        "#view-settings must scroll (it inherits .view{overflow:hidden})"
    # …and the panels inside stay flow-content, so exactly ONE scrollbar
    # exists (the generic .ws-panel rule says overflow:hidden + flex).
    assert re.search(r"#view-settings \.ws-panel\s*{[^}]*overflow:\s*visible", CSS)
    # No inline scroll containers inside the settings panels either.
    for m in re.finditer(r'style="([^"]*)"', INDEX.split('id="view-settings"', 1)[1]):
        assert "overflow-y" not in m.group(1), \
            f"inner scroller inside Settings: {m.group(1)!r}"


def test_settings_css_is_cache_busted():
    m = re.search(r'href="/static/style\.css\?v=([\d.]+)"', INDEX)
    assert m and m.group(1) >= "2026.07.06.2", "style.css version must be bumped"


# ── B. self-hosted configuration form ────────────────────────────────────────
def test_self_hosted_form_has_every_required_field_and_action():
    section = INDEX.split('id="models-selfhosted-section"', 1)
    assert len(section) == 2, "dedicated self-hosted section missing"
    body = section[1].split("models_managed_title", 1)[0]
    for marker in ('id="models-sh-url"', 'id="models-sh-model"',
                   'id="models-sh-key"', 'id="models-sh-ctx"',
                   'id="models-sh-timeout"', 'id="models-sh-insecure"',
                   'id="models-sh-save"', 'id="models-sh-test"',
                   'id="models-sh-clear"', 'id="models-sh-state"',
                   'id="models-sh-key-state"', 'id="models-sh-key-remove"',
                   'id="models-sh-datalist"'):
        assert marker in body, f"self-hosted form missing {marker}"
    # Model-name suggestions come from the server's own /v1/models answer.
    assert 'list="models-sh-datalist"' in body
    # Labelled fields, not bare placeholder-only inputs.
    for key in ("models_sh_url_label", "models_sh_model_label",
                "models_sh_key_label", "models_sh_ctx_label",
                "models_sh_timeout_label"):
        assert key in body, f"missing field label {key}"


def test_api_key_is_credential_store_only():
    key_input = re.search(r'<input id="models-sh-key"[^>]*>', INDEX).group(0)
    assert 'type="password"' in key_input          # masked, never a text field
    assert 'autocomplete="off"' in key_input
    # The key travels through the keyring endpoint, not the settings save…
    assert re.search(r"settingsSaveKey\(\s*'self_hosted'", APP_JS)
    save_fn = APP_JS.split("async _saveSelfHosted", 1)[1].split("_clearSelfHosted", 1)[0]
    assert "api_key" not in save_fn, \
        "the server-settings save must not carry the API key"
    assert "keyInput.value = ''" in save_fn        # never kept around
    # …and the backend never persists it with the server settings.
    put_route = MODELS_BP.split("def set_self_hosted", 1)[1].split("def ", 1)[0]
    assert "api_key" not in put_route


def test_every_probe_state_has_a_ui_label():
    sh_state = APP_JS.split("_shState(state", 1)[1].split("},", 1)[0]
    for state in ("connected", "unavailable", "timeout", "auth_failed",
                  "incompatible", "model_not_found", "context_insufficient",
                  "policy_blocked"):
        assert re.search(state + r"\s*:", sh_state), f"_shState missing {state}"
    # The backend can actually answer those two new states.
    assert '"state": "policy_blocked"' in MODELS_BP
    assert "probe_self_hosted_server" in MODELS_BP


def test_registry_row_links_to_the_form():
    # "Self-hosted server (not configured)" must not be a dead end.
    assert "_jumpToSelfHosted" in APP_JS
    assert "scrollIntoView" in APP_JS
    assert "models_configure" in APP_JS


def test_clear_disable_is_explicit_and_resets_routes():
    clear_fn = APP_JS.split("async _clearSelfHosted", 1)[1].split("},", 1)[0]
    assert "confirm(" in clear_fn                  # user-confirmed, not silent
    assert "routes_reset" in clear_fn
    put_route = MODELS_BP.split("def set_self_hosted", 1)[1].split("\n@", 1)[0]
    assert "routes_reset" in put_route
    assert "llm_gateway.AUTO" in put_route         # back to Automatic
    assert "SELF_HOSTED_ID" in put_route


def test_self_hosted_key_row_moved_out_of_the_cloud_keys_panel():
    # Its key management lives next to the URL (and works in Local-only);
    # the "Cloud provider API keys" panel is cloud-only again.
    providers_fn = APP_JS.split("_renderProviders() {", 1)[1].split("},", 1)[0]
    assert "'self_hosted'" in providers_fn and "return" in providers_fn


def test_i18n_has_the_new_keys_in_both_languages():
    for key in ("models_sh_desc", "models_sh_url_label", "models_sh_model_label",
                "models_sh_key_label", "models_sh_ctx_label",
                "models_sh_timeout_label", "models_sh_key_none",
                "models_sh_key_remove", "models_sh_clear",
                "models_sh_clear_confirm", "models_sh_cleared",
                "models_routes_reset", "models_state_timeout",
                "models_state_policy_blocked", "models_configure"):
        assert I18N.count(f"{key}:") >= 2, f"{key} missing from vi or en"


if __name__ == "__main__":
    import traceback
    failed = 0
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn(); print(f"PASS  {name}")
        except Exception:
            failed += 1; print(f"FAIL  {name}"); traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
