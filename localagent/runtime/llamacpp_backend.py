"""llama.cpp backend: runs llama-server (GGUF models) as a child process and talks to it over HTTP on 127.0.0.1.
Fast on CPU, and on small or older GPUs through Vulkan, which needs no CUDA toolkit or recent driver (page 10).

LoRA adapters: each one is converted to GGUF on first use (lora_gguf.py) and loaded into the server switched off;
every request switches on only the session's adapter. An adapter the server hasn't loaded yet means a restart
(a few seconds, once per adapter)."""
import atexit
import http.client
import json
import math
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from localagent.runtime.base import TURN_START_TOKENS, AdapterLoadError
from localagent.runtime.llamacpp_install import SERVER_DIR
from localagent.runtime.lora_gguf import gguf_adapter
# A 3B model on a GTX 1050 (Vulkan) failed with "device lost" at the default 512-token batches; 128 runs, and
# prompts are still read at ~160 tokens/s.
GPU_BATCH = 128
LOAD_TIMEOUT_S = 600
DEVICE_LINE = re.compile(r"^\s*(\S+): (.+?) \((\d+) MiB, (\d+) MiB free\)", re.M)
# Integrated GPUs share normal RAM and are slower than the CPU path for this; a real GPU is used instead.
INTEGRATED = re.compile(r"Intel\(R\) (U?HD|Iris)|Radeon\(TM\) Graphics|Radeon Vega", re.I)
QUANT_SUFFIX = re.compile(r"[-_.]((?:i?q\d|f16|bf16|f32)[a-z0-9_]*?)(?:-\d{5}-of-\d{5})?\.gguf$", re.I)


def find_server() -> Path | None:
    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    for candidate in (os.environ.get("LOCALAGENT_LLAMA_SERVER"), SERVER_DIR / exe, shutil.which("llama-server")):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def pick_device(list_devices_output: str) -> str:
    """The GPU with the most free memory from `llama-server --list-devices`, skipping integrated ones;
    "none" (CPU) if there is no other."""
    found = [(int(free), name) for name, desc, _total, free in DEVICE_LINE.findall(list_devices_output)
             if not INTEGRATED.search(desc)]
    return max(found)[1] if found else "none"


def pick_gguf_files(files: list[str], quantization: str) -> list[str]:
    """The repo files holding one quantization; a model split into parts gives every part, first part first."""
    pattern = re.compile(rf"(?:^|[-_.]){re.escape(quantization)}(?:-\d{{5}}-of-\d{{5}})?\.gguf$", re.I)
    matches = sorted(f for f in files if pattern.search(f))
    if not matches:
        available = sorted({m.group(1).lower() for f in files if (m := QUANT_SUFFIX.search(f))})
        raise ValueError(f"No '{quantization}' GGUF file in this repository. "
                         f"Available: {', '.join(available) or 'none'}")
    return matches


