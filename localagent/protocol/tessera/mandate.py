"""Mandates (v0.3): signed links "you may ask others on my behalf", chained from the person who asked first."""
from datetime import datetime, timedelta

from localagent.protocol.tessera.envelope import (EnvelopeError, check_signed, envelope_hash, format_time,
                                                  parse_time, sign_envelope)

MAX_CHAIN = 4  # the person and up to three agents ahead of the one checking
MANDATE_SECONDS = 600


def sign_mandate(identity, *, to: str, before: dict | None, now: datetime) -> dict:
    expires = now + timedelta(seconds=MANDATE_SECONDS)
    if before is not None:
        expires = min(expires, parse_time(before["body"]["expires"]))
    return sign_envelope(identity, type="mandate", session="", to=to,
                         seq=0 if before is None else before["seq"] + 1,
                         prev="" if before is None else envelope_hash(before),
                         body={"expires": format_time(expires)}, now=now, version="0.3")


def check_chain(mandates: list, *, caller: str, me: str, now: datetime) -> list[str]:
    """The ids the chain passed through, origin first. Any flaw is not_allowed."""
    def refuse(why: str):
        raise EnvelopeError("not_allowed", f"mandate chain: {why}")

    if not isinstance(mandates, list) or not 1 <= len(mandates) <= MAX_CHAIN:
        refuse(f"a chain has 1 to {MAX_CHAIN} mandates")
    ids, before = [], None
    for i, m in enumerate(mandates):
        try:
            check_signed(m, versions=("0.3",))
        except EnvelopeError as e:
            refuse(f"link {i}: {e}")
        if m["type"] != "mandate" or m["session"] or m["seq"] != i:
            refuse(f"link {i} is not mandate {i}")
        if m["prev"] != ("" if before is None else envelope_hash(before)):
            refuse(f"link {i} doesn't follow the link before it")
        if before is not None and m["from"] != before["to"]:
            refuse(f"link {i} isn't from the agent the link before it named")
        signed_at, expires = parse_time(m["time"]), parse_time(m["body"]["expires"])
        if expires <= now or expires > signed_at + timedelta(seconds=MANDATE_SECONDS):
            refuse(f"link {i} has expired or lasts too long")
        if before is not None and expires > parse_time(before["body"]["expires"]):
            refuse(f"link {i} outlives the link before it")
        ids.append(m["from"])
        before = m
    if before["from"] != caller or before["to"] != me:
        refuse("the last link must be from the caller to me")
    if len(set(ids + [me])) != len(ids) + 1:
        refuse("an agent appears twice")
    return ids
