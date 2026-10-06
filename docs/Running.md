# Running the Local Agent

How to start the agent, swap the model, run the phone-facing services, and how each capability works.

> First-time install (Python, CUDA torch, venv): see `Setup/2026-10-05-session-log.md`.
> Domain + Cloudflare Tunnel: see `Setup/cloudflare-tunnel-setup.md`.

---

## 1. Project layout

```
W:\LocalAgent
├── main.py                 # Terminal chat (REPL) — no server, no calendar
├── server.py               # Web server: phone chat UI, calendar API, push notifications
├── .env                    # Secrets + settings (NOT committed — copy from .env.example)
├── requirements.txt
├── agent/
│   ├── config.py           # MODEL_ID / USE_4BIT / MAX_NEW_TOKENS (overridable from .env)
│   ├── llm.py              # Loads the HuggingFace model, generates text
│   ├── session.py          # Builds the system prompt (base prompt + knowledge/)
│   ├── core.py             # Agent: chat history, streaming, calendar tag parsing
│   ├── calendar.py         # SQLite reminders + background scheduler
│   └── push.py             # Web Push sender (VAPID)
├── knowledge/
│   ├── private/            # Personal facts injected into the prompt (NOT committed)
│   └── public/             # General instructions injected into the prompt
├── static/                 # Phone web app (PWA): index.html, sw.js, manifest.json, icon
├── scripts/
│   ├── start_server.bat    # Double-click / Task Scheduler launcher for server.py
│   ├── smoke_test_model.py # Loads the model and says hello — sanity check
│   └── diagnose_gpu.py     # Shows whether weights are on the GPU
├── tests/                  # pytest suite (no model loading)
├── models/                 # HuggingFace cache (HF_HOME) — ~6GB, NOT committed
├── calendar.db             # Reminders database (created on first run, NOT committed)
└── docs/
    ├── Running.md          # ← you are here
    ├── Setup/              # Install logs, Cloudflare, Mac notes, Git guide
    ├── design/             # Design specs (architecture decisions)
    └── plans/              # Implementation plans (historical, step-by-step)
```

---

## 2. Every time: activate the environment

```powershell
cd W:\LocalAgent
.venv\Scripts\activate
```

`HF_HOME` is read from `.env` automatically by both `main.py` and `server.py`, so you no longer
need to `set HF_HOME=...` by hand. (If you run the scripts in `scripts/`, they do **not** read
`.env` — set `HF_HOME` first or they will re-download the model to `C:\Users\<you>\.cache`.)

---

## 3. Running

### 3a. Terminal chat (quickest test)

```powershell
python main.py
```

- Loads the model (~10s), then `You:` prompt.
- `reset` clears the conversation, `exit` or Ctrl+C quits.
- Calendar tags are **not** executed here — use the server for reminders.

### 3b. Web server (phone app + calendar + push)

```powershell
python server.py
```

Wait for `Server ready.` and `Uvicorn running on http://127.0.0.1:8000`.
Open http://127.0.0.1:8000 on the PC, enter the `AGENT_SECRET` from `.env` when prompted.

Equivalent forms:
```powershell
uvicorn server:app --host 127.0.0.1 --port 8000     # what the Cloudflare guide uses
scripts\start_server.bat                            # double-clickable / Task Scheduler
```

Change host/port with `HOST=` / `PORT=` in `.env`. Keep `127.0.0.1` — the Cloudflare Tunnel
connects locally, so the server never needs to be exposed on your LAN.

> **Why `python server.py` used to do nothing:** the file only defined the app and had no
> `if __name__ == "__main__"` block, so Python exited immediately with no output. It now starts
> uvicorn itself.

### 3c. Reaching it from the phone (after DNS is set up)

Terminal 2 (or install as a Windows service — see the Cloudflare guide, Step 8):
```powershell
cloudflared tunnel run local-agent
```
Then open `https://yourdomain.com` on the phone and **Add to Home Screen**.

### 3d. Tests

```powershell
pytest            # runs tests/ only (pytest.ini) — ~10s, model is mocked
pytest -v tests/test_calendar.py
```

### 3e. Startup checklist

| Order | What | Command | Ready when |
|---|---|---|---|
| 1 | Server | `python server.py` | `Server ready.` |
| 2 | Tunnel | `cloudflared tunnel run local-agent` (or the service) | `Registered tunnel connection` |
| 3 | Phone | open the PWA | header says **Connected** |

