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


_DRAG_MIME = "application/x-writingaid-slide-id"


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
        self._selected_page_id = None
        self.update()

    def refresh_waveform(self) -> None:
        """Drop the cached peaks so the next paint reloads them.
        Call after recording / importing / applying transforms —
        anything that mutates the underlying audio file."""
        self._waveform_peaks = None
        self._waveform_audio_path = ""
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
        # Audio bar — base fill + waveform peaks overlay.
        track = self._track_rect()
        audio_color = (
            QColor("#1e3a8a") if self._audio_duration() > 0
            else QColor("#334155"))
        painter.fillRect(track, audio_color)
        # Trim shading: dim the audio bar outside the trim
        # window so the kept region pops out visually.
        if self._audio_duration() > 0:
            in_x = self._seconds_to_x(self._trim_in())
            out_x = self._seconds_to_x(self._trim_out())
            kept = QRect(
                in_x, track.top(),
                max(0, out_x - in_x), track.height())
            painter.fillRect(kept, QColor("#3b82f6"))
        painter.setPen(QPen(QColor("#1e293b"), 1))
        painter.drawRect(track)
        # Waveform.
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

    def _start_internal_reorder_drag(self, new_x: int) -> None:
        if self._drag_page_id is None:
            return
        page = self._find_page(self._drag_page_id)
        if page is None:
            return
        secs = self._x_to_seconds(new_x)
        secs = max(self._trim_in(), min(secs, self._trim_out()))
        page.start_time_seconds_in_group = round(secs, 3)
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
        self._select_anchor_seconds = None
        self._in_selection_drag = False
        self._dragging_trim_handle = None
        self._drag_page_id = None
        self._drag_grab_dx_pixels = 0

    def contextMenuEvent(self, event) -> None:
        """Right-click on the audio bar (only when audio is
        loaded) fires ``audioContextRequested`` with a GLOBAL
        QPoint. The host dialog uses it to position a transform
        menu over the click."""
        if self._audio_duration() <= 0:
            return
        pos = event.pos()
        track = self._track_rect()
        # Allow a few pixels of slop above / below the bar so
        # writers don't have to hit a 56-pixel target dead-on.
        if not (track.left() <= pos.x() <= track.right()
                and track.top() - 8 <= pos.y()
                <= track.bottom() + 8):
            return
        self.audioContextRequested.emit(
            self.mapToGlobal(pos))
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        pos = event.position().toPoint()
        page_id = self._hit_test_block(pos)
        if page_id is not None:
            self.slideDoubleClicked.emit(page_id)

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
        if event.mimeData().hasFormat(_DRAG_MIME):
            event.acceptProposedAction()
            self._drag_hover_x = (
                event.position().toPoint().x())
            self.update()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(_DRAG_MIME):
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
        secs = self._x_to_seconds(
            event.position().toPoint().x())
        secs = max(self._trim_in(), min(secs, self._trim_out()))
        page.start_time_seconds_in_group = round(secs, 3)
        page.updated_at = datetime.now()
        self._drag_hover_x = None
        self.timelineChanged.emit()
        self._selected_page_id = page.id
        self.slideSelected.emit(page.id)
        self.update()
        event.acceptProposedAction()


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
