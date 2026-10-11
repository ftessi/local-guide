import ast
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "localagent"
ALLOWED = {
    "runtime": (),
    "vault": (),
    "protocol": ("localagent.vault",),
    "agent": ("localagent.protocol.session", "localagent.protocol.prompts", "localagent.runtime.base"),
    "training": ("localagent.protocol", "localagent.runtime"),
    "connect": ("localagent.protocol", "localagent.agent", "localagent.runtime"),
}


def _imports(path: Path, module: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                yield ".".join(base + ([node.module] if node.module else []))
            else:
                yield node.module


def _violations():
    found = []
    for layer, allowed in ALLOWED.items():
        for path in (PKG / layer).rglob("*.py"):
            rel = path.relative_to(PKG.parent).with_suffix("")
            module = ".".join(rel.parts).removesuffix(".__init__")
            for imp in _imports(path, module):
                if not imp or not imp.startswith("localagent"):
                    continue
                if imp == f"localagent.{layer}" or imp.startswith(f"localagent.{layer}."):
                    continue
                if any(imp == a or imp.startswith(a + ".") for a in allowed):
                    continue
                found.append(f"{module} imports {imp}")
    return found


def test_layer_import_rules():
    assert _violations() == []


def test_checker_catches_violations(tmp_path, monkeypatch):
    bad = PKG / "agent" / "_layer_probe.py"
    bad.write_text("from localagent.vault.store import Vault\n", encoding="utf-8")
    try:
        assert "localagent.agent._layer_probe imports localagent.vault.store" in _violations()
    finally:
        bad.unlink()
