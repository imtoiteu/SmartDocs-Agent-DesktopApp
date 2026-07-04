/* SmartDocs Agent workspace (Phase 10, additive). Vanilla JS, no build.
   Sessions list/resume + transcript + readable reasoning trace. Backend is the
   Phase 6 session endpoints (/api/agent/conversations[/<id>]) — no backend change. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // Durable session. Null = a fresh session (created server-side on first run).
  let conversationId = null;

  async function api(path, opts) {
    const res = await fetch(path, Object.assign({
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
    }, opts || {}));
    if (res.status === 401) { window.location = "/login"; throw new Error("auth"); }
    let body = {};
    try { body = await res.json(); } catch (e) { body = {}; }
    return { ok: res.ok, status: res.status, body };
  }

  // ── Document scope: picker + upload (Phase 14) ───────────────────────────────
  // The user picks/uploads a document by NAME; the file_id is resolved internally
  // and never shown. Reuses the existing /api/documents, /api/upload, /api/ocr/all
  // and /api/read-text endpoints (no new backend surface).
  async function loadDocs(keepValue) {
    const sel = $("agent-doc");
    const prev = keepValue != null ? keepValue : sel.value;
    try {
      // Recent documents only (newest-first), filenames shown; file_id stays internal.
      const { body } = await api("/api/documents?page_size=10&page=1");
      const docs = (body && body.documents) || [];
      sel.innerHTML = '<option value="">— none —</option>';
      docs.forEach((d) => {
        const o = document.createElement("option");
        o.value = d.file_id; o.textContent = d.filename;
        sel.appendChild(o);
      });
      if (prev) selectDoc(prev);
    } catch (e) { /* handled by api() */ }
    updateScopeLine();
  }

  // Select a document by file_id; if it isn't in the list (e.g. a brand-new upload
  // not yet reloaded), add a labelled option so the value still resolves.
  function selectDoc(fileId, label) {
    const sel = $("agent-doc");
    sel.value = fileId;
    if (sel.value !== fileId) {
      const o = document.createElement("option");
      o.value = fileId; o.textContent = label || "Attached document";
      sel.appendChild(o); sel.value = fileId;
    }
    updateScopeLine();
  }

  function setUploadStatus(html) { $("agent-upload-status").innerHTML = html || ""; }

  // ── Active scope (UI item 4): shown next to Run + on each result turn ───────
  function scopeLabel() {
    const sel = $("agent-doc");
    const fid = (sel && sel.value || "").trim();
    if (fid && sel.selectedOptions[0]) {
      return "📄 " + sel.selectedOptions[0].textContent + " only";
    }
    return "📚 entire document library";
  }

  function updateScopeLine() {
    const el = $("agent-scope");
    if (el) el.textContent = "Scope: " + scopeLabel();
  }

  // Copy-to-clipboard with execCommand fallback (mirrors app.js pattern —
  // agent page is standalone and does not load app.js).
  async function copyText(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) { /* fall through */ }
    try {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch (e) { return false; }
  }

  // Non-secret preference: remember the user's max-steps choice (UI item 7).
  const STEPS_STORE_KEY = "smartdocs_agent_steps";

  // Resolve the OCR engine for a request via the backend (single source of truth
  // for the routing rules). Falls back to GLM if the lookup fails.
  async function resolveOcrEngine(message) {
    try {
      const { body } = await api("/api/agent/ocr-engine?message=" + encodeURIComponent(message || ""));
      if (body && body.success) return { engine: body.engine, label: body.label };
    } catch (e) { /* fall through */ }
    return { engine: "glmocr", label: "GLM OCR" };
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // Wait out the async auto-index window so an "upload then immediately ask" flow
  // doesn't miss the just-uploaded document. Polls the index-status endpoint until
  // the document is indexed or the timeout elapses (then retrieval degrades
  // gracefully rather than blocking forever).
  async function waitForIndex(fileId, timeoutMs) {
    if (!fileId) return false;
    const deadline = Date.now() + (timeoutMs || 12000);
    while (Date.now() < deadline) {
      try {
        const { body } = await api("/api/agent/index-status?file_id=" + encodeURIComponent(fileId));
        if (body && body.success && body.indexed) return true;
      } catch (e) { return false; }
      await sleep(400);
    }
    return false;
  }

  async function apiUpload(file) {
    const fd = new FormData(); fd.append("file", file);
    const res = await fetch("/api/upload", { method: "POST", credentials: "same-origin", body: fd });
    if (res.status === 401) { window.location = "/login"; throw new Error("auth"); }
    try { return await res.json(); } catch (e) { return { success: false, error: "bad response" }; }
  }

  async function onAgentUpload(e) {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    e.target.value = "";                         // allow re-selecting the same file
    setUploadStatus("Uploading “" + f.name + "”…");
    let up;
    try { up = await apiUpload(f); } catch (_) { return; }
    if (!up || !up.success) { setUploadStatus('<span class="bad">Upload failed: ' + ((up && up.error) || "") + "</span>"); return; }
    const fid = up.file_id, name = up.filename || f.name;
    let didOcr = false, engineLabel = "";
    if (up.is_image || up.is_pdf) {
      // Pick the OCR engine from the typed request (default GLM; Vietnamese →
      // VietOCR). The routing rules live server-side (single source of truth).
      const route = await resolveOcrEngine($("msg").value || "");
      engineLabel = route.label;
      setUploadStatus("Running OCR (" + route.label + ") on “" + name + "”… (this can take a moment)");
      const { body } = await api("/api/ocr/all", {
        method: "POST", body: JSON.stringify({ file_id: fid, engine: route.engine }) });
      if (!body || !body.success) {
        setUploadStatus('<span class="bad">OCR failed: ' + ((body && body.error) || "") + "</span>");
      } else {
        didOcr = true;
        // The durable "View OCR Result" link now lives in the conversation turn
        // (recordIngest), so the banner is just transient feedback (no link).
        setUploadStatus('<span class="ok">OCR complete</span> (' + route.label + ') — “' + name + '” attached.');
      }
    } else {
      // Text file: extract + index so the agent can use its content.
      await api("/api/read-text", { method: "POST", body: JSON.stringify({ file_id: fid }) });
      setUploadStatus('<span class="ok">Attached</span> — “' + name + '”.');
    }
    // Wait out the async auto-index so a follow-up agent run over this document
    // (RAG/QA) sees it instead of racing the background indexer.
    await waitForIndex(fid, 12000);
    await loadDocs(fid);                          // refresh list and keep the new doc selected
    selectDoc(fid, name);
    // Record the upload (and any OCR) as a durable turn so the file + its result
    // card persist with the session and reopen later (F1).
    await recordIngest(fid, didOcr, engineLabel);
  }

  // Persist an agent-page upload as a conversation turn (F1). Best-effort: the
  // upload already succeeded; if this fails the file is still selectable.
  async function recordIngest(fileId, didOcr, engineLabel) {
    try {
      const { body } = await api("/api/agent/ingest", {
        method: "POST",
        body: JSON.stringify({ file_id: fileId, conversation_id: conversationId,
          ocr: !!didOcr, engine_label: engineLabel || "" }),
      });
      if (body && body.success && body.conversation_id) {
        conversationId = body.conversation_id;
        await openSession(conversationId);       // show the new turn + its card
        loadSessions();                          // session appears / count bumps
      }
    } catch (e) { /* ingest is best-effort */ }
  }

  // ── Sessions ───────────────────────────────────────────────────────────────
  function setSessionLabel() {
    $("session-label").textContent = conversationId ? "Session #" + conversationId : "New session";
    const dis = !conversationId;
    const rb = $("rename-session"), db = $("delete-session");
    if (rb) rb.disabled = dis;
    if (db) db.disabled = dis;
  }

  function markActive() {
    document.querySelectorAll("#sessions li").forEach((li) =>
      li.classList.toggle("active", String(li.dataset.id) === String(conversationId)));
  }

  async function loadSessions() {
    try {
      const { body } = await api("/api/agent/conversations");
      const ul = $("sessions"); ul.innerHTML = "";
      const convs = body.conversations || [];
      if (!convs.length) { ul.innerHTML = '<li class="muted">No sessions yet.</li>'; return; }
      convs.forEach((c) => {
        const li = document.createElement("li");
        li.dataset.id = c.id;
        if (String(c.id) === String(conversationId)) li.className = "active";
        const t = document.createElement("div"); t.className = "sess-title";
        t.textContent = c.title || ("Session #" + c.id);
        const m = document.createElement("div"); m.className = "sess-meta";
        const n = c.message_count || 0;
        m.textContent = n + " msg" + (n === 1 ? "" : "s");
        li.appendChild(t); li.appendChild(m);
        const del = document.createElement("button");
        del.className = "sess-del"; del.title = "Delete session"; del.textContent = "✕";
        del.addEventListener("click", (e) => { e.stopPropagation(); deleteSession(c.id); });
        li.appendChild(del);
        li.addEventListener("click", () => openSession(c.id));
        ul.appendChild(li);
      });
    } catch (e) { /* handled by api() */ }
  }

  // Re-scope the document picker to the session's most recent attached source doc,
  // so a follow-up run stays scoped without the user re-picking after navigating to
  // a result and back (F2). Skips documents flagged unavailable on reopen (F6).
  function rescopeFromMessages(messages) {
    let last = null;
    (messages || []).forEach((m) => (m.artifacts || []).forEach((a) => {
      if (a.kind === "source" && a.file_id && a.available !== false) last = a;
    }));
    if (last) selectDoc(last.file_id, last.label);
    else { const sel = $("agent-doc"); if (sel) sel.value = ""; }
  }

  async function openSession(id) {
    try {
      const { body } = await api("/api/agent/conversations/" + encodeURIComponent(id));
      if (!body.success) return;
      conversationId = id;
      renderTranscript(body.messages || []);
      rescopeFromMessages(body.messages || []);
      $("run-out").style.display = "none";
      $("run-status").textContent = "";
      setSessionLabel(); markActive();
    } catch (e) { /* handled */ }
  }

  function newSession() {
    conversationId = null;
    $("transcript").innerHTML = "";
    $("run-out").style.display = "none";
    $("run-status").textContent = "";
    setSessionLabel(); markActive();
    $("msg").focus();
  }

  async function renameSession() {
    if (!conversationId) return;
    const cur = ($("session-label").textContent || "").replace(/^Session #\d+$/, "");
    const title = window.prompt("Rename session:", cur);
    if (!title || !title.trim()) return;
    try {
      const { body } = await api("/api/agent/conversations/" + encodeURIComponent(conversationId),
        { method: "PATCH", body: JSON.stringify({ title: title.trim() }) });
      if (body && body.success) {
        $("session-label").textContent = (body.conversation && body.conversation.title) || title.trim();
        loadSessions();
      }
    } catch (e) { /* handled */ }
  }

  // Delete a session's history + references. Generated documents are kept (only the
  // agent session is removed). ``id`` defaults to the open session.
  async function deleteSession(id) {
    id = id != null ? id : conversationId;
    if (!id) return;
    if (!window.confirm("Delete this session? The generated documents are kept — only the session history and its links are removed.")) return;
    try {
      const { body } = await api("/api/agent/conversations/" + encodeURIComponent(id), { method: "DELETE" });
      if (body && body.success) {
        if (String(id) === String(conversationId)) newSession();
        loadSessions();
      }
    } catch (e) { /* handled */ }
  }

  // ── Transcript ─────────────────────────────────────────────────────────────
  // Friendly action label per destination module (the link OPENS the existing
  // module viewer — no viewer is duplicated here).
  function actionLabel(module) {
    return ({ ocr: "View OCR Result", text: "View Extracted Text",
             summarize: "View Summary", translate: "View Translation",
             chat: "View Conversation" })[module]
      || "View Result →";
  }

  // A corpus-wide retrieval hit (vs a document this session produced). New runs tag
  // it kind="citation"; older rows are kind="result" with a "Source · " label (F4).
  function isCitation(a) {
    return a.kind === "citation" || (a.kind === "result" && /^Source · /.test(a.label || ""));
  }
  // A card whose target document/conversation no longer exists (annotated on reopen
  // by the backend, F6). Live runs never set this, so cards stay clickable.
  function isUnavailable(a) { return a.available === false; }
  function unavailableTag() {
    const s = document.createElement("span");
    s.className = "muted small"; s.textContent = "(no longer available)";
    return s;
  }

  // Render a list of result/citation cards under a heading. A dead card (F6) shows
  // "(no longer available)" instead of a navigation button.
  function renderResultList(div, items, headText) {
    const head = document.createElement("div");
    head.className = "muted small"; head.style.margin = "6px 0 2px"; head.textContent = headText;
    div.appendChild(head);
    const ul = document.createElement("ul"); ul.className = "results";
    items.forEach((a) => {
      const li = document.createElement("li");
      const main = document.createElement("div"); main.className = "r-main";
      const lab = document.createElement("div"); lab.className = "r-label";
      lab.textContent = a.label || a.route || a.module || "result";
      const mod = document.createElement("span"); mod.className = "r-module";
      mod.textContent = a.module || "";
      main.appendChild(lab); main.appendChild(mod); li.appendChild(main);
      if (isUnavailable(a)) {
        li.appendChild(unavailableTag());
      } else {
        const btn = document.createElement("button"); btn.textContent = actionLabel(a.module);
        btn.addEventListener("click", () => { window.location.href = "/" + (a.route || ""); });
        li.appendChild(btn);
      }
      ul.appendChild(li);
    });
    div.appendChild(ul);
  }

  // Render a turn's persisted file/artifact references (Phase 16/17): source files
  // as 📄 chips, the session's own produced outputs under "Artifacts", and
  // corpus-wide retrieval hits separately under "Sources" (F4) — all into the
  // existing module viewers, with dead links disabled (F6).
  function renderTurnArtifacts(div, artifacts) {
    const list = artifacts || [];
    const sources = list.filter((a) => a.kind === "source");
    const produced = list.filter((a) => a.kind === "result" && !isCitation(a));
    const citations = list.filter((a) => isCitation(a));
    sources.forEach((a) => {
      const f = document.createElement("div"); f.className = "turn-file";
      if (a.route && !isUnavailable(a)) {
        const link = document.createElement("a");
        link.href = "/" + a.route; link.textContent = "📄 " + (a.label || "document");
        f.appendChild(link);
      } else {
        f.textContent = "📄 " + (a.label || "document");
        if (isUnavailable(a)) { f.appendChild(document.createTextNode(" ")); f.appendChild(unavailableTag()); }
      }
      div.appendChild(f);
    });
    if (produced.length) renderResultList(div, produced, "Artifacts:");
    if (citations.length) renderResultList(div, citations, "Sources (from your library):");
  }

  function appendTurn(role, content, meta) {
    meta = meta || {};
    const div = document.createElement("div");
    div.className = "turn " + (role === "user" ? "user" : "assistant");
    const who = document.createElement("div"); who.className = "who"; who.textContent = role;
    div.appendChild(who);
    const body = document.createElement("div"); body.textContent = content || ""; div.appendChild(body);
    renderTurnArtifacts(div, meta.artifacts);          // files + "View Result" links
    const calls = (meta.skill_calls || []).map((n) => "🧩 " + n)
      .concat((meta.tool_calls || []).map((n) => "🔧 " + n));
    const flags = meta.flags || [];              // e.g. scope / coverage notes
    const wantCopy = role !== "user" && (content || "").trim();
    if (calls.length || meta.status || flags.length || wantCopy) {
      const chips = document.createElement("div"); chips.className = "chips";
      if (meta.status) {
        const c = document.createElement("span"); c.className = "chip"; c.textContent = meta.status;
        chips.appendChild(c);
      }
      flags.forEach((x) => {
        const c = document.createElement("span"); c.className = "chip"; c.textContent = x;
        chips.appendChild(c);
      });
      calls.forEach((x) => {
        const c = document.createElement("span"); c.className = "chip"; c.textContent = x;
        chips.appendChild(c);
      });
      if (wantCopy) {                            // Copy Result (UI item 6)
        const b = document.createElement("button");
        b.className = "hbtn"; b.textContent = "📋 Copy";
        b.title = "Copy this answer to the clipboard";
        b.addEventListener("click", async () => {
          b.textContent = (await copyText(content)) ? "Copied ✓" : "Copy failed";
          setTimeout(() => { b.textContent = "📋 Copy"; }, 1600);
        });
        chips.appendChild(b);
      }
      div.appendChild(chips);
    }
    const t = $("transcript");
    t.appendChild(div);
    t.scrollTop = t.scrollHeight;
  }

  function renderTranscript(messages) {
    const t = $("transcript"); t.innerHTML = "";
    (messages || []).forEach((m) =>
      appendTurn(m.role, m.content, { tool_calls: m.tool_calls || [], artifacts: m.artifacts || [] }));
  }

  // ── Reasoning trace ────────────────────────────────────────────────────────
  function renderTrace(steps) {
    const wrap = $("run-trace"); wrap.innerHTML = "";
    (steps || []).forEach((s) => {
      const row = document.createElement("div"); row.className = "step";
      const hd = document.createElement("div"); hd.className = "hd";
      const kind = document.createElement("span"); kind.className = "kind " + (s.kind || "");
      kind.textContent = s.kind || "step"; hd.appendChild(kind);
      const name = document.createElement("b");
      name.textContent = s.tool || (s.kind === "final" ? "final answer" : "");
      hd.appendChild(name);
      const obs = s.observation || {};
      if (obs && typeof obs.ok === "boolean") {
        const st = document.createElement("span"); st.className = "small " + (obs.ok ? "ok" : "bad");
        st.textContent = obs.ok ? "ok" : ("error" + (obs.error ? ": " + String(obs.error).slice(0, 120) : ""));
        hd.appendChild(st);
      }
      if (obs && obs.meta && obs.meta.elapsed_ms != null) {
        const ms = document.createElement("span"); ms.className = "muted small";
        ms.textContent = obs.meta.elapsed_ms + " ms"; hd.appendChild(ms);
      }
      row.appendChild(hd);
      if (s.arguments && Object.keys(s.arguments).length) {
        const a = document.createElement("div"); a.className = "muted small"; a.style.marginTop = "3px";
        a.textContent = "args: " + JSON.stringify(s.arguments).slice(0, 200);
        row.appendChild(a);
      }
      wrap.appendChild(row);
    });
  }

  // ── Results (Phase 13) ───────────────────────────────────────────────────────
  // The agent orchestrates and persists outputs via the existing artifact pipeline;
  // each result is OPENED in the SmartDocs module viewer already built for it (no
  // result viewers are duplicated here). "View Result" navigates the SPA hash route.
  function renderResults(el, results) {
    if (!el) return;
    el.innerHTML = "";
    (results || []).forEach((r) => {
      const li = document.createElement("li");
      const main = document.createElement("div"); main.className = "r-main";
      const lab = document.createElement("div"); lab.className = "r-label";
      lab.textContent = r.label || r.route || r.module || "result";
      const mod = document.createElement("span"); mod.className = "r-module";
      mod.textContent = r.module || "";
      main.appendChild(lab); main.appendChild(mod); li.appendChild(main);
      const btn = document.createElement("button");
      btn.textContent = "View Result →";
      btn.addEventListener("click", () => { window.location.href = "/" + (r.route || ""); });
      li.appendChild(btn);
      el.appendChild(li);
    });
    if (el.id === "run-results") {
      const wrap = $("run-results-wrap");
      if (wrap) wrap.style.display = (results && results.length) ? "block" : "none";
    }
  }

  function renderRunDetails(body) {
    const planEl = $("run-plan");
    if (body.plan) { planEl.textContent = "Plan: " + body.plan; planEl.style.display = "block"; }
    else { planEl.textContent = ""; planEl.style.display = "none"; }

    // Citations (UI item 6): document NAME + excerpt, clickable into the source
    // viewer. Names/routes come from the run's own result destinations (server-
    // resolved, ownership-checked) — never from anything the client invents.
    const byFid = {};
    (body.results || []).forEach((r) => {
      if (r.file_id && r.route) {
        byFid[r.file_id] = { route: r.route,
          name: (r.label || r.file_id).replace(/^[^·]*·\s*/, "") };
      }
    });
    const cwrap = $("run-citations-wrap"), cul = $("run-citations"); cul.innerHTML = "";
    const cites = body.citations || [];
    cites.forEach((c) => {
      const li = document.createElement("li");
      const dest = byFid[c.file_id];
      const b = document.createElement("b");
      b.textContent = "📄 " + ((dest && dest.name) || c.file_id) +
        (c.score != null ? "  ·  " + c.score : "");
      const s = document.createElement("span"); s.textContent = c.excerpt || "";
      li.appendChild(b); li.appendChild(s);
      if (dest) {
        li.style.cursor = "pointer";
        li.title = "Open this source document";
        li.setAttribute("role", "link"); li.tabIndex = 0;
        const open = () => { window.location.href = "/" + dest.route; };
        li.addEventListener("click", open);
        li.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
      }
      cul.appendChild(li);
    });
    if (cites.length && body.context_truncated) {
      const note = document.createElement("li");
      note.className = "muted small";
      note.textContent = "⚠ The attached document was longer than the context " +
        "window — the answer may not cover all of it.";
      cul.appendChild(note);
    }
    cwrap.style.display = cites.length ? "block" : "none";

    // OCR engine for this request (shown only when the request actually involved OCR).
    const oe = body.ocr_engine, oeEl = $("run-ocr-engine");
    if (oeEl) {
      if (oe && oe.ocr_requested) { oeEl.textContent = "OCR engine: " + oe.label; oeEl.style.display = "block"; }
      else { oeEl.textContent = ""; oeEl.style.display = "none"; }
    }

    // Generated artifacts are shown in the conversation turn (persistent); the
    // run-out panel keeps only the transient reasoning detail.
    const rrw = $("run-results-wrap"); if (rrw) rrw.style.display = "none";
    renderTrace(body.steps || []);
    $("run-steps").textContent = JSON.stringify(body.steps || [], null, 2);
    $("run-out").style.display = "block";
  }

  // ── Agent run ──────────────────────────────────────────────────────────────
  // Human text for a progress phase polled from /api/agent/progress/<run_id>.
  function progressText(p) {
    const at = p.step ? "Step " + p.step + "/" + (p.max_steps || "?") + ": " : "";
    if (p.phase === "planning") return "Planning…";
    if (p.phase === "thinking") return at + "thinking…";
    if (p.phase === "acting") return at + "running " + (p.name || p.kind || "a tool") + "…";
    if (p.phase === "synthesis") return "Writing the final answer…";
    return "Running…";
  }

  // Last submitted run, so a failed one can be retried as-is (UI item 5).
  let lastRun = null;

  // One-time confirmation before the FIRST cloud-processing request (UI item 2):
  // only when cloud is allowed AND a cloud key is actually configured AND the
  // user has never acknowledged it. Accepting persists the ack server-side.
  async function confirmCloudIfNeeded() {
    const s = llmStatus;
    if (!s || s.processing_mode !== "cloud_allowed"
          || !s.cloud_keys_configured || s.cloud_ack) return true;
    const ok = window.confirm(
      "This run may send document text, retrieval excerpts and your prompt to " +
      "the configured cloud provider (e.g. Groq or Gemini).\n\nContinue? " +
      "(You can switch to Local only in Settings at any time.)");
    if (!ok) {
      const st = $("run-status");
      st.textContent = "Run cancelled — nothing was sent. ";
      st.appendChild(settingsLink());
      return false;
    }
    try {
      await api("/api/settings/privacy", { method: "PUT",
        body: JSON.stringify({ allow_cloud: true, ack: true }) });
      llmStatus.cloud_ack = true;
    } catch (e) { /* ack persistence is best-effort; the user already agreed */ }
    return true;
  }

  // Failure state with a real Retry (UI item 5) — restores the exact last run.
  function offerRetry(errText) {
    const st = $("run-status");
    st.innerHTML = "";
    const s = document.createElement("span");
    s.className = "bad"; s.textContent = errText + " ";
    st.appendChild(s);
    const b = document.createElement("button");
    b.className = "hbtn"; b.textContent = "↻ Retry";
    b.addEventListener("click", () => {
      if (lastRun) {
        $("msg").value = lastRun.message;
        $("steps").value = lastRun.maxSteps;
        if (lastRun.fileId) selectDoc(lastRun.fileId, lastRun.fileName);
      }
      runAgent();
    });
    st.appendChild(b);
  }

  async function runAgent() {
    const message = $("msg").value.trim();
    if (!message) { $("run-status").textContent = "Enter a request first."; return; }
    if (!(await confirmCloudIfNeeded())) return;
    const max_steps = parseInt($("steps").value, 10) || 3;
    try { localStorage.setItem(STEPS_STORE_KEY, String(max_steps)); } catch (e) { /* optional */ }
    $("run").disabled = true;
    $("run-status").textContent = "Running… (loading the local model on first run can take a moment)";
    // Source file shown on the user turn (file_id resolved internally; only the
    // filename is shown). The server persists the same reference for reopen.
    const sel = $("agent-doc");
    const fileId = (sel.value || "").trim();
    const fileName = fileId && sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : "";
    const userArtifacts = fileId
      ? [{ kind: "source", file_id: fileId, route: "#ocr/" + fileId, label: fileName }] : [];
    const scopeAtRun = scopeLabel();               // shown on the result (item 4)
    lastRun = { message, fileId, fileName, maxSteps: max_steps };
    const runStart = Date.now();
    appendTurn("user", message, { artifacts: userArtifacts });   // optimistic echo
    $("msg").value = "";
    // Progress feedback: an opaque run id lets us poll the run's current phase
    // ("Step 2/3: running chat…") while the POST is in flight. Best-effort — a
    // failed poll just leaves the generic status text.
    const runId = "r" + Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
    let polling = true;
    const poller = setInterval(async () => {
      if (!polling) return;
      const secs = Math.round((Date.now() - runStart) / 1000);
      try {
        const { body } = await api("/api/agent/progress/" + encodeURIComponent(runId));
        const p = body && body.progress;
        if (polling && p && p.phase && p.phase !== "done") {
          $("run-status").textContent = progressText(p) + " · " + secs + "s";
        } else if (polling) {
          $("run-status").textContent = "Running… (" + secs + "s)";
        }
      } catch (e) { /* progress is optional */ }
    }, 1200);
    try {
      const payload = { message, max_steps, conversation_id: conversationId,
                        run_id: runId };
      if (fileId) payload.file_id = fileId;
      const { body } = await api("/api/agent/run", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      polling = false;                       // a late poll must not overwrite the result
      if (!body.success) {
        // A failed run still records an honest "run failed" turn server-side (F5).
        // Adopt the session and re-render so the transcript reflects what happened
        // instead of leaving the optimistic echo with no response.
        if (body.conversation_id) {
          conversationId = body.conversation_id;
          await openSession(conversationId);
          loadSessions();
        }
        if (body.disabled) {                     // config problem — Settings, not Retry
          const st = $("run-status");
          st.innerHTML = '<span class="bad"></span>';
          st.firstChild.textContent = body.error || "This feature is disabled.";
          st.appendChild(settingsLink());
        } else {
          offerRetry(body.error || "The run failed.");
        }
        return;
      }
      if (body.conversation_id) conversationId = body.conversation_id;
      $("run-status").textContent = "";
      const resultArtifacts = (body.results || []).map((d) => ({
        kind: (d.origin === "citation" ? "citation" : "result"),
        module: d.module, route: d.route, file_id: d.file_id, label: d.label }));
      // Honesty flags (UI item 6): coverage + the scope this run actually used.
      const flags = ["scope: " + scopeAtRun];
      if (body.context_truncated) flags.push("⚠ partial document context");
      const consulted = (body.citations || []).length > 0 || !!fileId ||
        (body.tool_calls || []).some((n) => n === "chat" || n === "knowledge_search");
      if (!consulted) flags.push("ℹ documents not consulted");
      appendTurn("assistant", body.answer || "(no answer)", {
        tool_calls: body.tool_calls || [], skill_calls: body.skill_calls || [],
        status: body.completed ? "completed"
              : (body.timed_out ? "partial result (time limit)" : "max steps reached"),
        flags: flags,
        artifacts: resultArtifacts,
      });
      renderRunDetails(body);
      setSessionLabel();
      loadSessions();                      // new session appears / counts bump
    } catch (e) {
      offerRetry("Request failed (network or server error).");
    } finally {
      polling = false;
      clearInterval(poller);
      $("run").disabled = false;
    }
  }

  // ── Skills (presented as plain-language "actions") ───────────────────────────
  // Human-friendly action names so users don't need to know internal skill ids.
  const SKILL_LABELS = {
    ocr: "OCR",
    summarize: "Summarize",
    translate: "Translate",
    correct: "Correct Text",
    general_chat: "General Chat",
    document_chat: "Document Chat",
  };
  const SKILL_ORDER = ["ocr", "summarize", "translate", "correct",
                       "general_chat", "document_chat"];

  // Target languages offered by the translator. Codes come from the backend
  // (single source of truth); names below are for display only.
  let SUPPORTED_LANGS = ["de", "en", "es", "fr", "ja", "ko", "vi", "zh"];
  const LANG_NAMES = {
    en: "English", vi: "Vietnamese", zh: "Chinese", ja: "Japanese",
    ko: "Korean", fr: "French", de: "German", es: "Spanish",
  };
  const OCR_ENGINES = [
    { value: "", label: "Default (recommended)" },
    { value: "glmocr", label: "GLM OCR" },
    { value: "paddleocr_modern", label: "PaddleOCR Modern" },
    { value: "vietocr", label: "VietOCR (Vietnamese)" },
    { value: "paddle", label: "Legacy PaddleOCR" },
  ];
  // OCR-capable document types (mirrors backend IMG_EXTS + .pdf). The OCR action's
  // "Existing document" picker is restricted to these; DOCX/TXT are not OCR-able.
  const OCR_FILE_TYPES = [".pdf", ".jpg", ".jpeg", ".png", ".webp"];

  // Summary pipeline modes mirror the standalone Summarize feature: a fast extractive
  // pass, or an additional abstractive AI rewrite. Values match the summarize tool.
  const SUMMARY_MODES = [
    { value: "fast", label: "⚡ Fast Summary (recommended)" },
    { value: "ai_rewrite", label: "🤖 AI Rewrite Summary" },
  ];

  // Atomic, single-purpose actions only. OCR uses a "source" control (upload a new
  // file OR pick an existing OCR-capable document). Document Q&A is not an action —
  // it lives in the Chat experience (Document Chat).
  const SKILL_FIELDS = {
    ocr: [
      { key: "__source", type: "source", sourceModes: ["upload", "existing"],
        uploadAccept: ".jpg,.jpeg,.png,.webp,.pdf", docTypes: OCR_FILE_TYPES },
      { key: "engine", label: "OCR engine", type: "engine" },
    ],
    summarize: [
      { key: "text", label: "Text", type: "textarea" },
      { key: "summary_mode", label: "Summary mode", type: "summary_mode" },
    ],
    translate: [
      { key: "text", label: "Text", type: "textarea" },
      { key: "to_lang", label: "Translate to", type: "lang" },
    ],
    correct: [
      { key: "text", label: "Text", type: "textarea" },
    ],
    // Chat entry points — these don't run a skill; they open the existing Chat
    // experience (a fresh conversation deep-linked at /#chat/<id>), so there's no
    // second chat system here. General Chat needs no input; Document Chat picks the
    // single document to scope to (upload a new one or reuse an existing one).
    general_chat: [],
    document_chat: [
      { key: "__source", type: "source", sourceModes: ["upload", "existing"],
        uploadAccept: ".jpg,.jpeg,.png,.webp,.pdf,.txt,.docx" },
    ],
  };

  // Fill a <select> with the caller's recent documents (filenames shown; file_id
  // stays the value). Optional selects get a leading "none/whole-library" entry.
  async function fillDocSelect(sel, optional, noneLabel, fileTypes) {
    sel.innerHTML = optional ? '<option value="">' + (noneLabel || "— none —") + "</option>" : "";
    try {
      const { body } = await api("/api/documents?page_size=50&page=1");
      let docs = (body && body.documents) || [];
      // Restrict to a set of file types when given (e.g. OCR → images/PDF only).
      if (fileTypes && fileTypes.length) {
        docs = docs.filter((d) => fileTypes.indexOf((d.file_type || "").toLowerCase()) >= 0);
      }
      if (!optional && !docs.length) {
        sel.innerHTML = '<option value="">' +
          (fileTypes ? "(no image/PDF documents — upload one)" : "(no documents yet — upload one above)") +
          "</option>";
        return;
      }
      docs.forEach((d) => {
        const o = document.createElement("option");
        o.value = d.file_id; o.textContent = d.filename;
        o.dataset.type = (d.file_type || "").toLowerCase();   // for client-side validation
        sel.appendChild(o);
      });
    } catch (e) { /* handled by api() */ }
  }

  function buildLangSelect(sel, optional) {
    if (optional) {
      const o = document.createElement("option");
      o.value = ""; o.textContent = "— none (summary only) —";
      sel.appendChild(o);
    }
    SUPPORTED_LANGS.forEach((code) => {
      const o = document.createElement("option");
      o.value = code; o.textContent = LANG_NAMES[code] || code;
      sel.appendChild(o);
    });
  }

  function renderSkillFields() {
    const name = $("skill").value;
    const wrap = $("skill-fields"); wrap.innerHTML = "";
    (SKILL_FIELDS[name] || []).forEach((f) => {
      if (f.type === "source") { renderSourceField(wrap, f); return; }
      const label = document.createElement("label");
      label.textContent = f.label + (f.optional ? " (optional)" : "");
      label.htmlFor = "sf_" + f.key;
      let input;
      if (f.type === "textarea") {
        input = document.createElement("textarea");
      } else if (f.type === "lang") {
        input = document.createElement("select"); buildLangSelect(input, f.optional);
      } else if (f.type === "summary_mode") {
        input = document.createElement("select");
        SUMMARY_MODES.forEach((m) => {
          const o = document.createElement("option");
          o.value = m.value; o.textContent = m.label; input.appendChild(o);
        });
      } else if (f.type === "engine") {
        input = document.createElement("select");
        OCR_ENGINES.forEach((e) => {
          const o = document.createElement("option");
          o.value = e.value; o.textContent = e.label; input.appendChild(o);
        });
      } else if (f.type === "doc") {
        input = document.createElement("select");
      } else {
        input = document.createElement("input"); input.type = "text";
      }
      input.id = "sf_" + f.key;
      if (f.value) input.value = f.value;
      wrap.appendChild(label); wrap.appendChild(input);
      if (f.type === "doc") fillDocSelect(input, !!f.optional, "— entire library —");
    });
  }

  async function loadSkills() {
    try {
      const { body } = await api("/api/agent/skills");
      if (body && Array.isArray(body.languages) && body.languages.length) {
        SUPPORTED_LANGS = body.languages;
      }
      const sel = $("skill"); sel.innerHTML = "";
      const runnable = (body.skills || []).filter((s) => s.http_runnable).map((s) => s.name);
      // "OCR" and the two Chat entry points are first-class actions backed by
      // existing pipelines (OCR → /api/ocr/all; Chat → the existing Chat experience),
      // not HTTP skills — inject them alongside the runnable skills. Only keep actions
      // we have a field config for (guards against stray skills).
      const actions = ["ocr"].concat(runnable).concat(["general_chat", "document_chat"])
        .filter((n) => SKILL_FIELDS[n]);
      const ordered = SKILL_ORDER.filter((n) => actions.indexOf(n) >= 0)
        .concat(actions.filter((n) => SKILL_ORDER.indexOf(n) < 0));
      ordered.forEach((n) => {
        const o = document.createElement("option");
        o.value = n; o.textContent = SKILL_LABELS[n] || n;
        sel.appendChild(o);
      });
      renderSkillFields();
    } catch (e) { /* handled */ }
  }

  // ── "Source" control (upload new file / existing document / all documents) ────
  const SOURCE_LABELS = {
    upload: "Upload new file", existing: "Existing document", all: "All documents",
  };

  function renderSourceField(wrap, f) {
    const head = document.createElement("label"); head.textContent = "Source";
    wrap.appendChild(head);
    const modes = f.sourceModes || ["upload", "existing"];
    const group = document.createElement("div"); group.className = "chips"; group.style.margin = "2px 0 6px";
    modes.forEach((m, i) => {
      const lab = document.createElement("label");
      lab.style.cssText = "display:inline-flex;align-items:center;gap:5px;margin:0 12px 0 0;color:var(--fg)";
      const r = document.createElement("input");
      r.type = "radio"; r.name = "src_" + f.key; r.value = m; if (i === 0) r.checked = true;
      r.style.width = "auto";
      r.addEventListener("change", () => updateSourceWidgets(f));
      lab.appendChild(r); lab.appendChild(document.createTextNode(SOURCE_LABELS[m] || m));
      group.appendChild(lab);
    });
    wrap.appendChild(group);
    if (modes.indexOf("upload") >= 0) {
      const fileInp = document.createElement("input");
      fileInp.type = "file"; fileInp.id = "sf_" + f.key + "_file";
      if (f.uploadAccept) fileInp.accept = f.uploadAccept;
      wrap.appendChild(fileInp);
    }
    if (modes.indexOf("existing") >= 0) {
      const docSel = document.createElement("select"); docSel.id = "sf_" + f.key + "_doc";
      wrap.appendChild(docSel);
      fillDocSelect(docSel, false, null, f.docTypes);   // f.docTypes restricts to OCR-capable for OCR
    }
    updateSourceWidgets(f);
  }

  function currentSourceMode(key) {
    const r = document.querySelector('input[name="src_' + key + '"]:checked');
    return r ? r.value : null;
  }

  function updateSourceWidgets(f) {
    const mode = currentSourceMode(f.key);
    const fileInp = $("sf_" + f.key + "_file"), docSel = $("sf_" + f.key + "_doc");
    if (fileInp) fileInp.style.display = mode === "upload" ? "block" : "none";
    if (docSel) docSel.style.display = mode === "existing" ? "block" : "none";
  }

  // Resolve a "source" control to a document scope: All → null (whole library);
  // Existing → the selected file_id; Upload → upload + ingest (OCR for image/PDF,
  // text-extract otherwise) so the new document is indexed and queryable, then
  // scope to it. (An uploaded doc becomes a selected doc immediately after ingest.)
  async function resolveSource(f) {
    const mode = currentSourceMode(f.key);
    if (mode === "all") return { file_id: null };
    if (mode === "existing") {
      const sel = $("sf_" + f.key + "_doc");
      const fid = sel ? (sel.value || "").trim() : "";
      return fid ? { file_id: fid } : { error: "Pick a document." };
    }
    const inp = $("sf_" + f.key + "_file");
    const file = inp && inp.files && inp.files[0];
    if (!file) return { error: "Choose a file to upload." };
    $("skill-status").textContent = "Uploading & indexing…";
    const up = await apiUpload(file);
    if (!up || !up.success) return { error: "Upload failed." };
    const fid = up.file_id;
    if (up.is_image || up.is_pdf) {
      let engine = "glmocr";
      try { engine = (await resolveOcrEngine("")).engine; } catch (e) { /* default */ }
      const { body } = await api("/api/ocr/all", {
        method: "POST", body: JSON.stringify({ file_id: fid, engine }) });
      if (!body || !body.success) return { error: "OCR failed." };
    } else {
      const { body } = await api("/api/read-text", {
        method: "POST", body: JSON.stringify({ file_id: fid }) });
      if (!body || !body.success) return { error: "Text extraction failed." };
    }
    // Wait out the async auto-index so the retrieval that immediately follows this
    // upload actually finds the new document.
    await waitForIndex(fid, 12000);
    await loadDocs(fid);              // surface the new doc in the conversation picker too
    return { file_id: fid };
  }

  // OCR action — a true atomic capability backed by the EXISTING OCR pipeline
  // (/api/ocr/all: persists the canonical 'ocr' artifact + RAG-indexes), so a
  // Run-Action OCR behaves exactly like the normal upload→OCR workflow. A non-image
  // upload can't be OCR'd, so it falls back to text extraction (still indexed).
  async function runOcrAction() {
    const f = (SKILL_FIELDS.ocr || []).find((x) => x.type === "source");
    const mode = currentSourceMode(f.key);
    let fileId = "", fileName = "";
    if (mode === "upload") {
      const inp = $("sf_" + f.key + "_file");
      const file = inp && inp.files && inp.files[0];
      if (!file) { $("skill-status").innerHTML = '<span class="bad">Choose a file to OCR.</span>'; return; }
      $("skill-status").textContent = "Uploading…";
      const up = await apiUpload(file);
      if (!up || !up.success) { $("skill-status").innerHTML = '<span class="bad">Upload failed.</span>'; return; }
      // OCR is for images/PDFs only — reject anything else (no silent text fallback).
      if (!(up.is_image || up.is_pdf)) {
        $("skill-status").innerHTML = '<span class="bad">OCR supports images and PDFs only. For DOCX/TXT use Summarize, Translate, or Ask My Documents.</span>';
        return;
      }
      fileId = up.file_id; fileName = up.filename || file.name;
    } else {
      const opt = $("sf_" + f.key + "_doc") && $("sf_" + f.key + "_doc").selectedOptions[0];
      fileId = opt ? (opt.value || "").trim() : "";
      fileName = opt ? opt.textContent : "";
      if (!fileId) { $("skill-status").innerHTML = '<span class="bad">Pick an image or PDF document.</span>'; return; }
      // Defense in depth: the picker is filtered to OCR-capable docs, but re-validate.
      const dtype = (opt.dataset.type || "").toLowerCase();
      if (dtype && OCR_FILE_TYPES.indexOf(dtype) < 0) {
        $("skill-status").innerHTML = '<span class="bad">That document isn’t an image or PDF — OCR can’t run on it.</span>';
        return;
      }
    }
    let engine = ($("sf_engine") && $("sf_engine").value || "").trim();
    if (!engine) { try { engine = (await resolveOcrEngine("")).engine; } catch (e) { engine = "glmocr"; } }

    $("skill-status").textContent = "Running OCR… (this can take a moment)";
    const { body } = await api("/api/ocr/all", {
      method: "POST", body: JSON.stringify({ file_id: fileId, engine }) });
    if (!body || !body.success) {
      $("skill-status").innerHTML = '<span class="bad">OCR failed: ' + ((body && body.error) || "") + "</span>"; return;
    }
    $("skill-status").innerHTML = '<span class="ok">ok</span>';
    renderResults($("skill-results"), [{ module: "ocr", route: "#ocr/" + fileId, label: "OCR Result · " + fileName }]);
    $("skill-out").style.display = "none";
    loadDocs(fileId);                // the new/updated doc is now in the agent picker
  }

  // ── Chat entry points ────────────────────────────────────────────────────────
  // These open the EXISTING Chat experience (no second chat system here). Each
  // launch creates a fresh server-side conversation and deep-links the SPA to
  // /#chat/<id>, which restores the scope + mode and starts with empty history.
  function openChatConversation(convId) {
    window.location.href = "/#chat/" + encodeURIComponent(convId);
  }

  async function startChatSession(payload, opening) {
    $("skill-status").textContent = opening;
    const { body } = await api("/api/chat/conversations", {
      method: "POST", body: JSON.stringify(payload) });
    if (!body || !body.success || !body.conversation) {
      $("skill-status").innerHTML = '<span class="bad">Could not start chat.</span>'; return false;
    }
    openChatConversation(body.conversation.id);
    return true;
  }

  // General Chat — standard LLM conversation, no document retrieval (mode=general).
  async function startGeneralChat() {
    await startChatSession({ mode: "general" }, "Opening General Chat…");
  }

  // Document Chat — scoped to EXACTLY ONE document. Upload a new file (OCR/extract +
  // index, waiting until ready) or reuse an existing one (re-using its OCR; running
  // OCR only if it has none). A fresh conversation per launch resets history, so
  // switching documents never contaminates a prior session.
  async function startDocumentChat() {
    const f = (SKILL_FIELDS.document_chat || []).find((x) => x.type === "source");
    const mode = currentSourceMode(f.key);
    let fileId = "";
    if (mode === "upload") {
      const r = await resolveSource(f);        // upload → OCR/extract → wait for index
      if (r.error) { $("skill-status").innerHTML = '<span class="bad">' + r.error + "</span>"; return; }
      fileId = r.file_id;
    } else {
      const opt = $("sf_" + f.key + "_doc") && $("sf_" + f.key + "_doc").selectedOptions[0];
      fileId = opt ? (opt.value || "").trim() : "";
      if (!fileId) { $("skill-status").innerHTML = '<span class="bad">Pick a document.</span>'; return; }
      $("skill-status").textContent = "Preparing document…";
      const { body } = await api("/api/agent/ensure-indexed", {
        method: "POST", body: JSON.stringify({ file_id: fileId }) });
      if (!body || !body.success) {
        $("skill-status").innerHTML = '<span class="bad">Could not prepare the document.</span>'; return;
      }
      if (!body.indexed) {
        if (!body.needs_ocr) {
          $("skill-status").innerHTML = '<span class="bad">That document has no readable text yet.</span>'; return;
        }
        // No OCR/text yet — produce it now, then wait out the async index.
        const dtype = ((opt && opt.dataset.type) || "").toLowerCase();
        if (OCR_FILE_TYPES.indexOf(dtype) >= 0) {
          $("skill-status").textContent = "Running OCR… (this can take a moment)";
          let engine = "glmocr";
          try { engine = (await resolveOcrEngine("")).engine; } catch (e) { /* default */ }
          const { body: ob } = await api("/api/ocr/all", {
            method: "POST", body: JSON.stringify({ file_id: fileId, engine }) });
          if (!ob || !ob.success) { $("skill-status").innerHTML = '<span class="bad">OCR failed.</span>'; return; }
        } else {
          $("skill-status").textContent = "Extracting text…";
          const { body: tb } = await api("/api/read-text", {
            method: "POST", body: JSON.stringify({ file_id: fileId }) });
          if (!tb || !tb.success) { $("skill-status").innerHTML = '<span class="bad">Text extraction failed.</span>'; return; }
        }
        await waitForIndex(fileId, 12000);
      }
    }
    await startChatSession({ mode: "doc_current", file_id: fileId }, "Opening Document Chat…");
  }

  async function runSkill() {
    const name = $("skill").value;
    $("run-skill").disabled = true;
    $("skill-status").textContent = "Running…";
    $("skill-out").style.display = "none";
    $("skill-results").innerHTML = "";
    try {
      if (name === "ocr") { await runOcrAction(); return; }
      if (name === "general_chat") { await startGeneralChat(); return; }
      if (name === "document_chat") { await startDocumentChat(); return; }

      const fields = SKILL_FIELDS[name] || [];
      const args = {};
      for (const f of fields) {
        if (f.type === "source") {
          const r = await resolveSource(f);
          if (r.error) { $("skill-status").innerHTML = '<span class="bad">' + r.error + "</span>"; return; }
          if (r.file_id) args.file_id = r.file_id;     // document scope (e.g. research)
          continue;
        }
        const el = $("sf_" + f.key);
        const v = el ? (el.value || "").trim() : "";
        if (v) args[f.key] = v;
      }
      const { body } = await api("/api/agent/skill/" + encodeURIComponent(name), {
        method: "POST", body: JSON.stringify({ args }),
      });
      $("skill-status").innerHTML = body.success
        ? '<span class="ok">ok</span>'
        : '<span class="bad">error: ' + (body.error || "failed") + "</span>";
      renderResults($("skill-results"), body.results || []);
      $("skill-out").textContent = JSON.stringify(body.data || body, null, 2);
      $("skill-out").style.display = "block";
    } catch (e) {
      $("skill-status").textContent = "Request failed.";
    } finally {
      $("run-skill").disabled = false;
    }
  }

  // ── LLM / agent availability (shown on load) ─────────────────────────────────
  // One read-only call to /api/llm/status so provider, model and enabled state
  // are visible BEFORE the first run — a disabled agent or missing model is a
  // labelled state, not a surprise failure. Built with textContent (no HTML
  // injection from config-derived strings). Best-effort: on any error the line
  // stays empty and the page behaves as before.
  let llmStatus = null;                    // latest /api/llm/status payload

  // "Open Settings" link appended to actionable status lines (UI item 3) —
  // Settings lives in the main SPA at /#settings.
  function settingsLink() {
    const a = document.createElement("a");
    a.href = "/#settings";
    a.textContent = "Open Settings →";
    a.style.cssText = "color:var(--accent);margin-left:6px";
    return a;
  }

  async function loadLlmStatus() {
    const el = $("llm-status");
    if (!el) return;
    try {
      const { body } = await api("/api/llm/status");
      if (!body || !body.success) return;
      llmStatus = body;
      const enabled = body.enabled || {};
      const local = body.local || {};
      const oc = body.openai_compatible || {};
      let model;
      if (body.provider === "openai_compatible") {
        model = (oc.model || "(model not set)") + " @ " + (oc.base_url || "(no endpoint)");
      } else {
        model = (local.model || "?") + (local.cached === false ? " — not downloaded" : "");
      }
      // Active processing mode (P7): make "Local only" vs cloud visible.
      const mode = body.processing_mode === "local_only"
        ? " · 🔒 Local only (no cloud)" : "";
      if (enabled.agent === false) {
        el.textContent = "⚠ Agent disabled — " +
          (body.setup_hint || "set ENABLE_AGENT=true (and LLM_PROVIDER) in .env.");
        el.appendChild(settingsLink());
        el.classList.add("bad");
        const run = $("run");
        run.disabled = true;
        run.title = "The Agent is disabled on this installation.";
      } else {
        el.textContent = "LLM: " + (body.provider || "?") + " · " + model + mode +
          (body.setup_hint ? " — ⚠ " + body.setup_hint : "");
        if (body.setup_hint) { el.classList.add("bad"); el.appendChild(settingsLink()); }
      }
    } catch (e) { /* status line is optional — never blocks the page */ }
  }

  // ── Tools list ─────────────────────────────────────────────────────────────
  async function loadTools() {
    try {
      const { body } = await api("/api/agent/tools");
      const ul = $("tools"); ul.innerHTML = "";
      (body.tools || []).forEach((t) => {
        const li = document.createElement("li");
        const b = document.createElement("b"); b.textContent = t.name;
        const s = document.createElement("span"); s.textContent = t.description;
        li.appendChild(b); li.appendChild(s); ul.appendChild(li);
      });
    } catch (e) { /* handled */ }
  }

  // ── wire up ────────────────────────────────────────────────────────────────
  $("run").addEventListener("click", runAgent);
  $("run-skill").addEventListener("click", runSkill);
  $("skill").addEventListener("change", renderSkillFields);
  $("new-session").addEventListener("click", newSession);
  $("rename-session").addEventListener("click", renameSession);
  $("delete-session").addEventListener("click", () => deleteSession());
  $("agent-upload").addEventListener("change", onAgentUpload);
  $("agent-doc-refresh").addEventListener("click", () => loadDocs());
  $("agent-doc").addEventListener("change", updateScopeLine);
  // Restore the remembered max-steps preference (non-secret, UI item 7).
  try {
    const savedSteps = parseInt(localStorage.getItem(STEPS_STORE_KEY) || "", 10);
    if (savedSteps >= 1 && savedSteps <= 6) $("steps").value = savedSteps;
  } catch (e) { /* optional */ }
  updateScopeLine();
  // Launch-from-document (Phase 13/14): /agent?file_id=<uuid> pre-scopes the agent to
  // that document (selected by name in the picker; the file_id stays internal).
  let initialFid = "";
  try { initialFid = new URLSearchParams(window.location.search).get("file_id") || ""; } catch (e) { /* no-op */ }
  loadDocs(initialFid);
  setSessionLabel();
  loadSessions();
  loadSkills();
  loadTools();
  loadLlmStatus();
})();
