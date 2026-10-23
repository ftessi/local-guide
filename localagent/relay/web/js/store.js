// What the page keeps in this browser (localStorage only): its Tessera identity and, per agent, the chats' records.
// Without usable storage everything still works for this tab; `persistent` tells the page history won't be kept.
import { fromHex, toHex } from "./b64.js";
import { finished } from "./inspection.js";

const IDENTITY = "tessera.identity";
const CHATS = "tessera.chats.";
const AGENTS = "tessera.agents";

function openStorage(storage) {
  try {
    if (!storage) return null;
    storage.getItem(IDENTITY); // throws where storage is blocked
    return storage;
  } catch {
    return null;
  }
}

export class Store {
  constructor(storage = (() => { try { return globalThis.localStorage; } catch { return undefined; } })()) {
    this._storage = openStorage(storage);
    this.persistent = this._storage !== null;
    this._memory = new Map(); // key -> value, always current; storage is written through
  }

  _get(key) {
    if (!this._memory.has(key) && this._storage) {
      try {
        const value = this._storage.getItem(key);
        if (value !== null) this._memory.set(key, value);
      } catch { /* treated as absent */ }
    }
    return this._memory.has(key) ? this._memory.get(key) : null;
  }

  _set(key, value) {
    this._memory.set(key, value);
    if (!this.persistent) return;
    try {
      this._storage.setItem(key, value);
    } catch {
      this.persistent = false;
    }
  }

  _agents() {
    const ids = new Set([...this._memory.keys()].filter((k) => k.startsWith(CHATS)).map((k) => k.slice(CHATS.length)));
    if (this._storage) {
      try {
        for (let i = 0; i < (this._storage.length ?? 0); i++) {
          const k = this._storage.key(i);
          if (k && k.startsWith(CHATS)) ids.add(k.slice(CHATS.length));
        }
      } catch { /* memory only */ }
    }
    return [...ids];
  }

  /** Writes one agent's chats. When storage is full, the oldest chats already sent for inspection (from any agent,
   * this list included) make room, one at a time; when none is left, history stops being kept. */
  _saveChats(agentId, list) {
    for (;;) {
      const value = JSON.stringify(list);
      this._memory.set(CHATS + agentId, value);
      if (!this.persistent) return;
      try {
        this._storage.setItem(CHATS + agentId, value);
        return;
      } catch { /* full */ }
      let oldest = null;
      for (const id of this._agents()) {
        const chats = id === agentId ? list : this.chats(id);
        for (const chat of [...chats].reverse()) { // oldest first, so ties go to the older chat
          if (chat.inspected && (!oldest || chat.started < oldest.chat.started)) oldest = { id, chat };
        }
      }
      if (!oldest) {
        this.persistent = false;
        return;
      }
      if (oldest.id === agentId) {
        list = list.filter((c) => c !== oldest.chat);
        continue;
      }
      const rest = JSON.stringify(this.chats(oldest.id).filter((c) => c.session !== oldest.chat.session));
      this._memory.set(CHATS + oldest.id, rest);
      try {
        this._storage.setItem(CHATS + oldest.id, rest);
      } catch {
        try { this._storage.removeItem(CHATS + oldest.id); } catch { /* nothing more to do */ }
      }
    }
  }

  identitySeed() {
    const saved = this._get(IDENTITY);
    if (saved && /^[0-9a-f]{64}$/.test(saved)) return fromHex(saved);
    const seed = crypto.getRandomValues(new Uint8Array(32));
    this._set(IDENTITY, toHex(seed));
    return seed;
  }

  /** Names and descriptions of agents seen in the directory, so saved chats still have a name when one is offline. */
  knownAgents() {
    try {
      const known = JSON.parse(this._get(AGENTS) || "{}");
      return known && typeof known === "object" && !Array.isArray(known) ? known : {};
    } catch {
      return {};
    }
  }

  rememberAgent(agentId, { name, description }) {
    const known = this.knownAgents();
    if (known[agentId]?.name === name && known[agentId]?.description === description) return;
    this._set(AGENTS, JSON.stringify({ ...known, [agentId]: { name, description } }));
  }

  /** Newest first: [{session, envelopes, inspected, started}]. */
  chats(agentId) {
    try {
      const list = JSON.parse(this._get(CHATS + agentId) || "[]");
      return Array.isArray(list) ? list : [];
    } catch {
      return [];
    }
  }

  saveRecord(agentId, session, envelopes) {
    const list = this.chats(agentId);
    const at = list.findIndex((c) => c.session === session);
    // A chat that grew after it was sent for inspection is sent again, whole.
    if (at >= 0) list[at] = { ...list[at], envelopes, inspected: list[at].inspected && envelopes.length === list[at].envelopes.length };
    else list.unshift({ session, envelopes, inspected: false, started: Date.now() });
    this._saveChats(agentId, list);
  }

  markInspected(agentId, session) {
    this._saveChats(agentId, this.chats(agentId).map((c) => (c.session === session ? { ...c, inspected: true } : c)));
  }

  /** Finished chats not yet sent for inspection, from every agent; never a session a client still holds open. */
  pendingUploads(now, open = new Set()) {
    return this._agents().flatMap((agentId) => this.chats(agentId)
      .filter((c) => !c.inspected && !open.has(c.session) && finished(c.envelopes, now))
      .map((c) => ({ agentId, session: c.session, envelopes: c.envelopes })));
  }
}
