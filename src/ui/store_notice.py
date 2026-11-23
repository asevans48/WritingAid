"""Tell the writer, once, when a stored file could not be read (piece 0.4).

``safe_store`` sets an unreadable file aside and raises one notice per file.
Notices can come from background threads, so they travel to the main window
through a Qt signal (queued across threads) and are shown there.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QWidget

from src.data import safe_store


class _StoreNotice(QObject):
    notice = pyqtSignal(str)


_bridge = None


def install(parent: QWidget) -> None:
    """Show safe_store's notices over ``parent`` (the main window)."""
    global _bridge
    bridge = _StoreNotice(parent)
    bridge.notice.connect(lambda message: _show(parent, message))
    _bridge = bridge                       # keep it alive with the window
    safe_store.set_notifier(bridge.notice.emit)


def _show(parent: QWidget, message: str) -> None:
    try:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("A saved file could not be read")
        box.setText(message)
        box.setInformativeText("Nothing was overwritten. The unreadable copy is still in "
                               "the folder if you want to recover it.")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.open()                         # not modal-blocking
        bar = getattr(parent, "statusBar", None)
        if callable(bar):
            bar().showMessage(message, 15000)
    except Exception as e:                 # an exception escaping a slot aborts PyQt6
        print(f"[store-notice] {e}")
