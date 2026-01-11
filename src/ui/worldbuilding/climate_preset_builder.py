"""Climate preset builder for creating reusable climate templates."""

from typing import List, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QLabel, QLineEdit, QTextEdit, QFormLayout, QGroupBox,
    QDialog, QDialogButtonBox, QListWidgetItem, QScrollArea
)
from PyQt6.QtCore import pyqtSignal, Qt

from src.models.worldbuilding_objects import ClimatePreset


class ClimatePresetEditor(QDialog):
    """Dialog for editing a climate preset."""

    def __init__(self, preset: Optional[ClimatePreset] = None, parent=None):
        """Initialize climate preset editor.

        Args:
            preset: Climate preset to edit (None for new preset)
            parent: Parent widget
        """
        super().__init__(parent)
        self.preset = preset or ClimatePreset(
            id="",
            name="",
            description="",
            default_zones=[],
            temperature_range="",
            precipitation_pattern="",
            seasons=[],
            atmospheric_composition="",
            weather_patterns="",
            extreme_events=[],
            notes=""
        )
        self._init_ui()
        if preset:
            self._load_preset()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Climate Preset Editor")
        self.setMinimumWidth(600)
        self.setMinimumHeight(650)

        layout = QVBoxLayout(self)

        # Create scrollable area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        # Basic info
        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g., 'Earth-like', 'Desert World', 'Ice Planet'")
        basic_layout.addRow("Preset Name:*", self.name_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Brief description of this climate type...")
        self.description_edit.setMaximumHeight(60)
        basic_layout.addRow("Description:", self.description_edit)

        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)

        # Climate zones
        zones_group = QGroupBox("Default Climate Zones")
        zones_layout = QVBoxLayout()

        zones_help = QLabel("Climate zones for this preset (one per line):")
        zones_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        zones_layout.addWidget(zones_help)

        self.zones_edit = QTextEdit()
        self.zones_edit.setPlaceholderText("e.g.:\nTropical\nTemperate\nArctic")
        self.zones_edit.setMaximumHeight(80)
        zones_layout.addWidget(self.zones_edit)

        zones_group.setLayout(zones_layout)
        scroll_layout.addWidget(zones_group)

        # Climate characteristics
        char_group = QGroupBox("Climate Characteristics")
        char_layout = QFormLayout()

        self.temp_range_edit = QLineEdit()
        self.temp_range_edit.setPlaceholderText("e.g., '-50°C to 50°C'")
        char_layout.addRow("Temperature Range:", self.temp_range_edit)

        self.precip_edit = QLineEdit()
        self.precip_edit.setPlaceholderText("e.g., 'Seasonal monsoons', 'Low precipitation'")
        char_layout.addRow("Precipitation Pattern:", self.precip_edit)

        self.atmosphere_edit = QLineEdit()
        self.atmosphere_edit.setPlaceholderText("e.g., '78% N2, 21% O2, 1% Ar'")
        char_layout.addRow("Atmospheric Composition:", self.atmosphere_edit)

        char_group.setLayout(char_layout)
        scroll_layout.addWidget(char_group)

        # Seasons
        seasons_group = QGroupBox("Seasons")
        seasons_layout = QVBoxLayout()

        seasons_help = QLabel("Seasons for this climate (one per line):")
        seasons_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        seasons_layout.addWidget(seasons_help)

        self.seasons_edit = QTextEdit()
        self.seasons_edit.setPlaceholderText("e.g.:\nSpring\nSummer\nFall\nWinter")
        self.seasons_edit.setMaximumHeight(80)
        seasons_layout.addWidget(self.seasons_edit)

        seasons_group.setLayout(seasons_layout)
        scroll_layout.addWidget(seasons_group)

        # Weather patterns
        weather_group = QGroupBox("Weather Patterns")
        weather_layout = QVBoxLayout()

        self.weather_edit = QTextEdit()
        self.weather_edit.setPlaceholderText("Describe general weather patterns...")
        self.weather_edit.setMaximumHeight(80)
        weather_layout.addWidget(self.weather_edit)

        weather_group.setLayout(weather_layout)
        scroll_layout.addWidget(weather_group)

        # Extreme events
        extreme_group = QGroupBox("Extreme Weather Events")
        extreme_layout = QVBoxLayout()

        extreme_help = QLabel("Extreme weather events (one per line):")
        extreme_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        extreme_layout.addWidget(extreme_help)

        self.extreme_edit = QTextEdit()
        self.extreme_edit.setPlaceholderText("e.g.:\nHurricanes\nTornadoes\nBlizzards")
        self.extreme_edit.setMaximumHeight(80)
        extreme_layout.addWidget(self.extreme_edit)

        extreme_group.setLayout(extreme_layout)
        scroll_layout.addWidget(extreme_group)

        # Notes
        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout()

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Additional notes about this climate preset...")
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

    def _load_preset(self):
        """Load preset data into form."""
        self.name_edit.setText(self.preset.name)
        self.description_edit.setPlainText(self.preset.description)

        # Default zones
        if self.preset.default_zones:
            self.zones_edit.setPlainText("\n".join(self.preset.default_zones))

        self.temp_range_edit.setText(self.preset.temperature_range or "")
        self.precip_edit.setText(self.preset.precipitation_pattern or "")
        self.atmosphere_edit.setText(self.preset.atmospheric_composition or "")

        # Seasons
        if self.preset.seasons:
            self.seasons_edit.setPlainText("\n".join(self.preset.seasons))

        self.weather_edit.setPlainText(self.preset.weather_patterns)

        # Extreme events
        if self.preset.extreme_events:
            self.extreme_edit.setPlainText("\n".join(self.preset.extreme_events))

        self.notes_edit.setPlainText(self.preset.notes)

    def _save(self):
        """Save preset data."""
        name = self.name_edit.text().strip()
        if not name:
            return  # Don't save without name

        # Generate ID from name if needed
        if not self.preset.id:
            self.preset.id = name.lower().replace(" ", "-")

        self.preset.name = name
        self.preset.description = self.description_edit.toPlainText().strip()

        # Parse zones
        zones_text = self.zones_edit.toPlainText().strip()
        self.preset.default_zones = [z.strip() for z in zones_text.split("\n") if z.strip()]

        self.preset.temperature_range = self.temp_range_edit.text().strip()
        self.preset.precipitation_pattern = self.precip_edit.text().strip()
        self.preset.atmospheric_composition = self.atmosphere_edit.text().strip()

        # Parse seasons
        seasons_text = self.seasons_edit.toPlainText().strip()
        self.preset.seasons = [s.strip() for s in seasons_text.split("\n") if s.strip()]

        self.preset.weather_patterns = self.weather_edit.toPlainText().strip()

        # Parse extreme events
        extreme_text = self.extreme_edit.toPlainText().strip()
        self.preset.extreme_events = [e.strip() for e in extreme_text.split("\n") if e.strip()]

        self.preset.notes = self.notes_edit.toPlainText().strip()

        self.accept()

    def get_preset(self) -> ClimatePreset:
        """Get the edited preset."""
        return self.preset