---

## 4. Changing the model

Everything model-related lives in `agent/config.py`, and every value can be overridden from `.env`:

```ini
MODEL_ID=Qwen/Qwen2.5-3B-Instruct   # any HuggingFace chat model id
USE_4BIT=1                           # 1 = 4-bit quantized (bitsandbytes), 0 = fp16
MAX_NEW_TOKENS=256                   # longest reply, in tokens
```

Restart the server after changing them. The first run with a new `MODEL_ID` downloads it into
`models/`.

### Requirements for a model to work

1. **It must be a chat/instruct model** with a chat template (names usually end in `-Instruct`
   or `-Chat`). `llm.py` calls `tokenizer.apply_chat_template(...)` — base models fail or ramble.
2. **It must fit in VRAM.** The GTX 1050 has 4GB. Rough guide with `USE_4BIT=1`:

   | Size | 4-bit VRAM | Fits on GTX 1050? |
   |---|---|---|
   | 0.5B–1.5B | 0.5–1.2 GB | Yes, fast |
   | 3B (current) | ~2.2 GB | Yes |
   | 7B–8B | ~5 GB | No — spills to CPU RAM, very slow |

   `device_map="auto"` will silently offload layers to CPU if the model doesn't fit. Run
   `python scripts/diagnose_gpu.py` (after editing its `model_id`) — you want
   `Parameter devices: {'cuda:0'}`.
3. **Gated models** (Llama, Gemma) need a HuggingFace account, accepting the licence on the
   model page, and `huggingface-cli login` once.

### Models worth trying on this GPU

| MODEL_ID | Notes |
|---|---|
| `Qwen/Qwen2.5-3B-Instruct` | Current default. Good balance, follows the `<cal>` format well |
| `Qwen/Qwen2.5-1.5B-Instruct` | ~2× faster, weaker at following the calendar format |
| `microsoft/Phi-3.5-mini-instruct` | 3.8B, strong reasoning, tight on 4GB |
| `meta-llama/Llama-3.2-3B-Instruct` | Gated — needs HF login |
| `google/gemma-2-2b-it` | Gated — needs HF login |

### Checking a new model properly

The calendar depends on the model emitting exact `<cal>{...}</cal>` JSON. After switching, in
the chat ask: *"remind me to call mom tomorrow at 6pm"* then check the reminder exists:

```powershell
curl -H "Authorization: Bearer <AGENT_SECRET>" http://127.0.0.1:8000/api/calendar
```

If nothing was created, the model isn't following the format — try a bigger model or tighten
`BASE_PROMPT` in `agent/session.py`.

### Other generation knobs (`agent/llm.py`)

- `do_sample=False` → greedy, deterministic, fastest. For more varied answers use
  `do_sample=True, temperature=0.7`.
- Swapping to a non-HuggingFace backend (llama.cpp, Ollama, an API): write a class with the same
  two methods as `LLMEngine` — `generate(messages) -> str` and `generate_stream(messages)` yielding
  text chunks — and construct it in `main.py` / `server.py` instead. Nothing else needs to change.

---

## 5. How the capabilities work

### 5.1 Chat + memory of the conversation

```
phone ──WebSocket /ws?token=…──► server.py ──► Agent.chat_stream_async ──► LLMEngine
                                                     │
                       system prompt = BASE_PROMPT + knowledge/private + knowledge/public
                                     + full conversation history
```

- The **system prompt** is rebuilt on every message (`agent/session.py`), so it always contains
  the current date/time and the current contents of `knowledge/`.
- **History** is kept in memory in the `Agent` object: it is lost on server restart, and is
  **shared by every connected device** (there is one Agent for the whole server). There is no
  trimming yet, so very long chats will eventually slow down and exceed the model's context —
  restart the server to clear it.
- **Streaming:** in the terminal, text prints token by token. On the phone the server currently
  waits for the full reply and sends it at once, because `<cal>` tags have to be removed before
  the user sees them. Expect a few seconds of "nothing" before the reply appears.

### 5.2 Knowledge files

Drop `.md` or `.txt` files into:
- `knowledge/private/` — facts about you (name, family, preferences, work). Not committed to git.
- `knowledge/public/` — general behaviour instructions (tone, language, style).

They are concatenated into the system prompt on every message — no restart needed. Keep them
short: everything here eats into the model's context on every turn.

### 5.3 Calendar / reminders

