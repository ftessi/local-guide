# Telegram-Free Chat Interface + Calendar — Design Spec
Date: 2026-10-05

## Overview

A self-hosted chat interface accessible from the owner's phone via their own domain, backed by
the local LLM agent. Includes a calendar module with natural-language input and Web Push
reminders delivered directly to the phone — no Telegram, no third-party message relay.

---

## 1. Architecture

```
Phone (PWA installed to home screen)
        │
        │ HTTPS + WebSocket (TLS)
        ▼
Cloudflare (DNS + Tunnel — routing only)
        │
        │ cloudflared tunnel (outbound, dynamic IP safe)
        ▼
FastAPI server (server.py — local)
        │
        ├──── WebSocket handler ──── Agent (LLM + session)
        ├──── REST /calendar ──── Calendar module (SQLite + APScheduler)
        ├──── REST /push ──── Web Push dispatcher (VAPID)
        └──── Static files ──── PWA (HTML/JS/CSS + service worker)
```

**Key properties:**
- Runs entirely on the owner's machine
- Messages never stored outside the machine
- HTTPS enforced by Cloudflare automatically
- Works on dynamic ISP IP — tunnel is outbound from the machine
- No port forwarding needed

---

## 2. Components

### 2.1 Cloudflare Tunnel
- Domain DNS moved to Cloudflare (free)
- `cloudflared` daemon runs as a Windows service
- Routes `yourdomain.com` → `localhost:<port>`
- One-time setup; persists across reboots

### 2.2 FastAPI Server (`server.py`)
Endpoints:
- `GET /` — serves the PWA HTML
- `WS /ws` — WebSocket chat connection (token-authenticated)
- `GET /calendar` — list upcoming reminders
- `POST /calendar` — create reminder (title, datetime)
- `DELETE /calendar/{id}` — delete reminder
- `POST /push/register` — register browser for Web Push
- `GET /static/*` — PWA assets

### 2.3 PWA (`static/`)
- Single HTML file + JS + CSS — no build toolchain
- `manifest.json` — installable to phone home screen
- `sw.js` — service worker for Web Push (receives push even when browser closed)
- WebSocket connection to `/ws` with secret token in header
- Chat interface: message input, scrollable history
- Notification permission prompt on first open

### 2.4 Calendar Module (`agent/calendar.py`)
- SQLite database: `calendar.db` in project root
- Schema: `id, title, remind_at (ISO datetime), fired (bool), created_at`
- APScheduler: checks every minute for due reminders, fires Web Push
- Agent integration: LLM extracts datetime + title from natural language, calls calendar API

### 2.5 Web Push Dispatcher (`agent/push.py`)
- VAPID key pair generated once, stored in `.env`
- `pywebpush` library sends push notifications
- Subscription stored in `push_subscriptions.json` (local)
- Notification payload: `{ title, body, url }` — tapping opens the PWA

---

## 3. Security

### 3.1 Authentication
- Single secret token in `.env` (`AGENT_SECRET`)
- WebSocket: token sent as query param on connect — rejected immediately if wrong
- REST endpoints: `Authorization: Bearer <token>` header required
- No token → no access, LLM never invoked

### 3.2 Transport
- HTTPS enforced by Cloudflare (automatic cert)
- WebSocket runs over WSS (secure WebSocket)
- Cloudflare terminates TLS at edge — message content visible to Cloudflare in transit
  (acceptable for Phase 1; optional second-layer encryption in Phase 2)

### 3.3 Push Security
- VAPID keys: asymmetric, generated locally, stored in `.env`
- Only the local server can send push to registered browser
- Push subscription bound to origin (`yourdomain.com`)

### 3.4 `.env` contents
```
HF_HOME=W:\LocalAgent\models
AGENT_SECRET=<long random string>
VAPID_PRIVATE_KEY=<generated>
VAPID_PUBLIC_KEY=<generated>
VAPID_CLAIMS_EMAIL=<your email>
```

---

## 4. Calendar — Natural Language Flow

User types: `"remind me to call John tomorrow at 3pm"`

1. Agent receives message via WebSocket
2. LLM detects calendar intent (system prompt includes calendar instructions)
3. LLM responds with structured JSON: `{ "action": "create_reminder", "title": "Call John", "remind_at": "2026-10-06T15:00:00" }`
4. Server parses JSON, calls `calendar.create(title, remind_at)`
5. Agent confirms in natural language: "Got it, I'll remind you to call John tomorrow at 3pm."

When reminder fires:
1. APScheduler triggers at `remind_at`
2. Calls `push.send(title="Reminder", body="Call John")`
3. Phone receives Web Push notification (even if screen is off, browser closed)
4. Tapping notification opens PWA

User can also ask: `"what reminders do I have?"` → agent lists from SQLite.
User can ask: `"cancel the John reminder"` → agent calls `calendar.delete(id)`.

---

## 5. File Layout

```
W:\LocalAgent\
  server.py              # FastAPI app — WebSocket + REST + static
  agent/
    calendar.py          # SQLite CRUD + APScheduler
    push.py              # Web Push via pywebpush
    core.py              # (existing) — extended with calendar/push awareness
  static/
    index.html           # PWA chat interface
    manifest.json        # PWA install manifest
    sw.js                # Service worker for Web Push
  calendar.db            # SQLite (auto-created)
  push_subscriptions.json # Web Push subscriptions (auto-created)
  .env                   # Secrets (never commit)
  docs/
    Setup/
      cloudflare-tunnel-setup.md   # Step-by-step Cloudflare setup guide
```

---

## 6. Dependencies to Add

```
fastapi>=0.110.0
uvicorn>=0.27.0
python-dotenv>=1.0.0
apscheduler>=3.10.0
pywebpush>=2.0.0
```

---

## 7. Phase Plan

### Phase 1 (this spec)
- [ ] FastAPI server with WebSocket chat + auth
- [ ] PWA: installable chat interface with push permission
- [ ] Calendar module: SQLite CRUD + APScheduler
- [ ] Web Push dispatcher
- [ ] Agent calendar intent detection
- [ ] Cloudflare Tunnel setup guide

### Phase 2 (future)
- [ ] Second-layer WebSocket encryption (beyond Cloudflare TLS)
- [ ] Multi-device support (multiple push subscriptions)
- [ ] Supabase calendar sync/backup
- [ ] Recurring reminders
