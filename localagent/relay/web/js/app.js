// The relay's page: the person's workspace board on the left (Running, then Latest), the open agent's chat on the
// right. Everything shown of a chat is rendered from its verified record; records and the workspace live in this
// browser only. Questions go to the open agent; the lead (★) is opened first, and its answers list the calls it made.
import { sha256 } from "@noble/hashes/sha2.js";

import { utf8 } from "./b64.js";
import { TesseraClient, agentAddress, verifyReport } from "./client.js";
import { decode, identityFromSeed } from "./envelope.js";
import { NOTICE, sealUpload, upload } from "./inspection.js";
import { Store } from "./store.js";

const REFRESH_MS = 30_000;
const UPLOAD_EVERY_MS = 60_000;
const AGENT_ID = /^[A-Za-z0-9_-]{43}$/;
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
const CALL_ERRORS = {
  not_allowed: "wouldn't answer for you: its owner hasn't allowed you, or an agent on the way",
  not_connected: "didn't accept the lead's call",
  old_version: "runs an older Tessera that can't be asked on your behalf",
  too_large: "had a question or answer too large to report",
  "already in the chain": "was already part of this question",
  unreachable: "couldn't be reached",
  timeout: "didn't answer in time",
  unavailable: "couldn't answer right now",
};

const store = new Store();
const identity = identityFromSeed(store.identitySeed());
const clients = new Map(); // agent id -> TesseraClient
const inFlight = new Set(); // agents with a question from this page still waiting for its answer
const errors = new Map(); // agent id -> the last error to show in its chat
let directory = []; // public agents listed on the relay
let selected = null; // agent id of the open chat
let viewing = null; // the session shown, or null for a fresh chat

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

/** Name and state of an agent. One that was listed publicly and is gone now is offline; one added by its id is
 * assumed reachable (asking tells). */
function agentInfo(agentId) {
  const live = directory.find((a) => a.id === agentId);
  const known = store.knownAgents()[agentId];
  return { name: live?.name || known?.name || agentId.slice(0, 8), description: live?.description ?? known?.description ?? "",
    online: Boolean(live) || known?.listed !== true };
}

const when = (ms) => {
  const minutes = Math.round((ms - Date.now()) / 60_000);
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (Math.abs(minutes) < 1) return "just now";
  if (Math.abs(minutes) < 60) return rtf.format(minutes, "minute");
  if (Math.abs(minutes) < 60 * 24) return rtf.format(Math.round(minutes / 60), "hour");
  return rtf.format(Math.round(minutes / (60 * 24)), "day");
};

// ── Board ──────────────────────────────────────────────────────────────────

async function refreshDirectory() {
  try {
    const response = await fetch("/agents", { cache: "no-store" });
    if (!response.ok) return;
    const listed = await response.json();
    directory = Array.isArray(listed) ? listed.filter((a) => a && a.public === true && AGENT_ID.test(a.id)) : [];
    for (const a of directory) store.rememberAgent(a.id, { name: a.name, description: a.description, listed: true });
  } catch {
    return; // keep the last list; the next refresh tries again
  }
  renderBoard();
  renderHead();
}

function card(agentId, lead) {
  const info = agentInfo(agentId);
  const last = store.lastExchange(agentId);
  let line = info.description || "No messages yet.";
  if (inFlight.has(agentId)) line = "Answering…";
  else if (last) line = `${last.by ? `asked by ${agentInfo(last.by).name}` : "You"}: ${last.text} · ${when(last.at)}`;
  const isLead = agentId === lead;
  return el("li", { class: "card" + (inFlight.has(agentId) ? " running" : "") + (info.online ? "" : " offline") },
    el("button", { type: "button", class: "card-open", "aria-current": String(agentId === selected), onclick: () => openChat(agentId) },
      tile(agentId),
      el("span", { class: "card-text" },
        el("span", { class: "card-name" }, info.name, info.online ? null : el("span", { class: "card-state" }, " · offline")),
        el("span", { class: "card-line" }, line))),
    el("button", { type: "button", class: "star" + (isLead ? " on" : ""), "aria-pressed": String(isLead),
      title: isLead ? `${info.name} is your lead` : `Make ${info.name} your lead`,
      "aria-label": isLead ? `${info.name} is your lead` : `Make ${info.name} your lead`,
      onclick: () => { store.setLead(agentId); renderBoard(); } }, isLead ? "★" : "☆"));
}

