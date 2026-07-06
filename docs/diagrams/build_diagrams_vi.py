#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vietnamese editions of the shared-backend diagrams (suffix ``-vi``).

Reuses build_diagrams.py: each English diagram is rebuilt with its EXACT
proven layout, then every label/title/row is mapped through a translation
table — so the ``-vi`` files stay in visual sync with the English originals.
Code identifiers (routes, module/class/table names, config keys) are kept
verbatim; only descriptive text is translated.

Two facts are also brought up to date while translating:
  * backend-architecture: the app now registers SIX blueprints
    (auth · admin · chat · agent · settings · models — app.py:84-89).
  * provider-fallback-chain: fully REDRAWN (not just translated) — the old
    diagram predates the self-hosted OpenAI-compatible provider and the
    Local-only privacy mode.

Run:  python3 build_diagrams_vi.py
"""
import os

import build_diagrams as B

OUT = os.path.dirname(os.path.abspath(__file__))


def write(d):
    with open(os.path.join(OUT, d.name + '.drawio'), 'w', encoding='utf-8') as f:
        f.write(B.render_drawio(d))
    with open(os.path.join(OUT, d.name + '.svg'), 'w', encoding='utf-8') as f:
        f.write(B.render_svg(d))
    print('wrote', d.name + '.drawio', '+', d.name + '.svg', '(%dx%d)' % (d.w, d.h))


# ── titles ────────────────────────────────────────────────────────────────────
VI_TITLES = {
    'ocr-pipeline': '2 · Quy trình xử lý OCR',
    'document-lifecycle': '3 · Vòng đời tài liệu',
    'rag-architecture': '4 · Kiến trúc RAG',
    'database-erd': '6 · Sơ đồ quan hệ CSDL (SQLite · paddleocr.db)',
    'security-architecture': '7 · Kiến trúc bảo mật (thực thi theo lớp)',
    'chat-modes': '8 · Kiến trúc các chế độ Chat',
    'use-case-diagram': '9 · Sơ đồ Use Case',
    'functional-decomposition': '10 · Phân rã chức năng',
    'document-chat-sequence': '12 · Chat tài liệu — Sơ đồ tuần tự',
    'ocr-engine-architecture': '14 · Kiến trúc engine OCR',
    'correction-flow': '15 · Luồng sửa lỗi',
    'translation-flow': '16 · Luồng dịch thuật',
    'summarization-flow': '17 · Luồng tóm tắt',
    'rag-runtime-flow': '18 · RAG runtime & vòng đời chỉ mục',
    'context-diagram': 'Sơ đồ ngữ cảnh (Mức 0)',
    'dfd-level-1': 'Sơ đồ luồng dữ liệu — Mức 1',
    'backend-architecture': 'Kiến trúc Backend',
    'full-component-architecture': 'Phụ lục · Kiến trúc thành phần đầy đủ (mức file & module)',
}

# ── label translations (exact-string map; untouched = code identifiers) ───────
VI = {
    # generic edge labels
    'yes': 'có', 'no': 'không',

    # 2 · ocr-pipeline
    'POST /api/upload\nUUID filename · ext allowlist': 'POST /api/upload\ntên file UUID · allowlist đuôi file',
    'Document row\nstatus = uploaded': 'Bản ghi Document\nstatus = uploaded',
    'POST /api/ocr/all\nor /api/ocr/page': 'POST /api/ocr/all\nhoặc /api/ocr/page',
    '_resolve_owned_file\nownership / IDOR guard': '_resolve_owned_file\nkiểm tra sở hữu / chống IDOR',
    'Engine OCR via router\nLegacy / Modern / VietOCR / GLM': 'Engine OCR qua router\nLegacy / Modern / VietOCR / GLM',
    'geometry / layout\nreading-order reconstruction\n(Legacy, VietOCR)':
        'geometry / layout\nkhôi phục thứ tự đọc\n(Legacy, VietOCR)',
    'Qwen line cleanup\n(smart mode · safety-gated · text only)':
        'Dọn dòng bằng Qwen\n(chế độ smart · có cổng an toàn · chỉ text)',
    'yes (Modern, GLM)': 'có (Modern, GLM)',
    'index_document_async\ncanonical "ocr" text': 'index_document_async\nvăn bản "ocr" chuẩn',
    'In-memory RAG index': 'Chỉ mục RAG trong bộ nhớ',
    'Document Library\nGET /api/documents (artifact_kinds badges)':
        'Thư viện tài liệu\nGET /api/documents (nhãn artifact_kinds)',

    # 3 · document-lifecycle
    'Upload': 'Tải lên',
    'Document\nstatus = uploaded': 'Tài liệu\nstatus = uploaded',
    'read-text\nTXT / DOCX / PDF': 'Đọc văn bản (read-text)\nTXT / DOCX / PDF',
    'document_artifacts  —  one row per (document_id, kind)':
        'document_artifacts — mỗi (document_id, kind) một bản ghi',
    'kind: translation\n(only if file_id · NOT indexed)': 'kind: translation\n(chỉ khi có file_id · KHÔNG index)',
    'indexed': 'được index',
    'Correction\nPOST /api/correct': 'Sửa lỗi\nPOST /api/correct',
    'returned to UI only': 'chỉ trả về UI',
    'transient — NOT an artifact': 'tạm thời — KHÔNG lưu artifact',
    'Translate\nPOST /api/translate': 'Dịch\nPOST /api/translate',
    'Summarize\nPOST /api/summarize': 'Tóm tắt\nPOST /api/summarize',

    # 4 · rag-architecture
    'User question\n/api/chat/send  or  knowledge_search tool':
        'Câu hỏi của người dùng\n/api/chat/send hoặc tool knowledge_search',
    'EmbeddingEngine.embed(query)\nSBERT → Hashing fallback · L2-normalized':
        'EmbeddingEngine.embed(query)\nSBERT → dự phòng Hashing · chuẩn hóa L2',
    'Select target indexes\nsingle file_id OR all owned ∩ allowed_file_ids':
        'Chọn chỉ mục đích\nmột file_id HOẶC tất cả sở hữu ∩ allowed_file_ids',
    'Per-index search\nFAISS IndexFlatIP (inner product = cosine)':
        'Tìm trên từng chỉ mục\nFAISS IndexFlatIP (tích trong = cosine)',
    'Union + sort by score + top_k = 5\nNO threshold · NO reranker':
        'Gộp + sắp theo điểm + top_k = 5\nKHÔNG ngưỡng · KHÔNG reranker',
    'No retrieval (plain assistant prompt)': 'Không truy hồi (prompt trợ lý thuần)',
    'Context assembly · _build_chat_prompt\nMAX_CTX_CHARS = 3000 + token-budget fit':
        'Ghép ngữ cảnh · _build_chat_prompt\nMAX_CTX_CHARS = 3000 + vừa ngân sách token',
    'Qwen chat model\n_run_inference': 'Model chat Qwen\n_run_inference',
    'Answer': 'Câu trả lời',
    'Sources / citations\n{file_id, score, excerpt}': 'Nguồn / trích dẫn\n{file_id, score, excerpt}',
    'from retrieved chunks': 'từ các đoạn truy hồi',

    # 6 · database-erd (edge labels only — schema stays verbatim)
    'owns 1→*': 'sở hữu 1→*',
    'owns · CASCADE': 'sở hữu · CASCADE',
    'has · CASCADE': 'có · CASCADE',
    'scopes · SET NULL': 'giới hạn phạm vi · SET NULL',

    # 7 · security-architecture
    'Incoming HTTP request': 'Yêu cầu HTTP đến',
    '1 · Authentication — Flask-Login': '1 · Xác thực — Flask-Login',
    '@login_required (session cookie) · Werkzeug password hashing · 401 JSON or redirect /login on failure':
        '@login_required (cookie phiên) · băm mật khẩu Werkzeug · thất bại → 401 JSON hoặc chuyển hướng /login',
    '2 · Authorization': '2 · Phân quyền',
    'role = admin | user · @admin_required on /admin/* and admin API':
        'role = admin | user · @admin_required cho /admin/* và API quản trị',
    '3 · Ownership validation': '3 · Kiểm tra quyền sở hữu',
    '_resolve_owned_file(file_id): file_id → Document → owner-or-admin check · glob disk by STORED UUID (no path traversal)':
        '_resolve_owned_file(file_id): file_id → Document → kiểm tra chủ sở hữu / admin · glob đĩa theo UUID ĐÃ LƯU (không path traversal)',
    '4 · Document access control': '4 · Kiểm soát truy cập tài liệu',
    'lists + artifacts scoped to current_user · admins see all':
        'danh sách + artifact giới hạn theo current_user · admin thấy tất cả',
    '5 · Retrieval scope enforcement': '5 · Thực thi phạm vi truy hồi',
    'allowed_file_ids → retrieve_chunks (None = admin) · Agent injects scope server-side (LLM never picks it) · chat/knowledge tools drop unowned file_id':
        'allowed_file_ids → retrieve_chunks (None = admin) · Agent tiêm phạm vi phía server (LLM không bao giờ chọn) · tool chat/knowledge bỏ file_id không sở hữu',
    'Service / data access': 'Truy cập dịch vụ / dữ liệu',

    # 8 · chat-modes
    'General Chat': 'Chat tổng quát',
    'chat_service.chat()\nNO retrieval': 'chat_service.chat()\nKHÔNG truy hồi',
    'Qwen chat model': 'Model chat Qwen',
    'Document Chat': 'Chat tài liệu',
    'retrieve_chunks()\nRAG, scoped to owned file_ids': 'retrieve_chunks()\nRAG, giới hạn theo file_id sở hữu',
    'chat_service.chat()\ncontext-grounded prompt': 'chat_service.chat()\nprompt bám ngữ cảnh',
    'AgentCore loop\n(plan + tools)': 'Vòng lặp AgentCore\n(kế hoạch + tool)',
    'Providers:\nGroq → Gemini → Local Qwen':                    # updated fact
        'LLM qua Model Router — tác vụ “agent”\n(auto: Groq → Gemini → self-hosted → Qwen)',
    'tools: chat (RAG) · knowledge_search ·\nsummarize · translate · correct':
        'tool: chat (RAG) · knowledge_search ·\nsummarize · translate · correct',
    'Shared: chat_service · EmbeddingEngine ·\nin-memory FAISS index':
        'Dùng chung: chat_service · EmbeddingEngine ·\nchỉ mục FAISS trong bộ nhớ',
    'chat tool reuses RAG': 'tool chat dùng lại RAG',

    # 9 · use-case-diagram
    'Log in': 'Đăng nhập',
    'Upload & Manage Documents': 'Tải lên & quản lý tài liệu',
    'Run OCR': 'Chạy OCR',
    'Correct Text': 'Sửa lỗi văn bản',
    'Translate': 'Dịch thuật',
    'Summarize': 'Tóm tắt',
    'Run Agent': 'Chạy Agent',
    'Administer System\n(users · logs · files)': 'Quản trị hệ thống\n(người dùng · nhật ký · file)',
    'User': 'Người dùng',
    'Admin': 'Quản trị viên',
    'Online Translation (Google)': 'Dịch trực tuyến (Google)',
    'also has all User use cases': 'kế thừa mọi use case của Người dùng',

    # 10 · functional-decomposition
    'SmartDocs-Agent\nFunctional Decomposition': 'SmartDocs-Agent\nPhân rã chức năng',
    'Document Processing': 'Xử lý tài liệu',
    'OCR Execution': 'Thực thi OCR',
    'Structured Extraction': 'Trích xuất cấu trúc',
    'Artifact Storage': 'Lưu trữ artifact',
    'Document Library': 'Thư viện tài liệu',
    'Engines: Legacy · Modern · VietOCR · GLM': 'Engine: Legacy · Modern · VietOCR · GLM',
    'AI Services': 'Dịch vụ AI',
    'Correction': 'Sửa lỗi',
    'Translation': 'Dịch thuật',
    'Summarization': 'Tóm tắt',
    'AI Rewrite': 'Viết lại AI',
    'Text Extraction': 'Trích xuất văn bản',
    'Knowledge / RAG': 'Tri thức / RAG',
    'Indexing': 'Lập chỉ mục',
    'Embedding': 'Embedding (nhúng)',
    'Retrieval': 'Truy hồi',
    'Ranking': 'Xếp hạng',
    'Citations': 'Trích dẫn',
    'AgentCore (reasoning loop)': 'AgentCore (vòng lặp suy luận)',
    'Providers (Groq/Gemini/Local)': 'Provider (Groq/Gemini/cục bộ)',
    'Knowledge': 'Tri thức',
    'Memory': 'Bộ nhớ',
    'OCR routing': 'Định tuyến OCR',
    'Results': 'Kết quả',
    'Tools: chat · knowledge_search · summarize · translate · correct':
        'Tool: chat · knowledge_search · summarize · translate · correct',
    'Platform / Admin': 'Nền tảng / Quản trị',
    'Authentication': 'Xác thực',
    'User Management': 'Quản lý người dùng',
    'Activity Logs': 'Nhật ký hoạt động',
    'File Oversight': 'Giám sát file',
    'Document Management': 'Quản lý tài liệu',

    # 12 · document-chat-sequence
    'User (SPA)': 'Người dùng (SPA)',
    'In-memory index': 'Chỉ mục trong bộ nhớ',
    'chat_messages (DB)': 'chat_messages (CSDL)',
    'ownership checks · load server history': 'kiểm tra sở hữu · nạp lịch sử phía server',
    'add_message(user turn) — persisted first': 'add_message(lượt người dùng) — lưu trước',
    'retrieve_chunks (cosine/IP · top_k=5 · scoped)': 'retrieve_chunks (cosine/IP · top_k=5 · theo phạm vi)',
    'ranked (score, chunk, file_id)': 'đã xếp hạng (score, chunk, file_id)',
    'build context-grounded prompt + token-budget fit': 'dựng prompt bám ngữ cảnh + vừa ngân sách token',
    'generate (cancellable · MPS→CPU fallback)': 'sinh trả lời (hủy được · dự phòng MPS→CPU)',
    'answer': 'câu trả lời',
    'add_message(assistant turn + sources JSON)': 'add_message(lượt trợ lý + sources JSON)',

    # 14 · ocr-engine-architecture
    'OCREngine (ABC · base.py)\nrun(image_path) → standard dict':
        'OCREngine (ABC · base.py)\nrun(image_path) → dict chuẩn',
    'router.run_ocr / get_engine\nselect by explicit name OR cfg.OCR_ENGINE default (paddle→paddleocr) · aliases':
        'router.run_ocr / get_engine\nchọn theo tên chỉ định HOẶC mặc định cfg.OCR_ENGINE (paddle→paddleocr) · bí danh',
    'implemented by engines': 'các engine hiện thực',
    'PaddleOCR · PP-OCRv5 (pinned)': 'PaddleOCR · PP-OCRv5 (ghim phiên bản)',
    'text + boxes\n(no structure)': 'text + box\n(không cấu trúc)',
    'PPStructureV3 · PP-OCRv6_medium\norientation + unwarp': 'PPStructureV3 · PP-OCRv6_medium\nxoay hướng + unwarp',
    'markdown · html · tables ·\nblocks · images (layout_native)':
        'markdown · html · bảng ·\nblock · ảnh (layout_native)',
    'PP-OCRv5 detection +\nVietOCR recognition · images only':
        'phát hiện PP-OCRv5 +\nnhận dạng VietOCR · chỉ ảnh',
    'text + boxes\n(confidence = None)': 'text + box\n(confidence = None)',
    'markdown · tables · blocks ·\nimages · raw_json (layout_native)':
        'markdown · bảng · block ·\nảnh · raw_json (layout_native)',
    'Standard result dict\nsuccess · results[{text, confidence, box}] · img_w/h · elapsed_ms · ocr_engine · inference_status':
        'Dict kết quả chuẩn\nsuccess · results[{text, confidence, box}] · img_w/h · elapsed_ms · ocr_engine · inference_status',
    'layout_service → geometry_service\nreading-order reconstruction\n(Legacy, VietOCR)':
        'layout_service → geometry_service\nkhôi phục thứ tự đọc\n(Legacy, VietOCR)',
    'ocr_service returns dict\n→ OCR Processing Pipeline (persist + index)':
        'ocr_service trả về dict\n→ Quy trình OCR (lưu + lập chỉ mục)',

    # 15 · correction-flow
    'Agent: correct tool\n(CorrectionTool)': 'Agent: tool correct\n(CorrectionTool)',
    'correction_service.correct(text)\nclassical · rule-based (no LLM)':
        'correction_service.correct(text)\ncổ điển · theo luật (không dùng LLM)',
    '_basic_clean(text)\nwhitespace / punctuation regex': '_basic_clean(text)\nregex khoảng trắng / dấu câu',
    'English text?': 'Văn bản tiếng Anh?',
    'result\n{corrected, changes, elapsed_ms}': 'kết quả\n{corrected, changes, elapsed_ms}',
    'Note: OCR "smart mode" line cleanup is a\nseparate Qwen path (ai_rewrite_service)':
        'Ghi chú: dọn dòng OCR "chế độ smart" là\nđường Qwen riêng (ai_rewrite_service)',

    # 16 · translation-flow
    'Agent: translate tool\n(TranslateTool)': 'Agent: tool translate\n(TranslateTool)',
    'detect language (langdetect)\nfrom_lang = auto': 'nhận diện ngôn ngữ (langdetect)\nfrom_lang = auto',
    'online\nreachable?': 'online\ntruy cập được?',
    'Argos Translate / CTranslate2\n(offline · Stanza patched)':
        'Argos Translate / CTranslate2\n(offline · đã vá Stanza)',
    'result {translated, to_lang, engine}': 'kết quả {translated, to_lang, engine}',
    'engine=auto: try online if reachable,\nelse offline · NO mid-execution fallback':
        'engine=auto: thử online nếu truy cập được,\nkhông thì offline · KHÔNG fallback giữa chừng',

    # 17 · summarization-flow
    'Agent: summarize tool\n(SummarizeTool)': 'Agent: tool summarize\n(SummarizeTool)',
    'smart: PhoBERT embeddings + MMR (VI)': 'smart: embedding PhoBERT + MMR (tiếng Việt)',
    'apply mode: short / bullets / executive': 'áp dụng mode: short / bullets / executive',
    'ai_rewrite_service · Qwen local / API fallback\n(abstractive rewrite)':
        'ai_rewrite_service · Qwen cục bộ / API dự phòng\n(viết lại trừu tượng)',
    'model warming → HTTP 202': 'model đang khởi động → HTTP 202',
    'result {summary, mode, engine}': 'kết quả {summary, mode, engine}',
    'on error → extractive': 'lỗi → trích xuất (extractive)',

    # 18 · rag-runtime-flow
    'Indexing triggers': 'Kích hoạt lập chỉ mục',
    'OCR persist → index_document_async': 'Lưu OCR → index_document_async',
    'read-text persist → index': 'Lưu read-text → lập chỉ mục',
    'startup: rebuild_indexes_from_db(app)': 'khởi động: rebuild_indexes_from_db(app)',
    'chunk_text (size=400 · overlap=80 · drop ≤20)': 'chunk_text (size=400 · chồng lấp=80 · bỏ ≤20)',
    'EmbeddingEngine.embed\nSBERT → Hashing fallback · L2-norm':
        'EmbeddingEngine.embed\nSBERT → dự phòng Hashing · chuẩn hóa L2',
    '_index_cache[file_id] = DocumentIndex\nFAISS IndexFlatIP (cosine) · in-memory · per file_id':
        '_index_cache[file_id] = DocumentIndex\nFAISS IndexFlatIP (cosine) · trong bộ nhớ · theo file_id',
    'in-memory — lost on restart\n→ rebuilt from DB artifacts (B4)':
        'trong bộ nhớ — mất khi khởi động lại\n→ dựng lại từ artifact trong CSDL',
    'select targets: single file_id OR\nall owned ∩ allowed_file_ids':
        'chọn đích: một file_id HOẶC\ntất cả sở hữu ∩ allowed_file_ids',
    'per-index search · FAISS IndexFlatIP': 'tìm trên từng chỉ mục · FAISS IndexFlatIP',
    'union + sort by score + top_k\nNO threshold · NO reranker':
        'gộp + sắp theo điểm + top_k\nKHÔNG ngưỡng · KHÔNG reranker',
    '(score, chunk, file_id) → consumers:\nchat_service.chat (doc_current / doc_all) ·\nKnowledgeSearchTool / DocumentKnowledge':
        '(score, chunk, file_id) → nơi sử dụng:\nchat_service.chat (doc_current / doc_all) ·\nKnowledgeSearchTool / DocumentKnowledge',

    # context-diagram
    '0\nSmartDocs-Agent Platform': '0\nNền tảng SmartDocs-Agent',
    'GLM-OCR\nMLX server :8080': 'GLM-OCR\nMLX server :8080',
    'Online Translation\n(Google)': 'Dịch trực tuyến\n(Google)',
    'requests & uploads  /  results & answers': 'yêu cầu & tải lên  /  kết quả & câu trả lời',
    'admin actions  /  users · logs · files': 'thao tác quản trị  /  người dùng · nhật ký · file',
    'agent prompt / completion': 'prompt agent / phản hồi',
    'agent fallback / completion': 'dự phòng agent / phản hồi',
    'OCR request / structured result': 'yêu cầu OCR / kết quả cấu trúc',
    'text / translation (online)': 'văn bản / bản dịch (online)',
    'Notation: rounded box = system process (0) · rectangle = external entity.\nLevel-0 context: the platform as a single process with its external interactors.':
        'Ký hiệu: hộp bo tròn = tiến trình hệ thống (0) · chữ nhật = thực thể bên ngoài.\nNgữ cảnh mức 0: nền tảng là một tiến trình duy nhất cùng các bên tương tác bên ngoài.',

    # dfd-level-1
    'Online\nTranslation': 'Dịch\ntrực tuyến',
    '1 · Authenticate\n& Admin': '1 · Xác thực\n& Quản trị',
    '2 · Document Intake\n(upload · read-text · library)': '2 · Tiếp nhận tài liệu\n(tải lên · read-text · thư viện)',
    '3 · OCR Processing\n(engines → artifacts)': '3 · Xử lý OCR\n(engine → artifact)',
    '4 · AI Services\n(correct · translate · summarize)': '4 · Dịch vụ AI\n(sửa lỗi · dịch · tóm tắt)',
    '5 · RAG Index &\nRetrieval': '5 · Chỉ mục RAG &\ntruy hồi',
    '6 · Chat (general / document)\nlocal Qwen chat model': '6 · Chat (tổng quát / tài liệu)\nmodel chat Qwen cục bộ',
    '7 · Agent Orchestration\nproviders + tools': '7 · Điều phối Agent\nprovider + tool',
    'D4 · RAG index (in-memory)': 'D4 · Chỉ mục RAG (trong bộ nhớ)',
    'admin actions / users·logs·files': 'thao tác quản trị / người dùng·nhật ký·file',
    'users': 'người dùng',
    'log': 'ghi log',
    'login / session': 'đăng nhập / phiên',
    'upload / file_id, list': 'tải lên / file_id, danh sách',
    'store file': 'lưu file',
    'create / read': 'tạo / đọc',
    'read file': 'đọc file',
    'OCR request / result': 'yêu cầu OCR / kết quả',
    'store artifacts': 'lưu artifact',
    'index text': 'lập chỉ mục văn bản',
    'request / result': 'yêu cầu / kết quả',
    'OCR text / summary·translation': 'văn bản OCR / tóm tắt·bản dịch',
    'online translate': 'dịch online',
    'embed / retrieve': 'nhúng / truy hồi',
    'chat query / answer + sources': 'câu hỏi chat / trả lời + nguồn',
    'store / history': 'lưu / lịch sử',
    'agent message / results': 'tin nhắn agent / kết quả',
    'prompt / completion': 'prompt / phản hồi',
    'fallback': 'dự phòng',
    'tools: summarize / translate / correct': 'tool: tóm tắt / dịch / sửa lỗi',
    'store / refs': 'lưu / tham chiếu',
    'Notation:\n· rounded = process (n)\n· cylinder = data store (Dn)\n· rectangle = external entity\n(both-headed arrow = request / response)':
        'Ký hiệu:\n· bo tròn = tiến trình (n)\n· trụ = kho dữ liệu (Dn)\n· chữ nhật = thực thể ngoài\n(mũi tên hai đầu = yêu cầu / phản hồi)',

    # backend-architecture
    'Web browser — Main SPA (app.js · chat.js · i18n.js) · Agent workspace (agent.js) · Admin console (Jinja templates)':
        'Trình duyệt web — SPA chính (app.js · chat.js · i18n.js) · Không gian Agent (agent.js) · Bảng quản trị (Jinja)',
    'Flask application core — global app at app.py:23 (not an app factory)':
        'Lõi ứng dụng Flask — app toàn cục tại app.py:23 (không dùng app factory)',
    'register_blueprint ×4\nauth · admin · chat · agent':          # updated fact (now 6)
        'register_blueprint ×6\nauth · admin · chat · agent\n· settings · models',
    'Request lifecycle  ·  the only hooks are @login_required (gate) and after_request — no before_request / teardown':
        'Vòng đời yêu cầu · hook duy nhất là @login_required (cổng) và after_request — không có before_request / teardown',
    '① Auth gate\n@login_required → 401 JSON {redirect:"/login"} or HTML redirect':
        '① Cổng xác thực\n@login_required → 401 JSON {redirect:"/login"} hoặc chuyển hướng HTML',
    '② Body-size cap\nMAX_CONTENT_LENGTH → 413 RequestEntityTooLarge':
        '② Giới hạn kích thước body\nMAX_CONTENT_LENGTH → 413 RequestEntityTooLarge',
    '③ Handler (blueprint / app.py)\nownership resolve → service → persist → JSON':
        '③ Handler (blueprint / app.py)\nkiểm tra sở hữu → dịch vụ → lưu → JSON',
    'No CSRF protection · no CORS layer · no rate limiter — only mitigation: SameSite=Lax on session / remember cookies':
        'Không CSRF · không CORS · không giới hạn tốc độ — giảm nhẹ duy nhất: SameSite=Lax trên cookie phiên / remember',
    'Blueprints & route groups  (registered at app.py:81-84)':      # updated fact
        'Blueprint & nhóm route (app.py:84-89 — nay gồm 6 blueprint: + settings_bp · models_bp)',
    'no auth': 'không xác thực',
    'safe tools (no OCR)': 'tool an toàn (không OCR)',
    'Service & persistence layer  (the backend delegates here; agent/ reuses services through tools)':
        'Tầng dịch vụ & lưu trữ (backend ủy quyền tại đây; agent/ dùng lại dịch vụ qua tool)',
    'services/ — OCR pipeline\nsmart_ocr_service · router · 4 engines':
        'services/ — quy trình OCR\nsmart_ocr_service · router · 4 engine',
    'services/ — AI services\ncorrection · translate · summary · ai_rewrite':
        'services/ — dịch vụ AI\ncorrection · translate · summary · ai_rewrite',
    'services/ — Chat / RAG\nchat_service · EmbeddingEngine · FAISS (in-memory)':
        'services/ — Chat / RAG\nchat_service · EmbeddingEngine · FAISS (trong bộ nhớ)',
    'agent/ — AgentCore · tools · knowledge\nproviders: Groq → Gemini → Local Qwen':  # updated fact
        'agent/ — AgentCore · tool · tri thức\nLLM qua Model Router (auto: Groq → Gemini → self-hosted → Qwen)',
    'HTTP / JSON · cookie session': 'HTTP / JSON · cookie phiên',
    'every request': 'mọi yêu cầu',
    'dispatch to handler': 'chuyển tới handler',
    'correct / translate / summarize': 'sửa lỗi / dịch / tóm tắt',
    'RAG chat': 'chat RAG',
    'agent run': 'chạy agent',
    'users · logs': 'người dùng · nhật ký',

    # full-component-architecture (titles + prose; module lists stay verbatim)
    'Frontend (static/, templates/)  —  vanilla JS, no build':
        'Frontend (static/, templates/) — JS thuần, không cần build',
    'Agent workspace (agent.html)\n• agent.js — runAgent, runSkill,\n  loadSessions, renderTranscript':
        'Không gian Agent (agent.html)\n• agent.js — runAgent, runSkill,\n  loadSessions, renderTranscript',
    'login.html · 403.html\n(server-rendered Jinja)': 'login.html · 403.html\n(Jinja render phía server)',
    'hash routes: #ocr/<id> · #translate/<id>\n#summarize/<id> · #chat/<id>':
        'route băm: #ocr/<id> · #translate/<id>\n#summarize/<id> · #chat/<id>',
    'Flask backend (app.py — global app, 4 blueprints)':            # updated fact
        'Flask backend (app.py — app toàn cục, 6 blueprint)',
    'OCR pipeline (services/ + services/ocr_engines/)': 'Quy trình OCR (services/ + services/ocr_engines/)',
    'GLM-OCR subprocess (own venv) → MLX server localhost:8080  [external]':
        'GLM-OCR subprocess (venv riêng) → MLX server localhost:8080  [bên ngoài]',
    'AI services (services/)': 'Dịch vụ AI (services/)',
    'tools/ — Tool · ToolRegistry · ToolResult\nOcrTool* · TranslateTool · SummarizeTool\nChatTool · KnowledgeSearchTool · CorrectionTool\n(*excluded from agent safe set)':
        'tools/ — Tool · ToolRegistry · ToolResult\nOcrTool* · TranslateTool · SummarizeTool\nChatTool · KnowledgeSearchTool · CorrectionTool\n(*bị loại khỏi bộ tool an toàn của agent)',
    'skills/ — Skill · SkillRegistry\nSkillContext · SkillResult\nOcrDigest · Research · DocQa\nSummarizeTranslate · …  [dormant in loop]':
        'skills/ — Skill · SkillRegistry\nSkillContext · SkillResult\nOcrDigest · Research · DocQa\nSummarizeTranslate · …  [không dùng trong vòng lặp]',
    'ocr_routing.py — select_ocr_engine\n(GLM default · vi→VietOCR · explicit wins)':
        'ocr_routing.py — select_ocr_engine\n(mặc định GLM · vi→VietOCR · chỉ định thắng)',
    'results.py\ndestination deep-links\n(dedupe_destinations)':
        'results.py\ndeep-link đích đến\n(dedupe_destinations)',
    'No skill-selection layer in the live HTTP agent: AgentCore is built with an EMPTY skill registry → orchestrates the 5 safe tools directly':
        'Không có tầng chọn skill trong agent HTTP thực tế: AgentCore được tạo với skill registry RỖNG → điều phối trực tiếp 5 tool an toàn',
    'Persistence (models.py · SQLite paddleocr.db)': 'Lưu trữ (models.py · SQLite paddleocr.db)',
    'document_artifacts\n(one row per kind)': 'document_artifacts\n(mỗi kind một bản ghi)',
    'agent_artifacts\n(reference rows)': 'agent_artifacts\n(bản ghi tham chiếu)',
    'HTTP / JSON (cookie session)': 'HTTP / JSON (cookie phiên)',
    'chat / knowledge tools': 'tool chat / knowledge',
}


def tr(s):
    return VI.get(s, s)


def translate(d):
    d.title = VI_TITLES.get(d.name, d.title)
    d.name = d.name + '-vi'
    for c in d.containers:
        c['title'] = tr(c['title'])
    for n in d.nodes:
        n['label'] = tr(n['label'])
    for t in d.tables:
        t['title'] = tr(t['title'])
        t['rows'] = [(tr(a), tr(b)) for (a, b) in t['rows']]
    for e in d.edges:
        e['label'] = tr(e['label'])
    for ll in d.lifelines:
        ll['label'] = tr(ll['label'])
    for m in d.messages:
        m['label'] = tr(m['label'])
    for fr in d.fragments:
        fr['label'] = tr(fr['label'])
    return d


# ── 21 · provider-fallback-chain — REDRAWN (self-hosted + Local-only) ─────────
def d_provider_chain_vi():
    d = B.Diagram('provider-fallback-chain-vi',
                  '21 · Chuỗi provider dự phòng — chế độ “auto” (legacy)', 1240, 740)
    d.node('gdp', 450, 66, 360, 50, 'get_default_provider()\nđọc AGENT_LLM_PROVIDER (mặc định: auto)', 'be',
           bold=True, fontsize=10.5)
    d.node('sel', 550, 150, 160, 80, 'AGENT_LLM_PROVIDER?', 'note', shape='diamond', fontsize=9.5)
    d.edge('gdp', 'sel', srcside='bottom', dstside='top')
    d.node('localonly', 840, 168, 300, 46, 'chỉ LocalQwenProvider', 'llm', fontsize=11)
    d.edge('sel', 'localonly', label='local', srcside='right', dstside='left')
    d.node('build', 280, 268, 320, 50, 'dựng chuỗi (auto / groq / gemini /\nopenai_compatible)', 'be', fontsize=10.5)
    d.edge('sel', 'build', label='các lựa chọn khác', srcside='bottom', dstside='top', waypoints=[(630, 250)])
    d.node('c1', 80, 344, 380, 46, 'nếu có GROQ_API_KEY và ĐƯỢC phép cloud\n→ thêm GroqProvider', 'llm', fontsize=9.5)
    d.node('c2', 80, 402, 380, 46, 'nếu có GEMINI_API_KEY và ĐƯỢC phép cloud\n→ thêm GeminiProvider', 'llm', fontsize=9.5)
    d.node('c3', 80, 460, 380, 50, 'nếu self-hosted (OpenAI-compatible) đã cấu hình\n→ thêm OpenAICompatibleProvider', 'llm', fontsize=9.5)
    d.node('c4', 80, 524, 380, 44, 'luôn thêm LocalQwenProvider (cuối chuỗi)', 'llm', fontsize=9.5)
    d.edge('build', 'c1', srcside='bottom', dstside='top', waypoints=[(270, 334)])
    d.edge('c1', 'c2', srcside='bottom', dstside='top')
    d.edge('c2', 'c3', srcside='bottom', dstside='top')
    d.edge('c3', 'c4', srcside='bottom', dstside='top')
    d.container('FB', 540, 344, 660, 200,
                'FallbackProvider(chuỗi) — hạ cấp khi lỗi · ghi nhớ provider chạy được · chuỗi rỗng = lỗi rõ', 'llm')
    px = B.row_x(560, 1184, 4, 146)
    fb = [('groq', 'GroqProvider\n(cloud)'), ('gem', 'GeminiProvider\n(cloud)'),
          ('oc', 'OpenAICompatible\n(self-hosted /v1)'), ('local', 'LocalQwenProvider\n(cục bộ, cuối)')]
    for i, (nid, lab) in enumerate(fb):
        d.node(nid, int(px[i]), 412, 146, 64, lab, 'llm', parent='FB', fontsize=9.5)
    d.edge('groq', 'gem', label='lỗi', color='#B85450', srcside='right', dstside='left')
    d.edge('gem', 'oc', label='lỗi', color='#B85450', srcside='right', dstside='left')
    d.edge('oc', 'local', label='lỗi', color='#B85450', srcside='right', dstside='left')
    d.edge('c4', 'FB', label='≥ 2 provider', srcside='right', dstside='left')
    d.node('lo', 540, 566, 660, 50,
           'Local-only (ALLOW_CLOUD=false): loại Groq · Gemini khỏi chuỗi kể cả khi có khóa\n→ chuỗi = self-hosted (nếu có) + Qwen cục bộ',
           'sec', fontsize=10)
    d.node('promote', 540, 632, 660, 44,
           'LLM_PROVIDER=openai_compatible: đẩy self-hosted lên ĐẦU chuỗi (Windows/Linux không có model cục bộ)',
           'note', fontsize=10)
    d.node('router', 80, 600, 380, 76,
           'Đây là chuỗi “auto” (hành vi cũ) mà Model Router\ndùng khi tác vụ đặt Automatic — model chỉ định\nđi qua Router (xem sơ đồ D6 / W2)', 'agent', fontsize=10)
    return d


FNS = [B.d_ocr, B.d_lifecycle, B.d_rag, B.d_erd, B.d_security, B.d_chatmodes,
       B.d_appendix, B.d_usecase, B.d_funcdecomp, B.d_docchat_seq, B.d_ocr_engines,
       B.d_correction, B.d_translation, B.d_summarization, B.d_rag_runtime,
       B.d_context, B.d_dfd1, B.d_backend]

if __name__ == '__main__':
    used = set()
    for fn in FNS:
        d = fn()
        # track which translation keys actually matched, to catch typos
        for coll, key in ((d.containers, 'title'), (d.nodes, 'label'), (d.edges, 'label'),
                          (d.lifelines, 'label'), (d.messages, 'label'), (d.fragments, 'label')):
            for item in coll:
                if item[key] in VI:
                    used.add(item[key])
        for t in d.tables:
            if t['title'] in VI:
                used.add(t['title'])
            for a, b in t['rows']:
                used.update(k for k in (a, b) if k in VI)
        write(translate(d))
    write(d_provider_chain_vi())
    unused = [k for k in VI if k not in used]
    if unused:
        print('\nWARNING — translation keys that matched nothing (check for typos):')
        for k in unused:
            print('  ·', k.replace('\n', '\\n'))
    print('\ndone:', len(FNS) + 1, 'Vietnamese diagrams')
