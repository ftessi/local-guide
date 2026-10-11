# Web search fixes — making "how did the Berlin election go?" work
Date: 2026-10-11

Everything that was changed so the agent (Qwen2.5-1.5B-Instruct, fp16, on a GTX 1050 with 4 GB) answers a
web question with real numbers and a real source. Most of this page is about the last change, **reading the
prompt in chunks**, because it is the one that changes what this hardware can do.

---

## Contents

1. [What was going wrong](#1-what-was-going-wrong)
2. [Fix 1: history stops teaching the model to skip tools](#2-fix-1-history-stops-teaching-the-model-to-skip-tools)
3. [Fix 2: the agent opens the page itself, and keeps only the relevant parts](#3-fix-2-the-agent-opens-the-page-itself-and-keeps-only-the-relevant-parts)
4. [Fix 3: reading the prompt in chunks](#4-fix-3-reading-the-prompt-in-chunks)
5. [Configuration changes](#5-configuration-changes)
6. [How it was verified](#6-how-it-was-verified)
7. [What is still not right](#7-what-is-still-not-right)

---

## 1. What was going wrong

Symptom: the first web question searched, later ones "got dumb": no tool calls, the same invented numbers
(FDP 2%, SPD 1%, "Minister President Christian Lindner") repeated in every answer, or "I can't browse the web".

Found in `my-agent/memory/private/2026-10-11.jsonl` and by rebuilding the exact prompt of a failing turn:

| # | Cause | Evidence |
|---|---|---|
| 1 | **Search results don't contain the answer.** DuckDuckGo returns titles and one-line summaries. The model had to decide to open a page with `fetch_content`; the 1.5B model never did and invented numbers instead. | 12:30 turn: one `web.search`, then made-up seat counts. |
| 2 | **History replayed the model's own bad answers.** Every answer is replayed as conversation history. After a few turns the prompt held 7 examples of "user asks to search → assistant answers without searching". Small models copy what's in front of them over what the system prompt says. | The 12:50 answer is a near word-for-word copy of the 12:42 one. |
| 3 | **The one good example was cut first.** The prompt budget (`max_prompt_chars: 8000`) drops the oldest turns first, and the only turn that searched was the oldest. | Rebuilt 12:50 prompt: 14 history messages, none with a tool call. |
| 4 | **Long pages were cut at the start.** Tool results were truncated to their first 4000 characters; on Wikipedia the results table starts around character 18,000 of 43,000. | Fetched page text, measured. |
| 5 | **Out of GPU memory once the page fit.** After fixes 1–2 the page excerpt made the prompt 2,350 tokens and the card ran out of memory. | `[error] Out of GPU memory: the prompt was 2350 tokens` |

---

## 2. Fix 1: history stops teaching the model to skip tools

**File:** `localagent/protocol/session.py` (`Session.history`, `PLAIN_TURNS = 2`)

When the session has tools, only the **2 latest** turns answered *without* a tool are replayed to the model.
Turns where a tool really ran (at least one call with `ok: true`) are always replayed: they are the examples
we *want* the model to copy. Agents without tools replay everything, as before. Nothing is deleted:
memory files are unchanged, this only affects what the model sees.

- Pro: invented answers and "I can't browse" stop piling up as examples.
- Con: something said in a tool-less exchange more than two such turns ago is no longer in the model's
  context.

Tests: `tests/test_session.py` (3 new).

---

## 3. Fix 2: the agent opens the page itself, and keeps only the relevant parts

**Files:** `localagent/agent/core.py`, new `localagent/agent/excerpt.py`, `localagent/extensions.py`,
`localagent/agent/tools/base.py`

### 3a. `follow:` — a tool setting in `installables.yaml`

```yaml
follow: {search: fetch_content}
```

After a successful `search`, the **agent's code** (not the model) takes the links in the result and runs
`fetch_content` on the first one that works (up to 3 tries, `FOLLOW_TRIES`). The user sees
`(used web.fetch_content: url=…)`. The model receives the page next to the search results, so the
decision a 1.5B model was bad at ("these are only links, I should open one") no longer has to be made.

It is generic: any tool can declare `follow`. `install` checks that both actions exist and that the second
takes exactly one required argument (the link).

### 3b. Excerpts instead of the first N characters

Any text in a tool result longer than `RESULT_CHARS = 2500` is reduced by `excerpt()` to:

- the start of the page (it says what the page is), plus
- the 400-character windows sharing the most words with the user's question, in page order.

Plain word matching, no model involved. Words are cut to 4 letters so "parties" matches "party" and
"percentages" matches "percent"; common words ("what", "search", "please"…) are ignored; windows with
numbers get a small bonus. Windows are fixed-size because fetched pages often arrive as one long line.

Opened pages are put **before** the link list in the results message, so if the prompt budget has to cut,
it cuts the link list, not the page.

Tests: `tests/test_excerpt.py` (3), `tests/test_agent_core.py` (3), `tests/test_extensions.py` (4).

---

## 4. Fix 3: reading the prompt in chunks

**File:** `localagent/runtime/transformers_backend.py` (`_prefill`, `PREFILL_CHUNK = 256`)
**Test:** `tests/test_runtime_contract.py::test_long_prompts_are_read_in_chunks`

### 4.1 Background: the two phases of generating a reply

A model produces a reply in two phases:

1. **Prefill — reading the prompt.** Every prompt token goes through all 28 layers of the model. In each
   layer, *attention* lets every token look at every earlier token. Done for the whole prompt in one go,
   that means building a table of scores of size *tokens × tokens* for each of the model's 12 attention
   heads, in every layer.
2. **Decode — writing the reply.** One new token at a time. Each new token only needs its own row of
   scores against everything before it.

To avoid recomputing the prompt for every new token, each layer stores two vectors per token (a *key* and a
*value*): the **KV cache**. For Qwen2.5-1.5B that is:

```
28 layers × 2 (key + value) × 2 KV heads × 128 numbers × 2 bytes (fp16) = 28,672 bytes ≈ 28 KB per token
```

So remembering a 2,000-token conversation costs ≈ 56 MB. Small.

### 4.2 Where the memory actually went

The card has 4096 MiB. The model weights take 2,944 MiB, plus the CUDA context and Windows' display,
which leaves **≈ 400 MiB free**. Measured extra GPU memory while reading a prompt (same model, same card):

| Prompt | Read in one go | Read in 256-token chunks |
|---|---|---|
| 1,000 tokens | +181 MiB | +42 MiB |
| 2,000 tokens | +561 MiB | +71 MiB |
| 2,500 tokens | **out of memory** | — |
| 3,000 tokens | **out of memory** | +128 MiB |
| 4,000 tokens | **out of memory** | +145 MiB |
| 6,000 tokens | **out of memory** | +207 MiB |
| 8,000 tokens | **out of memory** | +282 MiB |

Doubling the prompt from 1,000 to 2,000 tokens tripled the memory in one go: the score tables grow with
the **square** of the length. They exist only for a moment, but that moment has to fit. In chunks, growth is
close to linear, because the dominant cost becomes the KV cache.

This is also why a character budget was a poor proxy. English is about 4 characters per token, but a web
page full of numbers and German names is about 2.5. The same 6,000 characters were about 1,500 tokens of chat
but 2,350 tokens of election results.

### 4.3 How chunked reading works

Instead of giving the whole prompt to `generate()`, the backend first feeds it to the model **256 tokens at
a time**, keeping the KV cache between pieces:

```python
def _prefill(self, input_ids, chunk: int = PREFILL_CHUNK):
    end = input_ids.shape[1] - 1          # leave the last token for generate()
    if end <= chunk:
        return None                       # short prompts: read in one go, as before
    cache = DynamicCache()
    with torch.no_grad():
        for start in range(0, end, chunk):
            self.model(input_ids=input_ids[:, start:min(start + chunk, end)],
                       past_key_values=cache, use_cache=True, logits_to_keep=1)
    return cache
```

Then `generate()` is called with the **full** `input_ids` plus `past_key_values=cache`. Transformers sees
that the cache already covers all but the last token and only processes that last token, then decodes as
usual. Streaming, stop tokens and the "out of GPU memory" message work the same.

What changes per chunk: chunk *k* compares its 256 tokens against the *k × 256* tokens before it. The
biggest table is 256 × (whole prompt), not (whole prompt) × (whole prompt).

Details:

- **Why leave the last token?** `generate()` needs at least one uncached token to compute the scores for
  the first reply token. Leaving exactly one keeps `generate()` on its normal path.
- **`logits_to_keep=1`**: at the end of each pass the model would otherwise compute a score for every one
  of its 151,936 vocabulary words, for every token in the chunk. Nothing reads those scores during
  prefill, so only one row is kept.
- **Prompts of 257 tokens or fewer** skip all of this.

### 4.4 Does it change the answers?

Mathematically, no: attention for a token depends only on the tokens before it, which is exactly what the
cache holds. Checked on a 1,868-token prompt with greedy decoding: **the same 40-token answer, word for
word**, with +504 MiB read in one go vs +42 MiB in chunks. A 7,433-token prompt, impossible before, ran
with +149 MiB.

In theory fp16 arithmetic done in a different order can differ in the last bits, which could very rarely
flip a greedy choice between two near-equal words. Not observed.

### 4.5 Pros

- **About 4× to 12× less extra memory** at the prompt sizes the agent uses, more the longer the prompt
  (1,000 tokens: 181 → 42 MiB; 2,000 tokens: 561 → 71 MiB). The
  out-of-memory error is gone at the current budget.
- **Longer prompts are possible**: 8,000 tokens measured, within the ≈ 400 MiB free.
- **Same answers**: verified above. No quality trade-off, unlike shrinking the prompt.
- **No new dependencies, no new settings.** Short prompts take the old path.
- **The budget can leave more for results and history.** `max_prompt_chars: 8000` is now far below the
  card's limit.

### 4.6 Cons and limits

- **Some extra time.** Each chunk is a separate pass, and each pass reads the 2.9 GB of weights from GPU
  memory again. This was not timed separately. Estimate: the GTX 1050 reads about 112 GB/s, so roughly 30 ms
  per extra pass, ≈ 0.2 s for a 2,000-token prompt (8 chunks). Small next to a 7–30 s reply.
- **It does not make the model smarter.** A longer prompt is more for a 1.5B model to get confused by.
  In the verification run it still called Die Linke "(Green Party)" with the right page in front of it.
- **It does not speed up writing.** Decode speed (≈ 19 tokens/s for this model) is unchanged, and each
  new token gets slightly slower as the context grows.
- **There is still a ceiling.** The KV cache and each chunk's table still grow with the prompt. 8,000
  tokens was fine; beyond about 10,000 is untested. The free memory also depends on what Windows' display
  takes on the same card.
- **Only the `transformers` backend.** Other backends will need their own equivalent (llama.cpp has one
  built in, see below).
- **Untested with LoRA adapters** (`training/adapters/…`). It should work, because adapters wrap the same
  forward pass, but no adapter was loaded during verification.
- **The budget is still in characters.** With this much headroom that's harmless, but it's still a
  proxy.

### 4.7 Where to go from here

Roughly in order of value for this machine:

1. **Raise `max_prompt_chars`** to give the model more page text and history. Something like 12,000
   characters (≈ 3,000–4,800 tokens) is well inside the measured range. Re-check with a long web answer
   before going higher. Keep in mind the con above: more text isn't always better for a 1.5B model.
2. **Budget in tokens, not characters.** Count with the model's tokenizer in `_fit`
   (`localagent/agent/core.py`) and set `max_prompt_tokens` in `agent.yaml`. Number-heavy pages can then
   never surprise the budget again. Add a `diagnose.py --context` probe that finds this card's ceiling
   automatically (the measurement script used for the table above does that in ~1 minute).
3. **Reuse the system prompt's cache between messages.** The system prompt (tool list, ≈ 900 tokens) is the
   same every turn, so its KV cache could be kept and only the new part read. That makes replies faster.
   Blocker: the system prompt contains the current time to the minute. That line would need to move to the
   end of the prompt, or be rounded, for the cached part to stay identical.
4. **Read long pages in passes ("map, then reduce").** With memory no longer the limit, the agent could
   split a fetched page into pieces, ask the model "what in this piece answers the question?", and then
   answer from those notes. Better than word matching for pages whose wording differs from the question;
   costs one model call per piece (seconds each).
5. **A llama.cpp backend** (already listed in `agent.yaml` as "coming later"). It does chunked prefill
   natively (`n_batch`), can quantize the KV cache, and can split layers between GPU and RAM (`-ngl`).
   That is the realistic route to a **3B model** at usable speed on this card. Today the 3B in 4-bit runs
   at 1.5 tokens/s under transformers (`scripts/benchmark_results.csv`), and chunked prefill doesn't fix
   that because it's a decode-speed problem.
6. **KV cache in RAM** (transformers `OffloadedCache`). This is the "load it into RAM" idea. For the 1.5B
   model it isn't worth it: the cache is ≈ 28 KB per token, 224 MB at 8,000 tokens. It becomes useful with
   a bigger model or prompts in the tens of thousands of tokens, at a speed cost (every layer copies its
   cache across PCIe for every token).
7. **Quantized KV cache** (`QuantizedCache`, 4- or 8-bit). Halves or quarters the cache. Same story: the
   cache isn't the bottleneck at this size yet.
8. **Tune `PREFILL_CHUNK`.** 256 was picked, not measured. 512 should be slightly faster and still small;
   128 would be leaner if the free memory ever shrinks.

---

## 5. Configuration changes

**`my-agent/installables.yaml`** (not in git) — web tool:

```yaml
fixed_args: {max_results: 5, max_length: 50000}  # max_length: fetch whole pages (the server's default is 8000)
max_result_chars: 60000                          # was 4000 (default): excerpting now does the shortening
follow: {search: fetch_content}                  # after a search, the agent opens the first result itself
```

The same lines were added (commented) to `agent_template/installables.yaml`, and documented in
`docs/guide/05b-give-it-abilities.md` (settings table, the "small models" notes).

**`my-agent/agent.yaml`** (not in git): `max_new_tokens: 256 → 400`. Answers with lists and links were
being cut mid-sentence ("…wiki/202", a seat list missing SPD). The template still says 256.

---

## 6. How it was verified

- **Unit tests:** 177 → 191, all passing (`python -m pytest -q`).
- **Real web tool, scripted model:** the model would receive electiomap.com's "Die Linke 25.65%, CDU
  18.77%, AfD 16.26%, Grüne 14.29%, SPD 12.11%" in a 5,943-character prompt.
- **Real everything** (Qwen2.5-1.5B fp16 on the GTX 1050, DuckDuckGo, throwaway session):

  | Question | Time | Result |
  |---|---|---|
  | "Search the web and let me know how Berlin's latest election went" | 33 s | searched, opened electiomap.com, gave the correct percentages and seats; no out-of-memory |
  | "How were the percentages of votes per party?" | 7 s | correct percentages again (the page stays in context for 3 messages) |
  | "Show me the source" | 20 s | named ElectioMap but without the URL, and opened with "I don't have direct access…" |

---

## 7. What is still not right

- **Not searching unless told to.** "let me know how berlin latest elections went" (no word "search")
  got "I don't have access to recent events" on a clean history. Next step: tune the tool instructions in
  `localagent/agent/prompt.py` and add such questions to `scripts/tool_eval.py`.
- **Small-model slips on correct data:** "Die Linke (Green Party)".
- **Source answers** should include the URL. The URL is in the context; the model doesn't always use it.
