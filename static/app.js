/* PaddleOCR Studio — app.js */

// ── Toast ──────────────────────────────────────────────
const Toast = {
  show(msg, type = 'info', ms = 3500) {
    const ico = { success:'✅', error:'❌', info:'ℹ️' };
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `<span>${ico[type]||'ℹ️'}</span><span>${msg}</span>`;
    document.getElementById('toast-wrap').appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s';
      setTimeout(() => el.remove(), 300); }, ms);
  }
};

// ── Clipboard ──────────────────────────────────────────
// Reliable copy for modern browsers AND http:// LAN origins. The async Clipboard API
// only exists in a secure context (https or localhost); on a plain-http LAN IP it is
// undefined (or rejects), so we fall back to a hidden-textarea execCommand.
// Returns true on success, false on failure.
async function copyTextToClipboard(text) {
  text = text == null ? '' : String(text);
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (_) { /* fall through to the legacy path below */ }
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed'; ta.style.top = '0'; ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select(); ta.setSelectionRange(0, ta.value.length);
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch (_) { return false; }
}

// Copy + toast feedback. Empty/whitespace content → info toast (nothing copied);
// success → green message (custom or "Copied!"); failure → red "Failed to copy".
async function copyWithToast(text, successMsg) {
  const s = text == null ? '' : String(text);
  if (!s.trim()) { Toast.show(t('copy_nothing'), 'info'); return false; }
  const ok = await copyTextToClipboard(s);
  Toast.show(ok ? (successMsg || t('copied')) : t('copy_failed'), ok ? 'success' : 'error');
  return ok;
}

// ── API ────────────────────────────────────────────────
const API = {
  async upload(file) {
    const fd = new FormData(); fd.append('file', file);
    const r = await fetch('/api/upload', { method: 'POST', body: fd });
    return r.json();
  },
  async ocrPage(fileId, page, engine = 'auto', aiEnhancement = false, previewOnly = false) {
    return (await fetch('/api/ocr/page', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ file_id: fileId, page, engine: engine, ai_enhancement: aiEnhancement, preview_only: previewOnly }) })).json();
  },
  async ocrAll(fileId, engine = 'auto', aiEnhancement = false) {
    return (await fetch('/api/ocr/all', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ file_id: fileId, engine: engine, ai_enhancement: aiEnhancement }) })).json();
  },
  async readText(fileId) {
    return (await fetch('/api/read-text', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ file_id: fileId }) })).json();
  },
  async correct(text) {
    return (await fetch('/api/correct', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ text }) })).json();
  },
  async translate(text, from_lang, to_lang, engine = 'auto', fileId = null) {
    return (await fetch('/api/translate', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ text, from_lang, to_lang, engine, file_id: fileId }) })).json();
  },
  async getDocText(docId) {                       // G1: persisted artifacts for a document
    return (await fetch(`/api/documents/${docId}/text`)).json();
  },
  async getOcrImages(docId) {                      // lazy: base64 extracted-image artifacts
    return (await fetch(`/api/documents/${docId}/ocr-images`)).json();
  },
  async translateStatus(force = false) {
    const url = force ? '/api/translate/status?force=1' : '/api/translate/status';
    return (await fetch(url)).json();
  },
  async summarize(text, mode, engine = 'auto', summary_mode = 'fast', fileId = null) {
    return (await fetch('/api/summarize', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ text, mode, engine, summary_mode, file_id: fileId }) })).json();
  },
  async summarizeStatus() {
    return (await fetch('/api/summarize/status')).json();
  },
  // ── Settings (cloud keys + privacy). The API key travels only in the save/
  // test request body over the session — it is never echoed back or stored
  // client-side (no localStorage / no State).
  async settingsGet() {
    return (await fetch('/api/settings')).json();
  },
  async settingsPrivacy(allowCloud, ack) {
    return (await fetch('/api/settings/privacy', { method:'PUT',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ allow_cloud: allowCloud, ack: !!ack }) })).json();
  },
  async settingsSaveKey(provider, apiKey) {
    return (await fetch('/api/settings/keys/' + encodeURIComponent(provider), {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ api_key: apiKey }) })).json();
  },
  async settingsDeleteKey(provider) {
    return (await fetch('/api/settings/keys/' + encodeURIComponent(provider), {
      method:'DELETE' })).json();
  },
  async settingsTestKey(provider, apiKey) {
    return (await fetch('/api/settings/keys/' + encodeURIComponent(provider) + '/test', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(apiKey ? { api_key: apiKey } : {}) })).json();
  }
};

// ── Shared state ───────────────────────────────────────
const State = {
  ocrText: '',           // last OCR full text (for chaining)
  activeDocFileId: null, // G1: file_id of the document a tool view is currently working on
                         //     (so re-running translate/summarize persists back to it)
  aiModel: { name: '', device: '' },  // actual loaded AI model (from /api/summarize/status),
                                       // so badges show the real model instead of a hardcoded name
  setOcrText(t) { this.ocrText = t; }
};

// ── Download ───────────────────────────────────────────
function dlTxt(text, name = 'result.txt') {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type:'text/plain' }));
  a.download = name; a.click();
}
function dlBlob(text, name, mime = 'text/plain') {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: mime }));
  a.download = name; a.click();
}

// ── Minimal HTML sanitizer for rendering model-produced tables (own-document,
//    same-user context). Strips active content and event/URL handlers. ────────
function sanitizeHtml(html) {
  const tmp = document.createElement('div');
  tmp.innerHTML = String(html || '');
  tmp.querySelectorAll('script,style,iframe,object,embed,link,meta').forEach(n => n.remove());
  tmp.querySelectorAll('*').forEach(el => {
    [...el.attributes].forEach(a => {
      const n = a.name.toLowerCase();
      if (n.startsWith('on') ||
          ((n === 'href' || n === 'src') && /^\s*javascript:/i.test(a.value))) {
        el.removeAttribute(a.name);
      }
    });
  });
  return tmp.innerHTML;
}

// ── LaTeX → HTML via vendored KaTeX (offline). Returns null on failure so the
//    caller can leave the original delimiters in place. ────────────────────────
function katexToHtml(tex, displayMode) {
  try {
    if (window.katex) {
      return window.katex.renderToString(tex, { displayMode, throwOnError: false, strict: false });
    }
  } catch (_) { /* fall through */ }
  return null;
}

// ── Markdown → sanitized HTML (vendored marked; raw HTML tables pass through),
//    with offline KaTeX math rendering. GLM/Modern emit LaTeX ($…$, $$…$$, \(…\),
//    \[…\]); marked has no math support AND mangles backslashes (the \\ row breaks
//    in arrays/matrices collapse to \), so math is rendered with KaTeX BEFORE marked
//    tokenizes — swapped out for placeholders, then the trusted KaTeX HTML is
//    restored after marked + sanitize. `math` is gated on real markdown so bare `$`
//    in plain text (currency) is never mistaken for inline math. ─────────────────
function renderMarkdown(md, math) {
  let src = String(md || '');
  if (!src.trim()) return '';
  const store = [];
  // Private-use sentinels survive HTML round-trips and are never markdown-special.
  const stash = (html) => '\uE000' + (store.push(html) - 1) + '\uE001';
  if (math && window.katex) {
    // Display math first ($$…$$, \[…\]), then inline ($…$, \(…\)).
    src = src.replace(/\$\$([\s\S]+?)\$\$/g,   (m, t) => { const h = katexToHtml(t.trim(), true);  return h ? '\n\n' + stash(h) + '\n\n' : m; });
    src = src.replace(/\\\[([\s\S]+?)\\\]/g,   (m, t) => { const h = katexToHtml(t.trim(), true);  return h ? '\n\n' + stash(h) + '\n\n' : m; });
    src = src.replace(/\$(?!\$)((?:\\.|[^$\\\n])+?)\$/g, (m, t) => { const h = katexToHtml(t, false); return h ? stash(h) : m; });
    src = src.replace(/\\\(([\s\S]+?)\\\)/g,   (m, t) => { const h = katexToHtml(t, false); return h ? stash(h) : m; });
  }
  let html = null;
  try {
    if (window.marked) html = window.marked.parse ? window.marked.parse(src) : window.marked(src);
  } catch (_) { /* fall through to escaped plaintext */ }
  if (html == null) html = '<pre>' + esc(src) + '</pre>';
  html = sanitizeHtml(html);
  // Restore trusted KaTeX HTML (we generated it; KaTeX never emits scripts/handlers).
  if (store.length) html = html.replace(/\uE000(\d+)\uE001/g, (_, i) => store[+i] || '');
  return html;
}

