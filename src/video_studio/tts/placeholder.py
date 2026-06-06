"""Placeholder TTS — always installed, doesn't produce audio.

Writes a sidecar with the requested text so the studio's narration
flow can be exercised end-to-end without any TTS engine installed.
The audio file is empty; the stitcher will skip muxing when it
detects a 0-byte audio file.
"""

from __future__ import annotations

from .base import (
    TTSBackend, TTSRequest, TTSResult,
)


class PlaceholderTTSBackend(TTSBackend):
    name = "placeholder_tts"
    label = "Placeholder TTS (no audio)"
    description = (
        "Always-available stub TTS backend. Writes a sidecar with "
        "the text so the narration UX works end-to-end, but does "
        "NOT produce audio. Pick the System TTS backend or install "
        "a richer one (Piper, Coqui, ElevenLabs, OpenAI TTS) for "
        "real synthesis.")

    def is_installed(self) -> bool:
        return True

    def install_instructions(self) -> str:
        return (
            "The placeholder TTS backend has no install step. It's "
            "built in so the studio can validate narration "
            "metadata flow without an actual synthesizer.")

    def synthesize(self, request: TTSRequest) -> TTSResult:
        try:
            out = request.output_path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"")
            sidecar = out.with_suffix(out.suffix + ".json")
            self._write_sidecar(
                sidecar, request, backend_name=self.name,
                extra={"placeholder": True})
            return TTSResult(
                success=True,
                output_path=out,
                sidecar_path=sidecar,
                duration_seconds=0.0,
                is_placeholder=True,
            )
        except Exception as e:
            return TTSResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=request.output_path.with_suffix(
                    request.output_path.suffix + ".json"),
                error=str(e),
            )
