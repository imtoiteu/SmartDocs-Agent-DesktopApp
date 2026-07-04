from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from config import cfg

from .base import OCREngine

logger = logging.getLogger(__name__)

# Layout labels GLM-OCR emits whose `content` is HTML (kept verbatim in markdown /
# tables_html, but stripped to readable text for the flat `results`/plain-text path).
_HTML_LABELS = {"table"}
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")


def _strip_html(s: str) -> str:
    """Turn an HTML fragment (e.g. a <table>) into readable plain text."""
    s = re.sub(r"</(tr|p|div|h\d|li)>", "\n", s, flags=re.I)
    s = re.sub(r"</t[dh]>", "\t", s, flags=re.I)
    s = _TAG_RE.sub("", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">"))
    lines = [_WS_RE.sub(" ", ln).strip(" \t") for ln in s.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


def _scale_box(region: dict, w: int, h: int):
    """Convert GLM 0–1000 normalised polygon/bbox to an image-pixel polygon
    ([[x,y],...]) so the existing canvas overlay (which scales by canvas/img) aligns.
    """
    sx, sy = w / 1000.0, h / 1000.0
    poly = region.get("polygon")
    if isinstance(poly, list) and len(poly) >= 3:
        try:
            return [[round(float(p[0]) * sx, 1), round(float(p[1]) * sy, 1)] for p in poly]
        except Exception:
            pass
    bbox = region.get("bbox_2d")
    if isinstance(bbox, list) and len(bbox) == 4:
        try:
            x1, y1, x2, y2 = (float(v) for v in bbox)
            return [[round(x1 * sx, 1), round(y1 * sy, 1)],
                    [round(x2 * sx, 1), round(y1 * sy, 1)],
                    [round(x2 * sx, 1), round(y2 * sy, 1)],
                    [round(x1 * sx, 1), round(y2 * sy, 1)]]
        except Exception:
            pass
    return None


def _page_of(name: str, default: int = 1) -> int:
    m = re.search(r"page(\d+)", name, re.I)
    return int(m.group(1)) + 1 if m else default


def _img_data_uri(path: Path) -> str | None:
    try:
        b = path.read_bytes()
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(b).decode()}"
    except Exception:
        return None


