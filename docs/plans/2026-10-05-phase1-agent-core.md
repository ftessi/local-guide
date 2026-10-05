# Phase 1 — Agent Core Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working local AI agent with HuggingFace inference, knowledge store, session context, and a CLI interface — owner-only access, no protocol layer yet.

**Architecture:** Four components in sequence: `llm.py` wraps raw inference and cleans output, `session.py` reads the knowledge store and scopes it into a system prompt, `core.py` ties LLM + session into a stateful agent with conversation history, `main.py` is the CLI REPL.

**Tech Stack:** Python 3.10+, HuggingFace Transformers 5.x, bitsandbytes (4-bit quantization), pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `agent/__init__.py` | Create | Makes `agent/` a Python package |
| `agent/llm.py` | Create | Loads model, runs inference, returns clean assistant reply |
| `agent/session.py` | Create | Reads knowledge store files, builds scoped system prompt |
| `agent/core.py` | Create | Stateful agent: holds LLM + session + conversation history |
| `main.py` | Create | CLI REPL — loads agent, loops on user input |
| `knowledge/private/about.md` | Create | Sample private knowledge entry |
| `knowledge/public/greeting.md` | Create | Sample public knowledge entry |
| `tests/__init__.py` | Create | Makes `tests/` a Python package |
| `tests/test_session.py` | Create | Unit tests for SessionContext |
| `tests/test_core.py` | Create | Unit tests for Agent (mocked LLM) |
| `tests/test_llm_integration.py` | Create | Integration test loading the real model |

---

## Chunk 1: Scaffolding + LLM Wrapper

### Task 1: Install pytest and create package structure

**Files:**
- Create: `agent/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Install pytest**

```bash
pip install pytest
```

- [ ] **Step 2: Create package files**

Create `agent/__init__.py` (empty file).
Create `tests/__init__.py` (empty file).

- [ ] **Step 3: Verify pytest works**

```bash
pytest --collect-only
```
Expected: `no tests ran` — no errors.

---

### Task 2: LLM wrapper (`agent/llm.py`)

**Files:**
- Create: `agent/llm.py`
- Create: `tests/test_llm_integration.py`

The wrapper must:
- Load the model once at init (expensive — do not reload per call)
- Accept a list of `{"role": ..., "content": ...}` messages
- Return only the assistant's reply text — no role labels, no repeated prompt

- [ ] **Step 1: Write the integration test**

Create `tests/test_llm_integration.py`:
```python
import pytest
from agent.llm import LLMEngine

# This test loads the real model — runs once, takes ~10s
@pytest.fixture(scope="module")
def llm():
    return LLMEngine(model_id="Qwen/Qwen2.5-3B-Instruct", use_4bit=True)

def test_generate_returns_string(llm):
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Reply with exactly the word: HELLO"}
    ]
    result = llm.generate(messages)
    assert isinstance(result, str)
    assert len(result) > 0

def test_generate_no_role_labels(llm):
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Say hi."}
    ]
    result = llm.generate(messages)
    # Output must not contain chat template role labels
    assert "system" not in result.lower().split()
    assert "user" not in result.lower().split()
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/test_llm_integration.py -v
```
Expected: `ImportError` — `agent/llm.py` does not exist yet.

- [ ] **Step 3: Implement `agent/llm.py`**

```python
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
import torch


class LLMEngine:
    def __init__(self, model_id: str, use_4bit: bool = True):
        quant_config = None
        if use_4bit:
            quant_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
            )

        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id,
            quantization_config=quant_config,
            torch_dtype=None if use_4bit else torch.float16,
            device_map="auto",
        )
        self._input_len = 0

    def generate(self, messages: list[dict], max_new_tokens: int = 512) -> str:
        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)
        self._input_len = inputs["input_ids"].shape[1]

        output_ids = self.model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            pad_token_id=self.tokenizer.eos_token_id,
        )
        # Slice off the input tokens — return only the new tokens
        new_tokens = output_ids[0][self._input_len:]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
