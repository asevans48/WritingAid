"""Slide-deck editor helpers: build a project from chapter scenes,
distribute timings from a pasted script, and stitch the result
into an MP4 (image stills + per-slide audio).

Kept separate from the chapter-deck export module because the
slide editor's model is finer-grained — one slide per action
favorite — and the audio handling is per-slide rather than a
single master mix.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, List, Optional, Tuple

from src.video_studio.models import (
    SlideDeckProject, SlideGroup, SlidePage,
)
from src.video_studio.stitcher import (
    ffmpeg_available, stitch_clips, stitch_with_transitions,
)


# Minimum duration we clamp a slide to. Anything shorter and the
# stitcher's image-to-MP4 conversion produces noisy output, and
# the audio mux can drop the slide entirely on some ffmpeg builds.
MIN_SLIDE_SECONDS = 1.0

# How long the LAST slide of a group may keep showing after its
# narration has finished. Kept tiny so groups butt-join cleanly on
# a cut instead of freezing on the final image for ~0.5s (the "gap
# between groups" writers see when no transition is selected). When
# the narration runs longer than the slide, the slide still
# stretches to cover it — this only caps the trailing silent hold.
MAX_TRAILING_HOLD_SECONDS = 0.15


def build_slide_deck_from_chapter(
    chapter_scenes: List[Any],
    working_dir: Path,
    chapter_id: str = "",
    chapter_label: str = "",
    default_duration_seconds: float = 4.0,
) -> SlideDeckProject:
    """Walk the chapter's scenes and assemble a SlideDeckProject.

    Per scene:
      * Slideshow mode → one page per action's favorite image.
      * Other modes → one page per scene's favorite clip when the
        favorite is an image (videos are skipped — the slide
        editor works with stills).
    """
    deck = SlideDeckProject(
        name=chapter_label or "Slide deck",
        chapter_id=chapter_id,
        working_dir=str(working_dir),
        wpm_estimate=150,
    )
    page_index = 0
    for scene in chapter_scenes:
        scene_label = scene.name or f"Scene {page_index + 1}"
        if (getattr(scene, "mode", "video") == "slideshow"
                and (getattr(scene, "actions", None) or [])):
            for action in scene.actions:
                img = action.favorite_image()
                if img is None:
                    continue
                path_str = (img.file_path or "").strip()
                if not path_str:
                    continue
                p = Path(path_str)
                if not p.exists() or p.stat().st_size == 0:
                    continue
                page = SlidePage(
                    index=page_index,
                    label=f"{scene_label} → "
                          + (action.name or f"action {page_index + 1}"),
                    image_path=str(p),
                    duration_seconds=max(
                        MIN_SLIDE_SECONDS,
                        float(
                            action.display_seconds
                            or scene.image_display_seconds
                            or default_duration_seconds)),
                    source_scene_id=scene.id,
                    source_action_id=action.id,
                )
                deck.pages.append(page)
                page_index += 1
            continue
        # Non-slideshow scene — single slide from the favorite
        # clip when it's an image.
        clip = scene.favorite_clip()
        if clip is None or not clip.file_path:
            continue
        p = Path(clip.file_path)
        if (not p.exists()
                or p.stat().st_size == 0
                or p.suffix.lower() not in
                {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}):
            continue
        page = SlidePage(
            index=page_index,
            label=scene_label,
            image_path=str(p),
            duration_seconds=max(
                MIN_SLIDE_SECONDS,
                float(
                    scene.image_display_seconds
                    or default_duration_seconds)),
            source_scene_id=scene.id,
        )
        deck.pages.append(page)
        page_index += 1
    return deck


def suggest_timings_from_script(
    deck: SlideDeckProject,
    script_text: str,
) -> Tuple[int, str]:
    """Split the script into per-slide chunks (one blank-line
    paragraph per slide), assign each chunk to its slide, and
    compute each slide's duration from word count + WPM. Returns
    ``(slides_touched, message)``.

    Honors ``locked_duration`` — locked slides keep their
    explicit time and the script chunk still lands on them as
    text so the writer can read along.

    Pure heuristic — no LLM call. Writers can override per slide
    afterward or paste a more detailed script and re-run.
    """
    if not deck.pages:
        return (0, "No slides in deck.")
    text = (script_text or "").strip()
    if not text:
        return (0, "No script text provided.")
    # Split on blank lines. Falls back to one-chunk-per-sentence
    # when the writer pasted prose without paragraph breaks.
    chunks = [
        c.strip() for c in re.split(r"\n\s*\n", text)
        if c.strip()
    ]
    if len(chunks) <= 1:
        # Sentence split as the fallback so a single paragraph
        # still distributes across slides instead of all landing
        # on slide 1.
        sentences = re.split(r"(?<=[.!?])\s+", chunks[0] if chunks else text)
        chunks = [s.strip() for s in sentences if s.strip()]
    if not chunks:
        return (0, "No usable script chunks found.")
    pages = deck.pages
    # When the writer gave us more chunks than slides, pool the
    # tail into the last slide. When fewer chunks, distribute
    # evenly across slides.
    per_slide: List[str] = ["" for _ in pages]
    if len(chunks) <= len(pages):
        # Distribute by stretching — chunk i lands on page
        # round(i * pages / chunks). This keeps order without
        # leaving early slides starved.
        n_pages = len(pages)
        n_chunks = len(chunks)
        for i, chunk in enumerate(chunks):
            target = int(round(i * (n_pages - 1) / max(1, n_chunks - 1))) \
                if n_chunks > 1 else 0
            if per_slide[target]:
                per_slide[target] += "\n\n" + chunk
            else:
                per_slide[target] = chunk
    else:
        # More chunks than slides: assign chunk i to slide
        # floor(i * pages / chunks). Tail chunks pool on the last.
        for i, chunk in enumerate(chunks):
            target = min(
                len(pages) - 1,
                int(i * len(pages) / len(chunks)))
            if per_slide[target]:
                per_slide[target] += "\n\n" + chunk
            else:
                per_slide[target] = chunk
    wpm = max(60, int(deck.wpm_estimate or 150))
    touched = 0
    for page, chunk in zip(pages, per_slide):
        if not chunk:
            continue
        page.script_text = chunk
        if not page.locked_duration:
            words = max(1, len(chunk.split()))
            secs = max(
                MIN_SLIDE_SECONDS,
                round(words / (wpm / 60.0), 2))
            page.duration_seconds = secs
        touched += 1
    return (
        touched,
        f"Distributed {len(chunks)} chunk(s) across "
        f"{touched} slide(s) at ~{wpm} WPM.")


def adjust_slide_to_audio(page: SlidePage) -> bool:
    """When a recorded / imported audio take is attached, set the
    slide's duration to match. Honors ``locked_duration``. Returns
    True when the duration changed."""
    if page.locked_duration:
        return False
    if (page.audio_duration_seconds <= 0
            or not page.audio_path):
        return False
    new_dur = max(MIN_SLIDE_SECONDS,
                  round(page.audio_duration_seconds + 0.2, 2))
    if abs(new_dur - page.duration_seconds) < 0.05:
        return False
    page.duration_seconds = new_dur
    return True


def distribute_group_timings(
    deck: SlideDeckProject,
    group: SlideGroup,
) -> int:
    """Evenly split a group's ``target_total_seconds`` across its
    UNLOCKED pages. Locked pages keep their exact times; the
    remainder splits equally across the rest. Returns the count
    of pages whose duration changed."""
    if group.target_total_seconds <= 0:
        return 0
    pages_by_id = {p.id: p for p in deck.pages}
    members = [
        pages_by_id[pid] for pid in group.page_ids
        if pid in pages_by_id]
    if not members:
        return 0
    locked = [p for p in members if p.locked_duration]
    unlocked = [p for p in members if not p.locked_duration]
    if not unlocked:
        return 0
    locked_total = sum(p.duration_seconds for p in locked)
    remainder = max(
        0.0, group.target_total_seconds - locked_total)
    if remainder <= 0:
        return 0
    per_page = max(
        MIN_SLIDE_SECONDS, remainder / len(unlocked))
    changed = 0
    for p in unlocked:
        if abs(p.duration_seconds - per_page) > 0.05:
            p.duration_seconds = round(per_page, 2)
            changed += 1
    return changed


def export_slide_deck_to_pptx(
    deck: SlideDeckProject,
    output_path: Path,
) -> Tuple[bool, str, List[str]]:
    """Render a SlideDeckProject as a PowerPoint file.

    One slide per ``SlidePage`` with its image as the only visual.
    Per-slide audio is embedded (if present) and configured to
    play on slide entry, so when the deck is opened in PowerPoint
    / Keynote / Slides the narration runs automatically. Each
    slide's advance time is set to its ``duration_seconds`` so a
    slideshow presentation matches the recorded timings.

    No text overlays — the writer can edit freely in their slide
    tool. Returns ``(success, message, skipped)``.
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches
        from pptx.dml.color import RGBColor
        from pptx.oxml.ns import qn
        from lxml import etree
    except Exception as e:
        return (
            False,
            (
                "python-pptx isn't installed. Install it with:\n"
                "  pip install python-pptx\n\n"
                f"Underlying error: {e}"),
            [])
    pages = [
        p for p in deck.pages
        if p.image_path and Path(p.image_path).exists()]
    if not pages:
        return (
            False,
            "No slides with usable images on disk.",
            [])
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]
    slide_w_emu = int(prs.slide_width)
    slide_h_emu = int(prs.slide_height)
    skipped: List[str] = []
    AUDIO_EXTS = {
        ".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac",
        ".opus", ".aiff", ".aif"}
    for page in pages:
        slide = prs.slides.add_slide(blank_layout)
        # Pure black background — the image is the show.
        bg = slide.background.fill
        bg.solid()
        bg.fore_color.rgb = RGBColor(0x00, 0x00, 0x00)
        # Image, fitted preserving aspect ratio.
        try:
            left, top, width, height = _fit_image_to_slide(
                Path(page.image_path),
                slide_w_emu, slide_h_emu)
            slide.shapes.add_picture(
                page.image_path, left, top,
                width=width, height=height)
        except Exception as e:
            skipped.append(
                f"{page.label or page.id}: image embed failed "
                f"({e})")
            continue
        # Per-slide audio — embedded via add_movie. PowerPoint
        # treats audio files (.wav / .mp3 / etc.) as media objects
        # too. We tuck the speaker icon offscreen and patch the XML
        # to play automatically + hide while playing — that's
        # what writers expect for narration.
        if (page.audio_path
                and Path(page.audio_path).exists()
                and Path(page.audio_path).suffix.lower()
                in AUDIO_EXTS):
            try:
                # 32 EMU ≈ ~0.03 inch — effectively invisible.
                from pptx.util import Emu
                icon_w = Emu(304800)  # 0.5 in
                icon_h = Emu(304800)
                # Park the speaker icon in the bottom-right corner
                # off the visible canvas, so writers can still find
                # it to edit if needed.
                left = slide_w_emu - icon_w - Emu(91440)
                top = slide_h_emu - icon_h - Emu(91440)
                movie = slide.shapes.add_movie(
                    page.audio_path, left, top, icon_w, icon_h,
                    mime_type="audio/x-wav")
                # Patch the timing XML so the audio auto-plays on
                # slide entry. python-pptx leaves this as
                # ``click`` by default.
                _patch_media_autoplay(slide, movie)
            except Exception as e:
                skipped.append(
                    f"{page.label or page.id}: audio embed "
                    f"failed ({e})")
        # Per-slide advance time — slideshow honors this as the
        # auto-advance interval. The XML lives on the slide's
        # transition element.
        try:
            secs = max(
                MIN_SLIDE_SECONDS,
                float(page.duration_seconds))
            _set_slide_advance_time(slide, secs)
        except Exception as e:
            skipped.append(
                f"{page.label or page.id}: advance-time set "
                f"failed ({e})")
        # Per-slide transition effect. The first slide ignores its
        # transition (no previous slide). PowerPoint stores the
        # transition on the SLIDE you're transitioning INTO, which
        # matches the writer's "transition_in" semantic.
        if (page.index > 0
                and (page.transition_in or "cut") != "cut"):
            try:
                _set_slide_transition_effect(
                    slide,
                    page.transition_in,
                    float(page.transition_seconds or 0.7))
            except Exception as e:
                skipped.append(
                    f"{page.label or page.id}: transition set "
                    f"failed ({e})")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        prs.save(str(output_path))
    except Exception as e:
        return (
            False, f"PowerPoint save failed: {e}", skipped)
    return (
        True,
        f"PowerPoint deck saved to {output_path}.",
        skipped)


