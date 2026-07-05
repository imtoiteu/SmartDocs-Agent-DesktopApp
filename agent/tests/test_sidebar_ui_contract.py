"""UI contract — sidebar navigation layout + Local-only state sync (stdlib).

Source-scan tests in the style of test_ui_contract.py: they assert the
STRUCTURE the desktop UI relies on (landmarks, a11y attributes, role gating,
state-sync wiring) directly against the shipped static files, so they run on
any Python without Flask or a browser.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
I18N = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
SIDEBAR_JS = (ROOT / "static" / "sidebar.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
SPLASH = (ROOT / "desktop" / "splash" / "index.html").read_text(encoding="utf-8")


# ── sidebar structure ─────────────────────────────────────────────────────────
def test_sidebar_is_a_labelled_nav_landmark():
    assert re.search(r'<nav id="sidebar" aria-label="[^"]+"', INDEX)
    assert '<header id="topbar"' in INDEX


def test_sidebar_contains_every_destination():
    for view in ("home", "ocr", "correct", "translate", "summarize",
                 "documents", "chat", "settings"):
        assert f'data-view="{view}"' in INDEX, f"missing sidebar item {view}"
    assert 'id="nav-agent-link"' in INDEX and 'href="/agent"' in INDEX
    assert 'id="nav-admin-link"' in INDEX and 'href="/admin/"' in INDEX


def test_settings_and_admin_live_in_the_bottom_section():
    bottom = INDEX.split('class="sb-group sb-bottom"', 1)[1].split("</nav>")[0]
    assert 'data-view="settings"' in bottom
    assert 'id="nav-admin-link"' in bottom
    # ...and not duplicated in the main group.
    main_group = INDEX.split('class="sb-group sb-grow"', 1)[1].split("sb-bottom")[0]
    assert 'data-view="settings"' not in main_group


def test_admin_entry_hidden_by_default_and_role_gated_in_js():
    admin = re.search(r'<a id="nav-admin-link"[^>]*>', INDEX).group(0)
    assert "display:none" in admin
    assert "u.role === 'admin'" in INDEX          # /api/auth/me gate unchanged


def test_labels_cannot_wrap_and_collapse_uses_icons_with_tooltips():
    assert re.search(r"\.sb-label\s*{[^}]*white-space:\s*nowrap", CSS)
    assert "#app.sb-collapsed #sidebar" in CSS
    m = re.search(r"#app\.sb-collapsed #sidebar\s*{[^}]*width:\s*(\d+)px", CSS)
    assert m and 64 <= int(m.group(1)) <= 72, "collapsed width out of 64-72px"
    m = re.search(r"#sidebar\s*{[^}]*width:\s*(\d+)px", CSS)
    assert m and 220 <= int(m.group(1)) <= 240, "expanded width out of 220-240px"
    assert "setAttribute('title', text)" in SIDEBAR_JS   # collapsed tooltips
    assert "aria-label" in SIDEBAR_JS


def test_narrow_windows_get_an_overlay_drawer():
    assert "@media (max-width: 860px)" in CSS
    assert "sb-drawer-open" in CSS and "sb-backdrop" in CSS
    assert "aria-expanded" in SIDEBAR_JS          # hamburger state
    assert "'Escape'" in SIDEBAR_JS               # keyboard close


def test_keyboard_navigation_and_focus_visibility():
    assert "ArrowDown" in SIDEBAR_JS and "ArrowUp" in SIDEBAR_JS
    assert "focus-visible" in CSS


def test_only_the_collapse_preference_is_persisted():
    stored = re.findall(r"localStorage\.setItem\(\s*([^,]+),", SIDEBAR_JS)
    assert stored == ["COLLAPSE_KEY"], f"sidebar.js must persist ONLY the collapse pref, got {stored}"
    assert "token" not in SIDEBAR_JS.lower()


def test_topbar_keeps_only_the_mandated_items():
    topbar = INDEX.split('<header id="topbar"', 1)[1].split("</header>")[0]
    assert 'id="topbar-title"' in topbar
    assert 'id="topbar-runtime"' in topbar        # backend/runtime status
    assert 'id="topbar-privacy"' in topbar        # processing-mode status
    assert 'class="lang-switcher"' in topbar
    assert 'id="nav-user"' in topbar and "/logout" in topbar
    assert 'data-view=' not in topbar, "primary navigation must not be duplicated in the top bar"


def test_home_cards_keep_their_routes():
    for goto in ("ocr", "correct", "translate", "summarize", "documents", "chat"):
        assert f'data-goto="{goto}"' in INDEX
    assert 'data-href="/agent"' in INDEX
    assert 'id="home-card-admin"' in INDEX        # still role-gated


def test_i18n_has_sidebar_keys_in_both_languages():
    for key in ("sb_home", "sb_correct", "sb_translate", "sb_summarize",
                "sb_documents", "sb_chat", "sb_agent", "sb_settings", "sb_admin",
                "sidebar_collapse", "privacy_chip_local", "runtime_bundled"):
        assert I18N.count(f"{key}:") >= 2, f"{key} missing from vi or en"


# ── Local-only state sync (regression for the dead-toggle bug) ────────────────
def test_settings_state_loads_on_direct_hash_entry():
    # The old wiring only called SettingsView.show() inside the patched
    # Router.goto — reload / Back-Forward / #settings deep links left a
    # disabled "Loading…" button. It must now live in Router._render.
    render = APP_JS.split("_render()", 1)[1].split("init()")[0]
    assert "SettingsView.show()" in render
    boot_wrapper = APP_JS.split("const _origGoto", 1)[1].split("};", 1)[0]
    assert "SettingsView.show()" not in boot_wrapper


def test_privacy_toggle_has_state_semantics_and_rollback():
    assert "aria-pressed" in APP_JS               # pressed = Local only active
    assert "aria-busy" in APP_JS                  # in-flight; no double submit
    assert "PrivacyIndicator.set" in APP_JS       # top-bar chip synced
    # data-i18n markers are dropped once real state is rendered, so language
    # re-application can never reset the controls to "Loading…".
    assert "removeAttribute('data-i18n')" in APP_JS
    toggle = APP_JS.split("async _togglePrivacy", 1)[1].split("_stateBadge", 1)[0]
    assert "catch" in toggle and "error" in toggle, "backend failure must roll back, not lie"


def test_cloud_controls_disabled_in_local_only():
    row = APP_JS.split("_providerRow(", 1)[1].split("_setState(", 1)[0]
    assert "input.disabled = true" in row
    assert "localOnly" in row


def test_runtime_settings_panel_is_desktop_only_and_hides_bundle_paths():
    assert 'id="settings-runtime-panel"' in INDEX
    assert "__SMARTDOCS_DESKTOP__" in APP_JS
    assert "/desktop/runtime-settings" in INDEX
    # The web UI never renders internal bundle paths.
    assert "_internal" not in INDEX and "Contents/Resources" not in INDEX


# ── launcher page (runtime modes UI) ──────────────────────────────────────────
def test_launcher_offers_all_three_modes_with_required_controls():
    for value in ("bundled", "external", "remote"):
        assert f'value="{value}"' in SPLASH
    for control in ("rt-pick", "rt-validate", "rt-test", "rt-path", "rt-url"):
        assert f'id="{control}"' in SPLASH
    assert "aria-live" in SPLASH


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
