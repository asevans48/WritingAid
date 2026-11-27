"""The Video Studio's side panel (Backend status and Hints): dropped by
default, on the canvas's right-click (the writer's request, 26 Nov 2026).

* The panel starts closed, so the canvas has the whole width. ▶◀ on the
  toolbar brings it back (as before), and whether it is open is remembered.
* Right-clicking the empty canvas offers **Backend status…** and
  **Hints…**; each opens a small window with what the panel shows, so
  neither needs the panel open. Nothing was removed (rule 11): the panel,
  its toggle and its text are all still there.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QGroupBox, QLabel, QVBoxLayout, QWidget,
)

KEY = "video_studio/side_panel_open"


def _settings():
    from src.ui import ui_kit
    return ui_kit._settings()


def is_open() -> bool:
    try:
        return bool(_settings().value(KEY, False, type=bool))
    except Exception:
        return False


def _remember(on: bool) -> None:
    try:
        _settings().setValue(KEY, bool(on))
    except Exception as e:
        print(f"[studio] could not remember the side panel: {e}")


def install(studio) -> None:
    """Close the panel unless the writer left it open; remember ▶◀; add the
    two right-click entries. ``studio`` is the ``VideoStudioWidget``."""
    toggle = studio._toggle_side_btn
    toggle.setToolTip("Show or hide Backend status and Hints (also on the "
                      "canvas's right-click).")
    if not is_open():
        toggle.setChecked(False)
        studio._splitter.setSizes([1, 0])
    toggle.toggled.connect(_remember)
    studio._canvas.extra_empty_actions = [
        ("Backend status…", lambda: show(studio, "Backend status")),
        ("Hints…", lambda: show(studio, "Hints")),
    ]


def _texts(studio, title: str):
    """The labels' text in the panel's box called ``title``."""
    for box in studio.findChildren(QGroupBox):
        if box.title() == title:
            return [(lbl.text(), lbl.textFormat()) for lbl in box.findChildren(QLabel)
                    if lbl.text().strip()]
    return []


def show(studio, title: str) -> QDialog:
    """A small window with what the panel's ``title`` box says."""
    if title == "Backend status":
        try:
            studio._refresh_backend_info()
        except Exception:
            pass
    dlg = QDialog(studio)
    dlg.setWindowTitle(title)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    lay = QVBoxLayout(dlg)
    texts = _texts(studio, title) or [("Nothing to show yet.", Qt.TextFormat.PlainText)]
    body = QWidget()
    body_lay = QVBoxLayout(body)
    body_lay.setContentsMargins(0, 0, 0, 0)
    for text, fmt in texts:
        lbl = QLabel(text)
        lbl.setTextFormat(fmt)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body_lay.addWidget(lbl)
    body_lay.addStretch()
    from src.ui.ui_kit import fit_to_screen, scrollable
    lay.addWidget(scrollable(body))
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dlg.close)
    lay.addWidget(buttons)
    fit_to_screen(dlg, 420, 360, min_width=320, min_height=240)
    dlg.show()
    return dlg
