#!/usr/bin/env python3
"""grill-me-with-ui: the CLI the agent runs, and the local server the page talks to.

Both meet in .grill/ in the folder the agent works in:

  .grill/config.json                  {"theme": "system", "idleTimeoutMinutes": 120, "useHub": true, "artifactHubUrl": "..."}
  .grill/sessions/<uuid>/session.json {id, title, status, updatedAt, server: {port, pid}, artifact: {url, id, page}, openRound}
  .grill/sessions/<uuid>/round-N.json {"questions": [{id, title, body, choices, answer}]}

The status says whose turn it is, and only that side writes:
  agent_writing_round  the agent, through `round`, `finish`
  user_writing_round   the server, saving each answer as the user gives it. Until the user submits,
                       those answers are drafts: `wait` returns only after the submit
  session_finished     nobody

If an artifact hub (scripts/artifact-hub in the repo) answers at artifactHubUrl when the session starts, the
session is an artifact there, of type "grill", instead of a local server: the page is published once, each
round goes into the artifact's data, and `wait` copies the user's answers (drafts included) back into .grill/.
The choice is made once, at `start`, and never changes for that session. Sessions started on the older grill
hub (session.json has "hub" instead of "artifact") keep talking to it, at hubUrl, until they're finished.

`finish` during the user's turn records the open round, and the first round of the next session in the
folder gets the drafts back for the questions it asks again, so restarting a session doesn't lose them.

Commands: start --title "..." [--local], round <path>, wait [--timeout SECONDS], finish, status, connect.
Python 3.8+, standard library only.
"""
import argparse
import base64
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AGENT, USER, FINISHED = "agent_writing_round", "user_writing_round", "session_finished"
PAGE_DIR = Path(__file__).resolve().parent / "page"
HUB_URL = "http://127.0.0.1:7171"  # the older grill hub, only for sessions started on it
ARTIFACT_HUB_URL = "http://127.0.0.1:7173"
DEFAULT_CONFIG = {"theme": "system", "idleTimeoutMinutes": 120, "useHub": True, "artifactHubUrl": ARTIFACT_HUB_URL}
HUB_RETRY_SECONDS = 300
THEMES = ("system", "light", "dark")
PORTS = range(4747, 4800)
CMD = "{} {}".format("python" if os.name == "nt" else "python3", Path(__file__).resolve())
ROUND_EXAMPLE = """{
  "questions": [
    {
      "title": "Primary user",
      "body": "Who is this for? Markdown is fine.",
      "choices": ["Paying customers", "Internal team only", "Both"]
    }
  ]
}"""
# localhost only: skip any HTTP proxy from the environment
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class GrillError(Exception):
    pass


# ---------- files ----------

def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path):
    # Windows can refuse a read while another process swaps the file in, so retry briefly
    for _ in range(20):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            time.sleep(0.05)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    """Write to a temp file, then rename it over the target, so readers never see half a file."""
    tmp = path.with_name(".{}.{}-{}.tmp".format(path.name, os.getpid(), threading.get_ident()))
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for _ in range(20):
        try:
            return os.replace(str(tmp), str(path))
        except PermissionError:
            time.sleep(0.05)
    os.replace(str(tmp), str(path))


def grill_dir():
    return Path.cwd() / ".grill"


def ensure_grill_dir():
    gdir = grill_dir()
    (gdir / "sessions").mkdir(parents=True, exist_ok=True)
    if not (gdir / ".gitignore").exists():
        (gdir / ".gitignore").write_text("*\n", encoding="utf-8")
    if not (gdir / "config.json").exists():
        write_json(gdir / "config.json", DEFAULT_CONFIG)
    return gdir


def load_config(gdir):
    cfg = dict(DEFAULT_CONFIG)
    try:
        cfg.update(read_json(gdir / "config.json"))
    except (OSError, ValueError):
        pass
    if cfg["theme"] not in THEMES:
        cfg["theme"] = "system"
    if not isinstance(cfg["idleTimeoutMinutes"], (int, float)) or cfg["idleTimeoutMinutes"] <= 0:
        cfg["idleTimeoutMinutes"] = DEFAULT_CONFIG["idleTimeoutMinutes"]
    if not isinstance(cfg["useHub"], bool):
        cfg["useHub"] = DEFAULT_CONFIG["useHub"]
    for key, default in (("hubUrl", HUB_URL), ("artifactHubUrl", ARTIFACT_HUB_URL)):
        if not isinstance(cfg.get(key), str) or not cfg[key].strip():
            cfg[key] = default
        cfg[key] = cfg[key].strip().rstrip("/")
    return cfg


def session_file(sdir):
    return sdir / "session.json"


