"""Copies a connection's adapter from the internal agent to a Tessera-facing agent. Never the private one."""
import shutil
from pathlib import Path

from localagent.training.examples import INTERNAL
from localagent.training.lora import read_adapter_info


class ExportError(ValueError):
    """The adapter can't or mustn't be exported; the message says why."""


def export_adapter(source: Path, dest: Path, *, compartment: str, dest_model_id: str,
                   dest_compartments: list[str]) -> Path:
    source, dest = Path(source), Path(dest)
    if compartment == INTERNAL:
        raise ExportError("The private adapter never leaves the internal agent.")
    info = read_adapter_info(source)
    if info is None:
        raise ExportError(f"No trained adapter at {source}. Run: python -m localagent train --adapter {compartment}")
    if info.get("compartment") != compartment:
        raise ExportError(f"{source} holds the adapter of '{info.get('compartment')}', not '{compartment}'")
    if compartment not in dest_compartments:
        raise ExportError(f"'{compartment}' is not a compartment of the destination agent; "
                          "add it to that agent's agent.yaml first")
    if info.get("base_model") != dest_model_id:
        raise ExportError(f"The adapter was trained for {info.get('base_model')}, but the destination agent uses "
                          f"{dest_model_id}. An adapter only works on the model it was trained on.")
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(source, tmp)
    if dest.exists():
        shutil.rmtree(dest)
    tmp.rename(dest)
    return dest
