"""Plot event editor for managing story events."""

from typing import List, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit,
    QComboBox, QSlider, QFormLayout, QGroupBox, QDialog, QDialogButtonBox,
    QListWidget, QCheckBox, QScrollArea, QSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal

from src.models.project import PlotEvent


class PlotEventEditor(QDialog):
    """Dialog for editing a single plot event."""

    def __init__(self, event: Optional[PlotEvent] = None, available_characters: List[str] = None,
                 available_subplots: List = None, parent=None):
        """Initialize plot event editor.

        Args:
            event: PlotEvent to edit (None for new event)
            available_characters: List of character names
            available_subplots: List of subplot objects with id and title
            parent: Parent widget
        """
        super().__init__(parent)
        self.event = event or PlotEvent(
            id="",
            title="",
            description="",
            outcome="",
            stage="rising_action",
            intensity=50,
            sort_order=0,
            related_characters=[],
            related_subplots=[],
            notes=""
        )
        self.available_characters = available_characters or []
        self.available_subplots = available_subplots or []
        self._init_ui()
        if event:
            self._load_event()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Plot Event Editor")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)  # Reduced for laptop compatibility

        layout = QVBoxLayout(self)

        # Create scrollable area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        # Basic info
        basic_group = QGroupBox("Event Details")
        basic_layout = QFormLayout()

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Brief event title")
        basic_layout.addRow("Title:*", self.title_edit)

        self.stage_combo = QComboBox()
        self.stage_combo.addItems([
            "Exposition",
            "Rising Action",
            "Climax",
            "Falling Action",
            "Resolution"
        ])
        self.stage_combo.setCurrentIndex(1)  # Default to Rising Action
        basic_layout.addRow("Story Stage:", self.stage_combo)

        self.sort_order_spin = QSpinBox()
        self.sort_order_spin.setRange(0, 1000)
        self.sort_order_spin.setToolTip("Order of this event within its stage (0 = first)")
        basic_layout.addRow("Sort Order:", self.sort_order_spin)

        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)

        # Intensity slider
        intensity_group = QGroupBox("Intensity")
        intensity_layout = QVBoxLayout()

        intensity_help = QLabel("Event intensity determines vertical position on pyramid (0=low, 100=high tension)")
        intensity_help.setWordWrap(True)
        intensity_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        intensity_layout.addWidget(intensity_help)

        slider_layout = QHBoxLayout()
        self.intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self.intensity_slider.setRange(0, 100)
        self.intensity_slider.setValue(50)
        self.intensity_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.intensity_slider.setTickInterval(10)
        slider_layout.addWidget(self.intensity_slider)

        self.intensity_label = QLabel("50")
        self.intensity_label.setMinimumWidth(30)
        self.intensity_slider.valueChanged.connect(lambda v: self.intensity_label.setText(str(v)))
        slider_layout.addWidget(self.intensity_label)

        intensity_layout.addLayout(slider_layout)
        intensity_group.setLayout(intensity_layout)
        scroll_layout.addWidget(intensity_group)

        # Description
        desc_group = QGroupBox("Description")
        desc_layout = QVBoxLayout()

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Describe what happens in this event...")
        self.description_edit.setMaximumHeight(100)
        desc_layout.addWidget(self.description_edit)

        desc_group.setLayout(desc_layout)
        scroll_layout.addWidget(desc_group)

        # Outcome
        outcome_group = QGroupBox("Outcome")
        outcome_layout = QVBoxLayout()

        self.outcome_edit = QTextEdit()
        self.outcome_edit.setPlaceholderText("What happens as a result of this event?")
        self.outcome_edit.setMaximumHeight(100)
        outcome_layout.addWidget(self.outcome_edit)

        outcome_group.setLayout(outcome_layout)
        scroll_layout.addWidget(outcome_group)

        # Related characters
        char_group = QGroupBox("Related Characters")
        char_layout = QVBoxLayout()

        char_help = QLabel("Characters involved in this event:")
        char_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        char_layout.addWidget(char_help)

        self.characters_edit = QTextEdit()
        self.characters_edit.setPlaceholderText("Character names (one per line)")
        self.characters_edit.setMaximumHeight(80)
        char_layout.addWidget(self.characters_edit)

        char_group.setLayout(char_layout)
        scroll_layout.addWidget(char_group)

        # Related subplots
        subplot_group = QGroupBox("Related Subplots")
        subplot_layout = QVBoxLayout()

        subplot_help = QLabel("Connect this event to subplots:")
        subplot_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        subplot_layout.addWidget(subplot_help)

        self.subplot_checkboxes = {}
        if self.available_subplots:
            for subplot in self.available_subplots:
                checkbox = QCheckBox(subplot.title)
                checkbox.setProperty("subplot_id", subplot.id)
                self.subplot_checkboxes[subplot.id] = checkbox
                subplot_layout.addWidget(checkbox)
        else:
            no_subplots_label = QLabel("No subplots available. Create subplots first.")
            no_subplots_label.setStyleSheet("color: #ef4444; font-style: italic;")
            subplot_layout.addWidget(no_subplots_label)

        subplot_group.setLayout(subplot_layout)
        scroll_layout.addWidget(subplot_group)

        # Notes
        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout()

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Additional notes about this event...")
        self.notes_edit.setMaximumHeight(80)
        notes_layout.addWidget(self.notes_edit)

        notes_group.setLayout(notes_layout)
        scroll_layout.addWidget(notes_group)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_event(self):
        """Load event data into form."""
        self.title_edit.setText(self.event.title)

        # Set stage combo
        stage_map = {
            "exposition": 0,
            "rising_action": 1,
            "climax": 2,
            "falling_action": 3,
            "resolution": 4
        }
        self.stage_combo.setCurrentIndex(stage_map.get(self.event.stage, 1))

        self.sort_order_spin.setValue(self.event.sort_order)
        self.intensity_slider.setValue(self.event.intensity)
        self.description_edit.setPlainText(self.event.description)
        self.outcome_edit.setPlainText(self.event.outcome)

        # Characters
        if self.event.related_characters:
            self.characters_edit.setPlainText("\n".join(self.event.related_characters))

        # Subplots
        for subplot_id in self.event.related_subplots:
            if subplot_id in self.subplot_checkboxes:
                self.subplot_checkboxes[subplot_id].setChecked(True)

        self.notes_edit.setPlainText(self.event.notes)

    def _save(self):
        """Save event data."""
        title = self.title_edit.text().strip()
        if not title:
            return  # Don't save without title

        # Generate ID from title if needed
        if not self.event.id:
            import uuid
            self.event.id = str(uuid.uuid4())

        self.event.title = title

        # Get stage from combo
        stage_map = ["exposition", "rising_action", "climax", "falling_action", "resolution"]
        self.event.stage = stage_map[self.stage_combo.currentIndex()]

        self.event.sort_order = self.sort_order_spin.value()
        self.event.intensity = self.intensity_slider.value()
        self.event.description = self.description_edit.toPlainText().strip()
        self.event.outcome = self.outcome_edit.toPlainText().strip()

        # Get characters
        char_text = self.characters_edit.toPlainText().strip()
        self.event.related_characters = [c.strip() for c in char_text.split("\n") if c.strip()]

        # Get selected subplots
        self.event.related_subplots = [
            subplot_id for subplot_id, checkbox in self.subplot_checkboxes.items()
            if checkbox.isChecked()
        ]

        self.event.notes = self.notes_edit.toPlainText().strip()

        self.accept()

    def get_event(self) -> PlotEvent:
        """Get the edited event."""
        return self.event
