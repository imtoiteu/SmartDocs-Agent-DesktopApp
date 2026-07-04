# SmartDocs-Agent — Architecture Diagrams (Draw.io)

Editable Draw.io sources + publication SVGs for the architecture documented in
[`../ARCHITECTURE.md`](../ARCHITECTURE.md) and [`../ARCHITECTURE-DIAGRAMS.md`](../ARCHITECTURE-DIAGRAMS.md).
Every diagram reflects the **current implementation** (grounded in source), not an idealized design.

## Files

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
