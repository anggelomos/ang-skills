# grill-hub

An optional companion to [grill-me-with-ui](../../grill-me-with-ui/). It serves your grill sessions outside localhost, so you can answer a round from your phone, or from a laptop while the agent runs on a home server.

- A dashboard lists your active sessions, grouped by project.
- Each session gets its own URL: `https://<your-hub>/<project>/<session-id>/`.
- Nothing changes for the agent. When the hub is running, `grill.py start` uses it automatically.

## How it works

The hub listens on two ports:

| Port | For | Auth |
|---|---|---|
| `7170` (public) | The dashboard and the session pages. Point your tunnel or reverse proxy here. | Paired browsers only |
| `7171` (agent) | `grill.py` on the same machine. | None, so never expose it |

`.grill/` in your project stays the agent's source of truth. `grill.py` pushes every change to the hub. While it waits, `wait` copies your draft answers from the hub into `.grill/`, and once you submit, it copies the final answers and returns.

- **Choosing the hub.** `start` checks whether a hub answers at `http://127.0.0.1:7171`. If one does, the session runs on the hub; otherwise it runs locally, as without the hub. That choice is fixed for the whole session.
- **Draft answers.** The page saves each answer to the hub as you give it, so a reload, a closed tab or another device picks up where you left off. Answers the hub hasn't confirmed wait in the browser and are sent again once it's back. A draft never counts as a submission. `wait` only returns after you submit.
- **When the hub goes down.** A hub session never falls back to a local server. `wait` retries for 5 minutes, then stops with an error that says how to continue. Rounds already sent stay in `.grill/`, and the hub gets them again once it's back.

## Run it

```sh
cd scripts/grill-hub
echo "GRILL_HUB_PUBLIC_URL=https://grill-hub.example.com" > .env
docker compose up -d --build
```

Both ports bind to `127.0.0.1` only. To reach the hub from outside, route a tunnel to the public port. With a Cloudflare tunnel, add a public hostname in the dashboard: `grill-hub.example.com` → `http://localhost:7170`. Only route port 7170.

Without Docker: `python3 hub.py`. It needs Python 3.8+ and the `grill-me-with-ui` folder at `../../grill-me-with-ui`, or wherever `GRILL_SKILL_DIR` points.

## Pairing a browser

1. Run `grill.py connect`, or ask your agent to. It prints a 6-character code that works once and expires after 10 minutes.
2. Open the hub on the device and enter the code.

That browser stays paired; the cookie never expires. If you get 5 codes wrong within a minute, `/pair` stops accepting codes for that minute.

To revoke a browser, delete its entry from `devices.json` in the data volume:

```sh
docker exec -it grill-hub vi /data/devices.json
```

## Settings

Set these in `.grill/config.json` in a project:

| Key | Default | What it does |
|---|---|---|
| `useHub` | `true` | Set it to `false` to always run that project's sessions locally. |
| `hubUrl` | `http://127.0.0.1:7171` | Where `grill.py` looks for the hub's agent port. |

`grill.py start --local` skips the hub for one session.

Set these environment variables on the hub:

| Variable | Default |
|---|---|
| `GRILL_HUB_PUBLIC_URL` | `http://localhost:7170` |
| `GRILL_HUB_DATA` | `./data` (`/data` in Docker) |
| `GRILL_HUB_HOST` | `127.0.0.1` (`0.0.0.0` in Docker) |
| `GRILL_HUB_PUBLIC_PORT`, `GRILL_HUB_AGENT_PORT` | `7170`, `7171` |
