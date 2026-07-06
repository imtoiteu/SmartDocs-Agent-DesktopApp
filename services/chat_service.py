"""
SmartDocs Platform — AI Chat Service
======================================
RAG pipeline for document-aware AI chat.

Primary model  : Qwen/Qwen2.5-1.5B-Instruct (cfg.CHAT_MODEL)  — default local LLM
Fallback model : Qwen/Qwen2.5-1.5B-Instruct (cfg.FALLBACK_CHAT_MODEL)
(Both default to the same 1.5B model; larger models like 3B are opt-in via .env.)

Embedding:
  1. sentence-transformers multilingual (paraphrase-multilingual-MiniLM-L12-v2)
  2. TF-IDF cosine similarity (fallback, zero extra deps)

Vector store: FAISS flat-L2 (in-memory, per file_id)
"""

from __future__ import annotations

import logging
import os
import re
import sys, gc, traceback
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Pipeline logger — flush-on-emit, human-readable format ───────────────────
class _FlushHandler(logging.StreamHandler):
    """StreamHandler that flushes after every emit for real-time terminal output."""
    def emit(self, record):
        super().emit(record)
        self.flush()

def _setup_chat_logger() -> logging.Logger:
    lg = logging.getLogger("smartdocs.chat")
    if lg.handlers:          # already configured
        return lg
    lg.setLevel(logging.DEBUG)
    h = _FlushHandler()
    h.setFormatter(logging.Formatter(
        fmt="[%(asctime)s] %(levelname)-5s  %(message)s",
        datefmt="%H:%M:%S",
    ))
    lg.addHandler(h)
    lg.propagate = False     # don't double-print to root logger
    return lg

logger = _setup_chat_logger()

# Latency thresholds — warn if a stage exceeds these (seconds)
_WARN_EMBED_S   = 5.0
_WARN_SEARCH_S  = 2.0
_WARN_PROMPT_S  = 1.0
_WARN_INFER_S   = 60.0   # Qwen 3B on CPU can be slow; warn at 60s

def _t(label: str, t0: float) -> float:
    """Log elapsed time for a stage, return elapsed seconds."""
    elapsed = time.time() - t0
    return elapsed

def _arm_stack_watchdog(after_s: float, tag: str) -> threading.Event:
    """DIAGNOSTIC one-shot watchdog. Returns an Event; call .set() to disarm.

    If not disarmed within `after_s`, dumps EVERY thread's stack to stderr via
    faulthandler. This is the single most decisive probe: it shows whether the
    wedged thread is inside torch (real inference stall) or parked on
    `_chat_gen_lock.acquire` (head-of-line block behind a prior generation).
    Purely observational — does not touch generation or locking.
    """
    import faulthandler
    disarm = threading.Event()

    def _bark():
        if not disarm.wait(after_s):
            logger.error(
                f"[WATCHDOG] {tag}: not finished after {after_s:.0f}s — "
                f"dumping ALL thread stacks ↓↓↓"
            )
            try:
                faulthandler.dump_traceback(all_threads=True)
            except Exception as e:
                logger.error(f"[WATCHDOG] stack dump failed: {e}")

    threading.Thread(target=_bark, name=f"watchdog-{tag}", daemon=True).start()
    return disarm


# ══════════════════════════════════════════════════════════════════════════════
#  CONTENTION PROBE (DIAGNOSTIC)
# ══════════════════════════════════════════════════════════════════════════════
# A/B tests proved the chat slowdown is concurrent CPU contention (NOT memory).
# This probe samples per-thread CPU WHILE generate() runs and attributes it to
# named Python threads (Flask request handlers, auto-index, rag-index-rebuild,
# ai-rewrite, …) versus anonymous native threads (torch/paddle/BLAS workers), so
# we can see exactly what else was burning CPU during a slow generation.
# Toggle with CHAT_CONTENTION_PROBE=0. Sample interval: CHAT_PROBE_SAMPLE_S.

_PROBE_ENABLED  = os.getenv("CHAT_CONTENTION_PROBE", "1") != "0"
try:
    _PROBE_SAMPLE_S = float(os.getenv("CHAT_PROBE_SAMPLE_S") or 2.0)
except (TypeError, ValueError):
    _PROBE_SAMPLE_S = 2.0


def _thread_name_map() -> Dict[int, str]:
    """Map OS-level native thread id → Python thread name (for attribution)."""
    m: Dict[int, str] = {}
    for t in threading.enumerate():
        nid = getattr(t, "native_id", None)
        if nid is not None:
            m[nid] = t.name
    return m


def _log_thread_snapshot(tag: str) -> None:
    """One-shot: log how many Python threads exist and flag known heavy-task
    threads that are alive at generation start (likely contention sources)."""
    names = [t.name for t in threading.enumerate()]
    logger.info(f"[CONTENTION] {tag}: {len(names)} python threads alive")
    # The reliable signal: which logical app operations are in flight right now
    # (OCR, translate, indexing) — these are the native-threaded CPU contenders.
    inflight = activity_registry.snapshot()
    if inflight:
        desc = ", ".join(f"{lbl}(+{age:.1f}s)" for lbl, age in inflight)
        logger.warning(f"[CONTENTION] {tag}: ⚠ concurrent app operations in flight: {desc}")
    else:
        logger.info(f"[CONTENTION] {tag}: no other heavy app operation in flight")


