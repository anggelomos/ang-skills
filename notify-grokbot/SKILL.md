---
name: notify-grokbot
description: Ping a Grok bot when coding work is blocked, needs a user decision, reaches a handoff, or encounters a risky situation.
---

# Notify Grok bot

Use `grokbot-ping` when the user needs an actionable update during a coding task: you are blocked, need a decision, have finished a handoff, or found a concrete risk. Choose `--status blocked`, `decision`, or `handoff` as appropriate, and send a short message naming the issue and next action. Use `--to <target>` when the recipient is not the default `fabro`, and `--from` for your agent name.

Turn-finished `done` pings already come from the installed hooks. Do not send another `done` ping manually.
