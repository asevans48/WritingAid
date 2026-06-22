"""Audio editing helpers — trim, denoise, gain.

Used by ``AudioEditorDialog`` to apply the writer's edits to a
recorded take. Everything routes through ffmpeg's audio filter
graph: ``afftdn`` for FFT-based noise reduction, ``volume`` for
gain, and the ``-ss`` / ``-t`` flags for trimming. ffmpeg ships
with the studio's stitcher already, so no new dependencies.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

# Tiny alias so ``compose_clips`` can declare a function-local
# dataclass without re-importing ``dataclass`` inside its body.
# Pure cosmetic — keeps the per-clip render struct close to
# the code that builds it.
dataclass_safe = dataclass


@dataclass
class AudioEditResult:
    success: bool
    output_path: Path
    duration_seconds: float = 0.0
    error: str = ""


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def edit_audio(
    src: Path,
    dest: Path,
    *,
    in_point_seconds: float = 0.0,
    out_point_seconds: float = 0.0,
    denoise: bool = False,
    denoise_strength_db: float = -25.0,
    gain_db: float = 0.0,
    normalize: bool = False,
    fade_in_seconds: float = 0.0,
    fade_out_seconds: float = 0.0,
    highpass_hz: float = 0.0,
) -> AudioEditResult:
    """Apply an edit chain to ``src`` and write the result to
    ``dest``. Empty / zero parameters are no-ops, so callers can
    use this for any subset of trim / denoise / gain / fade /
    rumble removal.

    ``in_point_seconds`` clips the head; ``out_point_seconds``
    sets the absolute end timestamp (not the slice length). When
    ``out_point_seconds == 0`` the cut runs to end-of-file.
    ``denoise_strength_db`` is the noise floor that ``afftdn``
    interprets: more negative = more aggressive (typical range
    -10 to -40). ``gain_db`` runs through ``volume``; positive
    boosts, negative attenuates. ``normalize`` is shorthand for
    ``loudnorm`` (target -16 LUFS). ``fade_in_seconds`` /
    ``fade_out_seconds`` add linear fades at the head / tail of
    the OUTPUT (post-trim, so the writer can hear what they
    chopped without a pop). ``highpass_hz`` rolls off rumble
    below the cutoff — voice recordings on cheap mics often
    benefit from a 80–120 Hz highpass.

    Returns ``AudioEditResult(success=False, error=...)`` instead
    of raising so callers can surface the message in a dialog.
    """
    if not ffmpeg_available():
        return AudioEditResult(
            success=False, output_path=dest,
            error="ffmpeg not found on PATH.")
    if not src.exists() or src.stat().st_size == 0:
        return AudioEditResult(
            success=False, output_path=dest,
            error=f"Source missing or empty: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd: list = ["ffmpeg", "-y"]
    if in_point_seconds > 0:
        cmd += ["-ss", f"{in_point_seconds:.3f}"]
    cmd += ["-i", str(src.resolve())]
    out_duration_for_fade: Optional[float] = None
    if out_point_seconds > 0 and out_point_seconds > in_point_seconds:
        out_duration_for_fade = (
            out_point_seconds - in_point_seconds)
        cmd += ["-t", f"{out_duration_for_fade:.3f}"]
    filters: list = []
    if highpass_hz > 0:
        # Roll off DC + room rumble. Single-pole biquad is
        # cheap and good enough for voice.
        filters.append(f"highpass=f={highpass_hz:.0f}")
    if denoise:
        # ``afftdn`` accepts ``nr`` (noise reduction in dB,
        # default 12) and ``nf`` (noise floor, default -30).
        # Treat ``denoise_strength_db`` as the noise floor —
        # more negative → more aggressive.
        filters.append(f"afftdn=nf={denoise_strength_db:.1f}")
    if gain_db != 0:
        filters.append(f"volume={gain_db:.2f}dB")
    if normalize:
        # EBU R128 target. Two-pass ``loudnorm`` is more
        # accurate but slower; single-pass is fine for voiceover.
        filters.append(
            "loudnorm=I=-16:TP=-1.5:LRA=11")
    if fade_in_seconds > 0:
        # Linear fade from silence over the first N seconds of
        # the trimmed output (start_time=0 because -ss has
        # already advanced the input cursor).
        filters.append(
            f"afade=t=in:st=0:d={fade_in_seconds:.3f}")
    if fade_out_seconds > 0:
        # Need the OUTPUT duration to place the fade. Falls
        # back to probing the source when no trim was set.
        out_dur = out_duration_for_fade
        if out_dur is None:
            out_dur = _probe_duration(src) - in_point_seconds
        if out_dur > fade_out_seconds > 0:
            start = max(0.0, out_dur - fade_out_seconds)
            filters.append(
                f"afade=t=out:st={start:.3f}:"
                f"d={fade_out_seconds:.3f}")
    if filters:
        cmd += ["-af", ",".join(filters)]
    cmd += ["-c:a", "pcm_s16le", str(dest.resolve())]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return AudioEditResult(
            success=False, output_path=dest,
            error="ffmpeg timed out after 5 minutes.")
    except Exception as e:
        return AudioEditResult(
            success=False, output_path=dest,
            error=f"ffmpeg raised: {e}")
    if proc.returncode != 0:
        return AudioEditResult(
            success=False, output_path=dest,
            error=(
                "ffmpeg failed (last 400 chars):\n"
                + (proc.stderr or "")[-400:]))
    duration = _probe_duration(dest)
    return AudioEditResult(
        success=True, output_path=dest,
        duration_seconds=duration)


def compose_clips(
    clips: list,
    dest: Path,
    *,
    default_crossfade_seconds: float = 0.15,
    track_gain_db: Optional[dict] = None,
) -> AudioEditResult:
    """Position-aware audio composer.

    Each clip carries ``start_time_seconds`` — its offset on
    the group's composed timeline. The graph for N clips:

        [0:a] atrim,asetpts,volume,afade(in/out),aformat,
              adelay=START_MS|START_MS [c0]
        [1:a] atrim,...,adelay=... [c1]
        ...
        [c0][c1]...[cN] amix=inputs=N:normalize=0[mix]

    ``adelay`` pads each clip with silence so it starts at its
    timeline position, and ``amix`` sums everything together.
    Gaps between clips render as silence; overlaps mix (per-
    clip ``fade_in_seconds`` / ``fade_out_seconds`` give the
    writer control over how harsh the overlap sounds).

    Backwards compat: clips that arrive without
    ``start_time_seconds`` (legacy decks that haven't been
    migrated yet) get auto-positioned sequentially with the
    legacy ``crossfade_seconds`` overlap so the rendered
    output matches what the old composer produced.

    Returns ``AudioEditResult(success=False, error=...)`` on
    failure.
    """
    if not ffmpeg_available():
        return AudioEditResult(
            success=False, output_path=dest,
            error="ffmpeg not found on PATH.")
    if not clips:
        return AudioEditResult(
            success=False, output_path=dest,
            error="No clips to compose.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Collect per-clip render data, skipping missing sources.
    @dataclass_safe
    class _ClipRender:
        path: Path
        start: float
        eff_dur: float
        trim_in: float
        trim_out: float
        gain_db: float
        fade_in: float
        fade_out: float

    renders: list[_ClipRender] = []
    for c in clips:
        path = Path(getattr(c, "audio_path", "") or "")
        if not path.exists() or path.stat().st_size == 0:
            continue
        full = float(
            getattr(c, "duration_seconds", 0.0) or 0.0)
        if full <= 0:
            full = _probe_duration(path)
        if full <= 0:
            continue
        tin = max(0.0, float(
            getattr(c, "trim_in_seconds", 0.0) or 0.0))
        tout = float(
            getattr(c, "trim_out_seconds", 0.0) or 0.0)
        if tout <= 0 or tout > full:
            tout = full
        if tout <= tin:
            continue
        eff_dur = tout - tin
        explicit = getattr(c, "start_time_seconds", None)
        if explicit is None:
            # ``None`` is the "unplaced" sentinel — clip lives
            # in the group but isn't on the timeline (writer
            # parked it in the clip list / tray). Skip it
            # entirely so it doesn't bleed into the rendered
            # overlay; the source file stays on disk.
            continue
        start = max(0.0, float(explicit))
        # Apply per-track lane gain ON TOP OF per-clip gain.
        # ``track_index`` defaults to 0 (the primary lane), so
        # legacy clips that pre-date the multi-track refactor
        # stay on lane 0 and pick up the lane-0 gain if any.
        track_idx = int(
            getattr(c, "track_index", 0) or 0)
        clip_gain = float(
            getattr(c, "gain_db", 0.0) or 0.0)
        lane_gain = 0.0
        if track_gain_db is not None:
            # Allow either int or str keys — JSON round-trip
            # would otherwise turn ``{0: -3.0}`` into
            # ``{"0": -3.0}`` and the lookup would silently
            # miss.
            lane_gain = float(
                track_gain_db.get(track_idx,
                                  track_gain_db.get(
                                      str(track_idx), 0.0))
                or 0.0)
        effective_gain = clip_gain + lane_gain
        renders.append(_ClipRender(
            path=path,
            start=start,
            eff_dur=eff_dur,
            trim_in=tin,
            trim_out=tout,
            gain_db=effective_gain,
            fade_in=max(0.0, float(
                getattr(c, "fade_in_seconds", 0.0) or 0.0)),
            fade_out=max(0.0, float(
                getattr(c, "fade_out_seconds", 0.0) or 0.0)),
        ))
    if not renders:
        return AudioEditResult(
            success=False, output_path=dest,
            error="Every clip's source file was missing.")
    cmd: list = ["ffmpeg", "-y"]
    for r in renders:
        cmd += ["-i", str(r.path.resolve())]
    # Build per-clip chain.
    parts: list[str] = []
    labels: list[str] = []
    for i, r in enumerate(renders):
        chain = [
            f"[{i}:a]atrim=start={r.trim_in:.3f}:"
            f"end={r.trim_out:.3f}",
            "asetpts=N/SR/TB"]
        if r.gain_db != 0:
            chain.append(f"volume={r.gain_db:.2f}dB")
        # Fades are clamped to the effective duration so
        # ffmpeg doesn't reject a fade longer than the clip.
        if r.fade_in > 0:
            fd_in = min(r.fade_in, r.eff_dur)
            chain.append(
                f"afade=t=in:st=0:d={fd_in:.3f}")
        if r.fade_out > 0:
            fd_out = min(r.fade_out, r.eff_dur)
            chain.append(
                f"afade=t=out:"
                f"st={max(0.0, r.eff_dur - fd_out):.3f}:"
                f"d={fd_out:.3f}")
        chain.append(
            "aformat=channel_layouts=mono:sample_rates=44100")
        if r.start > 0:
            delay_ms = int(round(r.start * 1000))
            chain.append(f"adelay={delay_ms}|{delay_ms}")
        label = f"[c{i}]"
        parts.append(",".join(chain) + label)
        labels.append(label)
    if len(renders) == 1:
        parts.append(f"{labels[0]}anull[mix]")
    else:
        # normalize=0 keeps individual clip levels (no auto
        # ducking when more clips overlap). The writer's
        # per-clip gain + fade settings handle level shaping.
        parts.append(
            "".join(labels)
            + f"amix=inputs={len(renders)}:"
              "normalize=0:dropout_transition=0[mix]")
    graph = ";".join(parts)
    cmd += [
        "-filter_complex", graph,
        "-map", "[mix]",
        "-c:a", "pcm_s16le",
        str(dest.resolve())]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return AudioEditResult(
            success=False, output_path=dest,
            error="ffmpeg timed out after 5 minutes.")
    except Exception as e:
        return AudioEditResult(
            success=False, output_path=dest,
            error=f"ffmpeg raised: {e}")
    if proc.returncode != 0:
        return AudioEditResult(
            success=False, output_path=dest,
            error=(
                "ffmpeg failed (last 600 chars):\n"
                + (proc.stderr or "")[-600:]))
    return AudioEditResult(
        success=True, output_path=dest,
        duration_seconds=_probe_duration(dest))


def _probe_duration(path: Path) -> float:
    """ffprobe duration, 0 on failure."""
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(path.resolve())],
            capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            return 0.0
        return float((proc.stdout or "0").strip())
    except Exception:
        return 0.0
