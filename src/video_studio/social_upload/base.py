"""Base abstractions for social-platform video uploads.

A ``SocialPlatform`` is a thin adapter — it owns the credential
shape, the privacy enum, the upload call, and an install-status
check. The dialog and registry use only these interfaces; adding
a new platform later means dropping a new module beside the
existing ones and registering it.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class Privacy(str, Enum):
    """Common privacy buckets. Each platform maps them to its
    own values (YouTube ``public`` / ``unlisted`` / ``private``,
    TikTok ``SELF_ONLY`` / ``MUTUAL_FOLLOW_FRIENDS`` /
    ``PUBLIC_TO_EVERYONE``, etc.)."""
    PUBLIC = "public"
    UNLISTED = "unlisted"
    PRIVATE = "private"


@dataclass
class UploadMetadata:
    """Writer-supplied metadata for one upload job.

    Fields that don't apply to a platform are ignored — the dialog
    surfaces only the fields each platform actually uses, but the
    payload stays uniform so the same struct can drive a multi-
    platform cross-post in the future.
    """
    title: str
    description: str = ""
    tags: List[str] = field(default_factory=list)
    privacy: Privacy = Privacy.PRIVATE
    category: str = ""
    language: str = ""
    thumbnail_path: Optional[Path] = None
    schedule_time_iso: str = ""  # empty = upload now
    # Platform-specific overrides (e.g. TikTok's allow_comment).
    # Writers don't usually touch these; advanced UI may.
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UploadRequest:
    """One upload job — a video file plus the metadata that goes
    with it."""
    video_path: Path
    metadata: UploadMetadata


@dataclass
class UploadResult:
    """Outcome of an upload call."""
    success: bool
    platform: str
    remote_url: str = ""    # canonical link to the uploaded video
    remote_id: str = ""     # platform's video id
    error: str = ""
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CredentialField:
    """Describes one piece of credential data the platform needs.

    ``key`` is the keystore key used by ``credential_manager``;
    ``label`` and ``help`` drive the settings UI. ``secret`` masks
    the field with bullets. ``required`` means the upload can't
    run without it.
    """
    key: str
    label: str
    help: str = ""
    secret: bool = True
    required: bool = True
    multiline: bool = False


class SocialPlatform(abc.ABC):
    """Adapter for one social platform's video upload API."""

    # ``name`` is the registry key — also the credential namespace
    # prefix. ``label`` is the user-facing string in the UI.
    name: str = "abstract"
    label: str = "Abstract Platform"
    description: str = ""
    # Maximum video duration the platform accepts. Set to 0 when
    # the platform doesn't impose a hard ceiling. The dialog
    # surfaces this so writers don't queue up a 10-min video for
    # TikTok's 10-min cap and only learn at upload time.
    max_duration_seconds: float = 0.0
    # Aspect-ratio guidance shown in the dialog. Free-form string
    # so platforms with multiple shapes (TikTok 9:16, YouTube
    # 16:9 / Shorts 9:16) can describe both.
    aspect_hint: str = ""

    # Fields the platform needs in the credential store.
    credential_fields: List[CredentialField] = []

    # Categories the platform exposes. Empty when there's no
    # category dropdown.
    categories: List[str] = []

    # ------------------------------------------------------------------
    # Capability + install
    # ------------------------------------------------------------------
    @abc.abstractmethod
    def is_installed(self) -> bool:
        """True when the platform's runtime dependency (SDK) is
        importable. Returns False so the UI can offer install
        guidance via ``install_instructions``."""

    def install_instructions(self) -> str:
        """Human-readable install steps for this platform's SDK.
        Default: empty (the platform has no extra dep)."""
        return ""

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------
    def credential_keys(self) -> List[str]:
        """Fully-qualified keystore keys for the credential
        fields — namespaced by the platform's ``name`` so two
        platforms with the same field name don't collide."""
        return [
            f"social_{self.name}_{f.key}"
            for f in self.credential_fields]

    def has_credentials(self) -> bool:
        """Cheap check: do we have a value for every required
        credential field? Uses the shared credential manager."""
        try:
            from src.config.credential_manager import (
                get_credential_manager)
            cm = get_credential_manager()
            for field in self.credential_fields:
                if not field.required:
                    continue
                full_key = (
                    f"social_{self.name}_{field.key}")
                if not cm.get_credential(full_key):
                    return False
            return True
        except Exception:
            return False

    def get_credential(self, key: str) -> Optional[str]:
        """Load a credential by short key (without namespace)."""
        try:
            from src.config.credential_manager import (
                get_credential_manager)
            cm = get_credential_manager()
            return cm.get_credential(
                f"social_{self.name}_{key}")
        except Exception:
            return None

    def store_credential(self, key: str, value: str) -> bool:
        """Save a credential by short key. Empty values are
        deleted by the credential manager."""
        try:
            from src.config.credential_manager import (
                get_credential_manager)
            cm = get_credential_manager()
            return cm.store_credential(
                f"social_{self.name}_{key}", value)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------
    @abc.abstractmethod
    def upload(self, request: UploadRequest) -> UploadResult: ...
