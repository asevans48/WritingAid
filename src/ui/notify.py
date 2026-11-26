"""Messages that need no click (piece D.9).

A message that only informs is shown in the status bar for a few seconds
instead of a box the writer has to close:

* ``done(parent, title, text, path=None)``: something finished ("Exported
  to …", "Copied"). With ``path``, the status bar also shows **Show file**
  for as long as the message is there.
* ``empty(parent, title, text)``: nothing to do ("Select some text first",
  "No drafts yet").
* ``notice(parent, title, text)``: something the writer should see but need
  not click ("Draft #3 saved", "Created draft …"; the writer's choice, 24
  November 2026: "visible but no box"). Shown longer (``NOTICE_MS``) on a
  tinted status bar, so it stands out.

Both take the same arguments as ``QMessageBox.information``, so a call
site changes one word. Warnings, errors, questions and anything about
saving, deleting, moving or replacing work still use ``QMessageBox`` and do
not come here.

**Nothing is lost:** every quiet message is kept for the session
(``recent()``) and Help ▸ Recent messages lists them (``show_recent``).

**The old boxes, one switch away:** Settings ▸ Features ▸ Messages, "Show
a box for every message" (``KEY_BOXES``, off by default). On, each call
opens ``QMessageBox.information`` exactly as before. A box is also shown
when there is no status bar to put the message in.
"""

from __future__ import annotations

import html
import os
import re
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QMainWindow, QMessageBox,
    QPushButton, QStatusBar, QTextBrowser, QVBoxLayout,
)

KEY_BOXES = "notify_show_boxes"
SHOW_MS = 8000
NOTICE_MS = 20000
KEEP = 100


@dataclass
class Message:
    when: datetime
    kind: str                 # "done" or "empty"
    title: str
    text: str
    path: Optional[str] = None


_recent: Deque[Message] = deque(maxlen=KEEP)
_override: Dict[str, bool] = {}      # tests: force the switch without touching settings


# ── The switch ─────────────────────────────────────────────────────────

def boxes_wanted() -> bool:
    if "boxes" in _override:
        return _override["boxes"]
    try:
        from src.config.ai_config import get_ai_config
        return bool(get_ai_config().get_settings().get(KEY_BOXES, False))
    except Exception:
        return False


def set_for_session(boxes: Optional[bool]) -> None:
    """Force the switch without saving it (tests); None goes back to Settings."""
    if boxes is None:
        _override.pop("boxes", None)
    else:
        _override["boxes"] = bool(boxes)


class BoxesOption:
    """The switch in Settings (one call line in ``SettingsDialog``)."""

    def __init__(self, layout, settings: Dict[str, Any]):
        from PyQt6.QtWidgets import QGroupBox
        group = QGroupBox("Messages")
        inner = QVBoxLayout()
        self.check = QCheckBox("Show a box for every message")
        self.check.setToolTip(
            "Off: a message that only informs (\"Exported to …\", \"Select some text "
            "first\") appears in the status bar and goes away by itself; Help ▸ Recent "
            "messages lists them. On: each one opens a box you close, as before. "
            "Warnings and questions always open a box.")
        self.check.setChecked(bool(settings.get(KEY_BOXES, False)))
        inner.addWidget(self.check)
        group.setLayout(inner)
        layout.addWidget(group)

    def values(self) -> Dict[str, bool]:
        return {KEY_BOXES: self.check.isChecked()}


# ── Showing a message ──────────────────────────────────────────────────

def _plain(text: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", str(text or ""), flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\s+", " ", text).strip()


def _main_window(parent: Any) -> Optional[QMainWindow]:
    """The window whose status bar shows the message: the parent's own if
    it already has one, else the app's main window. Never creates one.

    None (so a box, as before) when the parent is in a separate dialog or
    tool window with no status bar of its own: the main window's bar may be
    hidden behind it (second session, 25 November 2026)."""
    seen = []
    try:
        if parent is not None:
            own = parent.window()
            if isinstance(own, QDialog) or (
                    isinstance(own, QMainWindow) and own.findChild(QStatusBar) is None):
                return None
            seen.append(own)
    except Exception:
        pass
    app = QApplication.instance()
    if app is not None:
        active = app.activeWindow()
        if active is not None:
            seen.append(active)
        seen.extend(w for w in app.topLevelWidgets() if hasattr(w, "manuscript_editor"))
        seen.extend(app.topLevelWidgets())
    for w in seen:
        if isinstance(w, QMainWindow) and w.findChild(QStatusBar) is not None:
            return w
    return None


