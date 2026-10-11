"""JSON Canonicalization Scheme (RFC 8785) for the JSON Tessera uses: objects, arrays, strings, integers,
booleans and null. Floats are refused: Tessera has none, and number formatting is where implementations differ."""
import json

MAX_SAFE_INT = 2 ** 53 - 1


class CanonicalError(ValueError):
    """A value Tessera messages can't contain."""


def canonical(value) -> bytes:
    try:
        return _encode(value).encode("utf-8")
    except UnicodeEncodeError:
        raise CanonicalError("strings must be valid Unicode (no lone surrogates)") from None


def _encode(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        if abs(v) > MAX_SAFE_INT:
            raise CanonicalError("integers must be within ±(2^53 - 1)")
        return str(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ",".join(_encode(x) for x in v) + "]"
    if isinstance(v, dict):
        if not all(isinstance(k, str) for k in v):
            raise CanonicalError("object keys must be strings")
        items = sorted(v.items(), key=lambda kv: kv[0].encode("utf-16-be"))
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + _encode(x) for k, x in items) + "}"
    raise CanonicalError(f"{type(v).__name__} values are not allowed in Tessera messages")
