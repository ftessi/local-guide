// Tessera envelopes: signing, checking (shape, signature, time) and chains, as protocol/tessera/envelope.py and
// chain.py. Errors carry the spec's codes.
import { ed25519 } from "@noble/curves/ed25519.js";
import { sha256 } from "@noble/hashes/sha2.js";

import { b64url, b64urlDecode } from "./b64.js";
import { canonical } from "./canonical.js";

export const VERSION = "0.3";
export const WIRE_VERSIONS = ["0.2", "0.3"];
export const CARD_VERSION = "0.2"; // cards stay 0.2 envelopes, so v0.2 clients still read them
export const INNER_MAX = 46 * 1024;
const MAX_BYTES = 64 * 1024;
const CLOCK_SKEW_MS = 5 * 60 * 1000;
const AGENT_ID = /^[A-Za-z0-9_-]{43}$/;
const FIELDS = ["body", "from", "prev", "seq", "session", "sig", "tessera", "time", "to", "type"];
const BODIES = {
  hello: { purpose: "string", requested_level: "int", nonce: "string", e: "string" },
  welcome: { session: "string", granted_level: "int", expires: "string", limits: "object", f: "string" },
  refuse: { f: "string" },
  ask: { text: "string" },
  answer: { text: "string", binding: "boolean" },
  decline: {},
  close: {},
  error: { code: "string" },
  card: { agent_id: "string", name: "string", versions: "array", kx: "string" },
};
const SHAPES = {
  "0.2": BODIES,
  "0.3": { ...BODIES, ask: { text: "string", mandates: "array", reply_bytes: "int" },
    answer: { text: "string", binding: "boolean", calls: "array" }, mandate: { expires: "string" } },
};
const TEXT_LIMITS = { purpose: 200, nonce: 64, session: 64, expires: 20, name: 100, code: 32, agent_id: 43, e: 43, f: 43, kx: 43 };
const ERROR_CODES = new Set(["bad_signature", "bad_chain", "stale", "too_large", "expired", "limit", "not_allowed",
  "malformed", "unavailable", "replay"]);

export class TesseraError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

export function identityFromSeed(seed) {
  const agentId = b64url(ed25519.getPublicKey(seed));
  return { agentId, seed, sign: (data) => b64url(ed25519.sign(data, seed)) };
}

export function verify(agentId, data, signature) {
  try {
    const key = b64urlDecode(agentId), sig = b64urlDecode(signature);
    return key.length === 32 && sig.length === 64 && ed25519.verify(sig, data, key, { zip215: false });
  } catch {
    return false;
  }
}

export function formatTime(date) {
  return date.toISOString().slice(0, 19) + "Z";
}

export function parseTime(text) {
  const date = typeof text === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(text) ? new Date(text) : null;
  if (!date || Number.isNaN(date.getTime()) || formatTime(date) !== text) throw new Error(`${text} is not a Tessera time`);
  return date;
}

export const envelopeHash = (env) => b64url(sha256(canonical(env)));

export function signEnvelope(identity, { type, session, to, seq, prev, body }, now, version = VERSION) {
  const env = { tessera: version, type, session, from: identity.agentId, to, seq, prev, time: formatTime(now), body };
  return { ...env, sig: identity.sign(canonical(env)) };
}

const isType = (value, kind) =>
  kind === "int" ? Number.isSafeInteger(value)
    : kind === "array" ? Array.isArray(value)
      : kind === "object" ? value !== null && typeof value === "object" && !Array.isArray(value)
        : typeof value === kind;

