# SmartDocs-Agent — Architecture Diagrams

> Mermaid diagrams reflecting the **current implementation** as documented in [ARCHITECTURE.md](./ARCHITECTURE.md). These are not idealized designs — each diagram maps to code that exists today. Notably: the agent has **no skill-selection layer** (skills are implemented but disabled in the live HTTP loop), the `ocr` tool is **excluded** from the agent's reachable toolset, RAG uses **no score threshold and no reranker**, and `/api/correct` output is **not persisted** as a document artifact.

---

## 1. Overall System Architecture

```mermaid
flowchart TB
  subgraph FE["Frontend — vanilla JS, no build step"]
    direction TB
    SPA["Main SPA<br/>index.html · app.js · chat.js · ocr-canvas.js · i18n.js"]
    AGUI["Agent workspace<br/>agent.html · agent.js"]
    ADMUI["Admin console (Jinja)<br/>templates/admin/*"]
  end

  subgraph BE["Flask backend — single process (app.py)"]
    direction TB
    AUTH["auth_bp<br/>/login · /api/auth/me"]
    ADM["admin_bp<br/>/admin/*"]
    APPR["app.py routes<br/>/api/upload · /api/ocr/* · /api/documents/*"]
    CB["chat_bp<br/>/api/chat/*"]
    AB["agent_bp<br/>/api/agent/*"]
  end

  subgraph OCR["OCR pipeline (services/)"]
    direction TB
    SOS["smart_ocr_service / ocr_service"]
    RT["router"]
    E1["Legacy PaddleOCR (PP-OCRv5)"]
    E2["PaddleOCR Modern (PP-StructureV3)"]
    E3["VietOCR (images only)"]
    E4["GLM-OCR (subprocess)"]
    GEO["layout / geometry / markdown_normalize"]
  end
  MLX["GLM MLX server<br/>localhost:8080"]

  subgraph AISVC["AI services (services/)"]
    direction TB
    CORR["correction_service"]
    TRAN["translate_service (Google / Argos)"]
    SUMM["summary_service (TF-IDF / PhoBERT / AI-rewrite)"]
    REW["ai_rewrite_service (local Qwen)"]
  end

  subgraph RAG["Chat / RAG (services/chat_service.py)"]
    direction TB
    CS["chat_service.chat()"]
    EE["EmbeddingEngine<br/>SBERT → Hashing fallback"]
    IDX["In-memory index per file_id<br/>FAISS IndexFlatIP"]
    QWEN["Qwen chat model (local)"]
  end

  subgraph AGENT["Agent (agent/)"]
    direction TB
    AC["AgentCore — reasoning loop"]
    TOOLS["Tool registry (safe set)<br/>chat · knowledge_search · summarize · translate · correct"]
    KN["Knowledge — DocumentKnowledge"]
    MEM["Memory — ConversationMemory"]
  end

  subgraph LLM["Agent LLM providers (FallbackProvider)"]
    direction LR
    GROQ["Groq"] --> GEM["Gemini"] --> LQ["Local Qwen"]
  end

  DB[("SQLite — paddleocr.db<br/>models.py")]

  SPA --> AUTH & APPR & CB
  AGUI --> AB
  ADMUI --> ADM

  APPR --> SOS --> RT --> E1 & E2 & E3 & E4
  E4 --> MLX
  SOS --> GEO
  APPR --> AISVC
  APPR -->|"save_artifact + index_document_async"| DB
  APPR --> CS

  CB --> CS
  CS --> EE --> IDX
  CS --> QWEN
  CS --> DB

  AB --> AC
  AC --> TOOLS
  AC --> MEM --> DB
  AC -->|"provider chain"| LLM
  TOOLS --> CS
  TOOLS --> KN --> CS
  TOOLS --> AISVC
  AB --> DB
  ADM --> DB
```

**Explanation.** A single-process Flask monolith serves two front ends (the main hash-routed SPA and a standalone `/agent` page) plus a Jinja admin console. Four blueprints route to in-process service modules. The only out-of-process dependency is GLM-OCR, which runs as a subprocess that talks to a local MLX server on `:8080`. The agent reuses the same OCR/AI/RAG services through tools rather than duplicating them, and all state persists to one SQLite database.

---

## 2. OCR Processing Pipeline

