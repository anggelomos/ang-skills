// The page around a private artifact. The artifact itself runs in a sandboxed frame with an opaque origin
// and no network; this page is the only thing that talks to the hub for it. It hands the frame a
// MessagePort once the frame says hello with this load's token, pushes the hub's state down that port,
// and carries the frame's saves and submits up to the hub.
(function () {
  const $ = (s) => document.querySelector(s);
  const frame = $("#artifact");
  const LABEL = { awaiting: "Awaiting your response", responded: "Response sent", working: "Agent working",
                  view: "Ready to view", done: "Done" };
  const random = () => [...crypto.getRandomValues(new Uint8Array(18))].map((b) => b.toString(16).padStart(2, "0")).join("");
  const clientId = random();
  let token = null, port = null, state = null, loadedHtml = null, lastSent = null;

  const toastBox = $("#toast");
  let toastTimer;
  function toast(text, kind) {
    clearTimeout(toastTimer);
    toastBox.textContent = text;
    toastBox.className = "toast is-on" + (kind ? " is-" + kind : "");
    toastTimer = setTimeout(() => (toastBox.className = "toast"), kind === "error" ? 7000 : 3500);
  }

  // what the frame sees: no versions, no device IDs
  const forFrame = (s) => ({ status: s.status, title: s.title, data: s.data, drafts: s.drafts, response: s.response,
                             expired: s.expired });

  function load() {
    token = random();
    if (port) port.close();
    port = null;
    loadedHtml = state.htmlVersion;
    frame.src = "frame?v=" + encodeURIComponent(state.htmlVersion) + "#" + token;
  }

  window.addEventListener("message", (e) => {
    const m = e.data;
    if (e.source !== frame.contentWindow || !m || m.artifactHub !== "hello" || !token || m.token !== token) return;
    // a frame that reloads itself says hello again with the same token: give it a fresh port
    if (port) port.close();
    const ch = new MessageChannel();
    port = ch.port1;
    port.onmessage = fromFrame;
    e.source.postMessage({ artifactHub: "port" }, "*", [ch.port2]);
    lastSent = forFrame(state);
    port.postMessage({ type: "state", state: lastSent });
  });

  async function post(path, body) {
    let r;
    try {
      r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    } catch (e) {
      throw new Error("couldn't reach the hub");
    }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || r.statusText);
    return data;
  }

  async function fromFrame(e) {
    const m = e.data || {}, reply = (ok, extra) => port && port.postMessage({ type: "result", id: m.id, ok, ...extra });
    try {
      if (m.type === "save") {
        await post("api/save", { slot: m.slot, value: m.value, client: clientId });
      } else if (m.type === "submit") {
        await post("api/submit", { value: m.value, via: m.via === "form" ? "form" : "sdk" });
        toast("Sent to the agent.", "ok");
      } else {
        return reply(false, { error: "unknown request" });
      }
      reply(true);
    } catch (err) {
      if (m.type === "submit") toast("Couldn't send: " + err.message, "error");
      reply(false, { error: err.message });
    }
  }

  function paint(s) {
    document.title = s.title + " · Artifact hub";
    $("#title").textContent = s.title;
    $("#status").textContent = s.expired ? "Expired" : LABEL[s.status] || s.status;
    $("#status").dataset.status = s.status;
    $("#expiry").textContent = s.expiryText;
    document.body.classList.toggle("is-expired", !!s.expired);
    const icon = s.status === "awaiting" ? "favicon" : "favicon-cooked";
    for (const link of document.querySelectorAll('link[rel="icon"]')) {
      const href = "/static/" + icon + "." + (link.type === "image/svg+xml" ? "svg" : "png");
      if (link.getAttribute("href") !== href) link.setAttribute("href", href);
    }
  }

  function apply(s) {
    state = s;
    paint(s);
    if (s.expired) {
      frame.removeAttribute("src");
      if (port) port.close();
      port = token = loadedHtml = null; // brought back with a new expiry: load it again
      return;
    }
    if (s.htmlVersion !== loadedHtml) return load();
    if (!port) return;
    const next = forFrame(s);
    // a draft this page just saved comes back as a change; the frame already has it
    const same = (k) => JSON.stringify(next[k]) === JSON.stringify(lastSent[k]);
    if (["status", "title", "data", "response", "expired"].every(same) && (same("drafts") || s.draftClient === clientId)) {
      lastSent = next;
      return;
    }
    lastSent = next;
    port.postMessage({ type: "state", state: next });
  }

  let lost = false;
  function connect() {
    const events = new EventSource("events");
    events.onmessage = (e) => {
      if (lost) toastBox.className = "toast";
      lost = false;
      apply(JSON.parse(e.data));
    };
    events.addEventListener("gone", () => {
      events.close();
      location.reload();
    });
    // EventSource gives up on an error reply, like the 502 a tunnel sends while the hub restarts
    events.onerror = () => {
      lost = true;
      toast("Lost the connection to the hub. Reconnecting…", "error");
      if (events.readyState === EventSource.CLOSED) setTimeout(connect, 3000);
    };
  }
  connect();
})();
