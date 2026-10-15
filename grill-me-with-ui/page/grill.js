// Round behavior: answer state, hover-to-focus, and keyboard shortcuts. The page supplies
// `render(question, index)` returning markup with: [data-q="<id>"] on the question root,
// [data-chip="<n>"] buttons, and one [data-text] textarea. Buttons anywhere with
// [data-action="copy"|"done"|"jump"] are wired automatically.
(function () {
  const esc = (s) =>
    String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  // `code`, **bold**, *italic* and [links](https://…)
  const inline = (s) =>
    String(s)
      .split(/(`[^`]+`)/)
      .map((part, i) =>
        i % 2
          ? `<code>${esc(part.slice(1, -1))}</code>`
          : esc(part)
              .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
              .replace(/\*(.+?)\*/g, "<em>$1</em>")
              .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      )
      .join("");

  // just enough markdown for question bodies: paragraphs, lists, code blocks, headings as bold lines
  function md(src) {
    const out = [];
    let para = [], list = null, code = null;
    const flushPara = () => {
      if (para.length) out.push(`<p>${inline(para.join(" "))}</p>`);
      para = [];
    };
    const flushList = () => {
      if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`);
      list = null;
    };
    for (const line of String(src).split(/\r?\n/)) {
      if (code) {
        if (/^\s*```/.test(line)) {
          out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
          code = null;
        } else code.push(line);
        continue;
      }
      if (/^\s*```/.test(line)) {
        flushPara(); flushList();
        code = [];
        continue;
      }
      const item = line.match(/^\s*([-*+]|\d+[.)])\s+(.*)$/);
      const heading = line.match(/^\s*#{1,6}\s+(.*)$/);
      if (item) {
        flushPara();
        const tag = /\d/.test(item[1]) ? "ol" : "ul";
        if (list && list.tag !== tag) flushList();
        list = list || { tag, items: [] };
        list.items.push(item[2]);
      } else if (heading) {
        flushPara(); flushList();
        out.push(`<p><strong>${inline(heading[1])}</strong></p>`);
      } else if (!line.trim()) {
        flushPara(); flushList();
      } else if (list) {
        list.items[list.items.length - 1] += " " + line.trim();
      } else para.push(line.trim());
    }
    if (code) out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
    flushPara(); flushList();
    return out.join("");
  }

  const blank = () => ({ choice: null, text: "" });

  // the same lines `grill.py wait` prints
  function answerText(q, a) {
    const text = a.text.trim();
    const parts = [];
    if (a.choice !== null) parts.push(text ? q.choices[a.choice].replace(/\.$/, "") : q.choices[a.choice]);
    if (text) parts.push(parts.length ? `Note: ${text}` : text);
    return parts.join(". ") || "(skipped)";
  }

  // Mounts one round. Call `destroy()` before mounting the next one.
  function mount({ root, questions, render, onChange, onAnswer, onDone, onPick, scrollToCard, enterAddsNewline }) {
    const qs = questions;
    const ac = new AbortController();
    const on = (el, type, fn, opts) => el.addEventListener(type, fn, { ...opts, signal: ac.signal });
    const state = Object.fromEntries(
      qs.map((q) => [q.id, q.answer ? { choice: q.answer.choice, text: q.answer.text || "" } : blank()])
    );
    root.innerHTML = qs.map((q, i) => render(q, i)).join("");
    const cards = qs.map((q) => root.querySelector(`[data-q="${q.id}"]`));
    const inputs = cards.map((c) => c.querySelector("[data-text]"));
    inputs.forEach((t, i) => (t.value = state[qs[i].id].text));
    let current = 0, closed = false;

    const isAnswered = (id) => state[id].choice !== null || state[id].text.trim() !== "";

    function sync() {
      cards.forEach((el, i) => {
        const id = qs[i].id;
        el.classList.toggle("is-answered", isAnswered(id));
        el.classList.toggle("is-current", i === current);
        el.querySelectorAll("[data-chip]").forEach((b) =>
          b.setAttribute("aria-pressed", String(state[id].choice === Number(b.dataset.chip)))
        );
      });
      onChange &&
        onChange({ answered: qs.filter((q) => isAnswered(q.id)).length, total: qs.length, current, questions: qs, isAnswered });
    }

    // `focus: false` moves without focusing the input, so touch keyboards stay closed.
    // `scroll: false` leaves scrolling to the caller.
    function setCurrent(i, { focus = true, scroll = true } = {}) {
      current = (i + qs.length) % qs.length;
      if (focus && !closed) inputs[current].focus({ preventScroll: true });
      if (scroll && scrollToCard) scrollToCard(cards[current]);
      else if (scroll) cards[current].scrollIntoView({ block: "nearest", behavior: "smooth" });
      sync();
    }

    function pick(i, n) {
      const q = qs[i];
      if (closed || n >= q.choices.length) return;
      state[q.id].choice = state[q.id].choice === n ? null : n;
      current = i;
      sync();
      onAnswer && onAnswer(q.id, state[q.id], { now: true });
      onPick && onPick(i, state[q.id].choice);
    }

    function nextUnanswered() {
      for (let k = 1; k <= qs.length; k++) {
        const j = (current + k) % qs.length;
        if (!isAnswered(qs[j].id)) return setCurrent(j);
      }
      setCurrent(current + 1);
    }

    // Scrolling under a still cursor fires mouseenter/mousemove too; only a cursor that actually
    // moved should steal focus, or keyboard navigation would jump to whatever card lands under it.
    let lastPointer = null;
    cards.forEach((el, i) => {
      // pointermove + pointerType skips the fake mouse moves phones send with every tap
      on(el, "pointermove", (e) => {
        if (e.pointerType !== "mouse" || closed) return;
        const moved = !lastPointer || lastPointer[0] !== e.screenX || lastPointer[1] !== e.screenY;
        lastPointer = [e.screenX, e.screenY];
        if (!moved || (current === i && el.contains(document.activeElement))) return;
        if (!el.contains(document.activeElement)) inputs[i].focus({ preventScroll: true });
        current = i;
        sync();
      });
      on(el, "focusin", () => {
        if (current !== i) {
          current = i;
          sync();
        }
      });
      el.querySelectorAll("[data-chip]").forEach((b) => on(b, "click", () => pick(i, Number(b.dataset.chip))));
      on(inputs[i], "input", () => {
        state[qs[i].id].text = inputs[i].value;
        sync();
        onAnswer && onAnswer(qs[i].id, state[qs[i].id], { now: false });
      });
      on(inputs[i], "keydown", (e) => {
        if (enterAddsNewline && enterAddsNewline()) return;
        if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
          e.preventDefault();
          nextUnanswered();
        }
      });
    });

    function copy(btn) {
      const payload = qs.map((q) => `${q.id}: ${answerText(q, state[q.id])}`).join("\n");
      const done = () => {
        btn.dataset.state = "copied";
        setTimeout(() => delete btn.dataset.state, 1600);
      };
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(payload).then(done, done);
      else {
        const ta = document.createElement("textarea");
        ta.value = payload;
        document.body.append(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
        done();
      }
    }

    function submit() {
      if (closed) return;
      onDone && onDone(qs.map((q) => ({ id: q.id, ...state[q.id] })));
    }

    on(document, "keydown", (e) => {
      if (e.altKey && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        setCurrent(current + (e.key === "ArrowDown" ? 1 : -1));
      } else if (e.altKey && /^Digit[1-9]$/.test(e.code)) {
        e.preventDefault();
        pick(current, Number(e.code.slice(5)) - 1);
      } else if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        submit();
      }
    });
    document.querySelectorAll('[data-action="copy"]').forEach((b) => on(b, "click", () => copy(b)));
    document.querySelectorAll('[data-action="done"]').forEach((b) => on(b, "click", submit));
    document.querySelectorAll('[data-action="jump"]').forEach((b) =>
      on(b, "click", () => setCurrent(Number(b.dataset.index)))
    );

    sync();
    return {
      setCurrent,
      // a sent round stays on screen, read-only, until the next one arrives
      close() {
        closed = true;
        inputs.forEach((t) => (t.readOnly = true));
        cards.forEach((c) => c.querySelectorAll("[data-chip]").forEach((b) => (b.disabled = true)));
      },
      reopen() {
        closed = false;
        inputs.forEach((t) => (t.readOnly = false));
        cards.forEach((c) => c.querySelectorAll("[data-chip]").forEach((b) => (b.disabled = false)));
      },
      destroy: () => ac.abort(),
    };
  }

  window.Grill = { mount, esc, inline, md };
})();
