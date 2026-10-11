from pathlib import Path

import pytest

from localagent.runtime.base import AdapterLoadError, Backend
from localagent.runtime.factory import AVAILABLE_BACKENDS, create_backend
from localagent.runtime.transformers_backend import TransformersBackend
from tests.fakes import FakeBackend

MSGS = [{"role": "user", "content": "hi"}]


@pytest.fixture(params=[FakeBackend])
def backend(request):
    b = request.param(replies=["hello there friend", "hello there friend"])
    b.load("fake/model", "4bit")
    return b


def test_satisfies_protocol(backend):
    assert isinstance(backend, Backend)


def test_generate_returns_str(backend):
    assert isinstance(backend.generate(MSGS, 16), str)


def test_stream_yields_str_chunks(backend):
    chunks = list(backend.generate_stream(MSGS, 16))
    assert chunks and all(isinstance(c, str) for c in chunks)


def test_set_adapters_empty_is_base(backend):
    backend.set_adapters([])
    assert backend.info()["adapters"] == []


def test_info_keys(backend):
    assert {"model_id", "backend", "device", "adapters"} <= set(backend.info())


def test_adapter_failure_leaves_none_active():
    b = FakeBackend(fail_adapters=True)
    with pytest.raises(AdapterLoadError):
        b.set_adapters([Path("x")])
    assert b.info()["adapters"] == []


def test_transformers_backend_satisfies_protocol_without_loading():
    assert isinstance(TransformersBackend(), Backend)


def test_factory():
    assert "transformers" in AVAILABLE_BACKENDS
    assert isinstance(create_backend("transformers"), TransformersBackend)
    with pytest.raises(NotImplementedError, match="planned"):
        create_backend("mlx")
    with pytest.raises(ValueError, match="Unknown backend"):
        create_backend("nope")


def test_long_prompts_are_read_in_chunks():
    """Reading a prompt in one go needs GPU memory that grows with its length squared (a 2500-token prompt ran
    a 4 GB card out of memory); in chunks it stays small. The last token is left for generate()."""
    torch = pytest.importorskip("torch")
    seen = []

    class FakeModel:
        def __call__(self, input_ids, past_key_values, use_cache, logits_to_keep):
            seen.append(input_ids.shape[1])

    backend = TransformersBackend()
    backend.model = FakeModel()
    cache = backend._prefill(torch.zeros((1, 600), dtype=torch.long), chunk=256)
    assert seen == [256, 256, 87] and cache is not None
    seen.clear()
    assert backend._prefill(torch.zeros((1, 100), dtype=torch.long), chunk=256) is None and seen == []
