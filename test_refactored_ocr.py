import os
import sys
from pathlib import Path
from services import smart_ocr_service

# Mock config
import config
config.cfg.OFFLINE = True

test_img = Path("static/img/empty.png") # Create a dummy image
if not test_img.parent.exists():
    test_img.parent.mkdir(parents=True)
from PIL import Image
Image.new('RGB', (100, 100), color = 'white').save(test_img)

print("Test 1: PaddleOCR, AI Off")
res1 = smart_ocr_service.run_ocr_pipeline(str(test_img), engine_name="paddleocr", apply_ai=False)
print("  Engine Used:", res1.get('ocr_engine'))
print("  AI Enhancement:", res1.get('ai_enhancement'))
print("  Smart Applied:", res1.get('smart_applied'))

print("\nTest 2: VietOCR, AI Off")
res2 = smart_ocr_service.run_ocr_pipeline(str(test_img), engine_name="vietocr", apply_ai=False)
print("  Engine Used:", res2.get('ocr_engine'))
print("  AI Enhancement:", res2.get('ai_enhancement'))
print("  Smart Applied:", res2.get('smart_applied'))