// ── Router ─────────────────────────────────────────────
// Hash-based router: location.hash is the single source of truth for SPA view
// state, so browser Back/Forward (and bookmarks/refresh) work natively. Admin is
// a separate server-rendered app at /admin/* and is reached by real navigation.
const Router = {
  current: null,
  views: {},
  register(name, el) { this.views[name] = el; },
  _show(name) {
    Object.entries(this.views).forEach(([n, el]) => el.classList.toggle('v-hidden', n !== name));
    this.current = name;
    document.querySelectorAll('.nav-link').forEach(l =>
      l.classList.toggle('active', l.dataset.view === name));
  },
  // Navigate by setting the hash (optionally with a deep-link arg). The hashchange
  // listener calls _render(); calling with the current hash re-renders in place.
  goto(name, arg) {
    const hash = '#' + name + (arg ? '/' + encodeURIComponent(arg) : '');
    if (location.hash === hash) this._render();
    else location.hash = hash;
  },
  back() { history.back(); },
  // Render the view + run any deep-link handler from the current hash.
  _render() {
    const raw = (location.hash || '').replace(/^#/, '');
    const slash = raw.indexOf('/');
    const name  = (slash === -1 ? raw : raw.slice(0, slash)) || 'home';
    const arg   = slash === -1 ? null : decodeURIComponent(raw.slice(slash + 1));
    const view  = this.views[name] ? name : 'home';
    this._show(view);
    // Deep links reuse existing open paths (loaders, NOT navigators — no goto here).
    if (view === 'ocr' && arg && typeof OCRView !== 'undefined') {
      OCRView._openFromFileId(arg);
    } else if ((view === 'translate' || view === 'summarize') && arg
               && typeof DocumentsView !== 'undefined') {
      DocumentsView._openToolFromFileId(view, arg);   // Phase 13 — agent "View Result"
    } else if (view === 'chat' && window.ChatModule) {
      if (typeof window.ChatModule.onViewActivated === 'function') window.ChatModule.onViewActivated();
      if (arg && typeof window.ChatModule.openConversation === 'function') window.ChatModule.openConversation(arg);
    }
  },
  init() {
    window.addEventListener('hashchange', () => this._render());
    this._render();
  }
};

// ══════════════════════════════════════════════════════
// OCR View
// ══════════════════════════════════════════════════════
const OCRView = {
  fileId: null, isPdf: false, pageCount: 1, currentPage: 1,
  pages: {}, zoom: 1, rotate: 0, canvas: null,
  ocrEngine: 'glmocr', _sessionEngine: 'glmocr',  // default = ⭐ Recommended; _sessionEngine remembers a manual pick across in-app navigation
  ocrAi: false, ocrLayout: 'enhanced', ocrSelectionMode: false,
  ocrView: 'md',      // active result tab: md | raw | images | json
  _abortCtrl: null,   // active AbortController for the current OCR fetch
  // Cache of the current page's renderable artifacts (driven by the OCR response /
  // restored artifacts), so tab switches and downloads don't recompute.
  _plainText: '', _markdown: '', _hasRealMd: false, _images: [], _jsonText: '',
  _curDocId: null,    // document id (for lazy image fetch when restoring a saved doc)

  init() {
    this.canvas = new OCRCanvas(
      document.getElementById('overlay-canvas'),
      document.getElementById('preview-img')
    );
    this.canvas.onHover  = (i, e) => this._hover(i, e);
    this.canvas.onSelect = i => this._select(i);
    this.canvas.onRegionSelect = rect => this._onRegionSelect(rect);

    document.getElementById('ocr-file-input').addEventListener('change', e => {
      if (e.target.files[0]) this._upload(e.target.files[0]);
    });
    const dz = document.getElementById('ocr-drop-zone');
    const fi = document.getElementById('ocr-file-input');
    dz.addEventListener('click', () => fi.click());
    dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('drag-over'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));
    dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('drag-over');
      if (e.dataTransfer.files[0]) this._upload(e.dataTransfer.files[0]); });

    document.getElementById('btn-ocr-run').addEventListener('click', () => this._ocrPage(this.currentPage));
    document.getElementById('btn-ocr-all').addEventListener('click', () => this._ocrAll());
    document.getElementById('btn-ocr-reset').addEventListener('click', () => this._reset());
    document.getElementById('btn-ocr-stop').addEventListener('click', () => this._ocrStop());
    document.getElementById('btn-zoom-in').addEventListener('click',  () => this._setZoom(this.zoom + 0.2));
    document.getElementById('btn-zoom-out').addEventListener('click', () => this._setZoom(this.zoom - 0.2));
    document.getElementById('btn-zoom-fit').addEventListener('click', () => this._setZoom(1));
    document.getElementById('btn-rotate').addEventListener('click', () => { this.rotate=(this.rotate+90)%360; this._applyTransform(); });
    document.getElementById('btn-select-region').addEventListener('click', () => {
      this.ocrSelectionMode = !this.ocrSelectionMode;
      document.getElementById('btn-select-region').classList.toggle('active', this.ocrSelectionMode);
      this.canvas.setSelectionMode(this.ocrSelectionMode);
    });
    document.getElementById('btn-prev-page').addEventListener('click', () => this._goPage(this.currentPage - 1));
    document.getElementById('btn-next-page').addEventListener('click', () => this._goPage(this.currentPage + 1));
    document.getElementById('ocr-page-input').addEventListener('change', e => this._goPage(+e.target.value));
    document.getElementById('ocr-copy-btn').addEventListener('click', () => {
      const text = this.ocrView === 'json' ? this._jsonText : this._activeOcrText();
      copyWithToast(text, t('toast_text_copied'));
    });
    // Download Markdown (real markdown when present, else plain text rendered as .md).
    document.getElementById('ocr-dl-md').addEventListener('click', () =>
      dlBlob(this._markdown || this._plainText || '', 'ocr-result.md', 'text/markdown'));
    // Download JSON (structured OCR output across all pages).
    document.getElementById('ocr-dl-json').addEventListener('click', () =>
      dlBlob(this._buildJsonExport(), 'ocr-result.json', 'application/json'));
    document.getElementById('ocr-dl-txt').addEventListener('click', () =>
      dlTxt(this._plainText || State.ocrText || '', 'ocr-result.txt'));
    // Chain buttons — send the ACTIVE view's content (opt-in markdown/html for Modern).
    document.getElementById('ocr-send-correct').addEventListener('click', () => {
      State.setOcrText(this._activeOcrText());
      CorrectView.importText(State.ocrText); Router.goto('correct');
    });
    document.getElementById('ocr-send-translate').addEventListener('click', () => {
      State.setOcrText(this._activeOcrText());
      TranslateView.importText(State.ocrText); Router.goto('translate');
    });
    document.getElementById('ocr-send-summarize').addEventListener('click', () => {
      State.setOcrText(this._activeOcrText());
      SummarizeView.importText(State.ocrText); Router.goto('summarize');
    });
    // Launch the Agent workspace scoped to THIS document (Phase 13). The agent page
    // is a separate app at /agent — reached by real navigation, like Admin.
    document.getElementById('ocr-ask-agent')?.addEventListener('click', () => {
      if (!this.fileId) { Toast.show(t('toast_run_ocr_first') || 'Open a document first', 'info'); return; }
      window.location.href = '/agent?file_id=' + encodeURIComponent(this.fileId);
    });

    // ── Structured-output view tabs (Text / Markdown / HTML / Table) ──────────
    document.querySelectorAll('#ocr-view-tabs .ocr-vtab').forEach(btn => {
      btn.addEventListener('click', () => this._setOcrView(btn.dataset.vtab));
    });

    // ── OCR Engine & AI selector ──────────────────────────────────────────
    const engineSelect = document.getElementById('ocr-engine-select');
    if (engineSelect) {
      engineSelect.addEventListener('change', (e) => {
        // Respect & persist the user's manual choice for the rest of the session;
        // never auto-switch away from it (see _resetMode).
        this.ocrEngine = e.target.value;
        this._sessionEngine = e.target.value;
      });
      engineSelect.value = this.ocrEngine;
    }
    document.querySelectorAll('#ocr-ai-toggle .ocr-mode-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this.ocrAi = btn.dataset.ai === 'true';
        this._updateModeSelector();
      });
    });
    document.querySelectorAll('#ocr-layout-toggle .ocr-mode-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this.ocrLayout = btn.dataset.layout;
        this._updateModeSelector();
        // Immediately re-render current page from cache
        const cacheKey = this.ocrEngine + '_' + this.ocrAi;
        const cached = this.pages[this.currentPage]?.[cacheKey];
        if (cached) {
          const results = this.ocrLayout === 'original' ? (cached.raw_results || cached.results) : cached.results;
          if (this.canvas) {
            this.canvas.load(results, cached.img_width, cached.img_height);
            this.canvas.draw();
          }
          this._renderResults(cached); this._renderStructured(cached); this._updateStats(cached);
          this._renderTextAll();
        }
      });
    });
    this._updateModeSelector();

    window.addEventListener('resize', () => { if (this.canvas) { this.canvas.resize(); this.canvas.draw(); } });
  },

  _updateModeSelector() {
    document.querySelectorAll('#ocr-ai-toggle .ocr-mode-btn').forEach(btn => {
      btn.classList.toggle('active', (btn.dataset.ai === 'true') === this.ocrAi);
    });
    document.querySelectorAll('#ocr-layout-toggle .ocr-mode-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.layout === this.ocrLayout);
    });
  },

  _resetMode() {
    // Keep the user's session engine choice (default ⭐ Recommended) across nav.
    this.ocrEngine = this._sessionEngine || 'glmocr';
    this.ocrAi = false;
    this.ocrLayout = 'enhanced';
    const engineSelect = document.getElementById('ocr-engine-select');
    if (engineSelect) engineSelect.value = this.ocrEngine;
    this._updateModeSelector();
  },

  // Clear the viewer's visible state to a clean blank slate. Used when loading a
  // NEW file (upload or from the library) so the previous file's OCR text/boxes/
  // stats never linger in the DOM. (Fixes: opening a file showed the last file's
  // OCR when the selected file had no persisted OCR of its own.)
  _resetViewerState() {
    const detList = document.getElementById('det-list');
    if (detList) detList.innerHTML = '';
    const empty = document.getElementById('ocr-empty-results');
    if (empty) empty.style.display = 'flex';
    const sReg = document.getElementById('stat-regions'); if (sReg) sReg.textContent = '0';
    const sConf = document.getElementById('stat-conf'); if (sConf) sConf.textContent = '—';
    const sTime = document.getElementById('stat-time'); if (sTime) sTime.textContent = '0';
    const sPages = document.getElementById('stat-pages');
    if (sPages) sPages.textContent = `${this.currentPage || 1}/${this.pageCount || '?'}`;
    const raw = document.getElementById('ocr-md-raw'); if (raw) raw.value = '';
    const rend = document.getElementById('ocr-md-rendered'); if (rend) rend.innerHTML = '';
    const imgs = document.getElementById('ocr-images'); if (imgs) imgs.innerHTML = '';
    const jsn = document.getElementById('ocr-json'); if (jsn) { const c = jsn.querySelector('code'); if (c) c.textContent = ''; }
    this._plainText = ''; this._markdown = ''; this._hasRealMd = false; this._images = []; this._jsonText = '';
    this._curDocId = null;
    const badge = document.getElementById('ocr-status-badge');
    if (badge) badge.style.display = 'none';
    if (this.canvas) this.canvas.load([], 1, 1);
    if (typeof State !== 'undefined' && State.setOcrText) State.setOcrText('');
  },


  async _upload(file) {
    const allowed = ['.jpg','.jpeg','.png','.webp','.pdf'];
    const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    if (!allowed.includes(ext)) { Toast.show(t('toast_unsupported'), 'error'); return; }
    
    // Reset file input so same file can be selected again
    const fi = document.getElementById('ocr-file-input');
    if (fi) fi.value = '';

    this.isPdf = ext === '.pdf';
    this.currentPage = 1;
    this.pageCount = 1;
    this.pages = {};
    this.fileId = null;

    // 1. Swap UI IMMEDIATELY
    document.getElementById('ocr-upload-zone').style.display = 'none';
    document.getElementById('ocr-workspace').style.display = 'grid';
    document.getElementById('ocr-file-name').textContent = file.name;

    // 2. Clear UI state (shared with library-open so neither leaks prior results)
    this._resetViewerState();

    // 3. Display Local Preview IMMEDIATELY
    const img = document.getElementById('preview-img');
    if (!this.isPdf) {
      if (this._previewUrl) URL.revokeObjectURL(this._previewUrl);
      this._previewUrl = URL.createObjectURL(file);
      
      img.onload = () => {
        if (this.canvas) {
          this.canvas.load([], img.naturalWidth, img.naturalHeight);
        }
        this._applyTransform();
      };
      img.src = this._previewUrl;
      img.style.display = 'block';
    } else {
      if (this.canvas) this.canvas.load([], 1, 1);
      // For PDFs, we'll request a preview from the backend after upload
      img.src = ''; 
      img.style.display = 'none';
    }

    // 4. Background Upload
    try {
      const data = await API.upload(file);
      if (!data.success) { Toast.show(data.error, 'error'); return; }
      
      this.fileId = data.file_id;
      this.pageCount = data.page_count;
      document.getElementById('stat-pages').textContent = `1/${this.pageCount}`;
      this._buildTabs();
      this._updateNav();
      
      // 5. If PDF, trigger immediate preview of Page 1
      if (this.isPdf) this._ocrPage(1, true); 
    } catch (e) {
      Toast.show(e.message, 'error');
    }
  },

  _buildTabs() {
    const bar = document.getElementById('page-tabs-bar');
    bar.style.display = this.isPdf && this.pageCount > 1 ? 'flex' : 'none';
    bar.innerHTML = '';
    for (let p = 1; p <= this.pageCount; p++) {
      const b = document.createElement('button'); b.className = 'pg-tab'; b.textContent = `Page ${p}`; b.dataset.page = p;
      b.addEventListener('click', () => this._goPage(p)); bar.appendChild(b);
    }
    this._updateTabs();
  },
  _updateTabs() {
    document.querySelectorAll('.pg-tab').forEach(t => {
      const p = +t.dataset.page;
      const pageModes = this.pages[p] || {};
      const hasAnyMode = !!(pageModes.standard || pageModes.smart);
      t.classList.toggle('active', p === this.currentPage);
      t.classList.toggle('done', hasAnyMode && p !== this.currentPage);
    });
  },
  _goPage(p) {
    p = Math.max(1, Math.min(this.pageCount, p));
    this.currentPage = p; this._updateNav(); this._updateTabs();
    const cacheKey = this.ocrEngine + '_' + this.ocrAi;
    const cached = this.pages[p]?.[cacheKey];
    if (cached) this._renderPage(cached);
    else this._ocrPage(p, true);
  },
  _updateNav() {
    document.getElementById('ocr-page-input').value = this.currentPage;
    document.getElementById('ocr-page-total').textContent = `/ ${this.pageCount}`;
    document.getElementById('btn-prev-page').disabled = this.currentPage <= 1;
    document.getElementById('btn-next-page').disabled = this.currentPage >= this.pageCount;
  },

  async _ocrPage(p, previewOnly = false) {
    if (!previewOnly) this._setLoading(true);
    this._abortCtrl = new AbortController();
    try {
      const data = await API.ocrPage(this.fileId, p, this.ocrEngine, this.ocrAi, previewOnly, this._abortCtrl.signal);
      if (!data.success) { Toast.show(data.error, 'error'); return; }
      this.pages[p] ||= {};
      const cacheKey = this.ocrEngine + '_' + this.ocrAi;
      this.pages[p][cacheKey] = data;
      this._renderPage(data); this._updateTabs();
      // A preview load (opening a file) returns no regions — the real count comes from
      // the restored artifact, so only announce a count for an actual OCR run.
      if (!previewOnly) {
        const modeLabel = this.ocrAi ? ' 🧠' : '';
        Toast.show(`${t('nav_ocr')}: ${data.results.length} ${t('regions_found')}${modeLabel}`, 'success');
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        Toast.show('OCR cancelled.', 'info');
      } else {
        Toast.show('OCR failed: ' + err.message, 'error');
      }
    } finally {
      this._abortCtrl = null;
      if (!previewOnly) this._setLoading(false);
    }
  },

  async _ocrAll() {
    this._setLoading(true, true);
    this._abortCtrl = new AbortController();
    try {
      const data = await API.ocrAll(this.fileId, this.ocrEngine, this.ocrAi, this._abortCtrl.signal);
      if (!data.success) { Toast.show(data.error, 'error'); return; }
      const cacheKey = this.ocrEngine + '_' + this.ocrAi;
      data.pages.forEach(p => {
        this.pages[p.page_num] ||= {};
        this.pages[p.page_num][cacheKey] = p;
      });
      this._renderPage(this.pages[this.currentPage][cacheKey]);
      this._updateTabs(); this._updateStats();
      const modeLabel = this.ocrAi ? ' 🧠' : '';
      Toast.show(`${data.pages.length} ${t('pages_done')}${modeLabel}`, 'success');
    } catch (err) {
      if (err.name === 'AbortError') {
        Toast.show('OCR cancelled.', 'info');
      } else {
        Toast.show('OCR all failed: ' + err.message, 'error');
      }
    } finally {
      this._abortCtrl = null;
      this._setLoading(false);
    }
  },

  _ocrStop() {
    if (this._abortCtrl) {
      this._abortCtrl.abort();
    }
  },

  _renderPage(data) {
    const img = document.getElementById('preview-img');
    img.style.display = 'block';
    img.onload = () => {
      document.getElementById('overlay-canvas').classList.add('interactive');
      const results = this.ocrLayout === 'original' ? (data.raw_results || data.results) : data.results;
      this.canvas.load(results, data.img_width, data.img_height);
      this._applyTransform();
    };
    img.src = `data:image/png;base64,${data.page_image_b64}`;
    this._renderResults(data); this._renderStructured(data); this._updateStats(data);
    this._renderTextAll();
  },

  _renderTextAll() {
    const cacheKey = this.ocrEngine + '_' + this.ocrAi;
    const allText = Object.values(this.pages)
      .map(pageModes => pageModes?.[cacheKey])
      .filter(Boolean)
      .flatMap(p => {
        const arr = this.ocrLayout === 'original' ? (p.raw_results || p.results) : p.results;
        return (arr || []).map(r => r.text);
      })
      .join('\n');
    State.setOcrText(allText);
  },

  _renderResults(data) {
    const list = document.getElementById('det-list');
    const empty = document.getElementById('ocr-empty-results');
    // Only remove detection items — keep #ocr-empty-results in the DOM
    list.querySelectorAll('.det-item').forEach(el => el.remove());
    const results = this.ocrLayout === 'original' ? (data?.raw_results || data?.results) : data?.results;
    if (!results?.length) { if (empty) empty.style.display='flex'; return; }
    if (empty) empty.style.display = 'none';
    results.forEach((item, i) => {
      const cc = item.confidence >= .9 ? 'conf-high' : item.confidence >= .7 ? 'conf-med' : 'conf-low';
      const div = document.createElement('div'); div.className='det-item'; div.id=`det-${i}`;
      div.innerHTML = `<span class="det-text">${esc(item.text)}</span>
        ${item.confidence!=null?`<span class="det-conf ${cc}">${(item.confidence*100).toFixed(1)}%</span>`:''}`;
      div.addEventListener('click', () => {
        document.querySelectorAll('.det-item').forEach(d=>d.classList.remove('selected'));
        div.classList.add('selected'); this.canvas.selectByIndex(i); this.canvas.draw();
      });
      list.appendChild(div);
    });
  },

  // Content sent to Correct/Translate/Summarize. On the Markdown tabs (rendered/raw)
  // send markdown when the engine produced real markdown, otherwise plain text. The
  // raw textarea is editable, so its (possibly edited) value wins on the raw tab.
  _activeOcrText() {
    const raw = document.getElementById('ocr-md-raw');
    if (this.ocrView === 'raw' && raw) return raw.value;
    if (this.ocrView === 'md')  return this._hasRealMd ? (this._markdown || '') : (this._plainText || '');
    return this._plainText || (raw ? raw.value : '');
  },

  _setOcrView(tab) {
    // Don't switch to a disabled tab (e.g. Images when there are none).
    const btn = document.querySelector(`#ocr-view-tabs .ocr-vtab[data-vtab="${tab}"]`);
    if (btn && btn.disabled) tab = 'md';
    this.ocrView = tab;
    document.querySelectorAll('#ocr-view-tabs .ocr-vtab').forEach(b =>
      b.classList.toggle('active', b.dataset.vtab === tab));
    const show = (id, on) => { const el = document.getElementById(id); if (el) el.style.display = on ? '' : 'none'; };
    show('ocr-md-rendered', tab === 'md');
    show('ocr-md-raw',      tab === 'raw');
    show('ocr-images',      tab === 'images');
    show('ocr-json',        tab === 'json');
    // Lazily fetch extracted images for a restored document the first time the tab opens.
    if (tab === 'images' && !this._images.length && this._curDocId != null) {
      this._loadImagesForDoc(this._curDocId);
    }
  },

  // Artifact-driven renderer: populates all four tabs from a page result (live OCR)
  // or a restore-synthesized object. Markdown is the default; the Images tab is
  // disabled when the engine produced no visual artifacts. No per-engine forks.
  _renderStructured(data) {
    const results = (data && (data.results)) || [];
    const plain = results.map(r => r.text).filter(s => (s || '').trim()).join('\n');
    const realMd = (data && typeof data.markdown === 'string' && data.markdown.trim()) ? data.markdown : '';
    const md = realMd || plain;
    this._plainText = plain;
    this._markdown  = realMd;
    this._hasRealMd = !!realMd;
    this._images    = (data && data.images) || [];

    const rend = document.getElementById('ocr-md-rendered');
    if (rend) rend.innerHTML = renderMarkdown(md, this._hasRealMd) ||
      '<div class="output-empty"><div class="oe-icon">📝</div><div>No text</div></div>';
    const raw = document.getElementById('ocr-md-raw');
    if (raw) raw.value = md;

    // JSON: prefer the engine's structured raw_json; else the results + layout blocks.
    const jsonObj = (data && data.raw_json) || {
      results, layout_blocks: (data && data.layout_blocks) || undefined,
    };
    this._jsonText = JSON.stringify(jsonObj, null, 2);
    const jc = document.querySelector('#ocr-json code');
    if (jc) jc.textContent = this._jsonText;

    this._renderImages(this._images);
    this._setOcrView(this.ocrView || 'md');
  },

  // Document-viewer rendering: one large fit-to-container stage (wheel/click zoom + drag
  // pan) plus a horizontal thumbnail strip when there's more than one image.
  _renderImages(images) {
    const box = document.getElementById('ocr-images');
    const tabBtn = document.querySelector('#ocr-view-tabs .ocr-vtab[data-vtab="images"]');
    const has = !!(images && images.length);
    if (tabBtn) { tabBtn.disabled = !has; tabBtn.classList.toggle('disabled', !has); }
    if (!box) return;
    if (!has) {
      this._iv = null;
      box.innerHTML = '<div class="output-empty"><div class="oe-icon">🖼</div><div>No extracted images for this engine</div></div>';
      return;
    }
    const multi = images.length > 1;
    const cap = im => `${esc(im.kind || 'image')}${im.page ? (' · p' + im.page) : ''}`;
    box.innerHTML = `
      <div class="ocr-iv-stage" tabindex="0">
        <img class="ocr-iv-img" draggable="false" alt="">
        <div class="ocr-iv-bar">
          <button class="ocr-iv-btn" data-iv="out" title="Zoom out">−</button>
          <span class="ocr-iv-zoom">100%</span>
          <button class="ocr-iv-btn" data-iv="in" title="Zoom in">+</button>
          <button class="ocr-iv-btn" data-iv="fit" title="Fit to view">⤢</button>
          <span class="ocr-iv-count"></span>
        </div>
        <div class="ocr-iv-cap"></div>
      </div>
      ${multi ? `<div class="ocr-iv-strip">${images.map((im, i) => `
        <button class="ocr-iv-thumb" data-idx="${i}" title="${esc(im.label || cap(im))}">
          <img src="${im.src}" alt="" loading="lazy">
          <span>${cap(im)}</span>
        </button>`).join('')}</div>` : ''}`;
    this._initImageViewer(images);
  },

  // Wire zoom (wheel + buttons), click-to-zoom-toggle, drag-to-pan and thumbnail
  // navigation for the Extracted Images stage. State lives on this._iv.
  _initImageViewer(images) {
    const box = document.getElementById('ocr-images');
    const stage = box.querySelector('.ocr-iv-stage');
    const img = box.querySelector('.ocr-iv-img');
    const zoomLbl = box.querySelector('.ocr-iv-zoom');
    const countLbl = box.querySelector('.ocr-iv-count');
    const capLbl = box.querySelector('.ocr-iv-cap');
    const iv = this._iv = { images, idx: 0, scale: 1, tx: 0, ty: 0, drag: null, moved: false };

    const apply = () => {
      img.style.transform = `translate(${iv.tx}px, ${iv.ty}px) scale(${iv.scale})`;
      img.style.cursor = iv.scale > 1 ? (iv.drag ? 'grabbing' : 'grab') : 'zoom-in';
      if (zoomLbl) zoomLbl.textContent = Math.round(iv.scale * 100) + '%';
    };

    // Keep the (zoomed) image overlapping the stage so it can't be panned out of view.
    const clampPan = () => {
      const sr = stage.getBoundingClientRect();
      const maxX = Math.max(0, (img.offsetWidth * iv.scale - sr.width) / 2);
      const maxY = Math.max(0, (img.offsetHeight * iv.scale - sr.height) / 2);
      iv.tx = Math.max(-maxX, Math.min(maxX, iv.tx));
      iv.ty = Math.max(-maxY, Math.min(maxY, iv.ty));
    };

    // Zoom toward a screen point (cursor), keeping that point stationary.
    const zoomAt = (px, py, factor) => {
      const s0 = iv.scale, s1 = Math.max(1, Math.min(8, s0 * factor));
      if (s1 === s0) return;
      const sr = stage.getBoundingClientRect();
      const cx = sr.left + img.offsetLeft + img.offsetWidth / 2;   // untransformed center
      const cy = sr.top + img.offsetTop + img.offsetHeight / 2;
      iv.tx += (s0 - s1) / s0 * (px - cx - iv.tx);
      iv.ty += (s0 - s1) / s0 * (py - cy - iv.ty);
      iv.scale = s1;
      if (s1 === 1) { iv.tx = 0; iv.ty = 0; }
      clampPan(); apply();
    };

    const select = (i) => {
      iv.idx = (i + images.length) % images.length;
      const im = images[iv.idx];
      img.src = im.src;
      iv.scale = 1; iv.tx = 0; iv.ty = 0;
      box.querySelectorAll('.ocr-iv-thumb').forEach((t, k) => t.classList.toggle('active', k === iv.idx));
      if (countLbl) countLbl.textContent = images.length > 1 ? `${iv.idx + 1} / ${images.length}` : '';
      if (capLbl) capLbl.textContent = im.label || `${im.kind || 'image'}${im.page ? (' · p' + im.page) : ''}`;
      apply();
    };

    stage.addEventListener('wheel', (e) => {
      e.preventDefault();
      zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.15 : 1 / 1.15);
    }, { passive: false });

    img.addEventListener('pointerdown', (e) => {
      iv.moved = false;
      if (iv.scale <= 1) return;
      iv.drag = { x: e.clientX, y: e.clientY, tx: iv.tx, ty: iv.ty };
      try { img.setPointerCapture(e.pointerId); } catch (_) {}
      apply();
    });
    img.addEventListener('pointermove', (e) => {
      if (!iv.drag) return;
      iv.moved = true;
      iv.tx = iv.drag.tx + (e.clientX - iv.drag.x);
      iv.ty = iv.drag.ty + (e.clientY - iv.drag.y);
      clampPan(); apply();
    });
    const endDrag = (e) => {
      if (!iv.drag) return;
      iv.drag = null;
      try { img.releasePointerCapture(e.pointerId); } catch (_) {}
      apply();
    };
    img.addEventListener('pointerup', endDrag);
    img.addEventListener('pointercancel', endDrag);

    // Click toggles between fit and 2.2× at the click point (suppressed after a pan).
    img.addEventListener('click', (e) => {
      if (iv.moved) { iv.moved = false; return; }
      if (iv.scale > 1) { iv.scale = 1; iv.tx = 0; iv.ty = 0; apply(); }
      else zoomAt(e.clientX, e.clientY, 2.2);
    });

    box.querySelectorAll('.ocr-iv-btn').forEach(b => b.addEventListener('click', () => {
      const sr = stage.getBoundingClientRect();
      const cx = sr.left + sr.width / 2, cy = sr.top + sr.height / 2;
      if (b.dataset.iv === 'in') zoomAt(cx, cy, 1.3);
      else if (b.dataset.iv === 'out') zoomAt(cx, cy, 1 / 1.3);
      else { iv.scale = 1; iv.tx = 0; iv.ty = 0; apply(); }
    }));

    box.querySelectorAll('.ocr-iv-thumb').forEach(t =>
      t.addEventListener('click', () => select(parseInt(t.dataset.idx, 10))));

    stage.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight') { select(iv.idx + 1); e.preventDefault(); }
      else if (e.key === 'ArrowLeft') { select(iv.idx - 1); e.preventDefault(); }
    });

    select(0);
  },

  // Aggregate the structured JSON across all OCR'd pages for the JSON download.
  _buildJsonExport() {
    const cacheKey = this.ocrEngine + '_' + this.ocrAi;
    const out = [];
    Object.keys(this.pages).map(Number).sort((a, b) => a - b).forEach(pn => {
      const p = this.pages[pn]?.[cacheKey];
      if (!p) return;
      if (Array.isArray(p.raw_json)) out.push(...p.raw_json);
      else if (p.raw_json != null) out.push(p.raw_json);
      else out.push({ page: pn, results: p.results || [], layout_blocks: p.layout_blocks || [] });
    });
    return JSON.stringify(out.length ? out : (this._jsonText ? JSON.parse(this._jsonText) : []), null, 2);
  },

  async _loadImagesForDoc(docId) {
    try {
      const r = await API.getOcrImages(docId);
      if (r && r.success && r.images && r.images.length) {
        this._images = r.images;
        this._renderImages(r.images);
        if (this.ocrView === 'images') this._setOcrView('images');
      }
    } catch (_) { /* leave tab disabled */ }
  },

  _updateStats(data) {
    let all=[]; let ms=0; let pg=Object.keys(this.pages).length;
    const cacheKey = this.ocrEngine + '_' + this.ocrAi;
    Object.values(this.pages).forEach(pageModes=>{
      const p = pageModes?.[cacheKey];
      if (p) { all=[...all,...(p.results||[])]; ms+=p.elapsed_ms||0; }
    });
    if(data){all=data.results;ms=data.elapsed_ms;}
    const avg = all.length ? all.reduce((s,r)=>s+(r.confidence||0),0)/all.length : 0;
    document.getElementById('stat-regions').textContent = all.length;
    document.getElementById('stat-conf').textContent = avg?(avg*100).toFixed(1)+'%':'—';
    document.getElementById('stat-time').textContent = ms?ms+'ms':'—';
    document.getElementById('stat-pages').textContent = `${pg}/${this.pageCount}`;
  },

  _hover(i, e) {
    document.querySelectorAll('.det-item').forEach(d=>d.classList.remove('highlighted'));
    const tt = document.getElementById('box-tooltip');
    if (i===-1) { tt.classList.remove('show'); return; }
    const pageData = this.pages[this.currentPage]?.[cacheKey];
    const results = this.ocrLayout === 'original' ? (pageData?.raw_results || pageData?.results) : pageData?.results;
    const item = results?.[i];
    if (!item) return;
    document.getElementById(`det-${i}`)?.classList.add('highlighted');
    tt.innerHTML = `<strong>${esc(item.text)}</strong><br>Conf: ${item.confidence!=null?(item.confidence*100).toFixed(1)+'%':'n/a'}`;
    if (e) { tt.style.left=(e.clientX+14)+'px'; tt.style.top=(e.clientY-10)+'px'; }
    tt.classList.add('show');
  },
  _select(i) {
    document.querySelectorAll('.det-item').forEach(d=>d.classList.remove('selected'));
    const el = document.getElementById(`det-${i}`);
    if (el) { el.classList.add('selected'); el.scrollIntoView({behavior:'smooth',block:'nearest'}); }
  },

  _setZoom(z) {
    this.zoom = Math.max(.3, Math.min(4, z));
    document.getElementById('zoom-lbl').textContent = Math.round(this.zoom*100)+'%';
    this._applyTransform();
  },
  _applyTransform() {
    document.getElementById('preview-img').style.transform = `scale(${this.zoom}) rotate(${this.rotate}deg)`;
    setTimeout(()=>{this.canvas.resize();this.canvas.draw();},50);
  },
  _setLoading(on, all=false) {
    const btnRun  = document.getElementById('btn-ocr-run');
    const btnAll  = document.getElementById('btn-ocr-all');
    const btnStop = document.getElementById('btn-ocr-stop');
    btnRun.disabled = on;
    btnAll.disabled = on;
    btnRun.innerHTML = on && !all ? `<span class="spin"></span> ${t('run_ocr_running')}` : t('run_ocr');
    btnAll.innerHTML = on && all  ? `<span class="spin"></span> ${t('ocr_all_running')}` : t('ocr_all');
    // Show/hide stop button
    if (btnStop) btnStop.style.display = on ? 'inline-flex' : 'none';
    const pb = document.getElementById('progress-bar-wrap');
    pb.classList.toggle('show', on);
    document.getElementById('progress-bar').style.width = on ? '60%' : '100%';
    if (!on) setTimeout(() => pb.classList.remove('show'), 500);
  },
  _reset() {
    this._resetMode();
    this.fileId=null;this.pages={};this.zoom=1;this.rotate=0;
    document.getElementById('ocr-upload-zone').style.display = 'flex';
    document.getElementById('ocr-workspace').style.display='none';
    document.getElementById('overlay-canvas').classList.remove('interactive');
    document.getElementById('preview-img').src='';
    this._resetViewerState();
    document.getElementById('det-list').querySelectorAll('.det-item').forEach(el => el.remove());
    const empty = document.getElementById('ocr-empty-results');
    if (empty) empty.style.display='flex';
  },

  async _onRegionSelect(rect) {
    const cacheKey = this.ocrEngine + '_' + this.ocrAi;
    const pageData = this.pages[this.currentPage]?.[cacheKey];
    if (!pageData || !pageData.results) return;

    // Filter boxes whose bounding rectangle intersects the drawn selection
    const subset = pageData.results.filter(item => {
      const box = item.box;
      const xmin = Math.min(...box.map(pt => pt[0]));
      const ymin = Math.min(...box.map(pt => pt[1]));
      const xmax = Math.max(...box.map(pt => pt[0]));
      const ymax = Math.max(...box.map(pt => pt[1]));
      return !(xmax < rect.x1 || xmin > rect.x2 || ymax < rect.y1 || ymin > rect.y2);
    });

    if (subset.length === 0) {
      Toast.show('No text found in selected region.', 'info');
      return;
    }

    // Sort spatially: top-to-bottom, then left-to-right within the same row
    // Group into rows whose Y-centres are within ~20px of each other
    const ROW_GAP = 20;
    const withCentre = subset.map(item => {
      const box = item.box;
      const cx = (Math.min(...box.map(p => p[0])) + Math.max(...box.map(p => p[0]))) / 2;
      const cy = (Math.min(...box.map(p => p[1])) + Math.max(...box.map(p => p[1]))) / 2;
      return { ...item, cx, cy };
    }).sort((a, b) => a.cy - b.cy);

    const rows = [];
    for (const item of withCentre) {
      const lastRow = rows[rows.length - 1];
      if (lastRow && Math.abs(item.cy - lastRow[0].cy) <= ROW_GAP) {
        lastRow.push(item);
      } else {
        rows.push([item]);
      }
    }
    // Within each row sort left-to-right
    rows.forEach(row => row.sort((a, b) => a.cx - b.cx));

    const text = rows.map(row => row.map(r => r.text).join(' ')).join('\n');

    // Copy via the shared helper (secure-context Clipboard API + execCommand fallback,
    // with success/error feedback).
    await copyWithToast(text, `${subset.length} region(s) copied to clipboard`);
  },

  // Resolve a document by file_id and load it (deep-link loader; no navigation).
  async _openFromFileId(fileId) {
    if (!fileId) return;
    const find = () => (DocumentsView.docs || []).find(d => d.file_id === fileId);
    let doc = find();
    if (!doc) { try { await DocumentsView.load(); } catch (_) {} doc = find(); }
    if (!doc) { Toast.show(t('doc_not_found') || 'Document not found', 'error'); return; }
    this.loadByFileId(doc);
  },

  // Load a pre-existing file from the Documents library (skip upload). This is a
  // LOADER only — the view switch is owned by the hash router (Router._render).
  loadByFileId(doc) {
    this.fileId = doc.file_id; this.isPdf = doc.file_type === '.pdf';
    this.pageCount = doc.page_count || 1; this.currentPage = 1; this.pages = {};
    document.getElementById('ocr-upload-zone').style.display = 'none';
    document.getElementById('ocr-workspace').style.display = 'grid';
    document.getElementById('ocr-file-name').textContent = doc.filename;
    // Blank the viewer for THIS file before preview/restore, so a file with no
    // persisted OCR never shows the previously opened file's result. Also reset
    // the engine selector to default; _restoreStoredArtifact overrides it from
    // the file's own artifact when one exists.
    this._resetViewerState();
    this.ocrEngine = this._sessionEngine || 'glmocr';
    const _eng = document.getElementById('ocr-engine-select');
    if (_eng) _eng.value = this.ocrEngine;
    this._buildTabs(); this._updateNav();
    Toast.show(`${t('loaded_from_lib')} "${doc.filename}"`, 'info');
    // Preview is non-destructive (no re-OCR). After it renders, restore the
    // persisted OCR result + the engine that produced it, so the viewer shows the
    // real latest result (e.g. VietOCR) instead of a blank/re-run page.
    this._ocrPage(1, true).then(() => this._restoreStoredArtifact(doc));
  },

  // Restore persisted OCR state for a library document. Prefers the structured
  // 'ocr_layout' snapshot (overlay boxes + stats + status, no re-run); falls back
  // to text + engine only for older documents that predate the snapshot.
  async _restoreStoredArtifact(doc) {
    if (!doc || doc.id == null) return;
    const applyEngine = (eng) => {
      // Restore the engine a saved doc was processed with. paddleocr_modern is now
      // hidden from the selector but still valid internally — keep it as the active
      // engine, but only reflect it in the dropdown when a matching option exists
      // (so a restored Modern doc doesn't blank out the 3-option selector).
      if (['paddleocr', 'vietocr', 'paddleocr_modern', 'glmocr'].includes(eng)) {
        this.ocrEngine = eng;
        const sel = document.getElementById('ocr-engine-select');
        if (sel && [...sel.options].some(o => o.value === eng)) sel.value = eng;
      }
    };
    try {
      const a = await API.getDocText(doc.id);
      if (!a || !a.success || !a.artifacts) return;
      const arts = a.artifacts;

      // ── Full structured restore ─────────────────────────────────────────
      if (arts.ocr_layout && arts.ocr_layout.content) {
        let layout = null;
        try { layout = JSON.parse(arts.ocr_layout.content); } catch (_) {}
        if (layout && Array.isArray(layout.pages) && layout.pages.length) {
          this.ocrAi = false;
          if (layout.engine) applyEngine(String(layout.engine).toLowerCase());
          const cacheKey = this.ocrEngine + '_' + this.ocrAi;
          layout.pages.forEach(pg => {
            const data = {
              results:          pg.results || [],
              raw_results:      pg.results || [],   // keep Original/Enhanced toggle working
              img_width:        pg.img_width,
              img_height:       pg.img_height,
              elapsed_ms:       pg.elapsed_ms,
              inference_status: pg.inference_status,
              page_num:         pg.page_num,
            };
            this.pages[pg.page_num] ||= {};
            this.pages[pg.page_num][cacheKey] = data;
          });
          // Draw the current page's overlay onto the already-loaded preview image.
          const cur = this.pages[this.currentPage] && this.pages[this.currentPage][cacheKey];
          if (cur) {
            const results = this.ocrLayout === 'original' ? (cur.raw_results || cur.results) : cur.results;
            if (cur.img_width && cur.img_height) this.canvas.load(results, cur.img_width, cur.img_height);
            this._applyTransform();
            this._renderResults(cur);
            this._updateStats(cur);
            // Rehydrate the result tabs (markdown/json/images) from persisted artifacts.
            if (arts.ocr_markdown && arts.ocr_markdown.content) cur.markdown = arts.ocr_markdown.content;
            if (arts.ocr_json && arts.ocr_json.content) {
              try { cur.raw_json = JSON.parse(arts.ocr_json.content); } catch (_) {}
            }
            this._curDocId = doc.id;
            this._renderStructured(cur);
            this._loadImagesForDoc(doc.id);   // enable Images tab if artifacts exist
          }
          this._renderTextAll();
          this._setOcrStatusBadge(doc, layout);
          // Reflect the actual restored artifact (sum of regions across pages).
          const regions = layout.pages.reduce((n, pg) => n + ((pg.results || []).length), 0);
          Toast.show(`${t('nav_ocr')}: ${regions} ${t('regions_found')}`, 'success');
          return;
        }
      }

      // ── Fallback: text (+ optional markdown) only ───────────────────────
      const art = arts.ocr || arts.text;
      if (!art || !art.content) return;
      this._curDocId = doc.id;
      const data = { results: String(art.content).split('\n').map(text => ({ text })) };
      if (arts.ocr_markdown && arts.ocr_markdown.content) data.markdown = arts.ocr_markdown.content;
      if (arts.ocr_json && arts.ocr_json.content) {
        try { data.raw_json = JSON.parse(arts.ocr_json.content); } catch (_) {}
      }
      this._renderStructured(data);
      this._loadImagesForDoc(doc.id);   // enable Images tab if artifacts exist
      State.setOcrText(art.content);
      const m = /engine=([a-z0-9_]+)/i.exec(art.meta || '');
      if (m) applyEngine(m[1].toLowerCase());
      this._setOcrStatusBadge(doc, null);
    } catch (e) { /* leave preview as-is */ }
  },

  // Show an OCR-status badge next to the filename from Document.status / layout.
  _setOcrStatusBadge(doc, layout) {
    const el = document.getElementById('ocr-status-badge');
    if (!el) return;
    const status = (doc && doc.status) || '';
    let txt = '';
    if (status === 'ocr_done' || (layout && layout.pages)) {
      const eng = (layout && layout.engine) || this.ocrEngine || '';
      txt = '✓ OCR' + (eng ? ' · ' + eng : '');
      const inf = layout && layout.pages && layout.pages[0] && layout.pages[0].inference_status;
      if (inf && inf !== 'ok') txt += ' · ' + inf;
    }
    el.textContent = txt;
    el.style.display = txt ? '' : 'none';
  }
};