class _ContentionProbe:
    """Samples per-thread CPU during generation. Purely observational.

    On stop, reports: peak process & machine CPU%, load average, the native
    (torch/paddle/BLAS) CPU total (expected to be high — that's our own
    inference), and any NON-generation Python-named thread that consumed CPU
    concurrently (the suspects)."""

    def __init__(self, tag: str, sample_s: float = 2.0):
        self.tag       = tag
        self.sample_s  = sample_s
        self._stop     = threading.Event()
        self._thr      = None
        self._peak_p   = 0.0
        self._peak_m   = 0.0
        self._cpu      = {}    # native_tid -> accumulated cpu-seconds (delta)
        self._names    = {}    # native_tid -> python name (None = native worker)
        self._samples  = 0
        self._ops_seen = {}    # app-operation label -> times observed in flight

    def _run(self):
        try:
            import psutil
            proc = psutil.Process()
            prev = {t.id: t.user_time + t.system_time for t in proc.threads()}
        except Exception as e:
            logger.debug(f"[CONTENTION] probe unavailable: {e}")
            return
        proc.cpu_percent(None)
        psutil.cpu_percent(None)
        while not self._stop.wait(self.sample_s):
            try:
                nm  = _thread_name_map()
                cur = {t.id: t.user_time + t.system_time for t in proc.threads()}
                self._peak_p = max(self._peak_p, proc.cpu_percent(None))
                self._peak_m = max(self._peak_m, psutil.cpu_percent(None))
            except Exception:
                continue
            for tid, tot in cur.items():
                d = tot - prev.get(tid, tot)
                if d > 0:
                    self._cpu[tid]   = self._cpu.get(tid, 0.0) + d
                    self._names[tid] = nm.get(tid)
            for lbl, _age in activity_registry.snapshot():
                self._ops_seen[lbl] = self._ops_seen.get(lbl, 0) + 1
            prev = cur
            self._samples += 1

    def start(self):
        self._thr = threading.Thread(target=self._run, name=f"contention-probe-{self.tag}",
                                     daemon=True)
        self._thr.start()
        return self

    def stop_and_report(self, gen_native_id: int):
        self._stop.set()
        if self._thr:
            self._thr.join(timeout=self.sample_s + 1.0)
        if self._samples == 0:
            logger.info(f"[CONTENTION] {self.tag}: finished in <{self.sample_s:.0f}s — no sample taken")
            return
        native_cpu = 0.0
        named = []   # (cpu_s, label)
        for tid, cpu in self._cpu.items():
            name = self._names.get(tid)
            if name is None:
                native_cpu += cpu
            else:
                label = name + (" (THIS gen thread)" if tid == gen_native_id else "")
                named.append((cpu, label))
        named.sort(reverse=True)
        try:
            import os as _os
            la = ", ".join(f"{x:.2f}" for x in _os.getloadavg())
        except Exception:
            la = "n/a"
        logger.info(
            f"[CONTENTION] {self.tag}: peak_process_CPU={self._peak_p:.0f}%  "
            f"peak_machine_CPU={self._peak_m:.0f}%  loadavg=[{la}]  samples={self._samples}"
        )
        logger.info(
            f"[CONTENTION]   native worker CPU (our torch/paddle/BLAS, expected): {native_cpu:.1f}s"
        )
        # THE KEY SIGNAL: logical app operations seen running during this generation.
        if self._ops_seen:
            ops = ", ".join(f"{lbl}×{n}/{self._samples}" for lbl, n in
                            sorted(self._ops_seen.items(), key=lambda x: -x[1]))
            logger.warning(
                f"[CONTENTION]   ⚠ CONCURRENT app operations during generation "
                f"(label×samples-seen): {ops}"
            )
        else:
            logger.info("[CONTENTION]   no tracked app operation (OCR/translate/index) ran during generation")
        suspects = [(c, n) for c, n in named if "THIS gen thread" not in n and c > 0.05]
        if suspects:
            logger.warning("[CONTENTION]   ⚠ concurrent Python threads burning CPU DURING generation:")
            for c, n in suspects[:8]:
                logger.warning(f"[CONTENTION]       {c:6.2f}s cpu  ←  {n}")
        else:
            logger.info(
                "[CONTENTION]   no non-generation Python thread consumed CPU → any contention is "
                "native (torch/paddle/BLAS oversubscription) or another OS process"
            )


def _mem_info() -> str:
    """Return a short memory usage string (RSS MB) for this process."""
    try:
        import psutil, os
        proc = psutil.Process(os.getpid())
        mb = proc.memory_info().rss / 1024 / 1024
        return f"{mb:.0f}MB RSS"
    except Exception:
        return "mem=n/a"

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import cfg
from services import llm_registry       # B1: share one Qwen copy with AI-Rewrite
from services import activity_registry   # DIAGNOSTIC: track in-flight CPU-heavy ops
from services import cpu_threads         # restore torch threads collapsed by PaddleOCR

# ── Constants ─────────────────────────────────────────────────────────────────
_MPS_MAX_NEW_TOKENS = 128     # Clamp generation on MPS to avoid NDArray > 2**32
_MPS_MAX_PROMPT_LEN = 1024    # Truncate prompt more aggressively on MPS

CHUNK_SIZE    = 400     # characters per chunk
CHUNK_OVERLAP = 80      # overlap between consecutive chunks
TOP_K         = 5       # chunks to retrieve per query
MAX_CTX_CHARS = 3000    # max context injected into LLM prompt
MAX_IN_TOKENS = 2048    # token budget for input
MAX_OUT_TOKENS = 512    # token budget for answer


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


# Hang guards (env-overridable, no .env edit required):
#   • GEN_LOCK_TIMEOUT_S — max time a request waits for the shared generation
#     lock before failing fast with a 503 "busy" instead of hanging forever
#     behind another (possibly wedged) generation.
#   • GEN_MAX_TIME_S — wall-clock backstop passed to model.generate(); stops a
#     runaway/slow generation between tokens so it can't run unbounded.
GEN_LOCK_TIMEOUT_S = _env_float("CHAT_GEN_LOCK_TIMEOUT_S", 25.0)
GEN_MAX_TIME_S     = _env_float("CHAT_GEN_MAX_TIME_S", 180.0)




# ── Chat model singleton state ─────────────────────────────────────────────────
_chat_lock          = threading.Lock()
_chat_model         = None
_chat_tok           = None
_chat_device        = None
_chat_model_name    = None    # which model is actually loaded
_chat_loading       = False
_chat_load_error: Optional[str] = None
_chat_gen_lock      = threading.Lock()

# Cancellation event — set() to interrupt active generation at the next token
_cancel_event       = threading.Event()


# ══════════════════════════════════════════════════════════════════════════════
#  CANCELLATION CRITERIA (HuggingFace StoppingCriteria)
# ══════════════════════════════════════════════════════════════════════════════

class _CancellationCriteria:
    """
    HuggingFace StoppingCriteria that checks _cancel_event on each token.
    Imported lazily inside _run_inference so transformers is not required at module load.

    DIAGNOSTIC: also timestamps every token. transformers invokes this AFTER each
    generated token, so:
      • if it is never called → execution is stuck in the FIRST forward pass
        (model paging/swap) and cancel CANNOT take effect (criteria never runs).
      • inter-token gaps reveal swap thrash; first-token latency reveals warm-up cost.
    """
    def __init__(self):
        self.n = 0
        self.t_entry = time.time()
        self.t_prev  = self.t_entry
        self.t_first = None   # absolute wall-clock time of the first produced token

    def __call__(self, input_ids, scores, **kwargs) -> bool:  # type: ignore[override]
        now = time.time()
        if self.n == 0:
            self.t_first = now
            logger.info(
                f"[LLM]   ⏱ FIRST token produced (+{now - self.t_entry:.1f}s into generate) "
                f"— forward pass is progressing"
            )
        else:
            dt = now - self.t_prev
            if dt > 5.0:
                logger.warning(
                    f"[LLM]   ⚠ token #{self.n} took {dt:.1f}s — likely memory swap/paging"
                )
        self.n += 1
        self.t_prev = now
        return _cancel_event.is_set()


def _extract_cache_device(pkv) -> Optional[str]:
    """DEVICE-TEST helper: return the device of the KV cache's first key tensor.

    Handles both the transformers 5.x DynamicCache (with `.layers` / `.key_cache`)
    and the legacy tuple-of-tuples past_key_values. Returns None if no cache.
    """
    if pkv is None:
        return None
    try:
        # transformers 5.x DynamicCache: list of per-layer cache objects
        layers = getattr(pkv, "layers", None)
        if layers:
            keys = getattr(layers[0], "keys", None)
            if keys is not None:
                return str(keys.device)
        # older DynamicCache exposes parallel key_cache / value_cache lists
        key_cache = getattr(pkv, "key_cache", None)
        if key_cache:
            return str(key_cache[0].device)
        # legacy tuple: ((k, v), (k, v), …)
        if isinstance(pkv, (tuple, list)) and pkv and isinstance(pkv[0], (tuple, list)):
            return str(pkv[0][0].device)
    except Exception as e:
        logger.debug(f"[LLM]   (kv-cache device probe failed: {e})")
    return None


def cancel_generation() -> bool:
    """
    Signal the active generation to stop at the next token.
    Safe to call even when no generation is running.
    Returns True if a generation was in progress.
    """
    was_generating = _chat_gen_lock.locked()
    _cancel_event.set()
    logger.info("[ChatService] cancel_generation() called — generation will stop at next token.")
    return was_generating


