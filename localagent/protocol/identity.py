"""Agent identity: an Ed25519 keypair. The public key (base64url) is the agent id."""
import base64
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat


def generate_identity(identity_dir: Path) -> str:
    identity_dir = Path(identity_dir)
    key_path, pub_path = identity_dir / "agent.key", identity_dir / "agent.pub"
    if key_path.exists() or pub_path.exists():
        raise FileExistsError(f"An identity already exists in {identity_dir}")
    identity_dir.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    key_path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    agent_id = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    pub_path.write_text(agent_id + "\n", encoding="utf-8")
    return agent_id


def load_agent_id(identity_dir: Path) -> str | None:
    pub_path = Path(identity_dir) / "agent.pub"
    return pub_path.read_text(encoding="utf-8").strip() if pub_path.is_file() else None
