"""Configuration for generative AI models (image, audio, video generation).

Separate from LLM config to allow different model choices for different modalities.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum


class ImageGenProvider(Enum):
    """Available image generation providers."""
    LOCAL_MLX = "local_mlx"  # Apple Silicon with MLX
    LOCAL_TORCH = "local_torch"  # NVIDIA/AMD with PyTorch
    OPENAI_DALLE = "openai_dalle"  # DALL-E 3
    STABILITY_AI = "stability_ai"  # Stable Diffusion via API
    REPLICATE = "replicate"  # Various models via Replicate


@dataclass
class ImageGenModelInfo:
    """Information about an image generation model."""
    model_id: str
    display_name: str
    provider: ImageGenProvider
    vram_gb: float
    ram_gb: float
    description: str
    best_for: str
    requires_api_key: bool = False
    platform: str = "any"  # "apple_silicon", "nvidia", "amd", "any"


# MLX Models for Apple Silicon (M1/M2/M3/M4/M5)
MLX_IMAGE_MODELS: List[ImageGenModelInfo] = [
    ImageGenModelInfo(
        model_id="mflux/flux2-klein-9b",
        display_name="FLUX 2 Klein 9B (Ultra Quality)",
        provider=ImageGenProvider.LOCAL_MLX,
        vram_gb=32.0,
        ram_gb=32.0,
        description="FLUX 2 Klein 9B - state-of-the-art 4-step generation (Jan 2026)",
        best_for="Highest quality character portraits and scenes with fast 4-step generation",
        platform="apple_silicon"
    ),
    ImageGenModelInfo(
        model_id="mflux/flux2-klein-4b",
        display_name="FLUX 2 Klein 4B (Fast)",
        provider=ImageGenProvider.LOCAL_MLX,
        vram_gb=15.0,
        ram_gb=16.0,
        description="FLUX 2 Klein 4B - fast 4-step generation with high quality",
        best_for="Fast high-quality generations, lower memory usage",
        platform="apple_silicon"
    ),
    ImageGenModelInfo(
        model_id="mflux/flux-schnell-4bit",
        display_name="FLUX 1 Schnell 4-bit (Fast)",
        provider=ImageGenProvider.LOCAL_MLX,
        vram_gb=6.0,
        ram_gb=8.0,
        description="Fast 4-bit quantized FLUX model optimized for Apple Silicon",
        best_for="Quick iterations, character concepts, fast generation",
        platform="apple_silicon"
    ),
    ImageGenModelInfo(
        model_id="mflux/flux-dev-4bit",
        display_name="FLUX 1 Dev 4-bit (Quality)",
        provider=ImageGenProvider.LOCAL_MLX,
        vram_gb=10.0,
        ram_gb=16.0,
        description="High-quality 4-bit FLUX model, 12B parameters",
        best_for="Character portraits, detailed scenes, quality over speed",
        platform="apple_silicon"
    ),
    ImageGenModelInfo(
        model_id="argmax/stable-diffusion-xl-base-1.0",
        display_name="Stable Diffusion XL (SDXL)",
        provider=ImageGenProvider.LOCAL_MLX,
        vram_gb=8.0,
        ram_gb=12.0,
        description="SDXL 1.0 optimized for Apple Silicon with Core ML",
        best_for="General purpose, wide variety of styles",
        platform="apple_silicon"
    ),
    ImageGenModelInfo(
        model_id="argmax/stable-diffusion-2-1",
        display_name="Stable Diffusion 2.1",
        provider=ImageGenProvider.LOCAL_MLX,
        vram_gb=6.0,
        ram_gb=8.0,
        description="Fast SD 2.1 for quick generations",
        best_for="Fast iterations, concept art, lower memory",
        platform="apple_silicon"
    ),
]

# PyTorch Models for NVIDIA GPUs
TORCH_IMAGE_MODELS: List[ImageGenModelInfo] = [
    ImageGenModelInfo(
        model_id="black-forest-labs/FLUX.1-dev",
        display_name="FLUX.1 Dev (12B)",
        provider=ImageGenProvider.LOCAL_TORCH,
        vram_gb=20.0,
        ram_gb=32.0,
        description="State-of-the-art FLUX model from Black Forest Labs",
        best_for="Highest quality character portraits, detailed scenes",
        platform="nvidia"
    ),
    ImageGenModelInfo(
        model_id="black-forest-labs/FLUX.1-schnell",
        display_name="FLUX.1 Schnell (12B, Fast)",
        provider=ImageGenProvider.LOCAL_TORCH,
        vram_gb=16.0,
        ram_gb=24.0,
        description="Fast FLUX variant, fewer steps needed",
        best_for="Quick high-quality generations",
        platform="nvidia"
    ),
    ImageGenModelInfo(
        model_id="stabilityai/stable-diffusion-xl-base-1.0",
        display_name="Stable Diffusion XL 1.0",
        provider=ImageGenProvider.LOCAL_TORCH,
        vram_gb=12.0,
        ram_gb=16.0,
        description="SDXL 1.0 with excellent prompt following",
        best_for="General purpose, wide variety of styles",
        platform="nvidia"
    ),
    ImageGenModelInfo(
        model_id="stabilityai/stable-diffusion-xl-refiner-1.0",
        display_name="SDXL Refiner 1.0",
        provider=ImageGenProvider.LOCAL_TORCH,
        vram_gb=12.0,
        ram_gb=16.0,
        description="SDXL refiner for upscaling and detail enhancement",
        best_for="Refining SDXL outputs, adding detail",
        platform="nvidia"
    ),
    ImageGenModelInfo(
        model_id="runwayml/stable-diffusion-v1-5",
        display_name="Stable Diffusion 1.5",
        provider=ImageGenProvider.LOCAL_TORCH,
        vram_gb=6.0,
        ram_gb=8.0,
        description="Classic SD 1.5, widely supported and fast",
        best_for="Fast iterations, broad compatibility",
        platform="nvidia"
    ),
]

# Cloud API Models
CLOUD_IMAGE_MODELS: List[ImageGenModelInfo] = [
    ImageGenModelInfo(
        model_id="dall-e-3",
        display_name="DALL-E 3 (OpenAI)",
        provider=ImageGenProvider.OPENAI_DALLE,
        vram_gb=0.0,
        ram_gb=0.0,
        description="OpenAI's DALL-E 3, excellent at following prompts",
        best_for="High-quality generations without local hardware",
        requires_api_key=True,
        platform="any"
    ),
    ImageGenModelInfo(
        model_id="stable-diffusion-xl-1024-v1-0",
        display_name="SDXL via Stability AI API",
        provider=ImageGenProvider.STABILITY_AI,
        vram_gb=0.0,
        ram_gb=0.0,
        description="SDXL via Stability AI's cloud API",
        best_for="Cloud-based SDXL without local compute",
        requires_api_key=True,
        platform="any"
    ),
]


def get_available_image_models() -> List[ImageGenModelInfo]:
    """Get available image generation models based on platform.

    Returns:
        List of models appropriate for current hardware
    """
    from src.ai.mlx_utils import can_use_mlx

    if can_use_mlx():
        # Apple Silicon - return MLX models + cloud
        return MLX_IMAGE_MODELS + CLOUD_IMAGE_MODELS
    else:
        # NVIDIA/AMD/Intel - return PyTorch models + cloud
        return TORCH_IMAGE_MODELS + CLOUD_IMAGE_MODELS


class GenAIConfig:
    """Configuration manager for generative AI models."""

    def __init__(self, config_dir: Optional[Path] = None):
        """Initialize GenAI configuration.

        Args:
            config_dir: Directory for config files (default: ~/.writer_platform)
        """
        if config_dir is None:
            config_dir = Path.home() / ".writer_platform"

        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / "genai_config.json"

        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Load or create config
        self.settings = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file or create default."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading genai config: {e}, using defaults")
                return self._get_default_config()
        else:
            config = self._get_default_config()
            self._save_config(config)
            return config

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration."""
        from src.ai.mlx_utils import can_use_mlx

        # Platform-specific defaults
        if can_use_mlx():
            default_provider = "local_mlx"
            default_model = "mflux/flux2-klein-9b"  # Use FLUX 2 Klein 9B for 32GB RAM
        else:
            default_provider = "local_torch"
            default_model = "black-forest-labs/FLUX.1-dev"

        # Get platform-specific default for prompt enhancement LLM
        from src.ai.agent_suite import get_default_local_model
        default_prompt_llm = get_default_local_model()

        # FLUX-2 defaults to 4 steps, FLUX-1 uses 20 steps
        default_steps = 4 if "flux2" in default_model.lower() else 20

        return {
            # Image Generation
            "image_generation_enabled": True,
            "image_provider": default_provider,
            "image_model_id": default_model,
            "image_width": 1024,
            "image_height": 1024,
            "image_num_inference_steps": default_steps,
            "image_guidance_scale": 7.5,
            "image_negative_prompt": "blurry, low quality, distorted, deformed, ugly, bad anatomy",

            # Prompt Enhancement (separate LLM/SLM for GenAI prompt generation)
            "use_prompt_enhancement": True,  # Use LLM to enhance prompts
            "prompt_llm_provider": "local",  # "local", "claude", "chatgpt", "gemini"
            "prompt_llm_model_id": default_prompt_llm,  # For local: MLX/PyTorch model
            "prompt_llm_cloud_model": "claude-3-5-sonnet-20241022",  # For cloud providers
            "prompt_enhancement_style": "detailed",  # "concise", "detailed", "artistic"

            # Cloud API Keys (separate from main LLM keys in ai_config)
            "stability_ai_key": "",
            "replicate_api_key": "",
            "dalle_api_key": "",  # Can use same as OpenAI or separate
            "huggingface_token": "",  # For downloading gated models like FLUX-2

            # Character-Specific Settings
            "include_character_context": True,  # Use character backstory/personality in prompts
            "character_prompt_weight": 0.8,  # How much to weight character description vs style

            # Advanced Settings
            "image_seed": -1,  # -1 for random
            "image_batch_size": 1,
            "save_generated_images": True,
            "image_output_dir": str(self.config_dir / "generated_images"),
            "save_prompts": True,  # Save generated prompts alongside images
        }

    def _save_config(self, config: Dict[str, Any]):
        """Save configuration to file."""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Error saving genai config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.settings.get(key, default)

    def set(self, key: str, value: Any):
        """Set a configuration value and save."""
        self.settings[key] = value
        self._save_config(self.settings)

    def get_settings(self) -> Dict[str, Any]:
        """Get all settings."""
        return self.settings.copy()

    def update_settings(self, updates: Dict[str, Any]):
        """Update multiple settings at once."""
        self.settings.update(updates)
        self._save_config(self.settings)


# Global instance
_genai_config = None


def get_genai_config() -> GenAIConfig:
    """Get the global GenAI configuration instance."""
    global _genai_config
    if _genai_config is None:
        _genai_config = GenAIConfig()
    return _genai_config
