#!/usr/bin/env python3
"""artifact-hub: serves HTML artifacts that agents publish, privately to paired browsers or publicly under /p/.

It listens on two ports:
  public (7172)  the gallery, the artifacts and pairing. Route the tunnel here.
  agent  (7173)  the `artifact-hub` CLI (and grill.py) on this machine. It has no auth, so never route anything
                 to it. It refuses anything that looks like a browser: requests with an Origin or Sec-Fetch-*
                 header, or a Host that isn't loopback (DNS rebinding).

Artifacts:
  private  /a/<id>/       paired browsers only. A shell page holds the artifact in a sandboxed frame (opaque origin,
                          no network) and carries its saves and submits to the hub. Input reaches the agent only
                          through `wait`.
  public   /p/<pid>/      anyone with the link. The artifact itself, sandboxed: inline JS, no network, no forms.
                          <pid> is separate from <id> and changes each time an artifact is made public.

Lifecycle: only the latest version is kept. An artifact expires after 30 days unless told otherwise; then it's
hidden from the gallery and its links stop working, but its files stay for 90 more days, then it's deleted.

Data, in ARTIFACT_HUB_DATA (default ./data next to this file):
  artifacts/<id>/meta.json      {id, title, project, type, status, public, publicId, createdAt, updatedAt,
                                 expiresAt, expired, expiredAt, htmlVersion, rev, draftClient}
  artifacts/<id>/index.html     the artifact, as the agent sent it
  artifacts/<id>/data.json      {"value": ...} JSON the agent attached (optional)
  artifacts/<id>/drafts.json    {slot: value} saved by the page; never sent to the agent unasked
  artifacts/<id>/response.json  {value, via, submittedAt}: the latest submit
  devices.json                  {sha256 of a browser's cookie: {pairedAt, userAgent}}

Statuses: awaiting (the user's turn), responded (they submitted; `wait` returns it), working (the agent's turn),
view (nothing to answer), done. A submit is accepted while awaiting or responded.

Python 3.8+, standard library only.
"""
import datetime
import hashlib
import html
import json
import math
import os
import re
import secrets
import shutil
import signal
import sys
import threading
import time
import unicodedata

sys.dont_write_bytecode = True  # no __pycache__ next to the hub
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from pages import gallery_html, message_html, pair_html, shell_html

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
DATA = Path(os.environ.get("ARTIFACT_HUB_DATA", str(HERE / "data")))
ARTIFACTS = DATA / "artifacts"
DEVICES = DATA / "devices.json"
PUBLIC_URL = os.environ.get("ARTIFACT_HUB_PUBLIC_URL", "http://localhost:7172").rstrip("/")
HOST = os.environ.get("ARTIFACT_HUB_HOST", "127.0.0.1")  # 0.0.0.0 inside Docker
PUBLIC_PORT = int(os.environ.get("ARTIFACT_HUB_PUBLIC_PORT", "7172"))
AGENT_PORT = int(os.environ.get("ARTIFACT_HUB_AGENT_PORT", "7173"))

STATUSES = ("awaiting", "responded", "working", "view", "done")
LABELS = {"awaiting": "Awaiting your response", "responded": "Response sent", "working": "Agent working",
          "view": "Ready to view", "done": "Done"}
DEFAULT_DAYS = 30
KEEP_DAYS = 90  # after expiry, before the files are deleted
MAX_DAYS = 3650
MAX_HTML = 5_000_000  # bytes, UTF-8
MAX_DATA = 2_000_000  # bytes of JSON
MAX_DRAFT = 1_000_000  # per slot
MAX_SLOTS = 8
MAX_RESPONSE = 1_000_000
MAX_BODY = 8_000_000
MAX_TITLE = 200

