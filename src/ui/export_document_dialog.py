"""Pick a scope (current chapter / entire book) and an office format
(Word, RTF, TXT, ODT, ODS) for a manuscript export.

When the project has scene markers (7.4), one tick, "Mark scene breaks",
puts the standard centred "#" at each marked scene in the exported copy
only. Unticked by default: the export is the text exactly as written."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QLabel, QRadioButton, QVBoxLayout,
)

from src.export.manuscript_exporter import DOCUMENT_FORMATS


class ExportDocumentDialog(QDialog):
    """Small chooser used by File → Export Chapter / Book. Exposes
    ``scope()`` ("chapter" | "book"), ``fmt()`` (format key) and
    ``extension()`` after the writer accepts it."""

    def __init__(
        self, has_current_chapter: bool, parent=None, scene_marks: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Chapter / Book")
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Export the current chapter or the whole "
                           "book, in the format you choose."))

        form = QFormLayout()
        self._book_radio = QRadioButton("Entire book")
        self._chapter_radio = QRadioButton("Current chapter")
        self._scope = QButtonGroup(self)
        self._scope.addButton(self._book_radio)
        self._scope.addButton(self._chapter_radio)
        if has_current_chapter:
            self._chapter_radio.setChecked(True)
        else:
            self._chapter_radio.setEnabled(False)
            self._chapter_radio.setToolTip(
                "Open a chapter in the editor to export just that one.")
            self._book_radio.setChecked(True)
        form.addRow("Scope", self._book_radio)
        form.addRow("", self._chapter_radio)

        self._format = QComboBox()
        for key, label, ext in DOCUMENT_FORMATS:
            self._format.addItem(label, (key, ext))
        form.addRow("Format", self._format)
        # 7.4: only when there are markers to mark.
        self._marks = QCheckBox("Mark scene breaks")
        self._marks.setToolTip("Put the standard centred “#” at each scene you marked, in the "
                               "exported copy only. Your text is not changed.")
        self._has_marks = bool(scene_marks)
        self._marks.setVisible(self._has_marks)
        if scene_marks:
            form.addRow("", self._marks)
        v.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def scope(self) -> str:
        return "chapter" if self._chapter_radio.isChecked() else "book"

    def fmt(self) -> str:
        return self._format.currentData()[0]

    def extension(self) -> str:
        return self._format.currentData()[1]

    def mark_scenes(self) -> bool:
        """The "Mark scene breaks" tick (7.4)."""
        return self._has_marks and self._marks.isChecked()

    def format_label(self) -> str:
        return self._format.currentText()
