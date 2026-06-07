"""Backend registry — discoverable list for the picker UI."""

from __future__ import annotations

from typing import List, Optional

from .base import VideoBackend
from .cogvideox import CogVideoX2BBackend, CogVideoX5BBackend
from .flux_schnell import FluxSchnellBackend
from .configured_image import ConfiguredImageBackend
from .image_base import ImageBackend
from .image_placeholder import PlaceholderImageBackend
from .ltx_video import LtxVideoBackend
from .placeholder import PlaceholderBackend
from .sdxl import SDXLBackend
from .wan21 import Wan21Backend


# Order matters: placeholder first so new users see a working
# default. After that, lightest → heaviest, so the picker hints at
# memory cost just by position.
_BACKENDS: List[VideoBackend] = [
    PlaceholderBackend(),
    LtxVideoBackend(),        # ~8-12 GB VRAM, MPS + 12 GB GPUs
    CogVideoX2BBackend(),     # ~5 GB VRAM, MPS + 12 GB GPUs
    CogVideoX5BBackend(),     # ~13 GB VRAM, 24 GB GPUs
    Wan21Backend(),           # ~14 GB VRAM (14B variant), 24 GB GPUs
]

# Image backends — the "Configured Model" entry delegates to the
# unified ``ImageGenerationAgent`` so the studio renders with
# whatever the writer picked in Settings → 🎨 Image Generation.
# That makes the FULL model catalog (MLX, diffusers, DALL-E,
# Stability AI, Replicate) available to the studio without
# duplicating loader logic.
#
# SDXLBackend and FluxSchnellBackend remain in the registry as
# explicit legacy options for installs that still wire diffusers
# directly; new selections should prefer the Configured entry.
_IMAGE_BACKENDS: List[ImageBackend] = [
    PlaceholderImageBackend(),
    ConfiguredImageBackend(),   # uses Settings → Image Generation
    SDXLBackend(),              # legacy: direct diffusers, ~8 GB VRAM
    FluxSchnellBackend(),       # legacy: direct diffusers, ~16 GB VRAM
]


def all_backends() -> List[VideoBackend]:
    """Return every registered backend regardless of install status.

    The UI shows everything so users can read install instructions
    for backends they haven't set up yet.
    """
    return list(_BACKENDS)


def available_backends() -> List[VideoBackend]:
    """Return only the backends ready to generate now."""
    return [b for b in _BACKENDS if b.is_installed()]


def get_backend(name: str) -> Optional[VideoBackend]:
    for b in _BACKENDS:
        if b.name == name:
            return b
    return None


def default_backend() -> VideoBackend:
    """Pick a sensible default for first-launch.

    The placeholder is always installed; prefer it so the user can
    immediately exercise the UX. Once they install a real backend
    they can switch via the picker.
    """
    avail = available_backends()
    if avail:
        return avail[0]
    # Should never happen — placeholder is always installed — but
    # guard anyway so a partial install doesn't crash the studio.
    return _BACKENDS[0]


# ---- Image backend helpers (parallel API) ----
def all_image_backends() -> List[ImageBackend]:
    return list(_IMAGE_BACKENDS)


def available_image_backends() -> List[ImageBackend]:
    return [b for b in _IMAGE_BACKENDS if b.is_installed()]


def get_image_backend(name: str) -> Optional[ImageBackend]:
    for b in _IMAGE_BACKENDS:
        if b.name == name:
            return b
    return None


def default_image_backend() -> ImageBackend:
    """Prefer the Configured backend so the studio honors the
    user's Settings → 🎨 Image Generation choice out of the box.
    Falls back to placeholder when no model is configured."""
    configured = get_image_backend("configured")
    if configured is not None and configured.is_installed():
        return configured
    avail = available_image_backends()
    return avail[0] if avail else _IMAGE_BACKENDS[0]
