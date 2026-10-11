import pytest

from localagent.training.dataset import InvalidExample, validate_example


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
