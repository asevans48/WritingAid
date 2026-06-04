"""FLUX.1-schnell image backend (Black Forest Labs).

The fast public-Apache variant of FLUX.1 — ~24 GB weights, ~16 GB
VRAM at inference. Produces excellent quality at 4 steps (the
"schnell" / fast distill). Public model, no gating, so the HF
token isn't strictly required — we still pass it when configured
so rate-limited mirrors don't throttle.

For the ``FLUX.1-dev`` variant (license-gated, requires
acceptance), the same code works — point ``_FLUX_REPO_ID`` at the
``dev`` repo and the configured HF token covers the gate.
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


_FLUX_REPO_ID = "black-forest-labs/FLUX.1-schnell"
_FLUX_BYTES_ESTIMATE = 24 * 1024 * 1024 * 1024  # ~24 GB
_PIP_BYTES_ESTIMATE = 600 * 1024 * 1024


class FluxSchnellBackend(ImageBackend):
    name = "flux_schnell"
    label = "FLUX.1-schnell (Black Forest Labs, local)"
    description = (
        "FLUX.1-schnell — the fast Apache-licensed FLUX. Produces "
        "top-tier still images at 4 inference steps. ~24 GB "
        "weights, ~16 GB VRAM. Realistic on a 24 GB GPU; tight on "
        "12 GB without offload tricks; not workable on Apple "
        "Silicon under 32 GB.")
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
        lines = ["FLUX.1-schnell install:", ""]
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
        lines.append("  3. Download weights (~24 GB, one-time):")
        lines.append(f"     hf download {_FLUX_REPO_ID}")
        if not _hf_token.has_token():
            lines.append("")
            lines.append(
                "  Note: FLUX.1-schnell is Apache-licensed (no "
                "token required), but setting your HF token in "
                "Settings avoids rate-limited mirrors.")
        return "\n".join(lines)

    def memory_requirements(self) -> MemoryRequirements:
        return MemoryRequirements(
            vram_mb=16 * 1024,
            ram_mb=20 * 1024,
            notes=(
                "FLUX.1-schnell needs ~16 GB VRAM at full quality. "
                "12 GB GPUs can run with CPU offload at ~3× speed "
                "cost; the studio's pre-flight uses 16 GB as the "
                "safety bar."),
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
            label=f"Download FLUX.1-schnell weights ({_FLUX_REPO_ID})",
            command=_diffusers_repo_download_command(_FLUX_REPO_ID),
            check=lambda: _weights_cached(_FLUX_REPO_ID),
            env_overrides=_hf_token.env_overrides_with_token(),
            bytes_estimate=_FLUX_BYTES_ESTIMATE,
            seconds_estimate=max(
                60, int(_FLUX_BYTES_ESTIMATE / (50 * 1024 * 1024))),
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
            _FLUX_REPO_ID, **kwargs)
        # FLUX is large — on 12 GB GPUs enable CPU offload so users
        # don't OOM. On bigger cards the move-to-device path is
        # faster; we hit it via .to(device).
        try:
            import torch
            if (device == "cuda"
                    and torch.cuda.get_device_properties(0).total_memory
                    < 18 * 1024 * 1024 * 1024):
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
                    "FLUX.1-schnell not installed. Use Install / "
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
                error=f"Could not load FLUX pipeline: {e}",
            )
        full_prompt = _compose_prompt_with_refs(
            request.prompt, request.character_refs)
        try:
            import torch
            generator = None
            if request.seed is not None:
                generator = torch.Generator(
                    device="cpu").manual_seed(int(request.seed))
            # FLUX likes multiples of 16, schnell variant runs in 4
            # inference steps.
            w = max(512, (int(request.width) // 16) * 16)
            h = max(512, (int(request.height) // 16) * 16)
            result = pipe(
                prompt=full_prompt,
                width=w, height=h,
                num_inference_steps=4,
                guidance_scale=0.0,  # schnell — guidance unused
                generator=generator,
            )
            image = result.images[0]
        except Exception as e:
            return ImageGenerationResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=request.output_path.with_suffix(
                    request.output_path.suffix + ".json"),
                error=f"FLUX generation failed: {e}",
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
                error=f"Could not save FLUX image: {e}",
            )
        return ImageGenerationResult(
            success=True,
            output_path=out,
            sidecar_path=sidecar,
            is_placeholder=False,
            backend_metadata={"device": self._loaded_on_device},
        )
