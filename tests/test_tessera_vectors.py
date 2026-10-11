import json
from pathlib import Path

from localagent.protocol.identity import verify
from localagent.protocol.tessera.canonical import canonical
from localagent.protocol.tessera.chain import verify_record
from localagent.protocol.tessera.envelope import envelope_hash
from localagent.protocol.tessera.vectors import build_vectors

FILE = Path(__file__).parent / "data" / "tessera_vectors_v0.1.json"


def test_published_vectors_match_this_implementation():
    """If this fails after a code change, the bytes on the wire changed: that's a protocol change, not a refactor."""
    assert json.loads(FILE.read_text(encoding="utf-8")) == build_vectors()


def test_vectors_are_self_consistent():
    v = build_vectors()
    for case in v["canonical"]:
        assert canonical(case["value"]).decode("utf-8") == case["canonical"]
    for item in v["envelopes"]:
        env = item["envelope"]
        assert canonical({k: x for k, x in env.items() if k != "sig"}).decode("utf-8") == item["signed_bytes"]
        assert verify(env["from"], item["signed_bytes"].encode("utf-8"), env["sig"])
        assert envelope_hash(env) == item["hash"]
    session = [i["envelope"] for i in v["envelopes"] if i["name"] in ("hello", "welcome", "ask", "answer")]
    verify_record(session)
