#!/usr/bin/env python3
"""
ab_harness.py — Real-document A/B comparison of two chat/rewrite models
======================================================================
Answers the question a smoke test cannot: *does model B actually give better
answers on YOUR documents than model A?* It runs the real RAG + summarization
pipeline over a deterministic sample of real uploaded documents and records each
model's answers, so you can read them side-by-side and judge quality yourself.

It changes NOTHING permanent: like eval_model.py, it sets QWEN_MODEL/CHAT_MODEL
as process env vars before config loads (config uses load_dotenv(override=False)),
so the committed default (Qwen2.5-1.5B) stays put. CPU + bfloat16 (MPS hard-crashes
at 3B+), which is why 1.5B is the default local model for this app.

Because two 6–8 GB models can't both fit in 16 GB, run ONE model per process:

  PY=/Users/imtoiteu/Desktop/OCRSoftware/.venv/bin/python
  $PY tools/ab_harness.py "Qwen/Qwen2.5-3B-Instruct"
  $PY tools/ab_harness.py "Qwen/Qwen3-4B-Instruct-2507"
  $PY tools/ab_harness.py --report      # writes tools/ab_results/AB_comparison.md

Document selection is deterministic (same docs for both models): real .pdf/.docx
from uploads/, de-duplicated, truncated, and spread across short/medium/long.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB_APP = HERE.parent
OUT = HERE / "ab_results"
OUT.mkdir(exist_ok=True)

N_DOCS    = int(os.environ.get("AB_N_DOCS", "3"))
MAX_CHARS = int(os.environ.get("AB_MAX_CHARS", "5000"))

# Questions asked of EVERY document (content-agnostic, answer-requiring).
# Mixes comprehension, grounded extraction, and a cross-lingual Vietnamese ask —
# the last one tends to separate stronger models.
QUESTIONS = [
    "Summarize what this document is about in 2-3 sentences.",
    "List the most important specific facts, numbers, names, or details stated in the document.",
    "Tài liệu này nói về vấn đề gì và mục đích chính là gì? Trả lời bằng tiếng Việt.",
]


def _short(model_id: str) -> str:
    return model_id.split("/")[-1]


# ── Deterministic real-document sample (same for every model run) ─────────────
def select_documents():
    sys.path.insert(0, str(WEB_APP))
    from services import text_service

    cands = []
    seen = set()
    for f in sorted(glob.glob(str(WEB_APP / "uploads" / "*.pdf"))
                    + glob.glob(str(WEB_APP / "uploads" / "*.docx"))
                    + glob.glob(str(WEB_APP / "uploads" / "*.txt"))):
        try:
            txt = text_service.read_file(f)
        except Exception:
            continue
        txt = (txt or "").strip()
        if len(txt) < 200:
            continue
        h = hashlib.md5(txt[:2000].encode("utf-8", "ignore")).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        cands.append((Path(f).name, txt))

    if not cands:
        return []
    # Spread across length: shortest, medium, longest, … (diverse difficulty)
    cands.sort(key=lambda c: len(c[1]))
    n = min(N_DOCS, len(cands))
    idxs = sorted({round(i * (len(cands) - 1) / max(1, n - 1)) for i in range(n)})
    picked = [cands[i] for i in idxs]
    return [(name, txt[:MAX_CHARS]) for name, txt in picked]


# ══════════════════════════════════════════════════════════════════════════════
#  RUN ONE MODEL
# ══════════════════════════════════════════════════════════════════════════════
def run(model_id: str):
    os.environ["QWEN_MODEL"]          = model_id
    os.environ["CHAT_MODEL"]          = model_id
    os.environ["FALLBACK_CHAT_MODEL"] = model_id
    os.environ["QWEN_DEVICE"]         = "cpu"
    os.environ["CHAT_DEVICE"]         = "cpu"
    os.environ["DTYPE"]               = "bfloat16"
    os.environ["OFFLINE"]             = "1"

    docs = select_documents()
    if not docs:
        print("No extractable documents found in uploads/."); return

    sys.path.insert(0, str(WEB_APP))
    from config import cfg
    from services import chat_service as chat, summary_service

    print(f"▶ A/B run: {model_id}  on {cfg.CHAT_DEVICE}/{cfg.CHAT_DTYPE}  ({len(docs)} docs)", flush=True)
    t0 = time.time()
    chat._ensure_chat_loaded(timeout=1800)
    print(f"  model ready in {round(time.time()-t0,1)}s", flush=True)

    out = {"model": model_id, "device": cfg.CHAT_DEVICE, "dtype": str(cfg.CHAT_DTYPE),
           "questions": QUESTIONS, "documents": []}

    for di, (name, text) in enumerate(docs):
        fid = f"ab-{di}"
        chat.remove_document(fid)
        n_chunks = chat.index_document(fid, text, source_label="ab")
        doc_rec = {"filename": name, "chars": len(text), "chunks": n_chunks,
                   "excerpt": text[:300], "answers": [], "embedding_mode": None, "summary": None}
        print(f"\n── Doc {di+1}/{len(docs)}: {name}  ({len(text)} chars, {n_chunks} chunks)", flush=True)

        for q in QUESTIONS:
            t = time.time()
            try:
                res = chat.chat(q, file_id=fid, mode="doc_current")
                ans, dt = res["answer"], round(time.time() - t, 2)
                doc_rec["embedding_mode"] = res.get("embedding_mode")
                doc_rec["answers"].append({"q": q, "answer": ans, "latency_s": dt,
                                           "chunks_found": res.get("chunks_found")})
                print(f"   Q: {q[:50]}…  ({dt}s)  → {ans[:70]!r}", flush=True)
            except Exception as e:
                doc_rec["answers"].append({"q": q, "answer": f"[ERROR] {e}", "latency_s": None})
                print(f"   Q FAIL: {e}", flush=True)

        # Abstractive AI summary of the same document
        t = time.time()
        try:
            sm = summary_service.summarize(text, "short", summary_mode="ai_rewrite")
            doc_rec["summary"] = {"text": sm.get("summary", ""), "engine": sm.get("engine_used"),
                                  "latency_s": round(time.time() - t, 2)}
            print(f"   Summary ({doc_rec['summary']['latency_s']}s) → {sm.get('summary','')[:70]!r}", flush=True)
        except Exception as e:
            doc_rec["summary"] = {"text": f"[ERROR] {e}", "engine": None, "latency_s": None}

        chat.remove_document(fid)
        out["documents"].append(doc_rec)

    path = OUT / (_short(model_id) + ".json")
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\n✅ saved → {path}", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
#  SIDE-BY-SIDE REPORT (human judgement)
# ══════════════════════════════════════════════════════════════════════════════
def report():
    files = sorted(OUT.glob("*.json"))
    runs = [json.loads(f.read_text()) for f in files]
    if len(runs) < 2:
        print(f"Need 2 model runs to compare; found {len(runs)}. "
              f"Run ab_harness.py for both models first.")
        return

    a, b = runs[0], runs[1]
    na, nb = _short(a["model"]), _short(b["model"])
    md = []
    md.append(f"# Real-Document A/B — {na}  vs  {nb}\n")
    md.append(f"- Device/dtype: **{a['device']} / {a['dtype']}** (both)")
    md.append(f"- Embedding: **{(a['documents'][0].get('embedding_mode') if a['documents'] else '?')}** "
              f"(same for both → isolates the LLM)")
    md.append(f"- Documents: **{len(a['documents'])}** real files from `uploads/`\n")
    md.append("> Read each pair and mark which answer is better. The retrieved context is "
              "identical for both models, so any difference is the model's reasoning.\n")

    def find_doc(run_obj, filename):
        for d in run_obj["documents"]:
            if d["filename"] == filename:
                return d
        return None

    for da in a["documents"]:
        db = find_doc(b, da["filename"]) or {"answers": [], "summary": None}
        md.append(f"\n---\n\n## Document: `{da['filename']}`  ({da['chars']} chars, {da['chunks']} chunks)\n")
        md.append(f"> {da['excerpt'].strip().replace(chr(10),' ')[:280]}…\n")
        for i, qa in enumerate(da["answers"]):
            qb = db["answers"][i] if i < len(db.get("answers", [])) else {"answer": "—", "latency_s": "—"}
            md.append(f"\n### Q{i+1}: {qa['q']}\n")
            md.append(f"**{na}** ({qa.get('latency_s')}s):\n\n{qa['answer'].strip()}\n")
            md.append(f"\n**{nb}** ({qb.get('latency_s')}s):\n\n{qb['answer'].strip()}\n")
        # summaries
        sa = da.get("summary") or {}; sb = db.get("summary") or {}
        md.append(f"\n### Abstractive summary\n")
        md.append(f"**{na}** ({sa.get('latency_s')}s):\n\n{(sa.get('text') or '').strip()}\n")
        md.append(f"\n**{nb}** ({sb.get('latency_s')}s):\n\n{(sb.get('text') or '').strip()}\n")

    out_md = OUT / "AB_comparison.md"
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"✅ wrote side-by-side comparison → {out_md}")
    print(f"   open it with:  open {out_md}")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__); return
    if args[0] == "--report":
        report(); return
    run(args[0])


if __name__ == "__main__":
    main()
