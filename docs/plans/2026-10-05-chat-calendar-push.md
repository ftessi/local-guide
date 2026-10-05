# Chat Server + Calendar + Web Push Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-hosted chat interface accessible from the owner's phone via their domain, with a local calendar and Web Push reminders — no Telegram, no third-party message relay.

**Architecture:** FastAPI serves a PWA over a Cloudflare Tunnel. A WebSocket connects the phone to the existing LLM agent. The calendar module stores reminders in SQLite and fires Web Push notifications via APScheduler. Calendar actions are triggered by structured tags in LLM responses.

**Tech Stack:** FastAPI, uvicorn, python-dotenv, APScheduler, pywebpush, plain HTML/JS/CSS PWA (no build toolchain)

**Note:** No git repo in this project — skip all commit steps.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `.env` | Create | Secrets: AGENT_SECRET, VAPID keys, HF_HOME |
| `server.py` | Create | FastAPI app — WebSocket, REST calendar API, static files |
| `agent/calendar.py` | Create | SQLite CRUD + APScheduler reminder firing |
| `agent/push.py` | Create | VAPID key generation + Web Push send |
| `static/index.html` | Create | PWA chat interface |
| `static/manifest.json` | Create | PWA install manifest |
| `static/sw.js` | Create | Service worker — receives push notifications |
| `agent/core.py` | Modify | Add calendar action tag parsing after chat_stream |
| `agent/session.py` | Modify | Add calendar instructions to system prompt |
| `tests/test_calendar.py` | Create | Unit tests for calendar module |
| `tests/test_push.py` | Create | Unit tests for push module |
| `docs/Setup/cloudflare-tunnel-setup.md` | Create | Step-by-step Cloudflare setup guide |

---

## Chunk 1: FastAPI Server + WebSocket Chat

### Task 1: Install dependencies

**Files:** none (just pip installs)

- [ ] **Step 1: Install packages**

```bash
pip install "fastapi>=0.110.0" "uvicorn[standard]>=0.27.0" "python-dotenv>=1.0.0" "apscheduler>=3.10.0" "pywebpush>=2.0.0" websockets
```

- [ ] **Step 2: Verify installs**

```bash
python -c "import fastapi, uvicorn, dotenv, apscheduler, pywebpush; print('all ok')"
```
Expected: `all ok`

---

### Task 2: Create .env file

**Files:**
- Create: `.env`

- [ ] **Step 1: Generate a random secret token**

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Copy the output — this is your AGENT_SECRET.

- [ ] **Step 2: Create `.env`**

```
HF_HOME=W:\LocalAgent\models
AGENT_SECRET=<paste token here>
VAPID_PRIVATE_KEY=
VAPID_PUBLIC_KEY=
VAPID_CLAIMS_EMAIL=your@email.com
```

Leave VAPID keys blank for now — Task 8 generates them.

---

### Task 3: FastAPI server skeleton with auth

**Files:**
- Create: `server.py`

- [ ] **Step 1: Write `server.py`**

```python
import os
import json
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

load_dotenv()

SECRET = os.getenv("AGENT_SECRET", "")
STATIC_DIR = Path(__file__).parent / "static"

bearer = HTTPBearer(auto_error=False)


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if not credentials or credentials.credentials != SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return credentials.credentials


def verify_ws_token(token: str = ""):
    if token != SECRET:
        return False
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Agent and scheduler are initialized here so they load once at startup
    from agent.llm import LLMEngine
    from agent.session import SessionContext
    from agent.core import Agent
    from agent.calendar import CalendarModule
    from agent.push import PushDispatcher

    MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"
    KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

    print("Loading model...")
    app.state.llm = LLMEngine(model_id=MODEL_ID, use_4bit=True)
    app.state.session = SessionContext(knowledge_dir=KNOWLEDGE_DIR)
    app.state.agent = Agent(llm=app.state.llm, session=app.state.session)
    app.state.calendar = CalendarModule()
    app.state.push = PushDispatcher()

    app.state.calendar.start(push=app.state.push)
    print("Server ready.")
    yield
    app.state.calendar.stop()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws")
async def websocket_chat(ws: WebSocket, token: str = ""):
    if not verify_ws_token(token):
        await ws.close(code=1008)
        return
    await ws.accept()
    agent: "Agent" = app.state.agent
    try:
        while True:
            user_msg = await ws.receive_text()
            full_reply = []
            async for chunk in agent.chat_stream_async(user_msg, calendar=app.state.calendar):
                full_reply.append(chunk)
                await ws.send_text(json.dumps({"type": "chunk", "text": chunk}))
            await ws.send_text(json.dumps({"type": "done"}))
    except WebSocketDisconnect:
        pass


# Mount static files (PWA)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def serve_pwa():
    return FileResponse(STATIC_DIR / "index.html")
```

