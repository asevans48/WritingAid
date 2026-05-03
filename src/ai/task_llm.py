"""Resolve the LLMClient that should handle a given writing-tool task.

The writing tool lets users pick a per-task model in CreativeOS
settings (``model_for_plot``, ``model_for_rephrase``, etc.). Most call
sites already route through ``AgentSuite.get_llm_for_task`` for that,
but a handful of UI surfaces (notably the Critique/Grader worker)
build their own ``LLMClient`` straight from settings without ever
consulting an AgentSuite. This helper exists so those surfaces can
honour the same per-task preference without dragging the full
AgentSuite into every worker thread.

The chosen model can be ANY kind, not just a trained one — see
``creativeos_config.parse_task_model_spec``. Supported kinds:
    * trained (LoRA / fine-tune from the Training Studio)
    * hf      (local HuggingFace transformer)
    * mlx     (local MLX model, Apple Silicon)
    * local   (auto-detect mlx/hf based on the model id)
    * cloud   (Claude / ChatGPT / OpenAI / Gemini)

Returns ``None`` when no per-task preference is set (or the chosen
model can't be constructed) so the caller's existing fallback path
runs unchanged.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.ai.llm_client import LLMClient


def _build_local_llm(model_id: str,
                     force_mlx: Optional[bool] = None
                     ) -> Optional["LLMClient"]:
    """Construct an LLMClient for a local HF/MLX model id or path.

    ``force_mlx`` overrides the substring-based MLX detection — used
    when the user picked an explicit ``hf:`` or ``mlx:`` kind in
    settings; ``None`` falls back to the heuristic.
    """
    if not model_id:
        return None
    try:
        from src.config.ai_config import get_ai_config
        from src.ai.llm_client import (
            LLMClient, LLMProvider, HuggingFaceConfig,
        )
        from src.ai.mlx_utils import can_use_mlx

        local_settings = get_ai_config().get_local_model_settings()
        quantization = local_settings.get("quantization", "none")
        if quantization == "none":
            quantization = None
        trust = local_settings.get("trust_remote_code", True)

        hf_config = HuggingFaceConfig(
            model_id=model_id,
            use_local=True,
            device="auto",
            quantization=quantization,
            trust_remote_code=trust,
        )
        if force_mlx is True:
            use_mlx = can_use_mlx()
        elif force_mlx is False:
            use_mlx = False
        else:
            use_mlx = ("mlx" in model_id.lower()) and can_use_mlx()
        provider = (LLMProvider.MLX_LOCAL if use_mlx
                    else LLMProvider.HUGGINGFACE_LOCAL)
        return LLMClient(provider=provider, hf_config=hf_config)
    except Exception as e:
        print(f"[task_llm] Could not build local LLM '{model_id}': {e}")
        return None


def _build_cloud_llm(provider_name: str,
                     model_override: Optional[str] = None
                     ) -> Optional["LLMClient"]:
    """Construct an LLMClient for a cloud provider.

    ``provider_name`` is one of ``claude`` / ``chatgpt`` / ``openai`` /
    ``gemini`` (case-insensitive). ``model_override`` lets the caller
    pin a specific model id — falls back to whatever the user has
    configured in AI Settings for that provider.
    """
    try:
        from src.config.ai_config import get_ai_config
        from src.ai.llm_client import LLMClient, LLMProvider
    except Exception as e:
        print(f"[task_llm] cloud LLM imports failed: {e}")
        return None
    name = (provider_name or "").strip().lower()
    provider_map = {
        "claude": LLMProvider.CLAUDE,
        "chatgpt": LLMProvider.CHATGPT,
        "openai": LLMProvider.CHATGPT,
        "gemini": LLMProvider.GEMINI,
    }
    provider = provider_map.get(name)
    if provider is None:
        print(f"[task_llm] unknown cloud provider '{provider_name}'")
        return None
    cfg = get_ai_config()
    api_key = cfg.get_api_key(name)
    if not api_key:
        print(f"[task_llm] no API key configured for '{name}' — "
              f"falling back to default LLM")
        return None
    model = model_override or cfg.get_model(name)
    try:
        return LLMClient(provider=provider, api_key=api_key,
                          model=model)
    except Exception as e:
        print(f"[task_llm] Could not build cloud LLM '{name}': {e}")
        return None


def build_task_llm_override(task: str) -> Optional["LLMClient"]:
    """Return an ``LLMClient`` for the user-chosen task model, or ``None``.

    ``task`` should be one of: ``rephrase``, ``plot``, ``worldbuilding``,
    ``character``, ``general``. Unknown tasks return ``None``.
    Resolves any spec kind — trained, local HF/MLX, or cloud.
    """
    try:
        from src.config.creativeos_config import get_creativeos_config
        cfg = get_creativeos_config()
        res = cfg.resolve_task_model(task)
    except Exception as e:
        print(f"[task_llm] resolve_task_model failed: {e}")
        return None

    spec = (res or {}).get("spec") or {"kind": ""}
    kind = spec.get("kind", "")
    if not kind:
        return None

    if kind == "trained":
        trained = (res or {}).get("trained_model") or {}
        path = trained.get("path", "")
        return _build_local_llm(path)
    if kind in ("hf", "mlx", "local"):
        force_mlx = None
        if kind == "mlx":
            force_mlx = True
        elif kind == "hf":
            force_mlx = False
        return _build_local_llm(spec.get("model_id", ""),
                                  force_mlx=force_mlx)
    if kind == "cloud":
        return _build_cloud_llm(spec.get("provider", ""),
                                  model_override=spec.get("model"))
    return None