def context_size(max_prompt_chars: int, max_new_tokens: int) -> int:
    """Tokens for the longest prompt plus the reply. A token can be as short as ~2.5 characters."""
    return max(2048, math.ceil((max_prompt_chars / 2.5 + max_new_tokens) / 1024) * 1024)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LlamaCppBackend:
    name = "llamacpp"

    def __init__(self, gguf: str = "", device: str = "auto", max_prompt_chars: int = 8000,
                 max_new_tokens: int = 256, server: list[str] | None = None, converter: list[str] | None = None):
        """gguf: a HuggingFace repo with GGUF files (default: the model id + "-GGUF") or a local .gguf file.
        device: "auto", "cpu", or a name from `llama-server --list-devices` (e.g. Vulkan1).
        server: the command that starts llama-server (default: found by find_server).
        converter: the command that converts an adapter to GGUF (default: llama.cpp's convert_lora_to_gguf.py)."""
        self.gguf = gguf
        self.device_setting = device
        self.ctx = context_size(max_prompt_chars, max_new_tokens)
        self.server = server
        self.converter = converter
        self.model_id = ""
        self.device = ""
        self.process: subprocess.Popen | None = None
        self.port = 0
        self.log_path: Path | None = None
        self._command: list[str] = []
        self._model_path: Path | None = None
        self._loaded: list[Path] = []  # adapter GGUFs in the server, in --lora order (= their ids)
        self._active: set[int] = set()
        self._adapters: list[Path] = []

    def load(self, model_id: str, quantization: str = "q4_k_m") -> None:
        self._command = self.server or self._server_command()
        self._model_path = self._model_file(model_id, quantization)
        self.device = self._device(self._command)
        self.model_id = model_id
        atexit.register(self.close)
        self._start()

    def _start(self) -> None:
        self.port = _free_port()
        args = [*self._command, "-m", str(self._model_path), "--host", "127.0.0.1", "--port", str(self.port),
                "-c", str(self.ctx), "-np", "1", "-dev", self.device, "--no-webui"]
        if self.device != "none":
            args += ["-b", str(GPU_BATCH), "-ub", str(GPU_BATCH)]
        if self._loaded:
            args += ["--lora", ",".join(str(p) for p in self._loaded), "--lora-init-without-apply"]
        log = tempfile.NamedTemporaryFile(prefix="llama-server-", suffix=".log", delete=False)
        self.log_path = Path(log.name)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        log.close()
        self._wait_until_ready()

    @staticmethod
    def _server_command() -> list[str]:
        path = find_server()
        if path is None:
            raise RuntimeError("llama-server was not found. Download it with: python scripts/get_llamacpp.py "
                               "(or set LOCALAGENT_LLAMA_SERVER to its path)")
        return [str(path)]

    def _model_file(self, model_id: str, quantization: str) -> Path:
        if self.gguf.lower().endswith(".gguf"):
            return Path(self.gguf)
        from huggingface_hub import HfApi, hf_hub_download

        repo = self.gguf or f"{model_id}-GGUF"
        try:
            files = pick_gguf_files(HfApi().list_repo_files(repo), quantization)
        except ValueError as e:
            raise RuntimeError(f"{repo}: {e}") from None
        paths = [hf_hub_download(repo, f) for f in files]  # every part of a split model; the first is loaded
        return Path(paths[0])

    def _device(self, command: list[str]) -> str:
        if self.device_setting == "cpu":
            return "none"
        if self.device_setting != "auto":
            return self.device_setting
        out = subprocess.run([*command, "--list-devices"], capture_output=True, text=True, timeout=120)
        return pick_device(out.stdout + out.stderr)

    def _log_tail(self, lines: int = 15) -> str:
        try:
            return "\n".join(self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        except OSError:
            return ""

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + LOAD_TIMEOUT_S
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"llama-server stopped while loading the model (log: {self.log_path}):\n"
                                   f"{self._log_tail()}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                    if r.status == 200:
                        return
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass  # still starting (503 while the model loads)
            time.sleep(0.25)
        self.close()
        raise RuntimeError(f"llama-server did not get ready in {LOAD_TIMEOUT_S} s (log: {self.log_path})")

    def generate(self, messages: list[dict], max_new_tokens: int = 256) -> str:
        return "".join(self.generate_stream(messages, max_new_tokens)).strip()

    def generate_stream(self, messages: list[dict], max_new_tokens: int = 256):
        request = {"messages": messages, "max_tokens": max_new_tokens, "temperature": 0,
                   "stop": list(TURN_START_TOKENS), "stream": True}
        if self._loaded:  # every loaded adapter gets a scale: on for this session's, off for the rest
            request["lora"] = [{"id": i, "scale": 1.0 if i in self._active else 0.0} for i in range(len(self._loaded))]
        body = json.dumps(request)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=LOAD_TIMEOUT_S)
        try:
            try:
                conn.request("POST", "/v1/chat/completions", body, {"Content-Type": "application/json"})
                response = conn.getresponse()
            except ConnectionError as e:
                raise RuntimeError(f"llama-server is not answering ({e}). Its log ({self.log_path}):\n"
                                   f"{self._log_tail()}") from None
            if response.status != 200:
                self._raise_error(response.read())
            for raw in response:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                if line == "data: [DONE]":
                    break
                event = json.loads(line[6:])
                if "error" in event:
                    self._raise_error(line[6:].encode())
                text = event["choices"][0]["delta"].get("content")
                if text:
                    yield text
        finally:
            conn.close()

    def _raise_error(self, body: bytes):
        try:
            message = json.loads(body)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = body.decode("utf-8", errors="replace")
        if "context" in message:
            raise RuntimeError(f"The prompt is too long for the model's context ({self.ctx} tokens). Lower "
                               "model.max_prompt_chars in agent.yaml, or type 'reset' to drop old conversation.")
        raise RuntimeError(f"llama-server: {message}")

    def set_adapters(self, paths: list[Path]) -> None:
        paths = [Path(p) for p in paths]
        if paths == self._adapters:
            return
        self._adapters, self._active = [], set()  # none active unless all of these load
        converted = [gguf_adapter(p, self.model_id, self.converter) for p in paths]
        ggufs = [g for g, _ in converted]
        if any(g not in self._loaded or fresh for g, fresh in converted):  # new to the server, or retrained
            previous = self._loaded
            self._loaded = previous + [g for g in ggufs if g not in previous]
            try:
                self.close()
                self._start()
            except RuntimeError as e:
                self._loaded = previous
                self._start()  # back to the adapters that worked
                raise AdapterLoadError(f"llama-server could not load the adapters {[str(p) for p in paths]}: {e}") from e
        self._active = {self._loaded.index(g) for g in ggufs}
        self._adapters = paths

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

    def info(self) -> dict:
        device = {"": "not loaded", "none": "cpu"}.get(self.device, self.device)
        return {"model_id": self.model_id, "backend": self.name, "device": device,
                "adapters": [str(p) for p in self._adapters]}