- [ ] **Step 2: Create `static/` directory placeholder**

Create an empty file `static/.gitkeep` so the directory exists.

- [ ] **Step 3: Smoke test — server starts**

```bash
python -c "
import os; os.environ['AGENT_SECRET']='test'
from server import app
print('server imports ok')
"
```
Expected: `server imports ok` (model does NOT load here — lifespan only runs with uvicorn)

---

### Task 4: Async chat stream in Agent

The WebSocket handler needs `chat_stream_async` — an async generator wrapping the existing sync generator.

**Files:**
- Modify: `agent/core.py`

- [ ] **Step 1: Read current `agent/core.py`**

Current file has `chat()` and `chat_stream()` (sync generator).

- [ ] **Step 2: Add `chat_stream_async` and calendar action parsing**

Add to `agent/core.py`:

```python
import asyncio
import json
import re

# Regex to find calendar action tags in LLM output
_ACTION_RE = re.compile(r'\[ACTION:calendar:(\w+)(?::(\{.*?\}))?\]', re.DOTALL)


def _parse_calendar_actions(text: str):
    """Extract and return list of (action, payload_dict) tuples found in text."""
    actions = []
    for match in _ACTION_RE.finditer(text):
        action = match.group(1)
        payload = json.loads(match.group(2)) if match.group(2) else {}
        actions.append((action, payload))
    return actions


def _strip_action_tags(text: str) -> str:
    return _ACTION_RE.sub("", text).strip()


class Agent:
    # ... existing __init__, chat, chat_stream, reset ...

    async def chat_stream_async(self, user_message: str, calendar=None):
        """Async generator version of chat_stream. Executes calendar actions after reply."""
        self._history.append({"role": "user", "content": user_message})
        messages = [
            {"role": "system", "content": self.session.build_system_prompt(scope=None)}
        ] + self._history

        full_reply = []
        loop = asyncio.get_event_loop()

        # Run the sync generator in a thread so we don't block the event loop
        import concurrent.futures
        chunks = []

        def _collect():
            return list(self.llm.generate_stream(messages))

        with concurrent.futures.ThreadPoolExecutor() as pool:
            chunks = await loop.run_in_executor(pool, _collect)

        for chunk in chunks:
            clean = _strip_action_tags(chunk)
            if clean:
                full_reply.append(clean)
                yield clean

        full_text = "".join(full_reply)
        raw_text = "".join(chunks)

        # Execute any calendar actions embedded in the response
        if calendar:
            for action, payload in _parse_calendar_actions(raw_text):
                if action == "create" and "title" in payload and "remind_at" in payload:
                    calendar.create(payload["title"], payload["remind_at"])
                elif action == "delete" and "id" in payload:
                    calendar.delete(payload["id"])

        self._history.append({"role": "assistant", "content": full_text})
```

**Important:** Do NOT replace the existing `Agent` class — add `chat_stream_async`, `_parse_calendar_actions`, and `_strip_action_tags` alongside the existing methods.

- [ ] **Step 3: Run existing tests to confirm nothing broke**

```bash
.venv\Scripts\pytest tests/test_core.py tests/test_session.py -v
```
Expected: 6 passed.

---

### Task 5: Calendar instructions in system prompt

**Files:**
- Modify: `agent/session.py`

- [ ] **Step 1: Add calendar system prompt section**

In `agent/session.py`, update `BASE_PROMPT`:

```python
BASE_PROMPT = """You are a helpful local AI assistant.

You can manage the user's calendar. When the user asks you to set a reminder or schedule something, include a structured action tag at the END of your reply (after your natural language response):
- Create reminder: [ACTION:calendar:create:{"title":"<title>","remind_at":"<ISO 8601 datetime, e.g. 2026-10-06T15:00:00>"}]
- Delete reminder: [ACTION:calendar:delete:{"id":<integer id>}]
- To list reminders, just say you will show them — the server will fetch and display them.

Today's date and time is {datetime_now}. Use this to interpret relative times like "tomorrow" or "in 2 hours"."""
```

