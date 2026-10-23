"""The browser's Tessera code, run with Node: the published vectors, the client, the inspection upload."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="Node is not installed")


@needs_node
def test_js_suite():
    result = subprocess.run([NODE, "--test", "tests/js/*.test.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
