import tarfile
import zipfile

import pytest

from localagent.runtime.llamacpp_install import choose_build, release_assets, unpack, unpack_converter

TAG = "b11576"


def test_assets_for_each_platform():
    assert release_assets("Windows", "AMD64", "vulkan", TAG) == ["llama-b11576-bin-win-vulkan-x64.zip"]
    assert release_assets("Windows", "AMD64", "cuda", TAG) == ["llama-b11576-bin-win-cuda-12.4-x64.zip",
                                                               "cudart-llama-bin-win-cuda-12.4-x64.zip"]
    assert release_assets("Linux", "x86_64", "cpu", TAG) == ["llama-b11576-bin-ubuntu-x64.tar.gz"]
    assert release_assets("Darwin", "arm64", "metal", TAG) == ["llama-b11576-bin-macos-arm64.tar.gz"]


def test_unknown_combination_says_what_exists():
    with pytest.raises(ValueError, match="metal"):
        release_assets("Darwin", "arm64", "cuda", TAG)


def test_build_follows_the_gpu():
    """Vulkan for NVIDIA: it runs on old drivers too (CUDA builds need CUDA 12.4+, a 2022 driver has 11.6)."""
    assert choose_build({"vendor": "nvidia"}) == "vulkan"
    assert choose_build({"vendor": "apple"}) == "metal"
    assert choose_build(None) == "cpu"


def test_unpack_puts_the_server_folder_at_the_destination(tmp_path):
    archive = tmp_path / "a.tar.gz"
    src = tmp_path / "src" / "build" / "bin"
    src.mkdir(parents=True)
    (src / "llama-server").write_text("x")
    (src / "libggml.so").write_text("y")
    with tarfile.open(archive, "w:gz") as t:
        t.add(tmp_path / "src" / "build", arcname="build")
    dest = tmp_path / "llama.cpp"
    unpack(archive, dest)
    assert sorted(p.name for p in dest.iterdir()) == ["libggml.so", "llama-server"]


def test_unpack_refuses_paths_outside_the_destination(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../outside.txt", "x")
        z.writestr("llama-server.exe", "x")
    with pytest.raises(ValueError, match="outside"):
        unpack(archive, tmp_path / "llama.cpp")
    assert not (tmp_path / "outside.txt").exists()


def test_converter_comes_from_the_source_archive_without_the_rest(tmp_path):
    archive = tmp_path / "src.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for name in ("convert_lora_to_gguf.py", "convert_hf_to_gguf.py", "conversion/__init__.py",
                     "conversion/qwen.py", "gguf-py/gguf/__init__.py", "gguf-py/pyproject.toml", "src/llama.cpp",
                     "README.md"):
            z.writestr(f"llama.cpp-b11576/{name}", "x")
    dest = tmp_path / "convert"
    unpack_converter(archive, dest)
    found = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    assert found == ["conversion/__init__.py", "conversion/qwen.py", "convert_hf_to_gguf.py",
                     "convert_lora_to_gguf.py", "gguf-py/gguf/__init__.py"]
