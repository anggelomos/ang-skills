#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HOME/.local/bin"
ln -sfn "$script_dir/grokbot-ping" "$HOME/.local/bin/grokbot-ping"

cat <<'EOF'
Added ~/.local/bin/grokbot-ping. Ensure ~/.local/bin is on PATH for the agents.
Pings are off until the agent runs: grokbot-ping enable --to fabro
That command opts in only the current Claude or Codex session.

Add to ~/.claude/settings.json (merge into an existing "hooks" object):
{
  "hooks": {
    "Stop": [{"hooks": [{"type": "command", "command": "grokbot-ping --from claude --status done --claude-stop"}]}]
  }
}

Add this root-level line before any [table] in ~/.codex/config.toml:
notify = ["grokbot-ping", "--from", "codex", "--status", "done", "--codex-notify"]

For OpenCode v1, copy the repo's scripts/grokbot-ping/opencode-plugin.js to:
~/.config/opencode/plugins/grokbot-ping.js

Create ~/.config/grokbot-ping/fabro.env with:
GROKBOT_PING_URL='https://...'
GROKBOT_PING_KEY='...'
Then chmod 600 ~/.config/grokbot-ping/fabro.env.
EOF
