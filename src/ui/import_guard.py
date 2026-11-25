"""Ask before an import replaces a chapter's text (piece 9.2).

"Import from Word" replaces the whole chapter. Before 9.2 it did so without
asking and the old text could not be undone. Now a chapter with text asks
first (the safe answer is the default), and the replacement is one undo
step (``EnhancedTextEditor.import_from_docx``).
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QMessageBox


def may_replace(parent: Any, current_text: str) -> bool:
    """True when the chapter is empty, or the writer agrees to replace it."""
    if not (current_text or "").strip():
        return True
    words = len(current_text.split())
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Replace this chapter?")
    box.setText(f"Importing replaces this chapter's text ({words:,} words) with the "
                "Word document's.")
    box.setInformativeText("Ctrl+Z puts the current text back afterwards. "
                           "To keep both, save the chapter as a new draft first.")
    replace = box.addButton("Replace", QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel)
    box.exec()
    return box.clickedButton() is replace