export function checkShape(env, versions = WIRE_VERSIONS) {
  const bad = (why) => { throw new TesseraError("malformed", why); };
  if (env === null || typeof env !== "object" || Array.isArray(env) || Object.keys(env).sort().join() !== FIELDS.join()) {
    bad("an envelope has exactly the fields " + FIELDS.join(", "));
  }
  if (!versions.includes(env.tessera)) bad(`unsupported version ${env.tessera}`);
  const spec = Object.hasOwn(SHAPES[env.tessera], env.type) ? SHAPES[env.tessera][env.type] : null;
  if (typeof env.type !== "string" || !spec) bad(`unknown type ${env.type}`);
  for (const f of ["session", "from", "to", "prev", "time", "sig"]) if (typeof env[f] !== "string") bad(`'${f}' must be text`);
  if (!Number.isSafeInteger(env.seq) || env.seq < -1) bad("'seq' must be an integer ≥ -1");
  if (!AGENT_ID.test(env.from) || (env.to && !AGENT_ID.test(env.to))) bad("'from'/'to' must be agent ids");
  if (env.session.length > 64 || env.prev.length > 64) bad("'session'/'prev' too long");
  try { parseTime(env.time); } catch { bad("'time' must look like 2026-10-11T12:00:00Z"); }
  const body = env.body;
  if (!isType(body, "object") || Object.keys(body).sort().join() !== Object.keys(spec).sort().join()) {
    bad(`a ${env.type} body has exactly: ${Object.keys(spec).join(", ") || "nothing"}`);
  }
  for (const [key, kind] of Object.entries(spec)) {
    if (!isType(body[key], kind)) bad(`'${key}' has the wrong type`);
    if (kind === "string" && body[key].length > (TEXT_LIMITS[key] ?? MAX_BYTES)) bad(`'${key}' is too long`);
  }
  const t = env.type;
  if (t === "hello" || t === "welcome") {
    const level = body[t === "hello" ? "requested_level" : "granted_level"];
    if (level < 0 || level > 4) bad("levels go from 0 to 4");
  }
  if (t === "answer" && body.binding !== false) bad("answers are never binding at levels 1 and 2");
  if (t === "error" && !ERROR_CODES.has(body.code)) bad(`unknown error code ${body.code}`);
  if (t === "ask" && "reply_bytes" in body && body.reply_bytes < 0) bad("'reply_bytes' must be ≥ 0");
  if (t === "mandate") {
    try { parseTime(body.expires); } catch { bad("'expires' must look like 2026-10-11T13:00:00Z"); }
  }
  if (t === "welcome") {
    const limits = body.limits;
    if (Object.keys(limits).sort().join() !== "ask_chars,asks" || !Object.values(limits).every((v) => Number.isSafeInteger(v) && v >= 0)) {
      bad("limits are {asks, ask_chars}, both integers");
    }
    try { parseTime(body.expires); } catch { bad("'expires' must look like 2026-10-11T13:00:00Z"); }
  }
  for (const key of ["e", "f", "kx"]) if (key in body && !AGENT_ID.test(body[key])) bad(`'${key}' must be a 43-character base64url key`);
  if (t === "card") {
    if (!AGENT_ID.test(body.agent_id)) bad("'agent_id' must be an agent id");
    if (!body.versions.every((v) => typeof v === "string")) bad("versions are text");
  }
}

/** Shape and signature only, no clock: for envelopes carried inside others (mandates, reported calls). */
export function checkSigned(env, versions = WIRE_VERSIONS) {
  checkShape(env, versions);
  let signed;
  try {
    const { sig, ...rest } = env;
    signed = canonical(rest);
  } catch (e) {
    throw new TesseraError("malformed", e.message);
  }
  if (!verify(env.from, signed, env.sig)) throw new TesseraError("bad_signature", "the signature doesn't match the sender");
  return env;
}

/** Bytes to a checked envelope: size, JSON, shape, signature, time. Chain and session checks are the caller's. */
export function decode(raw, now, versions = WIRE_VERSIONS) {
  if (raw.length > INNER_MAX) throw new TesseraError("too_large", `envelopes are at most ${INNER_MAX} bytes`);
  let env;
  try {
    env = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
  } catch {
    throw new TesseraError("malformed", "not a JSON object");
  }
  checkSigned(env, versions);
  if (Math.abs(parseTime(env.time) - now) > CLOCK_SKEW_MS) throw new TesseraError("stale", "the envelope's time is more than 5 minutes from ours");
  return env;
}

export class Chain {
  constructor(envelopes = []) {
    this.envelopes = [];
    for (const env of envelopes) this.append(env);
  }

  nextSeq() {
    return this.envelopes.length;
  }

  lastHash() {
    return this.envelopes.length ? envelopeHash(this.envelopes.at(-1)) : "";
  }

  checkNext(env) {
    if (env.seq !== this.nextSeq() || env.prev !== this.lastHash()) {
      throw new TesseraError("bad_chain", `expected seq ${this.nextSeq()} after the last envelope`);
    }
  }

  append(env) {
    this.checkNext(env);
    this.envelopes.push(env);
  }
}
