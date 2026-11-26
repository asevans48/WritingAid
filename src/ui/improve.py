"""One Improve window: how a passage is opened in it (piece D.2b).

``open(host, tab, text, start, end, …)`` opens the Improve window
(``improve_window.ImproveWindow``) on a tab and, when the writer accepts a
version, puts it into the chapter through the call the old window used
(``apply``). It returns True when text was put in place, as the old callers
expect (a True still clears a Companion note, a 👂 mark or a fix).

``rephrase(host, cursor, …)`` (D.2c) opens it on ✨ Rephrase for the
highlighted text, with exactly the arguments the old Rephrase window got;
the other tabs work on the highlight widened to whole sentences. It is
used by Ctrl+R and ✨, the right-click Rephrase, a style flag's ✨ Rewrite
with AI, and the draft window's Rephrase.

**The trial switch** (rule 11: trial, then retire): Settings ▸ Features ▸
*Improve window*. Ticked, Rephrase, Suggestions and Overly descriptive?
open in the one window; unticked, the old ``RephraseDialog``,
``PassageCritiqueDialog`` and ``ExpandStatementDialog`` open exactly as
before. It starts ticked (decision 16). Kept as ``improve/merged`` beside
the window positions; a missing or unreadable value means the starting
position.
"""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtWidgets import QCheckBox, QDialog, QGroupBox, QVBoxLayout

SETTING_KEY = "improve/merged"
STARTS_ON = True                 # decision 16: the trial switch starts on

# The tabs, in order (decision 16): Ctrl+1 … Ctrl+4.
TABS = ("suggestions", "critique", "rephrase", "expand")

# The name each tool gives ``_replace_span`` (its message's title), as today.
TOOL_NAMES = {"suggestions": "Suggestions", "expand": "Overly descriptive",
              "rephrase": "Rephrase"}


def _settings():
    from src.ui.ui_kit import _settings as kit_settings
    return kit_settings()


def merged() -> bool:
    """True when the Improve window is used (the default), False for the
    old windows."""
    try:
        value = _settings().value(SETTING_KEY, None)
    except Exception:                        # unreadable: the starting position
        return STARTS_ON
    if value is None or value == "":
        return STARTS_ON
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    return STARTS_ON


def set_merged(on: bool) -> None:
    try:
        s = _settings()
        s.setValue(SETTING_KEY, "true" if on else "false")
        s.sync()
    except Exception as e:                   # a setting never breaks the app
        print(f"[improve] could not save the switch: {e}")


def open(host: Any, tab: str, text: str, start: int, end: int, *,
         selection: Optional[tuple] = None, focus: str = "", window_factory=None,
         chapter: Any = None, **window_kw) -> bool:
    """Open the Improve window on ``text[start:end]`` (Python indices) at
    ``tab``, over the window ``host`` (a ``ChapterEditor``, or a draft
    window's panel) is in. True when the accepted version was put in place."""
    if window_factory is None:
        from src.ui.improve_window import ImproveWindow
        window_factory = ImproveWindow
    parent = host.window() if hasattr(host, "window") else None
    if chapter is None:
        chapter = getattr(host, "chapter", None)
    window = window_factory(text, start, end, getattr(host, "project", None),
                            chapter, parent, tab=tab,
                            selection=selection, focus=focus, **window_kw)
    if window.exec() != QDialog.DialogCode.Accepted or not window.replacement:
        return False
    return apply(host, window, text)


def rephrase(host: Any, cursor: Any, *, instruction: str = "", chapter: Any = None,
             draft: bool = False, **kw) -> bool:
    """✨ Rephrase on the highlighted text (``cursor``'s selection in
    ``host.editor``), with the arguments the old Rephrase window got: 500
    characters either side, the chapter's text, the hint from a style
    flag. The other tabs get the highlight widened to whole sentences."""
    from src.ai.passage_critique import expand_to_sentences, qt_to_py_index
    doc = host.editor.toPlainText()
    qs, qe = cursor.selectionStart(), cursor.selectionEnd()
    ps, pe = qt_to_py_index(doc, qs), qt_to_py_index(doc, qe)
    args = dict(text=cursor.selectedText(),
                surrounding_context=(doc[max(0, qs - 500):qs], doc[qe:qe + 500]),
                chapter_content=doc, chapter=chapter, instruction=instruction,
                text_before=doc[:qs] if draft else doc[:ps])
    start, end = expand_to_sentences(doc, ps, pe)
    return open(host, "rephrase", doc, start, end, selection=(ps, pe), chapter=chapter,
                rephrase=args, **kw)


def apply(host: Any, window: Any, text: str) -> bool:
    """Put the window's accepted version in place through the call its tool
    uses (``_replace_span``, with its check that the chapter has not changed
    meanwhile). Rephrase replaces exactly the highlight, with the same tidy
    paragraphs its old window's insert gave. A draft window has its own
    branch: the same check, its own insert, and the draft marked unsaved."""
    start, end = window.span
    tool = TOOL_NAMES.get(window.tool, "Suggestions")
    if not hasattr(host, "_replace_span"):
        return _apply_to_draft(host, text, start, end, window.replacement, tool)
    return host._replace_span(text, start, end, window.replacement, tool)


def _apply_to_draft(host: Any, text: str, start: int, end: int, replacement: str,
                    tool: str) -> bool:
    from PyQt6.QtGui import QTextCursor
    from PyQt6.QtWidgets import QMessageBox
    from src.ai.passage_critique import py_to_qt_index
    editor = host.editor
    if editor.toPlainText() != text:
        QMessageBox.information(host, tool, "The draft changed while the window was open, so "
                                f"the change wasn't inserted. Run {tool} again.")
        return False
    cursor = QTextCursor(editor.document())
    cursor.setPosition(py_to_qt_index(text, start))
    cursor.setPosition(py_to_qt_index(text, end), QTextCursor.MoveMode.KeepAnchor)
    cursor.insertText(replacement)              # as the draft's Rephrase always did
    editor.setTextCursor(cursor)
    host._set_dirty(True)
    return True


class ImproveOption:
    """Settings ▸ Features ▸ Improve window (two call lines in
    ``SettingsDialog``, as ``TabsOption``)."""

    def __init__(self, layout):
        group = QGroupBox("Improve window")
        lay = QVBoxLayout()
        self.box = QCheckBox("Open Rephrase, Suggestions and Overly descriptive? in one "
                             "Improve window")
        self.box.setToolTip("One window with tabs: Suggestions · Critique · Rephrase · Expand. "
                            "Untick for the separate windows as they were.")
        self.box.setChecked(merged())
        lay.addWidget(self.box)
        group.setLayout(lay)
        layout.addWidget(group)

    def save(self) -> None:
        try:
            if self.box.isChecked() != merged():
                set_merged(self.box.isChecked())
        except Exception as e:                       # noqa: BLE001
            print(f"[improve] could not save: {e}")
