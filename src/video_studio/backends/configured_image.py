"""Configured image backend — uses the model picked in
Settings → 🎨 Image Generation.

This is the unification point for image generation across the app.
The Visuals tab and the Video Studio both reference the same
``image_model_id`` in ``GenAIConfig`` — so writers pick their
model once and everything that renders an image (character
portraits, scene stills, per-action slide-deck images, single
image stills on the canvas) uses it.

We delegate the heavy lifting to ``ImageGenerationAgent`` so the
full provider matrix (MLX, PyTorch / diffusers, OpenAI DALL-E,
Stability AI, Replicate) keeps working without duplicating the
loader logic. This backend is a thin adapter that satisfies the
studio's ``ImageBackend`` protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import MemoryRequirements
from .image_base import (
    ImageBackend, ImageGenerationRequest, ImageGenerationResult,
)


class ConfiguredImageBackend(ImageBackend):
    name = "configured"
    label = "Configured Model (Settings → 🎨 Image Generation)"
    description = (
        "Uses the image model configured in Settings → "
        "🎨 Image Generation. Pick from FLUX / SDXL / SD 3.5 / "
        "MLX / cloud APIs there — every renderer in the app "
        "(Visuals tab, character portraits, scene cards, slide "
        "decks) honors the same choice."
    )
    output_kind = "image"

    # ------------------------------------------------------------------
    # Capability / install state
    # ------------------------------------------------------------------
    def is_installed(self) -> bool:
        """Treat this backend as installed when the user has both
        enabled image generation AND picked a real model. The
        downstream agent surfaces a precise error per-provider on
        the first generate call when a runtime piece is missing."""
        try:
            from src.config.genai_config import get_genai_config
            settings = get_genai_config().get_settings()
            if not settings.get("image_generation_enabled", True):
                return False
            model_id = settings.get("image_model_id", "") or ""
            return bool(model_id)
        except Exception:
            return False

    def install_instructions(self) -> str:
        return (
            "Open Settings → 🎨 Image Generation and pick an image "
            "model. For local models (MLX / diffusers) the Download "
            "button in that panel fetches the weights; cloud "
            "providers need an API key set on the API Keys tab.")

    def memory_requirements(self) -> MemoryRequirements:
        """Look up RAM/VRAM from the chosen model's catalog entry
        so the studio's pre-flight check can offer to evict other
        models when memory's tight. Searches ALL catalogs (MLX,
        Torch, Cloud) regardless of current platform so the lookup
        succeeds even when the writer flipped platforms or cross-
        configured. Conservative defaults when nothing matches."""
        try:
            from src.config.genai_config import (
                get_genai_config,
                MLX_IMAGE_MODELS, TORCH_IMAGE_MODELS,
                CLOUD_IMAGE_MODELS,
            )
            model_id = (
                get_genai_config().get("image_model_id", "") or "")
            for cat in (MLX_IMAGE_MODELS, TORCH_IMAGE_MODELS,
                        CLOUD_IMAGE_MODELS):
                for m in cat:
                    if m.model_id == model_id:
                        return MemoryRequirements(
                            vram_mb=int(m.vram_gb * 1024),
                            ram_mb=int(m.ram_gb * 1024),
                            notes=(
                                f"Model: {m.display_name} "
                                f"(provider: {m.provider.value})"))
        except Exception:
            pass
        return MemoryRequirements(
            vram_mb=6 * 1024, ram_mb=8 * 1024,
            notes="Configured model (catalog entry unknown).")

    def supports_character_refs(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate(
        self, request: ImageGenerationRequest,
    ) -> ImageGenerationResult:
        sidecar = request.output_path.with_suffix(
            request.output_path.suffix + ".json")
        try:
            from src.ai.image_generation_agent import (
                ImageGenerationAgent,
            )
        except Exception as e:
            return ImageGenerationResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=sidecar,
                error=(
                    "Image generation agent unavailable: "
                    f"{e}"))
        try:
            agent = ImageGenerationAgent()
        except Exception as e:
            return ImageGenerationResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=sidecar,
                error=f"Could not init image agent: {e}")
        # Fold character refs into the prompt so the chosen model
        # has likeness anchors — the agent's own enhancer handles
        # the heavier prompt-rewriting work via the prompt LLM.
        full_prompt = _compose_prompt_with_refs(
            request.prompt, request.character_refs)
        try:
            request.output_path.parent.mkdir(
                parents=True, exist_ok=True)
            result_path: Optional[Path] = agent._generate_image(
                prompt=full_prompt,
                save_path=request.output_path)
        except Exception as e:
            return ImageGenerationResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=sidecar,
                error=f"Generation failed: {e}")
        if result_path is None or not Path(result_path).exists():
            return ImageGenerationResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=sidecar,
                error=(
                    "Agent returned no image. Check the log for "
                    "provider-specific errors (missing API key, "
                    "weights not downloaded, etc.)."))
        out = Path(result_path)
        # Pull the resolved model id for the sidecar so the writer
        # can audit which model rendered which frame.
        try:
            from src.config.genai_config import get_genai_config
            settings = get_genai_config().get_settings()
            resolved_model = settings.get("image_model_id", "")
            resolved_provider = settings.get("image_provider", "")
        except Exception:
            resolved_model = ""
            resolved_provider = ""
        self._write_sidecar(
            sidecar, request, backend_name=self.name,
            extra={
                "model_id": resolved_model,
                "provider": resolved_provider,
                "full_prompt_used": full_prompt,
            })
        return ImageGenerationResult(
            success=True,
            output_path=out,
            sidecar_path=sidecar,
            is_placeholder=False,
            backend_metadata={
                "model_id": resolved_model,
                "provider": resolved_provider,
            })


def _compose_prompt_with_refs(
    prompt: str,
    character_refs: list,
) -> str:
    """Append character appearance prompts to the base prompt so
    the chosen model has likeness anchors. Mirrors the SDXL
    backend's helper of the same name."""
    base = (prompt or "").strip()
    parts = [base] if base else []
    for ref in character_refs or []:
        appearance = (
            ref.get("appearance_prompt", "") or "").strip()
        name = (ref.get("name", "") or "").strip()
        if name and appearance:
            parts.append(f"{name}: {appearance}")
        elif name:
            parts.append(name)
    return ". ".join(parts)
