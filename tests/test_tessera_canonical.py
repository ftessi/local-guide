import pytest

from localagent.protocol.identity import (AGENT_ID_RE, generate_identity, identity_from_seed, load_agent_id,
                                          load_identity, verify)
from localagent.protocol.tessera.canonical import CanonicalError, canonical


def test_sorted_keys_no_spaces():
    assert canonical({"b": 1, "a": [True, None, -5], "c": "x"}) == b'{"a":[true,null,-5],"b":1,"c":"x"}'


def test_strings_escape_only_what_jcs_escapes():
    assert canonical("é\n\u0001\"\\/") == '"é\\n\\u0001\\"\\\\/"'.encode("utf-8")


def test_keys_sort_by_utf16_code_units():
    # U+FB01 < U+1F600 as code points, but in UTF-16 the emoji's first unit (0xD83D) sorts before 0xFB01
    assert canonical({"ﬁ": 1, "\U0001F600": 2}).startswith('{"\U0001F600"'.encode("utf-8"))


@pytest.mark.parametrize("value", [1.5, float("nan"), b"x", {1: "a"}, "\ud800", 2 ** 53, (1, 2)])
def test_refuses_what_tessera_never_sends(value):
    with pytest.raises(CanonicalError):
        canonical(value)


def test_identity_signs_and_verifies(tmp_path):
    agent_id = generate_identity(tmp_path / "identity")
    me = load_identity(tmp_path / "identity")
    assert me.agent_id == agent_id == load_agent_id(tmp_path / "identity") and AGENT_ID_RE.match(agent_id)
    sig = me.sign(b"hello")
    assert len(sig) == 86 and verify(agent_id, b"hello", sig)
    assert not verify(agent_id, b"hellO", sig)
    other = identity_from_seed(bytes(32))
    assert not verify(other.agent_id, b"hello", sig)
    assert not verify("not-an-id", b"hello", sig) and not verify(agent_id, b"hello", "%%%")


def test_seeded_identity_is_deterministic():
    a, b = identity_from_seed(bytes(range(32))), identity_from_seed(bytes(range(32)))
    assert a.agent_id == b.agent_id and a.sign(b"x") == b.sign(b"x")  # Ed25519 signatures are deterministic


def test_missing_identity(tmp_path):
    with pytest.raises(FileNotFoundError, match="new_agent.py"):
        load_identity(tmp_path / "identity")
