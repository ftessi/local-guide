// Prints, as hex, the inspection upload the browser makes for fixed inputs (the vector keys), so Python can compare
// it with inspection.seal_upload byte for byte. Usage: node tests/js/seal_upload.mjs <company key>
import { readFileSync } from "node:fs";

import { fromHex, toHex } from "../../localagent/relay/web/js/b64.js";
import { identityFromSeed } from "../../localagent/relay/web/js/envelope.js";
import { sealUpload } from "../../localagent/relay/web/js/inspection.js";

const V = JSON.parse(readFileSync(new URL("../data/tessera_vectors_v0.2.json", import.meta.url), "utf8"));
const envelopes = V.envelopes.filter((i) => ["hello", "welcome", "ask", "answer"].includes(i.name)).map((i) => i.envelope);
const raw = sealUpload(identityFromSeed(fromHex(V.keys.B.seed_hex)), {
  peer: V.keys.A.agent_id, session: "s-0123456789abcdef", envelopes, now: new Date("2026-10-11T12:00:00Z"),
  ePriv: fromHex(V.x25519.e_B.seed_hex), companyKey: process.argv[2],
});
console.log(toHex(raw));
