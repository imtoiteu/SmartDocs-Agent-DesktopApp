#!/usr/bin/env python3
"""
eval_model.py — Candidate-LLM evaluation harness (NON-PERMANENT, .env untouched)
================================================================================
Evaluates a Qwen chat/rewrite model END-TO-END through the real services, without
changing the committed configuration. It sets QWEN_MODEL / CHAT_MODEL etc. as
process environment variables BEFORE importing `config`; because config.py loads
the .env with `override=False`, these process-env values win, so the committed
default local LLM (Qwen2.5-1.5B) is never modified.

It exercises and measures: AI Rewrite, AI Chat (general), RAG (index + doc chat),
Summarization (AI-rewrite + fast/extractive), and Translation (offline Argos).
It confirms B1 (the two services share ONE model instance) and records:
  startup/load time · peak RAM (RSS) · per-feature latency · tokens/sec.

USAGE
-----
  # evaluate a model (run each in its OWN process so RAM is isolated):
  .venv/bin/python tools/eval_model.py "Qwen/Qwen3-4B-Instruct-2507"
  .venv/bin/python tools/eval_model.py "Qwen/Qwen2.5-3B-Instruct"     # baseline

  # then print a side-by-side comparison of everything evaluated so far:
  .venv/bin/python tools/eval_model.py --report

Device is forced to CPU + bfloat16 (MPS hard-crashes for 3B+; 4B is larger).
Results are written to tools/eval_results/<model>.json.

⚠ Evaluation/testing only. Does NOT make any model the default.
"""

from __future__ import annotations

import json
import os
import resource
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB_APP = HERE.parent
RESULTS_DIR = HERE / "eval_results"
RESULTS_DIR.mkdir(exist_ok=True)

DEFAULT_BASELINE = "Qwen/Qwen2.5-3B-Instruct"


# ── peak RSS (resident memory) ────────────────────────────────────────────────
def peak_rss_gb() -> float:
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports ru_maxrss in BYTES; Linux in KILOBYTES.
    factor = 1 if sys.platform == "darwin" else 1024
    return round(ru * factor / (1024 ** 3), 2)


def _short(model_id: str) -> str:
    return model_id.split("/")[-1]


# ══════════════════════════════════════════════════════════════════════════════
#  REPORT MODE — compare previously-saved results
# ══════════════════════════════════════════════════════════════════════════════
def report():
    files = sorted(RESULTS_DIR.glob("*.json"))
    if not files:
        print("No results yet. Run:  python tools/eval_model.py <model_id>")
        return
    runs = [json.loads(f.read_text()) for f in files]

    def col(r, *path, default="—"):
        cur = r
        for p in path:
            cur = (cur or {}).get(p) if isinstance(cur, dict) else None
        return cur if cur is not None else default

    rows = [
        ("model",                 lambda r: _short(r["model"])),
        ("device / dtype",        lambda r: f"{r['device']} / {r['dtype']}"),
        ("B1 shared instance",    lambda r: "yes" if r.get("b1_shared") else "NO"),
        ("registry entries",      lambda r: r.get("registry_entries")),
        ("load → ready (s)",      lambda r: r.get("load_seconds")),
        ("peak RAM (GB)",         lambda r: r.get("peak_rss_gb")),
        ("AI Rewrite (s | tok/s)",lambda r: f"{col(r,'rewrite','latency_s')} | {col(r,'rewrite','tok_per_s')}"),
        ("AI Chat (s | tok/s)",   lambda r: f"{col(r,'chat','latency_s')} | {col(r,'chat','tok_per_s')}"),
        ("RAG doc-chat (s)",      lambda r: col(r, "rag", "latency_s")),
        ("Summary-AI (s | tok/s)",lambda r: f"{col(r,'summary_ai','latency_s')} | {col(r,'summary_ai','tok_per_s')}"),
        ("Summary-fast (s)",      lambda r: col(r, "summary_fast", "latency_s")),
        ("Translation (s)",       lambda r: col(r, "translation", "latency_s")),
        ("embedding mode",        lambda r: r.get("embedding_mode")),
        ("stability",             lambda r: r.get("stability")),
    ]
    w0 = max(len(lbl) for lbl, _ in rows) + 1
    wc = max(22, *(len(_short(r["model"])) + 2 for r in runs))
    print("\n" + "=" * (w0 + wc * len(runs)))
    print("  MODEL EVALUATION COMPARISON")
    print("=" * (w0 + wc * len(runs)))
    for lbl, fn in rows:
        cells = "".join(str(fn(r)).ljust(wc) for r in runs)
        print(f"{lbl.ljust(w0)}{cells}")
    print()
    # per-feature pass/fail
    print("  Feature status:")
    feats = ["rewrite", "chat", "rag", "summary_ai", "summary_fast", "translation"]
    for r in runs:
        st = " ".join(f"{f}={'OK' if col(r,f,'ok') is True else 'FAIL'}" for f in feats)
        print(f"   {_short(r['model']):28s} {st}")
    print()