COOKIE = "artifact_device"
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
CODE_MINUTES = 10
MAX_FAILURES = 5  # wrong codes per minute, from anyone, before /pair stops checking
ID_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"
ID = re.compile(r"[a-z0-9]{20}")
SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?")
SLOT = re.compile(r"[a-z0-9_-]{1,32}")
LOOPBACK = ("127.0.0.1", "localhost", "::1")

# One condition for everything: writers hold it and notify, so `wait` and the pages' event streams wake at once
COND = threading.Condition()
codes = {}  # pairing code -> expiry time. In memory: a restart drops unused codes
failures = []  # times of recent wrong codes


class Refused(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


# ---------- files ----------

def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def parse_stamp(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    """Write to a temp file, then rename it over the target, so readers never see half a file."""
    tmp = path.with_name(".{}.{}-{}.tmp".format(path.name, os.getpid(), threading.get_ident()))
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def write_text(path, text):
    tmp = path.with_name(".{}.{}-{}.tmp".format(path.name, os.getpid(), threading.get_ident()))
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


def read_optional(path, default=None):
    try:
        return read_json(path)
    except (OSError, ValueError):
        return default


def adir(aid):
    return ARTIFACTS / aid


def load_meta(aid):
    """meta.json for a valid, existing artifact id, else None."""
    if not isinstance(aid, str) or not ID.fullmatch(aid):
        return None
    m = read_optional(adir(aid) / "meta.json")
    if not (isinstance(m, dict) and m.get("id") == aid and m.get("status") in STATUSES
            and all(isinstance(m.get(k), str) for k in ("title", "project", "type", "createdAt"))):
        return None  # missing or hand-edited into something the hub can't show
    return m


def all_metas():
    out = []
    for f in ARTIFACTS.glob("*/meta.json"):
        m = load_meta(f.parent.name)
        if m:
            out.append(m)
    return out


def new_id():
    while True:
        aid = "".join(secrets.choice(ID_ALPHABET) for _ in range(20))
        if not adir(aid).exists():
            return aid


def full_state(m):
    """Everything about an artifact except its HTML."""
    d = adir(m["id"])
    data = read_optional(d / "data.json", {})
    return {"meta": m, "data": data.get("value") if isinstance(data, dict) else None,
            "drafts": read_optional(d / "drafts.json", {}) or {}, "response": read_optional(d / "response.json")}


def expiry_text(m, t=None):
    exp = parse_stamp(m.get("expiresAt"))
    if m.get("expired") or (exp and exp <= (t or now())):
        return "Expired"
    if not exp:
        return "Never expires"
    days = math.ceil((exp - (t or now())).total_seconds() / 86400)
    return "Expires within a day" if days <= 1 else "Expires in {} days".format(days)


def links(m):
    out = {"url": "{}/a/{}/".format(PUBLIC_URL, m["id"])}
    if m.get("public") and m.get("publicId"):
        out["publicUrl"] = "{}/p/{}/".format(PUBLIC_URL, m["publicId"])
    return out


def bump(m, *, touched=True):
    m["rev"] = int(m.get("rev") or 0) + 1
    if touched:
        m["updatedAt"] = stamp(now())
    write_json(adir(m["id"]) / "meta.json", m)
    COND.notify_all()


# ---------- validating what the agent sends ----------

def clean_text(value, field, limit):
    """One line of plain text: control and format characters dropped, whitespace collapsed."""
    if not isinstance(value, str):
        raise Refused(400, "{} must be a string".format(field))
    value = "".join(" " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else c
                    for c in value if unicodedata.category(c) != "Cf" or c == "\u200d")
    value = " ".join(value.split())
    if not value:
        raise Refused(400, "{} can't be empty".format(field))
    if len(value) > limit:
        raise Refused(400, "{} is longer than {} characters".format(field, limit))
    return value


def clean_slug(value, field):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise Refused(400, "{} must be lowercase letters, digits and dashes (1-80), like my-project".format(field))
    return value


def json_size(value):
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def parse_expires(value):
    """'30d', '<n>d' or 'never' -> datetime or None. Also takes a bare number of days."""
    if isinstance(value, int) and not isinstance(value, bool):
        days = value
    elif isinstance(value, str) and value.strip().lower() == "never":
        return None
    elif isinstance(value, str) and re.fullmatch(r"\s*\d{1,4}\s*d?\s*", value):
        days = int(re.sub(r"\D", "", value))
    else:
        raise Refused(400, "expires must be '<n>d' (for example 30d) or 'never'")
    if not 1 <= days <= MAX_DAYS:
        raise Refused(400, "expires must be between 1d and {}d, or 'never'".format(MAX_DAYS))
    return now() + datetime.timedelta(days=days)


def check_html(value):
    if not isinstance(value, str):
        raise Refused(400, "html must be a string")
    if "\x00" in value:
        raise Refused(400, "html contains NUL characters; is it really an HTML file?")
    if len(value.encode("utf-8", "surrogatepass")) > MAX_HTML:
        raise Refused(413, "html is larger than {} MB".format(MAX_HTML // 1_000_000))
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise Refused(400, "html isn't valid UTF-8 text")
    return value


def apply_changes(m, body, creating):
    """Validates the agent's fields and applies them to meta m. Returns (html or None, data present?, data)."""
    known = {"title", "project", "type", "html", "data", "public", "expires", "status"}
    unknown = sorted(set(body) - known)
    if unknown:
        raise Refused(400, "unknown field{} {}".format("s" if len(unknown) > 1 else "", ", ".join(unknown)))
    if creating or "title" in body:
        m["title"] = clean_text(body.get("title"), "title", MAX_TITLE)
    if creating or "project" in body:
        m["project"] = clean_slug(body.get("project"), "project")
    if creating or "type" in body:
        m["type"] = clean_slug(body.get("type", "page"), "type")
    page = check_html(body["html"]) if "html" in body else None
    if creating and page is None:
        raise Refused(400, "html is required")
    has_data = "data" in body
    if has_data and json_size(body["data"]) > MAX_DATA:
        raise Refused(413, "data is larger than {} MB".format(MAX_DATA // 1_000_000))
    if "public" in body:
        if not isinstance(body["public"], bool):
            raise Refused(400, "public must be true or false")
        if body["public"] and not m.get("public"):
            m["publicId"] = new_id()  # a fresh link each time it's made public
        if not body["public"]:
            m["publicId"] = None
        m["public"] = body["public"]
    if creating or "expires" in body:
        exp = parse_expires(body.get("expires", "{}d".format(DEFAULT_DAYS)))
        m["expiresAt"] = stamp(exp)
        m["expired"], m["expiredAt"] = False, None  # a new expiry brings an expired artifact back
    if "status" in body:
        if body["status"] not in STATUSES:
            raise Refused(400, "status must be one of: " + ", ".join(STATUSES))
        m["status"] = body["status"]
    elif creating:
        m["status"] = "view" if m.get("public") else "awaiting"
    elif (page is not None or has_data) and m.get("status") == "responded":
        m["status"] = "awaiting"  # new content after a response is the agent's reply: the user's turn again
    return page, has_data, body.get("data")


def create(body):
    with COND:
        aid = new_id()
        t = stamp(now())
        m = {"id": aid, "public": False, "publicId": None, "createdAt": t, "updatedAt": t, "rev": 0,
             "htmlVersion": 1, "draftClient": None}
        page, has_data, data = apply_changes(m, body, creating=True)
        d = adir(aid)
        d.mkdir(parents=True)
        write_text(d / "index.html", page)
        if has_data:
            write_json(d / "data.json", {"value": data})
        bump(m)
        return agent_view(m)


def change(aid, body):
    with COND:
        m = load_meta(aid)
        if not m:
            raise Refused(404, "no artifact with id {}".format(aid))
        page, has_data, data = apply_changes(m, body, creating=False)
        d = adir(aid)
        if page is not None:
            write_text(d / "index.html", page)
            m["htmlVersion"] = int(m.get("htmlVersion") or 0) + 1
        if has_data:
            write_json(d / "data.json", {"value": data})
        bump(m)
        return agent_view(m)


def remove(aid):
    with COND:
        if not load_meta(aid):
            raise Refused(404, "no artifact with id {}".format(aid))
        shutil.rmtree(str(adir(aid)), ignore_errors=True)
        COND.notify_all()
    return {"deleted": aid}


def agent_view(m):
    s = full_state(m)
    out = dict(m, **links(m))
    out.update(expired=not live(m), expiryText=expiry_text(m), data=s["data"], draft=s["drafts"].get("default"),
               drafts=s["drafts"], response=s["response"])
    return out


def summary(m):
    out = {k: m.get(k) for k in ("id", "title", "project", "type", "status", "public", "createdAt", "updatedAt",
                                 "expiresAt", "expired")}
    out.update(links(m), expired=not live(m), expiryText=expiry_text(m))
    return out


# ---------- expiry ----------

def sweep():
    """Expire what's due, and delete what expired more than KEEP_DAYS ago."""
    t = now()
    with COND:
        for m in all_metas():
            exp = parse_stamp(m.get("expiresAt"))
            if not m.get("expired") and exp and exp <= t:
                m["expired"], m["expiredAt"] = True, stamp(t)
                bump(m, touched=False)
                print("{} expired {} ({})".format(stamp(t), m["id"], m["title"]), flush=True)
            gone = parse_stamp(m.get("expiredAt"))
            if m.get("expired") and gone and gone + datetime.timedelta(days=KEEP_DAYS) <= t:
                shutil.rmtree(str(adir(m["id"])), ignore_errors=True)
                COND.notify_all()
                print("{} deleted {} after {} days expired".format(stamp(t), m["id"], KEEP_DAYS), flush=True)


def sweeper():
    while True:
        try:
            sweep()
        except Exception as e:  # never let one bad folder stop expiry for good
            print("{} sweep failed: {}".format(stamp(now()), e), flush=True)
        time.sleep(300)


def live(m):
    """Still served: not expired, even if the sweeper hasn't caught up yet."""
    exp = parse_stamp(m.get("expiresAt"))
    return not m.get("expired") and not (exp and exp <= now())


# ---------- HTTP helpers ----------

def reply(handler, code, body, ctype="application/json; charset=utf-8", headers=()):
    if not isinstance(body, bytes):
        body = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    for k, v in headers:
        handler.send_header(k, v)
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(body)


def read_body(handler):
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        raise Refused(400, "bad Content-Length")
    if length > MAX_BODY:
        raise Refused(413, "request body is larger than {} MB".format(MAX_BODY // 1_000_000))
    return handler.rfile.read(length) if length > 0 else b""


def read_json_body(handler):
    if (handler.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
        raise Refused(415, "send JSON with Content-Type: application/json")
    raw = read_body(handler)
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except UnicodeDecodeError:
        raise Refused(400, "request body isn't valid UTF-8")
    except ValueError as e:
        raise Refused(400, "invalid JSON: {}".format(e))
    if not isinstance(body, dict):
        raise Refused(400, "expected a JSON object")
    return body


def host_name(value):
    """The host part of a Host header: 'example.com:443' -> 'example.com', '[::1]:7173' -> '::1'."""
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else ""
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"


class Quiet(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass


# ---------- agent port ----------

class AgentHandler(Quiet):
    """The CLI's API. No auth, so it only answers what can't be a browser: browsers send Origin on cross-origin
    requests and Sec-Fetch-* on all of them, and a rebound DNS name still arrives with its own Host."""
    server_version = "artifact-hub"

    def guard(self):
        if self.headers.get("Origin") is not None or any(k.lower().startswith("sec-fetch-") for k in self.headers.keys()):
            raise Refused(403, "the agent port doesn't take browser requests")
        if host_name(self.headers.get("Host")) not in LOOPBACK:
            raise Refused(403, "the agent port only answers requests addressed to localhost")

    def handle_api(self):
        try:
            self.guard()
            url = urlsplit(self.path)
            parts, query = [p for p in url.path.split("/") if p], parse_qs(url.query)
            reply(self, 200, self.dispatch(parts, query))
        except Refused as e:
            reply(self, e.status, {"error": str(e)})

    do_GET = do_POST = do_PATCH = do_DELETE = handle_api

    def dispatch(self, parts, query):
        method = self.command
        if parts == ["api", "ping"] and method == "GET":
            return {"hub": "artifact-hub", "publicUrl": PUBLIC_URL, "devices": len(load_devices())}
        if parts == ["api", "pair-codes"] and method == "POST":
            return new_pair_code()
        if parts == ["api", "artifacts"]:
            if method == "GET":
                every = query.get("all", ["0"])[0] == "1"
                with COND:
                    items = [summary(m) for m in all_metas() if every or live(m)]
                return {"artifacts": sorted(items, key=lambda a: a["createdAt"] or "", reverse=True)}
            if method == "POST":
                return create(read_json_body(self))
        if len(parts) >= 3 and parts[:2] == ["api", "artifacts"]:
            aid = parts[2]
            if len(parts) == 3:
                if method == "GET":
                    with COND:
                        m = load_meta(aid)
                        if not m:
                            raise Refused(404, "no artifact with id {}".format(aid))
                        return agent_view(m)
                if method == "PATCH":
                    return change(aid, read_json_body(self))
                if method == "DELETE":
                    return remove(aid)
            if parts[3:] == ["wait"] and method == "GET":
                try:
                    seconds = max(0, min(60, int(query.get("timeout", ["25"])[0])))
                except ValueError:
                    raise Refused(400, "timeout must be a number of seconds")
                return wait_for_response(aid, seconds)
        raise Refused(404, "not found")


def wait_for_response(aid, seconds):
    """Long poll: returns as soon as the user has responded (or the artifact is done, expired or gone)."""
    deadline = time.time() + seconds
    with COND:
        while True:
            m = load_meta(aid)
            if not m:
                raise Refused(404, "no artifact with id {}".format(aid))
            if m["status"] in ("responded", "done") or not live(m) or time.time() >= deadline:
                return agent_view(m)
            COND.wait(max(0.05, min(5, deadline - time.time())))


def new_pair_code():
    with COND:
        t = time.time()
        for c in [c for c, exp in codes.items() if exp < t]:
            del codes[c]
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        codes[code] = t + CODE_MINUTES * 60
    return {"code": code, "pairUrl": PUBLIC_URL + "/pair", "expiresInMinutes": CODE_MINUTES}


# ---------- public port ----------

def load_devices():
    d = read_optional(DEVICES, {})
    return d if isinstance(d, dict) else {}


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Artifacts get no network at all, except Google Fonts in private ones. Inline scripts and styles are fine:
# the sandbox gives them an opaque origin, so they can't reach the hub's cookies or API.
ARTIFACT_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'{fonts_css}; "
                "img-src data: blob:; media-src data: blob:; font-src data:{fonts}; form-action 'none'; base-uri 'none'")
PUBLIC_CSP = "sandbox allow-scripts; " + ARTIFACT_CSP.format(fonts_css="", fonts="") + "; frame-ancestors 'none'"
# links with target="_blank" open in a new tab, outside the sandbox; the frame could navigate itself anyway
FRAME_CSP = ("sandbox allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox; "
             + ARTIFACT_CSP.format(fonts_css=" https://fonts.googleapis.com", fonts=" https://fonts.gstatic.com")
             + "; frame-ancestors 'self'")
HUB_CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
           "img-src 'self' data:; connect-src 'self'; frame-src 'self'; "
           "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")


def inject(page, script):
    """Puts a <script> first in the document: after <head>, else after <html> or the doctype, else at the top."""
    tag = "<script>" + script.replace("</script", "<\\/script") + "</script>"
    for pattern in (r"<head\b[^>]*>", r"<html\b[^>]*>", r"<!doctype[^>]*>"):
        m = re.search(pattern, page, re.I)
        if m:
            return page[:m.end()] + tag + page[m.end():]
    return tag + page


def script_json(value):
    """JSON that's safe inside a <script>."""
    return (json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def static_text(name):
    return (STATIC / name).read_text(encoding="utf-8")


def frame_state(m):
    s = full_state(m)
    return {"id": m["id"], "rev": m.get("rev"), "title": m["title"], "status": m["status"],
            "htmlVersion": m.get("htmlVersion"), "expired": not live(m), "expiryText": expiry_text(m),
            "data": s["data"], "drafts": s["drafts"], "draftClient": m.get("draftClient"), "response": s["response"]}


STATIC_TYPES = {".svg": "image/svg+xml", ".png": "image/png", ".js": "text/javascript; charset=utf-8"}
STATIC_FILES = {"favicon.svg", "favicon.png", "favicon-cooked.svg", "favicon-cooked.png", "shell.js", "pair.js", "theme.js"}
NEXT = re.compile(r"/(?:a/[a-z0-9]{20}/)?")


def safe_next(nxt):
    """Where to go after pairing: only the gallery or an artifact, so /pair can't be used to redirect anywhere."""
    return nxt if isinstance(nxt, str) and NEXT.fullmatch(nxt) else "/"


class PublicHandler(Quiet):
    server_version = "artifact-hub"

    def send_page(self, code, body, csp=HUB_CSP, headers=()):
        reply(self, code, body, "text/html; charset=utf-8", [("Content-Security-Policy", csp)] + list(headers))

    def not_found(self, title="Not found", text="There's nothing here."):
        self.send_page(404, message_page(title, text))

    def paired(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie") or "")
        except Exception:
            return False
        token = cookie.get(COOKIE)
        return bool(token) and token_hash(token.value) in load_devices()

    def same_origin(self):
        """A POST from a page on this hub. Browsers send Origin on POSTs; other clients may not, and they'd
        still need the cookie."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        own = {PUBLIC_URL.lower()}
        host = self.headers.get("Host")
        if host:
            own |= {"http://" + host.lower(), "https://" + host.lower()}
        return origin.lower() in own

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            self.route_get()
        except Refused as e:
            reply(self, e.status, {"error": str(e)})

    def do_POST(self):
        try:
            self.route_post()
        except Refused as e:
            reply(self, e.status, {"error": str(e)})

    def route_get(self):
        url = urlsplit(self.path)
        path = url.path
        if path.startswith("/static/") and path[8:] in STATIC_FILES:
            name = path[8:]
            return reply(self, 200, (STATIC / name).read_bytes(), STATIC_TYPES[Path(name).suffix])
        if path in ("/favicon.ico", "/favicon.svg"):
            return reply(self, 200, (STATIC / "favicon-cooked.svg").read_bytes(), "image/svg+xml")
        if path.startswith("/p/"):
            return self.public_artifact(path)
        if path == "/pair":
            nxt = safe_next(parse_qs(url.query).get("next", ["/"])[0])
            return self.send_page(200, pair_page(nxt))
        if not self.paired():
            if path.endswith("/events"):
                return reply(self, 401, {"error": "this browser isn't paired with the hub"})
            return reply(self, 303, b"", "text/plain", [("Location", "/pair?next=" + quote(safe_next(path)))])
        if path == "/":
            return self.send_page(200, gallery())
        m, rest = self.artifact_for(path)
        if not m:
            return
        if rest == "":
            return reply(self, 308, b"", "text/plain", [("Location", "/a/{}/".format(m["id"]))])
        if rest == "/":
            return self.send_page(200, shell_page(m))
        if rest == "/frame":
            if not live(m):
                return self.send_page(410, message_page("Expired", "This artifact has expired."))
            page = (adir(m["id"]) / "index.html").read_text(encoding="utf-8")
            return reply(self, 200, inject(page, static_text("artifact.js")).encode("utf-8"),
                         "text/html; charset=utf-8", [("Content-Security-Policy", FRAME_CSP)])
        if rest == "/events":
            return self.events(m["id"])
        self.not_found()

    def artifact_for(self, path):
        """(meta, rest of the path) for /a/<id>..., or (None, None) after answering 404/410."""
        match = re.fullmatch(r"/a/([a-z0-9]{20})(/.*)?", path)
        m = load_meta(match.group(1)) if match else None
        if not m:
            self.not_found()
            return None, None
        if not live(m) and (match.group(2) or "") in ("", "/"):
            self.send_page(410, message_page("Expired", "This artifact has expired, so its link no longer works."))
            return None, None
        return m, match.group(2) or ""

    def public_artifact(self, path):
        match = re.fullmatch(r"/p/([a-z0-9]{20})(/?)", path)
        m = None
        if match:
            with COND:
                m = next((x for x in all_metas() if x.get("public") and x.get("publicId") == match.group(1)), None)
        if not m:
            return self.not_found()
        if not live(m):
            return self.send_page(410, message_page("Expired", "This artifact has expired, so its link no longer works."))
        if not match.group(2):
            return reply(self, 308, b"", "text/plain", [("Location", "/p/{}/".format(match.group(1)))])
        data = full_state(m)["data"]
        page = (adir(m["id"]) / "index.html").read_text(encoding="utf-8")
        stub = static_text("artifact-public.js").replace("/*DATA*/null", script_json(data))
        reply(self, 200, inject(page, stub).encode("utf-8"), "text/html; charset=utf-8",
              [("Content-Security-Policy", PUBLIC_CSP), ("X-Robots-Tag", "noindex")])

    def events(self, aid):
        """Server-sent events: the artifact's state now and on every change."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last, sent_at = None, time.time()
        try:
            while True:
                with COND:
                    m = load_meta(aid)
                    if m and m.get("rev") == last:
                        COND.wait(15)
                        m = load_meta(aid)
                    state = frame_state(m) if m else None
                if not state:
                    self.wfile.write(b"event: gone\ndata: {}\n\n")
                    self.wfile.flush()
                    return
                if state["rev"] != last:
                    self.wfile.write("data: {}\n\n".format(json.dumps(state, ensure_ascii=False)).encode("utf-8"))
                    last, sent_at = state["rev"], time.time()
                elif time.time() - sent_at > 14:
                    self.wfile.write(b": keepalive\n\n")
                    sent_at = time.time()
                self.wfile.flush()
        except OSError:
            pass  # the page went away

    def route_post(self):
        path = urlsplit(self.path).path
        if path == "/pair":
            return self.pair()
        if not self.paired():
            raise Refused(401, "this browser isn't paired with the hub. Reload the page.")
        if not self.same_origin():
            raise Refused(403, "cross-origin request")
        match = re.fullmatch(r"/a/([a-z0-9]{20})/api/(save|submit)", path)
        if not match:
            raise Refused(404, "not found")
        body = read_json_body(self)
        with COND:
            m = load_meta(match.group(1))
            if not m:
                raise Refused(404, "this artifact no longer exists")
            if not live(m):
                raise Refused(410, "this artifact has expired")
            d = adir(m["id"])
            if match.group(2) == "save":
                slot, client = body.get("slot", "default"), body.get("client")
                if not isinstance(slot, str) or not SLOT.fullmatch(slot):
                    raise Refused(400, "bad draft slot")
                if "value" not in body or json_size(body["value"]) > MAX_DRAFT:
                    raise Refused(413, "a draft must be a JSON value under 1 MB")
                if m["status"] == "done":
                    raise Refused(409, "this artifact is done, so it doesn't keep drafts")
                drafts = read_optional(d / "drafts.json", {}) or {}
                drafts[slot] = body["value"]
                if len(drafts) > MAX_SLOTS:
                    raise Refused(400, "too many draft slots")
                write_json(d / "drafts.json", drafts)
                m["draftClient"] = client if isinstance(client, str) and len(client) <= 64 else None
                bump(m, touched=False)
            else:
                if m["status"] not in ("awaiting", "responded"):
                    raise Refused(409, "this artifact isn't taking responses right now")
                if "value" not in body or json_size(body["value"]) > MAX_RESPONSE:
                    raise Refused(413, "a response must be a JSON value under 1 MB")
                via = body.get("via") if body.get("via") in ("form", "sdk") else "sdk"
                write_json(d / "response.json", {"value": body["value"], "via": via, "submittedAt": stamp(now())})
                m["status"] = "responded"
                bump(m)
        reply(self, 200, {"ok": True})

    def pair(self):
        """Checks a pairing code. The page posts it with fetch and gets JSON; a plain form post gets HTML."""
        try:
            form = parse_qs(read_body(self).decode("utf-8", "replace"))
        except Refused as e:
            return reply(self, e.status, {"error": str(e)})
        nxt = safe_next(form.get("next", ["/"])[0])
        code = re.sub(r"[\s-]", "", form.get("code", [""])[0]).upper()
        wants_json = "application/json" in (self.headers.get("Accept") or "")

        def refuse(status, error):
            if wants_json:
                return reply(self, status, {"error": error})
            self.send_page(status, pair_page(nxt, error))

        if not self.same_origin():
            return refuse(403, "Pair from the hub's own page.")
        with COND:
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
            ua = clean_text(self.headers.get("User-Agent") or "unknown", "user agent", 10_000)[:200]
            devices[token_hash(token)] = {"pairedAt": stamp(now()), "userAgent": ua}
            write_json(DEVICES, devices)
        cookie = "{}={}; Path=/; Max-Age=315360000; HttpOnly; SameSite=Lax".format(COOKIE, token)
        if PUBLIC_URL.startswith("https://"):
            cookie += "; Secure"
        if wants_json:
            return reply(self, 200, {"next": nxt}, headers=[("Set-Cookie", cookie)])
        reply(self, 303, b"", "text/plain", [("Location", nxt), ("Set-Cookie", cookie)])


# ---------- pages ----------


def gallery():
    with COND:
        items = [m for m in all_metas() if live(m)]
    items.sort(key=lambda m: m.get("createdAt") or "", reverse=True)
    t = now()
    cards = [dict(m, label=LABELS.get(m["status"], m["status"]), expiryText=expiry_text(m, t)) for m in items]
    return gallery_html(cards).encode("utf-8")


def shell_page(m):
    return shell_html(m, LABELS.get(m["status"], m["status"]), expiry_text(m)).encode("utf-8")


def pair_page(nxt, error=""):
    return pair_html(nxt, error).encode("utf-8")


def message_page(title, text):
    return message_html(title, text).encode("utf-8")


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    public = Server((HOST, PUBLIC_PORT), PublicHandler)
    agent = Server((HOST, AGENT_PORT), AgentHandler)
    threading.Thread(target=agent.serve_forever, daemon=True).start()
    threading.Thread(target=sweeper, daemon=True).start()
    # in Docker this runs as PID 1, which ignores SIGTERM unless it handles it
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print("{} artifact hub: public port {} ({}), agent port {}, data in {}".format(
        stamp(now()), PUBLIC_PORT, PUBLIC_URL, AGENT_PORT, DATA), flush=True)
    public.serve_forever(poll_interval=0.25)


if __name__ == "__main__":
    main()
