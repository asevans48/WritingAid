"""A PowerPoint-style WYSIWYG canvas for designing a slide/card.

The scene is a fixed 1920x1080 frame (scene coordinates ARE render
pixels at 1080p; every element stores its geometry normalized to
0..1). ``ElementItem`` renders one text / image / video element and
supports click-drag move, 8-handle resize, and z-ordered layering —
the same gestures as PowerPoint / Impress / Canva. ``ElementPalette``
offers draggable element types; ``SlideDesignCanvas`` hosts the frame
background plus the elements, accepts palette drops, and round-trips
the whole design to/from a ``TitleCard``'s ``elements`` list.
"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import (
    QMimeData, QPointF, QRectF, Qt, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDrag, QFont, QImage, QPainter, QPen, QPixmap,
    QTextCursor, QTextOption,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsTextItem, QGraphicsView, QListWidget, QListWidgetItem,
)

from src.video_studio.models import SlideElement

FRAME_W = 1920
FRAME_H = 1080
ELEMENT_MIME = "application/x-slide-element"


def _qcolor(hex_str: str, default: str = "#FFFFFF") -> QColor:
    c = QColor(hex_str.strip()) if hex_str else QColor()
    return c if c.isValid() else QColor(default)


class ElementPalette(QListWidget):
    """A little tray of DRAGGABLE element types. Drag one onto the
    canvas to drop a new element where you release it."""

    ITEMS = [
        ("title", "🔠  Title"),
        ("text", "🅃  Text box"),
        ("image", "🖼  Image"),
        ("video", "🎞  Video"),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setFixedWidth(150)
        self.setSpacing(2)
        for key, label in self.ITEMS:
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.addItem(it)

    def startDrag(self, actions) -> None:
        it = self.currentItem()
        if it is None:
            return
        kind = it.data(Qt.ItemDataRole.UserRole)
        mime = QMimeData()
        mime.setData(ELEMENT_MIME, str(kind).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class ElementItem(QGraphicsRectItem):
    """A movable, resizable, z-ordered element: text, image, or a
    (playing) video. Renders text with alignment / legibility fill /
    outline / shadow, or a fitted media preview with a ▶ badge for
    video."""

    HANDLE = 22  # scene-unit hit radius for resize handles
    _CURSORS = {
        "tl": Qt.CursorShape.SizeFDiagCursor,
        "br": Qt.CursorShape.SizeFDiagCursor,
        "tr": Qt.CursorShape.SizeBDiagCursor,
        "bl": Qt.CursorShape.SizeBDiagCursor,
        "t": Qt.CursorShape.SizeVerCursor,
        "b": Qt.CursorShape.SizeVerCursor,
        "l": Qt.CursorShape.SizeHorCursor,
        "r": Qt.CursorShape.SizeHorCursor,
    }

    def __init__(self, canvas: "SlideDesignCanvas") -> None:
        super().__init__(0.0, 0.0, 600.0, 200.0)
        self._canvas = canvas
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        # Common.
        self.el_id: Optional[str] = None
        self.kind: str = "text"
        # Text.
        self.text: str = "Text"
        self.font_size: int = 72
        self.color: str = "#FFFFFF"
        self.align: str = "center"
        self.valign: str = "middle"
        self.bold: bool = False
        self.italic: bool = False
        self.box_color: str = ""
        self.box_opacity: float = 0.5
        self.outline_color: str = ""
        self.outline_width: int = 0
        self.shadow: bool = False
        # Media.
        self.media_path: str = ""
        self.video_muted: bool = False
        self.video_loop: bool = True
        self._pixmap: Optional[QPixmap] = None
        self._active_handle: Optional[str] = None
        self._editing: bool = False  # inline text editor is open

    # -- model round-trip ---------------------------------------------
    def load(self, el: SlideElement) -> None:
        self.el_id = el.id
        self.kind = el.kind or "text"
        self.text = el.text or ""
        self.font_size = int(el.font_size or 72)
        self.color = el.color or "#FFFFFF"
        self.align = el.align or "center"
        self.valign = el.valign or "middle"
        self.bold = bool(el.bold)
        self.italic = bool(el.italic)
        self.box_color = el.box_color or ""
        self.box_opacity = float(el.box_opacity or 0.5)
        self.outline_color = el.outline_color or ""
        self.outline_width = int(el.outline_width or 0)
        self.shadow = bool(el.shadow)
        self.media_path = el.media_path or ""
        self.video_muted = bool(el.video_muted)
        self.video_loop = bool(el.video_loop)
        self.setZValue(int(el.z or 0))
        self.setPos(el.x * FRAME_W, el.y * FRAME_H)
        self.setRect(0.0, 0.0,
                     max(40.0, el.w * FRAME_W),
                     max(24.0, el.h * FRAME_H))
        self.reload_pixmap()

    def to_model(self) -> SlideElement:
        r = self.rect()
        p = self.pos()
        return SlideElement(
            id=self.el_id or SlideElement().id,
            kind=self.kind,
            x=round(max(0.0, p.x()) / FRAME_W, 4),
            y=round(max(0.0, p.y()) / FRAME_H, 4),
            w=round(r.width() / FRAME_W, 4),
            h=round(r.height() / FRAME_H, 4),
            z=int(self.zValue()),
            text=self.text,
            font_size=int(self.font_size),
            color=self.color,
            align=self.align,
            valign=self.valign,
            bold=bool(self.bold),
            italic=bool(self.italic),
            box_color=self.box_color,
            box_opacity=float(self.box_opacity),
            outline_color=self.outline_color,
            outline_width=int(self.outline_width),
            shadow=bool(self.shadow),
            media_path=self.media_path,
            video_muted=bool(self.video_muted),
            video_loop=bool(self.video_loop))

    def set_preview_pixmap(self, pm: Optional[QPixmap]) -> None:
        self._pixmap = pm if (pm and not pm.isNull()) else None
        self.update()

    def reload_pixmap(self) -> None:
        """(Re)load an image element's preview from its file. Video
        previews are set by the host (first-frame extraction)."""
        if self.kind == "image" and self.media_path:
            pm = QPixmap(self.media_path)
            self._pixmap = pm if not pm.isNull() else None
        elif self.kind != "video":
            self._pixmap = None
        self.update()

    # -- resize handles -----------------------------------------------
    def _handle_at(self, pos) -> Optional[str]:
        r = self.rect()
        h = self.HANDLE
        x, y = pos.x(), pos.y()
        left = abs(x - r.left()) <= h
        right = abs(x - r.right()) <= h
        top = abs(y - r.top()) <= h
        bottom = abs(y - r.bottom()) <= h
        if not (r.left() - h <= x <= r.right() + h
                and r.top() - h <= y <= r.bottom() + h):
            return None
        if top and left:
            return "tl"
        if top and right:
            return "tr"
        if bottom and left:
            return "bl"
        if bottom and right:
            return "br"
        if top:
            return "t"
        if bottom:
            return "b"
        if left:
            return "l"
        if right:
            return "r"
        return None

    def hoverMoveEvent(self, event) -> None:
        handle = self._handle_at(event.pos()) if self.isSelected() \
            else None
        self.setCursor(
            self._CURSORS[handle] if handle
            else Qt.CursorShape.SizeAllCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._active_handle = (
            self._handle_at(event.pos())
            if self.isSelected() else None)
        if self._active_handle:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._active_handle:
            self._resize(event)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was = self._active_handle is not None
        self._active_handle = None
        super().mouseReleaseEvent(event)
        if was:
            self._canvas._emit_changed()

    def _resize(self, event) -> None:
        r = QRectF(self.rect())
        lp = self.mapFromScene(event.scenePos())
        h = self._active_handle
        min_w, min_h = 60.0, 40.0
        left, top, right, bottom = (
            r.left(), r.top(), r.right(), r.bottom())
        if "l" in h:
            left = min(lp.x(), right - min_w)
        if "r" in h:
            right = max(lp.x(), left + min_w)
        if "t" in h:
            top = min(lp.y(), bottom - min_h)
        if "b" in h:
            bottom = max(lp.y(), top + min_h)
        new_local = QRectF(left, top, right - left, bottom - top)
        self.prepareGeometryChange()
        self.setPos(self.pos().x() + new_local.left(),
                    self.pos().y() + new_local.top())
        self.setRect(0.0, 0.0,
                     new_local.width(), new_local.height())
        self.update()

    def itemChange(self, change, value):
        if change == (QGraphicsItem.GraphicsItemChange
                      .ItemPositionHasChanged):
            self._canvas._emit_changed()
        return super().itemChange(change, value)

    # -- painting ------------------------------------------------------
    def paint(self, painter: QPainter, option, widget=None) -> None:
        r = self.rect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(
            QPainter.RenderHint.TextAntialiasing, True)
        if self.kind in ("image", "video"):
            self._paint_media(painter, r)
        else:
            self._paint_text(painter, r)
        if self.isSelected():
            self._paint_selection(painter, r)

    def _paint_media(self, painter, r) -> None:
        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                int(r.width()), int(r.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            ox = r.left() + (r.width() - scaled.width()) / 2
            oy = r.top() + (r.height() - scaled.height()) / 2
            painter.drawPixmap(int(ox), int(oy), scaled)
        else:
            painter.fillRect(r, QColor(40, 40, 48))
            painter.setPen(QColor("#888"))
            f = QFont()
            f.setPixelSize(28)
            painter.setFont(f)
            name = self.media_path.rsplit("/", 1)[-1] or "(no file)"
            painter.drawText(
                r, int(Qt.AlignmentFlag.AlignCenter
                       | Qt.TextFlag.TextWordWrap),
                ("🎞 " if self.kind == "video" else "🖼 ") + name)
        if self.kind == "video":
            # A play badge so it reads as motion, not a still.
            badge = 64.0
            cx, cy = r.center().x(), r.center().y()
            painter.setBrush(QColor(0, 0, 0, 140))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(
                QPointF(cx, cy), badge / 2, badge / 2)
            painter.setBrush(QColor("#FFFFFF"))
            tri = [
                QPointF(cx - badge * 0.16, cy - badge * 0.22),
                QPointF(cx - badge * 0.16, cy + badge * 0.22),
                QPointF(cx + badge * 0.26, cy)]
            painter.drawPolygon(*tri)

    def _paint_text(self, painter, r) -> None:
        if self.box_color:
            fill = _qcolor(self.box_color, "#000000")
            fill.setAlphaF(max(0.0, min(1.0, self.box_opacity)))
            painter.fillRect(r, fill)
        # While the inline editor is open, the QGraphicsTextItem draws
        # the glyphs — skip our own so it doesn't double up.
        if self._editing:
            return
        font = QFont()
        font.setPixelSize(max(6, int(self.font_size)))
        font.setBold(bool(self.bold))
        font.setItalic(bool(self.italic))
        painter.setFont(font)
        flags = Qt.TextFlag.TextWordWrap.value
        halign = {
            "left": Qt.AlignmentFlag.AlignLeft,
            "right": Qt.AlignmentFlag.AlignRight,
        }.get(self.align, Qt.AlignmentFlag.AlignHCenter)
        valign = {
            "top": Qt.AlignmentFlag.AlignTop,
            "bottom": Qt.AlignmentFlag.AlignBottom,
        }.get(self.valign, Qt.AlignmentFlag.AlignVCenter)
        align = int(halign | valign)
        text = self.text or ""
        if self.shadow:
            painter.setPen(QColor(0, 0, 0, 160))
            painter.drawText(r.translated(3, 3), align | flags, text)
        if self.outline_width > 0 and self.outline_color:
            painter.setPen(QPen(_qcolor(self.outline_color, "#000000")))
            ow = max(1, int(self.outline_width))
            for dx in (-ow, 0, ow):
                for dy in (-ow, 0, ow):
                    if dx or dy:
                        painter.drawText(
                            r.translated(dx, dy), align | flags, text)
        painter.setPen(_qcolor(self.color, "#FFFFFF"))
        painter.drawText(r, align | flags, text)

    def _paint_selection(self, painter, r) -> None:
        pen = QPen(QColor("#4C9AFF"))
        pen.setWidthF(3.0)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(r)
        painter.setPen(QPen(QColor("#4C9AFF")))
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        hs = 14.0
        for cx, cy in (
                (r.left(), r.top()), (r.right(), r.top()),
                (r.left(), r.bottom()), (r.right(), r.bottom()),
                ((r.left() + r.right()) / 2, r.top()),
                ((r.left() + r.right()) / 2, r.bottom()),
                (r.left(), (r.top() + r.bottom()) / 2),
                (r.right(), (r.top() + r.bottom()) / 2)):
            painter.drawRect(QRectF(cx - hs / 2, cy - hs / 2, hs, hs))

    def mouseDoubleClickEvent(self, event) -> None:
        self._canvas._request_edit(self)
        event.accept()


class _InlineTextEditorItem(QGraphicsTextItem):
    """A transient, editable text item shown over a text element so
    the writer can type directly on the preview. Commits on focus-out
    or Enter; Escape cancels."""

    def __init__(self, canvas: "SlideDesignCanvas", element) -> None:
        super().__init__()
        self._canvas = canvas
        self.element = element
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextEditorInteraction)
        self.document().setDocumentMargin(0)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._canvas._commit_inline_edit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._canvas._cancel_inline_edit()
            event.accept()
            return
        # Enter commits; Shift+Enter inserts a newline (multi-line).
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not (event.modifiers()
                         & Qt.KeyboardModifier.ShiftModifier)):
            self._canvas._commit_inline_edit()
            event.accept()
            return
        super().keyPressEvent(event)


class SlideDesignCanvas(QGraphicsView):
    """The design surface: a 16:9 frame with a color/image background
    plus draggable, resizable, layered elements. Accepts drops from an
    ``ElementPalette``."""

    changed = pyqtSignal()
    selectionChanged = pyqtSignal(object)   # ElementItem or None
    addMediaRequested = pyqtSignal(object)  # ElementItem needing a file

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(0, 0, FRAME_W, FRAME_H, self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setMinimumSize(560, 315)
        self.setAcceptDrops(True)
        self._bg_color = "#1e1e28"
        self._bg_pixmap: Optional[QPixmap] = None
        self._items: List[ElementItem] = []
        self._editor: Optional[_InlineTextEditorItem] = None
        self._scene.selectionChanged.connect(self._on_scene_selection)
        self.setBackgroundBrush(QBrush(QColor("#2b2b33")))

    # -- background ----------------------------------------------------
    def set_background(
        self, kind: str, color: str, media_path: str,
    ) -> None:
        self._bg_color = color or "#000000"
        self._bg_pixmap = None
        if kind in ("image", "video") and media_path:
            pm = QPixmap(media_path)
            if not pm.isNull():
                self._bg_pixmap = pm
        self.viewport().update()
        self._scene.update()

    def drawBackground(self, painter: QPainter, rect) -> None:
        super().drawBackground(painter, rect)
        frame = QRectF(0, 0, FRAME_W, FRAME_H)
        if self._bg_pixmap is not None and not self._bg_pixmap.isNull():
            scaled = self._bg_pixmap.scaled(
                FRAME_W, FRAME_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            sx = max(0, (scaled.width() - FRAME_W) // 2)
            sy = max(0, (scaled.height() - FRAME_H) // 2)
            painter.drawPixmap(
                frame, scaled, QRectF(sx, sy, FRAME_W, FRAME_H))
        else:
            painter.fillRect(frame, _qcolor(self._bg_color, "#000000"))

    # -- drag & drop ---------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(ELEMENT_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(ELEMENT_MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(ELEMENT_MIME):
            super().dropEvent(event)
            return
        kind = bytes(
            event.mimeData().data(ELEMENT_MIME)).decode("utf-8")
        scene_pt = self.mapToScene(event.position().toPoint())
        self.add_element(kind, at=scene_pt)
        event.acceptProposedAction()

    # -- elements ------------------------------------------------------
    def _next_z(self) -> int:
        return (max((int(i.zValue()) for i in self._items),
                    default=-1) + 1)

    def add_element(
        self, kind: str,
        at: Optional[QPointF] = None,
    ) -> ElementItem:
        """Create an element of ``kind`` (title/text/image/video). For
        image/video, emits ``addMediaRequested`` so the host can prompt
        for a file / recording."""
        el = self._default_element(kind)
        if at is not None:
            # Center the new element on the drop point.
            el.x = max(0.0, min(
                1.0 - el.w, at.x() / FRAME_W - el.w / 2))
            el.y = max(0.0, min(
                1.0 - el.h, at.y() / FRAME_H - el.h / 2))
        el.z = self._next_z()
        item = ElementItem(self)
        item.load(el)
        self._scene.addItem(item)
        self._items.append(item)
        item.setSelected(True)
        self._emit_changed()
        if kind in ("image", "video"):
            self.addMediaRequested.emit(item)
        return item

    @staticmethod
    def _default_element(kind: str) -> SlideElement:
        if kind == "title":
            return SlideElement(
                kind="text", text="Title", x=0.15, y=0.36,
                w=0.70, h=0.18, font_size=110, bold=True,
                color="#FFFFFF")
        if kind == "text":
            return SlideElement(
                kind="text", text="Text", x=0.20, y=0.44,
                w=0.60, h=0.14, font_size=54, color="#FFFFFF")
        if kind == "image":
            return SlideElement(
                kind="image", x=0.30, y=0.30, w=0.40, h=0.40)
        if kind == "video":
            return SlideElement(
                kind="video", x=0.28, y=0.26, w=0.44, h=0.44)
        return SlideElement(kind="text", text="Text")

    def delete_selected(self) -> None:
        for item in list(self._scene.selectedItems()):
            if isinstance(item, ElementItem):
                self._scene.removeItem(item)
                if item in self._items:
                    self._items.remove(item)
        self._renumber_z()
        self._emit_changed()
        self.selectionChanged.emit(self.selected())

    def raise_selected(self) -> None:
        self._reorder(+1)

    def lower_selected(self) -> None:
        self._reorder(-1)

    def _reorder(self, direction: int) -> None:
        item = self.selected()
        if item is None:
            return
        ordered = sorted(self._items, key=lambda i: i.zValue())
        idx = ordered.index(item)
        swap = idx + direction
        if 0 <= swap < len(ordered):
            other = ordered[swap]
            zi, zo = item.zValue(), other.zValue()
            item.setZValue(zo)
            other.setZValue(zi)
            self._renumber_z()
            self._emit_changed()

    def _renumber_z(self) -> None:
        for i, item in enumerate(
                sorted(self._items, key=lambda it: it.zValue())):
            item.setZValue(i)

    def selected(self) -> Optional[ElementItem]:
        for item in self._scene.selectedItems():
            if isinstance(item, ElementItem):
                return item
        return None

    def elements_bottom_to_top(self) -> List[ElementItem]:
        return sorted(self._items, key=lambda i: i.zValue())

    # -- card round-trip ----------------------------------------------
    def load_card(self, card) -> None:
        for item in list(self._items):
            self._scene.removeItem(item)
        self._items.clear()
        for el in sorted(
                (getattr(card, "elements", None) or []),
                key=lambda e: getattr(e, "z", 0)):
            item = ElementItem(self)
            item.load(el)
            self._scene.addItem(item)
            self._items.append(item)
        self._renumber_z()
        self.set_background(
            getattr(card, "kind", "color") or "color",
            getattr(card, "bg_color", "#000000") or "#000000",
            getattr(card, "bg_media_path", "") or "")

    def apply_to_card(self, card) -> None:
        # Flush any in-progress inline edit so its text is captured.
        if self._editor is not None:
            self._commit_inline_edit()
        card.elements = [
            item.to_model()
            for item in self.elements_bottom_to_top()]

    # -- internals -----------------------------------------------------
    def _emit_changed(self) -> None:
        self.changed.emit()

    def _on_scene_selection(self) -> None:
        self.selectionChanged.emit(self.selected())

    def _request_edit(self, item: ElementItem) -> None:
        if item.kind in ("image", "video"):
            self.addMediaRequested.emit(item)
        else:
            self.start_inline_edit(item)

    # -- inline text editing ------------------------------------------
    def start_inline_edit(self, item: ElementItem) -> None:
        """Open a caret-driven editor directly over ``item`` so the
        writer types on the preview. No-op for non-text elements."""
        if item is None or item.kind != "text":
            return
        if self._editor is not None:
            self._commit_inline_edit()
        editor = _InlineTextEditorItem(self, item)
        f = QFont()
        f.setPixelSize(max(6, int(item.font_size)))
        f.setBold(bool(item.bold))
        f.setItalic(bool(item.italic))
        editor.setFont(f)
        editor.setDefaultTextColor(_qcolor(item.color, "#FFFFFF"))
        editor.setPlainText(item.text or "")
        editor.setTextWidth(max(20.0, item.rect().width()))
        opt = editor.document().defaultTextOption()
        opt.setAlignment({
            "left": Qt.AlignmentFlag.AlignLeft,
            "right": Qt.AlignmentFlag.AlignRight,
        }.get(item.align, Qt.AlignmentFlag.AlignHCenter))
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        editor.document().setDefaultTextOption(opt)
        editor.setPos(item.pos())
        editor.setZValue(100000)
        self._scene.addItem(editor)
        self._editor = editor
        item._editing = True
        item.update()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)
        cur = editor.textCursor()
        cur.select(QTextCursor.SelectionType.Document)
        editor.setTextCursor(cur)

    def _finish_inline_edit(self, commit: bool) -> None:
        editor = self._editor
        if editor is None:
            return
        item = editor.element
        self._editor = None            # guard re-entry from focus-out
        if commit and item is not None:
            item.text = editor.toPlainText()
        if item is not None:
            item._editing = False
            item.update()
        self._scene.removeItem(editor)
        if commit:
            self._emit_changed()
            # Refresh the side panel's Text field from the item.
            self.selectionChanged.emit(self.selected())

    def _commit_inline_edit(self) -> None:
        self._finish_inline_edit(commit=True)

    def _cancel_inline_edit(self) -> None:
        self._finish_inline_edit(commit=False)

    def keyPressEvent(self, event) -> None:
        # While an inline text editor is open, every key — Backspace,
        # Delete, arrows — belongs to the text editor. Only hijack
        # Delete/Backspace to remove the selected element when NOT
        # editing text.
        if self._editor is None and event.key() in (
                Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fitInView(
            self._scene.sceneRect(),
            Qt.AspectRatioMode.KeepAspectRatio)
