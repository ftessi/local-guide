"""Agent identity: an Ed25519 keypair. The public key (base64url) is the agent id. Beside it: an X25519 key for
Tessera's key exchange and a key for records at rest."""
import base64
import re
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.serialization import (Encoding, NoEncryption, PrivateFormat, PublicFormat,
                                                          load_pem_private_key)

AGENT_ID_RE = re.compile(r"[A-Za-z0-9_-]{43}")
_B64URL = re.compile(r"[A-Za-z0-9_-]*")
_KEY_BYTES, _SIG_BYTES = 32, 64


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(text: str) -> bytes:
    """Strict: only the one canonical spelling of each byte string is accepted."""
    if not isinstance(text, str) or not _B64URL.fullmatch(text):
        raise ValueError("not base64url")
    data = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if b64url(data) != text:
        raise ValueError("non-canonical base64url")
    return data


def _agent_id(key: Ed25519PrivateKey) -> str:
    return b64url(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def x25519_public(key: X25519PrivateKey) -> str:
    return b64url(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def x25519_from_b64(text: str) -> X25519PublicKey:
    data = b64url_decode(text)  # ValueError if not canonical base64url
    if len(data) != _KEY_BYTES:
        raise ValueError("not an X25519 public key")
    return X25519PublicKey.from_public_bytes(data)


def x25519_from_seed(seed: bytes) -> X25519PrivateKey:
    """For test vectors and tests only: a fixed key from 32 fixed bytes."""
    return X25519PrivateKey.from_private_bytes(seed)


def _write_new(path: Path, data: bytes) -> None:
    """Creates the file only if it doesn't exist: two processes starting at once both keep the first key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "xb") as fh:
            fh.write(data)
    except FileExistsError:
        pass


def load_kx(identity_dir: Path) -> X25519PrivateKey:
    """The agent's key-exchange key (its public half is in the card). Created on first use."""
    path = Path(identity_dir) / "kx.key"
    if not path.is_file():
        _write_new(path, X25519PrivateKey.generate().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    key = load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, X25519PrivateKey):
        raise ValueError(f"{path} is not an X25519 key")
    return key


def load_record_key(identity_dir: Path) -> bytes:
    """The key that encrypts this agent's Tessera records on disk. Created on first use."""
    path = Path(identity_dir) / "record.key"
    if not path.is_file():
        _write_new(path, (b64url(secrets.token_bytes(32)) + "\n").encode())
    key = b64url_decode(path.read_text(encoding="utf-8").strip())
    if len(key) != 32:
        raise ValueError(f"{path} is not a 32-byte key")
    return key


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
    load_kx(identity_dir)
    load_record_key(identity_dir)
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
    if not isinstance(agent_id, str) or not AGENT_ID_RE.fullmatch(agent_id):
        return False
    try:
        key_bytes, sig_bytes = b64url_decode(agent_id), b64url_decode(signature)
        if len(key_bytes) != _KEY_BYTES or len(sig_bytes) != _SIG_BYTES:
            return False
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(sig_bytes, data)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True
