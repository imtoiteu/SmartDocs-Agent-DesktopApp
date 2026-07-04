"""
SmartDocs Platform — Central Configuration
==========================================
Reads from environment variables (or a .env file via python-dotenv).
All platform-specific paths and device settings are resolved here.
Every other module imports from this file instead of hardcoding values.

Usage:
    from config import cfg
    print(cfg.UPLOAD_DIR)
    print(cfg.DEVICE)
"""

import os
import sys
import logging
import platform
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Try to load .env file ──────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
        logger.info(f"[Config] Loaded .env from {_env_file}")
except ImportError:
    pass   # python-dotenv is optional; env vars can be set manually

# ── Base directory (always the folder containing this file) ───────────────
BASE_DIR = Path(__file__).parent.resolve()


# ── VietOCR config.yml validation (shared) ─────────────────────────────────
# Used by tools/setup_offline.py (post-generation validation), by
# check_offline_readiness() (so the readiness report flags an INVALID file, not
# just a missing one) and by the VietOCR adapter (clear runtime error instead of
# "'NoneType' object is not iterable" — vietocr's Cfg.load_config_from_file does
# dict.update(yaml.safe_load(f)), which crashes exactly that way on an empty or
# non-mapping yaml file). Keys mirror what vietocr's build_model()/Predictor
# actually reads (vietocr 0.3.13 source: tool/translate.py + tool/predictor.py).
VIETOCR_REQUIRED_KEYS = (
    "vocab", "device", "weights", "backbone",
    "cnn", "transformer", "seq_modeling", "dataset", "predictor",
)


def validate_vietocr_config(path) -> tuple:
    """Structurally validate a VietOCR config.yml. Returns (ok, reason).

    Pure yaml — never imports vietocr/torch, safe for readiness checks.
    Checks: file exists, parses to a NON-EMPTY mapping, every key vietocr's
    Predictor reads is present and non-None, and the weights path (if local)
    points at an existing file.
    """
    try:
        import yaml
        p = Path(path)
        if not p.exists():
            return False, "file missing"
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        if raw is None:
            return False, "file is EMPTY (yaml parses to None)"
        if not isinstance(raw, dict) or not raw:
            return False, f"yaml is not a mapping (got {type(raw).__name__})"
        missing = [k for k in VIETOCR_REQUIRED_KEYS if raw.get(k) is None]
        if missing:
            return False, "required keys missing/None: " + ", ".join(missing)
        w = str(raw.get("weights") or "")
        if w and not w.startswith("http") and not Path(w).exists():
            return False, f"weights path in config does not exist: {w}"
        return True, "ok"
    except Exception as e:
        return False, f"unreadable ({e})"

# ── Model directory ───────────────────────────────────────────────────────
# Default: web_app/models/  (portable, offline-ready)
# Override: set MODEL_DIR=/absolute/path in .env
MODEL_DIR_RAW = os.environ.get("MODEL_DIR", "")
MODEL_DIR_DEFAULT = BASE_DIR / "models"


def _resolve_dir(env_key: str, default: Path) -> Path:
    """Read a Path from env; fall back to default. Always creates the dir."""
    raw = os.environ.get(env_key, "")
    p = Path(raw).resolve() if raw else default
    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_file(env_key: str, default: Path) -> Path:
    """Read a file Path from env; fall back to default. Parent dir is created."""
    raw = os.environ.get(env_key, "")
    p = Path(raw).resolve() if raw else default
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _env_bool(env_key: str, default: bool) -> bool:
    """Read a boolean env var (1/true/yes/on vs 0/false/no/off)."""
    raw = os.environ.get(env_key, "")
    if raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _resolve_model_dir() -> Path:
    """Resolve MODEL_DIR: env override → ./models → HuggingFace default cache."""
    raw = os.environ.get("MODEL_DIR", "")
    if raw:
        p = Path(raw).resolve()
    else:
        p = BASE_DIR / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _configure_hf_env(model_dir: Path):
    """
    Set all required environment variables for offline model loading.
    Must be called BEFORE any import of transformers, huggingface_hub,
    or argostranslate.

    Directory layout inside MODEL_DIR (standard HF hub layout):
        huggingface/
            hub/
                models--Qwen--Qwen2.5-1.5B-Instruct/
                models--vinai--phobert-base-v2/
                models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2/
        argos/
            packages/
    """
    hf_local = model_dir / "huggingface"
    hf_hub = hf_local / "hub"
    hf_hub.mkdir(parents=True, exist_ok=True)

    # HuggingFace: HF_HOME → models/huggingface/, hub cache → models/huggingface/hub/
    # (the STANDARD layout, so `cache_dir=` args and env-var resolution agree).
    # HARD-set (not setdefault): an HF_HOME/HF_HUB_CACHE inherited from the user's
    # shell (typically ~/.cache/huggingface) would silently split the caches —
    # setup downloads into one place, the app loads from another ("setup says
    # downloaded, app says missing"). MODEL_DIR in .env is the single supported
    # relocation knob; these paths derive from it.
    for _k, _v in (("HF_HOME", str(hf_local)),
                   ("HF_HUB_CACHE", str(hf_hub)),
                   ("TRANSFORMERS_CACHE", str(hf_hub))):
        if os.environ.get(_k) not in (None, "", _v):
            logger.warning(f"[Config] Overriding inherited {_k}="
                           f"{os.environ.get(_k)} → {_v} (derived from MODEL_DIR)")
        os.environ[_k] = _v
    # sentence-transformers>=2.3 stores models in the HF hub cache above; an
    # inherited SENTENCE_TRANSFORMERS_HOME would move them OUT of it.
    os.environ.pop("SENTENCE_TRANSFORMERS_HOME", None)

    # Argos Translate: MUST be set before argostranslate is imported.
    # argostranslate reads ARGOS_PACKAGES_DIR at module import time to build
    # its package_dirs list — setting settings.data_dir after import does nothing.
    # HARD-set (not setdefault): a stale ARGOS_PACKAGES_DIR inherited from the
    # user's shell would make setup install into models/argos/ while the runtime
    # loads from somewhere else ("packages installed but model not installed").
    # The project-local dir is the single supported location; relocate it via
    # MODEL_DIR in .env, which this path derives from.
    argos_packages = model_dir / "argos" / "packages"
    argos_packages.mkdir(parents=True, exist_ok=True)
    if os.environ.get("ARGOS_PACKAGES_DIR") not in ("", None, str(argos_packages)):
        logger.warning(f"[Config] Overriding inherited ARGOS_PACKAGES_DIR="
                       f"{os.environ.get('ARGOS_PACKAGES_DIR')} → {argos_packages}")
    os.environ["ARGOS_PACKAGES_DIR"]          = str(argos_packages)
    os.environ["ARGOS_TRANSLATE_PACKAGE_DIR"] = str(argos_packages)  # legacy

    # Offline mode: never attempt downloads if OFFLINE=1 in .env
    offline = os.environ.get("OFFLINE", "1")   # default ON (local-first)
    if offline == "1":
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        # Stanza Offline: Prevent check for updates and raw.githubusercontent.com calls
        os.environ["STANZA_RESOURCES_DIR"] = str(argos_packages)
    else:
        # Allow downloads (useful when online to fetch newer versions)
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ.pop("TRANSFORMERS_OFFLINE", None)
        os.environ.pop("STANZA_RESOURCES_DIR", None)


    return hf_local


