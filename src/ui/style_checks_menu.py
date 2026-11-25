"""The "Style checks" submenu of the editor's ✓ Checks ▾ menu (piece D.3).

One switch per style check, as the Style tab has, each with how many it
finds in the chapter now. A switch turns that check's highlighting (and
listing) on or off; the Style tab's boxes follow, and the other way round.
No new toolbar control: the menu was already there (agreed in 0.2).
"""

from __future__ import annotations

from typing import Any, Dict

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

from src.utils.style_checks import KINDS


def counts(editor: Any) -> Dict[str, int]:
    """How many of each style kind the editor finds in its text now."""
    hl = editor.writing_highlighter
    out: Dict[str, int] = {}
    saved = set(hl._style_kinds)
    hl._style_kinds = set(KINDS)              # count every kind, even those switched off
    try:
        block = editor.document().begin()
        while block.isValid():
            if block.text().strip():
                for issue in hl.style_issues_for(block.text()):
                    out[issue.kind] = out.get(issue.kind, 0) + 1
            block = block.next()
    finally:
        hl._style_kinds = saved
    return out


def install(chapter_editor: Any) -> QMenu:
    """Add the submenu above "Style issues panel…"."""
    menu = chapter_editor.checks_menu
    sub = QMenu("Style checks", menu)
    sub.setToolTipsVisible(True)
    actions: Dict[str, QAction] = {}
    for kind, (label, _colour, _sentence) in KINDS.items():
        act = QAction(label, sub)
        act.setCheckable(True)
        act.setToolTip("Untick to stop highlighting (and listing) this check.")
        act.toggled.connect(lambda on, k=kind: _set(chapter_editor, k, on))
        sub.addAction(act)
        actions[kind] = act
    chapter_editor._style_check_actions = actions

    def refresh() -> None:
        found = counts(chapter_editor.editor)
        on = chapter_editor.editor.writing_highlighter._style_kinds
        for kind, act in actions.items():
            n = found.get(kind, 0)
            act.blockSignals(True)
            act.setChecked(kind in on)
            act.setText(f"{KINDS[kind][0]}  ({n})")
            act.blockSignals(False)
    sub.aboutToShow.connect(refresh)
    before = next((a for a in menu.actions() if a.text() == "Style issues panel…"), None)
    if before is not None:
        menu.insertMenu(before, sub)
    else:
        menu.addMenu(sub)
    refresh()
    return sub


def _set(chapter_editor: Any, kind: str, on: bool) -> None:
    hl = chapter_editor.editor.writing_highlighter
    kinds = set(hl._style_kinds)
    (kinds.add if on else kinds.discard)(kind)
    hl.set_style_kinds(kinds)
    panel = getattr(chapter_editor, "style_panel", None)      # the Style tab follows
    if panel is not None and kind in getattr(panel, "kind_boxes", {}):
        cb = panel.kind_boxes[kind][0]
        cb.blockSignals(True)
        cb.setChecked(on)
        cb.blockSignals(False)
        panel.refresh()
