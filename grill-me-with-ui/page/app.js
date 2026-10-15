// The Ember Grate page. It renders only what the server sends from the session files, saves each
// answer as you give it, and swaps in the next round as soon as the agent sends it.
const { md, inline } = Grill;
const root = document.documentElement;
const $ = (s) => document.querySelector(s);
const AGENT = "agent_writing_round", FINISHED = "session_finished";

// one shape, two colorways: plain pink when raw, browned with two sear lines once answered
const raw = pixelSprite(`
  .pppppp.
  pppppppp
  pppppppp
  pppppppp
  pppppppp
  pppppppp
  PPPPPPPP
  .PPPPPP.`, { p: "#f3b2a4", P: "#e3958a" }, { scale: 4 });
const cooked = pixelSprite(`
  .pppppp.
  pppppppp
  PPPPPPPP
  pppppppp
  pppppppp
  PPPPPPPP
  pppppppp
  .pppppp.`, { p: "#a75a30", P: "#6e3517" }, { scale: 4, className: "cooked" });
const arrow = pixelSprite(`
  ..f...
  ..ff..
  fffff.
  ffffff
  fffff.
  ..ff..
  ..f...`, { f: "#dd5f1c" }, { scale: 2, className: "rec-mark", label: "Recommended" });
const check = pixelSprite(`
  ......f
  .....ff
  f...ff.
  ff.ff..
  .fff...
  ..f....`, { f: "#dd5f1c" }, { scale: 4, className: "q-check", label: "Answered" });

// the toggle shows a moon in light mode and a sun in dark mode. config.json sets the default
const toggle = $(".theme-toggle");
toggle.innerHTML = pixelSprite(`
  ...mmmm..
  ..mmm....
  .mmm.....
  .mmm.....
  .mmm.....
  .mmm.....
  ..mmm....
  ...mmmm..`, { m: "#3b2418" }, { scale: 3, className: "moon" }) + pixelSprite(`
  ....s....
  .s.....s.
  ...sss...
  ..sssss..
  s.sssss.s
  ..sssss..
  ...sss...
  .s.....s.
  ....s....`, { s: "#f2b440" }, { scale: 3, className: "sun" });
const labelToggle = () => toggle.setAttribute("aria-label",
  root.dataset.theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
labelToggle();
toggle.addEventListener("click", () => {
  root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
  labelToggle();
});

const phone = matchMedia("(max-width: 600px)");
const rail = $(".rail");
const skewer = $("#skewer");

// a quick ease-out scroll; the browser's own smooth scroll is slower and its speed varies
const still = matchMedia("(prefers-reduced-motion: reduce)");
// snapping is paused while gliding, or each step would get pulled back to the nearest question
const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);
const easeOutQuad = (t) => 1 - (1 - t) * (1 - t);
// each glide gets a number; starting a new one (or touching the screen) makes the old one stop
let glideId = 0;
const stopGlide = () => { glideId++; root.classList.remove("is-gliding"); };
function glide(top, ms = 170, ease = easeOutCubic) {
  const id = ++glideId;
  const from = window.scrollY, dist = Math.min(top, root.scrollHeight - innerHeight) - from;
  root.classList.add("is-gliding");
  if (still.matches) {
    window.scrollTo(0, from + dist);
    return root.classList.remove("is-gliding");
  }
  const t0 = performance.now();
  const step = (now) => {
    if (id !== glideId) return;
    const t = Math.min(1, Math.max(0, (now - t0) / ms)); // a frame can be stamped just before t0
    window.scrollTo(0, from + dist * ease(t));
    if (t < 1) requestAnimationFrame(step);
    else root.classList.remove("is-gliding");
  };
  requestAnimationFrame(step);
}

// scrolls so `el` starts just below the sticky skewer on phones, or near the top on desktop
function scrollToEl(el) {
  const offset = phone.matches ? rail.offsetHeight + 16 : 32;
  glide(el.getBoundingClientRect().top + window.scrollY - offset);
}

// ---------- talking to the server ----------

