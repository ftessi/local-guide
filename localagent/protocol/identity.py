"""Agent identity: an Ed25519 keypair. The public key (base64url) is the agent id."""
import base64
import re
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (Encoding, NoEncryption, PrivateFormat, PublicFormat,
                                                          load_pem_private_key)

AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_B64URL = re.compile(r"^[A-Za-z0-9_-]*$")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(text: str) -> bytes:
    if not isinstance(text, str) or not _B64URL.match(text):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _agent_id(key: Ed25519PrivateKey) -> str:
    return b64url(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


class Identity:
    """This agent's signing key. The private key never leaves this object."""

    def __init__(self, key: Ed25519PrivateKey):
        self._key = key
        self.agent_id = _agent_id(key)

    def sign(self, data: bytes) -> str:
        return b64url(self._key.sign(data))


def generate_identity(identity_dir: Path) -> str:
    identity_dir = Path(identity_dir)
    key_path, pub_path = identity_dir / "agent.key", identity_dir / "agent.pub"
    if key_path.exists() or pub_path.exists():
        raise FileExistsError(f"An identity already exists in {identity_dir}")
    identity_dir.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    key_path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    agent_id = _agent_id(key)
    pub_path.write_text(agent_id + "\n", encoding="utf-8")
    return agent_id


def load_agent_id(identity_dir: Path) -> str | None:
    pub_path = Path(identity_dir) / "agent.pub"
    return pub_path.read_text(encoding="utf-8").strip() if pub_path.is_file() else None


def load_identity(identity_dir: Path) -> Identity:
    path = Path(identity_dir) / "agent.key"
    if not path.is_file():
        raise FileNotFoundError(f"No identity at {path}. Agents created with scripts/new_agent.py have one.")
    key = load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"{path} is not an Ed25519 key")
    return Identity(key)


def identity_from_seed(seed: bytes) -> Identity:
    """For test vectors and tests only: a fixed key from 32 fixed bytes."""
    return Identity(Ed25519PrivateKey.from_private_bytes(seed))


def verify(agent_id: str, data: bytes, signature: str) -> bool:
    if not isinstance(agent_id, str) or not AGENT_ID_RE.match(agent_id):
        return False
    try:
        Ed25519PublicKey.from_public_bytes(b64url_decode(agent_id)).verify(b64url_decode(signature), data)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True