def update_session(sdir, **changes):
    s = read_json(session_file(sdir))
    s.update(changes, updatedAt=now())
    write_json(session_file(sdir), s)
    return s


def active_session():
    """The session in this folder that isn't finished. `start` makes sure there's at most one."""
    found = []
    for f in (grill_dir() / "sessions").glob("*/session.json"):
        try:
            s = read_json(f)
        except (OSError, ValueError):
            continue
        if s.get("status") != FINISHED:
            found.append((s.get("updatedAt", ""), f.parent))
    return max(found)[1] if found else None


def require_active():
    sdir = active_session()
    if not sdir:
        raise GrillError('there is no active grill session in this folder.\n\n'
                         'Start one with:\n  {} start --title "<session title>"'.format(CMD))
    return sdir


def round_count(sdir):
    nums = [int(m.group(1)) for m in (re.fullmatch(r"round-(\d+)\.json", p.name) for p in sdir.iterdir()) if m]
    return max(nums, default=0)


def round_file(sdir, n):
    return sdir / "round-{}.json".format(n)


def latest_questions(sdir):
    n = round_count(sdir)
    return read_json(round_file(sdir, n))["questions"] if n else []


def copy_answers(sdir, n, questions):
    """Write the answers in `questions` (from the hub) into round n in .grill/, if they changed."""
    answers = {q["id"]: q.get("answer") for q in questions}
    data = read_json(round_file(sdir, n))
    if all(q.get("answer") == answers.get(q["id"]) for q in data["questions"]):
        return
    for q in data["questions"]:
        q["answer"] = answers.get(q["id"])
    write_json(round_file(sdir, n), data)


# ---------- server process (started and found by the CLI) ----------

def server_url(s):
    if s.get("artifact"):
        return s["artifact"]["page"]
    if s.get("hub"):
        return s["hub"]["page"]
    return "http://localhost:{}/".format(s["server"]["port"])


def ping(s):
    port = (s.get("server") or {}).get("port")
    if not port:
        return False
    try:
        with LOCAL.open("http://127.0.0.1:{}/api/ping".format(port), timeout=1) as r:
            return json.loads(r.read().decode()).get("id") == s["id"]
    except Exception:
        return False


def ensure_server(sdir, open_browser=False):
    """Start the session's server in the background unless it's already answering."""
    s = read_json(session_file(sdir))
    if ping(s):
        return s
    args = [sys.executable, str(Path(__file__).resolve()), "serve", str(sdir)]
    if open_browser:
        args.append("--open")
    # the server must not hold on to the agent's terminal, or the agent's command never returns
    log = open(str(sdir / "server.log"), "ab")
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": log, "stderr": log, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)
    log.close()
    deadline = time.time() + 10
    while time.time() < deadline:
        time.sleep(0.1)
        s = read_json(session_file(sdir))
        if ping(s):
            return s
    raise GrillError("the server didn't start. Its log is in {}".format(sdir / "server.log"))


def stop_server(sdir, s):
    """Ask a running server to finish the session itself, and wait until it's gone."""
    try:
        req = urllib.request.Request("http://127.0.0.1:{}/api/finish".format(s["server"]["port"]),
                                     data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        LOCAL.open(req, timeout=2).close()
    except Exception:
        update_session(sdir, status=FINISHED)
    deadline = time.time() + 5
    while time.time() < deadline and ping(s):
        time.sleep(0.1)


# ---------- the hub (when the session uses one) ----------

class HubDown(GrillError):
    pass


def hub_call(base, method, path, body=None, timeout=5):
    """One request to the hub's agent port. Returns (HTTP status, JSON body); raises HubDown if unreachable."""
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with LOCAL.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {}
    except (OSError, ValueError) as e:
        raise HubDown("the hub at {} isn't answering ({})".format(base, e))


def project_name():
    """The git remote's repo name, or the folder name, as a URL-friendly slug."""
    name = Path.cwd().name
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, timeout=3).stdout.strip()
        if url:
            name = re.sub(r"\.git$", "", url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1])
    except (OSError, subprocess.SubprocessError):
        pass
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"


def hub_sync(sdir):
    """Push the whole session to the hub. The hub keeps anything newer it already has (the user's answers)."""
    s = read_json(session_file(sdir))
    rounds = [read_json(round_file(sdir, n)) for n in range(1, round_count(sdir) + 1)]
    code, state = hub_call(s["hub"]["url"], "PUT", "/api/sessions/" + s["id"],
                           {"project": s["hub"]["project"], "title": s["title"], "status": s["status"], "rounds": rounds})
    if code != 200:
        raise GrillError("the grill hub refused the session: {}".format(state.get("error", code)))
    return state


