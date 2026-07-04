Two terminals — the GLM model server (already running, but here's how to start it) and the SmartDocs web app.

# Terminal 1 — GLM OCR model server (only needed for the GLM engine; leave it running):

/Users/imtoiteu/Desktop/OCRSoftware/SmartDocs-Agent/tools/glm_serve.sh

# Terminal 2 — SmartDocs web app:

/Users/imtoiteu/Desktop/OCRSoftware/.venv/bin/python \
 /Users/imtoiteu/Desktop/OCRSoftware/SmartDocs-Agent/app.py

## Then open http://localhost:5002 and log in (e.g. user / admin).

Quick checks:

Confirm the GLM server is up: curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/chat/completions -X POST -H "Content-Type: application/json" -d '{"model":"mlx-community/GLM-OCR-bf16","messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}],"max_tokens":3}' → 200.
In the UI: OCR tab → upload an image → pick 🧠 GLM OCR (Structured) → Run OCR. The other three engines work without Terminal 1.
Note: Legacy/VietOCR/Modern don't need the GLM server; if it's down, only the GLM engine shows an error toast telling you to start it.
