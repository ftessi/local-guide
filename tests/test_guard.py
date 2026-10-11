import json

import pytest

from localagent.protocol.guard import AuthError, Protocol
from localagent.protocol.identity import generate_identity, load_agent_id
from localagent.protocol.scopes import Scope
from localagent.protocol.session import Session
from localagent.vault.store import Vault


@pytest.fixture
def agent_dir(tmp_path):
    (tmp_path / "knowledge/private").mkdir(parents=True)
    (tmp_path / "knowledge/private/me.md").write_text("MY-BANK-PIN-1234")
    (tmp_path / "knowledge/shared").mkdir(parents=True)
    (tmp_path / "knowledge/shared/s.md").write_text("I like jazz.")
    return tmp_path


def proto(agent_dir, secret="s3cret"):
    return Protocol.for_agent(agent_dir, ["private", "shared"], tools={}, owner_secret=secret)


def test_owner_session(agent_dir):
    s = proto(agent_dir).open_owner_session("s3cret")
    assert s.principal == "owner" and s.scope.is_all
    events = [json.loads(line)["event"] for line in (agent_dir / "audit.log").read_text().splitlines()]
    assert events == ["session_opened"]


def test_wrong_token(agent_dir):
    with pytest.raises(AuthError):
        proto(agent_dir).open_owner_session("nope")
    assert "auth_failed" in (agent_dir / "audit.log").read_text()


def test_empty_secret_refuses_everyone(agent_dir):
    for token in ("", "anything"):
        with pytest.raises(AuthError, match="AGENT_SECRET"):
            proto(agent_dir, secret="").open_owner_session(token)


def test_private_never_in_non_private_session(agent_dir):
    Vault(agent_dir, ["private", "shared"]).append_memory("private", {"user": "MY-BANK-PIN-1234", "assistant": "ok"})
    s = Session(principal="peer:x", scope=Scope(["knowledge:shared", "memory:shared", "work:shared"]),
                memory_compartment="peer:x", vault=Vault(agent_dir, ["private", "shared"]),
                audit=proto(agent_dir).audit, tools={}, adapters_dir=agent_dir / "training/adapters")
    blob = json.dumps([i.content for i in s.context()]) + json.dumps(s.history(100))
    assert "I like jazz." in blob
    assert "MY-BANK-PIN-1234" not in blob


def test_training_set_exact_compartment(agent_dir):
    v = Vault(agent_dir, ["private", "shared"])
    v.write_training_examples("private", [{"messages": [{"role": "user", "content": "PRIV"}]}])
    v.write_training_examples("shared", [{"messages": [{"role": "user", "content": "SHARED"}]}])
    v.append_memory("peer:x", {"user": "PEER", "assistant": "y"})
    p = proto(agent_dir)
    blob = json.dumps(p.training_set("shared"))
    assert "SHARED" in blob and "PRIV" not in blob and "PEER" not in blob
    with pytest.raises(ValueError):
        p.training_set("peer:x")


def test_peer_sessions_not_yet_supported(agent_dir):
    with pytest.raises(NotImplementedError):
        proto(agent_dir).open_peer_session({})


def test_identity(tmp_path):
    agent_id = generate_identity(tmp_path / "identity")
    assert load_agent_id(tmp_path / "identity") == agent_id
    assert len(agent_id) == 43  # 32 bytes, base64url without padding
    with pytest.raises(FileExistsError):
        generate_identity(tmp_path / "identity")
    assert load_agent_id(tmp_path / "missing") is None
