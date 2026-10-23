"""Sends this agent's finished conversations, sealed to the company's key, while inspection mode is on.
State: tessera/inspection.yaml (enabled, relay, sent)."""
import logging
import os
from pathlib import Path
from urllib.request import Request, urlopen

import yaml

from localagent.connect.peer.tessera.endpoint import utc_now
from localagent.protocol.tessera import inspection
from localagent.protocol.tessera.envelope import parse_time

log = logging.getLogger(__name__)


def _path(agent_dir) -> Path:
    return Path(agent_dir) / "tessera" / "inspection.yaml"


def load_state(agent_dir) -> dict:
    path = _path(agent_dir)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a mapping")
    sent = raw.get("sent") or []
    return {"enabled": raw.get("enabled") is True, "relay": str(raw.get("relay") or ""),
            "sent": [s for s in sent if isinstance(s, str)]}


def save_state(agent_dir, state: dict) -> None:
    path = _path(agent_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")  # replaced in one step: never seen half written
    tmp.write_text(yaml.safe_dump({k: state[k] for k in ("enabled", "relay", "sent")}, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)


def finished(record: list[dict], now) -> bool:
    """Closed, or past the expiry its welcome named. Both sides decide from their own record."""
    if not record:
        return False
    if record[-1]["type"] == "close":
        return True
    welcome = next((env for env in record if env["type"] == "welcome"), None)
    return welcome is not None and parse_time(welcome["body"]["expires"]) <= now


def upload(relay: str, raw: bytes, opener=urlopen, timeout: float = 60) -> None:
    request = Request(relay.rstrip("/") + "/relay/inspection", data=raw, method="POST",
                      headers={"Content-Type": "application/octet-stream"})
    with opener(request, timeout=timeout) as response:
        if response.status not in (200, 204):
            raise OSError(f"the relay answered {response.status}")


def send_finished(agent_dir, protocol, identity, *, now=None, post=None) -> int:
    """Uploads every finished, not yet sent conversation. Stops at the first failed upload (next time)."""
    post = post or upload
    state = load_state(agent_dir)
    if not state["enabled"] or not inspection.COMPANY_KEY:
        return 0
    now = now or utc_now()
    count = 0
    for name in protocol.record_names():
        if name in state["sent"]:
            continue
        other, sid = name.split("/")
        try:
            record = protocol.read_record(other, sid)
        except ValueError as e:
            log.warning("Not sent for inspection: %s", e)
            continue
        if not finished(record, now):
            continue
        try:
            raw = inspection.seal_upload(identity, inspection.COMPANY_KEY, peer=other, session=sid,
                                         envelopes=record, now=now)
        except inspection.InspectionError as e:
            log.warning("Not sent for inspection: %s", e)
            continue
        state = load_state(agent_dir)  # the owner may have turned inspection off meanwhile, from another process
        if not state["enabled"]:
            break
        try:
            post(state["relay"], raw)
        except OSError as e:
            log.warning("Could not send conversations for inspection (%s); will retry", e)
            break
        state = load_state(agent_dir)
        state["sent"].append(name)
        save_state(agent_dir, state)
        protocol.audit.log("tessera_inspection", session=sid, bytes=len(raw))
        count += 1
    return count
