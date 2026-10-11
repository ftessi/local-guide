# 11. Troubleshooting

## Install and startup

| Symptom | Cause / fix |
|---|---|
| `No agent found at …` | Run `python scripts/new_agent.py`, or pass `--agent <folder>` / set `LOCALAGENT_DIR` |
| `Error: … agent.yaml …` or `… policy.yaml …` | The message names the bad setting; fix it and restart |
| `'default_peer' … was removed` | Old `policy.yaml`: delete the `default_peer:` line; accept agents with `peers accept` (page 8) |
| Very slow, `+cpu` or `CUDA: False` | pip replaced torch with a CPU build: reinstall the CUDA build (page 2, step 4) |
| `bitsandbytes` errors on Mac or CPU | 4-bit needs an NVIDIA GPU: set `quantization: none` (or `fp16` on a GPU) |
| Model download fails for Llama / Gemma | Gated model: `huggingface-cli login` first |
| `pip install -r requirements.txt` fails on Mac or CPU | It pins the NVIDIA cu118 torch build: use the commands on page 2 instead |

## Chat and the model

| Symptom | Cause / fix |
|---|---|
| `[error] Out of GPU memory …` | Another program holds the GPU (close it), or the prompt is too long: lower `max_prompt_chars`, or `reset` |
| `[error] Could not load adapters …` | A trained adapter in `training/adapters/` is broken or for another model: retrain it (page 7) or remove the folder. The agent refuses rather than running without it. |
| Answers cut off mid-sentence | Raise `max_new_tokens` (400 is a good value) |
| It invents answers / says it searched when it didn't | Look for `(used …)` lines: only those really ran. Small models do this; ask again naming the tool, `reset` if it keeps copying old answers, or use a bigger model |
| It says "I can't access the internet/files" | The tool isn't installed (`python -m localagent list`) or the model didn't call it; ask again ("search the web for…") |
| It set a reminder but nothing happened | Look for `(Couldn't run calendar.create: …)`. Reminders fire only while `serve` runs |

## Tools

| Symptom | Fix |
|---|---|
| `'npx' was not found on PATH` | Install Node.js LTS and open a new terminal |
| `MCP server for 'x' failed to start` | Read `my-agent/data/x/server.log`; run the `mcp:` command by hand to see the error |
| `no action(s) foo. It offers: …` | A name in `actions:` is misspelled; the message lists the real ones |
| `… is listed in installables.yaml but not installed` | `python -m localagent install` |
| `(Couldn't run files.write_file: Access denied - path outside allowed directories…)` | Working as intended: the model tried a path outside the workspace |
| A tool's answer is cut off | Raise `max_result_chars` |

## Phone app and tunnel

| Symptom | Fix |
|---|---|
| "Connection error" in the app | Wrong token (clear the site's data and re-enter `AGENT_SECRET`), `serve` not running, or the tunnel is down |
| `Address already in use` | Another program is on that port: close it or change `port:` in `installables.yaml` |
| `cloudflared is not installed or not on PATH` | Install cloudflared (page 4), or remove the `cloudflare` connection |
| Site unreachable from the phone | `cloudflared tunnel info local-agent`; check DNS at https://dnschecker.org |
| No notifications | Notifications denied on the phone; on iPhone the app must be on the Home Screen (iOS 16.4+) |

## Training

| Symptom | Fix |
|---|---|
| `Out of GPU memory while training` | Close chat/serve (they hold the GPU), or `--device cpu` |
| `examples.jsonl is empty or missing` | Run `python -m localagent examples --compartment <c>` first |
| Recall below 90% in `adapter_eval.py` | Retrain with more epochs (`--epochs 12`) or add phrasings to the sources |
| `The private adapter never leaves the internal agent` | Working as intended: only connection adapters can be exported |
| `The adapter was trained for …` | Adapters only work on their base model: the destination must use the same model, or retrain |

## Tessera

| Symptom | Fix |
|---|---|
| `Not connected: … hasn't accepted this agent (or isn't reachable)` | They haven't run `peers accept` yet, the address/port is wrong, the firewall blocks it, or their `serve` isn't running. (By design you can't tell which.) |
| `This agent folder can't face other agents: …` | The Tessera-facing folder holds something it shouldn't: the message lists each item. Remove it; don't put anything else in that folder |
| `Only a Tessera-facing agent accepts peers` | Run `peers` with `--agent tessera-<name>`, not on your own agent |
| `… is a Tessera-facing agent … Chat with your internal agent instead` | Working as intended: chat with `my-agent` |
| Every question gets `declined` | Expected for things not in the adapter. If even the shared facts are declined, check the adapter was exported (`export --adapter … --to …`) and `adapter_eval.py` passes |
| `Error talking to …: limit` / `expired` | Session limits (50 questions, 1 hour): `ask` again; it reconnects |

Next: [12. Decisions and roadmap](12-decisions-and-roadmap.md)