const alertBox = $("#alert");
let alertTimer;
function showAlert(text, { sticky = false } = {}) {
  clearTimeout(alertTimer);
  alertBox.textContent = text;
  alertBox.classList.add("is-on");
  if (!sticky) alertTimer = setTimeout(() => alertBox.classList.remove("is-on"), 5000);
}
const hideAlert = () => alertBox.classList.remove("is-on");

async function post(url, data) {
  try {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
    return true;
  } catch (e) {
    showAlert(`Couldn't save: ${e.message}`);
    return false;
  }
}

let shown = null; // the round number and status on screen
let api = null;
let questions = [];

// a pick saves right away; typing saves once you pause
const timers = {};
function saveAnswer(id, answer, { now }) {
  clearTimeout(timers[id]);
  const round = shown.round;
  const send = () => post("/api/answer", { round, id, choice: answer.choice, text: answer.text });
  if (now) send();
  else timers[id] = setTimeout(send, 400);
}

async function submitRound(answers) {
  Object.values(timers).forEach(clearTimeout);
  document.body.classList.add("is-submitted");
  api.close();
  // the note sits after the last question, so scroll down to it
  glide(root.scrollHeight);
  if (!(await post("/api/submit", { round: shown.round, answers }))) {
    document.body.classList.remove("is-submitted");
    api.reopen();
  }
}

function setNote(html) {
  $("#note").innerHTML = html;
}
const loader = '<span class="loader" aria-hidden="true"><i></i><i></i><i></i></span>';

function apply(s) {
  document.title = `${s.title} · Grill`;
  $("#topic").textContent = s.title;
  const empty = s.round === 0, finished = s.status === FINISHED;
  document.body.classList.toggle("is-empty", empty);
  document.body.classList.toggle("is-finished", finished);
  if (!empty && (!shown || shown.round !== s.round)) mountRound(s);
  $("#round-label").textContent = empty ? "" : `Round ${s.round}`;
  const sent = !empty && s.status === AGENT;
  document.body.classList.toggle("is-submitted", sent);
  if (api) sent || finished ? api.close() : api.reopen();
  $("#finished-detail").textContent = `The grill's off · ${s.round} round${s.round === 1 ? "" : "s"} cooked`;
  if (finished) setNote("Session finished. You can close this tab.");
  else if (empty) setNote(`The agent is preparing the first round ${loader}`);
  else if (sent) setNote(`Round ${s.round} sent. Round ${s.round + 1} shows up here as soon as it's ready.`);
  shown = { round: s.round, status: s.status };
}

function render(q) {
  const chips = q.choices.map((c, n) =>
    `<button class="chip" data-chip="${n}" aria-pressed="false"${n === 0 ? ' title="Recommended"' : ""}>` +
    `<kbd>${n + 1}</kbd>${n === 0 ? arrow : ""}${inline(c)}</button>`).join("");
  return `
    <section class="q" data-q="${q.id}" aria-labelledby="${q.id}-t">
      <span class="q-id">${q.id}</span>
      ${check}
      <h2 class="q-title" id="${q.id}-t">${inline(q.title)}</h2>
      <div class="q-body">${md(q.body)}</div>
      <div class="chips">${chips}</div>
      <textarea data-text rows="1" placeholder="Add your own answer, or dictate it here" aria-label="Your answer to ${q.id}"></textarea>
    </section>`;
}

function mountRound(s) {
  if (api) api.destroy();
  questions = s.questions;
  skewer.innerHTML = '<span class="ring"></span>' + questions.map((q, i) =>
    `<button class="chunk" data-action="jump" data-index="${i}" aria-label="Go to ${q.id}">${raw}${cooked}</button>`).join("");
  api = Grill.mount({
    root: $("#round"),
    questions,
    render,
    onAnswer: saveAnswer,
    onDone: submitRound,
    onChange: ({ answered, total, current, questions, isAnswered }) => {
      document.querySelectorAll(".chunk").forEach((c, i) => {
        c.classList.toggle("is-done", isAnswered(questions[i].id));
        c.classList.toggle("is-here", i === current);
      });
      $("#tally").innerHTML = `<b>${answered}</b> of ${total}<br><span>cooked</span>`;
    },
    // keyboard moves (Enter, Alt/Opt ↑↓) and skewer clicks land the question at the top, like auto-advance
    scrollToCard: (card) => scrollToEl(card),
    // on phones Enter in an answer box is just a new line; moving on is a swipe or a tap on an answer
    enterAddsNewline: () => phone.matches,
    // picking an answer moves on to the next question (or the buttons after the last one);
    // phones skip focusing the next answer box so the keyboard doesn't pop up
    onPick: (i, choice) => {
      if (choice === null) return;
      setTimeout(() => {
        if (i < questions.length - 1) {
          api.setCurrent(i + 1, { focus: !phone.matches, scroll: false });
          scrollToEl(document.querySelectorAll(".q")[i + 1]);
        } else {
          glide(root.scrollHeight);
        }
      }, 30);
    },
  });
  setupCards();
  fitBar();
  window.scrollTo(0, 0);
  if (!phone.matches) api.setCurrent(0, { scroll: false });
}

