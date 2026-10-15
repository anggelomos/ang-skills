---
name: grill-me-with-ui
description: Grill Me, answered in a browser page instead of the chat. Each round shows up as question cards with clickable answers, hover-to-dictate and keyboard shortcuts.
disable-model-invocation: true
---

Call the Skill tool with "grilling" and run the session exactly as it says, with one change: **rounds go to a browser page instead of the chat**. If the Skill tool can't find "grilling", read `grilling.md` in this skill's folder and follow that instead. It's a copy of the same skill.

Everything below replaces only the "Format a round like so" part and the "wait for the user's answers" part of grilling. The frontier, the sub-agents and the stop rule stay the same.

## Commands

Run them from the project's root folder. `<skill-dir>` is the folder this file is in. Use `python` instead of `python3` on Windows.

| Command | What it does |
|---|---|
| `python3 <skill-dir>/grill.py start --title "<title>"` | Starts the session and its server, and opens the page. |
| `python3 <skill-dir>/grill.py round <path>` | Sends the round in the JSON file at `<path>`. |
| `python3 <skill-dir>/grill.py wait` | Waits until the user submits the round, then prints their answers. |
| `python3 <skill-dir>/grill.py finish` | Ends the session and stops the server. |
| `python3 <skill-dir>/grill.py status` | Shows the session, its URL and what to do next. |

## The loop

1. **Start.** Run `start` with a short title for what's being grilled. Tell the user the URL it prints, in one line.
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
   - `body`: the question body: context, trade-offs, options. It can be several paragraphs.
   - `choices`: the answers the user can click. **The first one is your recommended answer.** Write each choice as the answer itself ("Use Postgres"), not "Yes". At least one choice.

   Then run `round <path>`. If it prints problems, fix the file and run it again. Don't add IDs: they're assigned for you (Q1, Q2, …).
3. **Wait for the answers.** Run `wait`.
   - In Claude Code, run it as a background command and don't poll: you're woken up when it finishes.
   - Elsewhere, run it in the foreground. If it's cut off or times out before printing answers, run it again. It's safe to repeat.
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
- A round can't change once it's sent. Questions that come up while the user is answering go into the next round.
- Never edit the files in `.grill/` by hand. The commands are the only way in.
- If the user replies in the chat instead of the page, take that as their answer and carry on.
- If a command fails, read its message: it says what to run next (for example, `finish` when a session is already active).