# ══════════════════════════════════════════════════════════════════════════════
#  DEVICE / PATH HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _hf_snapshot(model_id: str) -> Optional[Path]:
    """Locate a downloaded HF model snapshot folder (project-local cache).

    Delegates to cfg.hf_snapshot_dir(), which searches the standard hub layout
    (models/huggingface/hub/) first, then the legacy flat layout — the SAME
    resolution setup_offline.py and check_offline.sh use.
    """
    return cfg.hf_snapshot_dir(model_id)


# ══════════════════════════════════════════════════════════════════════════════
#  CHAT MODEL LOADER
# ══════════════════════════════════════════════════════════════════════════════

def _load_chat_model(model_id: str) -> Tuple:
    """Load (or reuse) a single Qwen model. Returns (tok, model, device).

    B1: routed through the shared LLM registry, so when AI-Chat and AI-Rewrite are
    configured with the same (model, device, dtype) only one copy lives in RAM.
    """
    device = cfg.CHAT_DEVICE
    dtype  = cfg.CHAT_DTYPE

    snap = _hf_snapshot(model_id)
    source = str(snap) if snap else model_id
    local_only = snap is not None  # if we found local snapshot, stay offline

    def _loader():
        from transformers import AutoTokenizer, AutoModelForCausalLM
        logger.info(f"════ Loading Chat Model ════")
        logger.info(f"  model   : {model_id}")
        logger.info(f"  device  : {device}  dtype={dtype}")
        logger.info(f"  source  : {source}")
        logger.info(f"  offline : {local_only}")
        t0 = time.time()

        logger.info("  [1/3] Loading tokenizer…")
        tok = AutoTokenizer.from_pretrained(source, local_files_only=local_only)

        logger.info("  [2/3] Loading model weights…")
        # attn_implementation="eager" is critical on MPS:
        # PyTorch's default SDPA kernel on MPS creates a temporary NDArray that can
        # exceed the 4 GB Metal limit (MPSNDArray.mm:788 hard abort). Eager attention
        # uses the manual Q@K^T path which avoids that oversized temporary buffer.
        load_kwargs = {
            "torch_dtype": dtype,
            "device_map": None,
            "local_files_only": local_only,
        }
        if device == "mps":
            load_kwargs["attn_implementation"] = "eager"
            logger.info("  [2/3] MPS detected: using attn_implementation=eager (avoids SDPA buffer crash)")
        mdl = AutoModelForCausalLM.from_pretrained(source, **load_kwargs)

        logger.info(f"  [3/3] Moving model to {device}…")
        mdl = mdl.to(device)
        mdl.eval()

        # ── DEVICE-TEST INSTRUMENTATION: verify full residency ───────────────
        # Scan every parameter so we can prove the model is FULLY on the target
        # device (a partial/sharded load would silently fall back to CPU math).
        dev_counts: Dict[str, int] = {}
        first_param_dtype = None
        for p in mdl.parameters():
            d = str(p.device)
            dev_counts[d] = dev_counts.get(d, 0) + 1
            if first_param_dtype is None:
                first_param_dtype = p.dtype
        on_target = all(d.split(":")[0] == device for d in dev_counts)
        logger.info(
            f"[LLM]   📍 Model device after loading: "
            f"param_devices={dev_counts}  dtype={first_param_dtype}  "
            f"fully_on_{device}={on_target}"
        )
        if not on_target:
            logger.warning(
                f"[LLM]   ⚠ Model is NOT fully on {device} — some params are elsewhere "
                f"({dev_counts}); device test results will be contaminated by CPU math."
            )

        elapsed = round(time.time() - t0, 1)
        logger.info(f"════ Model ready: {model_id}  total={elapsed}s  {_mem_info()} ════")
        return tok, mdl, device

    return llm_registry.load_or_get(model_id, device, dtype, _loader)


def _do_load():
    """Background thread: try primary then fallback model."""
    global _chat_model, _chat_tok, _chat_device, _chat_model_name
    global _chat_loading, _chat_load_error, _chat_gen_lock

    primary  = cfg.CHAT_MODEL
    fallback = cfg.FALLBACK_CHAT_MODEL

    with _chat_lock:
        if _chat_model is not None or _chat_load_error is not None:
            _chat_loading = False
            return

    for model_id in (primary, fallback):
        if not model_id:
            continue
        try:
            tok, mdl, device = _load_chat_model(model_id)
            with _chat_lock:
                _chat_tok        = tok
                _chat_model      = mdl
                _chat_device     = device
                _chat_model_name = model_id
                # B1: share the generation lock for this model key — if AI-Rewrite
                # shares the same weights, generate() calls serialize across services.
                _chat_gen_lock   = llm_registry.generation_lock(model_id, device, cfg.CHAT_DTYPE)
                _chat_loading    = False
            logger.info(f"[ChatService] Active chat model: {model_id}")
            return
        except Exception as e:
            logger.warning(f"[ChatService] Failed to load {model_id}: {e}", exc_info=True)
            logger.warning(f"  → Trying fallback model next…")

    with _chat_lock:
        _chat_load_error = "No chat model could be loaded (primary + fallback both failed)"
        _chat_loading    = False
    logger.error(f"[ChatService] {_chat_load_error}")


def start_loading():
    """Kick off background model load. Safe to call multiple times."""
    global _chat_loading
    with _chat_lock:
        if _chat_model is not None or _chat_loading or _chat_load_error is not None:
            return
        _chat_loading = True
    t = threading.Thread(target=_do_load, name="chat-model-loader", daemon=True)
    t.start()
    logger.info("[ChatService] Background chat model load started.")


def _ensure_chat_loaded(timeout: float = 360.0) -> Tuple:
    """Block until model is ready. Raises RuntimeError on failure/timeout."""
    if not _chat_loading and _chat_model is None and _chat_load_error is None:
        start_loading()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _chat_model is not None:
            return _chat_tok, _chat_model, _chat_device
        if _chat_load_error:
            raise RuntimeError(f"Chat model unavailable: {_chat_load_error}")
        if not _chat_loading:
            raise RuntimeError("Chat model loader stopped unexpectedly")
        time.sleep(0.5)
    raise RuntimeError(f"Chat model still loading after {timeout}s")


