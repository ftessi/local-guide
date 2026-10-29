// JSON Canonicalization Scheme (RFC 8785) for the JSON Tessera uses, exactly as protocol/tessera/canonical.py:
// objects, arrays, strings, integers, booleans and null. Non-integers are refused.
import { utf8 } from "./b64.js";

const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;

function encode(v) {
  if (v === null) return "null";
  if (v === true) return "true";
  if (v === false) return "false";
  if (typeof v === "number") {
    if (!Number.isSafeInteger(v)) throw new Error("only integers within ±(2^53 - 1) are allowed");
    return String(v);
  }
  if (typeof v === "string") {
    if (LONE_SURROGATE.test(v)) throw new Error("strings must be valid Unicode (no lone surrogates)");
    return JSON.stringify(v); // same escapes as Python's json.dumps(ensure_ascii=False)
  }
  if (Array.isArray(v)) return "[" + v.map(encode).join(",") + "]";
  if (typeof v === "object") {
    const keys = Object.keys(v).sort(); // default sort compares UTF-16 code units, as RFC 8785 asks
    return "{" + keys.map((k) => encode(k) + ":" + encode(v[k])).join(",") + "}";
  }
  throw new Error(`${typeof v} values are not allowed in Tessera messages`);
}

export const canonical = (value) => utf8(encode(value));
