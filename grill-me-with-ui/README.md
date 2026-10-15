# grill-me-with-ui

[Grill Me](https://github.com/mattpocock/skills), answered in a browser page instead of the chat.

The agent still runs the grilling session. Each round shows up as question cards in a local web page, where you can:

- click an answer: the first one is the agent's recommendation
- hover over a question and dictate or type your own answer
- move with `Alt+↑/↓`, pick with `Alt+1–9`, and send the round with `Ctrl+Enter`

As soon as you hit "Round done", the agent picks up your answers, and the next round appears in the same page.

## Install

Copy this folder into your agent's skills folder, for example `~/.claude/skills/grill-me-with-ui/` for Claude Code, then run `/grill-me-with-ui`. You need Python 3.8 or newer. Nothing else needs installing.

## How it works

`grill.py` is the CLI the agent runs and the local server the page talks to, in one file. They meet in `.grill/` inside your project:

```
.grill/
  config.json              { "theme": "system", "idleTimeoutMinutes": 120 }
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

`.grill/` contains its own `.gitignore`, so session files never end up in your repo. In `config.json`, `theme` can be `system`, `light` or `dark`.

## Credits

`grilling.md` is Matt Pocock's grilling skill, copied unchanged from [mattpocock/skills](https://github.com/mattpocock/skills/blob/95249b0b49782349740fd9b8c6ce32b4e59e497a/skills/productivity/grilling/SKILL.md) (commit `95249b0`) under the MIT license in `grilling-LICENSE`. This skill loads the installed `grilling` skill when there is one, and falls back to that copy.
