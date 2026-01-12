"""Flora builder widget for managing plant species."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QDialog, QDialogButtonBox, QLabel, QLineEdit,
    QTextEdit, QComboBox, QCheckBox, QFormLayout, QGroupBox, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal
from typing import List, Optional

from src.models.worldbuilding_objects import Flora, FloraType, SpeciesInteraction


class FloraEditor(QDialog):
    """Dialog for editing flora species."""

    def __init__(self, flora: Optional[Flora] = None, all_flora: List[Flora] = None,
                 all_fauna: List = None, available_planets: List[str] = None, parent=None):
        """Initialize flora editor."""
        super().__init__(parent)
        self.flora = flora or Flora(
            id="",
            name="",
            flora_type=FloraType.TREE,
            description=""
        )
        self.all_flora = all_flora or []
        self.all_fauna = all_fauna or []
        self.available_planets = available_planets or []
        self._init_ui()
        if flora:
            self._load_flora()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Flora Species Editor")
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
        self.type_combo.addItems([t.value.replace("_", " ").title() for t in FloraType])
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
        self.description_edit.setPlaceholderText("Describe this plant species...")
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
        self.preferred_climate_edit.setPlaceholderText("e.g., tropical, temperate, arid")
        habitat_form.addRow("Preferred Climate:", self.preferred_climate_edit)

        self.habitat_edit = QLineEdit()
        self.habitat_edit.setPlaceholderText("e.g., forest floor, canopy, riverbanks")
        habitat_form.addRow("Habitat:", self.habitat_edit)

        habitat_layout.addLayout(habitat_form)

        habitat_group.setLayout(habitat_layout)
        scroll_layout.addWidget(habitat_group)

        # Physical Characteristics
        physical_group = QGroupBox("Physical Characteristics")
        physical_layout = QFormLayout()

        self.size_edit = QLineEdit()
        self.size_edit.setPlaceholderText("e.g., 10-15 meters tall, ground cover")
        physical_layout.addRow("Size:", self.size_edit)

        self.lifespan_edit = QLineEdit()
        self.lifespan_edit.setPlaceholderText("e.g., annual, perennial, 1000+ years")
        physical_layout.addRow("Lifespan:", self.lifespan_edit)

        self.growth_rate_edit = QLineEdit()
        self.growth_rate_edit.setPlaceholderText("e.g., fast, slow, seasonal")
        physical_layout.addRow("Growth Rate:", self.growth_rate_edit)

        self.appearance_edit = QTextEdit()
        self.appearance_edit.setPlaceholderText("Physical appearance details...")
        self.appearance_edit.setMaximumHeight(80)
        physical_layout.addRow("Appearance:", self.appearance_edit)

        physical_group.setLayout(physical_layout)
        scroll_layout.addWidget(physical_group)

        # Special Properties
        properties_group = QGroupBox("Special Properties")
        properties_layout = QFormLayout()

        self.edible_checkbox = QCheckBox("Edible")
        properties_layout.addRow("", self.edible_checkbox)

        self.medicinal_edit = QTextEdit()
        self.medicinal_edit.setPlaceholderText("Medicinal properties, if any...")
        self.medicinal_edit.setMaximumHeight(60)
        properties_layout.addRow("Medicinal Properties:", self.medicinal_edit)

        self.toxicity_edit = QTextEdit()
        self.toxicity_edit.setPlaceholderText("Toxic effects, if any...")
        self.toxicity_edit.setMaximumHeight(60)
        properties_layout.addRow("Toxicity:", self.toxicity_edit)

        self.magical_edit = QTextEdit()
        self.magical_edit.setPlaceholderText("Magical properties (for fantasy settings)...")
        self.magical_edit.setMaximumHeight(60)
        properties_layout.addRow("Magical Properties:", self.magical_edit)

        self.economic_edit = QTextEdit()
        self.economic_edit.setPlaceholderText("Trade value, resource importance...")
        self.economic_edit.setMaximumHeight(60)
        properties_layout.addRow("Economic Value:", self.economic_edit)

        properties_group.setLayout(properties_layout)
        scroll_layout.addWidget(properties_group)

        # Cultural/Story Significance
        significance_group = QGroupBox("Significance")
        significance_layout = QFormLayout()

        self.cultural_edit = QTextEdit()
        self.cultural_edit.setPlaceholderText("Religious, symbolic, or cultural meaning...")
        self.cultural_edit.setMaximumHeight(80)
        significance_layout.addRow("Cultural Significance:", self.cultural_edit)

        self.story_edit = QTextEdit()
        self.story_edit.setPlaceholderText("Why this matters to the story...")
        self.story_edit.setMaximumHeight(80)
        significance_layout.addRow("Story Relevance:", self.story_edit)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Additional notes...")
        self.notes_edit.setMaximumHeight(80)
        significance_layout.addRow("Notes:", self.notes_edit)

        significance_group.setLayout(significance_layout)
        scroll_layout.addWidget(significance_group)

        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def _load_flora(self):
        """Load flora data into form."""
        self.name_edit.setText(self.flora.name)

        type_index = list(FloraType).index(self.flora.flora_type)
        self.type_combo.setCurrentIndex(type_index)

        self.scientific_name_edit.setText(self.flora.scientific_name or "")

        if self.flora.common_names:
            self.common_names_edit.setPlainText("\n".join(self.flora.common_names))

        self.description_edit.setPlainText(self.flora.description)

        # Check planet checkboxes
        for planet_name in self.flora.native_planets:
            if planet_name in self.planet_checkboxes:
                self.planet_checkboxes[planet_name].setChecked(True)

        self.preferred_climate_edit.setText(self.flora.preferred_climate)
        self.habitat_edit.setText(self.flora.habitat)

        self.size_edit.setText(self.flora.size)
        self.lifespan_edit.setText(self.flora.lifespan)
        self.growth_rate_edit.setText(self.flora.growth_rate)
        self.appearance_edit.setPlainText(self.flora.appearance)

        self.edible_checkbox.setChecked(self.flora.edible)
        self.medicinal_edit.setPlainText(self.flora.medicinal_properties)
        self.toxicity_edit.setPlainText(self.flora.toxicity)
        self.magical_edit.setPlainText(self.flora.magical_properties)
        self.economic_edit.setPlainText(self.flora.economic_value)

        self.cultural_edit.setPlainText(self.flora.cultural_significance)
        self.story_edit.setPlainText(self.flora.story_relevance)
        self.notes_edit.setPlainText(self.flora.notes)

    def _save(self):
        """Save flora data."""
        name = self.name_edit.text().strip()
        if not name:
            return

        if not self.flora.id:
            import uuid
            self.flora.id = str(uuid.uuid4())

        self.flora.name = name

        type_list = list(FloraType)
        self.flora.flora_type = type_list[self.type_combo.currentIndex()]

        self.flora.scientific_name = self.scientific_name_edit.text().strip() or None

        common_names_text = self.common_names_edit.toPlainText().strip()
        self.flora.common_names = [n.strip() for n in common_names_text.split("\n") if n.strip()]

        self.flora.description = self.description_edit.toPlainText().strip()

        # Get selected planets from checkboxes
        self.flora.native_planets = [
            planet_name for planet_name, checkbox in self.planet_checkboxes.items()
            if checkbox.isChecked()
        ]

        self.flora.preferred_climate = self.preferred_climate_edit.text().strip()
        self.flora.habitat = self.habitat_edit.text().strip()

        self.flora.size = self.size_edit.text().strip()
        self.flora.lifespan = self.lifespan_edit.text().strip()
        self.flora.growth_rate = self.growth_rate_edit.text().strip()
        self.flora.appearance = self.appearance_edit.toPlainText().strip()

        self.flora.edible = self.edible_checkbox.isChecked()
        self.flora.medicinal_properties = self.medicinal_edit.toPlainText().strip()
        self.flora.toxicity = self.toxicity_edit.toPlainText().strip()
        self.flora.magical_properties = self.magical_edit.toPlainText().strip()
        self.flora.economic_value = self.economic_edit.toPlainText().strip()

        self.flora.cultural_significance = self.cultural_edit.toPlainText().strip()
        self.flora.story_relevance = self.story_edit.toPlainText().strip()
        self.flora.notes = self.notes_edit.toPlainText().strip()

        self.accept()

    def get_flora(self) -> Flora:
        """Get the edited flora."""
        return self.flora


class FloraBuilderWidget(QWidget):
    """Widget for managing flora species."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize flora builder."""
        super().__init__()
        self.flora_list: List[Flora] = []
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

        header = QLabel("🌿 Flora")
        header.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header_layout.addWidget(header)

        subtitle = QLabel("Manage plant species and vegetation")
        subtitle.setStyleSheet("font-size: 12px; color: #6b7280;")
        header_layout.addWidget(subtitle)

        layout.addWidget(header_widget)

        # Toolbar
        toolbar = QHBoxLayout()

        add_btn = QPushButton("➕ Add Flora")
        add_btn.clicked.connect(self._add_flora)
        toolbar.addWidget(add_btn)

        self.edit_btn = QPushButton("✏️ Edit")
        self.edit_btn.clicked.connect(self._edit_flora)
        self.edit_btn.setEnabled(False)
        toolbar.addWidget(self.edit_btn)

        self.remove_btn = QPushButton("🗑️ Remove")
        self.remove_btn.clicked.connect(self._remove_flora)
        self.remove_btn.setEnabled(False)
        toolbar.addWidget(self.remove_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Flora list
        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self._edit_flora)
        layout.addWidget(self.list_widget)

    def _add_flora(self):
        """Add new flora."""
        editor = FloraEditor(all_flora=self.flora_list, available_planets=self.available_planets, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            flora = editor.get_flora()
            self.flora_list.append(flora)
            self._update_list()
            self.content_changed.emit()

    def _edit_flora(self):
        """Edit selected flora."""
        items = self.list_widget.selectedItems()
        if not items:
            return

        flora_id = items[0].data(Qt.ItemDataRole.UserRole)
        flora = next((f for f in self.flora_list if f.id == flora_id), None)
        if not flora:
            return

        editor = FloraEditor(flora=flora, all_flora=self.flora_list, available_planets=self.available_planets, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_list()
            self.content_changed.emit()

    def _remove_flora(self):
        """Remove selected flora."""
        items = self.list_widget.selectedItems()
        if not items:
            return

        flora_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.flora_list = [f for f in self.flora_list if f.id != flora_id]
        self._update_list()
        self.content_changed.emit()

    def _update_list(self):
        """Update flora list display."""
        self.list_widget.clear()

        for flora in self.flora_list:
            # Create display text with type and key features
            features = []
            if flora.edible:
                features.append("🍽️")
            if flora.medicinal_properties:
                features.append("💊")
            if flora.toxicity:
                features.append("☠️")
            if flora.magical_properties:
                features.append("✨")

            features_text = " ".join(features)
            type_display = flora.flora_type.value.replace("_", " ").title()

            # Show planet associations
            planets_text = ""
            if flora.native_planets:
                planets_text = f" • {', '.join(flora.native_planets)}"

            item_text = f"{flora.name} ({type_display})"
            if features_text:
                item_text += f" {features_text}"
            if planets_text:
                item_text += planets_text

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, flora.id)
            self.list_widget.addItem(item)

    def _on_selection_changed(self):
        """Handle selection change."""
        has_selection = bool(self.list_widget.selectedItems())
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def set_available_planets(self, planets: List[str]):
        """Set available planets for flora association.

        Args:
            planets: List of planet names
        """
        self.available_planets = planets
        # Clean up references to deleted planets
        valid_planets = set(planets)
        for flora in self.flora_list:
            flora.native_planets = [p for p in flora.native_planets if p in valid_planets]
        self._update_list()

    def load_flora(self, flora_list: List[Flora]):
        """Load flora list."""
        self.flora_list = flora_list
        self._update_list()

    def get_flora(self) -> List[Flora]:
        """Get flora list."""
        return self.flora_list
