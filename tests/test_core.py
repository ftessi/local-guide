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
    assert mock_llm.generate.call_count == 2
    second_call_messages = mock_llm.generate.call_args_list[1][0][0]
    roles = [m["role"] for m in second_call_messages]
    assert roles.count("user") == 2
    assert roles.count("assistant") == 1


def test_reset_clears_history(mock_llm, mock_session):
    agent = Agent(llm=mock_llm, session=mock_session)
    agent.chat("Something")
    agent.reset()
    agent.chat("After reset")
    call_messages = mock_llm.generate.call_args_list[-1][0][0]
    user_messages = [m for m in call_messages if m["role"] == "user"]
    assert len(user_messages) == 1