def _reveal(path: str) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
            return
    except Exception:
        pass
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


def _show_file_button(window: QMainWindow, path: Optional[str]) -> None:
    bar = window.statusBar()
    btn = getattr(window, "_notify_show_file_btn", None)
    if btn is None:
        btn = QPushButton("Show file")
        btn.setFlat(True)
        btn.setStyleSheet("QPushButton { text-decoration: underline; padding: 0 6px; }")
        bar.addPermanentWidget(btn)
        window._notify_show_file_btn = btn
        # Only beside its own message: hidden when the message goes or another replaces it.
        bar.messageChanged.connect(
            lambda m, w=window, b=btn: b.setVisible(bool(m) and m == getattr(w, "_notify_text", None)))
    try:
        btn.clicked.disconnect()
    except TypeError:
        pass
    if path:
        btn.clicked.connect(lambda _=False, p=path: _reveal(p))
        btn.setToolTip(path)
    btn.setVisible(bool(path))


def _tint(window: QMainWindow, shown: str) -> None:
    """Tint the status bar while ``shown`` is its message (a notice)."""
    from src.ui.ui_kit import PALETTE
    bar = window.statusBar()
    if not getattr(window, "_notify_tint_hooked", False):
        window._notify_tint_hooked = True
        bar.messageChanged.connect(
            lambda m, w=window: w.statusBar().setStyleSheet(
                w._notify_tint_qss if m and m == getattr(w, "_notify_tinted", None) else ""))
    window._notify_tint_qss = (f"QStatusBar {{ background: {PALETTE['primary_tint']};"
                               f" color: {PALETTE['primary_ink']}; font-weight: bold; }}")
    window._notify_tinted = shown
    bar.setStyleSheet(window._notify_tint_qss)


def _notify(parent: Any, title: str, text: str, kind: str, path: Optional[str]):
    _recent.append(Message(datetime.now(), kind, str(title or ""), str(text or ""), path))
    window = None if boxes_wanted() else _main_window(parent)
    if window is None:
        return QMessageBox.information(parent, title, text)
    shown = _plain(text)
    window._notify_text = shown if path else None
    if kind == "notice":
        _tint(window, shown)
    else:
        window._notify_tinted = None
    window.statusBar().showMessage(shown, NOTICE_MS if kind == "notice" else SHOW_MS)
    _show_file_button(window, path)
    return QMessageBox.StandardButton.Ok


def done(parent: Any, title: str, text: str, path: Optional[str] = None):
    """Something finished; nothing to decide."""
    return _notify(parent, title, text, "done", path)


def empty(parent: Any, title: str, text: str):
    """Nothing to do (no selection, no chapters …)."""
    return _notify(parent, title, text, "empty", None)


def notice(parent: Any, title: str, text: str):
    """Should be seen, needs no click: longer, on a tinted status bar."""
    return _notify(parent, title, text, "notice", None)


# ── Reading them again ─────────────────────────────────────────────────

def recent() -> List[Message]:
    """This session's quiet messages, newest first."""
    return list(reversed(_recent))


def clear() -> None:
    _recent.clear()


def recent_html() -> str:
    items = recent()
    if not items:
        return "<p>No messages yet this session.</p>"
    rows = []
    for m in items:
        link = (f" <a href='{QUrl.fromLocalFile(m.path).toString()}'>Show file</a>"
                if m.path else "")
        rows.append(f"<p><b>{m.when:%H:%M}</b> · {html.escape(m.title)}<br>"
                    f"{html.escape(_plain(m.text))}{link}</p>")
    return "".join(rows)


def show_recent(parent: Any) -> QDialog:
    """Help ▸ Recent messages."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Recent messages")
    dlg.resize(520, 420)
    lay = QVBoxLayout(dlg)
    view = QTextBrowser(dlg)
    view.setOpenLinks(False)
    view.anchorClicked.connect(lambda url: _reveal(url.toLocalFile()))
    view.setHtml(recent_html())
    lay.addWidget(view)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dlg)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)
    dlg.show()
    return dlg


def install_menu(help_menu: Any, window: Any) -> Any:
    """The Help ▸ Recent messages entry (a call line in ``MainWindow``)."""
    act = help_menu.addAction("Recent &messages…")
    act.setToolTip("Messages shown in the status bar this session")
    act.triggered.connect(lambda _=False: show_recent(window))
    return act
