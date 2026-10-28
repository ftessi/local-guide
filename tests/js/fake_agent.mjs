// A test-only Tessera agent behind a fake fetch: the agent side of seal.py, built from the same primitives, so the
// browser client can be tested without a relay. Not a test file itself.
import { chacha20poly1305 } from "../../localagent/relay/web/node_modules/@noble/ciphers/chacha.js";
import { x25519 } from "../../localagent/relay/web/node_modules/@noble/curves/ed25519.js";
import { sha256 } from "../../localagent/relay/web/node_modules/@noble/hashes/sha2.js";

import { b64url, b64urlDecode, concat, fromHex, utf8 } from "../../localagent/relay/web/js/b64.js";
import { canonical } from "../../localagent/relay/web/js/canonical.js";
import { decode, envelopeHash, formatTime, identityFromSeed, signEnvelope } from "../../localagent/relay/web/js/envelope.js";
import { signMandate } from "../../localagent/relay/web/js/mandate.js";
import { derive, openMsg, parse, sealMsg, TO_AGENT, TO_ASKER, x25519Public } from "../../localagent/relay/web/js/seal.js";

export const AGENT = identityFromSeed(fromHex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"));
const KX = fromHex("606162636465666768696a6b6c6d6e6f707172737475767778797a7b7c7d7e7f");
export const ADDRESS = `http://relay.test/a/${AGENT.agentId}`;
export const OTHER = identityFromSeed(new Uint8Array(32).fill(42)); // an agent the fake agent "called"
const STRANGER = identityFromSeed(new Uint8Array(32).fill(43));

/** One reported call, as a lead puts it in its answer: AGENT asked OTHER on behalf of the ask's sender. */
export function reportCall(ask, { text, edit, wrongSigner, forSomeoneElse }) {
  const now = new Date();
  const origin = forSomeoneElse ? signMandate(STRANGER, { to: AGENT.agentId, before: null }, now) : ask.body.mandates[0];
  const mandates = [origin, signMandate(AGENT, { to: OTHER.agentId, before: origin }, now)];
  const delegated = signEnvelope(AGENT, { type: "ask", session: "s-0000000000000001", to: OTHER.agentId, seq: 2, prev: "",
    body: { text: "What do you charge?", mandates, reply_bytes: 6656 } }, now);
  const reply = signEnvelope(wrongSigner ? STRANGER : OTHER, { type: "answer", session: "s-0000000000000001",
    to: AGENT.agentId, seq: 3, prev: envelopeHash(delegated), body: { text, binding: false, calls: [] } }, now);
  if (edit) reply.body = { ...reply.body, text: edit };
  return { agent: OTHER.agentId, name: "pricing", ask: delegated, reply, error: "" };
}

function nonce(direction, counter) {
  const out = new Uint8Array(12);
  new DataView(out.buffer).setUint32(0, direction);
  new DataView(out.buffer).setBigUint64(4, BigInt(counter));
  return out;
}

/** Options: now() (the agent's clock), answer(text), status (forced HTTP status), limits. */
export function fakeAgent(options = {}) {
  const now = options.now || (() => new Date());
  const state = { sessions: new Map(), posts: 0, refuse: false, asks: [], versions: ["0.2", "0.3"], ...options };
  const respond = (body, status = 200) =>
    new Response(status === 200 ? body : JSON.stringify({ error: options.error || "x" }),
      { status, headers: { Date: now().toUTCString() } });

  function sign(type, fields, version = "0.2") {
    return signEnvelope(AGENT, { type, ...fields }, now(), version);
  }

  function hello(raw, pkg) {
    const ss1 = x25519.getSharedSecret(KX, b64urlDecode(pkg.e));
    const key = derive(ss1, concat(b64urlDecode(pkg.e), b64urlDecode(x25519Public(KX))), "tessera 0.2 hello", 32);
    const { ct, ...rest } = pkg;
    const env = decode(chacha20poly1305(key, nonce(TO_AGENT, 0), canonical(rest)).decrypt(b64urlDecode(ct)), now());
    const f = crypto.getRandomValues(new Uint8Array(32));
    const session = "s-" + Math.random().toString(16).slice(2, 18).padEnd(16, "0");
    const expires = new Date(now().getTime() + 3600_000);
    const reply = state.refuse
      ? sign("refuse", { session: "", to: env.from, seq: 1, prev: envelopeHash(env), body: { f: x25519Public(f) } }, env.tessera)
      : sign("welcome", { session: "", to: env.from, seq: 1, prev: envelopeHash(env),
        body: { session, granted_level: 1, expires: formatTime(expires), limits: state.limits || { asks: 5, ask_chars: 20 }, f: x25519Public(f) } },
      env.tessera);
    const okm = derive(concat(x25519.getSharedSecret(f, b64urlDecode(pkg.e)), ss1), sha256(raw), "tessera 0.2 session", 64);
    const keys = { send: okm.slice(32), recv: okm.slice(0, 32) };
    const handle = "0123456789abcdef".split("").sort(() => Math.random() - 0.5).join("");
    state.sessions.set(handle, { keys, chain: [env, reply], out: 1, session, peer: env.from, version: env.tessera });
    const wpkg = { tessera: "0.2", kind: "welcome", h: handle, f: x25519Public(f) };
    const wct = chacha20poly1305(keys.send, nonce(TO_ASKER, 0), canonical(wpkg)).encrypt(canonical(reply));
    return canonical({ ...wpkg, ct: b64url(wct) });
  }

  function msg(pkg) {
    const s = state.sessions.get(pkg.h);
    const env = decode(openMsg(s.keys, TO_AGENT, pkg), now());
    s.chain.push(env);
    if (env.type === "close") return new Uint8Array();
    state.asks.push(env);
    const body = { text: (state.answer || ((t) => "re: " + t))(env.body.text), binding: false };
    if (s.version === "0.3") body.calls = state.report ? state.report(env) : [];
    const reply = sign("answer", { session: s.session, to: s.peer, seq: s.chain.length, prev: envelopeHash(env), body },
      s.version);
    s.chain.push(reply);
    return sealMsg(s.keys, TO_ASKER, s.out++, pkg.h, canonical(reply));
  }

  async function fetch(url, init = {}) {
    if (state.status) return respond("", state.status);
    if (url === `${ADDRESS}/tessera/card`) {
      return respond(canonical(sign("card", { session: "", to: "", seq: 0, prev: "",
        body: { agent_id: AGENT.agentId, name: "Fake", versions: state.versions, kx: x25519Public(KX) } })));
    }
    if (url === `${ADDRESS}/tessera` && init.method === "POST") {
      state.posts += 1;
      const raw = new Uint8Array(init.body);
      const pkg = parse(raw);
      return respond(pkg.kind === "hello" ? hello(raw, pkg) : msg(pkg));
    }
    return respond("", 404);
  }

  return { fetch, state };
}

export const text = (bytes) => new TextDecoder().decode(bytes);
export { utf8 };
