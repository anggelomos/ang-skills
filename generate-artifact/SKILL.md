---
name: generate-artifact
description: Build a self-contained HTML artifact (report, dashboard, mockup, comparison, form, checklist) and publish it to the user's artifact hub, then collect what they send back. Use when the user asks for an artifact, a page, a visual, or a form to fill in, or when an answer is better seen than read in the chat.
---

Build the artifact as **one HTML file**, publish it with the `artifact-hub` CLI, and give the user the link. If it asks for input, wait for the response.

## Commands

`<skill-dir>` is the folder this file is in. Use `python <skill-dir>/artifact-hub` on Windows.

| Command | What it does |
|---|---|
| `<skill-dir>/artifact-hub publish <file.html> --title "<title>" [--type <kind>] [--data <file.json>] [--public] [--expires <n>d\|never]` | Publishes and prints the ID and link. |
| `<skill-dir>/artifact-hub update <id> [<file.html>] [--data <file.json>] [--title ...] [--status ...] [--public\|--private] [--expires ...]` | Overwrites the artifact. Only the latest version is kept. |
| `<skill-dir>/artifact-hub wait <id> [--timeout <seconds>]` | Waits until the user submits, then prints the response as JSON. |
| `<skill-dir>/artifact-hub show <id>` | Everything about the artifact, including the user's unsent drafts. |
| `<skill-dir>/artifact-hub list [--all]` / `delete <id>` | List (newest first) or delete. |
| `<skill-dir>/artifact-hub connect` | Prints a one-time code that pairs a browser with the hub. |

`--project` defaults to the git repo's name. `--type` is a short kind shown on the gallery card: `report`, `mockup`, `form`, `chart`, `doc` and so on.

## Rules for publishing

- **Private by default.** Only the user's paired browsers can open it. Add `--public` only when the user explicitly asks in the chat for a public or shareable link. Never decide that on your own. A public link is read-only: no forms, no responses.
- **Expiry.** Artifacts expire after 30 days. Pass `--expires` only when the user asks for something else: `--expires 7d`, `--expires never`.
- **Status.** A private artifact starts as `awaiting` (it's the user's turn). If there's nothing to answer, publish with `--status view`. While you prepare the next version, `--status working`. When it's finished, `update <id> --status done`.
- Tell the user the link in one line. Don't paste the HTML into the chat.
- If they can't open it, their browser isn't paired: run `connect` and give them the code and link it prints.
- If the hub isn't answering, say so. Save the file in the project and give the user its path instead.

## Building the HTML

The page runs sandboxed with **no network**: no external scripts, stylesheets, images, fetch, or iframes. Everything goes in the one file.

- Inline `<style>` and `<script>`. Images as inline SVG or `data:` URLs. Charts as inline SVG or hand-written canvas code; no chart libraries from a CDN.
- Start with `<!doctype html>`, `<meta charset="utf-8">` and `<meta name="viewport" content="width=device-width, initial-scale=1">`. The user often opens it on a phone, so make it responsive.
- Support light and dark with `prefers-color-scheme`.
- Google Fonts is the one exception, and only for private artifacts. Always give a system font fallback.
- `localStorage` and cookies don't work. Links to other sites need `target="_blank" rel="noopener"`, which opens them in a new tab; without it, a click replaces the artifact inside its frame. Public artifacts can't open links at all, so show URLs as text there.
- To keep data separate from layout, pass it with `--data <file.json>` and read it from `state.data` (below). Then `update <id> --data <file.json>` changes what's shown without republishing the HTML.

## Getting input back

Two ways, and both reach you only through `wait`:

1. **Plain forms.** Any `<form>` works with no code. On submit, `wait` prints `{"value": {"form": "<name>", "values": {...}}, "via": "form", "submittedAt": "..."}`. Fields with the same name become arrays; unchecked checkboxes are left out. Give each form a `name`. What the user types is kept as a draft, so a reload doesn't lose it.
2. **The SDK.** The hub injects `window.Artifact` into every private artifact:
   ```js
   Artifact.onUpdate((state) => render(state.data, state.draft)); // now, and on every change
   Artifact.save({ picks });    // a draft: survives reloads and other devices, not sent to you
   Artifact.submit({ picks });  // the response `wait` prints, as {"value": {...}, "via": "sdk", ...}
   ```
   `state` is `{status, title, data, draft, response, readOnly}`. `save` and `submit` return promises; show an error if they reject. When `readOnly` is true, the artifact is done: disable the inputs.

After the user submits, the hub shows them "Sent to the agent". A second submit replaces the first.

### Waiting

Run `wait <id>` right after publishing anything that asks for input, and **don't end your turn until it prints the response**. The user is in the browser and won't come back to the chat to nudge you.

- **Claude Code only:** run `wait` as a background command and don't poll. Claude Code wakes you up when it finishes.
- **Everywhere else** (Codex, Cursor, OpenCode and others): run `wait <id> --timeout <seconds>` in the foreground, a bit below your shell tool's time limit, for example `--timeout 540` for a 10-minute limit. When it prints "Still waiting", run it again right away. It's safe to repeat.

Treat the response as the user's reply. If you answer it by updating the artifact, the new HTML or data makes it `awaiting` again, and you `wait` again. If the user replies in the chat instead, take that as their answer.
