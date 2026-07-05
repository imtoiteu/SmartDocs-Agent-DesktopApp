// Bundled launcher page: startup splash + backend runtime settings.
//
// The splash hooks are driven by the Rust shell via webview.eval(). The
// runtime panel talks to the shell through Tauri IPC (window.__TAURI__) —
// which only works on this bundled origin; web content (local backend pages
// or a remote server) can never call these commands (Tauri ACL).
//
// No network access from this page, and no secrets: the launch token never
// reaches this page's code.

(function () {
  "use strict";

  var invoke = window.__TAURI__ && window.__TAURI__.core && window.__TAURI__.core.invoke;
  var $ = function (id) { return document.getElementById(id); };

  // ── splash hooks (Rust-driven) ─────────────────────────────────────────────
  window.__splashStatus = function (text) {
    var el = $("status");
    if (el) { el.classList.remove("error"); el.textContent = text; }
  };
  window.__splashError = function (text) {
    var el = $("status"), sp = $("spinner");
    if (sp) { sp.style.display = "none"; }
    if (el) { el.classList.add("error"); el.textContent = text; }
    var btn = $("open-runtime");
    if (btn) { btn.style.display = "inline-block"; }
  };

  // ── view switching ─────────────────────────────────────────────────────────
  function showRuntime() {
    $("view-splash").style.display = "none";
    $("view-runtime").style.display = "block";
    loadState();
    var first = document.querySelector('input[name="rt-mode"]:checked') ||
                document.querySelector('input[name="rt-mode"]');
    if (first) { first.focus(); }
  }
  function showSplash() {
    $("view-runtime").style.display = "none";
    $("view-splash").style.display = "block";
  }
  window.addEventListener("hashchange", function () {
    if (location.hash === "#runtime") { showRuntime(); }
  });
  $("open-runtime").addEventListener("click", showRuntime);

  // ── runtime settings panel ─────────────────────────────────────────────────
  var platform = { mlx_supported: false, windows: false };

  function mode() {
    var el = document.querySelector('input[name="rt-mode"]:checked');
    return el ? el.value : "bundled";
  }
  function syncSubsections() {
    $("rt-external-sub").classList.toggle("on", mode() === "external");
    $("rt-remote-sub").classList.toggle("on", mode() === "remote");
  }
  Array.prototype.forEach.call(
    document.querySelectorAll('input[name="rt-mode"]'),
    function (r) { r.addEventListener("change", syncSubsections); });

  function statusLabel(s) {
    if (s === "running") return "running (local backend)";
    if (s === "remote") return "connected to a remote server";
    if (s === "starting") return "starting…";
    if (s === "stopped") return "stopped";
    return s; // idle / error: …
  }

  function loadState() {
    if (!invoke) {
      $("rt-status").textContent =
        "Shell bridge unavailable — runtime settings need the desktop shell.";
      $("rt-status").className = "state-bad";
      return;
    }
    invoke("runtime_get_state").then(function (st) {
      platform = st.platform || platform;
      var cfg = st.config || {};
      var radio = document.querySelector(
        'input[name="rt-mode"][value="' + (cfg.mode || "bundled") + '"]');
      if (radio) { radio.checked = true; }
      $("rt-path").value = cfg.external_path || "";
      $("rt-url").value = cfg.remote_url || "";
      $("rt-glm").checked = cfg.glm_enabled !== false;
      $("rt-glm").disabled = !platform.mlx_supported;
      $("rt-glm-hint").textContent = platform.mlx_supported
        ? "" : "(Apple Silicon macOS only — not available on this machine)";
      $("rt-current").textContent =
        "Current: " + (st.active_mode || cfg.mode || "bundled") +
        " — " + statusLabel(st.status || "idle");
      syncSubsections();
    }).catch(function (e) {
      $("rt-status").textContent = "Could not read runtime state: " + e;
      $("rt-status").className = "state-bad";
    });
  }

  $("rt-pick").addEventListener("click", function () {
    if (!invoke) { return; }
    invoke("runtime_pick_folder").then(function (p) {
      if (p) { $("rt-path").value = p; validatePath(); }
    }).catch(function () { /* user cancelled */ });
  });

  function renderReport(rep) {
    var ul = $("rt-report");
    ul.textContent = "";
    (rep.components || []).forEach(function (c) {
      var li = document.createElement("li");
      li.className = "st-" + c.status + (c.required ? "" : " opt");
      li.textContent = c.name + (c.detail ? " — " + c.detail : "");
      ul.appendChild(li);
    });
    var head = document.createElement("li");
    head.style.fontWeight = "600";
    head.className = rep.ok ? "st-ok" : "st-missing";
    head.textContent = rep.ok
      ? "Usable SmartDocs runtime."
      : "Not usable yet — fix the missing required components above.";
    ul.appendChild(head);
  }

  function validatePath() {
    var p = $("rt-path").value.trim();
    if (!invoke || !p) { return; }
    invoke("runtime_validate", { path: p }).then(renderReport)
      .catch(function (e) {
        $("rt-status").textContent = "Validation failed: " + e;
        $("rt-status").className = "state-bad";
      });
  }
  $("rt-validate").addEventListener("click", validatePath);

  $("rt-test").addEventListener("click", function () {
    var out = $("rt-remote-result");
    out.textContent = "Testing…";
    out.className = "";
    if (!invoke) { return; }
    invoke("runtime_test_remote", { url: $("rt-url").value.trim() })
      .then(function (r) {
        var good = r.state === "ok" || r.state === "auth_required";
        out.textContent = r.message || r.state;
        out.className = good ? "state-ok"
          : (r.state === "tls_error" ? "state-warn" : "state-bad");
      })
      .catch(function (e) {
        out.textContent = "Test failed: " + e;
        out.className = "state-bad";
      });
  });

  $("rt-form").addEventListener("submit", function (ev) {
    ev.preventDefault();
    if (!invoke) { return; }
    var st = $("rt-status");
    st.textContent = "Applying…";
    st.className = "";
    var cfg = {
      mode: mode(),
      external_path: $("rt-path").value.trim() || null,
      remote_url: $("rt-url").value.trim() || null,
      glm_enabled: $("rt-glm").checked,
    };
    invoke("runtime_apply", { config: cfg }).then(function () {
      st.textContent = "Restarting the backend…";
      st.className = "state-ok";
      // The shell navigates back to the splash and then into the app;
      // nothing else to do here.
      showSplash();
      var sp = $("spinner");
      if (sp) { sp.style.display = ""; }
      window.__splashStatus("Restarting backend…");
    }).catch(function (e) {
      st.textContent = String(e);
      st.className = "state-bad";
    });
  });

  $("rt-cancel").addEventListener("click", function () {
    if (!invoke) { return; }
    invoke("runtime_resume").catch(function () {
      $("rt-status").textContent =
        "No backend is running — apply a runtime configuration first.";
      $("rt-status").className = "state-warn";
    });
  });

  // Escape returns to the app (same as Back) when the panel is open.
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" &&
        $("view-runtime").style.display === "block" && invoke) {
      invoke("runtime_resume").catch(function () { /* stay on the panel */ });
    }
  });

  if (location.hash === "#runtime") { showRuntime(); }
})();