function renderBoard() {
  const { agents, lead } = store.workspace();
  const running = agents.filter((id) => inFlight.has(id));
  const latest = agents.filter((id) => !inFlight.has(id))
    .sort((a, b) => store.lastActivity(b) - store.lastActivity(a));
  $("running").replaceChildren(...running.map((id) => card(id, lead)));
  $("latest").replaceChildren(...latest.map((id) => card(id, lead)));
  $("running-head").hidden = running.length === 0;
  $("latest-head").hidden = latest.length === 0;
  $("empty-workspace").hidden = agents.length > 0;
  $("lead-line").replaceChildren(lead ? el("span", {}, "Lead: ", el("b", {}, `★ ${agentInfo(lead).name}`))
    : el("span", { class: "muted" }, agents.length ? "Star an agent to make it your lead." : ""));
  const others = directory.filter((a) => !agents.includes(a.id));
  $("directory").replaceChildren(...others.map((a) => el("li", {},
    el("button", { type: "button", class: "directory-item", onclick: () => addAgent(a.id) }, tile(a.id),
      el("span", { class: "card-text" }, el("span", { class: "card-name" }, a.name),
        el("span", { class: "card-line" }, a.description || "")),
      el("span", { class: "add-mark", "aria-hidden": "true" }, "+")))));
  $("no-directory").hidden = others.length > 0;
}

function addAgent(agentId) {
  const first = store.workspace().agents.length === 0;
  store.addToWorkspace(agentId);
  if (first) store.setLead(agentId);
  toggleAdd(false);
  renderBoard();
  openChat(agentId);
}

/** An agent added by its id: its card (signed by it, fetched through this relay) gives its name. */
async function addById(event) {
  event.preventDefault();
  const agentId = $("add-id").value.trim();
  $("add-error").textContent = "";
  if (!AGENT_ID.test(agentId)) {
    $("add-error").textContent = "An agent id is 43 letters, digits, - or _.";
    return;
  }
  try {
    const response = await fetch(`${agentAddress(location.origin, agentId)}/tessera/card`, { cache: "no-store" });
    if (!response.ok) throw new Error(String(response.status));
    const card = decode(new Uint8Array(await response.arrayBuffer()), new Date(Date.parse(response.headers.get("Date") || "") || Date.now()));
    if (card.type !== "card" || card.from !== agentId || card.body.agent_id !== agentId) throw new Error("not its card");
    store.rememberAgent(agentId, { name: card.body.name, description: "" });
  } catch {
    $("add-error").textContent = "No agent with this id is connected to this relay right now.";
    return;
  }
  $("add-id").value = "";
  addAgent(agentId);
}

function toggleAdd(open = $("add-panel").hidden) {
  $("add-panel").hidden = !open;
  $("add-agent").setAttribute("aria-expanded", String(open));
  if (open) refreshDirectory();
}

// ── Chat ───────────────────────────────────────────────────────────────────

function openChat(agentId) {
  selected = agentId;
  viewing = store.chats(agentId)[0]?.session ?? null; // the latest chat, even one that ended (a reload ends it)
  $("app").dataset.view = "chat";
  renderBoard();
  renderChat();
  $("question").focus();
}

function renderHead() {
  if (!selected) return;
  const info = agentInfo(selected);
  const isLead = store.workspace().lead === selected;
  $("chat-agent").replaceChildren(tile(selected),
    el("div", {}, el("h2", {}, (isLead ? "★ " : "") + info.name),
      el("p", {}, info.online ? info.description : "Offline. Your saved chats are still here.")));
  const waiting = inFlight.has(selected);
  $("question").disabled = !info.online || waiting;
  $("question").placeholder = info.online ? `Ask ${info.name}` : `${info.name} is offline`;
  $("new-chat").disabled = !info.online || waiting;
  updateCount();
}

function callItem(call) {
  const name = call.name || call.agent.slice(0, 8);
  const failed = Boolean(call.error) || !call.text && !call.question;
  const status = failed ? CALL_ERRORS[call.error] || `couldn't answer (${call.error || "no reply"})`
    : call.verified ? "answered" : "answered · not verified";
  return el("li", { class: "call" + (failed ? " failed" : call.verified ? "" : " unverified") },
    el("details", {},
      el("summary", {}, el("b", {}, name), ` ${status}`),
      call.question ? el("p", { class: "call-q" }, el("span", { class: "label" }, "Asked: "), call.question) : null,
      !failed ? el("p", { class: "call-a" }, el("span", { class: "label" }, "Reply: "), call.text || "(declined)") : null,
      !failed && !call.verified ? el("p", { class: "call-warn" },
        "Not verified: this reply doesn't carry the agent's own signature for this question, so the lead may have changed it.") : null,
      call.calls.length ? el("ul", { class: "calls" }, ...call.calls.map(callItem)) : null));
}

