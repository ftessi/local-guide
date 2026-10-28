// Mandates (v0.3), as protocol/tessera/mandate.py: signed links "you may ask others on my behalf", chained from the
// person who asked first. The page signs the first link of every ask it sends to a v0.3 agent.
import { TesseraError, checkSigned, envelopeHash, formatTime, parseTime, signEnvelope } from "./envelope.js";

export const MAX_CHAIN = 4;
export const MANDATE_SECONDS = 600;

export function signMandate(identity, { to, before }, now) {
  let expires = new Date(now.getTime() + MANDATE_SECONDS * 1000);
  if (before) {
    const earlier = parseTime(before.body.expires);
    if (earlier < expires) expires = earlier;
  }
  return signEnvelope(identity, { type: "mandate", session: "", to, seq: before ? before.seq + 1 : 0,
    prev: before ? envelopeHash(before) : "", body: { expires: formatTime(expires) } }, now, "0.3");
}

/** The ids the chain passed through, origin first. Any flaw is not_allowed. */
export function checkChain(mandates, { caller, me, now }) {
  const refuse = (why) => { throw new TesseraError("not_allowed", `mandate chain: ${why}`); };
  if (!Array.isArray(mandates) || mandates.length < 1 || mandates.length > MAX_CHAIN) {
    refuse(`a chain has 1 to ${MAX_CHAIN} mandates`);
  }
  const ids = [];
  let before = null;
  mandates.forEach((m, i) => {
    try {
      checkSigned(m, ["0.3"]);
    } catch (e) {
      refuse(`link ${i}: ${e.message}`);
    }
    if (m.type !== "mandate" || m.session || m.seq !== i) refuse(`link ${i} is not mandate ${i}`);
    if (m.prev !== (before ? envelopeHash(before) : "")) refuse(`link ${i} doesn't follow the link before it`);
    if (before && m.from !== before.to) refuse(`link ${i} isn't from the agent the link before it named`);
    const signedAt = parseTime(m.time), expires = parseTime(m.body.expires);
    if (expires <= now || expires - signedAt > MANDATE_SECONDS * 1000) refuse(`link ${i} has expired or lasts too long`);
    if (before && expires > parseTime(before.body.expires)) refuse(`link ${i} outlives the link before it`);
    ids.push(m.from);
    before = m;
  });
  if (before.from !== caller || before.to !== me) refuse("the last link must be from the caller to me");
  if (new Set([...ids, me]).size !== ids.length + 1) refuse("an agent appears twice");
  return ids;
}