class GLMOCREngine(OCREngine):
    """GLM OCR — a local GLM-V vision OCR model (0.9B) run via its own SDK/venv.

    GLM-OCR is a *client*: it does layout detection (PP-DocLayoutV3, CPU) and then
    calls a local MLX model server (OpenAI-compatible, default :8080) per region.
    Because the SDK's deps (torch/transformers) cannot co-install with PaddlePaddle,
    SmartDocs invokes it as a **subprocess** in its own venv and reads the artifacts
    it writes (``X.json``/``X.md``/``layout_vis/``/``imgs/``), never importing it.

    Returns the standard SmartDocs shape (``results`` = ``{text, confidence, box}``
    per region, boxes scaled to pixels for the canvas overlay) plus the structured
    representations the viewer consumes: ``markdown``, ``tables_html``,
    ``layout_blocks``, ``images`` (base64 layout-vis + cropped regions) and
    ``raw_json``. ``layout_native=True`` skips the geometric reconstruction.
    """

    engine_name = "glmocr"

    # User-facing message for a listening-but-not-ready server (cold start:
    # the MLX model is still loading, or first-run downloading). Deliberately a
    # calm retry hint, NOT a fatal-looking connection error.
    _LOADING_MSG = "GLM server is still loading the OCR model. Please wait and retry."

    # Cross-platform guard: local MLX exists only on macOS Apple Silicon.
    _UNSUPPORTED_MLX_MSG = ("GLM local MLX is only supported on macOS Apple "
                            "Silicon. Use external_server, maas_api, or disable GLM.")

    def _check_mode(self, w: int, h: int):
        """Validate GLM_OCR_MODE for this platform. Returns an error dict to
        return verbatim, or None when the request may proceed.

        Every unsupported/unconfigured combination answers with a clear,
        structured message — never an exception, never a crash — so on
        Windows/Linux the app keeps running and only the GLM engine explains
        itself (PaddleOCR/VietOCR are unaffected).
        """
        mode = cfg.GLM_OCR_MODE
        if mode == "disabled":
            return self._error(
                "GLM OCR is disabled (GLM_OCR_MODE=disabled). The other OCR "
                "engines are unaffected. Enable it in .env with "
                "GLM_OCR_MODE=local_mlx (macOS Apple Silicon), external_server, "
                "or maas_api.", w, h)
        if mode == "ollama":
            # glmocr ships api_mode=ollama_generate, but the integration is NOT
            # verified in SmartDocs yet — refuse instead of promising support.
            # TODO(glm-ollama): verify glmocr selfhosted with
            # pipeline.ocr_api.api_mode=ollama_generate against
            # GLM_OLLAMA_BASE_URL/GLM_OLLAMA_MODEL, then wire it here.
            return self._error(
                "GLM via Ollama is not verified in SmartDocs yet (reserved "
                "mode). Use external_server (openai_compatible) or maas_api.", w, h)
        if mode not in ("local_mlx", "external_server", "maas_api"):
            return self._error(
                f"Unknown GLM_OCR_MODE '{mode}'. Valid modes: "
                + ", ".join(cfg.GLM_OCR_MODES) + ".", w, h)
        if mode == "local_mlx" and not cfg.IS_APPLE_SILICON:
            return self._error(self._UNSUPPORTED_MLX_MSG, w, h)
        if mode == "external_server":
            if cfg.GLM_EXTERNAL_PROTOCOL == "sdk_server":
                # TODO(glm-sdk-server): POST the image to
                # <GLM_OCR_API_URL>/glmocr/parse (the glmocr SDK server does
                # layout+OCR remotely; see GLM-OCR/glmocr/server.py) and map the
                # JSON/markdown response into _collect()'s shape. Config is
                # reserved; only the transport is missing.
                return self._error(
                    "GLM_EXTERNAL_PROTOCOL=sdk_server is not implemented yet — "
                    "SmartDocs currently reaches external GLM servers via the "
                    "openai_compatible protocol (vLLM / SGLang / mlx_vlm). Set "
                    "GLM_EXTERNAL_PROTOCOL=openai_compatible.", w, h)
            if cfg.GLM_EXTERNAL_PROTOCOL != "openai_compatible":
                return self._error(
                    f"Unknown GLM_EXTERNAL_PROTOCOL "
                    f"'{cfg.GLM_EXTERNAL_PROTOCOL}'. Valid: openai_compatible, "
                    "sdk_server (reserved).", w, h)
        if mode == "maas_api" and not cfg.GLM_MAAS_API_KEY:
            return self._error(
                "GLM_OCR_MODE=maas_api needs an API key — set GLM_MAAS_API_KEY "
                "(or ZHIPU_API_KEY) in .env.", w, h)
        return None

    def _server_up(self) -> bool:
        """Cheap TCP connect to the MLX model server. True if something is listening."""
        try:
            u = urlparse(cfg.GLM_OCR_API_URL)
            host = u.hostname or "localhost"
            port = u.port or (443 if u.scheme == "https" else 80)
            with socket.create_connection((host, port), timeout=3):
                return True
        except Exception:
            return False

    def _server_ready(self):
        """Model-level readiness (``_server_up`` is only port-level).

        mlx_vlm.server exposes ``GET /health`` → ``{"loaded_model": <id|null>,…}``
        (verified in the pinned mlx-vlm 0.6.3 source); it never triggers a model
        load. During a cold load the server's event loop is blocked (the load
        runs inside the request handler), so /health not answering while the
        port is open reliably means "still loading". Returns:

          True  – a model is loaded; inference will answer
          False – listening but still loading → tell the user to retry
          None  – can't tell (no /health endpoint, foreign body, or lazy mode
                  with no model loaded yet) → proceed; a resulting SDK
                  connect-timeout is translated to the retry message instead

        We deliberately do NOT probe ``/v1/models`` (it can block during a load
        and scans the whole cache) and never POST ``/chat/completions`` as a
        check (that WOULD trigger a cold model load).
        """
        import json
        import urllib.error
        import urllib.request

        # Probe scheme://host:port/health — GLM_OCR_API_URL may carry a path in
        # external_server mode (e.g. …/v1/chat/completions); /health always
        # lives at the server root (mlx_vlm, vLLM, SGLang and the glmocr SDK
        # server all expose it there).
        u = urlparse(cfg.GLM_OCR_API_URL)
        base = f"{u.scheme or 'http'}://{u.hostname or 'localhost'}"
        if u.port:
            base += f":{u.port}"
        url = base + "/health"
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                raw = r.read()
        except urllib.error.HTTPError:
            return None            # endpoint unsupported → don't rely on it
        except Exception:
            return False           # port open (checked before) but no answer → loading
        try:
            body = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return None            # answers, but not like mlx_vlm — can't tell
        if not isinstance(body, dict) or "loaded_model" not in body:
            return None
        return True if body.get("loaded_model") else None

    def _error(self, msg: str, w: int = 0, h: int = 0, ms: int = 0) -> dict:
        # Structured failure (NOT an exception) → the route returns it verbatim and
        # the SPA shows a clean error toast (it checks `data.success`).
        return {
            "success": False, "error": msg, "results": [],
            "img_width": w, "img_height": h, "elapsed_ms": ms,
            "ocr_engine": self.engine_name, "inference_status": "error",
            "layout_native": True,
        }

    def run(self, image_path: str) -> dict:
        from PIL import Image

        try:
            with Image.open(image_path) as im:
                w, h = im.size
        except Exception as e:
            return self._error(f"GLM OCR: cannot open image ({e})")

        # Cross-platform mode gate (disabled / wrong platform / reserved modes
        # answer with a clear message instead of a confusing connection error).
        mode = cfg.GLM_OCR_MODE
        mode_err = self._check_mode(w, h)
        if mode_err is not None:
            return mode_err

        # Every supported mode shells out to the glmocr CLI (local layout for
        # local_mlx/external_server; thin cloud passthrough for maas_api).
        if not Path(cfg.GLM_SDK_PYTHON).exists():
            return self._error(
                f"GLM OCR SDK not found at {cfg.GLM_SDK_PYTHON}. "
                f"Install the GLM-OCR venv (see GLM-OCR/GLM-OCR).", w, h)

        # Server checks apply to server-backed modes only (maas_api is a cloud
        # HTTPS API — nothing local to probe, glmocr reports its own errors).
        if mode in ("local_mlx", "external_server"):
            if not self._server_up():
                if mode == "external_server":
                    return self._error(
                        "External GLM server is not reachable at "
                        f"{cfg.GLM_OCR_API_URL}. Check GLM_OCR_API_URL and that "
                        "the vLLM/SGLang/MLX server is running.", w, h)
                return self._error(
                    "GLM-OCR model server is not running on "
                    f"{cfg.GLM_OCR_API_URL}. Start it with tools/glm_serve.sh.", w, h)

            if self._server_ready() is False:
                return self._error(self._LOADING_MSG, w, h)

        # The GLM layout model lives in the PROJECT-LOCAL HF cache
        # (models/huggingface/hub — same cache as every other model; cached by
        # 'scripts/setup_glm.sh --precache-layout'). Export SmartDocs' redirect to
        # the glmocr child explicitly and force offline so it never reaches the
        # network. Legacy fallback: installs primed BEFORE this fix cached the
        # layout model in the default ~/.cache/huggingface — if it is absent
        # locally, strip the redirects (old behavior) so those installs keep
        # working; check_offline.sh flags that state and recommends re-priming.
        env = dict(os.environ)
        if cfg._has_hf_model(cfg.GLM_LAYOUT_MODEL_DIR) or Path(cfg.GLM_LAYOUT_MODEL_DIR).is_dir():
            env["HF_HOME"]            = str(cfg.HF_DIR)
            env["HF_HUB_CACHE"]       = str(cfg.HF_HUB_DIR)
            env["TRANSFORMERS_CACHE"] = str(cfg.HF_HUB_DIR)
            env.pop("HF_DATASETS_CACHE", None)
        else:
            for k in ("HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE", "HF_DATASETS_CACHE"):
                env.pop(k, None)
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"

        out_dir = tempfile.mkdtemp(prefix="glmocr_")
        t0 = time.time()
        try:
            cmd = [
                cfg.GLM_SDK_PYTHON, "-m", "glmocr.cli", "parse", str(image_path),
                "--config", cfg.GLM_CONFIG_YAML,
                "--output", out_dir, "--log-level", "WARNING",
            ]
            if mode == "maas_api":
                # Thin passthrough to the Zhipu cloud API — glmocr does no local
                # layout/OCR in this mode. Needs internet + GLM_MAAS_API_KEY.
                cmd += ["--mode", "maas"]
                env["ZHIPU_API_KEY"] = cfg.GLM_MAAS_API_KEY
                if cfg.GLM_MAAS_API_URL:
                    cmd += ["--set", "pipeline.maas.api_url", cfg.GLM_MAAS_API_URL]
                cmd += ["--set", "pipeline.maas.verify_ssl",
                        "true" if cfg.GLM_MAAS_VERIFY_SSL else "false"]
            else:
                cmd += ["--mode", "selfhosted"]
                if mode == "external_server":
                    # glmocr's pipeline.ocr_api.api_url is the FULL endpoint URL
                    # (GLMOCR_OCR_API_URL env override, see glmocr/config.py).
                    # Accept a bare base URL by appending the OpenAI path.
                    api_url = cfg.GLM_OCR_API_URL.rstrip("/")
                    if not api_url.endswith("/chat/completions"):
                        api_url += "/v1/chat/completions"
                    env["GLMOCR_OCR_API_URL"] = api_url
                    if cfg.GLM_OCR_MODEL:
                        env["GLMOCR_OCR_MODEL"] = cfg.GLM_OCR_MODEL
                    if cfg.GLM_OCR_API_KEY:
                        env["GLMOCR_OCR_API_KEY"] = cfg.GLM_OCR_API_KEY
                    cmd += ["--set", "pipeline.ocr_api.verify_ssl",
                            "true" if cfg.GLM_OCR_VERIFY_SSL else "false"]
            try:
                proc = subprocess.run(
                    cmd, cwd=cfg.GLM_ROOT, env=env, capture_output=True, text=True,
                    timeout=cfg.GLM_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                return self._error(
                    f"GLM OCR timed out after {cfg.GLM_TIMEOUT}s.", w, h,
                    round((time.time() - t0) * 1000))
            if proc.returncode != 0:
                combined = (proc.stderr or "") + (proc.stdout or "")
                # glmocr's connect test raises "Failed to connect to API server
                # at …/v1/chat/completions within 30 seconds" when the server is
                # listening but the model load outlasted its window — on
                # local_mlx a cold start, not a fatal failure. Show the retry
                # message; for remote backends name the endpoint instead.
                if "Failed to connect to API server" in combined:
                    if mode == "local_mlx":
                        return self._error(self._LOADING_MSG, w, h,
                                           round((time.time() - t0) * 1000))
                    endpoint = (cfg.GLM_MAAS_API_URL if mode == "maas_api"
                                else cfg.GLM_OCR_API_URL)
                    return self._error(
                        f"GLM backend not reachable ({endpoint}) — check the "
                        "URL/network"
                        + (", API key" if mode == "maas_api" else "")
                        + ", or whether the remote model is still loading. "
                        "Please retry.", w, h,
                        round((time.time() - t0) * 1000))
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()
                tail = " ".join(tail[-3:])[:300] if tail else "no output"
                return self._error(f"GLM OCR failed: {tail}", w, h,
                                   round((time.time() - t0) * 1000))

            res = self._collect(out_dir, w, h)
            res["elapsed_ms"] = round((time.time() - t0) * 1000)
            return res
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

    # ── artifact parsing ────────────────────────────────────────────────────
    def _collect(self, out_dir: str, w: int, h: int) -> dict:
        import json

        base = Path(out_dir)
        subs = [d for d in base.iterdir() if d.is_dir()]
        stem_dir = subs[0] if subs else base

        # structured json (the one NOT ending _model.json) + raw model json
        struct_path = next(
            (p for p in sorted(stem_dir.glob("*.json")) if not p.name.endswith("_model.json")),
            None)
        if struct_path is None:
            return self._error("GLM OCR produced no JSON output.", w, h)
        try:
            pages = json.loads(struct_path.read_text(encoding="utf-8"))
        except Exception as e:
            return self._error(f"GLM OCR: bad JSON ({e})", w, h)

        items: list[dict] = []
        tables_html: list[str] = []
        layout_blocks: list[dict] = []
        order = 0
        for page in (pages or []):
            for region in (page or []):
                if not isinstance(region, dict):
                    continue
                label = (region.get("label") or "text").lower()
                content = str(region.get("content") or "")
                box = _scale_box(region, w, h)
                text = _strip_html(content) if label in _HTML_LABELS else content
                items.append({"text": text, "confidence": None, "box": box})
                if label in _HTML_LABELS and "<table" in content.lower():
                    tables_html.append(content)
                layout_blocks.append({
                    "label": region.get("label"),
                    "content": content,
                    "bbox": region.get("bbox_2d"),
                    "order": region.get("index", order),
                })
                order += 1

        # markdown
        md_path = next(iter(stem_dir.glob("*.md")), None)
        markdown = md_path.read_text(encoding="utf-8") if md_path else ""

        # extracted images: layout visualisation(s) + cropped region images
        images: list[dict] = []
        for p in sorted((stem_dir / "layout_vis").glob("*")):
            uri = _img_data_uri(p)
            if uri:
                images.append({"label": p.name, "kind": "layout", "page": _page_of(p.stem), "src": uri})
        for p in sorted((stem_dir / "imgs").glob("*")):
            uri = _img_data_uri(p)
            if uri:
                images.append({"label": p.name, "kind": "crop", "page": _page_of(p.stem), "src": uri})

        return {
            "success": True,
            "results": items,
            "img_width": w,
            "img_height": h,
            "ocr_engine": self.engine_name,
            "inference_status": "ok",
            "layout_native": True,
            "markdown": markdown,
            "tables_html": tables_html,
            "layout_blocks": layout_blocks,
            "images": images,
            "raw_json": pages,
        }
