import os
import json
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

load_dotenv()

SECRET = os.getenv("AGENT_SECRET", "")
STATIC_DIR = Path(__file__).parent / "static"

bearer = HTTPBearer(auto_error=False)


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if not credentials or credentials.credentials != SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return credentials.credentials


def verify_ws_token(token: str = "") -> bool:
    return token == SECRET


@asynccontextmanager
async def lifespan(app: FastAPI):
    from agent.llm import LLMEngine
    from agent.session import SessionContext
    from agent.core import Agent
    from agent.calendar import CalendarModule
    from agent.push import PushDispatcher
    from agent.config import MODEL_ID, USE_4BIT

    KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

    print(f"Loading model {MODEL_ID}...")
    app.state.llm = LLMEngine(model_id=MODEL_ID, use_4bit=USE_4BIT)
    app.state.session = SessionContext(knowledge_dir=KNOWLEDGE_DIR)
    app.state.agent = Agent(llm=app.state.llm, session=app.state.session)
    app.state.calendar = CalendarModule()
    app.state.push = PushDispatcher()
    app.state.calendar.start(push=app.state.push)
    print("Server ready.")
    yield
    app.state.calendar.stop()


app = FastAPI(lifespan=lifespan)


# ── WebSocket chat ──────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_chat(ws: WebSocket, token: str = ""):
    if not verify_ws_token(token):
        await ws.close(code=1008)
        return
    await ws.accept()
    agent = app.state.agent
    try:
        while True:
            user_msg = await ws.receive_text()
            async for chunk in agent.chat_stream_async(user_msg, calendar=app.state.calendar):
                await ws.send_text(json.dumps({"type": "chunk", "text": chunk}))
            await ws.send_text(json.dumps({"type": "done"}))
    except WebSocketDisconnect:
        pass


# ── Calendar REST ───────────────────────────────────────────────────────────

class ReminderIn(BaseModel):
    title: str
    remind_at: str


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


# ── Web Push ────────────────────────────────────────────────────────────────

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


# ── Static / PWA ────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def serve_pwa():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
