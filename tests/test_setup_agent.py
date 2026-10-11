import pytest
from dotenv import dotenv_values

from localagent.config import load_config
from localagent.setup_agent import create_agent, migrate_legacy


def test_create_agent(tmp_path):
    d = tmp_path / "bob"
    agent_id = create_agent(d, model={"id": "Qwen/Qwen2.5-1.5B-Instruct", "quantization": "fp16"})
    cfg = load_config(d)
    assert cfg.name == "bob"
    assert (cfg.model.id, cfg.model.quantization) == ("Qwen/Qwen2.5-1.5B-Instruct", "fp16")
    env = dotenv_values(d / ".env")
    assert len(env["AGENT_SECRET"]) == 64
    assert env["VAPID_PRIVATE_KEY"] == "vapid_private.pem" and (d / "vapid_private.pem").is_file()
    assert len(env["VAPID_PUBLIC_KEY"]) == 87
    assert (d / "identity/agent.pub").read_text().strip() == agent_id
    assert (d / "knowledge/private").is_dir() and (d / "knowledge/shared").is_dir()


def test_create_agent_refuses_existing(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "file").write_text("keep me")
    with pytest.raises(FileExistsError):
        create_agent(tmp_path / "x")
    assert (tmp_path / "x" / "file").read_text() == "keep me"


def _legacy_repo(root):
    (root / "knowledge/private").mkdir(parents=True)
    (root / "knowledge/public").mkdir(parents=True)
    (root / "knowledge/private/about.md").write_text("ME")
    (root / "knowledge/public/greeting.md").write_text("HI")
    (root / "calendar.db").write_bytes(b"db")
    (root / "push_subscriptions.json").write_text("[]")
    (root / ".vapid_private.pem").write_text("PEM")
    (root / ".env").write_text(
        f"HF_HOME=x\nAGENT_SECRET=legacysecret\nVAPID_PRIVATE_KEY={root / '.vapid_private.pem'}\n"
        "VAPID_PUBLIC_KEY=legacypub\nVAPID_CLAIMS_EMAIL=me@x.com\n"
        "MODEL_ID=Qwen/Qwen2.5-1.5B-Instruct\nUSE_4BIT=0\n"
    )
    return root


def test_migrate(tmp_path):
    root = _legacy_repo(tmp_path / "repo")
    d = root / "my-agent"
    actions = migrate_legacy(root, d)
    assert (d / "knowledge/private/about.md").read_text() == "ME"
    assert (d / "knowledge/shared/greeting.md").read_text() == "HI"
    assert (d / "data/calendar/calendar.db").read_bytes() == b"db"
    assert (d / "data/push_subscriptions.json").exists()
    assert (d / "vapid_private.pem").read_text() == "PEM"
    env = dotenv_values(d / ".env")
    assert env["AGENT_SECRET"] == "legacysecret" and env["VAPID_PUBLIC_KEY"] == "legacypub"
    assert env["VAPID_PRIVATE_KEY"] == "vapid_private.pem"
    cfg = load_config(d)
    assert (cfg.model.id, cfg.model.quantization) == ("Qwen/Qwen2.5-1.5B-Instruct", "fp16")
    assert not (root / "knowledge").exists() and not (root / "calendar.db").exists()
    assert (root / ".env").exists()  # left for the owner to delete
    assert any(a.startswith("NOTE") for a in actions)


def test_migrate_dry_run_changes_nothing(tmp_path):
    root = _legacy_repo(tmp_path / "repo")
    actions = migrate_legacy(root, root / "my-agent", dry_run=True)
    assert all(a.startswith(("[dry-run]", "SKIP", "NOTE")) for a in actions)
    assert not (root / "my-agent").exists() and (root / "calendar.db").exists()


def test_migrate_never_overwrites(tmp_path):
    root = _legacy_repo(tmp_path / "repo")
    d = root / "my-agent"
    create_agent(d)
    (d / "knowledge/private/about.md").write_text("NEWER")
    actions = migrate_legacy(root, d)
    assert (d / "knowledge/private/about.md").read_text() == "NEWER"
    assert (root / "knowledge/private/about.md").exists()
    assert any(a.startswith("SKIP") and "about.md" in a for a in actions)
    assert any(a.startswith("SKIP") and "AGENT_SECRET" in a for a in actions)