Then update `build_system_prompt` to inject the current datetime:

```python
from datetime import datetime

def build_system_prompt(self, scope: list[str] | None) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    sections = [BASE_PROMPT.format(datetime_now=now)]
    # ... rest unchanged ...
```

- [ ] **Step 2: Run session tests**

```bash
.venv\Scripts\pytest tests/test_session.py -v
```
Expected: 3 passed.

---

## Chunk 2: Calendar Module

### Task 6: Calendar module with SQLite

**Files:**
- Create: `agent/calendar.py`
- Create: `tests/test_calendar.py`

- [ ] **Step 1: Write tests**

Create `tests/test_calendar.py`:
```python
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from agent.calendar import CalendarModule


@pytest.fixture
def cal(tmp_path):
    return CalendarModule(db_path=str(tmp_path / "test.db"))


def test_create_and_list(cal):
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    id_ = cal.create("Call John", future)
    items = cal.list_upcoming()
    assert len(items) == 1
    assert items[0]["title"] == "Call John"
    assert items[0]["id"] == id_


def test_delete(cal):
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    id_ = cal.create("Test", future)
    assert cal.delete(id_) is True
    assert cal.list_upcoming() == []


def test_delete_nonexistent(cal):
    assert cal.delete(999) is False


def test_due_reminders(cal):
    past = (datetime.now() - timedelta(seconds=1)).isoformat()
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    cal.create("Overdue", past)
    cal.create("Future", future)
    due = cal.get_due()
    assert len(due) == 1
    assert due[0]["title"] == "Overdue"


def test_mark_fired(cal):
    past = (datetime.now() - timedelta(seconds=1)).isoformat()
    id_ = cal.create("Overdue", past)
    cal.mark_fired(id_)
    assert cal.get_due() == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv\Scripts\pytest tests/test_calendar.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement `agent/calendar.py`**

```python
import sqlite3
from datetime import datetime
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler


DB_PATH = Path(__file__).parent.parent / "calendar.db"


class CalendarModule:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(DB_PATH)
        self._scheduler = None
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    fired INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)

    def create(self, title: str, remind_at: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO reminders (title, remind_at) VALUES (?, ?)",
                (title, remind_at)
            )
            return cur.lastrowid

    def list_upcoming(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE fired=0 ORDER BY remind_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def delete(self, id_: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM reminders WHERE id=?", (id_,))
            return cur.rowcount > 0

    def get_due(self) -> list[dict]:
        now = datetime.now().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE fired=0 AND remind_at <= ?", (now,)
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_fired(self, id_: int):
        with self._connect() as conn:
            conn.execute("UPDATE reminders SET fired=1 WHERE id=?", (id_,))

    def start(self, push=None):
        self._scheduler = BackgroundScheduler()
        cal = self

        def _check_reminders():
            for reminder in cal.get_due():
                if push:
                    push.send(
                        title="Reminder",
                        body=reminder["title"]
                    )
                cal.mark_fired(reminder["id"])

        self._scheduler.add_job(_check_reminders, "interval", minutes=1)
        self._scheduler.start()

    def stop(self):
        if self._scheduler:
            self._scheduler.shutdown()
```

- [ ] **Step 4: Run tests**

```bash
.venv\Scripts\pytest tests/test_calendar.py -v
```
Expected: 5 passed.

---

### Task 7: Calendar REST endpoints

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Add calendar routes to `server.py`**

Add after the `verify_token` function:

```python
from pydantic import BaseModel

class ReminderIn(BaseModel):
    title: str
    remind_at: str  # ISO 8601


@app.get("/api/calendar", dependencies=[Depends(verify_token)])
async def list_reminders():
    return app.state.calendar.list_upcoming()


@app.post("/api/calendar", dependencies=[Depends(verify_token)])
async def create_reminder(body: ReminderIn):
    id_ = app.state.calendar.create(body.title, body.remind_at)
    return {"id": id_}


@app.delete("/api/calendar/{id_}", dependencies=[Depends(verify_token)])
async def delete_reminder(id_: int):
    ok = app.state.calendar.delete(id_)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": id_}
```

---

## Chunk 3: Web Push + PWA

### Task 8: Web Push dispatcher

**Files:**
- Create: `agent/push.py`
- Create: `tests/test_push.py`

- [ ] **Step 1: Generate VAPID keys (one-time)**

```bash
python -c "
from pywebpush import generate_vapid_keys
keys = generate_vapid_keys()
print('VAPID_PRIVATE_KEY=' + keys['private_key'])
print('VAPID_PUBLIC_KEY=' + keys['public_key'])
"
```

Copy both lines into `.env`.

- [ ] **Step 2: Write tests**

Create `tests/test_push.py`:
```python
import pytest
import json
from unittest.mock import patch, MagicMock
from agent.push import PushDispatcher


@pytest.fixture
def push(tmp_path, monkeypatch):
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "test_private")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "test_public")
    monkeypatch.setenv("VAPID_CLAIMS_EMAIL", "test@test.com")
    return PushDispatcher(subs_path=str(tmp_path / "subs.json"))


