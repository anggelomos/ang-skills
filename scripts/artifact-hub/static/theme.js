// Light / dark / system for the hub's own pages. Loaded in <head> so a saved choice applies before the first paint.
(function () {
  const root = document.documentElement, KEY = "artifact-hub-theme";
  const saved = () => { try { return localStorage.getItem(KEY); } catch (e) { return null; } };
  function apply(t) {
    if (t !== "light" && t !== "dark") t = "system";
    if (t === "system") root.removeAttribute("data-theme"); else root.dataset.theme = t;
    document.querySelectorAll(".theme button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.theme === t)));
    return t;
  }
  apply(saved());
  document.addEventListener("DOMContentLoaded", () => {
    apply(saved());
    document.querySelectorAll(".theme button").forEach((b) => b.addEventListener("click", () => {
      const t = apply(b.dataset.theme);
      try { localStorage.setItem(KEY, t); } catch (e) {}
    }));
  });
  window.addEventListener("storage", (e) => { if (e.key === KEY) apply(e.newValue); });
})();
