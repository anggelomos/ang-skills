# Ang skills

- **[grill-me-with-ui](#grill-me-with-ui):** Matt Pocock's [grill-me](https://github.com/mattpocock/skills/tree/main/skills/productivity/grill-me), but you answer each round in a web app with clickable answers, hover-to-dictate and keyboard shortcuts. The optional [grill hub](scripts/grill-hub/) lets you answer from your phone or another computer.
- **[notify-grokbot](#grokbot-ping):** Send deliberate bot updates when coding work is blocked, needs a decision, or reaches a handoff. Optional hooks ping automatically when a turn finishes.

## Install

Just ask your agent to install it for you ;)

## grokbot-ping

[`grokbot-ping`](scripts/grokbot-ping/grokbot-ping) sends a small JSON update to a Grok Bot webhook. Get the URL and sender key from the **Grok Bot routine panel**. Put them in a private file outside this repo:

```sh
mkdir -p ~/.config/grokbot-ping
cat > ~/.config/grokbot-ping/fabro.env <<'EOF'
GROKBOT_PING_URL='https://...'
GROKBOT_PING_KEY='...'
EOF
chmod 600 ~/.config/grokbot-ping/fabro.env
```

Run `bash scripts/grokbot-ping/install.sh` to symlink the sender into `~/.local/bin`; the script only prints agent configuration snippets and does not change those configurations. Ensure `~/.local/bin` is on each agent's `PATH`. The exact snippets are also in [`claude-stop.json`](scripts/grokbot-ping/claude-stop.json), [`codex-notify.toml`](scripts/grokbot-ping/codex-notify.toml), and [`opencode-plugin.js`](scripts/grokbot-ping/opencode-plugin.js). Merge the Claude `Stop` entry into `~/.claude/settings.json`; put the Codex `notify` line at the root of `~/.codex/config.toml`, before any table; copy the OpenCode v1 plugin to `~/.config/opencode/plugins/grokbot-ping.js`. OpenCode is not installed here, so that adapter remains untested.

By default the key is sent as `Authorization: Bearer <key>`. Confirm that the routine expects this header. If it expects a different header name, set `GROKBOT_PING_KEY_HEADER='X-API-Key'` in the env file; the key is then sent as that header's raw value. A missing config or failed POST never breaks an agent turn; failures go to `~/.cache/grokbot-ping/log`. For another bot, create `~/.config/grokbot-ping/<target>.env` and pass `--to <target>`.

The payload includes target, sender, status, T3 thread ID when an explicit `T3_THREAD_ID`, `T3_CODE_THREAD_ID`, or `T3CODE_THREAD_ID` environment variable exists, session ID, working directory, project, message, and timestamp. No T3-specific thread variable was observed in this agent environment. Codex's notify payload supplies its own thread ID and turn ID; those fill `thread_id` and `session_id` respectively. Claude and OpenCode supply their session IDs.

## grill-me-with-ui

[Grill Me](https://github.com/mattpocock/skills), answered in a browser page instead of the chat.

The agent still runs the grilling session. Each round shows up as question cards in a local web page, where you can:

- click an answer: the first one is the agent's recommendation
- hover over a question and dictate or type your own answer
- move with `Alt+↑/↓`, pick with `Alt+1–9`, and send the round with `Ctrl+Enter`

As soon as you hit "Round done", the agent picks up your answers, and the next round appears in the same page.

Each answer is saved as a draft the moment you give it, so reloading the page, closing it, or opening it on another device doesn't lose anything. If the agent restarts the session, your drafts carry over to the questions it asks again. Only "Round done" sends the round to the agent.

### Install

Copy the `grill-me-with-ui` folder into your agent's skills folder, for example `~/.claude/skills/grill-me-with-ui/` for Claude Code, then run `/grill-me-with-ui`. You need Python 3.8 or newer. Nothing else needs installing.

### How it works

`grill.py` is the CLI the agent runs and the local server the page talks to, in one file. They meet in `.grill/` inside your project:

```
.grill/
  config.json              { "theme": "system", "idleTimeoutMinutes": 120, "useHub": true, "hubUrl": "http://127.0.0.1:7171" }
  sessions/<uuid>/
    session.json           title, status, server port
    round-1.json           the round's questions and your answers
```

`session.json` has a status that says whose turn it is: `agent_writing_round`, `user_writing_round` or `session_finished`. Only the side whose turn it is writes to the files.

| Command | What it does |
|---|---|
| `grill.py start --title "…"` | Starts a session and its server, and opens the page. |
| `grill.py round <file.json>` | Sends a round: `{"questions": [{"title", "body", "choices"}]}`. |
| `grill.py wait [--timeout <s>]` | Waits until you submit, then prints `Q1: <answer>` lines. With `--timeout`, it gives up cleanly so the agent can run it again. |
| `grill.py finish` | Ends the session and stops the server. |
| `grill.py status` | Shows the session, its URL and what to do next. |
| `grill.py connect` | Prints a one-time code that pairs a browser with the grill hub. |

`.grill/` contains its own `.gitignore`, so session files never end up in your repo. In `config.json`, `theme` can be `system`, `light` or `dark`.

### Answering from another device

The optional [grill hub](scripts/grill-hub/) is a small Docker container that serves your sessions outside localhost, for example through a Cloudflare tunnel. It has a dashboard of your active sessions and pairs devices with a one-time code. When the hub is running, `start` uses it automatically. Use `start --local` or `"useHub": false` in `config.json` to opt out.

### Credits

`grilling.md` is Matt Pocock's grilling skill, copied from [mattpocock/skills](https://github.com/mattpocock/skills/blob/95249b0b49782349740fd9b8c6ce32b4e59e497a/skills/productivity/grilling/SKILL.md) (commit `95249b0`) under the MIT license. Its license notice is in a comment at the end of the file. This skill loads the installed `grilling` skill when there is one, and falls back to that copy.
