// The relay's page: public agents on the left, the open chat on the right. Everything the user sees of a chat is
// rendered from its verified record; the record lives in this browser only.
import { sha256 } from "@noble/hashes/sha2.js";

import { utf8 } from "./b64.js";
import { TesseraClient, agentAddress } from "./client.js";
import { identityFromSeed } from "./envelope.js";
import { NOTICE, sealUpload, upload } from "./inspection.js";
import { Store } from "./store.js";

const REFRESH_MS = 30_000;
const UPLOAD_EVERY_MS = 60_000;
const ERRORS = {
  offline: "The agent is offline.",
  busy: "Busy, try again.",
  timeout: "No answer in time.",
  slow_down: "Slow down a little.",
  unreachable: "Can't reach the relay. Check your connection.",
  unavailable: "The relay couldn't deliver this. Try again.",
  not_connected: "The agent didn't accept this chat.",
  not_allowed: "The agent no longer accepts this chat.",
  limit: "This chat reached its limit. Start a new chat.",
};

const store = new Store();
const identity = identityFromSeed(store.identitySeed());
const clients = new Map(); // agent id -> TesseraClient
let agents = []; // from the directory, public only
let selected = null; // agent id
let viewing = null; // the session shown, or null for a fresh chat
let waiting = false;
let lastError = "";

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const child of children) if (child !== null && child !== undefined) node.append(child);
  return node;
}

/** The agent's tile: a 3×3 mosaic from its id, so the same agent always looks the same. */
function tile(agentId) {
  const h = sha256(utf8(agentId));
  const hue = Math.round((h[0] / 256) * 360);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 3 3");
  svg.setAttribute("class", "tile");
  svg.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 9; i++) {
    const rect = document.createElementNS(ns, "rect");
    rect.setAttribute("x", String(i % 3));
    rect.setAttribute("y", String(Math.floor(i / 3)));
    rect.setAttribute("width", "1.02");
    rect.setAttribute("height", "1.02");
    const shade = h[i + 1] % 4;
    rect.setAttribute("fill", `hsl(${(hue + (shade === 3 ? 40 : 0)) % 360} ${38 + shade * 10}% ${30 + shade * 14}%)`);
    svg.append(rect);
  }
  return svg;
}

function agentInfo(agentId) {
  const live = agents.find((a) => a.id === agentId);
  const known = store.knownAgents()[agentId];
  return { name: live?.name || known?.name || agentId.slice(0, 8), description: live?.description ?? known?.description ?? "",
    online: Boolean(live) };
}

// ── Agents ─────────────────────────────────────────────────────────────────

async function refreshAgents() {
  try {
    const response = await fetch("/agents", { cache: "no-store" });
    if (!response.ok) return;
    const listed = await response.json();
    agents = Array.isArray(listed) ? listed.filter((a) => a && a.public === true) : [];
    for (const a of agents) store.rememberAgent(a.id, { name: a.name, description: a.description });
  } catch {
    return; // keep the last list; the next refresh tries again
  }
  renderAgents();
  renderHead();
}

function renderAgents() {
  const offlineWithChats = Object.keys(store.knownAgents())
    .filter((id) => !agents.some((a) => a.id === id) && store.chats(id).length);
  const ids = [...agents.map((a) => a.id), ...offlineWithChats];
  $("agents").replaceChildren(...ids.map((id) => {
    const info = agentInfo(id);
    return el("li", {}, el("button", {
      type: "button", class: "agent" + (info.online ? "" : " offline"),
      "aria-current": String(id === selected), onclick: () => selectAgent(id),
    }, tile(id), el("span", {}, el("span", { class: "agent-name" }, info.name),
      info.online ? el("span", { class: "agent-desc" }, info.description) : el("span", { class: "agent-state" }, "offline"))));
  }));
  $("no-agents").hidden = ids.length > 0;
}

function selectAgent(id) {
  selected = id;
  viewing = store.chats(id)[0]?.session ?? null; // the latest chat, even one that ended (a reload ends it)
  lastError = "";
  renderAgents();
  renderChat();
  $("question").focus();
}

// ── Chat ───────────────────────────────────────────────────────────────────

function renderHead() {
  if (!selected) return;
  const info = agentInfo(selected);
  $("chat-agent").replaceChildren(tile(selected),
    el("div", {}, el("h2", {}, info.name), el("p", {}, info.online ? info.description : "Offline. Your saved chats are still here.")));
  const canAsk = info.online && !waiting;
  $("question").disabled = !canAsk;
  $("question").placeholder = info.online ? `Ask ${info.name}` : `${info.name} is offline`;
  $("new-chat").disabled = !info.online || waiting;
  updateCount();
}

