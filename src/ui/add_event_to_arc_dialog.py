"""Add-event-to-arc dialog used by the general AI chat.

When the user has been discussing a beat with the chat and wants to
commit it to a chapter's plot arc, this dialog opens with the AI's
last response pre-filled. The user can:
  * Pick the target chapter (defaults to the current chapter)
  * Edit the event text + description
  * Pick the arc stage (exposition / rising / climax / falling /
    resolution) — auto-detected from the AI text when possible
  * Slide the arc position (0-100) to place the beat

Pressing Add invokes the host's callback with the chosen chapter
and event spec. The host (main window) wires the callback to push
the new beat onto the ChapterPlannerWidget.
"""

from __future__ import annotations

import re
from typing import Any, Callable, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QSlider, QSpinBox,
    QVBoxLayout, QWidget,
)


_STAGES = (
    ("exposition", "Exposition"),
    ("rising",     "Rising action"),
    ("climax",     "Climax"),
    ("falling",    "Falling action"),
    ("resolution", "Resolution"),
)

_STAGE_DEFAULT_POS = {
    "exposition": 10,
    "rising":     30,
    "climax":     55,
    "falling":    75,
    "resolution": 90,
}


def _guess_stage_from_text(text: str) -> str:
    """Best-effort stage detection from the AI's wording.

    Looks for explicit ``[stage]`` markers first (the chapter
    planner's event format), then falls back to keyword scoring
    over each stage's signal vocabulary. Returns ``"rising"`` when
    nothing matches — the safest middle of the arc.
    """
    if not text:
        return "rising"
    bracket = re.search(r"\[(exposition|rising|climax|falling|"
                        r"resolution|denouement)\b", text.lower())
    if bracket:
        m = bracket.group(1)
        if m == "denouement":
            return "resolution"
        return m
    low = text.lower()
    signals = {
        "exposition": ("opening", "introduce", "setup", "establish",
                       "first time", "we meet"),
        "rising":     ("tension", "builds", "complicates",
                       "escalate", "reveal", "confront"),
        "climax":     ("climax", "turning point", "showdown",
                       "decisive", "all is lost", "midpoint"),
        "falling":    ("aftermath", "consequence", "reckoning",
                       "fallout"),
        "resolution": ("conclude", "resolve", "denouement", "ending",
                       "closes", "epilogue"),
    }
    best = ("rising", 0)
    for stage, terms in signals.items():
        score = sum(1 for t in terms if t in low)
        if score > best[1]:
            best = (stage, score)
    return best[0]


class AddEventToArcDialog(QDialog):
    """Refine a proposed event before committing it to a chapter."""

    def __init__(
        self,
        chapters: List[Any],
        proposed_text: str = "",
        proposed_description: str = "",
        initial_chapter_id: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Add event to chapter arc")
        self.setModal(True)
        self.resize(620, 560)
        self._chapters = list(chapters)
        self._initial_chapter_id = initial_chapter_id
        self._build_ui(proposed_text, proposed_description)

    # ------------------------------------------------------------------
    # Results — callers grab these after exec() returns Accepted
    # ------------------------------------------------------------------
    def selected_chapter(self) -> Optional[Any]:
        return self._chapter_combo.currentData()

    def event_text(self) -> str:
        return self._text_edit.text().strip()

    def event_description(self) -> str:
        return self._desc_edit.toPlainText().strip()

    def event_stage(self) -> str:
        return self._stage_combo.currentData() or "rising"

    def event_arc_position(self) -> int:
        return int(self._arc_slider.value())

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(
        self, proposed_text: str, proposed_description: str,
    ) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Refine the beat and pick where it lands on the arc, "
            "then click <b>Add</b> to drop it on the chapter's "
            "plot arc."))

        form = QFormLayout()

        # Chapter
        self._chapter_combo = QComboBox()
        for ch in self._chapters:
            num = getattr(ch, "number", 0)
            title = getattr(ch, "title", "") or "(untitled)"
            label = f"Ch. {num}: {title}" if num else title
            self._chapter_combo.addItem(label, ch)
        if self._initial_chapter_id:
            for i, ch in enumerate(self._chapters):
                if getattr(ch, "id", "") == self._initial_chapter_id:
                    self._chapter_combo.setCurrentIndex(i)
                    break
        form.addRow("Chapter", self._chapter_combo)

        # Event text — single line for the headline
        self._text_edit = QLineEdit()
        self._text_edit.setPlaceholderText(
            "Short, concrete: who does what, where")
        # Strip any leading [stage] marker / numbering from the
        # proposed text; we'll set the stage explicitly via the combo.
        cleaned = re.sub(r"^\s*\d+[\.\):]?\s*", "",
                         proposed_text or "")
        cleaned = re.sub(r"^\s*\[[^\]]+\]\s*", "", cleaned).strip()
        self._text_edit.setText(cleaned[:300])
        form.addRow("Event text", self._text_edit)

        # Stage — pre-guessed from the proposed text
        self._stage_combo = QComboBox()
        for value, label in _STAGES:
            self._stage_combo.addItem(label, value)
        guessed = _guess_stage_from_text(proposed_text)
        for i in range(self._stage_combo.count()):
            if self._stage_combo.itemData(i) == guessed:
                self._stage_combo.setCurrentIndex(i)
                break
        self._stage_combo.currentIndexChanged.connect(
            self._on_stage_changed)
        form.addRow("Arc stage", self._stage_combo)

        # Arc position — slider + numeric readout
        arc_row = QHBoxLayout()
        self._arc_slider = QSlider(Qt.Orientation.Horizontal)
        self._arc_slider.setRange(0, 100)
        self._arc_slider.setValue(_STAGE_DEFAULT_POS.get(guessed, 50))
        self._arc_slider.setTickInterval(10)
        self._arc_slider.setTickPosition(
            QSlider.TickPosition.TicksBelow)
        self._arc_pos_spin = QSpinBox()
        self._arc_pos_spin.setRange(0, 100)
        self._arc_pos_spin.setSuffix(" / 100")
        self._arc_pos_spin.setValue(self._arc_slider.value())
        self._arc_slider.valueChanged.connect(
            self._arc_pos_spin.setValue)
        self._arc_pos_spin.valueChanged.connect(
            self._arc_slider.setValue)
        arc_row.addWidget(self._arc_slider, stretch=1)
        arc_row.addWidget(self._arc_pos_spin)
        form.addRow("Arc position", arc_row)

        # Description — longer notes, optional
        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setPlaceholderText(
            "Optional notes — context, character motivation, "
            "what the beat sets up, etc.")
        self._desc_edit.setPlainText(proposed_description or "")
        self._desc_edit.setMaximumHeight(140)
        form.addRow("Description", self._desc_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QDialogButtonBox.StandardButton.Ok).setText("Add to arc")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_stage_changed(self, _index: int) -> None:
        """When the user picks a different stage, jump the arc
        slider to that stage's canonical position so the beat lands
        in the right zone by default."""
        stage = self._stage_combo.currentData()
        if not stage:
            return
        self._arc_slider.setValue(_STAGE_DEFAULT_POS.get(stage, 50))
