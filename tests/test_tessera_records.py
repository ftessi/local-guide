import json

import pytest

from localagent.__main__ import main
from localagent.protocol.guard import Protocol
from localagent.protocol.identity import generate_identity, identity_from_seed
from localagent.protocol.tessera.envelope import envelope_hash, sign_envelope
from localagent.protocol.identity import x25519_from_seed, x25519_public
from tests.fakes import write_agent_yaml

A = identity_from_seed(bytes(range(32)))
B = identity_from_seed(bytes(range(32, 64)))
KEY = x25519_public(x25519_from_seed(bytes(range(128, 160))))
YAML = "name: a\nmodel:\n  id: org/model\ncompartments: [demo]\n"


def session_record():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    hello = sign_envelope(B, type="hello", session="", to=A.agent_id, seq=0, prev="",
                          body={"purpose": "p", "requested_level": 1, "nonce": "n", "e": KEY}, now=now)
    welcome = sign_envelope(A, type="welcome", session="", to=B.agent_id, seq=1, prev=envelope_hash(hello),
                            body={"session": "s-1", "granted_level": 1, "expires": "2030-01-01T00:00:00Z",
                                  "limits": {"asks": 5, "ask_chars": 100}, "f": KEY}, now=now)
    ask = sign_envelope(B, type="ask", session="s-1", to=A.agent_id, seq=2, prev=envelope_hash(welcome),
                        body={"text": "What is the shared secret?"}, now=now)
    return [hello, welcome, ask]


def agent(tmp_path):
    d = write_agent_yaml(tmp_path / "a", YAML, installables=None)
    generate_identity(d / "identity")
    return d


def test_records_are_encrypted_on_disk_and_read_back(tmp_path):
    d = agent(tmp_path)
    p = Protocol.for_agent(d, ["demo"], tools={}, owner_secret="")
    for env in session_record():
        p.record_envelope(B.agent_id, "s-1", env)
    p.record_request(B.agent_id, "a secret purpose", 1)
    files = list((d / "tessera").rglob("*.jsonl"))
    assert files and not any(b"shared secret" in f.read_bytes() or b"secret purpose" in f.read_bytes() for f in files)
    assert [e["type"] for e in p.read_record(B.agent_id, "s-1")] == ["hello", "welcome", "ask"]
    assert p.requests()[0]["purpose"] == "a secret purpose"
    assert p.record_names() == [f"{B.agent_id}/s-1"]


def test_a_line_from_another_agent_is_refused_with_a_clear_error(tmp_path):
    d, other = agent(tmp_path), write_agent_yaml(tmp_path / "o", YAML, installables=None)
    generate_identity(other / "identity")
    p = Protocol.for_agent(d, ["demo"], tools={}, owner_secret="")
    p.record_envelope(B.agent_id, "s-1", session_record()[0])
    q = Protocol.for_agent(other, ["demo"], tools={}, owner_secret="")
    (other / "tessera" / B.agent_id).mkdir(parents=True)
    (other / "tessera" / B.agent_id / "s-1.jsonl").write_bytes((d / "tessera" / B.agent_id / "s-1.jsonl").read_bytes())
    with pytest.raises(ValueError, match="s-1.jsonl"):
        q.read_record(B.agent_id, "s-1")


def test_old_plaintext_records_are_encrypted_in_place(tmp_path):
    d = agent(tmp_path)
    folder = d / "tessera" / B.agent_id
    folder.mkdir(parents=True)
    (folder / "s-1.jsonl").write_text("".join(json.dumps(e) + "\n" for e in session_record()), encoding="utf-8")
    (d / "tessera" / "requests.jsonl").write_text(json.dumps({"id": B.agent_id, "purpose": "x", "level": 1,
                                                              "status": "pending", "time": "t"}) + "\n")
    p = Protocol.for_agent(d, ["demo"], tools={}, owner_secret="")
    assert b"shared secret" not in (folder / "s-1.jsonl").read_bytes()
    assert p.read_record(B.agent_id, "s-1") == session_record()
    assert p.requests()[0]["purpose"] == "x"


def test_records_command(tmp_path, capsys):
    d = agent(tmp_path)
    p = Protocol.for_agent(d, ["demo"], tools={}, owner_secret="")
    record = session_record()
    for env in record:
        p.record_envelope(B.agent_id, "s-1", env)
    assert main(["records", "--agent", str(d)]) == 0
    assert "s-1" in capsys.readouterr().out
    assert main(["records", "show", "s-1", "--agent", str(d)]) == 0
    assert "What is the shared secret?" in capsys.readouterr().out
    assert main(["records", "verify", "s-1", "--agent", str(d)]) == 0
    assert "verified" in capsys.readouterr().out
    out = tmp_path / "export.jsonl"
    assert main(["records", "export", "s-1", "--to", str(out), "--agent", str(d)]) == 0
    assert [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()] == record
    assert main(["records", "show", "nope", "--agent", str(d)]) == 2
