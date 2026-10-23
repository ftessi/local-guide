// A browser chat run from Node against a real relay and agent: ask, close, seal and upload for inspection.
// Usage: node tests/js/chat_e2e.mjs <relay url> <agent id> <question> [--company-key <key>]  (the key only for tests)
import { randomBytes } from "node:crypto";

import { TesseraClient } from "../../localagent/relay/web/js/client.js";
import { identityFromSeed } from "../../localagent/relay/web/js/envelope.js";
import { sealUpload, upload } from "../../localagent/relay/web/js/inspection.js";

const [relay, agentId, question, flag, companyKey] = process.argv.slice(2);
const identity = identityFromSeed(new Uint8Array(randomBytes(32)));
const client = new TesseraClient({ identity, agentId, address: `${relay}/a/${agentId}` });
const reply = await client.ask(question);
console.log(reply.kind, reply.text);
const session = client.sessionId;
await client.close();
const raw = sealUpload(identity, { peer: agentId, session, envelopes: client.record, now: client.now(),
  ...(flag === "--company-key" ? { companyKey } : {}) });
console.log("uploaded", await upload(relay, raw));
console.log("me", identity.agentId);
