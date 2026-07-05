/* Sidebar — expanded/collapsed/drawer behavior for the primary navigation.
   The decision logic lives in `Sidebar.logic` (pure, node-testable in
   desktop/tests/ui); `Sidebar.init` wires it to the DOM.
   localStorage stores ONLY the collapsed preference — never secrets. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) { module.exports = factory(); }
  else { root.Sidebar = factory(); }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var COLLAPSE_KEY = 'sd.sidebar.collapsed';
  var DRAWER_MAX_WIDTH = 860; // px — must match the style.css media query

  var logic = {
    COLLAPSE_KEY: COLLAPSE_KEY,
    DRAWER_MAX_WIDTH: DRAWER_MAX_WIDTH,
    initialCollapsed: function (stored) { return stored === '1'; },
    storeValue: function (collapsed) { return collapsed ? '1' : '0'; },
    isDrawer: function (width) { return width <= DRAWER_MAX_WIDTH; },
    /** Roving focus inside the sidebar: next item index for a key press. */
    nextIndex: function (key, current, count) {
      if (count <= 0) { return -1; }
      if (key === 'ArrowDown') { return (current + 1) % count; }
      if (key === 'ArrowUp') { return (current - 1 + count) % count; }
      if (key === 'Home') { return 0; }
      if (key === 'End') { return count - 1; }
      return -1;
    },
  };

  function init(doc, win) {
    doc = doc || document;
    win = win || window;
    var app = doc.getElementById('app');
    var sidebar = doc.getElementById('sidebar');
    var collapseBtn = doc.getElementById('sb-collapse');
    var openBtn = doc.getElementById('sb-open');
    var backdrop = doc.getElementById('sb-backdrop');
    if (!app || !sidebar) { return; }

    var t = function (k, fb) {
      return (win.I18n && win.I18n.t) ? win.I18n.t(k, fb) : fb;
    };

    // ── collapsed preference (persisted; the ONLY thing stored) ────────────
    var collapsed = false;
    try { collapsed = logic.initialCollapsed(win.localStorage.getItem(COLLAPSE_KEY)); }
    catch (e) { /* storage unavailable → session-only */ }

    function items() {
      return Array.prototype.filter.call(
        sidebar.querySelectorAll('.nav-link'),
        function (el) { return el.offsetParent !== null || el === doc.activeElement; });
    }

    function syncTooltips() {
      // Collapsed: labels hidden → expose them as tooltip + aria-label.
      Array.prototype.forEach.call(
        sidebar.querySelectorAll('.nav-link'), function (el) {
          var label = el.querySelector('.sb-label');
          var text = label ? label.textContent.trim() : '';
          if (!text) { return; }
          el.setAttribute('aria-label', text);
          if (collapsed) { el.setAttribute('title', text); }
          else if (!el.hasAttribute('data-i18n-title')) { el.removeAttribute('title'); }
        });
    }

    function applyCollapsed() {
      app.classList.toggle('sb-collapsed', collapsed);
      if (collapseBtn) {
        collapseBtn.setAttribute('aria-pressed', collapsed ? 'true' : 'false');
        var lbl = collapseBtn.querySelector('.sb-label');
        var text = collapsed ? t('sidebar_expand', 'Expand sidebar')
                             : t('sidebar_collapse', 'Collapse sidebar');
        if (lbl) { lbl.textContent = text; }
      }
      syncTooltips();
    }

    if (collapseBtn) {
      collapseBtn.addEventListener('click', function () {
        collapsed = !collapsed;
        try { win.localStorage.setItem(COLLAPSE_KEY, logic.storeValue(collapsed)); }
        catch (e) { /* session-only */ }
        applyCollapsed();
      });
    }

    // ── drawer mode (narrow windows) ────────────────────────────────────────
    var lastFocus = null;
    function drawerOpen() { return app.classList.contains('sb-drawer-open'); }
    function openDrawer() {
      lastFocus = doc.activeElement;
      app.classList.add('sb-drawer-open');
      if (backdrop) { backdrop.hidden = false; }
      if (openBtn) { openBtn.setAttribute('aria-expanded', 'true'); }
      var first = sidebar.querySelector('.nav-link');
      if (first) { first.focus(); }
    }
    function closeDrawer() {
      if (!drawerOpen()) { return; }
      app.classList.remove('sb-drawer-open');
      if (backdrop) { backdrop.hidden = true; }
      if (openBtn) { openBtn.setAttribute('aria-expanded', 'false'); }
      if (lastFocus && lastFocus.focus) { lastFocus.focus(); }
    }
    if (openBtn) {
      openBtn.addEventListener('click', function () {
        if (drawerOpen()) { closeDrawer(); } else { openDrawer(); }
      });
    }
    if (backdrop) { backdrop.addEventListener('click', closeDrawer); }
    doc.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') { closeDrawer(); }
    });
    // Navigating closes the drawer (the content is now the focus).
    sidebar.addEventListener('click', function (ev) {
      if (ev.target.closest && ev.target.closest('.nav-link[data-view], a.nav-link')) {
        closeDrawer();
      }
    });

    // ── keyboard navigation inside the sidebar ──────────────────────────────
    sidebar.addEventListener('keydown', function (ev) {
      var list = items();
      var idx = list.indexOf(doc.activeElement);
      if (idx === -1) { return; }
      var next = logic.nextIndex(ev.key, idx, list.length);
      if (next !== -1) {
        ev.preventDefault();
        list[next].focus();
      }
    });

    // Tooltips/labels follow language switches.
    doc.addEventListener('sd-lang', function () { applyCollapsed(); });

    applyCollapsed();
  }

  // Browser auto-init; node (tests) just imports the pure logic.
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () { init(); });
    } else {
      init();
    }
  }

  return { logic: logic, init: init };
}));
