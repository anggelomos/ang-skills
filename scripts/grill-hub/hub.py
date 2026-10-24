#!/usr/bin/env python3
"""grill-hub: serves grill-me-with-ui sessions outside localhost, for example through a Cloudflare tunnel.

It listens on two ports:
  public (7170)  the dashboard and the session pages. Only paired browsers get in. Route the tunnel here.
  agent  (7171)  for grill.py on this machine. It has no auth, so never route anything to it.

grill.py keeps .grill/ in the project as the agent's source of truth and pushes every change here.
The page writes the user's answers here, and `grill.py wait` copies them back into .grill/.

Data, in GRILL_HUB_DATA (default ./data next to this file):
  sessions/<uuid>/session.json  {id, project, title, status, updatedAt}
  sessions/<uuid>/round-N.json  the same round files as .grill/ in the project
  devices.json                  {sha256 of a browser's cookie: {pairedAt, userAgent}}

Pairing: `grill.py connect` asks the agent port for a one-time code (6 characters, 10 minutes). Entering it
at /pair gives that browser a cookie that never expires. Delete its entry in devices.json to revoke it.

Python 3.8+, standard library only. It reuses grill.py's page server, so it needs the skill folder:
GRILL_SKILL_DIR, default ../../grill-me-with-ui.
"""
import hashlib
import html
import json
import os
import re
import secrets
import signal
import sys
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ in the skill folder
sys.path.insert(0, os.environ.get("GRILL_SKILL_DIR", str(HERE.parent.parent / "grill-me-with-ui")))
import grill  # noqa: E402
from grill import AGENT, FINISHED, USER, latest_questions, now, read_json, round_count, round_file, session_file, write_json  # noqa: E402

DATA = Path(os.environ.get("GRILL_HUB_DATA", str(HERE / "data")))
SESSIONS = DATA / "sessions"
DEVICES = DATA / "devices.json"
PUBLIC_URL = os.environ.get("GRILL_HUB_PUBLIC_URL", "http://localhost:7170").rstrip("/")
HOST = os.environ.get("GRILL_HUB_HOST", "127.0.0.1")  # 0.0.0.0 inside Docker
PUBLIC_PORT = int(os.environ.get("GRILL_HUB_PUBLIC_PORT", "7170"))
AGENT_PORT = int(os.environ.get("GRILL_HUB_AGENT_PORT", "7171"))

COOKIE = "grill_device"
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
CODE_MINUTES = 10
MAX_FAILURES = 5  # wrong codes per minute, from anyone, before /pair stops checking
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PROJECT = re.compile(r"[a-z0-9-]{1,80}")

# one lock for both ports, so the page and the agent never write a session at the same time
LOCK = threading.Lock()
codes = {}  # pairing code -> expiry time. In memory: a restart drops unused codes
failures = []  # times of recent wrong codes


def find_session(sid):
    """(session folder, session.json) for a valid, existing session id, else (None, None)."""
    if not SESSION_ID.fullmatch(sid or ""):
        return None, None
    sdir = SESSIONS / sid
    try:
        return sdir, read_json(session_file(sdir))
    except (OSError, ValueError):
        return None, None


def agent_state(sdir):
    s = read_json(session_file(sdir))
    return {"status": s["status"], "round": round_count(sdir), "questions": latest_questions(sdir)}


def load_devices():
    try:
        return read_json(DEVICES)
    except (OSError, ValueError):
        return {}


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def reply(handler, code, body, ctype="application/json; charset=utf-8", headers=()):
    if not isinstance(body, bytes):
        body = json.dumps(body, ensure_ascii=False).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    for k, v in headers:
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(body)


def read_body(handler):
    length = int(handler.headers.get("Content-Length") or 0)
    return handler.rfile.read(min(length, 5_000_000))


# ---------- agent port: grill.py on this machine ----------

