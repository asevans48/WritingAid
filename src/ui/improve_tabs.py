"""The Improve window's tabs: 💡 Suggestions, 📝 Critique and 🔍 Expand
(piece D.2b). ✨ Rephrase (D.2c) is in ``improve_rephrase``.

Each tab is a small object the window (``improve_window.ImproveWindow``)
asks for: ``key``, ``title``, ``tip``, ``widget`` (its own options, at the
top), ``start()`` (run the first time it is shown), ``rate(version, value,
text)``, ``accept(version, text)`` (returns the tool whose call puts the
text in place), ``talk`` (its ``ConversationPanel``, or None) and
``stop()``.

Nothing here is new behaviour. Each tab runs the workers its old window
ran, with the model its old window used (``passage_critique_dialog``'s
``_build_llm``: the critique task model, else the default), and saves
ratings through the same calls with the same values (the old windows
themselves were deleted in D.12):

* Suggestions and Critique are one model call (``SuggestionWorker``), as
  in the old Suggestions window; that run also fills Expand, unless Expand
  already ran (no second call).
* Expand is ``OverdescriptionPanel`` with ``ReviewWorker`` and
  ``MoreWorker``, as in the old Overly descriptive? window. Its ✓ Accept is called
  **Apply to passage** here, so the window has one ✓ Accept. Applied
  expansions are logged with ``log_accepted`` (style "expansion") and
  build "Your text, expanded". When Suggestions has not run, that version
  can be rated too, saved with style "expansion" (decision 16).
"""

from __future__ import annotations

import html
from typing import Dict, Optional

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QWidget

from src.ui import background
from src.ui.ui_kit import GAP, PALETTE, plain


def _disconnect(signal, slot=None) -> None:
    try:
        if slot is None:
            signal.disconnect()
        else:
            signal.disconnect(slot)
    except (TypeError, RuntimeError):
        pass


def _saved(saved: bool) -> str:
    return "Saved." if saved else "Noted. Turn on data collection in Settings to keep ratings."


# ── 💡 Suggestions ──────────────────────────────────────────────────────

