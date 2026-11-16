"""The conversation panel shared by Suggestions and Rephrase."""

from __future__ import annotations

import html
from typing import Callable, Set

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

# A QThread destroyed while running aborts the app; keep turns until done.
_RUNNING: Set["ChatTurnWorker"] = set()


class ChatTurnWorker(QThread):
    """Runs one conversation turn (a callable returning a ChatResult)."""
    done = pyqtSignal(object, str)          # ChatResult | None, error

    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(), "")
        except Exception as e:
            self.done.emit(None, f"Couldn't get a reply: {e}")


class ConversationPanel(QWidget):
    """Transcript, message box and Send. Emits ``message_sent``."""
    message_sent = pyqtSignal(str)
    remember_requested = pyqtSignal(str)    # text for the Story memory

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.transcript = QTextBrowser()
        self.transcript.setMinimumHeight(110)
        self.transcript.setStyleSheet("background: #f9fafb; font-size: 11px;")
        self.transcript.setPlaceholderText(
            "Talk about the results: ask why, give direction, or ask for changes "
            "(\"combine 1 and 3\", \"darker\", \"keep Tobin rambling\").")
        layout.addWidget(self.transcript)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder or "Reply to the editor…")
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input, 1)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send)
        row.addWidget(self.send_btn)
        self.remember_btn = QPushButton("📌 Remember")
        self.remember_btn.setToolTip("Save a decision to Story memory: select text in the "
                                     "conversation, or it saves your last message.")
        self.remember_btn.clicked.connect(self._remember)
        row.addWidget(self.remember_btn)
        layout.addLayout(row)
        self.status = QLabel("")
        self.status.setStyleSheet("color: #6b7280; font-size: 10px; font-style: italic;")
        layout.addWidget(self.status)
        self._html: list = []
        self._last_author = ""

    def _remember(self):
        text = self.transcript.textCursor().selectedText().replace("\u2029", " ").strip()
        text = text or self._last_author
        if text:
            self.remember_requested.emit(text)

    def _send(self):
        text = self.input.text().strip()
        if not text or not self.send_btn.isEnabled():
            return
        self.input.clear()
        self.message_sent.emit(text)

    def add_message(self, who: str, text: str) -> None:
        if who == "You":
            self._last_author = text
        color = "#1f2937" if who == "You" else "#4338ca"
        body = html.escape(text).replace("\n", "<br>")
        self._html.append(f"<p><b style='color:{color}'>{html.escape(who)}:</b> {body}</p>")
        self.transcript.setHtml("".join(self._html))
        bar = self.transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.send_btn.setEnabled(not busy)
        self.input.setEnabled(not busy)
        self.status.setText(message)

    def clear(self) -> None:
        self._html = []
        self.transcript.clear()
        self.status.setText("")

    def plain_text(self) -> str:
        return self.transcript.toPlainText()


def run_turn(owner, fn: Callable[[], object], on_done: Callable[[object, str], None]):
    """Start a turn in the background; ``on_done(result, error)`` on the GUI thread."""
    worker = ChatTurnWorker(fn)

    def safe(result, error):
        try:
            on_done(result, error)
        except Exception as e:           # an exception escaping a slot aborts PyQt6
            print(f"[chat] could not show the reply: {e}")

    worker.done.connect(safe)
    _RUNNING.add(worker)
    worker.finished.connect(lambda w=worker: _RUNNING.discard(w))
    owner._chat_worker = worker
    worker.start()
    return worker


def remember(panel: "ConversationPanel", project, text: str, source: str) -> None:
    """📌 Remember from a conversation panel."""
    from src.ai import story_memory
    if project is None:
        panel.status.setText("Open a project to use Story memory.")
        return
    added = story_memory.add(project, text, source=source)
    panel.status.setText("Remembered in Story memory." if added else "Already in Story memory.")


def propose_memory(panel: "ConversationPanel", project, llm, message: str, reply: str,
                   source: str) -> None:
    """When the writer settles something, suggest it for the Story memory."""
    from src.ai import story_memory
    if project is None or llm is None or not story_memory.has_decision(message):
        return
    from src.ui.companion_panel import run_background

    def done(decisions, _error):
        added = [d for d in decisions or []
                 if story_memory.add(project, d, source=source, suggested=True)]
        if added:
            panel.status.setText(f"💡 Suggested for Story memory: {added[0]} — keep it in the "
                                 f"chapter's Companion tab.")

    run_background(lambda: story_memory.extract_decisions(llm, message, reply), done)
