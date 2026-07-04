"""One-time online warm-up: fetch the PaddleOCR 3.7 models needed by 'PaddleOCR Modern'.

Run ONCE while online. Sets the PaddleX model source to HuggingFace (reachable here;
ModelScope is not) and disables the source check. Does NOT import the app config, so the
app's OFFLINE flag does not block these downloads. After this completes, the app runs the
Modern engine fully offline.

Usage:
    .venv/bin/python3 PaddleOCR/web_app/tools/warmup_modern_models.py
"""
import os

os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "HuggingFace")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
# Make sure no stale HF offline flags are set in this process.
for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
    os.environ.pop(k, None)

import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../tests/test_files"))
BOOK = os.path.join(REPO, "book.jpg")
MEDAL = os.path.join(REPO, "medal_table.png")


def banner(msg):
    print("\n" + "=" * 70 + f"\n  {msg}\n" + "=" * 70)


banner("1/2  PaddleOCR PP-OCRv6 (standalone) — forces PP-OCRv6 model download")
from paddleocr import PaddleOCR

v6 = PaddleOCR(ocr_version="PP-OCRv6",
               use_doc_orientation_classify=False, use_doc_unwarping=False)
t0 = time.time()
r = list(v6.predict(BOOK))
print(f"PP-OCRv6 ran on book.jpg in {round((time.time()-t0)*1000)} ms; "
      f"lines={len(r[0].get('rec_texts', [])) if r else 0}")

banner("2/2  PPStructureV3 — forces 3.7 structure models; reveals OCR sub-models used")
from paddleocr import PPStructureV3

pipe = PPStructureV3(use_doc_orientation_classify=False, use_doc_unwarping=False,
                     use_seal_recognition=False, use_chart_recognition=False)
t0 = time.time()
res = list(pipe.predict(MEDAL))
ms = round((time.time() - t0) * 1000)
for x in res:
    j = x.json or {}
    if isinstance(j, dict) and "res" in j:
        j = j["res"]
    ocr = j.get("overall_ocr_res", {}) or {}
    print(f"PPStructureV3 ran on medal_table.png in {ms} ms; "
          f"ocr_lines={len(ocr.get('rec_texts', []))}; "
          f"tables={len(j.get('table_res_list', []) or [])}; "
          f"blocks={len(j.get('parsing_res_list', []) or [])}")
    print("overall_ocr_res model_settings:", ocr.get("model_settings"))

banner("DONE — models cached under ~/.paddlex/official_models/")