class SuggestionsTab:
    key = "suggestions"
    status_key = "suggestions"
    title = "💡 Suggestions"
    tip = ("A critique of the passage and three rewrites, against your characters, world, "
           "plot and outline")

    def __init__(self, win, worker_factory=None):
        from src.ui.passage_critique_dialog import SuggestionWorker
        from src.ui.rewrite_chat_panel import ConversationPanel, remember
        self.win = win
        self.worker_factory = worker_factory or SuggestionWorker
        self.critique: Optional["CritiqueTab"] = None
        self.expand: Optional["ExpandTab"] = None
        self.started = False
        self.result = None                      # PassageCritique
        self.turns: list = []
        self.llm = self.ctx = self.voice = None
        self._worker = None
        self._chat_worker = None
        self.final_status: Optional[str] = None

        self.widget = QWidget()
        row = QHBoxLayout(self.widget)
        row.setContentsMargins(0, GAP, 0, GAP)
        row.addWidget(QLabel("Focus (optional):"))
        self.focus_edit = QLineEdit()
        self.focus_edit.setPlaceholderText("e.g. more tension, Mara's voice, less exposition")
        self.focus_edit.setToolTip("Return runs Suggestions again with this focus")
        self.focus_edit.returnPressed.connect(self.generate)
        row.addWidget(self.focus_edit, 1)
        self.regenerate_btn = plain(QPushButton("↻ Regenerate"))
        self.regenerate_btn.setAutoDefault(False)
        self.regenerate_btn.clicked.connect(self.generate)
        row.addWidget(self.regenerate_btn)

        self.talk = ConversationPanel("e.g. why is [2] out of order? · combine 1 and 3 · "
                                      "keep Tobin rambling")
        self.talk.message_sent.connect(self._send)
        self.talk.remember_requested.connect(
            lambda text: remember(self.talk, win.project, text, "suggestions"))
        self.talk.set_busy(True, "Talk it through opens once 💡 Suggestions has run.")

    # Running

    def start(self) -> None:
        if not self.started:
            self.generate()

    def running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def generate(self) -> None:
        if self.running():
            return
        self.started = True
        w = self.win
        self.regenerate_btn.setEnabled(False)
        self.final_status = None
        w.set_status(self.key, "Starting…")
        worker = self.worker_factory(w.project, w.chapter, w.text, w.start, w.end,
                                     self.focus_edit.text())
        # One review of overly descriptive statements per window.
        review = self.expand is not None and not self.expand.has_review()
        worker.review = review
        worker.progress.connect(lambda m: self.win.set_status(self.key, m))
        worker.done.connect(self._on_done)
        if review and hasattr(worker, "overdescribed"):
            self.expand.wait_for(worker)
        self._worker = worker
        background.start(worker)

    def _on_done(self, result, error: str) -> None:
        try:
            self.regenerate_btn.setEnabled(True)
            worker = self._worker
            self.llm = getattr(worker, "llm", None)
            self.ctx = getattr(worker, "ctx", None)
            self.voice = getattr(worker, "voice", None)
            if result is None:
                if self.critique is not None:
                    self.critique.show_error(error)
                self.final_status = html.escape(error) + self._fallback()
                self.win.set_status(self.key, self.final_status)
                return
            self._show_result(result)
            learned = (getattr(worker, "examples_from", None) or {}).get("from", "")
            from src.ui.improve_window import RATE_TIP
            tip = RATE_TIP + (f"\nThese suggestions learned from rewrites you rated, "
                              f"{learned}." if learned else "")
            self.win.set_rate_tip(self.key, tip)        # where they came from (V.4)
            self.win.set_rate_tip("expand", tip)
        except Exception as e:      # an exception escaping a slot aborts PyQt6
            print(f"[improve] could not show the suggestions: {e}")

    def review_done(self) -> None:
        """The overly-descriptive review that follows the run has finished:
        its progress gives way to the run's own line."""
        if self.final_status is not None:
            self.win.set_status(self.key, self.final_status)

    def _fallback(self) -> str:
        """With no model: what still works in this window (rule 1)."""
        links = []
        if "rephrase" in self.win.tab_objects:
            links.append("<a href='rephrase'>✨ Rephrase</a> still works (simpler rewrites)")
        if self.expand is not None:
            links.append("<a href='expand'>🔍 Expand</a> still shows the word scan (clues, not "
                         "proof)")
        return (" · " + " · ".join(links) + ".") if links else ""

    def _show_result(self, result) -> None:
        from src.ui.improve_window import Version
        self.result = result
        count = len(result.suggestions)
        self.final_status = ("" if count >= 3 else
                             f"The model gave {count} suggestion(s) — Regenerate for more.")
        self.win.set_status(self.key, self.final_status)
        if self.critique is not None:
            self.critique.show(result)
        self.win.replace_versions(self.key, [
            Version(s.text, self.key, kind="revised" if s.angle.startswith("revised")
                    else "suggestion", why=s.why, notes=list(s.notes), voice_fit=s.voice_fit,
                    angle=s.angle) for s in result.suggestions])
        # A fresh critique starts a fresh conversation.
        self.turns = []
        self.talk.clear()
        self.talk.set_busy(self.llm is None or self.ctx is None, "")

    # Talk it through

    def _send(self, message: str) -> None:
        if self.llm is None or self.ctx is None or self.result is None:
            return
        from src.ai.rewrite_chat import ChatTurn
        from src.ui.passage_critique_dialog import chat_turn_fn
        from src.ui.rewrite_chat_panel import run_turn
        self.talk.add_message("You", message)
        self.talk.set_busy(True, "Thinking…")
        # Numbered as the versions list shows them.
        versions = [(v.angle, v.text) for v in self.win.versions]
        turn = chat_turn_fn(self.llm, self.ctx, self.voice, self.result, versions,
                            list(self.turns), message)
        self.turns.append(ChatTurn("author", message))
        run_turn(self, turn, self._on_reply)

    def _on_reply(self, result, error: str) -> None:
        from src.ai.rewrite_chat import ChatTurn
        from src.ui.improve_window import Version, _short
        from src.ui.rewrite_chat_panel import propose_memory
        self.talk.set_busy(False, "")
        if result is None:
            self.talk.add_message("Editor", error)
            return
        self.talk.add_message("Editor", result.reply)
        author = next((t.text for t in reversed(self.turns) if t.role == "author"), "")
        propose_memory(self.talk, self.win.project, self.llm, author, result.reply,
                       "suggestions")
        note = result.reply
        if result.versions:
            new = []
            for v in result.versions:
                v.angle = "revised" + (f": {v.angle}" if v.angle else "")
                new.append(Version(v.text, self.key, kind="revised", why=v.why,
                                   notes=list(v.notes), voice_fit=v.voice_fit, angle=v.angle))
            self.result.suggestions = result.versions + self.result.suggestions
            self.win.add_versions(new)
            count = len(result.versions)
            self.talk.status.setText(f"{count} new version{'s' if count != 1 else ''} at the "
                                     f"top of the list.")
            note += "\n" + "\n".join(f"(new version: {_short(v.text, 120)})"
                                     for v in result.versions)
        self.turns.append(ChatTurn("editor", note))

    # Rating and accepting (the old Suggestions window's calls and values)

    def rate(self, version, value: str, text: str) -> str:
        from src.ui.passage_critique_dialog import log_rating
        w = self.win
        return _saved(log_rating(w.project, w.text, w.start, w.end, text, value,
                                 accepted=value in ("excellent", "good")))

    def accept(self, version, text: str) -> str:
        from src.ui.passage_critique_dialog import log_rating
        w = self.win
        if version.rating not in ("poor", "bad"):
            log_rating(w.project, w.text, w.start, w.end, text, version.rating or "good",
                       accepted=True)
        return self.key

    def stop(self) -> None:
        if self._worker is not None:
            _disconnect(self._worker.done, self._on_done)
        if self._chat_worker is not None:
            _disconnect(self._chat_worker.done)