// ══════════════════════════════════════════════════════
// Tool View Factory (Correct / Translate / Summarize share pattern)
// ══════════════════════════════════════════════════════
function makeToolView(cfg) {
  return {
    importText(text) { State.activeDocFileId = null; const el=document.getElementById(cfg.inputId); if(el) el.value=text; },

    // G1: display a previously-saved result (translation/summary) without re-running.
    presetResult(text) {
      if (text == null) return;
      const empty   = document.getElementById(cfg.outputEmptyId);   if (empty)   empty.style.display='none';
      const loading = document.getElementById(cfg.outputLoadingId); if (loading) loading.style.display='none';
      const area    = document.getElementById(cfg.outputAreaId);    if (area)    area.style.display='flex';
      const out     = document.getElementById(cfg.outputId);        if (out)     out.value = text;
    },

    init() {
      // Editing the input by hand detaches it from any source document (G1).
      document.getElementById(cfg.inputId)?.addEventListener('input', () => { State.activeDocFileId = null; });
      // Tab switching
      document.querySelectorAll(`#${cfg.viewId} .tab-btn`).forEach(btn => {
        btn.addEventListener('click', () => {
          document.querySelectorAll(`#${cfg.viewId} .tab-btn`).forEach(b=>b.classList.remove('active'));
          document.querySelectorAll(`#${cfg.viewId} .tab-pane`).forEach(p=>p.classList.remove('active'));
          btn.classList.add('active');
          document.getElementById(btn.dataset.tab)?.classList.add('active');
        });
      });

      // File upload
      const fi = document.getElementById(cfg.fileInputId);
      if (fi) fi.addEventListener('change', async e => {
        const f = e.target.files[0]; if (!f) return;
        e.target.value = ''; // reset so same file can be re-selected next time
        const d = await API.upload(f);
        if (!d.success) { Toast.show(d.error,'error'); return; }
        const t = await API.readText(d.file_id);
        if (!t.success) { Toast.show(t.error,'error'); return; }
        this.importText(t.text);
        Toast.show(`${t('toast_file_loaded')} "${f.name}"`, 'success');
        const pasteTab = document.querySelector(`#${cfg.viewId} [data-tab="${cfg.pasteTabId}"]`);
        if (pasteTab) pasteTab.click();
      });

      // Import OCR button
      const importBtn = document.getElementById(cfg.importBtnId);
      if (importBtn) importBtn.addEventListener('click', () => {
        if (!State.ocrText) { Toast.show(t('toast_no_ocr'),'info'); return; }
        this.importText(State.ocrText);
        Toast.show(t('toast_ocr_imported'),'success');
        const pasteTab = document.querySelector(`#${cfg.viewId} [data-tab="${cfg.pasteTabId}"]`);
        if (pasteTab) pasteTab.click();
      });

      // Run button
      document.getElementById(cfg.runBtnId)?.addEventListener('click', () => this.run());

      // Ask Agent (Phase 14) — launch the agent scoped to the active document when
      // one is attached (State.activeDocFileId), else open the agent unscoped.
      if (cfg.askAgentBtnId) document.getElementById(cfg.askAgentBtnId)?.addEventListener('click', () => {
        const fid = State.activeDocFileId;
        window.location.href = '/agent' + (fid ? '?file_id=' + encodeURIComponent(fid) : '');
      });

      // Copy / Download
      document.getElementById(cfg.copyBtnId)?.addEventListener('click', () => {
        copyWithToast(document.getElementById(cfg.outputId)?.value || '', t('toast_text_copied'));
      });
      document.getElementById(cfg.dlBtnId)?.addEventListener('click', () => {
        dlTxt(document.getElementById(cfg.outputId)?.value||'', cfg.dlName);
      });

      // Chain buttons
      if (cfg.chainCfg) cfg.chainCfg.forEach(c => {
        document.getElementById(c.btnId)?.addEventListener('click', () => {
          const t=document.getElementById(cfg.outputId)?.value||'';
          if(!t){Toast.show(t('toast_no_output'),'info');return;}
          c.view.importText(t); Router.goto(c.viewName);
        });
      });
    },

    async run() {
      const text = (document.getElementById(cfg.inputId)?.value||'').trim();
      if (!text) { Toast.show(t('toast_no_text'),'info'); return; }
      const btn = document.getElementById(cfg.runBtnId);
      btn.disabled=true; btn.innerHTML=`<span class="spin"></span> ${cfg.runningText}`;
      this._showLoading();
      try {
        const result = await cfg.apiFn(text, this);

        // Handle AI model warming up — auto-retry with countdown
        if (result.warming_up) {
          const retryAfter = (result.retry_after || 15) * 1000;
          const meta = document.getElementById('summarize-meta');
          if (meta) {
            let countdown = Math.round(retryAfter / 1000);
            meta.textContent = `⏳ AI model loading… retrying in ${countdown}s`;
            const tick = setInterval(() => {
              countdown--;
              if (meta) meta.textContent = `⏳ AI model loading… retrying in ${countdown}s`;
            }, 1000);
            await new Promise(r => setTimeout(r, retryAfter));
            clearInterval(tick);
          } else {
            await new Promise(r => setTimeout(r, retryAfter));
          }
          // Retry once after waiting
          const retry = await cfg.apiFn(text, this);
          if (!retry.success) { Toast.show(retry.error || 'AI model still loading, please try again.', 'info'); }
          else { this._showResult(retry); Toast.show(cfg.successMsg, 'success'); }
          return;
        }

        if (!result.success) { Toast.show(result.error,'error'); }
        else { this._showResult(result); Toast.show(cfg.successMsg,'success'); }
      } catch(e) { Toast.show('Error: '+e.message,'error'); }
      finally { btn.disabled=false; btn.innerHTML=cfg.runBtnLabel; this._hideLoading(); }
    },

    _showLoading() {
      document.getElementById(cfg.outputEmptyId).style.display='none';
      document.getElementById(cfg.outputAreaId).style.display='none';
      document.getElementById(cfg.outputLoadingId).style.display='flex';
    },
    _hideLoading() { document.getElementById(cfg.outputLoadingId).style.display='none'; },
    _showResult(result) {
      document.getElementById(cfg.outputAreaId).style.display='flex';
      document.getElementById(cfg.outputId).value = cfg.resultExtract(result);
      cfg.metaUpdate?.(result);
    }
  };
}

