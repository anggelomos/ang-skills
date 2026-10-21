// Copy to ~/.config/opencode/plugins/grokbot-ping.js (OpenCode v1 plugin API).
export const GrokbotPingPlugin = async ({ $ }) => ({
  event: async ({ event }) => {
    if (event.type !== "session.idle") return
    const sessionID = event.properties?.sessionID
    try {
      if (sessionID) {
        await $`grokbot-ping --from opencode --status done --session ${sessionID}`
      } else {
        await $`grokbot-ping --from opencode --status done`
      }
    } catch {
      // Notifications must never interrupt the agent.
    }
  },
})