def _fit_image_to_slide(
    image_path: Path, slide_w_emu: int, slide_h_emu: int,
) -> Tuple[int, int, int, int]:
    """Compute (left, top, width, height) in EMUs that fits the
    image in the slide preserving its aspect ratio. Falls back to
    full-bleed when the image can't be probed."""
    try:
        from PIL import Image
        with Image.open(image_path) as im:
            img_w, img_h = im.size
    except Exception:
        return (0, 0, slide_w_emu, slide_h_emu)
    if img_w <= 0 or img_h <= 0:
        return (0, 0, slide_w_emu, slide_h_emu)
    slide_aspect = slide_w_emu / slide_h_emu
    img_aspect = img_w / img_h
    if img_aspect > slide_aspect:
        width = slide_w_emu
        height = int(slide_w_emu / img_aspect)
        left = 0
        top = (slide_h_emu - height) // 2
    else:
        height = slide_h_emu
        width = int(slide_h_emu * img_aspect)
        top = 0
        left = (slide_w_emu - width) // 2
    return (left, top, width, height)


def _patch_media_autoplay(slide, movie) -> None:
    """Replace the click-to-play trigger on a movie shape with an
    auto-play-on-slide-entry trigger, and hide the speaker icon
    while presenting.

    PowerPoint stores this in the slide's ``<p:timing>`` element.
    python-pptx exposes the underlying XML so we can walk it,
    swap ``clickEffect`` → ``withEffect``, and add a
    ``showMediaCtrls=0`` attribute on the picture.
    """
    from pptx.oxml.ns import qn
    timing = slide.element.find(qn("p:timing"))
    if timing is None:
        return
    # Find every condition that triggers on click and flip it.
    for cond in timing.iter(qn("p:cond")):
        evt = cond.get("evt")
        if evt == "onClick":
            cond.set("evt", "afterEffect")
    # Mark every video filter so PowerPoint hides the speaker
    # icon during playback (it's already tucked offscreen, but
    # belt and braces).
    media_id = movie.shape_id
    for video_shape in slide.element.iter(qn("p:pic")):
        nvSpPr = video_shape.find(qn("p:nvPicPr"))
        if nvSpPr is None:
            continue
        cNvPr = nvSpPr.find(qn("p:cNvPr"))
        if cNvPr is None:
            continue
        if cNvPr.get("id") == str(media_id):
            # Hide media controls while the slide plays.
            cNvPr.set("hidden", "1")
            break


