"""Cheap peak-style waveform loader.

The group editor's timeline paints the overlay audio as a
waveform so the writer can SEE where the loud parts are when
placing slides. We don't render every sample — at typical audio
rates (44.1 kHz) and pixel widths (~1000 px) that would be
~44 samples per pixel, way past what a peak band can usefully
show. Instead we bucket the file into ``num_buckets`` columns
and store the (min, max) amplitude for each one. Painting then
draws one vertical line per bucket.

Loading goes through soundfile (which already ships as a dep for
recording) so we don't pull in another audio library. Mono is
the only supported channel layout — multi-channel files get
mixed down to mono. That's fine for our use case: writers
record voiceovers, which are mono.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class WaveformPeaks:
    """Compact peak band suitable for one ``paintEvent``.

    ``mins`` and ``maxs`` are float lists of equal length —
    each pair represents the min/max sample value in that
    bucket. Values are normalized to ``[-1.0, 1.0]`` so the
    painter can scale them by the bar height without thinking
    about source bit depth.
    """

    mins: list[float]
    maxs: list[float]
    duration_seconds: float
    samplerate: int

    @property
    def num_buckets(self) -> int:
        return len(self.mins)


def load_peaks(
    path: Path,
    num_buckets: int = 800,
) -> Optional[WaveformPeaks]:
    """Read an audio file and return a peak band of
    ``num_buckets`` columns. Returns ``None`` when soundfile
    isn't installed, the file is missing, or it can't be
    decoded — none of those should crash the UI; the timeline
    just falls back to drawing a flat bar.
    """
    if num_buckets <= 0:
        return None
    if not path.exists():
        return None
    try:
        import soundfile as sf  # noqa: F401
        import numpy as np
    except ImportError:
        # soundfile + numpy is the same dep set as the
        # recorder. If we got here without it, the writer
        # also can't record — that's a separate problem to
        # surface; here we just stay quiet.
        return None
    try:
        # Stream the file so we don't load 20 minutes of audio
        # into memory just to compute peaks.
        with sf.SoundFile(str(path)) as src:
            samplerate = src.samplerate
            total_frames = len(src)
            channels = src.channels
            if total_frames <= 0 or samplerate <= 0:
                return None
            buckets = min(num_buckets, total_frames)
            frames_per_bucket = max(
                1, total_frames // buckets)
            mins: list[float] = []
            maxs: list[float] = []
            read_so_far = 0
            for bucket_idx in range(buckets):
                # Last bucket eats any remainder so we don't drop
                # the tail of the audio off the visualization.
                to_read = (
                    total_frames - read_so_far
                    if bucket_idx == buckets - 1
                    else frames_per_bucket)
                if to_read <= 0:
                    break
                block = src.read(
                    frames=to_read,
                    dtype="float32",
                    always_2d=True)
                read_so_far += block.shape[0]
                if block.shape[0] == 0:
                    break
                # Downmix to mono — mean across channels.
                if channels > 1:
                    mono = block.mean(axis=1)
                else:
                    mono = block[:, 0]
                mins.append(float(np.min(mono)))
                maxs.append(float(np.max(mono)))
            if not mins:
                return None
            duration = total_frames / float(samplerate)
            return WaveformPeaks(
                mins=mins, maxs=maxs,
                duration_seconds=duration,
                samplerate=samplerate)
    except Exception as exc:
        print(f"[waveform] load_peaks failed for {path}: {exc}")
        return None
