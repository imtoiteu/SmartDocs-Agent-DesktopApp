import json
from services import layout_service

# Mock a 2-column page with a header
results = [
    # Header: spans across
    {"text": "HEADER", "box": [[100, 10], [500, 10], [500, 30], [100, 30]]},
    # Right column text 1 (out of order in raw OCR)
    {"text": "Right Col 1", "box": [[350, 50], [500, 50], [500, 70], [350, 70]]},
    # Left column text 1
    {"text": "Left Col 1", "box": [[50, 50], [200, 50], [200, 70], [50, 70]]},
    # Right column text 2 (paragraph with Right Col 1)
    {"text": "Right Col 2", "box": [[350, 75], [500, 75], [500, 95], [350, 95]]},
    # Left column text 2 (different paragraph)
    {"text": "Left Col 2", "box": [[50, 100], [200, 100], [200, 120], [50, 120]]},
]

# Run reconstruction
reconstructed = layout_service.reconstruct_layout(results, img_width=600, img_height=200)

for i, item in enumerate(reconstructed):
    print(f"[{i}] {item['text']}")

