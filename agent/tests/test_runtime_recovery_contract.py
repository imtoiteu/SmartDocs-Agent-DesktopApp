"""Source-contract tests: runtime recovery, UI-always-local, insecure LAN.

Cross-platform source scans (stdlib only, no build needed) pinning the
guarantees of the runtime-architecture rework:

  * the WebView is only ever allowed on the local gateway origin — remote
    mode carries no navigable remote origin at all;
  * the runtime selector is reachable independently of any backend (native
    menu + CmdOrCtrl+, accelerator, error-screen recovery, Option/Alt
    startup override) and failures open it instead of trapping the user;
  * remote mode enters desktop_gateway BEFORE any Flask/app import;
  * the insecure-LAN option exists end to end (config fields, policy,
    ack sentinel, launcher warning UI, top-bar indicator, i18n) and is
    OFF by default;
  * the bundle ships the gateway + UI assets for the shim layout.

Behavioral coverage lives in desktop/tests/test_gateway.py (real gateway)
and src-tauri/src/runtime.rs (cargo test).
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

MAIN_RS = (ROOT / "src-tauri" / "src" / "main.rs").read_text()
RUNTIME_RS = (ROOT / "src-tauri" / "src" / "runtime.rs").read_text()
SPLASH_HTML = (ROOT / "desktop" / "splash" / "index.html").read_text()
SPLASH_JS = (ROOT / "desktop" / "splash" / "splash.js").read_text()
SERVER_PY = (ROOT / "desktop_server.py").read_text()
GATEWAY_PY = (ROOT / "desktop_gateway.py").read_text()
APP_JS = (ROOT / "static" / "app.js").read_text()
INDEX_HTML = (ROOT / "static" / "index.html").read_text()
I18N_JS = (ROOT / "static" / "i18n.js").read_text()
CONF = (ROOT / "src-tauri" / "tauri.conf.json").read_text()


# ── UI always local / no remote navigation ──────────────────────────────────
def test_nav_rule_has_no_remote_origin():
    m = re.search(r"struct NavRule \{(.*?)\}", MAIN_RS, re.S)
    assert m, "NavRule struct missing"
    assert "remote" not in m.group(1), \
        "NavRule must not carry a navigable remote origin"
    assert "StartPlan::Navigate" not in MAIN_RS


def test_remote_plan_is_gateway_only():
    assert "ServeRemote" in RUNTIME_RS
    assert "SMARTDOCS_GATEWAY_ONLY" in MAIN_RS
    assert "SMARTDOCS_GATEWAY_UPSTREAM" in MAIN_RS


def test_gateway_only_branch_runs_before_any_app_import():
    branch = SERVER_PY.index("SMARTDOCS_GATEWAY_ONLY")
    app_import = SERVER_PY.index("from app import")
    assert branch < app_import, \
        "the gateway-only branch must come before the Flask app import"
    # And the gateway module itself never imports Flask/app/models/config.
    for banned in ("import flask", "from app import", "import config",
                   "from models", "import sqlalchemy"):
        assert banned not in GATEWAY_PY, f"gateway must not use {banned!r}"


def test_gateway_is_an_allowlist_not_an_open_proxy():
    assert 'PROXY_PREFIXES = ("/api/", "/admin/")' in GATEWAY_PY
    assert '"/login"' in GATEWAY_PY and '"/logout"' in GATEWAY_PY
    assert "Not found" in GATEWAY_PY          # default deny


def test_local_handshake_reports_the_gateway_port():
    assert "gw.server_address[1]" in SERVER_PY
    assert "make_gateway" in SERVER_PY


# ── recoverable runtime selection ────────────────────────────────────────────
def test_native_menu_item_with_accelerator():
    assert '"backend-runtime"' in MAIN_RS
    assert "Backend Runtime…" in MAIN_RS
    assert 'accelerator("CmdOrCtrl+,")' in MAIN_RS
    assert "on_menu_event" in MAIN_RS


def test_startup_option_alt_override_per_platform():
    assert "startup_selector_forced" in MAIN_RS
    assert "SMARTDOCS_FORCE_RUNTIME_SELECTOR" in MAIN_RS
    assert 'cfg!(all(target_os = "macos"' in MAIN_RS.replace("\n", " ") or \
        'target_os = "macos"' in MAIN_RS
    assert "CGEventSourceFlagsState" in MAIN_RS      # macOS
    assert "GetAsyncKeyState" in MAIN_RS             # Windows
    assert "XQueryKeymap" in MAIN_RS                 # Linux/X11 (dlopen)


def test_failures_open_the_selector_instead_of_trapping():
    assert "open_runtime_selector" in MAIN_RS
    # Both failure paths (plan/probe fail + spawn/health fail) recover.
    assert MAIN_RS.count("open_runtime_selector(") >= 4
    assert "__openRuntime" in MAIN_RS and "__openRuntime" in SPLASH_JS
    assert "Change backend…" in SPLASH_HTML
    # The gateway's connection-error page offers the same way out.
    assert "Change backend…" in GATEWAY_PY


def test_saved_config_is_preserved_not_deleted_on_failure():
    assert "remove_file" not in MAIN_RS, \
        "failure handling must never delete runtime.json"
    assert "runtime.json" in RUNTIME_RS


# ── insecure HTTP on private LAN ─────────────────────────────────────────────
def test_config_has_insecure_fields_defaulting_off():
    assert "allow_insecure_lan: false" in RUNTIME_RS.replace(
        "allow_insecure_lan: bool", "")
    assert "insecure_lan_ack: false" in RUNTIME_RS
    assert '"allow_insecure_lan"' in RUNTIME_RS


def test_policy_accepts_private_ip_literals_only():
    assert "is_private_lan_ip" in RUNTIME_RS
    assert "HttpInsecureLan" in RUNTIME_RS
    assert "0xfc00" in RUNTIME_RS                       # IPv6 unique-local
    assert "INSECURE_ACK_REQUIRED" in RUNTIME_RS
    # The gateway re-verifies before every connect (defense in depth).
    assert "_is_private_ip" in GATEWAY_PY
    assert "not a private LAN address" in GATEWAY_PY


def test_launcher_has_the_option_warning_and_confirmation():
    assert 'id="rt-insecure"' in SPLASH_HTML
    assert 'id="rt-insecure-warn"' in SPLASH_HTML
    assert 'id="rt-insecure-confirm"' in SPLASH_HTML
    assert 'id="rt-insecure-cancel"' in SPLASH_HTML
    assert "unencrypted" in SPLASH_HTML
    assert "needsInsecureConfirm" in SPLASH_JS
    assert "insecure-lan-ack-required" in SPLASH_JS
    assert "allowInsecureLan" in SPLASH_JS


def test_persistent_insecure_indicator_in_the_top_bar():
    assert 'id="topbar-insecure"' in INDEX_HTML
    assert "insecure_lan" in APP_JS
    for lang_marker in ("Kết nối LAN không mã hoá", "Insecure LAN connection"):
        assert lang_marker in I18N_JS
    assert "runtime_insecure_lan" in I18N_JS


def test_no_secrets_in_runtime_config_surface():
    # Only URL + booleans + paths are persisted; tokens live elsewhere
    # (OS credential store for cloud keys; per-launch token in memory).
    m = re.search(r"pub fn to_json.*?\n    \}", RUNTIME_RS, re.S)
    assert m, "to_json missing"
    for banned in ("token", "password", "secret", "key"):
        assert banned not in m.group(0).lower()


# ── packaging ────────────────────────────────────────────────────────────────
def test_bundle_ships_gateway_and_ui_assets_for_the_shim():
    assert '"../desktop_gateway.py": "desktop-shim/desktop_gateway.py"' in CONF
    assert '"../static/": "desktop-shim/static/"' in CONF


def test_gateway_ci_step_exists():
    wf = (ROOT / ".github" / "workflows" / "desktop-build.yml").read_text()
    assert "desktop/tests/test_gateway.py" in wf


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
