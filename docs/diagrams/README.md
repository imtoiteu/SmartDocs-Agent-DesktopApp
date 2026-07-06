# SmartDocs-Agent — Architecture Diagrams (Draw.io)

Editable Draw.io sources + publication SVGs for the architecture documented in
[`../ARCHITECTURE.md`](../ARCHITECTURE.md) and [`../ARCHITECTURE-DIAGRAMS.md`](../ARCHITECTURE-DIAGRAMS.md).
Every diagram reflects the **current implementation** (grounded in source), not an idealized design.

## DesktopApp diagram set (tiếng Việt)

Bộ sơ đồ **DesktopApp hiện tại** (Tauri shell · UI gateway · 3 chế độ runtime ·
Model Router · Local-only), nhãn tiếng Việt, dùng cho báo cáo/tài liệu kỹ thuật.
Nguồn sinh: `build_desktop_diagrams.py` (chạy `python3 build_desktop_diagrams.py`
để tạo lại cả `.drawio` + `.svg`).

| # | Sơ đồ | Editable | Publication |
|---|-------|----------|-------------|
| D1 | Kiến trúc tổng thể DesktopApp | `desktop-overall-architecture.drawio` | `desktop-overall-architecture.svg` |
| D2 | Ba chế độ Backend Runtime | `desktop-runtime-architecture.drawio` | `desktop-runtime-architecture.svg` |
| D3 | Kiến trúc triển khai (mô hình client) | `desktop-deployment.drawio` | `desktop-deployment.svg` |
| D4 | Luồng chọn & khởi động runtime | `desktop-runtime-selection-flow.drawio` | `desktop-runtime-selection-flow.svg` |
| D5 | UI Gateway — luồng xử lý yêu cầu | `desktop-gateway-flow.drawio` | `desktop-gateway-flow.svg` |
| D6 | Model Registry & Router theo tác vụ | `desktop-model-routing.drawio` | `desktop-model-routing.svg` |
| D7 | Local-only · khóa API · chính sách URL | `desktop-privacy-local-only.drawio` | `desktop-privacy-local-only.svg` |
| D8 | Vòng đời tài liệu (OCR → chat trích dẫn) | `desktop-document-flow.drawio` | `desktop-document-flow.svg` |
| D9 | Luồng thực thi Agent | `desktop-agent-flow.drawio` | `desktop-agent-flow.svg` |

## Bản tiếng Việt của các sơ đồ backend chung (hậu tố `-vi`)

Bản dịch tiếng Việt 1-1 của các sơ đồ backend bên dưới, cùng bố cục với bản gốc
(sinh bởi `build_diagrams_vi.py` — chạy `python3 build_diagrams_vi.py` để tạo lại).
Định danh mã nguồn (route, module, bảng CSDL) giữ nguyên; chỉ dịch phần mô tả.
Hai sơ đồ được **cập nhật theo hiện trạng** trong lúc dịch:

* `backend-architecture-vi` — app hiện đăng ký **6 blueprint**
  (auth · admin · chat · agent · settings · models, `app.py:84-89`).
* `provider-fallback-chain-vi` — **vẽ lại hoàn toàn**: bổ sung provider
  self-hosted (OpenAI-compatible) và chế độ Local-only mà bản gốc chưa có.

| Sơ đồ tiếng Việt | Bản gốc tiếng Anh tương ứng |
|------------------|------------------------------|
| `ocr-pipeline-vi.drawio` / `.svg` | #2 |
| `document-lifecycle-vi.drawio` / `.svg` | #3 |
| `rag-architecture-vi.drawio` / `.svg` | #4 |
| `database-erd-vi.drawio` / `.svg` | #6 |
| `security-architecture-vi.drawio` / `.svg` | #7 |
| `chat-modes-vi.drawio` / `.svg` | #8 |
| `use-case-diagram-vi.drawio` / `.svg` | #9 |
| `functional-decomposition-vi.drawio` / `.svg` | #10 |
| `document-chat-sequence-vi.drawio` / `.svg` | #12 |
| `ocr-engine-architecture-vi.drawio` / `.svg` | #14 |
| `correction-flow-vi.drawio` / `.svg` | #15 |
| `translation-flow-vi.drawio` / `.svg` | #16 |
| `summarization-flow-vi.drawio` / `.svg` | #17 |
| `rag-runtime-flow-vi.drawio` / `.svg` | #18 |
| `provider-fallback-chain-vi.drawio` / `.svg` | #21 (vẽ lại) |
| `context-diagram-vi.drawio` / `.svg` | Context Diagram |
| `dfd-level-1-vi.drawio` / `.svg` | DFD Level 1 |
| `backend-architecture-vi.drawio` / `.svg` | Backend Architecture |
| `full-component-architecture-vi.drawio` / `.svg` | Appendix |

