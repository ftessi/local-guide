"""Inspection mode: a finished conversation, signed by the agent and sealed to the company's public key, so only the
company's offline private key opens it (docs/08-connecting-agents.md). The key is built in here and never fetched
from a relay, so a relay can't substitute its own."""
import json

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from localagent.protocol.identity import b64url, b64url_decode, verify, x25519_from_b64, x25519_public
from localagent.protocol.tessera.canonical import canonical
from localagent.protocol.tessera.chain import verify_record
from localagent.protocol.tessera.envelope import EnvelopeError, format_time
from localagent.protocol.tessera.seal import derive

COMPANY_KEY = ""  # the public half from scripts/new_inspection_key.py; empty: inspection can't be turned on
ASKER_NOTICE = ("Conversations are end-to-end encrypted. The other side's owner may send them to the relay operator "
                "for security analysis.")
MAX_UPLOAD = 4 * 1024 * 1024
PAYLOAD_FIELDS = {"agent_id", "peer", "session", "envelopes", "sent", "sig"}


class InspectionError(ValueError):
    """An upload that can't be opened or doesn't check out."""


def _key(shared: bytes, e_pub: str, company: str) -> bytes:
    return derive(shared, b64url_decode(e_pub) + b64url_decode(company), "tessera inspection", 32)


def seal_upload(identity, company_key: str, *, peer: str, session: str, envelopes: list, now,
                e: X25519PrivateKey | None = None) -> bytes:
    payload = {"agent_id": identity.agent_id, "peer": peer, "session": session, "envelopes": envelopes,
               "sent": format_time(now)}
    payload["sig"] = identity.sign(canonical(payload))
    e = e or X25519PrivateKey.generate()
    e_pub = x25519_public(e)
    package = {"tessera-inspection": 1, "e": e_pub}
    key = _key(e.exchange(x25519_from_b64(company_key)), e_pub, company_key)
    ct = ChaCha20Poly1305(key).encrypt(bytes(12), canonical(payload), canonical(package))
    raw = canonical({**package, "ct": b64url(ct)})
    if len(raw) > MAX_UPLOAD:
        raise InspectionError(f"session {session} is larger than {MAX_UPLOAD} bytes")
    return raw


def open_upload(private_key: X25519PrivateKey, raw: bytes) -> dict:
    """Opens an upload with the company's private key and checks the agent's signature and every message."""
    try:
        package = json.loads(raw.decode("utf-8"))
        if not isinstance(package, dict) or set(package) != {"tessera-inspection", "e", "ct"} \
                or package["tessera-inspection"] != 1:
            raise ValueError("not an inspection upload")
        company = x25519_public(private_key)
        key = _key(private_key.exchange(x25519_from_b64(package["e"])), package["e"], company)
        aad = canonical({"tessera-inspection": 1, "e": package["e"]})
        payload = json.loads(ChaCha20Poly1305(key).decrypt(bytes(12), b64url_decode(package["ct"]), aad))
    except (InvalidTag, ValueError, TypeError, UnicodeDecodeError) as e:
        raise InspectionError(f"this upload doesn't open with this key ({e or 'authentication failed'})") from None
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_FIELDS:
        raise InspectionError("the upload's content is malformed")
    signed = canonical({k: v for k, v in payload.items() if k != "sig"})
    if not verify(payload["agent_id"], signed, payload["sig"]):
        raise InspectionError("the upload isn't signed by the agent it names")
    try:
        verify_record(payload["envelopes"])
    except (EnvelopeError, TypeError, KeyError) as e:
        raise InspectionError(f"the conversation doesn't verify ({e})") from None
    parties = {payload["agent_id"], payload["peer"]}
    if not all(env["from"] in parties and env["to"] in parties | {""} for env in payload["envelopes"]):
        raise InspectionError("the conversation has messages from other agents")
    return payload