def test_register_subscription(push):
    sub = {"endpoint": "https://example.com/push/123", "keys": {"auth": "a", "p256dh": "b"}}
    push.register(sub)
    assert len(push.subscriptions) == 1


def test_register_deduplicates(push):
    sub = {"endpoint": "https://example.com/push/123", "keys": {"auth": "a", "p256dh": "b"}}
    push.register(sub)
    push.register(sub)
    assert len(push.subscriptions) == 1


def test_send_calls_webpush(push):
    sub = {"endpoint": "https://example.com/push/123", "keys": {"auth": "a", "p256dh": "b"}}
    push.register(sub)
    with patch("agent.push.webpush") as mock_wp:
        push.send("Test", "Body")
        assert mock_wp.called
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
.venv\Scripts\pytest tests/test_push.py -v
```
Expected: `ImportError`

- [ ] **Step 4: Implement `agent/push.py`**

```python
import json
import os
from pathlib import Path
from pywebpush import webpush, WebPushException

SUBS_PATH = Path(__file__).parent.parent / "push_subscriptions.json"


class PushDispatcher:
    def __init__(self, subs_path: str | None = None):
        self.subs_path = Path(subs_path or SUBS_PATH)
        self.private_key = os.getenv("VAPID_PRIVATE_KEY", "")
        self.public_key = os.getenv("VAPID_PUBLIC_KEY", "")
        self.claims_email = os.getenv("VAPID_CLAIMS_EMAIL", "admin@localhost")
        self.subscriptions: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if self.subs_path.exists():
            return json.loads(self.subs_path.read_text())
        return []

    def _save(self):
        self.subs_path.write_text(json.dumps(self.subscriptions, indent=2))

    def register(self, subscription: dict):
        endpoint = subscription.get("endpoint")
        if not any(s.get("endpoint") == endpoint for s in self.subscriptions):
            self.subscriptions.append(subscription)
            self._save()

    def send(self, title: str, body: str):
        payload = json.dumps({"title": title, "body": body})
        failed = []
        for sub in self.subscriptions:
            try:
                webpush(
                    subscription_info=sub,
                    data=payload,
                    vapid_private_key=self.private_key,
                    vapid_claims={"sub": f"mailto:{self.claims_email}"},
                )
            except WebPushException:
                failed.append(sub.get("endpoint"))
        # Remove dead subscriptions
        if failed:
            self.subscriptions = [s for s in self.subscriptions if s.get("endpoint") not in failed]
            self._save()
```

- [ ] **Step 5: Run tests**

```bash
.venv\Scripts\pytest tests/test_push.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Add push register endpoint to `server.py`**

```python
class PushSubscription(BaseModel):
    endpoint: str
    keys: dict


@app.post("/api/push/register", dependencies=[Depends(verify_token)])
async def register_push(sub: PushSubscription):
    app.state.push.register(sub.model_dump())
    return {"registered": True}


@app.get("/api/push/vapid-public-key")
async def get_vapid_public_key():
    return {"key": os.getenv("VAPID_PUBLIC_KEY", "")}
```

---

### Task 9: PWA — service worker

**Files:**
- Create: `static/sw.js`

- [ ] **Step 1: Create `static/sw.js`**

