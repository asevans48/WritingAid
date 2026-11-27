"""Shared interface parts (piece U.1).

One place for what every screen needs, so screens look and behave the same
and new ones are cheaper to build:

* **Fitting the screen:** ``fit_to_screen`` opens a window no larger than
  the screen it is on; ``remember_geometry`` brings it back where it was
  (size, position and screen), or onto a visible screen if that monitor is
  gone; ``size_class`` says whether a window is narrow, normal or wide.
* **Scrolling:** ``scrollable`` wraps content in a scroll area the standard
  way, so nothing is squeezed; ``scroll_dialog`` does it to a built dialog,
  keeping its buttons below the scroll area (U.3b).
* **Narrow rows (U.3a, U.3b):** ``FlowLayout`` (a row that switches to
  the short words given with ``short_label``, then wraps), ``ElidedLabel``
  (a title that shortens with …) and ``grow_with_text``.
* **Parts:** ``CollapsibleSection`` (moved here from the Companion, still
  importable there), ``card``, ``status_chip``, ``section_header``,
  ``primary_button`` and ``empty_state``.
* **One look (D.8):** ``plain`` / ``plain_qss`` for every other button,
  ``PRIMARY_BUTTON`` for an existing main button, ``text_style`` for a
  label's colour and size, and the spacing ``GAP``, ``PANEL_MARGIN`` and
  ``DIALOG_MARGIN``.
* **Colours:** ``PALETTE`` (from ``styles.COLORS``), ``PROBLEM_COLOURS``
  (one colour per kind of problem, from ``style_checks.KINDS`` and the
  editor's flag colours) and ``STAGE_COLOURS``.

Nothing here sets a fixed height on anything that holds text, so layouts
hold up at 150% and 200% text scaling.
"""

from __future__ import annotations

from typing import Dict, Optional

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, QSettings, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QFrame, QLabel, QLayout, QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout,
    QWidget,
)

from src.ui.styles import COLORS

# ── Colours ─────────────────────────────────────────────────────────────

PALETTE: Dict[str, str] = COLORS

# The editor's colour for each family of flag (spelling, grammar, ...).
# ``ErrorCard.COLORS`` in enhanced_text_editor.py points here.
FLAG_COLOURS: Dict[str, str] = {
    "spelling": "#dc2626",
    "grammar": "#16a34a",
    "overuse": "#2563eb",
    "overused_phrase": "#7c3aed",
    "style": "#d97706",
}


def _style_kind_colours() -> Dict[str, str]:
    try:
        from src.utils.style_checks import KINDS
        return {kind: colour for kind, (_label, colour, _sentence) in KINDS.items()}
    except Exception:                       # never let a colour lookup break a screen
        return {}


# One colour per kind of problem, everywhere: the editor's flag families plus
# each style check's own colour.
PROBLEM_COLOURS: Dict[str, str] = {**FLAG_COLOURS, **_style_kind_colours()}

# The revision stages (Structure › Scene › Line › Copyedit › Proof), coloured
# from the existing palette. Change them here and every screen follows.
STAGE_COLOURS: Dict[str, str] = {
    "structure": COLORS["primary"],
    "scene": COLORS["info"],
    "line": COLORS["warning"],
    "copyedit": COLORS["success"],
    "proof": COLORS["accent"],
}


# Hues beyond the palette for charts and kinds that must stay apart (a
# faction's type, an economy's type, a timeline event's kind). Each screen
# that colours categories takes them from PALETTE or here, never by hand.
CHART_COLOURS: Dict[str, str] = {
    "teal": "#14b8a6", "orange": "#f97316", "gold": "#ca8a04", "violet": "#7c3aed",
    "zinc": "#71717a", "light_green": "#22c55e",
}

# The planner's story-arc stages (Freytag), used by its arc drawing and its
# beat list alike.
ARC_COLOURS: Dict[str, str] = {
    "exposition": COLORS["info"], "rising": CHART_COLOURS["light_green"], "climax": COLORS["error"],
    "falling": CHART_COLOURS["orange"], "resolution": COLORS["violet"],
}


def colour_for(kind: str, default: Optional[str] = None) -> str:
    """The colour for a kind of problem, a stage, or a semantic name
    ("success", "warning", ...)."""
    key = (kind or "").lower()
    return (PROBLEM_COLOURS.get(key) or STAGE_COLOURS.get(key) or COLORS.get(key)
            or default or COLORS["ink_faint"])


# ── Fitting the screen ──────────────────────────────────────────────────

def _screen_for(window: QWidget):
    screen = window.screen() if hasattr(window, "screen") else None
    return screen or QGuiApplication.primaryScreen()


def fit_to_screen(window: QWidget, width: int, height: int, *,
                  min_width: int = 480, min_height: int = 360,
                  margin_x: int = 40, margin_y: int = 60) -> QSize:
    """Resize ``window`` to ``width`` × ``height``, but no larger than the
    screen it is on (less a margin) and no smaller than the minimum."""
    screen = _screen_for(window)
    if screen is not None:
        avail = screen.availableGeometry()
        width = min(width, avail.width() - margin_x)
        height = min(height, avail.height() - margin_y)
    size = QSize(max(width, min_width), max(height, min_height))
    window.resize(size)
    return size


