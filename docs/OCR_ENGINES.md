# OCR Engines — Comparison & Evaluation Guide

This app now ships **four** OCR engines side by side. The goal of this setup is
**evaluation, not migration**: nothing was removed, and the existing workflow is
unchanged. Use this guide to decide which engine to adopt.

> Stack: PaddleOCR **3.7.0** / PaddleX **3.7.1** / PaddlePaddle 3.3.1, CPU, offline.
> GLM OCR runs as a separate local MLX model server (Apple Silicon) — see §9.

---

## 1. The three engines

| Engine (dropdown label) | `engine` value | Pipeline | OCR models | Extra output | Speed (CPU) |
|---|---|---|---|---|---|
| **OCR English** (Legacy) | `paddleocr` | `PaddleOCR` basic OCR | **PP-OCRv5_server** det+rec (pinned) | none (plain text + boxes) | fast (~1–2 s/page) |
| **OCR Vietnamese** | `vietocr` | PaddleOCR **detection** + VietOCR recognition | PP-OCRv5_server det (pinned) + `vgg_transformer` | none | medium (~2–4 s/page) |
| **PaddleOCR Modern** | `paddleocr_modern` | **PP-StructureV3** (layout + table + formula) | **PP-OCRv6_medium** det+rec | **Markdown · HTML · tables · layout blocks · layout overlay** | slow (~20–65 s/page) |
| **GLM OCR** | `glmocr` | **GLM-OCR** VLM (PP-DocLayoutV3 + GLM-V 0.9B via MLX) | GLM-OCR-bf16 (MLX) | **Markdown · tables · layout blocks · extracted images (layout + crops) · JSON** | medium (~7–30 s/page, MLX) |
| **Auto Detect** | `auto` | alias → `paddleocr` (configurable via `OCR_ENGINE`) | — | — | — |

**Why Legacy/VietOCR are pinned to PP-OCRv5:** PaddleOCR 3.7's *default* pipeline is
PP-OCRv6. To keep these two engines behaving **exactly** as before the upgrade, they are
explicitly pinned to `ocr_version="PP-OCRv5"` (verified byte-for-byte identical to the
pre-upgrade output). Only "Modern" uses the newer PP-OCRv6.

**Why Modern is the strongest production option here:** an audit of the PaddleOCR repo found
PP-StructureV3 is the strongest *production-ready, CPU-offline* document pipeline. The
higher-accuracy PaddleOCR-VL is a VLM that needs GPU/MLX serving, and PPChatOCRv4 /
PPDocTranslation require a Baidu API key — both violate this app's offline-first/CPU constraint.

> **User-facing selector (simplified).** The main **OCR view** dropdown now exposes only three
> labels — **⭐ Recommended → `glmocr`** (default), **🇻🇳 Vietnamese → `vietocr`**,
> **📄 Standard → `paddleocr`**. *Auto Detect* and *PP-StructureV3 / Modern (`paddleocr_modern`)*
> are hidden from that dropdown but are **fully intact in the backend** and remain selectable for
> evaluation/benchmarking on the **⚖️ Compare** page below. The option `value`s are unchanged
> engine keys, so the routing/adapters are untouched.

---

## 2. What "Modern" produces that the others can't

For each page, the Modern engine returns the same `results` list (text + boxes, so the
canvas overlay and plain-text flatten path keep working) **plus**:

- `markdown` — reading-order Markdown reconstruction of the page
- `html` — a simple HTML reconstruction (headings/paragraphs/tables)
- `tables_html` — each detected table as an HTML `<table>` (cells aligned)
- `layout_blocks` — `{label, content, bbox, order}` per block (paragraph_title, text, table, formula, figure, …)

These are persisted as **DocumentArtifacts** (one row per kind, per document):
`ocr` (plain text — unchanged), `ocr_markdown`, `ocr_html`, `ocr_tables` (JSON), `ocr_blocks` (JSON),
plus the existing `ocr_layout` viewer snapshot. Legacy/VietOCR write only `ocr` + `ocr_layout`.

---

## 3. How to test / compare

### A. Switch engines in the OCR view
1. Open the **OCR** tab, upload a document.
2. Pick an engine in the **Engine** dropdown (incl. 🆕 *OCR Modern (Structured)*).
3. Click **Run OCR**. For Modern, a **Text / Markdown / HTML / Table** tab strip appears
   above the text box — use the **Table** tab to see reconstructed tables.
