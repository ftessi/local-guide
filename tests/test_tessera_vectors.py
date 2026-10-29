import json
from pathlib import Path

from localagent.protocol.identity import verify
from localagent.protocol.tessera.canonical import canonical
from localagent.protocol.tessera.chain import verify_record
from localagent.protocol.tessera.envelope import envelope_hash
from localagent.protocol.tessera.vectors import build_vectors

FILE = Path(__file__).parent / "data" / "tessera_vectors_v0.2.json"


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
    from localagent.protocol.identity import x25519_from_seed
    from localagent.protocol.tessera import seal
    keys = v["x25519"]
    kx, e = (x25519_from_seed(bytes.fromhex(keys[n]["seed_hex"])) for n in ("kx_A", "e_B"))
    p = {item["name"]: item["package"].encode("utf-8") for item in v["packages"]}
    _, inner = seal.open_hello(kx, seal.parse(p["hello"]))
    assert inner.decode("utf-8") == next(i for i in v["envelopes"] if i["name"] == "hello")["canonical"]
    welcome, asker_keys, handle, _ = seal.open_welcome(e, keys["kx_A"]["public"], p["hello"], seal.parse(p["welcome"]))
    assert asker_keys.send.hex() == v["session_keys"]["asker_to_agent"] and handle == v["handle"]
    assert seal.open_msg(seal.Keys(send=asker_keys.recv, recv=asker_keys.send), seal.TO_AGENT,
                         seal.parse(p["ask"])).decode("utf-8") == next(i for i in v["envelopes"] if i["name"] == "ask")["canonical"]


FILE_V03 = Path(__file__).parent / "data" / "tessera_vectors_v0.3.json"


def test_v03_vectors_file_matches_builder():
    from localagent.protocol.tessera.vectors import build_vectors_v03
    assert json.loads(FILE_V03.read_text(encoding="utf-8")) == build_vectors_v03()


def test_v03_vectors_check():
    from localagent.protocol.tessera.envelope import check_signed
    from localagent.protocol.tessera.mandate import check_chain
    from localagent.protocol.tessera.vectors import TIME
    v = json.loads(FILE_V03.read_text(encoding="utf-8"))
    ids = {name: key["agent_id"] for name, key in v["keys"].items()}
    env = {item["name"]: item["envelope"] for item in v["envelopes"]}
    for item in v["envelopes"]:
        check_signed(item["envelope"])
        assert envelope_hash(item["envelope"]) == item["hash"]
        assert canonical({k: x for k, x in item["envelope"].items() if k != "sig"}).decode("utf-8") == item["signed_bytes"]
    assert check_chain(env["ask_with_mandate"]["body"]["mandates"], caller=ids["B"], me=ids["A"], now=TIME) == [ids["B"]]
    assert check_chain(env["delegated_ask"]["body"]["mandates"], caller=ids["A"], me=ids["C"],
                       now=TIME) == [ids["B"], ids["A"]]
    call = env["answer_with_calls"]["body"]["calls"][0]
    assert call["ask"] == env["delegated_ask"] and call["reply"] == env["delegated_answer"]
    assert call["reply"]["prev"] == envelope_hash(call["ask"])