def size_class(widget: QWidget) -> str:
    """"narrow" (under 1,200 px wide), "normal", or "wide" (2,000 px and
    up), from the width of the widget's window."""
    width = widget.window().width() if widget is not None else 0
    if width < 1200:
        return "narrow"
    if width >= 2000:
        return "wide"
    return "normal"


def _settings() -> QSettings:
    """Where window positions are kept. Tests redirect this."""
    return QSettings("WritingAid", "WindowGeometry")


def _visible_rect(rect: QRect, screen_name: str) -> Optional[QRect]:
    """``rect`` if most of its title bar lands on a connected screen
    (preferring the one it was saved on), else None."""
    screens = QGuiApplication.screens()
    ordered = ([s for s in screens if s.name() == screen_name]
               + [s for s in screens if s.name() != screen_name])
    title_bar = QRect(rect.x(), rect.y(), rect.width(), 40)
    for screen in ordered:
        avail = screen.availableGeometry()
        overlap = avail.intersected(title_bar)
        if overlap.width() * overlap.height() >= title_bar.width() * title_bar.height() // 3:
            return rect
    return None


class _GeometryKeeper(QObject):
    def __init__(self, window: QWidget, key: str):
        super().__init__(window)
        self.window, self.key = window, key

    def eventFilter(self, obj, event) -> bool:
        if obj is self.window and event.type() in (QEvent.Type.Close, QEvent.Type.Hide):
            save_geometry(self.window, self.key)
        return False


def save_geometry(window: QWidget, key: str) -> None:
    """Record the window's size, position and screen under ``key``."""
    try:
        # Position of the frame (what move() takes), size of the contents
        # (what resize() takes), so the window comes back exactly.
        pos, size = window.pos(), window.size()
        screen = window.screen()
        s = _settings()
        s.setValue(f"{key}/rect", [pos.x(), pos.y(), size.width(), size.height()])
        s.setValue(f"{key}/screen", screen.name() if screen is not None else "")
        s.sync()
    except Exception as e:                  # window state must never break a close
        print(f"[ui_kit] could not save window position: {e}")


