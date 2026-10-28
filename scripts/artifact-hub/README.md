# artifact-hub

A small server for the HTML artifacts your agents make: reports, mockups, forms, and [grill-me-with-ui](../../README.md#grill-me-with-ui) sessions. Agents publish with the [`artifact-hub` CLI](../../generate-artifact/artifact-hub), and the [`/generate-artifact`](../../generate-artifact/SKILL.md) skill teaches them how.

- **Private by default.** Only browsers you've paired see an artifact, at `/a/<id>/`.
- **Public when you ask.** `--public` also serves it at `/p/<id>/` to anyone with the link, read-only.
- **Answers come back.** Private artifacts can take input, through plain `<form>`s or the `artifact.js` SDK, and the agent picks it up with `artifact-hub wait`.
- **They expire.** After 30 days by default, an artifact leaves the gallery and its links stop working. The hub keeps its files for 90 more days, then deletes them.
- **A gallery** at `/` shows every live artifact, newest first. Artifacts waiting on you get an ember stripe and tag. The hub's own pages have a light / dark / system toggle, saved per browser; artifacts follow the device's setting.

## How it works

The hub listens on two ports:

| Port | For | Auth |
|---|---|---|
| `7172` (public) | The gallery, the artifacts and pairing. Point your tunnel or reverse proxy here. | Paired browsers, except `/p/` |
| `7173` (agent) | The `artifact-hub` CLI and `grill.py` on the same machine. | None, so never expose it |

The agent port refuses anything that looks like a browser: requests with an `Origin` or `Sec-Fetch-*` header, or a `Host` other than `localhost`, `127.0.0.1` or `[::1]`. That keeps web pages, including ones reached through DNS rebinding, from using it. Writes also need `Content-Type: application/json`.

### Sandboxing

Artifacts are agent-written HTML, so the hub never runs them with its own origin.

- **Private** artifacts load in a frame inside a small page of the hub's (the shell). The frame's `Content-Security-Policy` sandboxes it (`allow-scripts allow-forms allow-popups`, no `allow-same-origin`), so it gets an opaque origin: it can't read the hub's cookie or call its API. It has no network either, except Google Fonts. The shell hands the frame a `MessagePort` only after the frame says hello with a token from its own URL, and carries saves and submits from that port to the hub. Links with `target="_blank"` open in a new tab.
- **Public** artifacts are served as-is under `sandbox allow-scripts`, with no network and no forms at all (`form-action 'none'`, no `allow-forms`). Inline JavaScript runs. This is the same model as Postplan.

Inline `<script>` and `<style>` work everywhere. External files don't: put everything in the one HTML file, with images as `data:` URLs.

### Input

The hub injects `artifact.js` into every private artifact. It gives the page:

| | |
|---|---|
| `Artifact.ready` | A promise of the state: `{status, title, data, draft, response, readOnly}`. `data` is the JSON the agent attached with `--data`. |
| `Artifact.save(value)` | Keeps a draft on the hub, so a reload or another device picks it up. The agent isn't told. |
| `Artifact.submit(value)` | Sends a response. `artifact-hub wait` returns it. |
| `Artifact.onUpdate(fn)` | Calls `fn(state)` now and on every change: new data, a new status, a draft from another device. |

A phone keyboard covers the bottom of the frame instead of resizing it (resizing the frame froze touch input on Android Chrome). The covered part is in the CSS variables `--artifact-inset-top` and `--artifact-inset-bottom` on `<html>`, `0px` without a keyboard, and each change fires an `artifactviewport` event on `window` with `{top, bottom}` in `detail`. To keep something above the keyboard, use `bottom: var(--artifact-inset-bottom, 0px)`.

Plain `<form>`s need no code. A submit goes to the agent as `{"form": "<name or id>", "values": {...}}`; repeated names become arrays. What's typed is saved as a draft and filled back in on the next load. Mark a form `data-artifact="off"` to leave it alone.

Public artifacts get a stub with the same API: `data` works, `save` and `submit` fail.

### Status

| Status | Meaning |
|---|---|
| `awaiting` | The user's turn. The default for private artifacts. |
| `responded` | The user submitted; `wait` returns the response. Set by the hub. |
| `working` | The agent's turn. |
| `view` | Nothing to answer. The default for public artifacts. |
| `done` | Finished. No more drafts or responses. |

A submit is accepted while the status is `awaiting` or `responded`; a later submit replaces the earlier one. Updating the HTML or data of a `responded` artifact makes it `awaiting` again, unless `--status` says otherwise.

### Lifecycle

Only the latest version is kept: `update` overwrites. `--expires` takes `30d` (the default), any `<n>d` up to `3650d`, or `never`. An expired artifact is hidden from the gallery and from `list` (but `list --all` shows it), and its links answer `410 Gone`. Giving it a new `--expires` within the 90 days brings it back. `delete` removes it at once.

## Run it

```sh
cd scripts/artifact-hub
echo "ARTIFACT_HUB_PUBLIC_URL=https://artifacts.example.com" > .env
docker compose up -d --build
```

Both ports bind to `127.0.0.1` only. To reach the hub from outside, route a tunnel to the public port. With a Cloudflare tunnel, add a public hostname: `artifacts.example.com` → `http://localhost:7172`. Only route port 7172.

Without Docker: `python3 hub.py`. It needs Python 3.8+ and nothing else.

## Pairing a browser

1. Run `artifact-hub connect` (or `grill.py connect`), or ask your agent to. It prints a 6-character code that works once and expires after 10 minutes.
2. Open the hub on the device and enter the code.

That browser stays paired; the cookie never expires. If anyone gets 5 codes wrong within a minute, `/pair` stops accepting codes for that minute. To revoke a browser, delete its entry from `devices.json` in the data volume:

```sh
docker exec -it artifact-hub vi /data/devices.json
```

## Agent API

The CLI wraps these; `grill.py` calls them directly. All bodies are JSON.

| Request | Does |
|---|---|
| `GET /api/ping` | `{hub: "artifact-hub", publicUrl, devices}` |
| `POST /api/artifacts` | Publish: `{title, project, type?, html, data?, public?, expires?, status?}` |
| `PATCH /api/artifacts/<id>` | Update any of those fields |
| `GET /api/artifacts/<id>` | The artifact with its data, drafts and response |
| `GET /api/artifacts/<id>/wait?timeout=<s>` | Long poll, up to 60 s, until it's `responded`, `done` or expired |
| `GET /api/artifacts[?all=1]` | List, newest first |
| `DELETE /api/artifacts/<id>` | Delete |
| `POST /api/pair-codes` | A pairing code |

## Data

In `ARTIFACT_HUB_DATA` (`/data` in Docker):

```
devices.json                  sha256 of each paired browser's cookie
artifacts/<id>/meta.json      title, project, type, status, expiry, public link
artifacts/<id>/index.html     the artifact
artifacts/<id>/data.json      the agent's JSON, if any
artifacts/<id>/drafts.json    the page's drafts
artifacts/<id>/response.json  the latest submit
```

## Settings

| Variable | Default |
|---|---|
| `ARTIFACT_HUB_PUBLIC_URL` | `http://localhost:7172` |
| `ARTIFACT_HUB_DATA` | `./data` (`/data` in Docker) |
| `ARTIFACT_HUB_HOST` | `127.0.0.1` (`0.0.0.0` in Docker) |
| `ARTIFACT_HUB_PUBLIC_PORT`, `ARTIFACT_HUB_AGENT_PORT` | `7172`, `7173` |

The CLI reads `ARTIFACT_HUB_URL` (default `http://127.0.0.1:7173`).
