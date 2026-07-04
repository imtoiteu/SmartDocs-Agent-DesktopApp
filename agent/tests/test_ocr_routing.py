"""OCR engine routing tests (Phase 15).

Pure logic: natural-language request → OCR engine (default GLM, Vietnamese → VietOCR,
explicit always wins). Runs under pytest OR standalone.
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import pytest  # noqa: F401
except ImportError:
    pytest = None

from agent.ocr_routing import (  # noqa: E402
    select_ocr_engine, normalize_engine, glm_available,
    GLM, VIETOCR, PADDLE, PADDLE_MODERN,
)


def _eng(msg, explicit=None, glm_ok=True):
    # glm_ok pinned True: these tests exercise the ROUTING rules independent of
    # this host's GLM availability (the fallback has its own tests below).
    return select_ocr_engine(msg, explicit, glm_ok=glm_ok)["engine"]


# ── the spec's worked examples ───────────────────────────────────────────────
def test_examples_from_spec():
    assert _eng("run OCR on this file") == GLM
    assert _eng("run OCR on this file using Vietnamese model") == VIETOCR
    assert _eng("extract Vietnamese text from this image") == VIETOCR
    assert _eng("run OCR using GLM") == GLM


# ── default ──────────────────────────────────────────────────────────────────
def test_default_is_glm():
    r = select_ocr_engine("please OCR this document", glm_ok=True)
    assert r["engine"] == GLM and r["reason"] == "default" and r["ocr_requested"] is True


def test_default_for_empty_message():
    assert _eng("") == GLM
    assert _eng(None) == GLM


# ── Vietnamese routing ───────────────────────────────────────────────────────
def test_vietnamese_variants_route_to_vietocr():
    for msg in [
        "use Vietnamese OCR",
        "run OCR using the Vietnamese model",
        "OCR Vietnamese text",
        "scan this with VietOCR",
        "đọc OCR tiếng việt",                 # Vietnamese-language phrasing + ocr
    ]:
        assert _eng(msg) == VIETOCR, msg
    assert select_ocr_engine("use Vietnamese OCR")["reason"] in (
        "vietnamese-request", "explicit-in-text")


def test_translate_to_vietnamese_is_not_ocr():
    # A translation request that merely mentions Vietnamese must NOT pick VietOCR,
    # and must not be flagged as an OCR request.
    r = select_ocr_engine("translate this document to Vietnamese", glm_ok=True)
    assert r["engine"] == GLM and r["ocr_requested"] is False


# ── explicit engine named in text ────────────────────────────────────────────
def test_explicit_engine_in_text():
    assert _eng("run OCR using GLM") == GLM
    assert _eng("ocr with PaddleOCR Modern") == PADDLE_MODERN
    assert _eng("use ppstructure to ocr this") == PADDLE_MODERN
    assert select_ocr_engine("run OCR using GLM")["reason"] == "explicit-in-text"


# ── explicit engine argument always overrides ────────────────────────────────
def test_explicit_arg_overrides_text():
    # Even though the text screams Vietnamese, an explicit arg wins.
    r = select_ocr_engine("extract Vietnamese text", explicit="glm")
    assert r["engine"] == GLM and r["reason"] == "explicit"
    assert _eng("run OCR using GLM", explicit="vietocr") == VIETOCR
    assert _eng("anything", explicit="paddleocr_modern") == PADDLE_MODERN


def test_unknown_explicit_arg_is_ignored():
    # An unrecognized engine arg falls through to text/default routing.
    assert _eng("run OCR on this file", explicit="nope") == GLM
    assert _eng("OCR Vietnamese text", explicit="") == VIETOCR


# ── normalize_engine ─────────────────────────────────────────────────────────
def test_normalize_engine_aliases():
    assert normalize_engine("glm") == GLM
    assert normalize_engine("GLM_OCR") == GLM
    assert normalize_engine("vietocr") == VIETOCR
    assert normalize_engine("paddle") == PADDLE
    assert normalize_engine("modern") == PADDLE_MODERN
    assert normalize_engine("auto") == GLM            # agent default
    assert normalize_engine("bogus") is None
    assert normalize_engine(None) is None


# ── GLM-unavailable fallback (cross-platform; review P1) ─────────────────────
def test_default_falls_back_when_glm_unavailable():
    r = select_ocr_engine("run OCR on this file", glm_ok=False)
    assert r["engine"] == PADDLE_MODERN
    assert r["reason"] == "glm-unavailable-fallback"
    assert r["fallback_from"] == GLM
    assert r["ocr_requested"] is True


def test_auto_explicit_arg_gets_fallback_too():
    # 'auto' means "use the default", so it must fall back like the default does.
    r = select_ocr_engine("anything", explicit="auto", glm_ok=False)
    assert r["engine"] == PADDLE_MODERN and r["reason"] == "glm-unavailable-fallback"
    assert select_ocr_engine("anything", explicit="auto", glm_ok=True)["engine"] == GLM


def test_explicit_glm_is_honoured_even_when_unavailable():
    # A user who explicitly picked GLM keeps their choice (the mode layer's clear
    # per-mode error message explains why it cannot run) — arg AND in-text forms.
    assert _eng("scan this", explicit="glm", glm_ok=False) == GLM
    assert _eng("run OCR using GLM", glm_ok=False) == GLM


def test_vietnamese_routing_unaffected_by_glm_availability():
    assert _eng("use Vietnamese OCR", glm_ok=False) == VIETOCR


def test_glm_available_follows_config_mode():
    # glm_available() reads config.GLM_OCR_MODE lazily; drive it via the cfg
    # singleton (restored afterwards) so the test is host-independent.
    from config import cfg
    saved = (cfg.GLM_OCR_MODE, cfg.IS_APPLE_SILICON, cfg.GLM_EXTERNAL_PROTOCOL,
             cfg.GLM_MAAS_API_KEY)
    try:
        cfg.GLM_OCR_MODE = "disabled"
        assert glm_available() is False
        cfg.GLM_OCR_MODE = "ollama"                     # reserved → unavailable
        assert glm_available() is False
        cfg.GLM_OCR_MODE = "local_mlx"
        cfg.IS_APPLE_SILICON = False
        assert glm_available() is False                 # MLX off-platform
        cfg.IS_APPLE_SILICON = True
        assert glm_available() is True
        cfg.GLM_OCR_MODE = "external_server"
        cfg.GLM_EXTERNAL_PROTOCOL = "openai_compatible"
        assert glm_available() is True
        cfg.GLM_EXTERNAL_PROTOCOL = "sdk_server"        # reserved protocol
        assert glm_available() is False
        cfg.GLM_OCR_MODE = "maas_api"
        cfg.GLM_MAAS_API_KEY = ""
        assert glm_available() is False                 # no key
        cfg.GLM_MAAS_API_KEY = "zh-key"
        assert glm_available() is True
    finally:
        (cfg.GLM_OCR_MODE, cfg.IS_APPLE_SILICON, cfg.GLM_EXTERNAL_PROTOCOL,
         cfg.GLM_MAAS_API_KEY) = saved


def test_select_uses_config_when_glm_ok_not_given():
    # Without a glm_ok override the config-derived availability decides.
    from config import cfg
    saved = cfg.GLM_OCR_MODE
    try:
        cfg.GLM_OCR_MODE = "disabled"
        assert select_ocr_engine("run OCR on this file")["engine"] == PADDLE_MODERN
    finally:
        cfg.GLM_OCR_MODE = saved


# ── result shape ─────────────────────────────────────────────────────────────
def test_result_shape_and_labels():
    r = select_ocr_engine("run OCR on this file", glm_ok=True)
    assert set(r.keys()) == {"engine", "label", "reason", "ocr_requested"}
    assert r["label"] == "GLM OCR"
    assert select_ocr_engine("use Vietnamese OCR")["label"] == "VietOCR"
    rf = select_ocr_engine("run OCR on this file", glm_ok=False)
    assert set(rf.keys()) == {"engine", "label", "reason", "ocr_requested",
                              "fallback_from"}
    assert rf["label"] == "PaddleOCR Modern"


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
