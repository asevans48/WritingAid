"""Overly descriptive statements: the sub-module the Suggestions dialog,
the editor and the Critique tab share.

``OverdescriptionPanel`` lists the flagged statements, shows why each
reads as over-described and the ways to expand it, and lets the writer
accept (and edit) an expansion. It doesn't touch the manuscript itself:
it emits ``accepted(index, text)`` and the host applies it.

``ExpandStatementDialog`` hosts the panel on its own for a highlighted
passage (from the editor's context menu or a Critique-tab link).
"""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional, Set

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QFrame, QScrollArea, QSplitter, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from src.ai import overdescription as od

HIGHLIGHT = "#fde68a"          # flagged statement
CUE_COLOR = "#b45309"          # the cue words inside it

# A QThread destroyed while running aborts the app; keep running ones here.
# Running workers are kept alive by the shared helper (R.2); the name stays
# for existing imports.
from src.ui import background  # noqa: E402

_RUNNING = background._RUNNING


def flag_html(flag: od.Flag) -> str:
    """The statement with its cue words marked."""
    out, last = [], 0
    for c in sorted(flag.cues, key=lambda c: c.start):
        if c.start < last:
            continue
        out.append(html.escape(flag.text[last:c.start]))
        out.append(f"<b style='color:{CUE_COLOR}'>{html.escape(flag.text[c.start:c.end])}</b>")
        last = c.end
    out.append(html.escape(flag.text[last:]))
    return "".join(out)


def highlight_flags(edit: QTextEdit, text: str, flags: List[od.Flag], offset: int = 0) -> None:
    """Tint the flagged statements in ``edit`` (which shows ``text``);
    flag offsets are Python indices into ``text`` minus ``offset``."""
    from src.ai.passage_critique import py_to_qt_index
    selections = []
    fmt = QTextCharFormat()
    fmt.setBackground(QColor(HIGHLIGHT))
    for f in flags:
        cursor = QTextCursor(edit.document())
        cursor.setPosition(py_to_qt_index(text, offset + f.start))
        cursor.setPosition(py_to_qt_index(text, offset + f.end), QTextCursor.MoveMode.KeepAnchor)
        sel = QTextEdit.ExtraSelection()
        sel.cursor, sel.format = cursor, fmt
        selections.append(sel)
    edit.setExtraSelections(selections)


def _heading(text: str) -> QLabel:
    label = QLabel(f"<b>{text}</b>")
    label.setStyleSheet("color: #333;")
    return label