def merge_session(sid, body):
    """Take a full snapshot from grill.py. The hub keeps what's newer on its side: the user's answers
    to the open round, and a submit grill.py hasn't collected yet."""
    project, title, status, rounds = body.get("project"), body.get("title"), body.get("status"), body.get("rounds")
    if not (isinstance(project, str) and PROJECT.fullmatch(project) and isinstance(title, str)
            and status in (AGENT, USER, FINISHED) and isinstance(rounds, list)
            and all(isinstance(r, dict) and isinstance(r.get("questions"), list) for r in rounds)):
        raise ValueError("expected {project, title, status, rounds: [{questions}]}")
    with LOCK:
        sdir = SESSIONS / sid
        try:
            old = read_json(session_file(sdir))
        except (OSError, ValueError):
            old = None
        have = round_count(sdir) if old else 0
        sdir.mkdir(parents=True, exist_ok=True)
        for n in range(have + 1, len(rounds) + 1):
            write_json(round_file(sdir, n), {"questions": rounds[n - 1]["questions"]})
        if old and len(rounds) <= have and status != FINISHED:
            status = old["status"]
        write_json(session_file(sdir), {"id": sid, "project": project, "title": title, "status": status, "updatedAt": now()})
        return agent_state(sdir)


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "grill-hub"

    def log_message(self, fmt, *args):
        pass

    def parts(self):
        url = urlsplit(self.path)
        return url.path.strip("/").split("/"), parse_qs(url.query)

    def do_GET(self):
        parts, query = self.parts()
        if parts == ["api", "ping"]:
            return reply(self, 200, {"hub": True, "publicUrl": PUBLIC_URL, "devices": len(load_devices())})
        if len(parts) != 3 or parts[:2] != ["api", "sessions"]:
            return reply(self, 404, {"error": "not found"})
        sdir, _ = find_session(parts[2])
        if not sdir:
            return reply(self, 404, {"error": "no such session"})
        try:
            n = int(query.get("round", ["0"])[0])
            wait = max(0, min(60, int(query.get("wait", ["0"])[0])))
        except ValueError:
            return reply(self, 400, {"error": "round and wait must be numbers"})
        # long poll: answer as soon as the user submits round n (or anything else changes), or when time's up
        deadline = time.time() + wait
        while True:
            state = agent_state(sdir)
            if state["status"] != USER or state["round"] != n or time.time() >= deadline:
                return reply(self, 200, state)
            time.sleep(0.4)

    def do_PUT(self):
        parts, _ = self.parts()
        if len(parts) != 3 or parts[:2] != ["api", "sessions"] or not SESSION_ID.fullmatch(parts[2]):
            return reply(self, 404, {"error": "not found"})
        try:
            body = json.loads(read_body(self) or b"{}")
            return reply(self, 200, merge_session(parts[2], body))
        except (ValueError, AttributeError) as e:
            return reply(self, 400, {"error": str(e)})

    def do_POST(self):
        parts, _ = self.parts()
        if parts != ["api", "pair-codes"]:
            return reply(self, 404, {"error": "not found"})
        with LOCK:
            t = time.time()
            for c in [c for c, exp in codes.items() if exp < t]:
                del codes[c]
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
            codes[code] = t + CODE_MINUTES * 60
        reply(self, 200, {"code": code, "pairUrl": PUBLIC_URL + "/pair", "expiresInMinutes": CODE_MINUTES})


# ---------- public port: the dashboard and the pages ----------

