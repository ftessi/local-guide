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
