"""Tests for FastAPI server endpoints — no model loading."""
import pytest
import os
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

TOKEN = "test-secret-token"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SECRET", TOKEN)
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "test-public-key")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "")
    monkeypatch.setenv("VAPID_CLAIMS_EMAIL", "test@test.com")

    from contextlib import asynccontextmanager
    from agent.calendar import CalendarModule
    from agent.push import PushDispatcher
    import server

    mock_agent = MagicMock()

    @asynccontextmanager
    async def mock_lifespan(app):
        app.state.calendar = CalendarModule(db_path=str(tmp_path / "test.db"))
        app.state.push = PushDispatcher(subs_path=str(tmp_path / "subs.json"))
        app.state.agent = mock_agent
        app.state.calendar.start(push=app.state.push)
        yield
        app.state.calendar.stop()

    # Override the lifespan directly on the router (where FastAPI stores it)
    original = server.app.router.lifespan_context
    server.app.router.lifespan_context = mock_lifespan
    try:
        with TestClient(server.app) as c:
            yield c
    finally:
        server.app.router.lifespan_context = original


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_calendar_requires_auth(client):
    r = client.get("/api/calendar")
    assert r.status_code == 401


def test_wrong_token_rejected(client):
    r = client.get("/api/calendar", headers=auth("wrong"))
    assert r.status_code == 401


# ── Calendar CRUD ─────────────────────────────────────────────────────────────

def test_list_empty(client):
    r = client.get("/api/calendar", headers=auth())
    assert r.status_code == 200
    assert r.json() == []


def test_create_reminder(client):
    r = client.post("/api/calendar", headers=auth(), json={
        "title": "Call John",
        "remind_at": "2026-10-07T15:00:00"
    })
    assert r.status_code == 200
    assert "id" in r.json()


def test_list_after_create(client):
    client.post("/api/calendar", headers=auth(), json={
        "title": "Test", "remind_at": "2026-10-07T15:00:00"
    })
    r = client.get("/api/calendar", headers=auth())
    assert len(r.json()) == 1
    assert r.json()[0]["title"] == "Test"


def test_delete_reminder(client):
    r = client.post("/api/calendar", headers=auth(), json={
        "title": "To Delete", "remind_at": "2026-10-07T15:00:00"
    })
    id_ = r.json()["id"]
    r = client.delete(f"/api/calendar/{id_}", headers=auth())
    assert r.status_code == 200
    assert client.get("/api/calendar", headers=auth()).json() == []


def test_delete_nonexistent(client):
    r = client.delete("/api/calendar/999", headers=auth())
    assert r.status_code == 404


# ── Push ──────────────────────────────────────────────────────────────────────

def test_vapid_public_key(client):
    r = client.get("/api/push/vapid-public-key")
    assert r.status_code == 200
    assert r.json()["key"] == "test-public-key"


def test_register_push(client):
    r = client.post("/api/push/register", headers=auth(), json={
        "endpoint": "https://push.example.com/123",
        "keys": {"auth": "abc", "p256dh": "def"}
    })
    assert r.status_code == 200
    assert r.json()["registered"] is True


# ── PWA ───────────────────────────────────────────────────────────────────────

def test_root_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
