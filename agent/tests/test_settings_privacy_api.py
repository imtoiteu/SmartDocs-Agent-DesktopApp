"""Settings privacy API flow — success, failure and persistence (UI item 3).

Exercises the REAL Flask app (with the desktop hooks installed) through its
HTTP surface, against a throwaway data dir:

  * PUT /api/settings/privacy success response carries the full refreshed
    payload (what the UI re-renders from)
  * failure paths: first-time cloud enable without ack (409 needs_ack) and
    env-locked ALLOW_CLOUD (409 error) — never a false success
  * Local only actually gates cloud: provider routing flips and cloud-key
    save/test endpoints refuse
  * the choice survives a restart (persisted app_settings.json)

Needs Flask + the core backend deps (the sidecar venv); on a bare Python it
reports SKIPPED and exits 0, like desktop/tests/test_sidecar_integration.py.
"""

import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    import flask  # noqa: F401
except ImportError:
    print("SKIPPED: Flask not available (run with the sidecar venv python).")
    sys.exit(0)

TOK = "settings-privacy-api-test-token-0123456789"
_TMP = tempfile.mkdtemp(prefix="sd-settings-api-")

# Desktop-mode env BEFORE any app/config import; scrub anything that could
# env-lock or leak real keys into the test.
os.environ["SMARTDOCS_DESKTOP"] = "1"
os.environ["SMARTDOCS_DATA_DIR"] = _TMP
os.environ["HOST"] = "127.0.0.1"
for var in ("ALLOW_CLOUD", "_ALLOW_CLOUD_MANAGED", "GROQ_API_KEY", "GEMINI_API_KEY"):
    os.environ.pop(var, None)

from services import desktop_mode as dm  # noqa: E402

dm.apply_data_dirs()

from app import app, APP_VERSION, login_manager  # noqa: E402
import desktop_server as ds  # noqa: E402
from services import settings_store  # noqa: E402

ds.install_desktop_hooks(app, login_manager, TOK, lambda: None, APP_VERSION)
app.config["TESTING"] = True


def _client():
    return app.test_client()


def _put_privacy(c, allow, ack=False):
    return c.put("/api/settings/privacy",
                 headers={dm.TOKEN_HEADER: TOK},
                 json={"allow_cloud": allow, "ack": ack})


def _get_settings(c):
    r = c.get("/api/settings", headers={dm.TOKEN_HEADER: TOK})
    assert r.status_code == 200, r.data
    return r.get_json()


def test_switch_to_local_only_returns_the_refreshed_state():
    c = _client()
    r = _put_privacy(c, allow=False)
    assert r.status_code == 200, r.data
    payload = r.get_json()
    # The success response IS the render source — it must carry the flip.
    assert payload["success"] is True
    assert payload["privacy"]["processing_mode"] == "local_only"
    assert payload["privacy"]["allow_cloud"] is False
    assert _get_settings(c)["privacy"]["processing_mode"] == "local_only"


def test_local_only_actually_blocks_cloud():
    c = _client()
    _put_privacy(c, allow=False)
    # Provider routing gate (what chat/agent consult before any cloud call).
    from agent.core.provider import cloud_allowed
    assert cloud_allowed() is False
    # Cloud key save/test endpoints refuse — not merely hidden in the UI.
    r = c.post("/api/settings/keys/groq", headers={dm.TOKEN_HEADER: TOK},
               json={"api_key": "gsk_dummy_value_for_refusal_test"})
    assert r.status_code == 409, r.data
    r = c.post("/api/settings/keys/groq/test", headers={dm.TOKEN_HEADER: TOK}, json={})
    assert r.status_code == 409
    assert r.get_json()["state"] == "blocked"


def test_first_cloud_enable_requires_ack_then_never_again():
    c = _client()
    _put_privacy(c, allow=False)
    # Reset the ack for a clean first-enable.
    sp = settings_store._settings_path()
    data = json.loads(sp.read_text()) if sp.exists() else {}
    data["cloud_ack"] = False
    sp.write_text(json.dumps(data))

    r = _put_privacy(c, allow=True, ack=False)          # failure path
    assert r.status_code == 409
    body = r.get_json()
    assert body["success"] is False and body["needs_ack"] is True
    assert _get_settings(c)["privacy"]["processing_mode"] == "local_only"  # unchanged

    r = _put_privacy(c, allow=True, ack=True)           # confirmed
    assert r.status_code == 200
    assert r.get_json()["privacy"]["processing_mode"] == "cloud_allowed"
    assert r.get_json()["privacy"]["cloud_ack"] is True  # UI won't ask again


def test_env_locked_toggle_fails_with_an_actionable_error():
    c = _client()
    os.environ["ALLOW_CLOUD"] = "true"
    os.environ.pop("_ALLOW_CLOUD_MANAGED", None)
    try:
        assert _get_settings(c)["privacy"]["env_locked"] is True
        r = _put_privacy(c, allow=False)
        assert r.status_code == 409
        body = r.get_json()
        assert body["success"] is False and "ALLOW_CLOUD" in body["error"]
    finally:
        os.environ.pop("ALLOW_CLOUD", None)


def test_choice_persists_for_the_next_start():
    c = _client()
    _put_privacy(c, allow=False)
    sp = settings_store._settings_path()
    assert sp.exists() and sp.parent == pathlib.Path(_TMP)
    assert json.loads(sp.read_text())["allow_cloud"] is False
    # What a fresh process would resolve on startup:
    assert settings_store.get_allow_cloud() is False
    os.environ.pop("ALLOW_CLOUD", None)
    os.environ.pop("_ALLOW_CLOUD_MANAGED", None)
    settings_store.apply_persisted_settings()
    from config import cfg
    assert cfg.ALLOW_CLOUD is False


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
