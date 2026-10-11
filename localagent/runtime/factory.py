"""Backend name (from agent.yaml) -> backend instance."""
from localagent.runtime.base import Backend

AVAILABLE_BACKENDS = ("transformers",)
PLANNED_BACKENDS = ("llamacpp", "mlx")


def create_backend(name: str) -> Backend:
    if name == "transformers":
        from localagent.runtime.transformers_backend import TransformersBackend
        return TransformersBackend()
    if name in PLANNED_BACKENDS:
        raise NotImplementedError(
            f"Backend '{name}' is planned but not implemented yet. Use 'transformers' for now."
        )
    raise ValueError(f"Unknown backend '{name}'. Available: {', '.join(AVAILABLE_BACKENDS)}")