def get_chat_status() -> dict:
    return {
        "model_ready":   _chat_model is not None,
        "model_loading": _chat_loading,
        "model_name":    _chat_model_name,
        "model_error":   _chat_load_error,
        "primary_model": cfg.CHAT_MODEL,
        "fallback_model": cfg.FALLBACK_CHAT_MODEL,
        "device":        _chat_device,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  TEXT CHUNKING
# ══════════════════════════════════════════════════════════════════════════════

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping character-level chunks."""
    text   = re.sub(r"\n{3,}", "\n\n", text.strip())
    chunks = []
    start  = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start += size - overlap
    return [c for c in chunks if len(c) > 20]


# ══════════════════════════════════════════════════════════════════════════════
#  EMBEDDING ENGINE  (sentence-transformers → TF-IDF fallback)
# ══════════════════════════════════════════════════════════════════════════════

class EmbeddingEngine:
    """Lazy-loaded embedding engine with automatic fallback."""

    SBERT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self):
        self._sbert     = None
        self._lock      = threading.Lock()
        self._ready     = False
        self._mode      = "none"      # "sbert" | "hashing"
        self._hashing   = None        # stateless fixed-dim fallback vectorizer (A3)

    def _try_load_sbert(self) -> bool:
        try:
            from sentence_transformers import SentenceTransformer
            snap = _hf_snapshot(f"sentence-transformers/{self.SBERT_MODEL}")
            src  = str(snap) if snap else self.SBERT_MODEL
            logger.info(f"[Embed] Loading sentence-transformers: {self.SBERT_MODEL}")
            t0 = time.time()
            self._sbert = SentenceTransformer(src)
            self._mode  = "sbert"
            logger.info(f"[Embed] Ready: sentence-transformers ({time.time()-t0:.1f}s) — multilingual VI+EN")
            return True
        except Exception as e:
            logger.warning(f"[Embed] sentence-transformers unavailable: {e}")
            logger.warning("[Embed] → Falling back to hashing vectorizer (stateless, fixed-dim, lower quality)")
            return False

    def _ensure_ready(self):
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            if not self._try_load_sbert():
                self._mode = "hashing"
            self._ready = True

    def embed(self, texts: List[str], _label: str = "") -> "np.ndarray":
        import numpy as np
        self._ensure_ready()
        n = len(texts)
        t0 = time.time()
        if self._mode == "sbert":
            result = self._sbert.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
            elapsed = time.time() - t0
            logger.debug(f"[Embed] sbert encoded {n} text(s) in {elapsed:.3f}s{' ('+_label+')' if _label else ''}")
            if elapsed > _WARN_EMBED_S:
                logger.warning(f"[Embed] ⚠ Embedding took {elapsed:.1f}s — consider GPU or smaller model")
            return result

        # ── Hashing fallback (A3) ────────────────────────────────────────────────────────
        # A HashingVectorizer is STATELESS and has a FIXED output dimension, so document
        # chunks, queries, and every per-document index always share the same dimension.
        # This replaces the previous per-document TfidfVectorizer.fit(), which gave each
        # file a different vocabulary/dimension and broke multi-document retrieval
        # (`doc_all` / `general`): a single query vector could not be searched against
        # indexes built with differing dimensions.
        #
        # analyzer="char_wb" + 3-5-grams (instead of word tokens): the documents come
        # from OCR and are full of errors ("genecal"→general, "progranmed"→programmed).
        # Word-level hashing needs an EXACT token match, so a correctly-spelled query
        # scores ~0 against the misspelled chunk. Character n-grams share subsequences
        # across those variants, so retrieval survives OCR noise (measured: the OCR-typo
        # query jumped 0.34→0.51). Still stateless + fixed-dim, so A3 holds.
        from sklearn.feature_extraction.text import HashingVectorizer
        if self._hashing is None:
            self._hashing = HashingVectorizer(
                analyzer="char_wb", ngram_range=(3, 5),
                n_features=16384, alternate_sign=False, norm=None,
            )
        logger.debug(f"[Embed] hashing-encoding {n} text(s)…")
        mat = self._hashing.transform(texts).toarray().astype(np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
        elapsed = time.time() - t0
        logger.debug(f"[Embed] hashing done in {elapsed:.3f}s (dim={mat.shape[1]})")
        return mat / norms

    def reset_tfidf(self):
        """Deprecated no-op (A3): the hashing fallback is stateless and fixed-dimension,
        so there is no per-document vocabulary to reset."""
        return

    @property
    def mode(self) -> str:
        return self._mode


_embedding_engine = EmbeddingEngine()


# ══════════════════════════════════════════════════════════════════════════════
#  DOCUMENT INDEX  (FAISS or cosine fallback)
# ══════════════════════════════════════════════════════════════════════════════

class DocumentIndex:
    """In-memory FAISS (or cosine) index for a single document."""

    def __init__(self, chunks: List[str], embeddings: "np.ndarray"):
        import numpy as np
        self.chunks     = chunks
        self.embeddings = embeddings
        self._faiss_idx = None
        self._build_faiss(embeddings)

    def _build_faiss(self, embeddings: "np.ndarray"):
        try:
            import faiss
            dim = embeddings.shape[1]
            idx = faiss.IndexFlatIP(dim)   # inner-product (works with normalized vecs)
            idx.add(embeddings.astype("float32"))
            self._faiss_idx = idx
            logger.debug("[ChatService] FAISS index built.")
        except Exception as e:
            logger.warning(f"[ChatService] FAISS unavailable: {e}. Using cosine fallback.")
            self._faiss_idx = None

    def search(self, query_emb: "np.ndarray", top_k: int = TOP_K) -> List[Tuple[float, str]]:
        import numpy as np
        qv = query_emb.flatten().astype("float32")
        if self._faiss_idx is not None:
            D, I = self._faiss_idx.search(qv.reshape(1, -1), top_k)
            results = [(float(D[0][i]), self.chunks[I[0][i]])
                       for i in range(len(I[0])) if I[0][i] >= 0]
        else:
            scores = self.embeddings @ qv
            top    = np.argsort(scores)[::-1][:top_k]
            results = [(float(scores[i]), self.chunks[i]) for i in top]
        return sorted(results, key=lambda x: x[0], reverse=True)


# ── Index Cache ────────────────────────────────────────────────────────────────
_index_cache: Dict[str, DocumentIndex] = {}   # file_id → DocumentIndex
_cache_lock = threading.Lock()


def index_document(file_id: str, text: str, source_label: str = "") -> int:
    """Chunk + embed + store a document. Returns number of chunks indexed.

    The embedding engine is stateless w.r.t. dimension (SBERT is fixed-dim; the
    hashing fallback is fixed-dim, A3), so every per-document index shares the same
    dimension and multi-document retrieval is safe.
    """
    chunks = chunk_text(text)
    if not chunks:
        return 0
    # DIAGNOSTIC: embedding (numpy/sklearn) is a concurrent CPU op vs generation.
    with activity_registry.track(f"index:{source_label or 'doc'}"):
        embeddings = _embedding_engine.embed(chunks)
    idx = DocumentIndex(chunks, embeddings)
    with _cache_lock:
        _index_cache[file_id] = idx
    logger.info(f"[ChatService] Indexed {len(chunks)} chunks for file_id={file_id} ({source_label})")
    return len(chunks)


def index_document_async(file_id: str, text: str, source_label: str = "") -> None:
    """Index a document in a background daemon thread (F2 — server-side auto-index).

    Used by the OCR / read-text routes so producing text also makes it queryable
    without the client having to re-upload the text to /api/chat/index, and without
    adding embedding latency to the originating request.
    """
    if not file_id or not text or not text.strip():
        return

    def _run():
        try:
            n = index_document(file_id, text, source_label=source_label or "auto-index")
            logger.info(f"[AutoIndex] file_id={file_id} indexed {n} chunk(s)")
        except Exception:
            logger.warning(f"[AutoIndex] failed for file_id={file_id}", exc_info=True)

    threading.Thread(target=_run, name="auto-index", daemon=True).start()


def pick_rebuild_texts(rows) -> List[Tuple[str, str]]:
    """Choose ONE text per document from persisted (file_id, kind, content)
    rows: the canonical 'ocr' artifact wins over plain extracted 'text' (the
    same preference the agent's document scope uses), and empty contents are
    skipped. Pure — unit-testable without a DB. First-seen document order is
    preserved so newer queries can order the rebuild.
    """
    chosen: Dict[str, Tuple[str, str]] = {}     # file_id → (kind, content)
    order: List[str] = []
    for file_id, kind, content in rows:
        if not file_id or kind not in ("ocr", "text"):
            continue
        if not content or not str(content).strip():
            continue
        cur = chosen.get(file_id)
        if cur is None:
            chosen[file_id] = (kind, content)
            order.append(file_id)
        elif cur[0] == "text" and kind == "ocr":
            chosen[file_id] = (kind, content)   # ocr replaces text
    return [(fid, chosen[fid][1]) for fid in order]


def rebuild_index_from_pairs(pairs, _index=None) -> int:
    """Re-index (file_id, text) pairs into the in-memory store, per-document
    best-effort (one bad document never stops the rest). Returns how many
    documents were indexed. ``_index`` overrides the indexer for tests.
    """
    index = _index or index_document
    indexed = 0
    for file_id, text in pairs:
        try:
            if index(file_id, text, source_label="rebuild"):
                indexed += 1
        except Exception:
            logger.warning(f"[Rebuild] failed for file_id={file_id}", exc_info=True)
    return indexed


def rebuild_indexes_from_db(app) -> None:
    """Rebuild the in-memory vector store from persisted text on startup (B4).

    The FAISS index is in-memory and lost on restart. This re-embeds the stored
    'ocr' / 'text' artifacts (A2) in a background daemon thread so previously
    processed documents become queryable again without a manual re-index —
    corpus-wide agent/chat retrieval works after a restart, not just the
    document-scoped path that re-indexes on demand. Tenancy is unaffected:
    the index is keyed by file_id only; ownership is enforced at query time
    (``retrieve_chunks(allowed_file_ids=…)``), exactly as for live indexing.
    """
    def _run():
        try:
            with app.app_context():
                from models import Document, DocumentArtifact
                arts = (DocumentArtifact.query
                        .filter(DocumentArtifact.kind.in_(("ocr", "text")))
                        .all())
                rows = []
                for art in arts:
                    doc = Document.query.get(art.document_id)
                    if doc:
                        rows.append((doc.file_id, art.kind, art.content))
            # One text per document, 'ocr' preferred over 'text' — indexing both
            # would leave whichever happened to come last from the query.
            pairs = pick_rebuild_texts(rows)
            # Embed OUTSIDE the app context — index_document only touches memory.
            indexed = rebuild_index_from_pairs(pairs)
            if pairs:
                logger.info(f"[Rebuild] Re-indexed {indexed}/{len(pairs)} document(s) from DB.")
        except Exception:
            logger.warning("[Rebuild] index rebuild from DB failed", exc_info=True)

    threading.Thread(target=_run, name="rag-index-rebuild", daemon=True).start()


def remove_document(file_id: str):
    with _cache_lock:
        _index_cache.pop(file_id, None)


def is_indexed(file_id: str) -> bool:
    """True if the document's vectors are present in the in-memory RAG index.

    The auto-index after OCR / read-text runs in a background thread
    (``index_document_async``), so a caller that wants to retrieve immediately
    after producing text can poll this to wait out that window. Read-only.
    """
    if not file_id:
        return False
    with _cache_lock:
        return file_id in _index_cache


def retrieve_chunks(
    query: str,
    file_id: Optional[str] = None,
    top_k: int = TOP_K,
    allowed_file_ids: Optional[set] = None,
) -> List[Tuple[float, str, str]]:
    """
    Retrieve top_k relevant chunks.
    Returns list of (score, chunk_text, source_file_id).
    If file_id is given, searches only that document; otherwise all.

    When ``allowed_file_ids`` is provided (a set), an all-documents search is
    restricted to those ids — this is how a caller scopes cross-document
    retrieval to one user's own documents. ``None`` means no restriction
    (e.g. an admin search).
    """
    t0 = time.time()
    logger.info(f"[RAG] Starting retrieval  query_len={len(query)}  file_id={file_id or 'ALL'}  top_k={top_k}")

    if not _index_cache:
        logger.warning("[RAG] Index cache is empty — no documents have been indexed yet")
        return []

    n_docs = len(_index_cache)
    logger.info(f"[RAG] Index cache has {n_docs} document(s)")

    logger.info("[RAG] Embedding query…")
    t_emb = time.time()
    with activity_registry.track("rag-query-embed"):
        query_emb = _embedding_engine.embed([query], _label="query")
    elapsed_emb = time.time() - t_emb
    logger.info(f"[RAG] Query embedded ({elapsed_emb:.3f}s)  engine={_embedding_engine.mode}")
    if elapsed_emb > _WARN_EMBED_S:
        logger.warning(f"[RAG] ⚠ Embedding took {elapsed_emb:.1f}s — BOTTLENECK")

    with _cache_lock:
        if file_id and file_id in _index_cache:
            targets = {file_id: _index_cache[file_id]}
            logger.info(f"[RAG] Searching 1 document index (file_id={file_id})")
        else:
            targets = dict(_index_cache)
            if allowed_file_ids is not None:
                targets = {k: v for k, v in targets.items() if k in allowed_file_ids}
                logger.info(f"[RAG] Scoped to {len(targets)} owned document index(es)")
            else:
                logger.info(f"[RAG] Searching all {len(targets)} document index(es)")

    t_search = time.time()
    all_results: List[Tuple[float, str, str]] = []
    for fid, idx in targets.items():
        for score, chunk in idx.search(query_emb, top_k=top_k):
            all_results.append((score, chunk, fid))

    all_results.sort(key=lambda x: x[0], reverse=True)
    result = all_results[:top_k]

    elapsed_search = time.time() - t_search
    elapsed_total  = time.time() - t0
    logger.info(f"[RAG] Vector search done ({elapsed_search:.3f}s) — found {len(result)} chunks")
    if elapsed_search > _WARN_SEARCH_S:
        logger.warning(f"[RAG] ⚠ Vector search took {elapsed_search:.1f}s — BOTTLENECK")

    if result:
        top_score = result[0][0]
        logger.info(f"[RAG] Top match score={top_score:.3f}  excerpt={result[0][1][:80]!r}")
    else:
        logger.warning("[RAG] No matching chunks found — LLM will run without context")

    logger.info(f"[RAG] Retrieval complete  total={elapsed_total:.3f}s")
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

# Markers inside the final user message. _Q_MARK is the boundary the token-budget
# fitter splits on so it can trim document context while keeping the question.
_CTX_HEADER = "[Document Context]\n"
_Q_MARK     = "\n\n[Question]\n"

# Upper bound on history messages handed to the fitter (bounds its work); the
# token budget — not this count — decides how many actually survive.
_MAX_HISTORY_MESSAGES = 12


def _fit_messages_to_budget(tok, messages, budget):
    """Trim `messages` so the rendered chat prompt fits within `budget` tokens.

    Replaces blind right-truncation (which cut the question/generation tag off the
    END). Priority, most-protected first:
      1. system prompt
      2. the user's question (never dropped)
      3. document context (highest-scoring chunks are first, so trim from the tail)
      4. chat history (drop oldest first)

    Returns (fitted_messages, info_dict).
    """
    sys_msgs   = messages[:1] if messages and messages[0]["role"] == "system" else []
    final_user = messages[-1]
    history    = messages[len(sys_msgs):-1]

    def ntok(msgs):
        s = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        return len(tok(s)["input_ids"])

    info = {"history_total": len(history), "history_kept": len(history),
            "context_trimmed": False, "overflow": False}

    # 1) Make the core (system + question[+context]) fit; protect the question.
    if ntok(sys_msgs + [final_user]) > budget:
        content = final_user["content"]
        if _Q_MARK in content:
            ctx_part, q_part = content.split(_Q_MARK, 1)
            question_tail = _Q_MARK + q_part                      # kept intact
            ctx_ids = tok(ctx_part, add_special_tokens=False)["input_ids"]
            lo, hi, best = 0, len(ctx_ids), ""
            while lo <= hi:                                       # largest context that fits
                mid = (lo + hi) // 2
                cand_ctx = tok.decode(ctx_ids[:mid], skip_special_tokens=True)
                if ntok(sys_msgs + [{"role": "user", "content": cand_ctx + question_tail}]) <= budget:
                    best, lo = cand_ctx, mid + 1
                else:
                    hi = mid - 1
            final_user = {"role": "user", "content": best + question_tail}
            info["context_trimmed"] = True
        # general mode (no context to trim): the question stays whole; the final
        # tokenizer net will clip an extreme question as a last resort.
        info["overflow"] = ntok(sys_msgs + [final_user]) > budget

    # 2) Re-add the most recent history that still fits (oldest dropped first).
    kept = []
    for m in reversed(history):
        if ntok(sys_msgs + [m] + kept + [final_user]) <= budget:
            kept = [m] + kept
        else:
            break
    info["history_kept"] = len(kept)

    return sys_msgs + kept + [final_user], info

def _build_chat_prompt(
    query: str,
    chunks: List[Tuple[float, str, str]],
    mode: str,
    history: List[dict],
    lang: str = "auto",
) -> List[dict]:
    """Build messages list for the Qwen chat template."""

    if mode == "general":
        system = (
            "You are SmartDocs AI, a helpful assistant integrated into a document intelligence platform. "
            "Answer concisely and accurately. For Vietnamese questions, respond in Vietnamese."
        )
        context_block = ""
    else:
        # RAG mode
        ctx_parts = []
        total = 0
        for _, chunk, _ in chunks:
            if total + len(chunk) > MAX_CTX_CHARS:
                break
            ctx_parts.append(chunk)
            total += len(chunk)
        context_block = "\n\n---\n\n".join(ctx_parts)

        system = (
            "You are SmartDocs AI, a document intelligence assistant. "
            "Answer questions based ONLY on the provided document context. "
            "If the answer is not in the context, say so clearly. "
            "For Vietnamese text, respond in Vietnamese. Be concise and accurate."
        )

    messages = [{"role": "system", "content": system}]

    # Inject recent history (bounded); the token-budget fitter trims it further,
    # oldest-first, so the actual count is governed by the token budget.
    for turn in history[-_MAX_HISTORY_MESSAGES:]:
        messages.append({"role": turn["role"], "content": turn["content"]})

    # Build user message. The markers (_CTX_HEADER / _Q_MARK) let the token-budget
    # fitter split context from question and protect the question if it must trim.
    if context_block:
        user_content = f"{_CTX_HEADER}{context_block}{_Q_MARK}{query}"
    else:
        user_content = query

    messages.append({"role": "user", "content": user_content})
    return messages


# ══════════════════════════════════════════════════════════════════════════════
#  INFERENCE
# ══════════════════════════════════════════════════════════════════════════════

def _complete_via_openai_compatible(messages: List[dict]) -> Optional[Tuple[str, str]]:
    """(answer, engine_label) via the configured OpenAI-compatible endpoint, or
    None when no endpoint is configured (P8). The provider abstraction is
    imported lazily and is torch-free; the endpoint is explicitly user-configured
    (vLLM / llama.cpp / LM Studio), so it is available in Local-only mode too.
    """
    from agent.core.provider import get_openai_compatible_provider
    oc = get_openai_compatible_provider()
    if oc is None:
        return None
    answer = oc.complete(messages, max_tokens=MAX_OUT_TOKENS, temperature=0.7)
    return (answer or "").strip(), oc.name


def _run_inference_routed(messages: List[dict]) -> Tuple[str, str, bool]:
    """Route chat inference through the configured LLM provider.

    Model Router first: when the user picked an explicit Chat model in
    Settings → AI models, that model answers — no silent substitution; the
    only fallback is the user-configured fallback model (handled inside the
    gateway). ``auto`` (the default) keeps the exact pre-existing behavior:

    * ``LLM_PROVIDER=openai_compatible`` (+ endpoint configured) → the endpoint
      answers Document QA, no local model needed; the local model stays as a
      fallback when the endpoint errors.
    * Otherwise → the local chat model exactly as before; if it is UNAVAILABLE
      (RuntimeError from load) and an endpoint is configured, the endpoint is
      tried before giving up — the original error is re-raised when it can't
      help, preserving the existing error contract.
    """
    from agent.core import llm_gateway

    route = llm_gateway.resolve("chat")          # RouteError → clear message
    if route.kind == "model":
        # Explicit bundled-local keeps THIS service's local runner (its
        # cancellation + partial-output contract); anything else goes through
        # the gateway-built provider for the routed model.
        if route.entry.provider_type == "bundled_local" and route.fallback is None:
            return _run_inference(messages)
        provider = llm_gateway.provider_for_route(route)
        answer = provider.complete(messages, max_tokens=MAX_OUT_TOKENS,
                                   temperature=0.7)
        return (answer or "").strip(), getattr(provider, "name", "routed"), False

    prefer_oc = cfg.LLM_PROVIDER == "openai_compatible"
    if prefer_oc:
        try:
            res = _complete_via_openai_compatible(messages)
            if res is not None:
                return res[0], res[1], False
            logger.warning("[LLM] LLM_PROVIDER=openai_compatible but no endpoint "
                           "configured — falling back to the local chat model")
        except Exception as e:
            logger.warning(f"[LLM] OpenAI-compatible endpoint failed ({e}) — "
                           "falling back to the local chat model")
    try:
        return _run_inference(messages)
    except RuntimeError:
        if not prefer_oc:
            try:
                res = _complete_via_openai_compatible(messages)
            except Exception as e:
                logger.warning(f"[LLM] OpenAI-compatible fallback failed: {e}")
                res = None
            if res is not None:
                return res[0], res[1], False
        raise


def _run_inference(messages: List[dict], force_cpu: bool = False) -> Tuple[str, str, bool]:
    """Run messages through the chat model.
    Returns (answer, engine_label, was_cancelled).
    If cancelled mid-generation, returns the partial text decoded so far.
    """
    import torch
    import gc
    from transformers import StoppingCriteriaList

    t_total = time.time()

    # ── Stage: Model readiness ─────────────────────────────────────────────
    logger.info("[LLM] Waiting for model to be ready…")
    t_load = time.time()
    try:
        tok, mdl, device = _ensure_chat_loaded()
    except RuntimeError as e:
        logger.error(f"[LLM] ✗ Model unavailable: {e}")
        raise
    logger.info(f"[LLM] Model ready ({time.time()-t_load:.3f}s)  model={_chat_model_name}  device={device}  {_mem_info()}")

    # NOTE: the cancel flag is intentionally NOT cleared here. Clearing it before
    # acquiring the generation lock would let a queued request erase a Stop aimed at
    # the generation currently running. It is cleared below, only after we hold the
    # lock (at which point no other generation can be in progress).

    # ── Stage: Prompt tokenization ─────────────────────────────────────────
    logger.info(f"[LLM] Building prompt from {len(messages)} message(s)…")
    t_tok = time.time()

    safe_max_in = MAX_IN_TOKENS
    if device == "mps":
        safe_max_in = min(MAX_IN_TOKENS, 1024)

    # Token-budget fit BEFORE rendering: protect the question + document context and
    # drop the oldest history first, instead of letting the tokenizer blindly
    # right-truncate (which used to cut the question/generation tag off the end).
    messages, _fit = _fit_messages_to_budget(tok, messages, safe_max_in)
    if _fit["history_kept"] < _fit["history_total"]:
        logger.info(f"[LLM]   ✂ history trimmed to fit budget: "
                    f"kept {_fit['history_kept']}/{_fit['history_total']} turn(s)")
    if _fit["context_trimmed"]:
        logger.info("[LLM]   ✂ document context trimmed to fit budget (question protected)")
    if _fit["overflow"]:
        logger.warning("[LLM]   ⚠ question alone exceeds input budget — will be clipped")

    prompt = tok.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    # truncation=True is now only a defensive net; the fitter already made it fit.
    inputs = tok(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=safe_max_in,
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}
    prompt_len = inputs["input_ids"].shape[1]
    elapsed_tok = time.time() - t_tok
    logger.info(f"[LLM] Prompt tokenized ({elapsed_tok:.3f}s)  input_tokens={prompt_len}  max_new={MAX_OUT_TOKENS}")

    # ── DEVICE-TEST INSTRUMENTATION: input tensor device before generation ───
    _in_devices = {k: str(v.device) for k, v in inputs.items()}
    _model_param_device = str(next(mdl.parameters()).device)
    logger.info(
        f"[LLM]   📍 Input tensor device(s) before generation: {_in_devices}  "
        f"| model param device: {_model_param_device}  "
        f"| match={all(d == _model_param_device for d in _in_devices.values())}"
    )

    cancel_criteria  = _CancellationCriteria()
    stopping_criteria = StoppingCriteriaList([cancel_criteria])

    # ── Stage: LLM inference ───────────────────────────────────────────────
    logger.info(f"[LLM] ▶ Starting Qwen inference on {device}…")
    t_gen = time.time()

    # ── MPS generation safety (chat-specific) ─────────────────────────────
    # use_cache=True on MPS causes PyTorch to allocate KV cache + SDPA temp
    # buffers that can exceed the 4 GB Metal hard limit → hard C++ abort.
    # Setting use_cache=False prevents this while keeping all other features
    # (summary, OCR, translate) completely unaffected.
    target_max_new = MAX_OUT_TOKENS
    use_cache = True
    if device == "mps":
        # DEVICE TEST (2026-06-13): KV cache is intentionally LEFT ENABLED on MPS.
        # The old `use_cache=False` + 128-token clamp was a Qwen-3B-on-MPS crash
        # workaround (MPSNDArray > 2**32). With the 1.5B model that abort does not
        # occur, and disabling the cache would (a) leave nothing to log for "KV
        # cache device" and (b) make MPS recompute the full context every token,
        # invalidating the CPU-vs-MPS speed comparison this test is meant to run.
        logger.info(
            f"[LLM] 🧪 MPS device test: use_cache=True, max_new_tokens={target_max_new} "
            f"(3B no-cache/clamp workaround disabled for 1.5B speed test)"
        )

    # DIAGNOSTIC: is the lock already held by another (possibly wedged) generation?
    _held_before = _chat_gen_lock.locked()
    logger.info(
        f"[LLM]   Acquiring shared generation lock "
        f"(already_held={_held_before}, thread={threading.get_ident()})…"
    )
    if _held_before:
        logger.warning(
            f"[LLM]   ⚠ Generation lock is BUSY — another generation (chat OR ai-rewrite, "
            f"shared B1 lock) is running. This request will wait up to {GEN_LOCK_TIMEOUT_S:.0f}s "
            f"then fail fast with a 'busy' error rather than hang."
        )
    # ── Acquire the shared generation lock with a BOUND ───────────────────
    # Fix: a plain `with _chat_gen_lock:` waits forever, so one wedged/slow
    # generation made every later request (any mode, plus AI-Rewrite, which
    # shares this lock via B1) hang behind it. A bounded acquire fails fast with
    # a clear "busy" error instead of an indefinite hang.
    _t_lock = time.time()
    acquired = _chat_gen_lock.acquire(timeout=GEN_LOCK_TIMEOUT_S)
    if not acquired:
        _wait = time.time() - _t_lock
        logger.error(
            f"[LLM] ✗ Could not acquire generation lock within {GEN_LOCK_TIMEOUT_S:.0f}s "
            f"({_wait:.1f}s waited) — another generation is still running. Failing fast."
        )
        raise RuntimeError(
            "The AI model is busy with another request. Please wait a few seconds and try again."
        )

    _wait = time.time() - _t_lock
    logger.info(
        f"[LLM]   Generation lock acquired after {_wait:.2f}s — "
        f"generating tokens (use_cache={use_cache}, max_time={GEN_MAX_TIME_S:.0f}s)…"
    )
    if _wait > 1.0:
        logger.warning(
            f"[LLM]   ⚠ Waited {_wait:.1f}s for the generation lock "
            f"(serialized behind another generation)."
        )

    # Now that we hold the lock, no other generation can be running, so it is safe
    # to reset the cancel flag for THIS generation without erasing anyone's Stop.
    _cancel_event.clear()

    # ── DEVICE-TEST INSTRUMENTATION: log the KV cache device on the first decode
    # step. A forward hook fires every layer/step; we log once then self-clear.
    _kv_state = {"logged": False}

    def _kv_cache_hook(module, hook_inputs, output):
        if _kv_state["logged"]:
            return
        pkv = getattr(output, "past_key_values", None)
        dev = _extract_cache_device(pkv)
        if dev is not None:
            logger.info(
                f"[LLM]   📍 KV cache device during generation: {dev}  "
                f"(use_cache={use_cache})"
            )
            _kv_state["logged"] = True

    _kv_handle = mdl.register_forward_hook(_kv_cache_hook) if use_cache else None
    if not use_cache:
        logger.info("[LLM]   📍 KV cache device: n/a (use_cache=False)")

    _wd = _arm_stack_watchdog(45.0, "chat-generate")

    # ── DIAGNOSTIC: torch CPU-parallelism state at gen-start ─────────────────
    # Live finding: after PaddleOCR loads, per-generation process CPU drops from
    # ~385% (≈4 cores) to 100% (1 core) with NO concurrent op — i.e. torch's
    # thread pool collapsed (paddle + torch both ship libomp → OpenMP conflict).
    # Log torch's view, and optionally FORCE-restore threads to test the fix:
    #   CHAT_FORCE_TORCH_THREADS=6  → calls torch.set_num_threads(6) each gen.
    import os as _os
    logger.info(
        f"[CONTENTION] gen-start: torch_threads={torch.get_num_threads()} "
        f"interop={torch.get_num_interop_threads()}  "
        f"OMP_NUM_THREADS={_os.environ.get('OMP_NUM_THREADS', 'unset')}  "
        f"MKL_NUM_THREADS={_os.environ.get('MKL_NUM_THREADS', 'unset')}"
    )
    # PERMANENT FIX: PaddleOCR collapses torch's thread pool to 1; restore it to the
    # pre-paddle baseline (or LLM_TORCH_THREADS) before generating. No-op when intact.
    cpu_threads.restore("chat-generate")

    # ── DIAGNOSTIC: contention probe — who else is burning CPU during generate?
    _probe = None
    _gen_native_id = threading.get_native_id()
    if _PROBE_ENABLED:
        _log_thread_snapshot("gen-start")
        _probe = _ContentionProbe("chat-generate", _PROBE_SAMPLE_S).start()

    try:
        with torch.no_grad():
            output_ids = mdl.generate(
                **inputs,
                max_new_tokens=target_max_new,
                max_time=GEN_MAX_TIME_S,   # wall-clock backstop (stops runaway generation)
                temperature=0.7,
                do_sample=True,
                repetition_penalty=1.1,
                pad_token_id=tok.eos_token_id,
                stopping_criteria=stopping_criteria,
                use_cache=use_cache,
            )
    except RuntimeError as e:
        elapsed_gen = time.time() - t_gen
        err_str = str(e)
        logger.error(f"[LLM] ✗ MPS/Inference error after {elapsed_gen:.1f}s: {err_str}")

        # Automatic CPU Fallback if MPS fails (retried while still holding the lock)
        if "MPS" in err_str or "NDArray" in err_str:
            logger.warning("[LLM] 🛡 Detected MPS-specific crash! Falling back to CPU.")
            t_move = time.time()
            mdl.to("cpu")
            logger.info(f"[LLM]   Model moved to CPU ({time.time()-t_move:.2f}s)")

            inputs_cpu = {k: v.to("cpu") for k, v in inputs.items()}
            with torch.no_grad():
                output_ids = mdl.generate(
                    **inputs_cpu,
                    max_new_tokens=MAX_OUT_TOKENS,
                    max_time=GEN_MAX_TIME_S,
                    temperature=0.7,
                    do_sample=True,
                    repetition_penalty=1.1,
                    pad_token_id=tok.eos_token_id,
                    stopping_criteria=stopping_criteria,
                    use_cache=True,
                )
            device = "cpu"
        else:
            raise
    except Exception as e:
        elapsed_gen = time.time() - t_gen
        logger.error(f"[LLM] ✗ generate() raised after {elapsed_gen:.1f}s: {e}", exc_info=True)
        raise
    finally:
        if _probe is not None:
            _probe.stop_and_report(_gen_native_id)   # DIAGNOSTIC: who contended for CPU
        if _kv_handle is not None:
            _kv_handle.remove()    # DEVICE-TEST: detach the KV-cache probe hook
        _chat_gen_lock.release()   # always release the bounded lock
        _wd.set()                  # DIAGNOSTIC: disarm the stack-dump watchdog
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()

    elapsed_gen = time.time() - t_gen
    was_cancelled = _cancel_event.is_set()
    _cancel_event.clear()

    # ── Stage: Decoding ────────────────────────────────────────────────────
    t_dec = time.time()
    new_tokens = output_ids[0][prompt_len:]
    n_new = len(new_tokens)
    answer = tok.decode(new_tokens, skip_special_tokens=True).strip()
    elapsed_dec = time.time() - t_dec

    elapsed_total = time.time() - t_total
    tok_per_sec   = n_new / elapsed_gen if elapsed_gen > 0 else 0

    # ── DEVICE-TEST INSTRUMENTATION: first-token latency + decode throughput ──
    # first-token latency  = time from generate() start to the first produced token
    # decode tok/s         = steady-state speed AFTER the first token (excludes the
    #                        one-time prefill/warm-up so it reflects per-token cost)
    if cancel_criteria.t_first is not None:
        first_tok_latency = cancel_criteria.t_first - t_gen
        decode_secs       = max(elapsed_gen - first_tok_latency, 1e-9)
        decode_tok_per_sec = (n_new - 1) / decode_secs if n_new > 1 else 0.0
    else:
        first_tok_latency = None
        decode_tok_per_sec = 0.0

    _ftl = f"{first_tok_latency:.2f}s" if first_tok_latency is not None else "n/a (no token)"

    if was_cancelled:
        logger.info(f"[LLM] ⏹ Generation CANCELLED after {elapsed_gen:.1f}s  tokens_so_far={n_new}")
        logger.info(f"[LLM]   device={device}  first_token_latency={_ftl}")
    else:
        logger.info(f"[LLM] ✓ Generation complete  device={device}")
        logger.info(f"[LLM]   inference={elapsed_gen:.2f}s  decode={elapsed_dec:.3f}s  total={elapsed_total:.2f}s")
        logger.info(f"[LLM]   ⏱ first_token_latency={_ftl}")
        logger.info(
            f"[LLM]   🚀 output_tokens={n_new}  overall={tok_per_sec:.1f} tok/s  "
            f"decode_only={decode_tok_per_sec:.1f} tok/s"
        )

    engine_label = f"local:{_chat_model_name}:{device}"
    return answer, engine_label, was_cancelled


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def chat(
    query: str,
    file_id: Optional[str] = None,
    mode: str = "doc_current",
    history: Optional[List[dict]] = None,
    allowed_file_ids: Optional[set] = None,
) -> dict:
    """Main chat entry point.

    ``allowed_file_ids`` scopes 'doc_all' retrieval to the caller's own documents
    (None = no restriction, e.g. admin); see retrieve_chunks.
    """
    if history is None:
        history = []

    t_pipeline = time.time()
    logger.info("━" * 60)
    logger.info(f"[Chat] ▶ NEW REQUEST (mode={mode})")

    # Determine retrieval scope
    search_id = file_id if mode == "doc_current" else None

    # ── Stage: RAG retrieval ───────────────────────────────────────────────
    chunks = []
    if mode != "general":
        t_rag = time.time()
        chunks = retrieve_chunks(query, file_id=search_id, top_k=TOP_K,
                                 allowed_file_ids=allowed_file_ids)
        logger.info(f"[Chat] RAG stage done ({time.time()-t_rag:.3f}s)  chunks={len(chunks)}")

    # ── Stage: Prompt construction ─────────────────────────────────────────
    logger.info("[Chat] Building LLM prompt…")
    t_prompt = time.time()
    messages = _build_chat_prompt(query, chunks, mode, history)
    logger.info(f"[Chat] Prompt built ({time.time()-t_prompt:.3f}s)  messages={len(messages)}")

    # ── Stage: LLM inference (provider-routed, P8) ─────────────────────────
    logger.info("[Chat] Starting LLM inference…")
    t_infer = time.time()
    try:
        answer, engine, cancelled = _run_inference_routed(messages)
    except Exception as e:
        logger.error(f"[Chat] ✗ Inference failed: {e}", exc_info=True)
        raise
    
    # Build source references
    sources = []
    seen = set()
    for score, chunk, fid in chunks:
        key = chunk[:60]
        if key not in seen:
            seen.add(key)
            sources.append({
                "file_id": fid,
                "score":   round(score, 3),
                "excerpt": chunk[:200] + ("…" if len(chunk) > 200 else ""),
            })

    t_total_elapsed = time.time() - t_pipeline
    logger.info(f"[Chat] ◀ RESPONSE READY  total_time={t_total_elapsed:.2f}s")
    logger.info("━" * 60)

    return {
        "answer":         answer,
        "sources":        sources,
        "engine_used":    engine,
        "mode":           mode,
        "chunks_found":   len(chunks),
        "embedding_mode": _embedding_engine.mode,
        "cancelled":      cancelled,
        "elapsed_s":      round(t_total_elapsed, 2),
    }