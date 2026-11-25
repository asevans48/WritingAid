"""The Critique in its own window, beside Write.

"⧉ Own window" on the Critique's top row (and "Critique in Its Own
Window" in the Critique menu) moves the whole Critique (scorecard, issues,
detailed critique) into a separate window, so the writer can put Write and
the Critique side by side. The first time, the two are tiled: the main
window on the left of the screen, the Critique on the right. After that
the Critique window opens where the writer last left it.

The Critique tab stays where it was, with a note and "Bring it back".
Closing the window brings it back too. Every control keeps its object,
its signals and its behaviour: only its parent changes.

While it is out, "Show in chapter" and the other links bring the main
window forward with the passage selected, and choosing the Critique tab
(or "Open Critique Tab") brings the Critique window forward.
"""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtWidgets import QLabel, QToolButton, QVBoxLayout, QWidget

GEOMETRY_KEY = "critique_window/geometry"
OUT_KEY = "critique_window/out"
SHARE = 0.42                    # of the screen's width, when tiling the first time


def _settings():
    from src.ui.ui_kit import _settings as kit_settings
    return kit_settings()


class CritiqueWindow(QWidget):
    def __init__(self, owner: "PopOut"):
        super().__init__(owner.main_window, Qt.WindowType.Window)
        self.owner = owner
        self.setWindowTitle("Critique")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

    def closeEvent(self, event):
        try:
            _settings().setValue(GEOMETRY_KEY, self.saveGeometry())
        except Exception:
            pass
        event.accept()
        self.owner.bring_back(from_close=True)