# ══════════════════════════════════════════════════════════════════════════════
#  EVAL MODE
# ══════════════════════════════════════════════════════════════════════════════
def evaluate(model_id: str):
    # ── Override config BEFORE importing it (.env stays the source of the default).
    #    config.py calls load_dotenv(override=False), so these process-env values win.
    os.environ["QWEN_MODEL"]          = model_id   # AI Rewrite + Smart-OCR
    os.environ["CHAT_MODEL"]          = model_id   # AI Chat
    os.environ["FALLBACK_CHAT_MODEL"] = model_id   # force the SAME model (detect real failures)
    os.environ["QWEN_DEVICE"]         = "cpu"
    os.environ["CHAT_DEVICE"]         = "cpu"
    os.environ["DTYPE"]               = "bfloat16"
    os.environ["OFFLINE"]             = "1"        # must already be downloaded locally

    sys.path.insert(0, str(WEB_APP))
    t_import = time.time()
    from config import cfg
    import torch, transformers

    result = {
        "model": model_id, "device": cfg.CHAT_DEVICE, "dtype": str(cfg.CHAT_DTYPE),
        "torch": torch.__version__, "transformers": transformers.__version__,
        "stability": "ok",
    }

    # Sanity: config really took the override and both services align (B1 precondition)
    assert cfg.QWEN_MODEL == cfg.CHAT_MODEL == model_id, "env override didn't take"
    assert cfg.QWEN_DEVICE == cfg.CHAT_DEVICE == "cpu"

    print(f"▶ Evaluating {model_id}  on {cfg.CHAT_DEVICE}/{cfg.CHAT_DTYPE}", flush=True)
    print(f"  torch {torch.__version__} · transformers {transformers.__version__}", flush=True)

    from services import ai_rewrite_service as air   # auto-prewarm starts at import
    from services import chat_service as chat
    from services import summary_service, translate_service, llm_registry

    # ── 1. LOAD (startup) ─────────────────────────────────────────────────────
    try:
        air._ensure_loaded(timeout=1800)
        chat._ensure_chat_loaded(timeout=1800)
    except Exception as e:
        result["stability"] = f"LOAD FAILED: {e}"
        _save(result); print("✗ model failed to load:", e); return result
    result["load_seconds"] = round(time.time() - t_import, 1)
    result["b1_shared"] = bool(air._qwen_model is chat._chat_model)
    result["registry_entries"] = len(llm_registry._entries)
    print(f"[load] ready in {result['load_seconds']}s  B1_shared={result['b1_shared']}  "
          f"registry={result['registry_entries']}", flush=True)

    tok = air._qwen_tok
    def toks(text):  # token count of a string (for tok/s)
        try: return len(tok(text).input_ids)
        except Exception: return len(text.split())

    def timed_llm(fn, *, count_text):
        t = time.time(); out = fn(); dt = time.time() - t
        n = toks(count_text(out))
        return out, round(dt, 2), (round(n / dt, 1) if dt > 0 else 0.0)

    # ── 2. AI REWRITE ─────────────────────────────────────────────────────────
    try:
        out, dt, tps = timed_llm(
            lambda: air.run_local_messages(
                [{"role": "user", "content": "Dịch sang tiếng Việt: 'Good morning, team'. Chỉ trả lời bản dịch."}],
                max_new_tokens=40, temperature=0.0, do_sample=False)[0],
            count_text=lambda o: o)
        result["rewrite"] = {"ok": True, "latency_s": dt, "tok_per_s": tps, "sample": out[:80]}
        print(f"[rewrite] {dt}s {tps} tok/s :: {out[:60]!r}", flush=True)
    except Exception as e:
        result["rewrite"] = {"ok": False, "error": str(e)[:200]}; print("[rewrite] FAIL", e, flush=True)

    # ── 3. AI CHAT (general, no RAG) ──────────────────────────────────────────
    try:
        out, dt, tps = timed_llm(
            lambda: chat.chat("Trả lời ngắn gọn: thủ đô của Việt Nam là gì?", mode="general")["answer"],
            count_text=lambda o: o)
        result["chat"] = {"ok": True, "latency_s": dt, "tok_per_s": tps, "sample": out[:80]}
        print(f"[chat] {dt}s {tps} tok/s :: {out[:60]!r}", flush=True)
    except Exception as e:
        result["chat"] = {"ok": False, "error": str(e)[:200]}; print("[chat] FAIL", e, flush=True)

    # ── 4. RAG (index a doc, then doc-scoped chat) ────────────────────────────
    try:
        doc = ("Hợp đồng số 12. Bên A là Công ty ABC, địa chỉ Hà Nội. "
               "Giá trị hợp đồng là 250 triệu đồng. Thời hạn 12 tháng kể từ ngày ký. "
               "Bên B chịu trách nhiệm bảo hành 24 tháng.")
        n_chunks = chat.index_document("eval-doc-1", doc, source_label="eval")
        t = time.time()
        res = chat.chat("Giá trị hợp đồng là bao nhiêu?", file_id="eval-doc-1", mode="doc_current")
        dt = round(time.time() - t, 2)
        result["embedding_mode"] = res.get("embedding_mode")
        result["rag"] = {"ok": bool(res["answer"]), "latency_s": dt,
                         "chunks_indexed": n_chunks, "chunks_found": res.get("chunks_found"),
                         "sources": len(res.get("sources", [])), "sample": res["answer"][:80]}
        chat.remove_document("eval-doc-1")
        print(f"[rag] {dt}s chunks={n_chunks} found={res.get('chunks_found')} emb={res.get('embedding_mode')} "
              f":: {res['answer'][:60]!r}", flush=True)
    except Exception as e:
        result["rag"] = {"ok": False, "error": str(e)[:200]}; print("[rag] FAIL", e, flush=True)

    # ── 5. SUMMARIZATION — AI-rewrite (uses Qwen) + fast (extractive) ─────────
    long_text = (" ".join([
        "Trí tuệ nhân tạo đang thay đổi nhiều ngành công nghiệp.",
        "Các mô hình ngôn ngữ lớn có thể tóm tắt, dịch và trả lời câu hỏi.",
        "Việc triển khai cục bộ giúp bảo vệ quyền riêng tư dữ liệu.",
        "Tuy nhiên, mô hình lớn đòi hỏi nhiều bộ nhớ và thời gian xử lý.",
        "Người dùng cần cân bằng giữa chất lượng và hiệu năng.",
    ] * 3))
    try:
        t = time.time()
        r = summary_service.summarize(long_text, "short", summary_mode="ai_rewrite")
        dt = round(time.time() - t, 2)
        ok = bool(r.get("summary")) and "ai" in str(r.get("engine_used", ""))
        result["summary_ai"] = {"ok": ok, "latency_s": dt,
                                "tok_per_s": round(toks(r["summary"]) / dt, 1) if dt > 0 else 0,
                                "engine": r.get("engine_used"), "sample": r.get("summary", "")[:80]}
        print(f"[summary-ai] {dt}s engine={r.get('engine_used')} :: {r.get('summary','')[:60]!r}", flush=True)
    except Exception as e:
        result["summary_ai"] = {"ok": False, "error": str(e)[:200]}; print("[summary-ai] FAIL", e, flush=True)
    try:
        t = time.time()
        r = summary_service.summarize(long_text, "short", summary_mode="fast")
        result["summary_fast"] = {"ok": bool(r.get("summary")), "latency_s": round(time.time() - t, 2),
                                  "engine": r.get("engine_used")}
        print(f"[summary-fast] engine={r.get('engine_used')}", flush=True)
    except Exception as e:
        result["summary_fast"] = {"ok": False, "error": str(e)[:200]}

    # ── 6. TRANSLATION (offline Argos — model-independent; confirm unaffected) ─
    try:
        t = time.time()
        tr = translate_service.translate("The contract value is 250 million dong.", "en", "vi", engine="offline")
        result["translation"] = {"ok": bool(tr.get("translated")), "latency_s": round(time.time() - t, 2),
                                 "engine": tr.get("engine_used"), "sample": tr.get("translated", "")[:80]}
        print(f"[translation] {result['translation']['latency_s']}s :: {tr.get('translated','')[:60]!r}", flush=True)
    except Exception as e:
        result["translation"] = {"ok": False, "error": str(e)[:200]}; print("[translation] FAIL", e, flush=True)

    # ── peak RAM (after everything) ───────────────────────────────────────────
    result["peak_rss_gb"] = peak_rss_gb()
    print(f"[mem] peak RSS = {result['peak_rss_gb']} GB", flush=True)

    _save(result)
    print(f"\n✅ saved → {RESULTS_DIR / (_short(model_id) + '.json')}", flush=True)
    print(json.dumps({k: v for k, v in result.items()
                      if k in ('load_seconds', 'peak_rss_gb', 'b1_shared', 'registry_entries')}, indent=2))
    return result


def _save(result):
    (RESULTS_DIR / (_short(result["model"]) + ".json")).write_text(json.dumps(result, indent=2, ensure_ascii=False))


# ══════════════════════════════════════════════════════════════════════════════
def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__); return
    if args[0] == "--report":
        report(); return
    evaluate(args[0])


if __name__ == "__main__":
    main()