Không dịch (giữ bản tiếng Anh): `overall-system-architecture` (đã được thay thế
bởi D1/W1), `deployment-diagram` (triển khai WebApp production — bản desktop xem D3),
và bộ agent chi tiết `agent-architecture` / `agent-execution-flow` /
`agent-execution-sequence` / `agent-tool-ecosystem` (vẫn đúng hiện trạng;
luồng agent bản tiếng Việt xem D9). Lưu ý: `provider-fallback-chain` (bản gốc EN)
và mục Providers trong `agent-architecture`/`overall-system-architecture` chưa có
self-hosted + Local-only — xem bản `-vi` / D6 / W2 cho hiện trạng.

## Files (backend chung — nhãn tiếng Anh, bản gốc)

| # | Diagram | Editable | Publication |
|---|---------|----------|-------------|
| 1 | Overall System Architecture | `overall-system-architecture.drawio` | `overall-system-architecture.svg` |
| 2 | OCR Processing Pipeline | `ocr-pipeline.drawio` | `ocr-pipeline.svg` |
| 3 | Document Lifecycle | `document-lifecycle.drawio` | `document-lifecycle.svg` |
| 4 | RAG Architecture | `rag-architecture.drawio` | `rag-architecture.svg` |
| 5 | Agent Architecture (tool orchestration, no skill layer) | `agent-architecture.drawio` | `agent-architecture.svg` |
| 6 | Database ER Diagram | `database-erd.drawio` | `database-erd.svg` |
| 7 | Security Architecture | `security-architecture.drawio` | `security-architecture.svg` |
| 8 | Chat Modes Architecture | `chat-modes.drawio` | `chat-modes.svg` |
| 9 | Use Case Diagram | `use-case-diagram.drawio` | `use-case-diagram.svg` |
| 10 | Functional Decomposition | `functional-decomposition.drawio` | `functional-decomposition.svg` |
| 11 | Deployment Diagram (production) | `deployment-diagram.drawio` | `deployment-diagram.svg` |
| 12 | Document Chat — Sequence | `document-chat-sequence.drawio` | `document-chat-sequence.svg` |
| 13 | Agent Execution — Sequence | `agent-execution-sequence.drawio` | `agent-execution-sequence.svg` |
| 14 | OCR Engine Architecture | `ocr-engine-architecture.drawio` | `ocr-engine-architecture.svg` |
| 15 | Correction Flow | `correction-flow.drawio` | `correction-flow.svg` |
| 16 | Translation Flow | `translation-flow.drawio` | `translation-flow.svg` |
| 17 | Summarization Flow | `summarization-flow.drawio` | `summarization-flow.svg` |
| 18 | RAG Runtime & Index Lifecycle | `rag-runtime-flow.drawio` | `rag-runtime-flow.svg` |
| 19 | Agent Execution Flow (AgentCore.run) | `agent-execution-flow.drawio` | `agent-execution-flow.svg` |
| 20 | Agent Tool Ecosystem | `agent-tool-ecosystem.drawio` | `agent-tool-ecosystem.svg` |
| 21 | Provider Fallback Chain | `provider-fallback-chain.drawio` | `provider-fallback-chain.svg` |
| — | **Appendix** · Full Component Architecture (file/module level) | `full-component-architecture.drawio` | `full-component-architecture.svg` |

Diagrams 1–21 are report-friendly (landscape, fit A4). The appendix is high-detail
and is best printed on **A3** or A4-landscape; the SVG is vector, so it stays crisp at any zoom.
Diagrams 12–13 are UML **sequence diagrams** (lifelines, messages, and `alt`/`opt`/`loop`
fragments); 14–21 are implementation flows for the OCR engines, AI services (correction /
translation / summarization), RAG runtime, agent execution & tools, and the provider chain.
They mirror the descriptions in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) and
[`../ARCHITECTURE-DIAGRAMS.md`](../ARCHITECTURE-DIAGRAMS.md).

## Editing

Open any `.drawio` in **[app.diagrams.net](https://app.diagrams.net)** or the **Draw.io desktop app**
(`brew install --cask drawio`). Containers are real swimlanes, tables are grouped cells, and nodes
are individually movable. After editing, re-export the SVG from the app via **File → Export as → SVG**
(the desktop GUI renders text natively — crisp and selectable).

## Regenerating

The diagrams are produced from a single layout model so the `.drawio` and `.svg` stay in sync:

```bash
python3 build_diagrams.py     # re-emits all 14 .drawio + 14 .svg
```

The generated `.svg` uses native vector `<text>` (small, crisp, A4/A3 printable).

> Note: the headless Draw.io CLI (`drawio -x -f svg ...`) **rasterizes label text into embedded
> PNGs** on this machine, producing large files with non-selectable text. Prefer the generator's
> SVG (or the desktop GUI export) for publication output.

## Color legend

| Layer | Color |
|-------|-------|
| Frontend | blue |
| Flask backend / blueprints | indigo |
| OCR pipeline | teal |
| AI services | orange |
| Chat / RAG | green |
| Agent | purple |
| LLM providers | yellow |
| Database | gray |
| Security / exclusions | red |
| External (GLM MLX) | light gray |