function renderChat() {
  renderHead();
  $("not-kept").hidden = store.persistent;
  if (!selected) return;
  const chats = store.chats(selected);
  const shown = chats.find((c) => c.session === viewing);
  const items = [];
  for (const env of shown ? shown.envelopes : []) {
    if (env.type === "ask") items.push(el("li", { class: "msg mine" }, env.body.text));
    else if (env.type === "answer") {
      const calls = verifyReport(env.body.calls, selected, identity.agentId);
      items.push(el("li", { class: "msg theirs" }, el("div", {}, env.body.text),
        calls.length ? el("ul", { class: "calls", "aria-label": "Agents it asked" }, ...calls.map(callItem)) : null));
    } else if (env.type === "decline") items.push(el("li", { class: "msg theirs declined" }, "The agent declined to answer."));
    else if (env.type === "close") items.push(el("li", { class: "line" }, "Chat ended."));
  }
  if (inFlight.has(selected)) items.push(el("li", { class: "msg theirs thinking" }, "Thinking"));
  if (errors.get(selected)) items.push(el("li", { class: "line error", role: "alert" }, errors.get(selected)));
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
    return el("li", {}, el("button", { type: "button", onclick: () => { viewing = c.session; errors.delete(selected); $("earlier").open = false; renderChat(); } },
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
      if (selected !== agentId) return;
      viewing = session;
      renderChat(); // the question shows as soon as it is recorded, before the answer
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
  const agentId = selected;
  if (!text || !agentId || inFlight.has(agentId)) return;
  const client = clientFor(agentId);
  inFlight.add(agentId);
  errors.delete(agentId);
  $("question").value = "";
  renderBoard();
  renderChat();
  const reply = await client.ask(text);
  inFlight.delete(agentId);
  if (reply.kind === "error" || reply.kind === "not_connected") {
    errors.set(agentId, reply.text === "too_long" ? `Question too long (max ${client.limits.askChars} characters).`
      : ERRORS[reply.kind === "not_connected" ? "not_connected" : reply.text] || `Something went wrong (${reply.text}).`);
    if (selected === agentId && !$("question").value
      && !store.chats(agentId).some((c) => c.envelopes.some((e) => e.type === "ask" && e.body.text === text))) {
      $("question").value = text; // never sent: give the text back
    }
  }
  renderBoard();
  if (selected === agentId) renderChat();
  sendForInspection();
}

async function newChat() {
  const client = clients.get(selected);
  if (client) await client.close();
  viewing = null;
  errors.delete(selected);
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
$("me").textContent = identity.agentId;
$("copy-id").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(identity.agentId);
    $("copy-id").textContent = "Copied";
  } catch {
    getSelection()?.selectAllChildren($("me")); // copy by hand
  }
  setTimeout(() => { $("copy-id").textContent = "Copy"; }, 1500);
});
$("not-kept").hidden = store.persistent;
$("add-agent").addEventListener("click", () => toggleAdd());
$("add-by-id").addEventListener("submit", addById);
$("back").addEventListener("click", () => { $("app").dataset.view = "board"; });
$("composer").addEventListener("submit", send);
$("question").addEventListener("input", updateCount);
$("question").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) $("composer").requestSubmit();
});
$("new-chat").addEventListener("click", newChat);
window.addEventListener("focus", refreshDirectory);
window.addEventListener("pagehide", () => {
  for (const client of clients.values()) client.close();
});
setInterval(refreshDirectory, REFRESH_MS);
setInterval(sendForInspection, UPLOAD_EVERY_MS);

// Agents chatted with before the workspace existed join it, so no history is hidden.
for (const id of Object.keys(store.knownAgents())) if (store.chats(id).length) store.addToWorkspace(id);
await refreshDirectory();
const { agents, lead } = store.workspace();
renderBoard();
if (agents.length === 0) toggleAdd(true);
else if (matchMedia("(min-width: 701px)").matches) openChat(lead || agents[0]);
sendForInspection();
