import json
import os
import sys
from pathlib import Path

import pytest

from localagent.runtime.base import AdapterLoadError, Backend, TURN_START_TOKENS
from localagent.runtime.llamacpp_backend import LlamaCppBackend, context_size, pick_device, pick_gguf_files
from tests.fakes import FAKE_EXTENSIONS

FAKE_SERVER = [sys.executable, str(FAKE_EXTENSIONS / "fake_llama_server.py")]
FAKE_CONVERTER = [sys.executable, str(FAKE_EXTENSIONS / "fake_lora_converter.py")]
MSGS = [{"role": "user", "content": "hi"}]


@pytest.fixture
def gguf(tmp_path):
    path = tmp_path / "model-q4_k_m.gguf"
    path.write_bytes(b"GGUF")
    return path


@pytest.fixture
def backend(gguf):
    b = LlamaCppBackend(gguf=str(gguf), server=FAKE_SERVER, converter=FAKE_CONVERTER)
    b.load("fake/model", "q4_k_m")
    yield b
    b.close()


def adapter(tmp_path, name: str) -> Path:
    """An adapter folder as training writes it (only the weights file matters to the converter)."""
    path = tmp_path / "adapters" / name
    path.mkdir(parents=True)
    (path / "adapter_model.safetensors").write_bytes(b"weights")
    return path


def echo(backend) -> dict:
    return json.loads(backend.generate([{"role": "user", "content": "ECHO"}], 8))


def conversions(path: Path) -> int:
    log = path / "conversions.log"
    return len(log.read_text().splitlines()) if log.exists() else 0


def test_picks_the_discrete_gpu_over_the_integrated_one():
    out = ("Available devices:\n"
           "  Vulkan0: Intel(R) HD Graphics 630 (12230 MiB, 11462 MiB free)\n"
           "  Vulkan1: NVIDIA GeForce GTX 1050 (4235 MiB, 3631 MiB free)\n")
    assert pick_device(out) == "Vulkan1"


def test_picks_apple_and_cuda_devices():
    assert pick_device("Available devices:\n  MTL0: Apple M2 (16384 MiB, 16000 MiB free)\n") == "MTL0"
    assert pick_device("Available devices:\n  CUDA0: NVIDIA GeForce RTX 3060 (12288 MiB, 11000 MiB free)\n") == "CUDA0"


def test_no_gpu_or_only_integrated_means_cpu():
    assert pick_device("Available devices:\n") == "none"
    assert pick_device("Available devices:\n  Vulkan0: Intel(R) UHD Graphics 620 (8000 MiB, 7000 MiB free)\n") == "none"


def test_gguf_file_for_a_quantization():
    files = ["README.md", "qwen2.5-3b-instruct-q4_0.gguf", "qwen2.5-3b-instruct-q4_k_m.gguf",
             "qwen2.5-3b-instruct-q8_0.gguf"]
    assert pick_gguf_files(files, "q4_k_m") == ["qwen2.5-3b-instruct-q4_k_m.gguf"]
    assert pick_gguf_files(["Qwen2.5-3B-Instruct-Q4_K_M.gguf"], "q4_k_m") == ["Qwen2.5-3B-Instruct-Q4_K_M.gguf"]


def test_gguf_split_into_parts_returns_all_parts_first_part_first():
    files = ["qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf", "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf",
             "qwen2.5-7b-instruct-q8_0-00001-of-00003.gguf"]
    assert pick_gguf_files(files, "q4_k_m") == ["qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf",
                                                "qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf"]


def test_missing_quantization_lists_the_ones_there_are():
    with pytest.raises(ValueError, match=r"q8_0"):
        pick_gguf_files(["m-q8_0.gguf", "m-q5_k_m.gguf"], "q4_k_m")


def test_context_fits_the_longest_prompt_and_reply():
    # max_prompt_chars counts characters; a token can be as short as ~2.5 characters (page 10)
    assert context_size(8000, 256) == 4096
    assert context_size(8000, 2000) >= 8000 / 2.5 + 2000
    assert context_size(1000, 64) == 2048  # never below 2048


def test_satisfies_protocol():
    assert isinstance(LlamaCppBackend(), Backend)


def test_streams_the_reply(backend):
    assert list(backend.generate_stream(MSGS, 16)) == ["hello", " there", " friend"]
    assert backend.generate(MSGS, 16) == "hello there friend"


def test_request_is_greedy_capped_and_stops_at_a_new_turn(backend):
    sent = json.loads(backend.generate([{"role": "user", "content": "ECHO"}], 33))
    assert sent["max_tokens"] == 33 and sent["temperature"] == 0 and sent["stream"] is True
    assert set(TURN_START_TOKENS) <= set(sent["stop"])


