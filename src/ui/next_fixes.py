"""Next fixes: the Companion's queue (piece 3.2).

One card at a time: what's wrong, the sentence with a coloured
before-and-after, and **Accept**, **Skip**, **Go to** and **More options…**.
The findings are the chapter's readiness report (``fix_queue``) for its
current stage (``chapter_stages``), most important first. Keys, with the
Companion showing: ⌘⇧↩ accept, ⌘⇧] skip, ⌘⇧[ back (Ctrl on Windows and
Linux). Nothing is added on screen for them.

* **Fixes as today.** Each finding becomes the Companion's ``Fix``
  (``readiness_fixes.fixes_from_items``) with the editor's own quick fix
  where it has one; with a model, the suggested rewrites in the writer's
  voice are written for the card being shown (``suggest_fix_options``),
  as "Today's three fixes" does. Accept goes through the Companion's own
  ``apply_fix``, which checks the sentence is still where it was.
* **The report follows.** After an accept the chapter is checked again in
  the background (scan only; the results are stored as any check's are),
  so the scorecard's cells turn as the work is done.
* **Trial.** The section "Today's three fixes" is now "Next fixes" (same
  key, so each project's open or closed record still applies): the card on
  top, the three fixes below behind a link. "Overly descriptive" stays,
  closed by default for projects that haven't chosen. Both are retired only
  when the writer agrees.
"""

from __future__ import annotations

import difflib
import html
from typing import Any, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                             QWidget)

from src.ui.ui_kit import PALETTE

KEYS = {"accept": "Ctrl+Shift+Return", "skip": "Ctrl+Shift+]", "back": "Ctrl+Shift+[",
        "dismiss": "Ctrl+Shift+Backspace"}
_PROSE_KINDS_WITHOUT_REWRITES = ("spelling", "grammar")


def before_after(before: str, after: str) -> str:
    """The sentence with what goes struck through in red and what comes in
    green, word by word."""
    a, b = before.split(" "), after.split(" ")
    out: List[str] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(html.escape(" ".join(a[i1:i2])))
            continue
        if i2 > i1:
            out.append(f"<span style='color:{PALETTE['error']}; text-decoration:line-through'>"
                       f"{html.escape(' '.join(a[i1:i2]))}</span>")
        if j2 > j1:
            out.append(f"<span style='color:{PALETTE['success']}; font-weight:bold'>"
                       f"{html.escape(' '.join(b[j1:j2]))}</span>")
    return " ".join(p for p in out if p)


def marked(sentence: str, excerpt: str) -> str:
    """The sentence with the flagged words marked (no fix to show)."""
    at = sentence.find(excerpt) if excerpt else -1
    if at < 0:
        return html.escape(sentence)
    return (html.escape(sentence[:at])
            + f"<span style='background:{PALETTE['primary_tint']}; font-weight:bold'>"
            + html.escape(excerpt) + "</span>" + html.escape(sentence[at + len(excerpt):]))