// ── Correct ────────────────────────────────────────────
const CorrectView = makeToolView({
  viewId:'view-correct', inputId:'correct-input', fileInputId:'correct-file-input',
  pasteTabId:'correct-paste-tab', importBtnId:'correct-import-btn',
  runBtnId:'correct-run-btn', runBtnLabel:'✨ Correct Text', runningText:'Correcting…',
  copyBtnId:'correct-copy-btn', dlBtnId:'correct-dl-btn', dlName:'corrected.txt',
  outputId:'correct-output', outputEmptyId:'correct-out-empty',
  outputAreaId:'correct-out-area', outputLoadingId:'correct-out-loading',
  successMsg: t('toast_correct_done'),
  apiFn: (text) => API.correct(text),
  resultExtract: r => r.corrected,
  metaUpdate: r => {
    const el = document.getElementById('correct-changes');
    if (el) el.textContent = `${r.changes} changes · ${r.elapsed_ms}ms`;
  },
  chainCfg:[
    {btnId:'correct-send-translate', viewName:'translate', view: {importText(t){TranslateView.importText(t)}}},
    {btnId:'correct-send-summarize', viewName:'summarize', view: {importText(t){SummarizeView.importText(t)}}},
  ]
});

// ── Translate ──────────────────────────────────────────
const TranslateView = makeToolView({
  viewId:'view-translate', inputId:'translate-input', fileInputId:'translate-file-input',
  pasteTabId:'translate-paste-tab', importBtnId:'translate-import-btn',
  runBtnId:'translate-run-btn',
  get runBtnLabel()  { return t('translate_run')  || '🌐 Dịch'; },
  get runningText()  { return t('translate_running') || 'Đang dịch…'; },
  copyBtnId:'translate-copy-btn', dlBtnId:'translate-dl-btn', dlName:'translated.txt',
  askAgentBtnId:'translate-ask-agent',
  outputId:'translate-output', outputEmptyId:'translate-out-empty',
    outputAreaId:'translate-out-area', outputLoadingId:'translate-out-loading',
  get successMsg() { return t('toast_translate_done'); },

  apiFn: async (text) => {
    const engine = document.querySelector('.engine-pill.active')?.dataset.engine || 'auto';
    // Client-side guard: Online mode needs internet
    if (engine === 'online' && !navigator.onLine) {
      throw new Error(t('engine_warn_online_no_net') ||
        'Chế độ Trực tuyến yêu cầu kết nối Internet.');
    }
    return API.translate(
      text,
      document.getElementById('from-lang')?.value || 'auto',
      document.getElementById('to-lang')?.value  || 'vi',
      engine,
      State.activeDocFileId          // G1: persist translation back to the source document
    );
  },
  resultExtract: r => r.translated,
  metaUpdate: r => {
    const badge = document.getElementById('translate-engine-used-badge');
    if (!badge) return;
    const icons = { online: '🌐', offline: '📴', auto: '⚡' };
    const labels = { online: 'Google Translate', offline: 'Offline Translation', auto: 'Auto' };
    const engine = r.engine_used || 'auto';
    badge.textContent = `${icons[engine] || '⚡'} ${labels[engine] || engine}`;
    badge.style.display = '';
  },
  chainCfg:[
    {btnId:'translate-send-correct', viewName:'correct', view:{importText(t){CorrectView.importText(t)}}},
    {btnId:'translate-send-summarize', viewName:'summarize', view:{importText(t){SummarizeView.importText(t)}}},
  ]
});

