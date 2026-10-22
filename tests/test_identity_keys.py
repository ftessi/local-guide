import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from localagent.protocol.identity import (generate_identity, load_kx, load_record_key, x25519_from_b64,
                                          x25519_from_seed, x25519_public)


def test_generate_identity_creates_all_three_keys(tmp_path):
    generate_identity(tmp_path / "identity")
    assert {p.name for p in (tmp_path / "identity").iterdir()} == {"agent.key", "agent.pub", "kx.key", "record.key"}


def test_keys_are_created_once_and_then_stable(tmp_path):
    kx, record = load_kx(tmp_path), load_record_key(tmp_path)
    assert isinstance(kx, X25519PrivateKey) and len(record) == 32
    assert x25519_public(load_kx(tmp_path)) == x25519_public(kx)
    assert load_record_key(tmp_path) == record


def test_public_keys_round_trip_and_bad_ones_are_refused():
    key = x25519_from_seed(bytes(range(32)))
    pub = x25519_public(key)
    assert len(pub) == 43 and x25519_public(x25519_from_seed(bytes(range(32)))) == pub
    assert x25519_from_b64(pub) is not None
    for bad in ("", "x" * 43, pub[:-1], pub + "A"):
        with pytest.raises(ValueError):
            x25519_from_b64(bad)


def test_a_wrong_key_file_is_refused(tmp_path):
    (tmp_path / "record.key").write_text("c2hvcnQ\n")
    with pytest.raises(ValueError):
        load_record_key(tmp_path)