def flush_finished(gdir):
    """Tell the hub about sessions here that were finished while it was down."""
    for f in (gdir / "sessions").glob("*/session.json"):
        try:
            if read_json(f).get("hubPending"):
                hub_sync(f.parent)
                update_session(f.parent, hubPending=None)
        except (OSError, ValueError, GrillError):
            pass


def hub_down_message(e):
    return ("{}.\n\nThis session runs on the hub, so it can't continue until the hub is back. Start it "
            "(for example `docker compose up -d` in scripts/artifact-hub), then run:\n  {} wait".format(e, CMD))


# ---------- the artifact hub (when the session is an artifact there) ----------

def find_artifact_hub(cfg):
    """The artifact hub's info if one answers at artifactHubUrl, else None."""
    try:
        code, info = hub_call(cfg["artifactHubUrl"], "GET", "/api/ping", timeout=1)
    except HubDown:
        return None
    return info if code == 200 and info.get("hub") == "artifact-hub" else None


def artifact_page(theme):
    """The page as one self-contained file: the artifact runs sandboxed, with no network, so the scripts and the
    cooked patty go inline. The hub's frame shows the favicon, so the page's own icon links go."""
    page = (PAGE_DIR / "index.html").read_text(encoding="utf-8").replace("{{theme}}", theme)
    page = re.sub(r'<link rel="icon"[^>]*>\n?', "", page)
    for name in ("pixel.js", "grill.js", "app.js"):
        js = (PAGE_DIR / name).read_text(encoding="utf-8")
        if name == "app.js":
            svg = base64.b64encode((PAGE_DIR / "favicon-cooked.svg").read_bytes()).decode("ascii")
            js = js.replace('src="favicon-cooked.svg"', 'src="data:image/svg+xml;base64,{}"'.format(svg))
        tag = '<script src="{}"></script>'.format(name)
        if tag not in page:
            raise GrillError("page/index.html doesn't load {} the way artifact_page expects".format(name))
        page = page.replace(tag, "<script>\n{}\n</script>".format(js.replace("</script", "<\\/script")))
    return page


def artifact_status(status):
    return {AGENT: "working", USER: "awaiting", FINISHED: "done"}[status]


def artifact_push(sdir):
    """Send the session's state to the hub: the artifact's data is the same state the local server serves."""
    s = read_json(session_file(sdir))
    data = {"id": s["id"], "title": s["title"], "status": s["status"], "round": round_count(sdir),
            "questions": latest_questions(sdir)}
    code, info = hub_call(s["artifact"]["url"], "PATCH", "/api/artifacts/" + s["artifact"]["id"],
                          {"data": data, "status": artifact_status(s["status"])})
    if code != 200:
        raise GrillError("the artifact hub refused the update: {}".format(info.get("error", code)))
    return info


def apply_answers(sdir, n, answers):
    """Write answers ({id: {choice, text}}, from the hub) into round n in .grill/, keeping only valid ones.
    Returns True if anything changed."""
    data = read_json(round_file(sdir, n))
    changed = False
    for q in data["questions"]:
        a = answers.get(q["id"]) if isinstance(answers, dict) else None
        try:
            a = clean_answer(q, a) if a is not None else None
        except ValueError:
            continue
        if q.get("answer") != a:
            q["answer"], changed = a, True
    if changed:
        write_json(round_file(sdir, n), data)
    return changed


def artifact_poll(sdir, s, n, seconds):
    """Wait up to `seconds` on the hub. Copies the user's drafts for round n into .grill/, and once they submit,
    their answers, handing the turn back to the agent. Returns True when the round is in."""
    code, a = hub_call(s["artifact"]["url"], "GET", "/api/artifacts/{}/wait?timeout={}".format(s["artifact"]["id"], seconds),
                       timeout=seconds + 15)
    if code == 404:
        raise GrillError("the session's artifact is gone from the artifact hub (deleted?). Finish this session with "
                         "`{} finish` and start a new one.".format(CMD))
    if code != 200:
        raise GrillError("the artifact hub answered {}: {}".format(code, a.get("error", "")))
    if a.get("expired"):
        raise GrillError("the session's artifact expired on the hub. Finish this session with `{} finish`.".format(CMD))
    if a["status"] == "done":
        raise GrillError("the session was finished on the hub, so there are no answers to wait for")
    draft = a.get("draft")
    if isinstance(draft, dict) and draft.get("round") == n:
        apply_answers(sdir, n, draft.get("answers"))
    if a["status"] != "responded":
        if a["status"] != "awaiting":
            artifact_push(sdir)  # the hub has an older state than .grill/: send it again
        return False
    sent = (a.get("response") or {}).get("value")
    if not (isinstance(sent, dict) and sent.get("round") == n and isinstance(sent.get("answers"), list)):
        artifact_push(sdir)  # a submit for some other round: ask for this one again
        return False
    apply_answers(sdir, n, {x.get("id"): x for x in sent["answers"] if isinstance(x, dict)})
    update_session(sdir, status=AGENT)
    try:
        artifact_push(sdir)
    except HubDown:
        pass  # the answers are in .grill/; the page catches up with the next round
    return True


