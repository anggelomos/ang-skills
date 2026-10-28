// artifact.js: the SDK artifact-hub injects into every private artifact. The artifact runs in a sandboxed
// frame with an opaque origin and no network, so it talks to the hub only through the page around it
// (the shell), over a MessageChannel the shell hands over once the frame proves it knows this load's token.
//
//   Artifact.ready              Promise of the state: {status, title, data, draft, response, readOnly}
//   Artifact.save(value)        keeps a draft on the hub. Not a response: the agent isn't told
//   Artifact.submit(value)      sends a response to the agent: `artifact-hub wait` returns it
//   Artifact.onUpdate(fn)       fn(state) now and on every change: new data from the agent, a status change,
//                               a draft saved on another device. Returns a function that unsubscribes
//
// While a phone keyboard is up it covers the bottom of the frame (the frame isn't resized). The covered parts are
// the CSS variables --artifact-inset-top and --artifact-inset-bottom on <html>, 0px otherwise, and every change
// fires an "artifactviewport" event on window with {top, bottom} in its detail.
//
// Plain <form>s need no code: a submit is sent as {form, values} JSON, and what's typed is kept as a draft
// and filled back in on the next load. Mark a form data-artifact="off" to leave it alone.
(function () {
  if (window.Artifact) return;
  const token = location.hash.slice(1);
  let port = null, state = null, nextId = 1;
  const pending = new Map(), listeners = new Set();
  let resolveReady;
  const ready = new Promise((r) => (resolveReady = r));

  const view = () => ({
    status: state.status, title: state.title, data: state.data, response: state.response,
    draft: state.drafts ? state.drafts.default === undefined ? null : state.drafts.default : null,
    readOnly: state.status === "done" || !!state.expired,
  });
  const emit = () => listeners.forEach((fn) => { try { fn(view()); } catch (e) { console.error(e); } });

  function call(msg) {
    return ready.then(() => new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      port.postMessage({ ...msg, id });
    }));
  }

  function onPort(e) {
    const m = e.data || {};
    if (m.type === "state") {
      const first = !state;
      state = m.state;
      if (first) {
        resolveReady(view());
        restoreForms();
      }
      emit();
    } else if (m.type === "viewport") {
      const top = Math.max(0, Number(m.top) || 0), bottom = Math.max(0, Number(m.bottom) || 0);
      document.documentElement.style.setProperty("--artifact-inset-top", top + "px");
      document.documentElement.style.setProperty("--artifact-inset-bottom", bottom + "px");
      window.dispatchEvent(new CustomEvent("artifactviewport", { detail: { top, bottom } }));
    } else if (m.type === "result" && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      m.ok ? p.resolve(m.value) : p.reject(new Error(m.error || "the hub refused it"));
    }
  }

  window.addEventListener("message", (e) => {
    if (e.source !== window.parent || port || !e.data || e.data.artifactHub !== "port" || !e.ports[0]) return;
    port = e.ports[0];
    port.onmessage = onPort;
  });
  window.parent.postMessage({ artifactHub: "hello", token }, "*");

  // ---------- forms ----------

  const managed = (f) => f.dataset.artifact !== "off";
  const formKey = (f) => f.getAttribute("name") || f.id || "form-" + [...document.forms].indexOf(f);

  function values(form, submitter) {
    let fd;
    try { fd = new FormData(form, submitter || undefined); } catch (e) { fd = new FormData(form); }
    const out = {};
    for (const [k, v] of fd.entries()) {
      const val = typeof v === "string" ? v : v.name; // files: the hub only takes JSON, so just the name
      if (!(k in out)) out[k] = val;
      else out[k] = [].concat(out[k], val);
    }
    return out;
  }

  function fill(form, vals) {
    for (const el of form.elements) {
      if (!el.name || !(el.name in vals) || /^(submit|button|reset|file)$/.test(el.type)) continue;
      const v = vals[el.name], list = [].concat(v).map(String);
      if (el.type === "checkbox" || el.type === "radio") el.checked = list.includes(el.value);
      else if (el.tagName === "SELECT" && el.multiple) [...el.options].forEach((o) => (o.selected = list.includes(o.value)));
      else el.value = Array.isArray(v) ? String(v[0] ?? "") : String(v);
    }
  }

  function restoreForms() {
    if (document.readyState === "loading") return document.addEventListener("DOMContentLoaded", restoreForms, { once: true });
    const saved = (state.drafts && state.drafts.forms) || {};
    for (const f of document.forms) if (managed(f) && saved[formKey(f)]) fill(f, saved[formKey(f)]);
  }

  let timer = null;
  function saveForms() {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const all = {};
      for (const f of document.forms) if (managed(f)) all[formKey(f)] = values(f);
      call({ type: "save", slot: "forms", value: all }).catch(() => {});
    }, 500);
  }
  document.addEventListener("input", (e) => e.target.form && managed(e.target.form) && saveForms(), true);
  document.addEventListener("change", (e) => e.target.form && managed(e.target.form) && saveForms(), true);

  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (!managed(form)) return;
    e.preventDefault();
    const value = { form: form.getAttribute("name") || form.id || null, values: values(form, e.submitter) };
    form.dataset.artifactState = "sending";
    call({ type: "submit", value, via: "form" }).then(
      () => {
        form.dataset.artifactState = "sent";
        form.dispatchEvent(new CustomEvent("artifact:submitted", { bubbles: true, detail: value }));
      },
      (err) => {
        form.dataset.artifactState = "error";
        form.dispatchEvent(new CustomEvent("artifact:error", { bubbles: true, detail: err.message }));
      });
  });

  const json = (v) => {
    if (v === undefined) throw new Error("nothing to send");
    return JSON.parse(JSON.stringify(v));
  };
  window.Artifact = Object.freeze({
    hub: true,
    public: false,
    ready,
    save: (value) => call({ type: "save", slot: "default", value: json(value) }),
    submit: (value) => call({ type: "submit", value: json(value), via: "sdk" }),
    onUpdate(fn) {
      listeners.add(fn);
      if (state) fn(view());
      return () => listeners.delete(fn);
    },
  });
})();
