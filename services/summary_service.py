"""
SmartDocs Platform — Dual-Engine Summarization + AI Rewrite
============================================================
Fast Engine  : TF-IDF + sparse TextRank + MMR  (English / short texts)
Smart Engine : PhoBERT sentence embeddings + cosine MMR  (Vietnamese)
AI Rewrite   : Qwen2.5-1.5B on MPS → abstractive natural summary

Language routing (engine="auto"):
  "vietnamese" → SmartEngine (PhoBERT)
  "english"    → FastEngine  (TextRank)

API contract:
  summarize(text, mode, engine, summary_mode)
  → {summary, mode, sentences, elapsed_ms, engine_used, summary_mode, lang}
"""

import time
import math
import re
import sys
import hashlib
import logging
import threading
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ── Central config ─────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import cfg

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_INPUT_CHARS = 60_000          # hard limit; longer text is truncated
PHOBERT_MODEL   = cfg.PHOBERT_MODEL
PHOBERT_BATCH   = 8               # sentences per inference batch (RAM-safe)
PHOBERT_DEVICE  = cfg.PHOBERT_DEVICE   # auto: MPS → CUDA → CPU
_phobert_lock   = threading.Lock()
_phobert_model  = None
_phobert_tok    = None
_underthesea_ok = None            # None = unchecked, True/False after first call


# ═══════════════════════════════════════════════════════════════════════════════
#  SHARED UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def _text_fingerprint(text: str) -> str:
    """Stable short hash of the first 500 chars for caching."""
    return hashlib.md5(text[:500].encode("utf-8", errors="ignore")).hexdigest()


@lru_cache(maxsize=512)
def _detect_language_cached(fingerprint: str, sample: str) -> str:
    """Cache language detection by text fingerprint."""
    try:
        from langdetect import detect
        code = detect(sample)
        return "vietnamese" if code == "vi" else "english"
    except Exception:
        return "english"


def detect_language(text: str) -> str:
    fp  = _text_fingerprint(text)
    return _detect_language_cached(fp, text[:500])


def clean_ocr_text(text: str, lang: str = "english") -> str:
    """Comprehensive OCR artifact cleaner."""
    # Normalize unicode (NFC)
    text = unicodedata.normalize("NFC", text)
    # Collapse multiple spaces / tabs
    text = re.sub(r"[ \t]+", " ", text)
    # Remove page number lines like "— 12 —" or "Page 3"
    text = re.sub(r"(?m)^[\s\-–—]*(?:Page\s*)?\d+[\s\-–—]*$", "", text)
    # Fix duplicate punctuation
    text = re.sub(r"([.,;!?])\1+", r"\1", text)
    # Merge broken lines for English: lowercase/comma then newline then lowercase
    if lang == "english":
        text = re.sub(r"([a-z,])\s*\n\s*([a-z])", r"\1 \2", text)
    # Vietnamese broken line merge (ends with vowel/consonant, continues)
    if lang == "vietnamese":
        text = re.sub(r"([a-zA-ZÀ-ỹ,])\s*\n\s*([a-záàảãạăắặằẳẵâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ])", r"\1 \2", text)
        # Fix common OCR word-merges in Vietnamese (e.g. "kếtquả" → "kết quả")
        # This handles the most frequent merged pairs with diacritics
        text = re.sub(r"([ăâêôơư][a-z])(kh|gh|ng|nh|th|tr|ph|ch|gi|qu)", r"\1 \2", text)
    # Remove excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _check_underthesea() -> bool:
    """Check underthesea availability once and cache the result."""
    global _underthesea_ok
    if _underthesea_ok is None:
        try:
            import underthesea  # noqa: F401
            _underthesea_ok = True
        except ImportError:
            _underthesea_ok = False
            logger.warning(
                "[SmartDocs] underthesea is NOT installed. "
                "Vietnamese sentence tokenization will use NLTK punkt (degraded quality). "
                "Install with: pip install underthesea"
            )
    return _underthesea_ok


def tokenize_sentences(text: str, lang: str) -> List[str]:
    if lang == "vietnamese":
        if _check_underthesea():
            try:
                from underthesea import sent_tokenize
                sents = sent_tokenize(text)
                return [s.strip() for s in sents if s.strip()]
            except Exception as e:
                logger.error(f"[SmartDocs] underthesea sent_tokenize failed: {e}")
        # Explicit degraded-mode fallback
        logger.warning("[SmartDocs] Falling back to NLTK for Vietnamese sentence splitting (degraded).")

    import nltk
    try:
        sents = nltk.sent_tokenize(text)
    except LookupError:
        nltk.download("punkt", quiet=True)
        nltk.download("punkt_tab", quiet=True)
        sents = nltk.sent_tokenize(text)
    return [s.strip() for s in sents if s.strip()]


