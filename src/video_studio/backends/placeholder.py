"""Placeholder backend — always installed, produces stub clip files.

Lets users exercise the full studio UX (add scenes, draw hops, edit
prompts, view clip cards, mark favorites, stitch, delete) without
needing a heavy model installed. The "video" is an empty .mp4-named
file plus a JSON sidecar with the prompt — viewing it in a media
player will fail, which is intentional: the placeholder is labeled
clearly in the UI so the user knows to swap in a real backend before
expecting playback.

We deliberately avoid faking the file content (no ffmpeg-rendered
black frame, no PNG-of-text fallback) — pretending to render is
worse than admitting we didn't.
"""

from __future__ import annotations

from .base import (
    GenerationRequest, GenerationResult, VideoBackend,
)


class PlaceholderBackend(VideoBackend):
    name = "placeholder"
    label = "Placeholder (no rendering)"
    description = (
        "Always-available stub backend. Writes a clip metadata "
        "sidecar so the studio UX can be exercised end-to-end, but "
        "does NOT produce a playable video. Swap in a real backend "
        "(WAN 2.1, etc.) when you're ready to render.")

    def is_installed(self) -> bool:
        return True

    def install_instructions(self) -> str:
        return (
            "The placeholder backend has no install step — it's "
            "built in. Install a real backend (see the backend "
            "picker) when you're ready to render actual video.")

    def supports_character_refs(self) -> bool:
        # Character refs are still passed through to the sidecar
        # for downstream backends that DO support them — useful when
        # the user later swaps backends and wants the metadata
        # already on the clip.
        return True

    def generate(
        self, request: GenerationRequest,
    ) -> GenerationResult:
        try:
            out = request.output_path
            out.parent.mkdir(parents=True, exist_ok=True)
            # Drop a stub file so the path resolves; downstream code
            # checks ``is_placeholder`` before attempting playback.
            out.write_bytes(b"")
            sidecar = out.with_suffix(out.suffix + ".json")
            self._write_sidecar(
                sidecar, request, backend_name=self.name,
                extra={"placeholder": True})
            return GenerationResult(
                success=True,
                output_path=out,
                sidecar_path=sidecar,
                is_placeholder=True,
                backend_metadata={"placeholder": True},
            )
        except Exception as e:
            return GenerationResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=request.output_path.with_suffix(
                    request.output_path.suffix + ".json"),
                error=str(e),
            )
