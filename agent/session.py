from pathlib import Path
from datetime import datetime


BASE_PROMPT = """You are a helpful local AI assistant.

You can manage the user's calendar. When the user asks you to set a reminder or schedule something, you MUST include one or more calendar tags at the very END of your reply. Use this exact format for each action:

<cal>{{"action":"create","title":"<title>","remind_at":"<ISO datetime e.g. 2026-10-07T18:00:00>"}}</cal>
<cal>{{"action":"delete","id":<integer>}}</cal>

Rules:
- Always place <cal> tags AFTER your natural language response, never inside it
- Use one <cal> tag per action — if the user asks for multiple reminders, include multiple tags
- "remind_at" must be a full ISO 8601 datetime string
- For listing reminders, just respond naturally without a tag

Today's date and time is {datetime_now}. Use this to interpret relative times like "tomorrow at 6pm" or "in 10 minutes"."""


class SessionContext:
    def __init__(self, knowledge_dir: str | Path):
        self.knowledge_dir = Path(knowledge_dir)

    def _read_dir(self, subdir: str) -> str:
        path = self.knowledge_dir / subdir
        if not path.exists():
            return ""
        files = sorted(path.glob("*.md")) + sorted(path.glob("*.txt"))
        parts = [f.read_text(encoding="utf-8").strip() for f in files]
        return "\n\n".join(p for p in parts if p)

    def build_system_prompt(self, scope: list[str] | None) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        sections = [BASE_PROMPT.format(datetime_now=now)]

        if scope is None:
            for subdir in ("private", "public"):
                content = self._read_dir(subdir)
                if content:
                    sections.append(content)
        else:
            for domain in scope:
                content = self._read_dir(domain)
                if content:
                    sections.append(content)

        return "\n\n".join(sections)
