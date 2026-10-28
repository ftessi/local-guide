import { test } from "node:test";
import assert from "node:assert/strict";

import { Store } from "../../localagent/relay/web/js/store.js";

class FakeStorage {
  constructor(cap = Infinity) {
    this.map = new Map();
    this.cap = cap;
  }
  getItem(k) {
    return this.map.has(k) ? this.map.get(k) : null;
  }
  setItem(k, v) {
    const size = [...this.map].reduce((n, [key, val]) => n + (key === k ? 0 : key.length + val.length), 0);
    if (size + k.length + v.length > this.cap) {
      const e = new Error("full");
      e.name = "QuotaExceededError";
      throw e;
    }
    this.map.set(k, String(v));
  }
  removeItem(k) {
    this.map.delete(k);
  }
  get length() {
    return this.map.size;
  }
  key(i) {
    return [...this.map.keys()][i] ?? null;
  }
}

const AGENT = "A".repeat(43);
const OTHER = "B".repeat(43);
const env = (type, extra = {}) => ({ type, body: {}, ...extra });
const welcome = (expires) => env("welcome", { body: { expires } });
const closed = [env("hello"), welcome("2030-01-01T00:00:00Z"), env("ask"), env("close")];
const open = [env("hello"), welcome("2030-01-01T00:00:00Z"), env("ask")];
const NOW = new Date("2026-10-23T12:00:00Z");

test("test_identity_created_once", () => {
  const storage = new FakeStorage();
  const seed = new Store(storage).identitySeed();
  assert.equal(seed.length, 32);
  assert.deepEqual(new Store(storage).identitySeed(), seed);
});

test("test_reload_starts_new_session_keeps_history", () => {
  const storage = new FakeStorage();
  const store = new Store(storage);
  store.saveRecord(AGENT, "s-1", closed);
  store.saveRecord(AGENT, "s-2", open);
  store.saveRecord(AGENT, "s-1", closed); // an update keeps its place
  const again = new Store(storage);
  assert.deepEqual(again.chats(AGENT).map((c) => c.session), ["s-2", "s-1"]);
  assert.deepEqual(again.chats(OTHER), []);
  assert.equal(again.persistent, true);
});

test("test_pending_uploads_only_finished_uninspected", () => {
  const store = new Store(new FakeStorage());
  store.saveRecord(AGENT, "s-1", closed);
  store.saveRecord(AGENT, "s-2", open);
  store.saveRecord(OTHER, "s-3", [env("hello"), welcome("2026-10-23T11:00:00Z"), env("ask")]); // expired
  store.saveRecord(OTHER, "s-4", closed);
  store.markInspected(OTHER, "s-4");
  assert.deepEqual(store.pendingUploads(NOW).map((p) => [p.agentId, p.session]).sort(),
    [[AGENT, "s-1"], [OTHER, "s-3"]]);
});

test("test_store_survives_quota_and_missing_storage", () => {
  const storage = new FakeStorage();
  const store = new Store(storage);
  store.identitySeed();
  for (const s of ["s-1", "s-2", "s-3"]) {
    store.saveRecord(AGENT, s, closed);
    store.markInspected(AGENT, s);
  }
  storage.cap = [...storage.map].reduce((n, [k, v]) => n + k.length + v.length, 0); // full now
  store.saveRecord(AGENT, "s-4", closed);
  assert.equal(store.persistent, true);
  assert.ok(new Store(storage).chats(AGENT).some((c) => c.session === "s-4")); // older inspected chats made room
  assert.ok(!new Store(storage).chats(AGENT).some((c) => c.session === "s-1")); // the oldest went first

  const none = new Store(undefined);
  assert.equal(none.persistent, false);
  none.saveRecord(AGENT, "s-1", closed);
  assert.equal(none.chats(AGENT).length, 1);
  assert.equal(none.identitySeed().length, 32);

  const throwing = new Store({ getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } });
  assert.equal(throwing.persistent, false);
  throwing.saveRecord(AGENT, "s-1", closed);
  assert.equal(throwing.chats(AGENT).length, 1);
});

test("known agents are remembered for offline chats", () => {
  const storage = new FakeStorage();
  new Store(storage).rememberAgent(AGENT, { name: "Demo", description: "Answers" });
  assert.deepEqual(new Store(storage).knownAgents(), { [AGENT]: { name: "Demo", description: "Answers" } });
});

test("a chat that grows after inspection is pending again, and open sessions are never pending", () => {
  const store = new Store(new FakeStorage());
  store.saveRecord(AGENT, "s-1", [env("hello"), welcome("2026-10-23T11:00:00Z"), env("ask")]); // expired by NOW
  store.markInspected(AGENT, "s-1");
  assert.deepEqual(store.pendingUploads(NOW), []);
  store.saveRecord(AGENT, "s-1", [env("hello"), welcome("2026-10-23T11:00:00Z"), env("ask"), env("answer")]);
  assert.deepEqual(store.pendingUploads(NOW).map((p) => p.session), ["s-1"]);
  assert.deepEqual(store.pendingUploads(NOW, new Set(["s-1"])), []); // still held open by a client
});

test("workspace starts empty", () => {
  assert.deepEqual(new Store(new FakeStorage()).workspace(), { agents: [], lead: null });
});

test("add, lead, remove", () => {
  const storage = new FakeStorage();
  const store = new Store(storage);
  store.addToWorkspace(AGENT);
  store.addToWorkspace(OTHER);
  store.addToWorkspace(AGENT); // once only
  store.addToWorkspace("not an id");
  store.setLead(OTHER);
  store.setLead("C".repeat(43)); // not in the workspace: ignored
  assert.deepEqual(new Store(storage).workspace(), { agents: [AGENT, OTHER], lead: OTHER });
  store.removeFromWorkspace(OTHER);
  assert.deepEqual(new Store(storage).workspace(), { agents: [AGENT], lead: null });
});

const at = (type, time, body = {}) => ({ type, time, body });

test("lastActivity counts calls made to an agent", () => {
  const store = new Store(new FakeStorage());
  store.saveRecord(AGENT, "s-1", [at("hello", "2026-10-28T10:00:00Z"), at("ask", "2026-10-28T10:01:00Z", { text: "hi" })]);
  const call = { agent: OTHER, name: "other", ask: { body: { text: "price?" } }, reply: null, error: "" };
  store.saveRecord("C".repeat(43), "s-2", [at("ask", "2026-10-28T11:00:00Z", { text: "q" }),
    at("answer", "2026-10-28T11:05:00Z", { text: "a", calls: [call] })]);
  assert.equal(store.lastActivity(AGENT), Date.parse("2026-10-28T10:01:00Z"));
  assert.equal(store.lastActivity(OTHER), Date.parse("2026-10-28T11:05:00Z"));
  assert.equal(store.lastActivity("D".repeat(43)), 0);
  assert.deepEqual(store.lastExchange(OTHER), { by: "C".repeat(43), text: "price?", at: Date.parse("2026-10-28T11:05:00Z") });
  assert.deepEqual(store.lastExchange(AGENT), { by: null, text: "hi", at: Date.parse("2026-10-28T10:01:00Z") });
});

test("workspace survives full storage", () => {
  const storage = new FakeStorage(0);
  const store = new Store(storage);
  store.addToWorkspace(AGENT);
  store.setLead(AGENT);
  assert.deepEqual(store.workspace(), { agents: [AGENT], lead: AGENT });
});
