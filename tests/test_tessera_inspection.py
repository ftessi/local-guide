import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from localagent.__main__ import main
from localagent.config import load_config
from localagent.connect.peer.tessera import inspection_sender
from localagent.protocol.identity import (generate_identity, identity_from_seed, load_identity, x25519_from_seed,
                                          x25519_public)
from localagent.protocol.tessera import inspection
from localagent.protocol.tessera.envelope import envelope_hash, sign_envelope
from localagent.tessera_cli import protocol_for
from tests.fakes import write_agent_yaml

A = identity_from_seed(bytes(range(32)))
B = identity_from_seed(bytes(range(32, 64)))
EKEY = x25519_public(x25519_from_seed(bytes(range(128, 160))))
COMPANY = x25519_from_seed(bytes(range(200, 232)))
YAML = "name: a\nmodel:\n  id: org/model\ncompartments: [demo]\n"
NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def company_key(monkeypatch):
    monkeypatch.setattr(inspection, "COMPANY_KEY", x25519_public(COMPANY))


def record(sid, *, closed=True, expires="2030-01-01T00:00:00Z", me=None):
    me = me or A
    hello = sign_envelope(B, type="hello", session="", to=me.agent_id, seq=0, prev="",
                          body={"purpose": "p", "requested_level": 1, "nonce": "n", "e": EKEY}, now=NOW)
    welcome = sign_envelope(me, type="welcome", session="", to=B.agent_id, seq=1, prev=envelope_hash(hello),
                            body={"session": sid, "granted_level": 1, "expires": expires,
                                  "limits": {"asks": 5, "ask_chars": 100}, "f": EKEY}, now=NOW)
    envs = [hello, welcome]
    if closed:
        envs.append(sign_envelope(B, type="close", session=sid, to=me.agent_id, seq=2,
                                  prev=envelope_hash(welcome), body={}, now=NOW))
    return envs


def agent(tmp_path, sessions):
    d = write_agent_yaml(tmp_path / "a", YAML, installables=None)
    generate_identity(d / "identity")
    me = load_identity(d / "identity")
    p = protocol_for(load_config(d))
    for sid, kwargs in sessions.items():
        for env in record(sid, me=me, **kwargs):
            p.record_envelope(B.agent_id, sid, env)
    return d, me, p


def test_an_upload_opens_only_with_the_company_key():
    raw = inspection.seal_upload(A, x25519_public(COMPANY), peer=B.agent_id, session="s-1",
                                 envelopes=record("s-1"), now=NOW)
    assert b"s-1" not in raw and B.agent_id.encode() not in raw
    payload = inspection.open_upload(COMPANY, raw)
    assert payload["agent_id"] == A.agent_id and payload["envelopes"] == record("s-1")
    with pytest.raises(inspection.InspectionError):
        inspection.open_upload(x25519_from_seed(bytes(range(1, 33))), raw)
    tampered = json.loads(raw)
    tampered["e"] = EKEY
    with pytest.raises(inspection.InspectionError):
        inspection.open_upload(COMPANY, json.dumps(tampered).encode())


def test_finished_sessions():
    assert inspection_sender.finished(record("s", closed=True), NOW)
    assert not inspection_sender.finished(record("s", closed=False), NOW)
    assert inspection_sender.finished(record("s", closed=False, expires="2020-01-01T00:00:00Z"), NOW)


def test_turning_inspection_on_sends_earlier_finished_conversations_once(tmp_path, capsys):
    d, me, p = agent(tmp_path, {"s-1": {}, "s-2": {"closed": False}})
    sent = []
    inspection_sender_upload = inspection_sender.upload
    try:
        inspection_sender.upload = lambda relay, raw, **kw: sent.append((relay, raw))
        assert main(["inspection", "on", "--relay", "http://relay.example", "--agent", str(d)]) == 0
        assert "including the other agents' messages" in capsys.readouterr().out
        assert [inspection.open_upload(COMPANY, raw)["session"] for _, raw in sent] == ["s-1"]
        assert inspection_sender.send_finished(d, p, me) == 0  # not twice
        for env in record("s-3", me=me):
            p.record_envelope(B.agent_id, "s-3", env)
        assert inspection_sender.send_finished(d, p, me) == 1
        assert main(["inspection", "off", "--agent", str(d)]) == 0
        for env in record("s-4", me=me):
            p.record_envelope(B.agent_id, "s-4", env)
        assert inspection_sender.send_finished(d, p, me) == 0
    finally:
        inspection_sender.upload = inspection_sender_upload


def test_a_failed_upload_is_sent_next_time(tmp_path):
    d, me, p = agent(tmp_path, {"s-1": {}})
    inspection_sender.save_state(d, {"enabled": True, "relay": "http://r", "sent": []})

    def down(relay, raw, **kw):
        raise OSError("unreachable")

    assert inspection_sender.send_finished(d, p, me, post=down) == 0
    assert inspection_sender.load_state(d)["sent"] == []
    assert inspection_sender.send_finished(d, p, me, post=lambda relay, raw, **kw: None) == 1


