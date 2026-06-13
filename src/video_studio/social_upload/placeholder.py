"""Placeholder upload backend — always installed, never uploads.

Used by tests and as a safe default in the dialog so the upload
flow can be exercised end-to-end without sending bytes to a real
platform. Records what would have been sent in a JSON sidecar
next to the source video so writers can audit the metadata
without risk.
"""

from __future__ import annotations

import json
from datetime import datetime

from .base import (
    Privacy, SocialPlatform, UploadRequest, UploadResult,
)


class PlaceholderUploadPlatform(SocialPlatform):
    name = "placeholder"
    label = "Dry-run (no upload)"
    description = (
        "Always-available dry-run backend. Writes a sidecar JSON "
        "describing the upload payload but never sends the video "
        "anywhere — pick this to verify the metadata form before "
        "wiring a real platform.")
    aspect_hint = "Any (no validation)"
    credential_fields = []
    categories = []

    def is_installed(self) -> bool:
        return True

    def install_instructions(self) -> str:
        return ""

    def upload(self, request: UploadRequest) -> UploadResult:
        sidecar = request.video_path.with_suffix(
            request.video_path.suffix + ".dryrun.json")
        try:
            payload = {
                "platform": self.name,
                "video": str(request.video_path.resolve()),
                "metadata": {
                    "title": request.metadata.title,
                    "description": request.metadata.description,
                    "tags": list(request.metadata.tags),
                    "privacy": request.metadata.privacy.value
                        if isinstance(
                            request.metadata.privacy, Privacy)
                        else str(request.metadata.privacy),
                    "category": request.metadata.category,
                    "language": request.metadata.language,
                    "thumbnail_path": (
                        str(request.metadata.thumbnail_path)
                        if request.metadata.thumbnail_path
                        else ""),
                    "schedule_time_iso":
                        request.metadata.schedule_time_iso,
                    "extras": dict(request.metadata.extras),
                },
                "would_upload_at": datetime.now().isoformat(),
            }
            sidecar.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False))
        except Exception as e:
            return UploadResult(
                success=False, platform=self.name,
                error=f"Could not write dry-run sidecar: {e}")
        return UploadResult(
            success=True, platform=self.name,
            remote_url="",
            remote_id=f"dryrun-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            raw_response={"sidecar_path": str(sidecar)})
