"""Visual timeline widget for a SlideGroup.

The group editor's centerpiece — a horizontal track that maps
the group's overlay audio to a time axis and lets the writer
place slides as draggable blocks along it.

Layout::

    ┌─ Track ─────────────────────────────────────────────────┐
    │  ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒ audio bar ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒  │
    │      ┃ playhead                                          │
    │  ╔══════╗  ╔══════════╗  ╔═══════════════╗               │
    │  ║slide1║  ║  slide2  ║  ║    slide3     ║               │
    │  ╚══════╝  ╚══════════╝  ╚═══════════════╝               │
    │  0s        4.2s          9.8s             audio end      │
    └─────────────────────────────────────────────────────────┘

Each placed slide is a rectangle starting at its
``start_time_seconds_in_group`` and ending at the next placed
slide's start (or the audio end for the last one). Dragging a
block sets the start time. The trim handles on the audio bar
set ``overlay_trim_in`` / ``overlay_trim_out`` (added below as
group fields).

Drag-and-drop from the "available slides" tray works by
accepting MIME data carrying ``page_id``. Dropping at an x
position pins the slide to the corresponding time.

The widget is intentionally Qt-only — no waveform rendering. We
draw the audio as a flat bar; the real audio waveform is
overkill for the slide-timing use case and would slow open
times to a crawl on long takes.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from PyQt6.QtCore import (
    QMimeData, QPoint, QRect, QSize, Qt, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDrag, QFont, QFontMetrics, QPainter, QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from src.video_studio.models import SlideDeckProject, SlideGroup, SlidePage

# Layout constants. Picked once instead of computed from font
# metrics so the widget stays readable when the writer makes
# the dialog very wide. The audio bar got a bump (36 → 56) and
# the slide band got a bigger one (110 → 160) when writers
# called out the visualization being too small to use on a
# laptop. TRACK_HEIGHT is the *minimum*; the widget's vertical
# policy is ``MinimumExpanding`` so the dialog can give it
# more room when it has it.
TRACK_HEIGHT = 300
AUDIO_BAR_TOP = 28
AUDIO_BAR_HEIGHT = 56
RULER_HEIGHT = 14
SLIDE_BAND_TOP = AUDIO_BAR_TOP + AUDIO_BAR_HEIGHT + RULER_HEIGHT + 10
SLIDE_BAND_HEIGHT = 160
LEFT_PAD = 14
RIGHT_PAD = 14

PLACEHOLDER_PIXELS_PER_SECOND = 40  # used when no audio yet

# Width in pixels of the trim-handle hot zone at each end of
# an audio clip block. Wide enough to grab on a trackpad but
# narrow enough that small blocks still let the writer click
# the middle to drag-reposition.
CLIP_EDGE_HANDLE_PX = 6


_DRAG_MIME = "application/x-writingaid-slide-id"
_AUDIO_CLIP_DRAG_MIME = "application/x-writingaid-audio-clip-id"


class GroupTimelineWidget(QWidget):
    """The interactive track. Repaints on every layout change so
    a single ``update()`` after mutating the group is enough."""

    slideSelected = pyqtSignal(str)              # page_id
    slideDoubleClicked = pyqtSignal(str)         # page_id
    timelineChanged = pyqtSignal()               # any mutation
    trimChanged = pyqtSignal(float, float)       # in_secs, out_secs
    # Right-click anywhere on the audio bar emits this with a
    # GLOBAL QPoint — the host dialog uses it to position a
    # context menu over the click. Emitted only when audio is
    # loaded; right-clicking an empty bar is a no-op.
    audioContextRequested = pyqtSignal(object)
    # An audio clip block was selected (or cleared with "").
    audioClipSelected = pyqtSignal(str)          # clip_id ("" = none)
    # Right-click on a specific clip block — the host pops the
    # per-clip menu (trim, fade, gain, delete). Args are
    # (clip_id, global QPoint).
    audioClipContextRequested = pyqtSignal(str, object)
    # An audio clip block was dragged to a new start_time, OR
    # a clip was dropped onto the bar from the clip list.
    audioClipMoved = pyqtSignal(str, float)      # clip_id, new_start_seconds
    # Right-click on a slide BLOCK on the slide band — host
    # pops the per-slide menu (preview / remove from timeline /
    # remove from group). Args are (page_id, global QPoint).
    slideContextRequested = pyqtSignal(str, object)

    def __init__(
        self,
        deck: SlideDeckProject,
        group: SlideGroup,
        on_request_image: Optional[Callable[[str], Optional[QPixmap]]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._deck = deck
        self._group = group
        self._on_request_image = on_request_image
        self._selected_page_id: Optional[str] = None
        # Drag state.
        self._drag_page_id: Optional[str] = None
        self._drag_grab_dx_pixels: int = 0
        self._dragging_trim_handle: Optional[str] = None  # "in"/"out"/None
        # Selection-drag state. Left-clicking on the audio bar
        # (away from a trim handle) anchors here; mouse motion
        # past ``_SELECT_DRAG_THRESHOLD_PX`` flips into selection
        # mode and starts updating ``overlay_trim_in/out`` live.
        # A press without significant motion stays a click and
        # scrubs the playhead instead.
        self._select_anchor_seconds: Optional[float] = None
        self._select_anchor_x: int = 0
        self._in_selection_drag: bool = False
        # Audio-clip block state. ``_selected_audio_clip_id``
        # mirrors the highlight in the clip list. Dragging a
        # block sets ``_audio_clip_drag_*`` so paintEvent can
        # honor the in-flight position before the model
        # commits on release.
        self._selected_audio_clip_id: Optional[str] = None
        self._audio_clip_drag_id: Optional[str] = None
        self._audio_clip_drag_grab_dx: int = 0
        self._audio_clip_drag_started: bool = False
        # Per-clip trim handle drag — set on press inside the
        # CLIP_EDGE_HANDLE_PX zone at the left or right edge of
        # a block. ``_audio_clip_trim_side`` is "in" or "out".
        # We dragged the clip's own ``trim_in_seconds`` /
        # ``trim_out_seconds`` live during move so the visual
        # block width tracks the cursor; on release we recompose.
        self._audio_clip_trim_id: Optional[str] = None
        self._audio_clip_trim_side: Optional[str] = None
        self._audio_clip_trim_started: bool = False
        # Layout snapshots taken at drag-start so the
        # cascade-shift logic always references the original
        # positions (not the in-flight ones we're updating
        # every mouseMove). Keyed by clip / page id.
        self._audio_clip_drag_snapshot: dict[str, float] = {}
        self._slide_drag_snapshot: dict[str, float] = {}
        # Playhead time in seconds, set by the dialog as media plays.
        self._playhead_seconds: float = 0.0
        # Pixmap cache so we don't reload every slide image on
        # each paint. Cleared when the group changes.
        self._pixmap_cache: dict[str, QPixmap] = {}
        # Waveform peaks cache — invalidated when the audio path
        # changes (see ``refresh_waveform``). Loaded lazily on
        # the first paint so opening the dialog stays snappy.
        self._waveform_peaks = None
        self._waveform_audio_path = ""
        # Per-clip peak cache keyed by source ``audio_path``.
        # Two clips that share a source file (rare but legal)
        # share the cached peaks. Cleared by
        # ``refresh_waveform`` and when a clip's path changes
        # under it (e.g. re-record into a fresh WAV).
        self._clip_peak_cache: dict = {}
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setMinimumHeight(TRACK_HEIGHT)
        # Both axes expand — the dialog dedicates most of its
        # vertical space to the timeline now that the tray
        # tucked underneath as a thin strip and the transforms
        # / detail panels moved into tabs.
        self.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding,
            QSizePolicy.Policy.MinimumExpanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Belt-and-suspenders context menu routing. Qt's
        # ``contextMenuEvent`` virtual is supposed to fire on
        # right-click, but writers reported that the per-clip
        # / per-slide menu sometimes never appeared. Switching
        # to ``CustomContextMenu`` makes Qt emit a signal at the
        # right-click position regardless of focus / event-
        # filter chains. The handler runs the SAME hit-test
        # logic ``contextMenuEvent`` uses, so we have two paths
        # to the same dispatch and the user sees the menu in
        # both cases.
        self.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            self._on_custom_context_menu_requested)

    # ------------------------------------------------------------------
    # External API
    # ------------------------------------------------------------------
    def set_group(
            self, deck: SlideDeckProject, group: SlideGroup) -> None:
        self._deck = deck
        self._group = group
        self._pixmap_cache.clear()
        self._waveform_peaks = None
        self._waveform_audio_path = ""
        self._clip_peak_cache.clear()
        self._selected_page_id = None
        self.update()

    def refresh_waveform(self) -> None:
        """Drop the cached peaks so the next paint reloads them.
        Call after recording / importing / applying transforms —
        anything that mutates the underlying audio file."""
        self._waveform_peaks = None
        self._waveform_audio_path = ""
        self._clip_peak_cache.clear()
        self.update()

    def set_playhead(self, seconds: float) -> None:
        self._playhead_seconds = max(0.0, float(seconds))
        self.update()

    def selected_page_id(self) -> Optional[str]:
        return self._selected_page_id

    def clear_selection(self) -> None:
        self._selected_page_id = None
        self.update()

    def select_page(self, page_id: str) -> None:
        if any(p.id == page_id for p in self._placed_pages()):
            self._selected_page_id = page_id
            self.update()

    def remove_placed(self, page_id: str) -> None:
        """Pull a slide off the timeline (back to the tray)
        without removing it from the group."""
        page = self._find_page(page_id)
        if page is None:
            return
        page.start_time_seconds_in_group = None
        page.updated_at = datetime.now()
        if self._selected_page_id == page_id:
            self._selected_page_id = None
        self.timelineChanged.emit()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(640, TRACK_HEIGHT)

    # ------------------------------------------------------------------
    # Time / pixel mapping
    # ------------------------------------------------------------------
    def _audio_duration(self) -> float:
        return max(
            0.0,
            float(
                getattr(
                    self._group,
                    "overlay_audio_duration_seconds", 0.0) or 0.0))

    def _trim_in(self) -> float:
        return max(0.0, float(
            getattr(self._group, "overlay_trim_in_seconds", 0.0)
            or 0.0))

    def _trim_out(self) -> float:
        # 0.0 means "play to end". Translate to actual seconds
        # so the painter / drop logic doesn't need to special-case.
        out = float(
            getattr(
                self._group, "overlay_trim_out_seconds", 0.0)
            or 0.0)
        dur = self._audio_duration()
        if out <= 0 or out > dur:
            return dur
        return out

    def _visible_duration(self) -> float:
        """The full audio duration — the bar always renders the
        WHOLE file. The trim window is a *selection overlay* on
        top of the bar, not a viewport crop. Previously this
        returned ``trim_out − trim_in``, which made the
        pixel↔seconds mapping shrink to the trim window while
        the waveform stayed drawn at full-file scale — clicks
        landed at the wrong time, the user's "selection not
        tracking the mouse" report."""
        return self._audio_duration()

    def _track_rect(self) -> QRect:
        return QRect(
            LEFT_PAD, AUDIO_BAR_TOP,
            max(1, self.width() - LEFT_PAD - RIGHT_PAD),
            AUDIO_BAR_HEIGHT)

    def _slide_band_rect(self) -> QRect:
        return QRect(
            LEFT_PAD, SLIDE_BAND_TOP,
            max(1, self.width() - LEFT_PAD - RIGHT_PAD),
            SLIDE_BAND_HEIGHT)

    def _seconds_to_x(self, seconds: float) -> int:
        """Map an absolute time in the full audio file to a
        pixel x on this widget. The bar's pixel range matches
        the full file's 0..duration range — trim is a selection
        drawn over the top, not a viewport shift."""
        rect = self._track_rect()
        dur = self._audio_duration()
        if dur > 0:
            ratio = seconds / dur
        else:
            # No audio yet — fall back to a fixed pixel scale so
            # the writer can still arrange slides before audio
            # lands. Map seconds 1:1 against the placeholder.
            ratio = seconds / max(0.1, (
                rect.width() / PLACEHOLDER_PIXELS_PER_SECOND))
        ratio = max(0.0, min(1.0, ratio))
        return rect.left() + int(ratio * rect.width())

    def _x_to_seconds(self, x: int) -> float:
        """Inverse of ``_seconds_to_x`` — pixel back to absolute
        seconds in the full file."""
        rect = self._track_rect()
        if rect.width() <= 0:
            return 0.0
        ratio = (x - rect.left()) / rect.width()
        ratio = max(0.0, min(1.0, ratio))
        dur = self._audio_duration()
        if dur > 0:
            return ratio * dur
        return ratio * (
            rect.width() / PLACEHOLDER_PIXELS_PER_SECOND)

    # ------------------------------------------------------------------
    # Group queries
    # ------------------------------------------------------------------
    def _find_audio_clip(self, clip_id: str):
        for c in (
                getattr(self._group, "audio_clips", None)
                or []):
            if c.id == clip_id:
                return c
        return None

    def _find_page(self, page_id: str) -> Optional[SlidePage]:
        for p in self._deck.pages:
            if p.id == page_id:
                return p
        return None

    def _group_pages(self) -> List[SlidePage]:
        return [
            p for pid in self._group.page_ids
            for p in [self._find_page(pid)]
            if p is not None
        ]

    def _placed_pages(self) -> List[SlidePage]:
        out = [
            p for p in self._group_pages()
            if p.start_time_seconds_in_group is not None
        ]
        out.sort(
            key=lambda p: p.start_time_seconds_in_group or 0.0)
        return out

    def _placed_blocks(
            self) -> List[Tuple[SlidePage, float, float]]:
        """Return ``(page, start, end)`` triples in time order.
        End is the next slide's start, or the audio end for the
        last placed slide."""
        placed = self._placed_pages()
        if not placed:
            return []
        dur = self._audio_duration() or (
            (placed[-1].start_time_seconds_in_group or 0.0)
            + max(1.0, placed[-1].duration_seconds))
        blocks: List[Tuple[SlidePage, float, float]] = []
        for i, page in enumerate(placed):
            start = float(
                page.start_time_seconds_in_group or 0.0)
            if i + 1 < len(placed):
                end = float(
                    placed[i + 1].start_time_seconds_in_group
                    or start)
            else:
                end = dur
            if end < start:
                end = start
            blocks.append((page, start, end))
        return blocks

    def _pixmap_for(self, page: SlidePage) -> Optional[QPixmap]:
        if page.id in self._pixmap_cache:
            return self._pixmap_cache[page.id]
        pix: Optional[QPixmap] = None
        if self._on_request_image is not None:
            try:
                pix = self._on_request_image(page.id)
            except Exception as e:
                print(f"[timeline] image load failed: {e}")
                pix = None
        if pix is None and page.image_path:
            try:
                p = QPixmap(page.image_path)
                if not p.isNull():
                    pix = p
            except Exception:
                pix = None
        if pix is not None:
            self._pixmap_cache[page.id] = pix
        return pix

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Background.
        painter.fillRect(self.rect(), QColor("#0f172a"))
        # Header.
        painter.setPen(QColor("#94a3b8"))
        f = QFont(painter.font())
        f.setPointSize(max(9, f.pointSize() - 1))
        painter.setFont(f)
        header = self._header_text()
        painter.drawText(LEFT_PAD, 16, header)
        # Audio bar — black background so gaps between clips
        # read as silence and the colored clip blocks pop out
        # against it. The empty (no-audio) state stays slate so
        # the writer can still tell the bar is there.
        track = self._track_rect()
        clips = getattr(
            self._group, "audio_clips", None) or []
        has_audio = (
            self._audio_duration() > 0 or len(clips) > 0)
        audio_color = (
            QColor("#000000") if has_audio
            else QColor("#334155"))
        painter.fillRect(track, audio_color)
        # Trim shading only fires for the single-clip / legacy
        # case where the whole-overlay trim handles still
        # mean something. Multi-clip arrangements rely on per-
        # clip trim, so the writer doesn't need the kept-window
        # halo bleeding through.
        if (self._audio_duration() > 0
                and len(clips) <= 1
                and (self._trim_in() > 0
                     or self._trim_out()
                     < self._audio_duration())):
            in_x = self._seconds_to_x(self._trim_in())
            out_x = self._seconds_to_x(self._trim_out())
            kept = QRect(
                in_x, track.top(),
                max(0, out_x - in_x), track.height())
            painter.fillRect(kept, QColor("#3b82f6"))
        painter.setPen(QPen(QColor("#1e293b"), 1))
        painter.drawRect(track)
        # Waveform only for single-clip view — the per-clip
        # blocks own the visualization when there are
        # multiple. A composed-overlay waveform would
        # distract from the block-edge boundaries.
        if len(clips) <= 1:
            self._draw_waveform(painter, track)
        # Trim handles (if there's audio to trim).
        if self._audio_duration() > 0:
            in_x = self._seconds_to_x(self._trim_in())
            out_x = self._seconds_to_x(self._trim_out())
            handle_pen = QPen(QColor("#facc15"), 3)
            painter.setPen(handle_pen)
            painter.drawLine(
                in_x, track.top() - 4,
                in_x, track.bottom() + 4)
            painter.drawLine(
                out_x, track.top() - 4,
                out_x, track.bottom() + 4)
            painter.setPen(QColor("#facc15"))
            painter.drawText(
                in_x + 3, track.top() - 2,
                f"in {self._trim_in():.2f}s")
            painter.drawText(
                out_x + 3, track.bottom() + 12,
                f"out {self._trim_out():.2f}s")
        # Playhead — visible whenever it's within the file,
        # not just within the trim window. Writers use it as
        # the anchor for "Trim before / after playhead", which
        # would be confusing if the line disappeared the moment
        # they moved it outside an existing selection.
        if (self._audio_duration() > 0
                and 0 <= self._playhead_seconds
                <= self._audio_duration()):
            px = self._seconds_to_x(self._playhead_seconds)
            painter.setPen(QPen(QColor("#ef4444"), 2))
            painter.drawLine(
                px, track.top() - 6,
                px, SLIDE_BAND_TOP + SLIDE_BAND_HEIGHT + 4)
        # Ruler ticks every second (or every 5 when track is short).
        self._draw_ruler(painter)
        # Clip boundary markers — drawn AFTER the waveform so
        # they sit on top. Each entry in audio_clips contributes
        # a labeled vertical tick at the cumulative offset; the
        # ticks visually break the rendered overlay into the
        # writer's individual takes.
        self._draw_clip_boundaries(painter, track)
        # Slide band background.
        band = self._slide_band_rect()
        painter.fillRect(band, QColor("#1e293b"))
        painter.setPen(QPen(QColor("#334155"), 1))
        painter.drawRect(band)
        # Slide blocks.
        for page, start, end in self._placed_blocks():
            self._draw_slide_block(painter, page, start, end)
        # Drop hint line — show where a drag would land.
        # (Drawn in dragMoveEvent via update() — we cache the
        #  x position in _drag_grab_dx_pixels via _drag_hover_x.)
        if getattr(self, "_drag_hover_x", None) is not None:
            painter.setPen(QPen(QColor("#a78bfa"), 2,
                                Qt.PenStyle.DashLine))
            painter.drawLine(
                self._drag_hover_x, band.top() - 6,
                self._drag_hover_x, band.bottom() + 6)

    def _header_text(self) -> str:
        dur = self._audio_duration()
        placed = len(self._placed_pages())
        total = len(self._group.page_ids)
        if dur > 0:
            return (
                f"{placed} of {total} slides placed  ·  "
                f"audio {self._trim_in():.2f}–"
                f"{self._trim_out():.2f}s "
                f"of {dur:.2f}s")
        return (
            f"{placed} of {total} slides placed  ·  "
            "no overlay audio yet")

    def _draw_ruler(self, painter: QPainter) -> None:
        track = self._track_rect()
        y = track.bottom() + 2
        painter.setPen(QColor("#64748b"))
        f = QFont(painter.font())
        f.setPointSize(8)
        painter.setFont(f)
        # Ruler walks the WHOLE file (the bar now shows the
        # whole file, not just the trim window).
        dur = self._audio_duration()
        if dur <= 0:
            return
        step = 1.0
        if dur > 60:
            step = 10.0
        elif dur > 30:
            step = 5.0
        elif dur > 15:
            step = 2.0
        t = 0.0
        end = dur
        while t <= end + 1e-3:
            x = self._seconds_to_x(t)
            painter.drawLine(x, y, x, y + 4)
            painter.drawText(
                x + 2, y + RULER_HEIGHT - 1, f"{t:.0f}s")
            t += step

    def _draw_clip_boundaries(
            self, painter: QPainter, track: QRect) -> None:
        """Render each audio clip as a positioned, colored
        block on the audio bar — replaces the old "boundary
        tick" markers since clips are now real, draggable,
        right-clickable rectangles. Block width = clip's
        effective duration (trim_out − trim_in); block x =
        clip's ``start_time_seconds``."""
        clips = getattr(self._group, "audio_clips", None) or []
        if not clips:
            return
        dur = self._audio_duration()
        if dur <= 0:
            return
        from PyQt6.QtGui import (
            QFont as _QF, QFontMetrics as _QFM)
        f = _QF(painter.font())
        f.setPointSize(9)
        f.setBold(True)
        painter.setFont(f)
        fm = _QFM(painter.font())
        # Rotate through a small palette so adjacent clips read
        # as distinct without picking custom colors per-clip.
        palette = [
            QColor("#22d3ee"), QColor("#34d399"),
            QColor("#a78bfa"), QColor("#fb923c"),
            QColor("#f472b6"), QColor("#facc15"),
        ]
        for idx, clip in enumerate(clips):
            # Unplaced clips (``start_time_seconds is None``)
            # live in the clip list only — they're not on the
            # timeline, so we skip rendering them as blocks.
            if getattr(clip, "start_time_seconds", None) is None:
                continue
            start = float(
                getattr(clip, "start_time_seconds", 0.0) or 0.0)
            eff = self._clip_effective_duration(clip)
            if eff <= 0:
                continue
            x_left = self._seconds_to_x(start)
            x_right = self._seconds_to_x(start + eff)
            width = max(6, x_right - x_left)
            rect = QRect(
                x_left, track.top() + 2,
                width, track.height() - 4)
            base = palette[idx % len(palette)]
            selected = (
                clip.id == self._selected_audio_clip_id)
            # Block background — deeper alpha so the white
            # waveform pops. Selected clips get a brighter
            # fill so they stand out against the lineup.
            fill = QColor(base)
            fill.setAlpha(220 if selected else 170)
            painter.fillRect(rect, fill)
            # Waveform inside the block — slices the cached
            # source peaks down to the kept (trim) window and
            # scales across the block width. Block resize
            # (trim handle drag) reshapes the waveform on the
            # fly because the slice is recomputed each paint;
            # the underlying file is NOT touched.
            self._draw_clip_block_waveform(
                painter, clip, rect)
            border = QPen(
                QColor("#0f172a") if not selected
                else QColor("#fef3c7"),
                2 if selected else 1)
            painter.setPen(border)
            painter.drawRect(rect)
            # Draw trim-handle pads on the selected clip's
            # edges so the writer sees where to grab. Skipped
            # for tiny blocks (where edge hits are disabled).
            if (selected
                    and rect.width()
                    >= CLIP_EDGE_HANDLE_PX * 2):
                handle_color = QColor("#facc15")
                left_handle = QRect(
                    rect.left(), rect.top(),
                    CLIP_EDGE_HANDLE_PX, rect.height())
                right_handle = QRect(
                    rect.right() - CLIP_EDGE_HANDLE_PX,
                    rect.top(),
                    CLIP_EDGE_HANDLE_PX, rect.height())
                painter.fillRect(left_handle, handle_color)
                painter.fillRect(right_handle, handle_color)
            # Label sits in a small dark backdrop pill so it
            # stays readable against the waveform. Skipped on
            # tiny blocks (no room for text without crowding
            # out the waveform).
            label = (clip.label or f"Take {idx + 1}")
            meta = f"  ({eff:.2f}s)"
            label_text = f"{label}{meta}"
            txt = fm.elidedText(
                label_text,
                Qt.TextElideMode.ElideRight,
                max(20, rect.width() - 8))
            if rect.width() >= 40:
                txt_w = fm.horizontalAdvance(txt) + 8
                txt_h = fm.height() + 2
                pill = QRect(
                    rect.left() + 2,
                    rect.top() + 2,
                    min(txt_w, rect.width() - 4),
                    txt_h)
                bg = QColor(0, 0, 0, 170)
                painter.fillRect(pill, bg)
                painter.setPen(QColor("#fef3c7"))
                painter.drawText(
                    pill.left() + 4,
                    pill.top() + fm.ascent() + 1,
                    txt)

    def _peaks_for_clip(self, clip):
        """Lazy-load + cache the waveform peaks for ``clip``'s
        source file. Keyed by ``audio_path`` so two clips
        pointing at the same file share peaks. Returns
        ``None`` when the source is missing or the deps
        (soundfile + numpy) aren't installed — paint falls
        back to a flat block in that case."""
        from pathlib import Path as _P
        path = getattr(clip, "audio_path", "") or ""
        if not path:
            return None
        if path in self._clip_peak_cache:
            return self._clip_peak_cache[path]
        from src.video_studio.audio_waveform import load_peaks
        # 400 buckets is plenty even for a wide block — at
        # 800 px wide that's 2 px per peak, indistinguishable
        # from a higher resolution without scope sniffing.
        peaks = load_peaks(_P(path), num_buckets=400)
        if peaks is not None:
            self._clip_peak_cache[path] = peaks
        return peaks

    def _draw_clip_block_waveform(
            self, painter: QPainter, clip,
            rect: QRect) -> None:
        """Paint the clip's trimmed waveform across ``rect``.

        Slice math: the cached peaks span the WHOLE source
        file in ``num_buckets`` equal-width buckets. We take
        the bucket range that corresponds to ``[trim_in,
        trim_out]`` and stretch / aggregate it across the
        pixels of ``rect``. The source file is never written
        to — this is purely a render-time transformation.
        """
        if rect.width() < 4 or rect.height() < 6:
            return
        peaks = self._peaks_for_clip(clip)
        if peaks is None or peaks.num_buckets == 0:
            return
        source_dur = float(
            getattr(clip, "duration_seconds", 0.0) or 0.0)
        if source_dur <= 0:
            return
        tin = max(0.0, float(
            getattr(clip, "trim_in_seconds", 0.0) or 0.0))
        tout = float(
            getattr(clip, "trim_out_seconds", 0.0) or 0.0)
        if tout <= 0 or tout > source_dur:
            tout = source_dur
        if tout <= tin:
            return
        n = peaks.num_buckets
        start_bucket = max(0, int(
            (tin / source_dur) * n))
        end_bucket = min(n, max(
            start_bucket + 1,
            int((tout / source_dur) * n)))
        slice_count = end_bucket - start_bucket
        if slice_count <= 0:
            return
        width = rect.width()
        # Leave a couple of pixels of padding at top/bottom
        # so the waveform doesn't kiss the block border, and
        # an extra ~12 px on top reserved for the label pill.
        top_padding = 16
        bottom_padding = 3
        if rect.height() <= top_padding + bottom_padding:
            top_padding = 2
            bottom_padding = 2
        avail_h = max(2, rect.height()
                      - top_padding - bottom_padding)
        mid_y = rect.top() + top_padding + avail_h // 2
        half_h = max(1, avail_h // 2)
        # Waveform color — soft white at high alpha; the
        # block's color shows around the edges of the trace.
        pen = QPen(QColor(255, 255, 255, 220))
        pen.setWidth(1)
        painter.setPen(pen)
        # For each pixel column in the block, find the bucket
        # range it maps to in the source slice, take the
        # extreme min/max, draw one vertical line.
        mins = peaks.mins
        maxs = peaks.maxs
        for px in range(width):
            frac_start = px / float(width)
            frac_end = (px + 1) / float(width)
            bi_start_f = start_bucket + frac_start * slice_count
            bi_end_f = start_bucket + frac_end * slice_count
            bi_start = max(start_bucket, int(bi_start_f))
            bi_end = min(end_bucket,
                         max(bi_start + 1, int(bi_end_f) + 1))
            # Aggregate min / max across this pixel's bucket
            # range. ``min()`` / ``max()`` over a Python list
            # is fast enough for the 400-bucket source — no
            # need to numpy this.
            seg_mins = mins[bi_start:bi_end]
            seg_maxs = maxs[bi_start:bi_end]
            if not seg_mins:
                continue
            mn = min(seg_mins)
            mx = max(seg_maxs)
            top_y = mid_y - int(mx * half_h)
            bot_y = mid_y - int(mn * half_h)
            if top_y == bot_y:
                bot_y = top_y + 1
            painter.drawLine(
                rect.left() + px, top_y,
                rect.left() + px, bot_y)

    def hit_audio_clip_handle(
            self, pos: QPoint) -> Tuple[
                Optional[str], Optional[str]]:
        """Hit-test the trim handles at the edges of audio
        clip blocks. Returns ``(clip_id, side)`` where
        ``side`` is ``"in"`` (left edge) or ``"out"`` (right
        edge), or ``(None, None)`` when ``pos`` isn't on any
        handle. Use BEFORE ``hit_audio_clip`` so an edge
        click triggers a trim drag instead of a body drag."""
        track = self._track_rect()
        if not track.contains(pos):
            return None, None
        clips = getattr(
            self._group, "audio_clips", None) or []
        for clip in clips:
            if getattr(clip, "start_time_seconds", None) is None:
                continue
            start = float(
                getattr(clip, "start_time_seconds", 0.0) or 0.0)
            eff = self._clip_effective_duration(clip)
            if eff <= 0:
                continue
            x_left = self._seconds_to_x(start)
            x_right = self._seconds_to_x(start + eff)
            # Body must be wide enough to expose both handles
            # AND still have a draggable middle. Below 3×HANDLE
            # we only expose one handle (the closer one) so the
            # block stays interactable.
            if x_right - x_left < CLIP_EDGE_HANDLE_PX * 2:
                # Tiny block — let the body handle the click.
                continue
            if abs(pos.x() - x_left) <= CLIP_EDGE_HANDLE_PX:
                return clip.id, "in"
            if abs(pos.x() - x_right) <= CLIP_EDGE_HANDLE_PX:
                return clip.id, "out"
        return None, None

    def audio_clip_at_seconds(
            self, seconds: float) -> Optional[str]:
        """Return the id of the audio clip whose visible window
        contains ``seconds`` (i.e. its block on the timeline
        covers that time), or ``None`` when ``seconds`` lands in
        a gap. The host uses this to scope playhead-relative
        trims to one clip — "trim before red line" should chop
        the clip the red line is sitting on, not the rendered
        overlay."""
        clips = (
            getattr(self._group, "audio_clips", None) or [])
        for c in clips:
            if getattr(c, "start_time_seconds", None) is None:
                continue
            start = float(
                getattr(c, "start_time_seconds", 0.0) or 0.0)
            eff = self._clip_effective_duration(c)
            if start <= seconds <= start + eff:
                return c.id
        return None

    def hit_audio_clip(self, pos: QPoint) -> Optional[str]:
        """Public hit-test: returns the id of the audio clip
        block under ``pos``, or ``None`` when the pos is in
        empty space (or on the track outside any block).
        Used by the dialog to translate right-clicks into clip
        operations."""
        track = self._track_rect()
        if not track.contains(pos):
            return None
        clips = getattr(
            self._group, "audio_clips", None) or []
        for clip in clips:
            if getattr(clip, "start_time_seconds", None) is None:
                continue
            start = float(
                getattr(clip, "start_time_seconds", 0.0) or 0.0)
            eff = self._clip_effective_duration(clip)
            if eff <= 0:
                continue
            x_left = self._seconds_to_x(start)
            x_right = self._seconds_to_x(start + eff)
            if x_left <= pos.x() <= x_right:
                return clip.id
        return None

    def selected_audio_clip_id(self) -> Optional[str]:
        return self._selected_audio_clip_id

    def select_audio_clip(
            self, clip_id: Optional[str]) -> None:
        self._selected_audio_clip_id = clip_id
        self.update()

    def _snapshot_audio_clip_layout(self) -> None:
        """Capture every clip's current start time. Called at
        drag-start (block move OR trim). The shift logic in
        ``_enforce_audio_no_overlap`` reads from this snapshot
        so it can compute delta-from-original instead of
        delta-from-last-frame, which would compound errors."""
        # Snapshot only the PLACED clips — unplaced ones live
        # in the clip list and shouldn't participate in the
        # drag-cascade math.
        self._audio_clip_drag_snapshot = {
            c.id: float(
                getattr(c, "start_time_seconds", 0.0) or 0.0)
            for c in (
                getattr(self._group, "audio_clips", None)
                or [])
            if getattr(c, "start_time_seconds", None) is not None
        }

    def _enforce_audio_no_overlap(
            self,
            moved_clip_id: str,
            *,
            cascade_right: bool = True) -> None:
        """Layout policy for audio clip blocks:
          * Blocks cannot overlap. The moved clip's start
            gets clamped to its predecessor's end (or 0 for
            the very first clip in snapshot-order).
          * When the moved clip ended up at a LATER start
            than its snapshot, every clip that was AFTER it
            in the snapshot shifts right by the same delta
            so relative gaps survive — the user's "drag right
            to add space" gesture.
          * When the moved clip ended up at an EARLIER (or
            equal) start, subsequent clips reset to their
            snapshot positions — so a drag-right-then-back
            doesn't strand later clips out at the pushed
            position.
        ``cascade_right`` exists for the drop-from-list path,
        which sets a brand-new start without a snapshot delta;
        in that mode we only enforce non-overlap on the moved
        clip itself.
        """
        clips = (
            getattr(self._group, "audio_clips", None) or [])
        moved = next(
            (c for c in clips if c.id == moved_clip_id),
            None)
        if moved is None:
            return
        snapshot = self._audio_clip_drag_snapshot
        # Sort clips by their snapshot start so predecessor
        # math is stable even if the moved clip has crossed
        # past others. Clips missing from the snapshot
        # (added after drag-start, shouldn't happen) sort to
        # the end via a large fallback.
        def _key(c):
            return snapshot.get(c.id, 1e9)
        # Walk only PLACED clips; unplaced ones aren't on
        # the timeline so they don't participate in overlap
        # arithmetic.
        placed_clips = [
            c for c in clips
            if getattr(c, "start_time_seconds", None) is not None
        ]
        if moved not in placed_clips:
            return
        ordered = sorted(placed_clips, key=_key)
        idx = ordered.index(moved)
        # Predecessor end in snapshot-order — using the LIVE
        # start + eff_duration so the predecessor's own in-
        # flight position (from a cascade earlier this drag)
        # is respected.
        if idx == 0:
            min_start = 0.0
        else:
            prev = ordered[idx - 1]
            min_start = (
                float(
                    getattr(prev, "start_time_seconds", 0.0)
                    or 0.0)
                + self._clip_effective_duration(prev))
        proposed = float(
            getattr(moved, "start_time_seconds", 0.0) or 0.0)
        new_start = max(min_start, proposed)
        moved.start_time_seconds = round(new_start, 3)
        if not cascade_right:
            return
        snap_start = snapshot.get(moved.id, new_start)
        delta = new_start - snap_start
        # Walk subsequent clips. If delta > 0, shift each by
        # +delta from its snapshot. Else, reset to snapshot
        # so we don't strand them out.
        for i in range(idx + 1, len(ordered)):
            other = ordered[i]
            snap = snapshot.get(other.id)
            if snap is None:
                continue
            if delta > 0:
                other.start_time_seconds = round(
                    snap + delta, 3)
            else:
                other.start_time_seconds = round(snap, 3)
        # Final pass — even if delta <= 0, a clip that was
        # pre-existing at e.g. start=1.5 with eff=1.0 and is
        # now adjacent to a clip at start=1.2 needs nudging.
        # Walk left-to-right and clamp each subsequent clip's
        # start to the running max(end).
        running_end = (
            float(moved.start_time_seconds)
            + self._clip_effective_duration(moved))
        for i in range(idx + 1, len(ordered)):
            other = ordered[i]
            os = float(
                getattr(other, "start_time_seconds", 0.0)
                or 0.0)
            if os < running_end:
                other.start_time_seconds = round(
                    running_end, 3)
            running_end = (
                float(other.start_time_seconds)
                + self._clip_effective_duration(other))

    def _snapshot_slide_layout(self) -> None:
        """Same idea as ``_snapshot_audio_clip_layout`` but
        for slide blocks on the slide drop band."""
        self._slide_drag_snapshot = {
            p.id: float(
                getattr(
                    p, "start_time_seconds_in_group", 0.0)
                or 0.0)
            for p in self._placed_pages()
        }

    def _enforce_slide_no_overlap(
            self, moved_page_id: str) -> None:
        """Slide-band twin of ``_enforce_audio_no_overlap``.
        Slide blocks use ``duration_seconds`` as their visible
        width and ``start_time_seconds_in_group`` as their
        position; otherwise the cascade math is identical."""
        placed = self._placed_pages()
        moved = next(
            (p for p in placed if p.id == moved_page_id),
            None)
        if moved is None:
            return
        snapshot = self._slide_drag_snapshot
        def _key(p):
            return snapshot.get(p.id, 1e9)
        ordered = sorted(placed, key=_key)
        idx = ordered.index(moved)
        if idx == 0:
            min_start = 0.0
        else:
            prev = ordered[idx - 1]
            min_start = (
                float(
                    getattr(
                        prev,
                        "start_time_seconds_in_group", 0.0)
                    or 0.0)
                + max(0.25, float(
                    getattr(prev, "duration_seconds", 0.0)
                    or 0.0)))
        proposed = float(
            getattr(
                moved, "start_time_seconds_in_group", 0.0)
            or 0.0)
        new_start = max(min_start, proposed)
        moved.start_time_seconds_in_group = round(new_start, 3)
        snap_start = snapshot.get(moved.id, new_start)
        delta = new_start - snap_start
        for i in range(idx + 1, len(ordered)):
            other = ordered[i]
            snap = snapshot.get(other.id)
            if snap is None:
                continue
            if delta > 0:
                other.start_time_seconds_in_group = round(
                    snap + delta, 3)
            else:
                other.start_time_seconds_in_group = round(
                    snap, 3)
        # Final non-overlap pass — slides whose existing snap
        # already left room don't get touched, but slides that
        # would overlap (because the moved slide grew into
        # their space) get pushed.
        running_end = (
            float(moved.start_time_seconds_in_group)
            + max(0.25, float(
                getattr(moved, "duration_seconds", 0.0)
                or 0.0)))
        for i in range(idx + 1, len(ordered)):
            other = ordered[i]
            os = float(
                getattr(
                    other, "start_time_seconds_in_group", 0.0)
                or 0.0)
            if os < running_end:
                other.start_time_seconds_in_group = round(
                    running_end, 3)
            running_end = (
                float(other.start_time_seconds_in_group)
                + max(0.25, float(
                    getattr(other, "duration_seconds", 0.0)
                    or 0.0)))

    def _max_audio_clip_right_edge(
            self, clip_id: str) -> float:
        """The largest source-time the trim handle on ``clip_id``'s
        right edge can claim WITHOUT overlapping the next clip.
        Returns the source duration as a free upper bound when
        there's no next clip."""
        clips = (
            getattr(self._group, "audio_clips", None) or [])
        moved = next(
            (c for c in clips if c.id == clip_id), None)
        if moved is None:
            return 0.0
        full = float(
            getattr(moved, "duration_seconds", 0.0) or 0.0)
        ordered = sorted(
            clips,
            key=lambda c: float(
                getattr(c, "start_time_seconds", 0.0) or 0.0))
        idx = ordered.index(moved)
        if idx + 1 >= len(ordered):
            return full
        next_clip = ordered[idx + 1]
        next_start = float(
            getattr(next_clip, "start_time_seconds", 0.0)
            or 0.0)
        my_start = float(
            getattr(moved, "start_time_seconds", 0.0) or 0.0)
        my_in = float(
            getattr(moved, "trim_in_seconds", 0.0) or 0.0)
        # Source-time-of-right-edge = trim_in + (block_eff)
        # = trim_in + (next_start - my_start)
        max_eff = max(0.01, next_start - my_start)
        return min(full, my_in + max_eff)

    @staticmethod
    @staticmethod
    def _clip_effective_duration(clip) -> float:
        """Trim-window length for a clip: trim_out − trim_in,
        falling back to its full ``duration_seconds`` when
        trim_out is the sentinel 0."""
        full = float(
            getattr(clip, "duration_seconds", 0.0) or 0.0)
        tin = max(0.0, float(
            getattr(clip, "trim_in_seconds", 0.0) or 0.0))
        tout = float(
            getattr(clip, "trim_out_seconds", 0.0) or 0.0)
        if tout <= 0 or tout > full:
            tout = full
        return max(0.0, tout - tin)

    def _draw_waveform(
            self, painter: QPainter, track: QRect) -> None:
        """Render peak waveform over the audio bar.

        Loads peaks lazily on first paint after the audio path
        changes — the writer sees a blank bar for a single
        repaint, then the wave snaps in. That's preferable to
        blocking ``paintEvent`` on the disk read.
        """
        path_str = getattr(
            self._group, "overlay_audio_path", "") or ""
        if not path_str:
            return
        # Lazy load + cache invalidation.
        if (self._waveform_peaks is None
                or self._waveform_audio_path != path_str):
            from src.video_studio.audio_waveform import (
                load_peaks)
            # Bucket count tracks the visible pixel width so the
            # wave stays detailed when the writer enlarges the
            # window. Cap at 2000 to keep the soundfile read
            # cheap on long takes.
            num_buckets = min(
                2000, max(120, track.width()))
            self._waveform_peaks = load_peaks(
                Path(path_str), num_buckets=num_buckets)
            self._waveform_audio_path = path_str
        peaks = self._waveform_peaks
        if peaks is None or peaks.num_buckets == 0:
            return
        # Peaks span the WHOLE file. Trim handles operate in the
        # same time axis, so the trim shading is already
        # painted under us — we just draw the entire wave on
        # top, and the dim-out outside the trim window does the
        # visual disambiguation.
        mid_y = track.top() + track.height() // 2
        half_h = (track.height() // 2) - 2
        # One vertical line per bucket, scaled to the track
        # width. When buckets > pixels we sub-sample; when
        # buckets < pixels we just stretch.
        pen = QPen(QColor("#e0f2fe"), 1)
        painter.setPen(pen)
        bucket_count = peaks.num_buckets
        # Map: bucket idx → x. Skip buckets that collide on the
        # same pixel.
        last_x = -1
        for i in range(bucket_count):
            x_frac = i / float(bucket_count - 1 or 1)
            x = (track.left()
                 + int(x_frac * (track.width() - 1)))
            if x == last_x:
                continue
            last_x = x
            mn = peaks.mins[i]
            mx = peaks.maxs[i]
            top_y = mid_y - int(mx * half_h)
            bot_y = mid_y - int(mn * half_h)
            if top_y == bot_y:
                bot_y = top_y + 1
            painter.drawLine(x, top_y, x, bot_y)

    def _draw_slide_block(
        self,
        painter: QPainter,
        page: SlidePage,
        start: float,
        end: float,
    ) -> None:
        x_left = self._seconds_to_x(start)
        x_right = self._seconds_to_x(end)
        width = max(28, x_right - x_left - 2)
        band = self._slide_band_rect()
        rect = QRect(
            x_left + 1, band.top() + 6,
            width, band.height() - 12)
        selected = (page.id == self._selected_page_id)
        bg = QColor("#fef3c7") if selected else QColor("#e0e7ff")
        border = QColor("#d97706") if selected else QColor("#6366f1")
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(border, 2))
        painter.drawRoundedRect(rect, 6, 6)
        # Optional thumbnail at the left side of the block.
        pix = self._pixmap_for(page)
        if pix is not None and rect.width() > 70:
            thumb_h = rect.height() - 24
            scaled = pix.scaledToHeight(
                thumb_h,
                Qt.TransformationMode.SmoothTransformation)
            thumb_w = min(scaled.width(), rect.width() - 40)
            painter.drawPixmap(
                rect.left() + 6, rect.top() + 6,
                scaled.copy(0, 0, thumb_w, thumb_h))
        # Label + duration.
        painter.setPen(QColor("#1e1b4b"))
        label_x = rect.left() + 6
        if pix is not None and rect.width() > 70:
            label_x = rect.left() + 6 + min(
                pix.scaledToHeight(rect.height() - 24).width(),
                rect.width() - 40) + 6
        label = page.label or "Slide"
        fm = QFontMetrics(painter.font())
        elided = fm.elidedText(
            label, Qt.TextElideMode.ElideRight,
            max(20, rect.right() - label_x - 4))
        painter.drawText(label_x, rect.top() + 18, elided)
        duration = end - start
        meta = f"{duration:.2f}s"
        if (page.transition_in or "cut") != "cut":
            meta += f"  · {page.transition_in}"
            if page.transition_seconds:
                meta += f" {page.transition_seconds:.1f}s"
        painter.setPen(QColor("#475569"))
        painter.drawText(label_x, rect.bottom() - 6, meta)

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------
    _SELECT_DRAG_THRESHOLD_PX = 4

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        # Edge-handle hit-test runs before the body hit-test so
        # an edge click triggers an in-place trim instead of a
        # reposition drag. The selected block highlights too so
        # the writer sees which clip they're trimming.
        edge_id, edge_side = self.hit_audio_clip_handle(pos)
        if edge_id is not None:
            self._audio_clip_trim_id = edge_id
            self._audio_clip_trim_side = edge_side
            self._audio_clip_trim_started = False
            self._selected_audio_clip_id = edge_id
            self.audioClipSelected.emit(edge_id)
            # Snapshot layout so a right-edge extend that
            # pushes against the next clip can cascade-shift
            # without compounding errors frame to frame.
            self._snapshot_audio_clip_layout()
            self.update()
            return
        # Audio-clip block hit-test runs after edge-handles so
        # blocks aren't eaten by the trim-handle or selection-
        # drag paths.
        clip_id = self.hit_audio_clip(pos)
        if clip_id is not None:
            self._selected_audio_clip_id = clip_id
            self.audioClipSelected.emit(clip_id)
            clip = self._find_audio_clip(clip_id)
            if clip is not None:
                self._audio_clip_drag_id = clip_id
                x_left = self._seconds_to_x(
                    float(
                        getattr(
                            clip, "start_time_seconds", 0.0)
                        or 0.0))
                self._audio_clip_drag_grab_dx = (
                    pos.x() - x_left)
                self._audio_clip_drag_started = False
                self._snapshot_audio_clip_layout()
            self.update()
            return
        # Trim handle hit-test on the audio bar.
        if self._audio_duration() > 0:
            track = self._track_rect()
            if (track.top() - 6 <= pos.y()
                    <= track.bottom() + 6):
                in_x = self._seconds_to_x(self._trim_in())
                out_x = self._seconds_to_x(self._trim_out())
                if abs(pos.x() - in_x) <= 6:
                    self._dragging_trim_handle = "in"
                    return
                if abs(pos.x() - out_x) <= 6:
                    self._dragging_trim_handle = "out"
                    return
        # Slide block hit-test.
        page_id = self._hit_test_block(pos)
        if page_id is not None:
            self._selected_page_id = page_id
            self.slideSelected.emit(page_id)
            page = self._find_page(page_id)
            if page is not None:
                self._drag_page_id = page_id
                x_left = self._seconds_to_x(
                    page.start_time_seconds_in_group or 0.0)
                self._drag_grab_dx_pixels = pos.x() - x_left
                # Snapshot slide layout so the same cascade
                # logic the audio path uses works for slides.
                self._snapshot_slide_layout()
            self.update()
            return
        # Press on empty audio bar — anchor a potential
        # selection drag. We don't commit to selection mode
        # yet; that flips on once the cursor moves past
        # ``_SELECT_DRAG_THRESHOLD_PX``. A press-and-release
        # without motion stays a click and just scrubs.
        track = self._track_rect()
        if track.contains(pos) and self._audio_duration() > 0:
            self._select_anchor_seconds = self._x_to_seconds(
                pos.x())
            self._select_anchor_x = pos.x()
            self._in_selection_drag = False
            return
        # Click on empty slide band — clear selection.
        if self._slide_band_rect().contains(pos):
            self._selected_page_id = None
            self.slideSelected.emit("")
            self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        # Free-cursor hover (no button held) updates the cursor
        # shape so the writer sees what each region affords:
        #   * Clip edge handle → SplitHCursor (resize / trim)
        #   * Clip body       → OpenHandCursor (grab to move)
        #   * Anywhere else   → default
        # Active drag swaps OpenHand for ClosedHand so the
        # writer's "I'm holding it" feedback matches the OS-
        # standard finder / DAW pattern.
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            edge_id, _side = self.hit_audio_clip_handle(pos)
            if edge_id is not None:
                self.setCursor(Qt.CursorShape.SplitHCursor)
            elif self.hit_audio_clip(pos) is not None:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.unsetCursor()
        elif self._audio_clip_drag_id is not None:
            # In an active body drag — show a closed hand.
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        if self._dragging_trim_handle is not None:
            secs = self._x_to_seconds(pos.x())
            dur = self._audio_duration()
            if self._dragging_trim_handle == "in":
                secs = max(0.0, min(secs, self._trim_out() - 0.05))
                self._group.overlay_trim_in_seconds = round(
                    secs, 3)
            else:
                secs = max(
                    self._trim_in() + 0.05, min(secs, dur))
                self._group.overlay_trim_out_seconds = round(
                    secs, 3)
            self.trimChanged.emit(
                self._trim_in(), self._trim_out())
            self.timelineChanged.emit()
            self.update()
            return
        # Selection drag: once the cursor's moved far enough
        # past the anchor, flip into selection mode and update
        # trim_in / trim_out live (sorted, so the writer can
        # drag in either direction).
        if (self._select_anchor_seconds is not None
                and (event.buttons() & Qt.MouseButton.LeftButton)):
            if (not self._in_selection_drag
                    and abs(pos.x() - self._select_anchor_x)
                    >= self._SELECT_DRAG_THRESHOLD_PX):
                self._in_selection_drag = True
            if self._in_selection_drag:
                dur = self._audio_duration()
                here = max(
                    0.0,
                    min(dur, self._x_to_seconds(pos.x())))
                anchor = self._select_anchor_seconds
                lo, hi = (here, anchor) if here < anchor else (
                    anchor, here)
                # Guard against zero-width selection — keep at
                # least one frame so the trim window is sane.
                if hi - lo < 0.01:
                    hi = min(dur, lo + 0.01)
                self._group.overlay_trim_in_seconds = round(
                    lo, 3)
                self._group.overlay_trim_out_seconds = round(
                    hi, 3)
                self.trimChanged.emit(
                    self._trim_in(), self._trim_out())
                self.timelineChanged.emit()
                self.update()
                return
        if self._drag_page_id is not None:
            # Initiate a Qt drag once the writer's moved far enough
            # — short clicks shouldn't trigger a drag.
            if (event.buttons() & Qt.MouseButton.LeftButton):
                # Cheap distance check.
                self._start_internal_reorder_drag(
                    pos.x() - self._drag_grab_dx_pixels)
                return
        # Trim-handle drag — adjust the clip's trim_in or
        # trim_out live so the block visually shrinks /
        # extends from the dragged edge. Clip start_time stays
        # anchored; only the trim window changes. Both ends
        # clamp to stay sane (in < out, both inside source).
        if (self._audio_clip_trim_id is not None
                and (event.buttons() & Qt.MouseButton.LeftButton)):
            clip = self._find_audio_clip(
                self._audio_clip_trim_id)
            if clip is None:
                return
            full = float(
                getattr(clip, "duration_seconds", 0.0) or 0.0)
            if full <= 0:
                return
            start = float(
                getattr(clip, "start_time_seconds", 0.0)
                or 0.0)
            secs_at_cursor = max(
                0.0, self._x_to_seconds(pos.x()))
            tin = max(0.0, float(
                getattr(clip, "trim_in_seconds", 0.0) or 0.0))
            tout = float(
                getattr(clip, "trim_out_seconds", 0.0) or 0.0)
            if tout <= 0 or tout > full:
                tout = full
            # The block's left edge in seconds is
            # ``start_time``; the right edge is
            # ``start_time + (tout - tin)``. The handle is in
            # GROUP coordinates; map to SOURCE coordinates by
            # the same delta.
            if self._audio_clip_trim_side == "in":
                # Cursor in group time corresponds to source
                # time ``tin + (cursor - start)``.
                new_tin = max(
                    0.0,
                    min(tout - 0.01,
                        tin + (secs_at_cursor - start)))
                clip.trim_in_seconds = round(new_tin, 3)
            else:
                # The right edge can't expand past the next
                # clip's start — clips don't overlap on the
                # timeline. ``_max_audio_clip_right_edge``
                # returns the largest legal trim_out for this
                # clip given its current start_time_seconds.
                max_tout = self._max_audio_clip_right_edge(
                    clip.id)
                new_tout = max(
                    tin + 0.01,
                    min(max_tout,
                        tin + (secs_at_cursor - start)))
                # Collapse back to sentinel 0 when at the
                # source's natural end so future re-recordings
                # of the same source don't hit a stale cap.
                clip.trim_out_seconds = (
                    0.0
                    if abs(new_tout - full) < 0.005
                    else round(new_tout, 3))
            self._audio_clip_trim_started = True
            self.update()
            return
        if self._audio_clip_drag_id is not None and (
                event.buttons() & Qt.MouseButton.LeftButton):
            clip = self._find_audio_clip(
                self._audio_clip_drag_id)
            if clip is None:
                return
            new_x = pos.x() - self._audio_clip_drag_grab_dx
            new_secs = max(
                0.0, self._x_to_seconds(new_x))
            # Skip the first sub-pixel jiggle so a click that
            # never moves the mouse doesn't bump the clip.
            if (not self._audio_clip_drag_started
                    and abs(pos.x() - (
                        self._seconds_to_x(
                            float(getattr(
                                clip, "start_time_seconds",
                                0.0) or 0.0))
                        + self._audio_clip_drag_grab_dx))
                    < 3):
                return
            self._audio_clip_drag_started = True
            clip.start_time_seconds = round(new_secs, 3)
            # Enforce no-overlap + cascade-shift subsequent
            # clips when the writer drags right.
            self._enforce_audio_no_overlap(clip.id)
            self.update()
            return

    def _start_internal_reorder_drag(self, new_x: int) -> None:
        if self._drag_page_id is None:
            return
        page = self._find_page(self._drag_page_id)
        if page is None:
            return
        secs = self._x_to_seconds(new_x)
        secs = max(self._trim_in(), min(secs, self._trim_out()))
        page.start_time_seconds_in_group = round(secs, 3)
        # Mirror the audio-clip layout: clamp to non-overlap +
        # cascade-shift subsequent slides for right-drags.
        self._enforce_slide_no_overlap(page.id)
        page.updated_at = datetime.now()
        self.timelineChanged.emit()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        # If the press never crossed the drag threshold, treat
        # it as a click. Two effects:
        #   1. Move the playhead to the click time (writers use
        #      the red line as the anchor for trim-before /
        #      trim-after).
        #   2. CLEAR any existing trim selection — the user
        #      asked for "a new click in the audio to unselect"
        #      so we don't strand an old selection across
        #      unrelated clicks.
        # A real selection drag stays committed to the trim
        # window we already updated during move.
        if (self._select_anchor_seconds is not None
                and not self._in_selection_drag):
            pos = event.position().toPoint()
            self._playhead_seconds = self._x_to_seconds(pos.x())
            had_selection = (
                float(getattr(
                    self._group,
                    "overlay_trim_in_seconds", 0.0) or 0.0)
                > 0
                or float(getattr(
                    self._group,
                    "overlay_trim_out_seconds", 0.0) or 0.0)
                > 0)
            if had_selection:
                self._group.overlay_trim_in_seconds = 0.0
                self._group.overlay_trim_out_seconds = 0.0
                self.timelineChanged.emit()
            self.trimChanged.emit(
                self._trim_in(), self._trim_out())
            self.update()
        # If an audio clip was being dragged AND actually moved,
        # tell the host so it can recompose. A click without
        # motion just keeps the selection.
        if (self._audio_clip_drag_id is not None
                and self._audio_clip_drag_started):
            clip = self._find_audio_clip(
                self._audio_clip_drag_id)
            if clip is not None:
                self.audioClipMoved.emit(
                    self._audio_clip_drag_id,
                    float(
                        getattr(
                            clip,
                            "start_time_seconds", 0.0)
                        or 0.0))
        # Same idea for trim-handle drags — emit so the host
        # recomposes the rendered overlay with the new trim.
        # We piggyback on ``audioClipMoved`` because the host
        # treats both events the same way: refresh + recompose.
        if (self._audio_clip_trim_id is not None
                and self._audio_clip_trim_started):
            clip = self._find_audio_clip(
                self._audio_clip_trim_id)
            if clip is not None:
                self.audioClipMoved.emit(
                    self._audio_clip_trim_id,
                    float(
                        getattr(
                            clip,
                            "start_time_seconds", 0.0)
                        or 0.0))
        self._audio_clip_drag_id = None
        self._audio_clip_drag_grab_dx = 0
        self._audio_clip_drag_started = False
        self._audio_clip_trim_id = None
        self._audio_clip_trim_side = None
        self._audio_clip_trim_started = False
        self._select_anchor_seconds = None
        self._in_selection_drag = False
        self._dragging_trim_handle = None
        self._drag_page_id = None
        self._drag_grab_dx_pixels = 0
        # Drop back to the default cursor — the next move event
        # will set OpenHand again if the cursor is still over
        # a clip body.
        self.unsetCursor()

    def _on_custom_context_menu_requested(
            self, local_pos) -> None:
        """Backup right-click router for environments where
        ``contextMenuEvent`` doesn't fire (some Linux WMs,
        macOS with certain focus policies on Qt.Tool windows).
        Same dispatch logic — slide block first, then audio
        clip block, then the whole-overlay menu."""
        self._dispatch_context_menu(local_pos)

    def _dispatch_context_menu(self, pos) -> None:
        # Slide block first.
        page_id = self._hit_test_block(pos)
        if page_id is not None:
            self._selected_page_id = page_id
            self.slideSelected.emit(page_id)
            self.update()
            self.slideContextRequested.emit(
                page_id, self.mapToGlobal(pos))
            return
        if self._audio_duration() <= 0:
            return
        clip_id = self.hit_audio_clip(pos)
        if clip_id is not None:
            self._selected_audio_clip_id = clip_id
            self.audioClipSelected.emit(clip_id)
            self.update()
            self.audioClipContextRequested.emit(
                clip_id, self.mapToGlobal(pos))
            return
        track = self._track_rect()
        if not (track.left() <= pos.x() <= track.right()
                and track.top() - 8 <= pos.y()
                <= track.bottom() + 8):
            return
        self.audioContextRequested.emit(
            self.mapToGlobal(pos))

    def contextMenuEvent(self, event) -> None:
        """Right-click routing. Same as
        ``_on_custom_context_menu_requested`` — both call
        ``_dispatch_context_menu``. We keep this override too
        because some hosts wire context menus via the virtual
        and only fall back to the signal in environments where
        the virtual doesn't fire."""
        self._dispatch_context_menu(event.pos())
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        pos = event.position().toPoint()
        # Slide block double-click keeps its existing behavior
        # (the host opens the slide image preview).
        page_id = self._hit_test_block(pos)
        if page_id is not None:
            self.slideDoubleClicked.emit(page_id)
            return
        # Anywhere ELSE on the timeline — including the audio
        # bar, the audio clip blocks, and the ruler — moves
        # the red playhead to the double-clicked x. The host
        # uses the playhead as the anchor for trim-before /
        # trim-after, so making it draggable-by-double-click
        # lets the writer scrub to a precise spot without
        # needing to grab the (1-pixel-wide) red line.
        if self._audio_duration() > 0:
            secs = max(
                0.0,
                min(self._audio_duration(),
                    self._x_to_seconds(pos.x())))
            self._playhead_seconds = secs
            self.update()

    def _hit_test_block(
            self, pos: QPoint) -> Optional[str]:
        band = self._slide_band_rect()
        if not band.contains(pos):
            return None
        for page, start, end in self._placed_blocks():
            x_left = self._seconds_to_x(start)
            x_right = self._seconds_to_x(end)
            if x_left <= pos.x() <= x_right:
                return page.id
        return None

    # ------------------------------------------------------------------
    # Drag & drop from the tray
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if (event.mimeData().hasFormat(_DRAG_MIME)
                or event.mimeData().hasFormat(
                    _AUDIO_CLIP_DRAG_MIME)):
            event.acceptProposedAction()
            self._drag_hover_x = (
                event.position().toPoint().x())
            self.update()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if (event.mimeData().hasFormat(_DRAG_MIME)
                or event.mimeData().hasFormat(
                    _AUDIO_CLIP_DRAG_MIME)):
            event.acceptProposedAction()
            self._drag_hover_x = (
                event.position().toPoint().x())
            self.update()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._drag_hover_x = None
        self.update()

    def dropEvent(self, event) -> None:
        # Audio clip drop from the clip list → position the
        # clip at the drop x.
        if event.mimeData().hasFormat(_AUDIO_CLIP_DRAG_MIME):
            clip_id = bytes(
                event.mimeData().data(
                    _AUDIO_CLIP_DRAG_MIME)).decode(
                "utf-8", "ignore")
            clip = self._find_audio_clip(clip_id)
            if clip is None:
                event.ignore()
                return
            # Snapshot BEFORE mutating the dropped clip's
            # start — the enforcer needs the prior layout to
            # know whether subsequent clips should cascade.
            self._snapshot_audio_clip_layout()
            secs = max(
                0.0,
                self._x_to_seconds(
                    event.position().toPoint().x()))
            clip.start_time_seconds = round(secs, 3)
            self._enforce_audio_no_overlap(clip.id)
            self._drag_hover_x = None
            self._selected_audio_clip_id = clip.id
            self.audioClipSelected.emit(clip.id)
            self.audioClipMoved.emit(
                clip.id,
                float(clip.start_time_seconds or 0.0))
            self.update()
            event.acceptProposedAction()
            return
        if not event.mimeData().hasFormat(_DRAG_MIME):
            event.ignore()
            return
        page_id = bytes(
            event.mimeData().data(_DRAG_MIME)).decode(
            "utf-8", "ignore")
        page = self._find_page(page_id)
        if page is None:
            event.ignore()
            return
        # Make sure the page is actually in this group; if a
        # writer dragged from a different group's tray we move
        # it over.
        if page.group_id != self._group.id:
            old = next(
                (g for g in self._deck.groups
                 if g.id == page.group_id), None)
            if old is not None:
                old.page_ids = [
                    pid for pid in old.page_ids
                    if pid != page.id]
            page.group_id = self._group.id
            if page.id not in self._group.page_ids:
                self._group.page_ids.append(page.id)
        # Snapshot BEFORE mutating so the enforcer can compute
        # delta correctly. Pages that weren't placed yet seed
        # the snapshot with their about-to-set value, so
        # cascade only kicks in when this drop displaced an
        # existing block.
        self._snapshot_slide_layout()
        secs = self._x_to_seconds(
            event.position().toPoint().x())
        secs = max(self._trim_in(), min(secs, self._trim_out()))
        page.start_time_seconds_in_group = round(secs, 3)
        self._enforce_slide_no_overlap(page.id)
        page.updated_at = datetime.now()
        self._drag_hover_x = None
        self.timelineChanged.emit()
        self._selected_page_id = page.id
        self.slideSelected.emit(page.id)
        self.update()
        event.acceptProposedAction()


def start_audio_clip_drag(
    source: QWidget,
    clip_id: str,
    label: str,
) -> None:
    """Kick off a Qt drag carrying an audio clip id. The clip
    list calls this from its ``mouseMoveEvent`` when the writer
    drags a clip row onto the timeline. The timeline's
    ``dropEvent`` then sets ``start_time_seconds`` to the drop
    x-position."""
    drag = QDrag(source)
    mime = QMimeData()
    mime.setData(
        _AUDIO_CLIP_DRAG_MIME, clip_id.encode("utf-8"))
    drag.setMimeData(mime)
    # Tiny text pixmap so the writer sees what they're
    # dragging; we don't have a thumbnail for audio.
    from PyQt6.QtGui import QPainter as _QP
    pix = QPixmap(160, 28)
    pix.fill(QColor("#22d3ee"))
    p = _QP(pix)
    p.setPen(QColor("#0f172a"))
    p.drawText(pix.rect(),
               Qt.AlignmentFlag.AlignCenter,
               f"🔊 {label}")
    p.end()
    drag.setPixmap(pix)
    drag.setHotSpot(QPoint(pix.width() // 2, pix.height() // 2))
    drag.exec(Qt.DropAction.MoveAction)


# ----------------------------------------------------------------------
# Helper for the tray: build a QDrag from a slide pixmap
# ----------------------------------------------------------------------
def start_slide_drag(
    source: QWidget,
    page_id: str,
    page_label: str,
    pixmap: Optional[QPixmap],
) -> None:
    """Kick off a Qt drag carrying a slide id. The tray widget
    calls this from its ``mouseMoveEvent`` when the writer drags
    a slide off the tray onto the timeline."""
    drag = QDrag(source)
    mime = QMimeData()
    mime.setData(_DRAG_MIME, page_id.encode("utf-8"))
    drag.setMimeData(mime)
    if pixmap is not None and not pixmap.isNull():
        scaled = pixmap.scaledToHeight(
            72, Qt.TransformationMode.SmoothTransformation)
        drag.setPixmap(scaled)
        drag.setHotSpot(
            QPoint(scaled.width() // 2, scaled.height() // 2))
    drag.exec(Qt.DropAction.MoveAction)
