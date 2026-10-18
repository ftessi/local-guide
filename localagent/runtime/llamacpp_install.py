"""Downloads a prebuilt llama-server from llama.cpp's GitHub releases into LocalAgent/llama.cpp/, and the LoRA
converter (Python scripts from the same release's source) into LocalAgent/llama.cpp/convert/."""
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2] / "llama.cpp"
CONVERTER_DIR = SERVER_DIR / "convert"
TESTED_TAG = "b11576"  # the release measured on page 10; newer ones: --tag
RELEASES = "https://github.com/ggml-org/llama.cpp/releases/download"
SOURCE = "https://github.com/ggml-org/llama.cpp/archive/refs/tags/{tag}.zip"
# What convert_lora_to_gguf.py needs from the source tree; paths below its top folder
CONVERTER_FILES = ("convert_lora_to_gguf.py", "convert_hf_to_gguf.py")
CONVERTER_FOLDERS = ("conversion/", "gguf-py/gguf/")
# (system, machine) -> build -> asset names, "{tag}" filled in. CUDA builds also need the CUDA runtime archive.
ASSETS = {
    ("windows", "x64"): {
        "cpu": ["llama-{tag}-bin-win-cpu-x64.zip"],
        "vulkan": ["llama-{tag}-bin-win-vulkan-x64.zip"],
        "cuda": ["llama-{tag}-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip"],
    },
    ("linux", "x64"): {
        "cpu": ["llama-{tag}-bin-ubuntu-x64.tar.gz"],
        "vulkan": ["llama-{tag}-bin-ubuntu-vulkan-x64.tar.gz"],
        "cuda": ["llama-{tag}-bin-ubuntu-cuda-12.8-x64.tar.gz", "cudart-llama-{tag}-bin-ubuntu-cuda-12.8-x64.tar.gz"],
    },
    ("darwin", "arm64"): {"metal": ["llama-{tag}-bin-macos-arm64.tar.gz"]},
    ("darwin", "x64"): {"cpu": ["llama-{tag}-bin-macos-x64.tar.gz"]},
}
MACHINES = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}


def release_assets(system: str, machine: str, build: str, tag: str) -> list[str]:
    builds = ASSETS.get((system.lower(), MACHINES.get(machine.lower(), machine.lower())), {})
    if build not in builds:
        raise ValueError(f"No '{build}' llama.cpp build for {system} {machine}. "
                         f"Builds there are: {', '.join(builds) or 'none (build llama.cpp yourself)'}")
    return [name.format(tag=tag) for name in builds[build]]


def choose_build(gpu: dict | None) -> str:
    """Vulkan for NVIDIA cards: it runs with any recent-ish driver, while the CUDA builds need CUDA 12.4+."""
    vendor = (gpu or {}).get("vendor")
    return {"nvidia": "vulkan", "apple": "metal"}.get(vendor, "cpu")


def _inside(base: Path, path: Path) -> bool:
    return path.resolve().is_relative_to(base.resolve())


def _extract(archive: Path, into: Path) -> None:
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            if not all(_inside(into, into / name) for name in z.namelist()):
                raise ValueError(f"{archive.name} has files outside its folder; not unpacked")
            z.extractall(into)
        return
    with tarfile.open(archive) as t:
        for m in t.getmembers():
            link_ok = not (m.issym() or m.islnk()) or _inside(into, into / Path(m.name).parent / m.linkname)
            if not _inside(into, into / m.name) or not link_ok or m.isdev():
                raise ValueError(f"{archive.name} has files outside its folder; not unpacked")
        t.extractall(into)


def unpack(archive: Path, dest: Path, *, fresh: bool = True) -> None:
    """Puts the folder holding llama-server (or the archive's top folder) at dest; fresh replaces dest."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _extract(Path(archive), tmp)
        servers = [p for p in tmp.rglob("llama-server*") if p.is_file()]
        root = servers[0].parent if servers else tmp
        if fresh and dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        for item in root.iterdir():
            target = dest / item.name
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            shutil.move(str(item), str(target))


def unpack_converter(source_zip: Path, dest: Path) -> None:
    """Only the LoRA converter and the gguf package it imports, from llama.cpp's source archive; replaces dest."""
    if dest.exists():
        shutil.rmtree(dest)
    with zipfile.ZipFile(source_zip) as z:
        for member in z.infolist():
            rel = member.filename.split("/", 1)[1] if "/" in member.filename else ""
            if member.is_dir() or not (rel in CONVERTER_FILES or rel.startswith(CONVERTER_FOLDERS)):
                continue
            target = dest / rel
            if not _inside(dest, target):
                raise ValueError(f"{source_zip.name} has files outside its folder; not unpacked")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(member))


def install(dest: Path, build: str, tag: str, system: str, machine: str, log=print) -> None:
    assets = release_assets(system, machine, build, tag)
    with tempfile.TemporaryDirectory() as tmp:
        for i, name in enumerate(assets):
            url = f"{RELEASES}/{tag}/{name}"
            log(f"Downloading {url}")
            path = Path(tmp) / name
            urllib.request.urlretrieve(url, path)
            unpack(path, dest, fresh=i == 0)
        url = SOURCE.format(tag=tag)
        log(f"Downloading the LoRA converter from {url}")
        path = Path(tmp) / "source.zip"
        urllib.request.urlretrieve(url, path)
        unpack_converter(path, dest / CONVERTER_DIR.name)
