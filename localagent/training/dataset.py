"""Training example format: one JSON object per line in training/<compartment>/examples.jsonl.
Plain chat messages, so the same data trains any model."""
from datetime import datetime

ROLES = {"system", "user", "assistant"}


class InvalidExample(ValueError):
    pass


def validate_example(example) -> dict:
    if not isinstance(example, dict) or not isinstance(example.get("messages"), list) or not example["messages"]:
        raise InvalidExample("an example needs a non-empty 'messages' list")
    for m in example["messages"]:
        if not isinstance(m, dict) or m.get("role") not in ROLES or not isinstance(m.get("content"), str):
            raise InvalidExample(f"bad message {m!r}: needs role in {sorted(ROLES)} and text content")
    roles = {m["role"] for m in example["messages"]}
    if not {"user", "assistant"} <= roles:
        raise InvalidExample("an example needs at least one user and one assistant message")
    return example


def make_example(messages: list[dict], source: str = "manual") -> dict:
    return validate_example({"messages": messages, "source": source,
                             "added": datetime.now().isoformat(timespec="seconds")})