```mermaid
flowchart LR
  UP["POST /api/upload<br/>UUID filename · extension allowlist"] --> DOC["Document row<br/>status = uploaded"]
  DOC --> REQ["POST /api/ocr/all or /api/ocr/page"]
  REQ --> OWN["_resolve_owned_file<br/>ownership / IDOR guard"]
  OWN --> ENG["Engine OCR via router<br/>Legacy / Modern / VietOCR / GLM"]
  ENG --> NAT{"layout_native?"}
  NAT -->|"no (Legacy, VietOCR)"| GEO["geometry / layout<br/>reading-order reconstruction"]
  NAT -->|"yes (Modern, GLM)"| AIQ
  GEO --> AIQ{"apply_ai?"}
  AIQ -->|"yes"| CLEAN["Qwen line cleanup<br/>(smart mode, safety-gated; text only)"]
  AIQ -->|"no"| STORE
  CLEAN --> STORE["save_artifact<br/>ocr · ocr_layout · ocr_markdown/html/tables/blocks/json/images"]
  STORE --> IDX["index_document_async<br/>(canonical 'ocr' text)"]
  IDX --> RIDX["In-memory RAG index"]
  STORE --> LIB["Document Library<br/>GET /api/documents (artifact_kinds badges)"]
```

**Explanation.** Upload stores the file under a server-generated UUID and creates a `Document`. OCR runs through the engine router; only engines that are **not** `layout_native` get geometric re-ordering. The optional "smart" AI pass corrects recognized text lines but never alters boxes/structure. Results upsert into `document_artifacts` (one row per kind), the canonical text is asynchronously indexed for RAG, and the Document Library surfaces which artifact kinds exist.

---

## 3. Document Lifecycle

```mermaid
flowchart TB
  U["Upload"] --> D["Document<br/>status = uploaded"]
  D --> O["OCR<br/>status = ocr_done"]
  D --> R["read-text (TXT/DOCX/PDF)"]

  O --> AO["artifact: ocr (+ ocr_layout + structured)"]
  R --> AT["artifact: text"]
  AO -->|"RAG indexed"| RAGI["in-memory index"]
  AT -->|"RAG indexed"| RAGI

  AO --> C["Correction · POST /api/correct"]
  C -.->|"transient — NOT a document artifact"| CX["returned to UI only"]

  AO --> T["Translate · POST /api/translate"]
  T --> ATR["artifact: translation<br/>(only if file_id; NOT RAG-indexed)"]

  AO --> S["Summarize · POST /api/summarize"]
  S --> ASU["artifact: summary"]

  subgraph STORE["document_artifacts — one row per document + kind"]
    direction TB
    AO
    AT
    ATR
    ASU
  end
```

**Explanation.** A document accumulates persisted artifacts keyed by `(document_id, kind)`. OCR and read-text outputs are both RAG-indexed. Translation persists only when a `file_id` is supplied and is **not** indexed; summary persists. **Correction is a transient text transform** — it returns to the UI but has no `document_artifacts` kind, so it is never stored.

---

## 4. RAG Architecture

```mermaid
flowchart TB
  Q["User question<br/>/api/chat/send or knowledge_search tool"] --> MODE{"mode == general?"}
  MODE -->|"yes"| NORAG["No retrieval"]
  MODE -->|"no"| RET["retrieve_chunks(query, file_id?, allowed_file_ids)"]

  RET --> EMB["EmbeddingEngine.embed(query)<br/>SBERT → Hashing fallback · L2-normalized"]
  EMB --> SEL["Select target indexes<br/>single file_id OR all owned ∩ allowed_file_ids"]
  SEL --> SRCH["Per-index search<br/>FAISS IndexFlatIP (inner product = cosine)"]
  SRCH --> RANK["Union + sort by score + top_k = 5<br/>NO threshold · NO reranker"]

  RANK --> CTX["Context assembly · _build_chat_prompt<br/>MAX_CTX_CHARS = 3000 + token-budget fit"]
  NORAG --> CTX2["Plain assistant prompt (no context)"]
  CTX --> GEN["Qwen chat model · _run_inference"]
  CTX2 --> GEN
  GEN --> ANS["Answer"]

  RANK --> CITE["Sources / citations<br/>{file_id, score, excerpt}"]
  ANS --> OUT["Chat result"]
  CITE --> OUT
```

**Explanation.** Retrieval is skipped entirely in `general` mode. Otherwise the query is embedded, the candidate index set is scoped by `allowed_file_ids` (tenancy), each index is searched via inner-product over L2-normalized vectors (cosine), and the union is sorted and truncated to `top_k = 5` — with **no similarity threshold and no second-stage reranking**. The fitted context drives the local Qwen model; sources are derived directly from the retrieved chunks.

---

## 5. Agent Architecture *(current implementation — tool orchestration, no skill layer)*

