"""The browser's Tessera code, run with Node: the published vectors, the client, the inspection upload."""
import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from localagent.bootstrap import build_services
from localagent.config import load_config
from localagent.protocol.identity import generate_identity, identity_from_seed, x25519_from_seed, x25519_public
from localagent.protocol.tessera import inspection
from localagent.relay.core import Relay
from localagent.relay.http import RelayServer
from localagent.testing import FakeBackend
from tests.fakes import write_agent_yaml

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="Node is not installed")
COMPANY = x25519_from_seed(bytes(range(200, 232)))
FACING = "name: tessera-demo\nmodel:\n  id: org/model\ncompartments: [demo]\n"


@needs_node
def test_js_suite():
    result = subprocess.run([NODE, "--test", "tests/js/*.test.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


def test_js_company_key_matches():
    source = (ROOT / "localagent/relay/web/js/inspection.js").read_text(encoding="utf-8")
    assert re.search(r'COMPANY_KEY = "([A-Za-z0-9_-]{43})"', source).group(1) == inspection.COMPANY_KEY


@needs_node
def test_js_upload_matches_python():
    vectors = json.loads((ROOT / "tests/data/tessera_vectors_v0.2.json").read_text(encoding="utf-8"))
    envelopes = [i["envelope"] for i in vectors["envelopes"] if i["name"] in ("hello", "welcome", "ask", "answer")]
    company = x25519_public(COMPANY)
    expected = inspection.seal_upload(identity_from_seed(bytes(range(32, 64))), company,
                                      peer=vectors["keys"]["A"]["agent_id"], session="s-0123456789abcdef",
                                      envelopes=envelopes, now=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc),
                                      e=x25519_from_seed(bytes(range(128, 160))))
    result = subprocess.run([NODE, "tests/js/seal_upload.mjs", company], cwd=ROOT, capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == 0, result.stderr
    assert bytes.fromhex(result.stdout.strip()) == expected


@needs_node
def test_browser_chat_end_to_end(tmp_path):
    server = RelayServer(Relay(), "127.0.0.1", 0, poll_wait=0.2, inbox=tmp_path / "inbox")
    server.start()
    relay = f"http://127.0.0.1:{server.port}"
    facing = write_agent_yaml(tmp_path / "facing", FACING, installables=(
        f"connections:\n  tessera:\n    builtin: true\n    relay: {relay}\n    listed: true\n    public: true\n"))
    adapter = facing / "training/adapters/org--model/demo"
    adapter.mkdir(parents=True)
    (adapter / "adapter.json").write_text(json.dumps({"compartment": "demo", "base_model": "org/model"}))
    facing_id = generate_identity(facing / "identity")
    conn = build_services(load_config(facing), backend=FakeBackend(replies=["pong"])).connections["tessera"]
    conn.start()
    try:
        assert conn.link.connected.wait(5)
        result = subprocess.run([NODE, "tests/js/chat_e2e.mjs", relay, facing_id, "ping",
                                 "--company-key", x25519_public(COMPANY)],
                                cwd=ROOT, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        lines = result.stdout.splitlines()
        assert lines[:2] == ["answer pong", "uploaded true"]
        me = lines[2].split()[1]
        files = list((tmp_path / "inbox").iterdir())
        assert len(files) == 1
        payload = inspection.open_upload(COMPANY, files[0].read_bytes())
        assert payload["agent_id"] == me and payload["peer"] == facing_id
        assert [e["type"] for e in payload["envelopes"]] == ["hello", "welcome", "ask", "answer", "close"]
        deadline = time.monotonic() + 5  # the agent records the close after answering it
        while conn.protocol.public_sessions() != {f"{me}/{payload['session']}"} and time.monotonic() < deadline:
            time.sleep(0.05)
        assert conn.protocol.public_sessions() == {f"{me}/{payload['session']}"}
    finally:
        conn.stop()
        server.stop()
