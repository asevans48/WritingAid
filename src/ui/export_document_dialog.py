"""Pick a scope (current chapter / entire book) and an office format
(Word, RTF, TXT, ODT, ODS) for a manuscript export."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QLabel, QRadioButton, QVBoxLayout,
)

from src.export.manuscript_exporter import DOCUMENT_FORMATS


class ExportDocumentDialog(QDialog):
    """Small chooser used by File → Export Chapter / Book. Exposes
    ``scope()`` ("chapter" | "book"), ``fmt()`` (format key) and
    ``extension()`` after the writer accepts it."""

    def __init__(
        self, has_current_chapter: bool, parent=None,
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

    def format_label(self) -> str:
        return self._format.currentText()
