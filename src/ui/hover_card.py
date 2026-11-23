"""Keeping the editor's hover card open while the writer uses it.

The card (``ErrorCard`` in enhanced_text_editor.py) used to close on its own:

* on every ``textChanged``, and the editor fires that whenever highlights
  are redrawn (background checks finishing, typing pausing, the cursor
  moving), not only when the text is edited;
* on a scroll over the card, which reached the text underneath;
* when the pointer crossed the small gap between the word and the card, if
  the card did not get its "enter" event (tooltip windows on macOS).

These helpers close it only when the text really changes, when the word is
no longer flagged, or when the pointer has left both the word and the card.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QCursor, QTextCursor

# How far around the word and the card the pointer may stray.
MARGIN = 12


def watch_editor(card, editor) -> None:
    """Close ``card`` when the text is edited, or when a redraw removes the
    flag it shows; not on every redraw."""
    def on_edit(_pos, removed, added):
        if (removed or added) and card.isVisible():
            card.hide()

    def on_redraw():
        if card.isVisible() and not still_flagged(card, editor):
            card.hide()

    editor.document().contentsChange.connect(on_edit)
    editor.textChanged.connect(on_redraw)


def still_flagged(card, editor) -> bool:
    """Whether the flag the card shows is still in the text."""
    error = getattr(card, "error", None)
    if error is None:
        return False
    try:
        current = editor.writing_highlighter.get_error_at(card.block_number, error.start)
    except Exception:
        return True                          # cannot tell: keep it open
    return current is not None and (current.start, current.end) == (error.start, error.end)


def word_rect(card, editor) -> QRect:
    """The flagged word on screen, in global coordinates."""
    start = QTextCursor(editor.document())
    start.setPosition(card.span[0])
    end = QTextCursor(editor.document())
    end.setPosition(card.span[1])
    a, b = editor.cursorRect(start), editor.cursorRect(end)
    rect = a.united(b)
    top_left = editor.viewport().mapToGlobal(rect.topLeft())
    return QRect(top_left, rect.size())


def near_card(card, editor, pos: QPoint = None) -> bool:
    """Whether the pointer is on the card, on its word, or in between."""
    pos = QCursor.pos() if pos is None else pos
    area = card.geometry()
    try:
        area = area.united(word_rect(card, editor))
    except Exception:
        pass
    return area.adjusted(-MARGIN, -MARGIN, MARGIN, MARGIN).contains(pos)
