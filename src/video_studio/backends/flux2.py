"""FLUX.2 image backend (Black Forest Labs).

FLUX.2 is the successor to FLUX.1 — higher quality, better prompt
adherence, improved consistency. Available in multiple variants:
  * flux2-schnell  — fast distill, Apache-licensed
  * flux2-dev      — research license, gated

This backend defaults to the public schnell variant. Switch to
``flux2-dev`` by changing ``_FLUX2_REPO_ID`` or configuring the
studio's model picker.
"""

from __future__ import annotations

import importlib
import sys
from typing import Any, List, Optional

from . import _hf_token
from .base import InstallStep, MemoryRequirements
from .image_base import (
    ImageBackend, ImageGenerationRequest, ImageGenerationResult,
)
from .ltx_video import (
    _diffusers_repo_download_command, _weights_cached,
)
from .sdxl import _compose_prompt_with_refs


_FLUX2_REPO_ID = "black-forest-labs/FLUX.2-klein-4B"
_FLUX2_BYTES_ESTIMATE = 10 * 1024 * 1024 * 1024  # ~10 GB
_PIP_BYTES_ESTIMATE = 600 * 1024 * 1024


class Flux2Backend(ImageBackend):
    name = "flux2"
    label = "FLUX.2 Klein 4B (Black Forest Labs, local)"
    description = (
        "FLUX.2 Klein 4B — fast 4-step generation from Black Forest "
        "Labs. Excellent quality-to-speed ratio, fits comfortably on "
        "12-16 GB GPUs. ~10 GB weights, ~10 GB VRAM.")
    output_kind = "image"

    def __init__(self) -> None:
        super().__init__()
        self._pipe: Any = None
        self._loaded_on_device: Optional[str] = None

    # ---- install detection ----
    def _has_diffusers(self) -> bool:
        try:
            importlib.import_module("diffusers")
            return True
        except Exception:
            return False

    def _has_torch_with_gpu(self) -> bool:
        try:
            import torch
            return torch.cuda.is_available() or (
                hasattr(torch.backends, "mps")
                and torch.backends.mps.is_available())
        except Exception:
            return False

    def is_installed(self) -> bool:
        return self._has_diffusers() and self._has_torch_with_gpu()

    def install_instructions(self) -> str:
        lines = ["FLUX.2 Klein 4B install:", ""]
        if not self._has_diffusers():
            lines.append(
                "  1. pip install --upgrade diffusers accelerate "
                "transformers sentencepiece protobuf")
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
        lines.append("  3. Download weights (~10 GB, one-time):")
        lines.append(f"     hf download {_FLUX2_REPO_ID}")
        if not _hf_token.has_token():
            lines.append("")
            lines.append(
                "  Note: Set your HF token in Settings to access "
                "gated models (Klein 4B may require acceptance).")
        return "\n".join(lines)

    def memory_requirements(self) -> MemoryRequirements:
        return MemoryRequirements(
            vram_mb=10 * 1024,
            ram_mb=16 * 1024,
            notes=(
                "FLUX.2 Klein 4B needs ~10 GB VRAM. Fits "
                "comfortably on 12-16 GB GPUs without offload."),
        )

    def supports_character_refs(self) -> bool:
        return True

    def install_steps(self) -> List[InstallStep]:
        steps: List[InstallStep] = []
        py = sys.executable
        if not self._has_diffusers():
            steps.append(InstallStep(
                label=(
                    "Install diffusers, accelerate, transformers, "
                    "sentencepiece, protobuf"),
                command=[
                    py, "-m", "pip", "install", "--upgrade",
                    "diffusers", "accelerate", "transformers",
                    "sentencepiece", "protobuf"],
                check=self._has_diffusers,
                bytes_estimate=_PIP_BYTES_ESTIMATE,
                seconds_estimate=180,
                required=True,
            ))
        steps.append(InstallStep(
            label=f"Download FLUX.2 weights ({_FLUX2_REPO_ID})",
            command=_diffusers_repo_download_command(_FLUX2_REPO_ID),
            check=lambda: _weights_cached(_FLUX2_REPO_ID),
            env_overrides=_hf_token.env_overrides_with_token(),
            bytes_estimate=_FLUX2_BYTES_ESTIMATE,
            seconds_estimate=max(
                60, int(_FLUX2_BYTES_ESTIMATE / (50 * 1024 * 1024))),
            required=True,
            is_large_download=True,
        ))
        return steps

    # ---- pipeline ----
    def _device_and_dtype(self):
        import torch
        if torch.cuda.is_available():
            cc = torch.cuda.get_device_capability(0)
            dtype = torch.bfloat16 if cc[0] >= 8 else torch.float16
            return "cuda", dtype
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps", torch.float16
        return "cpu", torch.float32

    def _ensure_pipeline(self):
        if self._pipe is not None:
            return self._pipe
        from diffusers import FluxPipeline
        device, dtype = self._device_and_dtype()
        token = _hf_token.get_token()
        kwargs = {"torch_dtype": dtype}
        if token:
            kwargs["token"] = token
        self._pipe = FluxPipeline.from_pretrained(
            _FLUX2_REPO_ID, **kwargs)
        try:
            import torch
            if (device == "cuda"
                    and torch.cuda.get_device_properties(0).total_memory
                    < 20 * 1024 * 1024 * 1024):
                self._pipe.enable_model_cpu_offload()
            else:
                self._pipe.to(device)
        except Exception:
            self._pipe.to(device)
        self._loaded_on_device = device
        return self._pipe

    def unload(self) -> None:
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
                    "FLUX.2 not installed. Use Install / "
                    "Help in the toolbar."),
            )
        try:
            pipe = self._ensure_pipeline()
        except Exception as e:
            return ImageGenerationResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=request.output_path.with_suffix(
                    request.output_path.suffix + ".json"),
                error=f"Could not load FLUX.2 pipeline: {e}",
            )
        full_prompt = _compose_prompt_with_refs(
            request.prompt, request.character_refs)
        try:
            import torch
            generator = None
            if request.seed is not None:
                generator = torch.Generator(
                    device="cpu").manual_seed(int(request.seed))
            w = max(512, (int(request.width) // 16) * 16)
            h = max(512, (int(request.height) // 16) * 16)
            result = pipe(
                prompt=full_prompt,
                width=w, height=h,
                num_inference_steps=4,
                guidance_scale=0.0,
                generator=generator,
            )
            image = result.images[0]
        except Exception as e:
            return ImageGenerationResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=request.output_path.with_suffix(
                    request.output_path.suffix + ".json"),
                error=f"FLUX.2 generation failed: {e}",
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
                    "num_inference_steps": 4,
                    "guidance_scale": 0.0,
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
                error=f"Could not save FLUX.2 image: {e}",
            )
        return ImageGenerationResult(
            success=True,
            output_path=out,
            sidecar_path=sidecar,
            is_placeholder=False,
            backend_metadata={"device": self._loaded_on_device},
        )
