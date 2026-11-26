"""Suggestions dialog: a critique of the highlighted passage with three
rewrites the writer can drop into the chapter."""

from __future__ import annotations

import html
from typing import Any, Optional, Set

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QFrame, QPushButton, QScrollArea, QSplitter, QTabWidget, QTextBrowser, QTextEdit,
    QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt

from src.ai.passage_critique import (
    PassageCritique, Suggestion, build_context, critique_passage)

EXPANDED_ANGLE = "your text, expanded"

# A QThread destroyed while running aborts the app, so running workers are
# kept here until they finish even if their dialog is closed.
# Running workers are kept alive by the shared helper (R.2); the name stays
# for existing imports.
from src.ui import background  # noqa: E402

_RUNNING = background._RUNNING


_RATE_TIP = ("Ratings teach Suggestions and Rephrase your taste, and become "
             "training data (when data collection is on in Settings).")


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
    # Overly descriptive statements (overdescription.Review), sent after
    # ``done``; the word scan alone when there's no model.
    overdescribed = pyqtSignal(object)

    def __init__(self, project, chapter, text: str, start: int, end: int, focus: str,
                 llm_factory=_build_llm, search_factory=_project_search, review: bool = True):
        super().__init__()
        self.args = (project, chapter, text, start, end)
        self.focus = focus
        self.llm_factory, self.search_factory = llm_factory, search_factory
        self.llm = self.ctx = self.voice = None
        # False when the overly-descriptive review already ran (the Improve
        # window's Expand tab, D.2b): no second model call for it.
        self.review = review

    def run(self):
        try:
            self._critique()
        finally:
            if self.review:
                self._overdescription()

    def _overdescription(self):
        from src.ai import overdescription as od
        project, chapter, text, start, end = self.args
        try:
            if self.ctx is None or self.llm is None:
                review = od.Review(od.scan(text[start:end]), error="no model")
            else:
                review = od.review_passage(self.llm, self.ctx, self.voice,
                                           progress=self.progress.emit)
        except Exception as e:
            print(f"[suggestions] overly-descriptive review failed: {e}")
            review = od.Review(od.scan(text[start:end]), error=str(e))
        self.overdescribed.emit(review)

    def _critique(self):
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
            self.examples_from = {}
            examples = examples_prompt(text[start:end], _project_path(project), before=text[:start],
                                       after=text[end:], note=self.examples_from)
            ctx = build_context(project, chapter, text, start, end,
                                compact=is_local_llm(llm), related=search,
                                voice=voice, examples=examples)
            # Kept for the conversation that follows (and the
            # overly-descriptive review, even if the critique fails).
            self.llm, self.ctx, self.voice = llm, ctx, voice
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
                 parent=None, selection: tuple = None, worker_factory=SuggestionWorker,
                 focus: str = ""):
        super().__init__(parent)
        self.text, self.start, self.end = text, start, end
        self.turns: list = []               # the conversation (rewrite_chat.ChatTurn)
        self._chat_worker = None
        self._llm = self._ctx = self._voice = None
        self.ratings: dict = {}              # suggestion index → rating
        self.project, self.chapter = project, chapter
        self.passage = text[start:end]
        self.replacement: Optional[str] = None
        self.result: Optional[PassageCritique] = None
        self._worker_factory = worker_factory
        self._worker: Optional[SuggestionWorker] = None
        self.over_review = None                 # overdescription.Review
        self._expansions = None                 # overdescription_panel.ExpansionState
        self._more_worker = None
        self._over_llm = self._over_ctx = self._over_voice = None
        self._result_status = ""
        self.setWindowTitle("Suggestions")
        self._build_ui(selection)
        self._fit_to_screen(900, 760)
        if focus:
            self.focus_edit.setText(focus)   # e.g. the Companion's fix or note
        self._generate()

    # ── UI ───────────────────────────────────────────────────────────

    def _fit_to_screen(self, width: int, height: int):
        from src.ui.ui_kit import fit_to_screen
        fit_to_screen(self, width, height)

    def _build_ui(self, selection):
        # Everything but the Close / Use buttons scrolls, so a small window
        # (or a laptop screen) never squeezes the sections to nothing.
        from src.ui.ui_kit import scrollable
        outer = QVBoxLayout(self)
        content = QWidget()
        self.scroll_area = scrollable(content)
        outer.addWidget(self.scroll_area, 1)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 6, 0)
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

        splitter = self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.discussion = QTextBrowser()
        self.discussion.setOpenExternalLinks(False)
        from src.ui.overdescription_panel import OverdescriptionPanel
        self.over_panel = OverdescriptionPanel()
        self.over_panel.set_busy("Looking for overly descriptive statements…")
        self.over_panel.accepted.connect(self._accept_expansion)
        self.over_panel.more_requested.connect(self._more_expansions)
        self.top_tabs = QTabWidget()
        self.top_tabs.addTab(self.discussion, "Critique")
        self.top_tabs.addTab(self.over_panel, "Overly descriptive")
        self.top_tabs.setTabToolTip(
            1, "Statements that tell instead of show (words like “too” and “almost” are "
               "clues), with ways to expand them in your voice. Accepted expansions build "
               "the version at the top of the suggestions.")
        self.top_tabs.currentChanged.connect(self._make_room_for_tab)
        splitter.addWidget(self.top_tabs)

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
            btn.setToolTip(_RATE_TIP)
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
        from src.ui.rewrite_chat_panel import ConversationPanel
        chat_box = QWidget()
        chat_layout = QVBoxLayout(chat_box)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.addWidget(QLabel("<b>Talk it through</b> — ask why, give direction, or "
                                     "ask for changes; new versions go to the top of the list."))
        self.chat = ConversationPanel("e.g. why is [2] out of order? · combine 1 and 3 · "
                                      "keep Tobin rambling")
        self.chat.message_sent.connect(self._send_message)
        from src.ui.rewrite_chat_panel import remember
        self.chat.remember_requested.connect(
            lambda text: remember(self.chat, self.project, text, "suggestions"))
        self.chat.set_busy(True, "")
        chat_layout.addWidget(self.chat)
        splitter.addWidget(chat_box)
        # Each part keeps a usable height; below that the dialog scrolls.
        self.top_tabs.setMinimumHeight(200)
        lower.setMinimumHeight(280)
        chat_box.setMinimumHeight(180)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([240, 300, 200])
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
        outer.addLayout(buttons)

    def _make_room_for_tab(self, index: int):
        """The Overly descriptive tab holds a list, a statement, ways to
        expand it and an editor — give it the room it needs while it's open
        (the window scrolls rather than squeezing it)."""
        over = self.top_tabs.widget(index) is self.over_panel
        want = (self.over_panel.minimumHeight() + self.top_tabs.tabBar().sizeHint().height()
                + 8) if over else 200
        self.top_tabs.setMinimumHeight(want)
        sizes = self.main_splitter.sizes()
        if over and sizes and sizes[0] < want:
            sizes[0] = want
            self.main_splitter.setSizes(sizes)

    def _expansion_note(self, selection) -> str:
        return widened_note(self.text, self.start, self.end, selection)

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
        if hasattr(worker, "overdescribed"):
            worker.overdescribed.connect(self._on_overdescribed)
        self.over_panel.set_busy("Looking for overly descriptive statements…")
        self._worker = worker
        background.start(worker)

    def _on_done(self, result, error: str):
        try:
            self.regenerate_btn.setEnabled(True)
            worker = self._worker
            self._llm = getattr(worker, "llm", None)
            self._ctx = getattr(worker, "ctx", None)
            self._voice = getattr(worker, "voice", None)
            if result is None:
                self.status_label.setText("")
                self._result_status = ""
                self.discussion.setHtml(f"<p style='color:#b00020'>{html.escape(error)}</p>")
                return
            self._show_result(result)
            learned = (getattr(worker, "examples_from", None) or {}).get("from", "")
            for btn in self.rate_buttons.values():      # where they came from (V.4)
                btn.setToolTip(_RATE_TIP + (f"\nThese suggestions learned from rewrites you "
                                            f"rated, {learned}." if learned else ""))
        except Exception as e:      # an exception escaping a slot aborts PyQt6
            print(f"[suggestions] could not show the result: {e}")

    def _show_result(self, result: PassageCritique):
        self.result = result
        count = len(result.suggestions)
        self._result_status = (
            "" if count >= 3 else f"The model gave {count} suggestion(s) — Regenerate for more.")
        self.status_label.setText(self._result_status)
        if self._expansions is not None and self._expansions.changed:
            self._put_expanded_version()
        self.discussion.setHtml(self._discussion_html(result))
        self._fill_suggestion_list(0)
        # A fresh critique starts a fresh conversation.
        self.turns = []
        self.chat.clear()
        self.chat.set_busy(self._llm is None or self._ctx is None, "")

    def _fill_suggestion_list(self, select: int = 0) -> None:
        self.ratings = {}
        self.suggestion_list.clear()
        for i, s in enumerate(self.result.suggestions, 1):
            fit = f" · voice {s.voice_fit:.0%}" if s.voice_fit is not None else ""
            flag = " ⚠" if s.notes else ""
            tag = " · revised" if s.angle.startswith("revised") else ""
            label = "Your text, expanded" if s.angle == EXPANDED_ANGLE else f"Suggestion {i}"
            item = QListWidgetItem(f"{label}{tag}{fit}{flag}\n{_short(s.text, 70)}")
            item.setToolTip(s.why or s.text[:300])
            self.suggestion_list.addItem(item)
        if self.result.suggestions:
            self.suggestion_list.setCurrentRow(select)

    # ── Overly descriptive statements ───────────────────────────────

    def _on_overdescribed(self, review) -> None:
        try:
            from src.ui.overdescription_panel import ExpansionState, highlight_flags
            if self._expansions is not None and self._expansions.changed:
                # Regenerate: keep the expansions the writer already accepted.
                if self.status_label.text().startswith("Looking for overly"):
                    self.status_label.setText(self._result_status)
                return
            self.over_review = review
            self._expansions = ExpansionState(self.passage)
            worker = self._worker
            self._over_llm = getattr(worker, "llm", None)
            self._over_ctx = getattr(worker, "ctx", None)
            self._over_voice = getattr(worker, "voice", None)
            self.over_panel.set_review(review, can_ask_ai=self._over_llm is not None
                                       and self._over_ctx is not None)
            highlight_flags(self.passage_view, self.passage, review.flags)
            count = len(review.flags)
            self.top_tabs.setTabText(1, f"Overly descriptive ({count})" if count
                                     else "Overly descriptive")
            if self.status_label.text().startswith("Looking for overly"):
                self.status_label.setText(self._result_status)
            if self.result is None and count:
                self.top_tabs.setCurrentIndex(1)     # no critique to show
        except Exception as e:      # an exception escaping a slot aborts PyQt6
            print(f"[suggestions] could not show overly descriptive statements: {e}")

    def _accept_expansion(self, index: int, text: str) -> None:
        from src.ui.overdescription_panel import log_accepted
        if self.over_review is None or not (0 <= index < len(self.over_review.flags)):
            return
        flag = self.over_review.flags[index]
        if not self._expansions.apply(index, flag, text):
            self.over_panel.status.setText("That statement isn't in the passage any more.")
            return
        if text != flag.text:
            log_accepted(self.project, flag.text, text)
        self.over_panel.mark_applied(
            index, None if text == flag.text else text,
            "Accepted — see “Your text, expanded” at the top of the suggestions.")
        self._put_expanded_version()

    def _put_expanded_version(self) -> None:
        """Keep one suggestion holding the passage with every accepted
        expansion, at the top of the list."""
        if self.result is None:
            self.result = PassageCritique()
        rest = [s for s in self.result.suggestions if s.angle != EXPANDED_ANGLE]
        if self._expansions.changed:
            self.result.suggestions = [expanded_suggestion(self._expansions.text)] + rest
        else:
            self.result.suggestions = rest
        self._fill_suggestion_list(0)
        if not self.result.suggestions:
            self.preview_edit.clear()
            self.use_btn.setEnabled(False)

    def _more_expansions(self, index: int, note: str) -> None:
        from src.ui.overdescription_panel import MoreWorker, start_worker
        if self._over_llm is None or self.over_review is None:
            return
        worker = MoreWorker(self._over_llm, self._over_ctx, self.over_review.flags[index],
                            index, self._over_voice, note)
        worker.done.connect(self.over_panel.add_expansions)
        self._more_worker = worker
        start_worker(worker)

    # ── Conversation ─────────────────────────────────────────────────

    def _chat_context(self):
        return chat_context(self._ctx, self.result)

    def _send_message(self, message: str) -> None:
        if self._llm is None or self._ctx is None or self.result is None:
            return
        from src.ai.rewrite_chat import ChatTurn
        from src.ui.rewrite_chat_panel import run_turn
        self.chat.add_message("You", message)
        self.chat.set_busy(True, "Thinking…")
        versions = [(s.angle, s.text) for s in self.result.suggestions]
        turn = chat_turn_fn(self._llm, self._ctx, self._voice, self.result, versions,
                            list(self.turns), message)
        self.turns.append(ChatTurn("author", message))
        run_turn(self, turn, self._on_reply)

    def _on_reply(self, result, error: str) -> None:
        from src.ai.rewrite_chat import ChatTurn
        self.chat.set_busy(False, "")
        if result is None:
            self.chat.add_message("Editor", error)
            return
        self.chat.add_message("Editor", result.reply)
        from src.ui.rewrite_chat_panel import propose_memory
        author = next((t.text for t in reversed(self.turns) if t.role == "author"), "")
        propose_memory(self.chat, self.project, self._llm, author, result.reply, "suggestions")
        note = result.reply
        if result.versions:
            for v in result.versions:
                v.angle = "revised" + (f": {v.angle}" if v.angle else "")
            self.result.suggestions = result.versions + self.result.suggestions
            self._fill_suggestion_list(0)
            count = len(result.versions)
            self.chat.status.setText(f"{count} new version{'s' if count != 1 else ''} at the top "
                                     f"of the list.")
            note += "\n" + "\n".join(f"(new version: {_short(v.text, 120)})" for v in result.versions)
        self.turns.append(ChatTurn("editor", note))

    @staticmethod
    def _discussion_html(result: PassageCritique) -> str:
        return discussion_html(result)

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
        return log_rating(self.project, self.text, self.start, self.end, output, rating,
                          accepted)

    def _avoid_phrase(self, _checked: bool = False, phrase: Optional[str] = None):
        message = avoid_phrase(self, self.preview_edit, phrase)
        if message is not None:
            self.rating_status.setText(message)

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
        if self._worker is not None and hasattr(self._worker, "overdescribed"):
            try:
                self._worker.overdescribed.disconnect(self._on_overdescribed)
            except TypeError:
                pass
        for w in (self._chat_worker, self._more_worker):
            if w is not None:
                try:
                    w.done.disconnect()
                except TypeError:
                    pass
        super().done(code)


