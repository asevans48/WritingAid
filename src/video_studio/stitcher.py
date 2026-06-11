"""Stitch multiple clips into a single video via ffmpeg.

The user asks for "stitch the videos together when ready" — that's
this module. We shell out to ffmpeg's concat demuxer, which is the
fastest path for clips that share codec / container (the usual case
when one backend renders the whole batch).

ffmpeg is NOT bundled with the app — if it isn't on PATH, we report
a clear actionable error instead of trying to silently substitute
anything. The studio's data layer keeps working without stitching.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple


@dataclass
class StitchResult:
    success: bool
    output_path: Path
    error: str = ""


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def stitch_clips(
    clip_paths: List[Path],
    output_path: Path,
    fade_seconds: float = 0.0,
    clip_durations: Optional[List[float]] = None,
) -> StitchResult:
    """Concatenate clips in order to a single mp4.

    Inputs may be a mix of video clips and image stills (any path
    ending in ``.png``, ``.jpg``, ``.jpeg``, ``.webp``); image
    stills are converted to a short MP4 segment looping the image
    for the corresponding entry in ``clip_durations`` (defaults to
    4 seconds when None or short).

    ``fade_seconds`` is accepted for API forwards-compatibility but
    not yet wired in — concat demuxer doesn't do crossfades. When
    we add a follow-up that uses the filter_complex graph we can
    honor it.

    Returns success=False with a clear message rather than raising
    so the caller can surface it as a one-line UI notification.
    """
    if not ffmpeg_available():
        return StitchResult(
            success=False, output_path=output_path,
            error=(
                "ffmpeg not found on PATH. Install ffmpeg "
                "(brew install ffmpeg / apt install ffmpeg / "
                "https://ffmpeg.org/download.html) and try again."))
    if not clip_paths:
        return StitchResult(
            success=False, output_path=output_path,
            error="No clips selected to stitch.")
    missing = [p for p in clip_paths if not p.exists()]
    if missing:
        return StitchResult(
            success=False, output_path=output_path,
            error=(
                f"Cannot stitch — {len(missing)} clip file(s) "
                f"missing on disk: {missing[0].name}"
                + (f" (+{len(missing) - 1} more)"
                   if len(missing) > 1 else "")))
    # Pair each path with its requested display time (used for image
    # stills) BEFORE we filter — keep alignment between path and
    # duration as we drop placeholders.
    durations = list(clip_durations or [])
    while len(durations) < len(clip_paths):
        durations.append(4.0)  # safe default for any unspecified
    pairs: List[Tuple[Path, float]] = list(zip(clip_paths, durations))
    # Skip placeholder / empty files — they aren't real media.
    real_pairs = [
        (p, d) for p, d in pairs
        if p.exists() and p.stat().st_size > 0
    ]
    if not real_pairs:
        return StitchResult(
            success=False, output_path=output_path,
            error=(
                "All selected clips are placeholders (0 bytes). "
                "Generate real videos / images with an installed "
                "backend before stitching."))
    real_clips = [p for p, _ in real_pairs]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Convert any image stills to short MP4 segments first, holding
    # the references in ``staged_paths`` so we know which to clean
    # up at the end. Video clips pass through unchanged.
    staging_dir: Optional[Path] = None
    staged_paths: List[Path] = []
    temp_segments: List[Path] = []
    try:
        for i, (p, dur) in enumerate(real_pairs):
            if _looks_like_image(p):
                if staging_dir is None:
                    staging_dir = Path(tempfile.mkdtemp(
                        prefix="wa_stitch_"))
                seg = staging_dir / f"still_{i:03d}.mp4"
                err = _render_image_segment(
                    p, seg, duration=max(1.0, float(dur)))
                if err:
                    return StitchResult(
                        success=False, output_path=output_path,
                        error=(
                            f"Could not render image still "
                            f"'{p.name}' as a video segment: {err}"))
                staged_paths.append(seg)
                temp_segments.append(seg)
            else:
                staged_paths.append(p)

        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False) as f:
            for p in staged_paths:
                # The concat demuxer requires file '...' with single
                # quotes; escape internal single quotes per ffmpeg's
                # rules ('\''...).
                escaped = str(p.resolve()).replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")
            manifest_path = Path(f.name)

        # When ALL inputs were already-encoded MP4s we can stream-
        # copy. If any image stills were rendered fresh, ``-c copy``
        # may fail when codec/timebase mismatches the existing
        # clips — re-encode instead. Slower but reliable.
        codec_args = (["-c", "copy"]
                      if not temp_segments else
                      ["-c:v", "libx264", "-pix_fmt", "yuv420p",
                       "-r", "30"])
        try:
            proc = subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(manifest_path),
                 *codec_args,
                 str(output_path)],
                capture_output=True, text=True, timeout=300)
            if proc.returncode != 0:
                return StitchResult(
                    success=False, output_path=output_path,
                    error=(
                        "ffmpeg concat failed. stderr (last 400 chars):\n"
                        + (proc.stderr or "")[-400:]))
            return StitchResult(
                success=True, output_path=output_path)
        except subprocess.TimeoutExpired:
            return StitchResult(
                success=False, output_path=output_path,
                error="ffmpeg timed out after 5 minutes.")
        except Exception as e:
            return StitchResult(
                success=False, output_path=output_path,
                error=f"ffmpeg invocation failed: {e}")
        finally:
            try:
                manifest_path.unlink()
            except Exception:
                pass
    finally:
        # Always clean up image-still staging — they're disposable
        # by-products of the stitch.
        if staging_dir is not None:
            try:
                shutil.rmtree(staging_dir, ignore_errors=True)
            except Exception:
                pass


# ---------------------------------------------------------------------
# Image-still helpers
# ---------------------------------------------------------------------
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _looks_like_image(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_EXTENSIONS


# ---------------------------------------------------------------------
# Audio mux — combine a per-scene clip with a narration track
# ---------------------------------------------------------------------
@dataclass
class MuxResult:
    success: bool
    output_path: Path
    error: str = ""
    # Effective duration of the produced clip in seconds (the longer
    # of video / audio, or the trimmed length depending on mode).
    effective_duration: float = 0.0


# Valid mismatch handler names. Mirrored from
# ``models.VIDEO_AUDIO_MISMATCH_MODES`` so callers can validate
# before invoking the mux.
MISMATCH_MODES = (
    "trim", "loop", "fade_extend", "extend_silent",
)


def mix_voiceover_segments(
    segments: List[Any],
    scene_visual_duration: float,
    action_starts: Optional[dict] = None,
    output_path: Optional[Path] = None,
) -> "MuxResult":
    """Render a single audio track from a scene's voiceover takes.

    Each segment carries: ``audio_path``, ``start_at``,
    ``in_point``, ``out_point``, ``gain_db``, ``fade_in_seconds``,
    ``fade_out_seconds``, ``muted``, ``anchored_to_action_id``.
    We build one ffmpeg ``filter_complex`` graph that:

      * loads each non-muted segment as an input
      * trims with ``atrim`` (in/out points within the source)
      * applies ``volume`` for gain
      * applies ``afade`` for fade-in / fade-out
      * delays via ``adelay`` so each segment lands at the right
        offset on the master timeline (anchor-resolved or raw)
      * mixes everything into a single stereo track via ``amix``
      * pads / trims to the scene's visual duration so the final
        clip's audio aligns with the video / image / deck

    Returns a ``MuxResult``. Caller uses the output_path with
    ``mux_audio`` to attach the mixed track to the visuals.
    """
    if not ffmpeg_available():
        return MuxResult(
            success=False,
            output_path=output_path or Path("voiceover.wav"),
            error="ffmpeg not found on PATH.")
    if output_path is None:
        return MuxResult(
            success=False, output_path=Path("voiceover.wav"),
            error="output_path is required.")
    active = [
        s for s in (segments or [])
        if not getattr(s, "muted", False)
        and getattr(s, "audio_path", "")
        and Path(s.audio_path).exists()
        and Path(s.audio_path).stat().st_size > 0
    ]
    if not active:
        return MuxResult(
            success=False, output_path=output_path,
            error="No active voiceover segments to mix.")
    # Resolve each segment's start time. When the segment is
    # anchored to an action, the action's slide-start wins —
    # caller supplies ``action_starts`` (action_id → seconds).
    action_starts = action_starts or {}
    inputs: List[str] = []
    filter_parts: List[str] = []
    mix_labels: List[str] = []
    for idx, seg in enumerate(active):
        inputs.extend(["-i", str(Path(seg.audio_path).resolve())])
        in_pt = float(getattr(seg, "in_point", 0.0) or 0.0)
        out_pt = float(getattr(seg, "out_point", 0.0) or 0.0)
        gain_db = float(getattr(seg, "gain_db", 0.0) or 0.0)
        fade_in = float(getattr(seg, "fade_in_seconds", 0.0) or 0.0)
        fade_out = float(getattr(seg, "fade_out_seconds", 0.0) or 0.0)
        anchor = getattr(seg, "anchored_to_action_id", None)
        start = action_starts.get(anchor) if anchor else None
        if start is None:
            start = float(getattr(seg, "start_at", 0.0) or 0.0)
        start = max(0.0, start)
        # Build the per-segment filter chain.
        chain: List[str] = []
        if out_pt > in_pt > 0:
            chain.append(f"atrim={in_pt:.3f}:{out_pt:.3f}")
        elif in_pt > 0:
            chain.append(f"atrim=start={in_pt:.3f}")
        elif out_pt > 0:
            chain.append(f"atrim=end={out_pt:.3f}")
        # asetpts so trims re-base to 0 — without this adelay
        # would skip over the trimmed lead-in.
        chain.append("asetpts=PTS-STARTPTS")
        if gain_db != 0.0:
            # Convert dB to linear ratio. ffmpeg's volume filter
            # also accepts dB directly via ``volume=NdB`` but
            # explicit ratio is clearer.
            chain.append(f"volume={gain_db:.2f}dB")
        if fade_in > 0:
            chain.append(
                f"afade=t=in:st=0:d={fade_in:.3f}")
        if fade_out > 0:
            played = (
                (out_pt - in_pt) if (out_pt > in_pt) else
                float(
                    getattr(seg, "source_duration_seconds", 0.0))
                or 0.0)
            if played > 0:
                fade_start = max(0.0, played - fade_out)
                chain.append(
                    f"afade=t=out:"
                    f"st={fade_start:.3f}:d={fade_out:.3f}")
        if start > 0:
            chain.append(
                f"adelay={int(start * 1000)}|{int(start * 1000)}")
        # Force stereo so amix doesn't fail on mono ↔ stereo mix.
        chain.append("aformat=channel_layouts=stereo")
        label = f"a{idx}"
        filter_parts.append(
            f"[{idx}:a]" + ",".join(chain) + f"[{label}]")
        mix_labels.append(f"[{label}]")
    # Mix everything down. ``normalize=0`` keeps perceptual loudness
    # consistent with the writer's chosen gains (default amix
    # normalises which writers usually don't want).
    mix_filter = (
        "".join(mix_labels)
        + f"amix=inputs={len(mix_labels)}:duration=longest:normalize=0[mix]")
    filter_parts.append(mix_filter)
    # Pad / trim to scene visual duration.
    if scene_visual_duration > 0:
        filter_parts.append(
            f"[mix]apad=pad_dur=0,"
            f"atrim=0:{scene_visual_duration:.3f}[out]")
        out_label = "out"
    else:
        out_label = "mix"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", f"[{out_label}]",
        "-c:a", "pcm_s16le",
        str(output_path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            return MuxResult(
                success=False, output_path=output_path,
                error=(
                    "ffmpeg voiceover mix failed. stderr "
                    "(last 400 chars):\n"
                    + (proc.stderr or "")[-400:]))
        return MuxResult(
            success=True, output_path=output_path,
            effective_duration=float(scene_visual_duration))
    except subprocess.TimeoutExpired:
        return MuxResult(
            success=False, output_path=output_path,
            error="ffmpeg voiceover mix timed out after 10 minutes.")
    except Exception as e:
        return MuxResult(
            success=False, output_path=output_path,
            error=f"ffmpeg voiceover mix raised: {e}")


def mux_audio(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    *,
    mode: str = "trim",
    video_duration: float = 0.0,
    audio_duration: float = 0.0,
) -> MuxResult:
    """Combine a narration track with a video clip via ffmpeg.

    ``mode`` decides what happens when video and audio differ in
    length — see ``MISMATCH_MODES``. ``video_duration`` and
    ``audio_duration`` are best-effort hints used only by the
    loop / fade_extend / extend_silent modes (the ``trim`` mode
    uses ffmpeg's ``-shortest`` and doesn't need them).

    Returns ``success=False`` with a descriptive error on failure
    so the caller (scene generation, stitching) can surface the
    message in the UI.
    """
    if not ffmpeg_available():
        return MuxResult(
            success=False, output_path=output_path,
            error=(
                "ffmpeg not found on PATH. Install ffmpeg and "
                "try again."))
    if not video_path.exists() or video_path.stat().st_size == 0:
        return MuxResult(
            success=False, output_path=output_path,
            error=f"Video clip missing or empty: {video_path}")
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        return MuxResult(
            success=False, output_path=output_path,
            error=f"Audio file missing or empty: {audio_path}")
    if mode not in MISMATCH_MODES:
        return MuxResult(
            success=False, output_path=output_path,
            error=f"Unknown mismatch mode: {mode!r}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # When we don't have durations, fall back to ``trim`` since
    # loop / fade / extend all need to know the deltas.
    if (mode != "trim"
            and (video_duration <= 0 or audio_duration <= 0)):
        mode = "trim"

    cmd: List[str]
    if mode == "trim":
        # ``-shortest`` cuts the longer stream to match the
        # shorter. Simplest and safest default.
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac",
            "-shortest",
            str(output_path),
        ]
        effective = min(video_duration or 0.0,
                        audio_duration or 0.0) or 0.0
    elif mode == "loop":
        # ``-stream_loop -1`` on the video repeats until ``-t``
        # cuts it at audio length. Audio plays through once.
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-t", f"{audio_duration:.2f}",
            str(output_path),
        ]
        effective = float(audio_duration)
    elif mode == "fade_extend":
        # Hold the last frame after the video ends, fading to
        # black over the trailing audio. ``tpad`` clones the
        # final frame for the gap, ``fade`` does the dim.
        gap = max(0.0, audio_duration - video_duration)
        fade_start = max(0.0, audio_duration - gap)
        # Fade out the audio's tail too so it doesn't cut harshly.
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-filter_complex",
            (f"[0:v]tpad=stop_mode=clone:"
             f"stop_duration={gap:.2f},"
             f"fade=t=out:st={fade_start:.2f}:d={gap:.2f}[v];"
             f"[1:a]afade=t=out:st={fade_start:.2f}:d=0.5[a]"),
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-t", f"{audio_duration:.2f}",
            str(output_path),
        ]
        effective = float(audio_duration)
    else:  # extend_silent
        # Audio shorter than video — pad audio with silence so
        # video plays to natural end.
        gap = max(0.0, video_duration - audio_duration)
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-filter_complex",
            (f"[1:a]apad=pad_dur={gap:.2f}[a]"),
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac",
            "-t", f"{video_duration:.2f}",
            str(output_path),
        ]
        effective = float(video_duration)

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            return MuxResult(
                success=False, output_path=output_path,
                error=(
                    f"ffmpeg mux failed (mode={mode}). "
                    f"stderr (last 400 chars):\n"
                    + (proc.stderr or "")[-400:]))
        return MuxResult(
            success=True, output_path=output_path,
            effective_duration=effective)
    except subprocess.TimeoutExpired:
        return MuxResult(
            success=False, output_path=output_path,
            error="ffmpeg mux timed out after 10 min.")
    except Exception as e:
        return MuxResult(
            success=False, output_path=output_path,
            error=f"ffmpeg mux invocation failed: {e}")


def _render_image_segment(
    image_path: Path, output_path: Path, duration: float,
) -> Optional[str]:
    """Encode a single image as a silent MP4 segment held for
    ``duration`` seconds. Returns None on success, or an error
    string. Uses libx264 with yuv420p so the segment concatenates
    cleanly with real video clips later.
    """
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y",
             "-loop", "1",
             "-t", f"{duration:.2f}",
             "-i", str(image_path),
             "-c:v", "libx264",
             "-pix_fmt", "yuv420p",
             "-r", "30",
             # Pad to even dimensions; libx264 requires even W/H
             "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
             str(output_path)],
            capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return (proc.stderr or "")[-400:]
        return None
    except subprocess.TimeoutExpired:
        return "ffmpeg image-segment encode timed out after 2 min."
    except Exception as e:
        return str(e)
