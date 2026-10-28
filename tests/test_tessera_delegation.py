import json
from types import SimpleNamespace

import pytest

from localagent.agent.core import Agent
from localagent.connect.peer.tessera.delegation import (ASK_RESERVE, MAX_CALLS, MIN_DELEGATE_BYTES, Delegator)
from localagent.connect.peer.tessera.endpoint import TesseraEndpoint, utc_now
from localagent.connect.peer.tessera.remotes import Remote, RemotesError, load
from localagent.connect.peer.tessera.sealed import SealedEndpoint
from localagent.protocol.guard import Protocol
from localagent.protocol.identity import identity_from_seed, x25519_from_seed, x25519_public
from localagent.protocol.tessera.canonical import canonical
from localagent.protocol.tessera.envelope import INNER_MAX, check_signed, envelope_hash
from localagent.protocol.tessera.mandate import sign_mandate
from localagent.testing import FakeBackend

P = identity_from_seed(bytes([1]) * 32)  # the person who asked the lead
Q = identity_from_seed(bytes([2]) * 32)  # another person
L = identity_from_seed(bytes([3]) * 32)  # the lead
C = identity_from_seed(bytes([4]) * 32)  # a callee


def callee(tmp_path, name, identity, replies, public=True):
    d = tmp_path / name
    path = d / "training/adapters/org--model/demo"
    path.mkdir(parents=True)
    (path / "adapter.json").write_text(json.dumps({"compartment": "demo", "base_model": "org/model"}))
    protocol = Protocol.for_agent(d, ["demo"], tools={}, owner_secret="t")
    kx = x25519_from_seed(bytes([9]) * 32)
    backend = FakeBackend(replies=replies)
    endpoint = TesseraEndpoint(identity, protocol, Agent(backend, {}, model_id="org/model"), name=name,
                               kx_public=x25519_public(kx), public=public, max_ask_chars=4000)
    return SimpleNamespace(protocol=protocol, backend=backend, endpoint=endpoint, sealed=SealedEndpoint(endpoint, kx))


def lead(tmp_path, callees, remotes_yaml):
    d = tmp_path / "lead"
    (d / "tessera").mkdir(parents=True)
    (d / "tessera/remotes.yaml").write_text(remotes_yaml, encoding="utf-8")
    protocol = Protocol.for_agent(d, ["demo"], tools={}, owner_secret="t")
    by_address = {f"http://{name}": c for name, c in callees.items()}
    return Delegator(L, protocol, d, post=lambda address, raw, **kw: by_address[address].sealed.handle(raw),
                     get_card=lambda address, **kw: by_address[address].endpoint.card())


def chain_from(person=P):
    return [sign_mandate(person, to=L.agent_id, before=None, now=utc_now())]


def remote_yaml(name, identity, purpose="Prices", extra=""):
    return f"{name}:\n  address: http://{name}\n  id: {identity.agent_id}\n  purpose: {purpose}\n{extra}"


def test_remotes_load_and_validate(tmp_path):
    (tmp_path / "tessera").mkdir()
    (tmp_path / "tessera/remotes.yaml").write_text(remote_yaml("pricing", C) + remote_yaml("mine", P, extra="  delegate: false\n"))
    remotes = load(tmp_path)
    assert remotes["pricing"] == Remote("pricing", C.agent_id, "http://pricing", "Prices", True)
    assert remotes["mine"].delegate is False
    (tmp_path / "tessera/remotes.yaml").write_text(remote_yaml("x", C, extra="  delegate: maybe\n"))
    with pytest.raises(RemotesError, match="delegate"):
        load(tmp_path)


def test_agents_lists_delegating_remotes_only(tmp_path):
    d = lead(tmp_path, {}, remote_yaml("pricing", C) + remote_yaml("mine", P, purpose="Mine", extra="  delegate: false\n"))
    delegation = d.start(chain_from(), P.agent_id, INNER_MAX)
    assert delegation.agents == [("pricing", "Prices")]