class OverdescriptionPanel(QWidget):
    accepted = pyqtSignal(int, str)         # flag index, replacement for that statement
    more_requested = pyqtSignal(int, str)   # flag index, the writer's direction

    def __init__(self, parent=None):
        super().__init__(parent)
        self.review: Optional[od.Review] = None
        self.can_ask_ai = False
        self.applied: Dict[int, str] = {}   # flag index → text now in place
        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #555; font-style: italic;")
        layout.addWidget(self.status)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        self.flag_list = QListWidget()
        self.flag_list.setMinimumWidth(200)
        self.flag_list.setWordWrap(True)
        self.flag_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.flag_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.flag_list.setSpacing(2)
        self.flag_list.currentRowChanged.connect(self._show_flag)
        split.addWidget(self.flag_list)

        # The detail side scrolls on its own, so every part keeps a readable
        # height even when the tab is short.
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 0, 8, 0)
        rl.setSpacing(6)
        rl.addWidget(_heading("The statement"))
        self.statement = QTextBrowser()
        self.statement.setMinimumHeight(48)
        self.statement.setMaximumHeight(64)
        rl.addWidget(self.statement)
        self.reason = QLabel("")
        self.reason.setWordWrap(True)
        self.reason.setStyleSheet("color: #444;")
        rl.addWidget(self.reason)
        self.hints = QLabel("")
        self.hints.setWordWrap(True)
        self.hints.setStyleSheet("color: #555; font-size: 11px;")
        rl.addWidget(self.hints)
        rl.addSpacing(4)
        rl.addWidget(_heading("Ways to expand it"))
        self.expansion_list = QListWidget()
        self.expansion_list.setWordWrap(True)
        self.expansion_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.expansion_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.expansion_list.setSpacing(2)
        self.expansion_list.setMinimumHeight(110)
        self.expansion_list.setMaximumHeight(170)
        self.expansion_list.currentRowChanged.connect(self._show_expansion)
        rl.addWidget(self.expansion_list)
        self.notes = QLabel("")
        self.notes.setWordWrap(True)
        self.notes.setStyleSheet("color: #b45309; font-size: 11px;")
        rl.addWidget(self.notes)
        rl.addSpacing(4)
        rl.addWidget(_heading("Your version (edit before accepting)"))
        self.preview = QTextEdit()
        self.preview.setPlaceholderText("Pick a way to expand it — or write your own — then "
                                        "Accept.")
        self.preview.setMinimumHeight(80)
        self.preview.setMaximumHeight(140)
        rl.addWidget(self.preview)
        row = QHBoxLayout()
        self.accept_btn = QPushButton("✓ Accept")
        self.accept_btn.setToolTip("Put this in place of the statement")
        self.accept_btn.clicked.connect(self._accept)
        row.addWidget(self.accept_btn)
        self.revert_btn = QPushButton("↺ Keep original")
        self.revert_btn.clicked.connect(self._revert)
        row.addWidget(self.revert_btn)
        row.addStretch()
        rl.addLayout(row)
        more_row = QHBoxLayout()
        self.more_edit = QLineEdit()
        self.more_edit.setPlaceholderText("direction (optional), e.g. more sound, less sight")
        self.more_edit.returnPressed.connect(self._more)
        more_row.addWidget(self.more_edit, 1)
        self.more_btn = QPushButton("More ideas")
        self.more_btn.clicked.connect(self._more)
        more_row.addWidget(self.more_btn)
        rl.addLayout(more_row)
        rl.addStretch(1)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setWidget(right)
        split.addWidget(right_scroll)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([240, 560])
        layout.addWidget(split, 1)
        # Enough room to read a statement and its expansions without
        # scrolling; the Suggestions window scrolls if it's smaller.
        self.setMinimumHeight(360)
        self._enable(False)

    def _enable(self, on: bool):
        for w in (self.accept_btn, self.revert_btn, self.preview):
            w.setEnabled(on)
        self.more_btn.setEnabled(on and self.can_ask_ai)
        self.more_edit.setEnabled(on and self.can_ask_ai)

    # ── Filling ──────────────────────────────────────────────────────

    def set_busy(self, message: str):
        self.status.setText(message)

    def set_review(self, review: Optional[od.Review], can_ask_ai: bool = False):
        self.review = review or od.Review()
        self.can_ask_ai = can_ask_ai
        self.applied = {}
        flags = self.review.flags
        if not flags:
            self.status.setText("Nothing here reads as overly descriptive."
                                + self._source_note())
        else:
            self.status.setText(f"{len(flags)} statement{'s' if len(flags) != 1 else ''} may "
                                f"be overly descriptive (highlighted)." + self._source_note())
        self._fill_flags(0)

    def _source_note(self) -> str:
        r = self.review
        if r.used_ai:
            return (f" The AI judged {len(r.cleared)} other word-scan hit"
                    f"{'s' if len(r.cleared) != 1 else ''} fine." if r.cleared else "")
        return (" Found by the word scan (no AI) — words like “too” and “almost” are clues, "
                "not proof.")

    def _fill_flags(self, select: int):
        self.flag_list.clear()
        for i, f in enumerate(self.review.flags):
            mark = "✓ " if i in self.applied else ""
            src = {"ai": " · AI", "both": " · AI"}.get(f.source, "")
            item = QListWidgetItem(f"{mark}{_short(f.text, 140)}{src}")
            item.setToolTip(f.reason or f.text)
            self.flag_list.addItem(item)
        if self.review.flags:
            self.flag_list.setCurrentRow(min(select, len(self.review.flags) - 1))
        else:
            self._clear_detail()

    def _clear_detail(self):
        self.statement.clear()
        self.reason.setText("")
        self.hints.setText("")
        self.expansion_list.clear()
        self.preview.clear()
        self.notes.setText("")
        self._enable(False)

    def current_flag(self) -> Optional[od.Flag]:
        row = self.flag_list.currentRow()
        if self.review is None or not (0 <= row < len(self.review.flags)):
            return None
        return self.review.flags[row]

    def _show_flag(self, row: int):
        flag = self.current_flag()
        if flag is None:
            self._clear_detail()
            return
        self.statement.setHtml(flag_html(flag))
        self.reason.setText(f"<b>Why:</b> {html.escape(flag.reason, quote=False)}" if flag.reason else "")
        self.hints.setText("<br>".join(f"• {html.escape(h, quote=False)}" for h in flag.hints))
        self.expansion_list.clear()
        for x in flag.expansions:
            tag = x.approach or ("expansion" if x.by_ai else "edit")
            fit = f" · voice {x.voice_fit:.0%}" if x.voice_fit is not None else ""
            warn = " ⚠" if x.notes else ""
            item = QListWidgetItem(f"{tag}{'' if x.by_ai else ' (no AI)'}{fit}{warn}: "
                                   f"{_short(x.text, 240)}")
            item.setToolTip(x.why or x.text)
            self.expansion_list.addItem(item)
        self._enable(True)
        if flag.expansions:
            self.expansion_list.setCurrentRow(0)
        else:
            self.preview.setPlainText(self.applied.get(row, flag.text))
            self.notes.setText("")

    def _show_expansion(self, row: int):
        flag = self.current_flag()
        if flag is None or not (0 <= row < len(flag.expansions)):
            return
        x = flag.expansions[row]
        self.preview.setPlainText(x.text)
        self.notes.setText("⚠ This expansion " + "; ".join(x.notes) + "." if x.notes else "")

    def add_expansions(self, index: int, found: List[od.Expansion], error: str = ""):
        self.more_btn.setEnabled(self.can_ask_ai)
        if self.review is None or not (0 <= index < len(self.review.flags)):
            return
        if error or not found:
            self.status.setText(error or "The model didn't suggest anything new — try again.")
            return
        flag = self.review.flags[index]
        flag.expansions = found + flag.expansions
        if self.flag_list.currentRow() == index:
            self._show_flag(index)
        self.status.setText(f"{len(found)} more idea{'s' if len(found) != 1 else ''} added.")

    # ── Actions ──────────────────────────────────────────────────────

    def _accept(self):
        row = self.flag_list.currentRow()
        text = self.preview.toPlainText().strip()
        if self.current_flag() is None or not text:
            return
        self.accepted.emit(row, text)

    def _revert(self):
        flag = self.current_flag()
        if flag is not None:
            self.accepted.emit(self.flag_list.currentRow(), flag.text)

    def _more(self):
        if self.current_flag() is None or not self.can_ask_ai:
            return
        self.more_btn.setEnabled(False)
        self.status.setText("Asking for more ideas…")
        self.more_requested.emit(self.flag_list.currentRow(), self.more_edit.text())

    def mark_applied(self, index: int, text: Optional[str], message: str = "Accepted."):
        """The host applied (``text``) or reverted (``None``) a statement."""
        if text is None:
            self.applied.pop(index, None)
        else:
            self.applied[index] = text
        self._fill_flags(index)
        self.status.setText(message if text is not None else "Back to your original.")


