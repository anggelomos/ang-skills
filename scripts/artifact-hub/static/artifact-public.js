// artifact.js for public artifacts (/p/...): the same API, but there's no one to send to. The page gets the
// agent's data and can render it; save and submit fail, and forms can't submit at all (the sandbox has no forms).
(function () {
  if (window.Artifact) return;
  const state = Object.freeze({ status: "view", title: null, data: /*DATA*/null, draft: null, response: null, readOnly: true });
  const refuse = () => Promise.reject(new Error("public artifacts can't send anything back"));
  window.Artifact = Object.freeze({
    hub: true,
    public: true,
    ready: Promise.resolve(state),
    save: refuse,
    submit: refuse,
    onUpdate(fn) { fn(state); return () => {}; },
  });
})();
