import pytest
from unittest.mock import patch
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
