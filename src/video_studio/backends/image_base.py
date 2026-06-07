"""Image backends for the Video Studio.

Parallel to ``VideoBackend`` but for still images. The studio uses
image stills as scene clips when:
  * A heavy video model isn't installed (low-VRAM laptops)
  * The writer wants a storyboard frame, not a full clip
  * A scene is short enough that a held image works as background

Each image clip is a single PNG; the stitcher converts it to a
silent MP4 of the requested display time via ffmpeg's loop filter.

ImageBackend mirrors VideoBackend's shape (install detection,
install steps, memory requirements, generate) so the studio UI can
treat them uniformly via the picker.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import InstallStep, MemoryRequirements


@dataclass
class ImageGenerationRequest:
    """One request to an image backend.

    Width / height default to a sensible video-aspect (16:9) at
    high enough resolution to look good when held on screen for a
    few seconds. Backends can clamp these to their supported set.
    """
    prompt: str
    output_path: Path
    width: int = 1280
    height: int = 720
    scene_name: str = ""
    seed: Optional[int] = None
    character_refs: List[Dict[str, Any]] = field(default_factory=list)
    chapter_context: str = ""
    plot_context: str = ""
    worldbuilding_context: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageGenerationResult:
    success: bool
    output_path: Path
    sidecar_path: Path
    is_placeholder: bool = False
    error: str = ""
    backend_metadata: Dict[str, Any] = field(default_factory=dict)


class ImageBackend(abc.ABC):
    """Backend that produces a single still image per call."""

    name: str = "abstract_image"
    label: str = "Abstract Image Backend"
    description: str = ""
    # ``output_kind`` lets the studio's unified picker know what to
    # expect (so a single dropdown can show both video and image
    # backends with a label).
    output_kind: str = "image"

    @abc.abstractmethod
    def is_installed(self) -> bool: ...

    @abc.abstractmethod
    def install_instructions(self) -> str: ...

    @abc.abstractmethod
    def generate(
        self, request: ImageGenerationRequest,
    ) -> ImageGenerationResult: ...

    def memory_requirements(self) -> MemoryRequirements:
        return MemoryRequirements()

    def install_steps(self) -> List[InstallStep]:
        return []

    def supports_character_refs(self) -> bool:
        return False

    # ------------------------------------------------------------------
    # Helper — sidecar writer (mirrors VideoBackend)
    # ------------------------------------------------------------------
    @staticmethod
    def _write_sidecar(
        sidecar_path: Path,
        request: ImageGenerationRequest,
        backend_name: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = {
            "backend": backend_name,
            "output_kind": "image",
            "scene_name": request.scene_name,
            "prompt": request.prompt,
            "width": request.width,
            "height": request.height,
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
