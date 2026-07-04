/**
 * SmartDocs AI Chat — UI Controller
 * ===================================
 * Manages the chat view: mode switching, message rendering,
 * document indexing, RAG-aware API calls, and status polling.
 *
 * Integration with existing app (optional seam — all reads are null-guarded):
 *   - Reads window.App.lastFileId   (last OCR'd document id, if set)
 *   - Reads window.App.lastOcrText  (last OCR'd text, if set)
 *   - Reads window.App.lastFilename (last OCR'd filename, if set)
 */

'use strict';

const ChatModule = (() => {

  // ── State ──────────────────────────────────────────────────────────────────
  let _mode           = 'doc_current';   // doc_current | general
  let _history        = [];              // [{role, content}, …] render buffer for open thread
  let _conversationId = null;            // active persisted conversation id (null = new)
  let _forceNew       = false;           // next send should branch a NEW thread
  let _activeFileId   = null;            // chat-owned document scope (RAG file_id)
  let _activeDocLabel = null;            // label for the active document scope
  let _activeDocGone  = false;           // true when the scoped document was deleted
  let _collapsed      = new Set();       // collapsed history group keys
  let _busy           = false;
  let _modelReady     = false;
  let _statusTimer    = null;
  let _indexedDocs    = new Set();       // file_ids already indexed this session
  let _currentDocInfo = null;            // {file_id, filename, chunks}
  let _abortController = null;           // AbortController for active fetch request

  // ── DOM refs ───────────────────────────────────────────────────────────────
  const $ = id => document.getElementById(id);

  function _els() {
    return {
      messages    : $('chat-messages'),
      welcome     : $('chat-welcome'),
      input       : $('chat-input'),
      sendBtn     : $('chat-send-btn'),
      clearBtn    : $('chat-clear-btn'),
      modelBadge  : $('chat-model-badge'),
      badgeText   : $('chat-model-badge-text'),
      docInfo     : $('chat-doc-info'),
      indexBtn    : $('chat-index-btn'),
    };
  }

  // ── Init ───────────────────────────────────────────────────────────────────
  function init() {
    _bindModeButtons();
    _bindInputEvents();
    _bindTipItems();
    _bindIndexButton();
    _bindNewButton();
    _pollModelStatus();
    _seedScopeFromOcr();
    _updateSidebarFromOcrState();
    _loadConversations();
  }

  // ── Active document scope ────────────────────────────────────────────────────
  // The chat module owns the document scope used for RAG (file_id). It is seeded
  // from the OCR view but, crucially, is overridden when a saved conversation is
  // reopened — so retrieval follows the conversation, not the transient OCR state.
  function _seedScopeFromOcr(force) {
    // Only fill an EMPTY scope from the OCR view; never clobber a scope already
    // set by OCR completion or by reopening a conversation (so "New chat"
    // branches on the same document). `force` is used by OCR completion.
    if (_activeFileId && !force) return;
    const app = window.App || {};
    if (app.lastFileId) {
      _activeFileId   = app.lastFileId;
      _activeDocLabel = app.lastFilename || app.lastFileId;
      _activeDocGone  = false;
    }
  }

  // ── Mode switching ─────────────────────────────────────────────────────────
  function _bindModeButtons() {
    document.querySelectorAll('.chat-mode-pill').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.chat-mode-pill').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        _mode = btn.dataset.mode;
        _updateInputPlaceholder();
        _updateSidebarFromOcrState();
      });
    });
  }

  function _updateInputPlaceholder() {
    const el = $('chat-input');
    if (!el) return;
    const placeholders = {
      doc_current: 'Hỏi về tài liệu hiện tại… (Enter gửi)',
      general:     'Hỏi bất kỳ điều gì…',
    };
    el.placeholder = placeholders[_mode] || 'Nhập câu hỏi…';
  }

  // ── Input events ───────────────────────────────────────────────────────────
  function _bindInputEvents() {
    const input   = $('chat-input');
    const sendBtn = $('chat-send-btn');
    const clearBtn= $('chat-clear-btn');

    if (!input) return;

    // Auto-resize textarea
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 160) + 'px';
    });

    // Enter sends; blocked during generation (use Stop button instead)
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (_busy) return;   // ignore Enter while generating
        sendMessage();
      }
    });

    // Send button: click sends OR stops depending on busy state
    if (sendBtn) {
      sendBtn.addEventListener('click', () => {
        if (_busy) stopGeneration();
        else sendMessage();
      });
    }
    clearBtn && clearBtn.addEventListener('click', clearHistory);
  }

  // ── Tip items ──────────────────────────────────────────────────────────────
  function _bindTipItems() {
    document.querySelectorAll('.chat-tip-item').forEach(tip => {
      tip.addEventListener('click', () => {
        const question = tip.dataset.tip;
        if (!question) return;
        const input = $('chat-input');
        if (input) {
          input.value = question;
          input.style.height = 'auto';
          input.style.height = Math.min(input.scrollHeight, 160) + 'px';
          input.focus();
        }
      });
    });
  }

  // ── Index button ───────────────────────────────────────────────────────────
  function _bindIndexButton() {
    const btn = $('chat-index-btn');
    if (!btn) return;
    btn.addEventListener('click', () => {
      const app = window.App || {};
      const fileId = app.lastFileId || null;
      const text   = app.lastOcrText || '';
      const name   = app.lastFilename || fileId;
      if (!fileId || !text) {
        _showToast('Chưa có kết quả OCR để lập chỉ mục.', 'error');
        return;
      }
      _indexDocument(fileId, text, name);
    });
  }

  // ── Sidebar update ─────────────────────────────────────────────────────────
  function _updateSidebarFromOcrState() {
    const app      = window.App || {};
    const ocrFid   = app.lastFileId   || null;   // the freshly-OCR'd doc (has text)
    const ocrText  = app.lastOcrText  || '';
    const docInfo  = $('chat-doc-info');
    const indexBtn = $('chat-index-btn');

    if (!docInfo) return;

    // The panel reflects the active chat scope (which may be a reopened
    // conversation's document), falling back to the OCR doc when no scope is set.
    const fileId   = _activeFileId   || ocrFid;
    const filename = _activeDocLabel || app.lastFilename || fileId;

    // The "Index" button only makes sense for the doc we actually have text for.
    const canIndex = !!(ocrFid && ocrText && ocrFid === fileId && !_indexedDocs.has(ocrFid));

    if (_activeDocGone) {
      docInfo.className = '';
      docInfo.innerHTML = `
        <div class="chat-doc-info">
          <div class="chat-doc-name" title="${_esc(filename || '')}">🗑 ${_esc(filename || '')}</div>
          <div class="chat-doc-chunks" style="color:var(--warn)">⚠️ Tài liệu đã bị xóa — chuyển sang Trợ lý chung để tiếp tục</div>
        </div>`;
      if (indexBtn) indexBtn.style.display = 'none';
      return;
    }

    if (!fileId) {
      docInfo.className = 'chat-doc-empty';
      docInfo.innerHTML = 'Chưa có tài liệu. Hãy chạy OCR hoặc mở một cuộc trò chuyện tài liệu.';
      if (indexBtn) indexBtn.style.display = 'none';
      return;
    }

    const indexed = _indexedDocs.has(fileId);
    docInfo.className = '';
    docInfo.innerHTML = `
      <div class="chat-doc-info">
        <div class="chat-doc-name" title="${_esc(filename)}">📄 ${_esc(filename)}</div>
        <div class="chat-doc-chunks"${indexed ? '' : ' style="color:var(--warn)"'}>${
          indexed
            ? `✅ Đã lập chỉ mục · ${(_currentDocInfo || {}).chunks || '?'} đoạn`
            : (canIndex ? '⚠️ Chưa được lập chỉ mục' : 'Sẵn sàng hỏi đáp')
        }</div>
        <button class="btn btn-ghost btn-sm chat-view-doc-btn" data-view-fid="${_esc(fileId)}">
          📄 ${_esc(t('chat.view_doc', 'Xem tài liệu'))}
        </button>
      </div>`;
    const viewBtn = docInfo.querySelector('.chat-view-doc-btn');
    if (viewBtn) viewBtn.addEventListener('click', () => {
      if (window.App && typeof window.App.openDocumentByFileId === 'function') {
        window.App.openDocumentByFileId(viewBtn.dataset.viewFid);
      }
    });
    if (indexBtn) indexBtn.style.display = canIndex ? 'block' : 'none';
  }

  // ── Index a document ───────────────────────────────────────────────────────
  async function _indexDocument(fileId, text, filename) {
    const btn = $('chat-index-btn');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang lập chỉ mục…'; }
    try {
      const res = await fetch('/api/chat/index', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_id: fileId, text, label: filename }),
      });
      const data = await res.json();
      if (data.success) {
        _indexedDocs.add(fileId);
        _currentDocInfo = { file_id: fileId, filename, chunks: data.chunks };
        _updateSidebarFromOcrState();
        _showToast(`✅ Đã lập chỉ mục ${data.chunks} đoạn văn bản`, 'success');
      } else {
        _showToast('Lỗi lập chỉ mục: ' + (data.error || 'unknown'), 'error');
      }
    } catch (e) {
      _showToast('Lỗi kết nối: ' + e.message, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '⚡ Lập chỉ mục tài liệu'; }
    }
  }

  // ── Stop generation ──────────────────────────────────────────────────────────
  async function stopGeneration() {
    if (!_busy) return;
    // 1. Abort the pending fetch immediately
    if (_abortController) {
      _abortController.abort();
      _abortController = null;
    }
    // 2. Tell the backend to stop model.generate() at the next token
    try { await fetch('/api/chat/cancel', { method: 'POST' }); } catch (_) {}
    // _setBusy(false) is called in sendMessage's finally block
  }

  // ── Send message ───────────────────────────────────────────────────────────────
  async function sendMessage() {
    if (_busy) return;
    const input = $('chat-input');
    if (!input) return;
    const query = input.value.trim();
    if (!query) return;

    // Make sure the active scope reflects the OCR view when no conversation is open.
    _seedScopeFromOcr();

    // Document modes require a document in scope. Block + prompt rather than
    // silently sending file_id=null (which retrieves all docs and misfiles the
    // thread under General Assistant).
    if (_mode !== 'general' && !_activeFileId) {
      _showToast(t('chat.need_doc',
        'Hãy mở một cuộc trò chuyện tài liệu hoặc chuyển sang Trợ lý chung.'), 'info');
      return;
    }

    // Auto-index only the freshly-OCR'd doc (the only one we hold text for on the
    // client). A reopened conversation's document is already indexed server-side.
    const app   = window.App || {};
    const scope = _activeFileId;
    if (_mode !== 'general' && scope && app.lastFileId === scope &&
        app.lastOcrText && !_indexedDocs.has(scope)) {
      await _indexDocument(scope, app.lastOcrText, _activeDocLabel || app.lastFilename);
    }

    // Clear input
    input.value = '';
    input.style.height = 'auto';

    // Show user bubble
    _hideWelcome();
    _appendBubble('user', query);
    _history.push({ role: 'user', content: query });

    // Show typing indicator
    const typingId = _appendTyping();
    _setBusy(true);

    try {
      const body = {
        query,
        file_id:         _mode === 'general' ? null : _activeFileId,
        mode:            _mode,
        conversation_id: _conversationId,   // null → server auto-creates (hybrid)
        new_thread:      _forceNew,         // true → branch a fresh thread
      };
      _forceNew = false;

      // Create fresh AbortController for this request
      _abortController = new AbortController();

      const res  = await fetch('/api/chat/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: _abortController.signal,
      });
      const data = await res.json();
      _removeTyping(typingId);

      if (res.status === 202 && data.warming_up) {
        _appendBubble('ai', '⏳ Mô hình AI đang khởi động. Vui lòng thử lại sau 15–30 giây.', []);
        _showToast('Mô hình đang tải, thử lại sau...', 'info');
        return;
      }

      if (!data.success) {
        _appendBubble('ai', '❌ ' + (data.error || 'Có lỗi xảy ra.'), []);
        return;
      }

      const answer = data.answer || '(Không có câu trả lời)';
      _history.push({ role: 'assistant', content: answer });
      // Mark partial responses that were interrupted on the backend
      _appendBubble('ai', answer, data.sources || [], !!data.cancelled);

      // Adopt the persisted conversation id/title and ALWAYS refresh the history
      // list so the just-used conversation — and its document group — move to the
      // top (server orders by updated_at desc), not just when a thread is new.
      if (data.conversation_id) {
        _conversationId = data.conversation_id;
        _loadConversations();
      }

    } catch (e) {
      _removeTyping(typingId);
      if (e.name === 'AbortError') {
        // Fetch was aborted by stopGeneration() — show a clean stopped note
        _appendBubble('ai', '⏹ Đã dừng tạo câu trả lời.', [], false);
      } else {
        _appendBubble('ai', '❌ Lỗi kết nối: ' + e.message, []);
      }
    } finally {
      _abortController = null;
      _setBusy(false);
    }
  }

  // ── Message rendering ──────────────────────────────────────────────────────
  function _hideWelcome() {
    const w = $('chat-welcome');
    if (w) w.style.display = 'none';
  }

  function _appendBubble(role, text, sources, interrupted = false) {
    const msgs = $('chat-messages');
    if (!msgs) return;

    const row = document.createElement('div');
    row.className = `chat-msg-row ${role}`;

    const avatarEmoji = role === 'ai' ? '🤖' : '👤';
    const avatarClass = role === 'ai' ? 'ai-avatar' : 'user-avatar';

    // Interrupted badge
    const interruptedBadge = interrupted
      ? `<span class="chat-interrupted-badge">⏹ Dừng</span>` : '';
    let sourcesHtml = '';
    if (sources && sources.length > 0) {
      const chips = sources.map(s => {
        const excerpt = _esc(s.excerpt || '').substring(0, 80);
        return `<span class="chat-source-chip" title="${_esc(s.excerpt || '')}" data-file-id="${_esc(s.file_id||'')}">
          📎 ${excerpt}…
        </span>`;
      }).join('');
      sourcesHtml = `<div class="chat-sources">${chips}</div>`;
    }

    row.innerHTML = `
      <div class="chat-avatar ${avatarClass}">${avatarEmoji}</div>
      <div class="chat-bubble-wrap">
        <div class="chat-bubble ${role}">${_esc(text)}</div>
        ${interruptedBadge}
        ${sourcesHtml}
      </div>`;

    msgs.appendChild(row);
    msgs.scrollTop = msgs.scrollHeight;
    return row;
  }

  function _appendTyping() {
    const msgs = $('chat-messages');
    if (!msgs) return null;
    const id = 'typing-' + Date.now();
    const row = document.createElement('div');
    row.className = 'chat-msg-row ai';
    row.id = id;
    row.innerHTML = `
      <div class="chat-avatar ai-avatar">🤖</div>
      <div class="chat-bubble-wrap">
        <div class="chat-bubble ai thinking">
          <div class="chat-typing"><span></span><span></span><span></span></div>
        </div>
      </div>`;
    msgs.appendChild(row);
    msgs.scrollTop = msgs.scrollHeight;
    return id;
  }

  function _removeTyping(id) {
    if (!id) return;
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  // ── Clear current view / start a new chat ────────────────────────────────────
  // Persisted conversations are NOT deleted here — this only resets the open
  // thread so the next message starts (or auto-creates) a fresh conversation.
  function clearHistory() {
    _history = [];
    _conversationId = null;
    _forceNew = true;   // next message branches a fresh thread (hybrid)
    _activeDocGone = false;  // leaving any deleted-document thread
    // Keep _activeFileId so "+ New chat" branches on the same document; if it is
    // empty, the next send seeds it from the OCR view.
    const msgs = $('chat-messages');
    if (msgs) {
      msgs.querySelectorAll('.chat-msg-row').forEach(el => el.remove());
      const w = $('chat-welcome');
      if (w) w.style.display = '';
    }
    // Deselect any active history row
    document.querySelectorAll('.chat-history-row.active')
            .forEach(r => r.classList.remove('active'));
    _updateSidebarFromOcrState();
  }

  // ── New chat button ──────────────────────────────────────────────────────────
  function _bindNewButton() {
    const btn = $('chat-new-btn');
    if (btn) btn.addEventListener('click', () => clearHistory());
  }

  // ── Conversation history ─────────────────────────────────────────────────────
  async function _loadConversations() {
    const list = $('chat-history-list');
    if (!list) return;
    try {
      const res  = await fetch('/api/chat/conversations');
      if (!res.ok) return;
      const data = await res.json();
      if (!data.success) return;
      _renderHistory(data.conversations || []);
    } catch (_) { /* offline / not logged in — leave panel as-is */ }
  }

  function _groupKey(c) {
    if (c.document_id != null)  return { key: 'doc:' + c.document_id, type: 'doc',
                                         label: c.document_label || ('Tài liệu #' + c.document_id) };
    if (c.document_label)       return { key: 'former:' + c.document_label, type: 'former',
                                         label: c.document_label + ' (đã xóa)' };
    return { key: 'general', type: 'general', label: 'Trợ lý chung' };
  }

  function _renderHistory(convs) {
    const list = $('chat-history-list');
    if (!list) return;

    if (!convs.length) {
      list.innerHTML = '<div class="chat-history-empty" data-i18n="chat.history_empty">Chưa có cuộc trò chuyện nào.</div>';
      return;
    }

    // Group by document, preserving updated_at-desc order (convs arrive sorted).
    const order = [];           // group keys in first-seen order
    const groups = {};          // key → { meta, items[] }
    convs.forEach(c => {
      const g = _groupKey(c);
      if (!groups[g.key]) { groups[g.key] = { meta: g, items: [] }; order.push(g.key); }
      groups[g.key].items.push(c);
    });

    list.innerHTML = '';
    order.forEach(key => {
      const { meta, items } = groups[key];
      const collapsed = _collapsed.has(key);
      const icon = meta.type === 'general' ? '💬' : (meta.type === 'former' ? '🗑' : '📄');

      const group = document.createElement('div');
      group.className = 'chat-history-group' + (collapsed ? ' collapsed' : '') +
                        (meta.type === 'former' ? ' chat-history-group-former' : '');

      const head = document.createElement('div');
      head.className = 'chat-history-group-head';
      head.innerHTML =
        `<span class="chat-history-caret">▼</span>` +
        `<span>${icon}</span>` +
        `<span class="chat-history-group-label" title="${_esc(meta.label)}">${_esc(meta.label)}</span>` +
        `<span class="chat-history-group-count">${items.length}</span>`;
      head.addEventListener('click', () => {
        if (_collapsed.has(key)) _collapsed.delete(key); else _collapsed.add(key);
        group.classList.toggle('collapsed');
      });
      group.appendChild(head);

      const itemsWrap = document.createElement('div');
      itemsWrap.className = 'chat-history-items';
      items.forEach(c => itemsWrap.appendChild(_historyRow(c)));
      group.appendChild(itemsWrap);

      list.appendChild(group);
    });
  }

  function _historyRow(c) {
    const row = document.createElement('div');
    row.className = 'chat-history-row' + (c.id === _conversationId ? ' active' : '');
    row.dataset.convId = c.id;
    row.innerHTML =
      `<span class="chat-history-title" title="${_esc(c.title)}">${_esc(c.title)}</span>` +
      `<span class="chat-history-actions">` +
        `<button class="chat-history-act act-rename" title="Đổi tên">✏️</button>` +
        `<button class="chat-history-act act-delete" title="Xóa">🗑</button>` +
      `</span>`;
    row.addEventListener('click', e => {
      if (e.target.closest('.chat-history-act')) return;
      _openConversation(c.id);
    });
    row.querySelector('.act-rename').addEventListener('click', e => {
      e.stopPropagation(); _renameConversation(c);
    });
    row.querySelector('.act-delete').addEventListener('click', e => {
      e.stopPropagation(); _deleteConversation(c);
    });
    return row;
  }

  function _touchActiveRow() {
    // Mark the active conversation's row without a full reload.
    document.querySelectorAll('.chat-history-row.active').forEach(r => r.classList.remove('active'));
    const row = document.querySelector(`.chat-history-row[data-conv-id="${_conversationId}"]`);
    if (row) row.classList.add('active');
  }

  async function _openConversation(id) {
    if (_busy) return;
    try {
      const res  = await fetch('/api/chat/conversations/' + id);
      if (!res.ok) return;
      const data = await res.json();
      if (!data.success) return;

      _conversationId = id;
      _forceNew = false;   // continuing an existing thread, not branching
      _history = [];

      // Restore the mode pill AND the document scope so retrieval follows this
      // conversation rather than the OCR view's transient document.
      const conv = data.conversation || {};
      if (conv.last_mode) _setModePill(conv.last_mode);
      if (conv.file_id) {
        _activeFileId   = conv.file_id;
        _activeDocLabel = conv.document_label || conv.file_id;
        _activeDocGone  = false;
      } else if (conv.document_label) {
        // Document-linked thread whose document was deleted.
        _activeFileId   = null;
        _activeDocLabel = conv.document_label;
        _activeDocGone  = true;
      } else {
        // General Assistant thread — no document scope.
        _activeFileId   = null;
        _activeDocLabel = null;
        _activeDocGone  = false;
      }
      _updateSidebarFromOcrState();

      // Re-render the message thread
      const msgs = $('chat-messages');
      if (msgs) msgs.querySelectorAll('.chat-msg-row').forEach(el => el.remove());
      _hideWelcome();
      (data.messages || []).forEach(m => {
        _history.push({ role: m.role === 'assistant' ? 'assistant' : 'user', content: m.content });
        _appendBubble(m.role === 'assistant' ? 'ai' : 'user', m.content, m.sources || []);
      });
      _touchActiveRow();
    } catch (_) {}
  }

  async function _renameConversation(c) {
    const title = window.prompt('Đổi tên cuộc trò chuyện:', c.title || '');
    if (title == null) return;
    const t = title.trim();
    if (!t) return;
    try {
      const res = await fetch('/api/chat/conversations/' + c.id, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: t }),
      });
      if (res.ok) _loadConversations();
    } catch (_) {}
  }

  async function _deleteConversation(c) {
    if (!window.confirm(`Xóa cuộc trò chuyện "${c.title}"?`)) return;
    try {
      const res = await fetch('/api/chat/conversations/' + c.id, { method: 'DELETE' });
      if (res.ok) {
        if (c.id === _conversationId) clearHistory();
        _loadConversations();
      }
    } catch (_) {}
  }

  function _setModePill(mode) {
    // Only two chat modes exist: Document Chat + General Chat. Fold any legacy
    // "all documents" thread back to Document Chat so it reopens cleanly.
    if (mode !== 'general') mode = 'doc_current';
    _mode = mode;
    document.querySelectorAll('.chat-mode-pill').forEach(b => {
      b.classList.toggle('active', b.dataset.mode === mode);
    });
    _updateInputPlaceholder();
  }

  // ── Model status polling ───────────────────────────────────────────────────
  function _pollModelStatus() {
    _checkStatus();
    _statusTimer = setInterval(_checkStatus, 8000);
  }

  async function _checkStatus() {
    try {
      const res  = await fetch('/api/chat/status');
      if (!res.ok) return;
      const data = await res.json();
      _updateModelBadge(data);
      if (data.model_ready) {
        clearInterval(_statusTimer);
        _modelReady = true;
      }
    } catch (_) {}
  }

  function _updateModelBadge(data) {
    const badge = $('chat-model-badge');
    const text  = $('chat-model-badge-text');
    if (!badge || !text) return;

    badge.className = 'chat-model-badge';

    if (data.model_ready) {
      badge.classList.add('ready');
      text.textContent = '✓ AI Assistant Ready';
    } else if (data.model_loading) {
      badge.classList.add('loading');
      text.textContent = 'Đang tải mô hình…';
    } else if (data.model_error) {
      badge.classList.add('error');
      text.textContent = '✗ Mô hình không khả dụng';
    } else {
      badge.classList.add('loading');
      text.textContent = 'Chưa tải…';
    }
  }

  // ── Busy state ─────────────────────────────────────────────────────────────
  function _setBusy(busy) {
    _busy = busy;
    const btn   = $('chat-send-btn');
    const input = $('chat-input');
    if (btn) {
      btn.disabled = false;   // always clickable (send OR stop)
      if (busy) {
        btn.classList.add('stop-mode');
        btn.classList.remove('sending');
        btn.title       = 'Dừng tạo (⏹)';
        btn.textContent = '⏹';
      } else {
        btn.classList.remove('stop-mode', 'sending');
        btn.title       = 'Gửi (Enter)';
        btn.textContent = '➤';
      }
    }
    // Keep input enabled so user can type-ahead while generating
    if (input) input.disabled = false;
  }

  // ── Utilities ──────────────────────────────────────────────────────────────
  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _showToast(msg, type) {
    // Delegate to existing app toast system if available
    if (window.App && typeof window.App.toast === 'function') {
      window.App.toast(msg, type);
      return;
    }
    // Fallback: use existing #toast-wrap
    const wrap = document.getElementById('toast-wrap');
    if (!wrap) return;
    const el = document.createElement('div');
    el.className = `toast ${type || 'info'}`;
    el.textContent = msg;
    wrap.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  // ── Public API ─────────────────────────────────────────────────────────────
  return {
    init,
    sendMessage,
    clearHistory,
    /** Call when navigating to the chat view */
    onViewActivated() {
      _seedScopeFromOcr();
      _updateSidebarFromOcrState();
      _loadConversations();
      // Kick off model load if not started
      fetch('/api/chat/status').then(r => r.json()).then(data => {
        _updateModelBadge(data);
        if (!data.model_ready && !data.model_loading) {
          // Trigger lazy load by sending a dummy status check (server starts on first /send)
        }
      }).catch(() => {});
    },
    /** Called by app.js when OCR completes to auto-refresh sidebar */
    onOcrComplete(fileId, text, filename) {
      // window.App.lastFileId etc. are getter-only proxies — write to
      // the mutable backing object that the getters read from instead.
      if (window._chatBridge) {
        window._chatBridge.fileId   = fileId;
        window._chatBridge.ocrText  = text;
        window._chatBridge.filename = filename;
      }
      // A freshly OCR'd document becomes the active chat scope, and the next
      // message starts a new thread attached to it (not the previously open one).
      if (fileId) {
        _activeFileId   = fileId;
        _activeDocLabel = filename || fileId;
        _activeDocGone  = false;
        _conversationId = null;
        _forceNew       = true;
      }
      _updateSidebarFromOcrState();
    },
    /** Open a conversation by id (deep link #chat/<id>). */
    openConversation(id) {
      const n = parseInt(id, 10);
      if (!isNaN(n)) _openConversation(n);
    },
  };

})();

// ── Boot ───────────────────────────────────────────────────────────────────
// View activation is driven by the hash router (Router._render calls
// ChatModule.onViewActivated when the #chat view is shown), so no goto patch.
document.addEventListener('DOMContentLoaded', () => {
  ChatModule.init();
  // Expose globally so app.js / the router can reach it.
  window.ChatModule = ChatModule;
  // Cold-load deep link: app.js Router.init() ran its first render before this
  // module existed, so re-render if the URL points at the chat view.
  if (/^#chat(\/|$)/.test(location.hash) && window.Router && window.Router._render) {
    window.Router._render();
  }
});
