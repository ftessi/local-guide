import pytest

from localagent.connect.owner.terminal import _is_command


@pytest.mark.parametrize("text", ["reset", "/reset", "Reset.", "reset once", "RESET!"])
def test_reset_variants(text):
    assert _is_command(text, "reset")


@pytest.mark.parametrize("text", ["please reset my calendar reminders", "resetting", "", "what is reset"])
def test_normal_messages_are_not_commands(text):
    assert not _is_command(text, "reset")
