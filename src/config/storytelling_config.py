"""Configuration for storytelling-optimized language models.

Provides curated lists of models specifically tuned for creative writing,
storytelling, and narrative generation.
"""

from dataclasses import dataclass
from typing import List
from enum import Enum


class StorytellingProvider(Enum):
    """Available storytelling model providers."""
    LOCAL_MLX = "local_mlx"  # Apple Silicon with MLX
    LOCAL_TORCH = "local_torch"  # NVIDIA/AMD with PyTorch


@dataclass
class StorytellingModelInfo:
    """Information about a storytelling-optimized model."""
    model_id: str
    display_name: str
    provider: StorytellingProvider
    vram_gb: float
    ram_gb: float
    description: str
    best_for: str
    requires_trust_remote_code: bool = True
    platform: str = "any"  # "apple_silicon", "nvidia", "amd", "any"
    context_length: int = 4096  # Maximum context window


# MLX Models for Apple Silicon (M1/M2/M3/M4/M5)
MLX_STORYTELLING_MODELS: List[StorytellingModelInfo] = [
    # === Latest Mistral Models ===
    StorytellingModelInfo(
        model_id="mlx-community/Ministral-3-8B-Instruct-2512-4bit",
        display_name="Ministral 3 8B - MLX [Latest, Dec 2024]",
        provider=StorytellingProvider.LOCAL_MLX,
        vram_gb=5.6,
        ram_gb=8.0,
        description="Latest Mistral model with 256K context, excellent for storytelling",
        best_for="Creative writing, storytelling, dialogue, long narratives",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=262144
    ),
    StorytellingModelInfo(
        model_id="mlx-community/Mistral-Nemo-Instruct-2407-4bit",
        display_name="Mistral Nemo 12B - MLX [High Quality]",
        provider=StorytellingProvider.LOCAL_MLX,
        vram_gb=6.89,
        ram_gb=12.0,
        description="Mistral-NVIDIA collaboration, 128K context for long-form writing",
        best_for="High-quality creative writing, complex narratives",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=131072
    ),

    # === Long-Context Models ===
    StorytellingModelInfo(
        model_id="mlx-community/Meta-Llama-3.1-8B-Instruct-4bit",
        display_name="Llama 3.1 8B - MLX",
        provider=StorytellingProvider.LOCAL_MLX,
        vram_gb=5.0,
        ram_gb=12.0,
        description="Meta's Llama 3.1 with 128K context window",
        best_for="Long chapters, extended narratives, worldbuilding documents",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=131072
    ),

    # === Lightweight Story Models (CPU-friendly) ===
    StorytellingModelInfo(
        model_id="roneneldan/TinyStories-33M",
        display_name="TinyStories 33M - MLX [Ultra Fast]",
        provider=StorytellingProvider.LOCAL_MLX,
        vram_gb=0.5,
        ram_gb=1.0,
        description="Tiny model trained on children's stories, extremely fast",
        best_for="Quick story drafts, testing, CPU-only generation",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=2048
    ),

    # === Medium Models (8-16GB RAM) ===
    StorytellingModelInfo(
        model_id="mlx-community/Qwen2.5-7B-Instruct-4bit",
        display_name="Qwen 2.5 7B - MLX [Recommended]",
        provider=StorytellingProvider.LOCAL_MLX,
        vram_gb=4.0,
        ram_gb=8.0,
        description="Excellent balance of speed and quality",
        best_for="All-around best choice for most storytelling tasks",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=131072
    ),
    StorytellingModelInfo(
        model_id="mlx-community/Qwen3-8B-4bit",
        display_name="Qwen 3 8B - MLX [Latest]",
        provider=StorytellingProvider.LOCAL_MLX,
        vram_gb=4.0,
        ram_gb=8.0,
        description="Latest Qwen 8B model (January 2026)",
        best_for="General writing, latest features",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=131072
    ),
    StorytellingModelInfo(
        model_id="mlx-community/Mistral-7B-Instruct-v0.3-4bit",
        display_name="Mistral 7B v0.3 - MLX",
        provider=StorytellingProvider.LOCAL_MLX,
        vram_gb=4.0,
        ram_gb=8.0,
        description="Mistral AI's powerful 7B model",
        best_for="High-quality writing, reasoning",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=32768
    ),
    StorytellingModelInfo(
        model_id="mlx-community/gemma-3-12b-it-4bit",
        display_name="Gemma 3 12B - MLX",
        provider=StorytellingProvider.LOCAL_MLX,
        vram_gb=6.0,
        ram_gb=16.0,
        description="Google's high-quality 12B model",
        best_for="Creative writing, complex tasks",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=8192
    ),

    # === High-Performance Models (16-32GB RAM) ===
    StorytellingModelInfo(
        model_id="mlx-community/Qwen2.5-14B-Instruct-4bit",
        display_name="Qwen 2.5 14B - MLX",
        provider=StorytellingProvider.LOCAL_MLX,
        vram_gb=7.0,
        ram_gb=16.0,
        description="High-quality 14B model with excellent reasoning",
        best_for="Complex writing, long context (128K)",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=131072
    ),
    StorytellingModelInfo(
        model_id="mlx-community/Qwen3-14B-4bit",
        display_name="Qwen 3 14B - MLX [Latest, High Quality]",
        provider=StorytellingProvider.LOCAL_MLX,
        vram_gb=7.0,
        ram_gb=16.0,
        description="Latest Qwen 3 with exceptional creative writing, 128K context",
        best_for="High-quality storytelling, long chapters, worldbuilding",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=131072
    ),
    StorytellingModelInfo(
        model_id="mlx-community/gemma-3-27b-it-4bit",
        display_name="Gemma 3 27B - MLX [High Quality]",
        provider=StorytellingProvider.LOCAL_MLX,
        vram_gb=14.0,
        ram_gb=32.0,
        description="Google's top-tier creative writing model",
        best_for="Maximum quality creative writing, complex narratives",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=8192
    ),
    StorytellingModelInfo(
        model_id="mlx-community/Qwen3-30B-A3B-4bit",
        display_name="Qwen 3 30B - MLX [Latest]",
        provider=StorytellingProvider.LOCAL_MLX,
        vram_gb=15.0,
        ram_gb=32.0,
        description="Latest Qwen model with exceptional quality",
        best_for="Highest quality, latest features",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=131072
    ),
    StorytellingModelInfo(
        model_id="mlx-community/Qwen2.5-32B-Instruct-4bit",
        display_name="Qwen 2.5 32B - MLX",
        provider=StorytellingProvider.LOCAL_MLX,
        vram_gb=17.0,
        ram_gb=32.0,
        description="Top-tier model with exceptional capabilities",
        best_for="Maximum quality across all tasks",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=131072
    ),
    StorytellingModelInfo(
        model_id="mlx-community/Mistral-Small-Instruct-2409-4bit",
        display_name="Mistral Small 22B - MLX",
        provider=StorytellingProvider.LOCAL_MLX,
        vram_gb=12.0,
        ram_gb=32.0,
        description="Mistral's high-quality 22B model",
        best_for="Professional writing, complex reasoning",
        requires_trust_remote_code=False,
        platform="apple_silicon",
        context_length=32768
    ),
]