// -- Engine selector + status probe ---------------------
const EngineSelector = {
  active: 'auto',
  _lastStatus: null,
  _probing: false,

  init() {
    document.querySelectorAll('.engine-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        if (pill.disabled) {
          // Disabled pill clicked — trigger fresh re-check and inform user
          Toast.show(t('engine_rechecking') || 'Đang kiểm tra lại kết nối…', 'info');
          this.probe(true);
          return;
        }
        document.querySelectorAll('.engine-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        this.active = pill.dataset.engine;
      });
    });

    // Instant badge update when browser goes offline/online
    window.addEventListener('online',  () => {
      Toast.show(t('engine_internet_restored') || 'Đã phát hiện kết nối mạng. Đang kiểm tra…', 'success');
      this.probe(true);
    });
    window.addEventListener('offline', () => this._handleBrowserOffline());

    // Re-probe when user returns to this tab
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) this.probe(true);
    });

    this.probe();
    // Periodic re-probe every 15s — always force so backend cache is bypassed
    setInterval(() => this.probe(true), 15_000);
  },

  _handleBrowserOffline() {
    const badge = document.getElementById('engine-status-badge');
    const txt   = document.getElementById('engine-status-text');
    const onlinePill = document.getElementById('engine-pill-online');
    if (!badge) return;
    if (this._lastStatus) this._lastStatus.online = false;
    badge.className = 'engine-status-badge engine-status-none';
    txt.textContent = t('engine_no_internet') || 'Không có kết nối Internet';
    if (onlinePill) { onlinePill.disabled = true; onlinePill.title = t('engine_disabled_click') || 'Nhấp để kiểm tra lại'; }
  },

  async probe(force = false) {
    // Prevent concurrent probes
    if (this._probing) return;
    this._probing = true;

    const badge       = document.getElementById('engine-status-badge');
    const txt         = document.getElementById('engine-status-text');
    const onlinePill  = document.getElementById('engine-pill-online');
    const offlinePill = document.getElementById('engine-pill-offline');
    if (!badge) { this._probing = false; return; }

    badge.className = 'engine-status-badge engine-status-checking';
    txt.textContent = t('engine_checking');

    // Always reset disabled states before re-applying fresh results
    [onlinePill, offlinePill].forEach(p => { if (p) { p.disabled = false; p.title = ''; } });

    try {
      const s = await API.translateStatus(force);
      const wasOnline = this._lastStatus?.online ?? null;
      this._lastStatus = s;

      if (s.online && s.offline) {
        badge.className = 'engine-status-badge engine-status-all';
        txt.textContent = t('engine_status_all');
        // Notify if internet was restored
        if (wasOnline === false) {
          Toast.show(t('engine_internet_back') || 'Kết nối Internet đã khôi phục. Chế độ Trực tuyến sẵn sàng!', 'success');
        }
      } else if (s.online) {
        badge.className = 'engine-status-badge engine-status-online';
        txt.textContent = t('engine_status_online');
        if (offlinePill) { offlinePill.disabled = true; offlinePill.title = t('engine_offline_tip'); }
        if (wasOnline === false) {
          Toast.show(t('engine_internet_back') || 'Kết nối Internet đã khôi phục!', 'success');
        }
        // Auto-switch away from offline if currently selected
        if (this.active === 'offline') onlinePill?.click();
      } else if (s.offline) {
        badge.className = 'engine-status-badge engine-status-offline';
        txt.textContent = t('engine_status_offline');
        if (onlinePill) {
          onlinePill.disabled = true;
          onlinePill.title = t('engine_disabled_click') || 'Nhấp để kiểm tra lại kết nối';
        }
        // Auto-switch away from online mode
        if (this.active === 'online') {
          document.querySelector('.engine-pill[data-engine="auto"]')?.click();
        }
      } else {
        badge.className = 'engine-status-badge engine-status-none';
        txt.textContent = t('engine_status_none');
        if (onlinePill)  { onlinePill.disabled  = true; }
        if (offlinePill) { offlinePill.disabled = true; }
      }
      // Privacy (Local only): online is off BY POLICY — say why, not "no internet",
      // and point at the Settings screen where the mode can be changed.
      if (s.local_only) {
        badge.className = 'engine-status-badge engine-status-offline';
        txt.textContent = t('engine_local_only') || '🔒 Local only — offline translation (see Settings)';
        if (onlinePill) {
          onlinePill.disabled = true;
          onlinePill.title = t('settings_local_only_keys') || 'Local only mode — change in Settings';
        }
      }
    } catch(e) {
      badge.className = 'engine-status-badge engine-status-none';
      txt.textContent = t('engine_status_error');
    }
    this._probing = false;
  }
};