def _set_slide_advance_time(slide, seconds: float) -> None:
    """Configure the slide's transition so PowerPoint auto-
    advances after ``seconds`` seconds during a slideshow.

    PPT stores advance time in milliseconds on the
    ``<p:transition>`` element via the ``advTm`` attribute.
    ``advClick="0"`` keeps the click-advance off so the auto-time
    is the only trigger.
    """
    from pptx.oxml.ns import qn
    from lxml import etree
    transition = slide.element.find(qn("p:transition"))
    if transition is None:
        transition = etree.SubElement(
            slide.element, qn("p:transition"))
    transition.set("advClick", "0")
    transition.set("advTm", str(int(seconds * 1000)))


# Map our shared xfade transition keys (CHAPTER_TRANSITIONS) to
# PowerPoint transition element names. Some xfade options have
# no exact PPT analogue — we substitute the visually closest
# option so writers don't lose the cue.
_PPT_TRANSITION_MAP = {
    "cut": None,
    "fade": ("fade", {}),
    "fadeblack": ("fade", {"thruBlk": "1"}),
    "fadewhite": ("fade", {"thruBlk": "1"}),
    "dissolve": ("fade", {}),
    "slideleft": ("push", {"dir": "l"}),
    "slideright": ("push", {"dir": "r"}),
    "slideup": ("push", {"dir": "u"}),
    "slidedown": ("push", {"dir": "d"}),
    "wipeleft": ("wipe", {"dir": "l"}),
    "wiperight": ("wipe", {"dir": "r"}),
    "circleopen": ("circle", {}),
    "circleclose": ("circle", {}),
    "radial": ("wheel", {"spokes": "1"}),
}


