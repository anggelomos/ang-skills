"""The hub's own pages: the gallery, the shell around a private artifact, pairing, and messages.
Everything here is escaped; nothing from an artifact's HTML ever lands in these pages."""
from html import escape

LIGHT = ("color-scheme: light; --bg: #f4f5f7; --card: #fff; --line: #dcdfe4; --ink: #1b1f24; --dim: #67707c; --prompt: #a05e00;"
         " --blue: #1f5fbf; --green: #1f7a3c; --await: #d9480f; --danger: #c92a2a;")

# dark unless the OS or the theme toggle says light
BASE = """
:root { color-scheme: dark; --bg: #0e1013; --card: #15181d; --line: #252a31; --ink: #d8dee6; --dim: #7c8794; --prompt: #ffb84d;
  --blue: #7cb8ff; --green: #6fd38f; --await: #ff7a1a; --danger: #ff6b6b;
  --mono: ui-monospace, "JetBrains Mono", "Cascadia Mono", Menlo, Consolas, monospace; }
@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) { LIGHT } }
:root[data-theme="light"] { LIGHT }
* { box-sizing: border-box; }
html { background: var(--bg); }
body { margin: 0; color: var(--ink); font: 400 13.5px/1.55 var(--mono); -webkit-font-smoothing: antialiased; }
a { color: inherit; }
.theme { flex: none; display: inline-flex; padding: 3px; gap: 2px; border: 1px solid var(--line); border-radius: 8px; background: var(--card); }
.theme button { font: inherit; font-size: 12px; color: var(--dim); background: none; border: 0; padding: 5px 10px; border-radius: 5px; cursor: pointer; }
.theme button:hover { color: var(--ink); }
.theme button[aria-pressed="true"] { background: var(--line); color: var(--ink); }
.corner { position: fixed; top: 16px; right: 16px; }
""".replace("LIGHT", LIGHT)

GALLERY = """
main { max-width: 1280px; margin: 0 auto; padding: 40px 22px 96px; }
header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 28px; }
h1 { margin: 0; font-size: 26px; font-weight: 700; letter-spacing: -.01em; white-space: nowrap; }
h1::before { content: "> "; color: var(--prompt); }
.grid { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); }
.card { display: flex; flex-direction: column; gap: 10px; height: 100%; padding: 14px; background: var(--card); border: 1px solid var(--line);
  text-decoration: none; }
.card:hover { border-color: var(--dim); }
.card:focus-visible { outline: 2px solid var(--await); }
.top { display: flex; justify-content: space-between; gap: 8px; color: var(--dim); font-size: 12px; }
.top span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.top span:last-child { flex: none; }
.title { margin: 0; font-size: 14.5px; font-weight: 600; line-height: 1.4; overflow-wrap: anywhere; flex: 1; }
.tag { align-self: flex-start; font-size: 12px; padding: 1px 6px; border: 1px solid currentColor; }
.awaiting, .awaiting:hover { border-left: 3px solid var(--await); }
.awaiting .tag { color: var(--await); font-weight: 700; }
.responded .tag, .working .tag { color: var(--blue); } .view .tag { color: var(--green); } .done .tag { color: var(--dim); }
.empty { margin: 0; color: var(--dim); }
@media (max-width: 760px) { main { padding: 28px 16px 72px; } h1 { font-size: 20px; } .theme button { padding: 5px 7px; } }
"""

