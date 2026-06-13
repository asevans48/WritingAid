"""Registry of social-upload platforms.

Other modules see this list, not the individual classes — adding
a new platform means dropping a new module and appending one
import + entry below.
"""

from __future__ import annotations

from typing import List, Optional

from .base import SocialPlatform
from .placeholder import PlaceholderUploadPlatform
from .tiktok import TikTokPlatform
from .youtube import YouTubePlatform


_PLATFORMS: List[SocialPlatform] = [
    PlaceholderUploadPlatform(),
    YouTubePlatform(),
    TikTokPlatform(),
]


def all_platforms() -> List[SocialPlatform]:
    return list(_PLATFORMS)


def get_platform(name: str) -> Optional[SocialPlatform]:
    for p in _PLATFORMS:
        if p.name == name:
            return p
    return None


def default_platform() -> SocialPlatform:
    """First installed real (non-placeholder) platform falling
    back to the placeholder. Drives the dialog's default pick."""
    for p in _PLATFORMS:
        if p.name == "placeholder":
            continue
        try:
            if p.is_installed():
                return p
        except Exception:
            continue
    return _PLATFORMS[0]
