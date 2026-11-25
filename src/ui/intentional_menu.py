"""This is intentional, in the editor's right-click menu (piece 4.1).

One entry in the flag section (``EnhancedTextEditor.add_flag_section``,
so the Write tab's menu and the editor's own both have it), after Ignore:
"📌 This is intentional". It calls ``intentional.mark``: the pattern is
not flagged again in this project (any chapter, after a restart), and a
line goes into the style sheet (the Companion's Style sheet section),
where it can be reworded or deleted. Deleting it there flags the quirk
again; so does "take that back" in the Critique.

``announce`` tells the open editor and the Companion that the style sheet
changed (redraw, refresh the list, mark the project changed so the rule
is saved with it). The Critique and the next-fix card use it too.
"""

from __future__ import annotations

from typing import Any, Optional

LABEL = "📌 This is intentional"
TIP = ("Meant this way: stop flagging it anywhere in this project, and add it to your "
       "style sheet (Companion › Style sheet), where you can reword or delete it.")

_CATEGORY = {"spelling": "spelling", "overuse": "overuse", "overused_phrase": "overuse",
             "grammar": "grammar", "style": "style"}


def add_to_menu(editor: Any, menu: Any, error: Any, block: Any) -> Optional[Any]:
    """Add the entry for ``error`` (a ``WritingError`` in ``block``)."""
    from src.ai import intentional
    if not intentional.flag_key(error):
        return None
    action = menu.addAction(LABEL)
    action.setToolTip(TIP)
    action.setEnabled(getattr(editor, "_project", None) is not None)
    action.triggered.connect(lambda _checked=False: mark_flag(editor, error, block))
    return action


def _label(error: Any) -> str:
    from src.utils.editor_flags import ErrorType
    t = error.error_type
    if t == ErrorType.STYLE:
        from src.utils.style_checks import KINDS
        kind = getattr(error, "style_kind", "")
        return KINDS[kind][0] if kind in KINDS else "Style"
    return {ErrorType.SPELLING: "Spelling", ErrorType.GRAMMAR: "Grammar",
            ErrorType.OVERUSE: "Repeated word",
            ErrorType.OVERUSED_PHRASE: "Repeated phrase"}.get(t, "Flag")


def _chapter_title(editor: Any) -> str:
    w = editor
    while w is not None:
        ch = getattr(w, "chapter", None)
        if ch is not None and hasattr(ch, "title"):
            return ch.title or ""
        w = w.parent() if hasattr(w, "parent") else None
    return ""


def mark_flag(editor: Any, error: Any, block: Any = None) -> Any:
    """Mark the flag intentional. Returns the style sheet line added (or
    None when it was already there)."""
    from src.ai import intentional
    project = getattr(editor, "_project", None)
    if project is None:
        return None
    category = _CATEGORY.get(getattr(error.error_type, "value", ""), "")
    text = error.word
    if category in ("grammar", "style") and block is not None:
        text = block.text()[error.start:error.end] or error.word
    saved, rule = intentional.mark(project, intentional.flag_key(error), text,
                                   error.reason or "", _label(error), _chapter_title(editor),
                                   category=category, word=error.word)
    if not saved:
        announce(editor, "Couldn't save that it's intentional (see the readiness file).")
        return None
    announce(editor, f"Marked intentional; added to your style sheet: {rule.text}" if rule
             else "Marked intentional; it won't be flagged again in this project.")
    return rule


def announce(editor: Any, message: str) -> None:
    """The style sheet changed: redraw the editor, and tell the Companion
    (which refreshes its list and marks the project changed)."""
    if editor is None:
        return
    try:
        editor.refresh_style_sheet()
    except Exception as e:                       # noqa: BLE001
        print(f"[intentional] redraw: {e}")
    signal = getattr(editor, "style_sheet_changed", None)
    if signal is not None:
        signal.emit(message)
    # The rule lives in the project file: make sure the project is marked
    # changed even with no Companion listening.
    w = editor.parent() if hasattr(editor, "parent") else None
    while w is not None:
        if getattr(w, "chapter", None) is not None and hasattr(w, "content_changed"):
            w.content_changed.emit()
            break
        w = w.parent() if hasattr(w, "parent") else None