# the session page's palette, fonts and pixel bevels. Code characters and numbers use Space Grotesk:
# in Pixelify Sans, 5 reads as S and 2 as 8
STYLE = """
  :root { color-scheme: light; --paper: #fbf6ef; --card: #fffdfa; --edge: #eadbca; --edge-lo: #dcc6ae; --ink: #3b2418;
          --ink-dim: #8a6b57; --ember: #dd5f1c; --ember-lo: #b2471a; --ember-hi: #ee8a4c; --ember-ink: #b2471a;
          --danger: #c4372a; --display: "Pixelify Sans", "Space Grotesk", system-ui, sans-serif;
          --text: "Space Grotesk", system-ui, sans-serif; }
  @media (prefers-color-scheme: dark) {
    :root { color-scheme: dark; --paper: #1b1411; --card: #241b16; --edge: #3a2c23; --edge-lo: #110c0a; --ink: #f0e3d5;
            --ink-dim: #a68d7b; --ember: #e2692a; --ember-lo: #9a3d14; --ember-hi: #f0955c; --ember-ink: #f29b64; --danger: #ff7a66; }
  }
  * { box-sizing: border-box; }
  html { background: var(--paper); }
  body { margin: 0; color: var(--ink); font: 400 17px/1.5 var(--text); -webkit-font-smoothing: antialiased; }
  h1 span { color: var(--ember); }
  .bevel { box-shadow: 0 -3px 0 0 var(--edge), 0 3px 0 0 var(--edge-lo), -3px 0 0 0 var(--edge), 3px 0 0 0 var(--edge-lo); }
  .bevel-hot { box-shadow: 0 -3px 0 0 var(--ember-hi), 0 3px 0 0 var(--ember-lo), -3px 0 0 0 var(--ember-hi), 3px 0 0 0 var(--ember-lo); }
  @keyframes blink { 0%, 33% { opacity: 1; } 34%, 100% { opacity: .3; } }
  @keyframes caret { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } }
  @keyframes shake { 0%, 100% { transform: none; } 20%, 60% { transform: translateX(-6px); } 40%, 80% { transform: translateX(6px); } }

  /* dashboard */
  .list { max-width: 720px; margin: 0 auto; padding: 64px 24px 80px; }
  .list h1 { margin: 0; font: 600 clamp(48px, 11vw, 72px)/1 var(--display); }
  section { margin-top: 52px; }
  h2 { margin: 0 0 18px; font: 600 16px/1.4 var(--text); letter-spacing: .1em; text-transform: uppercase; color: var(--ink-dim);
       overflow-wrap: anywhere; }
  ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 14px; }
  a.row { display: flex; align-items: center; gap: 20px; padding: 6px 10px 6px 6px; margin-left: -6px; color: inherit; text-decoration: none; }
  a.row:hover .name { text-decoration: underline; text-decoration-thickness: 2px; text-underline-offset: 5px; text-decoration-color: var(--ember); }
  a.row:focus-visible { outline: 3px dashed var(--ink); outline-offset: 2px; }
  .tile { flex: none; width: 58px; height: 58px; display: grid; place-content: center; text-align: center; background: var(--card); color: var(--ink-dim); }
  .tile b { font: 600 26px/1 var(--text); color: var(--ink); }
  .tile small { font: 600 9px/1 var(--text); letter-spacing: .12em; text-transform: uppercase; margin-bottom: 3px; }
  .is-you .tile { background: var(--ember); color: #ffe0c8; }
  .is-you .tile b { color: #fff; }
  .text { min-width: 0; display: grid; gap: 2px; }
  .name { font-size: 19px; font-weight: 500; line-height: 1.3; overflow-wrap: anywhere; }
  .who { font-size: 14px; color: var(--ink-dim); }
  .is-you .who { color: var(--ember-ink); font-weight: 500; }
  .empty { margin-top: 48px; color: var(--ink-dim); }
  .empty a { color: var(--ember-ink); }

  /* pairing: one real input over six boxes, so paste, autofill and phone keyboards just work */
  .center { min-height: 100dvh; display: grid; place-items: center; padding: 32px 20px; text-align: center; }
  .stack { display: grid; justify-items: center; gap: 28px; width: 100%; max-width: 600px; }
  .center h1 { margin: 0; font: 600 clamp(26px, 6vw, 34px)/1.15 var(--display); letter-spacing: .01em; }
  .code { position: relative; display: flex; align-items: center; gap: 14px; }
  .code input { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; border: 0; padding: 0; font-size: 16px;
                color: transparent; background: transparent; caret-color: transparent; }
  .group { display: flex; gap: 12px; }
  .dash { width: 14px; height: 4px; background: var(--ink-dim); }
  .slot { width: 52px; height: 66px; display: grid; place-items: center; background: var(--card); font: 600 32px/1 var(--text); }
  .slot.is-active { box-shadow: 0 -3px 0 0 var(--ember-hi), 0 3px 0 0 var(--ember-lo), -3px 0 0 0 var(--ember-hi), 3px 0 0 0 var(--ember-lo); }
  .slot.is-active:empty::after { content: ""; width: 4px; height: 30px; background: var(--ember); animation: caret 1s steps(1) infinite; }
  .code.is-error .slot { color: var(--danger); box-shadow: 0 -3px 0 0 var(--danger), 0 3px 0 0 var(--danger), -3px 0 0 0 var(--danger), 3px 0 0 0 var(--danger); }
  .code.is-ok .slot { background: var(--ember); color: #fff; box-shadow: 0 -3px 0 0 var(--ember-hi), 0 3px 0 0 var(--ember-lo), -3px 0 0 0 var(--ember-hi), 3px 0 0 0 var(--ember-lo); }
  .shake { animation: shake .32s steps(4) 1; }
  .status { margin: 0; min-height: 26px; font-size: 15px; color: var(--ink-dim); display: flex; align-items: center; gap: 10px; }
  .status.is-error { color: var(--danger); }
  .status.is-ok { color: var(--ember-ink); }
  .loader { display: inline-flex; gap: 4px; }
  .loader i { width: 6px; height: 6px; background: currentColor; opacity: .3; animation: blink .9s steps(1) infinite; }
  .loader i:nth-child(2) { animation-delay: .3s; } .loader i:nth-child(3) { animation-delay: .6s; }
  @media (max-width: 420px) {
    .code { gap: 8px; } .group { gap: 8px; } .dash { width: 8px; }
    .slot { width: 44px; height: 58px; font-size: 27px; }
  }
  @media (prefers-reduced-motion: reduce) { .shake { animation: none; } }
"""

