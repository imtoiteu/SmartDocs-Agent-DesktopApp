"""
SmartDocs Platform — AI Rewrite Service
========================================
Provides abstractive summarization using:
  Primary : Qwen (model from cfg.QWEN_MODEL) on cfg.QWEN_DEVICE
              — auto-selects CUDA → CPU (MPS excluded by default due to
                Apple driver bug: MPSTemporaryNDArray > 2**32 bytes abort)
  Fallback : OpenAI-compatible API (OPENAI_API_KEY) or Groq (GROQ_API_KEY)
  Last resort: raises NoAIAvailableError → caller falls back to extractive

Device notes:
  CUDA : fastest; set QWEN_DEVICE=cuda in .env
  MPS  : Apple Silicon — disabled by default (hard OS abort in Qwen forward).
         Can be enabled with QWEN_DEVICE=mps at your own risk.
  CPU  : default; stable on all platforms (~15–30s/request)
"""

import os
import sys, gc, traceback
import time
import logging
import threading
from pathlib import Path
from typing import List, Optional, Tuple


logger = logging.getLogger(__name__)

# ── Central config ─────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import cfg
from services import llm_registry   # B1: share one Qwen copy with AI-Chat
from services import cpu_threads    # restore torch threads collapsed by PaddleOCR

# ── Constants ───────────────────────────────────────────────────
_MPS_MAX_NEW_TOKENS = 128     # Clamp generation on MPS to avoid NDArray > 2**32
_MPS_MAX_PROMPT_LEN = 1024    # Truncate prompt more aggressively on MPS

QWEN_MODEL       = cfg.QWEN_MODEL
MAX_INPUT_TOKENS = 1024   # tokens for condensed input
MAX_NEW_TOKENS   = 350    # tokens for AI output


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


# Hang guards (shared env vars with chat_service; AI-Rewrite shares the same
# generation lock via B1, so it gets the same fail-fast + wall-clock backstop):
#   • GEN_LOCK_TIMEOUT_S — max wait for the shared generation lock before failing fast.
#   • GEN_MAX_TIME_S     — wall-clock backstop passed to model.generate().
GEN_LOCK_TIMEOUT_S = _env_float("CHAT_GEN_LOCK_TIMEOUT_S", 25.0)
GEN_MAX_TIME_S     = _env_float("CHAT_GEN_MAX_TIME_S", 180.0)
# ── Singleton state ───────────────────────────────────────────────────────────
_qwen_lock       = threading.Lock()
_qwen_model      = None
_qwen_tok        = None
_qwen_device     = None
_qwen_loading    = False        # True while background thread is loading
_qwen_load_error: Optional[str] = None   # set on permanent failure only
_qwen_generate_lock = threading.Lock()


class NoAIAvailableError(Exception):
    """Raised when no AI backend (local or API) is reachable."""
    pass