SHELL = """
html, body { height: 100%; }
body { display: grid; grid-template-rows: auto 1fr; }
.bar { display: flex; align-items: center; gap: 14px; min-width: 0; padding: 6px 10px 6px 14px; border-bottom: 1px solid var(--line); }
.bar a { flex: none; text-decoration: none; color: var(--dim); }
.bar a:hover { color: var(--ink); }
#title { flex: 1; min-width: 0; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#status { flex: none; font-size: 12px; padding: 1px 6px; border: 1px solid currentColor; color: var(--dim); }
#status[data-status="awaiting"] { color: var(--await); font-weight: 700; }
#status[data-status="responded"], #status[data-status="working"] { color: var(--blue); }
#status[data-status="view"] { color: var(--green); }
#expiry { flex: none; color: var(--dim); font-size: 12px; }
iframe { display: block; width: 100%; height: 100%; border: 0; background: #fff; }
.expired { display: none; place-content: center; text-align: center; color: var(--dim); }
body.is-expired iframe { display: none; } body.is-expired .expired { display: grid; }
.toast { position: fixed; left: 50%; bottom: 20px; transform: translate(-50%, 30px); opacity: 0; pointer-events: none;
  padding: 10px 16px; background: var(--ink); color: var(--bg); font-weight: 500; transition: .2s; max-width: calc(100% - 32px); }
.toast.is-on { opacity: 1; transform: translate(-50%, 0); }
.toast.is-error { background: var(--danger); color: #fff; }
@media (max-width: 600px) { #expiry, .bar .theme { display: none; } }
"""

THEME = ('<div class="theme{cls}" role="group" aria-label="Theme"><button type="button" data-theme="light">light</button>'
         '<button type="button" data-theme="dark">dark</button><button type="button" data-theme="system">system</button></div>')

# one real input over six boxes, so paste, autofill and phone keyboards just work
PAIR = """
@keyframes blink { 0%, 33% { opacity: 1; } 34%, 100% { opacity: .3; } }
@keyframes caret { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } }
@keyframes shake { 0%, 100% { transform: none; } 20%, 60% { transform: translateX(-6px); } 40%, 80% { transform: translateX(6px); } }
.center { min-height: 100dvh; display: grid; place-items: center; padding: 32px 20px; text-align: center; }
.stack { display: grid; justify-items: center; gap: 28px; width: 100%; max-width: 600px; }
.center h1 { margin: 0; font-size: clamp(20px, 5vw, 26px); font-weight: 700; letter-spacing: -.01em; }
.center h1::before { content: "> "; color: var(--prompt); }
.code { position: relative; display: flex; align-items: center; gap: 14px; }
.code input { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; border: 0; padding: 0; font-size: 16px;
              color: transparent; background: transparent; caret-color: transparent; }
.group { display: flex; gap: 10px; }
.dash { width: 14px; height: 2px; background: var(--dim); }
.slot { width: 52px; height: 66px; display: grid; place-items: center; background: var(--card); border: 1px solid var(--line);
        font: 600 30px/1 var(--mono); }
.slot.is-active { border-color: var(--await); box-shadow: inset 0 0 0 1px var(--await); }
.slot.is-active:empty::after { content: ""; width: 3px; height: 30px; background: var(--await); animation: caret 1s steps(1) infinite; }
.code.is-error .slot { color: var(--danger); border-color: var(--danger); }
.code.is-ok .slot { background: var(--await); border-color: var(--await); color: var(--bg); }
.shake { animation: shake .32s steps(4) 1; }
.status { margin: 0; min-height: 26px; color: var(--dim); display: flex; align-items: center; gap: 10px; }
.status.is-error { color: var(--danger); }
.status.is-ok { color: var(--await); }
.loader { display: inline-flex; gap: 4px; }
.loader i { width: 6px; height: 6px; background: currentColor; opacity: .3; animation: blink .9s steps(1) infinite; }
.loader i:nth-child(2) { animation-delay: .3s; } .loader i:nth-child(3) { animation-delay: .6s; }
@media (max-width: 420px) { .code { gap: 8px; } .group { gap: 8px; } .dash { width: 8px; } .slot { width: 44px; height: 58px; font-size: 27px; } }
@media (prefers-reduced-motion: reduce) { .shake { animation: none; } }
"""

MESSAGE = """
main { min-height: 100dvh; display: grid; place-content: center; gap: 12px; padding: 32px 20px; text-align: center; }
h1 { margin: 0; font-size: 22px; font-weight: 700; }
h1::before { content: "> "; color: var(--prompt); }
p { margin: 0; color: var(--dim); }
p a { color: var(--prompt); }
"""


