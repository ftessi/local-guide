// What the page keeps in this browser (localStorage only): its Tessera identity, its workspace (agents and lead)
// and, per agent, the chats' records.
// Without usable storage everything still works for this tab; `persistent` tells the page history won't be kept.
import { fromHex, toHex } from "./b64.js";
import { finished } from "./inspection.js";

const IDENTITY = "tessera.identity";
const CHATS = "tessera.chats.";
const AGENTS = "tessera.agents";
const WORKSPACE = "tessera.workspace";
const AGENT_ID = /^[A-Za-z0-9_-]{43}$/;

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

  /** `listed`: seen in the public directory (gone from it later means offline); agents added by id don't have it. */
  rememberAgent(agentId, { name, description, listed }) {
    const known = this.knownAgents();
    const entry = listed ? { name, description, listed: true } : { name, description };
    if (JSON.stringify(known[agentId]) === JSON.stringify(entry)) return;
    this._set(AGENTS, JSON.stringify({ ...known, [agentId]: entry }));
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

  /** The agents this person keeps on the board, and the one their questions go to first (the lead). */
  workspace() {
    try {
      const saved = JSON.parse(this._get(WORKSPACE) || "{}");
      const agents = Array.isArray(saved.agents) ? saved.agents.filter((id) => AGENT_ID.test(id)) : [];
      return { agents, lead: agents.includes(saved.lead) ? saved.lead : null };
    } catch {
      return { agents: [], lead: null };
    }
  }

  _saveWorkspace(workspace) {
    this._set(WORKSPACE, JSON.stringify(workspace));
  }

  addToWorkspace(agentId) {
    const ws = this.workspace();
    if (AGENT_ID.test(agentId) && !ws.agents.includes(agentId)) this._saveWorkspace({ ...ws, agents: [...ws.agents, agentId] });
  }

  removeFromWorkspace(agentId) {
    const ws = this.workspace();
    this._saveWorkspace({ agents: ws.agents.filter((id) => id !== agentId), lead: ws.lead === agentId ? null : ws.lead });
  }

  setLead(agentId) {
    const ws = this.workspace();
    if (ws.agents.includes(agentId)) this._saveWorkspace({ ...ws, lead: agentId });
  }

  /** The latest thing that happened with an agent: this person's own question to it, or a question a lead asked it
   * in one of this person's chats (`by` is that lead). Null when nothing has. */
  lastExchange(agentId) {
    let latest = null;
    const consider = (by, text, time) => {
      const when = Date.parse(time);
      if (!Number.isNaN(when) && (!latest || when > latest.at)) latest = { by, text: typeof text === "string" ? text : "", at: when };
    };
    for (const chat of this.chats(agentId)) {
      for (const env of chat.envelopes) if (env?.type === "ask") consider(null, env.body?.text, env.time);
    }
    for (const leadId of this._agents()) {
      for (const chat of this.chats(leadId)) {
        for (const env of chat.envelopes) {
          if (env?.type !== "answer" || !Array.isArray(env.body?.calls)) continue;
          for (const call of env.body.calls) if (call?.agent === agentId) consider(leadId, call.ask?.body?.text, env.time);
        }
      }
    }
    return latest;
  }

  /** Milliseconds since the epoch of the latest exchange, 0 for none: the board's "Latest" order. */
  lastActivity(agentId) {
    return this.lastExchange(agentId)?.at ?? 0;
  }

  /** Finished chats not yet sent for inspection, from every agent; never a session a client still holds open. */
  pendingUploads(now, open = new Set()) {
    return this._agents().flatMap((agentId) => this.chats(agentId)
      .filter((c) => !c.inspected && !open.has(c.session) && finished(c.envelopes, now))
      .map((c) => ({ agentId, session: c.session, envelopes: c.envelopes })));
  }
}
