# Local Agent + Zero-Trust Connection Protocol — Design Spec
Date: 2026-10-05

## Overview

A locally-hosted AI agent built on HuggingFace Transformers, with a custom zero-trust inter-agent communication protocol. Agents can connect to each other, share a scoped subset of their knowledge and tools per connection, and communicate freely within that scope — while actively protecting private knowledge from leaking across connection boundaries.

Phase 1: single agent, accessible to the owner only.
Phase 2: multi-agent connections using the custom protocol.

---

## 1. Architecture

Each agent node has four components:

### 1.1 Private Knowledge Store
The agent's full data, tools, and capabilities. Stored locally (files, structured data, or a vector store). Never sent raw over the protocol. Only accessed internally by the Session Context builder.

### 1.2 Session Context
Built at connection time from the Private Knowledge Store, filtered to the agreed scope of the connection. This is the only view the LLM receives when handling inter-agent messages. Injected as part of the system prompt for each inference call.

### 1.3 LLM Engine (HuggingFace)
Wraps model inference. Receives only: the scoped system prompt, the conversation history for this session, and the current message. Has no direct access to the Private Knowledge Store.

**Starting model:** `Qwen/Qwen2.5-3B-Instruct`
- 3B parameters, instruction-tuned
- Tested on GTX 1050 (4GB VRAM) with 4-bit quantization — loads in ~9s, ~2GB download
- Use 4-bit quantization (`bitsandbytes`) if GPU VRAM is under 6GB; float16 requires ~6GB
- Swap candidates: `microsoft/phi-2`, `TinyLlama/TinyLlama-1.1B-Chat-v1.0`

For full installation and setup instructions, see `2026-10-05-model-install-run.md` in this directory.

**Inference config (full precision):**
```python
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

model_id = "Qwen/Qwen2.5-3B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    torch_dtype=torch.float16,
    device_map="auto"
)
```

### 1.4 Protocol Handler
Manages all inter-agent communication. Responsible for:
- Executing the connection handshake
- Validating that every incoming/outgoing message falls within the agreed session scope
- Blocking out-of-scope requests before they reach the LLM

---

## 2. Zero-Trust Connection Protocol (v0.1)

### 2.1 Design Principles
- No agent inherently trusts another
- Every connection has an explicit, declared purpose
- Scope is agreed at handshake time; no scope expansion mid-session
- Two-layer enforcement: Protocol Handler (transport) + System Prompt (model level)

### 2.2 Handshake

**Agent A initiates:**
```json
{
  "protocol_version": "0.1",
  "purpose": "task:<task_name>",
  "agent_id": "<uuid>",
  "offered_scope": ["tool:<name>", "knowledge:<domain>"],
  "requested_scope": ["tool:<name>", "knowledge:<domain>"]
}
```

**Agent B responds:**
```json
{
  "accepted": true,
  "granted_scope": ["tool:<name>", "knowledge:<domain>"],
  "session_token": "<token>",
  "session_expires": "<iso_timestamp>"
}
```

- `offered_scope`: what A is willing to share with B
- `requested_scope`: what A wants access to from B
- `granted_scope`: what B actually allows (may be a subset of requested)
- `session_token`: used to authenticate all subsequent messages in this session

### 2.3 Message Format

Every message after handshake:
```json
{
  "session_token": "<token>",
  "from": "<agent_id>",
  "type": "query | response | tool_call | tool_result",
  "payload": { ... },
  "timestamp": "<iso_timestamp>"
}
```

The Protocol Handler validates `session_token` and checks that `type` + `payload` are within the granted scope before passing to the LLM Engine.

### 2.4 Dual-Layer Enforcement

**Layer 1 — Protocol Handler:**
Structural validation. If a message references a tool or knowledge domain not in the granted scope, it is rejected with an error response before the LLM is invoked.

**Layer 2 — System Prompt Scoping:**
The LLM system prompt is built from the Session Context, which only contains knowledge and tool descriptions within the granted scope. Even if Layer 1 were bypassed, the model has no awareness of out-of-scope private knowledge.

---

## 3. File Layout

```
W:\LocalAgent\
  agent/
    core.py          # agent node — ties all components together
    session.py       # session context builder (filters knowledge store)
    protocol.py      # handshake + message validation + routing
    llm.py           # HuggingFace inference wrapper
  knowledge/
    private/         # full private knowledge store (never exposed directly)
    public/          # knowledge explicitly marked shareable
  models/            # HuggingFace model cache (set HF_HOME to this dir)
  main.py            # entry point — starts agent, accepts owner connections
  requirements.txt
```

---

## 4. Phase Plan

### Phase 1 — Single Agent (current)
- [ ] Set up HuggingFace environment and download starting model
- [ ] Implement `llm.py` — basic inference wrapper
- [ ] Implement `agent/core.py` — agent loop with private knowledge store
- [ ] Implement `agent/session.py` — context builder
- [ ] `main.py` — owner-only access (CLI or simple local interface)
- [ ] Test with 2-3 models to establish baseline

### Phase 2 — Multi-Agent Protocol
- [ ] Implement `agent/protocol.py` — handshake + message handler
- [ ] Define scope vocabulary (tool names, knowledge domain tags)
- [ ] Connect two local agent instances and test scoped sessions
- [ ] Harden dual-layer enforcement
- [ ] Document protocol v0.1 formally

---

## 5. Models to Test

| Model | Params | VRAM (4-bit) | Notes |
|-------|--------|--------------|-------|
| `Qwen/Qwen2.5-3B-Instruct` | 3B | ~2GB | Start here — tested, works on GTX 1050 |
| `TinyLlama/TinyLlama-1.1B-Chat-v1.0` | 1.1B | ~1GB | Fallback if 3B is too slow |
| `microsoft/phi-2` | 2.7B | ~1.5GB | Alternative, test second |

---

## 6. Dependencies

```
transformers>=4.40.0
torch>=2.2.0
accelerate>=0.27.0   # required for device_map="auto"
```

GPU: CUDA-capable GPU recommended; CPU fallback supported via `device_map="auto"`.
