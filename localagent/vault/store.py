"""Passive, labeled storage over an agent folder. Applies the filters it is given; decides nothing."""
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

KINDS = ("knowledge", "memory", "work", "training")
PEER_PREFIX = "peer:"
_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class Item:
    kind: str
    compartment: str
    id: str
    content: object  # str for knowledge; dict for memory, work and training


def compartment_to_folder(compartment: str) -> str:
    return compartment.replace(":", "__", 1)


def folder_to_compartment(name: str) -> str:
    return name.replace("__", ":", 1)


class Vault:
    def __init__(self, agent_dir: Path, compartments: list[str]):
        self.root = Path(agent_dir)
        self.compartments = list(compartments)
        self._warned: set[str] = set()

    # ── reading ──────────────────────────────────────────────────────────────

    def read(self, kind: str, compartments: list[str]) -> list[Item]:
        if kind not in KINDS:
            raise ValueError(f"Unknown kind '{kind}'")
        wanted = list(dict.fromkeys(compartments))
        return getattr(self, f"_read_{kind}")(wanted)

    def list_compartments(self, kind: str) -> list[str]:
        """Labels that can exist for `kind`: configured compartments, plus peer:* for memory."""
        found = list(self.compartments)
        memory = self.root / "memory"
        if kind == "memory" and memory.is_dir():
            for d in sorted(memory.iterdir()):
                c = folder_to_compartment(d.name)
                if d.is_dir() and c.startswith(PEER_PREFIX):
                    found.append(c)
        return found

    def _warn(self, message: str) -> None:
        if message not in self._warned:
            self._warned.add(message)
            log.warning(message)

    def _warn_unknown_folders(self, base: Path) -> None:
        if base.is_dir():
            for d in base.iterdir():
                if d.is_dir() and d.name not in self.compartments and d.name != "adapters":
                    self._warn(f"{base.name}/{d.name} is not a compartment in agent.yaml; ignoring it")

    def _jsonl(self, path: Path):
        if not path.is_file():
            return
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                self._warn(f"Skipping corrupt line {path}:{n}")
                continue
            if isinstance(record, dict):
                yield n, record

    def _read_knowledge(self, wanted: list[str]) -> list[Item]:
        base = self.root / "knowledge"
        self._warn_unknown_folders(base)
        items = []
        for c in self.compartments:
            folder = base / c
            if c not in wanted or not folder.is_dir():
                continue
            for f in sorted(folder.glob("*.md")) + sorted(folder.glob("*.txt")):
                text = f.read_text(encoding="utf-8").strip()
                if text:
                    items.append(Item("knowledge", c, f"{c}/{f.name}", text))
        return items

    def _read_memory(self, wanted: list[str]) -> list[Item]:
        items = []
        for c in wanted:
            if c not in self.compartments and not c.startswith(PEER_PREFIX):
                continue
            folder = self.root / "memory" / compartment_to_folder(c)
            for f in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
                for n, record in self._jsonl(f):
                    items.append(Item("memory", c, f"{f.name}#{n}", record))
        return items

    def _read_work(self, wanted: list[str]) -> list[Item]:
        folder = self.root / "work"
        items = []
        for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            meta, body = self._front_matter(f)
            c = str(meta.get("compartment", "private"))
            if c not in self.compartments:
                self._warn(f"work/{f.name} has unknown compartment '{c}'; ignoring it")
                continue
            if c in wanted:
                items.append(Item("work", c, f.name, {
                    "title": str(meta.get("title", f.stem)),
                    "status": str(meta.get("status", "active")),
                    "meta": meta,
                    "body": body.strip(),
                }))
        return items

    def _front_matter(self, path: Path) -> tuple[dict, str]:
        text = path.read_text(encoding="utf-8")
        match = _FRONT_MATTER.match(text)
        if not match:
            return {}, text
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            meta = None
        if not isinstance(meta, dict):
            self._warn(f"work/{path.name} has an invalid header; treating it as private")
            return {}, match.group(2)
        return meta, match.group(2)

    def _read_training(self, wanted: list[str]) -> list[Item]:
        self._warn_unknown_folders(self.root / "training")
        items = []
        for c in self.compartments:
            if c in wanted:
                f = self.root / "training" / c / "examples.jsonl"
                items += [Item("training", c, f"{c}#{n}", r) for n, r in self._jsonl(f)]
        return items

    # ── writing ──────────────────────────────────────────────────────────────

    def _append_jsonl(self, path: Path, records: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def append_memory(self, compartment: str, record: dict) -> None:
        if compartment not in self.compartments and not compartment.startswith(PEER_PREFIX):
            raise ValueError(f"Unknown memory compartment '{compartment}'")
        now = datetime.now()
        path = self.root / "memory" / compartment_to_folder(compartment) / f"{now:%Y-%m-%d}.jsonl"
        self._append_jsonl(path, [{"ts": now.isoformat(timespec="seconds"), **record}])

    def write_training_examples(self, compartment: str, examples: list[dict]) -> None:
        if compartment not in self.compartments:
            raise ValueError(f"Training examples must go to a configured compartment, not '{compartment}'")
        self._append_jsonl(self.root / "training" / compartment / "examples.jsonl", list(examples))

    def read_sources(self, compartment: str) -> list[tuple[str, object]]:
        """training/<c>/sources/*.yaml, parsed. Train-only: nothing ever reads these into a prompt."""
        if compartment not in self.compartments:
            raise ValueError(f"Unknown compartment '{compartment}'")
        folder = self.root / "training" / compartment / "sources"
        found = []
        for f in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
            try:
                found.append((f.name, yaml.safe_load(f.read_text(encoding="utf-8"))))
            except yaml.YAMLError as e:
                raise ValueError(f"training/{compartment}/sources/{f.name} is not valid YAML: {e}") from e
        return found

    def replace_training_examples(self, compartment: str, examples: list[dict]) -> None:
        """Generated examples replace the old ones: appending would train on stale copies of changed sources."""
        if compartment not in self.compartments:
            raise ValueError(f"Training examples must go to a configured compartment, not '{compartment}'")
        path = self.root / "training" / compartment / "examples.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in examples), encoding="utf-8")
        tmp.replace(path)