# ---------- the agent's round file ----------

HINTS = {
    "recommended": 'put the recommended answer first in "choices" instead',
    "id": "question IDs are assigned for you",
    "answer": "answers are filled in by the page",
}


def validate_round(data, path):
    problems = []
    if not isinstance(data, dict):
        raise GrillError('{} must be a JSON object like this:\n{}'.format(path, ROUND_EXAMPLE))
    for key in data:
        if key != "questions":
            problems.append('unknown top-level field "{}"'.format(key))
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        problems.append('"questions" must be a list with at least one question')
        questions = []
    for i, q in enumerate(questions):
        where = "questions[{}]".format(i)
        if not isinstance(q, dict):
            problems.append("{} must be an object with title, body and choices".format(where))
            continue
        for key in ("title", "body", "choices"):
            if key not in q:
                problems.append('{} is missing "{}"'.format(where, key))
        for key in q:
            if key not in ("title", "body", "choices"):
                hint = HINTS.get(key)
                problems.append('{} has unknown field "{}"{}'.format(where, key, " ({})".format(hint) if hint else ""))
        if "title" in q and (not isinstance(q["title"], str) or not q["title"].strip()):
            problems.append('{}.title must be a non-empty string'.format(where))
        if "body" in q and not isinstance(q["body"], str):
            problems.append('{}.body must be a string (markdown is fine)'.format(where))
        if "choices" in q:
            c = q["choices"]
            if not isinstance(c, list) or not c or not all(isinstance(x, str) and x.strip() for x in c):
                problems.append('{}.choices must be a list of at least one non-empty string; '
                                'the first one is your recommendation'.format(where))
    if problems:
        raise GrillError("{} has {} problem{}:\n{}\n\nExpected shape:\n{}".format(
            path, len(problems), "" if len(problems) == 1 else "s",
            "\n".join("  - " + p for p in problems), ROUND_EXAMPLE))
    return [{"id": "Q{}".format(i + 1), "title": q["title"].strip(), "body": q["body"].strip(),
             "choices": [c.strip() for c in q["choices"]], "answer": None}
            for i, q in enumerate(questions)]


def format_answers(questions):
    lines = []
    for q in questions:
        a = q.get("answer") or {}
        choice, text = a.get("choice"), (a.get("text") or "").strip()
        parts = []
        if isinstance(choice, int) and 0 <= choice < len(q["choices"]):
            parts.append(q["choices"][choice].rstrip(".") if text else q["choices"][choice])
        if text:
            text = text.replace("\n", "\n    ")
            parts.append("Note: " + text if parts else text)
        lines.append("{}: {}".format(q["id"], ". ".join(parts) if parts else "(skipped)"))
    return "\n".join(lines)


def carry_drafts(sdir, questions):
    """Fill in the draft answers the user left in the round still open when this folder's last session was
    finished, for the questions asked again (same title). Choices carry over only if they're unchanged.
    Returns how many answers carried over. They stay drafts: the user still submits the round."""
    previous = []
    for f in sdir.parent.glob("*/session.json"):
        try:
            s = read_json(f)
        except (OSError, ValueError):
            continue
        if f.parent != sdir and s.get("status") == FINISHED:
            previous.append((s.get("updatedAt", ""), f.parent, s.get("openRound")))
    if not previous:
        return 0
    _, pdir, n = max(previous, key=lambda p: p[0])
    try:
        old = {q["title"]: q for q in read_json(round_file(pdir, n))["questions"] if q.get("answer")} if n else {}
    except (OSError, ValueError, KeyError):
        return 0
    carried = 0
    for q in questions:
        o = old.get(q["title"])
        if not o:
            continue
        choice = o["answer"].get("choice") if o["choices"] == q["choices"] else None
        text = o["answer"].get("text") or ""
        if choice is not None or text.strip():
            q["answer"] = {"choice": choice, "text": text}
            carried += 1
    return carried


# ---------- commands ----------

