"""The hub's own pages: the gallery, the shell around a private artifact, pairing, and messages.
Everything here is escaped; nothing from an artifact's HTML ever lands in these pages."""
from html import escape

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Pixelify+Sans:wght@500;600&family=Space+Grotesk:wght@400;500;600&display=swap" rel="stylesheet">')

BASE = """
:root { color-scheme: light; --paper: #fbf6ef; --card: #fffdfa; --edge: #eadbca; --edge-lo: #dcc6ae; --ink: #3b2418;
  --dim: #8a6b57; --ember: #dd5f1c; --ember-lo: #b2471a; --ember-hi: #ee8a4c; --ember-ink: #b2471a; --sage: #5f7d4a;
  --danger: #c4372a; --display: "Pixelify Sans", "Space Grotesk", system-ui, sans-serif; --text: "Space Grotesk", system-ui, sans-serif; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark; --paper: #1b1411; --card: #241b16; --edge: #3a2c23;
  --edge-lo: #110c0a; --ink: #f0e3d5; --dim: #a68d7b; --ember: #e2692a; --ember-lo: #9a3d14; --ember-hi: #f0955c;
  --ember-ink: #f29b64; --sage: #9cbf83; --danger: #ff7a66; } }
* { box-sizing: border-box; }
html { background: var(--paper); }
body { margin: 0; color: var(--ink); font: 400 16px/1.5 var(--text); -webkit-font-smoothing: antialiased; }
a { color: inherit; }
.bevel { box-shadow: 0 -3px 0 0 var(--edge), 0 3px 0 0 var(--edge-lo), -3px 0 0 0 var(--edge), 3px 0 0 0 var(--edge-lo); }
.bevel-hot { box-shadow: 0 -3px 0 0 var(--ember-hi), 0 3px 0 0 var(--ember-lo), -3px 0 0 0 var(--ember-hi), 3px 0 0 0 var(--ember-lo); }
"""

GALLERY = """
main { max-width: 1120px; margin: 0 auto; padding: 56px 24px 96px; }
h1 { margin: 0 0 6px; font: 600 clamp(40px, 8vw, 60px)/1 var(--display); }
h1 span { color: var(--ember); }
.sub { margin: 0 0 40px; color: var(--dim); }
.grid { list-style: none; margin: 0; padding: 0; display: grid; gap: 22px; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); }
.card { display: flex; flex-direction: column; gap: 14px; height: 100%; padding: 18px 18px 16px; background: var(--card); text-decoration: none; }
.card:hover .title { text-decoration: underline 2px var(--ember); text-underline-offset: 4px; }
.card:focus-visible { outline: 3px dashed var(--ink); outline-offset: 4px; }
.meta { display: flex; justify-content: space-between; gap: 12px; white-space: nowrap; font: 600 11px/1 var(--text); letter-spacing: .1em; text-transform: uppercase; color: var(--dim); }
.meta span:first-child { overflow: hidden; text-overflow: ellipsis; }
.title { margin: 0; font-size: 19px; font-weight: 600; line-height: 1.3; overflow-wrap: anywhere; flex: 1; }
.status { font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.status i { width: 8px; height: 8px; background: currentColor; }
.awaiting .status { color: var(--ember-ink); } .responded .status, .working .status { color: var(--sage); }
.view .status, .done .status { color: var(--dim); }
.foot { display: flex; justify-content: space-between; font-size: 13px; color: var(--dim); border-top: 2px dashed var(--edge); padding-top: 10px; }
.pub { font: 600 10px/1.9 var(--text); letter-spacing: .1em; text-transform: uppercase; color: var(--ember-ink); }
.empty { color: var(--dim); }
"""