```javascript
self.addEventListener('push', function(event) {
    const data = event.data ? event.data.json() : { title: 'Reminder', body: '' };
    event.waitUntil(
        self.registration.showNotification(data.title, {
            body: data.body,
            icon: '/static/icon.png',
            badge: '/static/icon.png'
        })
    );
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    event.waitUntil(clients.openWindow('/'));
});
```

---

### Task 10: PWA — manifest and chat interface

**Files:**
- Create: `static/manifest.json`
- Create: `static/index.html`

- [ ] **Step 1: Create `static/manifest.json`**

```json
{
    "name": "Local Agent",
    "short_name": "Agent",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#1a1a2e",
    "theme_color": "#16213e",
    "icons": [
        { "src": "/static/icon.png", "sizes": "192x192", "type": "image/png" }
    ]
}
```

- [ ] **Step 2: Create a placeholder icon**

```bash
python -c "
# Create a minimal 1x1 transparent PNG as placeholder icon
import base64, pathlib
png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
pathlib.Path('static/icon.png').write_bytes(png)
print('icon created')
"
```

- [ ] **Step 3: Create `static/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Local Agent</title>
    <link rel="manifest" href="/static/manifest.json">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: system-ui, sans-serif; background: #1a1a2e; color: #e0e0e0; height: 100dvh; display: flex; flex-direction: column; }
        #status { padding: 8px 16px; font-size: 12px; background: #16213e; color: #888; }
        #status.connected { color: #4caf50; }
        #status.error { color: #f44336; }
        #messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
        .msg { max-width: 80%; padding: 10px 14px; border-radius: 18px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
        .msg.user { align-self: flex-end; background: #0f3460; border-bottom-right-radius: 4px; }
        .msg.agent { align-self: flex-start; background: #16213e; border-bottom-left-radius: 4px; }
        .msg.agent.streaming { border-left: 3px solid #4caf50; }
        #form { display: flex; padding: 12px; gap: 8px; background: #16213e; }
        #input { flex: 1; padding: 12px; border-radius: 24px; border: 1px solid #333; background: #0f1923; color: #e0e0e0; font-size: 16px; outline: none; }
        #input:focus { border-color: #4caf50; }
        #send { padding: 12px 20px; border-radius: 24px; border: none; background: #4caf50; color: #fff; font-size: 16px; cursor: pointer; }
        #send:disabled { background: #333; cursor: default; }
    </style>
</head>
<body>
    <div id="status">Connecting...</div>
    <div id="messages"></div>
    <form id="form">
        <input id="input" type="text" placeholder="Message..." autocomplete="off" disabled>
        <button id="send" type="submit" disabled>Send</button>
    </form>

    <script>
        const TOKEN = prompt("Enter access token:") || "";
        const WS_URL = `wss://${location.host}/ws?token=${encodeURIComponent(TOKEN)}`;
        const VAPID_KEY_URL = "/api/push/vapid-public-key";
        const PUSH_REGISTER_URL = "/api/push/register";

        const statusEl = document.getElementById("status");
        const messagesEl = document.getElementById("messages");
        const inputEl = document.getElementById("input");
        const sendBtn = document.getElementById("send");

        let ws, currentAgentMsg = null;

        function connect() {
            ws = new WebSocket(WS_URL);

            ws.onopen = () => {
                statusEl.textContent = "Connected";
                statusEl.className = "connected";
                inputEl.disabled = false;
                sendBtn.disabled = false;
                setupPush();
            };

            ws.onclose = () => {
                statusEl.textContent = "Disconnected — refresh to reconnect";
                statusEl.className = "error";
                inputEl.disabled = true;
                sendBtn.disabled = true;
            };

            ws.onerror = () => {
                statusEl.textContent = "Connection error";
                statusEl.className = "error";
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === "chunk") {
                    if (!currentAgentMsg) {
                        currentAgentMsg = appendMessage("", "agent streaming");
                    }
                    currentAgentMsg.textContent += data.text;
                    messagesEl.scrollTop = messagesEl.scrollHeight;
                } else if (data.type === "done") {
                    if (currentAgentMsg) {
                        currentAgentMsg.className = "msg agent";
                        currentAgentMsg = null;
                    }
                    sendBtn.disabled = false;
                    inputEl.disabled = false;
                    inputEl.focus();
                }
            };
        }

        function appendMessage(text, cls) {
            const el = document.createElement("div");
            el.className = `msg ${cls}`;
            el.textContent = text;
            messagesEl.appendChild(el);
            messagesEl.scrollTop = messagesEl.scrollHeight;
            return el;
        }

        document.getElementById("form").addEventListener("submit", (e) => {
            e.preventDefault();
            const text = inputEl.value.trim();
            if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
            appendMessage(text, "user");
            ws.send(text);
            inputEl.value = "";
            sendBtn.disabled = true;
            inputEl.disabled = true;
        });

        async function setupPush() {
            if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
            try {
                const reg = await navigator.serviceWorker.register("/static/sw.js");
                const perm = await Notification.requestPermission();
                if (perm !== "granted") return;

                const keyResp = await fetch(VAPID_KEY_URL);
                const { key } = await keyResp.json();

                const sub = await reg.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: urlBase64ToUint8Array(key)
                });

                await fetch(PUSH_REGISTER_URL, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "Authorization": `Bearer ${TOKEN}`
                    },
                    body: JSON.stringify(sub.toJSON())
                });
            } catch (e) {
                console.warn("Push setup failed:", e);
            }
        }

        function urlBase64ToUint8Array(base64String) {
            const padding = '='.repeat((4 - base64String.length % 4) % 4);
            const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
            const rawData = atob(base64);
            return Uint8Array.from([...rawData].map(c => c.charCodeAt(0)));
        }

        connect();
    </script>