class ExpansionState:
    """The passage with the writer's accepted expansions applied."""

    def __init__(self, passage: str):
        self.passage = passage
        self.text = passage
        self.current: Dict[int, str] = {}       # flag index → text now in place

    def apply(self, index: int, flag: od.Flag, replacement: str) -> bool:
        before = self.current.get(index, flag.text)
        new = od.apply_expansion(self.text, before, replacement, near=flag.start)
        if new is None:
            return False
        self.text = new
        if replacement == flag.text:
            self.current.pop(index, None)
        else:
            self.current[index] = replacement
        return True

    @property
    def changed(self) -> bool:
        return self.text != self.passage


def log_accepted(project: Any, original: str, replacement: str) -> None:
    """Accepted expansions teach Suggestions and Rephrase the writer's taste
    (saved only when data collection is on)."""
    if original.strip() == replacement.strip():
        return
    from src.ai.rewrite_quality import log_rated_rewrite
    path = str(getattr(project, "project_path", "") or "") if project is not None else ""
    log_rated_rewrite(original, replacement, "good", accepted=True, project_path=path,
                      style="expansion")


# ── Workers ──────────────────────────────────────────────────────────

class ReviewWorker(QThread):
    """Runs the review for a passage with the model Suggestions uses
    (Settings' critique task model → the default model), or the word
    scan alone when AI is off or no model is configured."""
    progress = pyqtSignal(str)
    done = pyqtSignal(object, str)      # Review, note

    def __init__(self, project, chapter, text: str, start: int, end: int, llm_factory=None):
        super().__init__()
        self.args = (project, chapter, text, start, end)
        if llm_factory is None:
            from src.ui.passage_critique_dialog import _build_llm
            llm_factory = _build_llm
        self.llm_factory = llm_factory
        self.llm = self.ctx = self.voice = None

    def run(self):
        project, chapter, text, start, end = self.args
        try:
            self.progress.emit("Loading the model…")
            llm, error = self.llm_factory()
            from src.ai.passage_critique import build_context
            from src.ai.writer_voice import project_voice
            compact = False
            if llm is not None:
                from src.ai.chapter_analysis_agent import is_local_llm
                compact = is_local_llm(llm)
            voice = project_voice(project, chapter, text, selection=text[start:end])
            ctx = build_context(project, chapter, text, start, end, compact=compact, voice=voice)
            self.llm, self.ctx, self.voice = llm, ctx, voice
            review = od.review_passage(llm, ctx, voice, progress=self.progress.emit,
                                       compact=compact)
            self.done.emit(review, "" if llm is not None else (error or "AI is off"))
        except Exception as e:
            print(f"[overdescription] review failed: {e}")
            self.done.emit(od.Review(od.scan(text[start:end]), error=str(e)), str(e))


