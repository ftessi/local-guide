// Bytes and text: strict base64url (one spelling per byte string, as protocol/identity.py), hex, UTF-8.

const B64URL = /^[A-Za-z0-9_-]*$/;

export function b64url(bytes) {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

export function b64urlDecode(text) {
  if (typeof text !== "string" || !B64URL.test(text) || text.length % 4 === 1) throw new Error("not base64url");
  const bin = atob(text.replaceAll("-", "+").replaceAll("_", "/") + "=".repeat((4 - (text.length % 4)) % 4));
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  if (b64url(bytes) !== text) throw new Error("non-canonical base64url");
  return bytes;
}

export const utf8 = (text) => new TextEncoder().encode(text);

export function concat(...arrays) {
  const out = new Uint8Array(arrays.reduce((n, a) => n + a.length, 0));
  let at = 0;
  for (const a of arrays) {
    out.set(a, at);
    at += a.length;
  }
  return out;
}

export const toHex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");

export function fromHex(hex) {
  if (!/^([0-9a-f]{2})*$/.test(hex)) throw new Error("not hex");
  return Uint8Array.from(hex.match(/../g) || [], (h) => parseInt(h, 16));
}
