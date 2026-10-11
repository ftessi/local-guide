"""Create agent folders from agent_template/ and migrate the pre-restructure layout."""
import base64
import re
import secrets
import shutil
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from dotenv import dotenv_values

from localagent.config import REPO_ROOT
from localagent.protocol.identity import generate_identity

TEMPLATE_DIR = REPO_ROOT / "agent_template"
SECRET_KEYS = ("AGENT_SECRET", "VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_CLAIMS_EMAIL")
VAPID_FILE = "vapid_private.pem"


def _generate_vapid(agent_dir: Path) -> dict:
    key = ec.generate_private_key(ec.SECP256R1())
    (agent_dir / VAPID_FILE).write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    public = key.public_key().public_bytes(serialization.Encoding.X962,
                                           serialization.PublicFormat.UncompressedPoint)
    return {"VAPID_PRIVATE_KEY": VAPID_FILE,
            "VAPID_PUBLIC_KEY": base64.urlsafe_b64encode(public).rstrip(b"=").decode()}


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
    env = {"AGENT_SECRET": secrets.token_hex(32), "VAPID_CLAIMS_EMAIL": "you@example.com"}
    provided = dict(env_values or {})
    if not (provided.get("VAPID_PRIVATE_KEY") and provided.get("VAPID_PUBLIC_KEY")):
        env.update(_generate_vapid(agent_dir))
    env.update(provided)
    _write_env(agent_dir / ".env", env)
    return generate_identity(agent_dir / "identity")


def migrate_legacy(repo_root: Path, agent_dir: Path, dry_run: bool = False) -> list[str]:
    """Move the old root-level data into an agent folder. Never overwrites; reports every action."""
    repo_root, agent_dir = Path(repo_root), Path(agent_dir)
    actions: list[str] = []
    tag = "[dry-run] " if dry_run else ""

    legacy_env = repo_root / ".env"
    legacy = {k: v for k, v in dotenv_values(legacy_env).items() if v} if legacy_env.exists() else {}
    env_values = {k: legacy[k] for k in SECRET_KEYS if k in legacy}
    moves: list[tuple[Path, Path]] = []
    if legacy.get("VAPID_PRIVATE_KEY") and Path(legacy["VAPID_PRIVATE_KEY"]).is_file():
        moves.append((Path(legacy["VAPID_PRIVATE_KEY"]), agent_dir / VAPID_FILE))
        env_values["VAPID_PRIVATE_KEY"] = VAPID_FILE

    model = {}
    if legacy.get("MODEL_ID"):
        model["id"] = legacy["MODEL_ID"]
    if "USE_4BIT" in legacy:
        model["quantization"] = "fp16" if legacy["USE_4BIT"] == "0" else "4bit"
    if legacy.get("MAX_NEW_TOKENS", "").isdigit():
        model["max_new_tokens"] = legacy["MAX_NEW_TOKENS"]

    if not (agent_dir / "agent.yaml").exists():
        actions.append(f"{tag}create agent folder {agent_dir} (model settings and secrets from the old .env)")
        if not dry_run:
            create_agent(agent_dir, model=model, env_values=env_values)
    else:
        current = dotenv_values(agent_dir / ".env") if (agent_dir / ".env").exists() else {}
        missing = {k: v for k, v in env_values.items() if not current.get(k)}
        for k in env_values:
            if k not in missing:
                actions.append(f"SKIP .env {k}: already set in {agent_dir / '.env'}")
        if missing:
            actions.append(f"{tag}add {', '.join(missing)} to {agent_dir / '.env'}")
            if not dry_run:
                with (agent_dir / ".env").open("a", encoding="utf-8") as fh:
                    fh.writelines(f"{k}={v}\n" for k, v in missing.items())

    for sub, target in (("private", "private"), ("public", "shared")):
        folder = repo_root / "knowledge" / sub
        if folder.is_dir():
            moves += [(f, agent_dir / "knowledge" / target / f.name) for f in sorted(folder.iterdir()) if f.is_file()]
    moves += [(repo_root / "calendar.db", agent_dir / "data" / "calendar" / "calendar.db"),
              (repo_root / "push_subscriptions.json", agent_dir / "data" / "push_subscriptions.json")]

    for src, dst in moves:
        if not src.exists():
            continue
        if dst.exists():
            actions.append(f"SKIP {src} -> {dst}: target already exists")
            continue
        actions.append(f"{tag}move {src} -> {dst}")
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

    if not dry_run:
        for folder in (repo_root / "knowledge" / "private", repo_root / "knowledge" / "public",
                       repo_root / "knowledge"):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
                actions.append(f"remove empty folder {folder}")
    if legacy:
        actions.append(f"NOTE {legacy_env} is no longer read; delete it once the agent works")
    return actions