def remember_geometry(window: QWidget, key: str, default_size: Optional[QSize] = None) -> bool:
    """Bring ``window`` back to its last size, position and screen, and keep
    recording them when it closes. If its monitor is gone, or nothing was
    saved, it is fitted to the current screen instead (``default_size``, or
    its present size). Returns True when a saved position was used."""
    restored = False
    try:
        s = _settings()
        raw = s.value(f"{key}/rect")
        screen_name = s.value(f"{key}/screen", "") or ""
        if raw:
            x, y, w, h = (int(v) for v in raw)
            rect = _visible_rect(QRect(x, y, w, h), str(screen_name))
            if rect is not None:
                screen = next((sc for sc in QGuiApplication.screens()
                               if sc.availableGeometry().intersects(rect)), None)
                if screen is not None:
                    avail = screen.availableGeometry()
                    w, h = min(w, avail.width()), min(h, avail.height())
                window.resize(w, h)
                window.move(QPoint(x, y))
                restored = True
    except Exception as e:                  # a bad saved value means "not saved"
        print(f"[ui_kit] could not restore window position: {e}")
    if not restored:
        size = default_size or window.size()
        fit_to_screen(window, size.width(), size.height())
        screen = _screen_for(window)
        if screen is not None:
            centre = screen.availableGeometry().center()
            window.move(centre.x() - window.width() // 2, centre.y() - window.height() // 2)
    window.installEventFilter(_GeometryKeeper(window, key))
    return restored


# ── Scrolling ───────────────────────────────────────────────────────────

def scrollable(content: QWidget, *, frame: bool = False) -> QScrollArea:
    """``content`` in a scroll area that resizes with it and shows bars only
    when needed."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    if not frame:
        area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setWidget(content)
    return area


def _is_button_row(item) -> bool:
    """A dialog's closing row: a button box, or a horizontal row of buttons
    (with perhaps a label or a small choice beside them, as "Export for: ▾")."""
    from PyQt6.QtWidgets import (
        QAbstractButton, QAbstractSpinBox, QBoxLayout, QComboBox, QDialogButtonBox,
    )
    if isinstance(item.widget(), QDialogButtonBox):
        return True
    small = (QAbstractButton, QDialogButtonBox, QLabel, QComboBox, QAbstractSpinBox)

    def row(lay) -> Optional[bool]:            # None: not a row; else: holds a button
        if not isinstance(lay, QBoxLayout) or lay.direction() not in (
                QBoxLayout.Direction.LeftToRight, QBoxLayout.Direction.RightToLeft):
            return None
        found = False
        for i in range(lay.count()):
            k = lay.itemAt(i)
            if k.spacerItem() is not None:
                continue
            if k.layout() is not None:
                inner = row(k.layout())
                if inner is None:
                    return None
                found = found or inner
            elif isinstance(k.widget(), small):
                found = found or isinstance(k.widget(), (QAbstractButton, QDialogButtonBox))
            else:
                return None
        return found

    return bool(item.layout() is not None and row(item.layout()))


def scroll_dialog(dialog: QWidget, width: Optional[int] = None,
                  height: Optional[int] = None) -> QScrollArea:
    """Call after a dialog (or a ``QMainWindow``: its central widget) is
    built: its contents go into a scroll area, its
    closing row of buttons (OK, Cancel, Save…) stays below it, always on
    screen, and it opens no larger than the screen (``fit_to_screen``, at
    ``width`` × ``height`` or the size it had). For a dialog taller than a
    small screen (U.3b). Nothing in it changes but where it scrolls."""
    from PyQt6.QtWidgets import QBoxLayout, QMainWindow
    want = QSize(width or dialog.width(), height or dialog.height())
    if isinstance(dialog, QMainWindow):                # a window: its centre scrolls
        area = scrollable(dialog.takeCentralWidget())
        dialog.setCentralWidget(area)
        _fit_least(dialog, want)
        return area
    outer = dialog.layout()
    items, stretches = [], []
    for i in range(outer.count()):
        stretches.append(outer.stretch(i) if isinstance(outer, QBoxLayout) else 0)
    while outer.count():
        items.append(outer.takeAt(0))
    stretches = stretches[:len(items)]
    tail = []
    while items and (_is_button_row(items[-1]) or (tail and items[-1].spacerItem() is not None)):
        tail.insert(0, (items.pop(), stretches.pop()))
    body = QWidget()
    inner = QVBoxLayout(body)
    m = outer.contentsMargins()
    inner.setContentsMargins(m)
    inner.setSpacing(outer.spacing())
    outer.setContentsMargins(0, 0, 0, m.bottom())
    for item, stretch in zip(items, stretches):
        if item.widget() is not None:
            inner.addWidget(item.widget(), stretch)
        elif item.layout() is not None:
            lay = item.layout()
            lay.setParent(None)
            inner.addLayout(lay, stretch)
        else:
            inner.addItem(item)
    area = scrollable(body)
    outer.addWidget(area, 1)
    for item, stretch in tail:
        if item.widget() is not None:
            outer.addWidget(item.widget(), stretch)
        elif item.layout() is not None:
            lay = item.layout()
            lay.setParent(None)
            lay.setContentsMargins(m.left(), 0, m.right(), 0)
            outer.addLayout(lay, stretch)
        else:
            outer.addItem(item)
    _fit_least(dialog, want)
    return area


def _fit_least(window: QWidget, want: QSize) -> None:
    least = window.minimumSize()
    window.setMinimumSize(min(least.width(), 480), min(least.height(), 360))
    fit_to_screen(window, want.width(), want.height(), min_width=min(480, want.width()),
                  min_height=min(360, want.height()))


# ── Parts ───────────────────────────────────────────────────────────────

class CollapsibleSection(QWidget):
    """A section that opens and closes from its header, and remembers which
    (the owner records ``toggled(key, collapsed)``)."""
    toggled = pyqtSignal(str, bool)          # key, collapsed

    def __init__(self, title: str, key: str, parent=None):
        super().__init__(parent)
        self.key, self.title = key, title
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(0)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.header = QPushButton()
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setToolTip("Click to open or close")
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.setStyleSheet(
            "QPushButton { text-align: left; border: none; border-radius: 4px;"
            f" background: {COLORS['surface_muted']}; color: {COLORS['ink']};"
            " font-weight: bold; font-size: 11px;"
            " padding: 5px 8px; min-height: 0; }"
            f"QPushButton:hover, QPushButton:checked:hover {{ background: {COLORS['surface_hover']}; }}"
            f"QPushButton:checked {{ background: {COLORS['primary_tint']};"
            f" color: {COLORS['primary_ink']}; }}")
        self.header.toggled.connect(self._on_toggled)
        outer.addWidget(self.header)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(6, 4, 2, 6)
        outer.addWidget(self.body)
        self._count = ""
        self._label()

    def _label(self):
        arrow = "▾" if self.header.isChecked() else "▸"
        self.header.setText(f"{arrow}  {self.title}{self._count}")

    def set_count(self, n: Optional[int]) -> None:
        self._count = f"  ({n})" if n else ""
        self._label()

    def is_open(self) -> bool:
        return self.header.isChecked()

    def set_open(self, is_open: bool, *, quiet: bool = True) -> None:
        if quiet:
            self.header.blockSignals(True)
        self.header.setChecked(is_open)
        self._show_body(is_open)
        if quiet:
            self.header.blockSignals(False)

    def _show_body(self, is_open: bool) -> None:
        self.body.setVisible(is_open)
        self._label()
        # Closed sections shrink to their header right away.
        self.updateGeometry()
        parent = self.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().invalidate()
            parent.layout().activate()
            parent.adjustSize()

    def _on_toggled(self, is_open: bool):
        self._show_body(is_open)
        self.toggled.emit(self.key, not is_open)


def section_header(text: str) -> QLabel:
    """A small capitalised label that heads a group ("THIS CHAPTER")."""
    label = QLabel(text)
    label.setStyleSheet(f"color: {COLORS['ink_faint']}; font-size: 10px; font-weight: bold; "
                        "letter-spacing: 1px; padding: 8px 2px 2px 2px;")
    return label


def card(parent: Optional[QWidget] = None) -> QFrame:
    """A bordered card with a vertical layout (``card.layout()``)."""
    frame = QFrame(parent)
    frame.setObjectName("uiCard")
    frame.setStyleSheet(
        f"QFrame#uiCard {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']};"
        " border-radius: 6px; }")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(6)
    return frame


def status_chip(text: str, kind: str = "") -> QLabel:
    """A small rounded label coloured for a kind of problem, a stage or a
    semantic name."""
    colour = colour_for(kind)
    chip = QLabel(text)
    chip.setStyleSheet(
        f"QLabel {{ color: {colour}; border: 1px solid {colour}; border-radius: 8px;"
        " padding: 1px 7px; font-size: 10px; font-weight: bold; }")
    chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
    return chip


PRIMARY_BUTTON = (
    f"QPushButton {{ background: {COLORS['primary']}; color: white; font-weight: bold;"
    " border: none; border-radius: 5px; padding: 6px 14px; }"
    f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
    f"QPushButton:disabled {{ background: {COLORS['primary_light']}; }}")


def make_main(btn, pad: str = "8px 16px", size: Optional[int] = None, bold: bool = False):
    """Colour an existing button as the screen's main action. ``pad`` is
    the padding of the plain button it was (border included), and the text
    keeps the app-wide weight unless ``bold``, so it keeps its size and its
    words are never cut off; the default fits a button with the app-wide
    style. Unlike ``primary_button`` it does not make the button a dialog's
    default, so Enter does what it did before."""
    extra = (f" font-size: {size}px;" if size else "") + ("" if bold else " font-weight: 500;")
    btn.setStyleSheet(PRIMARY_BUTTON + f"QPushButton {{ padding: {pad};{extra} }}")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def main_button(text: str, parent: Optional[QWidget] = None, **kw) -> QPushButton:
    """``QPushButton(text)`` coloured as the screen's main action, the same
    size as a plain one (``make_main``)."""
    return make_main(QPushButton(text, parent), **kw)


def primary_button(text: str, parent: Optional[QWidget] = None) -> QPushButton:
    """The one main action on a screen, in the app's accent colour."""
    btn = QPushButton(text, parent)
    btn.setDefault(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(PRIMARY_BUTTON)
    return btn


# ── One look (D.8) ──────────────────────────────────────────────────────

# Spacing: the same margins and gaps inside panels and dialogs.
GAP = 6                 # between controls in a row or column
PANEL_MARGIN = 8        # inside side panels and cards
DIALOG_MARGIN = 12      # inside dialogs


def text_style(tone: str = "ink_faint", size: Optional[int] = None, *,
               bold: bool = False, italic: bool = False, extra: str = "") -> str:
    """A label's style sheet from the palette: ``tone`` is a ``PALETTE``
    name (or "" for the default text colour)."""
    parts = [f"color: {COLORS[tone]};" if tone else ""]
    if size:
        parts.append(f"font-size: {size}px;")
    if bold:
        parts.append("font-weight: bold;")
    if italic:
        parts.append("font-style: italic;")
    return " ".join(p for p in parts + [extra] if p)


def plain_qss(selector: str = "QPushButton", size: int = 11, pad: str = "3px 8px",
              bold: bool = False) -> str:
    """Every button that is not the screen's main action: white, a thin
    border, the palette's text colour; a checked toggle shows the tint.
    ``pad`` includes the 1 px border, so a borderless button keeps its size."""
    c, weight = COLORS, "bold" if bold else "normal"
    inner = " ".join(f"{max(int(p.rstrip('px') or 0) - 1, 0)}px" for p in pad.split())
    return (f"{selector} {{ background: {c['surface']}; color: {c['ink']}; font-weight: {weight};"
            f" border: 1px solid {c['border_strong']}; border-radius: 4px; padding: {inner};"
            f" font-size: {size}px; }}"
            f"{selector}:hover {{ background: {c['surface_hover']}; }}"
            f"{selector}:checked {{ background: {c['primary_tint']}; color: {c['primary_ink']};"
            f" border-color: {c['primary_border']}; }}"
            f"{selector}:disabled {{ background: {c['surface_muted']}; color: {c['ink_disabled']}; }}"
            f"{selector}::menu-indicator {{ image: none; }}")


def plain(btn, size: int = 11, pad: str = "3px 8px", bold: bool = False):
    """Style an existing button or tool button as a plain one (keeps its
    size, text, object name and default-button state)."""
    selector = "QToolButton" if isinstance(btn, QToolButton) else "QPushButton"
    btn.setStyleSheet(plain_qss(selector, size, pad, bold))
    return btn


def relayout(widget: QWidget) -> None:
    """Tell every container above ``widget`` that its size changed, up to
    a scroll area's page, which is resized to fit. (A widget that grows
    after results arrive was otherwise drawn over what follows it.)"""
    w = widget
    while w is not None:
        w.updateGeometry()
        if w.layout() is not None:
            w.layout().invalidate()
            w.layout().activate()
        parent = w.parentWidget()
        area = parent.parentWidget() if parent is not None else None
        if (isinstance(area, QScrollArea) and area.widget() is w) or \
                (isinstance(parent, QScrollArea) and parent.widget() is w):
            # The scroll area's page: grow (or shrink) its height to fit;
            # the width stays the scroll area's.
            need = max(w.minimumSizeHint().height(), w.minimumHeight())
            if w.height() != need and (w.height() < need or not (
                    isinstance(area, QScrollArea) and area.widgetResizable())):
                w.resize(w.width(), need)
            break
        w = parent


def compact_button(btn: QPushButton) -> QPushButton:
    """A narrow button that shows its symbol. The app's style gives every
    push button 16 px of padding each side, which leaves a 20–40 px button
    blank; this drops the side padding on this button only. Call it after
    the button's own ``setStyleSheet``."""
    rule = "padding-left: 0px; padding-right: 0px; min-width: 0px;"
    sheet = btn.styleSheet() or ""
    if rule in sheet:
        return btn
    if "{" in sheet:                         # selector rules: add one more, last wins
        sheet = sheet.rstrip() + "\nQPushButton { " + rule + " }"
    else:                                     # bare declarations (or none)
        sheet = (sheet.rstrip().rstrip(";") + "; " if sheet.strip() else "") + rule
    btn.setStyleSheet(sheet)
    return btn


class _GrowWithText(QObject):
    def __init__(self, edit, max_lines: int):
        super().__init__(edit)
        self.edit, self.max_lines, self._busy = edit, max_lines, False
        edit.document().contentsChanged.connect(self.fit)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.edit and event.type() in (
                QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.FontChange,
                QEvent.Type.StyleChange, QEvent.Type.Polish):
            self.fit()
        return False

    def fit(self) -> None:
        e = self.edit
        chrome = e.height() - e.viewport().height()          # frame and padding
        if self._busy or not e.isVisible() or chrome < 0:     # measured once laid out
            return
        self._busy = True
        try:
            doc = e.document()
            doc.setTextWidth(max(1, e.viewport().width()))
            most = e.fontMetrics().lineSpacing() * self.max_lines + 2 * doc.documentMargin()
            height = int(min(doc.size().height(), most) + chrome + 0.999)
            if e.minimumHeight() != height or e.maximumHeight() != height:
                e.setFixedHeight(height)
        finally:
            self._busy = False


def grow_with_text(edit, max_lines: int = 3):
    """A short text box (a title) as tall as its text, from one line up to
    ``max_lines``, then it scrolls: no fixed pixel height, so it holds up
    at 150% and a long title wraps instead of hiding (U.3a)."""
    keeper = _GrowWithText(edit, max_lines)
    edit.installEventFilter(keeper)
    edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    keeper.fit()
    return edit


# ── Narrow rows: shorter words, then wrap (U.3b) ────────────────────────

_SHORT, _FULL = "ui_kit_short_text", "ui_kit_full_text"


def short_label(widget, short: str):
    """Give a button (or a check box or a label) in a ``FlowLayout`` row
    shorter words for when the row lacks room (the writer's rule, 26 Nov:
    shorten, then wrap). Keep its icon in ``short``. The row switches its
    items to their short words before it wraps, and back when there is room
    again, so at full width the button reads exactly as before; while
    short, its full name heads its tooltip. Look such a button up with
    ``full_text``, not ``text``. Not for a button whose words the code
    changes as it goes."""
    widget.setProperty(_FULL, widget.text())
    widget.setProperty(_SHORT, short)
    return widget


def full_text(widget) -> str:
    """A widget's words at full width (its ``text()`` unless a narrow row
    has switched it to the short words given with ``short_label``)."""
    full, short = widget.property(_FULL), widget.property(_SHORT)
    if full and short is not None and widget.text() == short:
        return full
    return widget.text()


def _is_short(widget) -> bool:
    return widget.property(_SHORT) is not None and widget.text() == widget.property(_SHORT) \
        and widget.text() != widget.property(_FULL)


def _set_short(widget, short: bool) -> bool:
    """Switch one widget's words; True when its text changed."""
    full, words = widget.property(_FULL), widget.property(_SHORT)
    text = widget.text()
    if text not in (full, words):                 # the code gave it new words: those are full
        widget.setProperty(_FULL, text)
        full = text
    if short == _is_short(widget):
        return False
    tip = widget.toolTip() or ""
    if short:
        widget.setText(words)
        if not tip:
            widget.setToolTip(full)
        elif not tip.startswith(full):
            widget.setToolTip(f"{full}\n{tip}")
    else:
        widget.setText(full)
        if tip == full:
            widget.setToolTip("")
        elif tip.startswith(full + "\n"):
            widget.setToolTip(tip[len(full) + 1:])
    return True


def _contents_width(widget, text: str) -> int:
    """What a widget's contents need for ``text`` (a push button as Qt
    sizes it, so the style's least width is counted)."""
    fm = widget.fontMetrics()
    if isinstance(widget, QPushButton):
        from PyQt6.QtWidgets import QStyle, QStyleOptionButton
        opt = QStyleOptionButton()
        widget.initStyleOption(opt)
        w = h = 0
        if not widget.icon().isNull():
            w, h = opt.iconSize.width() + 4, opt.iconSize.height()
        size = fm.size(int(Qt.TextFlag.TextShowMnemonic), text or "XXXX")
        if text or not w:
            w += size.width()
        if text or not h:
            h = max(h, size.height())
        opt.text = text
        opt.rect.setSize(QSize(w, h))
        if widget.menu() is not None:
            w += widget.style().pixelMetric(QStyle.PixelMetric.PM_MenuButtonIndicator, opt, widget)
        return widget.style().sizeFromContents(
            QStyle.ContentsType.CT_PushButton, opt, QSize(w, h), widget).width()
    return fm.size(int(Qt.TextFlag.TextShowMnemonic), text).width()


def _is_separator(widget) -> bool:
    return isinstance(widget, QFrame) and type(widget) is QFrame \
        and widget.frameShape() == QFrame.Shape.VLine


def _names_next(item) -> bool:
    """A short label ending in a colon names the item after it."""
    w = item.widget()
    return isinstance(w, QLabel) and not w.wordWrap() and w.text().rstrip().endswith(":") \
        and len(w.text()) <= 24


def _is_gap(item) -> bool:
    """A divider or a fixed space between groups: left out where a row wraps."""
    return item.spacerItem() is not None or _is_separator(item.widget())


class FlowLayout(QLayout):
    """A row that wraps onto the next line when the room is short, instead
    of making its panel wider (U.3a). Before it wraps, the items given
    shorter words with ``short_label`` switch to them (U.3b); at full width
    they read as before. A drop-in for a ``QHBoxLayout`` of widgets:
    ``addWidget(w, stretch)`` (a stretching item takes the rest of its
    line), ``addStretch`` (nothing: the row is left-aligned), and a
    vertical line between groups is left out where a line wraps. An item
    wider than the row is narrowed to it (an ``ElidedLabel`` elides).
    No ``addLayout``."""

    def __init__(self, parent: Optional[QWidget] = None, spacing: int = GAP):
        super().__init__(parent)
        self._items = []
        self._stretch = {}
        self._seen = {}
        self._gap = spacing
        self._asked = None
        self._width = 0
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def addWidget(self, widget, stretch: int = 0, alignment=None) -> None:   # noqa: N802
        super().addWidget(widget)
        if stretch:
            self._stretch[id(widget)] = stretch

    def addStretch(self, stretch: int = 0) -> None:      # noqa: N802 — as QHBoxLayout's
        return None

    def addSpacing(self, size: int) -> None:             # noqa: N802 — left out at a wrap
        from PyQt6.QtWidgets import QSpacerItem
        self.addItem(QSpacerItem(size, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
        self.invalidate()

    def insertWidget(self, index: int, widget, stretch: int = 0) -> None:   # noqa: N802
        from PyQt6.QtWidgets import QWidgetItem
        self.addChildWidget(widget)
        self._items.insert(max(0, min(index, len(self._items))), QWidgetItem(widget))
        if stretch:
            self._stretch[id(widget)] = stretch
        self.invalidate()

    def setSpacing(self, spacing: int) -> None:          # noqa: N802
        self._gap = spacing
        self.invalidate()

    def spacing(self) -> int:
        return self._gap

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        if not 0 <= index < len(self._items):
            return None
        item = self._items.pop(index)
        if item.widget() is not None:
            self._stretch.pop(id(item.widget()), None)
        return item

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        # No: parents with height-for-width share height by size hints and
        # squeeze headers. The wrapped height is in sizeHint and
        # minimumSize instead, at the width the row has (see setGeometry).
        return False

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._width = rect.width()
        self._fit_words(rect)
        height = self._arrange(rect, move=True)
        key = (rect.width(), rect.height(), height)
        if height != rect.height() and key != self._asked:   # wrapped onto more (or fewer)
            self._asked = key                                 # lines: ask the parents once
            from PyQt6.QtCore import QTimer                   # for that height
            QTimer.singleShot(0, self._grow)

    def _grow(self) -> None:
        try:
            self.invalidate()
            parent = self.parentWidget()
            if parent is not None:
                relayout(parent)
        except RuntimeError:                       # deleted meanwhile
            pass

    # Words: full, or short when the row does not fit on one line.

    def _shortenable(self):
        return [i.widget() for i in self._visible()
                if i.widget() is not None and i.widget().property(_SHORT) is not None]

    def _item_width(self, item, short: Optional[bool] = None) -> int:
        """An item's width with its full (``short=False``) or short words
        (``None``: as it is now)."""
        width = item.sizeHint().width()
        w = item.widget()
        if w is None or w.property(_SHORT) is None:
            return width
        seen = self._seen.setdefault(id(w), {})        # measured widths, by words and font
        seen[(w.text(), w.font().key())] = width
        if short is None or short == _is_short(w):
            return width
        target = w.property(_SHORT) if short else (w.property(_FULL) or w.text())
        if (target, w.font().key()) in seen:
            return seen[(target, w.font().key())]
        width += _contents_width(w, target) - _contents_width(w, w.text())
        return max(w.minimumWidth(), min(width, w.maximumWidth()))

    def _one_line(self, short: Optional[bool]) -> int:
        items = self._visible()
        return sum(self._item_width(i, short) for i in items) + self._gap * max(0, len(items) - 1)

    def _fit_words(self, rect: QRect) -> None:
        widgets = self._shortenable()
        if not widgets or rect.width() <= 0:
            return
        m = self.contentsMargins()
        room = rect.width() - m.left() - m.right()
        short = self._one_line(False) > room
        changed = [w for w in widgets if _set_short(w, short)]
        if changed:
            for item in self._visible():
                item.invalidate()

    def _wrapped_height(self) -> int:
        """The height at the width it was last given (one line before it is
        laid out; ``invalidate`` clears ``geometry()``, so it is kept)."""
        width = self._width
        return self.heightForWidth(width) if width > 0 else 0

    def sizeHint(self) -> QSize:
        height = 0
        for item in self._visible():
            height = max(height, item.sizeHint().height())
        m = self.contentsMargins()
        return QSize(self._one_line(False) + m.left() + m.right(),
                     max(height + m.top() + m.bottom(), self._wrapped_height()))

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._visible():
            least = item.minimumSize()
            if item.widget() is not None and item.widget().property(_SHORT) is not None:
                least.setWidth(min(least.width(), self._item_width(item, True)))
            size = size.expandedTo(least)
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return QSize(size.width(), max(size.height(), self._wrapped_height()))

    def _visible(self):
        return [i for i in self._items if i.widget() is None or not i.widget().isHidden()]

    def _need(self, item, width: int) -> int:
        w = item.widget()
        stretch = w is not None and id(w) in self._stretch
        need = item.minimumSize().width() if stretch else self._item_width(item)
        if need > width:                                  # narrowed to the row, never below
            need = max(width, item.minimumSize().width())   # its own least width
        return need

    def _lines(self, width: int):
        """The items on each line, with their widths. A label that names
        the next item ("Sort:") goes onto the next line with it."""
        lines, line, used = [], [], 0
        items = self._visible()
        for n, item in enumerate(items):
            need = self._need(item, width)
            if _is_gap(item) and not line:
                continue                                  # no line starts with a divider
            keep = need
            if _names_next(item) and n + 1 < len(items):
                keep += self._gap + self._need(items[n + 1], width)
            if line and used + self._gap + keep > width:
                while line and _is_gap(line[-1][0]):
                    used -= line.pop()[1] + (self._gap if line else 0)
                lines.append(line)
                line, used = [], 0
                if _is_gap(item):
                    continue
            used += (self._gap if line else 0) + need
            line.append([item, need])
        while line and _is_gap(line[-1][0]):
            line.pop()
        if line:
            lines.append(line)
        for line in lines:                                # a stretching item takes the rest
            stretchy = [e for e in line if e[0].widget() is not None
                        and id(e[0].widget()) in self._stretch]
            if stretchy:
                room = width - sum(e[1] for e in line) - self._gap * (len(line) - 1)
                for e in stretchy:
                    e[1] += max(0, room) // len(stretchy)
        return lines

    def _arrange(self, rect: QRect, move: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        lines = self._lines(max(1, area.width()))
        if move:
            placed = {id(e[0]) for line in lines for e in line}
            for item in self._visible():
                if id(item) not in placed:                # a divider at a wrap: not drawn
                    item.setGeometry(QRect(area.x(), area.y(), 0, 0))
        y = area.y()
        for n, line in enumerate(lines):
            height = max(e[0].sizeHint().height() for e in line)
            x = area.x()
            for item, width in line:
                h = item.sizeHint().height()
                if move:
                    item.setGeometry(QRect(x, y + (height - h) // 2, width, h))
                x += width + self._gap
            y += height + (self._gap if n < len(lines) - 1 else 0)
        return y - rect.y() + m.bottom()


class _StackWhenNarrow(QObject):
    def __init__(self, row, host: QWidget, room):
        super().__init__(host)
        self.row, self.host, self.room = row, host, room

    def eventFilter(self, obj, event) -> bool:
        if obj is self.host and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.fit()
        return False

    def fit(self) -> None:
        from PyQt6.QtWidgets import QBoxLayout
        room = self.room() if callable(self.room) else self.room
        want = (QBoxLayout.Direction.TopToBottom if 0 < self.host.width() < room
                else QBoxLayout.Direction.LeftToRight)
        if self.row.direction() != want:
            self.row.setDirection(want)
            relayout(self.host)


def stack_when_narrow(row, host: QWidget, room) -> None:
    """A heading with its words beside it (a ``QHBoxLayout``) puts the
    words under the heading while ``host`` is narrower than ``room`` (a
    width, or a function giving one), so a narrow window does not squeeze
    them into a column taller than the row (U.3b)."""
    keeper = _StackWhenNarrow(row, host, room)
    host.installEventFilter(keeper)
    keeper.fit()


class ElidedLabel(QLabel):
    """A one-line label that gives up its width: when the room is short it
    shows the start of its text and "…" instead of pushing the window wider
    (U.3a). The full text is its tooltip while it is cut, unless the label
    has a tooltip of its own. Rich text keeps its look while it fits and is
    drawn plain when cut. Use it where a label holds a word that may grow
    ("Chapter", "Novella", "words"; decision 18)."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None, *,
                 least_chars: int = 6, text_in_tip: bool = False):
        super().__init__(text, parent)
        self._least_chars = least_chars
        self._text_in_tip = text_in_tip        # U.3b: while cut, the text heads its own tip
        self._own_tip = ""
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def plain_text(self) -> str:
        text, fmt = self.text(), self.textFormat()
        rich = fmt == Qt.TextFormat.RichText or (fmt == Qt.TextFormat.AutoText
                                                 and Qt.mightBeRichText(text))
        if not rich:
            return text
        from PyQt6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.setHtml(text)
        return doc.toPlainText()

    def is_cut(self) -> bool:
        return bool(self.text()) and self.width() + 1 < super().sizeHint().width()

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        if not self.text():
            return hint
        least = self.fontMetrics().horizontalAdvance("M" * self._least_chars + "…") + 16
        return QSize(min(hint.width(), least), hint.height())

    def setToolTip(self, tip: str) -> None:            # remembered so a cut can add its own
        self._own_tip = tip or ""
        super().setToolTip(tip)
        if self._text_in_tip:
            self._tip()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._tip()

    def setText(self, text: str) -> None:              # noqa: N802
        super().setText(text)
        self._tip()

    def _tip(self) -> None:
        cut = self.is_cut()
        if not self._own_tip:
            QLabel.setToolTip(self, self.plain_text() if cut else "")
        elif self._text_in_tip:
            QLabel.setToolTip(self, f"{self.plain_text()}\n\n{self._own_tip}" if cut
                              else self._own_tip)

    def paintEvent(self, event) -> None:
        if not self.is_cut():
            super().paintEvent(event)
            return
        from PyQt6.QtGui import QPainter
        painter = QPainter(self)
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(" ".join(self.plain_text().split()),
                                             Qt.TextElideMode.ElideRight, rect.width())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setFont(self.font())
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)


def empty_state(text: str) -> QLabel:
    """One quiet line that says what to do next when there is nothing to show."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(f"color: {COLORS['ink_faint']}; font-style: italic; padding: 12px;")
    return label


def fold_into_menu(text: str, buttons, tip: str = "", parent: Optional[QWidget] = None,
                   like: Optional[QWidget] = None):
    """One menu button holding ``buttons``' actions, so a crowded row shows
    fewer (the writer's request, 26 Nov: the Studio's "+"). Each entry
    takes its button's text and tooltip and clicks that button, so
    everything wired to it (signals, tests, enabled state) works as
    before; the buttons themselves are kept, hidden, inside it. ``like``:
    a neighbouring button whose height (and so whose look in the row) it
    takes."""
    from PyQt6.QtWidgets import QMenu
    btn = QToolButton(parent)
    btn.setText(text)
    btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    if tip:
        btn.setToolTip(tip)
    plain(btn, 12, "3px 9px")
    menu = QMenu(btn)
    for b in buttons:
        action = menu.addAction(b.text())
        action.setToolTip(b.toolTip())
        action.triggered.connect(b.click)
        b.setParent(btn)
        b.hide()
    menu.setToolTipsVisible(True)
    menu.aboutToShow.connect(lambda: [a.setEnabled(b.isEnabled())
                                      for a, b in zip(menu.actions(), buttons)])
    btn.setMenu(menu)
    if like is not None:
        h = like.sizeHint().height()
        btn.setFixedHeight(h)
        btn.setMinimumWidth(h)
    return btn
