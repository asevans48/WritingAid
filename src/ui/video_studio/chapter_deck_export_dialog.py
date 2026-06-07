"""Pick a chapter + export options before stitching a chapter deck.

Built as its own QDialog so the studio toolbar's "Export chapter
deck" affordance opens with a focused form — chapter picker, title
card toggle, and a short summary of how many scenes will land in
the deck.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QLabel, QVBoxLayout, QWidget,
)


class ChapterDeckExportDialog(QDialog):
    """Modal picker for chapter-deck export.

    Constructor takes a list of ``(chapter_id, chapter_label,
    scene_count)`` tuples — the host (studio_widget) computes those
    so this dialog stays oblivious to the project model.
    """

    def __init__(
        self,
        chapters_with_counts: List[Tuple[str, str, int]],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Export chapter deck")
        self.setModal(True)
        self.resize(520, 280)
        self._chapters = chapters_with_counts
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Pick a chapter to export as a single video. Each "
            "scene's favorite output (image, video, or stitched "
            "slide deck) lands in the chapter deck in scene order."))
        form = QFormLayout()
        self._chapter_combo = QComboBox()
        for ch_id, label, count in self._chapters:
            display = (
                f"{label}  —  {count} scene"
                + ("s" if count != 1 else ""))
            self._chapter_combo.addItem(display, ch_id)
        # Disable Save when there are no eligible chapters; the
        # toolbar handler suppresses opening this dialog in that
        # case but defensive-disable here keeps the dialog honest
        # if it's ever opened directly from a test or harness.
        form.addRow("Chapter", self._chapter_combo)
        self._title_card_check = QCheckBox(
            "Add a title card before each scene")
        self._title_card_check.setChecked(True)
        self._title_card_check.setToolTip(
            "Renders a clean dark slate with the scene name + "
            "description, held for ~2.5 seconds. Disable for a "
            "tighter deck without breaks between scenes.")
        form.addRow("", self._title_card_check)
        layout.addLayout(form)
        self._summary_label = QLabel("")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet(
            "color: #475569; font-size: 11px;")
        layout.addWidget(self._summary_label)
        self._chapter_combo.currentIndexChanged.connect(
            self._refresh_summary)
        self._refresh_summary()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QDialogButtonBox.StandardButton.Ok).setText("Export…")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if not self._chapters:
            self._chapter_combo.setEnabled(False)
            buttons.button(
                QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            self._summary_label.setText(
                "No chapters have scenes assigned yet. Link "
                "scenes to chapters via the AI generator or by "
                "picking 'Pull from chapter' inside the scene "
                "editor.")

    def _refresh_summary(self) -> None:
        if not self._chapters:
            return
        idx = self._chapter_combo.currentIndex()
        if idx < 0:
            return
        _id, label, count = self._chapters[idx]
        self._summary_label.setText(
            f"Will stitch {count} scene"
            + ("s" if count != 1 else "")
            + f" from {label}. Each scene's favorite clip / image / "
            "stitched slide deck contributes one segment.")

    def selected_chapter_id(self) -> Optional[str]:
        return self._chapter_combo.currentData()

    def include_title_cards(self) -> bool:
        return self._title_card_check.isChecked()