def cmd_start(args):
    title = args.title.strip()
    if not title:
        raise GrillError("--title can't be empty")
    gdir = ensure_grill_dir()
    current = active_session()
    if current:
        s = read_json(session_file(current))
        url = server_url(s) if s.get("artifact") or s.get("hub") or ping(s) else "(server stopped; `status` restarts it)"
        raise GrillError(
            "a grill session is already active in this folder.\n"
            "  Title:  {}\n  Status: {} (round {})\n  URL:    {}\n\n"
            "To end it, run:\n  {} finish\n\nThen run start again.".format(
                s["title"], s["status"], round_count(current), url, CMD))
    cfg = load_config(gdir)
    hub = find_artifact_hub(cfg) if cfg["useHub"] and not args.local else None
    flush_finished(gdir)
    sid = str(uuid.uuid4())
    sdir = gdir / "sessions" / sid
    sdir.mkdir(parents=True)
    session = {"id": sid, "title": title, "status": AGENT, "updatedAt": now(), "server": None}
    write_json(session_file(sdir), session)
    open_browser = not os.environ.get("GRILL_NO_BROWSER")
    if hub:
        try:
            code, a = hub_call(cfg["artifactHubUrl"], "POST", "/api/artifacts", {
                "title": title, "project": project_name(), "type": "grill", "html": artifact_page(cfg["theme"]),
                "data": {"id": sid, "title": title, "status": AGENT, "round": 0, "questions": []}, "status": "working"},
                timeout=15)
            if code != 200:
                raise GrillError("the artifact hub refused the session: {}".format(a.get("error", code)))
        except GrillError:
            shutil.rmtree(str(sdir), ignore_errors=True)
            raise
        session = update_session(sdir, artifact={"url": cfg["artifactHubUrl"], "id": a["id"], "page": a["url"]})
        if open_browser:
            webbrowser.open(a["url"])
        mode = "on the artifact hub"
        if not hub.get("devices"):
            mode += ("\n  No browser is paired with the hub yet. Run `{} connect` and show the user "
                     "the pairing code it prints.".format(CMD))
    else:
        session = ensure_server(sdir, open_browser=open_browser)
        mode = "locally"
        if cfg["useHub"] and not args.local:
            mode += " (no artifact hub answered at {})".format(cfg["artifactHubUrl"])
    print("Grill session started: {}\n  URL: {}\n  Runs {}\n\n"
          "Next: write the first round to a JSON file and run:\n  {} round <path>".format(
              title, server_url(session), mode, CMD))


def cmd_round(args):
    sdir = require_active()
    s = read_json(session_file(sdir))
    if s["status"] == USER:
        raise GrillError("round {} is still open in the browser: it's the user's turn.\n\n"
                         "Get their answers with:\n  {} wait".format(round_count(sdir), CMD))
    path = Path(args.path)
    if not path.is_file():
        raise GrillError("{} doesn't exist. Write the round there first.".format(path))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise GrillError("{} is not valid JSON: {}\n\nExpected shape:\n{}".format(path, e, ROUND_EXAMPLE))
    questions = validate_round(data, path)
    if not s.get("hub") and not s.get("artifact"):
        s = ensure_server(sdir)
    n = round_count(sdir) + 1
    carried = carry_drafts(sdir, questions) if n == 1 else 0
    write_json(round_file(sdir, n), {"questions": questions})
    update_session(sdir, status=USER)
    if s.get("artifact"):
        try:
            artifact_push(sdir)
        except HubDown as e:
            raise GrillError("round {} is saved, but it didn't reach the hub: {}".format(n, hub_down_message(e)))
    elif s.get("hub"):
        try:
            hub_sync(sdir)
        except HubDown as e:
            # the round is saved; `wait` pushes it once the hub is back
            raise GrillError("round {} is saved, but it didn't reach the hub: {}".format(n, hub_down_message(e)))
    print("Round {} sent: {} question{}. The user answers it at {}\n{}\n"
          "Next, run this and don't end your turn until it prints the answers:\n  {} wait\n"
          "(Add --timeout <seconds> if your shell tool has a time limit.)".format(
              n, len(questions), "" if len(questions) == 1 else "s", server_url(s),
              "The user's draft answers to {} of these questions carried over from the previous session.\n".format(carried)
              if carried else "", CMD))


def hub_poll(sdir, s, n, seconds):
    """Wait up to `seconds` on the hub. Copies the user's draft answers to round n into .grill/, so a hub that
    loses the session gets them back, and hands the turn back to the agent once the user submits."""
    code, state = hub_call(s["hub"]["url"], "GET", "/api/sessions/{}?round={}&wait={}".format(s["id"], n, seconds),
                           timeout=seconds + 10)
    if code == 404 or (code == 200 and state["round"] < n):
        hub_sync(sdir)  # the hub lost the session or missed a round: send it again
    elif code != 200:
        raise GrillError("the grill hub answered {}: {}".format(code, state.get("error", "")))
    elif state["status"] == FINISHED:
        raise GrillError("the session was finished on the hub, so there are no answers to wait for")
    elif state["round"] == n:
        copy_answers(sdir, n, state["questions"])
        if state["status"] == AGENT:
            update_session(sdir, status=AGENT)