# ── 📝 Critique ─────────────────────────────────────────────────────────

class CritiqueTab:
    """The critique Suggestions wrote: the same model call, its own tab."""
    key = "critique"
    status_key = "suggestions"
    title = "📝 Critique"
    tip = "What works, what doesn't, dialogue, order and flow: from the same reply as Suggestions"
    talk = None                       # Suggestions' conversation is shown

    def __init__(self, win, suggestions: SuggestionsTab):
        self.win, self.suggestions = win, suggestions
        self.widget = QTextBrowser()
        self.widget.setOpenExternalLinks(False)
        self.widget.setMinimumHeight(self.widget.fontMetrics().lineSpacing() * 8 + 12)
        self.widget.setPlaceholderText("The critique of the passage appears here with the "
                                       "suggestions.")
        self.discussion = self.widget

    def start(self) -> None:
        self.suggestions.start()

    def show(self, result) -> None:
        from src.ui.passage_critique_dialog import discussion_html
        self.discussion.setHtml(discussion_html(result))

    def show_error(self, error: str) -> None:
        self.discussion.setHtml(f"<p style='color:{PALETTE['error']}'>{html.escape(error)}</p>")

    def rate(self, version, value, text):          # its versions are Suggestions'
        return self.suggestions.rate(version, value, text)

    def accept(self, version, text):
        return self.suggestions.accept(version, text)

    def stop(self) -> None:
        pass


# ── 🔍 Expand (Overly descriptive?) ─────────────────────────────────────

