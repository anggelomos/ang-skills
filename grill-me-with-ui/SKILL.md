---
name: grill-me-with-ui
description: Grill Me, answered in a browser page instead of the chat. Each round shows up as question cards with clickable answers, hover-to-dictate and keyboard shortcuts.
disable-model-invocation: true
---

Call the Skill tool with "grilling" and run the session exactly as it says, with one change: **rounds go to a browser page instead of the chat**. If the Skill tool can't find "grilling", read `grilling.md` in this skill's folder and follow that instead. It's a copy of the same skill.

Everything below replaces only the "Format a round like so" part and the "wait for the user's answers" part of grilling. The frontier, the sub-agents and the stop rule stay the same.

When an artifact hub is running, the session is an artifact on it, of type `grill`. Call the Skill tool with "generate-artifact" for how the hub works: private links, pairing, expiry, and why you never end your turn while waiting. If the Skill tool can't find it, carry on without it. Don't use its `artifact-hub` CLI for the session: `grill.py` publishes, updates and waits on the artifact itself, and keeps `.grill/` in step.

## Commands

Run them from the project's root folder. `<skill-dir>` is the folder this file is in. Use `python` instead of `python3` on Windows.

| Command | What it does |
|---|---|
| `python3 <skill-dir>/grill.py start --title "<title>" [--local]` | Starts the session and opens the page. If an artifact hub is running, the session is an artifact there unless you pass `--local`; otherwise it gets a local server. |
| `python3 <skill-dir>/grill.py round <path>` | Sends the round in the JSON file at `<path>`. |
| `python3 <skill-dir>/grill.py wait [--timeout <seconds>]` | Waits until the user submits the round, then prints their answers. |
| `python3 <skill-dir>/grill.py finish` | Ends the session, and marks its artifact done or stops its local server. |
| `python3 <skill-dir>/grill.py status` | Shows the session, its URL and what to do next. |
| `python3 <skill-dir>/grill.py connect` | Prints a one-time code that pairs a browser with the hub. |

## The loop

1. **Start.** Run `start` with a short title for what's being grilled. Tell the user the URL it prints, in one line. Pass `--local` only if the user asks for a local session. A hub session is private: never make it public. If `start` says no browser is paired with the hub, run `connect` and give the user the code and link it prints. Do the same whenever the user asks to pair a device.
2. **Send a round.** Instead of printing the round in the chat, write it to a JSON file, for example `.grill/next-round.json`:
   ```json
   {
     "questions": [
       {
         "title": "Primary user",
         "body": "Who is this for? Explain what's at stake. **Markdown** is fine.",
         "choices": ["Paying customers", "Internal team only", "Both"]
       }
     ]
   }
   ```
   - `title`: the question title.
   - `body`: the context, trade-offs and options behind the question. It can be several paragraphs.
   - `choices`: the answers the user can click. **The first one is your recommended answer.** Write each choice as the answer itself ("Use Postgres"), not "Yes". Give at least one choice.

   Then run `round <path>`. If it prints problems, fix the file and run it again. Don't add IDs. `round` numbers the questions Q1, Q2 and so on.
3. **Wait for the answers, and don't end your turn until you have them.** The user is answering in the browser and won't come back to the chat to nudge you. If you end your turn before `wait` prints the answers, the session stalls.
   - **Claude Code only:** run `wait` as a background command and don't poll. Claude Code wakes you up when it finishes, so ending your turn is fine there.
   - **Everywhere else** (Codex, Cursor, OpenCode and others): run `wait --timeout <seconds>` in the foreground, with `<seconds>` a bit below your shell tool's time limit, for example `--timeout 540` for a 10-minute limit. Leave `--timeout` out if there's no limit. When it prints "Still waiting", run it again right away, and keep going until it prints answers. It's safe to repeat. If you'd rather run it in the background, block on it with your harness's tool for awaiting a background command before you end your turn.
4. **Read the answers.** `wait` prints one line per question:
   ```
   Q1: Paying customers. Note: mostly enterprise
   Q2: We already store it per round
   Q3: (skipped)
   ```
   A line is the chosen choice, the user's own text, or both. Picking the first choice means they accepted your recommendation. Treat these lines as the user's reply to the round, then work out the next round and go back to step 2.
5. **Finish.** Grilling ends when the user confirms you have reached a shared understanding. Ask that as an ordinary question in the last round, with choices like `["Yes, we're aligned", "No, there's more to cover"]`. Once they confirm, run `finish`, then continue in the chat.

## Rules

- Don't print the questions in the chat. One line such as "Round 2 is up in the browser" is enough.
- While the session runs, ask the user everything through the page, including follow-ups and clarifications. They're in the browser, not reading the chat.
- A round can't change once it's sent. Questions that come up while the user is answering go into the next round.
- Never edit the files in `.grill/` by hand. The commands are the only way in.
- If the user replies in the chat instead of the page, take that as their answer and carry on.
- If a command fails, read its message. It says what to run next, for example `finish` when a session is already active.
