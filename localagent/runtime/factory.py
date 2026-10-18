"""Backend name (from agent.yaml) -> backend instance."""
from localagent.runtime.base import Backend

AVAILABLE_BACKENDS = ("transformers", "llamacpp")
PLANNED_BACKENDS = ("mlx",)


def create_backend(name: str, model=None) -> Backend:
    """model: the agent's ModelConfig, for backend settings beyond the model id (llamacpp: gguf, device)."""
    if name == "transformers":
        from localagent.runtime.transformers_backend import TransformersBackend
        return TransformersBackend()
    if name == "llamacpp":
        from localagent.runtime.llamacpp_backend import LlamaCppBackend
        if model is None:
            return LlamaCppBackend()
        return LlamaCppBackend(gguf=model.gguf, device=model.device, max_prompt_chars=model.max_prompt_chars,
                               max_new_tokens=model.max_new_tokens)
    if name in PLANNED_BACKENDS:
        raise NotImplementedError(
            f"Backend '{name}' is planned but not implemented yet. Use 'transformers' or 'llamacpp' for now."
        )
    raise ValueError(f"Unknown backend '{name}'. Available: {', '.join(AVAILABLE_BACKENDS)}")