def tokenize_words_en(sentence: str) -> List[str]:
    import nltk
    try:
        from nltk.corpus import stopwords
        stops = set(stopwords.words("english"))
    except LookupError:
        nltk.download("stopwords", quiet=True)
        from nltk.corpus import stopwords
        stops = set(stopwords.words("english"))
    try:
        tokens = nltk.word_tokenize(sentence)
    except LookupError:
        nltk.download("punkt", quiet=True)
        nltk.download("punkt_tab", quiet=True)
        tokens = nltk.word_tokenize(sentence)
    return [w.lower() for w in tokens if w.isalnum() and w.lower() not in stops]


def tokenize_words_vi(sentence: str) -> List[str]:
    if _check_underthesea():
        try:
            from underthesea import word_tokenize
            return [w.lower() for w in word_tokenize(sentence, format="text").split()]
        except Exception:
            pass
    return sentence.lower().split()


def post_process_sentences(sents: List[str]) -> List[str]:
    """Capitalize and clean up selected sentences before output."""
    result = []
    for s in sents:
        s = s.strip()
        if not s:
            continue
        # Capitalize first letter
        if s and not s[0].isupper():
            s = s[0].upper() + s[1:]
        # Ensure ends with punctuation
        if s and s[-1] not in ".!?…":
            s = s + "."
        result.append(s)
    return result


def _target_count(mode: str, total: int) -> int:
    """Compute target sentence count by mode."""
    if mode == "short":
        n = max(2, math.ceil(total * 0.15))
        n = min(n, 5)
    elif mode == "bullets":
        n = max(4, math.ceil(total * 0.22))
        n = min(n, 10)
    elif mode == "executive":
        n = max(6, math.ceil(total * 0.20))
        n = min(n, 18)
    else:
        n = 3
    return min(n, total)


def _mmr_select(scores: np.ndarray, sim_matrix: np.ndarray,
                target: int, lambda_param: float = 0.65) -> List[int]:
    """
    Maximal Marginal Relevance selection.
    Returns indices in original (chronological) order.
    """
    n = len(scores)
    if n <= target:
        return list(range(n))

    selected: List[int] = []
    remaining = list(range(n))

    # Seed: pick highest-scoring sentence
    first = int(np.argmax(scores))
    selected.append(first)
    remaining.remove(first)

    while len(selected) < target and remaining:
        best_mmr, best_idx = -float("inf"), -1
        for idx in remaining:
            rel = scores[idx]
            max_sim = max(sim_matrix[idx, s] for s in selected)
            mmr = lambda_param * rel - (1 - lambda_param) * max_sim
            if mmr > best_mmr:
                best_mmr, best_idx = mmr, idx
        if best_idx == -1:
            break
        selected.append(best_idx)
        remaining.remove(best_idx)

    selected.sort()
    return selected


# ═══════════════════════════════════════════════════════════════════════════════
#  ENGINE A — FAST (TF-IDF TextRank, English primary)
# ═══════════════════════════════════════════════════════════════════════════════