def _set_slide_transition_effect(
    slide, xfade_key: str, seconds: float,
) -> None:
    """Attach a PowerPoint-style transition effect to the slide
    based on the writer's xfade pick. ``cut`` is a no-op.

    PowerPoint expresses transitions via a child element of
    ``<p:transition>`` (e.g. ``<p:fade/>``, ``<p:wipe dir="l"/>``).
    The transition's speed is ``"fast"``/``"med"``/``"slow"`` —
    mapped from seconds.
    """
    from pptx.oxml.ns import qn
    from lxml import etree
    mapping = _PPT_TRANSITION_MAP.get(
        (xfade_key or "cut").lower())
    if mapping is None:
        return
    transition = slide.element.find(qn("p:transition"))
    if transition is None:
        transition = etree.SubElement(
            slide.element, qn("p:transition"))
    # Pick speed based on duration.
    if seconds <= 0.4:
        speed = "fast"
    elif seconds >= 1.2:
        speed = "slow"
    else:
        speed = "med"
    transition.set("spd", speed)
    name, attrs = mapping
    effect = etree.SubElement(
        transition, qn(f"p:{name}"))
    for k, v in attrs.items():
        effect.set(k, v)


def _track_map_get(m: Any, idx: int, default: Any = None) -> Any:
    """Read a per-track dict that may be keyed by int OR str
    (JSON round-trips int keys to strings)."""
    if not m:
        return default
    if idx in m:
        return m[idx]
    if str(idx) in m:
        return m[str(idx)]
    return default


def _next_free_track(group: SlideGroup) -> int:
    """Lowest track index not already used by a clip in ``group``."""
    used = {
        int(getattr(c, "track_index", 0) or 0)
        for c in (getattr(group, "audio_clips", None) or [])}
    i = 0
    while i in used:
        i += 1
    return i


def copy_group_track(
    src_group: SlideGroup,
    track_index: int,
    dst_group: SlideGroup,
    dst_track_index: Optional[int] = None,
) -> int:
    """Replicate one lane from ``src_group`` into ``dst_group``.

    Copies every clip on ``src_group``'s ``track_index`` — with
    all its edits (gain, fades, trims, de-esser, denoise) — plus
    that lane's settings (name, gain, de-esser, mute, background
    loop). Clips are DEEP-copied with fresh ids so the two groups
    stay fully independent: editing one lane never touches the
    other. Lands on ``dst_track_index`` (or the next free lane in
    the destination when omitted). Returns the destination track
    index. Does NOT recompose — the caller owns that so it can
    batch the render.
    """
    from uuid import uuid4
    src_clips = [
        c for c in (getattr(src_group, "audio_clips", None) or [])
        if int(getattr(c, "track_index", 0) or 0) == track_index]
    if dst_track_index is None:
        dst_track_index = _next_free_track(dst_group)
    if getattr(dst_group, "audio_clips", None) is None:
        dst_group.audio_clips = []
    for c in src_clips:
        nc = c.model_copy(deep=True)
        nc.id = f"aclip_{uuid4().hex[:10]}"
        nc.track_index = int(dst_track_index)
        dst_group.audio_clips.append(nc)
    # Carry the lane's treatment across so the copy sounds the
    # same, not just plays the same clips.
    for attr in (
            "track_names", "track_gain_db",
            "track_deesser_intensity", "track_muted",
            "track_background"):
        src_map = getattr(src_group, attr, None) or {}
        val = _track_map_get(src_map, track_index, None)
        if val is None:
            continue
        dst_map = dict(getattr(dst_group, attr, None) or {})
        # Normalize to int keys so the destination stays clean.
        dst_map = {
            int(k): v for k, v in dst_map.items()
            if str(k).lstrip("-").isdigit()}
        dst_map[int(dst_track_index)] = val
        setattr(dst_group, attr, dst_map)
    return int(dst_track_index)


