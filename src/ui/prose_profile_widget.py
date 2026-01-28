"""Prose Profile widget for setting project tone, style, voice, and genre targets."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QGroupBox, QPushButton, QMessageBox
)
from PyQt6.QtCore import pyqtSignal

from src.models.project import ProseProfile


class ProseProfileWidget(QWidget):
    """Widget for editing the project's target prose profile."""

    content_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel("Prose Profile")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(header)

        desc = QLabel(
            "Define the target tone, style, voice, and genre for your project. "
            "The Prose Analyzer will compare each chapter against these targets."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("padding: 0 10px 10px 10px; color: #666;")
        layout.addWidget(desc)

        # Fields
        fields_group = QGroupBox("Project Targets")
        fields_layout = QVBoxLayout()
        fields_layout.setSpacing(10)

        self.tone_edit = self._add_field(
            fields_layout, "Tone",
            "Emotional tone you're aiming for (e.g. dark, tense, whimsical, intimate, foreboding)"
        )
        self.style_edit = self._add_field(
            fields_layout, "Style",
            "Prose style (e.g. minimalist, ornate, cinematic, conversational, literary)"
        )
        self.voice_edit = self._add_field(
            fields_layout, "Voice",
            "Narrative voice (e.g. sardonic first-person, intimate third-person, clinical, poetic)"
        )
        self.genre_edit = self._add_field(
            fields_layout, "Genre",
            "Genre and subgenre (e.g. noir thriller, southern gothic, space opera, literary fiction)"
        )

        # Notes as a larger text area
        notes_label = QLabel("Additional Notes")
        notes_label.setStyleSheet("font-weight: bold;")
        fields_layout.addWidget(notes_label)
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText(
            "Any extra guidance: comparable authors you're emulating, specific qualities to hit or avoid, etc."
        )
        self.notes_edit.setMaximumHeight(120)
        self.notes_edit.textChanged.connect(self.content_changed.emit)
        fields_layout.addWidget(self.notes_edit)

        fields_group.setLayout(fields_layout)
        layout.addWidget(fields_group)

        layout.addStretch()

    def _add_field(self, parent_layout, label_text: str, placeholder: str) -> QLineEdit:
        """Add a labeled line edit field."""
        lbl = QLabel(label_text)
        lbl.setStyleSheet("font-weight: bold;")
        parent_layout.addWidget(lbl)
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setStyleSheet("padding: 6px; border-radius: 4px; border: 1px solid #d1d5db;")
        edit.textChanged.connect(self.content_changed.emit)
        parent_layout.addWidget(edit)
        return edit

    def load_data(self, profile: ProseProfile):
        """Load prose profile data into the widget."""
        self.tone_edit.setText(profile.tone)
        self.style_edit.setText(profile.style)
        self.voice_edit.setText(profile.voice)
        self.genre_edit.setText(profile.genre)
        self.notes_edit.setPlainText(profile.notes)

    def get_data(self) -> ProseProfile:
        """Get prose profile data from the widget."""
        return ProseProfile(
            tone=self.tone_edit.text().strip(),
            style=self.style_edit.text().strip(),
            voice=self.voice_edit.text().strip(),
            genre=self.genre_edit.text().strip(),
            notes=self.notes_edit.toPlainText().strip(),
        )