def icon_for(status, kind="doc"):
    """Grill sessions keep the campfire (awaiting) and the cooked patty; everything else is a document."""
    if kind == "grill":
        return "favicon" if status == "awaiting" else "favicon-cooked"
    return "doc-awaiting" if status == "awaiting" else "doc"


def document(title, css, body, icon="doc", head="", scripts=(), body_attrs=""):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">{head}<title>{title}</title>'
            '<link rel="icon" type="image/png" sizes="32x32" href="/static/{icon}.png">'
            '<link rel="icon" type="image/svg+xml" sizes="any" href="/static/{icon}.svg">'
            '<script src="/static/theme.js"></script><style>{css}</style></head><body{attrs}>{body}{scripts}</body></html>').format(
        head=head, title=escape(title), icon=icon, css=BASE + css, body=body, attrs=body_attrs,
        scripts="".join('<script src="/static/{}"></script>'.format(s) for s in scripts))


def card(m):
    return ('<li><a class="card {status}" href="/a/{id}/"><div class="top"><span>{project}/</span><span>{type}{pub}</span></div>'
            '<h2 class="title">{title}</h2><span class="tag">{label}</span></a></li>').format(
        status=escape(m["status"]), id=escape(m["id"]), project=escape(m["project"]), type=escape(m["type"]),
        pub=" · public" if m.get("public") else "", title=escape(m["title"]), label=escape(m["label"].lower()))


def gallery_html(cards):
    waiting = any(m["status"] == "awaiting" for m in cards)
    if cards:
        body = '<ul class="grid">{}</ul>'.format("".join(card(m) for m in cards))
    else:
        body = '<p class="empty">Nothing here yet. Artifacts your agents publish show up here, newest first.</p>'
    # the gallery refreshes on its own; the favicon gets the ember badge while anything waits on you
    return document("artifact-hub", GALLERY, '<main><header><h1>artifact-hub</h1>{}</header>{}</main>'.format(THEME.format(cls=""), body),
                    icon=icon_for("awaiting" if waiting else "view"), head='<meta http-equiv="refresh" content="15">')


def shell_html(m, label, expiry):
    body = ('<header class="bar"><a href="/" aria-label="All artifacts">← artifacts</a><span id="title">{title}</span>'
            '<span id="status" data-status="{status}">{label}</span><span id="expiry">{expiry}</span>{theme}</header>'
            '<iframe id="artifact" title="{title}" sandbox="allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox"></iframe>'
            '<div class="expired"><p>This artifact has expired.</p></div>'
            '<div id="toast" class="toast" role="status" aria-live="polite"></div>').format(
        title=escape(m["title"]), status=escape(m["status"]), label=escape(label.lower()), expiry=escape(expiry),
        theme=THEME.format(cls=""))
    kind = "grill" if m["type"] == "grill" else "doc"
    return document(m["title"] + " · artifact-hub", SHELL, body, icon=icon_for(m["status"], kind), scripts=["shell.js"],
                    body_attrs=' data-icons="{}"'.format(kind))


def pair_html(nxt, error=""):
    group = '<span class="group"><span class="slot"></span><span class="slot"></span><span class="slot"></span></span>'
    body = (THEME.format(cls=" corner") + '<main class="center"><form class="stack" method="post" action="/pair">'
            "<h1>enter the pairing code</h1>"
            '<label class="code{err}">{g}<span class="dash"></span>{g}'
            '<input name="code" autocomplete="one-time-code" autocapitalize="characters" autocorrect="off" spellcheck="false" '
            'maxlength="12" aria-label="Pairing code" required></label>'
            '<input type="hidden" name="next" value="{nxt}">'
            '<p class="status{err}" role="status">{error}</p></form></main>').format(
        err=" is-error" if error else "", g=group, nxt=escape(nxt), error=escape(error))
    return document("Pairing", PAIR, body, scripts=["pair.js"])


def message_html(title, text):
    return document(title, MESSAGE, THEME.format(cls=" corner") + '<main><h1>{}</h1><p>{}</p><p><a href="/">All artifacts</a></p></main>'.format(
        escape(title), escape(text)))