class PopOut:
    """Owns the move between the tab and the window."""

    def __init__(self, main_window: Any, grader: Any):
        self.main_window = main_window
        self.grader = grader
        self.window: Optional[CritiqueWindow] = None
        # Everything the Critique shows goes into one body widget, so it can
        # move as one. The grader keeps its own layout, holding the body.
        self.body = QWidget()
        old = grader.layout()
        if old is not None:
            self.body.setLayout(old)          # Qt takes the layout off the grader
        page = QVBoxLayout(grader)
        page.setContentsMargins(0, 0, 0, 0)
        page.addWidget(self.body)
        self.note = QLabel(
            "<p style='font-size:14px'>The Critique is open in its own window.</p>"
            "<p><a href='raise'>Show it</a> · <a href='back'>Bring it back here</a></p>")
        self.note.setTextFormat(Qt.TextFormat.RichText)
        self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.note.linkActivated.connect(
            lambda href: self.raise_window() if href == "raise" else self.bring_back())
        self.note.setVisible(False)
        page.addWidget(self.note)
        self.button = QToolButton()
        self.button.setText("⧉ Own window")
        self.button.setAutoRaise(True)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setToolTip("Open the Critique in its own window, to put it beside Write. "
                               "Close that window to bring it back.")
        self.button.clicked.connect(self.toggle)
        self._place_button()
        tabs = getattr(main_window, "tab_widget", None)
        if tabs is not None:
            tabs.currentChanged.connect(self._tab_changed)

    def _place_button(self) -> None:
        """On the scorecard's top row, before "Check readiness"."""
        scorecard = getattr(self.grader, "scorecard", None)
        top = None
        if scorecard is not None and scorecard.layout() is not None:
            first = scorecard.layout().itemAt(0)
            top = first.layout() if first is not None else None
        if top is not None:
            at = top.indexOf(getattr(scorecard, "check_btn", None))
            top.insertWidget(at if at >= 0 else top.count(), self.button)
        else:
            self.body.layout().insertWidget(0, self.button)

    # ── Out and back ─────────────────────────────────────────────

    @property
    def is_out(self) -> bool:
        return self.window is not None

    def toggle(self) -> None:
        self.bring_back() if self.is_out else self.pop_out()

    def pop_out(self) -> None:
        if self.is_out:
            self.raise_window()
            return
        self.window = CritiqueWindow(self)
        self.grader.layout().removeWidget(self.body)
        self.window.layout().addWidget(self.body)
        self.body.show()
        self.note.setVisible(True)
        self.button.setText("⧉ Back to the tab")
        self.button.setToolTip("Put the Critique back in its tab.")
        self._place_window()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self._remember(True)
        tabs = getattr(self.main_window, "tab_widget", None)
        if tabs is not None and tabs.currentWidget() is self.grader:
            tabs.setCurrentIndex(0)           # Write, beside it

    def bring_back(self, from_close: bool = False) -> None:
        window, self.window = self.window, None
        if window is None:
            return
        if not from_close:
            try:
                _settings().setValue(GEOMETRY_KEY, window.saveGeometry())
            except Exception:
                pass
        window.layout().removeWidget(self.body)
        self.note.setVisible(False)
        self.grader.layout().insertWidget(0, self.body)
        self.body.show()
        self.button.setText("⧉ Own window")
        self.button.setToolTip("Open the Critique in its own window, to put it beside Write. "
                               "Close that window to bring it back.")
        self._remember(False)
        if not from_close:
            window.hide()
        window.deleteLater()
        tabs = getattr(self.main_window, "tab_widget", None)
        if tabs is not None:
            tabs.setCurrentWidget(self.grader)

    def raise_window(self) -> None:
        if self.window is not None:
            self.window.showNormal() if self.window.isMinimized() else self.window.show()
            self.window.raise_()
            self.window.activateWindow()

    def bring_main_forward(self) -> None:
        """A link in the Critique window opened something in Write."""
        if self.is_out:
            self.main_window.raise_()
            self.main_window.activateWindow()

    def _tab_changed(self, index: int) -> None:
        tabs = self.main_window.tab_widget
        if self.is_out and tabs.widget(index) is self.grader:
            self.raise_window()

    def _remember(self, out: bool) -> None:
        try:
            _settings().setValue(OUT_KEY, "true" if out else "false")
        except Exception:
            pass

    def _place_window(self) -> None:
        """Where the writer left it; the first time, tiled with the main
        window (main on the left, the Critique on the right)."""
        try:
            saved = _settings().value(GEOMETRY_KEY)
        except Exception:
            saved = None
        if isinstance(saved, (QByteArray, bytes)) and self.window.restoreGeometry(saved):
            return
        screen = self.main_window.screen()
        if screen is None:
            self.window.resize(560, 700)
            return
        area = screen.availableGeometry()
        right = max(420, int(area.width() * SHARE))
        left = area.width() - right
        mw = self.main_window
        if mw.isMaximized() or mw.isFullScreen():
            mw.showNormal()
        if mw.width() > left:
            mw.setGeometry(area.left(), area.top(), left, area.height())
        self.window.setGeometry(area.left() + left, area.top(), right, area.height())


# ── Call lines (rule 14) ─────────────────────────────────────────────

def install(main_window: Any) -> Optional[PopOut]:
    """Called once the Critique tab is built."""
    grader = getattr(main_window, "grader_widget", None)
    if grader is None:
        return None
    try:
        main_window.critique_popout = PopOut(main_window, grader)
    except Exception as e:                    # never break the tab
        print(f"[critique window] not available: {e}")
        return None
    issues = getattr(getattr(grader, "scorecard", None), "issues", None)
    if issues is not None:
        bring = lambda *a: main_window.critique_popout.bring_main_forward()
        issues.show_requested.connect(bring)
        issues.companion_requested.connect(bring)
        issues.expand_requested.connect(bring)
    return main_window.critique_popout


def add_to_menu(main_window: Any, menu: Any) -> None:
    """In the Critique menu, beside "Open Critique Tab"."""
    pop = getattr(main_window, "critique_popout", None)
    if pop is None:
        return
    text = "Bring the Critique Back to Its Tab" if pop.is_out else "Critique in Its Own Window"
    menu.addAction(text).triggered.connect(lambda _=False: pop.toggle())
