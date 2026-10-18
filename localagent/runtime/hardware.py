"""Detect this machine's hardware and recommend a backend and model size."""
import os
import platform
import shutil
import subprocess

from localagent.runtime.factory import AVAILABLE_BACKENDS


def _ram_gb() -> float | None:
    try:
        if platform.system() == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return round(stat.ullTotalPhys / 2**30, 1)
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except Exception:
        return None


def _gpu() -> dict | None:
    try:
        import torch

        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return {"vendor": "nvidia", "name": props.name, "vram_gb": round(props.total_memory / 2**30, 1)}
    except Exception:
        pass
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
            if out:
                name, mem = out[0].rsplit(",", 1)
                return {"vendor": "nvidia", "name": name.strip(), "vram_gb": round(int(mem) / 1024, 1)}
        except Exception:
            pass
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return {"vendor": "apple", "name": "Apple Silicon (unified memory)", "vram_gb": None}
    return None


def recommend(info: dict) -> dict:
    gpu = info.get("gpu") or {}
    vendor = gpu.get("vendor")
    vram = gpu.get("vram_gb") or 0
    ram = info.get("ram_gb") or 0
    if vendor == "nvidia":
        if vram >= 10:
            backend, model, quant = "transformers", "Qwen/Qwen2.5-7B-Instruct", "4bit"
        elif vram >= 6:
            backend, model, quant = "transformers", "Qwen/Qwen2.5-3B-Instruct", "4bit"
        elif vram >= 3.5:
            # Measured on a GTX 1050: 1.5B fp16 is ~12x faster than 3B 4-bit (scripts/benchmark_results.csv)
            backend, model, quant = "transformers", "Qwen/Qwen2.5-1.5B-Instruct", "fp16"
        else:
            backend, model, quant = "transformers", "Qwen/Qwen2.5-1.5B-Instruct", "4bit"
    elif vendor == "apple":  # llama.cpp's Mac build runs on the GPU (Metal); MLX is planned
        model = "Qwen/Qwen2.5-7B-Instruct" if ram >= 16 else "Qwen/Qwen2.5-3B-Instruct"
        backend, quant = "llamacpp", "q4_k_m"
    else:  # i5-7300HQ, 4 threads: 1.5B q4_k_m 15 tokens/s, 3B 7 tokens/s (page 10)
        model = "Qwen/Qwen2.5-3B-Instruct" if ram >= 16 else "Qwen/Qwen2.5-1.5B-Instruct"
        backend, quant = "llamacpp", "q4_k_m"
    return {"recommended_backend": backend, "recommended_model": model,
            "recommended_quantization": quant, "backend_available": backend in AVAILABLE_BACKENDS}


def detect() -> dict:
    info = {"os": platform.system(), "machine": platform.machine(),
            "python": platform.python_version(), "ram_gb": _ram_gb(), "gpu": _gpu()}
    info.update(recommend(info))
    return info
