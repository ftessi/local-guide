// Tessera v0.2 in the browser must produce the published vectors byte for byte (tests/data/tessera_vectors_v0.2.json).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { b64url, b64urlDecode, fromHex, toHex, utf8 } from "../../localagent/relay/web/js/b64.js";
import { canonical } from "../../localagent/relay/web/js/canonical.js";
import { Chain, TesseraError, decode, envelopeHash, identityFromSeed, signEnvelope } from "../../localagent/relay/web/js/envelope.js";
import * as seal from "../../localagent/relay/web/js/seal.js";

const V = JSON.parse(readFileSync(new URL("../data/tessera_vectors_v0.2.json", import.meta.url), "utf8"));
const TIME = new Date("2026-10-11T12:00:00Z");
const A = identityFromSeed(fromHex(V.keys.A.seed_hex));
const B = identityFromSeed(fromHex(V.keys.B.seed_hex));
const X = Object.fromEntries(Object.entries(V.x25519).map(([k, v]) => [k, fromHex(v.seed_hex)]));
const envs = Object.fromEntries(V.envelopes.map((item) => [item.name, item.envelope]));
const text = (bytes) => new TextDecoder().decode(bytes);

test("identities and one-time keys match", () => {
  assert.equal(A.agentId, V.keys.A.agent_id);
  assert.equal(B.agentId, V.keys.B.agent_id);
  for (const [name, seed] of Object.entries(X)) assert.equal(seal.x25519Public(seed), V.x25519[name].public);
});

test("canonical JSON", () => {
  for (const c of V.canonical) assert.equal(text(canonical(c.value)), c.canonical);
  assert.throws(() => canonical({ a: 1.5 }));
  assert.throws(() => canonical({ a: 2 ** 53 }));
  assert.throws(() => canonical({ a: "\ud800" }));
});

test("envelopes: canonical bytes, hashes, signatures, decode", () => {
  for (const item of V.envelopes) {
    const env = item.envelope;
    assert.equal(text(canonical(env)), item.canonical);
    assert.equal(envelopeHash(env), item.hash);
    const { sig, tessera, from, ...fields } = env;
    const signer = from === A.agentId ? A : B;
    const again = signEnvelope(signer, fields, TIME, tessera);
    assert.equal(again.sig, sig);
    assert.deepEqual(decode(utf8(item.canonical), TIME), env);
  }
});

test("decode refuses tampering, staleness and bad shapes", () => {
  const bad = { ...envs.answer, sig: envs.ask.sig };
  assert.throws(() => decode(canonical(bad), TIME), (e) => e instanceof TesseraError && e.code === "bad_signature");
  assert.throws(() => decode(canonical(envs.answer), new Date("2026-10-11T12:06:00Z")), (e) => e.code === "stale");
  assert.throws(() => decode(utf8("[]"), TIME), (e) => e.code === "malformed");
  assert.throws(() => decode(canonical({ ...envs.answer, extra: 1 }), TIME), (e) => e.code === "malformed");
});

test("chain links", () => {
  const chain = new Chain();
  for (const name of ["hello", "welcome", "ask", "answer"]) chain.append(envs[name]);
  assert.equal(chain.nextSeq(), 4);
  assert.equal(chain.lastHash(), envelopeHash(envs.answer));
  assert.throws(() => chain.append(envs.ask), (e) => e.code === "bad_chain");
});

test("strict base64url", () => {
  assert.equal(b64url(b64urlDecode("YWJj")), "YWJj");
  assert.throws(() => b64urlDecode("YWJj="));
  assert.throws(() => b64urlDecode("YWJk_"));  // not canonical
});

test("sealed packages reproduce the vectors", () => {
  const pkgs = Object.fromEntries(V.packages.map((p) => [p.name, p.package]));
  const hello = seal.sealHello(X.e_B, V.x25519.kx_A.public, canonical(envs.hello));
  assert.equal(text(hello), pkgs.hello);
  const opened = seal.openWelcome(X.e_B, V.x25519.kx_A.public, hello, seal.parse(utf8(pkgs.welcome)));
  assert.equal(text(opened.inner), text(canonical(envs.welcome)));
  assert.equal(opened.handle, V.handle);
  assert.equal(opened.f, V.x25519.f_A.public);
  assert.equal(toHex(opened.keys.send), V.session_keys.asker_to_agent);
  assert.equal(toHex(opened.keys.recv), V.session_keys.agent_to_asker);
  const ask = seal.sealMsg(opened.keys, seal.TO_AGENT, 1, V.handle, canonical(envs.ask));
  assert.equal(text(ask), pkgs.ask);
  const answer = seal.openMsg(opened.keys, seal.TO_ASKER, seal.parse(utf8(pkgs.answer)));
  assert.equal(text(answer), text(canonical(envs.answer)));
  const tampered = { ...seal.parse(utf8(pkgs.answer)), n: 2 };
  assert.throws(() => seal.openMsg(opened.keys, seal.TO_ASKER, tampered), (e) => e.code === "bad_signature");
  assert.throws(() => seal.parse(utf8('{"tessera":"0.2","kind":"msg","h":"x","n":1,"ct":""}')), (e) => e.code === "malformed");
});

const V3 = JSON.parse(readFileSync(new URL("../data/tessera_vectors_v0.3.json", import.meta.url), "utf8"));

test("v0.3 envelopes reproduce the vectors and the chains check", async () => {
  const { checkChain, signMandate } = await import("../../localagent/relay/web/js/mandate.js");
  const { checkSigned } = await import("../../localagent/relay/web/js/envelope.js");
  const ids = Object.fromEntries(Object.entries(V3.keys).map(([k, v]) => [k, identityFromSeed(fromHex(v.seed_hex))]));
  for (const [k, v] of Object.entries(V3.keys)) assert.equal(ids[k].agentId, v.agent_id);
  const byId = Object.fromEntries(Object.values(ids).map((i) => [i.agentId, i]));
  const env3 = {};
  for (const item of V3.envelopes) {
    const env = item.envelope;
    env3[item.name] = env;
    assert.equal(text(canonical(env)), item.canonical);
    assert.equal(envelopeHash(env), item.hash);
    const { sig, tessera, from, ...fields } = env;
    assert.equal(signEnvelope(byId[from], fields, TIME, tessera).sig, sig);
    assert.deepEqual(checkSigned(env), env);
  }
  assert.deepEqual(signMandate(ids.B, { to: ids.A.agentId, before: null }, TIME), env3.mandate_b_a);
  assert.deepEqual(signMandate(ids.A, { to: ids.C.agentId, before: env3.mandate_b_a }, TIME), env3.mandate_a_c);
  assert.deepEqual(checkChain(env3.ask_with_mandate.body.mandates, { caller: ids.B.agentId, me: ids.A.agentId, now: TIME }),
    [ids.B.agentId]);
  assert.deepEqual(checkChain(env3.delegated_ask.body.mandates, { caller: ids.A.agentId, me: ids.C.agentId, now: TIME }),
    [ids.B.agentId, ids.A.agentId]);
  assert.throws(() => checkChain(env3.delegated_ask.body.mandates, { caller: ids.B.agentId, me: ids.C.agentId, now: TIME }),
    (e) => e.code === "not_allowed");
  assert.throws(() => checkChain(env3.delegated_ask.body.mandates,
    { caller: ids.A.agentId, me: ids.C.agentId, now: new Date(TIME.getTime() + 601_000) }), (e) => e.code === "not_allowed");
  assert.throws(() => decode(canonical({ ...env3.ask_with_mandate, tessera: "0.2" }), TIME), (e) => e.code === "malformed");
});
