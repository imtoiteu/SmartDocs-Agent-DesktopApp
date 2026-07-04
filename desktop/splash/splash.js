// Splash page hooks — the Rust shell drives these via webview.eval().
// No network access, no secrets: the token never reaches this page's code;
// it is injected as an initialization script and only used by the patched
// fetch/XHR on the application's own origins.
window.__splashStatus = function (text) {
  var el = document.getElementById("status");
  if (el) { el.classList.remove("error"); el.textContent = text; }
};
window.__splashError = function (text) {
  var el = document.getElementById("status");
  var sp = document.getElementById("spinner");
  if (sp) { sp.style.display = "none"; }
  if (el) { el.classList.add("error"); el.textContent = text; }
};