# ══════════════════════════════════════════════════════════════════════════════
#  DEVICE SELECTION
# ══════════════════════════════════════════════════════════════════════════════

def _select_device(requested: str = "auto") -> str:
    """
    Resolve the best available compute device.

    Priority (when requested == "auto"):
      1. CUDA  — if torch + CUDA GPU is available
      2. MPS   — if Apple Silicon (torch.backends.mps.is_available)
      3. CPU   — always available fallback

    The resolved device is logged once at startup.
    """
    req = requested.lower().strip()

    try:
        import torch
    except ImportError:
        logger.warning("[Config] PyTorch not installed — defaulting to cpu")
        return "cpu"

    if req == "cuda":
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            logger.info(f"[Config] Device: CUDA ({name})")
            return "cuda"
        logger.warning("[Config] CUDA requested but not available — falling back to cpu")
        return "cpu"

    if req == "mps":
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            logger.info("[Config] Device: MPS (Apple Silicon)")
            return "mps"
        logger.warning("[Config] MPS requested but not available — falling back to cpu")
        return "cpu"

    if req == "cpu":
        logger.info("[Config] Device: CPU (forced by config)")
        return "cpu"

    # "auto" — pick best available
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        logger.info(f"[Config] Device (auto): CUDA ({name})")
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        logger.info("[Config] Device (auto): MPS (Apple Silicon)")
        return "mps"
    logger.info("[Config] Device (auto): CPU")
    return "cpu"


def _select_dtype(device: str):
    """
    Choose the best floating-point dtype for the resolved device.

    - CUDA  → float16 (fast, VRAM-efficient)
    - MPS   → float16 (Apple driver supports it for most models)
    - CPU   → float32 (stable; float16 on CPU is slow and numerically fragile)

    Override with DTYPE env var: float16 | float32 | bfloat16
    """
    override = os.environ.get("DTYPE", "").lower()
    try:
        import torch
        _map = {
            "float16":  torch.float16,
            "fp16":     torch.float16,
            "float32":  torch.float32,
            "fp32":     torch.float32,
            "bfloat16": torch.bfloat16,
            "bf16":     torch.bfloat16,
        }
        if override in _map:
            logger.info(f"[Config] Dtype: {override} (from DTYPE env)")
            return _map[override]
        # Auto-select
        if device == "cuda":
            return torch.float16
        if device == "mps":
            return torch.float16
        return torch.float32      # CPU default
    except ImportError:
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  PLATFORM INFO
# ══════════════════════════════════════════════════════════════════════════════

def _platform_summary() -> str:
    bits = "64-bit" if sys.maxsize > 2**32 else "32-bit"
    return f"{platform.system()} {platform.release()} ({platform.machine()}, {bits})"


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG OBJECT
# ══════════════════════════════════════════════════════════════════════════════

