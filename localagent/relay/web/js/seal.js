// Tessera v0.2 packages, as protocol/tessera/seal.py: the signed message travels encrypted after the Noise IK pattern
// (X25519, HKDF-SHA256, ChaCha20-Poly1305). Every key comes from the caller.
import { chacha20poly1305 } from "@noble/ciphers/chacha.js";
import { x25519 } from "@noble/curves/ed25519.js";
import { hkdf } from "@noble/hashes/hkdf.js";
import { sha256 } from "@noble/hashes/sha2.js";

import { b64url, b64urlDecode, concat, utf8 } from "./b64.js";
import { canonical } from "./canonical.js";
import { TesseraError } from "./envelope.js";

export const VERSION = "0.2";
export const TO_AGENT = 0;
export const TO_ASKER = 1;
const MAX_BYTES = 64 * 1024;
const HANDLE = /^[0-9a-f]{16}$/;
const KINDS = { hello: ["e", "ct"], welcome: ["h", "f", "ct"], msg: ["h", "n", "ct"], error: ["env"] };

export const derive = (ikm, salt, info, n) => hkdf(sha256, ikm, salt, utf8(info), n);
export const x25519Public = (priv) => b64url(x25519.getPublicKey(priv));
export const newKey = () => crypto.getRandomValues(new Uint8Array(32));

function nonce(direction, counter) {
  const out = new Uint8Array(12);
  const view = new DataView(out.buffer);
  view.setUint32(0, direction);
  view.setBigUint64(4, BigInt(counter));
  return out;
}

function dh(priv, publicB64) {
  try {
    const pub = b64urlDecode(publicB64);
    if (pub.length !== 32) throw new Error("not a key");
    return x25519.getSharedSecret(priv, pub);
  } catch {
    throw new TesseraError("malformed", "bad public key");
  }
}

function sealPackage(key, n, pkg, inner) {
  const ct = chacha20poly1305(key, n, canonical(pkg)).encrypt(inner);
  return canonical({ ...pkg, ct: b64url(ct) });
}

function openPackage(key, n, pkg) {
  const { ct, ...rest } = pkg;
  try {
    return chacha20poly1305(key, n, canonical(rest)).decrypt(b64urlDecode(ct));
  } catch {
    throw new TesseraError("bad_signature", "the package doesn't decrypt");
  }
}

/** Bytes to a well-formed package. Nothing is decrypted here. */
export function parse(raw) {
  if (raw.length > MAX_BYTES) throw new TesseraError("too_large", `packages are at most ${MAX_BYTES} bytes`);
  let p;
  try {
    p = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
  } catch {
    throw new TesseraError("malformed", "not a JSON package");
  }
  const fields = p && typeof p === "object" && !Array.isArray(p) ? KINDS[p.kind] : undefined;
  if (p?.tessera !== VERSION || !fields || Object.keys(p).sort().join() !== [...fields, "tessera", "kind"].sort().join()) {
    throw new TesseraError("malformed", "not a Tessera 0.2 package");
  }
  if (["e", "f", "ct"].some((k) => k in p && typeof p[k] !== "string")) throw new TesseraError("malformed", "e, f and ct are text");
  if ("h" in p && !(typeof p.h === "string" && HANDLE.test(p.h))) throw new TesseraError("malformed", "bad handle");
  if ("n" in p && !(Number.isSafeInteger(p.n) && p.n >= 1)) throw new TesseraError("malformed", "bad counter");
  if ("env" in p && !(p.env && typeof p.env === "object" && !Array.isArray(p.env))) {
    throw new TesseraError("malformed", "an error package carries an envelope");
  }
  return p;
}

const helloKey = (ss1, ePub, sPub) => derive(ss1, concat(b64urlDecode(ePub), b64urlDecode(sPub)), "tessera 0.2 hello", 32);

function sessionKeys(ss2, ss1, helloRaw) {
  const okm = derive(concat(ss2, ss1), sha256(helloRaw), "tessera 0.2 session", 64);
  return [okm.slice(0, 32), okm.slice(32)]; // asker -> agent, agent -> asker
}

export function sealHello(e, agentKx, inner) {
  const ePub = x25519Public(e);
  const key = helloKey(dh(e, agentKx), ePub, agentKx);
  return sealPackage(key, nonce(TO_AGENT, 0), { tessera: VERSION, kind: "hello", e: ePub }, inner);
}

export function openWelcome(e, agentKx, helloRaw, pkg) {
  if (pkg.kind !== "welcome") throw new TesseraError("malformed", "expected a welcome");
  const [kA, kB] = sessionKeys(dh(e, pkg.f), dh(e, agentKx), helloRaw);
  return { inner: openPackage(kB, nonce(TO_ASKER, 0), pkg), keys: { send: kA, recv: kB }, handle: pkg.h, f: pkg.f };
}

export function sealMsg(keys, direction, n, handle, inner) {
  return sealPackage(keys.send, nonce(direction, n), { tessera: VERSION, kind: "msg", h: handle, n }, inner);
}

/** `direction` is the sender's: TO_ASKER for what the agent sent. */
export function openMsg(keys, direction, pkg) {
  if (pkg.kind !== "msg") throw new TesseraError("malformed", "expected a message");
  return openPackage(keys.recv, nonce(direction, pkg.n), pkg);
}
