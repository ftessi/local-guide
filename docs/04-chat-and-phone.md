# 4. Chat, and reach it from your phone

Always start from the `LocalAgent` folder with the virtual environment active.

## Chat in the terminal

```bash
python -m localagent chat
```

- The model loads (seconds to a minute), then you see `You:`.
- `reset` stops replaying the conversation so far to the model (it stays saved in `memory/`). `exit` or Ctrl+C
  quits.
- `/ask <name> <question>` asks a connected agent (page 8).
- Lines in brackets come from the agent itself, not the model: `(used web.search: …)` shows a tool that really
  ran, `(Couldn't run …)` one that failed, `(Waiting for your OK …)` one that needs your yes.

Only one program can use the model at a time on a small GPU: close `chat` before `serve`, training or anything
else that loads the model.

## Serve: phone app, reminders, tunnel

```bash
python -m localagent serve
```

`serve` starts every **connection** listed in `installables.yaml` and runs the tools' background jobs (such as
due reminders) once a minute. It does nothing useful until you add a connection.

### Where the phone app, calendar and tunnel come from

They are not in this repository: they live in the extensions repository,
https://github.com/ftessi/local-guide-extensions. Point `source:` at it and `path:` at the folder inside:

```yaml
# my-agent/installables.yaml
tools:
  calendar:                          # reminders the agent can create, list and delete
    source: https://github.com/ftessi/local-guide-extensions.git
    path: tools/calendar
    compartment: private
connections:
  phone:                             # chat web app, push notifications, REST API for tools
    source: https://github.com/ftessi/local-guide-extensions.git
    path: connections/phone
    host: 127.0.0.1                  # keep local: the tunnel connects locally
    port: 8000
```

Then `python -m localagent install`: it downloads the repository into `extensions/`, installs the packages each
one needs, and checks it. `ref: <branch or tag>` pins a version. Wait for `Phone app: http://127.0.0.1:8000` after
`python -m localagent serve`, open it in a browser, and enter your `AGENT_SECRET` (in `my-agent/.env`).

To work on the extensions yourself, clone the repository anywhere and use a folder instead:
`source: ../../local-guide-extensions` (relative to the agent folder) with the same `path:`.

## Reach it from your phone, from anywhere (Cloudflare Tunnel)

A tunnel gives your agent a public HTTPS address without opening ports on your router. You need a domain on a free
Cloudflare account. Once:

1. **Move the domain's DNS to Cloudflare:** in Cloudflare, *Add a site*, choose the Free plan, and replace the
   nameservers at your registrar with the two Cloudflare shows. Usually active within an hour.
2. **Install `cloudflared`:** Windows: the `.msi` from
   https://github.com/cloudflare/cloudflared/releases/latest; Mac: `brew install cloudflared`; Linux: the package
   for your distribution from the same releases page. Check with `cloudflared --version`.
3. **Create the tunnel:**

   ```bash
   cloudflared tunnel login                      # a browser opens; pick your domain
   cloudflared tunnel create local-agent         # prints a tunnel id and saves a credentials file
   cloudflared tunnel route dns local-agent yourdomain.com
   ```

4. **Point it at the phone app:** create `~/.cloudflared/config.yml` (Windows: `C:\Users\<you>\.cloudflared\config.yml`):

   ```yaml
   tunnel: <tunnel id>
   credentials-file: <path printed by "tunnel create">
   ingress:
     - hostname: yourdomain.com
       service: http://localhost:8000
     - service: http_status:404
   ```

5. **Let `serve` run the tunnel** by adding the `cloudflare` connection from the extensions repository:

   ```yaml
   connections:
     phone:
       source: https://github.com/ftessi/local-guide-extensions.git
       path: connections/phone
       port: 8000
     cloudflare:
       source: https://github.com/ftessi/local-guide-extensions.git
       path: connections/cloudflare
       tunnel: local-agent
   ```

   (Or run it yourself: `cloudflared tunnel run local-agent`, or install it as a system service:
   `cloudflared service install`.)

On the phone, open `https://yourdomain.com`, choose **Add to Home Screen**, and allow notifications. On iPhone,
notifications only work once the app is on the Home Screen (iOS 16.4+).

## Start it automatically

- **Windows:** `scripts\start_server.bat` activates the virtual environment and runs `serve`. In Task Scheduler,
  *Create Basic Task* → trigger *When the computer starts* → action: start that `.bat` file → tick *Run whether user
  is logged on or not*.
- **Linux / Mac:** run `cd <LocalAgent> && .venv/bin/python -m localagent serve` from a systemd user service (Linux)
  or a launchd agent (Mac).

## The phone app's REST API

With the phone connection, every tool action is also an endpoint, for scripts. All need
`Authorization: Bearer <AGENT_SECRET>`.

| Method | Path | |
|---|---|---|
| GET | `/api/tools/<tool>/<action>` | run a read action (query string = arguments) |
| POST | `/api/tools/<tool>/<action>` | run any action (JSON body = arguments) |

```bash
curl -H "Authorization: Bearer <AGENT_SECRET>" http://127.0.0.1:8000/api/tools/calendar/list
```

Errors: 401 bad token, 403 outside your scope, 404 unknown tool or action, 405 GET on a write action,
422 bad arguments, 500 the tool failed.

Next: [5. Knowledge, memory and work](05-knowledge-and-memory.md)
