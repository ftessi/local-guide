"""Spec §7.2: A internal → export → A's tessera-demo ← B, over real HTTP on localhost, with a fake model."""
import json

from localagent.__main__ import main
from localagent.bootstrap import build_services
from localagent.config import load_config
from localagent.protocol.identity import generate_identity
from localagent.protocol.tessera.chain import verify_record
from localagent.testing import FakeBackend
from tests.fakes import write_agent_yaml

INTERNAL = "name: a\nmodel:\n  id: org/model\ncompartments: [private, demo]\n"
FACING = "name: tessera-demo\nmodel:\n  id: org/model\ncompartments: [demo]\n"
B_YAML = "name: b\nmodel:\n  id: org/model\ncompartments: [private]\n"
SERVE = "connections:\n  tessera:\n    builtin: true\n    host: 127.0.0.1\n    port: 0\n"


def test_three_folders(tmp_path, capsys):
    a = write_agent_yaml(tmp_path / "a", INTERNAL, installables=None)
    adapter = a / "training/adapters/org--model/demo"
    adapter.mkdir(parents=True)
    (adapter / "adapter.json").write_text(json.dumps({"compartment": "demo", "base_model": "org/model"}))
    private = a / "training/adapters/org--model/private"
    private.mkdir(parents=True)
    (private / "adapter.json").write_text(json.dumps({"compartment": "private", "base_model": "org/model"}))
    (private / "adapter_model.safetensors").write_bytes(b"\x00weights BLUE-HARBOR-42 weights\x00")
    (a / "training/private/sources").mkdir(parents=True)
    (a / "training/private/sources/secret.yaml").write_text("note: BLUE-HARBOR-42\n")
    (a / "knowledge/private").mkdir(parents=True)
    (a / "knowledge/private/me.md").write_text("BLUE-HARBOR-42")
    facing = write_agent_yaml(tmp_path / "facing", FACING, installables=SERVE)
    facing_id = generate_identity(facing / "identity")
    b = write_agent_yaml(tmp_path / "b", B_YAML, installables=None)
    b_id = generate_identity(b / "identity")

    assert main(["export", "--adapter", "demo", "--to", str(facing), "--agent", str(a)]) == 0
    backend = FakeBackend(replies=["The shared secret is GREEN-LANTERN-7."])
    services = build_services(load_config(facing), backend=backend)
    conn = services.connections["tessera"]
    conn.start()
    try:
        address = f"http://127.0.0.1:{conn.server.port}"
        assert main(["connect", address, facing_id, "--name", "ana", "--purpose", "Review", "--agent", str(b)]) == 0
        assert main(["ask", "ana", "What is the shared secret?", "--agent", str(b)]) == 1
        assert "Not connected" in capsys.readouterr().out
        # before acceptance only the request exists, no session record
        assert not list((facing / "tessera" / b_id).glob("*.jsonl"))
        assert main(["peers", "accept", b_id, "--name", "Bob", "--agent", str(facing)]) == 0
        capsys.readouterr()
        assert main(["ask", "ana", "What is the shared secret?", "--agent", str(b)]) == 0
        out = capsys.readouterr().out
        assert "ana says:\n  The shared secret is GREEN-LANTERN-7." in out
    finally:
        conn.stop()

    assert backend.adapters == [facing / "training/adapters/org--model/demo"]
    assert "BLUE-HARBOR-42" not in json.dumps(backend.calls)
    assert not (facing / "training/adapters/org--model/private").exists()
    leaks = [f for f in facing.rglob("*") if f.is_file() and b"BLUE-HARBOR-42" in f.read_bytes()]
    assert leaks == []
    b_files = list((b / "tessera" / facing_id).glob("*.jsonl"))
    assert len(b_files) == 1
    sid = b_files[-1].stem
    b_record = [json.loads(line) for line in b_files[-1].read_text(encoding="utf-8").splitlines()]
    a_record = [json.loads(line) for line in
                (facing / "tessera" / b_id / f"{sid}.jsonl").read_text(encoding="utf-8").splitlines()]
    # hello, welcome, ask, answer, close (one-shot ask closes its session)
    assert a_record == b_record and len(a_record) == 5
    verify_record(a_record)