SHELL = """
html, body { height: 100%; }
body { display: grid; grid-template-rows: auto 1fr; }
.bar { display: flex; align-items: center; gap: 14px; min-width: 0; padding: 8px 14px; border-bottom: 2px solid var(--edge); font-size: 14px; }
.bar a { flex: none; text-decoration: none; font-weight: 600; color: var(--ember-ink); }
.bar a:hover { text-decoration: underline; }
#title { flex: 1; min-width: 0; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#status { flex: none; font-weight: 600; color: var(--dim); }
#status[data-status="awaiting"] { color: var(--ember-ink); }
#expiry { flex: none; color: var(--dim); }
iframe { display: block; width: 100%; height: 100%; border: 0; background: #fff; }
.expired { display: none; place-content: center; text-align: center; color: var(--dim); }
body.is-expired iframe { display: none; } body.is-expired .expired { display: grid; }
.toast { position: fixed; left: 50%; bottom: 20px; transform: translate(-50%, 30px); opacity: 0; pointer-events: none;
  padding: 10px 16px; background: var(--ink); color: var(--paper); font-weight: 500; transition: .2s; max-width: calc(100% - 32px); }
.toast.is-on { opacity: 1; transform: translate(-50%, 0); }
.toast.is-error { background: var(--danger); color: #fff; }
@media (max-width: 600px) { #expiry { display: none; } }
"""

# one real input over six boxes, so paste, autofill and phone keyboards just work
PAIR = """
@keyframes blink { 0%, 33% { opacity: 1; } 34%, 100% { opacity: .3; } }
@keyframes caret { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } }
@keyframes shake { 0%, 100% { transform: none; } 20%, 60% { transform: translateX(-6px); } 40%, 80% { transform: translateX(6px); } }
.center { min-height: 100dvh; display: grid; place-items: center; padding: 32px 20px; text-align: center; }
.stack { display: grid; justify-items: center; gap: 28px; width: 100%; max-width: 600px; }
.center h1 { margin: 0; font: 600 clamp(26px, 6vw, 34px)/1.15 var(--display); letter-spacing: .01em; }
.code { position: relative; display: flex; align-items: center; gap: 14px; }
.code input { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; border: 0; padding: 0; font-size: 16px;
              color: transparent; background: transparent; caret-color: transparent; }
.group { display: flex; gap: 12px; }
.dash { width: 14px; height: 4px; background: var(--dim); }
.slot { width: 52px; height: 66px; display: grid; place-items: center; background: var(--card); font: 600 32px/1 var(--text); }
.slot.is-active { box-shadow: 0 -3px 0 0 var(--ember-hi), 0 3px 0 0 var(--ember-lo), -3px 0 0 0 var(--ember-hi), 3px 0 0 0 var(--ember-lo); }
.slot.is-active:empty::after { content: ""; width: 4px; height: 30px; background: var(--ember); animation: caret 1s steps(1) infinite; }
.code.is-error .slot { color: var(--danger); box-shadow: 0 -3px 0 0 var(--danger), 0 3px 0 0 var(--danger), -3px 0 0 0 var(--danger), 3px 0 0 0 var(--danger); }
.code.is-ok .slot { background: var(--ember); color: #fff; box-shadow: 0 -3px 0 0 var(--ember-hi), 0 3px 0 0 var(--ember-lo), -3px 0 0 0 var(--ember-hi), 3px 0 0 0 var(--ember-lo); }
.shake { animation: shake .32s steps(4) 1; }
.status { margin: 0; min-height: 26px; font-size: 15px; color: var(--dim); display: flex; align-items: center; gap: 10px; }
.status.is-error { color: var(--danger); }
.status.is-ok { color: var(--ember-ink); }
.loader { display: inline-flex; gap: 4px; }
.loader i { width: 6px; height: 6px; background: currentColor; opacity: .3; animation: blink .9s steps(1) infinite; }
.loader i:nth-child(2) { animation-delay: .3s; } .loader i:nth-child(3) { animation-delay: .6s; }
@media (max-width: 420px) { .code { gap: 8px; } .group { gap: 8px; } .dash { width: 8px; } .slot { width: 44px; height: 58px; font-size: 27px; } }
@media (prefers-reduced-motion: reduce) { .shake { animation: none; } }
"""

MESSAGE = """
main { min-height: 100dvh; display: grid; place-content: center; gap: 12px; padding: 32px 20px; text-align: center; }
h1 { margin: 0; font: 600 34px/1.1 var(--display); }
p { margin: 0; color: var(--dim); }
p a { color: var(--ember-ink); }
"""


