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


def test_train_command_uses_only_that_compartments_examples(tmp_path, monkeypatch):
    import localagent.training.lora as lora
    d = agent(tmp_path)
    assert main(["examples", "--compartment", "demo", "--agent", str(d)]) == 0
    seen = {}

    def fake_train(model_id, examples, out_dir, *, compartment, device, log, **settings):
        seen.update(model_id=model_id, n=len(examples), out_dir=out_dir, compartment=compartment, device=device,
                    settings=settings)
        return {"final_loss": 0.1}

    monkeypatch.setattr(lora, "train_adapter", fake_train)
    assert main(["train", "--adapter", "demo", "--device", "cpu", "--epochs", "3", "--agent", str(d)]) == 0
    assert seen == {"model_id": "org/model", "n": 42, "out_dir": d / "training/adapters/org--model/demo",
                    "compartment": "demo", "device": "cpu", "settings": {"epochs": 3}}


def test_train_without_examples_says_what_to_run(tmp_path, capsys):
    d = agent(tmp_path)
    assert main(["train", "--adapter", "demo", "--agent", str(d)]) == 2
    assert "python -m localagent examples --compartment demo" in capsys.readouterr().err


TESSERA_AGENT = """\
name: tessera-demo
model:
  id: org/model
compartments: [private, demo]
"""


def trained(d, compartment="demo", base_model="org/model"):
    path = d / f"training/adapters/org--model/{compartment}"
    path.mkdir(parents=True, exist_ok=True)
    (path / "adapter.json").write_text(json.dumps({"compartment": compartment, "base_model": base_model}))
    (path / "adapter_model.safetensors").write_bytes(b"weights")
    return path


def test_export_copies_a_connection_adapter(tmp_path):
    a = agent(tmp_path)
    trained(a)
    t = write_agent_yaml(tmp_path / "tessera-demo", TESSERA_AGENT, installables=None)
    assert main(["export", "--adapter", "demo", "--to", str(t), "--agent", str(a)]) == 0
    copied = t / "training/adapters/org--model/demo"
    assert (copied / "adapter_model.safetensors").read_bytes() == b"weights"
    trained(a).joinpath("adapter_model.safetensors").write_bytes(b"retrained")
    assert main(["export", "--adapter", "demo", "--to", str(t), "--agent", str(a)]) == 0
    assert (copied / "adapter_model.safetensors").read_bytes() == b"retrained"  # replaced, not merged


def test_export_refusals(tmp_path, capsys):
    a = agent(tmp_path)
    trained(a, "private")
    t = write_agent_yaml(tmp_path / "t", TESSERA_AGENT.replace("[private, demo]", "[private]"), installables=None)
    assert main(["export", "--adapter", "private", "--to", str(t), "--agent", str(a)]) == 2
    assert "never leaves" in capsys.readouterr().err
    assert main(["export", "--adapter", "demo", "--to", str(t), "--agent", str(a)]) == 2
    assert "No trained adapter" in capsys.readouterr().err
    trained(a)
    assert main(["export", "--adapter", "demo", "--to", str(t), "--agent", str(a)]) == 2
    assert "not a compartment of the destination" in capsys.readouterr().err
    other = write_agent_yaml(tmp_path / "o", TESSERA_AGENT.replace("org/model", "other/model"), installables=None)
    assert main(["export", "--adapter", "demo", "--to", str(other), "--agent", str(a)]) == 2
    assert "other/model" in capsys.readouterr().err
    assert main(["export", "--adapter", "demo", "--agent", str(a)]) == 2
    assert "--to" in capsys.readouterr().err
    assert not (t / "training/adapters").exists()


def test_export_refuses_an_adapter_json_naming_another_compartment(tmp_path, capsys):
    a = agent(tmp_path)
    path = trained(a)
    (path / "adapter.json").write_text(json.dumps({"compartment": "private", "base_model": "org/model"}))
    t = write_agent_yaml(tmp_path / "tessera-demo", TESSERA_AGENT, installables=None)
    assert main(["export", "--adapter", "demo", "--to", str(t), "--agent", str(a)]) == 2
    assert "holds the adapter of 'private'" in capsys.readouterr().err
    assert not (t / "training/adapters").exists()


def test_export_refuses_the_source_agent_as_destination(tmp_path, capsys):
    a = agent(tmp_path)
    path = trained(a)
    assert main(["export", "--adapter", "demo", "--to", str(a), "--agent", str(a)]) == 2
    assert "same" in capsys.readouterr().err
    assert (path / "adapter_model.safetensors").read_bytes() == b"weights"