def test_server_runs_on_the_discrete_gpu_with_small_batches(backend):
    """A 3B model on a GTX 1050 hit 'device lost' with the default 512-token batches; 128 runs."""
    argv = json.loads(backend.generate([{"role": "user", "content": "ECHO"}], 8))["argv"]
    assert argv[argv.index("-dev") + 1] == "Vulkan1"
    assert argv[argv.index("-ub") + 1] == "128" and argv[argv.index("-c") + 1] == "4096"
    assert backend.info()["device"] == "Vulkan1"


def test_cpu_device_turns_gpu_off(gguf):
    b = LlamaCppBackend(gguf=str(gguf), device="cpu", server=FAKE_SERVER)
    b.load("fake/model", "q4_k_m")
    try:
        argv = json.loads(b.generate([{"role": "user", "content": "ECHO"}], 8))["argv"]
        assert argv[argv.index("-dev") + 1] == "none" and "-ub" not in argv
        assert b.info()["device"] == "cpu"
    finally:
        b.close()


def test_prompt_over_the_context_says_what_to_do(backend):
    with pytest.raises(RuntimeError, match="max_prompt_chars"):
        backend.generate([{"role": "user", "content": "TOO LONG"}], 8)


def test_server_that_fails_to_start_shows_its_output(tmp_path):
    b = LlamaCppBackend(gguf=str(tmp_path / "missing-q4_k_m.gguf"), server=FAKE_SERVER)
    with pytest.raises(RuntimeError, match="failed to load model"):
        b.load("fake/model", "q4_k_m")


def test_adapter_is_converted_next_to_itself_for_the_base_model(backend, tmp_path):
    a = adapter(tmp_path, "private")
    backend.set_adapters([a])
    assert (a / "adapter.gguf").read_text() == "LORA fake/model"
    assert backend.info()["adapters"] == [str(a)]


def test_adapter_is_switched_per_request_without_restarting(backend, tmp_path):
    a = adapter(tmp_path, "private")
    backend.set_adapters([a])
    sent = echo(backend)
    argv = sent["argv"]
    assert argv[argv.index("--lora") + 1] == str(a / "adapter.gguf") and "--lora-init-without-apply" in argv
    assert sent["lora"] == [{"id": 0, "scale": 1.0}]
    server = backend.process
    backend.set_adapters([])
    assert echo(backend)["lora"] == [{"id": 0, "scale": 0.0}]
    backend.set_adapters([a])
    assert echo(backend)["lora"] == [{"id": 0, "scale": 1.0}]
    assert backend.process is server and conversions(a) == 1  # converted once, loaded once


def test_a_new_adapter_restarts_the_server_with_all_of_them(backend, tmp_path):
    a, b = adapter(tmp_path, "private"), adapter(tmp_path, "acme")
    backend.set_adapters([a])
    first = backend.process
    backend.set_adapters([b])
    sent = echo(backend)
    argv = sent["argv"]
    assert argv[argv.index("--lora") + 1] == f"{a / 'adapter.gguf'},{b / 'adapter.gguf'}"
    assert sent["lora"] == [{"id": 0, "scale": 0.0}, {"id": 1, "scale": 1.0}]
    assert backend.process is not first and first.poll() is not None


def test_retrained_adapter_is_converted_and_loaded_again(backend, tmp_path):
    a = adapter(tmp_path, "private")
    backend.set_adapters([a])
    first = backend.process
    backend.set_adapters([])
    later = (a / "adapter.gguf").stat().st_mtime + 10
    os.utime(a / "adapter_model.safetensors", (later, later))  # training wrote new weights
    backend.set_adapters([a])
    assert conversions(a) == 2 and backend.process is not first


def test_failed_conversion_leaves_no_adapter_active_and_the_model_running(backend, tmp_path):
    a = adapter(tmp_path, "private")
    backend.set_adapters([a])
    broken = tmp_path / "adapters" / "broken"
    broken.mkdir()
    with pytest.raises(AdapterLoadError, match="adapter_model.safetensors"):
        backend.set_adapters([broken])
    assert backend.info()["adapters"] == []
    assert echo(backend)["lora"] == [{"id": 0, "scale": 0.0}]


def test_missing_converter_says_how_to_get_it(gguf, tmp_path):
    b = LlamaCppBackend(gguf=str(gguf), server=FAKE_SERVER, converter=[sys.executable, str(tmp_path / "nope.py")])
    b.load("fake/model", "q4_k_m")
    try:
        with pytest.raises(AdapterLoadError, match="get_llamacpp.py"):
            b.set_adapters([adapter(tmp_path, "private")])
        assert b.info()["adapters"] == []
    finally:
        b.close()


def test_close_stops_the_server(backend):
    proc = backend.process
    backend.close()
    assert proc.poll() is not None
    backend.close()  # twice is fine


def test_missing_server_says_how_to_get_it(gguf, monkeypatch):
    monkeypatch.setattr("localagent.runtime.llamacpp_backend.find_server", lambda: None)
    with pytest.raises(RuntimeError, match="get_llamacpp.py"):
        LlamaCppBackend(gguf=str(gguf)).load("fake/model", "q4_k_m")