class ExpandTab:
    key = "expand"
    status_key = "expand"
    title = "🔍 Expand"
    tip = ("Overly descriptive? Statements that tell instead of show (words like “too” and "
           "“almost” are clues), with ways to expand them in your voice")
    talk = None                       # Suggestions' conversation is shown

    def __init__(self, win, suggestions: SuggestionsTab, worker_factory=None,
                 more_factory=None):
        from src.ui.overdescription_panel import MoreWorker, OverdescriptionPanel, ReviewWorker
        self.win, self.suggestions = win, suggestions
        self.worker_factory = worker_factory or ReviewWorker
        self.more_factory = more_factory or MoreWorker
        self.started = False
        self.review = None                       # overdescription.Review
        self.state = None                        # ExpansionState
        self.llm = self.ctx = self.voice = None
        self._worker = self._more_worker = None
        self._waiting = None                     # the Suggestions run that will fill it
        self.provisional = False                 # the word scan, while the AI checks
        self.panel = OverdescriptionPanel()
        self.panel.accept_btn.setText("Apply to passage")
        self.panel.accept_btn.setToolTip("Put this in place of the statement, in “Your text, "
                                         "expanded” in the versions below")
        self.panel.accept_btn.setAutoDefault(False)
        for b in (self.panel.revert_btn, self.panel.more_btn):
            b.setAutoDefault(False)
        self.panel.accepted.connect(self._apply)
        self.panel.more_requested.connect(self._more)
        self.widget = self.panel

    def has_review(self) -> bool:
        # A review is here, or on its way (its own run, or a Suggestions run).
        return (self.review is not None or self._waiting is not None
                or self._worker is not None)

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        if self.has_review():
            return                                # Suggestions is filling it
        self._show_scan("The AI is checking them…")
        worker = self.worker_factory(self.win.project, self.win.chapter, self.win.text,
                                     self.win.start, self.win.end)
        worker.progress.connect(self._progress)
        worker.done.connect(self._on_review)
        self._worker = worker
        background.start(worker)

    def wait_for(self, worker) -> None:
        """A Suggestions run will send the review (one model call)."""
        self._waiting = worker
        self.panel.set_busy("Looking for overly descriptive statements…")
        worker.overdescribed.connect(self._from_suggestions)
        self._show_scan("The AI checks them once Suggestions is done…")

    # The word scan needs no model and takes milliseconds, so it is shown
    # at once; the AI's review takes its place when it comes (unless an
    # expansion has been applied by then, which is kept).

    def _show_scan(self, note: str) -> None:
        try:
            from src.ai import overdescription as od
            self._fill(od.Review(od.scan(self.win.passage), error="checking"), None, None, None)
            self.provisional = True
            self.panel.set_busy(f"{self._scan_line()} {note}")
        except Exception as e:     # an exception escaping a slot aborts PyQt6
            print(f"[improve] could not show the word scan: {e}")

    def _scan_line(self) -> str:
        n = len(self.review.flags) if self.review is not None else 0
        if not n:
            return "The word scan found nothing."
        return (f"The word scan found {n} statement{'s' if n != 1 else ''} that may be overly "
                f"descriptive (highlighted).")

    def _progress(self, message: str) -> None:
        if self.provisional:
            message = f"{self._scan_line()} The AI is checking them: {message}"
        self.panel.set_busy(message)

    def _from_suggestions(self, review) -> None:
        w, self._waiting = self._waiting, None
        self._fill(review, getattr(w, "llm", None), getattr(w, "ctx", None),
                   getattr(w, "voice", None))
        self.suggestions.review_done()
        # No critique to show (no model): the word scan is what helps, as the
        # old Suggestions window showed it.
        if self.suggestions.result is None and review is not None and review.flags \
                and self.win.tab_key() in ("suggestions", "critique"):
            self.win.select_tab(self.key)

    def _on_review(self, review, _note: str) -> None:
        w = self._worker
        self._fill(review, getattr(w, "llm", None), getattr(w, "ctx", None),
                   getattr(w, "voice", None))

    def _fill(self, review, llm, ctx, voice) -> None:
        try:
            from src.ui.overdescription_panel import ExpansionState
            if self.state is not None and self.state.changed:
                # Keep the expansions already applied; the model still
                # gives "More ideas".
                if self.provisional and llm is not None and ctx is not None:
                    self.llm, self.ctx, self.voice = llm, ctx, voice
                    self.panel.can_ask_ai = True
                    self.panel._enable(self.panel.current_flag() is not None)
                    self.panel.status.setText("The AI's review is ready; your applied "
                                              "expansions are kept. Ask for more ideas below.")
                self.provisional = False
                return
            self.provisional = False
            self.review = review
            self.state = ExpansionState(self.win.passage)
            self.llm, self.ctx, self.voice = llm, ctx, voice
            self.panel.set_review(review, can_ask_ai=llm is not None and ctx is not None)
            self.win.highlight(review.flags)
            count = len(review.flags)
            self.win.set_tab_title(self.key, f"{self.title} ({count})" if count else self.title)
        except Exception as e:     # an exception escaping a slot aborts PyQt6
            print(f"[improve] could not show overly descriptive statements: {e}")

    def _apply(self, index: int, text: str) -> None:
        from src.ui.overdescription_panel import log_accepted
        if self.review is None or not (0 <= index < len(self.review.flags)):
            return
        flag = self.review.flags[index]
        if not self.state.apply(index, flag, text):
            self.panel.status.setText("That statement isn't in the passage any more.")
            return
        if text != flag.text:
            log_accepted(self.win.project, flag.text, text)
        self.panel.mark_applied(
            index, None if text == flag.text else text,
            "Applied — see “Your text, expanded” at the top of the versions.")
        self._put_expanded()

    def _put_expanded(self) -> None:
        from src.ui.improve_window import Version
        from src.ui.passage_critique_dialog import EXPANDED_ANGLE
        version = None
        if self.state.changed:
            version = Version(self.state.text, self.key, kind="expanded",
                              why="Your passage with the expansions you accepted.",
                              angle=EXPANDED_ANGLE)
        self.win.put_expanded(version)

    def _more(self, index: int, note: str) -> None:
        if self.llm is None or self.review is None:
            return
        worker = self.more_factory(self.llm, self.ctx, self.review.flags[index], index,
                                   self.voice, note)
        worker.done.connect(self.panel.add_expansions)
        self._more_worker = worker
        background.start(worker)

    # Rating and accepting. Once Suggestions has run, "Your text, expanded"
    # is one of its versions, as in the old Suggestions window; before
    # that, as in the old Overly descriptive? window, plus a rating.

    def rate(self, version, value: str, text: str) -> str:
        if self.suggestions.started:
            return self.suggestions.rate(version, value, text)
        from src.ui.passage_critique_dialog import log_rating
        w = self.win
        return _saved(log_rating(w.project, w.text, w.start, w.end, text, value,
                                 accepted=value in ("excellent", "good"), style="expansion"))

    def accept(self, version, text: str) -> str:
        if self.suggestions.started:
            return self.suggestions.accept(version, text)
        return self.key

    def stop(self) -> None:
        if self._worker is not None:
            _disconnect(self._worker.done, self._on_review)
        if self._waiting is not None and hasattr(self._waiting, "overdescribed"):
            _disconnect(self._waiting.overdescribed, self._from_suggestions)
        if self._more_worker is not None:
            _disconnect(self._more_worker.done, self.panel.add_expansions)


def build(win, suggestion_worker=None, review_worker=None, more_worker=None, rephrase=None,
          rephrase_dialog=None) -> Dict[str, object]:
    """The four tabs, by key. Rephrase (D.2c) is ``improve_rephrase``:
    ``rephrase`` holds the arguments the Write screen gives Rephrase, and
    ``rephrase_dialog`` the class to host (``RephraseDialog`` unless a test
    passes a stand-in)."""
    from src.ui.improve_rephrase import RephraseTab
    suggestions = SuggestionsTab(win, suggestion_worker)
    critique = CritiqueTab(win, suggestions)
    expand = ExpandTab(win, suggestions, review_worker, more_worker)
    suggestions.critique, suggestions.expand = critique, expand
    return {"suggestions": suggestions, "critique": critique,
            "rephrase": RephraseTab(win, rephrase_dialog, rephrase), "expand": expand}
