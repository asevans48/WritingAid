"""Chapter-level deck export.

Walks a chapter's scenes in order, picks each scene's chosen output
(favorite image, video clip, or slideshow stitch), optionally renders
a title card per scene, and concatenates the result into a single
MP4 the writer can share — a "slide deck of the chapter."

The heavy lifting (mixed image+video concatenation) lives in
``stitcher.stitch_clips``; this module just builds the list of
(path, duration) tuples and renders the title cards.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont


# Card geometry matches the stitcher's default 30 fps / yuv420p
# pipeline; 1280x720 looks clean alongside 16:9 video clips and
# scales nicely for both phones and laptops.
TITLE_CARD_SIZE = (1280, 720)
TITLE_CARD_DURATION_SECONDS = 2.5


def render_title_card(
    out_path: Path,
    title: str,
    subtitle: str = "",
    overline: str = "",
    size: Tuple[int, int] = TITLE_CARD_SIZE,
) -> Path:
    """Render a clean, dark-background title card with one scene's
    name + optional metadata. PNG, ready for the stitcher.

    Layout::

        ┌────────────────────────────────────────┐
        │ <overline (small caps, dim)>           │
        │                                        │
        │         <title (large, bold)>          │
        │                                        │
        │ <subtitle (medium, dim)>               │
        └────────────────────────────────────────┘
    """
    w, h = size
    img = Image.new("RGB", size, color=(15, 23, 42))  # slate-900
    draw = ImageDraw.Draw(img)

    # Fonts — fall back to PIL's default when the system fonts
    # we'd prefer aren't reachable. Default is small and ugly but
    # always present, which beats crashing the export.
    title_font = _load_font(72, bold=True)
    subtitle_font = _load_font(28)
    overline_font = _load_font(20)

    pad = 80

    # Overline (small caps look, on a dim color).
    if overline:
        over_text = overline.upper()
        draw.text(
            (pad, pad),
            over_text,
            fill=(148, 163, 184),  # slate-400
            font=overline_font)

    # Title — wrap manually so very long names don't overflow.
    title_lines = _wrap_text(title, title_font, w - 2 * pad, draw)
    # Vertically center the title block.
    line_h = title_font.size + 12 if hasattr(title_font, "size") else 80
    total_h = line_h * len(title_lines)
    title_top = (h - total_h) // 2 - 20
    for i, line in enumerate(title_lines):
        draw.text(
            (pad, title_top + i * line_h),
            line,
            fill=(248, 250, 252),  # slate-50
            font=title_font)

    # Subtitle — under the title block.
    if subtitle:
        sub_y = title_top + total_h + 40
        sub_lines = _wrap_text(
            subtitle, subtitle_font, w - 2 * pad, draw)
        sub_line_h = (
            subtitle_font.size + 8
            if hasattr(subtitle_font, "size") else 32)
        for i, line in enumerate(sub_lines):
            draw.text(
                (pad, sub_y + i * sub_line_h),
                line,
                fill=(148, 163, 184),
                font=subtitle_font)

    img.save(out_path, "PNG")
    return out_path


def _load_font(size: int, bold: bool = False) -> Any:
    """Try a list of common system fonts; fall back to PIL default
    when nothing matches. PIL's default font ignores size, so the
    output looks bad — but it never crashes, which is what we want
    for export."""
    candidates = (
        # macOS — modern + classic locations.
        ("/System/Library/Fonts/SFNS.ttf"
         if not bold else
         "/System/Library/Fonts/SFNSMono.ttf"),
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        # Linux.
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
         if bold else
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        # Windows.
        ("C:/Windows/Fonts/arialbd.ttf"
         if bold else
         "C:/Windows/Fonts/arial.ttf"),
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _wrap_text(text: str, font: Any, max_w: int, draw) -> List[str]:
    """Greedy word-wrap into lines that fit ``max_w`` pixels. No
    hyphenation — long URLs / single tokens may overflow but won't
    crash the layout."""
    if not text:
        return []
    words = text.split()
    if not words:
        return []
    lines: List[str] = []
    current: List[str] = []
    for word in words:
        trial = " ".join(current + [word])
        try:
            bbox = draw.textbbox((0, 0), trial, font=font)
            width = bbox[2] - bbox[0]
        except Exception:
            # textbbox missing on very old PIL; fall back to length.
            width = len(trial) * 10
        if width <= max_w or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def collect_chapter_scenes(
    studio: Any, chapter_id: str,
) -> List[Any]:
    """Return the scenes that belong to a given chapter, ordered for
    deck export.

    Ordering precedence:
      1. Topological order from the chapter's first scene if the
         chapter's scenes are connected by hops.
      2. Otherwise grid reading order (top-to-bottom, left-to-right).
    """
    if studio is None or not chapter_id:
        return []
    members = [
        s for s in studio.scenes
        if getattr(s, "chapter_id", None) == chapter_id
    ]
    if not members:
        return []
    # Try hops first — if any scene in the chapter has incoming or
    # outgoing hops, prefer that order. Use studio's BFS helper.
    try:
        if any(
            (h.from_scene_id in {s.id for s in members}
             or h.to_scene_id in {s.id for s in members})
            for h in (getattr(studio, "hops", []) or [])
        ):
            # Pick the start: first chapter scene with NO incoming
            # hop within this chapter (so we start at the head).
            chapter_ids = {s.id for s in members}
            incoming = {
                h.to_scene_id for h in studio.hops
                if h.from_scene_id in chapter_ids
            }
            heads = [s for s in members if s.id not in incoming]
            start = heads[0].id if heads else members[0].id
            ordered_ids = [
                s.id for s in
                studio.topological_order_starting_at(start)
                if s.id in chapter_ids
            ]
            # If BFS missed any (disconnected components), append in
            # grid order so nothing is silently dropped.
            seen = set(ordered_ids)
            fallback = sorted(
                (s for s in members if s.id not in seen),
                key=lambda s: (s.grid_row, s.grid_col))
            id_to_scene = {s.id: s for s in members}
            return [id_to_scene[i] for i in ordered_ids] + fallback
    except Exception:
        pass
    # Grid reading order — top to bottom, left to right.
    return sorted(
        members, key=lambda s: (s.grid_row, s.grid_col))


def build_deck_entries(
    scenes: List[Any],
    title_card_dir: Optional[Path] = None,
    chapter_title: str = "",
    default_image_seconds: float = 4.0,
) -> Tuple[List[Path], List[float], List[str]]:
    """Walk the scenes and return three parallel lists ready for
    ``stitcher.stitch_clips``: paths, per-clip durations, and a
    short summary line per entry (for the UI's "skipped" report).

    When ``title_card_dir`` is set, a title card PNG is generated
    for each scene and prepended to that scene's clip.

    Scenes whose favorite clip is missing, a placeholder, or zero
    bytes are skipped. The returned ``skipped`` list explains each
    skip for the UI.
    """
    paths: List[Path] = []
    durations: List[float] = []
    skipped: List[str] = []
    for idx, scene in enumerate(scenes, start=1):
        clip = scene.favorite_clip()
        label = scene.name or f"Scene {idx}"
        if clip is None or not clip.file_path:
            skipped.append(f"{label}: no favorite output")
            continue
        path = Path(clip.file_path)
        if not path.exists() or path.stat().st_size == 0:
            skipped.append(f"{label}: file missing or empty")
            continue
        if getattr(clip, "is_placeholder", False):
            skipped.append(f"{label}: placeholder only")
            continue
        # Optional title card.
        if title_card_dir is not None:
            title_card_dir.mkdir(parents=True, exist_ok=True)
            card_path = (
                title_card_dir
                / f"title_{idx:03d}_{scene.id}.png")
            overline = (
                f"{chapter_title} · Scene {idx}"
                if chapter_title else f"Scene {idx}")
            render_title_card(
                card_path,
                title=scene.name or f"Scene {idx}",
                subtitle=(scene.description or "")[:280],
                overline=overline)
            paths.append(card_path)
            durations.append(TITLE_CARD_DURATION_SECONDS)
        paths.append(path)
        # Honor each clip's stored duration. Image stills carry the
        # writer's chosen display time; video clips carry the
        # actual length (ffmpeg ignores -t on already-encoded
        # videos so passing it through is harmless).
        durations.append(
            float(clip.duration_seconds or default_image_seconds))
    return paths, durations, skipped