4. **Opt-in structured downstream:** while viewing the **Markdown** tab, click
   **→ Dịch / → Tóm tắt / → Sửa lỗi** to send *markdown* (instead of plain text) to that
   tool. Viewing the **Text** tab sends plain text (the default, unchanged behavior).

### B. Side-by-side comparison page (`⚖️ Compare`)
1. Open a document in **OCR** first (this sets the active file).
2. Go to the **⚖️ Compare** tab, set the page, click **Run comparison**.
3. You get three columns — Legacy / VietOCR / Modern — each with extracted text,
   per-engine **line count + latency**, and (for Modern) rendered tables + a Markdown
   disclosure. The page is rendered to an image first, so VietOCR works even on PDFs.

> Note: Compare runs all three engines synchronously; Modern dominates wall-clock
> (~20–65 s/page on CPU). It operates on one page at a time by design.

---

## 4. Benchmark guidance

Use a small, deliberately varied set and run each through the Compare page:

| Document type | What it stresses | What to look for |
|---|---|---|
| A page with a **table** (e.g. `tests/test_files/medal_table.png`) | structure recovery | Legacy = scrambled cells; Modern = aligned HTML table |
| A **Vietnamese** scan/photo | diacritics & language model | VietOCR vs Modern (PP-OCRv6) accuracy on tones |
| A **multi-column** / mixed layout page (e.g. `tests/test_files/book.jpg`) | reading order | Modern's block order & Markdown vs Legacy's flat lines |
| A **plain single-column** English page | baseline | confirm Modern ≈ Legacy on simple text (and is it worth the latency?) |

Record per engine: line count, latency, and a subjective accuracy score. The Compare
page surfaces line count + latency automatically.

Measured on this machine (PP-OCRv5 vs PP-OCRv6 effect): `book.jpg` yields **52 lines**
with Legacy (v5) vs **60 lines** with Modern (v6) — a real recognition/segmentation
difference, not just structure.

---

## 5. Expected strengths & weaknesses

**Legacy PaddleOCR (PP-OCRv5)** — Fast, reliable plain-text OCR. No tables, no reading
order beyond the app's geometric heuristic. Best when you just need text quickly.

**VietOCR** — Specialized Vietnamese recognition (often best on Vietnamese diacritics);
image-only; no structure. Detection still uses PaddleOCR.

**PaddleOCR Modern (PP-StructureV3 + PP-OCRv6)** — Best structure: real tables (HTML),
reading-order Markdown, layout block labels, formulas; newest recognition models.
Trade-off: **much slower on CPU** (~20–65 s/page) and heavier. Best for documents whose
*structure* matters (tables, multi-column, forms) and for feeding richer text downstream.

### Document preprocessing (skewed photos) — important

Modern runs with **document orientation + UVDoc unwarping ON**
(`use_doc_orientation_classify=True, use_doc_unwarping=True` in
`services/ocr_engines/paddle_modern_adapter.py`). This is required for correct tables:
PP-StructureV3's table-structure model assigns cells to a grid **geometrically**, so a
perspective-skewed photo scrambles the table (dropped header cells, values mis-placed into
the wrong rows/columns). Dewarping rectifies the page first and produces the correct grid.

**Known limitation (box overlay only):** with unwarping on, the OCR bounding boxes are
computed in the *rectified* coordinate space, while the canvas still shows the *original*
uploaded image. On strongly-skewed photos the box overlay can therefore appear shifted
relative to the original. This does **not** affect the structured outputs — the
**Text / Markdown / HTML / Table tabs and the persisted artifacts are correct** and are the
source of truth for Modern. (PaddleX does not expose the clean rectified page image in the
result, so the overlay is left on the original rather than shipped misframed.) Legacy and
VietOCR are unaffected (no unwarping, boxes align as before).

---

## 6. The four evaluation questions → where to look

1. **Is Modern better than Legacy?** Compare page, plain-text columns + line counts on
   the same page; check tables/multi-column docs especially.
2. **Is Modern better than VietOCR on Vietnamese?** Compare page on Vietnamese docs;
   compare the VietOCR vs Modern text columns for diacritic accuracy.
3. **Does structure improve downstream translate/summarize/chat?** In the OCR view, send
   the **Markdown** tab to Translate/Summarize and compare against sending plain **Text**.
