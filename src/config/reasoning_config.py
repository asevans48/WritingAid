"""Configuration for reasoning-optimized language models.

Provides curated lists of models specifically tuned for analytical tasks:
- Story planning and outlining
- Plot structure analysis
- Character consistency checking
- Narrative critique
- Logic and continuity verification
"""

from dataclasses import dataclass
from typing import List
from enum import Enum


class ReasoningProvider(Enum):
    """Available reasoning model providers."""
    LOCAL_MLX = "local_mlx"  # Apple Silicon with MLX
    LOCAL_TORCH = "local_torch"  # NVIDIA/AMD with PyTorch


@dataclass
class ReasoningModelInfo:
    """Information about a reasoning-optimized model."""
    model_id: str
    display_name: str
    provider: ReasoningProvider
    vram_gb: float
    ram_gb: float
    description: str
    best_for: str
    requires_trust_remote_code: bool = False
    platform: str = "any"  # "apple_silicon", "nvidia", "amd", "any"
    context_length: int = 4096  # Maximum context window
    shows_reasoning: bool = False  # Whether model outputs explicit reasoning chains


# MLX Models for Apple Silicon (M1/M2/M3/M4/M5)
MLX_REASONING_MODELS: List[ReasoningModelInfo] = [
    # === Microsoft Phi-4 Reasoning (Best Balance) ===
    ReasoningModelInfo(
        model_id="mlx-community/Phi-4-reasoning-plus-4bit",
        display_name="Phi-4 Reasoning Plus - MLX [Recommended]",
        provider=ReasoningProvider.LOCAL_MLX,
        vram_gb=7.0,
        ram_gb=16.0,
        description="Microsoft's 14B reasoning model with 128K context, enhanced RL training",
        best_for="Story planning, plot analysis, character consistency, narrative critique",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=131072,
        shows_reasoning=True
    ),

    # === DeepSeek-R1 Distilled Models ===
    ReasoningModelInfo(
        model_id="mlx-community/DeepSeek-R1-Distill-Qwen-14B-4bit",
        display_name="DeepSeek-R1 Qwen 14B - MLX [High Quality]",
        provider=ReasoningProvider.LOCAL_MLX,
        vram_gb=7.0,
        ram_gb=16.0,
        description="Distilled from DeepSeek-R1, excellent chain-of-thought reasoning",
        best_for="Complex plot analysis, multi-character tracking, logic verification",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=131072,
        shows_reasoning=True
    ),
    ReasoningModelInfo(
        model_id="mlx-community/DeepSeek-R1-Distill-Qwen-7B-4bit",
        display_name="DeepSeek-R1 Qwen 7B - MLX [Balanced]",
        provider=ReasoningProvider.LOCAL_MLX,
        vram_gb=4.0,
        ram_gb=12.0,
        description="Lighter DeepSeek-R1 distillation with strong reasoning capabilities",
        best_for="Chapter planning, outline critique, continuity checking",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=131072,
        shows_reasoning=True
    ),

    # === Ministral Reasoning Models ===
    ReasoningModelInfo(
        model_id="mlx-community/Ministral-3-3B-Reasoning-2512-bf16",
        display_name="Ministral 3 3B Reasoning - MLX [Lightweight]",
        provider=ReasoningProvider.LOCAL_MLX,
        vram_gb=6.0,
        ram_gb=8.0,
        description="Mistral's compact reasoning model with 128K context",
        best_for="Quick plot checks, outline validation, fast iterations",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=131072,
        shows_reasoning=True
    ),

    # === Lightweight Fallback Models (Non-Reasoning) ===
    # These don't show explicit reasoning chains but can still handle analytical tasks
    ReasoningModelInfo(
        model_id="mlx-community/Qwen2.5-7B-Instruct-4bit",
        display_name="Qwen 2.5 7B - MLX [Fallback]",
        provider=ReasoningProvider.LOCAL_MLX,
        vram_gb=4.0,
        ram_gb=8.0,
        description="General-purpose model, good for analysis without explicit reasoning",
        best_for="Limited hardware, general planning and critique tasks",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=131072,
        shows_reasoning=False
    ),
    ReasoningModelInfo(
        model_id="mlx-community/gemma-3-4b-it-4bit",
        display_name="Gemma 3 4B - MLX [Ultra Lightweight]",
        provider=ReasoningProvider.LOCAL_MLX,
        vram_gb=2.0,
        ram_gb=4.0,
        description="Google's lightweight model for basic analytical tasks",
        best_for="Very limited hardware, simple planning tasks",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=8192,
        shows_reasoning=False
    ),
]