def group_has_background_lane(group: SlideGroup) -> bool:
    """True when ``group`` owns a background-loop lane with clips —
    i.e. a lane flagged in ``track_background`` that actually has
    audio on it. This is what the deck-wide universal bed defers to
    (OFF mode) or replaces (ON mode)."""
    bgs = getattr(group, "track_background", None) or {}
    bg_lanes = {
        int(k) for k, v in bgs.items()
        if str(k).lstrip("-").isdigit() and bool(v)}
    if not bg_lanes:
        return False
    for c in (getattr(group, "audio_clips", None) or []):
        if int(getattr(c, "track_index", 0) or 0) in bg_lanes:
            return True
    return False


def plan_universal_background_regions(
    group_timeline: List[Tuple[float, float, bool]],
    deck_dur: float,
    universal_len: float,
    is_universal: bool,
    complete_final: bool,
) -> Tuple[List[Tuple[float, float]], float]:
    """Decide WHERE (and for how long) the deck's background bed
    plays over the final timeline.

    ``group_timeline`` is one ``(start, end, has_own_bed)`` per
    rendered segment, in final-video seconds. Returns
    ``(regions, extra_tail)`` where each region is
    ``(start_seconds, play_length_seconds)`` — the bed is dropped in
    at ``start`` and loops for ``play_length`` — and ``extra_tail``
    is how many seconds the deck video must be extended past its
    natural end so the final loop can complete (0 when it is cut).

    Rules encoded:
      * Universal (ON): one region covering the whole deck; group
        beds are suppressed elsewhere.
      * Non-universal (OFF): regions are the maximal runs of
        consecutive segments with NO background lane of their own;
        a group that owns a bed is left to play it, and the deck
        bed restarts from the beginning at the next no-bed run.
      * Loops are whole cycles. A mid-deck region is cut at its
        boundary (the next bed-group takes over). Only the region
        that reaches the deck's end honors ``complete_final`` —
        letting the last loop finish past the end (``extra_tail``).
    """
    import math
    regions: List[Tuple[float, float]] = []
    extra_tail = 0.0
    if universal_len <= 0 or not group_timeline or deck_dur <= 0:
        return regions, extra_tail
    if is_universal:
        runs: List[Tuple[float, float]] = [(0.0, deck_dur)]
    else:
        runs = []
        cur: Optional[List[float]] = None
        for (s, e, has_bed) in group_timeline:
            if has_bed:
                if cur is not None:
                    runs.append((cur[0], cur[1]))
                    cur = None
            else:
                if cur is None:
                    cur = [s, e]
                else:
                    cur[1] = e
        if cur is not None:
            runs.append((cur[0], cur[1]))
    for (rs, re) in runs:
        length = max(0.0, re - rs)
        if length <= 0:
            continue
        reaches_end = abs(re - deck_dur) < 0.05
        if reaches_end and complete_final:
            cycles = max(1, math.ceil(length / universal_len - 1e-6))
            full = cycles * universal_len
            extra_tail = max(extra_tail, (rs + full) - deck_dur)
            length = full
        regions.append((round(rs, 3), round(length, 3)))
    return regions, extra_tail


def compose_group_overlay_variant(
    group: SlideGroup,
    working_dir: str,
    exclude_background: bool,
) -> str:
    """Compose ``group``'s overlay, optionally EXCLUDING its
    background-loop lanes (narration / foreground only). Used when
    a universal deck bed replaces group beds: the group renders its
    voice, the deck bed carries the music. Returns the WAV path, or
    "" when there's nothing to render. Non-excluded calls just defer
    to the normal resolver so the cache stays shared."""
    if not exclude_background:
        return resolve_group_overlay(group, working_dir=working_dir)
    clips = getattr(group, "audio_clips", None) or []
    if not clips:
        return ""
    bgs = getattr(group, "track_background", None) or {}
    bg_lanes = {
        int(k) for k, v in bgs.items()
        if str(k).lstrip("-").isdigit() and bool(v)}
    if not bg_lanes:
        # No bed to strip — identical to the normal overlay.
        return resolve_group_overlay(group, working_dir=working_dir)
    try:
        from src.video_studio.audio_edit import compose_clips
    except Exception:
        return resolve_group_overlay(group, working_dir=working_dir)
    # Mute the background lanes on top of any existing mutes.
    muted = {
        int(k): bool(v)
        for k, v in (getattr(group, "track_muted", None) or {}).items()
        if str(k).lstrip("-").isdigit()}
    for lane in bg_lanes:
        muted[lane] = True
    dest_dir = Path(
        working_dir
        or (Path.home() / ".writingaid_slides")) / "group_overlay"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return resolve_group_overlay(group, working_dir=working_dir)
    dest = dest_dir / f"{group.id}_narration.wav"
    try:
        result = compose_clips(
            clips, dest,
            track_gain_db=getattr(group, "track_gain_db", None),
            track_deesser_intensity=getattr(
                group, "track_deesser_intensity", None),
            track_muted=muted,
            track_background=getattr(
                group, "track_background", None))
    except Exception:
        return resolve_group_overlay(group, working_dir=working_dir)
    if not result.success:
        return ""
    return str(dest)