```mermaid
flowchart TB
  U["User · /agent"] -->|"POST /api/agent/run"| AB["agent_bp.agent_run<br/>ownership · lazy session · load history<br/>inject scoped doc context · set allowed_file_ids"]
  AB --> AC["AgentCore.run()"]
  AC --> PLAN["Planning pass (optional)<br/>1–3 sentence advisory plan"]
  PLAN --> PROV["Provider.complete(messages)"]
  PROV --> PARSE["_extract_json(raw) → one JSON action"]
  PARSE --> DISP{"action type"}
  DISP -->|"{final} or non-JSON"| FIN["Final answer + citations (≤5)"]
  DISP -->|"{tool, arguments}"| REG["ToolRegistry.run(name, args)"]
  REG --> OBS["Append tool observation as user turn"]
  OBS -->|"loop ≤ max_steps (1–6, default 4)"| PROV
  OBS -.->|"steps exhausted"| SYN["Synthesis pass"] --> FIN

  REG -.->|"dispatches one of"| TOOLS
  subgraph TOOLS["Reachable tools — _SAFE_TOOL_NAMES (no skill-selection layer)"]
    direction TB
    T_CHAT["chat → chat_service.chat (RAG)"]
    T_KN["knowledge_search → DocumentKnowledge → retrieve_chunks"]
    T_SUM["summarize → summary_service"]
    T_TR["translate → translate_service"]
    T_CO["correct → correction_service"]
  end

  PROV -.->|"via"| PROVS
  subgraph PROVS["FallbackProvider — priority order"]
    direction LR
    GROQ["Groq"] --> GEM["Gemini"] --> LQ["Local Qwen"]
  end

  T_CHAT -. "allowed_file_ids injected by server" .-> SCOPE["Tenancy scope<br/>(LLM never chooses it)"]
  T_KN -. "allowed_file_ids injected by server" .-> SCOPE

  AB -.->|"upload path, NOT the LLM loop"| OCRX
  subgraph OCRX["OCR is NOT an agent LLM tool"]
    direction TB
    O1["OcrTool exists in the full registry but is<br/>EXCLUDED from the agent's safe registry"]
    O2["OCR runs via agent upload → /api/ocr/all<br/>→ /api/agent/ingest (recorded as a session turn)"]
  end

  FIN --> DEST["results.py → deep-links<br/>#ocr / #summarize / #chat"]
```

**Explanation.** `AgentCore` runs an iterative ReAct-style loop: an optional advisory planning call, then up to `max_steps` cycles of *LLM completion → parse one JSON action → dispatch a tool → feed the observation back*, ending on a `{final}` action or a synthesis pass once steps are exhausted. There is **no skill-selection layer** — skills exist in code but the live agent is built with an empty skill registry, so it orchestrates the five safe tools directly. The path-based **`ocr` tool is deliberately excluded** from the agent's reach; OCR happens through the upload/ingest flow instead. `allowed_file_ids` is injected by the server for the `chat` and `knowledge_search` tools, so the model can never widen its own data scope. Each completion goes through the Groq→Gemini→Local-Qwen fallback chain.

---

## 6. Database ER Diagram

```mermaid
erDiagram
  users ||--o{ documents : "owns"
  users ||--o{ chat_conversations : "owns · CASCADE"
  users ||--o{ agent_conversations : "owns · CASCADE"
  users ||--o{ activity_logs : "logs · SET NULL"
  documents ||--o{ document_artifacts : "has · CASCADE"
  documents ||--o{ chat_conversations : "scopes · SET NULL"
  chat_conversations ||--o{ chat_messages : "contains · CASCADE"
  agent_conversations ||--o{ agent_messages : "contains · CASCADE"
  agent_conversations ||--o{ agent_artifacts : "refs · CASCADE"
  agent_messages ||--o{ agent_artifacts : "refs · CASCADE"

  users {
    int id PK
    string username UK
    string email UK
    string password_hash
    string role "admin | user"
    bool is_active
  }
  documents {
    int id PK
    int user_id FK
    string file_id UK "UUID"
    string filename
    string file_type
    int page_count
    string status "uploaded | ocr_done"
  }
  document_artifacts {
    int id PK
    int document_id FK
    string kind "unique per (document_id, kind)"
    text content
    string meta
  }
  chat_conversations {
    int id PK
    int user_id FK
    int document_id FK "nullable"
    string title
    string last_mode
  }
  chat_messages {
    int id PK
    int conversation_id FK
    string role
    text content
    text sources "JSON citations"
    string mode
    string engine_used
  }
  agent_conversations {
    int id PK
    int user_id FK
    string title
  }
  agent_messages {
    int id PK
    int conversation_id FK
    string role
    text content
    text tool_calls "JSON tool names"
    string provider
  }
  agent_artifacts {
    int id PK
    int conversation_id FK
    int message_id FK "nullable"
    string kind "source | result"
    string module
    string route "SPA hash"
    string file_id
    string label
  }
  activity_logs {
    int id PK
    int user_id FK "nullable"
    string action
    string detail
    string ip_address
  }
```