class _Config:
    """
    Singleton configuration object populated at import time.
    All values are resolved once; changes to env vars after import are ignored.
    """

    def __init__(self):
        # ── Directories ──────────────────────────────────────────────────────
        self.BASE_DIR:    Path = BASE_DIR
        self.UPLOAD_DIR:  Path = _resolve_dir("UPLOAD_DIR",  BASE_DIR / "uploads")

        # MODEL_DIR: defaults to web_app/models/ (portable, offline-ready)
        self.MODEL_DIR:   Path = _resolve_model_dir()

        # ── Configure HuggingFace env vars BEFORE any HF/transformers imports ─
        # This redirects all HF downloads to models/huggingface/hub/
        self.HF_DIR:      Path = _configure_hf_env(self.MODEL_DIR)
        # Standard hub cache (where HF_HUB_CACHE points and models actually live)
        self.HF_HUB_DIR:  Path = self.HF_DIR / "hub"

        # ── Argos Translate data directory ───────────────────────────────────
        self.ARGOS_DIR:   Path = self.MODEL_DIR / "argos"
        self.ARGOS_DIR.mkdir(parents=True, exist_ok=True)

        # ── Offline flag ──────────────────────────────────────────────────────
        self.OFFLINE:     bool = os.environ.get("OFFLINE", "1") == "1"

        # ── Database ─────────────────────────────────────────────────────────
        self.DB_PATH:     Path = _resolve_file("DB_PATH",    BASE_DIR / "paddleocr.db")

        # ── Server ───────────────────────────────────────────────────────────
        self.HOST:        str  = os.environ.get("HOST", "0.0.0.0")
        self.PORT:        int  = int(os.environ.get("PORT", "5001"))
        self.SECRET_KEY:  str  = os.environ.get("SECRET_KEY", "")  # filled later in app.py

        # ── Upload size limit (DoS protection) ───────────────────────────────
        # Caps the request body Flask will accept; applies to /api/upload and every
        # JSON endpoint. Without it a single huge request can exhaust disk/RAM.
        # Configurable via MAX_UPLOAD_MB (default 50 MB).
        self.MAX_UPLOAD_MB:      int = int(os.environ.get("MAX_UPLOAD_MB", "50"))
        self.MAX_CONTENT_LENGTH: int = self.MAX_UPLOAD_MB * 1024 * 1024

        # ── Session cookie hardening ─────────────────────────────────────────
        # HttpOnly + SameSite=Lax are always applied (safe over HTTP). The Secure
        # flag is gated here because the bundled dev server serves plain HTTP — set
        # SESSION_COOKIE_SECURE=1 when deployed behind HTTPS/TLS so cookies are
        # never sent in clear text.
        self.SESSION_COOKIE_SECURE: bool = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

        # ── Device ───────────────────────────────────────────────────────────
        _device_req      = os.environ.get("DEVICE", "auto")
        self.DEVICE:      str  = _select_device(_device_req)

        # ── Display timezone ────────────────────────────────────────────────
        # Timestamps are stored as UTC; this is the timezone used to render them
        # (admin templates via the vn_time Jinja filter; the SPA via Intl).
        self.DISPLAY_TZ: str = os.environ.get("DISPLAY_TZ", "Asia/Ho_Chi_Minh").strip()

        # ── OCR Engine Selection ────────────────────────────────────────────
        self.OCR_ENGINE: str = os.environ.get("OCR_ENGINE", "paddle").strip().lower()
        self.VIETOCR_DEVICE: str = os.environ.get("VIETOCR_DEVICE", self.DEVICE).strip().lower()
        self.VIETOCR_CONFIG: str = os.environ.get("VIETOCR_CONFIG", "vgg_transformer")
        _vietocr_default = self.MODEL_DIR / "vietocr" / f"{self.VIETOCR_CONFIG}.pth"
        self.VIETOCR_WEIGHTS: str = os.environ.get(
            "VIETOCR_WEIGHTS",
            str(_vietocr_default) if _vietocr_default.exists() else "",
        ).strip()

        # ── GLM-OCR engine (subprocess; OWN venv + local MLX model server) ───
        # GLM-OCR is a third-party SDK vendored INSIDE this repo at
        # <repo>/GLM-OCR. SmartDocs never imports it — the adapter shells out to
        # the `glmocr` CLI (running in the GLM venv) and reads the artifacts it
        # writes. GLM-OCR runs in its own venv because its torch/transformers
        # deps cannot co-install with paddle.
        #
        # Path resolution is CLEAN-CLONE friendly: with nothing configured, the
        # vendored copy at <repo>/GLM-OCR is used. Only an explicit env var points
        # elsewhere:
        #   GLM_OCR_DIR   – GLM-OCR directory (legacy alias: GLM_ROOT)
        #   GLM_SDK_PYTHON – interpreter that runs the `glmocr` CLI
        #   GLM_MLX_PYTHON – interpreter that runs the MLX model server
        # When the interpreters are not pinned, we pick the first that exists of
        # the repo-local .venv-mlx / .venv-sdk (setup_glm.sh creates .venv-mlx).
        _glm_dir_default = BASE_DIR / "GLM-OCR"
        _glm_dir = (os.environ.get("GLM_OCR_DIR")
                    or os.environ.get("GLM_ROOT")
                    or str(_glm_dir_default))
        self.GLM_ROOT:        Path = Path(_glm_dir)

        def _first_existing(candidates: list, fallback) -> str:
            for c in candidates:
                if Path(c).exists():
                    return str(c)
            return str(fallback)

        _glm_mlx_py = self.GLM_ROOT / ".venv-mlx" / "bin" / "python"
        _glm_sdk_py = self.GLM_ROOT / ".venv-sdk" / "bin" / "python"
        # SDK CLI: prefer a dedicated .venv-sdk, else the unified .venv-mlx.
        self.GLM_SDK_PYTHON:  str  = os.environ.get(
            "GLM_SDK_PYTHON", _first_existing([_glm_sdk_py, _glm_mlx_py], _glm_sdk_py))
        # MLX server: prefer .venv-mlx, else fall back to .venv-sdk.
        self.GLM_MLX_PYTHON:  str  = os.environ.get(
            "GLM_MLX_PYTHON", _first_existing([_glm_mlx_py, _glm_sdk_py], _glm_mlx_py))
        # Selfhosted config: prefer a repo-local mlx_config.yaml (setup_glm.sh
        # generates one), else the SDK's bundled glmocr/config.yaml.
        self.GLM_CONFIG_YAML: str  = os.environ.get(
            "GLM_CONFIG_YAML",
            _first_existing([self.GLM_ROOT / "mlx_config.yaml",
                             self.GLM_ROOT / "glmocr" / "config.yaml"],
                            self.GLM_ROOT / "mlx_config.yaml"))
        # Layout model for GLM self-hosted mode. glmocr requires
        # pipeline.layout.model_dir; setup_glm.sh writes this value into
        # mlx_config.yaml. May be a Hugging Face model id (default, cached in the
        # PROJECT-LOCAL hub) or an absolute local checkpoint directory.
        self.GLM_LAYOUT_MODEL_DIR: str = os.environ.get(
            "GLM_LAYOUT_MODEL_DIR", "PaddlePaddle/PP-DocLayoutV3_safetensors")
        # The model the MLX server ITSELF loads (a different model from the
        # layout detector above). Cached project-locally like every other model:
        # 'scripts/setup_glm.sh --precache-mlx' primes it, and tools/glm_serve.sh
        # exports the project HF cache before starting the server.
        self.GLM_MLX_MODEL: str = os.environ.get(
            "GLM_MODEL", "mlx-community/GLM-OCR-bf16")
        # Local MLX model server (OpenAI-compatible). Started manually via
        # tools/glm_serve.sh; the adapter health-checks it before each run.
        self.GLM_OCR_API_URL: str  = os.environ.get("GLM_OCR_API_URL", "http://localhost:8080")
        self.GLM_TIMEOUT:     int  = int(os.environ.get("GLM_TIMEOUT", "300"))

        # ── GLM backend mode (cross-platform) ────────────────────────────────
        # GLM-OCR (upstream github.com/zai-org/GLM-OCR) is NOT macOS-only — the
        # model can be reached several ways. GLM_OCR_MODE selects the transport:
        #   local_mlx       – local mlx_vlm server (macOS Apple Silicon ONLY;
        #                     the scripts/start_glm.sh + tools/glm_serve.sh flow)
        #   external_server – a GLM-OCR backend on another machine (vLLM /
        #                     SGLang / mlx_vlm on a Mac / the glmocr SDK server)
        #                     — see GLM_EXTERNAL_PROTOCOL below
        #   maas_api        – Zhipu MaaS cloud API (glmocr --mode maas; needs an
        #                     API key and internet)
        #   ollama          – RESERVED: glmocr ships api_mode=ollama_generate but
        #                     the integration is not yet verified in SmartDocs;
        #                     the adapter refuses it with a clear message
        #   disabled        – GLM OCR off (the other OCR engines are unaffected)
        # Platform-aware default: local_mlx on macOS Apple Silicon (the verified
        # baseline), disabled everywhere else — Windows/Linux must never assume a
        # local MLX server exists. ENABLE_GLM=false stays the master off switch
        # (same flag the scripts/ launchers honour) and forces disabled.
        self.IS_APPLE_SILICON: bool = (
            platform.system() == "Darwin" and platform.machine() == "arm64")
        self.GLM_OCR_MODES = ("disabled", "local_mlx", "external_server",
                              "maas_api", "ollama")
        _glm_mode = os.environ.get(
            "GLM_OCR_MODE",
            "local_mlx" if self.IS_APPLE_SILICON else "disabled").strip().lower()
        if not _env_bool("ENABLE_GLM", True):
            _glm_mode = "disabled"
        self.GLM_OCR_MODE: str = _glm_mode

        # external_server protocol:
        #   openai_compatible – POST <GLM_OCR_API_URL>/v1/chat/completions
        #                       (vLLM / SGLang / mlx_vlm). Layout detection still
        #                       runs locally in GLM-OCR/.venv-sdk (glmocr
        #                       "selfhosted" mode with a remote ocr_api URL).
        #                       This is the protocol SUPPORTED today.
        #   sdk_server        – POST <GLM_OCR_API_URL>/glmocr/parse (the glmocr
        #                       SDK server does layout+OCR remotely; no local GLM
        #                       venv needed). NOT implemented yet — config is
        #                       reserved; the adapter answers with a clear
        #                       message (see docs/OCR_ENGINES.md).
        self.GLM_EXTERNAL_PROTOCOL: str = os.environ.get(
            "GLM_EXTERNAL_PROTOCOL", "openai_compatible").strip().lower()
        # Model name sent in external OpenAI-compatible requests (vLLM/SGLang
        # require the served model id; blank = the config.yaml/server default).
        self.GLM_OCR_MODEL:      str  = os.environ.get("GLM_OCR_MODEL", "").strip()
        self.GLM_OCR_API_KEY:    str  = os.environ.get("GLM_OCR_API_KEY", "").strip()
        self.GLM_OCR_VERIFY_SSL: bool = _env_bool("GLM_OCR_VERIFY_SSL", False)

        # maas_api (Zhipu cloud) — glmocr forwards requests; no local models and
        # no local server needed. GLM_MAAS_API_KEY wins; ZHIPU_API_KEY (the
        # SDK's own variable) is honoured as a fallback.
        self.GLM_MAAS_API_URL: str = os.environ.get(
            "GLM_MAAS_API_URL",
            "https://open.bigmodel.cn/api/paas/v4/layout_parsing").strip()
        self.GLM_MAAS_API_KEY: str = (os.environ.get("GLM_MAAS_API_KEY")
                                      or os.environ.get("ZHIPU_API_KEY")
                                      or "").strip()
        self.GLM_MAAS_VERIFY_SSL: bool = _env_bool("GLM_MAAS_VERIFY_SSL", True)

        # ollama (RESERVED — unverified; see GLM_OCR_MODE above)
        self.GLM_OLLAMA_BASE_URL: str = os.environ.get(
            "GLM_OLLAMA_BASE_URL", "http://localhost:11434").strip()
        self.GLM_OLLAMA_MODEL:    str = os.environ.get("GLM_OLLAMA_MODEL", "").strip()

        # ── LLM provider layer (chat / rewrite / agent) ──────────────────────
        # LLM_PROVIDER selects where LLM completions come from:
        #   local_hf          – local Hugging Face model (offline-first DEFAULT)
        #   openai_compatible – any OpenAI-compatible /v1/chat/completions server
        #                       (vLLM, llama.cpp server, LM Studio, …). Wired into
        #                       the AGENT provider chain today; chat and AI-rewrite
        #                       still use the local model (documented TODO).
        #   disabled          – no LLM: chat/agent/AI-rewrite answer with a clear
        #                       setup hint instead of loading anything.
        self.LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "local_hf").strip().lower()
        # Default lightweight LOCAL model for ALL local LLM features.
        # Qwen2.5-1.5B-Instruct is the default, not the only option:
        # LOCAL_LLM_MODEL changes the default for chat + rewrite + agent at once;
        # the per-feature QWEN_MODEL / CHAT_MODEL overrides below still win.
        self.LOCAL_LLM_MODEL: str = os.environ.get(
            "LOCAL_LLM_MODEL", "Qwen/Qwen2.5-1.5B-Instruct").strip()
        # Optional device for the local LLM: auto | cpu | mps | cuda. Blank keeps
        # the per-feature CPU-safe defaults below (MPS excluded by default —
        # Apple driver crashes with tensors > 4GB on Qwen-class models).
        self.LOCAL_LLM_DEVICE: str = os.environ.get("LOCAL_LLM_DEVICE", "").strip().lower()
        # Sizing hint surfaced by /api/llm/status for the UI / desktop shell
        # (low ≈ 1–2B CPU-safe default, medium ≈ 3–7B, high ≈ GPU-backed).
        # Informational only — it does not change generation parameters yet.
        self.LOCAL_LLM_PROFILE: str = os.environ.get("LOCAL_LLM_PROFILE", "low").strip().lower()
        # OpenAI-compatible endpoint (used when LLM_PROVIDER=openai_compatible;
        # also offered to the agent's fallback chain whenever configured):
        self.OPENAI_COMPATIBLE_BASE_URL: str = os.environ.get(
            "OPENAI_COMPATIBLE_BASE_URL", "").strip()
        self.OPENAI_COMPATIBLE_API_KEY:  str = os.environ.get(
            "OPENAI_COMPATIBLE_API_KEY", "").strip()
        self.OPENAI_COMPATIBLE_MODEL:    str = os.environ.get(
            "OPENAI_COMPATIBLE_MODEL", "").strip()
        # Feature switches (default on; LLM_PROVIDER=disabled turns all three off
        # unless a flag explicitly re-enables one). Gated routes answer with a
        # clear "disabled" JSON message — never a crash.
        _llm_on = self.LLM_PROVIDER != "disabled"
        self.ENABLE_CHAT:    bool = _env_bool("ENABLE_CHAT",    _llm_on)
        self.ENABLE_AGENT:   bool = _env_bool("ENABLE_AGENT",   _llm_on)
        self.ENABLE_REWRITE: bool = _env_bool("ENABLE_REWRITE", _llm_on)

        # Privacy switch — "Local only" vs "Allow cloud processing". When False,
        # document text / retrieval excerpts / prompts are never sent to the
        # implicit cloud AI APIs (Groq, Gemini, OpenAI, OpenRouter) and
        # translation never uses the online API. An OPENAI_COMPATIBLE_* endpoint
        # the user explicitly configured is treated as self-hosted and stays
        # available. Default True — the pre-existing behavior.
        self.ALLOW_CLOUD: bool = _env_bool("ALLOW_CLOUD", True)

        # Wall-clock budget for one agent run (seconds). Past it the agent stops
        # calling tools and synthesizes an answer from the observations it has —
        # a slow local model can no longer hang a request indefinitely.
        # 0 (or negative) disables the budget.
        try:
            self.AGENT_MAX_SECONDS: float = float(
                os.environ.get("AGENT_MAX_SECONDS", "180"))
        except ValueError:
            self.AGENT_MAX_SECONDS = 180.0

        # ── Qwen / AI Rewrite ────────────────────────────────────────────────
        # For Qwen on MPS: Apple's MPS driver crashes with tensors > 4GB.
        # When MPS is selected as the global device, Qwen still runs on CPU
        # unless the user explicitly sets QWEN_DEVICE=mps (or LOCAL_LLM_DEVICE).
        # Model/device defaults come from LOCAL_LLM_MODEL / LOCAL_LLM_DEVICE
        # above; the per-feature vars keep overriding them (back-compat).
        _qwen_req         = os.environ.get(
            "QWEN_DEVICE",
            self.LOCAL_LLM_DEVICE or ("cpu" if self.DEVICE in ("mps", "cpu") else "auto"))
        self.QWEN_DEVICE: str  = _select_device(_qwen_req)
        self.QWEN_MODEL:  str  = os.environ.get("QWEN_MODEL", self.LOCAL_LLM_MODEL)
        self.QWEN_DTYPE         = _select_dtype(self.QWEN_DEVICE)

        # ── AI Chat ──────────────────────────────────────────────────────────
        # DEFAULT LOCAL LLM POLICY: Qwen2.5-1.5B-Instruct is the intended default
        # for ALL local LLM features (chat, AI rewrite, agent). Larger Qwen models
        # (e.g. 3B) are NOT used by default — they are unstable on Apple-Silicon
        # MPS for this app. To opt into a bigger model, set CHAT_MODEL in .env.
        # Fallback is the SAME 1.5B model until a different one is explicitly set,
        # so a missing 3B never makes chat report itself as broken.
        # Device   : same CPU-safe default as AI Rewrite
        _chat_req              = os.environ.get(
            "CHAT_DEVICE",
            self.LOCAL_LLM_DEVICE or ("cpu" if self.DEVICE in ("mps", "cpu") else "auto"))
        self.CHAT_DEVICE: str  = _select_device(_chat_req)
        self.CHAT_MODEL:  str  = os.environ.get("CHAT_MODEL",  self.LOCAL_LLM_MODEL)
        self.FALLBACK_CHAT_MODEL: str = os.environ.get("FALLBACK_CHAT_MODEL", self.LOCAL_LLM_MODEL)
        self.CHAT_DTYPE        = _select_dtype(self.CHAT_DEVICE)

        # ── PhoBERT / Summarization ──────────────────────────────────────────
        # PhoBERT is small enough to run on MPS safely.
        self.PHOBERT_DEVICE: str = self.DEVICE  # uses the global best device
        self.PHOBERT_MODEL: str  = os.environ.get("PHOBERT_MODEL", "vinai/phobert-base-v2")
        self.PHOBERT_DTYPE       = _select_dtype(self.PHOBERT_DEVICE)

        # ── SQLAlchemy URI (computed from DB_PATH) ───────────────────────────
        # On Windows, sqlite:/// + absolute path needs 4 slashes:
        #   sqlite:////C:/Users/... or sqlite:///C:/Users/...
        # Path.as_posix() gives forward-slash paths on all platforms.
        self.SQLALCHEMY_URI: str = f"sqlite:///{self.DB_PATH.as_posix()}"

        # ── Platform info ─────────────────────────────────────────────────────
        self.PLATFORM: str = _platform_summary()

        # Log key config at startup
        mode = "OFFLINE (local models)" if self.OFFLINE else "ONLINE (downloads allowed)"
        logger.info(f"[Config] Mode: {mode}")
        logger.info(f"[Config] MODEL_DIR: {self.MODEL_DIR}")
        logger.info(f"[Config] HF cache : {self.HF_DIR / 'hub'}")
        logger.info(f"[Config] Argos dir: {self.ARGOS_DIR}")

    def paddle_cache_status(self) -> dict:
        """Inspect PaddleOCR's ACTUAL runtime model cache.

        PaddleOCR 3.x delegates model management to PaddleX, which stores
        downloaded models in <PADDLE_PDX_CACHE_HOME or ~/.paddlex>/official_models/
        /<MODEL_NAME>/  (paddlex source: utils/cache.py:28-29 and
        inference/utils/official_models.py:880). The old check globbed the HF
        cache (models--PaddlePaddle--*), where these models NEVER land — so the
        report said ❌ while OCR worked fine. Pure filesystem; never imports paddle.

        Returns {"cache_dir": str, "models": [names], "det": [..], "rec": [..]}.
        """
        env = os.environ.get("PADDLE_PDX_CACHE_HOME", "").strip()
        roots = []
        if env:
            roots.append(Path(env) / "official_models")
        roots.append(Path.home() / ".paddlex" / "official_models")
        models, used_root = [], roots[-1]
        for root in roots:
            try:
                if root.is_dir():
                    names = sorted(d.name for d in root.iterdir() if d.is_dir())
                    if names:
                        models, used_root = names, root
                        break
            except Exception:
                pass
        return {
            "cache_dir": str(used_root),
            "models":    models,
            "det":       [n for n in models if "det" in n.lower()],
            "rec":       [n for n in models if "rec" in n.lower()],
        }

    def hf_snapshot_dir(self, model_id: str):
        """Locate the snapshot dir for a cached model in the PROJECT-LOCAL HF cache.

        Searches the standard hub layout (``models/huggingface/hub/`` — where
        HF_HUB_CACHE points and setup downloads) first, then the legacy flat
        layout (``models--*`` directly under ``models/huggingface/``) written by
        older setups. Prefers the revision pinned by ``refs/main``. Returns None
        when the model is not cached. Filesystem-only; never touches the network.
        """
        repo = "models--" + model_id.replace("/", "--")
        for root in (self.HF_HUB_DIR, self.HF_DIR):
            repo_dir = root / repo
            refs_main = repo_dir / "refs" / "main"
            if refs_main.exists():
                try:
                    snap = repo_dir / "snapshots" / refs_main.read_text(encoding="utf-8").strip()
                    if snap.exists():
                        return snap
                except Exception:
                    pass
            snapshots = repo_dir / "snapshots"
            if snapshots.exists():
                for snap in sorted(snapshots.iterdir()):
                    if snap.is_dir():
                        return snap
        return None

    def _hf_glob_any(self, pattern: str) -> bool:
        """True if any project-local HF cache root (hub/ or legacy flat) matches."""
        for root in (self.HF_HUB_DIR, self.HF_DIR):
            try:
                if root.exists() and any(root.glob(pattern)):
                    return True
            except Exception:
                pass
        return False

    def check_models(self) -> dict:
        """
        Check which local models are available.
        Returns a dict of {model_name: bool (exists)}.
        """
        paddle = self.paddle_cache_status()
        results = {
            "qwen":       self._hf_glob_any("models--Qwen--*"),
            "phobert":    self._hf_glob_any("models--vinai--*"),
            "paddle_det": bool(paddle["det"]),
            "paddle_rec": bool(paddle["rec"]),
            "vietocr":    Path(self.VIETOCR_WEIGHTS).exists()                if self.VIETOCR_WEIGHTS else False,
            "argos":      any(self.ARGOS_DIR.glob("packages/*/"))            if self.ARGOS_DIR.exists() else False,
        }
        return results

    # ── Comprehensive offline-readiness probe (feature-level) ────────────────
    def _hf_cache_dir_for(self, model_id: str, include_default_cache: bool = False):
        """Return the first HF cache dir that holds ``model_id`` (or None).

        By DEFAULT this searches ONLY the app's redirected cache
        (``models/huggingface/hub/``, plus the legacy flat layout) — the exact
        place the running app loads models from, because importing ``config`` sets
        ``HF_HUB_CACHE`` there. Reporting a model found in the user's DEFAULT
        ``~/.cache/huggingface`` as "ready" would be a false positive: the app
        (with the cache redirected) can't load it, which is precisely the
        "check shows ✅ but the app says not-in-cache" symptom.

        ``include_default_cache=True`` also searches ``~/.cache/huggingface`` — used
        ONLY to detect a GLM model (layout detector or the MLX server model)
        stranded in the default cache by an older setup/server run (reported as
        needing re-priming via ``setup_glm.sh --precache-*``, never as
        project-local/ready).
        """
        name = "models--" + model_id.replace("/", "--")
        roots = [self.HF_HUB_DIR, self.HF_DIR]
        if include_default_cache:
            roots.append(Path.home() / ".cache" / "huggingface" / "hub")
        for root in roots:
            try:
                if root.exists():
                    hit = next(iter(root.glob(name + "*")), None)
                    if hit is not None:
                        return hit
            except Exception:
                pass
        return None

    # Weight-file extensions that mark a genuinely downloaded model (not just a
    # tokenizer/config-only partial). Any ONE resolving file of these is enough.
    _WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth", ".pdparams",
                        ".msgpack", ".gguf", ".onnx", ".ckpt")

    def _hf_snapshot_complete(self, model_root) -> bool:
        """A located ``models--*`` dir is only USABLE offline if a snapshot revision
        holds a RESOLVING ``config.json`` AND at least one RESOLVING weight file.

        HF stores each file in a snapshot as a symlink into ``blobs/``. An aborted
        or partial download leaves DANGLING symlinks, and ``Path.exists()`` (which
        follows the link) returns False for a missing blob. Checking mere directory
        existence — as the old code did — reported a half-downloaded model as ready
        (the "check_offline shows ✅ but the app can't load it" bug). This inspects
        actual resolvable content instead. Filesystem-only; never raises.
        """
        try:
            snap_root = Path(model_root) / "snapshots"
            revs = [p for p in snap_root.iterdir() if p.is_dir()] if snap_root.is_dir() else []
            # Fallback: some caches / raw local dirs store files flat (no snapshots/).
            search_dirs = revs or [Path(model_root)]
            for d in search_dirs:
                has_cfg = (d / "config.json").exists()
                has_weight = any(
                    p.suffix.lower() in self._WEIGHT_SUFFIXES and p.exists()
                    for p in d.glob("*")
                )
                if has_cfg and has_weight:
                    return True
        except Exception:
            pass
        return False

    def _has_hf_model(self, model_id: str, include_default_cache: bool = False) -> bool:
        d = self._hf_cache_dir_for(model_id, include_default_cache=include_default_cache)
        return d is not None and self._hf_snapshot_complete(d)

    def _argos_installed_pairs(self) -> list:
        """List installed Argos language pairs as ``from→to`` strings (sorted).

        Filesystem-only: reads each ``packages/*/metadata.json`` (which carries
        ``from_code``/``to_code``); falls back to the package dir name if metadata
        is absent. Never imports argostranslate, never touches the network.
        """
        import json
        pairs = []
        pkgs = self.ARGOS_DIR / "packages"
        if not pkgs.is_dir():
            return pairs
        for d in sorted(pkgs.iterdir()):
            if not d.is_dir():
                continue
            meta = d / "metadata.json"
            label = None
            if meta.is_file():
                try:
                    m = json.loads(meta.read_text(encoding="utf-8"))
                    fc, tc = m.get("from_code"), m.get("to_code")
                    if fc and tc:
                        label = f"{fc}→{tc}"
                except Exception:
                    label = None
            pairs.append(label or d.name)
        return pairs

    def check_offline_readiness(self) -> dict:
        """
        Feature-level readiness snapshot used by scripts/check_offline.sh (and
        available to status endpoints). Purely filesystem inspection — never
        loads a model, never touches the network.

        Each entry is (bool_ready, human_status_string).
        """
        vietocr_cfg = self.MODEL_DIR / "vietocr" / "config.yml"
        vietocr_wts = (Path(self.VIETOCR_WEIGHTS) if self.VIETOCR_WEIGHTS
                       else self.MODEL_DIR / "vietocr" / f"{self.VIETOCR_CONFIG}.pth")

        chat_primary  = self._has_hf_model(self.CHAT_MODEL)
        chat_fallback = self._has_hf_model(self.FALLBACK_CHAT_MODEL)
        rewrite       = self._has_hf_model(self.QWEN_MODEL)
        phobert       = self._has_hf_model(self.PHOBERT_MODEL)
        sbert_id      = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        embeddings    = self._has_hf_model(sbert_id)
        argos_pairs   = self._argos_installed_pairs()
        argos         = bool(argos_pairs)
        # GLM layout model: PROJECT-LOCAL cache (same hub as every other model —
        # glm_adapter.py exports it to the glmocr child). A copy that exists only
        # in the default ~/.cache/huggingface (primed by an older setup_glm.sh)
        # is flagged for re-priming, not counted as project-local.
        glm_layout      = (Path(self.GLM_LAYOUT_MODEL_DIR).is_dir()
                           or self._has_hf_model(self.GLM_LAYOUT_MODEL_DIR))
        glm_global_only = (not glm_layout
                           and self._has_hf_model(self.GLM_LAYOUT_MODEL_DIR,
                                                  include_default_cache=True))
        # GLM MLX server model (the model mlx_vlm.server itself loads — distinct
        # from the layout detector above). Same project-local-cache policy.
        glm_mlx             = self._has_hf_model(self.GLM_MLX_MODEL)
        glm_mlx_global_only = (not glm_mlx
                               and self._has_hf_model(self.GLM_MLX_MODEL,
                                                      include_default_cache=True))

        setup = "run scripts/setup_offline.sh (online)"
        vcfg_ok, vcfg_why = validate_vietocr_config(vietocr_cfg)
        return {
            "vietocr_config": (vcfg_ok,
                               str(vietocr_cfg) + ("" if vcfg_ok else f"  ← {vcfg_why} ({setup})")),
            "vietocr_weights": (vietocr_wts.exists(),
                                str(vietocr_wts) + ("" if vietocr_wts.exists() else f"  ← MISSING ({setup})")),
            "chat_primary":  (chat_primary,  self.CHAT_MODEL          + ("" if chat_primary  else f"  ← MISSING ({setup})")),
            "chat_fallback": (chat_fallback, self.FALLBACK_CHAT_MODEL + ("" if chat_fallback else f"  ← MISSING ({setup})")),
            "ai_rewrite":    (rewrite,       self.QWEN_MODEL          + ("" if rewrite       else f"  ← MISSING ({setup})")),
            "phobert":       (phobert,       self.PHOBERT_MODEL       + ("" if phobert       else "  ← MISSING (extractive TF-IDF fallback still works)")),
            "embeddings":    (embeddings,    sbert_id                 + ("" if embeddings    else "  ← MISSING (char-hash retrieval fallback still works)")),
            "argos":         (argos,         (f"{len(argos_pairs)} package(s): {', '.join(argos_pairs)}" if argos else f"no packages  ← MISSING ({setup}); online Google translate still works")),
            "glm_layout_model": (glm_layout, str(self.GLM_LAYOUT_MODEL_DIR) + (
                "" if glm_layout
                else "  ← Found in global cache but missing from project-local cache. "
                     "Run scripts/setup_glm.sh --precache-layout." if glm_global_only
                else "  ← not cached (scripts/setup_glm.sh --precache-layout, online)")),
            "glm_mlx_model": (glm_mlx, str(self.GLM_MLX_MODEL) + (
                "" if glm_mlx
                else "  ← Found in global cache but missing from project-local cache. "
                     "Run scripts/setup_glm.sh --precache-mlx." if glm_mlx_global_only
                else "  ← not cached (scripts/setup_glm.sh --precache-mlx, online; "
                     "the first server start also downloads it project-locally)")),
        }

    def offline_readiness_report(self) -> str:
        """Human-readable feature readiness matrix (used by check_offline.sh)."""
        r = self.check_offline_readiness()
        mark = lambda ok: ("✅" if ok else "❌")
        rows = [
            ("VietOCR config.yml",   r["vietocr_config"]),
            ("VietOCR weights",      r["vietocr_weights"]),
        ]
        # Local LLM rows. Policy: Qwen2.5-1.5B-Instruct is the single default for
        # chat + rewrite + agent. When the model ids are identical (the default),
        # collapse them into ONE row so the report isn't three redundant lines and
        # never implies a separate/required larger model.
        _llm_ids = {self.CHAT_MODEL, self.FALLBACK_CHAT_MODEL, self.QWEN_MODEL}
        if len(_llm_ids) == 1:
            rows.append(("Local LLM (chat/rewrite/agent)", r["ai_rewrite"]))
        else:
            rows += [
                ("Chat model (primary)", r["chat_primary"]),
                ("Chat model (fallback)",r["chat_fallback"]),
                ("AI Rewrite (Qwen)",    r["ai_rewrite"]),
            ]
        rows += [
            ("PhoBERT summarize",    r["phobert"]),
            ("Embeddings (RAG)",     r["embeddings"]),
            ("Argos offline transl.",r["argos"]),
            ("GLM layout model",     r["glm_layout_model"]),
            ("GLM MLX server model", r["glm_mlx_model"]),
        ]
        # Paddle rows are three-state: ✅ cached in the runtime cache / ⚠️ will
        # download on first OCR run (needs internet once — NOT a failure: OFFLINE=1
        # gates HF/Argos/Stanza, it does not block PaddleX model downloads).
        pcache = self.paddle_cache_status()
        _pmark = lambda hit: ("✅" if hit else "⚠️ ")
        _pmsg = lambda hit: (
            f"cached ({', '.join(hit)})" if hit else
            "not cached — downloads on first OCR run (needs internet once; "
            "air-gapped machines: run tools/warmup_modern_models.py or one online OCR first)"
        )
        lines = [
            "  ── Offline model readiness ──────────────────────",
            f"  Mode       : {'🔒 OFFLINE (local only)' if self.OFFLINE else '🌐 ONLINE (downloads allowed)'}",
            f"  MODEL_DIR  : {self.MODEL_DIR}",
            f"  HF cache   : {self.HF_DIR}",
            f"  Argos dir  : {self.ARGOS_DIR}",
            f"  Paddle dir : {pcache['cache_dir']}",
            f"  {_pmark(pcache['det'])} Paddle det : {_pmsg(pcache['det'])}",
            f"  {_pmark(pcache['rec'])} Paddle rec : {_pmsg(pcache['rec'])}",
        ]
        for label, (ok, detail) in rows:
            lines.append(f"  {mark(ok)} {label:<30}: {detail}")
        # Feature usability rollup
        chat_ok = r["chat_primary"][0] or r["chat_fallback"][0]
        vietocr_ok = r["vietocr_config"][0] and r["vietocr_weights"][0]
        lines += [
            "  ── Feature usability now ────────────────────────",
            f"  VietOCR OCR      : {'usable' if vietocr_ok else 'NEEDS setup_offline (config.yml + weights)'}",
            f"  AI Chat          : {'usable' if chat_ok else 'NEEDS setup_offline (Qwen chat model)'}",
            f"  AI Rewrite       : {'usable' if r['ai_rewrite'][0] else 'NEEDS setup_offline (Qwen rewrite model)'}",
            f"  Offline translate: {'usable' if r['argos'][0] else 'online Google only until Argos installed'}",
            f"  GLM OCR layout   : {'config+cache OK (needs MLX server running)' if r['glm_layout_model'][0] else 'NEEDS layout model cache (setup_glm.sh)'}",
            f"  GLM MLX server   : {'model cached project-locally (start: scripts/start_glm.sh -b)' if r['glm_mlx_model'][0] else 'model NOT cached — first start needs internet (or setup_glm.sh --precache-mlx)'}",
        ]
        return "\n".join(lines)


    def summary(self) -> str:
        models = self.check_models()
        mode = "🔒 OFFLINE" if self.OFFLINE else "🌐 ONLINE"
        lines = [
            "=" * 56,
            "  SmartDocs Platform — Configuration",
            "=" * 56,
            f"  Platform   : {self.PLATFORM}",
            f"  Mode       : {mode}",
            f"  BASE_DIR   : {self.BASE_DIR}",
            f"  UPLOAD_DIR : {self.UPLOAD_DIR}",
            f"  DB_PATH    : {self.DB_PATH}",
            f"  MODEL_DIR  : {self.MODEL_DIR}",
            f"  HF cache   : {self.HF_DIR / 'hub'}",
            f"  Argos dir  : {self.ARGOS_DIR}",
            f"  DEVICE     : {self.DEVICE}  (global)",
            f"  OCR_ENGINE : {self.OCR_ENGINE}",
            f"  VIETOCR_CFG: {self.VIETOCR_CONFIG}",
            f"  VIETOCR_WTS: {self.VIETOCR_WEIGHTS or '(library default)'}",
            f"  QWEN_DEVICE: {self.QWEN_DEVICE}  (AI Rewrite)",
            f"  QWEN_MODEL : {self.QWEN_MODEL}",
            f"  CHAT_DEVICE: {self.CHAT_DEVICE}  (AI Chat)",
            f"  CHAT_MODEL : {self.CHAT_MODEL}",
            f"  CHAT_FALLBK: {self.FALLBACK_CHAT_MODEL}",
            "  ── Local Models ─────────────────────────────────",
            f"  Qwen      : {'✅' if models['qwen']     else '❌ MISSING — run scripts/setup_offline.sh'}",
            f"  PhoBERT   : {'✅' if models['phobert']  else '❌ MISSING — run scripts/setup_offline.sh'}",
            f"  Paddle det: {'✅' if models['paddle_det'] else '⚠️  will download on first OCR run'}",
            f"  Paddle rec: {'✅' if models['paddle_rec'] else '⚠️  will download on first OCR run'}",
            f"  VietOCR   : {'✅' if models['vietocr'] else '⚠️  using library default / configure VIETOCR_WEIGHTS'}",
            f"  Argos pkg : {'✅' if models['argos']    else '❌ MISSING — run scripts/setup_offline.sh'}",
            "=" * 56,
        ]
        return "\n".join(lines)


