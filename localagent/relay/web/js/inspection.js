// Every browser chat is sent for inspection once finished: the record, signed by this browser and sealed to the
// company's public key, in the format of protocol/tessera/inspection.py. The relay stores it and can't open it.
import { chacha20poly1305 } from "@noble/ciphers/chacha.js";
import { x25519 } from "@noble/curves/ed25519.js";

import { b64url, b64urlDecode, concat } from "./b64.js";
import { canonical } from "./canonical.js";
import { formatTime, parseTime } from "./envelope.js";
import { derive, newKey, x25519Public } from "./seal.js";

// Built in, never fetched: the same public half as COMPANY_KEY in protocol/tessera/inspection.py (a test checks).
export const COMPANY_KEY = "YQupBjDaQOwZKuFfnN0co6ErN9PqksLi8hsYdajGMGs";
export const MAX_UPLOAD = 4 * 1024 * 1024;
export const NOTICE = "Chats are end-to-end encrypted: the relay can't read them. A sealed copy of every chat is sent "
  + "to the Tessera company for security inspection.";

export function sealUpload(identity, { peer, session, envelopes, now, ePriv = newKey(), companyKey = COMPANY_KEY }) {
  const payload = { agent_id: identity.agentId, peer, session, envelopes, sent: formatTime(now) };
  const signed = { ...payload, sig: identity.sign(canonical(payload)) };
  const ePub = x25519Public(ePriv);
  const pkg = { "tessera-inspection": 1, e: ePub };
  const key = derive(x25519.getSharedSecret(ePriv, b64urlDecode(companyKey)),
    concat(b64urlDecode(ePub), b64urlDecode(companyKey)), "tessera inspection", 32);
  const ct = chacha20poly1305(key, new Uint8Array(12), canonical(pkg)).encrypt(canonical(signed));
  const raw = canonical({ ...pkg, ct: b64url(ct) });
  if (raw.length > MAX_UPLOAD) throw new Error(`session ${session} is larger than ${MAX_UPLOAD} bytes`);
  return raw;
}

/** Closed, or past the expiry its welcome named (inspection_sender.finished). */
export function finished(envelopes, now) {
  if (!envelopes.length) return false;
  if (envelopes.at(-1).type === "close") return true;
  const welcome = envelopes.find((env) => env.type === "welcome");
  return Boolean(welcome) && parseTime(welcome.body.expires) <= now;
}

/** True only when the relay stored it (204). */
export async function upload(relayBase, raw, fetch = (...a) => globalThis.fetch(...a)) {
  try {
    const response = await fetch(relayBase.replace(/\/+$/, "") + "/relay/inspection",
      { method: "POST", body: raw, headers: { "Content-Type": "application/octet-stream" }, keepalive: true });
    return response.status === 204;
  } catch {
    return false;
  }
}