// ── Settings view (cloud API keys + privacy) ───────────────────────────────
// Keys are handled write-only: typed into a password field, sent once to the
// backend (OS credential store), input cleared. Only masked hints ("••••abcd")
// ever come back. Nothing here touches localStorage or State.
const SettingsView = {
  _data: null,
  _names: { groq: 'Groq', gemini: 'Google Gemini' },

  init() { this._inited = true; },

  async show() {
    try {
      this._data = await API.settingsGet();
    } catch (e) {
      Toast.show(t('settings_load_failed') || 'Could not load settings.', 'error');
      return;
    }
    if (!this._data || !this._data.success) {
      Toast.show(t('settings_load_failed') || 'Could not load settings.', 'error');
      return;
    }
    this._renderPrivacy();
    this._renderProviders();
  },

  _renderPrivacy() {
    const p = this._data.privacy || {};
    const badge = document.getElementById('settings-privacy-badge');
    const txt = document.getElementById('settings-privacy-text');
    const btn = document.getElementById('settings-privacy-toggle');
    const note = document.getElementById('settings-privacy-note');
    const local = p.processing_mode === 'local_only';
    badge.className = 'engine-status-badge ' +
      (local ? 'engine-status-offline' : 'engine-status-online');
    txt.textContent = local
      ? (t('settings_mode_local') || '🔒 Local only — nothing is sent to the cloud')
      : (t('settings_mode_cloud') || '☁ Cloud processing allowed');
    btn.disabled = !!p.env_locked;
    btn.textContent = local
      ? (t('settings_enable_cloud') || 'Allow cloud processing…')
      : (t('settings_disable_cloud') || 'Switch to Local only');
    note.textContent = p.env_locked
      ? (t('settings_env_locked') || 'Set by ALLOW_CLOUD in .env — remove it there to control this here.')
      : '';
    btn.onclick = () => this._togglePrivacy(!local);
  },

  async _togglePrivacy(enableCloud) {
    const p = (this._data && this._data.privacy) || {};
    if (enableCloud && !p.cloud_ack) {
      // First-time confirmation (UI item 2): explain what leaves the machine.
      const msg = p.ack_message || 'Document text and prompts may be sent to the configured cloud provider. Continue?';
      if (!window.confirm(msg)) return;
    }
    const res = await API.settingsPrivacy(enableCloud, enableCloud);
    if (res && res.success) {
      this._data = res;
      this._renderPrivacy();
      this._renderProviders();
      Toast.show(enableCloud
        ? (t('settings_cloud_on') || 'Cloud processing allowed.')
        : (t('settings_cloud_off') || 'Local only enabled — nothing leaves this machine.'),
        'success');
    } else {
      Toast.show((res && (res.error || res.message)) ||
        t('settings_save_failed') || 'Could not save the setting.', 'error');
    }
  },

  _stateBadge(state, detail) {
    const map = {
      not_configured: ['engine-status-none', t('settings_state_none') || 'Not configured'],
      configured: ['engine-status-all', t('settings_state_configured') || 'Configured'],
      testing: ['engine-status-checking', t('settings_state_testing') || 'Testing…'],
      connected: ['engine-status-online', t('settings_state_connected') || 'Connected'],
      invalid: ['engine-status-none', t('settings_state_invalid') || 'Invalid key'],
      error: ['engine-status-none', t('settings_state_error') || 'Unreachable'],
      unavailable: ['engine-status-none', t('settings_state_unavailable') || 'Credential store unavailable'],
      blocked: ['engine-status-offline', t('settings_state_blocked') || 'Local only'],
    };
    const [cls, label] = map[state] || map.not_configured;
    const span = document.createElement('span');
    span.className = 'engine-status-badge ' + cls;
    span.setAttribute('role', 'status');
    const dot = document.createElement('span'); dot.className = 'status-dot';
    span.appendChild(dot);
    span.appendChild(document.createTextNode(' ' + label + (detail ? ' — ' + detail : '')));
    return span;
  },

  _renderProviders() {
    const wrap = document.getElementById('settings-providers');
    const kr = this._data.keyring || {};
    const localOnly = (this._data.privacy || {}).processing_mode === 'local_only';
    const warn = document.getElementById('settings-keyring-warn');
    if (!kr.available) {
      warn.style.display = '';
      warn.textContent = (t('settings_keyring_unavailable') ||
        'The OS credential store is unavailable — keys cannot be saved here. ') +
        '(' + (kr.backend || '') + ')';
    } else {
      warn.style.display = 'none';
    }
    wrap.innerHTML = '';
    (this._data.providers || []).forEach((prov) => {
      wrap.appendChild(this._providerRow(prov, kr.available, localOnly));
    });
  },

  _providerRow(prov, keyringOk, localOnly) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;align-items:center;' +
      'padding:10px 0;border-top:1px solid var(--border)';
    const name = document.createElement('b');
    name.style.cssText = 'flex:0 0 130px';
    name.textContent = this._names[prov.provider] || prov.provider;
    row.appendChild(name);

    const state = document.createElement('span');
    state.id = 'settings-state-' + prov.provider;
    state.appendChild(this._stateBadge(
      localOnly ? 'blocked' : (prov.configured ? 'configured' : 'not_configured'),
      prov.configured ? (prov.masked +
        (prov.source === 'env' ? ' · ' + (t('settings_from_env') || 'from .env') : '')) : ''));
    row.appendChild(state);

    const input = document.createElement('input');
    input.type = 'password';                       // masked; never a text field
    input.autocomplete = 'off';
    input.id = 'settings-key-' + prov.provider;
    input.placeholder = prov.configured
      ? (t('settings_key_replace') || 'Enter a new key to replace…')
      : (t('settings_key_enter') || 'Paste API key…');
    input.setAttribute('aria-label', (this._names[prov.provider] || prov.provider) + ' API key');
    input.style.cssText = 'flex:1;min-width:200px;background:var(--card2);' +
      'border:1px solid var(--border);border-radius:8px;padding:8px 10px;color:inherit';
    row.appendChild(input);

    const mkBtn = (label, cls, onclick, disabled, title) => {
      const b = document.createElement('button');
      b.className = 'btn ' + cls + ' btn-sm';
      b.textContent = label;
      b.disabled = !!disabled;
      if (title) b.title = title;
      b.addEventListener('click', onclick);
      row.appendChild(b);
      return b;
    };
    const localMsg = t('settings_local_only_keys') ||
      'Local only is enabled — cloud keys are not used or validated in this mode.';
    const envLocked = prov.source === 'env';
    const envMsg = t('settings_env_key') ||
      'This key comes from .env and wins over a stored key.';
    mkBtn(t('settings_btn_save') || 'Save', 'btn-primary',
      () => this._saveKey(prov.provider, input),
      localOnly || !keyringOk || envLocked,
      localOnly ? localMsg : (!keyringOk ? (t('settings_state_unavailable') || 'Credential store unavailable')
                              : (envLocked ? envMsg : '')));
    mkBtn(t('settings_btn_test') || 'Test', 'btn-ghost',
      () => this._testKey(prov.provider, input), localOnly,
      localOnly ? localMsg : '');
    mkBtn(t('settings_btn_remove') || 'Remove', 'btn-ghost',
      () => this._removeKey(prov.provider),
      !prov.configured || envLocked, envLocked ? envMsg : '');
    return row;
  },

  _setState(provider, state, detail) {
    const holder = document.getElementById('settings-state-' + provider);
    if (holder) {
      holder.innerHTML = '';
      holder.appendChild(this._stateBadge(state, detail));
    }
  },

  async _saveKey(provider, input) {
    const key = (input.value || '').trim();
    if (!key) { Toast.show(t('settings_key_required') || 'Enter an API key first.', 'error'); return; }
    const res = await API.settingsSaveKey(provider, key);
    input.value = '';                              // never keep the key around
    if (res && res.success) {
      this._setState(provider, 'configured', res.provider && res.provider.masked);
      Toast.show(t('settings_key_saved') || 'Key stored in the OS credential store.', 'success');
      this.show();                                 // refresh masked hints/buttons
    } else {
      this._setState(provider, (res && res.state) || 'error');
      Toast.show((res && res.error) || t('settings_save_failed') || 'Could not save the key.', 'error');
    }
  },

  async _testKey(provider, input) {
    this._setState(provider, 'testing');
    const typed = (input.value || '').trim();
    const res = await API.settingsTestKey(provider, typed || null);
    const state = (res && res.state) || 'error';
    this._setState(provider, state, res && res.detail);
    Toast.show((res && res.detail) || '', state === 'connected' ? 'success' : 'error');
  },

  async _removeKey(provider) {
    if (!window.confirm(t('settings_key_remove_confirm') ||
        'Remove the stored API key for this provider?')) return;
    const res = await API.settingsDeleteKey(provider);
    if (res && res.success) {
      Toast.show(t('settings_key_removed') || 'Key removed.', 'success');
      this.show();
    } else {
      Toast.show((res && res.error) || t('settings_save_failed') || 'Could not remove the key.', 'error');
    }
  },
};

