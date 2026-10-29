// The asking side of Tessera in the browser, as connect/peer/tessera/client.py: handshake, one ask at a time, every
// reply checked against the chain. ask() never throws: failures come back as {kind: "error", text: <reason>}.
import { toHex } from "./b64.js";
import { canonical } from "./canonical.js";
import { Chain, TesseraError, checkSigned, decode, envelopeHash, parseTime, signEnvelope } from "./envelope.js";
import { signMandate } from "./mandate.js";
import * as seal from "./seal.js";

const REQUESTED_LEVEL = 1; // Ask

class HttpError extends Error {
  constructor(kind) {
    super(kind);
    this.kind = kind; // offline | busy | timeout | slow_down | unavailable | unreachable
  }
}

const REPORT_DEPTH = 3; // a report's calls can hold their own calls (nested delegation), up to the chain's limit

const str = (value, max) => (typeof value === "string" ? value.slice(0, max) : "");

/** Checks a lead's reported calls (v0.3) without trusting any of it: a call is verified only if the ask was signed
 * by the lead, for us (its mandate chain starts with us), to the agent named, and the reply was signed by that agent
 * in answer to exactly that ask. Never throws; anything malformed is simply unverified. */
export function verifyReport(calls, leadId, originId, depth = 0) {
  if (!Array.isArray(calls) || depth > REPORT_DEPTH) return [];
  return calls.map((item) => {
    const call = { agent: "", name: "", question: "", text: "", error: "", verified: false, calls: [] };
    if (item === null || typeof item !== "object" || Array.isArray(item)) return call;
    Object.assign(call, { agent: str(item.agent, 43), name: str(item.name, 100), error: str(item.error, 100) });
    const { ask, reply } = item;
    if (ask === null || typeof ask !== "object" || reply === null || typeof reply !== "object") return call;
    call.question = str(ask.body?.text, 16000);
    call.text = str(reply.body?.text, 16000);
    try {
      checkSigned(ask, ["0.3"]);
      checkSigned(reply, ["0.3"]);
      call.verified = ask.type === "ask" && ["answer", "decline"].includes(reply.type)
        && ask.from === leadId && ask.to === call.agent && reply.from === call.agent && reply.to === leadId
        && reply.prev === envelopeHash(ask) && ask.body.mandates[0]?.from === originId && !call.error;
    } catch {
      call.verified = false;
    }
    call.calls = verifyReport(reply.body?.calls, call.agent, originId, depth + 1);
    return call;
  });
}

/** Where an agent is reached on a relay: the page's own origin, never an address the relay reports. */
export const agentAddress = (relayBase, agentId) => `${relayBase.replace(/\/+$/, "")}/a/${agentId}`;

export class TesseraClient {
  constructor({ identity, agentId, address, fetch = (...a) => globalThis.fetch(...a), now = () => new Date(),
    newKey = seal.newKey, purpose = "browser chat" }) {
    Object.assign(this, { identity, agentId, address: address.replace(/\/+$/, ""), purpose });
    this._fetch = fetch;
    this._local = now;
    this._newKey = newKey;
    this._offset = 0; // relay time minus our clock, from each response's Date header
    this._chain = new Chain();
    this._sid = null;
    this.version = "0.2"; // from the agent's card at each connect: 0.3 when it lists it
    this.onRecord = null; // (sessionId, envelopes) after every envelope added to the record
  }

  /** Our clock, corrected to the relay's: envelopes more than 5 minutes off are refused on both sides. */
  now() {
    return new Date(this._local().getTime() + this._offset);
  }

  get sessionId() {
    return this._sid;
  }

  get record() {
    return this._chain.envelopes;
  }

  get limits() {
    return this._limits || null;
  }

  get expires() {
    return this._expires || null;
  }

  async _http(path, body, extra = {}) {
    let response;
    try {
      response = await this._fetch(this.address + path, body === undefined ? extra
        : { method: "POST", body, headers: { "Content-Type": "application/json" }, ...extra });
    } catch {
      throw new HttpError("unreachable");
    }
    const date = Date.parse(response.headers.get("Date") || "");
    if (!Number.isNaN(date)) this._offset = date - this._local().getTime();
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (response.status === 200) return bytes;
    let message = "";
    try {
      message = String(JSON.parse(new TextDecoder().decode(bytes)).error || "");
    } catch { /* not JSON */ }
    if (response.status === 503) throw new HttpError(/too many/.test(message) ? "busy" : "offline");
    if (response.status === 504) throw new HttpError("timeout");
    if (response.status === 429) throw new HttpError("slow_down");
    throw new HttpError("unavailable");
  }

  _sign(type, body, { session, seq, prev }) {
    return signEnvelope(this.identity, { type, session, to: this.agentId, seq, prev, body }, this.now(), this.version);
  }

  /** A reply must come from the agent we asked and be addressed to us ("" allowed for clear errors). */
  _check(env, anyone = false) {
    const allowed = anyone || env.type === "error" ? [this.identity.agentId, ""] : [this.identity.agentId];
    if (env.from !== this.agentId || !allowed.includes(env.to)) {
      throw new TesseraError("bad_signature", "the reply comes from an unexpected agent");
    }
    return env;
  }

