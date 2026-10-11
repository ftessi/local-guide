import pytest

from localagent.training.dataset import InvalidExample, make_example, validate_example


def test_make_example():
    ex = make_example([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}],
                      source="memory:x#1")
    assert ex["source"] == "memory:x#1" and "added" in ex and validate_example(ex) == ex


@pytest.mark.parametrize("ex", [
    {},
    {"messages": []},
    {"messages": [{"role": "user", "content": "a"}]},
    {"messages": [{"role": "robot", "content": "a"}, {"role": "assistant", "content": "b"}]},
    {"messages": [{"role": "user", "content": 1}, {"role": "assistant", "content": "b"}]},
])
def test_invalid(ex):
    with pytest.raises(InvalidExample):
        validate_example(ex)