```

- [ ] **Step 4: Run integration test**

```bash
pytest tests/test_llm_integration.py -v
```
Expected: both tests PASS. Model loads once (module scope fixture).

---

## Chunk 2: Session Context + Knowledge Store

### Task 3: Knowledge store files

**Files:**
- Create: `knowledge/private/about.md`
- Create: `knowledge/public/greeting.md`

- [ ] **Step 1: Create sample knowledge files**

Create `knowledge/private/about.md`:
```markdown
This agent is owned and operated by its creator.
It runs locally and does not send data externally.
```

Create `knowledge/public/greeting.md`:
```markdown
When greeting users, be concise and friendly.
```

---

### Task 4: Session context (`agent/session.py`)

**Files:**
- Create: `agent/session.py`
- Create: `tests/test_session.py`

`SessionContext` reads all `.md`/`.txt` files from the knowledge directories and assembles a system prompt. In Phase 1 (owner session), all knowledge is included. Scope filtering is wired in now so Phase 2 can use it without refactoring.

- [ ] **Step 1: Write the tests**

Create `tests/test_session.py`:
```python
import pytest
import tempfile
import os
from pathlib import Path
from agent.session import SessionContext


@pytest.fixture
def tmp_knowledge(tmp_path):
    private = tmp_path / "private"
    public = tmp_path / "public"
    private.mkdir()
    public.mkdir()
    (private / "secret.md").write_text("Secret info.")
    (public / "greeting.md").write_text("Be friendly.")
    return tmp_path


def test_owner_session_includes_all_knowledge(tmp_knowledge):
    ctx = SessionContext(knowledge_dir=tmp_knowledge)
    prompt = ctx.build_system_prompt(scope=None)  # None = owner, full access
    assert "Secret info." in prompt
    assert "Be friendly." in prompt


def test_scoped_session_excludes_private(tmp_knowledge):
    ctx = SessionContext(knowledge_dir=tmp_knowledge)
    prompt = ctx.build_system_prompt(scope=["public"])
    assert "Be friendly." in prompt
    assert "Secret info." not in prompt


def test_empty_scope_returns_base_prompt(tmp_knowledge):
    ctx = SessionContext(knowledge_dir=tmp_knowledge)
    prompt = ctx.build_system_prompt(scope=[])
    assert isinstance(prompt, str)
    assert len(prompt) > 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_session.py -v
```
Expected: `ImportError`.

- [ ] **Step 3: Implement `agent/session.py`**

```python
from pathlib import Path


BASE_PROMPT = "You are a helpful local AI assistant."


class SessionContext:
    def __init__(self, knowledge_dir: str | Path):
        self.knowledge_dir = Path(knowledge_dir)

    def _read_dir(self, subdir: str) -> str:
        path = self.knowledge_dir / subdir
        if not path.exists():
            return ""
        parts = []
        for f in sorted(path.glob("*.md")) + sorted(path.glob("*.txt")):
            parts.append(f.read_text(encoding="utf-8").strip())
        return "\n\n".join(parts)

    def build_system_prompt(self, scope: list[str] | None) -> str:
        sections = [BASE_PROMPT]

        if scope is None:
            # Owner session — full access
            private = self._read_dir("private")
            public = self._read_dir("public")
            if private:
                sections.append(private)
            if public:
                sections.append(public)
        else:
            for domain in scope:
                content = self._read_dir(domain)
                if content:
                    sections.append(content)

        return "\n\n".join(sections)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_session.py -v
```
Expected: all 3 tests PASS.

---

## Chunk 3: Agent Core + CLI

### Task 5: Agent core (`agent/core.py`)

**Files:**
- Create: `agent/core.py`
- Create: `tests/test_core.py`

`Agent` maintains conversation history across turns. Each call to `chat()` appends the user message, generates a reply, appends the reply, and returns it.

- [ ] **Step 1: Write the tests**

Create `tests/test_core.py`:
```python
import pytest
from unittest.mock import MagicMock
from agent.core import Agent


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.generate.return_value = "Hello there!"
    return llm


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.build_system_prompt.return_value = "You are a helpful assistant."
    return session