def resolve_deck_background(deck: SlideDeckProject) -> str:
    """Return an on-disk WAV for the deck's background bed, with
    every clip edit (trim, gain, fades, de-esser, noise reduction,
    per-lane treatment) baked in. The bed is stored as a
    ``SlideGroup`` (``deck.background_group``), so this just defers
    to ``resolve_group_overlay`` — the exact renderer group tracks
    use. Returns "" when there is no bed."""
    bg_group = getattr(deck, "background_group", None)
    if bg_group is None or not (
            getattr(bg_group, "audio_clips", None) or []):
        return ""
    return resolve_group_overlay(
        bg_group, working_dir=deck.working_dir)


def resolve_group_overlay(
    group: SlideGroup,
    working_dir: str = "",
) -> str:
    """Return an on-disk overlay WAV for ``group`` that carries
    every audio-clip edit (gain, de-essing, noise reduction,
    per-lane looping, fades, trims) baked in.

    ``audio_clips`` is the source of truth; ``overlay_audio_path``
    is a rendered cache the group editor refreshes after each
    edit. Exports and previews used to trust that cache blindly —
    so when the cache file was missing (deck moved between
    machines, working_dir changed, the composed WAV was cleaned,
    or the clips were populated by a path that never opened the
    group editor) the export silently dropped the group's sound.

    This helper closes that gap: if the cached file is present it
    is returned as-is (fast path — the editor keeps it fresh);
    otherwise the overlay is recomposed from ``audio_clips`` right
    here so the narration — with all its edits — still lands in
    the render. Returns "" when the group genuinely has no audio.
    """
    cached = (getattr(group, "overlay_audio_path", "") or "").strip()
    if cached and Path(cached).exists() \
            and Path(cached).stat().st_size > 0:
        return cached
    clips = getattr(group, "audio_clips", None) or []
    if not clips:
        return ""
    # Cache missing but clips exist — recompose from the source
    # of truth so the edits aren't lost. Import lazily to keep
    # the module importable in environments without the audio
    # stack wired up.
    try:
        from src.video_studio.audio_edit import compose_clips
    except Exception:
        return cached  # best effort — nothing else we can do
    dest_dir = Path(
        working_dir
        or getattr(group, "working_dir", "")
        or (Path.home() / ".writingaid_slides")) / "group_overlay"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return cached
    # Deterministic name so repeated exports reuse one file
    # instead of littering the folder with timestamped renders.
    dest = dest_dir / f"{group.id}_export_overlay.wav"
    try:
        result = compose_clips(
            clips, dest,
            track_gain_db=getattr(group, "track_gain_db", None),
            track_deesser_intensity=getattr(
                group, "track_deesser_intensity", None),
            track_muted=getattr(group, "track_muted", None),
            track_background=getattr(
                group, "track_background", None))
    except Exception:
        return cached
    if not result.success:
        return cached
    # Refresh the in-memory cache so later exports in this session
    # take the fast path (and an autosave persists the valid
    # path). Guarded — some SlideGroup builds may not expose the
    # setters.
    try:
        group.overlay_audio_path = str(dest)
        group.overlay_audio_duration_seconds = float(
            result.duration_seconds or 0.0)
    except Exception:
        pass
    return str(dest)


