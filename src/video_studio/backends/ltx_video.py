"""LTX-Video backend (Lightricks).

The lightest text-to-video model on the registry — ~8–12 GB VRAM,
~9 GB weights download. Diffusers-native, MPS-supported, and fast
enough that a 4-second clip turns around in seconds on a 4090 and
under a minute on Apple Silicon. Practical default for both the
MacBook Pro target (32 GB unified) and the 12 GB Windows GPU
target.

Follows the same install + generate scaffold as the WAN 2.1
backend; the real ``generate()`` body is a TODO until the developer
flips the switch on the diffusers call. ``is_installed`` is honest
about what's present so the studio's pre-flight check works
end-to-end today.
"""

from __future__ import annotations

import importlib
import shutil
import sys
from typing import List

from . import _hf_token
from .base import (
    GenerationRequest, GenerationResult, InstallStep,
    MemoryRequirements, VideoBackend,
)


_LTX_REPO_ID = "Lightricks/LTX-Video"
_PIP_BYTES_ESTIMATE = 600 * 1024 * 1024       # ~600 MB for diffusers etc.
_MODEL_BYTES_ESTIMATE = 9 * 1024 * 1024 * 1024  # ~9 GB weights


class LtxVideoBackend(VideoBackend):
    name = "ltx_video"
    label = "LTX-Video (Lightricks, local)"
    description = (
        "Fast 2B-parameter text-to-video model from Lightricks. "
        "Designed for low-VRAM systems — works on a MacBook Pro "
        "via MPS and on a 12 GB GPU on Windows/Linux. ~9 GB "
        "weights, ~8–12 GB VRAM at inference. The most practical "
        "everyday choice if you don't have a 24 GB+ card.")

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
        # MPS works for LTX so we accept it (unlike heavier models
        # where we'd insist on CUDA). The studio's resource manager
        # still checks VRAM headroom at generate time.
        return self._has_diffusers() and self._has_torch_with_gpu()

    def install_instructions(self) -> str:
        lines = ["LTX-Video install:", ""]
        if not self._has_diffusers():
            lines.append(
                "  1. pip install --upgrade diffusers accelerate "
                "transformers")
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
            f"  3. Download weights (one-time, ~9 GB):")
        lines.append(f"     hf download {_LTX_REPO_ID}")
        lines.append("     (or huggingface-cli download …)")
        return "\n".join(lines)

    def memory_requirements(self) -> MemoryRequirements:
        return MemoryRequirements(
            vram_mb=12 * 1024,
            ram_mb=14 * 1024,
            notes=(
                "LTX-Video runs in ~8 GB VRAM at 512×512 and "
                "~12 GB at higher resolutions. The studio's "
                "pre-flight check uses the higher number for "
                "safety."),
        )

    def supports_character_refs(self) -> bool:
        return False

    def supported_durations(self) -> tuple:
        return (1.0, 10.0)

    def install_steps(self) -> List[InstallStep]:
        steps: List[InstallStep] = []
        py = sys.executable
        if not self._has_diffusers():
            steps.append(InstallStep(
                label="Install diffusers, accelerate, transformers",
                command=[py, "-m", "pip", "install", "--upgrade",
                         "diffusers", "accelerate", "transformers"],
                check=self._has_diffusers,
                bytes_estimate=_PIP_BYTES_ESTIMATE,
                seconds_estimate=120,
                required=True,
            ))
        steps.append(InstallStep(
            label=f"Download LTX-Video weights ({_LTX_REPO_ID})",
            command=_diffusers_repo_download_command(_LTX_REPO_ID),
            check=lambda: _weights_cached(_LTX_REPO_ID),
            env_overrides=_hf_token.env_overrides_with_token(),
            bytes_estimate=_MODEL_BYTES_ESTIMATE,
            seconds_estimate=20 * 60,
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
                    "LTX-Video backend not installed. Use "
                    "Install / Help in the toolbar."),
            )
        # ----------------------------------------------------------
        # TODO: real generation. Pattern:
        #   from diffusers import LTXPipeline
        #   pipe = LTXPipeline.from_pretrained(
        #       _LTX_REPO_ID, torch_dtype=torch.bfloat16)
        #   pipe.to(_pick_device())
        #   video = pipe(prompt=request.prompt,
        #                num_frames=int(request.duration_seconds * 24),
        #                width=704, height=480,
        #                generator=torch.manual_seed(request.seed or 0)
        #                ).frames[0]
        #   export_to_video(video, str(request.output_path), fps=24)
        # ----------------------------------------------------------
        return GenerationResult(
            success=False,
            output_path=request.output_path,
            sidecar_path=request.output_path.with_suffix(
                request.output_path.suffix + ".json"),
            error=(
                "LTX-Video generation not yet wired in. The backend "
                "abstraction is in place — see the TODO block in "
                "src/video_studio/backends/ltx_video.py for the "
                "diffusers call to add."),
        )


# ---------------------------------------------------------------------
# Module helpers — shared with the other diffusers/HF backends so we
# don't duplicate the "hf vs library form" logic in every backend.
# ---------------------------------------------------------------------
def _diffusers_repo_download_command(repo_id: str) -> List[str]:
    """Return the command that downloads ``repo_id`` from HF.

    Preference order: modern ``hf`` CLI → ``snapshot_download``
    library form via ``python -c``. Avoids the broken
    ``python -m huggingface_hub.commands.huggingface_cli`` path
    that some versions don't ship.
    """
    hf = shutil.which("hf")
    if hf:
        return [hf, "download", repo_id]
    snippet = (
        "from huggingface_hub import snapshot_download; "
        f"snapshot_download({repo_id!r})"
    )
    return [sys.executable, "-c", snippet]


def _weights_cached(repo_id: str) -> bool:
    """Best-effort: does the HF cache already have ``repo_id`` with
    at least one non-empty snapshot? Used by InstallStep.check so
    re-running the installer skips downloads that completed before.
    """
    try:
        from huggingface_hub import constants
        from pathlib import Path
        cache_dir = Path(constants.HF_HUB_CACHE).expanduser()
        repo_dir = cache_dir / (
            "models--" + repo_id.replace("/", "--"))
        if not repo_dir.exists():
            return False
        snapshots = repo_dir / "snapshots"
        if not snapshots.exists():
            return False
        for snap in snapshots.iterdir():
            if any(snap.iterdir()):
                return True
        return False
    except Exception:
        return False