class AIWarmingUpError(Exception):
    """Raised when model is still loading — caller should show 'warming up'."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
#  DEVICE & DTYPE
# ═══════════════════════════════════════════════════════════════════════════════

def _best_device() -> str:
    """
    Returns the device for Qwen from cfg.QWEN_DEVICE.
    Configured via QWEN_DEVICE env var (default: cpu for safety).
    CUDA is fast; MPS disabled by default (Apple driver hard abort).
    """
    return cfg.QWEN_DEVICE


def _best_dtype():
    """Returns cfg.QWEN_DTYPE (auto-selected based on device)."""
    return cfg.QWEN_DTYPE


def resolve_local_qwen_path() -> Optional[Path]:
    """Resolve the local snapshot path for the CONFIGURED QWEN_MODEL, if present.

    Delegates to cfg.hf_snapshot_dir(): standard hub layout
    (models/huggingface/hub/) first, then the legacy flat layout — the SAME
    resolution chat_service / setup_offline.py / check_offline.sh use.
    """
    return cfg.hf_snapshot_dir(QWEN_MODEL)


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKGROUND PRE-WARMER
# ═══════════════════════════════════════════════════════════════════════════════

def _do_load():
    """Load the model. Called from a background daemon thread."""
    global _qwen_model, _qwen_tok, _qwen_device, _qwen_loading, _qwen_load_error
    global _qwen_generate_lock

    with _qwen_lock:
        if _qwen_model is not None or _qwen_load_error is not None:
            _qwen_loading = False
            return

        local_path = resolve_local_qwen_path()
        logger.info(
            f"[AIRewrite] Loading local Qwen for OCR/AI tasks: model={QWEN_MODEL}, "
            f"path={local_path or 'not-found'}"
        )
        t0 = time.time()
        try:
            device = _best_device()
            dtype  = _best_dtype()
            model_source = str(local_path) if local_path else QWEN_MODEL

            def _loader():
                from transformers import AutoTokenizer, AutoModelForCausalLM
                tok = AutoTokenizer.from_pretrained(model_source, local_files_only=True)
                mdl = AutoModelForCausalLM.from_pretrained(
                    model_source,
                    dtype=dtype,
                    device_map=None,
                    local_files_only=True,    # never attempt a download mid-server
                ).to(device)
                mdl.eval()
                return tok, mdl, device

            # B1: load (or reuse, if AI-Chat already loaded the same model) via the
            # shared registry, and use the per-model shared generation lock so the two
            # services serialize generate() when they share one copy of the weights.
            tok, mdl, device = llm_registry.load_or_get(QWEN_MODEL, device, dtype, _loader)
            _qwen_generate_lock = llm_registry.generation_lock(QWEN_MODEL, device, dtype)

            _qwen_tok    = tok
            _qwen_model  = mdl
            _qwen_device = device
            elapsed = round(time.time() - t0, 1)
            logger.info(
                f"[AIRewrite] Qwen ready on {device} in {elapsed}s "
                f"(source={model_source})"
            )

        except Exception as e:
            _qwen_load_error = str(e)
            logger.error(f"[AIRewrite] Failed to load {QWEN_MODEL}: {e}")
        finally:
            _qwen_loading = False


def prewarm():
    """Start loading the model in a background daemon thread.
    
    Call this once at server startup. Safe to call multiple times.
    """
    global _qwen_loading
    with _qwen_lock:
        if _qwen_model is not None or _qwen_loading or _qwen_load_error is not None:
            return   # already loaded, loading, or permanently failed
        _qwen_loading = True

    t = threading.Thread(target=_do_load, name="qwen-loader", daemon=True)
    t.start()
    logger.info("[AIRewrite] Background model warm-up started.")


def _ensure_loaded(timeout: float = 300.0):
    """Block until the model is loaded, or raise if error/timeout.
    
    timeout: max seconds to wait (default 5min for slow machines).
    """
    global _qwen_loading

    deadline = time.time() + timeout

    # If not even started yet, kick off loading now
    if not _qwen_loading and _qwen_model is None and _qwen_load_error is None:
        prewarm()

    while time.time() < deadline:
        if _qwen_model is not None:
            return _qwen_tok, _qwen_model, _qwen_device
        if _qwen_load_error is not None:
            raise NoAIAvailableError(f"Qwen failed to load: {_qwen_load_error}")
        if not _qwen_loading:
            # Something went wrong — loading stopped without setting model or error
            raise NoAIAvailableError("Qwen loader stopped unexpectedly")
        time.sleep(0.5)

    raise NoAIAvailableError(f"Qwen still loading after {timeout}s timeout")


# ═══════════════════════════════════════════════════════════════════════════════
#  STATUS
# ═══════════════════════════════════════════════════════════════════════════════

def get_ai_status() -> dict:
    """Return current availability of all AI backends."""
    local_ready   = _qwen_model is not None and _qwen_load_error is None
    local_loading = _qwen_loading
    local_path    = resolve_local_qwen_path()
    api_ready     = bool(
        os.environ.get("OPENAI_API_KEY") or
        os.environ.get("GROQ_API_KEY") or
        os.environ.get("OPENROUTER_API_KEY")
    )
    return {
        "local":        local_ready,
        "local_loading": local_loading,
        "local_model":  QWEN_MODEL if (local_ready or local_loading) else None,
        "local_path":   str(local_path) if local_path else None,
        "local_device": _qwen_device if local_ready else None,
        "local_error":  _qwen_load_error,
        "api":          api_ready,
        "ready":        local_ready or api_ready,
        "model_name":   QWEN_MODEL,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  PROMPT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _build_messages(sentences: List[str], style: str, lang: str) -> list:
    """Build chat messages list for the given style and language."""
    content = "\n".join(f"- {s}" for s in sentences)

    if lang == "vietnamese":
        system = (
            "Bạn là trợ lý tóm tắt văn bản chuyên nghiệp. "
            "Hãy viết tóm tắt tự nhiên, mạch lạc bằng tiếng Việt. "
            "Chỉ trả về phần tóm tắt, không giải thích thêm."
        )
        if style == "short":
            user = (
                "Tóm tắt nội dung sau thành 2-3 câu ngắn gọn bằng tiếng Việt:\n\n"
                + content
            )
        elif style == "bullets":
            user = (
                "Liệt kê 5-7 ý chính từ nội dung sau, mỗi ý một dòng bắt đầu bằng •:\n\n"
                + content
            )
        else:  # executive
            user = (
                "Viết tóm tắt điều hành chuyên nghiệp 4-6 câu bằng tiếng Việt từ nội dung sau:\n\n"
                + content
            )
    else:  # english / other
        system = (
            "You are a professional text summarization assistant. "
            "Write concise, natural summaries. "
            "Return only the summary, no explanations or preamble."
        )
        if style == "short":
            user = (
                "Summarize the following in 2-3 concise, natural sentences:\n\n"
                + content
            )
        elif style == "bullets":
            user = (
                "Extract 5-7 key points as bullet points (each line starting with •) "
                "from the following:\n\n" + content
            )
        else:  # executive
            user = (
                "Write a professional executive summary in 4-6 sentences "
                "from the following:\n\n" + content
            )

    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]


# ═══════════════════════════════════════════════════════════════════════════════
#  LOCAL INFERENCE
# ═══════════════════════════════════════════════════════════════════════════════

def _run_local(sentences: List[str], style: str, lang: str) -> Tuple[str, str]:
    """Run Qwen locally on CPU. Returns (text, engine_label)."""
    messages = _build_messages(sentences, style, lang)
    return run_local_messages(messages, max_new_tokens=MAX_NEW_TOKENS)


def run_local_messages(
    messages: list,
    *,
    max_new_tokens: int = MAX_NEW_TOKENS,
    max_input_tokens: int = MAX_INPUT_TOKENS,
    temperature: float = 0.3,
    do_sample: bool = True,
    repetition_penalty: float = 1.1,
) -> Tuple[str, str]:
    """Run a raw chat prompt through the local Qwen model."""
    import torch
    import gc

    tok, mdl, device = _ensure_loaded(timeout=300.0)

    prompt = tok.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    
    # ── MPS pre-generation safety clamp ─────────────────────────────────
    # The MPS crash (MPSNDArray > 2**32) is a HARD C++ abort — Python
    # try/except CANNOT catch it. We MUST clamp BEFORE calling generate().
    safe_max_in = max_input_tokens
    safe_max_new = max_new_tokens
    if device == "mps":
        # Prompt: keep input tensor under ~1024 tokens to avoid attention map overflow
        safe_max_in = min(max_input_tokens, 1024)
        # Output: keep KV-cache growth under the 4GB Metal limit
        # Formula: (input + output) * hidden_dim * layers * 2 * dtype_bytes < 4GB
        # For Qwen2.5-1.5B on mps: ~256 new tokens is the safe ceiling
        safe_max_new = min(max_new_tokens, 256)
        if safe_max_new < max_new_tokens:
            logger.info(
                f"[AIRewrite] 🛡 MPS clamp: max_new_tokens {max_new_tokens} → {safe_max_new} "
                f"(prevents MPSNDArray > 2**32 abort)"
            )

    inputs = tok(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=safe_max_in,
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}
    prompt_tokens = inputs["input_ids"].shape[1]
    logger.info(f"[AIRewrite] prompt_tokens={prompt_tokens}  max_new={safe_max_new}  device={device}")

    # Bounded acquire of the shared generation lock — fail fast instead of hanging
    # behind another (possibly wedged) generation from AI-Chat or AI-Rewrite.
    _t_lock = time.time()
    if not _qwen_generate_lock.acquire(timeout=GEN_LOCK_TIMEOUT_S):
        logger.error(
            f"[AIRewrite] ✗ Could not acquire generation lock within {GEN_LOCK_TIMEOUT_S:.0f}s "
            f"— another generation is still running. Failing fast."
        )
        raise RuntimeError(
            "The AI model is busy with another request. Please wait a few seconds and try again."
        )
    _wait = time.time() - _t_lock
    if _wait > 1.0:
        logger.warning(f"[AIRewrite] ⚠ Waited {_wait:.1f}s for the shared generation lock.")
    try:
        # PERMANENT FIX: PaddleOCR collapses torch's thread pool to 1; restore it to
        # the pre-paddle baseline (or LLM_TORCH_THREADS) before generating. No-op when
        # intact. AI-Rewrite shares the same process-wide torch runtime as AI-Chat.
        cpu_threads.restore("ai-rewrite")
        logger.info(f"[AIRewrite] Starting inference on {device}… (max_time={GEN_MAX_TIME_S:.0f}s)")
        t_gen = time.time()
        try:
            with torch.no_grad():
                output_ids = mdl.generate(
                    **inputs,
                    max_new_tokens=safe_max_new,
                    max_time=GEN_MAX_TIME_S,
                    temperature=temperature,
                    do_sample=do_sample,
                    repetition_penalty=repetition_penalty,
                    pad_token_id=tok.eos_token_id,
                )
            logger.info(f"[AIRewrite] Inference complete in {time.time()-t_gen:.1f}s")
        except RuntimeError as e:
            err_str = str(e)
            logger.error(f"[AIRewrite] ✗ MPS error: {err_str}")
            if "MPS" in err_str or "NDArray" in err_str:
                logger.warning("[AIRewrite] 🛡 Falling back to CPU.")
                t_move = time.time()
                mdl.to("cpu")
                logger.info(f"Model moved to CPU ({time.time()-t_move:.2f}s)")
                inputs_cpu = {k: v.to("cpu") for k, v in inputs.items()}
                with torch.no_grad():
                    output_ids = mdl.generate(
                        **inputs_cpu,
                        max_new_tokens=max_new_tokens,
                        max_time=GEN_MAX_TIME_S,
                        temperature=temperature,
                        do_sample=do_sample,
                        repetition_penalty=repetition_penalty,
                        pad_token_id=tok.eos_token_id,
                    )
                device = "cpu"
            else:
                raise
    finally:
        _qwen_generate_lock.release()
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()

    prompt_len = prompt_tokens
    new_tokens = output_ids[0][prompt_len:]
    result = tok.decode(new_tokens, skip_special_tokens=True).strip()

    return result, f"ai_local:{device}"


# ═══════════════════════════════════════════════════════════════════════════════
#  API FALLBACK
# ═══════════════════════════════════════════════════════════════════════════════

def _run_openai_compatible(sentences: List[str], style: str, lang: str) -> Tuple[str, str]:
    """Run the rewrite through the explicitly configured OpenAI-compatible
    endpoint (OPENAI_COMPATIBLE_* — vLLM / llama.cpp / LM Studio), via the shared
    provider abstraction (P8). Self-hosted by definition, so it is available in
    Local-only mode too. Raises NoAIAvailableError when no endpoint is configured.
    """
    from agent.core.provider import get_openai_compatible_provider  # lazy, torch-free
    oc = get_openai_compatible_provider()
    if oc is None:
        raise NoAIAvailableError("No OpenAI-compatible endpoint configured")
    messages = _build_messages(sentences, style, lang)
    text = oc.complete(messages, max_tokens=MAX_NEW_TOKENS, temperature=0.3)
    return (text or "").strip(), f"ai_api:{oc.name}"


def _run_api(sentences: List[str], style: str, lang: str) -> Tuple[str, str]:
    """Try configured online API. Returns (text, engine_label)."""
    # Privacy (Local only — ALLOW_CLOUD=false): never send text to the implicit
    # cloud APIs. Same error type as "no keys", so the caller's extractive
    # fallback contract is unchanged.
    if not cfg.ALLOW_CLOUD:
        raise NoAIAvailableError(
            "Cloud AI APIs are disabled (ALLOW_CLOUD=false — Local-only mode)")

    messages = _build_messages(sentences, style, lang)

    # ── OpenAI-compatible ───────────────────────────────────────────────────
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        try:
            import openai
            client = openai.OpenAI(api_key=openai_key)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=MAX_NEW_TOKENS,
                temperature=0.3,
            )
            return resp.choices[0].message.content.strip(), "ai_api:openai"
        except Exception as e:
            logger.warning(f"[AIRewrite] OpenAI failed: {e}")

    # ── Groq (fast, free tier) ──────────────────────────────────────────────
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        try:
            import httpx
            resp = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       "llama-3.1-8b-instant",
                    "messages":    messages,
                    "max_tokens":  MAX_NEW_TOKENS,
                    "temperature": 0.3,
                },
                timeout=30,
            )
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip(), "ai_api:groq"
        except Exception as e:
            logger.warning(f"[AIRewrite] Groq failed: {e}")

    # ── OpenRouter ──────────────────────────────────────────────────────────
    or_key = os.environ.get("OPENROUTER_API_KEY")
    if or_key:
        try:
            import httpx
            resp = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {or_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       "meta-llama/llama-3.1-8b-instruct:free",
                    "messages":    messages,
                    "max_tokens":  MAX_NEW_TOKENS,
                    "temperature": 0.3,
                },
                timeout=30,
            )
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip(), "ai_api:openrouter"
        except Exception as e:
            logger.warning(f"[AIRewrite] OpenRouter failed: {e}")

    raise NoAIAvailableError("No API keys configured or all APIs failed")


# ═══════════════════════════════════════════════════════════════════════════════
#  OUTPUT CLEANER
# ═══════════════════════════════════════════════════════════════════════════════

def _clean_output(text: str, style: str) -> str:
    """Normalize AI output — strip preambles and ensure bullet formatting."""
    text = text.strip()

    # Strip common AI preamble phrases
    preambles = [
        "Tóm tắt:", "Summary:", "Here is", "Here's", "Đây là tóm tắt:",
        "Các ý chính:", "Key points:", "Executive Summary:", "Tóm tắt điều hành:",
    ]
    for p in preambles:
        if text.lower().startswith(p.lower()):
            text = text[len(p):].strip()
            break

    if style == "bullets":
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        normalized = []
        for line in lines:
            if line[:1] in ("•", "-", "*", "·", "–"):
                line = "• " + line[1:].strip()
            elif len(line) > 2 and line[0].isdigit() and line[1] in ".)":
                line = "• " + line[2:].strip()
            else:
                line = "• " + line
            normalized.append(line)
        text = "\n".join(normalized)

    return text


# ═══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

def _run_routed_provider(provider, sentences: List[str], style: str,
                         lang: str) -> Tuple[str, str]:
    """Run the rewrite through a Model-Router-selected provider (gateway)."""
    messages = _build_messages(sentences, style, lang)
    text = provider.complete(messages, max_tokens=MAX_NEW_TOKENS, temperature=0.3)
    return (text or "").strip(), f"ai:{getattr(provider, 'name', 'routed')}"


def ai_rewrite(
    condensed_sentences: List[str],
    style:  str = "short",
    lang:   str = "english",
    task:   str = "rewrite",
) -> Tuple[str, str]:
    """
    Generate an AI rewritten summary from condensed key sentences.

    Args:
        condensed_sentences: Key sentences from the extractive engine.
        style:  "short" | "bullets" | "executive"
        lang:   "english" | "vietnamese"
        task:   Model-Router task this call serves ("rewrite", or "summarize"
                when invoked by the summary pipeline) — each can have its own
                model in Settings → AI models.

    Returns:
        (summary_text, engine_used)
        engine_used: "ai_local:cpu", "ai_api:openai", "ai_api:groq" …

    Raises:
        NoAIAvailableError — no backend available (caller falls back to extractive)
    """
    if not condensed_sentences:
        raise NoAIAvailableError("No sentences provided to AI rewrite")

    # Model Router first: an explicit model choice is honored as-is (its only
    # fallback is the user-configured fallback model, applied INSIDE the
    # gateway provider) — no silent hopping across local/self-hosted/cloud.
    from agent.core import llm_gateway
    route = llm_gateway.resolve(task if task in llm_gateway.TASKS else "rewrite")
    if route.kind == "model":
        if route.entry.provider_type == "bundled_local" and route.fallback is None:
            result, engine = _run_local(condensed_sentences, style, lang)
        else:
            try:
                provider = llm_gateway.provider_for_route(route)
                result, engine = _run_routed_provider(
                    provider, condensed_sentences, style, lang)
            except llm_gateway.RouteError:
                raise
            except Exception as e:
                logger.error(f"[AIRewrite] routed model failed: {e}")
                raise NoAIAvailableError(
                    f"The configured {route.task} model failed: {e}") from e
        result = _clean_output(result, style)
        if not result:
            raise NoAIAvailableError("The configured model returned no text")
        return result, engine

    # Legacy backend order ("auto", P8): the local model first by default;
    # when the platform provider is the OpenAI-compatible endpoint
    # (LLM_PROVIDER=openai_compatible) that endpoint comes FIRST so a
    # cloud-only install needs no local model. The implicit cloud APIs
    # (_run_api) stay last and are ALLOW_CLOUD-gated.
    if cfg.LLM_PROVIDER == "openai_compatible":
        backends = (_run_openai_compatible, _run_local, _run_api)
    else:
        backends = (_run_local, _run_openai_compatible, _run_api)

    for backend in backends:
        try:
            result, engine = backend(condensed_sentences, style, lang)
            result = _clean_output(result, style)
            if result:
                return result, engine
        except NoAIAvailableError:
            pass   # backend not available — try the next one
        except Exception as e:
            logger.error(f"[AIRewrite] {backend.__name__} error: {e}")

    raise NoAIAvailableError("All AI backends failed or unavailable")


# ── Auto-prewarm when imported by the server ─────────────────────────────────
# This starts loading the model in the background immediately on first import,
# so it's ready by the time the user clicks AI Rewrite.
prewarm()