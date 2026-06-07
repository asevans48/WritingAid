"""Abstract video backend.

A backend takes a prompt + parameters and produces a video file. The
studio is agnostic about *how* the video is rendered — local model,
cloud API, placeholder generator, etc. — as long as the backend
implements this surface.

Backends self-report their install status so the UI can offer install
guidance (links / commands) without spawning subprocesses behind the
user's back. We never auto-install — that's a footgun for an
end-user app, especially when models are tens of gigabytes.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class GenerationRequest:
    """One request to a backend.

    The backend reads ``prompt`` and ``duration_seconds``; the
    other fields are optional grounding the backend can use if it
    supports them.
    """
    prompt: str
    duration_seconds: float
    output_path: Path
    scene_name: str = ""
    seed: Optional[int] = None
    # Each character is a dict shaped like
    # {"name": ..., "appearance_prompt": ..., "seed": ...}.
    # Backends that don't support character grounding can ignore.
    character_refs: List[Dict[str, Any]] = field(default_factory=list)
    # Optional context strings the AI director extracts from the
    # chapter / plot / worldbuilding via graph RAG. Backends that
    # can take longer prompts can fold these in.
    chapter_context: str = ""
    plot_context: str = ""
    worldbuilding_context: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationResult:
    """What the backend hands back after generating."""
    success: bool
    output_path: Path
    sidecar_path: Path
    is_placeholder: bool = False
    error: str = ""
    backend_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryRequirements:
    """Best-effort RAM / VRAM headroom a backend needs to load and run.

    Values are MEGABYTES. ``vram_mb`` is the dedicated GPU memory the
    backend wants free at the moment ``generate()`` is called — it
    has to include weights, activations, and any peak transient
    buffers the model uses. Backends that run on CPU set it to 0 and
    rely on ``ram_mb`` instead.

    ``notes`` is shown to the user when a check fails so they
    understand why ("WAN 2.1 needs ~14 GB free VRAM for the 14B
    variant; you have 6 GB").
    """
    vram_mb: int = 0
    ram_mb: int = 0
    notes: str = ""


@dataclass
class InstallStep:
    """One step of an in-app install for a backend.

    The runner shells the ``command`` as a subprocess (argv list — no
    shell=True ever, to keep the surface tight) and streams stdout +
    stderr to the UI. After the subprocess exits, ``check`` is called
    if provided — when it returns True, the step is marked complete
    even if the subprocess returned non-zero (some pip outputs use
    odd exit codes despite succeeding). When ``check`` returns False
    on success, the step is marked failed.

    ``env_overrides`` is merged into ``os.environ`` for the subprocess
    so a backend can hand ``HF_TOKEN`` (or any other secret-bearing
    variable) to the download tool without baking it into the argv
    list — keeps the token out of process listings, install logs,
    and the UI display.

    ``bytes_estimate`` and ``seconds_estimate`` are best-effort and
    used purely to populate the progress dialog. ``required`` is True
    for steps that must succeed; False marks "nice-to-have" steps the
    runner can skip on failure (e.g. the huggingface-cli convenience
    that isn't strictly required if the user manages weights another
    way).
    """
    label: str
    command: List[str]
    check: Optional[Callable[[], bool]] = None
    cwd: Optional[str] = None
    env_overrides: Optional[Dict[str, str]] = None
    bytes_estimate: int = 0
    seconds_estimate: int = 0
    required: bool = True
    # When True, the dialog warns the user about the size BEFORE
    # starting (e.g. multi-GB model downloads). Backends set this
    # for the big steps and leave it False for small pip installs.
    is_large_download: bool = False


class VideoBackend(abc.ABC):
    """Backend interface. Subclasses must implement is_installed,
    install_instructions, and generate."""

    #: Stable identifier — stored in VideoClip.backend.
    name: str = "abstract"
    #: Human-friendly label for the backend picker UI.
    label: str = "Abstract Backend"
    #: Short description for the UI.
    description: str = ""

    @abc.abstractmethod
    def is_installed(self) -> bool:
        """Return True if the backend can generate right now.

        Cheap to call — should not download anything or block on
        network. The UI calls this each time it shows the backend
        picker.
        """

    @abc.abstractmethod
    def install_instructions(self) -> str:
        """Return human-readable instructions for installing this
        backend. The UI presents these verbatim — typically pip
        install commands and a model-download step."""

    @abc.abstractmethod
    def generate(
        self, request: GenerationRequest,
    ) -> GenerationResult:
        """Generate one video. Errors should be returned via
        ``GenerationResult.success = False`` rather than raised, so
        the studio's queue can keep moving on the next request."""

    def supports_character_refs(self) -> bool:
        """Override to True when the backend can take per-character
        appearance prompts and produce stable likenesses across
        clips."""
        return False

    def memory_requirements(self) -> MemoryRequirements:
        """Return the RAM / VRAM headroom this backend needs.

        Default is empty (no specific requirement). Local
        model-loading backends should override with accurate
        estimates so the studio can pre-flight the request and offer
        to evict competing models before generation kicks off.
        """
        return MemoryRequirements()

    def install_steps(self) -> List[InstallStep]:
        """Return the steps required to install this backend.

        Default is empty — backends without an in-app installer fall
        back to ``install_instructions()`` text only. Backends that
        can install via subprocess / library calls should return a
        list of ``InstallStep`` here so the studio's InstallDialog
        can run them.
        """
        return []

    def supported_durations(self) -> tuple:
        """(min, max) duration in seconds the backend can produce.
        The UI clamps the user's choice to this range."""
        return (1.0, 30.0)

    # ------------------------------------------------------------------
    # Helpers shared by concrete backends
    # ------------------------------------------------------------------
    @staticmethod
    def _write_sidecar(
        sidecar_path: Path,
        request: GenerationRequest,
        backend_name: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write a JSON metadata file next to the video output.

        Sidecars let the UI surface "what prompt produced this clip"
        without having to re-look-up state.
        """
        payload = {
            "backend": backend_name,
            "scene_name": request.scene_name,
            "prompt": request.prompt,
            "duration_seconds": request.duration_seconds,
            "seed": request.seed,
            "character_refs": request.character_refs,
            "chapter_context": (request.chapter_context or "")[:2000],
            "plot_context": (request.plot_context or "")[:2000],
            "worldbuilding_context":
                (request.worldbuilding_context or "")[:2000],
        }
        if extra:
            payload.update(extra)
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8")
