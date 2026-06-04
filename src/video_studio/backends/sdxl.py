"""Stable Diffusion XL image backend.

Loads ``stabilityai/stable-diffusion-xl-base-1.0`` via diffusers
and produces a single still per ``generate()`` call. Works on CUDA,
MPS, and CPU (slow). The pipeline is loaded once per backend
instance and cached so subsequent generations don't pay the
load-from-disk cost again.

We use the configured HF token where available so future gated
checkpoints and rate-limited mirrors work without manual env setup.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, List, Optional

from . import _hf_token
from .base import InstallStep, MemoryRequirements
from .image_base import (
    ImageBackend, ImageGenerationRequest, ImageGenerationResult,
)
from .ltx_video import (
    _diffusers_repo_download_command, _weights_cached,
)


_SDXL_REPO_ID = "stabilityai/stable-diffusion-xl-base-1.0"
_SDXL_BYTES_ESTIMATE = 14 * 1024 * 1024 * 1024  # ~14 GB
_PIP_BYTES_ESTIMATE = 600 * 1024 * 1024


class SDXLBackend(ImageBackend):
    name = "sdxl"
    label = "Stable Diffusion XL (Stability AI, local)"
    description = (
        "Stable Diffusion XL 1.0 base for image stills. ~14 GB "
        "weights, ~8 GB VRAM at inference. Works on CUDA, MPS "
        "(Apple Silicon), and CPU (slow). A solid default for "
        "scene-illustration stills when you don't need the absolute "
        "quality of FLUX.")
    output_kind = "image"

    def __init__(self) -> None:
        super().__init__()
        # Cache the loaded pipeline on the instance so generating
        # multiple scenes doesn't repeatedly reload from disk.
        self._pipe: Any = None
        self._loaded_on_device: Optional[str] = None

    # ---- install detection (shared shape with video backends) ----
    def _has_diffusers(self) -> bool:
        try:
            importlib.import_module("diffusers")
            return True
        except Exception:
            return False

    def _has_torch_with_gpu(self) -> bool:
        try:
            import torch  # noqa: F401
            return torch.cuda.is_available() or (
                hasattr(torch.backends, "mps")
                and torch.backends.mps.is_available())
        except Exception:
            return False

    def is_installed(self) -> bool:
        # CPU-only is technically possible but practically unusable
        # for SDXL (~10 minutes per image). Require an accelerator.
        return self._has_diffusers() and self._has_torch_with_gpu()

    def install_instructions(self) -> str:
        lines = ["SDXL install:", ""]
        if not self._has_diffusers():
            lines.append(
                "  1. pip install --upgrade diffusers accelerate "
                "transformers safetensors")
        else:
            lines.append("  1. diffusers detected ✓")
        if not self._has_torch_with_gpu():
            lines.append("")
            lines.append("  2. Install PyTorch with GPU support.")
            lines.append(
                "     See https://pytorch.org/get-started/locally/")
        else:
            lines.append("  2. PyTorch with GPU/MPS detected ✓")
        lines.append("")
        lines.append(
            f"  3. Download weights (~14 GB, one-time):")
        lines.append(f"     hf download {_SDXL_REPO_ID}")
        return "\n".join(lines)

    def memory_requirements(self) -> MemoryRequirements:
        return MemoryRequirements(
            vram_mb=8 * 1024,
            ram_mb=12 * 1024,
            notes=(
                "SDXL needs ~8 GB VRAM in FP16; the studio's "
                "pre-flight uses this as the safety bar."),
        )

    def supports_character_refs(self) -> bool:
        # We pass character_refs into the prompt at generate time
        # so likeness stays consistent across scenes. Not as strong
        # as a real DreamBooth/LoRA but a step toward consistency.
        return True

    def install_steps(self) -> List[InstallStep]:
        steps: List[InstallStep] = []
        py = sys.executable
        if not self._has_diffusers():
            steps.append(InstallStep(
                label=(
                    "Install diffusers, accelerate, transformers, "
                    "safetensors"),
                command=[
                    py, "-m", "pip", "install", "--upgrade",
                    "diffusers", "accelerate", "transformers",
                    "safetensors"],
                check=self._has_diffusers,
                bytes_estimate=_PIP_BYTES_ESTIMATE,
                seconds_estimate=180,
                required=True,
            ))
        steps.append(InstallStep(
            label=f"Download SDXL weights ({_SDXL_REPO_ID})",
            command=_diffusers_repo_download_command(_SDXL_REPO_ID),
            check=lambda: _weights_cached(_SDXL_REPO_ID),
            env_overrides=_hf_token.env_overrides_with_token(),
            bytes_estimate=_SDXL_BYTES_ESTIMATE,
            seconds_estimate=max(
                60, int(_SDXL_BYTES_ESTIMATE / (50 * 1024 * 1024))),
            required=True,
            is_large_download=True,
        ))
        return steps

    # ---- pipeline lifecycle ----
    def _device_and_dtype(self):
        """Pick the best accelerator + dtype available right now.

        Order: CUDA bfloat16/fp16 → MPS fp16 → CPU fp32. Picked at
        load time so a backend instance survives a torch hot-swap.
        """
        import torch
        if torch.cuda.is_available():
            # bfloat16 on Ampere (sm_80+), float16 otherwise.
            cc = torch.cuda.get_device_capability(0)
            dtype = (torch.bfloat16
                     if cc[0] >= 8 else torch.float16)
            return "cuda", dtype
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps", torch.float16
        return "cpu", torch.float32

    def _ensure_pipeline(self):
        """Lazy-load the diffusers pipeline. Cached for subsequent
        generations. Returns the pipeline ready to call."""
        if self._pipe is not None:
            return self._pipe
        import torch  # noqa: F401  (loaded for side effects)
        from diffusers import StableDiffusionXLPipeline
        device, dtype = self._device_and_dtype()
        token = _hf_token.get_token()
        kwargs = {"torch_dtype": dtype, "use_safetensors": True}
        if token:
            kwargs["token"] = token
        self._pipe = StableDiffusionXLPipeline.from_pretrained(
            _SDXL_REPO_ID, **kwargs)
        self._pipe.to(device)
        # Memory-saver: SDXL's slicing tricks let it run on smaller
        # GPUs at a slight speed cost. Cheap to enable; if VRAM
        # is plentiful diffusers no-ops them effectively.
        try:
            self._pipe.enable_attention_slicing()
            self._pipe.enable_vae_slicing()
        except Exception:
            pass
        self._loaded_on_device = device
        return self._pipe

    def unload(self) -> None:
        """Drop the cached pipeline so the studio's resource manager
        can reclaim VRAM. Safe to call when nothing is loaded."""
        self._pipe = None
        self._loaded_on_device = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                if hasattr(torch.mps, "empty_cache"):
                    torch.mps.empty_cache()
        except Exception:
            pass

    # ---- generation ----
    def generate(
        self, request: ImageGenerationRequest,
    ) -> ImageGenerationResult:
        if not self.is_installed():
            return ImageGenerationResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=request.output_path.with_suffix(
                    request.output_path.suffix + ".json"),
                error=(
                    "SDXL not installed. Use Install / Help in the "
                    "toolbar."),
            )
        try:
            pipe = self._ensure_pipeline()
        except Exception as e:
            return ImageGenerationResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=request.output_path.with_suffix(
                    request.output_path.suffix + ".json"),
                error=f"Could not load SDXL pipeline: {e}",
            )
        # Compose the prompt with any character reference appearance
        # prompts so likeness has a fighting chance of being
        # consistent across scenes that name the same character.
        full_prompt = _compose_prompt_with_refs(
            request.prompt, request.character_refs)
        try:
            import torch
            generator = None
            if request.seed is not None:
                # Use a CPU generator — works across CUDA/MPS/CPU.
                generator = torch.Generator(
                    device="cpu").manual_seed(int(request.seed))
            # Clamp dimensions to multiples of 8 (SDXL requirement)
            # and the model's native 1024-ish window — odd sizes
            # produce artifacts.
            w = max(512, (int(request.width) // 8) * 8)
            h = max(512, (int(request.height) // 8) * 8)
            result = pipe(
                prompt=full_prompt,
                width=w, height=h,
                num_inference_steps=25,
                guidance_scale=7.0,
                generator=generator,
            )
            image = result.images[0]
        except Exception as e:
            return ImageGenerationResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=request.output_path.with_suffix(
                    request.output_path.suffix + ".json"),
                error=f"SDXL generation failed: {e}",
            )
        try:
            out = request.output_path
            out.parent.mkdir(parents=True, exist_ok=True)
            image.save(str(out), format="PNG")
            sidecar = out.with_suffix(out.suffix + ".json")
            self._write_sidecar(
                sidecar, request, backend_name=self.name,
                extra={
                    "device": self._loaded_on_device,
                    "num_inference_steps": 25,
                    "guidance_scale": 7.0,
                    "actual_width": w,
                    "actual_height": h,
                    "full_prompt_used": full_prompt,
                })
        except Exception as e:
            return ImageGenerationResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=request.output_path.with_suffix(
                    request.output_path.suffix + ".json"),
                error=f"Could not save SDXL image: {e}",
            )
        return ImageGenerationResult(
            success=True,
            output_path=out,
            sidecar_path=sidecar,
            is_placeholder=False,
            backend_metadata={"device": self._loaded_on_device},
        )


# ---------------------------------------------------------------------
# Shared helper — used by SDXL and FLUX
# ---------------------------------------------------------------------
def _compose_prompt_with_refs(
    base_prompt: str, character_refs: List[dict],
) -> str:
    """Append each character's appearance_prompt to the user's prompt.

    Trivial prompt-engineering for likeness consistency: by
    repeating the character's appearance description on every
    scene's prompt, the same name maps to a similar visual.
    """
    if not character_refs:
        return base_prompt
    appearance_bits: List[str] = []
    for ref in character_refs:
        name = (ref.get("name") or "").strip()
        appearance = (ref.get("appearance_prompt") or "").strip()
        if name and appearance:
            appearance_bits.append(f"{name}: {appearance}")
    if not appearance_bits:
        return base_prompt
    return base_prompt + " | character details: " + "; ".join(
        appearance_bits)
