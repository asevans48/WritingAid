"""Placeholder image backend — always installed.

Writes a small valid PNG (single black frame at the requested
dimensions) so the studio's pipeline (clip list, stitcher
ffmpeg-loop conversion) can be exercised end-to-end without a real
image model installed. The PNG is real enough that ffmpeg will
loop it into an MP4 just fine; users see a black scene where the
artwork would be.

We use a hand-written minimal PNG rather than pulling in Pillow so
this backend stays dependency-free and the studio's "always works"
guarantee holds even in a stripped environment.
"""

from __future__ import annotations

import struct
import zlib

from .image_base import (
    ImageBackend, ImageGenerationRequest, ImageGenerationResult,
)


class PlaceholderImageBackend(ImageBackend):
    name = "placeholder_image"
    label = "Placeholder image (no rendering)"
    description = (
        "Always-available stub backend for image stills. Writes a "
        "valid PNG (a black frame) plus a metadata sidecar so the "
        "studio's image flow works end-to-end. Install a real "
        "image backend (SDXL, FLUX, etc.) when you're ready to "
        "render actual artwork.")
    output_kind = "image"

    def is_installed(self) -> bool:
        return True

    def install_instructions(self) -> str:
        return (
            "The placeholder image backend has no install step — "
            "it's built in. Install a real backend (FLUX or SDXL) "
            "from the image backend picker when you're ready to "
            "render actual stills.")

    def supports_character_refs(self) -> bool:
        # We accept character refs and pass them through in the
        # sidecar, so swapping in a real backend later keeps the
        # grounding intact.
        return True

    def generate(
        self, request: ImageGenerationRequest,
    ) -> ImageGenerationResult:
        try:
            out = request.output_path
            out.parent.mkdir(parents=True, exist_ok=True)
            png_bytes = _minimal_black_png(
                max(16, int(request.width)),
                max(16, int(request.height)))
            out.write_bytes(png_bytes)
            sidecar = out.with_suffix(out.suffix + ".json")
            self._write_sidecar(
                sidecar, request, backend_name=self.name,
                extra={"placeholder": True,
                       "note": "single black frame"})
            return ImageGenerationResult(
                success=True,
                output_path=out,
                sidecar_path=sidecar,
                is_placeholder=True,
            )
        except Exception as e:
            return ImageGenerationResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=request.output_path.with_suffix(
                    request.output_path.suffix + ".json"),
                error=str(e),
            )


# ---------------------------------------------------------------------
# Tiny PNG writer — no Pillow dependency
# ---------------------------------------------------------------------
def _minimal_black_png(width: int, height: int) -> bytes:
    """Return raw PNG bytes for a black grayscale image of the given
    size. Hand-rolled because pulling Pillow into video_studio for a
    placeholder is way out of proportion to what we need.

    Format reference: https://www.w3.org/TR/PNG/  (we use 8-bit
    grayscale, no palette, no alpha — the smallest valid PNG that
    every viewer can decode).
    """
    sig = b"\x89PNG\r\n\x1a\n"
    # IHDR — width / height / bit depth / color type (0 = grayscale)
    ihdr_data = struct.pack(
        ">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    ihdr = _png_chunk(b"IHDR", ihdr_data)
    # IDAT — one filter byte (0 = None) per scanline followed by N
    # zero bytes (one per pixel). Compressed via zlib.
    raw = b""
    row = b"\x00" + (b"\x00" * width)
    for _ in range(height):
        raw += row
    idat = _png_chunk(b"IDAT", zlib.compress(raw))
    iend = _png_chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """One PNG chunk: length / type / data / CRC32(type + data)."""
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    return length + chunk_type + data + crc