  _recorded(env) {
    this._chain.append(env);
    if (this.onRecord) this.onRecord(this._sid, [...this._chain.envelopes]);
  }

  async _connect() {
    try {
      const card = decode(await this._http("/tessera/card"), this.now());
      if (card.type !== "card" || card.from !== this.agentId || card.body.agent_id !== this.agentId) {
        throw new TesseraError("bad_signature", "the card isn't this agent's");
      }
      const kx = card.body.kx;
      this.version = card.body.versions.includes("0.3") ? "0.3" : "0.2";
      const e = this._newKey();
      const hello = this._sign("hello", { purpose: this.purpose, requested_level: REQUESTED_LEVEL,
        nonce: toHex(crypto.getRandomValues(new Uint8Array(16))), e: seal.x25519Public(e) }, { session: "", seq: 0, prev: "" });
      const helloRaw = seal.sealHello(e, kx, canonical(hello));
      const pkg = seal.parse(await this._http("/tessera", helloRaw));
      if (pkg.kind !== "welcome") return false;
      const { inner, keys, handle, f } = seal.openWelcome(e, kx, helloRaw, pkg);
      const reply = this._check(decode(inner, this.now()));
      if (reply.type !== "welcome" || reply.body.f !== f || reply.body.granted_level < 1
        || reply.body.granted_level > REQUESTED_LEVEL) return false;
      const chain = new Chain([hello, reply]);
      const body = reply.body;
      Object.assign(this, { _chain: chain, _sid: body.session, _expires: parseTime(body.expires), _keys: keys,
        _handle: handle, _out: 1, _in: 1, _asksLeft: body.limits.asks,
        _limits: { asks: body.limits.asks, askChars: body.limits.ask_chars } });
      if (this.onRecord) this.onRecord(this._sid, [...chain.envelopes]);
      return true;
    } catch (err) {
      if (err instanceof HttpError) throw err;
      return false;
    }
  }

  async _ready() {
    if (this._sid !== null && this.now() < this._expires && this._asksLeft > 0) return true;
    this._sid = null;
    return this._connect();
  }

  /** Sends one message of the open session and returns the checked reply (an error envelope included). */
  async _exchange(env) {
    const raw = seal.sealMsg(this._keys, seal.TO_AGENT, this._out, this._handle, canonical(env));
    this._out += 1;
    const pkg = seal.parse(await this._http("/tessera", raw));
    if (pkg.kind === "error") return this._check(decode(canonical(pkg.env), this.now()), true);
    if (pkg.kind !== "msg" || pkg.h !== this._handle || pkg.n !== this._in) {
      throw new TesseraError("bad_chain", "an unexpected package");
    }
    this._in += 1;
    return this._check(decode(seal.openMsg(this._keys, seal.TO_ASKER, pkg), this.now()));
  }

  async ask(text) {
    let reply = await this._askOnce(text);
    if (reply.kind === "error" && reply.text === "expired") reply = await this._askOnce(text); // e.g. the agent restarted
    return reply;
  }

  async _askOnce(text) {
    try {
      if (!(await this._ready())) return { kind: "not_connected", text: "" };
    } catch (err) {
      return { kind: "error", text: err.kind };
    }
    if ([...text].length > this._limits.askChars) return { kind: "error", text: "too_long" };
    const body = this.version === "0.2" ? { text } : { text, reply_bytes: 0,
      mandates: [signMandate(this.identity, { to: this.agentId, before: null }, this.now())] };
    const ask = this._sign("ask", body, { session: this._sid, seq: this._chain.nextSeq(), prev: this._chain.lastHash() });
    this._recorded(ask); // recorded first: nothing is sent unrecorded
    this._asksLeft -= 1;
    let reply;
    try {
      reply = await this._exchange(ask);
    } catch (err) {
      this._sid = null;
      return { kind: "error", text: err instanceof HttpError ? err.kind : `invalid reply (${err.code || "malformed"})` };
    }
    if (reply.type === "error") {
      this._sid = null;
      return { kind: "error", text: reply.body.code };
    }
    try {
      if (reply.session !== this._sid) throw new TesseraError("bad_chain", "reply for another session");
      this._recorded(reply);
    } catch {
      this._sid = null;
      return { kind: "error", text: "bad_chain" };
    }
    if (reply.type === "answer") {
      return { kind: "answer", text: reply.body.text,
        calls: verifyReport(reply.body.calls, this.agentId, this.identity.agentId) };
    }
    if (reply.type === "decline") return { kind: "decline", text: "" };
    this._sid = null;
    return { kind: "error", text: "not_allowed" };
  }

  /** Best effort: closing is a courtesy, and the page may be going away (keepalive). */
  async close() {
    if (this._sid === null) return;
    const close = this._sign("close", {}, { session: this._sid, seq: this._chain.nextSeq(), prev: this._chain.lastHash() });
    this._recorded(close);
    const raw = seal.sealMsg(this._keys, seal.TO_AGENT, this._out, this._handle, canonical(close));
    this._out += 1;
    this._sid = null;
    try {
      await this._http("/tessera", raw, { keepalive: true });
    } catch { /* the record says closed either way */ }
  }
}
