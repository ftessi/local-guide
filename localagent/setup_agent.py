"""Create agent folders from agent_template/."""
import re
import secrets
import shutil
from pathlib import Path

from localagent.config import REPO_ROOT
from localagent.protocol.identity import generate_identity

TEMPLATE_DIR = REPO_ROOT / "agent_template"


def _write_env(path: Path, values: dict) -> None:
    lines = ["# Secrets for this agent. Never commit or share this file."]
    lines += [f"{k}={v}" for k, v in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_model(agent_yaml: Path, model: dict) -> None:
    """Rewrite values inside the model: block, keeping comments."""
    text = agent_yaml.read_text(encoding="utf-8")
    for key, value in model.items():
        text = re.sub(rf"(?m)^(  {key}:\s*)\S+", lambda m: f"{m.group(1)}{value}", text, count=1)
    agent_yaml.write_text(text, encoding="utf-8")


def create_agent(agent_dir: Path, *, model: dict | None = None, env_values: dict | None = None) -> str:
    """Copy the template, write secrets and a keypair. Returns the new agent id."""
    agent_dir = Path(agent_dir)
    if agent_dir.exists() and any(agent_dir.iterdir()):
        raise FileExistsError(f"{agent_dir} already exists and is not empty")
    shutil.copytree(TEMPLATE_DIR, agent_dir, dirs_exist_ok=True)
    yaml_path = agent_dir / "agent.yaml"
    text = re.sub(r"(?m)^name:.*$", f"name: {agent_dir.name}", yaml_path.read_text(encoding="utf-8"), count=1)
    yaml_path.write_text(text, encoding="utf-8")
    if model:
        set_model(yaml_path, model)
    env = {"AGENT_SECRET": secrets.token_hex(32)}
    env.update(env_values or {})
    _write_env(agent_dir / ".env", env)
    return generate_identity(agent_dir / "identity")
