"""TTS backend registry."""

from __future__ import annotations

from typing import List, Optional

from .base import TTSBackend
from .placeholder import PlaceholderTTSBackend
from .system_tts import SystemTTSBackend


_TTS_BACKENDS: List[TTSBackend] = [
    PlaceholderTTSBackend(),
    SystemTTSBackend(),
]


def all_tts_backends() -> List[TTSBackend]:
    return list(_TTS_BACKENDS)


def available_tts_backends() -> List[TTSBackend]:
    return [b for b in _TTS_BACKENDS if b.is_installed()]


def get_tts_backend(name: str) -> Optional[TTSBackend]:
    for b in _TTS_BACKENDS:
        if b.name == name:
            return b
    return None


def default_tts_backend() -> TTSBackend:
    """Prefer System TTS when available — it actually produces
    audio. Falls back to the placeholder otherwise."""
    for b in _TTS_BACKENDS:
        if isinstance(b, SystemTTSBackend) and b.is_installed():
            return b
    return _TTS_BACKENDS[0]
