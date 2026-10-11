import json

import pytest
from fastapi.testclient import TestClient

from localagent.agent.core import Agent
from localagent.agent.tools.registry import load_tools
from localagent.connect.owner.push import PushDispatcher
from localagent.connect.owner.server import create_app
from localagent.protocol.guard import Protocol
from tests.fakes import FakeBackend

TOKEN = "test-secret-token"
CREATE = ('<tool>{"name":"calendar","action":"create",'
          '"args":{"title":"Dentist","remind_at":"2030-01-01T10:00:00"}}</tool>')


@pytest.fixture
def setup(tmp_path):
    push = PushDispatcher(tmp_path / "data/push_subscriptions.json", public_key="test-public-key")
    tools = load_tools({"calendar": {}}, tmp_path / "data", push.send, ["private", "shared"])
    protocol = Protocol.for_agent(tmp_path, ["private", "shared"], tools, owner_secret=TOKEN)
    backend = FakeBackend(replies=["Reminder set! " + CREATE])
    agent = Agent(backend, tools, model_id="org/model")
    app = create_app(protocol=protocol, agent=agent, push=push, tools=tools, run_scheduler=False)
    with TestClient(app) as client:
        yield client, tools


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_tools_require_auth(setup):
    client, _ = setup
    assert client.get("/api/tools/calendar/list").status_code == 401
    assert client.get("/api/tools/calendar/list", headers=auth("wrong")).status_code == 401


def test_calendar_crud(setup):
    client, _ = setup
    assert client.get("/api/tools/calendar/list", headers=auth()).json() == {"reminders": []}
    r = client.post("/api/tools/calendar/create", headers=auth(),
                    json={"title": "Call John", "remind_at": "2030-10-07T15:00:00"})
    assert r.status_code == 200
    rid = r.json()["id"]
    assert client.get("/api/tools/calendar/list", headers=auth()).json()["reminders"][0]["title"] == "Call John"
    assert client.post("/api/tools/calendar/delete", headers=auth(), json={"id": rid}).json() == {"deleted": True}


@pytest.mark.parametrize("method, path, body, status", [
    ("get", "/api/tools/email/send", None, 404),
    ("get", "/api/tools/calendar/create", None, 405),
    ("post", "/api/tools/calendar/create", {"title": "x"}, 422),
])
def test_tool_errors(setup, method, path, body, status):
    client, _ = setup
    kwargs = {"headers": auth()} | ({"json": body} if body is not None else {})
    assert getattr(client, method)(path, **kwargs).status_code == status


def test_websocket_chat_creates_reminder(setup):
    client, tools = setup
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        ws.send_text("remind me")
        text = ""
        while True:
            msg = json.loads(ws.receive_text())
            if msg["type"] == "done":
                break
            text += msg["text"]
    assert text.strip() == "Reminder set!"
    assert [r["title"] for r in tools["calendar"].list_upcoming()] == ["Dentist"]


def test_websocket_bad_token(setup):
    client, _ = setup
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?token=wrong") as ws:
            ws.receive_text()


def test_push_endpoints(setup):
    client, _ = setup
    assert client.get("/api/push/vapid-public-key").json() == {"key": "test-public-key"}
    r = client.post("/api/push/register", headers=auth(),
                    json={"endpoint": "https://push.example.com/1", "keys": {"auth": "a", "p256dh": "b"}})
    assert r.json() == {"registered": True}


def test_root_serves_html(setup):
    client, _ = setup
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
