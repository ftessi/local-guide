from unittest.mock import patch

from localagent.connect.owner.push import PushDispatcher

SUB = {"endpoint": "https://example.com/push/123", "keys": {"auth": "a", "p256dh": "b"}}


def test_register_dedup_and_persist(tmp_path):
    p = PushDispatcher(tmp_path / "subs.json", private_key="k")
    p.register(SUB)
    p.register(SUB)
    assert len(PushDispatcher(tmp_path / "subs.json").subscriptions) == 1


def test_send_calls_webpush(tmp_path):
    p = PushDispatcher(tmp_path / "subs.json", private_key="k", claims_email="a@b.c")
    p.register(SUB)
    with patch("localagent.connect.owner.push.webpush") as wp:
        p.send("T", "B")
    assert wp.called and wp.call_args.kwargs["vapid_claims"] == {"sub": "mailto:a@b.c"}


def test_send_without_key_is_noop(tmp_path):
    p = PushDispatcher(tmp_path / "subs.json")
    p.register(SUB)
    with patch("localagent.connect.owner.push.webpush") as wp:
        p.send("T", "B")
    assert not wp.called
