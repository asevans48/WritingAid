"""Text-to-speech backend abstraction for the Video Studio.

Mirrors the shape of ``VideoBackend`` / ``ImageBackend`` so the UI
treats TTS as another pluggable backend the user picks from a
dropdown. Subclasses implement ``synthesize`` and the install/check
hooks the studio shares across all backend types.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.video_studio.backends.base import InstallStep


@dataclass
class TTSRequest:
    """Inputs to a single synthesize call."""
    text: str
    output_path: Path
    voice: str = ""               # backend-specific voice id / name
    rate_wpm: Optional[int] = None  # words per minute (None = backend default)
    scene_name: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSResult:
    success: bool
    output_path: Path
    sidecar_path: Path
    duration_seconds: float = 0.0
    is_placeholder: bool = False
    error: str = ""
    backend_metadata: Dict[str, Any] = field(default_factory=dict)


class TTSBackend(abc.ABC):
    """Pluggable text-to-speech backend."""

    name: str = "abstract_tts"
    label: str = "Abstract TTS"
    description: str = ""

    @abc.abstractmethod
    def is_installed(self) -> bool: ...

    @abc.abstractmethod
    def install_instructions(self) -> str: ...

    @abc.abstractmethod
    def synthesize(self, request: TTSRequest) -> TTSResult: ...

    def install_steps(self) -> List[InstallStep]:
        return []

    def available_voices(self) -> List[str]:
        """List voice identifiers the user can pick from. Empty list
        means "the backend uses a single default voice"."""
        return []

    # ------------------------------------------------------------------
    # Shared sidecar writer
    # ------------------------------------------------------------------
    @staticmethod
    def _write_sidecar(
        sidecar_path: Path,
        request: TTSRequest,
        backend_name: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = {
            "backend": backend_name,
            "output_kind": "audio",
            "scene_name": request.scene_name,
            "text": request.text,
            "voice": request.voice,
            "rate_wpm": request.rate_wpm,
        }
        if extra:
            payload.update(extra)
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False))


def probe_audio_duration_seconds(path: Path) -> float:
    """Best-effort duration probe via ffprobe. Returns 0.0 if probe
    fails (no ffprobe on PATH, unsupported format, etc.).

    Used by the imported-audio path so we can show the user how
    long their voiceover is. Falls back to 0 gracefully — the
    stitcher will use ``-shortest`` when duration is unknown.
    """
    import shutil
    import subprocess
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(path)],
            capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            return 0.0
        return float((proc.stdout or "0").strip())
    except Exception:
        return 0.0
