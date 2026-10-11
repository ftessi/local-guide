import pytest

from localagent.vault.store import Vault


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "knowledge/private").mkdir(parents=True)
    (tmp_path / "knowledge/shared").mkdir(parents=True)
    (tmp_path / "knowledge/private/me.md").write_text("I live in Madrid.")
    (tmp_path / "knowledge/shared/style.txt").write_text("Be brief.")
    (tmp_path / "knowledge/shared/empty.md").write_text("   ")
    return Vault(tmp_path, ["private", "shared"])


def test_knowledge_labeled_by_folder(vault):
    items = vault.read("knowledge", ["private", "shared"])
    assert [(i.compartment, i.content) for i in items] == [("private", "I live in Madrid."), ("shared", "Be brief.")]


def test_knowledge_filtered(vault):
    assert [i.content for i in vault.read("knowledge", ["shared"])] == ["Be brief."]


def test_unknown_folder_ignored(vault, caplog):
    (vault.root / "knowledge/family").mkdir()
    (vault.root / "knowledge/family/x.md").write_text("secret")
    assert all(i.content != "secret" for i in vault.read("knowledge", ["family", "private"]))
    assert "family" in caplog.text


def test_memory_roundtrip_and_peer(vault):
    vault.append_memory("private", {"user": "hi", "assistant": "hello"})
    vault.append_memory("peer:abc_-1", {"user": "q", "assistant": "a"})
    assert (vault.root / "memory/peer__abc_-1").is_dir()
    priv = vault.read("memory", ["private"])
    assert priv[0].content["user"] == "hi" and "ts" in priv[0].content
    assert vault.read("memory", ["peer:abc_-1"])[0].compartment == "peer:abc_-1"
    assert "peer:abc_-1" in vault.list_compartments("memory")
    assert "peer:abc_-1" not in vault.list_compartments("knowledge")


def test_memory_unknown_compartment_rejected(vault):
    with pytest.raises(ValueError):
        vault.append_memory("family", {"user": "x"})


def test_corrupt_memory_line_skipped(vault, caplog):
    vault.append_memory("private", {"user": "ok", "assistant": "fine"})
    f = next((vault.root / "memory/private").glob("*.jsonl"))
    with f.open("a") as fh:
        fh.write('{"user": "half-writ')
    items = vault.read("memory", ["private"])
    assert len(items) == 1 and "corrupt" in caplog.text


def test_work_front_matter(vault):
    (vault.root / "work").mkdir()
    (vault.root / "work/trip.md").write_text("---\ncompartment: shared\nstatus: active\ntitle: Trip\n---\nBook flights\n")
    (vault.root / "work/plain.md").write_text("No header here")
    (vault.root / "work/bad.md").write_text("---\ncompartment: family\n---\nx\n")
    shared = vault.read("work", ["shared"])
    assert [(w.content["title"], w.content["body"]) for w in shared] == [("Trip", "Book flights")]
    private = vault.read("work", ["private"])
    assert [w.content["title"] for w in private] == ["plain"]


def test_training_roundtrip(vault):
    ex = {"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]}
    vault.replace_training_examples("shared", [ex])
    items = vault.read("training", ["shared"])
    assert items[0].content == ex and items[0].compartment == "shared"
    assert vault.read("training", ["private"]) == []
    with pytest.raises(ValueError):
        vault.replace_training_examples("peer:x", [ex])
