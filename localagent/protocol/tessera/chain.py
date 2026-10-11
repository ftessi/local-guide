"""A session's record: every envelope in order, each naming the hash of the one before (both directions)."""
from dataclasses import dataclass, field

from localagent.protocol.identity import verify
from localagent.protocol.tessera.canonical import CanonicalError, canonical
from localagent.protocol.tessera.envelope import EnvelopeError, check_shape, envelope_hash


@dataclass
class Chain:
    envelopes: list = field(default_factory=list)

    def next_seq(self) -> int:
        return len(self.envelopes)

    def last_hash(self) -> str:
        return envelope_hash(self.envelopes[-1]) if self.envelopes else ""

    def check_next(self, env: dict) -> None:
        if env["seq"] != self.next_seq() or env["prev"] != self.last_hash():
            raise EnvelopeError("bad_chain", f"expected seq {self.next_seq()} after the last envelope")

    def append(self, env: dict) -> None:
        self.check_next(env)
        self.envelopes.append(env)


def verify_record(envelopes: list[dict]) -> None:
    """Checks a stored record end to end: every shape, signature and link. Raises only EnvelopeError."""
    chain = Chain()
    for env in envelopes:
        check_shape(env)
        try:
            signed = canonical({k: v for k, v in env.items() if k != "sig"})
        except CanonicalError as e:
            raise EnvelopeError("malformed", str(e)) from None
        if not verify(env["from"], signed, env["sig"]):
            raise EnvelopeError("bad_signature", f"envelope {env['seq']} has a bad signature")
        chain.append(env)
