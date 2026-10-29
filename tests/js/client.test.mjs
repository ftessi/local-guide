import { test } from "node:test";
import assert from "node:assert/strict";

import { TesseraClient } from "../../localagent/relay/web/js/client.js";
import { identityFromSeed } from "../../localagent/relay/web/js/envelope.js";
import { ADDRESS, AGENT, OTHER, fakeAgent, reportCall } from "./fake_agent.mjs";

const ME = identityFromSeed(new Uint8Array(32).fill(7));

function client(agent, extra = {}) {
  return new TesseraClient({ identity: ME, agentId: AGENT.agentId, address: ADDRESS, fetch: agent.fetch, ...extra });
}

test("ask, answer and the record in order", async () => {
  const records = [];
  const c = client(fakeAgent());
  c.onRecord = (session, envelopes) => records.push([session, envelopes.map((e) => e.type)]);
  assert.deepEqual(await c.ask("hello?"), { kind: "answer", text: "re: hello?", calls: [] });
  assert.deepEqual(await c.ask("again"), { kind: "answer", text: "re: again", calls: [] });
  assert.deepEqual(c.record.map((e) => e.type), ["hello", "welcome", "ask", "answer", "ask", "answer"]);
  assert.deepEqual(c.limits, { asks: 5, askChars: 20 });
  assert.equal(records.at(-1)[0], c.sessionId);
  await c.close();
  assert.deepEqual(records.at(-1)[1].at(-1), "close");
  assert.equal(c.sessionId, null);
});

test("a refused hello is not_connected", async () => {
  const agent = fakeAgent();
  agent.state.refuse = true;
  assert.deepEqual(await client(agent).ask("hi"), { kind: "not_connected", text: "" });
});

test("test_client_reports_offline_and_timeout", async () => {
  const agent = fakeAgent();
  const c = client(agent);
  await c.ask("first");
  const before = c.record.length;
  for (const [status, error, kind] of [[503, "this agent isn't connected to the relay", "offline"],
    [503, "too many requests waiting for this agent", "busy"], [504, "x", "timeout"], [429, "x", "slow_down"]]) {
    const reply = await client({ fetch: async () => new Response(JSON.stringify({ error }), { status }) }).ask("x");
    assert.deepEqual(reply, { kind: "error", text: kind });
  }
  agent.state.status = 504;
  assert.deepEqual(await c.ask("second"), { kind: "error", text: "timeout" });
  assert.equal(c.sessionId, null);
  assert.equal(c.record.length, before + 1); // the ask is recorded (it was sent), no reply appended
  const down = client({ fetch: async () => { throw new TypeError("fetch failed"); } });
  assert.deepEqual(await down.ask("x"), { kind: "error", text: "unreachable" });
});

test("test_client_corrects_clock_from_date_header", async () => {
  const relayNow = () => new Date();
  const agent = fakeAgent({ now: relayNow });
  const c = client(agent, { now: () => new Date(Date.now() + 10 * 60 * 1000) }); // the browser is 10 minutes fast
  assert.equal((await c.ask("hi")).kind, "answer");
  const stamped = new Date(c.record.at(-2).time);
  assert.ok(Math.abs(stamped - relayNow()) < 5 * 1000);
});

test("too long text is refused locally with the welcome's limit", async () => {
  const agent = fakeAgent();
  const c = client(agent);
  await c.ask("hi");
  const posts = agent.state.posts;
  assert.deepEqual(await c.ask("x".repeat(21)), { kind: "error", text: "too_long" });
  assert.equal(agent.state.posts, posts);
});

test("agent addresses come from the page's own origin", async () => {
  const { agentAddress } = await import("../../localagent/relay/web/js/client.js");
  assert.equal(agentAddress("https://relay.example/", AGENT.agentId), `https://relay.example/a/${AGENT.agentId}`);
});

test("v03 ask carries the browser's mandate", async () => {
  const agent = fakeAgent();
  const c = client(agent);
  await c.ask("hi");
  assert.equal(c.version, "0.3");
  const ask = agent.state.asks[0];
  assert.equal(ask.tessera, "0.3");
  assert.equal(ask.body.reply_bytes, 0);
  assert.deepEqual(ask.body.mandates.map((m) => [m.from, m.to]), [[ME.agentId, AGENT.agentId]]);
});

test("a v0.2 agent gets v0.2", async () => {
  const agent = fakeAgent({ versions: ["0.2"] });
  const c = client(agent);
  assert.deepEqual(await c.ask("hi"), { kind: "answer", text: "re: hi", calls: [] });
  assert.equal(c.version, "0.2");
  assert.deepEqual(agent.state.asks[0].body, { text: "hi" });
});

test("a report verifies", async () => {
  const agent = fakeAgent({ report: (ask) => [reportCall(ask, { text: "49 euros" })] });
  const reply = await client(agent).ask("price?");
  assert.equal(reply.kind, "answer");
  const [call] = reply.calls;
  assert.deepEqual(call, { agent: OTHER.agentId, name: "pricing", question: "What do you charge?",
    text: "49 euros", error: "", verified: true, calls: [] });
});

test("an edited reply is unverified", async () => {
  const agent = fakeAgent({ report: (ask) => [reportCall(ask, { text: "49 euros", edit: "1 euro" })] });
  const [call] = (await client(agent).ask("price?")).calls;
  assert.equal(call.text, "1 euro");
  assert.equal(call.verified, false);
});

test("a reply from the wrong agent is unverified", async () => {
  const agent = fakeAgent({ report: (ask) => [reportCall(ask, { text: "49 euros", wrongSigner: true })] });
  const [call] = (await client(agent).ask("price?")).calls;
  assert.equal(call.verified, false);
});

test("a call made for someone else is unverified, and a failed call keeps its error", async () => {
  const agent = fakeAgent({ report: (ask) => [reportCall(ask, { text: "x", forSomeoneElse: true }),
    { agent: OTHER.agentId, name: "pricing", ask: null, reply: null, error: "not_allowed" }, "garbage"] });
  const [other, failed, garbage] = (await client(agent).ask("price?")).calls;
  assert.equal(other.verified, false);
  assert.deepEqual({ error: failed.error, verified: failed.verified, text: failed.text },
    { error: "not_allowed", verified: false, text: "" });
  assert.equal(garbage.verified, false);
});