**Storage:** SQLite table `reminders` in `calendar.db` (`id, title, remind_at, fired, created_at`).

**Creating from chat** — the model is instructed (in `BASE_PROMPT`) to append machine-readable tags
at the end of its answer:

```
Sure, I'll remind you tomorrow at 6pm.
<cal>{"action":"create","title":"Call mom","remind_at":"2026-10-07T18:00:00"}</cal>
```

After the reply is complete, `agent/core.py`:
1. finds every `<cal>…</cal>` with a regex and parses the JSON (bad JSON is silently ignored),
2. runs `create` → `calendar.create(title, remind_at)` or `delete` → `calendar.delete(id)`,
3. strips the tags so you only see the natural-language part.

The model resolves "tomorrow", "in 10 minutes", etc. because the current date/time is injected
into the prompt each message. Times are **local PC time**, no timezone.

**Limitations to know:**
- The model never sees the list of existing reminders or their ids, so "delete my dentist
  reminder" from chat doesn't work reliably yet — use the REST API below.
- "List my reminders" in chat makes the model answer from conversation memory, not the database.

**REST API** (all need header `Authorization: Bearer <AGENT_SECRET>`):

| Method | Path | Body | Does |
|---|---|---|---|
| GET | `/api/calendar` | — | List un-fired reminders, soonest first |
| POST | `/api/calendar` | `{"title": "...", "remind_at": "2026-10-07T18:00:00"}` | Create |
| DELETE | `/api/calendar/{id}` | — | Delete |

PowerShell example:
```powershell
$h = @{ Authorization = "Bearer <AGENT_SECRET>" }
Invoke-RestMethod http://127.0.0.1:8000/api/calendar -Headers $h
Invoke-RestMethod http://127.0.0.1:8000/api/calendar -Method Post -Headers $h `
  -ContentType "application/json" -Body '{"title":"Test","remind_at":"2026-10-06T21:00:00"}'
```

**Firing:** when the server starts, APScheduler runs `_check_reminders` **every 1 minute**. Any
reminder with `remind_at <= now` and `fired=0` triggers a push notification and is marked
`fired=1`. So reminders arrive up to ~60s late, and reminders that came due while the server was
off fire as soon as it starts again.

### 5.4 Push notifications

1. When the phone app connects, it registers `static/sw.js` (service worker), asks for
   notification permission, fetches the public VAPID key from `/api/push/vapid-public-key`, and
   subscribes with the browser's push service (Google/Apple/Mozilla).
2. The subscription is POSTed to `/api/push/register` and saved in `push_subscriptions.json`.
3. When a reminder fires, `agent/push.py` signs a message with `VAPID_PRIVATE_KEY` and sends it to
   every saved subscription. Dead subscriptions are dropped automatically.
4. The service worker shows the notification even if the app is closed; tapping it opens the app.

Requirements: HTTPS (the Cloudflare domain — `localhost` also works for testing), VAPID keys in
`.env`, and on iPhone the app must be **installed to the Home Screen** (iOS 16.4+).
If `VAPID_PRIVATE_KEY` is empty, sending is silently skipped.

### 5.5 Security

- One shared secret, `AGENT_SECRET`, protects the WebSocket (`?token=`) and the REST API
  (`Bearer`). The phone stores it in `sessionStorage` — you'll re-enter it when the browser
  clears the session.
- Server binds to `127.0.0.1`; only the Cloudflare Tunnel can reach it from outside. Cloudflare
  provides the HTTPS.
- Anyone with the token has full access — rotate it in `.env` (and restart) if it leaks. Consider
  adding Cloudflare Access (free) in front of the domain as a second lock.

---

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `python server.py` exits instantly, no output | Old version of `server.py` without the `__main__` block — pull latest |
| Model downloads again | `HF_HOME` not set — check `.env`, or `set HF_HOME=W:\LocalAgent\models` for scripts |
| `CUDA: False` / very slow | torch got replaced by a CPU build — reinstall `torch==2.7.1+cu118` (see session log) |
| `pytest` hangs forever | You ran it with a path that includes `scripts/` — run plain `pytest` (uses `tests/`) |
| Phone: "Connection error" | Wrong token (clear site data), server not running, or tunnel down |
| Reminder created but no notification | Notification permission denied, VAPID keys missing, or iOS app not installed to Home Screen |
| `Address already in use` | Another server is still running on 8000 — close it or set `PORT=` |
