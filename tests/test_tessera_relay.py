"""Spec: Tessera relay §7. A Tessera-facing agent reachable only through a relay on localhost, asked by another agent
with the unchanged client; fake model, real guard, identities and records."""
import json

import pytest

from localagent.__main__ import main
from localagent.bootstrap import build_services
from localagent.config import load_config
from localagent.connect.base import SetupError
from localagent.protocol.identity import generate_identity, identity_from_seed
from localagent.protocol.tessera.chain import verify_record
from localagent.relay.core import Relay
from localagent.relay.http import RelayServer
from localagent.tessera_cli import make_asker, protocol_for
from localagent.testing import FakeBackend
from tests.fakes import write_agent_yaml

FACING = "name: tessera-demo\nmodel:\n  id: org/model\ncompartments: [demo]\n"
B_YAML = "name: b\nmodel:\n  id: org/model\ncompartments: [private]\n"


def facing_agent(tmp_path, installables):
    facing = write_agent_yaml(tmp_path / "facing", FACING, installables=installables)
    adapter = facing / "training/adapters/org--model/demo"
    adapter.mkdir(parents=True)
    (adapter / "adapter.json").write_text(json.dumps({"compartment": "demo", "base_model": "org/model"}))
    return facing, generate_identity(facing / "identity")


def tessera(tmp_path, installables, replies=()):
    facing, facing_id = facing_agent(tmp_path, installables)
    backend = FakeBackend(replies=list(replies))
    return facing, facing_id, backend, build_services(load_config(facing), backend=backend).connections["tessera"]


@pytest.fixture
def relay_server():
    server = RelayServer(Relay(), "127.0.0.1", 0, poll_wait=0.2)
    server.start()
    yield server
    server.stop()


def test_an_agent_reached_only_through_the_relay(tmp_path, relay_server, capsys):
    relay_url = f"http://127.0.0.1:{relay_server.port}"
    facing, facing_id, backend, conn = tessera(
        tmp_path, f"connections:\n  tessera:\n    builtin: true\n    relay: {relay_url}\n",
        ["The shared secret is GREEN-LANTERN-7.", "I can't share that.", "You asked about the shared secret."])
    assert conn.server is None  # no port opened
    b = write_agent_yaml(tmp_path / "b", B_YAML, installables=None)
    b_id = generate_identity(b / "identity")
    carried = []
    real_deliver = relay_server.relay.deliver

    def deliver(agent_id, kind, payload, timeout):
        reply = real_deliver(agent_id, kind, payload, timeout)
        if kind == "envelope":
            carried.extend([payload, reply])
        return reply

    relay_server.relay.deliver = deliver
    conn.start()
    try:
        assert conn.link.connected.wait(5)
        address = f"{relay_url}/a/{facing_id}"
        assert main(["connect", address, facing_id, "--name", "ana", "--purpose", "Review", "--agent", str(b)]) == 0
        assert main(["ask", "ana", "What is the shared secret?", "--agent", str(b)]) == 1
        assert "Not connected" in capsys.readouterr().out
        assert main(["peers", "accept", b_id, "--name", "Bob", "--agent", str(facing)]) == 0
        asker = make_asker(load_config(b))
        try:
            assert "GREEN-LANTERN-7" in asker("ana", "What is the shared secret?")
            assert asker("ana", "What is the private secret?") == "ana declined: I can't share that."
            assert "You asked about the shared secret." in asker("ana", "What did I ask first?")
            sid = asker.session("ana")
            assert carried and not any(s in b"".join(carried) for s in (b"shared secret", b"GREEN-LANTERN",
                                                                          b"private secret", b_id.encode()))
        finally:
            asker.close_all()
    finally:
        conn.stop()
    assert "What is the shared secret?" in json.dumps(backend.calls[-1])  # the follow-up saw the earlier turn
    b_record = protocol_for(load_config(b)).read_record(facing_id, sid)
    a_record = protocol_for(load_config(facing)).read_record(b_id, sid)
    assert a_record == b_record and len(a_record) == 9  # hello, welcome, 3 x (ask, reply), close
    verify_record(a_record)


def test_asking_through_a_relay_without_the_agent_or_without_the_relay(tmp_path, relay_server, capsys):
    other = identity_from_seed(bytes(range(64, 96))).agent_id
    b = write_agent_yaml(tmp_path / "b", B_YAML, installables=None)
    generate_identity(b / "identity")
    address = f"http://127.0.0.1:{relay_server.port}/a/{other}"
    assert main(["connect", address, other, "--name", "ana", "--purpose", "Review", "--agent", str(b)]) == 0
    assert main(["ask", "ana", "Hello?", "--agent", str(b)]) == 1
    assert "Not connected" in capsys.readouterr().out
    relay_server.stop()
    assert main(["ask", "ana", "Hello?", "--agent", str(b)]) == 1
    assert "Not connected" in capsys.readouterr().out


def test_without_a_relay_the_direct_server_runs_as_before(tmp_path):
    *_, conn = tessera(tmp_path, "connections:\n  tessera:\n    builtin: true\n    host: 127.0.0.1\n    port: 0\n")
    try:
        assert conn.server is not None and conn.link is None
    finally:
        conn.stop()


def test_relay_and_direct_together(tmp_path, relay_server):
    *_, conn = tessera(tmp_path, f"connections:\n  tessera:\n    builtin: true\n    port: 0\n"
                                 f"    relay: http://127.0.0.1:{relay_server.port}\n    listed: true\n"
                                 "    description: Demo answers\n")
    conn.start()
    try:
        assert conn.server is not None and conn.link.connected.wait(5)
        assert [(a["name"], a["description"]) for a in relay_server.relay.directory("http://x")] == \
               [("tessera-demo", "Demo answers")]
    finally:
        conn.stop()


@pytest.mark.parametrize("settings", ["    relay: ftp://relay.example.com\n", "    relay: 42\n",
                                      "    relay: https://r.example\n    listed: maybe\n"])
def test_bad_relay_settings_are_setup_errors(tmp_path, settings):
    with pytest.raises(SetupError, match="connections.tessera"):
        tessera(tmp_path, "connections:\n  tessera:\n    builtin: true\n" + settings)
