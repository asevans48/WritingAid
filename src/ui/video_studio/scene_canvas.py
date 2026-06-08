"""Scene canvas — QGraphicsView with grid-snapped cards and hops.

Each ``SceneCardItem`` is a QGraphicsObject so it can emit signals
(double-click opens the editor). Cards are positioned by
``(grid_col, grid_row)``; the canvas converts to pixel coords using
a fixed cell size. Dragging a card snaps it to the nearest empty
cell when the mouse is released.

Hops (edges) are repainted whenever a card moves or the scene set
changes — see ``_refresh_hops``. They're not user-draggable in v1;
users add hops via a context menu ("Connect to → …").
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QPainterPath, QPen, QPolygonF,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsObject, QGraphicsPathItem,
    QGraphicsScene, QGraphicsView, QMenu,
)

from src.video_studio.models import Scene, SceneHop, VideoStudio


# Pixel geometry. Card cells are wide enough for a name + a couple
# of meta lines; gutter keeps cards visually separated so cards
# don't smash together at the grid boundary.
CARD_W = 220
# Bumped from 140 → 180 to make room for the in-card "Generate
# video / image / slide deck" button row painted just above the
# footer. Grid math (CELL_H) tracks automatically.
CARD_H = 180
CELL_GUTTER = 28
CELL_W = CARD_W + CELL_GUTTER
CELL_H = CARD_H + CELL_GUTTER
CANVAS_PADDING = 32


# ---------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------
class SceneCardItem(QGraphicsObject):
    """A draggable scene card.

    Signals (Qt) so the canvas / parent widget can react:
      * ``editRequested`` — double-click; open the editor
      * ``moved`` — drag finished; canvas snaps + persists
      * ``contextMenuRequested`` — right-click; canvas opens menu
    """
    editRequested = pyqtSignal(str)            # scene_id
    moved = pyqtSignal(str)                    # scene_id
    contextMenuRequested = pyqtSignal(str, QPointF)  # scene_id, scene-pos
    # In-card button signals — let the writer kick off renders
    # without right-clicking. Wired up by SceneCanvasView, which
    # forwards to the studio widget's existing generate handlers.
    generateVideoClicked = pyqtSignal(str)        # scene_id
    generateImageClicked = pyqtSignal(str)        # scene_id
    generateSlideDeckClicked = pyqtSignal(str)    # scene_id

    def __init__(self, scene: Scene):
        super().__init__()
        self._scene_id = scene.id
        self._name = scene.name or "(unnamed)"
        self._clip_count = len(scene.clips)
        self._favorite_set = bool(scene.favorite_clip_id)
        self._description_preview = (
            (scene.description or "")[:80] + "…"
            if len(scene.description or "") > 80
            else (scene.description or ""))
        self._chapter_number = scene.chapter_number
        self._has_source_prose = bool(
            (scene.source_prose or "").strip())
        self._action_count = len(scene.actions)
        self._mode = scene.mode or "video"
        # Button geometry + state. Filled by ``_paint_button_row``
        # on every paint so it always tracks the current card size,
        # and read by mousePressEvent for hit testing. ``_pressed_btn``
        # holds the key of the button currently being pressed so
        # paint() can draw it in its pressed state.
        self._button_rects: dict = {}
        self._pressed_btn: Optional[str] = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)

    @property
    def scene_id(self) -> str:
        return self._scene_id

    def update_from_scene(self, scene: Scene) -> None:
        """Refresh display data from the underlying scene model.
        Called after the editor saves changes back to the model."""
        self._name = scene.name or "(unnamed)"
        self._clip_count = len(scene.clips)
        self._favorite_set = bool(scene.favorite_clip_id)
        self._description_preview = (
            (scene.description or "")[:80] + "…"
            if len(scene.description or "") > 80
            else (scene.description or ""))
        self._chapter_number = scene.chapter_number
        self._has_source_prose = bool(
            (scene.source_prose or "").strip())
        self._action_count = len(scene.actions)
        self._mode = scene.mode or "video"
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, CARD_W, CARD_H)

    def paint(self, painter, option, widget=None) -> None:
        rect = self.boundingRect().adjusted(0.5, 0.5, -0.5, -0.5)
        selected = self.isSelected()
        # Card body
        bg = QColor("#ffffff") if not selected else QColor("#eef2ff")
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(
            QColor("#6366f1" if selected else "#cbd5e1"),
            2 if selected else 1))
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.drawPath(path)
        # Title strip
        title_rect = QRectF(rect.x(), rect.y(), rect.width(), 32)
        painter.setBrush(QBrush(QColor("#f1f5f9")))
        painter.setPen(Qt.PenStyle.NoPen)
        title_path = QPainterPath()
        title_path.addRoundedRect(title_rect, 10, 10)
        painter.drawPath(title_path)
        # The rounded title strip leaves a faint sliver under the
        # bottom of the title; fill it so the boundary looks clean.
        painter.drawRect(QRectF(
            title_rect.x(), title_rect.bottom() - 6,
            title_rect.width(), 6))
        # Title text
        painter.setPen(QPen(QColor("#0f172a")))
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            title_rect.adjusted(12, 2, -12, 0),
            int(Qt.AlignmentFlag.AlignVCenter
                | Qt.AlignmentFlag.AlignLeft),
            self._name)
        # Mode chip in the upper-right of the title strip — at-a-
        # glance signal of which render path this scene uses and
        # an affordance the writer can click via the context menu
        # to switch. Color-coded so a mixed board reads instantly.
        is_slideshow = (self._mode == "slideshow")
        chip_w, chip_h = 76, 18
        chip_x = title_rect.right() - chip_w - 8
        chip_y = title_rect.y() + (title_rect.height() - chip_h) / 2
        chip_rect = QRectF(chip_x, chip_y, chip_w, chip_h)
        chip_bg = (QColor("#fef3c7") if is_slideshow
                   else QColor("#dbeafe"))
        chip_border = (QColor("#d97706") if is_slideshow
                       else QColor("#2563eb"))
        chip_text_color = (QColor("#92400e") if is_slideshow
                           else QColor("#1d4ed8"))
        painter.setBrush(QBrush(chip_bg))
        painter.setPen(QPen(chip_border, 1))
        chip_path = QPainterPath()
        chip_path.addRoundedRect(chip_rect, 9, 9)
        painter.drawPath(chip_path)
        painter.setPen(QPen(chip_text_color))
        chip_font = QFont()
        chip_font.setPointSize(8)
        chip_font.setBold(True)
        painter.setFont(chip_font)
        chip_label = ("🖼 slideshow" if is_slideshow
                      else "🎬 video")
        painter.drawText(
            chip_rect,
            int(Qt.AlignmentFlag.AlignCenter),
            chip_label)
        # Description preview — shrunken to leave room for the
        # button row painted just above the footer.
        painter.setPen(QPen(QColor("#475569")))
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        desc_rect = QRectF(rect.x() + 12, rect.y() + 40,
                           rect.width() - 24, 70)
        painter.drawText(
            desc_rect,
            int(Qt.AlignmentFlag.AlignTop
                | Qt.AlignmentFlag.AlignLeft
                | Qt.TextFlag.TextWordWrap),
            self._description_preview or "(no description)")
        # Generation buttons row — painted directly on the card so
        # the writer can kick off a render without right-clicking or
        # opening the editor. Hit-tested in mousePressEvent below.
        self._paint_button_row(painter, rect)
        # Footer: chapter + clip count badge
        footer_rect = QRectF(rect.x() + 12,
                             rect.bottom() - 24,
                             rect.width() - 24, 18)
        footer_text_parts = []
        if self._chapter_number:
            footer_text_parts.append(f"Ch. {self._chapter_number}")
        footer_text_parts.append(
            f"{self._clip_count} clip"
            + ("s" if self._clip_count != 1 else ""))
        if self._action_count:
            footer_text_parts.append(
                f"{self._action_count} action"
                + ("s" if self._action_count != 1 else ""))
        if self._has_source_prose:
            # Pencil-and-page glyph signals the writer has anchored
            # this scene to a chapter excerpt — easy at-a-glance
            # check that "Pull from chapter" actually persisted.
            footer_text_parts.append("📜 prose")
        if self._favorite_set:
            footer_text_parts.append("★ favorite set")
        painter.setPen(QPen(QColor("#64748b")))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(
            footer_rect,
            int(Qt.AlignmentFlag.AlignVCenter
                | Qt.AlignmentFlag.AlignLeft),
            " · ".join(footer_text_parts))

    # ------------------------------------------------------------------
    # In-card buttons — paint + hit-test
    # ------------------------------------------------------------------
    def _paint_button_row(self, painter, rect: QRectF) -> None:
        """Render the inline generation buttons just above the
        footer. Up to three buttons: Video (always), Image (always),
        Slide deck (only when the scene has actions). Button rects
        are cached on ``self._button_rects`` for hit testing.
        """
        self._button_rects = {}
        keys = [("video", "🎬 Video", "#2563eb", "#dbeafe"),
                ("image", "🖼 Image", "#d97706", "#fef3c7")]
        if self._action_count:
            keys.append(
                ("deck", "📑 Deck", "#059669", "#d1fae5"))
        n = len(keys)
        # Buttons live in a 28px-tall band 28px above the bottom
        # edge, leaving 24px below for the footer text.
        band_top = rect.bottom() - 56
        band_h = 26
        # Equal-width buttons with 6px gaps.
        gap = 6
        pad_x = 12
        total_w = rect.width() - 2 * pad_x
        btn_w = (total_w - gap * (n - 1)) / n
        for i, (key, label, border, fill) in enumerate(keys):
            x = rect.x() + pad_x + i * (btn_w + gap)
            btn_rect = QRectF(x, band_top, btn_w, band_h)
            self._button_rects[key] = btn_rect
            is_pressed = (self._pressed_btn == key)
            bg = QColor(fill).darker(108) if is_pressed else QColor(fill)
            painter.setBrush(QBrush(bg))
            painter.setPen(QPen(QColor(border), 1))
            path = QPainterPath()
            path.addRoundedRect(btn_rect, 6, 6)
            painter.drawPath(path)
            painter.setPen(QPen(QColor(border).darker(140)))
            f = QFont()
            f.setPointSize(8)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(
                btn_rect, int(Qt.AlignmentFlag.AlignCenter), label)

    def _button_at(self, pos: QPointF) -> Optional[str]:
        for key, rect in self._button_rects.items():
            if rect.contains(pos):
                return key
        return None

    def mouseDoubleClickEvent(self, event) -> None:
        # Don't open the editor when the user double-clicks one of
        # the inline buttons — the first click already fired it.
        if self._button_at(event.pos()) is not None:
            event.accept()
            return
        self.editRequested.emit(self._scene_id)
        event.accept()

    def mousePressEvent(self, event) -> None:
        hit = self._button_at(event.pos())
        if hit is not None:
            # Capture the press so paint() can show the pressed
            # state, then suppress the drag-start that the base
            # class would otherwise begin.
            self._pressed_btn = hit
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        # If we were tracking a button press, fire the signal when
        # the release lands inside the SAME button. Standard
        # button-cancel behavior when the user drags off.
        if self._pressed_btn is not None:
            target = self._pressed_btn
            self._pressed_btn = None
            self.update()
            hit = self._button_at(event.pos())
            if hit == target:
                if target == "video":
                    self.generateVideoClicked.emit(self._scene_id)
                elif target == "image":
                    self.generateImageClicked.emit(self._scene_id)
                elif target == "deck":
                    self.generateSlideDeckClicked.emit(
                        self._scene_id)
            event.accept()
            return
        # Snap-to-grid happens at the canvas level after release; we
        # just emit the moved signal so the canvas can re-snap and
        # repaint hops.
        super().mouseReleaseEvent(event)
        self.moved.emit(self._scene_id)

    def contextMenuEvent(self, event) -> None:
        self.contextMenuRequested.emit(
            self._scene_id, event.scenePos())
        event.accept()


# ---------------------------------------------------------------------
# Canvas view
# ---------------------------------------------------------------------
class SceneCanvasView(QGraphicsView):
    """View + scene combined into one widget. Owns the live mapping
    from scene IDs to card items so we can move / remove / refresh
    cards as the studio model changes.
    """
    sceneEditRequested = pyqtSignal(str)        # scene_id
    addSceneRequested = pyqtSignal(QPointF)     # canvas (scene) pos
    connectRequested = pyqtSignal(str, str)     # from_id, to_id
    manageHopsRequested = pyqtSignal(str)       # scene_id
    deleteSceneRequested = pyqtSignal(str)
    generateClipRequested = pyqtSignal(str)     # video clip
    generateImageRequested = pyqtSignal(str)    # image still
    generateSlideDeckRequested = pyqtSignal(str)  # per-action images
    stitchSlideDeckRequested = pyqtSignal(str)  # action images → mp4
    openLastClipRequested = pyqtSignal(str)     # open favorite clip
    openOutputFolderRequested = pyqtSignal(str)  # open scene dir
    copyPromptRequested = pyqtSignal(str)       # copy generation prompt
    uploadClipRequested = pyqtSignal(str)       # upload image/video file
    switchModeRequested = pyqtSignal(str, str)  # scene_id, "video"|"slideshow"
    sceneMoved = pyqtSignal(str, int, int)      # scene_id, col, row

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(self.renderHints()
                            | self.renderHints().Antialiasing)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(QBrush(QColor("#f8fafc")))
        # ScrollHandDrag on empty-canvas middle-click would be nice
        # too, but RubberBandDrag would conflict with card drags.
        # Keep the default NoDrag mode so card drags route to the
        # items first; the scrollbars handle panning.
        self._studio: Optional[VideoStudio] = None
        self._cards: Dict[str, SceneCardItem] = {}
        self._hop_items: List[QGraphicsPathItem] = []
        # Tracks ongoing "connect from" mode when user picks
        # "Connect to ..." from the context menu — second click on
        # another card commits the new hop.
        self._connect_from_id: Optional[str] = None
        # Zoom level — applied via setTransform's scaling. Range
        # caps stop the user from zooming so far that cards are 1px
        # or so big the view goes off-screen.
        self._zoom_level: float = 1.0

    # ------------------------------------------------------------------
    # Zoom + fit-to-view (Ctrl+wheel to zoom, no modifier scrolls)
    # ------------------------------------------------------------------
    _ZOOM_MIN = 0.25
    _ZOOM_MAX = 3.0
    _ZOOM_STEP = 1.15

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        """Ctrl + wheel zooms the canvas; plain wheel scrolls."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                return
            factor = (self._ZOOM_STEP if delta > 0
                      else 1.0 / self._ZOOM_STEP)
            new_zoom = self._zoom_level * factor
            if new_zoom < self._ZOOM_MIN or new_zoom > self._ZOOM_MAX:
                return
            self._zoom_level = new_zoom
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    def reset_zoom(self) -> None:
        """Snap back to 1:1 zoom and re-center on the scene."""
        self.resetTransform()
        self._zoom_level = 1.0
        s = self.scene()
        if s is not None:
            self.centerOn(s.itemsBoundingRect().center())

    def fit_to_view(self) -> None:
        """Scale so every card fits in the viewport. Capped at the
        zoom max so a single-scene board doesn't end up
        comically magnified."""
        s = self.scene()
        if s is None:
            return
        rect = s.itemsBoundingRect()
        if rect.isEmpty():
            return
        # ``fitInView`` resets the transform and re-scales. After
        # that we recompute our tracked zoom from the actual
        # transform so subsequent Ctrl+wheel steps move from here.
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        scale = self.transform().m11()
        if scale > self._ZOOM_MAX:
            # Re-cap to the max zoom.
            self.resetTransform()
            self.scale(self._ZOOM_MAX, self._ZOOM_MAX)
            self._zoom_level = self._ZOOM_MAX
            self.centerOn(rect.center())
        else:
            self._zoom_level = max(self._ZOOM_MIN, scale)

    # ------------------------------------------------------------------
    # Loading / refresh
    # ------------------------------------------------------------------
    def load_studio(self, studio: VideoStudio) -> None:
        self._studio = studio
        self._rebuild_all()

    def _rebuild_all(self) -> None:
        """Clear and recreate every item. Cheap enough for the
        scene counts the studio holds (tens, not thousands)."""
        s = self.scene()
        s.clear()
        self._cards.clear()
        self._hop_items.clear()
        if self._studio is None:
            return
        self._draw_grid()
        # Cards
        for scene in self._studio.scenes:
            card = self._make_card(scene)
            s.addItem(card)
            self._cards[scene.id] = card
        # Hops sit BEHIND cards in z-order so they don't overlap text
        self._refresh_hops()
        # Set scene rect so scrollbars work cleanly even when scenes
        # haven't been added far enough to push the bounds.
        cols = max(self._studio.grid_cols, 4)
        rows = max(self._studio.grid_rows, 4)
        s.setSceneRect(QRectF(
            -CANVAS_PADDING, -CANVAS_PADDING,
            cols * CELL_W + 2 * CANVAS_PADDING,
            rows * CELL_H + 2 * CANVAS_PADDING))

    def _draw_grid(self) -> None:
        """Draw a faint grid behind everything so users see the
        snap targets while dragging cards."""
        if self._studio is None:
            return
        s = self.scene()
        pen = QPen(QColor("#e2e8f0"), 1, Qt.PenStyle.DashLine)
        cols = self._studio.grid_cols
        rows = self._studio.grid_rows
        x_extent = cols * CELL_W
        y_extent = rows * CELL_H
        for c in range(cols + 1):
            x = c * CELL_W
            line = s.addLine(x, 0, x, y_extent, pen)
            line.setZValue(-100)
        for r in range(rows + 1):
            y = r * CELL_H
            line = s.addLine(0, y, x_extent, y, pen)
            line.setZValue(-100)

    def _make_card(self, scene: Scene) -> SceneCardItem:
        card = SceneCardItem(scene)
        card.setPos(self._cell_to_pixel(scene.grid_col, scene.grid_row))
        card.editRequested.connect(self.sceneEditRequested)
        card.moved.connect(self._on_card_moved)
        card.contextMenuRequested.connect(self._on_card_context)
        # Forward the in-card button clicks through the canvas's
        # existing generate signals so the studio widget doesn't
        # need new wiring — both the right-click menu and the
        # painted buttons land on the same handlers.
        card.generateVideoClicked.connect(
            self.generateClipRequested)
        card.generateImageClicked.connect(
            self.generateImageRequested)
        card.generateSlideDeckClicked.connect(
            self.generateSlideDeckRequested)
        card.setZValue(1)
        return card

    @staticmethod
    def _cell_to_pixel(col: int, row: int) -> QPointF:
        return QPointF(col * CELL_W + CELL_GUTTER / 2,
                       row * CELL_H + CELL_GUTTER / 2)

    @staticmethod
    def _pixel_to_cell(pos: QPointF) -> Tuple[int, int]:
        return (int(round((pos.x() - CELL_GUTTER / 2) / CELL_W)),
                int(round((pos.y() - CELL_GUTTER / 2) / CELL_H)))

    # ------------------------------------------------------------------
    # Hop drawing
    # ------------------------------------------------------------------
    def _refresh_hops(self) -> None:
        """Wipe and redraw every hop. Called on load and after any
        card move. Cheap; hop count is small."""
        s = self.scene()
        for h in self._hop_items:
            s.removeItem(h)
        self._hop_items.clear()
        if self._studio is None:
            return
        for hop in self._studio.hops:
            self._draw_hop(hop)

    def _draw_hop(self, hop: SceneHop) -> None:
        a = self._cards.get(hop.from_scene_id)
        b = self._cards.get(hop.to_scene_id)
        if a is None or b is None:
            return
        a_center = a.pos() + QPointF(CARD_W / 2, CARD_H / 2)
        b_center = b.pos() + QPointF(CARD_W / 2, CARD_H / 2)
        # Trim the line so it starts at the edge of A and ends at
        # the edge of B (so the arrowhead doesn't drown in B's body).
        start = _intersect_with_card_edge(a.pos(), a_center, b_center)
        end = _intersect_with_card_edge(b.pos(), b_center, a_center)
        path = QPainterPath()
        path.moveTo(start)
        # Slight curve so multiple hops between similar cells don't
        # overlap as straight lines.
        ctrl = QPointF((start.x() + end.x()) / 2,
                       (start.y() + end.y()) / 2
                       - 22 if start.y() == end.y() else 0)
        path.quadTo(ctrl, end)
        item = QGraphicsPathItem(path)
        pen = QPen(QColor("#6366f1"), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        item.setPen(pen)
        # ``setBrush`` wants a QBrush, not the BrushStyle enum.
        # ``QBrush()`` with no args produces a "no brush" — we want
        # the hop drawn as an outline only, no fill under the curve.
        item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        item.setZValue(0)
        s = self.scene()
        s.addItem(item)
        self._hop_items.append(item)
        # Arrowhead
        arrow_poly = _arrowhead(end, start)
        arrow_item = s.addPolygon(
            arrow_poly,
            QPen(QColor("#6366f1"), 1),
            QBrush(QColor("#6366f1")))
        arrow_item.setZValue(0)
        self._hop_items.append(arrow_item)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def _on_card_moved(self, scene_id: str) -> None:
        if self._studio is None:
            return
        card = self._cards.get(scene_id)
        if card is None:
            return
        col, row = self._pixel_to_cell(card.pos())
        # Snap card to the chosen cell. If occupied, bounce back.
        if not self._studio.move_scene(scene_id, col, row):
            # Restore original position.
            sc = self._studio.get_scene(scene_id)
            if sc is not None:
                card.setPos(self._cell_to_pixel(sc.grid_col, sc.grid_row))
        else:
            card.setPos(self._cell_to_pixel(col, row))
            self.sceneMoved.emit(scene_id, col, row)
        self._refresh_hops()

    def _on_card_context(self, scene_id: str, scene_pos: QPointF) -> None:
        if self._studio is None:
            return
        menu = QMenu(self)
        menu.addAction("Edit scene", lambda:
                       self.sceneEditRequested.emit(scene_id))
        menu.addAction(
            "Manage hops…",
            lambda: self.manageHopsRequested.emit(scene_id))
        if self._connect_from_id is None:
            menu.addAction(
                "Connect to … (then click another card)",
                lambda: self._begin_connect(scene_id))
        else:
            other = self._connect_from_id
            menu.addAction(
                f"Finish hop FROM {self._scene_name(other)} TO this",
                lambda: self._finish_connect(scene_id))
            menu.addAction(
                "Cancel pending hop",
                lambda: self._cancel_connect())
        menu.addSeparator()
        # Mode-aware generation commands. Both backends are always
        # available — letting the user mix video and image scenes
        # in the same board freely — but the slideshow variant is
        # promoted when this scene has actions because that's where
        # the per-action images live.
        scene_obj = self._studio.get_scene(scene_id)
        current_mode = (
            getattr(scene_obj, "mode", "video") or "video")
        action_count = len(getattr(scene_obj, "actions", []) or [])
        menu.addAction("Generate video clip", lambda:
                       self.generateClipRequested.emit(scene_id))
        menu.addAction("Generate image still", lambda:
                       self.generateImageRequested.emit(scene_id))
        if action_count:
            menu.addAction(
                f"Generate slide deck ({action_count} action"
                + ("s" if action_count != 1 else "") + ")",
                lambda: self.generateSlideDeckRequested.emit(
                    scene_id))
            # Stitch only makes sense once images exist; we still
            # offer it so the user can find it — the handler will
            # explain when there's nothing to stitch yet.
            menu.addAction(
                "Stitch slide deck → video",
                lambda: self.stitchSlideDeckRequested.emit(
                    scene_id))
        menu.addSeparator()
        # Open paths — let the writer view what's been generated
        # without digging into the editor or Finder.
        clips_count = len(getattr(scene_obj, "clips", []) or [])
        if clips_count:
            menu.addAction(
                "Open last clip / image",
                lambda: self.openLastClipRequested.emit(scene_id))
        menu.addAction(
            "Open output folder",
            lambda: self.openOutputFolderRequested.emit(scene_id))
        menu.addAction(
            "Copy generation prompt",
            lambda: self.copyPromptRequested.emit(scene_id))
        menu.addAction(
            "📤 Upload image / video…",
            lambda: self.uploadClipRequested.emit(scene_id))
        menu.addSeparator()
        # Quick render-mode toggle so writers can mix video and
        # slideshow scenes on one board without opening the editor
        # for every scene.
        if current_mode == "slideshow":
            menu.addAction(
                "Switch render mode → 🎬 Video",
                lambda: self.switchModeRequested.emit(
                    scene_id, "video"))
        else:
            menu.addAction(
                "Switch render mode → 🖼 Slideshow",
                lambda: self.switchModeRequested.emit(
                    scene_id, "slideshow"))
        menu.addSeparator()
        menu.addAction("Delete scene", lambda:
                       self.deleteSceneRequested.emit(scene_id))
        # Position the menu using the view-space coordinate.
        view_pos = self.mapFromScene(scene_pos)
        global_pos = self.mapToGlobal(view_pos)
        menu.exec(global_pos)

    def _begin_connect(self, scene_id: str) -> None:
        self._connect_from_id = scene_id

    def _finish_connect(self, to_id: str) -> None:
        if self._connect_from_id and self._connect_from_id != to_id:
            self.connectRequested.emit(self._connect_from_id, to_id)
        self._connect_from_id = None

    def _cancel_connect(self) -> None:
        self._connect_from_id = None

    def _scene_name(self, scene_id: str) -> str:
        if self._studio is None:
            return scene_id
        s = self._studio.get_scene(scene_id)
        return s.name if s else scene_id

    # ------------------------------------------------------------------
    # Empty-area context menu — add a scene at the clicked cell
    # ------------------------------------------------------------------
    def contextMenuEvent(self, event) -> None:
        # If a card handled it, don't open the canvas menu.
        item = self.itemAt(event.pos())
        if isinstance(item, SceneCardItem):
            super().contextMenuEvent(event)
            return
        if self._studio is None:
            return
        menu = QMenu(self)
        scene_pos = self.mapToScene(event.pos())
        menu.addAction(
            "Add scene here",
            lambda: self.addSceneRequested.emit(scene_pos))
        if self._connect_from_id is not None:
            menu.addSeparator()
            menu.addAction(
                "Cancel pending hop",
                lambda: self._cancel_connect())
        menu.exec(event.globalPos())

    # ------------------------------------------------------------------
    # Public refresh after model mutation
    # ------------------------------------------------------------------
    def refresh_scene_card(self, scene_id: str) -> None:
        """Update a single card's visuals (e.g., after the editor
        modified its name or clip count)."""
        if self._studio is None:
            return
        s = self._studio.get_scene(scene_id)
        card = self._cards.get(scene_id)
        if s is None or card is None:
            return
        card.update_from_scene(s)
        card.setPos(self._cell_to_pixel(s.grid_col, s.grid_row))
        self._refresh_hops()

    def refresh_all(self) -> None:
        """Full rebuild — call after a scene is added/deleted or
        the grid configuration changes."""
        self._rebuild_all()


# ---------------------------------------------------------------------
# Module-level geometry helpers
# ---------------------------------------------------------------------
def _intersect_with_card_edge(
    card_topleft: QPointF,
    card_center: QPointF,
    target_center: QPointF,
) -> QPointF:
    """Clip the line from card_center toward target_center at the
    edge of the card's bounding rect, so the hop line stops there
    instead of crossing into the card. Liang–Barsky for axis-
    aligned rectangle."""
    dx = target_center.x() - card_center.x()
    dy = target_center.y() - card_center.y()
    if dx == 0 and dy == 0:
        return card_center
    left = card_topleft.x()
    top = card_topleft.y()
    right = left + CARD_W
    bottom = top + CARD_H
    t = 1.0
    if dx != 0:
        t_x1 = (left - card_center.x()) / dx
        t_x2 = (right - card_center.x()) / dx
        for t_candidate in (t_x1, t_x2):
            if 0 < t_candidate < t:
                y_at = card_center.y() + t_candidate * dy
                if top <= y_at <= bottom:
                    t = t_candidate
    if dy != 0:
        t_y1 = (top - card_center.y()) / dy
        t_y2 = (bottom - card_center.y()) / dy
        for t_candidate in (t_y1, t_y2):
            if 0 < t_candidate < t:
                x_at = card_center.x() + t_candidate * dx
                if left <= x_at <= right:
                    t = t_candidate
    return QPointF(card_center.x() + t * dx,
                   card_center.y() + t * dy)


def _arrowhead(tip: QPointF, towards: QPointF) -> QPolygonF:
    """A small triangle pointing along the line from tip toward
    towards (used to terminate the hop at its destination card)."""
    angle = math.atan2(towards.y() - tip.y(), towards.x() - tip.x())
    size = 10
    p1 = QPointF(tip.x() + math.cos(angle) * size
                 - math.sin(angle) * size * 0.5,
                 tip.y() + math.sin(angle) * size
                 + math.cos(angle) * size * 0.5)
    p2 = QPointF(tip.x() + math.cos(angle) * size
                 + math.sin(angle) * size * 0.5,
                 tip.y() + math.sin(angle) * size
                 - math.cos(angle) * size * 0.5)
    return QPolygonF([tip, p1, p2])
