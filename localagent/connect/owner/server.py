"""Owner transport: phone/PC web app over WebSocket, tool REST API, push registration."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from localagent.protocol.guard import AuthError

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
STATUS = {"unknown": 404, "denied": 403, "withheld": 403, "bad_args": 422, "failed": 500}


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict


def _run_background(tools: dict) -> None:
    for name, tool in tools.items():
        try:
            tool.background()
        except Exception:
            log.exception("Background job of tool %s failed", name)


async def _stream_reply(agent, session, text: str):
    """Run the blocking agent turn in a thread and yield its chunks as they arrive."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def worker():
        try:
            for chunk in agent.respond_stream(session, text):
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
        except Exception as e:
            log.exception("Turn failed")
            loop.call_soon_threadsafe(queue.put_nowait, f"\n[error] {e}")
        loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, worker)
    while (chunk := await queue.get()) is not None:
        yield chunk


def create_app(*, protocol, agent, push, tools: dict, run_scheduler: bool = True) -> FastAPI:
    bearer = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(app):
        scheduler = None
        if run_scheduler:
            scheduler = BackgroundScheduler()
            scheduler.add_job(_run_background, "interval", minutes=1, args=[tools])
            scheduler.start()
        yield
        if scheduler:
            scheduler.shutdown()

    app = FastAPI(lifespan=lifespan)

    def owner_session(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        try:
            return protocol.open_owner_session(credentials.credentials if credentials else "")
        except AuthError:
            raise HTTPException(status_code=401)

    # ── Chat ────────────────────────────────────────────────────────────────

    @app.websocket("/ws")
    async def websocket_chat(ws: WebSocket, token: str = ""):
        try:
            session = protocol.open_owner_session(token)
        except AuthError:
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            while True:
                text = await ws.receive_text()
                async for chunk in _stream_reply(agent, session, text):
                    await ws.send_text(json.dumps({"type": "chunk", "text": chunk}))
                await ws.send_text(json.dumps({"type": "done"}))
        except WebSocketDisconnect:
            pass
        finally:
            session.close()

    # ── Tools ───────────────────────────────────────────────────────────────

    def _call(session, name: str, action: str, args: dict):
        try:
            outcome = agent.run_tool(session, name, action, args)
        finally:
            session.close()
        if not outcome.ok:
            raise HTTPException(status_code=STATUS[outcome.error_type], detail=outcome.error)
        return outcome.result

    @app.get("/api/tools/{name}/{action}")
    async def tool_get(name: str, action: str, request: Request, session=Depends(owner_session)):
        spec = getattr(tools.get(name), "actions", {}).get(action)
        if spec is not None and spec.kind != "read":
            session.close()
            raise HTTPException(status_code=405, detail="Use POST for actions that change data")
        return await run_in_threadpool(_call, session, name, action, dict(request.query_params))

    @app.post("/api/tools/{name}/{action}")
    async def tool_post(name: str, action: str, request: Request, session=Depends(owner_session)):
        body = await request.body()
        try:
            args = json.loads(body) if body else {}
        except json.JSONDecodeError:
            session.close()
            raise HTTPException(status_code=422, detail="Body must be JSON")
        return await run_in_threadpool(_call, session, name, action, args)

    # ── Push ────────────────────────────────────────────────────────────────

    @app.post("/api/push/register")
    async def register_push(sub: PushSubscription, session=Depends(owner_session)):
        session.close()
        push.register(sub.model_dump())
        return {"registered": True}

    @app.get("/api/push/vapid-public-key")
    async def vapid_public_key():
        return {"key": push.public_key}

    # ── PWA ─────────────────────────────────────────────────────────────────

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def serve_pwa():
        return FileResponse(STATIC_DIR / "index.html")

    return app
