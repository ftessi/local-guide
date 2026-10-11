from localagent.runtime.hardware import detect, recommend


def _info(gpu=None, ram=8):
    return {"os": "Windows", "machine": "AMD64", "ram_gb": ram, "gpu": gpu}


def test_nvidia_small_card_gets_fast_small_model():
    r = recommend(_info({"vendor": "nvidia", "name": "GTX 1050", "vram_gb": 3.9}))
    assert r["recommended_backend"] == "transformers"
    assert r["recommended_model"] == "Qwen/Qwen2.5-1.5B-Instruct"
    assert r["recommended_quantization"] == "fp16"
    assert r["backend_available"] is True


def test_nvidia_big_card():
    r = recommend(_info({"vendor": "nvidia", "name": "RTX", "vram_gb": 12}))
    assert r["recommended_model"] == "Qwen/Qwen2.5-7B-Instruct"


def test_mid_card():
    r = recommend(_info({"vendor": "nvidia", "name": "RTX", "vram_gb": 8}))
    assert r["recommended_model"] == "Qwen/Qwen2.5-3B-Instruct"
    assert r["recommended_quantization"] == "4bit"


def test_apple_and_cpu_backends_not_yet_available():
    assert recommend(_info({"vendor": "apple", "name": "M4", "vram_gb": None}, ram=16))["recommended_backend"] == "mlx"
    cpu = recommend(_info(None, ram=8))
    assert cpu["recommended_backend"] == "llamacpp"
    assert cpu["backend_available"] is False


def test_detect_shape():
    info = detect()
    assert {"os", "ram_gb", "gpu", "recommended_backend"} <= set(info)
