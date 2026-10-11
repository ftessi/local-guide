# 4. Run it, then reach it from your phone

Always start from the repo folder with the venv active (`.venv\Scripts\activate`).

## 4.1 Terminal chat

```bash
python -m localagent chat
```

- Loads the model (seconds to a minute), then shows `You:`.
- `reset` clears the conversation from what the model sees (it stays saved in `memory/`). `exit` or Ctrl+C quits.
- Reminders can be created here too; they *fire* only while `serve` (4.2) runs.

## 4.2 Serve: phone app, reminders, push

```bash
python -m localagent serve
```

This starts every connection in `installables.yaml` and fires due reminders every minute. The phone app is a connection: add it first (`source:` is the folder or git repo that holds its code):

```yaml
# my-agent/installables.yaml
connections:
  phone:
    source: W:/my-tools/phone
    port: 8000
```

then `python -m localagent install`. Wait for `Phone app: http://127.0.0.1:8000`, open that URL, and enter your `AGENT_SECRET` (from `my-agent/.env`).

`scripts\start_server.bat` does the same and can be double-clicked or run by Task Scheduler.

Both commands take `--agent <folder>` (or set the `LOCALAGENT_DIR` environment variable) if your agent isn't in `./my-agent`.

## 4.3 Reach it from your phone (Cloudflare Tunnel)

You need a domain on a free Cloudflare account. Full walkthrough: [`../Setup/cloudflare-tunnel-setup.md`](../Setup/cloudflare-tunnel-setup.md). In short, once:

```bash
cloudflared tunnel login
cloudflared tunnel create local-agent
cloudflared tunnel route dns local-agent yourdomain.com
```

with `~/.cloudflared/config.yml` pointing `yourdomain.com` at `http://localhost:8000`. Then let `serve` run the tunnel for you by adding the `cloudflare` connection:

```yaml
# my-agent/installables.yaml
connections:
  phone:
    source: W:/my-tools/phone
    port: 8000
  cloudflare:
    source: W:/my-tools/cloudflare
    tunnel: local-agent
```

and `python -m localagent install`. (Or skip it and run `cloudflared` as a Windows service: `cloudflared service install`.)

Then on the phone, open `https://yourdomain.com`, choose **Add to Home Screen**, and allow notifications. On iPhone, notifications only work once the app is installed to the Home Screen (iOS 16.4+).

Keep `host: 127.0.0.1` for the phone connection: the tunnel connects locally, so your agent is never exposed on your network.

## 4.4 Startup checklist

| Order | What | Ready when |
|---|---|---|
| 1 | `python -m localagent serve` | `Phone app: http://…` (and `Cloudflare tunnel … started`) |
| 2 | Only without the cloudflare connection: `cloudflared tunnel run local-agent` (or the service) | `Registered tunnel connection` |
| 3 | Open the app on the phone | Header says **Connected** |

## 4.5 Calendar from scripts (REST)

With the phone connection, every tool action is also an endpoint. All of them need `Authorization: Bearer <AGENT_SECRET>`.

| Method | Path | Body |
|---|---|---|
| GET | `/api/tools/calendar/list` | none |
| POST | `/api/tools/calendar/create` | `{"title": "...", "remind_at": "2026-10-12T18:00:00"}` |
| POST | `/api/tools/calendar/delete` | `{"id": 3}` |

```powershell
$h = @{ Authorization = "Bearer <AGENT_SECRET>" }
Invoke-RestMethod http://127.0.0.1:8000/api/tools/calendar/list -Headers $h
```

Read actions use GET; actions that change data must use POST.

## 4.6 Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No agent found at …` | Run `python scripts/new_agent.py`, or pass `--agent` |
| `Error: … agent.yaml …` / `policy.yaml …` | The message names the bad setting; fix it and restart |
| Very slow / `CUDA: False` | torch was replaced by a CPU build; see install step 2.4 |
| `[error] Could not load adapters …` | A trained adapter in `training/adapters/` is broken or `peft` isn't installed. The agent refuses rather than running without it; remove the folder or `pip install peft` |
| Phone: "Connection error" | Wrong token (clear site data), server not running, or tunnel down |
| Reminder created but no notification | Notifications denied on the phone, or the iOS app not installed to the Home Screen |
| `Address already in use` | Another server is on port 8000; close it or change the phone `port` in `installables.yaml` |
| `… is listed in installables.yaml but not installed` | Run `python -m localagent install` |
| `cloudflared is not installed or not on PATH` | Install cloudflared (4.3), or remove the `cloudflare` connection |
| Agent says it set a reminder but nothing happened | Look for a `(Couldn't run calendar.create: …)` line in the reply; small models sometimes get the format wrong. Try a bigger model |
