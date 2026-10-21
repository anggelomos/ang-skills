---
name: notify-grokbot
description: Ping a Grok bot from an opted-in coding session when work is blocked, needs a user decision, reaches a handoff, or encounters a risk.
---

# Notify Grok bot

Only ping when this session was explicitly opted in by a request to run `grokbot-ping enable --to <target>`. Run that command from the agent's shell when asked. Other sessions stay silent.

For an enabled session, use `grokbot-ping --status blocked` when progress is blocked or a concrete risk needs attention, `--status decision` when the user must choose, and `--status handoff` when work is ready for someone else. Add `--from` for your agent name and a short message with the issue and next action. The enabled target is remembered for this session. Use `grokbot-ping disable` if asked to stop.

Turn-finished `done` pings already come from the installed hooks for enabled sessions. Do not send another `done` ping manually or use `--force` to bypass opt-in.
