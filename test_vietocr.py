import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from config import cfg

# Force loading models from local directory
cfg.OFFLINE = True

from services.ocr_engines.vietocr_adapter import VietOCREngine
from services.ocr_engines.paddle_adapter import PaddleOCREngine


test_img = BASE_DIR / "models" / "_paddle_setup_test.png"
if not test_img.exists():
    import numpy as np
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (200, 60), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((10, 20), "SmartDocs test", fill=(0, 0, 0))
    img.save(str(test_img))

print("Testing PaddleOCR...")
try:
    p_eng = PaddleOCREngine()
    p_res = p_eng.run(str(test_img))
    print(f"PaddleOCR Success! Found {len(p_res['results'])} items.")
except Exception as e:
    print(f"PaddleOCR failed: {e}")

print("Testing VietOCR...")
try:
    v_eng = VietOCREngine()
    v_res = v_eng.run(str(test_img))
    print(f"VietOCR Success! Found {len(v_res['results'])} items.")
except Exception as e:
    import traceback
    traceback.print_exc()