# auto-submits once six characters are in; without JavaScript, Enter submits the form
PAIR_SCRIPT = """
const form = document.querySelector("form"), root = document.querySelector(".code"), input = root.querySelector("input");
const slots = [...root.querySelectorAll(".slot")], status = document.querySelector(".status");
const say = (cls, html) => { status.className = "status" + (cls ? " " + cls : ""); status.innerHTML = html; };
const paint = () => {
  const v = input.value, focused = document.activeElement === input;
  slots.forEach((s, i) => {
    s.textContent = v[i] || "";
    s.classList.toggle("is-active", focused && i === Math.min(v.length, 5));
  });
};
const toEnd = () => requestAnimationFrame(() => input.setSelectionRange(input.value.length, input.value.length));
input.addEventListener("focus", () => { toEnd(); paint(); });
input.addEventListener("click", toEnd);
input.addEventListener("keyup", toEnd);
input.addEventListener("blur", paint);
input.addEventListener("input", () => {
  // uppercase and keep only characters codes use, so a pasted "j59-t88" becomes J59T88
  input.value = input.value.toUpperCase().replace(/[^ABCDEFGHJKMNPQRSTUVWXYZ23456789]/g, "").slice(0, 6);
  if (root.classList.contains("is-error")) { root.classList.remove("is-error"); say("", ""); }
  paint();
  if (input.value.length === 6) send();
});
form.addEventListener("submit", (e) => { e.preventDefault(); if (input.value.length === 6) send(); });
async function send() {
  const body = new URLSearchParams(new FormData(form)); // before disabling: disabled fields aren't sent
  input.disabled = true;
  say("", 'Checking <span class="loader"><i></i><i></i><i></i></span>');
  let r, data = {};
  try {
    r = await fetch("/pair", { method: "POST", headers: { Accept: "application/json" }, body });
    data = await r.json();
  } catch (e) { data.error = "Couldn't reach the hub. Try again."; }
  if (r && r.ok) {
    root.classList.add("is-ok");
    say("is-ok", "Paired. Opening your session…");
    return setTimeout(() => location.replace(data.next), 400);
  }
  root.classList.add("is-error");
  root.classList.remove("shake"); void root.offsetWidth; root.classList.add("shake");
  say("is-error", data.error || "Something went wrong.");
  setTimeout(() => { input.value = ""; input.disabled = false; paint(); input.focus(); }, 700);
}
input.disabled = false;
input.focus();
paint();
"""