def test_chat_returns_string(mock_llm, mock_session):
    agent = Agent(llm=mock_llm, session=mock_session)
    result = agent.chat("Hi")
    assert isinstance(result, str)
    assert result == "Hello there!"


def test_chat_builds_history(mock_llm, mock_session):
    agent = Agent(llm=mock_llm, session=mock_session)
    agent.chat("First message")
    agent.chat("Second message")
    # llm.generate called twice
    assert mock_llm.generate.call_count == 2
    # Second call must include prior turn in messages
    second_call_messages = mock_llm.generate.call_args_list[1][0][0]
    roles = [m["role"] for m in second_call_messages]
    assert roles.count("user") == 2
    assert roles.count("assistant") == 1


def test_reset_clears_history(mock_llm, mock_session):
    agent = Agent(llm=mock_llm, session=mock_session)
    agent.chat("Something")
    agent.reset()
    agent.chat("After reset")
    # After reset, only 1 user message in history
    call_messages = mock_llm.generate.call_args_list[-1][0][0]
    user_messages = [m for m in call_messages if m["role"] == "user"]
    assert len(user_messages) == 1
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_core.py -v
```
Expected: `ImportError`.

- [ ] **Step 3: Implement `agent/core.py`**

```python
from agent.llm import LLMEngine
from agent.session import SessionContext


class Agent:
    def __init__(self, llm: LLMEngine, session: SessionContext):
        self.llm = llm
        self.session = session
        self._history: list[dict] = []

    def chat(self, user_message: str) -> str:
        self._history.append({"role": "user", "content": user_message})

        system_prompt = self.session.build_system_prompt(scope=None)
        messages = [{"role": "system", "content": system_prompt}] + self._history

        reply = self.llm.generate(messages)
        self._history.append({"role": "assistant", "content": reply})
        return reply

    def reset(self):
        self._history = []
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_core.py -v
```
Expected: all 3 tests PASS.

---

### Task 6: CLI entry point (`main.py`)

**Files:**
- Modify: `main.py` (currently empty — replace with CLI)

No unit test for the REPL loop itself (it's I/O). Covered by running it manually.

- [ ] **Step 1: Implement `main.py`**

```python
import os
from pathlib import Path
from agent.llm import LLMEngine
from agent.session import SessionContext
from agent.core import Agent

MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"
KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


def main():
    print("Loading model...")
    llm = LLMEngine(model_id=MODEL_ID, use_4bit=True)
    session = SessionContext(knowledge_dir=KNOWLEDGE_DIR)
    agent = Agent(llm=llm, session=session)
    print("Agent ready. Type 'exit' or Ctrl+C to quit. Type 'reset' to clear history.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() == "exit":
            print("Goodbye.")
            break
        if user_input.lower() == "reset":
            agent.reset()
            print("Conversation history cleared.\n")
            continue

        reply = agent.chat(user_input)
        print(f"Agent: {reply}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the full test suite**

```bash
pytest tests/test_session.py tests/test_core.py -v
```
Expected: all tests PASS. (Skip integration test unless you want to wait for model load.)

- [ ] **Step 3: Run the agent**

```bash
set HF_HOME=W:\LocalAgent\models
python main.py
```
Expected: "Loading model..." then "Agent ready." then interactive prompt.

Test a few messages, then `exit`.

---

## Done

After Task 6, Phase 1 is complete:
- Model loads once, serves all queries
- Knowledge store is read from files, scoped at session build time
- Conversation history accumulates across turns
- Owner has full knowledge access; scope parameter is ready for Phase 2

Next: Phase 2 — implement `agent/protocol.py` (handshake, scoped sessions, inter-agent messaging).
