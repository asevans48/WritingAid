"""The writing habit's link to one chapter editor (piece H.1).

Created by the Companion's controller for each chapter it opens:

* **Words.** The text at open is the starting point. At each save or
  chapter switch (the points ``companion_state.record_session`` already
  uses), the words added and cut since the last save are found by a diff
  of the word lists and added to the shared record (``writing_habit``).
* **Moved text.** A block of more than 300 words arriving at once (a paste,
  an import from Word, an undo that brings a cut back) is counted as moved,
  not written, and listed separately.
* **Minutes.** Key presses in the editor, in one-minute buckets; a minute
  counts if it had any typing, so idle time is not counted.
* **Goal met.** A save that reaches the daily or weekly goal puts one quiet
  line in the status bar (``notify.done``). No box, no sound.
* **The nudge.** When a chapter is opened (never while typing), an
  unfinished novel or novella whose last seven writing days were only
  revising gets one question: go to the next chapter, keep revising, or
  stop these nudges.

Every entry point catches its own errors: the habit must never get in the
way of writing.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional, Set

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QMessageBox

from src.data import writing_habit as wh

_TYPING_KEYS = {Qt.Key.Key_Backspace, Qt.Key.Key_Delete, Qt.Key.Key_Return, Qt.Key.Key_Enter}
_LARGE_CHARS = 600                 # fewer characters than this can't hold 300 words


def _now() -> datetime:
    return datetime.now()


class HabitTracker(QObject):
    """Counts one chapter editor's writing into the shared record."""

    def __init__(self, controller):
        super().__init__(controller)
        self.c = controller
        self._baseline = ""
        self._moved = 0
        self._minutes: Set[str] = set()       # "YYYY-MM-DDTHH:MM" with typing, not yet recorded
        self._last_recorded_minute = ""
        editor = controller.ce.editor
        editor.installEventFilter(self)
        editor.document().contentsChange.connect(self._on_change)

    # ── open ───────────────────────────────────────────────────────────

    def chapter_loaded(self, text: str) -> None:
        self._baseline = text
        self._moved = 0
        self._minutes.clear()
        try:
            self._fold_in()
        except Exception as e:                    # noqa: BLE001
            print(f"[habit] could not fold in old sessions: {e}")
        QTimer.singleShot(0, self.maybe_nudge)

    def _fold_in(self) -> None:
        project = self.c.project
        if project is None:
            return
        from src.data import companion_state as cs
        titles = {}
        try:
            for _scope, ms in project.iter_manuscripts():
                titles.update({ch.id: ch.title for ch in ms.chapters})
        except Exception:
            pass
        wh.fold_in_sessions(project, cs.load(project).get("sessions", {}), titles)

    # ── while writing ──────────────────────────────────────────────────

    def eventFilter(self, obj, event):                    # noqa: N802 (Qt)
        try:
            if event.type() == QEvent.Type.KeyPress and (event.text() or event.key() in _TYPING_KEYS):
                self._minutes.add(_now().strftime("%Y-%m-%dT%H:%M"))
        except Exception:
            pass
        return False

    def _on_change(self, position: int, removed: int, added: int) -> None:
        # A format-only change (the highlighter) reports removed == added.
        if added < _LARGE_CHARS or removed == added:
            return
        try:
            cursor = QTextCursor(self.c.ce.editor.document())
            cursor.setPosition(position)
            cursor.setPosition(min(position + added, self.c.ce.editor.document().characterCount() - 1),
                               QTextCursor.MoveMode.KeepAnchor)
            words = wh.word_count(cursor.selectedText())
            if words > wh.LARGE_PASTE_WORDS:
                self._moved += words
        except Exception:
            pass

    # ── save ───────────────────────────────────────────────────────────

    def _minutes_by_day(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for bucket in sorted(self._minutes):
            if bucket == self._last_recorded_minute:
                continue                          # already counted at the last save
            out[bucket[:10]] = out.get(bucket[:10], 0) + 1
        if self._minutes:
            self._last_recorded_minute = max(self._minutes)
        self._minutes.clear()
        return out

    def chapter_saved(self, text: str) -> None:
        project, chapter = self.c.project, self.c.chapter
        if project is None or chapter is None:
            return
        added, cut = wh.word_changes(self._baseline, text)
        moved = min(self._moved, added)
        added -= moved
        minutes = self._minutes_by_day()
        self._baseline, self._moved = text, 0
        if not (added or cut or moved or minutes):
            return
        daily, weekly = wh.goals()
        today = _now().date()
        before = wh.goal_progress(wh.load()["days"], today, daily, weekly)
        if not wh.record(project, chapter.id, getattr(chapter, "title", ""), added=added, cut=cut,
                         moved=moved, minutes=minutes, day=today):
            return
        after = wh.goal_progress(wh.load()["days"], today, daily, weekly)
        notes = wh.crossed(before, after)
        if notes:
            from src.ui import notify
            notify.done(self.c.ce, "Writing goal", " · ".join(notes))
        if daily or weekly:
            self.c.refresh_left_off()

    # ── the nudge ──────────────────────────────────────────────────────

    def nudge_reason(self) -> Optional[Dict[str, int]]:
        """The numbers for the question, or None when not to ask."""
        project, chapter = self.c.project, self.c.chapter
        if project is None or chapter is None or not wh.nudge_state()["on"]:
            return None
        scope = None
        if hasattr(project, "find_chapter_with_scope"):
            scope, found = project.find_chapter_with_scope(chapter.id)
            if found is None:
                return None
        if not wh.nudge_applies(project, scope):
            return None
        return wh.revising_only(wh.load()["days"], wh.project_key(project), since=wh.last_asked())

    def maybe_nudge(self) -> None:
        try:
            reason = self.nudge_reason()
            if not reason:
                return
            answer = ask(self.c.ce, reason)
            if answer == "stop":
                wh.set_nudge(on=False, asked=_now().date())
                from src.ui import notify
                notify.done(self.c.ce, "Writing habit",
                            "Nudges are off. Settings ▸ AI Features ▸ Writing habit "
                            "turns them back on.")
                return
            wh.set_nudge(asked=_now().date())
            if answer == "next":
                go_to_next_chapter(self.c.ce, self.c.project)
        except Exception as e:                        # noqa: BLE001
            print(f"[habit] nudge: {e}")


def ask(parent, reason: Dict[str, int]) -> str:
    """The one question: "next", "keep" or "stop"."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Keep polishing, or move on?")
    box.setText(f"You've spent your last {reason['days']} writing days revising. "
                "Keep polishing, or move on to the next chapter?")
    box.setInformativeText(f"In those days the manuscript grew by {max(reason['growth'], 0):,} "
                           f"words ({reason['added']:,} added, {reason['cut']:,} cut).")
    nxt = box.addButton("Go to the next chapter", QMessageBox.ButtonRole.AcceptRole)
    keep = box.addButton("Keep revising", QMessageBox.ButtonRole.RejectRole)
    stop = box.addButton("Stop these nudges", QMessageBox.ButtonRole.DestructiveRole)
    box.setDefaultButton(keep)
    box.setEscapeButton(keep)
    box.exec()
    clicked = box.clickedButton()
    return "next" if clicked is nxt else "stop" if clicked is stop else "keep"


def _manuscript_editor(widget):
    w = widget
    while w is not None:
        if hasattr(w, "open_chapter") and hasattr(w, "_add_chapter"):
            return w
        w = w.parentWidget()
    return None


def go_to_next_chapter(chapter_editor, project) -> bool:
    """Open the chapter after the one last worked on, or add one if that is
    the last chapter of its manuscript. True when something was opened."""
    me = _manuscript_editor(chapter_editor)
    if me is None or project is None:
        return False
    last_id = wh.last_chapter(wh.load(), project) or getattr(chapter_editor.chapter, "id", "")
    scope, chapter = project.find_chapter_with_scope(last_id)
    if chapter is None:
        last_id = getattr(chapter_editor.chapter, "id", "")
        scope, chapter = project.find_chapter_with_scope(last_id)
    chapters = []
    for s, ms in project.iter_manuscripts():
        if s == scope:
            chapters = list(ms.chapters)
    ids = [c.id for c in chapters]
    if last_id in ids and ids.index(last_id) + 1 < len(ids):
        return bool(me.open_chapter(ids[ids.index(last_id) + 1]))
    if last_id:
        me.open_chapter(last_id)
    me._add_chapter()                     # the existing way to add a chapter
    return True