def page(title, body, refresh=False, script=""):
    meta = '<meta http-equiv="refresh" content="15">' if refresh else ""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">{}<title>{} · Grill hub</title>'
            '<link rel="icon" type="image/png" sizes="32x32" href="/favicon.png">'
            '<link rel="icon" type="image/svg+xml" sizes="any" href="/favicon.svg">'
            '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link href="https://fonts.googleapis.com/css2?family=Pixelify+Sans:wght@500;600&family=Space+Grotesk:wght@400;500;600&display=swap" rel="stylesheet">'
            '<style>{}</style></head><body>{}{}</body></html>').format(
                meta, html.escape(title), STYLE, body, "<script>{}</script>".format(script) if script else "").encode()


def session_row(project, s, n):
    """A session's round tile and title. The tile shows the open round on your turn, or the one being written."""
    you = s["status"] == USER
    who = "Your turn" if you else "The agent is writing the {} round".format("next" if n else "first")
    return ('<li><a class="row{}" href="/{}/{}/"><span class="tile {}"><small>Round</small><b>{}</b></span>'
            '<span class="text"><span class="name">{}</span><span class="who">{}</span></span></a></li>').format(
                " is-you" if you else "", quote(project), s["id"], "bevel-hot" if you else "bevel",
                n if you else n + 1, html.escape(s["title"]), who)


def dashboard():
    projects = {}
    for f in SESSIONS.glob("*/session.json"):
        try:
            s = read_json(f)
        except (OSError, ValueError):
            continue
        if s.get("status") != FINISHED:
            projects.setdefault(s["project"], []).append((s, round_count(f.parent)))
    if not projects:
        body = '<p class="empty">No active sessions. Start one with <code>/grill-me-with-ui</code> and it shows up here.</p>'
    else:
        body = ""
        latest = lambda item: max(s["updatedAt"] for s, _ in item[1])
        for project, sessions in sorted(projects.items(), key=latest, reverse=True):
            rows = "".join(session_row(project, s, n) for s, n in sorted(sessions, key=lambda x: x[0]["updatedAt"], reverse=True))
            body += "<section><h2>{}</h2><ul>{}</ul></section>".format(html.escape(project), rows)
    return page("Sessions", '<main class="list"><h1>Grill <span>hub</span></h1>{}</main>'.format(body), refresh=True)


def pair_page(nxt, error=""):
    group = '<span class="group"><span class="slot bevel"></span><span class="slot bevel"></span><span class="slot bevel"></span></span>'
    return page("Pairing", (
        '<main class="center"><form class="stack" method="post" action="/pair">'
        "<h1>Introduce the pairing code</h1>"
        '<label class="code{}">{}<span class="dash"></span>{}'
        '<input name="code" autocomplete="one-time-code" autocapitalize="characters" autocorrect="off" spellcheck="false" '
        'maxlength="12" aria-label="Pairing code" required></label>'
        '<input type="hidden" name="next" value="{}">'
        '<p class="status{}" role="status">{}</p></form></main>').format(
            " is-error" if error else "", group, group, html.escape(nxt),
            " is-error" if error else "", html.escape(error)), script=PAIR_SCRIPT)


def safe_next(nxt):
    return nxt if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt else "/"


