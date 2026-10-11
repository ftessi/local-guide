import pytest

from localagent.protocol.policy import Policy, PeerEntry, PolicyError, load_policy, save_policy
from localagent.protocol.scopes import InvalidScope, Scope

BOB = "B" * 43


def test_scope_checks():
    s = Scope(["knowledge:shared", "tool:calendar:list", "memory:peer:abc"])
    assert s.allows("knowledge", "shared") and not s.allows("knowledge", "private")
    assert s.allows_tool("calendar", "list") and not s.allows_tool("calendar", "create")
    assert Scope(["tool:calendar"]).allows_tool("calendar", "delete")
    assert Scope(["all"]).allows("adapter", "private")


@pytest.mark.parametrize("bad", ["knowledge", "tool:", "files:x", "knowledge:Bad", "tool:a:b:c"])
def test_invalid_scopes(bad):
    with pytest.raises(InvalidScope):
        Scope([bad])


def test_scope_string_instead_of_list():
    with pytest.raises(InvalidScope, match="list"):
        Scope("all")


def test_defaults_when_missing(tmp_path):
    p = load_policy(tmp_path / "policy.yaml")
    assert p.owner.is_all and p.peers == {} and p.peer(BOB) is None


def test_peer_entries(tmp_path):
    (tmp_path / "policy.yaml").write_text(f"peers:\n  {BOB}: {{name: Bob, level: 1}}\n")
    assert load_policy(tmp_path / "policy.yaml").peer(BOB) == PeerEntry("Bob", 1)


def test_save_and_load_round_trip(tmp_path):
    policy = Policy(owner=Scope(["all"]), peers={BOB: PeerEntry("Bob's agent", 1)})
    save_policy(tmp_path / "policy.yaml", policy)
    text = (tmp_path / "policy.yaml").read_text(encoding="utf-8")
    loaded = load_policy(tmp_path / "policy.yaml")
    assert text.startswith("# Who may see what")
    assert loaded.peers == policy.peers and loaded.owner.items == policy.owner.items


@pytest.mark.parametrize("text, fragment", [
    ("default_peer: [knowledge:shared]\n", "peers accept"),
    (f"peers:\n  {BOB}: [knowledge:shared]\n", "name: \"Bob's agent\", level: 1"),
    (f"peers:\n  {BOB}: {{name: Bob, connection: demo, level: 1}}\n", "level: 1"),
    (f"peers:\n  {BOB}: {{name: Bob, level: 3}}\n", "only 1"),
    (f"peers:\n  {BOB}: {{name: Bob, level: true}}\n", "only 1"),
    (f"peers:\n  {BOB}: {{name: Bob, level: 1.0}}\n", "only 1"),
    ("peers:\n  shortid: {name: Bob, level: 1}\n", "not an agent id"),
    (f'peers:\n  "{BOB}\\n": {{name: Bob, level: 1}}\n', "not an agent id"),
    (f"peers:\n  {BOB}: {{name: '', level: 1}}\n", "name"),
])
def test_peer_format_errors(tmp_path, text, fragment):
    (tmp_path / "policy.yaml").write_text(text)
    with pytest.raises(PolicyError, match=fragment):
        load_policy(tmp_path / "policy.yaml")


@pytest.mark.parametrize("text, fragment", [
    ("owner: [everything]\n", "everything"),
    ("peerz: {}\n", "peerz"),
    ("peers: [a, b]\n", "peers"),
    ("owner: [all\n", "YAML"),
])
def test_policy_errors(tmp_path, text, fragment):
    (tmp_path / "policy.yaml").write_text(text)
    with pytest.raises(PolicyError, match=fragment):
        load_policy(tmp_path / "policy.yaml")
