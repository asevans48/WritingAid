"""Shared interface parts (piece U.1).

One place for what every screen needs, so screens look and behave the same
and new ones are cheaper to build:

* **Fitting the screen:** ``fit_to_screen`` opens a window no larger than
  the screen it is on; ``remember_geometry`` brings it back where it was
  (size, position and screen), or onto a visible screen if that monitor is
  gone; ``size_class`` says whether a window is narrow, normal or wide.
* **Scrolling:** ``scrollable`` wraps content in a scroll area the standard
  way, so nothing is squeezed.
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
    QFrame, QLabel, QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
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


# The planner's story-arc stages (Freytag), used by its arc drawing and its
# beat list alike.
ARC_COLOURS: Dict[str, str] = {
    "exposition": COLORS["info"], "rising": "#22c55e", "climax": COLORS["error"],
    "falling": "#f97316", "resolution": COLORS["violet"],
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


def empty_state(text: str) -> QLabel:
    """One quiet line that says what to do next when there is nothing to show."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(f"color: {COLORS['ink_faint']}; font-style: italic; padding: 12px;")
    return label