def render_group_to_mp4(
    deck: SlideDeckProject,
    group: SlideGroup,
    output_path: Path,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
    exclude_background: bool = False,
) -> Tuple[bool, str]:
    """Render ONE group into an MP4 the same way the group
    editor's "Preview" button does.

    Pipeline:
      * Pull the group's placed slides (those with
        ``start_time_seconds_in_group`` set), sort by start
        time.
      * Each slide's render hold = gap to next placed slide;
        the LAST slide stretches to the overlay end if that's
        longer than its own duration.
      * Strip per-slide audio_path (the overlay owns audio
        for the group's span).
      * Attach the group's composed overlay to the first
        slide so the stitcher's ``adelay`` lands it at deck-
        time 0 for this group.
      * Hand the synthetic deck to
        ``stitch_slide_deck_to_mp4``.

    This helper is the single source of truth for "what a
    group sounds + looks like" — both the group editor's
    preview and the slide deck editor's concat-based deck
    preview call it so they stay byte-for-byte consistent.
    """
    placed = sorted(
        (p for p in deck.pages
         if p.group_id == group.id
         and getattr(
             p, "start_time_seconds_in_group", None)
         is not None),
        key=lambda p: float(
            getattr(
                p, "start_time_seconds_in_group", 0.0)
            or 0.0))
    if not placed:
        # A group can carry a fully recorded + edited audio track
        # while its member slides still sit in the tray (the writer
        # recorded narration but never dragged the slides onto the
        # group timeline). Skipping the group outright then drops
        # its sound from every export — the deck renders its
        # visuals as orphan slides but comes out silent, which is
        # exactly the "12 minutes of video, no audio" symptom.
        #
        # Recover gracefully: if the group has audio and at least
        # one member slide, auto-place the members evenly across
        # the narration so the sound has slides to ride on. Uses
        # deep-copied pages so the writer's saved placement (empty)
        # is not mutated behind their back.
        overlay_probe = resolve_group_overlay(
            group, working_dir=deck.working_dir)
        if overlay_probe and Path(overlay_probe).exists():
            members = [
                p for p in deck.pages
                if p.group_id == group.id]
            order = {
                pid: i for i, pid in enumerate(
                    getattr(group, "page_ids", []) or [])}
            members.sort(
                key=lambda p: (
                    order.get(p.id, 1_000_000),
                    getattr(p, "index", 0)))
            if members:
                span = float(
                    getattr(
                        group,
                        "overlay_audio_duration_seconds",
                        0.0) or 0.0)
                if span <= 0:
                    span = max(1.0, len(members) * 3.0)
                per = max(0.25, span / len(members))
                placed = []
                for i, m in enumerate(members):
                    c = m.model_copy(deep=False)
                    c.start_time_seconds_in_group = round(
                        i * per, 3)
                    placed.append(c)
                print(
                    f"[slide_deck] group "
                    f"'{group.name or group.id}' had audio but "
                    f"no placed slides — auto-placed "
                    f"{len(placed)} member slide(s) across "
                    f"{span:.1f}s so its narration exports.")
        if not placed:
            return (False,
                    f"Group '{group.name or group.id}' has no "
                    "placed slides.")
    overlay_dur = float(
        getattr(
            group,
            "overlay_audio_duration_seconds", 0.0) or 0.0)
    render_pages: list = []
    for i, src in enumerate(placed):
        cur_start = float(
            getattr(
                src, "start_time_seconds_in_group", 0.0)
            or 0.0)
        if i + 1 < len(placed):
            next_start = float(
                getattr(
                    placed[i + 1],
                    "start_time_seconds_in_group", 0.0)
                or 0.0)
            hold = max(0.25, next_start - cur_start)
        else:
            own = max(
                0.25, float(
                    getattr(
                        src, "duration_seconds", 0.0)
                    or 0.0))
            tail = max(0.0, overlay_dur - cur_start)
            if tail > 0:
                # There is narration under this group. The last
                # slide should stretch to cover it, but NOT sit
                # frozen and silent for long after the voice stops
                # — that trailing dead-air reads as a ~0.5s gap
                # before the next group on a cut (a transition
                # hides it by overlapping, which is why the gap
                # only shows without one). Cap the post-narration
                # hold to a few frames so groups flow straight
                # into each other while a transition, if set, still
                # has content to fade over.
                hold = max(
                    tail,
                    min(own, tail + MAX_TRAILING_HOLD_SECONDS))
            else:
                hold = own
        copy = src.model_copy(deep=False)
        copy.duration_seconds = round(hold, 3)
        render_pages.append(copy)
    # Resolve (and, if the cache is missing, recompose) the
    # group's overlay so every audio-clip edit — gain, de-essing,
    # noise reduction, looping — is baked into the render even
    # when the cached WAV went missing. When ``exclude_background``
    # is set (a universal deck bed is replacing group beds), render
    # the group's narration WITHOUT its own background-loop lanes so
    # the two beds don't fight.
    overlay_path = compose_group_overlay_variant(
        group, deck.working_dir, exclude_background)
    has_overlay = bool(
        overlay_path and Path(overlay_path).exists())
    if has_overlay:
        # The composed overlay is the group's authoritative audio
        # — it already blends every take + edit — so per-slide
        # audio_path values are redundant and would double up.
        # Strip them and let the overlay own the group's sound.
        for copy in render_pages:
            copy.audio_path = ""
        # Attach the overlay to the first page that has a VALID
        # image on disk. ``stitch_slide_deck_to_mp4`` drops any
        # page whose image is missing before it builds the audio
        # mix — so if we blindly hung the overlay on
        # ``render_pages[0]`` and that first slide's image happened
        # to be gone, the audio was silently discarded along with
        # it while the remaining slides still rendered. That is the
        # "images export, audio doesn't" symptom. Anchoring the
        # audio to a surviving page guarantees the mix step sees
        # it.
        anchor = next(
            (c for c in render_pages
             if getattr(c, "image_path", "")
             and Path(c.image_path).exists()),
            render_pages[0])
        anchor.audio_path = overlay_path
    # else: NO group overlay — keep each slide's own audio_path so
    # narration the writer attached per-slide (via the main slide
    # editor's Import / Record / Edit) still exports. Stripping it
    # here is what silently muted decks whose audio lived on the
    # slides rather than in a group audio track.
    synthetic = SlideDeckProject(
        id=f"render_{group.id}",
        name=f"Group {group.name or group.id}",
        working_dir=deck.working_dir,
        pages=render_pages,
    )
    return stitch_slide_deck_to_mp4(
        synthetic, output_path,
        width=width, height=height, fps=fps)


