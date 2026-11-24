"""The spelling options in Settings → Writing Analysis: accept British
spellings, accept older (period) spellings (``spelling_varieties``)."""

from __future__ import annotations

from typing import Any, Dict

from PyQt6.QtWidgets import QCheckBox

from src.utils import spelling_varieties as sv


class SpellingOptions:
    def __init__(self, layout, settings: Dict[str, Any]):
        self.british = QCheckBox("Accept British spellings (colour, realise, centre, travelled)")
        self.british.setToolTip(
            "The dictionary is American. With this on, a British spelling is accepted when "
            "its American form is a real word. Mixing the two in one book is still reported "
            "by Edit → Consistency.")
        self.british.setChecked(bool(settings.get(sv.KEY_BRITISH, False)))
        layout.addWidget(self.british)
        self.period = QCheckBox("Accept older, period spellings (connexion, shew, gaol, 'tis, thou)")
        self.period.setToolTip("For historical fiction and older texts: spellings and words "
                               "from earlier English are not marked as misspelt.")
        self.period.setChecked(bool(settings.get(sv.KEY_PERIOD, False)))
        layout.addWidget(self.period)

    def values(self) -> Dict[str, bool]:
        return {sv.KEY_BRITISH: self.british.isChecked(), sv.KEY_PERIOD: self.period.isChecked()}


def apply_spelling_settings(main_window) -> None:
    """After Settings is saved: use the new spelling options at once."""
    if not sv.reload():
        return
    try:
        ce = main_window.manuscript_editor.current_chapter_editor
        if ce is not None:
            ce.editor.writing_highlighter.rehighlight()
    except Exception as e:
        print(f"[spelling] could not refresh the editor: {e}")
