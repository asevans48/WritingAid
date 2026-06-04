"""CogVideoX backends — 2B and 5B variants.

Two registry entries that share a single implementation class.
The 2B variant runs comfortably in ~5 GB VRAM (fits the 12 GB
Windows target AND Apple Silicon MPS); the 5B variant needs ~13 GB
and only fits comfortably on 24 GB GPUs.

Like the WAN 2.1 backend, ``generate()`` is a labeled TODO until
the developer wires the diffusers ``CogVideoXPipeline`` call. The
install + memory-check + UI flow all work today via the shared
backend abstraction.
"""

from __future__ import annotations

import importlib
import sys
from typing import List

from . import _hf_token
from .base import (
    GenerationRequest, GenerationResult, InstallStep,
    MemoryRequirements, VideoBackend,
)
from .ltx_video import (
    _diffusers_repo_download_command, _weights_cached,
)


_PIP_BYTES_ESTIMATE = 600 * 1024 * 1024


class _CogVideoXBase(VideoBackend):
    """Shared base. Subclasses set repo id, label, size, and memory."""

    repo_id: str = ""
    weights_bytes: int = 0

    # ---- install detection ----
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
        return self._has_diffusers() and self._has_torch_with_gpu()

    def install_instructions(self) -> str:
        lines = [f"{self.label} install:", ""]
        if not self._has_diffusers():
            lines.append(
                "  1. pip install --upgrade diffusers accelerate "
                "transformers sentencepiece")
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
        weights_gb = self.weights_bytes // (1024 ** 3)
        lines.append(
            f"  3. Download weights (~{weights_gb} GB, one-time):")
        lines.append(f"     hf download {self.repo_id}")
        return "\n".join(lines)

    def supports_character_refs(self) -> bool:
        return False

    def install_steps(self) -> List[InstallStep]:
        steps: List[InstallStep] = []
        py = sys.executable
        if not self._has_diffusers():
            steps.append(InstallStep(
                label=(
                    "Install diffusers, accelerate, transformers, "
                    "sentencepiece"),
                command=[
                    py, "-m", "pip", "install", "--upgrade",
                    "diffusers", "accelerate", "transformers",
                    "sentencepiece"],
                check=self._has_diffusers,
                bytes_estimate=_PIP_BYTES_ESTIMATE,
                seconds_estimate=180,
                required=True,
            ))
        weights_gb = self.weights_bytes // (1024 ** 3)
        repo = self.repo_id
        steps.append(InstallStep(
            label=f"Download {self.label.split(' (')[0]} weights "
                  f"({repo}, ~{weights_gb} GB)",
            command=_diffusers_repo_download_command(repo),
            check=lambda repo=repo: _weights_cached(repo),
            env_overrides=_hf_token.env_overrides_with_token(),
            bytes_estimate=self.weights_bytes,
            # Rough estimate at 50 MB/s download — actual varies.
            seconds_estimate=max(
                60, int(self.weights_bytes / (50 * 1024 * 1024))),
            required=True,
            is_large_download=True,
        ))
        return steps

    def generate(
        self, request: GenerationRequest,
    ) -> GenerationResult:
        if not self.is_installed():
            return GenerationResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=request.output_path.with_suffix(
                    request.output_path.suffix + ".json"),
                error=(
                    f"{self.label} not installed. Use Install / "
                    "Help in the toolbar."),
            )
        # ----------------------------------------------------------
        # TODO: real generation. Pattern:
        #   from diffusers import CogVideoXPipeline
        #   pipe = CogVideoXPipeline.from_pretrained(
        #       self.repo_id, torch_dtype=torch.bfloat16)
        #   pipe.to(_pick_device())
        #   video = pipe(
        #       prompt=request.prompt,
        #       num_frames=49,  # CogVideoX outputs ~6s at 8 fps
        #       generator=torch.manual_seed(request.seed or 0)
        #   ).frames[0]
        #   export_to_video(video, str(request.output_path), fps=8)
        # ----------------------------------------------------------
        return GenerationResult(
            success=False,
            output_path=request.output_path,
            sidecar_path=request.output_path.with_suffix(
                request.output_path.suffix + ".json"),
            error=(
                f"{self.label} generation not yet wired in. "
                "The backend abstraction is in place — see the TODO "
                "block in src/video_studio/backends/cogvideox.py."),
        )


class CogVideoX2BBackend(_CogVideoXBase):
    name = "cogvideox_2b"
    label = "CogVideoX-2B (Zhipu / Tsinghua, local)"
    description = (
        "2B-parameter text-to-video model. The lightest serious "
        "option — fits in ~5 GB VRAM, runs on MPS, and matches "
        "older 10B+ models for short clips. Strong choice for the "
        "12 GB GPU target and Apple Silicon."
    )
    repo_id = "THUDM/CogVideoX-2b"
    weights_bytes = 5 * 1024 * 1024 * 1024  # ~5 GB

    def memory_requirements(self) -> MemoryRequirements:
        return MemoryRequirements(
            vram_mb=6 * 1024,
            ram_mb=10 * 1024,
            notes=(
                "CogVideoX-2B fits in ~5 GB at FP16. The "
                "studio's pre-flight uses 6 GB for safety."),
        )

    def supported_durations(self) -> tuple:
        # CogVideoX produces a fixed ~6s clip at 8 fps in its
        # default config; longer outputs come from stitching.
        return (4.0, 6.0)


class CogVideoX5BBackend(_CogVideoXBase):
    name = "cogvideox_5b"
    label = "CogVideoX-5B (Zhipu / Tsinghua, local)"
    description = (
        "5B-parameter variant — markedly higher quality than the 2B "
        "model. Needs ~13 GB VRAM at inference, so only fits "
        "comfortably on a 24 GB GPU (RTX 4090 etc.). Worth the "
        "extra memory if you have it.")
    repo_id = "THUDM/CogVideoX-5b"
    weights_bytes = 14 * 1024 * 1024 * 1024  # ~14 GB

    def memory_requirements(self) -> MemoryRequirements:
        return MemoryRequirements(
            vram_mb=14 * 1024,
            ram_mb=18 * 1024,
            notes=(
                "CogVideoX-5B needs ~13 GB VRAM in BF16. Doesn't "
                "fit on a 12 GB GPU without offload tricks that "
                "are slow; use CogVideoX-2B instead on those."),
        )

    def supported_durations(self) -> tuple:
        return (4.0, 6.0)
