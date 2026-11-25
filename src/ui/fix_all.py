"""Accept all like this (piece 3.4).

For a mechanical fix only — one misspelling repeated through a chapter, a
doubled word, a space before a comma — **Fix all like this…** on the
editor's hover card and right-click menu lists every place the same flag
appears in the chapter, each in its sentence with a tick box, and one
button applies them all. One undo reverses them all.

* **Mechanical only.** Spelling, and the grammar rules that are right
  whenever they fire (``readiness_judge.SURE_RULES``). Never style,
  overused words, repeated phrases, the model's corrections or confused
  words (their/there is right in one sentence and wrong in the next).
* **The editor's own flags.** The places are found with the editor's live
  rules (``editor_flags.FlagState.from_highlighter``), so a word the writer
  ignored or added to the dictionary is not touched.
* **Nothing changed behind the writer's back.** A place whose text changed
  after the list was shown is left alone.

Only the paragraphs that contain the flagged words are checked, so it is
quick on a long chapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QVBoxLayout)
from PyQt6.QtCore import Qt

MAX_WORDS = 6                   # a longer suggestion is a rewrite, not a fix
CONTEXT = 60                    # characters either side in the list


@dataclass
class Place:
    start: int                  # in the whole text
    end: int
    found: str                  # the text there now
    replacement: str
    paragraph: str              # for the list


def is_mechanical(error: Any) -> bool:
    """A flag whose fix is the same wherever it appears (spelling and the
    sure grammar rules). Other kinds can still be fixed everywhere, but only
    when the writer ticks the box: see ``can_fix_everywhere``."""
    from src.utils.editor_flags import ErrorType
    from src.ai.readiness_judge import SURE_RULES
    kind = getattr(error, "error_type", None)
    if kind == ErrorType.SPELLING:
        return True
    return kind == ErrorType.GRAMMAR and getattr(error, "rule_id", "") in SURE_RULES


def can_fix_everywhere(error: Any) -> bool:
    """Any flag with a short fix: spelling, grammar, overused words, style."""
    return error is not None and getattr(error, "error_type", None) is not None \
        and bool(_fixes(error))


def _fixes(error: Any) -> List[str]:
    return [s for s in (getattr(error, "suggestions", None) or [])
            if s is not None and len(s.split()) <= MAX_WORDS]


def _pattern(word: str):
    w = re.escape(word)
    if word[:1].isalnum():
        w = r"(?<!\w)" + w
    if word[-1:].isalnum():
        w = w + r"(?!\w)"
    return re.compile(w, re.I)


def times_in(text: str, error: Any) -> int:
    """How often the flagged words appear in the text (a quick count: an
    upper bound on the places)."""
    word = getattr(error, "word", "") or ""
    return len(_pattern(word).findall(text)) if word.strip(" ") else 0


def worth_offering(editor: Any, error: Any) -> bool:
    return can_fix_everywhere(error) and times_in(editor.toPlainText(), error) >= 2


def _same(a: Any, b: Any) -> bool:
    if a.error_type != b.error_type or a.word.lower() != b.word.lower():
        return False
    return getattr(a, "rule_id", "") == getattr(b, "rule_id", "") \
        or a.error_type.value == "spelling"


def places(editor: Any, error: Any, suggestion: str) -> List[Place]:
    """Every place in the editor's text with the same flag, and what each
    becomes."""
    from src.utils.editor_flags import ErrorType, FlagState
    from src.ui.enhanced_text_editor import _match_word_case
    text = editor.toPlainText()
    state = FlagState.from_highlighter(editor.writing_highlighter)
    state.update_full_text(text)
    rx = _pattern(error.word)
    index = _fixes(error).index(suggestion) if suggestion in _fixes(error) else 0
    out: List[Place] = []
    pos = 0
    for n, para in enumerate(text.split("\n")):
        if rx.search(para):
            flags, _keep = state.paragraph_flags(para, n, pos)
            for e in flags:
                if not _same(e, error):
                    continue
                s, t = e.replace_span or (e.start, e.end)
                found = para[s:t]
                if error.error_type == ErrorType.SPELLING:
                    new = _match_word_case(found, suggestion) if suggestion else ""
                else:                      # each place's own fix ("The the" → "The")
                    own = _fixes(e)
                    if suggestion in own:
                        new = suggestion
                    else:
                        new = own[min(index, len(own) - 1)] if own else suggestion
                if new != found:
                    out.append(Place(pos + s, pos + t, found, new, para))
        pos += len(para) + 1
    return out


def apply(editor: Any, chosen: List[Place]) -> int:
    """Make the changes as one undo step; returns how many were made. A
    place whose text has changed is skipped."""
    doc = editor.document()
    text = editor.toPlainText()
    cursor = QTextCursor(doc)
    cursor.beginEditBlock()
    done = 0
    try:
        for p in sorted(chosen, key=lambda p: -p.start):     # from the end: places stay put
            if text[p.start:p.end] != p.found:
                continue
            c = QTextCursor(doc)
            c.setPosition(p.start)
            c.setPosition(p.end, QTextCursor.MoveMode.KeepAnchor)
            editor._replace_word(c, p.replacement)
            done += 1
    finally:
        cursor.endEditBlock()
    return done


def _line(p: Place, para_start: int) -> str:
    s, e = p.start - para_start, p.end - para_start
    before = p.paragraph[max(0, s - CONTEXT):s]
    after = p.paragraph[e:e + CONTEXT]
    lead = "…" if s > CONTEXT else ""
    tail = "…" if e + CONTEXT < len(p.paragraph) else ""
    return f"{lead}{before}[{p.found} → {p.replacement or '(delete)'}]{after}{tail}"


class FixAllDialog(QDialog):
    """The list, a tick box each, and one button."""

    def __init__(self, editor: Any, error: Any, suggestion: str, parent=None):
        super().__init__(parent or editor)
        self.editor, self.error = editor, error
        self.setWindowTitle("Fix all like this")
        lay = QVBoxLayout(self)
        self.head = QLabel()
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        fixes = _fixes(error)
        self.choice: Optional[QComboBox] = None
        if len(fixes) > 1:                 # pick the fix, for any kind of flag
            row = QHBoxLayout()
            row.addWidget(QLabel("Replace with:"))
            self.choice = QComboBox()
            self.choice.addItems([f or "(delete)" for f in fixes])
            self.choice.setCurrentIndex(fixes.index(suggestion) if suggestion in fixes else 0)
            self.choice.currentIndexChanged.connect(lambda _=0: self._fill())
            row.addWidget(self.choice, 1)
            lay.addLayout(row)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.itemChanged.connect(lambda _=None: self._count())
        lay.addWidget(self.list, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.addButton("Fix all", QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self._suggestion = suggestion
        self._fill()
        from src.ui.ui_kit import fit_to_screen
        fit_to_screen(self, 620, 420)
        self.ok.setFocus()

    def suggestion(self) -> str:
        if self.choice is None:
            return self._suggestion
        return _fixes(self.error)[self.choice.currentIndex()]

    def _fill(self) -> None:
        self.places = places(self.editor, self.error, self.suggestion())
        self.list.blockSignals(True)
        self.list.clear()
        text = self.editor.toPlainText()
        for p in self.places:
            para_start = text.rfind("\n", 0, p.start) + 1
            item = QListWidgetItem(_line(p, para_start))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._count()

    def chosen(self) -> List[Place]:
        return [p for n, p in enumerate(self.places)
                if self.list.item(n).checkState() == Qt.CheckState.Checked]

    def _count(self) -> None:
        n, total = len(self.chosen()), len(self.places)
        word = self.error.word.strip() or self.error.word
        self.head.setText(f"“{word}” is flagged in {total} place{'s' if total != 1 else ''} "
                          "in this chapter. Untick any to leave as they are. "
                          "One undo puts them all back.")
        self.ok.setText(f"Fix {n}" if n != total else f"Fix all {n}")
        self.ok.setEnabled(n > 0)


def offer(editor: Any, error: Any, suggestion: Optional[str] = None) -> int:
    """Show the list; make the ticked changes. Returns how many were made."""
    fixes = _fixes(error)
    if not fixes:
        return 0
    dlg = FixAllDialog(editor, error, suggestion if suggestion in fixes else fixes[0])
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return 0
    done = apply(editor, dlg.chosen())
    editor.setFocus()
    return done


# ── The "Fix all N" box (card and menu) ───────────────────────────────
#
# Tick the box, then pick a fix: that fix is made in every place with the
# same flag, as one undo. Ticking it leaves the card (or menu) open. While
# it is ticked, ``editor._fix_all_for`` holds the flag; the editor's
# ``_apply_fix`` asks ``everywhere`` first.

def _arm(editor: Any, error: Any, on: bool) -> None:
    editor._fix_all_for = error if on else None


def card_hidden(card: Any) -> None:
    """The hover card closed: the box goes with it."""
    _disarm_later(card.editor)


def _disarm_later(editor: Any) -> None:
    """Clear the box once the fix in hand (if any) has been made."""
    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, lambda: _arm(editor, None, False))


def _box(editor: Any, error: Any, n: int, parent=None):
    from PyQt6.QtWidgets import QCheckBox
    box = QCheckBox(f"Fix all {n} like this", parent)
    box.setToolTip("Tick, then pick a fix: it is made in all "
                   f"{n} places in this chapter. One undo puts them all back.")
    box.setCursor(Qt.CursorShape.PointingHandCursor)
    box.toggled.connect(lambda on, e=error: _arm(editor, e, on))
    return box


def count(editor: Any, error: Any) -> int:
    fixes = _fixes(error)
    return len(places(editor, error, fixes[0])) if fixes else 0


def everywhere(editor: Any, suggestion: str, error: Any) -> bool:
    """Called by the editor before a single fix: when the box is ticked for
    this flag, make the fix in every place instead. True when it did."""
    armed = getattr(editor, "_fix_all_for", None)
    if armed is None or error is None or armed is not error:
        return False
    editor._fix_all_for = None
    fixes = _fixes(error)
    chosen = next((f for f in fixes if f == suggestion), None)
    if chosen is None:            # the card matched the writer's case: map it back
        chosen = next((f for f in fixes if f.lower() == (suggestion or "").lower()), suggestion)
    done = apply(editor, places(editor, error, chosen))
    _tell(editor, f"Fixed {done} place{'s' if done != 1 else ''}. One undo puts them all back.")
    return done > 0


def _tell(editor: Any, message: str) -> None:
    win = editor.window()
    bar = getattr(win, "statusBar", None)
    if callable(bar) and bar() is not None:
        bar().showMessage(message, 5000)


# ── Call lines for the editor (rule 14) ──────────────────────────────

def add_to_card(card: Any, row: Any, error: Any) -> None:
    """On the hover card: the "Fix all N like this" box above the fixes, and
    "See all N…" (the list, to leave some) with the other actions."""
    editor = card.editor
    _arm(editor, None, False)
    if not worth_offering(editor, error):
        return
    n = count(editor, error)
    if n < 2:
        return
    lay = card._layout
    box = _box(editor, error, n)
    lay.insertWidget(max(0, lay.count() - 1), box)     # just above the fix buttons

    def go(_=False, e=error):
        card.hide()
        offer(editor, e)
    card._action(row, f"See all {n}…", go)


def add_to_menu(editor: Any, menu: Any, error: Any) -> None:
    """The same in the right-click menu: the box just under "Replace with:"
    (ticking it leaves the menu open), and "Fix all like this…" (the list)
    below the replacements."""
    _arm(editor, None, False)
    if not worth_offering(editor, error):
        return
    n = count(editor, error)
    if n < 2:
        return
    from PyQt6.QtWidgets import QWidgetAction
    box = _box(editor, error, n)
    box.setStyleSheet("QCheckBox { padding: 4px 12px; }")
    holder = QWidgetAction(menu)
    holder.setDefaultWidget(box)
    acts = menu.actions()
    label = next((i for i, a in enumerate(acts) if a.text() == "Replace with:"), None)
    if label is not None and label + 1 < len(acts):
        menu.insertAction(acts[label + 1], holder)
    else:
        menu.addAction(holder)
    menu.aboutToHide.connect(lambda: _disarm_later(editor))
    menu.addAction("Fix all like this…").triggered.connect(
        lambda _=False, e=error: offer(editor, e))
