"""What an agent and a Tessera relay agree on (localagent/relay/ is the relay; connect/peer/tessera/relay_link.py the
agent's side)."""
MAX_WAITING = 8  # unfinished requests per agent; the relay never hands an agent more than this at once


def register_message(nonce: str, agent_id: str) -> bytes:
    """What an agent signs to register: bound to this purpose, this challenge and this agent id."""
    return f"tessera-relay-register:{nonce}:{agent_id}".encode()
