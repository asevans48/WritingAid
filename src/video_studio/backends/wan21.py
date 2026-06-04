"""WAN 2.1 backend — install detection + invocation.

WAN 2.1 (Wan-Video/Wan2.1) is a text-to-video model from Tongyi /
Alibaba. Running it locally needs:
  * The ``diffusers`` Python package
  * Model weights (~10-30 GB depending on variant)
  * A GPU with enough VRAM (12 GB+ for the smaller variants)

We DON'T auto-install any of these — that's the user's choice. This
backend reports its install status, surfaces clear install steps,
and only attempts generation when the prerequisites are in place.

If you (the developer reading this later) want to flesh this out
into a working backend, the TODO block in ``generate`` is the only
place that needs changing — the request/result shape is stable.
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


# Hugging Face repo for the model. The 14B T2V variant is the
# "default" public flagship; smaller variants exist on the org page.
_WAN_REPO_ID = "Wan-AI/Wan2.1-T2V-14B"
# Approximate sizes — used to populate the progress dialog and the
# "this download is large" pre-confirmation. Updated when the org
# publishes new variants.
_PIP_BYTES_ESTIMATE = 600 * 1024 * 1024            # ~600 MB for deps
_MODEL_BYTES_ESTIMATE = 28 * 1024 * 1024 * 1024    # ~28 GB


class Wan21Backend(VideoBackend):
    name = "wan21"
    label = "WAN 2.1 (Wan-Video, local)"
    description = (
        "Local text-to-video generation via the Wan-Video/Wan2.1 "
        "model on Hugging Face. Requires diffusers, a Hugging Face "
        "cache of the weights (~10-30 GB), and a GPU (12 GB+ VRAM "
        "for the lighter variants). Heavy install — only enable "
        "when you're ready to render.")

    # -------- install detection --------
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

    def _has_huggingface_cli(self) -> bool:
        """Accept either the modern ``hf`` binary or the legacy
        ``huggingface-cli`` stub. The library API (``snapshot_download``)
        is the actual download path; this is just a "convenience tool
        available" check used by ``install_steps`` to decide whether
        to offer the optional pip-install step."""
        return (shutil.which("hf") is not None
                or shutil.which("huggingface-cli") is not None)

    def is_installed(self) -> bool:
        # Conservative: only "installed" when we have the library
        # AND a usable accelerator. The user can install diffusers
        # without a GPU but generation would be unusably slow.
        return self._has_diffusers() and self._has_torch_with_gpu()

    def install_instructions(self) -> str:
        steps = ["WAN 2.1 install (do these in order):", ""]
        if not self._has_diffusers():
            steps.append(
                "  1. Install diffusers + accelerate + transformers:")
            steps.append(
                "       pip install diffusers accelerate transformers")
        else:
            steps.append("  1. diffusers detected ✓")
        if not self._has_torch_with_gpu():
            steps.append("")
            steps.append(
                "  2. Install PyTorch with GPU support (CUDA or MPS).")
            steps.append(
                "       See https://pytorch.org/get-started/locally/")
        else:
            steps.append("  2. PyTorch with GPU/MPS detected ✓")
        if not self._has_huggingface_cli():
            steps.append("")
            steps.append("  3. Install Hugging Face CLI:")
            steps.append("       pip install -U \"huggingface_hub[cli]\"")
        else:
            steps.append("  3. huggingface-cli detected ✓")
        steps.append("")
        steps.append("  4. Download the model weights (one-time, large):")
        steps.append(
            "       huggingface-cli download Wan-AI/Wan2.1-T2V-14B")
        steps.append("     (substitute the variant you want — see")
        steps.append(
            "      https://huggingface.co/Wan-AI for available models)")
        return "\n".join(steps)

    def memory_requirements(self) -> MemoryRequirements:
        """WAN 2.1 14B T2V — empirical headroom for inference.

        ~14 GB VRAM gets the 14B variant going in float16; ~16 GB
        system RAM keeps offload buffers + the encoder happy.
        Smaller variants (1.3B) would use far less but the studio's
        ``is_installed()`` check doesn't tell which weights are
        present, so we declare the upper-bound and let the user
        override if they're running a smaller version.
        """
        return MemoryRequirements(
            vram_mb=14 * 1024,
            ram_mb=16 * 1024,
            notes=(
                "WAN 2.1 14B T2V needs ~14 GB free VRAM at "
                "inference. Smaller variants need less."),
        )

    def install_steps(self) -> List[InstallStep]:
        """Build an ordered list of install steps.

        Steps are idempotent — each one's ``check`` returns True when
        already satisfied, so the runner skips them on re-runs. Order:
          1. Install diffusers + accelerate + transformers (small)
          2. Install huggingface_hub CLI (small)
          3. Download the model weights (large; user-confirmed)

        We intentionally do NOT auto-install PyTorch — its install
        command depends on the user's CUDA/MPS/CPU setup and a wrong
        guess wastes hours. The install dialog detects this and shows
        a link to https://pytorch.org/get-started/locally/.
        """
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
        if not self._has_huggingface_cli():
            steps.append(InstallStep(
                label="Install huggingface_hub[cli] (download tool)",
                command=[py, "-m", "pip", "install", "--upgrade",
                         "huggingface_hub[cli]"],
                check=self._has_huggingface_cli,
                bytes_estimate=30 * 1024 * 1024,
                seconds_estimate=30,
                required=False,  # we fall back to library API
            ))
        # The weights download. Always offered — if the user has them
        # we let huggingface-cli short-circuit (it skips already-
        # cached files). The dialog confirms the multi-GB size before
        # invoking this step.
        steps.append(InstallStep(
            label=f"Download Wan2.1 weights ({_WAN_REPO_ID})",
            command=self._weights_download_command(),
            check=self._weights_likely_present,
            # Inject the configured HF token so gated / rate-limited
            # downloads work. No-op when the user hasn't set a token —
            # public models still download without auth.
            env_overrides=_hf_token.env_overrides_with_token(),
            bytes_estimate=_MODEL_BYTES_ESTIMATE,
            seconds_estimate=60 * 60,  # an hour on a typical link
            required=True,
            is_large_download=True,
        ))
        return steps

    def _weights_download_command(self) -> List[str]:
        """Download the weights using whichever path the environment
        actually supports.

        Preference order (canonical → fallback):

          1. The modern ``hf`` CLI (``huggingface_hub`` ≥ ~0.26
             renamed the binary from ``huggingface-cli`` to ``hf``
             and made ``huggingface-cli`` a deprecation stub that
             refuses to do real work).
          2. ``huggingface_hub.snapshot_download`` via
             ``python -c`` — the library API. Always available
             whenever ``huggingface_hub`` is importable, which is
             true as soon as the first install step (diffusers)
             has run, since diffusers pulls it in.
          3. Legacy ``huggingface-cli`` — kept as a final fallback
             for older envs where it still functions.

        We deliberately skip the broken
        ``python -m huggingface_hub.commands.huggingface_cli`` path
        — that module doesn't ship in any current release.
        """
        hf = shutil.which("hf")
        if hf:
            return [hf, "download", _WAN_REPO_ID]
        # Library form — repr() quotes the repo id so a hypothetical
        # future parameterized repo can't smuggle Python via -c.
        # Progress bars print to stderr → the runner streams them
        # via the subprocess.STDOUT redirect, so the user sees
        # download activity in real time.
        py_snippet = (
            "from huggingface_hub import snapshot_download; "
            f"snapshot_download({_WAN_REPO_ID!r})"
        )
        return [sys.executable, "-c", py_snippet]

    def _weights_likely_present(self) -> bool:
        """Best-effort check: does the HF cache already have the
        repo? We don't verify every file — that's huggingface_hub's
        job during download — just detect a non-empty snapshot
        folder so re-runs skip the multi-hour pull."""
        try:
            from huggingface_hub import constants, snapshot_download  # noqa: F401
            from huggingface_hub import HfFolder  # noqa: F401
            from pathlib import Path
            cache_dir = Path(constants.HF_HUB_CACHE).expanduser()
            # Repo dir mangles ``/`` to ``--`` in the cache filename.
            repo_dir = cache_dir / (
                "models--" + _WAN_REPO_ID.replace("/", "--"))
            if not repo_dir.exists():
                return False
            snapshots = repo_dir / "snapshots"
            if not snapshots.exists():
                return False
            # Any snapshot dir with at least one file counts.
            for snap in snapshots.iterdir():
                if any(snap.iterdir()):
                    return True
            return False
        except Exception:
            return False

    def supports_character_refs(self) -> bool:
        # WAN 2.1 doesn't currently support character-locking out of
        # the box; the backend can still pass appearance prompts
        # inline via the prompt itself. Mark False so the UI shows
        # the consistency caveat.
        return False

    def supported_durations(self) -> tuple:
        # WAN 2.1's typical limit is 5-10s per clip at the moment;
        # longer clips are stitched downstream.
        return (3.0, 10.0)

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
                    "WAN 2.1 backend not installed. "
                    "Open the Video Studio backend picker for "
                    "install instructions."),
            )
        # ----------------------------------------------------------
        # TODO: real generation goes here. The interface below is
        # stable; fill in the body when you're ready to ship real
        # rendering. The pattern (sketch):
        #
        #   from diffusers import WanPipeline
        #   pipe = WanPipeline.from_pretrained(
        #       "Wan-AI/Wan2.1-T2V-14B", torch_dtype=torch.float16)
        #   pipe.to("cuda")
        #   video = pipe(
        #       prompt=full_prompt,
        #       num_frames=int(request.duration_seconds * 16),
        #       generator=torch.manual_seed(request.seed or 0),
        #   ).frames[0]
        #   export_to_video(video, str(request.output_path), fps=16)
        #
        # Until that lands the user gets a clear error message
        # explaining the integration is pending rather than a
        # silent failure.
        # ----------------------------------------------------------
        return GenerationResult(
            success=False,
            output_path=request.output_path,
            sidecar_path=request.output_path.with_suffix(
                request.output_path.suffix + ".json"),
            error=(
                "WAN 2.1 generation not yet implemented in this "
                "build. The backend abstraction is in place — the "
                "diffusers call needs to be wired into generate(). "
                "See the TODO block in src/video_studio/backends/"
                "wan21.py."),
        )
