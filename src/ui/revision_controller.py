"""Open a chapter at a sentence and show a tool there (piece R.5).

One place for the wiring that the Critique tab, the scorecard and the
Companion share: switch to Write, open the chapter, find the passage,
select it, and hand it to a tool (the expand window, the Companion's
fixes). Moved out of ``main_window.py``; its old methods
(``_go_to_critique_line``, ``_expand_critique_statement``) now call these.

**Data safety:** a chapter is opened only through the editor's own chapter
switch (``ManuscriptEditor.open_chapter``), so the chapter being left is
carried into the project and saved exactly as before. Nothing here saves,
loads or closes anything.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Sequence


class RevisionController:
    def __init__(self, main_window):
        self.mw = main_window

    # ── The parts ────────────────────────────────────────────────

    @property
    def manuscript_editor(self):
        return getattr(self.mw, "manuscript_editor", None)

    def _status(self, message: str, ms: int = 5000) -> None:
        try:
            self.mw.statusBar().showMessage(message, ms)
        except Exception:
            pass

    def chapter_id_for_title(self, title: str) -> str:
        project = getattr(self.manuscript_editor, "project", None) or \
            getattr(self.mw, "current_project", None)
        if project is None or not title:
            return ""
        return next((c.id for _, ms in project.iter_manuscripts()
                     for c in ms.chapters if c.title == title), "")

    def open_chapter(self, chapter_id: str = ""):
        """Show Write with ``chapter_id`` open (the current chapter when
        empty) and return its chapter editor, or None."""
        me = self.manuscript_editor
        if me is None:
            return None
        from src.ui import screen_groups; screen_groups.show(self.mw, me)   # D.4
        ce = me.current_chapter_editor
        if chapter_id and (ce is None or getattr(ce.chapter, "id", None) != chapter_id):
            me.open_chapter(chapter_id)            # the normal switch: the old chapter is saved
            ce = me.current_chapter_editor
        return ce

    @staticmethod
    def select(editor, passage: str, near: int = 0) -> Optional[int]:
        """Select the occurrence of ``passage`` nearest ``near``; its start,
        or None when it isn't there."""
        text = editor.toPlainText()
        hits = [m.start() for m in re.finditer(re.escape(passage), text)] if passage else []
        if not hits:
            return None
        start = min(hits, key=lambda i: abs(i - near))
        from src.ai.passage_critique import py_to_qt_index
        cursor = editor.textCursor()
        cursor.setPosition(py_to_qt_index(text, start))
        cursor.setPosition(py_to_qt_index(text, start + len(passage)), cursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()
        return start

    # ── What the tools ask for ───────────────────────────────────

    def show_passage(self, chapter_id: str, passage: str, offset: int = 0) -> bool:
        """Open the chapter and select the passage (the scorecard's "Show in
        chapter"); the editor's hover card then offers its fixes."""
        ce = self.open_chapter(chapter_id)
        if ce is None:
            return False
        if self.select(ce.editor, passage, offset) is None:
            self._status("That passage has changed since the check; check readiness again.")
            return False
        ce.editor.setFocus()
        return True

    def expand_statement(self, chapter_id: str, title: str, sentence: str, offset: int) -> None:
        """Open an overly descriptive statement in the editor, with ways to
        expand it (the Critique tab's and the scorecard's links)."""
        if not chapter_id and title:
            ce = getattr(self.manuscript_editor, "current_chapter_editor", None)
            if ce is None or getattr(ce.chapter, "title", "") != title:
                chapter_id = self.chapter_id_for_title(title)
        ce = self.open_chapter(chapter_id)
        if ce is None:
            return
        start = self.select(ce.editor, sentence, offset)
        if start is None:
            self._status("That statement has changed since the critique — run it again.")
            return
        ce.expand_statement(start, start + len(sentence))

    def open_fixes(self, chapter_id: str, label: str, items: Sequence[Any]) -> bool:
        """Open the chapter with these readiness findings on the Companion's
        next-fix card, the first selected in the text (2.2; on the card
        since D.6 retired Today's three fixes)."""
        if not chapter_id:
            return False
        ce = self.open_chapter(chapter_id)
        if ce is None or getattr(ce, "companion", None) is None:
            return False
        mine = [i for i in items if not i.chapter_id or i.chapter_id == chapter_id]
        queue = ce.companion.queue
        queue.show_items(label, mine)
        panel = ce.companion.panel
        ce._show_right_panel(panel)
        panel.open_section("fixes")
        fix = queue.card.fix
        if fix is not None:
            self.select(ce.editor, fix.excerpt, mine[0].start if mine else 0)
            ce.editor.setFocus()
        return True

    def go_to_line(self, number: int) -> None:
        """Navigate to a sentence (positive, 1-indexed) or paragraph
        (negative) of the open chapter, from critique feedback."""
        ce = self.open_chapter()
        if ce is None or not ce.editor:
            return
        editor = ce.editor
        text = editor.toPlainText()
        if not text:
            return
        is_paragraph_mode = number < 0
        target_number = abs(number)
        if is_paragraph_mode:
            paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
            if target_number < 1 or target_number > len(paragraphs):
                return
            target_text = paragraphs[target_number - 1]
            position = 0
            for i in range(target_number - 1):
                if i < len(paragraphs):
                    found = text.find(paragraphs[i], position)
                    if found >= 0:
                        position = found + len(paragraphs[i])
            position = text.find(target_text, position)
            if position < 0:
                position = 0
            end_pos = position + len(target_text)
            status_msg = f"Navigated to paragraph {target_number}"
        else:
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
            if target_number < 1 or target_number > len(sentences):
                return
            target_text = sentences[target_number - 1]
            position = 0
            current_sentence = 0
            for match in re.finditer(r'[^.!?]*[.!?]', text):
                if match.group().strip():
                    current_sentence += 1
                    if current_sentence == target_number:
                        position = match.start()
                        break
            if position == 0 and target_number > 1:
                pos = 0
                for i in range(target_number - 1):
                    if i < len(sentences):
                        found = text.find(sentences[i], pos)
                        if found >= 0:
                            pos = found + len(sentences[i])
                position = text.find(target_text, pos)
            end_pos = position + len(target_text)
            status_msg = f"Navigated to sentence {target_number}"
        cursor = editor.textCursor()
        cursor.setPosition(position)
        if end_pos <= len(text):
            cursor.setPosition(position)
            cursor.setPosition(end_pos, cursor.MoveMode.KeepAnchor)
        else:
            cursor.movePosition(cursor.MoveOperation.EndOfBlock, cursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()
        editor.setFocus()
        self._status(status_msg, 3000)