class MoreWorker(QThread):
    done = pyqtSignal(int, object, str)  # flag index, [Expansion], error

    def __init__(self, llm, ctx, flag: od.Flag, index: int, voice=None, note: str = ""):
        super().__init__()
        self.llm, self.ctx, self.flag, self.index = llm, ctx, flag, index
        self.voice, self.note = voice, note

    def run(self):
        try:
            found = od.expand_more(self.llm, self.ctx, self.flag, self.voice, self.note)
            self.done.emit(self.index, found, "")
        except Exception as e:
            self.done.emit(self.index, [], f"Couldn't get more ideas: {e}")


def start_worker(worker: QThread) -> None:
    background.start(worker)


# ── Standalone dialog ────────────────────────────────────────────────

class ExpandStatementDialog(QDialog):
    """Overly descriptive statements in a passage, with ways to expand
    them. ``replacement`` holds the passage with the accepted expansions
    after Accept."""

    def __init__(self, text: str, start: int, end: int, project=None, chapter=None,
                 parent=None, worker_factory=ReviewWorker, more_factory=MoreWorker):
        super().__init__(parent)
        self.text, self.start, self.end = text, start, end
        self.project, self.chapter = project, chapter
        self.passage = text[start:end]
        self.state = ExpansionState(self.passage)
        self.replacement: Optional[str] = None
        self._worker_factory, self._more_factory = worker_factory, more_factory
        self._worker = self._more_worker = None
        self._llm = self._ctx = self._voice = None
        self.setWindowTitle("Overly descriptive?")
        self.resize(860, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Passage</b> — overly descriptive statements are "
                                "highlighted"))
        self.passage_view = QTextEdit()
        self.passage_view.setReadOnly(True)
        self.passage_view.setPlainText(self.passage)
        self.passage_view.setMaximumHeight(120)
        layout.addWidget(self.passage_view)
        self.panel = OverdescriptionPanel(self)
        self.panel.accepted.connect(self._on_accepted)
        self.panel.more_requested.connect(self._on_more)
        layout.addWidget(self.panel, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        self.use_btn = QPushButton("Use These Changes")
        self.use_btn.setDefault(True)
        self.use_btn.setEnabled(False)
        self.use_btn.clicked.connect(self._use)
        buttons.addWidget(self.use_btn)
        layout.addLayout(buttons)
        self._run()

    def _run(self):
        # The word scan needs no model and takes milliseconds: show it at
        # once; the AI's review takes its place when it comes.
        try:
            scanned = od.scan(self.passage)
            self.panel.set_review(od.Review(scanned, error="checking"))
            highlight_flags(self.passage_view, self.passage, scanned)
            self._provisional = True
            self.panel.set_busy(self._scan_line() + " The AI is checking them…")
        except Exception as e:
            print(f"[overdescription] could not show the word scan: {e}")
            self.panel.set_busy("Starting…")
        worker = self._worker_factory(self.project, self.chapter, self.text, self.start,
                                      self.end)
        worker.progress.connect(self._progress)
        worker.done.connect(self._on_review)
        self._worker = worker
        start_worker(worker)

    _provisional = False

    def _scan_line(self) -> str:
        n = len(self.panel.review.flags) if self.panel.review is not None else 0
        if not n:
            return "The word scan found nothing."
        return (f"The word scan found {n} statement{'s' if n != 1 else ''} that may be overly "
                f"descriptive (highlighted).")

    def _progress(self, message: str):
        if self._provisional:
            message = f"{self._scan_line()} The AI is checking them: {message}"
        self.panel.set_busy(message)

    def _on_review(self, review, note: str):
        try:
            w = self._worker
            provisional, self._provisional = self._provisional, False
            if provisional and self.state.changed:
                # Keep the expansions already accepted; the model still
                # gives "More ideas".
                self._llm = getattr(w, "llm", None)
                self._ctx = getattr(w, "ctx", None)
                self._voice = getattr(w, "voice", None)
                if self._llm is not None and self._ctx is not None:
                    self.panel.can_ask_ai = True
                    self.panel._enable(self.panel.current_flag() is not None)
                    self.panel.status.setText("The AI's review is ready; your accepted "
                                              "changes are kept. Ask for more ideas below.")
                return
            self._llm = getattr(w, "llm", None)
            self._ctx = getattr(w, "ctx", None)
            self._voice = getattr(w, "voice", None)
            self.panel.set_review(review, can_ask_ai=self._llm is not None
                                  and self._ctx is not None)
            highlight_flags(self.passage_view, self.passage, review.flags)
        except Exception as e:         # an exception escaping a slot aborts PyQt6
            print(f"[overdescription] could not show the review: {e}")

    def _on_accepted(self, index: int, text: str):
        flag = self.panel.review.flags[index]
        if not self.state.apply(index, flag, text):
            self.panel.status.setText("That statement isn't in the passage any more.")
            return
        if text != flag.text:
            log_accepted(self.project, flag.text, text)
        self.panel.mark_applied(index, None if text == flag.text else text)
        self.passage_view.setExtraSelections([])
        self.passage_view.setPlainText(self.state.text)
        self.use_btn.setEnabled(self.state.changed)

    def _on_more(self, index: int, note: str):
        flag = self.panel.review.flags[index]
        worker = self._more_factory(self._llm, self._ctx, flag, index, self._voice, note)
        worker.done.connect(self.panel.add_expansions)
        self._more_worker = worker
        start_worker(worker)

    def _use(self):
        if self.state.changed:
            self.replacement = self.state.text
            self.accept()

    def done(self, code: int) -> None:
        for w, slot in ((self._worker, self._on_review),
                        (self._more_worker, self.panel.add_expansions)):
            if w is not None:
                try:
                    w.done.disconnect(slot)
                except TypeError:
                    pass
        super().done(code)


def _short(text: str, n: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"