def stitch_slide_deck_to_mp4(
    deck: SlideDeckProject,
    output_path: Path,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
) -> Tuple[bool, str]:
    """Render the deck into a single MP4: each page is an image
    held for its duration with its audio mixed in.

    Returns ``(success, message)``. Uses the existing
    ``stitch_clips`` for the visual concat, then ffmpeg with
    filter_complex to attach per-slide audio offsets.
    """
    if not ffmpeg_available():
        return (
            False,
            "ffmpeg not found on PATH. Install ffmpeg and try again.")
    pages = [
        p for p in deck.pages
        if p.image_path and Path(p.image_path).exists()]
    if not pages:
        return (False, "No slides with usable images.")
    # Stitch images (no audio) first.
    image_paths = [Path(p.image_path) for p in pages]
    image_durations = [
        max(MIN_SLIDE_SECONDS, float(p.duration_seconds))
        for p in pages]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    silent_path = output_path.with_name(
        output_path.stem + "_silent.mp4")
    # When any slide has a non-cut transition, route through the
    # transition stitcher (xfade) so writers' picks land in the
    # final render. Otherwise stick with the simpler concat path.
    has_transitions = any(
        (p.transition_in or "cut") != "cut"
        and float(p.transition_seconds or 0.0) > 0
        for p in pages[1:])
    if has_transitions:
        transitions = [
            (p.transition_in or "cut",
             float(p.transition_seconds or 0.0))
            for p in pages]
        visual_result = stitch_with_transitions(
            image_paths, silent_path,
            clip_durations=image_durations,
            transitions=transitions,
            width=width, height=height, fps=fps)
        # Each non-cut transition compresses the timeline by
        # ``transition_seconds`` — adjust the per-slide start
        # offsets we use later for audio mixing.
        offsets_adjusted = True
    else:
        visual_result = stitch_clips(
            image_paths, silent_path,
            clip_durations=image_durations)
        offsets_adjusted = False
    if not visual_result.success:
        return (False, visual_result.error)
    # No audio at all? Done.
    audio_pages = [
        (i, p) for i, p in enumerate(pages)
        if p.audio_path and Path(p.audio_path).exists()
        and Path(p.audio_path).stat().st_size > 0
    ]
    if not audio_pages:
        try:
            silent_path.rename(output_path)
        except Exception as e:
            return (
                False,
                f"Could not finalize file: {e}")
        return (True, f"Slide deck saved to {output_path}.")
    # Compute per-page start offsets so each audio take lines up
    # with its slide. When transitions are present, each non-cut
    # boundary's seconds shorten the cumulative timeline (xfade
    # overlaps the prior clip's tail with the next clip's head).
    starts: List[float] = []
    running = 0.0
    for i, d in enumerate(image_durations):
        starts.append(running)
        running += d
        if has_transitions and i + 1 < len(pages):
            next_page = pages[i + 1]
            kind = next_page.transition_in or "cut"
            secs = float(next_page.transition_seconds or 0.0)
            if kind != "cut" and secs > 0:
                running -= secs
    # Build the audio mix filter.
    inputs: List[str] = ["-i", str(silent_path.resolve())]
    filter_parts: List[str] = []
    mix_labels: List[str] = []
    for idx, (page_idx, page) in enumerate(audio_pages, start=1):
        inputs.extend(
            ["-i", str(Path(page.audio_path).resolve())])
        start = starts[page_idx]
        chain = ["asetpts=PTS-STARTPTS"]
        if start > 0:
            chain.append(
                f"adelay={int(start * 1000)}|{int(start * 1000)}")
        chain.append("aformat=channel_layouts=stereo")
        label = f"a{idx}"
        filter_parts.append(
            f"[{idx}:a]" + ",".join(chain) + f"[{label}]")
        mix_labels.append(f"[{label}]")
    filter_parts.append(
        "".join(mix_labels)
        + f"amix=inputs={len(mix_labels)}:duration=longest:"
          "normalize=0[mix]")
    filter_str = ";".join(filter_parts)
    # The visual track is authoritative — we want the full slide
    # run-time even when a slide has shorter (or no) audio. Using
    # ``-shortest`` here would cut the deck the moment the last
    # audio take ends, dropping any trailing silent slides.
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_str,
        "-map", "0:v:0", "-map", "[mix]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-t", f"{running:.3f}",
        str(output_path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=900)
        if proc.returncode != 0:
            return (
                False,
                "ffmpeg slide mux failed. stderr (last 400):\n"
                + (proc.stderr or "")[-400:])
    except subprocess.TimeoutExpired:
        return (False, "ffmpeg slide mux timed out (15 min).")
    finally:
        try:
            silent_path.unlink(missing_ok=True)
        except Exception:
            pass
    return (True, f"Slide deck saved to {output_path}.")