def _fast_summarize(sentences: List[str], lang: str, target: int) -> List[str]:
    """Improved TF-IDF + sparse TextRank + MMR."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import networkx as nx

    if len(sentences) <= target:
        return sentences

    # Tokenize for TF-IDF
    if lang == "vietnamese":
        tokenized = [" ".join(tokenize_words_vi(s)) for s in sentences]
    else:
        tokenized = [" ".join(tokenize_words_en(s)) for s in sentences]

    # TF-IDF with stop words + bigrams
    try:
        stop = "english" if lang == "english" else None
        vect = TfidfVectorizer(
            stop_words=stop,
            max_df=0.95, min_df=1,
            ngram_range=(1, 2),
            max_features=5000,
        )
        X = vect.fit_transform(tokenized)
        sim_matrix = cosine_similarity(X).astype(np.float32)
        # Sparse: zero out weak similarities to speed up PageRank
        sim_matrix[sim_matrix < 0.05] = 0.0
        np.fill_diagonal(sim_matrix, 0.0)

        G = nx.from_numpy_array(sim_matrix)
        pr = nx.pagerank(G, alpha=0.85, max_iter=200, tol=1e-5)
        textrank_scores = np.array([pr.get(i, 0.0) for i in range(len(sentences))])
    except Exception as e:
        logger.warning(f"[FastEngine] TextRank failed ({e}), using uniform scores.")
        textrank_scores = np.ones(len(sentences))
        sim_matrix = np.zeros((len(sentences), len(sentences)), dtype=np.float32)

    n = len(sentences)
    hybrid = np.zeros(n)
    for i, s in enumerate(sentences):
        score = textrank_scores[i]
        # Positional boost (reduced — not aggressive like before)
        if i < n * 0.15:
            score *= 1.3
        elif i >= n * 0.85:
            score *= 1.2
        # Length filter — expanded range
        wc = len(s.split())
        if wc < 3 or wc > 100:
            score *= 0.4
        hybrid[i] = score

    # Normalize
    mx = np.max(hybrid)
    if mx > 0:
        hybrid /= mx

    # MMR
    selected = _mmr_select(hybrid, sim_matrix, target, lambda_param=0.65)
    return [sentences[i] for i in selected]


# ═══════════════════════════════════════════════════════════════════════════════
#  ENGINE B — SMART (PhoBERT, Vietnamese priority)
# ═══════════════════════════════════════════════════════════════════════════════

def _load_phobert():
    """Lazy singleton — load PhoBERT once, thread-safe."""
    global _phobert_model, _phobert_tok
    with _phobert_lock:
        if _phobert_model is None:
            logger.info(f"[SmartEngine] Loading {PHOBERT_MODEL} on {PHOBERT_DEVICE} (first use)…")
            t0 = time.time()
            try:
                import torch
                from transformers import AutoTokenizer, AutoModel
                _phobert_tok   = AutoTokenizer.from_pretrained(PHOBERT_MODEL)
                _phobert_model = AutoModel.from_pretrained(PHOBERT_MODEL)
                _phobert_model = _phobert_model.to(PHOBERT_DEVICE)
                _phobert_model.eval()
                logger.info(f"[SmartEngine] PhoBERT ready on {PHOBERT_DEVICE} in {time.time()-t0:.1f}s")
            except Exception as e:
                logger.error(f"[SmartEngine] Failed to load PhoBERT: {e}")
                _phobert_model = None
                _phobert_tok   = None
                raise
    return _phobert_tok, _phobert_model


def _embed_sentences(sentences: List[str]) -> np.ndarray:
    """
    Encode sentences with PhoBERT, return L2-normalised embeddings (n × 768).
    Uses mean-pool of last hidden state.
    """
    import torch

    tok, mdl = _load_phobert()
    all_embs = []

    for i in range(0, len(sentences), PHOBERT_BATCH):
        batch = sentences[i : i + PHOBERT_BATCH]
        enc = tok(
            batch,
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors="pt",
        )
        # Move inputs to the same device as the model
        enc = {k: v.to(PHOBERT_DEVICE) for k, v in enc.items()}
        with torch.no_grad():
            out = mdl(**enc)
        # Mean pool over token dimension, mask padding
        mask = enc["attention_mask"].unsqueeze(-1).float()
        emb  = (out.last_hidden_state * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        emb  = emb.cpu().numpy().astype(np.float32)  # always move back to CPU for numpy
        # L2 normalise
        norms = np.linalg.norm(emb, axis=1, keepdims=True).clip(min=1e-9)
        all_embs.append(emb / norms)

    return np.vstack(all_embs)          # (n, 768)


def _smart_summarize(sentences: List[str], target: int) -> List[str]:
    """PhoBERT embedding-based sentence selection + embedding-space MMR."""
    from sklearn.metrics.pairwise import cosine_similarity

    if len(sentences) <= target:
        return sentences

    # Embed all sentences
    embs = _embed_sentences(sentences)          # (n, 768), L2-normalised

    # Document centroid = mean of all sentence embeddings
    centroid = embs.mean(axis=0)
    centroid /= max(np.linalg.norm(centroid), 1e-9)

    # Relevance score = cosine similarity to centroid
    relevance = (embs @ centroid).clip(0, 1)    # (n,)

    # Positional weight
    n = len(sentences)
    pos_weight = np.ones(n)
    pos_weight[:max(1, int(n * 0.15))]    = 1.25
    pos_weight[max(0, int(n * 0.85)):]   = 1.15

    # Length weight
    len_weight = np.ones(n)
    for i, s in enumerate(sentences):
        wc = len(s.split())
        if wc < 3 or wc > 120:
            len_weight[i] = 0.3

    hybrid = relevance * pos_weight * len_weight

    # Normalize
    mx = np.max(hybrid)
    if mx > 0:
        hybrid /= mx

    # Cosine similarity matrix in embedding space (for MMR)
    sim_matrix = (embs @ embs.T).clip(0, 1).astype(np.float32)
    np.fill_diagonal(sim_matrix, 0.0)

    # MMR with tighter lambda (more diversity for Vietnamese multi-topic docs)
    selected = _mmr_select(hybrid, sim_matrix, target, lambda_param=0.70)
    return [sentences[i] for i in selected]


# ═══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

def summarize(text: str, mode: str = "short", engine: str = "auto",
              summary_mode: str = "fast") -> dict:
    """
    Summarize text.

    Args:
        text:         Input text (truncated if > MAX_INPUT_CHARS).
        mode:         "short" | "bullets" | "executive"
        engine:       "auto" | "fast" | "smart"  (extractive engine selector)
        summary_mode: "fast" | "ai_rewrite"      (pipeline mode)

    Returns:
        dict: summary, mode, sentences, elapsed_ms, engine_used, summary_mode, lang
    """
    t0 = time.time()

    # ── Input guard ────────────────────────────────────────────────
    if len(text) > MAX_INPUT_CHARS:
        logger.warning(f"[Summarize] Input truncated from {len(text)} to {MAX_INPUT_CHARS} chars.")
        text = text[:MAX_INPUT_CHARS]

    # ── Language detection ─────────────────────────────────────────
    lang = detect_language(text)

    # ── OCR cleanup ──────────────────────────────────────────────
    clean = clean_ocr_text(text, lang)

    # ── Sentence tokenization ───────────────────────────────────────
    sentences = tokenize_sentences(clean, lang)
    total     = len(sentences)

    if total == 0:
        return {
            "summary":      "",
            "mode":         mode,
            "sentences":    0,
            "elapsed_ms":   0,
            "engine_used":  "none",
            "summary_mode": summary_mode,
            "lang":         lang,
        }

    # ── Pick extractive engine ──────────────────────────────────────────
    use_smart = (engine == "smart" or (engine == "auto" and lang == "vietnamese"))

    # ══ AI REWRITE PATH ══════════════════════════════════════════════════
    if summary_mode == "ai_rewrite":
        # Step 1: Extract condensed sentences (40% of total, max 12)
        # This gives the AI model meaningful context without the full noise
        ai_pre_target = min(total, max(6, math.ceil(total * 0.40)))
        try:
            if use_smart:
                condensed = _smart_summarize(sentences, ai_pre_target)
            else:
                condensed = _fast_summarize(sentences, lang, ai_pre_target)
            condensed = post_process_sentences(condensed)
        except Exception as e:
            logger.warning(f"[AIRewrite] Pre-extraction failed: {e}")
            condensed = sentences[:ai_pre_target]

        # Step 2: AI rewrites the condensed content into natural prose/bullets
        try:
            from services import ai_rewrite_service
            ai_summary, ai_engine = ai_rewrite_service.ai_rewrite(
                condensed, mode, lang, task="summarize")
            if ai_summary:
                elapsed = round((time.time() - t0) * 1000)
                if mode == "bullets":
                    sent_count = len([l for l in ai_summary.split("\n") if l.strip()])
                else:
                    sent_count = max(1, ai_summary.count(".") + ai_summary.count("!") + ai_summary.count("?"))
                return {
                    "summary":      ai_summary,
                    "mode":         mode,
                    "sentences":    sent_count,
                    "elapsed_ms":   elapsed,
                    "engine_used":  ai_engine,
                    "summary_mode": "ai_rewrite",
                    "lang":         lang,
                }
        except Exception as e:
            logger.warning(f"[AIRewrite] AI failed ({e}), falling back to extractive.")
        # AI failed — fall through to extractive below
        summary_mode = "fast_fallback"

    # ══ FAST EXTRACTIVE PATH ═════════════════════════════════════════════
    target = _target_count(mode, total)

    engine_used = "fast"
    if use_smart:
        try:
            selected    = _smart_summarize(sentences, target)
            engine_used = "smart"
        except Exception as e:
            logger.error(f"[SmartEngine] Error, falling back to FastEngine: {e}")
            selected    = _fast_summarize(sentences, lang, target)
            engine_used = "fast_fallback"
    else:
        try:
            selected = _fast_summarize(sentences, lang, target)
        except Exception as e:
            logger.error(f"[FastEngine] Error, using raw sentences: {e}")
            selected    = sentences[:target]
            engine_used = "raw_fallback"

    # ── Post-processing ─────────────────────────────────────────────────
    selected = post_process_sentences(selected)

    # ── Format output ───────────────────────────────────────────────────
    if mode == "bullets":
        summary = "\n".join(f"• {s}" for s in selected)
    else:
        summary = " ".join(selected)

    elapsed = round((time.time() - t0) * 1000)

    return {
        "summary":      summary,
        "mode":         mode,
        "sentences":    len(selected),
        "elapsed_ms":   elapsed,
        "engine_used":  engine_used,
        "summary_mode": summary_mode,
        "lang":         lang,
    }


def get_ai_status() -> dict:
    """Passthrough to ai_rewrite_service status (safe to call before model loads)."""
    try:
        from services import ai_rewrite_service
        return ai_rewrite_service.get_ai_status()
    except Exception as e:
        return {"local": False, "api": False, "ready": False, "error": str(e)}