// the server pushes the whole state whenever the session files change
function connect() {
  const events = new EventSource("/api/events");
  let lost = false;
  events.onmessage = (e) => {
    if (lost) hideAlert();
    lost = false;
    apply(JSON.parse(e.data));
  };
  // EventSource keeps retrying on its own
  events.onerror = () => {
    if (shown && shown.status === FINISHED) return events.close();
    lost = true;
    showAlert("Lost the connection to the grill server. Reconnecting…", { sticky: true });
  };
}
connect();

// ---------- phones: swipe snapping, fixed tiles, typing mode ----------

// on phones the question that snaps under the skewer becomes the current one
const fitBar = () => root.style.setProperty("--bar", rail.offsetHeight + 16 + "px");
fitBar();
addEventListener("resize", fitBar);
// swipe snapping on touch screens: the finger scrolls natively, and on release the page moves exactly
// one stop (title, each question, the buttons) in the swipe's direction, faster and flatter than the
// browser's own snap. A swipe that only scrolled inside a long tile leaves the page alone.
if (matchMedia("(pointer: coarse)").matches) {
  root.classList.add("touch-snap");
  // each stop is a scroll position, plus the question index it shows (-1 for the title and the buttons)
  const stops = () => {
    const line = rail.offsetHeight + 16, max = root.scrollHeight - innerHeight;
    const cards = [...document.querySelectorAll(".q")].map((c, i) => ({ y: c.getBoundingClientRect().top + scrollY - line, i }));
    return [{ y: 0, i: -1 }, ...cards, { y: max, i: -1 }]
      .map((s) => ({ ...s, y: Math.min(Math.max(0, Math.round(s.y)), max) }))
      .filter((s, k, all) => all.findIndex((o) => o.y === s.y) === k);
  };
  let startY = null, startIndex = 0;
  addEventListener("touchstart", (e) => {
    if (!api || !phone.matches || e.touches.length > 1 || root.classList.contains("is-typing")) return (startY = null);
    if (root.classList.contains("is-gliding")) stopGlide();
    const all = stops(), gaps = all.map((s) => Math.abs(s.y - scrollY));
    startY = scrollY;
    startIndex = gaps.indexOf(Math.min(...gaps));
  }, { passive: true });
  addEventListener("touchend", () => {
    if (startY === null) return;
    const moved = scrollY - startY;
    startY = null;
    if (Math.abs(moved) < 2) return;
    const all = stops();
    const step = Math.abs(moved) < 24 ? 0 : Math.sign(moved);
    const target = all[Math.min(Math.max(0, startIndex + step), all.length - 1)];
    // highlight the question it's heading to right away, not once it lands
    if (target.i !== -1) api.setCurrent(target.i, { focus: false, scroll: false });
    glide(target.y, 180, easeOutQuad);
  }, { passive: true });
}

let settle;
addEventListener("scroll", () => {
  clearTimeout(settle);
  settle = setTimeout(() => {
    if (!api || !phone.matches || root.classList.contains("is-gliding")) return;
    const line = rail.offsetHeight + 16;
    const cards = [...document.querySelectorAll(".q")];
    const gaps = cards.map((c) => Math.abs(c.getBoundingClientRect().top - line));
    const i = gaps.indexOf(Math.min(...gaps));
    if (gaps[i] < innerHeight / 3 && !cards[i].classList.contains("is-current"))
      api.setCurrent(i, { focus: false, scroll: false });
  }, 120);
}, { passive: true });