4. **Is the added complexity justified?** Weigh the quality deltas from (1)–(3) against
   Modern's latency and the extra moving parts. The data to make this call comes straight
   from the Compare page + the downstream opt-in test.

---

## 7. Offline / CPU notes

- All three engines run **CPU-only and offline** once models are cached.
- Modern's models (PP-OCRv6, PP-DocLayout, table/formula nets) are fetched **once** by
  `tools/warmup_modern_models.py` (HuggingFace source; ModelScope is unreachable here).
  After that, no network is needed.
- Models live in `~/.paddlex/official_models/`.
- Keep AI Cleanup **off** with Modern: the Qwen line-correction only rewrites the flat
  `results`; the Markdown/tables remain the raw structured output.

## 8. Reverting / configuration

- Default engine is controlled by `OCR_ENGINE` env (default `paddle` → Legacy); `auto`
  maps to it. Nothing forces Modern or GLM on anyone.
- To remove an engine later: delete its `<option>` in `static/index.html`, its entry in
  `services/ocr_engines/router.py`, and the adapter file — the other engines are untouched.

---

## 9. GLM OCR — backend modes (cross-platform)

GLM OCR is a **GLM-V vision OCR model** (PP-DocLayoutV3 for layout + a 0.9B GLM decoder for
recognition; upstream: <https://github.com/zai-org/GLM-OCR>). SmartDocs is a *client* of a
GLM backend (it never imports GLM-OCR — incompatible deps — but shells out to its CLI in a
separate venv). **`GLM_OCR_MODE`** selects the backend; the platform-aware default is
`local_mlx` on macOS Apple Silicon and `disabled` on Windows/Linux.

| `GLM_OCR_MODE` | What serves the model | Works on | Status |
|---|---|---|---|
| `local_mlx` | `mlx_vlm.server` on this machine (`scripts/start_glm.sh`) | macOS Apple Silicon **only** | ✅ verified |
| `external_server` | vLLM / SGLang / a Mac's MLX server on another machine | any OS (client side) | ⚠️ implemented, unverified |
| `maas_api` | Zhipu MaaS cloud (`glmocr --mode maas`; needs `GLM_MAAS_API_KEY`) | any OS, internet | ⚠️ implemented, unverified |
| `ollama` | — | — | ❌ **reserved, not verified**; the adapter refuses it |
| `disabled` | — | any OS | ✅ (GLM off; other engines unaffected) |

On an unsupported combination the engine answers with a clear message (e.g. *"GLM local MLX
is only supported on macOS Apple Silicon. Use external_server, maas_api, or disable GLM."*)
— the app itself never fails because GLM is unavailable.

### 9a. `local_mlx` — local model server (Apple Silicon)

Fully offline once models are cached; **no cloud / no API key**.
**Start the model server once** (it holds the model resident between requests):

```bash
scripts/start_glm.sh -b       # serves mlx-community/GLM-OCR-bf16 on :8080 (wraps tools/glm_serve.sh)
```

Then pick **🧠 GLM OCR (Structured)** in the Engine dropdown and Run OCR. The adapter
health-checks `:8080` first and shows a clear error toast if the server is down (or a
*"still loading … retry"* note during a cold start).

**Config** (env, all optional — sensible defaults point at the vendored `GLM-OCR/`):
`GLM_OCR_DIR`/`GLM_ROOT`, `GLM_SDK_PYTHON`, `GLM_MLX_PYTHON`, `GLM_CONFIG_YAML`,
`GLM_OCR_API_URL` (default `http://localhost:8080`), `GLM_TIMEOUT` (default 300 s).

**How it runs**: `GLM_SDK_PYTHON -m glmocr.cli parse <img> --config mlx_config.yaml --mode
selfhosted --output <tmp>` with `HF_HUB_OFFLINE=1`. SmartDocs reads back `X.json` (regions,
coords normalised **0–1000** → scaled to pixels for the overlay), `X.md`, `layout_vis/` and
`imgs/`, and attaches `markdown / tables_html / layout_blocks / images (base64) / raw_json`.
`layout_native=True` so the geometric reconstruction is skipped.

### 9b. `external_server` — GLM served on another machine

Two protocol styles exist conceptually; **they do not share a request format**:

1. **`GLM_EXTERNAL_PROTOCOL=openai_compatible`** (SUPPORTED) —
   `http://<server>:8080/v1/chat/completions`, i.e. a vLLM / SGLang / mlx_vlm server
   hosting the GLM-OCR model. SmartDocs runs the same `glmocr --mode selfhosted` pipeline
   as `local_mlx` but points `pipeline.ocr_api.api_url` at the remote endpoint
   (`GLM_OCR_API_URL`; a bare base URL gets `/v1/chat/completions` appended). **Layout
   detection still runs locally** — `GLM-OCR/.venv-sdk` and the layout-model cache
   (`setup_glm.sh --precache-layout`) are required on the client; `.venv-mlx` is **not**.
   Extra knobs: `GLM_OCR_MODEL` (served model id — vLLM/SGLang require it),
   `GLM_OCR_API_KEY`, `GLM_OCR_VERIFY_SSL`.
2. **`GLM_EXTERNAL_PROTOCOL=sdk_server`** (RESERVED, not implemented) —
   `http://<server>:5002/glmocr/parse`, the glmocr SDK server (`GLM-OCR/glmocr/server.py`)
   which does layout **and** OCR remotely (no local GLM venv needed at all). The config
   structure is reserved; the adapter currently answers with a clear not-implemented
   message. TODO marker: `TODO(glm-sdk-server)` in `services/ocr_engines/glm_adapter.py`.

Server-side deployment (vLLM/SGLang on an NVIDIA-GPU Linux box) follows the upstream
GLM-OCR README — SmartDocs only needs the resulting URL.

### 9c. `maas_api` — Zhipu cloud API

`glmocr --mode maas` forwards the document to `GLM_MAAS_API_URL` (default: Zhipu's
`layout_parsing` endpoint) with `GLM_MAAS_API_KEY`/`ZHIPU_API_KEY`. No local models, no
local server — but internet and a paid key at OCR time. Implemented via the SDK's native
MaaS mode; not yet verified end-to-end from SmartDocs.

### 9d. `ollama` — reserved

The glmocr SDK has an `api_mode: ollama_generate` hook, but the integration is **not
verified in SmartDocs** — the mode is refused with a clear message rather than promised.
TODO marker: `TODO(glm-ollama)` in `services/ocr_engines/glm_adapter.py`
(`GLM_OLLAMA_BASE_URL` / `GLM_OLLAMA_MODEL` are reserved for it).

---

## 10. Result viewer — four artifact-driven tabs

The OCR result pane (right side) exposes four tabs, enabled/disabled by what the engine produced:

1. **📝 Markdown** — rendered markdown (default). Real markdown for GLM/Modern; for
   Legacy/VietOCR the plain text is rendered as markdown.
2. **⟨⟩ Raw** — the editable markdown/text source. This is the canonical edit surface; the
   send-to actions use it. Copy / Download `.md`.
3. **🖼 Images** — the **Extracted Images** gallery: GLM's `layout_vis` overlay + cropped
   regions; Modern's labelled reading-order overlay. Disabled when the engine has no images
   (the interactive box overlay in the left pane still works for all engines).
4. **{ } JSON** — the structured per-page OCR output. Copy / Download `.json`.

**Math (LaTeX) rendering**: GLM/Modern emit LaTeX (`$…$`, `$$…$$`, `\(…\)`, `\[…\]`).
The rendered-Markdown tab typesets it with **KaTeX** (vendored offline at
`static/vendor/katex/`, matching GLM-OCR's own Gradio UI). Because `marked` has no math
support *and* collapses the `\\` row breaks used by `\begin{array}`/matrices/aligned, math is
rendered with KaTeX **before** `marked` tokenizes (swapped for sentinels, restored after
sanitize). Math is gated on *real* markdown, so a bare `$` in plain-text engines (currency)
is never mistaken for inline math.

**Layout**: the result panel is the primary focus — the OCR workspace split is
`minmax(280px,38fr) minmax(420px,62fr)` (image ≈38% / results ≈62%), and the rendered-Markdown
pane flows with the panel's own scroll instead of a short inner scroll box, so long
math/markdown/table documents stay readable. Wide display equations scroll horizontally inside
the pane.

**Downstream**: viewing a Markdown tab sends markdown (when real markdown exists) to
Correct/Translate/Summarize; otherwise plain text — backward compatible. The plain-text `ocr`
artifact feeding chat/RAG is unchanged. New persisted artifacts: `ocr_json`, `ocr_images`
(base64, served lazily via `GET /api/documents/<id>/ocr-images`, excluded from the bulk text API).