def _short(text: str, n: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


# ── Shared with the Improve window (D.2b) ─────────────────────────────
# Moved out of PassageCritiqueDialog unchanged, so the old window and the
# Improve window's Suggestions tab do exactly the same thing.

def widened_note(text: str, start: int, end: int, selection) -> str:
    """"Your highlight was widened to whole sentences: added …", or ""."""
    if not selection:
        return ""
    s, e = selection
    added_before = text[start:s].strip()
    added_after = text[e:end].strip()
    if not (added_before or added_after):
        return ""
    bits = []
    if added_before:
        bits.append(f"the start of the sentence (“{_short(added_before)}”)")
    if added_after:
        bits.append(f"the end of the sentence (“{_short(added_after)}”)")
    return "Your highlight was widened to whole sentences: added " + " and ".join(bits) + "."


def expanded_suggestion(text: str) -> Suggestion:
    """The passage with every accepted expansion, as a suggestion."""
    return Suggestion(text, "Your passage with the expansions you accepted.",
                      angle=EXPANDED_ANGLE)


def discussion_html(result: PassageCritique) -> str:
    def section(title, items, color, mark):
        if not items:
            return ""
        rows = "".join(f"<li>{html.escape(i)}</li>" for i in items)
        return f"<h3 style='color:{color}'>{mark} {title}</h3><ul>{rows}</ul>"
    body = (section("What works", result.works, "#2e7d32", "✓")
            + section("What doesn't work", result.issues, "#c62828", "✗")
            + section("Dialogue", getattr(result, "dialogue", []), "#7c3aed", "💬")
            + section("Order and flow", result.order, "#1d4ed8", "⇅"))
    return body or "<p><i>No discussion — see the suggestions below.</i></p>"


def chat_context(ctx, result):
    """(context blocks, rules) for Talk it through about a critique."""
    from src.ai import passage_critique as pc
    r = result
    critique = []
    for title, items in (("What works", r.works), ("What doesn't work", r.issues),
                         ("Dialogue", getattr(r, "dialogue", [])), ("Order and flow", r.order)):
        if items:
            critique.append(f"{title}:\n" + "\n".join(f"- {i}" for i in items))
    blocks = [(t, b) for t, b in ctx.sections() if b]
    blocks.append(("THE SCENE (the passage is marked)", ctx.scene(1500)))
    from src.ai.event_order import events_prompt
    timeline = events_prompt(ctx.passage)
    if timeline:
        head, _, body = timeline.partition(":\n")
        blocks.append((head, body))
    if ctx.speakers:
        blocks.append(("WHO SPEAKS EACH LINE", ctx.speakers))
    if critique:
        blocks.append(("YOUR CRITIQUE OF THE PASSAGE", "\n\n".join(critique)))
    rules = pc._SCOPE_RULES + "\n" + pc._REWRITE_RULES + "- " + pc._avoid_line()
    return blocks, rules


def chat_turn_fn(llm, ctx, voice, result, versions, turns, message):
    """The callable that runs one Talk it through turn (in a worker)."""
    from src.ai import passage_critique as pc
    from src.ai.rewrite_chat import chat_turn
    blocks, rules = chat_context(ctx, result)

    def check(found):
        return pc._check_all(ctx, found, voice, message)

    def turn():
        return chat_turn(llm, system=pc.SYSTEM_PROMPT, context=blocks, passage=ctx.passage,
                         versions=versions, turns=turns, message=message, check=check,
                         rules=rules)
    return turn


def log_rating(project, text: str, start: int, end: int, output: str, rating: str,
               accepted: bool, style: str = "suggestion") -> bool:
    """A rated rewrite of ``text[start:end]``, saved as Suggestions saves it
    (when data collection is on)."""
    from src.ai.rewrite_quality import log_rated_rewrite
    genre = getattr(getattr(project, "prose_profile", None), "genre", "") or ""
    return log_rated_rewrite(text[start:end], output, rating, accepted=accepted,
                             project_path=_project_path(project), style=style,
                             before=text[max(0, start - 500):start],
                             after=text[end:end + 500], genre=genre)


def avoid_phrase(parent, edit, phrase: Optional[str] = None) -> Optional[str]:
    """🚫 Avoid a phrase: the phrase selected in ``edit``, or asked for.
    The message to show, or None when the writer cancelled."""
    from src.ai.rewrite_quality import add_avoid_phrase
    if phrase is None:
        phrase = edit.textCursor().selectedText().strip()
    if not phrase:
        from PyQt6.QtWidgets import QInputDialog
        phrase, ok = QInputDialog.getText(
            parent, "Avoid a phrase", "Phrase Suggestions and Rephrase should never use:")
        if not ok:
            return None
    try:
        added = add_avoid_phrase(phrase)
    except Exception as e:
        return f"Couldn't save: {e}"
    return (f"Won't suggest “{phrase.strip()}” again." if added
            else "Already avoided (or too short).")
