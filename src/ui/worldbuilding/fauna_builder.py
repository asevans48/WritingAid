"""Fauna builder widget for managing animal species."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QDialog, QDialogButtonBox, QLabel, QLineEdit,
    QTextEdit, QComboBox, QFormLayout, QGroupBox, QScrollArea, QSlider, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from typing import List, Optional

from src.models.worldbuilding_objects import Fauna, FaunaType, SpeciesInteraction


class FaunaEditor(QDialog):
    """Dialog for editing fauna species."""

    def __init__(self, fauna: Optional[Fauna] = None, all_fauna: List[Fauna] = None,
                 all_flora: List = None, available_planets: List[str] = None, parent=None):
        """Initialize fauna editor."""
        super().__init__(parent)
        self.fauna = fauna or Fauna(
            id="",
            name="",
            fauna_type=FaunaType.MAMMAL,
            description=""
        )
        self.all_fauna = all_fauna or []
        self.all_flora = all_flora or []
        self.available_planets = available_planets or []
        self._init_ui()
        if fauna:
            self._load_fauna()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Fauna Species Editor")
        self.setMinimumSize(600, 500)  # Reduced for laptop compatibility

        main_layout = QVBoxLayout(self)

        # Scroll area for all content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # Basic Information
        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Species name")
        basic_layout.addRow("Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value.replace("_", " ").title() for t in FaunaType])
        basic_layout.addRow("Type:", self.type_combo)

        self.scientific_name_edit = QLineEdit()
        self.scientific_name_edit.setPlaceholderText("Scientific or Latin name")
        basic_layout.addRow("Scientific Name:", self.scientific_name_edit)

        self.common_names_edit = QTextEdit()
        self.common_names_edit.setPlaceholderText("One per line")
        self.common_names_edit.setMaximumHeight(60)
        basic_layout.addRow("Common Names:", self.common_names_edit)

        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)

        # Description
        desc_group = QGroupBox("Description")
        desc_layout = QVBoxLayout()

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Describe this animal species...")
        self.description_edit.setMaximumHeight(100)
        desc_layout.addWidget(self.description_edit)

        desc_group.setLayout(desc_layout)
        scroll_layout.addWidget(desc_group)

        # Habitat
        habitat_group = QGroupBox("Habitat")
        habitat_layout = QVBoxLayout()

        # Native Planets - checkbox selection
        planets_label = QLabel("Native Planets:")
        planets_label.setStyleSheet("font-weight: bold;")
        habitat_layout.addWidget(planets_label)

        self.planet_checkboxes = {}
        self.planets_container = QWidget()
        self.planets_layout = QVBoxLayout(self.planets_container)
        self.planets_layout.setContentsMargins(0, 0, 0, 0)
        self.planets_layout.setSpacing(4)

        if self.available_planets:
            for planet_name in self.available_planets:
                checkbox = QCheckBox(planet_name)
                checkbox.setProperty("planet_name", planet_name)
                self.planet_checkboxes[planet_name] = checkbox
                self.planets_layout.addWidget(checkbox)
        else:
            no_planets_label = QLabel("No planets available. Create planets in Star Systems first.")
            no_planets_label.setStyleSheet("color: #6b7280; font-style: italic; font-size: 11px;")
            self.planets_layout.addWidget(no_planets_label)

        habitat_layout.addWidget(self.planets_container)

        # Form layout for other habitat fields
        habitat_form = QFormLayout()

        self.preferred_climate_edit = QLineEdit()
        self.preferred_climate_edit.setPlaceholderText("e.g., tropical, arctic, temperate")
        habitat_form.addRow("Preferred Climate:", self.preferred_climate_edit)

        self.habitat_edit = QLineEdit()
        self.habitat_edit.setPlaceholderText("e.g., forest, ocean, desert, mountains")
        habitat_form.addRow("Habitat:", self.habitat_edit)

        self.territory_edit = QLineEdit()
        self.territory_edit.setPlaceholderText("e.g., 5 km radius, migratory")
        habitat_form.addRow("Territory Size:", self.territory_edit)

        habitat_layout.addLayout(habitat_form)

        habitat_group.setLayout(habitat_layout)
        scroll_layout.addWidget(habitat_group)

        # Physical Characteristics
        physical_group = QGroupBox("Physical Characteristics")
        physical_layout = QFormLayout()

        self.size_edit = QLineEdit()
        self.size_edit.setPlaceholderText("e.g., 2 meters long, housecat-sized")
        physical_layout.addRow("Size:", self.size_edit)

        self.weight_edit = QLineEdit()
        self.weight_edit.setPlaceholderText("e.g., 50-70 kg")
        physical_layout.addRow("Weight:", self.weight_edit)

        self.lifespan_edit = QLineEdit()
        self.lifespan_edit.setPlaceholderText("e.g., 10-15 years")
        physical_layout.addRow("Lifespan:", self.lifespan_edit)

        self.appearance_edit = QTextEdit()
        self.appearance_edit.setPlaceholderText("Physical appearance details...")
        self.appearance_edit.setMaximumHeight(80)
        physical_layout.addRow("Appearance:", self.appearance_edit)

        physical_group.setLayout(physical_layout)
        scroll_layout.addWidget(physical_group)

        # Behavior
        behavior_group = QGroupBox("Behavior")
        behavior_layout = QFormLayout()

        self.diet_edit = QLineEdit()
        self.diet_edit.setPlaceholderText("What they eat")
        behavior_layout.addRow("Diet:", self.diet_edit)

        self.behavior_edit = QTextEdit()
        self.behavior_edit.setPlaceholderText("Behavioral patterns...")
        self.behavior_edit.setMaximumHeight(80)
        behavior_layout.addRow("Behavior:", self.behavior_edit)

        self.social_edit = QLineEdit()
        self.social_edit.setPlaceholderText("e.g., pack animal, solitary, herd")
        behavior_layout.addRow("Social Structure:", self.social_edit)

        self.intelligence_edit = QLineEdit()
        self.intelligence_edit.setPlaceholderText("e.g., low, moderate, high, sentient")
        behavior_layout.addRow("Intelligence Level:", self.intelligence_edit)

        self.reproduction_edit = QTextEdit()
        self.reproduction_edit.setPlaceholderText("Reproductive information...")
        self.reproduction_edit.setMaximumHeight(60)
        behavior_layout.addRow("Reproduction:", self.reproduction_edit)

        behavior_group.setLayout(behavior_layout)
        scroll_layout.addWidget(behavior_group)

        # Abilities & Threat
        abilities_group = QGroupBox("Abilities & Threat Level")
        abilities_layout = QFormLayout()

        self.abilities_edit = QTextEdit()
        self.abilities_edit.setPlaceholderText("Special abilities: flight, camouflage, venom, etc. (one per line)")
        self.abilities_edit.setMaximumHeight(80)
        abilities_layout.addRow("Special Abilities:", self.abilities_edit)

        self.magical_edit = QTextEdit()
        self.magical_edit.setPlaceholderText("Magical properties (for fantasy settings)...")
        self.magical_edit.setMaximumHeight(60)
        abilities_layout.addRow("Magical Properties:", self.magical_edit)

        # Danger level slider
        danger_label = QLabel("Danger Level (0=Harmless, 100=Extremely Dangerous):")
        danger_label.setStyleSheet("font-weight: 600; margin-top: 8px;")
        abilities_layout.addRow(danger_label)

        danger_slider_layout = QHBoxLayout()
        self.danger_slider = QSlider(Qt.Orientation.Horizontal)
        self.danger_slider.setRange(0, 100)
        self.danger_slider.setValue(0)
        self.danger_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.danger_slider.setTickInterval(10)
        danger_slider_layout.addWidget(self.danger_slider)

        self.danger_label = QLabel("0")
        self.danger_label.setMinimumWidth(30)
        self.danger_slider.valueChanged.connect(lambda v: self.danger_label.setText(str(v)))
        danger_slider_layout.addWidget(self.danger_label)

        abilities_layout.addRow("", danger_slider_layout)

        self.domestication_edit = QLineEdit()
        self.domestication_edit.setPlaceholderText("e.g., wild, domesticated, semi-domesticated")
        abilities_layout.addRow("Domestication Status:", self.domestication_edit)

        abilities_group.setLayout(abilities_layout)
        scroll_layout.addWidget(abilities_group)

        # Economic/Cultural Value
        value_group = QGroupBox("Value & Significance")
        value_layout = QFormLayout()

        self.economic_edit = QTextEdit()
        self.economic_edit.setPlaceholderText("Hunt value, trade goods, resources...")
        self.economic_edit.setMaximumHeight(60)
        value_layout.addRow("Economic Value:", self.economic_edit)

        self.cultural_edit = QTextEdit()
        self.cultural_edit.setPlaceholderText("Religious, symbolic, or cultural meaning...")
        self.cultural_edit.setMaximumHeight(80)
        value_layout.addRow("Cultural Significance:", self.cultural_edit)

        self.story_edit = QTextEdit()
        self.story_edit.setPlaceholderText("Why this matters to the story...")
        self.story_edit.setMaximumHeight(80)
        value_layout.addRow("Story Relevance:", self.story_edit)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Additional notes...")
        self.notes_edit.setMaximumHeight(80)
        value_layout.addRow("Notes:", self.notes_edit)

        value_group.setLayout(value_layout)
        scroll_layout.addWidget(value_group)

        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def _load_fauna(self):
        """Load fauna data into form."""
        self.name_edit.setText(self.fauna.name)

        type_index = list(FaunaType).index(self.fauna.fauna_type)
        self.type_combo.setCurrentIndex(type_index)

        self.scientific_name_edit.setText(self.fauna.scientific_name or "")

        if self.fauna.common_names:
            self.common_names_edit.setPlainText("\n".join(self.fauna.common_names))

        self.description_edit.setPlainText(self.fauna.description)

        # Check planet checkboxes
        for planet_name in self.fauna.native_planets:
            if planet_name in self.planet_checkboxes:
                self.planet_checkboxes[planet_name].setChecked(True)

        self.preferred_climate_edit.setText(self.fauna.preferred_climate)
        self.habitat_edit.setText(self.fauna.habitat)
        self.territory_edit.setText(self.fauna.territory_size)

        self.size_edit.setText(self.fauna.size)
        self.weight_edit.setText(self.fauna.weight)
        self.lifespan_edit.setText(self.fauna.lifespan)
        self.appearance_edit.setPlainText(self.fauna.appearance)

        self.diet_edit.setText(self.fauna.diet)
        self.behavior_edit.setPlainText(self.fauna.behavior)
        self.social_edit.setText(self.fauna.social_structure)
        self.intelligence_edit.setText(self.fauna.intelligence_level)
        self.reproduction_edit.setPlainText(self.fauna.reproduction)

        if self.fauna.special_abilities:
            self.abilities_edit.setPlainText("\n".join(self.fauna.special_abilities))

        self.magical_edit.setPlainText(self.fauna.magical_properties)
        self.danger_slider.setValue(self.fauna.danger_level)
        self.domestication_edit.setText(self.fauna.domestication_status)

        self.economic_edit.setPlainText(self.fauna.economic_value)
        self.cultural_edit.setPlainText(self.fauna.cultural_significance)
        self.story_edit.setPlainText(self.fauna.story_relevance)
        self.notes_edit.setPlainText(self.fauna.notes)

    def _save(self):
        """Save fauna data."""
        name = self.name_edit.text().strip()
        if not name:
            return

        if not self.fauna.id:
            import uuid
            self.fauna.id = str(uuid.uuid4())

        self.fauna.name = name

        type_list = list(FaunaType)
        self.fauna.fauna_type = type_list[self.type_combo.currentIndex()]

        self.fauna.scientific_name = self.scientific_name_edit.text().strip() or None

        common_names_text = self.common_names_edit.toPlainText().strip()
        self.fauna.common_names = [n.strip() for n in common_names_text.split("\n") if n.strip()]

        self.fauna.description = self.description_edit.toPlainText().strip()

        # Get selected planets from checkboxes
        self.fauna.native_planets = [
            planet_name for planet_name, checkbox in self.planet_checkboxes.items()
            if checkbox.isChecked()
        ]

        self.fauna.preferred_climate = self.preferred_climate_edit.text().strip()
        self.fauna.habitat = self.habitat_edit.text().strip()
        self.fauna.territory_size = self.territory_edit.text().strip()

        self.fauna.size = self.size_edit.text().strip()
        self.fauna.weight = self.weight_edit.text().strip()
        self.fauna.lifespan = self.lifespan_edit.text().strip()
        self.fauna.appearance = self.appearance_edit.toPlainText().strip()

        self.fauna.diet = self.diet_edit.text().strip()
        self.fauna.behavior = self.behavior_edit.toPlainText().strip()
        self.fauna.social_structure = self.social_edit.text().strip()
        self.fauna.intelligence_level = self.intelligence_edit.text().strip()
        self.fauna.reproduction = self.reproduction_edit.toPlainText().strip()

        abilities_text = self.abilities_edit.toPlainText().strip()
        self.fauna.special_abilities = [a.strip() for a in abilities_text.split("\n") if a.strip()]

        self.fauna.magical_properties = self.magical_edit.toPlainText().strip()
        self.fauna.danger_level = self.danger_slider.value()
        self.fauna.domestication_status = self.domestication_edit.text().strip()

        self.fauna.economic_value = self.economic_edit.toPlainText().strip()
        self.fauna.cultural_significance = self.cultural_edit.toPlainText().strip()
        self.fauna.story_relevance = self.story_edit.toPlainText().strip()
        self.fauna.notes = self.notes_edit.toPlainText().strip()

        self.accept()

    def get_fauna(self) -> Fauna:
        """Get the edited fauna."""
        return self.fauna


class FaunaBuilderWidget(QWidget):
    """Widget for managing fauna species."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize fauna builder."""
        super().__init__()
        self.fauna_list: List[Fauna] = []
        self.available_planets: List[str] = []
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(16, 12, 16, 8)

        header = QLabel("🦁 Fauna")
        header.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header_layout.addWidget(header)

        subtitle = QLabel("Manage animal species and creatures")
        subtitle.setStyleSheet("font-size: 12px; color: #6b7280;")
        header_layout.addWidget(subtitle)

        layout.addWidget(header_widget)

        # Toolbar
        toolbar = QHBoxLayout()

        add_btn = QPushButton("➕ Add Fauna")
        add_btn.clicked.connect(self._add_fauna)
        toolbar.addWidget(add_btn)

        self.edit_btn = QPushButton("✏️ Edit")
        self.edit_btn.clicked.connect(self._edit_fauna)
        self.edit_btn.setEnabled(False)
        toolbar.addWidget(self.edit_btn)

        self.remove_btn = QPushButton("🗑️ Remove")
        self.remove_btn.clicked.connect(self._remove_fauna)
        self.remove_btn.setEnabled(False)
        toolbar.addWidget(self.remove_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Fauna list
        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self._edit_fauna)
        layout.addWidget(self.list_widget)

    def _add_fauna(self):
        """Add new fauna."""
        editor = FaunaEditor(all_fauna=self.fauna_list, available_planets=self.available_planets, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            fauna = editor.get_fauna()
            self.fauna_list.append(fauna)
            self._update_list()
            self.content_changed.emit()

    def _edit_fauna(self):
        """Edit selected fauna."""
        items = self.list_widget.selectedItems()
        if not items:
            return

        fauna_id = items[0].data(Qt.ItemDataRole.UserRole)
        fauna = next((f for f in self.fauna_list if f.id == fauna_id), None)
        if not fauna:
            return

        editor = FaunaEditor(fauna=fauna, all_fauna=self.fauna_list, available_planets=self.available_planets, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_list()
            self.content_changed.emit()

    def _remove_fauna(self):
        """Remove selected fauna."""
        items = self.list_widget.selectedItems()
        if not items:
            return

        fauna_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.fauna_list = [f for f in self.fauna_list if f.id != fauna_id]
        self._update_list()
        self.content_changed.emit()

    def _update_list(self):
        """Update fauna list display."""
        self.list_widget.clear()

        for fauna in self.fauna_list:
            # Create display text with type and key features
            features = []
            if fauna.danger_level > 70:
                features.append("⚠️")
            elif fauna.danger_level < 20:
                features.append("🕊️")

            if fauna.domestication_status and "domesticated" in fauna.domestication_status.lower():
                features.append("🏠")

            if fauna.magical_properties:
                features.append("✨")

            features_text = " ".join(features)
            type_display = fauna.fauna_type.value.replace("_", " ").title()

            # Show planet associations
            planets_text = ""
            if fauna.native_planets:
                planets_text = f" • {', '.join(fauna.native_planets)}"

            item_text = f"{fauna.name} ({type_display})"
            if features_text:
                item_text += f" {features_text}"
            if planets_text:
                item_text += planets_text

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, fauna.id)
            self.list_widget.addItem(item)

    def _on_selection_changed(self):
        """Handle selection change."""
        has_selection = bool(self.list_widget.selectedItems())
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def set_available_planets(self, planets: List[str]):
        """Set available planets for fauna association.

        Args:
            planets: List of planet names
        """
        self.available_planets = planets
        # Clean up references to deleted planets
        valid_planets = set(planets)
        for fauna in self.fauna_list:
            fauna.native_planets = [p for p in fauna.native_planets if p in valid_planets]
        self._update_list()

    def load_fauna(self, fauna_list: List[Fauna]):
        """Load fauna list."""
        self.fauna_list = fauna_list
        self._update_list()

    def get_fauna(self) -> List[Fauna]:
        """Get fauna list."""
        return self.fauna_list