def document(title, css, body, icon="favicon-cooked", head="", scripts=()):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">{head}<title>{title}</title>'
            '<link rel="icon" type="image/png" sizes="32x32" href="/static/{icon}.png">'
            '<link rel="icon" type="image/svg+xml" sizes="any" href="/static/{icon}.svg">{fonts}'
            '<style>{css}</style></head><body>{body}{scripts}</body></html>').format(
        head=head, title=escape(title), icon=icon, fonts=FONTS, css=BASE + css, body=body,
        scripts="".join('<script src="/static/{}"></script>'.format(s) for s in scripts))


def card(m):
    hot = m["status"] == "awaiting"
    return ('<li><a class="card {status} {bevel}" href="/a/{id}/"><div class="meta"><span>{project}</span><span>{type}</span></div>'
            '<h2 class="title">{title}</h2><div class="status"><i></i>{label}</div>'
            '<div class="foot"><span>{expiry}</span>{pub}</div></a></li>').format(
        status=escape(m["status"]), bevel="bevel-hot" if hot else "bevel", id=escape(m["id"]),
        project=escape(m["project"]), type=escape(m["type"]), title=escape(m["title"]), label=escape(m["label"]),
        expiry=escape(m["expiryText"]), pub='<span class="pub">Public</span>' if m.get("public") else "")


def gallery_html(cards):
    waiting = sum(1 for m in cards if m["status"] == "awaiting")
    if cards:
        sub = "{} artifact{}{}".format(len(cards), "" if len(cards) == 1 else "s",
                                       " · {} waiting on you".format(waiting) if waiting else "")
        body = '<p class="sub">{}</p><ul class="grid">{}</ul>'.format(sub, "".join(card(m) for m in cards))
    else:
        body = '<p class="sub empty">Nothing here yet. Artifacts your agents publish show up here, newest first.</p>'
    # the gallery refreshes on its own; the favicon is the campfire while anything waits on you
    return document("Artifacts", GALLERY, '<main><h1>Artifact <span>hub</span></h1>{}</main>'.format(body),
                    icon="favicon" if waiting else "favicon-cooked", head='<meta http-equiv="refresh" content="15">')


def shell_html(m, label, expiry):
    body = ('<header class="bar"><a href="/" aria-label="All artifacts">← Artifacts</a><span id="title">{title}</span>'
            '<span id="status" data-status="{status}">{label}</span><span id="expiry">{expiry}</span></header>'
            '<iframe id="artifact" title="{title}" sandbox="allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox"></iframe>'
            '<div class="expired"><p>This artifact has expired.</p></div>'
            '<div id="toast" class="toast" role="status" aria-live="polite"></div>').format(
        title=escape(m["title"]), status=escape(m["status"]), label=escape(label), expiry=escape(expiry))
    return document(m["title"] + " · Artifact hub", SHELL, body,
                    icon="favicon" if m["status"] == "awaiting" else "favicon-cooked", scripts=["shell.js"])


def pair_html(nxt, error=""):
    group = '<span class="group"><span class="slot bevel"></span><span class="slot bevel"></span><span class="slot bevel"></span></span>'
    body = ('<main class="center"><form class="stack" method="post" action="/pair">'
            "<h1>Enter the pairing code</h1>"
            '<label class="code{err}">{g}<span class="dash"></span>{g}'
            '<input name="code" autocomplete="one-time-code" autocapitalize="characters" autocorrect="off" spellcheck="false" '
            'maxlength="12" aria-label="Pairing code" required></label>'
            '<input type="hidden" name="next" value="{nxt}">'
            '<p class="status{err}" role="status">{error}</p></form></main>').format(
        err=" is-error" if error else "", g=group, nxt=escape(nxt), error=escape(error))
    return document("Pairing", PAIR, body, scripts=["pair.js"])


def message_html(title, text):
    return document(title, MESSAGE, '<main><h1>{}</h1><p>{}</p><p><a href="/">All artifacts</a></p></main>'.format(
        escape(title), escape(text)))
