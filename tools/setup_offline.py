#!/usr/bin/env python3
"""
SmartDocs Platform — Offline Setup Tool
========================================
Run this script ONCE on a machine with internet access.
It downloads all required models into web_app/models/
so the app can run completely offline afterwards.

Usage (preferred — resolves the main SmartDocs venv automatically):
    scripts/setup_offline.sh

Running it directly works ONLY with the main venv's interpreter
(a bare `python tools/setup_offline.py` often picks the SYSTEM python,
which has no vietocr/PIL/argostranslate — steps then silently skip):
    .venv/bin/python tools/setup_offline.py      # or ../.venv/bin/python …

After this completes, copy the entire project folder
(including models/) to any machine and run:
    bash run_mac.sh     # macOS / Linux
    run_windows.bat     # Windows
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# ── Bootstrap path ────────────────────────────────────────────────────────────
WEB_APP = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(WEB_APP))

# ── Force the PROJECT-LOCAL HF cache BEFORE any HF-dependent import ───────────
# transformers / huggingface_hub / sentence_transformers freeze their cache
# location (HF_HOME / HF_HUB_CACHE / TRANSFORMERS_CACHE) into module constants
# AT IMPORT TIME. The import gate below imports transformers, so these env vars
# must be set FIRST — otherwise every download lands in ~/.cache/huggingface
# while the app (which imports config before transformers) loads from
# <repo>/models/huggingface/hub. That exact mismatch produced "setup says
# downloaded, runtime says missing" on a clean MacBook clone.
# The derivation below MUST stay identical to config._configure_hf_env()
# (verified after `from config import cfg` further down — hard-fails on drift).


def _dotenv_model_dir() -> str:
    """Minimal stdlib read of MODEL_DIR from <repo>/.env (config uses python-dotenv,
    but that may not be importable yet — and nothing HF-ish may be imported here)."""
    try:
        for line in (WEB_APP / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if line.startswith("MODEL_DIR="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


_model_dir_raw = os.environ.get("MODEL_DIR", "") or _dotenv_model_dir()
MODELS_DIR = Path(_model_dir_raw).resolve() if _model_dir_raw else (WEB_APP / "models")
HF_HOME_DIR = MODELS_DIR / "huggingface"
HF_HUB = HF_HOME_DIR / "hub"
HF_HUB.mkdir(parents=True, exist_ok=True)
os.environ["HF_HOME"]            = str(HF_HOME_DIR)
os.environ["HF_HUB_CACHE"]       = str(HF_HUB)
os.environ["TRANSFORMERS_CACHE"] = str(HF_HUB)
# sentence-transformers>=2.3 stores models in the HF hub cache above; an
# inherited SENTENCE_TRANSFORMERS_HOME would move them OUT of it.
os.environ.pop("SENTENCE_TRANSFORMERS_HOME", None)
# This is a download run — inherited offline flags must not block it. (config
# sets them again when OFFLINE=1; they are popped once more after config import.)
os.environ.pop("HF_HUB_OFFLINE", None)
os.environ.pop("TRANSFORMERS_OFFLINE", None)

# Default global HF cache — NEVER downloaded to or validated against; inspected
# only to (a) report models stranded there and (b) migrate them locally.
GLOBAL_HUB = Path.home() / ".cache" / "huggingface" / "hub"


def _project_model_dir(model_id: str) -> Path:
    return HF_HUB / ("models--" + model_id.replace("/", "--"))


def _global_model_dir(model_id: str) -> Path:
    return GLOBAL_HUB / ("models--" + model_id.replace("/", "--"))

print()
print("=" * 60)
print("  SmartDocs Platform — Offline Model Setup")
print("=" * 60)

# ── Interpreter diagnostics (BEFORE any app import) ───────────────────────────
# The single most common failure mode of this script is running it with the
# WRONG python (system interpreter instead of the main SmartDocs venv): the
# pure-download steps succeed but VietOCR config.yml / Argos / embeddings are
# silently skipped with "No module named …". Surface that immediately.
import platform


def _import_ok(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def _expected_venv_dirs():
    """The venv locations scripts/lib.sh::venv_python resolves, in order."""
    import os as _os
    dirs = []
    sp = _os.environ.get("SMARTDOCS_PYTHON", "").strip()
    if sp:
        # <venv>/bin/python → <venv>   (also handles <venv>/Scripts/python.exe)
        dirs.append(Path(sp).parent.parent)
    dirs.append(WEB_APP / ".venv")
    dirs.append(WEB_APP.parent / ".venv")
    return [d for d in dirs if d.is_dir()]


# The full runtime stack this setup needs BEFORE it downloads anything.
# All of these are provided by requirements.txt in the main venv.
_REQUIRED_IMPORTS = (
    "flask", "PIL", "yaml", "torch", "transformers",
    "vietocr", "argostranslate", "sentence_transformers",
)
_IMPORT_CHECKS = {mod: _import_ok(mod) for mod in _REQUIRED_IMPORTS}

print(f"\n  Python     : {sys.executable}")
print(f"  Version    : {platform.python_version()}")
for _mod, _okflag in _IMPORT_CHECKS.items():
    print(f"  import {_mod:<22}: {'OK' if _okflag else '❌ MISSING'}")

# HARD GATE 1 — Python version. paddlepaddle>=3.0.0 / Pillow==10.2.0 publish no
# wheels for 3.12+, so requirements.txt cannot even install there: every later
# step would fail with misleading per-model errors. Verified: 3.10 (3.11 tolerated).
if not (sys.version_info[:2] == (3, 10) or sys.version_info[:2] == (3, 11)):
    print()
    print("  ❌ UNSUPPORTED Python %s for the main SmartDocs venv." % platform.python_version())
    print("     Required: Python 3.10 (3.11 tolerated). 3.12/3.13/3.14 cannot")
    print("     install the dependency stack (paddlepaddle, Pillow 10.2.0).")
    print("     Recreate the venv:  scripts/setup.sh --reset-venv")
    print("     Then run:           scripts/setup_offline.sh")
    sys.exit(2)
if sys.version_info[:2] == (3, 11):
    print("  ⚠️  Python 3.11 is tolerated but not fully verified — 3.10 is the verified version.")

# In a venv, sys.prefix IS the venv directory (don't compare executables —
# venv pythons are symlinks, so realpath collapses to the base interpreter).
_expected = _expected_venv_dirs()
_in_expected_venv = any(
    Path(sys.prefix).resolve() == d.resolve() for d in _expected
)
if _expected and not _in_expected_venv:
    print()
    print("  " + "!" * 56)
    print("  ⚠️  You may be using the wrong Python. Use scripts/setup_offline.sh.")
    print("     It resolves the main SmartDocs venv automatically (same one")
    print("     scripts/check.sh uses).")
    print(f"     Expected venv: {_expected[0]}")
    print("  " + "!" * 56)

# HARD GATE 2 — required imports. Downloading models into an incomplete venv
# only produces a cascade of per-model 'No module named …' failures.
_missing = [m for m, okflag in _IMPORT_CHECKS.items() if not okflag]
if _missing:
    print()
    print("  ❌ Main venv is incomplete (missing: %s)." % ", ".join(_missing))
    print("     Re-run scripts/setup.sh with Python 3.10, then scripts/setup_offline.sh.")
    print("     No models were downloaded.")
    sys.exit(2)

# ── Load config (re-derives + re-asserts the same HF env vars) ────────────────
from config import cfg

ARGOS_DIR = cfg.ARGOS_DIR

# The early bootstrap above and config._configure_hf_env() derive the cache from
# MODEL_DIR independently — if they ever disagree, downloads and runtime would
# split across two caches again. Refuse to continue on drift.
if cfg.MODEL_DIR.resolve() != MODELS_DIR.resolve() or cfg.HF_HUB_DIR.resolve() != HF_HUB.resolve():
    print()
    print("  ❌ INTERNAL CACHE-PATH MISMATCH — refusing to download anything.")
    print(f"     bootstrap MODEL_DIR : {MODELS_DIR}")
    print(f"     config    MODEL_DIR : {cfg.MODEL_DIR}")
    print(f"     bootstrap HF hub    : {HF_HUB}")
    print(f"     config    HF hub    : {cfg.HF_HUB_DIR}")
    print("     Check the MODEL_DIR line in .env (both derivations must match).")
    sys.exit(2)

# config sets HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE when OFFLINE=1 — this is a
# download run, so clear them again.
os.environ.pop("HF_HUB_OFFLINE", None)
os.environ.pop("TRANSFORMERS_OFFLINE", None)

# ── Cache debug: prove which cache the HF libraries ACTUALLY use ──────────────
# huggingface_hub froze its cache constant when the import gate above imported
# transformers. If it is not the project-local hub, the env bootstrap regressed
# (e.g. an HF import crept in before it) — hard-fail rather than download 6 GB
# into the wrong cache.
import huggingface_hub

_effective_hub = Path(huggingface_hub.constants.HF_HUB_CACHE).resolve()
print(f"\n  MODEL_DIR              : {MODELS_DIR}")
print(f"  HF_HOME                : {os.environ['HF_HOME']}")
print(f"  HF_HUB_CACHE           : {os.environ['HF_HUB_CACHE']}")
print(f"  effective hub cache    : {_effective_hub}   (frozen at import time)")
print(f"  cache_dir for downloads: {HF_HUB}")
print(f"  Argos dir              : {ARGOS_DIR}")
if _effective_hub != HF_HUB.resolve():
    print()
    print("  ❌ The HF libraries are using a DIFFERENT cache than the project-local one.")
    print("     An HF-dependent import ran before the env bootstrap — this is a bug in")
    print("     this script. Refusing to download into the wrong cache.")
    sys.exit(2)

# Per-model cache location report (project-local vs stranded-in-global).
_HF_MODEL_IDS = []
for _m in (cfg.QWEN_MODEL, cfg.CHAT_MODEL, cfg.FALLBACK_CHAT_MODEL, cfg.PHOBERT_MODEL,
           "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
    if _m and _m not in _HF_MODEL_IDS:
        _HF_MODEL_IDS.append(_m)
print()
for _m in _HF_MODEL_IDS:
    _proj = _project_model_dir(_m)
    _glob = _global_model_dir(_m)
    if _proj.exists() and cfg._hf_snapshot_complete(_proj):
        _where = "project cache (complete)"
    elif _glob.exists() and cfg._hf_snapshot_complete(_glob):
        _where = "GLOBAL cache only (~/.cache/huggingface) — will migrate, no re-download"
    elif _proj.exists() or _glob.exists():
        _where = "partial/incomplete cache — will download"
    else:
        _where = "not cached — will download"
    print(f"  {_m:<62}: {_where}")


def _ensure_project_cached(model_id: str) -> bool:
    """Make sure ``model_id`` is COMPLETE in the project-local hub cache.

    Priority (never re-downloads what already exists somewhere usable):
      1. already complete in models/huggingface/hub/  → nothing to do
      2. complete in the GLOBAL ~/.cache/huggingface  → COPY the whole
         models--* tree (snapshots/blobs/refs preserved; HF blob symlinks are
         relative, so ``copytree(symlinks=True)`` keeps them valid)
      3. otherwise                                    → caller downloads from HF

    Returns True when the model is now complete locally (caller can and should
    load with local_files_only=True), False when a network download is needed.
    """
    proj = _project_model_dir(model_id)
    # Hub-dir-specific completeness (config.json + a weight file resolve). NOT
    # cfg._has_hf_model(), which also accepts the legacy flat layout — the caller
    # loads with cache_dir=<hub>, so only the hub copy counts here.
    if proj.exists() and cfg._hf_snapshot_complete(proj):
        return True
    glob_dir = _global_model_dir(model_id)
    if glob_dir.exists() and cfg._hf_snapshot_complete(glob_dir):
        try:
            size_gb = sum(f.stat().st_size for f in glob_dir.rglob("*") if f.is_file()) / (1024**3)
            print(f"  ↻ {model_id}: found complete in global cache — copying "
                  f"{size_gb:.1f} GB into {HF_HUB} (no re-download)…")
            if proj.exists():              # partial/broken local copy → replace it
                shutil.rmtree(proj)
            shutil.copytree(glob_dir, proj, symlinks=True)
            if cfg._hf_snapshot_complete(proj):
                print(f"  ✅ {model_id}: migrated from global cache")
                return True
            print(f"  ⚠️  {model_id}: migrated copy is incomplete — falling back to download")
        except Exception as e:
            print(f"  ⚠️  {model_id}: migration from global cache failed ({e}) — falling back to download")
    return False


errors = []


# ══════════════════════════════════════════════════════════════════════════════
#  1. Qwen local LLM(s) — chat (CHAT_MODEL / FALLBACK_CHAT_MODEL) + AI rewrite
#     (QWEN_MODEL) + agent local provider.
#     DEFAULT LOCAL LLM POLICY: Qwen2.5-1.5B-Instruct is the single default for
#     ALL local LLM features. With the shipped defaults these three ids are the
#     SAME model, so only Qwen2.5-1.5B is downloaded. A larger model (e.g. 3B) is
#     downloaded ONLY if you explicitly set CHAT_MODEL/QWEN_MODEL in .env — it is
#     never fetched by default (unstable on Apple-Silicon MPS for this app).
# ══════════════════════════════════════════════════════════════════════════════
_qwen_models = []
for _m in (cfg.QWEN_MODEL, cfg.CHAT_MODEL, cfg.FALLBACK_CHAT_MODEL):
    if _m and _m not in _qwen_models:
        _qwen_models.append(_m)
if len(_qwen_models) == 1:
    print(f"\n[1/7] Local LLM (default) — {_qwen_models[0]}  [chat + rewrite + agent]")
else:
    print(f"\n[1/7] Local LLMs — {', '.join(_qwen_models)}  (extra model(s) from .env opt-in)")
try:
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM

    for _m in _qwen_models:
        try:
            # Migrate from ~/.cache/huggingface when complete there; download only
            # when missing from BOTH caches. When the project cache is complete,
            # load with local_files_only=True — pure offline, no revision check.
            _local = _ensure_project_cached(_m)
            print(f"  {'✓ verifying local copy' if _local else '↓ downloading'} {_m} — tokenizer…")
            AutoTokenizer.from_pretrained(_m, cache_dir=str(HF_HUB), local_files_only=_local)
            if not _local:
                print(f"  ↓ {_m} — weights (1.5B≈3 GB / larger models bigger, please wait)…")
            AutoModelForCausalLM.from_pretrained(_m, cache_dir=str(HF_HUB),
                                                 local_files_only=_local,
                                                 torch_dtype=torch.float32)
            print(f"  ✅ {_m} ready in {HF_HUB}")
        except Exception as e:
            print(f"  ❌ {_m} failed: {e}")
            errors.append(f"Qwen {_m}: {e}")
except ImportError as e:
    print(f"  ⚠️  Skipped (missing library): {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  2. PhoBERT (Vietnamese summarization)
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n[2/7] PhoBERT — {cfg.PHOBERT_MODEL}")
try:
    from transformers import AutoTokenizer, AutoModel

    _local = _ensure_project_cached(cfg.PHOBERT_MODEL)
    print(f"  {'Verifying local' if _local else 'Downloading'} tokenizer…")
    AutoTokenizer.from_pretrained(cfg.PHOBERT_MODEL, cache_dir=str(HF_HUB), local_files_only=_local)

    print(f"  {'Verifying local' if _local else 'Downloading'} model weights (~400 MB)…")
    AutoModel.from_pretrained(cfg.PHOBERT_MODEL, cache_dir=str(HF_HUB), local_files_only=_local)

    print(f"  ✅ PhoBERT ready in {HF_HUB}")
except ImportError as e:
    print(f"  ⚠️  Skipped (missing library): {e}")
except Exception as e:
    print(f"  ❌ Failed: {e}")
    errors.append(f"PhoBERT: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  3. sentence-transformers (semantic embeddings for document chat / RAG)
# ══════════════════════════════════════════════════════════════════════════════
# Without this, AI Chat retrieval falls back to char-n-gram hashing (works, but
# can't match paraphrases). Caching it here enables real semantic retrieval offline.
# Keep in sync with EmbeddingEngine.SBERT_MODEL in services/chat_service.py.
_SBERT_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
print(f"\n[3/7] Embeddings (optional; hashing fallback if skipped) — {_SBERT_ID}")
try:
    from sentence_transformers import SentenceTransformer

    _local = _ensure_project_cached(_SBERT_ID)
    print(f"  {'Verifying local' if _local else 'Downloading'} sentence-transformers model (~470 MB)…")
    try:
        SentenceTransformer(_SBERT_ID, cache_folder=str(HF_HUB), local_files_only=_local)
    except TypeError:
        # older sentence-transformers without the local_files_only kwarg
        SentenceTransformer(_SBERT_ID, cache_folder=str(HF_HUB))
    print(f"  ✅ sentence-transformers ready in {HF_HUB} (semantic RAG enabled)")
except ImportError as e:
    print(f"  ⚠️  Skipped (missing library): {e}")
    print("     sentence-transformers IS in requirements.txt — a missing import here")
    print("     usually means the wrong Python. Use scripts/setup_offline.sh.")
except Exception as e:
    print(f"  ❌ Failed: {e}")
    errors.append(f"sentence-transformers: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  4. VietOCR models  (pure download — no torch/paddle; run BEFORE PaddleOCR so a
#     Paddle segfault can never block config.yml/weights generation)
# ══════════════════════════════════════════════════════════════════════════════
print("\n[4/7] VietOCR models")
try:
    import urllib.request
    vietocr_dir = MODELS_DIR / "vietocr"
    vietocr_dir.mkdir(parents=True, exist_ok=True)
    
    # Official URL for vgg_transformer.pth
    url = "https://vocr.vn/data/vietocr/vgg_transformer.pth"
    weight_path = vietocr_dir / "vgg_transformer.pth"
    
    if weight_path.exists():
        print(f"  ✓ {weight_path.name} already downloaded")
    else:
        print(f"  Downloading {weight_path.name} (~160 MB)…")
        urllib.request.urlretrieve(url, str(weight_path))

    # ── Generate models/vietocr/config.yml (via the library's own loader) ─────
    # The adapter (services/ocr_engines/vietocr_adapter.py) loads a LOCAL
    # config.yml on purpose so the RUNTIME never touches the network. Here (setup,
    # online) we build it with vietocr's canonical Cfg.load_config_from_name(),
    # which fetches base.yml + the arch yaml from vocr.vn — the same host the
    # weights come from. NOTE: vietocr 0.3.13 bundles NO yaml files in the wheel,
    # so there is no offline source for this config; it must be fetched here.
    #
    # An EXISTING config.yml is no longer trusted blindly: an empty/invalid file
    # (yaml → None/non-dict, or required keys missing) made the runtime crash with
    # "'NoneType' object is not iterable" (Cfg.load_config_from_file does
    # dict.update(yaml.safe_load(f))). Validate, and regenerate when broken.
    from config import validate_vietocr_config

    config_yml = vietocr_dir / "config.yml"
    cfg_ok, cfg_why = validate_vietocr_config(config_yml)
    if cfg_ok:
        print(f"  ✓ {config_yml.name} already present and valid")
    else:
        if config_yml.exists():
            backup = config_yml.with_suffix(".yml.bak")
            config_yml.replace(backup)
            print(f"  ⚠️  Existing {config_yml.name} is INVALID ({cfg_why}) — backed up to {backup.name}, regenerating")
        try:
            from vietocr.tool.config import Cfg as _VCfg
            arch = cfg.VIETOCR_CONFIG                       # e.g. "vgg_transformer"
            print(f"  ↓ Fetching vietocr '{arch}' config via Cfg.load_config_from_name()…")
            vcfg = _VCfg.load_config_from_name(arch)
            # Only the necessary local/offline overrides — nested fields stay
            # exactly as the library delivered them.
            vcfg["weights"] = str(weight_path)
            vcfg["device"] = cfg.VIETOCR_DEVICE
            if isinstance(vcfg.get("cnn"), dict) and "pretrained" in vcfg["cnn"]:
                vcfg["cnn"]["pretrained"] = False
            if isinstance(vcfg.get("predictor"), dict):
                vcfg["predictor"]["beamsearch"] = False
            vcfg.save(str(config_yml))                       # library-canonical dump
            print(f"  ✅ Wrote {config_yml}")
        except Exception as e:
            print(f"  ⚠️  Could not generate config.yml: {e}")
            if isinstance(e, ImportError):
                print("     vietocr IS in requirements.txt — a missing import here usually")
                print("     means the wrong Python. Use scripts/setup_offline.sh.")
            errors.append(f"VietOCR config.yml: {e}")

    # ── Post-generation validation: reload from disk exactly like the runtime ──
    # 1) structural: parse + required keys non-None + weights file resolves
    # 2) functional: Cfg.load_config_from_file + Predictor(config) — the real
    #    runtime path (loads the .pth once; slow but definitive, setup-time only).
    val_ok, val_why = validate_vietocr_config(config_yml)
    if not val_ok:
        print(f"  ❌ config.yml validation FAILED: {val_why}")
        errors.append(f"VietOCR config.yml invalid after generation: {val_why}")
    elif not weight_path.exists():
        print(f"  ❌ weights missing: {weight_path}")
        errors.append(f"VietOCR weights missing: {weight_path}")
    else:
        try:
            from vietocr.tool.config import Cfg as _VCfg
            from vietocr.tool.predictor import Predictor as _VPredictor
            _rt = _VCfg.load_config_from_file(str(config_yml))
            _rt["device"] = "cpu"                    # validation itself always on CPU
            _rt["predictor"]["beamsearch"] = False
            print("  Validating: instantiating Predictor from the generated config…")
            _VPredictor(_rt)
            print("  ✅ VietOCR config + weights validated (Predictor loads)")
        except Exception as e:
            print(f"  ❌ Predictor validation FAILED: {e}")
            errors.append(f"VietOCR Predictor validation: {e}")

    print("  ✅ VietOCR step finished")
except Exception as e:
    print(f"  ❌ Failed: {e}")
    errors.append(f"VietOCR: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  5. Argos Translate packages  (pure download — also before PaddleOCR)
# ══════════════════════════════════════════════════════════════════════════════
_argos_packages_dir = ARGOS_DIR / "packages"
_argos_packages_dir.mkdir(parents=True, exist_ok=True)
print(f"\n[5/7] Argos Translate offline packages → {_argos_packages_dir}")

# Must set env var BEFORE importing argostranslate (it reads it at import time)
os.environ["ARGOS_PACKAGES_DIR"] = str(_argos_packages_dir)
os.environ["ARGOS_TRANSLATE_PACKAGE_DIR"] = str(_argos_packages_dir)

# en↔vi is the CORE pair (listed first); the rest are best-effort extras. Each pair
# installs independently so one failed/absent package never blocks the others.
ARGOS_PAIRS = [
    ("en", "vi"), ("vi", "en"),
    ("en", "zh"), ("zh", "en"),
    ("en", "ja"), ("ja", "en"),
    ("en", "ko"), ("ko", "en"),
    ("en", "fr"), ("fr", "en"),
    ("en", "de"), ("de", "en"),
    ("en", "es"), ("es", "en"),
]
try:
    import socket
    import argostranslate.settings as _as
    import argostranslate.package

    # Patch runtime state (safety net) — same authoritative-first ordering the
    # runtime (services/translate_service.py) uses, so install + runtime + checks
    # all agree on models/argos/packages.
    _as.data_dir = ARGOS_DIR
    _as.package_data_dir = _argos_packages_dir
    _as.package_dirs = [_argos_packages_dir] + [
        d for d in getattr(_as, "package_dirs", []) if Path(d) != _argos_packages_dir
    ]
    print(f"  Package dir: {_argos_packages_dir}")

    # Fail fast instead of hanging forever on a stalled index/download connection.
    _prev_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(120)

    print("  Fetching package index…")
    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()
    installed = {(p.from_code, p.to_code) for p in argostranslate.package.get_installed_packages()}

    downloaded = 0
    for from_code, to_code in ARGOS_PAIRS:
        if (from_code, to_code) in installed:
            print(f"  ✓ {from_code}→{to_code} already installed")
            continue
        pkg = next((p for p in available if p.from_code == from_code and p.to_code == to_code), None)
        if not pkg:
            print(f"  ⚠️  Package {from_code}→{to_code} not available in index")
            continue
        # Per-package guard: a single download/install failure must not abort the
        # remaining pairs (esp. the core en↔vi pair listed first).
        try:
            print(f"  ↓ Installing {from_code}→{to_code}…")
            argostranslate.package.install_from_path(pkg.download())
            downloaded += 1
        except Exception as e:
            print(f"  ❌ {from_code}→{to_code} failed: {e}")

    socket.setdefaulttimeout(_prev_timeout)

    # Post-install verification through the LIBRARY (not just files on disk) —
    # exactly what the runtime will do. Catches "files written but not loadable".
    final_pairs = sorted(f"{p.from_code}→{p.to_code}"
                         for p in argostranslate.package.get_installed_packages())
    print(f"  ✅ Argos: {downloaded} new package(s); loadable now: "
          f"{', '.join(final_pairs) or 'NONE'}  (dir: {_argos_packages_dir})")
    # Only surface a hard error if the CORE en↔vi pair is not loadable.
    if not {"en→vi", "vi→en"}.issubset(set(final_pairs)):
        errors.append("Argos: core en↔vi pair not loadable after install "
                      "(manual: `argospm install translate-en_vi` / `translate-vi_en`, "
                      f"or drop the .argosmodel into {_argos_packages_dir})")
except ImportError as e:
    print(f"  ⚠️  Skipped (missing library): {e}")
    print("     argostranslate IS in requirements.txt — a missing import here usually")
    print("     means the wrong Python. Use scripts/setup_offline.sh.")
except Exception as e:
    print(f"  ❌ Failed: {e}")
    print(f"     Manual fallback: `argospm install translate-en_vi` and `translate-vi_en`, "
          f"or place .argosmodel files in {_argos_packages_dir}.")
    errors.append(f"Argos: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  6. PaddleOCR — LAST on purpose.
#     This script has already loaded torch/transformers (Qwen/PhoBERT steps), and
#     PaddlePaddle installs a Google-glog FailureSignalHandler that hijacks
#     SIGSEGV/SIGABRT. With torch + paddle sharing one process, that handler can
#     turn a benign worker-thread condition into a FATAL crash while symbolizing a
#     stack (observed in a macOS .ips: libpaddle FailureSignalHandler →
#     SymbolizeAndDemangle). Running Paddle LAST means even a hard crash here leaves
#     the Qwen/PhoBERT/embeddings/VietOCR/Argos assets already on disk. We also call
#     paddle.disable_signal_handler() first so Python handles signals normally.
#     Best-effort; never fatal if the API is unavailable.
# ══════════════════════════════════════════════════════════════════════════════
print("\n[6/7] PaddleOCR models  (downloads on first predict(); run last for stability)")
test_img = MODELS_DIR / "_paddle_setup_test.png"
try:
    from PIL import Image, ImageDraw

    # Create a small test image to force model download
    img = Image.new("RGB", (200, 60), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((10, 20), "SmartDocs test", fill=(0, 0, 0))
    img.save(str(test_img))

    # PaddleOCR 3.x (PaddleX) caches models in
    # <PADDLE_PDX_CACHE_HOME or ~/.paddlex>/official_models/ — NOT in models/ or
    # the HF cache. This prewarm writes into that SAME runtime cache the app uses.
    _pdx = os.environ.get("PADDLE_PDX_CACHE_HOME", str(Path.home() / ".paddlex"))
    print(f"  Runtime model cache: {_pdx}/official_models")
    print("  Initializing PaddleOCR PP-OCRv5 (the Legacy engine + VietOCR detector pipeline)…")
    try:
        import paddle
        paddle.disable_signal_handler()
    except Exception:
        pass
    from paddleocr import PaddleOCR
    # Same pipeline as services/ocr_engines/paddle_adapter.py + vietocr_adapter.py,
    # so the models cached here are exactly the ones the app loads offline.
    ocr = PaddleOCR(ocr_version="PP-OCRv5",
                    use_doc_orientation_classify=False, use_doc_unwarping=False)
    ocr.predict(str(test_img))
    test_img.unlink(missing_ok=True)
    print("  ✅ PaddleOCR (Legacy/VietOCR pipeline) ready")
    print("  ℹ️  PaddleOCR Modern (PP-StructureV3/PP-OCRv6) models are larger and")
    print("     prewarmed separately: python tools/warmup_modern_models.py (online)")
except Exception as e:
    if test_img.exists():
        test_img.unlink(missing_ok=True)
    print(f"  ❌ Failed: {e}")
    errors.append(f"PaddleOCR: {e}")



# ══════════════════════════════════════════════════════════════════════════════
#  7. FINAL VALIDATION — load every HF model with local_files_only=True from the
#     PROJECT-LOCAL cache. This is the exact resolution the offline runtime uses,
#     so "downloaded without error" can never again disagree with "the app can
#     load it" (the global-vs-project cache-mismatch bug). The success banner and
#     the exit code are GATED on the required (Qwen) models passing here.
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n[7/7] Validate: local_files_only=True load from {HF_HUB}")
hf_llm_validated = False
try:
    from transformers import AutoTokenizer as _VTok

    _required_ids = list(_qwen_models)
    _optional_ids = [m for m in (cfg.PHOBERT_MODEL, _SBERT_ID) if m and m not in _required_ids]
    _required_failed = []
    for _m in _required_ids + _optional_ids:
        _is_required = _m in _required_ids
        try:
            _VTok.from_pretrained(_m, cache_dir=str(HF_HUB), local_files_only=True)
            if not (_project_model_dir(_m).exists() and cfg._hf_snapshot_complete(_project_model_dir(_m))):
                raise RuntimeError("tokenizer loads, but config.json/weights do not resolve "
                                   "in the project cache (partial snapshot)")
            print(f"  ✅ {_m} — offline-loadable from project cache")
        except Exception as e:
            if _global_model_dir(_m).exists():
                print(f"  ❌ {_m}: Found in global cache but missing from project-local "
                      f"cache. Re-run setup_offline.sh after fixing cache config.")
            else:
                print(f"  ❌ {_m}: NOT loadable offline from {HF_HUB}: {e}")
            errors.append(f"offline validation {_m}: not loadable from project cache")
            if _is_required:
                _required_failed.append(_m)
    hf_llm_validated = not _required_failed
except Exception as e:
    print(f"  ❌ validation step failed: {e}")
    errors.append(f"offline validation: {e}")

# ══════════════════════════════════════════════════════════════════════════════
#  Summary
# ══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
if errors or not hf_llm_validated:
    print("  ⚠️  Setup completed with errors:")
    for e in errors:
        print(f"     • {e}")
    print()
    if hf_llm_validated:
        print("  The app may still work for features whose models succeeded.")
    else:
        print("  ❌ NOT offline-ready: the local LLM did not validate from the")
        print(f"     project cache ({HF_HUB}).")
        print("     Fix the errors above, then re-run scripts/setup_offline.sh.")
else:
    # Reaching this branch REQUIRES the [7/7] local_files_only validation of the
    # Qwen model(s) from the project-local cache — never claim readiness without it.
    print("  ✅ All models downloaded successfully!")
    print()
    print("  The project is now OFFLINE-READY.")
    print("  Copy the entire folder to another machine and run:")
    print("    bash run_mac.sh      (macOS / Linux)")
    print("    run_windows.bat      (Windows)")
print("=" * 60)
print()

# ── Post-setup readiness snapshot (same source of truth as check_offline.sh) ──
# Verifies what is ACTUALLY on disk now (completeness-checked, not just "downloaded
# without error"), and prints the exact re-run command if a required asset is short.
try:
    import importlib
    import config as _cfgmod
    importlib.reload(_cfgmod)          # pick up files written during this run
    _c = _cfgmod.cfg
    r = _c.check_offline_readiness()
    required = {
        "VietOCR config.yml":            r["vietocr_config"],
        "VietOCR weights":               r["vietocr_weights"],
        "Local LLM (chat/rewrite/agent)":r["ai_rewrite"],
    }
    optional = {
        "Embeddings (RAG, fallback OK)":  r["embeddings"],
        "Argos offline translate":        r["argos"],
        "PhoBERT summarize (fallback OK)":r["phobert"],
    }
    print("  ── Readiness after setup ────────────────────────")
    for label, (okflag, _detail) in required.items():
        print(f"   {'✅' if okflag else '❌'} {label}")
    for label, (okflag, _detail) in optional.items():
        print(f"   {'✅' if okflag else '⚠️ '} {label}")
    missing_required = [k for k, (okflag, _d) in required.items() if not okflag]
    if missing_required:
        print()
        print("  ❗ Required asset(s) still missing: " + ", ".join(missing_required))
        print("     Re-run online:  scripts/setup_offline.sh")
    print()
except Exception as e:
    print(f"  (readiness snapshot skipped: {e})")

# Show disk usage
try:
    total = sum(f.stat().st_size for f in MODELS_DIR.rglob("*") if f.is_file())
    gb = total / (1024**3)
    print(f"  models/ total size: {gb:.1f} GB")
except Exception:
    pass

# Non-zero exit when the REQUIRED local LLM did not validate from the project
# cache (optional-model failures keep exit 0 — their fallbacks still work).
if not hf_llm_validated:
    sys.exit(1)