class ClimatePresetBuilderWidget(QWidget):
    """Widget for managing climate presets."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize climate preset builder widget."""
        super().__init__()
        self.presets: List[ClimatePreset] = []
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QHBoxLayout()
        title = QLabel("🌤️ Climate Presets")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header.addWidget(title)

        header.addStretch()

        subtitle = QLabel("Reusable climate templates for planets")
        subtitle.setStyleSheet("font-size: 12px; color: #6b7280;")
        header.addWidget(subtitle)

        layout.addLayout(header)

        # Help text
        help_text = QLabel(
            "Create named climate presets that can be applied to multiple planets. "
            "Define temperature ranges, seasons, weather patterns, and more."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #6b7280; font-size: 11px; margin-bottom: 8px;")
        layout.addWidget(help_text)

        # Toolbar
        toolbar = QHBoxLayout()

        self.add_btn = QPushButton("➕ Add Preset")
        self.add_btn.clicked.connect(self._add_preset)
        toolbar.addWidget(self.add_btn)

        self.edit_btn = QPushButton("✏️ Edit")
        self.edit_btn.clicked.connect(self._edit_preset)
        self.edit_btn.setEnabled(False)
        toolbar.addWidget(self.edit_btn)

        self.remove_btn = QPushButton("🗑️ Remove")
        self.remove_btn.clicked.connect(self._remove_preset)
        self.remove_btn.setEnabled(False)
        toolbar.addWidget(self.remove_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Preset list
        self.preset_list = QListWidget()
        self.preset_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.preset_list.itemDoubleClicked.connect(self._edit_preset)
        layout.addWidget(self.preset_list)

    def load_presets(self, presets: List[ClimatePreset]):
        """Load presets into widget.

        Args:
            presets: List of climate presets to load
        """
        self.presets = presets
        self._update_list()

    def get_presets(self) -> List[ClimatePreset]:
        """Get all presets.

        Returns:
            List of climate presets
        """
        return self.presets

    def _update_list(self):
        """Update preset list display."""
        self.preset_list.clear()

        for preset in self.presets:
            # Create display text
            zones_text = f" • {', '.join(preset.default_zones[:3])}" if preset.default_zones else ""
            if len(preset.default_zones) > 3:
                zones_text += "..."

            item_text = f"{preset.name}{zones_text}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, preset.id)
            self.preset_list.addItem(item)

    def _on_selection_changed(self):
        """Handle selection change."""
        has_selection = bool(self.preset_list.selectedItems())
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def _add_preset(self):
        """Add new preset."""
        editor = ClimatePresetEditor(parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            preset = editor.get_preset()
            self.presets.append(preset)
            self._update_list()
            self.content_changed.emit()

    def _edit_preset(self):
        """Edit selected preset."""
        items = self.preset_list.selectedItems()
        if not items:
            return

        preset_id = items[0].data(Qt.ItemDataRole.UserRole)
        preset = next((p for p in self.presets if p.id == preset_id), None)
        if not preset:
            return

        editor = ClimatePresetEditor(preset=preset, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_list()
            self.content_changed.emit()

    def _remove_preset(self):
        """Remove selected preset."""
        items = self.preset_list.selectedItems()
        if not items:
            return

        preset_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.presets = [p for p in self.presets if p.id != preset_id]
        self._update_list()
        self.content_changed.emit()