function renderChat() {
  renderHead();
  $("not-kept").hidden = store.persistent;
  const chats = store.chats(selected);
  const shown = chats.find((c) => c.session === viewing);
  const items = [];
  for (const env of shown ? shown.envelopes : []) {
    if (env.type === "ask") items.push(el("li", { class: "msg mine" }, env.body.text));
    else if (env.type === "answer") items.push(el("li", { class: "msg theirs" }, env.body.text));
    else if (env.type === "decline") items.push(el("li", { class: "msg theirs declined" }, "The agent declined to answer."));
    else if (env.type === "close") items.push(el("li", { class: "line" }, "Chat ended."));
  }
  if (waiting) items.push(el("li", { class: "msg theirs thinking" }, "Thinking"));
  if (lastError) items.push(el("li", { class: "line error", role: "alert" }, lastError));
  if (!items.length) {
    items.push(el("li", { class: "hint" }, agentInfo(selected).online
      ? "Ask anything. Answers can take a minute: these agents often run on small computers."
      : "Nothing to show yet."));
  }
  $("messages").replaceChildren(...items);
  $("messages").scrollTop = $("messages").scrollHeight;

  const earlier = chats.filter((c) => c.session !== viewing);
  $("earlier").hidden = earlier.length === 0;
  $("earlier-list").replaceChildren(...earlier.map((c) => {
    const first = c.envelopes.find((e) => e.type === "ask");
    return el("li", {}, el("button", { type: "button", onclick: () => { viewing = c.session; lastError = ""; $("earlier").open = false; renderChat(); } },
      first ? first.body.text.slice(0, 60) : "(no messages)",
      el("time", { datetime: new Date(c.started).toISOString() }, new Date(c.started).toLocaleString())));
  }));
}

function clientFor(agentId) {
  let client = clients.get(agentId);
  if (!client) {
    client = new TesseraClient({ identity, agentId, address: agentAddress(location.origin, agentId) });
    client.onRecord = (session, envelopes) => {
      store.saveRecord(agentId, session, envelopes);
      if (selected === agentId) viewing = session;
    };
    clients.set(agentId, client);
  }
  return client;
}

function updateCount() {
  const client = selected && clients.get(selected);
  const max = client?.limits?.askChars;
  const used = [...$("question").value].length;
  $("count").textContent = max ? `${used} / ${max}` : "";
  $("count").classList.toggle("over", Boolean(max) && used > max);
  $("send").disabled = $("question").disabled || used === 0 || (Boolean(max) && used > max);
}

async function send(event) {
  event.preventDefault();
  const text = $("question").value.trim();
  if (!text || !selected || waiting) return;
  const agentId = selected;
  const client = clientFor(agentId);
  waiting = true;
  lastError = "";
  $("question").value = "";
  renderChat();
  const reply = await client.ask(text);
  waiting = false;
  if (reply.kind === "error" || reply.kind === "not_connected") {
    if (reply.text === "too_long") lastError = `Question too long (max ${client.limits.askChars} characters).`;
    else lastError = ERRORS[reply.kind === "not_connected" ? "not_connected" : reply.text] || `Something went wrong (${reply.text}).`;
    if (!store.chats(agentId).some((c) => c.envelopes.some((e) => e.type === "ask" && e.body.text === text))) {
      $("question").value = text; // never sent: give the text back
    }
  }
  if (selected === agentId) renderChat();
  sendForInspection();
}

async function newChat() {
  const client = clients.get(selected);
  if (client) await client.close();
  viewing = null;
  lastError = "";
  renderChat();
  sendForInspection();
}

// ── Inspection ─────────────────────────────────────────────────────────────

let sending = false;

async function sendForInspection() {
  if (sending) return;
  sending = true;
  try {
    const all = [...clients.values()];
    const now = all.length ? all[0].now() : new Date(); // the relay's time, as the clients keep it
    const open = new Set(all.map((c) => c.sessionId).filter(Boolean));
    for (const chat of store.pendingUploads(now, open)) {
      let raw;
      try {
        raw = sealUpload(identity, { peer: chat.agentId, session: chat.session, envelopes: chat.envelopes, now });
      } catch {
        continue; // too large to send; it stays here
      }
      if (await upload(location.origin, raw)) store.markInspected(chat.agentId, chat.session);
      else break; // the relay can't take it now: next time
    }
  } finally {
    sending = false;
  }
}

// ── Start ──────────────────────────────────────────────────────────────────

$("notice").textContent = NOTICE; // on screen before anything can be sent
$("me").textContent = `Your id in this browser: ${identity.agentId.slice(0, 8)}…`;
$("not-kept").hidden = store.persistent;
$("composer").addEventListener("submit", send);
$("question").addEventListener("input", updateCount);
$("question").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) $("composer").requestSubmit();
});
$("new-chat").addEventListener("click", newChat);
window.addEventListener("focus", refreshAgents);
window.addEventListener("pagehide", () => {
  for (const client of clients.values()) client.close();
});
setInterval(refreshAgents, REFRESH_MS);
setInterval(sendForInspection, UPLOAD_EVERY_MS);
await refreshAgents();
renderAgents();
sendForInspection();