// Swap languages
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('swap-langs')?.addEventListener('click', () => {
    const fEl = document.getElementById('from-lang');
    const tEl = document.getElementById('to-lang');
    [fEl.value, tEl.value] = [tEl.value === 'auto' ? 'en' : tEl.value, fEl.value];
  });
  EngineSelector.init();
});

// ── Summarize ──────────────────────────────────────────
const SummarizeView = makeToolView({
  viewId:'view-summarize', inputId:'summarize-input', fileInputId:'summarize-file-input',
  pasteTabId:'summarize-paste-tab', importBtnId:'summarize-import-btn',
  runBtnId:'summarize-run-btn', runBtnLabel:t('summarize_run')||'📝 Summarize', runningText:t('summarize_running')||'Summarizing…',
  copyBtnId:'summarize-copy-btn', dlBtnId:'summarize-dl-btn', dlName:'summary.txt',
  askAgentBtnId:'summarize-ask-agent',
  outputId:'summarize-output', outputEmptyId:'summarize-out-empty',
  outputAreaId:'summarize-out-area', outputLoadingId:'summarize-out-loading',
  successMsg: t('toast_summarize_done'),
  apiFn: (text) => {
    const style       = document.querySelector('.mode-pill.active')?.dataset.mode || 'short';
    const engine      = document.querySelector('.sum-engine-pill.active')?.dataset.engine || 'auto';
    const summaryMode = document.querySelector('.sum-mode-pill.active')?.dataset.summaryMode || 'fast';
    return API.summarize(text, style, engine, summaryMode, State.activeDocFileId);  // G1: persist back
  },
  resultExtract: r => r.summary,
  metaUpdate: r => {
    const el = document.getElementById('summarize-meta');
    if (!el) return;
    const eu = r.engine_used || 'fast';
    // Capability-focused labels — hide model ids, device, language codes, and timings.
    if (eu.startsWith('ai_local')) {
      el.textContent = '🧠 Local AI · Summary Ready';
    } else if (eu.startsWith('ai_api')) {
      el.textContent = '🌐 Cloud AI · Summary Ready';
    } else {
      const engineIcons  = { smart:'🧠', fast:'🔤', fast_fallback:'🔤', raw_fallback:'⚠️', none:'—' };
      const engineLabels = { smart:'Smart Summary', fast:'Fast Summary', fast_fallback:'Fast Summary', raw_fallback:'Basic Summary', none:'—' };
      el.textContent = `${engineIcons[eu] || '⚡'} ${engineLabels[eu] || 'Summary'} · Ready`;
    }
  },
  chainCfg:[
    {btnId:'summarize-send-translate', viewName:'translate', view:{importText(t){TranslateView.importText(t)}}},
  ]
});

