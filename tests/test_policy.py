import pytest

from localagent.protocol.policy import PolicyError, load_policy
from localagent.protocol.scopes import InvalidScope, Scope


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
    assert p.owner.is_all
    assert p.for_peer("anyone").allows("knowledge", "shared")
    assert not p.for_peer("anyone").allows("knowledge", "private")


def test_peer_override(tmp_path):
    (tmp_path / "policy.yaml").write_text("peers:\n  abc: [tool:calendar:list]\n")
    p = load_policy(tmp_path / "policy.yaml")
    assert p.for_peer("abc").allows_tool("calendar", "list")
    assert not p.for_peer("abc").allows("knowledge", "shared")


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