</body>
</html>
```

---

### Task 11: Cloudflare Tunnel setup guide

**Files:**
- Create: `docs/Setup/cloudflare-tunnel-setup.md`

- [ ] **Step 1: Create the guide**

```markdown
# Cloudflare Tunnel Setup Guide

## Prerequisites
- A domain registered anywhere (GoDaddy, Namecheap, etc.)
- A free Cloudflare account at cloudflare.com

## Step 1: Move DNS to Cloudflare
1. Log in to Cloudflare → Add a site → Enter your domain
2. Choose the Free plan
3. Cloudflare shows you two nameservers (e.g. `ara.ns.cloudflare.com`)
4. Go to your domain registrar → change nameservers to Cloudflare's
5. Wait up to 24h for propagation (usually < 1h)

## Step 2: Install cloudflared on Windows
Download from: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
Direct link: https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.msi

Run the installer.

## Step 3: Authenticate
```bash
cloudflared tunnel login
```
A browser window opens — log in to Cloudflare and select your domain.

## Step 4: Create a tunnel
```bash
cloudflared tunnel create local-agent
```
Note the tunnel ID printed (e.g. `abc123-...`).

## Step 5: Create tunnel config
Create `C:\Users\<you>\.cloudflared\config.yml`:
```yaml
tunnel: <your-tunnel-id>
credentials-file: C:\Users\<you>\.cloudflared\<tunnel-id>.json

ingress:
  - hostname: yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
```

## Step 6: Route DNS
```bash
cloudflared tunnel route dns local-agent yourdomain.com
```

## Step 7: Run the tunnel (test)
First start the FastAPI server:
```bash
cd W:\LocalAgent
set HF_HOME=W:\LocalAgent\models
.venv\Scripts\uvicorn server:app --host 127.0.0.1 --port 8000
```

In another terminal:
```bash
cloudflared tunnel run local-agent
```

Open https://yourdomain.com on your phone — you should see the chat interface.

## Step 8: Run as Windows Service (auto-start)
```bash
cloudflared service install
```
This installs cloudflared as a Windows service that starts automatically.

To also auto-start the FastAPI server, create a batch file `W:\LocalAgent\start_agent.bat`:
```batch
@echo off
cd W:\LocalAgent
set HF_HOME=W:\LocalAgent\models
.venv\Scripts\uvicorn server:app --host 127.0.0.1 --port 8000
```
Add it to Windows Task Scheduler → trigger: At startup.
```

---

## Done

After Task 11:
- Run `uvicorn server:app --port 8000` locally and open `http://localhost:8000` to test
- Set up Cloudflare Tunnel to expose it on your domain
- Install the PWA from your phone browser (Add to Home Screen)
- Test a reminder: "Remind me to test this in 2 minutes"
- Check push notification arrives even with browser in background

Next: Phase 2 of the zero-trust inter-agent protocol.
```