def cmd_wait(args):
    sdir = require_active()
    checked, deadline = 0, time.time() + args.timeout if args.timeout else None
    warned = False
    while True:
        s = read_json(session_file(sdir))
        if s["status"] == FINISHED:
            raise GrillError("the session was finished, so there are no answers to wait for")
        if s["status"] == AGENT:
            n = round_count(sdir)
            if not n:
                raise GrillError("no round has been sent yet. Write one and run:\n  {} round <path>".format(CMD))
            print(format_answers(latest_questions(sdir)))
            return
        # a clean exit before the agent's shell tool kills us, so the agent knows to run us again
        if deadline and time.time() >= deadline:
            print("Still waiting: the user hasn't submitted round {} yet. This is normal.\n\n"
                  "Run the same command again now, and don't end your turn:\n"
                  "  {} wait --timeout {}".format(round_count(sdir), CMD, args.timeout))
            return 2
        if s.get("hub") or s.get("artifact"):
            seconds = 25 if not deadline else max(1, min(25, int(deadline - time.time())))
            try:
                if s.get("artifact"):
                    artifact_poll(sdir, s, round_count(sdir), seconds)
                else:
                    hub_poll(sdir, s, round_count(sdir), seconds)
            except HubDown as e:
                # no fallback to a local server: keep trying for a while, then stop and say why.
                # The outage start is saved, so repeated `wait --timeout` runs share one retry window
                down_since = s.get("hubDownSince") or update_session(sdir, hubDownSince=time.time())["hubDownSince"]
                if time.time() - down_since > HUB_RETRY_SECONDS:
                    raise GrillError(hub_down_message(e))
                if not warned:
                    print("{}. Retrying for up to {} minutes.".format(e, HUB_RETRY_SECONDS // 60), file=sys.stderr, flush=True)
                    warned = True
                time.sleep(3)
                continue
            if s.get("hubDownSince"):
                update_session(sdir, hubDownSince=None)
                print("The hub is back.", file=sys.stderr, flush=True)
            warned = False
            continue
        # the server may have shut down while idle; the user needs it to submit
        if time.time() - checked > 10:
            ensure_server(sdir)
            checked = time.time()
        time.sleep(1)


def cmd_finish(args):
    sdir = require_active()
    s = read_json(session_file(sdir))
    # remember a round the user was still answering, so a session started again here gets its drafts back
    open_round = round_count(sdir) if s["status"] == USER else None
    if open_round:
        update_session(sdir, openRound=open_round)
    if s.get("artifact"):
        try:
            if open_round:
                code, a = hub_call(s["artifact"]["url"], "GET", "/api/artifacts/" + s["artifact"]["id"])
                draft = a.get("draft") if code == 200 else None
                if isinstance(draft, dict) and draft.get("round") == open_round:
                    apply_answers(sdir, open_round, draft.get("answers"))
            update_session(sdir, status=FINISHED)
            artifact_push(sdir)
        except (HubDown, GrillError) as e:
            update_session(sdir, status=FINISHED)
            print("Note: {}, so the hub still shows this session as open.".format(e), file=sys.stderr)
    elif s.get("hub"):
        if open_round:
            try:
                code, state = hub_call(s["hub"]["url"], "GET", "/api/sessions/{}?round={}".format(s["id"], open_round))
                if code == 200 and state["round"] == open_round:
                    copy_answers(sdir, open_round, state["questions"])
            except HubDown:
                pass  # the drafts `wait` already copied are all there is
        update_session(sdir, status=FINISHED)
        try:
            hub_sync(sdir)
        except HubDown as e:
            update_session(sdir, hubPending=True)  # the next `start` here tells the hub
            print("Note: {}, so it still lists this session as active.".format(e), file=sys.stderr)
    elif ping(s):
        stop_server(sdir, s)
    else:
        update_session(sdir, status=FINISHED)
    print("Session finished: {}".format(s["title"]))


def cmd_status(args):
    sdir = active_session() if (grill_dir() / "sessions").is_dir() else None
    if not sdir:
        print('No active grill session in this folder.\n\nStart one with:\n  {} start --title "<session title>"'.format(CMD))
        return
    s = read_json(session_file(sdir))
    where = ""
    if s.get("artifact"):
        try:
            hub_call(s["artifact"]["url"], "GET", "/api/ping", timeout=2)
            where = "\nRuns:   on the artifact hub"
        except HubDown as e:
            where = "\nRuns:   on the artifact hub, which isn't answering: {}".format(e)
    elif s.get("hub"):
        try:
            hub_call(s["hub"]["url"], "GET", "/api/ping", timeout=2)
            where = "\nRuns:   on the grill hub"
        except HubDown as e:
            where = "\nRuns:   on the grill hub, which isn't answering: {}".format(e)
    else:
        s = ensure_server(sdir)
    n = round_count(sdir)
    if s["status"] == USER:
        nxt = "the user is answering round {}. Run:\n  {} wait".format(n, CMD)
    elif n:
        nxt = ("the user submitted round {}. Run `{} wait` to print their answers, then send the next round "
               "with `round <path>`, or end the session with `finish`.".format(n, CMD))
    else:
        nxt = "write the first round to a JSON file and run:\n  {} round <path>".format(CMD)
    print("Title:  {}\nStatus: {}\nRound:  {}\nURL:    {}{}\n\nNext: {}".format(
        s["title"], s["status"], n, server_url(s), where, nxt))


def cmd_connect(args):
    cfg = load_config(grill_dir())
    # pair with the hub this folder's session runs on; that's the older grill hub only for sessions started there
    sdir = active_session() if (grill_dir() / "sessions").is_dir() else None
    legacy = sdir and read_json(session_file(sdir)).get("hub")
    try:
        code, info = hub_call(cfg["hubUrl"] if legacy else cfg["artifactHubUrl"], "POST", "/api/pair-codes", {})
    except HubDown as e:
        raise GrillError("{}. Start the hub first: see scripts/artifact-hub in the ang-skills repo.".format(e))
    if code != 200:
        raise GrillError("the hub answered {}: {}".format(code, info.get("error", "")))
    print("Pairing code: {}\n  Open {} on the device and enter it. It works once and expires in {} minutes.\n\n"
          "Show the user this code and link.".format(info["code"], info["pairUrl"], info["expiresInMinutes"]))


# ---------- the server ----------

class Server(ThreadingHTTPServer):
    daemon_threads = True
    # on Windows, address reuse would let two servers share a port
    allow_reuse_address = os.name != "nt"


def page_state(sdir):
    s = read_json(session_file(sdir))
    return {"id": s["id"], "title": s["title"], "status": s["status"],
            "round": round_count(sdir), "questions": latest_questions(sdir)}


def files_version(sdir):
    """Changes whenever the session or its latest round is rewritten."""
    out = []
    for f in (session_file(sdir), round_file(sdir, round_count(sdir))):
        try:
            st = f.stat()
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return out


def clean_answer(q, a):
    if not isinstance(a, dict):
        raise ValueError("answer must be an object")
    choice, text = a.get("choice"), a.get("text") or ""
    if choice is not None and (not isinstance(choice, int) or isinstance(choice, bool) or not 0 <= choice < len(q["choices"])):
        raise ValueError("bad choice for " + q["id"])
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return None if choice is None and not text.strip() else {"choice": choice, "text": text}


class Handler(BaseHTTPRequestHandler):
    """The page's API. The hub subclasses it and serves many sessions by overriding route()."""
    server_version = "grill"

    def log_message(self, fmt, *args):
        pass

    def route(self):
        """Sets self.sdir and returns the path to serve, or None if the request was already answered."""
        self.sdir = self.server.sdir
        return self.path.split("?")[0]

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        srv, path = self.server, self.route()
        if path is None:
            return
        if path == "/api/ping":
            return self.send(200, {"id": srv.session_id})
        if path == "/api/events":
            return self.events()
        srv.touch()
        if path == "/api/state":
            return self.send(200, page_state(self.sdir))
        name = "index.html" if path == "/" else path.lstrip("/")
        f = (PAGE_DIR / name).resolve()
        if f.parent != PAGE_DIR or not f.is_file():
            return self.send(404, {"error": "not found"})
        body = f.read_bytes()
        if name == "index.html":
            body = body.replace(b"{{theme}}", srv.config["theme"].encode())
        types = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png"}
        ctype = types.get(f.suffix, "application/octet-stream")
        if f.suffix in (".html", ".js", ".css", ".svg"):
            ctype += "; charset=utf-8"
        self.send(200, body, ctype)

    def do_POST(self):
        srv, path = self.server, self.route()
        if path is None:
            return
        srv.touch()
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(length, 2_000_000)) or b"{}")
        except ValueError:
            return self.send(400, {"error": "invalid JSON"})
        with srv.lock:
            if path == "/api/finish":
                update_session(self.sdir, status=FINISHED)
                return self.send(200, {"ok": True})
            if path not in ("/api/answer", "/api/submit"):
                return self.send(404, {"error": "not found"})
            # the server only writes during the user's turn, and only to the round on screen
            s, n = read_json(session_file(self.sdir)), round_count(self.sdir)
            if s["status"] != USER or body.get("round") != n:
                return self.send(409, {"error": "this round is closed", "status": s["status"], "round": n})
            data = read_json(round_file(self.sdir, n))
            by_id = {q["id"]: q for q in data["questions"]}
            items = body.get("answers") if path == "/api/submit" else [body]
            try:
                for item in items or []:
                    q = by_id.get(item.get("id"))
                    if not q:
                        raise ValueError("unknown question {}".format(item.get("id")))
                    q["answer"] = clean_answer(q, item)
            except (ValueError, AttributeError) as e:
                return self.send(400, {"error": str(e)})
            write_json(round_file(self.sdir, n), data)
            if path == "/api/submit":
                update_session(self.sdir, status=AGENT)
        self.send(200, {"ok": True})

    def events(self):
        """Server-sent events: the page gets the full state now and whenever the files change."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last, sent_at = None, 0
        try:
            while not self.server.stopping:
                version = files_version(self.sdir)
                if version != last:
                    try:
                        payload = json.dumps(page_state(self.sdir), ensure_ascii=False)
                    except (OSError, ValueError):
                        payload = None  # caught mid-change; try again next tick
                    if payload:
                        self.wfile.write("data: {}\n\n".format(payload).encode())
                        self.wfile.flush()
                        last, sent_at = version, time.time()
                elif time.time() - sent_at > 15:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    sent_at = time.time()
                time.sleep(0.4)
        except OSError:
            pass  # the page went away


def cmd_serve(args):
    sdir = Path(args.sdir)
    s = read_json(session_file(sdir))
    if s["status"] == FINISHED:
        return
    # reuse the last port, so an open page reconnects after a restart
    prev = (s.get("server") or {}).get("port")
    httpd = None
    for port in [p for p in [prev] if p] + [p for p in PORTS if p != prev] + [0]:
        try:
            httpd = Server(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    httpd.sdir, httpd.session_id = sdir, s["id"]
    httpd.config = load_config(sdir.parent.parent)
    httpd.lock, httpd.stopping, httpd.last_activity = threading.Lock(), False, time.time()
    httpd.touch = lambda: setattr(httpd, "last_activity", time.time())
    update_session(sdir, server={"port": httpd.server_address[1], "pid": os.getpid()})
    print("{} serving {} on port {}".format(now(), s["id"], httpd.server_address[1]), flush=True)

    def watch():
        idle = httpd.config["idleTimeoutMinutes"] * 60
        while True:
            time.sleep(1)
            try:
                status = read_json(session_file(sdir))["status"]
                changed = max(f.stat().st_mtime for f in sdir.glob("*.json"))
            except (OSError, ValueError):
                continue
            if status == FINISHED:
                time.sleep(1.5)  # let open pages receive the final state
                reason = "session finished"
                break
            if time.time() - max(httpd.last_activity, changed) > idle:
                reason = "idle"
                break
        print("{} stopping: {}".format(now(), reason), flush=True)
        httpd.stopping = True
        httpd.shutdown()

    threading.Thread(target=watch, daemon=True).start()
    if args.open:
        webbrowser.open(server_url(read_json(session_file(sdir))))
    httpd.serve_forever(poll_interval=0.25)
    httpd.server_close()
    os._exit(0)


def main():
    p = argparse.ArgumentParser(prog="grill.py", description="Run a Grill Me session in a browser page.")
    sub = p.add_subparsers(dest="command", metavar="command")
    sp = sub.add_parser("start", help="start a session, its server, and open the page")
    sp.add_argument("--title", required=True, help="short title shown on the page")
    sp.add_argument("--local", action="store_true", help="use a local server even if an artifact hub is running")
    sp = sub.add_parser("round", help="send the next round from a JSON file")
    sp.add_argument("path", help="JSON file with {\"questions\": [{title, body, choices}]}")
    sp = sub.add_parser("wait", help="block until the user submits the round, then print the answers")
    sp.add_argument("--timeout", type=int, metavar="SECONDS",
                    help="give up after this many seconds (exit code 2); set it below your shell tool's time limit")
    sub.add_parser("finish", help="end the session and stop its server")
    sub.add_parser("status", help="show the active session, its URL, and what to do next")
    sub.add_parser("connect", help="print a one-time code to pair a browser with the hub")
    sp = sub.add_parser("serve")  # internal: the background server
    sp.add_argument("sdir")
    sp.add_argument("--open", action="store_true")
    args = p.parse_args()
    commands = {"start": cmd_start, "round": cmd_round, "wait": cmd_wait,
                "finish": cmd_finish, "status": cmd_status, "connect": cmd_connect, "serve": cmd_serve}
    if not args.command:
        p.print_help()
        return 1
    try:
        return commands[args.command](args) or 0
    except GrillError as e:
        print("error: {}".format(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