class NextFixCard(QWidget):
    """The card. Signals carry the shown ``Fix``."""

    accept_requested = pyqtSignal(object, str)      # Fix, the text to put in
    skip_requested = pyqtSignal()
    back_requested = pyqtSignal()
    dismiss_requested = pyqtSignal()                # Not a problem (3.3)
    undo_requested = pyqtSignal()
    goto_requested = pyqtSignal(object)
    more_requested = pyqtSignal(object)
    find_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fix = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {PALETTE['ink_faint']}; font-size: 11px;")
        self.status.linkActivated.connect(
            lambda h: self.undo_requested.emit() if h == "undo" else self.find_requested.emit())
        v.addWidget(self.status)
        self.find_btn = QPushButton("🎯 Find the next fixes")
        self.find_btn.setToolTip("Check this chapter and line up what to fix, most important "
                                 "first, for the chapter's stage")
        self.find_btn.clicked.connect(self.find_requested.emit)
        v.addWidget(self.find_btn)
        self.what = QLabel("")
        self.what.setWordWrap(True)
        self.what.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.what)
        self.change = QLabel("")
        self.change.setWordWrap(True)
        self.change.setTextFormat(Qt.TextFormat.RichText)
        self.change.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.change.setStyleSheet(f"background: {PALETTE['surface_muted']}; "
                                  "border-radius: 4px; padding: 6px;")
        v.addWidget(self.change)
        self.options = QComboBox()
        self.options.currentIndexChanged.connect(lambda _i: self._show_option())
        v.addWidget(self.options)
        row = QHBoxLayout()
        from src.ui.ui_kit import primary_button
        self.accept_btn = primary_button("✓ Accept")
        self.accept_btn.clicked.connect(self._accept)
        self.skip_btn = QPushButton("Skip")
        self.skip_btn.clicked.connect(self.skip_requested.emit)
        self.dismiss_btn = QPushButton("Not a problem")
        self.dismiss_btn.clicked.connect(self.dismiss_requested.emit)
        self.goto_btn = QPushButton("Go to")
        self.goto_btn.clicked.connect(lambda: self.fix and self.goto_requested.emit(self.fix))
        self.more_btn = QPushButton("💡 More options…")
        self.more_btn.setToolTip("Open Suggestions on this sentence, focused on the problem")
        self.more_btn.clicked.connect(lambda: self.fix and self.more_requested.emit(self.fix))
        for b in (self.accept_btn, self.skip_btn, self.dismiss_btn):
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        row2 = QHBoxLayout()
        for b in (self.goto_btn, self.more_btn):
            row2.addWidget(b)
        row2.addStretch()
        v.addLayout(row2)
        self.buttons = [self.accept_btn, self.skip_btn, self.dismiss_btn, self.goto_btn,
                        self.more_btn]
        self._keys = []
        for name, slot in (("accept", self._accept), ("skip", self.skip_requested.emit),
                           ("back", self.back_requested.emit),
                           ("dismiss", lambda: self.fix and self.dismiss_requested.emit())):
            key = QShortcut(QKeySequence(KEYS[name]), self)
            key.setContext(Qt.ShortcutContext.WindowShortcut)
            key.activated.connect(slot)
            key.setEnabled(False)
            self._keys.append(key)
        self.dismiss_btn.setToolTip(
            "Not a problem here: stop raising it (this word or rule) anywhere in this project ("
            + QKeySequence(KEYS["dismiss"]).toString(QKeySequence.SequenceFormat.NativeText)
            + "). Take it back from the Critique.")
        text = QKeySequence(KEYS["accept"]).toString(QKeySequence.SequenceFormat.NativeText)
        self.accept_btn.setToolTip(f"Put the change in the chapter ({text})")
        self.skip_btn.setToolTip("Move on; it comes back at the end of the queue ("
                                 + QKeySequence(KEYS["skip"]).toString(
                                     QKeySequence.SequenceFormat.NativeText) + "; "
                                 + QKeySequence(KEYS["back"]).toString(
                                     QKeySequence.SequenceFormat.NativeText) + " goes back)")
        self.show_empty("Find what to fix next in this chapter, most important first.",
                        loaded=False)

    # Keys only while this card is on screen (one Companion per chapter).
    def showEvent(self, event):
        super().showEvent(event)
        for k in self._keys:
            k.setEnabled(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        for k in self._keys:
            k.setEnabled(False)

    def show_empty(self, text: str, loaded: bool = True) -> None:
        self.fix = None
        self.status.setText(html.escape(text) + (
            " <a href='find'>Check again</a>" if loaded else ""))
        self.find_btn.setVisible(not loaded)
        for w in (self.what, self.change, self.options, *self.buttons):
            w.setVisible(False)

    def show_busy(self, text: str = "Checking this chapter…") -> None:
        self.show_empty(text, loaded=True)
        self.status.setText(html.escape(text))

    def show_fix(self, fix: Any, position: int, total: int, scope_line: str,
                 note: str = "") -> None:
        self.fix = fix
        self.find_btn.setVisible(False)
        self.status.setText(f"<b>{position} of {total}</b> · {html.escape(scope_line)}"
                            + (f" · {html.escape(note)}" if note else "")
                            + " · <a href='find'>Check again</a>")
        label, _, reason = fix.text.partition(" — ")
        self.what.setText(f"<b>{html.escape(label)}</b>"
                          + (f"<br><span style='color:{PALETTE['ink_soft']}'>"
                             f"{html.escape(reason)}</span>" if reason else "")
                          + (f"<br><span style='color:{PALETTE['ink_faint']}'>The model: "
                             f"{html.escape(fix.why)}</span>" if fix.why else ""))
        self.options.blockSignals(True)
        self.options.clear()
        for o in fix.options:
            tag = "✨ " if o.by_ai else ""
            fit = f" · voice {o.voice_fit:.0%}" if o.voice_fit is not None else ""
            self.options.addItem(f"{tag}{o.text[:90]}{fit}")
        self.options.blockSignals(False)
        for w in (self.what, self.change, *self.buttons):
            w.setVisible(True)
        self.options.setVisible(len(fix.options) > 1)
        self._show_option()

    def option_text(self) -> str:
        if self.fix is None or not self.fix.options:
            return ""
        i = max(0, self.options.currentIndex())
        return self.fix.options[min(i, len(self.fix.options) - 1)].text

    def _show_option(self) -> None:
        if self.fix is None:
            return
        after = self.option_text()
        sentence = self.fix.sentence or self.fix.excerpt
        self.change.setText(before_after(sentence, after) if after
                            else marked(sentence, self.fix.excerpt))
        self.accept_btn.setEnabled(bool(after))
        if not after:
            self.accept_btn.setToolTip("No quick fix for this one — Go to it, or 💡 More "
                                       "options… for rewrites")

    def _accept(self) -> None:
        text = self.option_text()
        if self.fix is not None and text and self.accept_btn.isEnabled():
            self.accept_requested.emit(self.fix, text)


def install(panel: Any, v: Any):
    """The card at the top of the "Next fixes" section; returns (card, the
    layout for Today's three fixes), which sit below behind a link."""
    card = NextFixCard()
    v.addWidget(card)
    toggle = QLabel("")
    toggle.setStyleSheet(f"color: {PALETTE['ink_faint']}; font-size: 11px;")
    v.addWidget(toggle)
    older = QWidget()
    inner = QVBoxLayout(older)
    inner.setContentsMargins(0, 0, 0, 0)
    v.addWidget(older)

    def show_older(on: bool) -> None:
        older.setVisible(on)
        toggle.setText(f"<a href='older'>Today's three fixes {'▾' if on else '▸'}</a>")
        toggle.setToolTip("The earlier way: the three fixes that matter most, picked by the "
                          "model. On trial beside the queue.")
    toggle.linkActivated.connect(lambda _h: show_older(not older.isVisible()))
    panel.older_fixes = older
    panel.show_older_fixes = show_older
    show_older(False)
    return card, inner


class Queue:
    """The queue behind one Companion (its controller ``cc``)."""

    def __init__(self, cc: Any):
        self.cc = cc
        self.card: NextFixCard = cc.panel.queue
        self.entries: List[Any] = []
        self.fixes: dict = {}               # entry key → Fix (with its rewrites)
        self.skipped: List[str] = []
        self.index = 0
        self.report = None
        self.stage = ""
        self._busy = False
        self._again = False
        self.card.find_requested.connect(self.find)
        self.card.accept_requested.connect(self.accept)
        self.card.skip_requested.connect(self.skip)
        self.card.back_requested.connect(self.back)
        self.card.dismiss_requested.connect(self.dismiss)
        self.card.undo_requested.connect(self.undo_dismiss)
        self._last_dismissed: Optional[str] = None
        self.card.goto_requested.connect(lambda f: self.cc.jump_to(f.excerpt))
        self.card.more_requested.connect(self.more)
        self.extra: List[Any] = []          # the editor's style flags no check reports (D.3)

    # ── Finding ──────────────────────────────────────────────────

    def _where(self):
        project, chapter = self.cc.project, self.cc.chapter
        if project is None or chapter is None:
            return None, None, None
        scope, _ch = project.find_chapter_with_scope(chapter.id)
        return project, scope, chapter

    def chapter_loaded(self) -> None:
        self.entries, self.fixes, self.skipped, self.index, self.report = [], {}, [], 0, None
        self.card.show_empty("Find what to fix next in this chapter, most important first.",
                             loaded=False)

    def find(self) -> None:
        """Check the chapter (scan; stored results are reused) and line up
        its findings for its stage."""
        project, scope, chapter = self._where()
        if project is None:
            self.card.show_empty("Open a chapter of a project to find its next fixes.")
            return
        if self._busy:
            self._again = True
            return
        self._busy = True
        text = self.cc.ce.editor.toPlainText()
        self.extra = self._style_flags()
        if not self.entries:
            self.card.show_busy()
        from src.ui.companion_panel import run_background

        def work():
            from src.ai import chapter_stages, readiness as rd
            report = rd.chapter_report(project, chapter, scope=scope, text=text)
            return report, chapter_stages.stage_of(project, scope, chapter.id)

        def done(result, error):
            self._busy = False
            if self._again:
                self._again = False
                self.find()
                return
            if not result:
                self.card.show_empty(f"The check didn't finish: {error or 'unknown error'}")
                return
            self.set_report(*result)

        run_background(work, done)

    def set_report(self, report: Any, stage: str) -> None:
        from src.ai import fix_queue
        self.report, self.stage = report, stage
        current = self.entries[self.index].key if 0 <= self.index < len(self.entries) else None
        self.entries = fix_queue.entries(report, stage, skipped=self.skipped, extra=self.extra)
        keys = [e.key for e in self.entries]
        self.index = keys.index(current) if current in keys else 0
        self.show()

    def _style_flags(self) -> List[Any]:
        """The Style tab's own issues the report doesn't hold, as the editor
        shows them now (the writer's switches and ignores applied)."""
        from src.ai import fix_queue
        editor = self.cc.ce.editor
        hl = editor.writing_highlighter
        found = []
        block = editor.document().begin()
        while block.isValid():
            if block.text().strip():
                found.extend((block.position() + i.start, i)
                             for i in hl.style_issues_for(block.text()))
            block = block.next()
        return fix_queue.style_entries(found)

    def _entry_for(self, fix: Any):
        for key, f in self.fixes.items():
            if f is fix:
                return next((e for e in self.entries if e.key == key), None)
        return None

    # ── Showing ──────────────────────────────────────────────────

    def _scope_line(self) -> str:
        from src.ai import chapter_stages as cst
        if self.stage:
            return f"{cst.label(self.stage)} fixes (the chapter's stage)"
        return "every stage (no stage set)"

    def _fix_for(self, entry: Any):
        if entry.key not in self.fixes:
            from src.ui.readiness_fixes import fixes_from_items
            item = entry.item
            if item.kind == "spelling" and not item.suggestions:
                item.suggestions = self._spelling(item.text)    # as the editor does, on demand
            elif item.kind == "intensifier" and not item.suggestions:
                item.suggestions = [""]                         # "very", "really": cut it
            made = fixes_from_items(entry.label, [item], self.cc.ce.editor.toPlainText())
            self.fixes[entry.key] = made[0] if made else None
        return self.fixes[entry.key]

    def _spelling(self, word: str) -> List[str]:
        try:
            from src.ui.enhanced_text_editor import _match_word_case
            found = self.cc.ce.editor.writing_highlighter.spell_checker.suggest(word) or []
            return [_match_word_case(word, s) for s in found[:3]]
        except Exception:
            return []

    def show(self) -> None:
        while self.entries:
            self.index %= len(self.entries)
            entry = self.entries[self.index]
            fix = self._fix_for(entry)
            if fix is not None:
                note = "skipped before" if entry.key in self.skipped else ""
                self.card.show_fix(fix, self.index + 1, len(self.entries), self._scope_line(),
                                   note)
                self._count()
                self._rewrites(entry, fix)
                return
            self.entries.pop(self.index)          # the text changed under it
        self._count()
        from src.ai import chapter_stages as cst
        if self.stage:
            nxt = cst.next_stage(self.stage)
            self.card.show_empty(f"Nothing left to fix at {cst.label(self.stage)}."
                                 + (f" Move the chapter to {cst.label(nxt)} from the "
                                    "stage in the header when you're ready." if nxt else ""))
        else:
            self.card.show_empty("Nothing left to fix in this chapter — nice work.")

    def _count(self) -> None:
        section = self.cc.panel.sections.get("fixes")
        if section is not None:
            section.set_count(len(self.entries))

    def _rewrites(self, entry: Any, fix: Any) -> None:
        """With a model, rewrites in the writer's voice for the card shown
        (once per finding), as "Today's three fixes" writes them."""
        if fix.kind in _PROSE_KINDS_WITHOUT_REWRITES or any(o.by_ai for o in fix.options) \
                or getattr(fix, "_asked", False):
            return
        fix._asked = True
        from src.ui.companion_panel import _companion_ai_enabled, run_background
        if not _companion_ai_enabled():
            return
        cc, text = self.cc, self.cc.ce.editor.toPlainText()
        project, chapter = cc.project, cc.chapter

        def work():
            llm = cc._llm()
            if llm is None:
                return []
            from src.ai import companion
            from src.ai.chapter_analysis_agent import is_local_llm
            return companion.suggest_fix_options(llm, project, chapter, text, fix,
                                                 cc._voice_for(text), is_local_llm(llm))

        def done(options, error):
            if options:
                fix.options = list(options) + [o for o in fix.options if not o.by_ai]
                if self.card.fix is fix:
                    self.show()

        run_background(work, done)

    # ── Acting ───────────────────────────────────────────────────

    def accept(self, fix: Any, replacement: str) -> None:
        problem = self.cc.apply_fix(fix, replacement)
        if problem is not None:
            if problem:
                self.card.status.setText(html.escape(problem)
                                         + " <a href='find'>Check again</a>")
            return
        if 0 <= self.index < len(self.entries):
            done = self.entries.pop(self.index)
            self.fixes.pop(done.key, None)
        self.show()
        self.find()                     # the report follows (stored, for the scorecard)

    def skip(self) -> None:
        if not self.entries:
            return
        entry = self.entries[self.index]
        if entry.key in self.skipped:
            self.skipped.remove(entry.key)
        self.skipped.append(entry.key)
        self.entries.append(self.entries.pop(self.index))
        if self.index >= len(self.entries):
            self.index = 0
        self.show()

    def more(self, fix: Any) -> None:
        """💡 More options…: for a style flag, the Style tab's own ✨ rewrite
        of the sentence aimed at the issue; otherwise Suggestions."""
        from src.utils.style_checks import KINDS, sentences_with_offsets
        entry = self._entry_for(fix)
        item = entry.item if entry is not None else None
        if item is None or item.kind not in KINDS:
            self.cc.more_fix_options(fix)
            return
        editor = self.cc.ce.editor
        block = editor.document().findBlock(item.start)
        rel = item.start - block.position()
        s0, e0 = item.start, item.end
        for a, b, _ in sentences_with_offsets(block.text()):
            if a <= rel < b:
                s0, e0 = min(s0, block.position() + a), max(e0, block.position() + b)
                break
        editor.style_rewrite_requested.emit(
            s0, e0, f"Fix the {KINDS[item.kind][0].lower()}: {item.reason}")

    def dismiss(self) -> None:
        """Not a problem: this pattern stops being raised in this project
        (every chapter, after a restart) — it goes, and so do its others."""
        if not self.entries:
            return
        from src.ai import fix_queue
        entry = self.entries[self.index]
        project, _scope, chapter = self._where()
        if entry.check.startswith("style:"):        # a live style flag: the Style tab's Ignore
            self.cc.ce.editor.writing_highlighter.ignore_style_issue(entry.item.kind,
                                                                     entry.item.text)
        elif project is None or not fix_queue.dismiss(project, entry,
                                                      getattr(chapter, "title", "") or ""):
            return
        key = entry.item.key
        self.entries = [e for e in self.entries if e.item.key != key]
        self._last_dismissed = key
        self._last_style = ((entry.item.kind, entry.item.text)
                            if entry.check.startswith("style:") else None)
        self.show()
        what = entry.item.text if len(entry.item.text) <= 30 else entry.item.text[:29] + "…"
        note = (f"“{html.escape(what)}” won't be raised again in this project. "
                "<a href='undo'>Undo</a>")
        self.card.status.setText(note + (" · " + self.card.status.text()
                                         if self.card.fix is not None else ""))

    def undo_dismiss(self) -> None:
        project, _scope, _chapter = self._where()
        if project is None or not self._last_dismissed:
            return
        from src.ai import fix_queue
        style = getattr(self, "_last_style", None)
        if style is not None:                       # put the Style tab's Ignore back
            from src.utils.spell_checker import _apos
            hl = self.cc.ce.editor.writing_highlighter
            hl._style_ignored.discard((style[0], _apos(style[1].strip().lower())))
            hl.rehighlight()
        else:
            fix_queue.undismiss(project, self._last_dismissed)
        self._last_dismissed = self._last_style = None
        self.find()

    def back(self) -> None:
        if self.entries:
            self.index = (self.index - 1) % len(self.entries)
            self.show()
