"""Suggestions dialog: a critique of the highlighted passage with three
rewrites the writer can drop into the chapter."""

from __future__ import annotations

import html
from typing import Any, Optional, Set

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSplitter, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt

from src.ai.passage_critique import PassageCritique, build_context, critique_passage

# A QThread destroyed while running aborts the app, so running workers are
# kept here until they finish even if their dialog is closed.
_RUNNING: Set["SuggestionWorker"] = set()


def _project_path(project: Any) -> str:
    return str(getattr(project, "project_path", "") or "") if project is not None else ""


def _build_llm():
    from src.ai.task_llm import build_critique_llm, build_default_llm, no_model_message
    llm = build_critique_llm() or build_default_llm()
    return llm, ("" if llm is not None else no_model_message())


def _project_search(project: Any):
    """``query → text`` over the project's notes, or None."""
    try:
        from src.ai.enhanced_rag import EnhancedRAGSystem
        from src.ai.semantic_search import SearchMethod
        rag = EnhancedRAGSystem(project=project)
        rag.rebuild_index()
        return lambda query: rag.get_context_for_ai(
            query=query, max_tokens=500, method=SearchMethod.HYBRID)
    except Exception as e:
        print(f"[suggestions] project search unavailable: {e}")
        return None


class SuggestionWorker(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(object, str)          # PassageCritique | None, error

    def __init__(self, project, chapter, text: str, start: int, end: int, focus: str,
                 llm_factory=_build_llm, search_factory=_project_search):
        super().__init__()
        self.args = (project, chapter, text, start, end)
        self.focus = focus
        self.llm_factory, self.search_factory = llm_factory, search_factory

    def run(self):
        try:
            project, chapter, text, start, end = self.args
            self.progress.emit("Loading the model…")
            llm, error = self.llm_factory()
            if llm is None:
                self.done.emit(None, error)
                return
            from src.ai.chapter_analysis_agent import is_local_llm
            self.progress.emit("Gathering characters, world and plot…")
            search = self.search_factory(project) if project is not None else None
            from src.ai.rewrite_quality import examples_prompt
            from src.ai.writer_voice import project_voice
            voice = project_voice(project, chapter, text, selection=text[start:end])
            examples = examples_prompt(text[start:end], _project_path(project))
            ctx = build_context(project, chapter, text, start, end,
                                compact=is_local_llm(llm), related=search,
                                voice=voice, examples=examples)
            result = critique_passage(llm, ctx, self.focus, self.progress.emit, voice=voice)
            if result.empty:
                self.done.emit(None, "The model's reply couldn't be read as a critique. "
                                     "Try again, or pick another model in Settings.")
                return
            self.done.emit(result, "")
        except Exception as e:
            self.done.emit(None, f"Couldn't get suggestions: {e}")


class PassageCritiqueDialog(QDialog):
    """Shows what works, what doesn't, and three rewrites. ``replacement``
    holds the chosen (possibly edited) rewrite after Accept."""

    def __init__(self, text: str, start: int, end: int, project=None, chapter=None,
                 parent=None, selection: tuple = None, worker_factory=SuggestionWorker):
        super().__init__(parent)
        self.text, self.start, self.end = text, start, end
        self.ratings: dict = {}              # suggestion index → rating
        self.project, self.chapter = project, chapter
        self.passage = text[start:end]
        self.replacement: Optional[str] = None
        self.result: Optional[PassageCritique] = None
        self._worker_factory = worker_factory
        self._worker: Optional[SuggestionWorker] = None
        self.setWindowTitle("Suggestions")
        self.resize(900, 720)
        self._build_ui(selection)
        self._generate()

    # ── UI ───────────────────────────────────────────────────────────

    def _build_ui(self, selection):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Passage</b>"))
        self.passage_view = QTextEdit()
        self.passage_view.setReadOnly(True)
        self.passage_view.setPlainText(self.passage)
        self.passage_view.setMaximumHeight(110)
        layout.addWidget(self.passage_view)
        self.expanded_label = QLabel(self._expansion_note(selection))
        self.expanded_label.setWordWrap(True)
        self.expanded_label.setStyleSheet("color: #666; font-size: 11px;")
        self.expanded_label.setVisible(bool(self.expanded_label.text()))
        layout.addWidget(self.expanded_label)

        focus_row = QHBoxLayout()
        focus_row.addWidget(QLabel("Focus (optional):"))
        self.focus_edit = QLineEdit()
        self.focus_edit.setPlaceholderText("e.g. more tension, Mara's voice, less exposition")
        self.focus_edit.returnPressed.connect(self._generate)
        focus_row.addWidget(self.focus_edit, 1)
        self.regenerate_btn = QPushButton("↻ Regenerate")
        self.regenerate_btn.clicked.connect(self._generate)
        focus_row.addWidget(self.regenerate_btn)
        layout.addLayout(focus_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #555; font-style: italic;")
        layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.discussion = QTextBrowser()
        self.discussion.setOpenExternalLinks(False)
        splitter.addWidget(self.discussion)

        lower = QWidget()
        lower_layout = QHBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        self.suggestion_list = QListWidget()
        self.suggestion_list.setMaximumWidth(260)
        self.suggestion_list.currentRowChanged.connect(self._show_suggestion)
        lower_layout.addWidget(self.suggestion_list)
        right = QVBoxLayout()
        self.why_label = QLabel("")
        self.why_label.setWordWrap(True)
        self.why_label.setStyleSheet("color: #444;")
        right.addWidget(self.why_label)
        self.notes_label = QLabel("")
        self.notes_label.setWordWrap(True)
        self.notes_label.setStyleSheet("color: #b45309; font-size: 11px;")
        right.addWidget(self.notes_label)
        self.preview_edit = QTextEdit()
        self.preview_edit.setPlaceholderText("Pick a suggestion — you can edit it before using it.")
        self.preview_edit.textChanged.connect(self._update_changes)
        right.addWidget(self.preview_edit, 1)
        right.addWidget(QLabel("<small>Changes from your text:</small>"))
        self.changes_view = QTextBrowser()
        self.changes_view.setMaximumHeight(110)
        right.addWidget(self.changes_view)
        rate_row = QHBoxLayout()
        rate_row.addWidget(QLabel("Rate:"))
        self.rate_buttons = {}
        for value, label in (("excellent", "★ Excellent"), ("good", "Good"),
                             ("poor", "Poor"), ("bad", "Bad")):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setEnabled(False)
            btn.setToolTip("Ratings teach Suggestions and Rephrase your taste, and become "
                           "training data (when data collection is on in Settings).")
            btn.clicked.connect(lambda _=False, v=value: self._rate(v))
            rate_row.addWidget(btn)
            self.rate_buttons[value] = btn
        self.avoid_btn = QPushButton("🚫 Avoid a phrase…")
        self.avoid_btn.setToolTip("Select a phrase in the suggestion you never want to see "
                                  "again. Suggestions and Rephrase will avoid it and replace "
                                  "rewrites that use it.")
        self.avoid_btn.clicked.connect(self._avoid_phrase)
        rate_row.addWidget(self.avoid_btn)
        rate_row.addStretch()
        self.rating_status = QLabel("")
        self.rating_status.setStyleSheet("color: #666; font-size: 11px;")
        rate_row.addWidget(self.rating_status)
        right.addLayout(rate_row)
        lower_layout.addLayout(right, 1)
        splitter.addWidget(lower)
        splitter.setSizes([300, 320])
        layout.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Close")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.use_btn = QPushButton("Use This Suggestion")
        self.use_btn.setDefault(True)
        self.use_btn.setEnabled(False)
        self.use_btn.clicked.connect(self._use_selected)
        buttons.addWidget(self.use_btn)
        layout.addLayout(buttons)

    def _expansion_note(self, selection) -> str:
        if not selection:
            return ""
        s, e = selection
        added_before = self.text[self.start:s].strip()
        added_after = self.text[e:self.end].strip()
        if not (added_before or added_after):
            return ""
        bits = []
        if added_before:
            bits.append(f"the start of the sentence (“{_short(added_before)}”)")
        if added_after:
            bits.append(f"the end of the sentence (“{_short(added_after)}”)")
        return "Your highlight was widened to whole sentences: added " + " and ".join(bits) + "."

    # ── Running ──────────────────────────────────────────────────────

    def _generate(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self.regenerate_btn.setEnabled(False)
        self.use_btn.setEnabled(False)
        self.status_label.setText("Starting…")
        worker = self._worker_factory(self.project, self.chapter, self.text, self.start,
                                      self.end, self.focus_edit.text())
        worker.progress.connect(self.status_label.setText)
        worker.done.connect(self._on_done)
        _RUNNING.add(worker)
        worker.finished.connect(lambda w=worker: _RUNNING.discard(w))
        self._worker = worker
        worker.start()

    def _on_done(self, result, error: str):
        try:
            self.regenerate_btn.setEnabled(True)
            if result is None:
                self.status_label.setText("")
                self.discussion.setHtml(f"<p style='color:#b00020'>{html.escape(error)}</p>")
                return
            self._show_result(result)
        except Exception as e:      # an exception escaping a slot aborts PyQt6
            print(f"[suggestions] could not show the result: {e}")

    def _show_result(self, result: PassageCritique):
        self.result = result
        count = len(result.suggestions)
        self.status_label.setText(
            "" if count >= 3 else f"The model gave {count} suggestion(s) — Regenerate for more.")
        self.discussion.setHtml(self._discussion_html(result))
        self.ratings = {}
        self.suggestion_list.clear()
        for i, s in enumerate(result.suggestions, 1):
            fit = f" · voice {s.voice_fit:.0%}" if s.voice_fit is not None else ""
            flag = " ⚠" if s.notes else ""
            item = QListWidgetItem(f"Suggestion {i}{fit}{flag}\n{_short(s.text, 70)}")
            item.setToolTip(s.why or s.text[:300])
            self.suggestion_list.addItem(item)
        if result.suggestions:
            self.suggestion_list.setCurrentRow(0)

    @staticmethod
    def _discussion_html(result: PassageCritique) -> str:
        def section(title, items, color, mark):
            if not items:
                return ""
            rows = "".join(f"<li>{html.escape(i)}</li>" for i in items)
            return f"<h3 style='color:{color}'>{mark} {title}</h3><ul>{rows}</ul>"
        body = (section("What works", result.works, "#2e7d32", "✓")
                + section("What doesn't work", result.issues, "#c62828", "✗")
                + section("Order and flow", result.order, "#1d4ed8", "⇅"))
        return body or "<p><i>No discussion — see the suggestions below.</i></p>"

    def _show_suggestion(self, row: int):
        if not self.result or not (0 <= row < len(self.result.suggestions)):
            return
        s = self.result.suggestions[row]
        self.preview_edit.setPlainText(s.text)
        self.why_label.setText(f"<b>Why:</b> {html.escape(s.why)}" if s.why else "")
        self.notes_label.setText("⚠ This rewrite " + "; ".join(s.notes) + "." if s.notes else "")
        current = self.ratings.get(row, "")
        for value, btn in self.rate_buttons.items():
            btn.setEnabled(True)
            btn.setChecked(value == current)
        self.rating_status.setText("")
        self.use_btn.setEnabled(True)

    def _update_changes(self):
        from src.ai.rewrite_quality import diff_html
        text = self.preview_edit.toPlainText()
        self.changes_view.setHtml(diff_html(self.passage, text) if text.strip() else "")

    def _log(self, output: str, rating: str, accepted: bool) -> bool:
        from src.ai.rewrite_quality import log_rated_rewrite
        genre = getattr(getattr(self.project, "prose_profile", None), "genre", "") or ""
        return log_rated_rewrite(self.passage, output, rating, accepted=accepted,
                                 project_path=_project_path(self.project),
                                 before=self.text[max(0, self.start - 500):self.start],
                                 after=self.text[self.end:self.end + 500], genre=genre)

    def _avoid_phrase(self, _checked: bool = False, phrase: Optional[str] = None):
        from src.ai.rewrite_quality import add_avoid_phrase
        if phrase is None:
            phrase = self.preview_edit.textCursor().selectedText().strip()
        if not phrase:
            from PyQt6.QtWidgets import QInputDialog
            phrase, ok = QInputDialog.getText(
                self, "Avoid a phrase", "Phrase Suggestions and Rephrase should never use:")
            if not ok:
                return
        try:
            added = add_avoid_phrase(phrase)
        except Exception as e:
            self.rating_status.setText(f"Couldn't save: {e}")
            return
        self.rating_status.setText(f"Won't suggest “{phrase.strip()}” again." if added
                                   else "Already avoided (or too short).")

    def _rate(self, value: str):
        row = self.suggestion_list.currentRow()
        if not self.result or not (0 <= row < len(self.result.suggestions)):
            return
        self.ratings[row] = value
        for v, btn in self.rate_buttons.items():
            btn.setChecked(v == value)
        saved = self._log(self.preview_edit.toPlainText().strip(), value,
                          accepted=value in ("excellent", "good"))
        self.rating_status.setText("Saved." if saved else
                                   "Noted. Turn on data collection in Settings to keep ratings.")

    def _use_selected(self):
        text = self.preview_edit.toPlainText().strip()
        if not text:
            return
        self.replacement = text
        rating = self.ratings.get(self.suggestion_list.currentRow(), "")
        if rating not in ("poor", "bad"):
            self._log(text, rating or "good", accepted=True)
        self.accept()

    def done(self, code: int) -> None:
        # The worker keeps running (in _RUNNING) if it hasn't finished; its
        # result is simply ignored.
        if self._worker is not None:
            try:
                self._worker.done.disconnect(self._on_done)
            except TypeError:
                pass
        super().done(code)


def _short(text: str, n: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"
