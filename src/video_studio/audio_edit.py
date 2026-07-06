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
    track_deesser_intensity: Optional[dict] = None,
    track_muted: Optional[dict] = None,
    track_background: Optional[dict] = None,
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
        # Per-clip de-esser intensity (0..1). ``0`` skips
        # the filter so a deck with no de-essing pays no
        # ffmpeg cost. Sourced from the clip itself (wins)
        # falling back to the clip's track entry.
        deesser_intensity: float
        # Per-clip noise floor (negative dB). ``0`` skips
        # afftdn. Per-clip only — no track-level fallback;
        # noise reduction is too source-specific to apply
        # at the lane level.
        denoise_floor_db: float
        # When > 0, apply an infinite ``aloop`` and cap at
        # this many seconds (measured from clip.start).
        # ``0`` (default) = no looping, clip plays once at
        # its natural length. Set for clips on lanes flagged
        # as background whenever there's a foreground extent
        # to loop up to.
        loop_to_seconds: float

    def _is_bg(track_idx: int) -> bool:
        if track_background is None:
            return False
        return bool(
            track_background.get(
                track_idx,
                track_background.get(
                    str(track_idx), False)))

    def _is_muted(track_idx: int) -> bool:
        if track_muted is None:
            return False
        return bool(
            track_muted.get(
                track_idx,
                track_muted.get(str(track_idx), False)))

    # Foreground end = last stopping point across every clip
    # on a lane that isn't marked background AND isn't muted.
    # Background clips loop UNTIL this time (or until the
    # next clip on their own lane, whichever comes first).
    # When no foreground clips exist, background clips render
    # at their native length.
    foreground_end = 0.0
    for c in clips:
        idx = int(getattr(c, "track_index", 0) or 0)
        if _is_bg(idx) or _is_muted(idx):
            continue
        explicit = getattr(c, "start_time_seconds", None)
        if explicit is None:
            continue
        full = float(
            getattr(c, "duration_seconds", 0.0) or 0.0)
        tin = max(0.0, float(
            getattr(c, "trim_in_seconds", 0.0) or 0.0))
        tout = float(
            getattr(c, "trim_out_seconds", 0.0) or 0.0)
        if tout <= 0 or tout > full:
            tout = full
        if tout <= tin:
            continue
        eff = tout - tin
        end = float(explicit) + eff
        if end > foreground_end:
            foreground_end = end

    # For each background clip, compute the next-clip-on-same-
    # lane cutoff so a bed loops until its own lane's next
    # clip takes over (rather than plowing through it).
    # Missing next-clip → falls back to ``foreground_end``.
    def _next_clip_on_lane(target_c) -> Optional[float]:
        tidx = int(getattr(target_c, "track_index", 0) or 0)
        t0 = float(
            getattr(target_c, "start_time_seconds", 0.0)
            or 0.0)
        best: Optional[float] = None
        for other in clips:
            if other is target_c:
                continue
            if int(getattr(other, "track_index", 0)
                   or 0) != tidx:
                continue
            other_start = getattr(
                other, "start_time_seconds", None)
            if other_start is None:
                continue
            other_start_f = float(other_start)
            if other_start_f <= t0:
                continue
            if best is None or other_start_f < best:
                best = other_start_f
        return best

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
        # Skip muted lanes entirely. ``track_muted`` is a
        # ``{track_index: bool}`` dict; missing keys mean
        # "audible" (default) so nothing changes for decks
        # that don't use mute. Muted clips don't consume an
        # ffmpeg input slot / filter chain — cheaper AND keeps
        # the ``amix`` normalization from double-counting the
        # silent lane.
        track_idx_check = int(
            getattr(c, "track_index", 0) or 0)
        if track_muted is not None:
            muted = bool(
                track_muted.get(track_idx_check,
                                track_muted.get(
                                    str(track_idx_check),
                                    False)))
            if muted:
                continue
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
        # De-esser: per-clip value wins over track-level
        # fallback so a writer can fix one harsh take
        # without dialing the whole lane.
        clip_deesser = max(0.0, min(1.0, float(
            getattr(c, "deesser_intensity", 0.0) or 0.0)))
        if clip_deesser > 0:
            deesser = clip_deesser
        else:
            deesser = 0.0
            if track_deesser_intensity is not None:
                raw = track_deesser_intensity.get(
                    track_idx,
                    track_deesser_intensity.get(
                        str(track_idx), 0.0))
                try:
                    deesser = max(
                        0.0, min(1.0, float(raw or 0.0)))
                except (TypeError, ValueError):
                    deesser = 0.0
        # Denoise floor — per-clip only (no track fallback;
        # noise profiles are too source-specific to apply
        # at the lane level). Negative value enables afftdn.
        denoise_floor = float(
            getattr(c, "denoise_floor_db", 0.0) or 0.0)
        # Background looping: if the clip's lane is flagged
        # as background AND there's foreground content on
        # other lanes to loop up to, cap the loop at whichever
        # comes first — the next clip on the same lane or
        # ``foreground_end``. When neither is greater than
        # this clip's own end, no looping is needed.
        loop_to = 0.0
        if _is_bg(track_idx) and foreground_end > start:
            cap_end = foreground_end
            next_start = _next_clip_on_lane(c)
            if (next_start is not None
                    and next_start < cap_end):
                cap_end = next_start
            duration_from_start = cap_end - start
            if duration_from_start > eff_dur:
                loop_to = duration_from_start
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
            deesser_intensity=deesser,
            denoise_floor_db=denoise_floor,
            loop_to_seconds=loop_to,
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
        # Noise reduction first — clean the noise floor
        # BEFORE other processing so subsequent stages
        # (deesser, gain) don't amplify hiss. ``afftdn``
        # ``nf=`` is the noise floor in dB; anything below
        # gets attenuated. Per-clip only since noise
        # profiles vary by source.
        if r.denoise_floor_db < 0:
            chain.append(
                f"afftdn=nf={r.denoise_floor_db:.1f}")
        # De-esser runs BEFORE volume so the writer's gain
        # adjustment compensates for the slight perceived
        # loudness drop a heavy de-ess introduces. ffmpeg's
        # ``deesser`` filter takes ``i`` (intensity 0..1),
        # ``m`` (max reduction 0..1 — 0.5 is the default and
        # plenty for voiceover), ``f`` (frequency 0..1 mapped
        # to 5–15 kHz; 0.5 ≈ 6 kHz which catches the
        # ess / sh / ch band), and ``s`` (mode 'i'=input
        # passthrough, 'o'=de-essed output, 'e'=ess-only —
        # we want 'o').
        if r.deesser_intensity > 0:
            chain.append(
                f"deesser=i={r.deesser_intensity:.3f}:"
                f"m=0.5:f=0.5:s=o")
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
        # Background looping — insert AFTER the aformat so
        # ``aloop`` sees a normalized sample rate + channel
        # layout, avoiding "different formats in loop" ffmpeg
        # complaints. ``aloop=-1`` loops forever; ``size`` must
        # cover one whole iteration so we pass the clip's
        # kept-sample count (kept_seconds * 44100). ``atrim``
        # then caps at the total loop length so the mix has a
        # finite output.
        if r.loop_to_seconds > r.eff_dur:
            size_samples = max(
                1, int(round(r.eff_dur * 44100)))
            chain.append(
                f"aloop=loop=-1:size={size_samples}")
            chain.append(
                f"atrim=end={r.loop_to_seconds:.3f}")
            chain.append("asetpts=N/SR/TB")
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
