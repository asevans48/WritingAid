"""Backend registry — discoverable list for the picker UI."""

from __future__ import annotations

from typing import List, Optional

from .base import VideoBackend
from .cogvideox import CogVideoX2BBackend, CogVideoX5BBackend
from .flux_schnell import FluxSchnellBackend
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

# Image backends form a parallel registry — the studio picker shows
# them separately so users can mix-and-match (e.g. SDXL for stills
# + LTX-Video for animation). Same shape as video backends so the
# UI machinery (install dialog, memory check) is shared.
_IMAGE_BACKENDS: List[ImageBackend] = [
    PlaceholderImageBackend(),
    SDXLBackend(),              # ~8 GB VRAM, ~14 GB weights
    FluxSchnellBackend(),       # ~16 GB VRAM, ~24 GB weights
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
    avail = available_image_backends()
    return avail[0] if avail else _IMAGE_BACKENDS[0]