def test_call_extends_chain_and_reports(tmp_path):
    c = callee(tmp_path, "pricing", C, ["49 euros."])
    d = lead(tmp_path, {"pricing": c}, remote_yaml("pricing", C))
    delegation = d.start(chain_from(), P.agent_id, INNER_MAX)
    assert delegation.ask("pricing", "What do you charge?") == "49 euros."
    (item,) = delegation.report()
    assert item["agent"] == C.agent_id and item["name"] == "pricing" and item["error"] == ""
    check_signed(item["ask"])
    check_signed(item["reply"])
    assert item["reply"]["prev"] == envelope_hash(item["ask"]) and item["reply"]["body"]["text"] == "49 euros."
    sent = item["ask"]["body"]["mandates"]
    assert [(m["from"], m["to"]) for m in sent] == [(P.agent_id, L.agent_id), (L.agent_id, C.agent_id)]


def test_fourth_call_refused(tmp_path):
    c = callee(tmp_path, "pricing", C, ["1", "2", "3", "4"])
    d = lead(tmp_path, {"pricing": c}, remote_yaml("pricing", C))
    delegation = d.start(chain_from(), P.agent_id, INNER_MAX)
    for n in range(MAX_CALLS):
        assert delegation.ask("pricing", "Q?") == str(n + 1)
    assert "could not answer" in delegation.ask("pricing", "Q?")
    assert len(delegation.report()) == MAX_CALLS and len(c.backend.calls) == MAX_CALLS


def test_failed_call_reported(tmp_path):
    c = callee(tmp_path, "pricing", C, ["never"], public=False)
    d = lead(tmp_path, {"pricing": c}, remote_yaml("pricing", C))
    c.protocol.accept_peer(L.agent_id, name="Lead")  # the lead is accepted, the person isn't
    delegation = d.start(chain_from(), P.agent_id, INNER_MAX)
    text = delegation.ask("pricing", "Q?")
    assert text == "(pricing could not answer: not_allowed)"
    (item,) = delegation.report()
    assert item["error"] == "not_allowed" and item["ask"] is None and item["reply"] is None
    assert "unknown" in delegation.ask("nobody", "Q?")


def test_clients_not_shared_between_origins(tmp_path):
    c = callee(tmp_path, "pricing", C, ["For P.", "For Q."])
    d = lead(tmp_path, {"pricing": c}, remote_yaml("pricing", C))
    first = d.start(chain_from(P), P.agent_id, INNER_MAX)
    first.ask("pricing", "Q?")
    second = d.start(chain_from(Q), Q.agent_id, INNER_MAX)
    assert second.ask("pricing", "Q?") == "For Q."
    sessions = {item["ask"]["session"] for item in first.report() + second.report()}
    assert len(sessions) == 2


def test_small_budget_means_no_delegation(tmp_path):
    d = lead(tmp_path, {}, remote_yaml("pricing", C))
    assert d.start(chain_from(), P.agent_id, MIN_DELEGATE_BYTES - 1) is None
    assert lead(tmp_path / "x", {}, "").start(chain_from(), P.agent_id, INNER_MAX) is None  # no remotes


def test_full_chain_means_no_delegation(tmp_path):
    d = lead(tmp_path, {}, remote_yaml("pricing", C))
    ids = [identity_from_seed(bytes([n]) * 32) for n in (20, 21, 22)]
    chain, before = [], None
    for frm, to in zip(ids + [None], ids[1:] + [L]):
        if frm is None:
            break
        before = sign_mandate(frm, to=to.agent_id, before=before, now=utc_now())
        chain.append(before)
    assert len(chain) == 3
    assert d.start(chain, ids[0].agent_id, INNER_MAX) is not None
    chain.append(sign_mandate(L, to=C.agent_id, before=chain[-1], now=utc_now()))
    assert d.start(chain, ids[0].agent_id, INNER_MAX) is None


def test_loop_reported_without_calling(tmp_path):
    c = callee(tmp_path, "back", P, ["never"])  # the remote is the person who asked
    d = lead(tmp_path, {"back": c}, remote_yaml("back", P))
    delegation = d.start(chain_from(), P.agent_id, INNER_MAX)
    assert "already in the chain" in delegation.ask("back", "Q?")
    assert c.backend.calls == []


def test_report_fits_budget(tmp_path):
    c = callee(tmp_path, "pricing", C, ["x" * 20000] * 3)
    d = lead(tmp_path, {"pricing": c}, remote_yaml("pricing", C))
    delegation = d.start(chain_from(), P.agent_id, INNER_MAX)
    for _ in range(MAX_CALLS):
        delegation.ask("pricing", "y" * 3000)
    report = delegation.report()
    assert all(item["error"] == "" for item in report)
    assert len(canonical(report)) + ASK_RESERVE <= INNER_MAX