# PyTorch Models for NVIDIA GPUs / Windows
TORCH_REASONING_MODELS: List[ReasoningModelInfo] = [
    # === Microsoft Phi-4 Reasoning ===
    ReasoningModelInfo(
        model_id="microsoft/Phi-4-reasoning-plus",
        display_name="Phi-4 Reasoning Plus [Recommended]",
        provider=ReasoningProvider.LOCAL_TORCH,
        vram_gb=28.0,
        ram_gb=32.0,
        description="Microsoft's 14B reasoning model with 128K context, enhanced RL training",
        best_for="Story planning, plot analysis, character consistency, narrative critique",
        requires_trust_remote_code=False,
        platform="nvidia",
        context_length=131072,
        shows_reasoning=True
    ),

    # === Qwen Reasoning Models ===
    ReasoningModelInfo(
        model_id="Qwen/QwQ-32B",
        display_name="QwQ 32B [High Performance]",
        provider=ReasoningProvider.LOCAL_TORCH,
        vram_gb=64.0,
        ram_gb=64.0,
        description="Qwen's powerful 32B reasoning model with 131K context",
        best_for="Deep plot analysis, complex worldbuilding, full manuscript critique",
        requires_trust_remote_code=False,
        platform="nvidia",
        context_length=131072,
        shows_reasoning=True
    ),
    ReasoningModelInfo(
        model_id="Qwen/Qwen3-4B-Thinking-2507",
        display_name="Qwen3 4B Thinking [Efficient]",
        provider=ReasoningProvider.LOCAL_TORCH,
        vram_gb=8.0,
        ram_gb=12.0,
        description="Latest Qwen3 thinking model with massive 262K context",
        best_for="Long narrative analysis, multi-chapter tracking, continuity checks",
        requires_trust_remote_code=False,
        platform="nvidia",
        context_length=262144,
        shows_reasoning=True
    ),

    # === Mistral Reasoning Models ===
    ReasoningModelInfo(
        model_id="mistralai/Ministral-3-8B-Reasoning-2512",
        display_name="Ministral 3 8B Reasoning [Balanced]",
        provider=ReasoningProvider.LOCAL_TORCH,
        vram_gb=16.0,
        ram_gb=16.0,
        description="Mistral's reasoning model with 128K context, vision-capable",
        best_for="Plot structure, character arcs, scene analysis",
        requires_trust_remote_code=False,
        platform="nvidia",
        context_length=131072,
        shows_reasoning=True
    ),

    # === DeepSeek-R1 Distilled Models ===
    ReasoningModelInfo(
        model_id="deepseek-ai/DeepSeek-R1-Distill-Qwen-14B",
        display_name="DeepSeek-R1 Qwen 14B [High Quality]",
        provider=ReasoningProvider.LOCAL_TORCH,
        vram_gb=28.0,
        ram_gb=32.0,
        description="Distilled from DeepSeek-R1, excellent chain-of-thought reasoning",
        best_for="Complex plot analysis, multi-character tracking, logic verification",
        requires_trust_remote_code=False,
        platform="nvidia",
        context_length=131072,
        shows_reasoning=True
    ),
    ReasoningModelInfo(
        model_id="deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
        display_name="DeepSeek-R1 Qwen 7B [Fits 16GB]",
        provider=ReasoningProvider.LOCAL_TORCH,
        vram_gb=14.0,
        ram_gb=16.0,
        description="Lighter DeepSeek-R1 distillation with strong reasoning capabilities",
        best_for="Chapter planning, outline critique, continuity checking",
        requires_trust_remote_code=False,
        platform="nvidia",
        context_length=131072,
        shows_reasoning=True
    ),

    # === Lightweight Fallback Models (Non-Reasoning) ===
    # These don't show explicit reasoning chains but can still handle analytical tasks
    ReasoningModelInfo(
        model_id="Qwen/Qwen2.5-7B-Instruct",
        display_name="Qwen 2.5 7B [Fallback]",
        provider=ReasoningProvider.LOCAL_TORCH,
        vram_gb=14.0,
        ram_gb=16.0,
        description="General-purpose model, good for analysis without explicit reasoning",
        best_for="Limited hardware (16GB VRAM), general planning and critique",
        requires_trust_remote_code=True,
        platform="nvidia",
        context_length=131072,
        shows_reasoning=False
    ),
    ReasoningModelInfo(
        model_id="microsoft/Phi-4-mini-instruct",
        display_name="Phi 4 Mini [Lightweight Fallback]",
        provider=ReasoningProvider.LOCAL_TORCH,
        vram_gb=7.6,
        ram_gb=8.0,
        description="Microsoft's small but capable model for basic analytical tasks",
        best_for="8GB VRAM, quick planning and outline critique",
        requires_trust_remote_code=True,
        platform="any",
        context_length=4096,
        shows_reasoning=False
    ),
    ReasoningModelInfo(
        model_id="microsoft/Phi-3.5-mini-instruct",
        display_name="Phi 3.5 Mini [Ultra Lightweight]",
        provider=ReasoningProvider.LOCAL_TORCH,
        vram_gb=7.6,
        ram_gb=8.0,
        description="Efficient small model for basic planning tasks",
        best_for="6-8GB VRAM, simple planning and feedback",
        requires_trust_remote_code=True,
        platform="any",
        context_length=4096,
        shows_reasoning=False
    ),
    ReasoningModelInfo(
        model_id="google/gemma-3-4b-it",
        display_name="Gemma 3 4B [Very Lightweight]",
        provider=ReasoningProvider.LOCAL_TORCH,
        vram_gb=8.0,
        ram_gb=12.0,
        description="Google's lightweight model for basic analytical tasks",
        best_for="8GB VRAM, simple critique and planning",
        requires_trust_remote_code=False,
        platform="nvidia",
        context_length=8192,
        shows_reasoning=False
    ),
    ReasoningModelInfo(
        model_id="Qwen/Qwen2.5-3B-Instruct",
        display_name="Qwen 2.5 3B [Minimal Hardware]",
        provider=ReasoningProvider.LOCAL_TORCH,
        vram_gb=6.0,
        ram_gb=6.0,
        description="Very lightweight but capable model for basic tasks",
        best_for="6GB VRAM, basic planning and simple analysis",
        requires_trust_remote_code=True,
        platform="any",
        context_length=32768,
        shows_reasoning=False
    ),
]


def get_available_reasoning_models() -> List[ReasoningModelInfo]:
    """Get available reasoning models based on platform.

    Returns:
        List of models appropriate for current hardware
    """
    from src.ai.mlx_utils import can_use_mlx

    if can_use_mlx():
        return MLX_REASONING_MODELS
    else:
        return TORCH_REASONING_MODELS


def get_reasoning_model_by_id(model_id: str) -> ReasoningModelInfo:
    """Get model info by model ID.

    Args:
        model_id: HuggingFace model ID

    Returns:
        ReasoningModelInfo if found, None otherwise
    """
    all_models = MLX_REASONING_MODELS + TORCH_REASONING_MODELS
    for model in all_models:
        if model.model_id == model_id:
            return model
    return None