// fixed tiles (default; add ?free to the URL to turn them off)
if (!new URLSearchParams(location.search).has("free")) root.classList.add("fixed-tiles");
// mark tiles that still have content below their visible edge
const markMore = (q) => q.classList.toggle("has-more", phone.matches && q.scrollTop + q.clientHeight < q.scrollHeight - 4);
phone.addEventListener("change", () => document.querySelectorAll(".q").forEach(markMore));

// typing mode on phones: the focused answer box takes over the screen above the keyboard,
// then the page comes back to the same question once you're done
const bar = $(".typing-bar");
let typingIn = null, fullHeight = innerHeight, lastH = innerHeight, advanceAfterTyping = false;
const fitTyping = () => {
  const h = window.visualViewport ? visualViewport.height : innerHeight;
  // closing the keyboard with the back gesture doesn't blur the box, so treat a big grow as "done"
  if (typingIn && h > fullHeight - 80 && h - lastH > 120) document.activeElement.blur();
  lastH = h;
};
(window.visualViewport || window).addEventListener("resize", fitTyping);
// runs `done` once the page is back to full height, or after 600ms if it never gets there
function afterKeyboardCloses(done) {
  const open = () => innerHeight < fullHeight - 80;
  if (!open()) return requestAnimationFrame(done);
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    removeEventListener("resize", check);
    requestAnimationFrame(done);
  };
  const check = () => { if (!open()) finish(); };
  addEventListener("resize", check);
  setTimeout(finish, 600);
}
// keep the box focused through the tap so the blur runs once, from the button's own click.
// Done also moves on; closing the keyboard with the back gesture stays on the same question
bar.querySelector("button").addEventListener("pointerdown", (e) => e.preventDefault());
bar.querySelector("button").addEventListener("click", () => {
  advanceAfterTyping = true;
  document.activeElement.blur();
});

// per-round wiring; the old round's elements (and their listeners) are gone by now
function setupCards() {
  document.querySelectorAll(".q").forEach((q) => {
    q.addEventListener("scroll", () => markMore(q), { passive: true });
    new ResizeObserver(() => markMore(q)).observe(q);
    q.addEventListener("input", () => markMore(q));
  });
  document.querySelectorAll(".q textarea").forEach((t) => {
    t.addEventListener("focus", () => {
      if (!phone.matches || t.readOnly) return;
      typingIn = t.closest(".q");
      fullHeight = Math.max(fullHeight, innerHeight);
      bar.querySelector("span").innerHTML =
        `<b>${typingIn.dataset.q}</b>${Grill.esc(typingIn.querySelector(".q-title").textContent)}`;
      root.classList.add("is-typing");
      root.style.setProperty("--tbar", bar.offsetHeight + "px");
      fitTyping();
    });
    t.addEventListener("blur", () => {
      if (!typingIn) return;
      const card = typingIn;
      typingIn = null;
      root.classList.remove("is-typing");
      // the tiles resize as the keyboard closes, so wait for that before working out where to scroll
      afterKeyboardCloses(() => {
        root.classList.add("is-gliding");
        window.scrollTo(0, card.getBoundingClientRect().top + window.scrollY - rail.offsetHeight - 16);
        root.classList.remove("is-gliding");
        if (!advanceAfterTyping) return;
        // Done moves on to the next question, or to the buttons after the last one
        advanceAfterTyping = false;
        const cards = [...document.querySelectorAll(".q")], next = cards.indexOf(card) + 1;
        if (next < cards.length) {
          api.setCurrent(next, { focus: false, scroll: false });
          scrollToEl(cards[next]);
        } else glide(root.scrollHeight);
      });
    });
    // grow the answer box with its text, for browsers without field-sizing
    if (!CSS.supports("field-sizing", "content")) {
      const fit = () => { t.style.height = "auto"; t.style.height = t.scrollHeight + "px"; };
      t.addEventListener("input", fit);
      fit();
    }
  });
}
