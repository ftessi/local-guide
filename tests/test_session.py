import pytest
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
    prompt = ctx.build_system_prompt(scope=None)
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