**Explanation.** Nine tables, confirmed against the live schema. Documents own cascade-deleting `document_artifacts` (with a unique `(document_id, kind)` constraint). Chat and agent conversations are independent message trees. **There is no citations table**: chat citations live as JSON in `chat_messages.sources`, and `agent_artifacts` holds lightweight *references* (module + SPA route + label) back into the real artifacts. ORM-level cascades are the reliable delete path (DB-level `ON DELETE` only fires if SQLite `PRAGMA foreign_keys=ON`).

---

## 7. Security Architecture

```mermaid
flowchart TB
  REQ["Incoming HTTP request"] --> L1

  subgraph L1["1 · Authentication — Flask-Login"]
    A1["@login_required (session cookie)<br/>Werkzeug password hashing<br/>401 JSON or redirect /login on failure"]
  end
  L1 --> L2

  subgraph L2["2 · Authorization"]
    B1["role = admin | user<br/>@admin_required on /admin/* and admin API"]
  end
  L2 --> L3

  subgraph L3["3 · Ownership validation"]
    C1["_resolve_owned_file(file_id):<br/>file_id → Document → owner-or-admin check<br/>glob disk by STORED UUID (no path traversal)"]
  end
  L3 --> L4

  subgraph L4["4 · Document access control"]
    D1["lists + artifacts scoped to current_user<br/>admins see all"]
  end
  L4 --> L5

  subgraph L5["5 · Retrieval scope enforcement"]
    E1["allowed_file_ids passed into retrieve_chunks<br/>None = admin (unrestricted)"]
    E2["Agent: allowed_file_ids INJECTED by server<br/>never chosen by the LLM"]
    E3["Defense in depth: chat / knowledge tools<br/>drop a file_id the caller does not own"]
  end
  L5 --> SVC["Service / data access"]
```

**Explanation.** Every request passes through layered gates. Authentication is session-based; authorization is a simple `role` check. Ownership is enforced by resolving a `file_id` to an owned `Document` and globbing disk only by the **server-stored UUID**, which closes IDOR and path-traversal. Listings and retrieval are scoped to the caller's documents, and the agent path injects the allowed scope server-side (the model cannot pick `file_id`s), with tool-level guards as a backstop.

---

## 8. Chat Modes Architecture

```mermaid
flowchart TB
  subgraph G["General Chat"]
    direction TB
    G1["chat_bp · /api/chat/send (mode = general)"]
    G2["chat_service.chat() — NO retrieval"]
    G3["Qwen chat model"]
    G1 --> G2 --> G3
  end

  subgraph D["Document Chat"]
    direction TB
    D1["chat_bp · /api/chat/send (mode = doc_current / doc_all)"]
    D2["retrieve_chunks() — RAG, scoped to owned file_ids"]
    D3["chat_service.chat() — context-grounded prompt"]
    D4["Qwen chat model"]
    D1 --> D2 --> D3 --> D4
  end

  subgraph A["Agent"]
    direction TB
    A1["agent_bp · /api/agent/run"]
    A2["AgentCore loop (plan + tools)"]
    A3["Providers: Groq → Gemini → Local Qwen"]
    A4["tools: chat (RAG) · knowledge_search · summarize · translate · correct"]
    A1 --> A2 --> A3
    A2 --> A4
  end

  SHARED["Shared: chat_service · EmbeddingEngine · in-memory index"]
  D2 --> SHARED
  A4 --> SHARED

  CMSG[("chat_messages<br/>(+ sources JSON)")]
  AMSG[("agent_messages + agent_artifacts")]
  G3 --> CMSG
  D4 --> CMSG
  A2 --> AMSG
```

**Explanation.** Three distinct surfaces share infrastructure but differ in behavior and persistence. **General Chat** does no retrieval and answers from the local Qwen model alone. **Document Chat** adds scoped RAG retrieval before the same local model and stores citations as JSON on the message. **Agent** is the only orchestrating surface — it runs through the multi-provider fallback chain and can invoke multiple tools (its `chat` tool itself reuses the Document-Chat RAG path), persisting turns and lightweight artifact references to the separate `agent_*` tables.
