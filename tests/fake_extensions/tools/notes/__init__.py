"""Notes: a tiny in-memory tool used by the core tests (real tools live in the extensions repo)."""
from datetime import datetime

from localagent.agent.tools.base import Action, Tool


class NotesTool(Tool):
    name = "notes"
    actions = {
        "add": Action("Save a note", {"text": "str", "due": "iso-datetime"}, kind="write"),
        "list": Action("List saved notes", {}, kind="read"),
        "delete": Action("Delete a note by its id", {"id": "int"}, kind="write"),
    }
    options = ("max_notes",)

    def setup(self, data_dir, notify):
        self.data_dir, self.notify, self.notes, self._next = data_dir, notify, [], 1

    def run(self, action, args):
        if action == "add":
            self.notes.append({"id": self._next, **args})
            self._next += 1
            return {"id": self._next - 1}
        if action == "list":
            return {"notes": list(self.notes)}
        before = len(self.notes)
        self.notes = [n for n in self.notes if n["id"] != args["id"]]
        return {"deleted": len(self.notes) < before}

    def background(self):
        due = [n for n in self.notes if n["due"] <= datetime.now().isoformat()]
        for note in due:
            self.notify("Note due", note["text"])
        self.notes = [n for n in self.notes if n not in due]


TOOL = NotesTool