// ── Utilities ──────────────────────────────────────────
function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function fmtSize(b) {
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b/1024).toFixed(1) + ' KB';
  return (b/1048576).toFixed(1) + ' MB';
}
// Server timestamps are UTC (ISO now carries a +00:00/Z marker). Render them in a
// fixed Vietnam timezone so the display is correct regardless of the viewer's machine.
const DISPLAY_TZ = 'Asia/Ho_Chi_Minh';
function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  return new Intl.DateTimeFormat('vi-VN', {
    timeZone: DISPLAY_TZ,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(d);
}

// ══════════════════════════════════════════════════════
// Documents View
// ══════════════════════════════════════════════════════
const DocumentsView = {
  docs: [],
  isAdmin: false,
  filter: 'all',
  page: 1,
  pageSize: 20,
  totalPages: 1,
  totalItems: 0,
  stats: { total:0, images:0, pdfs:0, texts:0 },

  init() {
    document.getElementById('docs-refresh').addEventListener('click', () => { this.page = 1; this.load(); });
    document.querySelectorAll('.filter-pill').forEach(p =>
      p.addEventListener('click', () => {
        document.querySelectorAll('.filter-pill').forEach(x => x.classList.remove('active'));
        p.classList.add('active'); this.filter = p.dataset.filter;
        this.page = 1; this.load();
      }));
    
    let searchTimer;
    document.getElementById('docs-search').addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { this.page = 1; this.load(); }, 300);
    });

    document.getElementById('pagin-prev').addEventListener('click', () => {
      if (this.page > 1) { this.page--; this.load(); }
    });
    document.getElementById('pagin-next').addEventListener('click', () => {
      if (this.page < this.totalPages) { this.page++; this.load(); }
    });
    document.getElementById('pagin-size-select').addEventListener('change', (e) => {
      this.pageSize = parseInt(e.target.value);
      this.page = 1;
      this.load();
    });
  },

  show() { this.load(); },

  async load() {
    const tbl = document.getElementById('docs-table');
    const empty = document.getElementById('docs-empty');
    const loading = document.getElementById('docs-loading');
    const pagin = document.getElementById('docs-pagination');
    const q = (document.getElementById('docs-search')?.value||'').toLowerCase();
    
    loading.style.display='flex'; tbl.style.display='none'; empty.style.display='none'; pagin.style.display='none';
    
    try {
      const url = `/api/documents?page=${this.page}&page_size=${this.pageSize}&filter=${this.filter}&search=${encodeURIComponent(q)}`;
      const r = await fetch(url);
      const data = await r.json();
      if (!data.success) { Toast.show(t('toast_load_fail'), 'error'); return; }
      
      this.docs = data.documents; 
      this.isAdmin = data.is_admin;
      this.stats = data.stats || this.stats;
      
      if (data.pagination) {
          this.totalItems = data.pagination.total_items;
          this.totalPages = data.pagination.total_pages;
          this.page = data.pagination.current_page;
      }

      document.getElementById('docs-owner-col').style.display = this.isAdmin ? '' : 'none';
      this._renderStats(); 
      this._render();
      this._renderPagination();
    } finally { 
      loading.style.display='none'; 
    }
  },

  _renderStats() {
    document.getElementById('docs-stats').innerHTML =
      `<div class="ds-chip"><strong>${this.stats.total}</strong> ${t('docs_stat_total')}</div>
       <div class="ds-chip"><strong>${this.stats.images}</strong> ${t('docs_stat_images')}</div>
       <div class="ds-chip"><strong>${this.stats.pdfs}</strong> ${t('docs_stat_pdfs')}</div>
       <div class="ds-chip"><strong>${this.stats.texts}</strong> ${t('docs_stat_texts')}</div>`;
  },

  _render() {
    const tbody = document.getElementById('docs-tbody');
    const tbl   = document.getElementById('docs-table');
    const empty = document.getElementById('docs-empty');
    tbody.innerHTML = '';
    if (!this.docs.length) { tbl.style.display='none'; empty.style.display='flex'; return; }
    tbl.style.display=''; empty.style.display='none';
    
    const IMG = ['.jpg','.jpeg','.png','.webp'];
    const isOcr  = d => IMG.includes(d.file_type) || d.file_type==='.pdf';
    const isText = d => ['.txt','.docx','.pdf'].includes(d.file_type);
    
    this.docs.forEach((doc, i) => {
      const ext = doc.file_type;
      const stt = (this.page - 1) * this.pageSize + i + 1;
      const iconCls = IMG.includes(ext)?'doc-icon-img':ext==='.pdf'?'doc-icon-pdf':'doc-icon-txt';
      const icon = IMG.includes(ext)?'🖼️':ext==='.pdf'?'📜':'📄';
      const sc = 'status-'+(doc.status||'uploaded');
      const ownerTd = this.isAdmin ? `<td class="owner-cell">${esc(doc.owner||'')}</td>` : '';
      const ocrBtn = isOcr(doc)
        ? `<button class="btn-icon" data-i18n-title="docs_tip_ocr" title="${t('docs_tip_ocr')}" onclick="DocumentsView._sendOCR(${doc.id})">🔍</button>` : '';
      // G1: text files always get tool buttons; images get them once OCR text is stored.
      const _kinds = doc.artifact_kinds || [];
      const _hasText = _kinds.includes('ocr') || _kinds.includes('text');
      const canTools = isText(doc) || _hasText;
      const txtBtns = canTools ? `
        <button class="btn-icon" title="${t('docs_tip_correct')}" onclick="DocumentsView._sendTool(${doc.id},'correct')">✏️</button>
        <button class="btn-icon" title="${t('docs_tip_translate')}" onclick="DocumentsView._sendTool(${doc.id},'translate')">🌐</button>
        <button class="btn-icon" title="${t('docs_tip_summarize')}" onclick="DocumentsView._sendTool(${doc.id},'summarize')">📝</button>` : '';
      // G1: "already processed" badges from persisted artifacts.
      const _pb = (on, label) => on
        ? `<span class="proc-badge" style="display:inline-block;margin-left:4px;padding:1px 6px;border-radius:8px;background:rgba(60,120,220,.12);color:#2c5fd4;font-size:10px;font-weight:700;vertical-align:middle">${label}</span>`
        : '';
      const procBadges = _pb(_hasText, t('badge_text'))
                       + _pb(_kinds.includes('translation'), t('badge_translated'))
                       + _pb(_kinds.includes('summary'), t('badge_summarized'));
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="td-muted" style="text-align:center;font-size:12px">${stt}</td>
        <td><div class="doc-file-cell">
          <div class="doc-icon ${iconCls}">${icon}</div>
          <div><div class="doc-name" title="${esc(doc.filename)}">${esc(doc.filename)}</div>
               <div class="doc-size">${fmtSize(doc.file_size)}</div></div>
        </div></td>
        <td><span class="type-badge">${esc(ext)}</span></td>
        <td class="doc-size">${fmtSize(doc.file_size)}</td>
        ${ownerTd}
        <td class="date-cell">${fmtDate(doc.upload_date)}</td>
        <td><span class="doc-status ${sc}">${esc(doc.status)}</span>${procBadges}</td>
        <td><div class="doc-actions">
          ${ocrBtn}${txtBtns}
          <button class="btn-icon" title="Ask the SmartDocs Agent about this document" onclick="DocumentsView._askAgent('${doc.file_id}')">🤖</button>
          <a class="btn-icon" title="${t('docs_tip_download')}" href="/api/documents/${doc.id}/download">⬇️</a>
          <button class="btn-icon" title="${t('docs_tip_delete')}" style="color:var(--danger)" onclick="DocumentsView._delete(${doc.id}, this)">🗑️</button>
        </div></td>`;
      tbody.appendChild(tr);
    });
  },

  _renderPagination() {
    const pagin = document.getElementById('docs-pagination');
    if (this.totalItems === 0) { pagin.style.display = 'none'; return; }
    pagin.style.display = 'flex';
    
    document.getElementById('pagin-total').textContent = this.totalItems;
    const start = (this.page - 1) * this.pageSize + 1;
    const end = Math.min(this.page * this.pageSize, this.totalItems);
    document.getElementById('pagin-range').textContent = `${start}–${end}`;
    
    document.getElementById('pagin-prev').disabled = (this.page <= 1);
    document.getElementById('pagin-next').disabled = (this.page >= this.totalPages);
    
    const pagesDiv = document.getElementById('pagin-pages');
    pagesDiv.innerHTML = '';
    
    // Simple pagination: show current, first, last, and neighbors
    let range = [];
    for (let i = 1; i <= this.totalPages; i++) {
      if (i === 1 || i === this.totalPages || (i >= this.page - 1 && i <= this.page + 1)) {
        range.push(i);
      }
    }
    
    let last = 0;
    for (let i of range) {
      if (last && i - last > 1) {
        const dots = document.createElement('span');
        dots.className = 'pagin-dots';
        dots.textContent = '...';
        pagesDiv.appendChild(dots);
      }
      const btn = document.createElement('button');
      btn.className = 'pagin-btn' + (i === this.page ? ' active' : '');
      btn.textContent = i;
      btn.addEventListener('click', () => {
        this.page = i;
        this.load();
      });
      pagesDiv.appendChild(btn);
      last = i;
    }
  },

  _docById(id) { return this.docs.find(d => d.id === id); },

  _sendOCR(id) {
    const doc = this._docById(id); if (!doc) return;
    Router.goto('ocr', doc.file_id);   // deep link → Router loads + restores
  },

  // Launch the Agent workspace scoped to this document (Phase 14). The agent page
  // is a separate app at /agent, reached by real navigation (like Admin).
  _askAgent(fileId) {
    if (!fileId) return;
    window.location.href = '/agent?file_id=' + encodeURIComponent(fileId);
  },

  async _sendTool(id, tool) {
    const doc = this._docById(id); if (!doc) return;
    await this._applyToolDoc(doc, tool, true);   // button → also navigate to the view
  },

  // Deep-link loader for #translate/<file_id> and #summarize/<file_id> (Phase 13).
  // The hash router owns the view switch, so this LOADS only (navigate=false),
  // mirroring OCRView._openFromFileId. Reused by agent "View Result" navigation.
  async _openToolFromFileId(tool, fileId) {
    if (!fileId) return;
    const find = () => (this.docs || []).find(d => d.file_id === fileId);
    let doc = find();
    if (!doc) { try { await this.load(); } catch (_) {} doc = find(); }
    if (!doc) { Toast.show(t('doc_not_found') || 'Document not found', 'error'); return; }
    await this._applyToolDoc(doc, tool, false);
  },

  // Shared core: load a document into a tool view, presetting a saved result when
  // one exists. ``navigate`` switches the SPA view (button path) vs. leaving it to
  // the router (deep-link path).
  async _applyToolDoc(doc, tool, navigate) {
    const view = tool==='correct' ? CorrectView : tool==='translate' ? TranslateView : SummarizeView;

    // G1: reuse persisted artifacts — no recompute. Prefer stored OCR/extracted text
    // as the tool input (also works for image documents), and preload a stored
    // translation/summary result when one already exists.
    let srcText = null, storedResult = null;
    try {
      const a = await API.getDocText(doc.id);
      if (a && a.success && a.artifacts) {
        const src = a.artifacts.ocr || a.artifacts.text;
        if (src && src.content) srcText = src.content;
        const wantKind = tool==='translate' ? 'translation' : tool==='summarize' ? 'summary' : null;
        if (wantKind && a.artifacts[wantKind]) storedResult = a.artifacts[wantKind].content;
      }
    } catch (_) { /* fall through to read-text */ }

    // Fallback: extract text from the file (TXT/DOCX/PDF only — images have no text layer).
    if (!srcText) {
      Toast.show(`${t('reading_file')} "${doc.filename}"…`, 'info');
      const r = await API.readText(doc.file_id);
      if (!r.success) { Toast.show(t('toast_run_ocr_first'), 'info'); return; }
      srcText = r.text;
    }

    State.setOcrText(srcText);
    view.importText(srcText);
    State.activeDocFileId = doc.file_id;   // set AFTER importText (which clears it)
    if (navigate) Router.goto(tool);
    if (storedResult != null && view.presetResult) {
      view.presetResult(storedResult);
      Toast.show(t('toast_loaded_saved'), 'success');
    } else {
      Toast.show(t('toast_imported'), 'success');
    }
  },

  async _delete(id, btn) {
    if (!confirm(t('docs_delete_confirm'))) return;
    btn.disabled = true;
    const r = await fetch(`/api/documents/${id}`, { method:'DELETE' });
    const data = await r.json();
    if (data.success) {
      Toast.show(t('toast_delete_success'), 'success');
      this.load();
    } else {
      Toast.show(t('toast_delete_fail') + data.error, 'error');
      btn.disabled = false;
    }
  }
};


// ── Boot ───────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  // Init i18n first
  I18n.init();

  // Router: also call show() when navigating to documents
  const _origGoto = Router.goto.bind(Router);
  Router.goto = function(name, ...rest) {
    _origGoto(name, ...rest);   // forward the deep-link arg (e.g. file_id) — dropping it
                                // here was breaking Documents → OCR restore
    if (name === 'documents') DocumentsView.show();
    if (name === 'ocr') OCRView._resetMode();
    if (name === 'settings') SettingsView.show();
  };

  // Register views
  ['home','ocr','correct','translate','summarize','documents','chat','settings'].forEach(name =>
    Router.register(name, document.getElementById(`view-${name}`)));
  SettingsView.init();

  // Nav links
  document.querySelectorAll('.nav-link').forEach(l =>
    l.addEventListener('click', () => Router.goto(l.dataset.view)));

  // In-app back (OCR viewer → wherever the user came from)
  const ocrBackBtn = document.getElementById('ocr-back-btn');
  if (ocrBackBtn) ocrBackBtn.addEventListener('click', () => Router.back());

  // Home cards: SPA views navigate via the router…
  document.querySelectorAll('[data-goto]').forEach(el =>
    el.addEventListener('click', () => Router.goto(el.dataset.goto)));
  // …separate-page modules (Agent /agent, Admin /admin/) navigate for real.
  document.querySelectorAll('[data-href]').forEach(el =>
    el.addEventListener('click', () => { window.location.href = el.dataset.href; }));

  // ── Output style pills (Short / Bullets / Executive)
  document.querySelectorAll('.mode-pill').forEach(p =>
    p.addEventListener('click', () => {
      document.querySelectorAll('.mode-pill').forEach(x=>x.classList.remove('active'));
      p.classList.add('active');
    }));

  // ── Fast extractive engine pills (Auto / Fast / Smart VI)
  document.querySelectorAll('.sum-engine-pill').forEach(p =>
    p.addEventListener('click', () => {
      document.querySelectorAll('.sum-engine-pill').forEach(x=>x.classList.remove('active'));
      p.classList.add('active');
    }));

  // ── Top-level summary mode pills (Fast Summary / AI Rewrite)
  // Poll interval handle for status probing
  let _aiStatusPoll = null;

  function _updateAiStatusBadge(status, detail) {
    const badge = document.getElementById('ai-status-badge');
    const dot   = badge?.querySelector('.ai-status-dot');
    const txt   = document.getElementById('ai-status-text');
    if (!badge || !txt) return;
    if (status === 'loading' || status === 'warming_up') {
      dot.className = 'ai-status-dot checking';
      txt.textContent = t('sum_ai_loading') || '⏳ Loading AI model…';
    } else if (status === 'ready') {
      dot.className = 'ai-status-dot ready';
      txt.textContent = `🧠 Local AI · ${t('sum_ai_ready_word') || 'Ready'}`;
    } else if (status === 'api') {
      dot.className = 'ai-status-dot api';
      txt.textContent = t('sum_ai_api') || '🌐 API · Ready';
    } else {
      dot.className = 'ai-status-dot unavailable';
      txt.textContent = detail || t('sum_ai_unavailable') || 'AI unavailable — will use Fast';
    }
  }

  function _handleAiStatus(s) {
    // Cache the ACTUAL loaded model name/device so every AI badge reflects reality
    // (e.g. Qwen2.5-3B) instead of a hardcoded label.
    if (s.model_name)   State.aiModel.name   = String(s.model_name).split('/').pop().replace(/-Instruct$/i, '');
    if (s.local_device) State.aiModel.device = s.local_device;
    if (s.local)            { _updateAiStatusBadge('ready');   _stopAiStatusPoll(); }
    else if (s.local_loading) _updateAiStatusBadge('warming_up');
    else if (s.api)         { _updateAiStatusBadge('api');     _stopAiStatusPoll(); }
    else if (s.local_error) { _updateAiStatusBadge('unavailable', `❌ ${String(s.local_error).slice(0,60)}`); _stopAiStatusPoll(); }
    else                    _updateAiStatusBadge('unavailable');
  }

  function _startAiStatusPoll() {
    if (_aiStatusPoll) return;   // already polling
    _updateAiStatusBadge('loading');
    _aiStatusPoll = setInterval(() => {
      API.summarizeStatus().then(_handleAiStatus).catch(() => _updateAiStatusBadge('unavailable'));
    }, 3000);
    // Run immediately once
    API.summarizeStatus().then(_handleAiStatus).catch(() => _updateAiStatusBadge('unavailable'));
  }

  function _stopAiStatusPoll() {
    if (_aiStatusPoll) { clearInterval(_aiStatusPoll); _aiStatusPoll = null; }
  }

  document.querySelectorAll('.sum-mode-pill').forEach(p =>
    p.addEventListener('click', () => {
      document.querySelectorAll('.sum-mode-pill').forEach(x=>x.classList.remove('active'));
      p.classList.add('active');

      const isAI      = p.dataset.summaryMode === 'ai_rewrite';
      const engineWrap = document.getElementById('fast-engine-wrap');
      const aiBadge    = document.getElementById('ai-status-badge');

      if (engineWrap) engineWrap.style.display = isAI ? 'none' : '';
      if (aiBadge)    aiBadge.style.display    = isAI ? 'flex' : 'none';

      if (isAI) {
        _startAiStatusPoll();
      } else {
        _stopAiStatusPoll();
      }
    }));

  // Init views
  OCRView.init();
  CorrectView.init();
  TranslateView.init();
  SummarizeView.init();
  DocumentsView.init();

  // Render the initial view from the URL hash (defaults to home), and wire
  // browser Back/Forward via hashchange.
  Router.init();
});

// ── window.App bridge for ChatModule ─────────────────────────────────────────
// Exposes OCR state and toast utility so chat.js can stay decoupled from app.js
window.App = {
  get lastFileId()   { return window._chatBridge?.fileId   || null; },
  get lastOcrText()  { return window._chatBridge?.ocrText  || '';   },
  get lastFilename() { return window._chatBridge?.filename || null; },
  toast(msg, type)   { Toast.show(msg, type || 'info'); },
  // Open a library document in the existing OCR viewer (reused by ChatModule's
  // "View document" action). Navigates via the hash router; Router._render then
  // resolves the file_id and loads + restores the document.
  openDocumentByFileId(fileId) {
    if (!fileId) return;
    Router.goto('ocr', fileId);
  },
};
window._chatBridge = { fileId: null, ocrText: '', filename: null };

// Patch OCRView._renderTextAll to also push to chat bridge
const _origRenderTextAll = OCRView._renderTextAll.bind(OCRView);
OCRView._renderTextAll = function() {
  _origRenderTextAll();
  window._chatBridge.fileId   = OCRView.fileId;
  window._chatBridge.ocrText  = State.ocrText;
  window._chatBridge.filename = document.getElementById('ocr-file-name')?.textContent || OCRView.fileId;
  if (window.ChatModule && typeof window.ChatModule.onOcrComplete === 'function') {
    window.ChatModule.onOcrComplete(
      window._chatBridge.fileId,
      window._chatBridge.ocrText,
      window._chatBridge.filename
    );
  }
};