# PyTorch Models for NVIDIA GPUs / Windows
TORCH_STORYTELLING_MODELS: List[StorytellingModelInfo] = [
    # === Latest Mistral Models ===
    StorytellingModelInfo(
        model_id="mistralai/Ministral-3-8B-Instruct-2512",
        display_name="Ministral 3 8B [Latest, Dec 2024]",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=16.0,
        ram_gb=16.0,
        description="Latest Mistral model with 256K context, excellent for storytelling",
        best_for="Creative writing, storytelling, dialogue, long narratives",
        requires_trust_remote_code=False,
        platform="nvidia",
        context_length=262144
    ),
    StorytellingModelInfo(
        model_id="mistralai/Mistral-Nemo-Instruct-2407",
        display_name="Mistral Nemo 12B [High Quality]",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=24.0,
        ram_gb=24.0,
        description="Mistral-NVIDIA collaboration, 128K context for long-form writing",
        best_for="High-quality creative writing, complex narratives",
        requires_trust_remote_code=False,
        platform="nvidia",
        context_length=131072
    ),
    StorytellingModelInfo(
        model_id="NousResearch/Nous-Hermes-2-Mixtral-8x7B-DPO",
        display_name="Nous Hermes 2 Mixtral (47B)",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=90.0,
        ram_gb=96.0,
        description="Excellent creative writing model from Nous Research",
        best_for="Story writing, character dialogue, creative fiction",
        requires_trust_remote_code=False,
        platform="nvidia",
        context_length=32768
    ),

    # === Long-Context Models ===
    StorytellingModelInfo(
        model_id="Qwen/Qwen2.5-7B-Instruct",
        display_name="Qwen 2.5 7B (128K context)",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=14.0,
        ram_gb=16.0,
        description="Excellent for long-form writing with massive 128K context",
        best_for="Long chapters, extended narratives, worldbuilding documents",
        requires_trust_remote_code=True,
        platform="nvidia",
        context_length=131072
    ),
    StorytellingModelInfo(
        model_id="Qwen/Qwen3-14B-Instruct",
        display_name="Qwen 3 14B (128K context) [Latest]",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=28.0,
        ram_gb=32.0,
        description="Latest Qwen 3 model with exceptional creative writing capabilities",
        best_for="High-quality storytelling, long chapters, worldbuilding (32GB+ RAM)",
        requires_trust_remote_code=True,
        platform="nvidia",
        context_length=131072
    ),

    # === Lightweight Story Models (CPU-friendly) ===
    StorytellingModelInfo(
        model_id="roneneldan/TinyStories-33M",
        display_name="TinyStories 33M [Ultra Fast]",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=0.5,
        ram_gb=1.0,
        description="Tiny model trained on children's stories, extremely fast on CPU",
        best_for="Quick story drafts, testing, very low resource systems",
        requires_trust_remote_code=False,
        platform="any",
        context_length=2048
    ),
    StorytellingModelInfo(
        model_id="roneneldan/TinyStories-8M",
        display_name="TinyStories 8M [Fastest]",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=0.2,
        ram_gb=0.5,
        description="Ultra-lightweight story model, instant generation on any device",
        best_for="Rapid prototyping, CPU-only systems, story outlines",
        requires_trust_remote_code=False,
        platform="any",
        context_length=2048
    ),

    # === Lightweight Models (4-8GB VRAM) ===
    StorytellingModelInfo(
        model_id="microsoft/Phi-4-mini-instruct",
        display_name="Phi 4 Mini [Latest]",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=7.6,
        ram_gb=8.0,
        description="Microsoft's latest small model with excellent reasoning",
        best_for="General writing, rephrasing, creative tasks",
        requires_trust_remote_code=True,
        platform="any",
        context_length=4096
    ),
    StorytellingModelInfo(
        model_id="microsoft/Phi-3.5-mini-instruct",
        display_name="Phi 3.5 Mini",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=7.6,
        ram_gb=8.0,
        description="Improved Phi-3 with better multilingual support",
        best_for="Writing, translation, general tasks",
        requires_trust_remote_code=True,
        platform="any",
        context_length=4096
    ),
    StorytellingModelInfo(
        model_id="Qwen/Qwen2.5-3B-Instruct",
        display_name="Qwen 2.5 3B",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=6.0,
        ram_gb=6.0,
        description="Alibaba's efficient instruction-following model",
        best_for="Instructions, rephrasing, multilingual",
        requires_trust_remote_code=True,
        platform="any",
        context_length=32768
    ),
    StorytellingModelInfo(
        model_id="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
        display_name="TinyLlama 1.1B",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=2.2,
        ram_gb=4.0,
        description="Very fast and lightweight chat model",
        best_for="Quick suggestions, low-resource systems",
        requires_trust_remote_code=False,
        platform="any",
        context_length=2048
    ),

    # === Medium Models (8-16GB VRAM) ===
    StorytellingModelInfo(
        model_id="google/gemma-3-4b-it",
        display_name="Gemma 3 4B [Fits 16GB]",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=8.0,
        ram_gb=12.0,
        description="Google's efficient creative writing model",
        best_for="Creative writing, dialogue, chapter planning",
        requires_trust_remote_code=False,
        platform="nvidia",
        context_length=8192
    ),
    StorytellingModelInfo(
        model_id="Qwen/Qwen2.5-7B-Instruct",
        display_name="Qwen 2.5 7B [Recommended]",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=14.0,
        ram_gb=16.0,
        description="Excellent creative writing with very long context",
        best_for="All-around storytelling, fits comfortably in 16GB VRAM",
        requires_trust_remote_code=True,
        platform="nvidia",
        context_length=131072
    ),
    StorytellingModelInfo(
        model_id="meta-llama/Llama-3.2-3B-Instruct",
        display_name="Llama 3.2 3B",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=6.0,
        ram_gb=8.0,
        description="Meta's latest small Llama with strong performance",
        best_for="General writing, chat, creative tasks",
        requires_trust_remote_code=False,
        platform="any",
        context_length=131072
    ),
    StorytellingModelInfo(
        model_id="meta-llama/Llama-3.1-8B-Instruct",
        display_name="Llama 3.1 8B",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=16.0,
        ram_gb=16.0,
        description="Meta's powerful 8B model with excellent quality",
        best_for="High-quality writing, complex tasks",
        requires_trust_remote_code=False,
        platform="nvidia",
        context_length=131072
    ),
    StorytellingModelInfo(
        model_id="mistralai/Mistral-7B-Instruct-v0.3",
        display_name="Mistral 7B v0.3",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=14.0,
        ram_gb=16.0,
        description="Latest Mistral 7B with improved capabilities",
        best_for="High-quality writing, complex reasoning",
        requires_trust_remote_code=False,
        platform="nvidia",
        context_length=32768
    ),
    StorytellingModelInfo(
        model_id="mistralai/Ministral-8B-Instruct-2410",
        display_name="Ministral 8B (Oct 2024)",
        provider=StorytellingProvider.LOCAL_TORCH,
        vram_gb=16.0,
        ram_gb=16.0,
        description="Mistral's efficient 8B model optimized for edge",
        best_for="Quality writing, efficient inference",
        requires_trust_remote_code=False,
        platform="nvidia",
        context_length=131072
    ),
]


def get_available_storytelling_models() -> List[StorytellingModelInfo]:
    """Get available storytelling models based on platform.

    Returns:
        List of models appropriate for current hardware
    """
    from src.ai.mlx_utils import can_use_mlx

    if can_use_mlx():
        return MLX_STORYTELLING_MODELS
    else:
        return TORCH_STORYTELLING_MODELS