cfg = _Config()

def print_startup_diagnostics():
    """
    Requirement #8: Print detailed system and AI stability diagnostics at startup.
    """
    import torch
    try:
        import psutil
    except ImportError:
        psutil = None
    import os
    
    print("=" * 60)
    print("  SmartDocs Platform — AI Stability Diagnostics")
    print("=" * 60)
    
    # 1. Device Info
    mps_avail = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    cuda_avail = torch.cuda.is_available()
    
    print(f"  MPS Available   : {'✅ Yes' if mps_avail else '❌ No'}")
    print(f"  CUDA Available  : {'✅ Yes' if cuda_avail else '❌ No'}")
    print(f"  Resolved Global Device : {cfg.DEVICE}")
    
    # 2. RAM Usage
    if psutil:
        vm = psutil.virtual_memory()
        proc = psutil.Process(os.getpid())
        print(f"  System RAM      : {vm.total/1e9:.1f} GB total, {vm.available/1e9:.1f} GB free")
        print(f"  Process RSS     : {proc.memory_info().rss/1e6:.1f} MB")
    
    # 3. Model Configs
    print("\n  ── AI Chat Config ──")
    print(f"  Model           : {cfg.CHAT_MODEL}")
    print(f"  Device          : {cfg.CHAT_DEVICE}")
    print(f"  DType           : {cfg.CHAT_DTYPE}")
    
    # Estimate VRAM (rough)
    p_chat = 1.5 if "1.5B" in cfg.CHAT_MODEL else (3.0 if "3B" in cfg.CHAT_MODEL else 1.5)
    bytes_per_p = 2 if cfg.CHAT_DTYPE == torch.float16 or cfg.CHAT_DTYPE == torch.bfloat16 else 4
    est_chat = p_chat * bytes_per_p
    print(f"  Est. VRAM/RAM   : ~{est_chat:.1f} GB")
    
    print("\n  ── AI Rewrite Config ──")
    print(f"  Model           : {cfg.QWEN_MODEL}")
    print(f"  Device          : {cfg.QWEN_DEVICE}")
    print(f"  DType           : {cfg.QWEN_DTYPE}")
    
    p_rew = 1.5 if "1.5B" in cfg.QWEN_MODEL else 3.0
    bytes_per_rew = 2 if cfg.QWEN_DTYPE == torch.float16 or cfg.QWEN_DTYPE == torch.bfloat16 else 4
    est_rew = p_rew * bytes_per_rew
    print(f"  Est. VRAM/RAM   : ~{est_rew:.1f} GB")
    
    if mps_avail and (cfg.CHAT_DEVICE == "mps" or cfg.QWEN_DEVICE == "mps"):
        print("\n  ⚠️  STABILITY NOTICE (MPS):")
        print("  - Generation length is clamped to 128 tokens to avoid NDArray > 2**32 crashes.")
        print("  - KV cache may be disabled for long prompts.")
        print("  - Automatic CPU fallback is active.")
    
    print("=" * 60)
    print()
