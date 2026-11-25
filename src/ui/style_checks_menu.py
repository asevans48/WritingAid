"""The "Style checks" submenu of the editor's ✓ Checks ▾ menu (piece D.3).

One switch per style check, each with how many it finds in the chapter
now, and at the top the chapter's summary (issues, per 1,000 words, and the
share of sentences with a transition while Few transitions is on). A
switch turns that check's highlighting (and listing) on or off. Since D.6
retired the side panel's Style tab, this is where its switches, counts and
summary live; its list is the Companion's next-fix card.
No new toolbar control: the menu was already there (agreed in 0.2).
The ticks, and the Spelling / Grammar / Overused words / Style switches,
are remembered per project (``src/data/check_switches.py``, 24 Nov 2026).
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


def summary(editor: Any, found: Dict[str, int]) -> str:
    """The retired Style tab's summary line: issues of the checks that are
    on, per 1,000 words, and the transitions share (P.2a)."""
    on = editor.writing_highlighter._style_kinds
    total = sum(n for kind, n in found.items() if kind in on)
    text = editor.toPlainText()
    words = len(text.split())
    line = f"{total} issue{'s' if total != 1 else ''}"
    if words:
        line += f" · {round(1000 * total / words, 1)}/1,000 words"
    if "transition" in on:
        from src.utils.style_reports import transition_share
        used, sentences = transition_share(text)
        if sentences:
            line += f" · transitions in {round(100 * used / sentences)}% of sentences"
    return line


def install(chapter_editor: Any) -> QMenu:
    """Add the submenu above "Style issues panel…"."""
    menu = chapter_editor.checks_menu
    sub = QMenu("Style checks", menu)
    sub.setToolTipsVisible(True)
    head = QAction("", sub)
    head.setEnabled(False)                    # information, not an action
    sub.addAction(head)
    sub.addSeparator()
    chapter_editor._style_summary_action = head
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
        head.setText(summary(chapter_editor.editor, found))
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
    _restore(chapter_editor)
    refresh()
    return sub


def _set(chapter_editor: Any, kind: str, on: bool) -> None:
    hl = chapter_editor.editor.writing_highlighter
    kinds = set(hl._style_kinds)
    (kinds.add if on else kinds.discard)(kind)
    hl.set_style_kinds(kinds)
    _remember(chapter_editor)


def _restore(chapter_editor: Any) -> None:
    """Apply the project's remembered switches (without opening the style
    list, as ticking Style by hand does) and save every later change."""
    project = getattr(chapter_editor, "project", None)
    switches = getattr(chapter_editor, "_check_actions", None)
    if project is None or not switches:
        return
    from src.data import check_switches
    kinds, on = check_switches.resolve(project)
    chapter_editor.editor.writing_highlighter.set_style_kinds(kinds)
    for key, act in switches.items():
        if key in on:
            act.blockSignals(True)
            act.setChecked(on[key])
            act.blockSignals(False)
    chapter_editor._apply_check_modes()
    for act in switches.values():
        act.toggled.connect(lambda _on: _remember(chapter_editor))


def _remember(chapter_editor: Any) -> None:
    project = getattr(chapter_editor, "project", None)
    switches = getattr(chapter_editor, "_check_actions", None) or {}
    if project is None:
        return
    from src.data import check_switches
    check_switches.remember(project,
                            set(chapter_editor.editor.writing_highlighter._style_kinds),
                            {k: a.isChecked() for k, a in switches.items()})
