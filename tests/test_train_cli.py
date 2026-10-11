import json
from argparse import Namespace

from localagent.__main__ import main
from localagent.config import load_config
from localagent.train_cli import run
from tests.fakes import write_agent_yaml

DEMO_AGENT = """\
name: a
model:
  id: org/model
compartments: [private, demo]
"""


def agent(tmp_path, name="a", text=DEMO_AGENT):
    d = write_agent_yaml(tmp_path / name, text, installables=None)
    src = d / "training/demo/sources"
    src.mkdir(parents=True)
    (src / "secret.yaml").write_text(
        "- about: the shared secret\n  answer: The shared secret is GREEN-LANTERN-7.\n", encoding="utf-8")
    return d


def args(**kw):
    base = {"compartment": None, "adapter": None, "device": "auto", "epochs": None, "to": None}
    return Namespace(**{**base, **kw})


def test_examples_command_writes_and_replaces(tmp_path):
    d = agent(tmp_path)
    assert main(["examples", "--compartment", "demo", "--agent", str(d)]) == 0
    assert main(["examples", "--compartment", "demo", "--agent", str(d)]) == 0
    lines = (d / "training/demo/examples.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 42  # 30 answers + 12 declines, written once, not twice
    assert json.loads(lines[0])["messages"][-1]["content"] == "The shared secret is GREEN-LANTERN-7."


def test_examples_errors_are_clear(tmp_path, capsys):
    d = agent(tmp_path)
    cfg = load_config(d)
    assert run("examples", cfg, args()) == 2
    assert "--compartment" in capsys.readouterr().err
    assert run("examples", cfg, args(compartment="shared")) == 2
    assert "private, demo" in capsys.readouterr().err
    (d / "training/demo/sources/bad.yaml").write_text("- about: x\n", encoding="utf-8")
    assert run("examples", cfg, args(compartment="demo")) == 2
    assert "bad.yaml" in capsys.readouterr().err
    assert not (d / "training/demo/examples.jsonl").exists()