class PublicHandler(grill.Handler):
    """grill.py's page server, for every session on the hub, behind pairing."""
    server_version = "grill-hub"

    def paired(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie") or "")
        except Exception:
            return False
        token = cookie.get(COOKIE)
        return bool(token) and token_hash(token.value) in load_devices()

    def redirect(self, location, headers=()):
        reply(self, 303, b"", "text/plain", [("Location", location)] + list(headers))

    def route(self):
        url = urlsplit(self.path)
        path = url.path
        # Shared branding is public, including on the pairing page.
        if path in ("/favicon.svg", "/favicon.png") and self.command == "GET":
            ctype = "image/svg+xml" if path.endswith(".svg") else "image/png"
            reply(self, 200, (grill.PAGE_DIR / path[1:]).read_bytes(), ctype)
            return None
        if path == "/pair":
            if self.command == "POST":
                self.pair()
            else:
                reply(self, 200, pair_page(safe_next(parse_qs(url.query).get("next", ["/"])[0])), "text/html; charset=utf-8")
            return None
        if not self.paired():
            if "/api/" in path:
                reply(self, 401, {"error": "this browser isn't paired with the grill hub. Reload the page."})
            else:
                self.redirect("/pair?next=" + quote(path))
            return None
        if path == "/" and self.command == "GET":
            reply(self, 200, dashboard(), "text/html; charset=utf-8")
            return None
        parts = path.split("/")  # "", project, session id, rest of the path
        if len(parts) >= 3:
            sdir, s = find_session(parts[2])
            if s and s.get("project") == parts[1]:
                if len(parts) == 3:
                    self.redirect(path + "/")
                    return None
                rest = "/" + "/".join(parts[3:])
                # the agent finishes sessions, through the agent port
                if rest not in ("/api/ping", "/api/finish"):
                    self.sdir = sdir
                    return rest
        reply(self, 404, page("Not found", '<main class="list"><h1>Not <span>found</span></h1>'
                              '<p class="empty"><a href="/">Back to the sessions</a></p></main>'),
              "text/html; charset=utf-8")
        return None

    def pair(self):
        """Checks a pairing code. The page posts it with fetch and gets JSON; a plain form post gets HTML."""
        form = parse_qs(read_body(self).decode("utf-8", "replace"))
        nxt = safe_next(form.get("next", ["/"])[0])
        code = re.sub(r"[\s-]", "", form.get("code", [""])[0]).upper()
        wants_json = "application/json" in (self.headers.get("Accept") or "")

        def refuse(status, error):
            if wants_json:
                return reply(self, status, {"error": error})
            reply(self, status, pair_page(nxt, error), "text/html; charset=utf-8")

        with LOCK:
            t = time.time()
            failures[:] = [f for f in failures if f > t - 60]
            if len(failures) >= MAX_FAILURES:
                return refuse(429, "Too many wrong codes. Wait a minute, then try again.")
            if codes.get(code, 0) < t:
                failures.append(t)
                return refuse(400, "That code is wrong or has expired.")
            del codes[code]
            token = secrets.token_urlsafe(32)
            devices = load_devices()
            devices[token_hash(token)] = {"pairedAt": now(), "userAgent": self.headers.get("User-Agent", "")[:200]}
            write_json(DEVICES, devices)
        cookie = "{}={}; Path=/; Max-Age=315360000; HttpOnly; SameSite=Lax".format(COOKIE, token)
        if PUBLIC_URL.startswith("https://"):
            cookie += "; Secure"
        if wants_json:
            return reply(self, 200, {"next": nxt}, headers=[("Set-Cookie", cookie)])
        self.redirect(nxt, [("Set-Cookie", cookie)])


def main():
    SESSIONS.mkdir(parents=True, exist_ok=True)
    public = grill.Server((HOST, PUBLIC_PORT), PublicHandler)
    public.config, public.lock, public.stopping = {"theme": "system"}, LOCK, False
    public.touch = lambda: None
    agent = grill.Server((HOST, AGENT_PORT), AgentHandler)
    threading.Thread(target=agent.serve_forever, daemon=True).start()
    # in Docker this runs as PID 1, which ignores SIGTERM unless it handles it
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print("{} grill hub: public port {} ({}), agent port {}, data in {}".format(
        now(), PUBLIC_PORT, PUBLIC_URL, AGENT_PORT, DATA), flush=True)
    public.serve_forever(poll_interval=0.25)


if __name__ == "__main__":
    main()
