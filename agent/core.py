import asyncio
import json
import re
import concurrent.futures
from agent.llm import LLMEngine
from agent.session import SessionContext

_CAL_RE = re.compile(r'<cal>(.*?)</cal>', re.DOTALL)


def _parse_calendar_actions(text: str):
    actions = []
    for match in _CAL_RE.finditer(text):
        try:
            payload = json.loads(match.group(1).strip())
            action = payload.pop("action", None)
            if action:
                actions.append((action, payload))
        except json.JSONDecodeError:
            pass
    return actions


def _strip_action_tags(text: str) -> str:
    return _CAL_RE.sub("", text)


class Agent:
    def __init__(self, llm: LLMEngine, session: SessionContext):
        self.llm = llm
        self.session = session
        self._history: list[dict] = []

    def chat(self, user_message: str) -> str:
        self._history.append({"role": "user", "content": user_message})
        messages = [{"role": "system", "content": self.session.build_system_prompt(scope=None)}] + self._history
        reply = self.llm.generate(messages)
        self._history.append({"role": "assistant", "content": reply})
        return reply

    def chat_stream(self, user_message: str):
        """Streams the reply chunk by chunk. Accumulates full reply into history."""
        self._history.append({"role": "user", "content": user_message})
        messages = [{"role": "system", "content": self.session.build_system_prompt(scope=None)}] + self._history
        full_reply = []
        for chunk in self.llm.generate_stream(messages):
            full_reply.append(chunk)
            yield chunk
        self._history.append({"role": "assistant", "content": "".join(full_reply)})

    def reset(self):
        self._history = []

    async def chat_stream_async(self, user_message: str, calendar=None):
        """Async generator: streams reply chunks, executes calendar actions after completion."""
        self._history.append({"role": "user", "content": user_message})
        messages = [
            {"role": "system", "content": self.session.build_system_prompt(scope=None)}
        ] + self._history

        loop = asyncio.get_event_loop()

        def _collect():
            return list(self.llm.generate_stream(messages))

        with concurrent.futures.ThreadPoolExecutor() as pool:
            chunks = await loop.run_in_executor(pool, _collect)

        raw_text = "".join(chunks)
        clean_text = _strip_action_tags(raw_text).strip()

        # Yield the full clean text — tags span multiple chunks so we must strip after assembly
        yield clean_text

        if calendar:
            for action, payload in _parse_calendar_actions(raw_text):
                if action == "create" and "title" in payload and "remind_at" in payload:
                    calendar.create(payload["title"], payload["remind_at"])
                elif action == "delete" and "id" in payload:
                    calendar.delete(int(payload["id"]))

        self._history.append({"role": "assistant", "content": clean_text})