def test_the_company_key_comes_from_the_code_only(tmp_path, monkeypatch):
    d, me, p = agent(tmp_path, {"s-1": {}})
    inspection_sender.save_state(d, {"enabled": True, "relay": "http://r", "sent": [], "company_key": EKEY})
    got = []
    inspection_sender.send_finished(d, p, me, post=lambda relay, raw, **kw: got.append(raw))
    assert inspection.open_upload(COMPANY, got[0])["session"] == "s-1"
    monkeypatch.setattr(inspection, "COMPANY_KEY", "")
    assert main(["inspection", "on", "--relay", "http://r", "--agent", str(d)]) == 2


def test_inspection_on_needs_a_relay(tmp_path):
    d, *_ = agent(tmp_path, {})
    assert main(["inspection", "on", "--agent", str(d)]) == 2


def test_connect_prints_the_notice(tmp_path, capsys):
    d, *_ = agent(tmp_path, {})
    assert main(["connect", "http://x", B.agent_id, "--name", "bob", "--purpose", "p", "--agent", str(d)]) == 0
    assert inspection.ASKER_NOTICE in capsys.readouterr().out


def test_inspect_command(tmp_path, capsys):
    key_file = tmp_path / "company.pem"
    key_file.write_bytes(COMPANY.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    upload = tmp_path / "x.sealed"
    upload.write_bytes(inspection.seal_upload(A, x25519_public(COMPANY), peer=B.agent_id, session="s-1",
                                              envelopes=record("s-1"), now=NOW))
    assert main(["inspect", str(upload), "--key", str(key_file), "--delete"]) == 0
    assert '"session": "s-1"' in capsys.readouterr().out and not upload.exists()
    upload.write_bytes(b"garbage")
    assert main(["inspect", str(upload), "--key", str(key_file)]) == 2


def test_new_inspection_key_script(tmp_path, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("nik", "scripts/new_inspection_key.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--out", str(tmp_path / "k.pem")]) == 0
    assert "COMPANY_KEY" in capsys.readouterr().out and (tmp_path / "k.pem").is_file()
    assert module.main(["--out", str(tmp_path / "k.pem")]) == 2  # never overwrites


def test_inspection_off_in_another_process_stops_a_running_send(tmp_path):
    d, me, p = agent(tmp_path, {"s-1": {}, "s-2": {}})
    inspection_sender.save_state(d, {"enabled": True, "relay": "http://r", "sent": []})
    got = []

    def post(relay, raw, **kw):
        got.append(raw)
        assert main(["inspection", "off", "--agent", str(d)]) == 0  # the owner, meanwhile

    assert inspection_sender.send_finished(d, p, me, post=post) == 1
    assert len(got) == 1 and inspection_sender.load_state(d)["enabled"] is False


def test_an_unreadable_record_doesnt_stop_the_others(tmp_path):
    d, me, p = agent(tmp_path, {"s-1": {}, "s-2": {}})
    (d / "tessera" / B.agent_id / "s-1.jsonl").write_text("{broken\n", encoding="utf-8")
    inspection_sender.save_state(d, {"enabled": True, "relay": "http://r", "sent": []})
    got = []
    assert inspection_sender.send_finished(d, p, me, post=lambda relay, raw, **kw: got.append(raw)) == 1
    assert inspection.open_upload(COMPANY, got[0])["session"] == "s-2"


def test_ask_prints_the_answer_even_if_sending_for_inspection_breaks(tmp_path, capsys, monkeypatch):
    import http.client
    from localagent import tessera_cli
    from localagent.connect.peer.tessera.client import Reply
    d, *_ = agent(tmp_path, {})
    inspection_sender.save_state(d, {"enabled": True, "relay": "http://r", "sent": []})
    order = []

    class FakeAsker:
        def ask(self, name, question):
            return tessera_cli.Answer("The answer.", Reply("answer", "The answer."))

        def close_all(self):
            pass

    def broken(*args, **kwargs):
        order.append(capsys.readouterr().out)  # what the user already sees when sending starts
        raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(tessera_cli, "make_asker", lambda config: FakeAsker())
    monkeypatch.setattr(inspection_sender, "send_finished", broken)
    assert main(["ask", "bob", "q", "--agent", str(d)]) == 0
    assert len(order) == 1 and "The answer." in order[0]


def test_serve_sends_once_inspection_is_turned_on_later(tmp_path, monkeypatch):
    import threading
    from localagent.connect.peer.tessera import TesseraConnection
    d, me, p = agent(tmp_path, {})
    (d / "tessera").mkdir(exist_ok=True)
    (d / "tessera" / "inspection.yaml").write_text("enabled: [unclosed\n", encoding="utf-8")  # half written
    called = threading.Event()
    monkeypatch.setattr(inspection_sender, "send_finished", lambda *a, **k: called.set() or 0)
    c = TesseraConnection.__new__(TesseraConnection)
    c.server = c.link = None
    c.agent_dir, c.protocol, c.identity = d, p, me
    c._stop_inspection, c._inspection_thread = threading.Event(), None
    c.start()  # inspection is off (unreadable state): serve still starts, and keeps checking
    try:
        assert called.wait(5)
    finally:
        c.stop()
