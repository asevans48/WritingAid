"""Place and landmark builder widget."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QDialog, QDialogButtonBox, QLabel, QLineEdit,
    QTextEdit, QComboBox, QSpinBox, QFormLayout, QGroupBox, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal
from typing import List, Optional
import uuid

from src.models.worldbuilding_objects import Place, PlaceType, Faction
from src.ui.worldbuilding.filter_sort_widget import FilterSortWidget


class PlaceEditor(QDialog):
    """Dialog for editing a place or landmark."""

    def __init__(self, place: Optional[Place] = None, available_factions: List[Faction] = None,
                 available_planets: List[str] = None, parent=None):
        """Initialize place editor."""
        super().__init__(parent)
        self.place = place or Place(
            id="",
            name="",
            place_type=PlaceType.CITY,
            description=""
        )
        self.available_factions = available_factions or []
        self.available_planets = available_planets or []
        self._init_ui()
        if place:
            self._load_place()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Place/Landmark Editor")
        self.resize(750, 600)

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
        self.name_edit.setPlaceholderText("Place name")
        basic_layout.addRow("Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value.replace("_", " ").title() for t in PlaceType])
        basic_layout.addRow("Type:", self.type_combo)

        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)

        # Description
        desc_group = QGroupBox("Description")
        desc_layout = QVBoxLayout()

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Describe this place...")
        self.description_edit.setMaximumHeight(100)
        desc_layout.addWidget(self.description_edit)

        desc_group.setLayout(desc_layout)
        scroll_layout.addWidget(desc_group)

        # Location
        location_group = QGroupBox("Location")
        location_layout = QFormLayout()

        self.planet_combo = QComboBox()
        self.planet_combo.setEditable(True)
        self.planet_combo.addItem("")
        for planet in self.available_planets:
            self.planet_combo.addItem(planet)
        location_layout.addRow("Planet:", self.planet_combo)

        self.continent_edit = QLineEdit()
        location_layout.addRow("Continent/Region:", self.continent_edit)

        self.coordinates_edit = QLineEdit()
        self.coordinates_edit.setPlaceholderText("e.g., 40.7128° N, 74.0060° W")
        location_layout.addRow("Coordinates:", self.coordinates_edit)

        location_group.setLayout(location_layout)
        scroll_layout.addWidget(location_group)

        # Faction Control
        control_group = QGroupBox("Faction Control")
        control_layout = QVBoxLayout()

        faction_form = QFormLayout()

        self.controlling_faction_combo = QComboBox()
        self.controlling_faction_combo.addItem("-- None --", "")
        for faction in self.available_factions:
            self.controlling_faction_combo.addItem(faction.name, faction.id)
        faction_form.addRow("Controlling Faction:", self.controlling_faction_combo)

        control_layout.addLayout(faction_form)
        control_group.setLayout(control_layout)
        scroll_layout.addWidget(control_group)

        # Key Features
        features_group = QGroupBox("Key Features & Resources")
        features_layout = QFormLayout()

        self.size_edit = QLineEdit()
        self.size_edit.setPlaceholderText("e.g., 'small village', '50 sq km'")
        features_layout.addRow("Size:", self.size_edit)

        self.population_spin = QSpinBox()
        self.population_spin.setMaximum(999999999)
        features_layout.addRow("Population:", self.population_spin)

        features_group.setLayout(features_layout)
        scroll_layout.addWidget(features_group)

        # Strategic Value
        value_group = QGroupBox("Strategic & Economic Value")
        value_layout = QFormLayout()

        self.strategic_spin = QSpinBox()
        self.strategic_spin.setRange(0, 100)
        self.strategic_spin.setValue(50)
        value_layout.addRow("Strategic Value (0-100):", self.strategic_spin)

        self.economic_spin = QSpinBox()
        self.economic_spin.setRange(0, 100)
        self.economic_spin.setValue(50)
        value_layout.addRow("Economic Value (0-100):", self.economic_spin)

        value_group.setLayout(value_layout)
        scroll_layout.addWidget(value_group)

        # Cultural Significance
        cultural_group = QGroupBox("Cultural Significance")
        cultural_layout = QVBoxLayout()

        self.cultural_edit = QTextEdit()
        self.cultural_edit.setPlaceholderText("Religious, historical, or cultural importance...")
        self.cultural_edit.setMaximumHeight(80)
        cultural_layout.addWidget(self.cultural_edit)

        cultural_group.setLayout(cultural_layout)
        scroll_layout.addWidget(cultural_group)

        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def _load_place(self):
        """Load place data into form."""
        self.name_edit.setText(self.place.name)

        type_index = list(PlaceType).index(self.place.place_type)
        self.type_combo.setCurrentIndex(type_index)

        self.description_edit.setPlainText(self.place.description)

        if self.place.planet:
            index = self.planet_combo.findText(self.place.planet)
            if index >= 0:
                self.planet_combo.setCurrentIndex(index)
            else:
                self.planet_combo.setEditText(self.place.planet)

        self.continent_edit.setText(self.place.continent or "")
        self.coordinates_edit.setText(self.place.coordinates or "")

        # Controlling faction
        if self.place.controlling_faction:
            for i in range(self.controlling_faction_combo.count()):
                if self.controlling_faction_combo.itemData(i) == self.place.controlling_faction:
                    self.controlling_faction_combo.setCurrentIndex(i)
                    break

        self.size_edit.setText(self.place.size or "")
        if self.place.population:
            self.population_spin.setValue(self.place.population)

        self.strategic_spin.setValue(self.place.strategic_value)
        self.economic_spin.setValue(self.place.economic_value)
        self.cultural_edit.setPlainText(self.place.cultural_significance)

    def _save(self):
        """Save place data."""
        name = self.name_edit.text().strip()
        if not name:
            return

        if not self.place.id:
            self.place.id = str(uuid.uuid4())

        self.place.name = name

        type_list = list(PlaceType)
        self.place.place_type = type_list[self.type_combo.currentIndex()]

        self.place.description = self.description_edit.toPlainText().strip()

        self.place.planet = self.planet_combo.currentText().strip() or None
        self.place.continent = self.continent_edit.text().strip() or None
        self.place.coordinates = self.coordinates_edit.text().strip() or None

        self.place.controlling_faction = self.controlling_faction_combo.currentData() or None

        self.place.size = self.size_edit.text().strip() or None
        pop = self.population_spin.value()
        self.place.population = pop if pop > 0 else None

        self.place.strategic_value = self.strategic_spin.value()
        self.place.economic_value = self.economic_spin.value()
        self.place.cultural_significance = self.cultural_edit.toPlainText().strip()

        self.accept()

    def get_place(self) -> Place:
        """Get the edited place."""
        return self.place


class PlaceBuilderWidget(QWidget):
    """Widget for managing places and landmarks."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize place builder."""
        super().__init__()
        self.places_list: List[Place] = []
        self.available_factions: List[Faction] = []
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

        header = QLabel("🗺️ Places & Landmarks")
        header.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header_layout.addWidget(header)

        subtitle = QLabel("Manage cities, landmarks, and points of interest")
        subtitle.setStyleSheet("font-size: 12px; color: #6b7280;")
        header_layout.addWidget(subtitle)

        layout.addWidget(header_widget)

        # Filter/Sort controls
        self.filter_sort = FilterSortWidget(
            sort_options=["Name", "Type", "Planet"],
            filter_placeholder="Search places..."
        )
        self.filter_sort.set_filter_options(["All"] + [t.value.replace("_", " ").title() for t in PlaceType])
        self.filter_sort.filter_changed.connect(self._update_list)
        layout.addWidget(self.filter_sort)

        # Toolbar
        toolbar = QHBoxLayout()

        add_btn = QPushButton("➕ Add Place")
        add_btn.clicked.connect(self._add_place)
        toolbar.addWidget(add_btn)

        self.edit_btn = QPushButton("✏️ Edit")
        self.edit_btn.clicked.connect(self._edit_place)
        self.edit_btn.setEnabled(False)
        toolbar.addWidget(self.edit_btn)

        self.remove_btn = QPushButton("🗑️ Remove")
        self.remove_btn.clicked.connect(self._remove_place)
        self.remove_btn.setEnabled(False)
        toolbar.addWidget(self.remove_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Place list
        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self._edit_place)
        layout.addWidget(self.list_widget)

    def _update_list(self):
        """Update place list display."""
        self.list_widget.clear()

        # Filter and sort functions
        def get_searchable_text(place):
            faction_name = ""
            if place.controlling_faction:
                faction = next((f for f in self.available_factions if f.id == place.controlling_faction), None)
                if faction:
                    faction_name = faction.name
            return f"{place.name} {place.place_type.value} {place.planet or ''} {faction_name} {place.description or ''}"

        def get_sort_value(place, key):
            if key == "Name":
                return place.name.lower()
            elif key == "Type":
                return place.place_type.value
            elif key == "Planet":
                return (place.planet or "").lower()
            return place.name.lower()

        def get_type(place):
            return place.place_type.value.replace("_", " ").title()

        filtered_places = self.filter_sort.filter_and_sort(
            self.places_list, get_searchable_text, get_sort_value, get_type
        )

        for place in filtered_places:
            type_display = place.place_type.value.replace("_", " ").title()

            # Get controlling faction name if available
            faction_text = ""
            if place.controlling_faction:
                faction = next((f for f in self.available_factions if f.id == place.controlling_faction), None)
                if faction:
                    faction_text = f" • {faction.name}"

            item_text = f"{place.name} ({type_display}){faction_text}"

            # Add truncated description if available
            if place.description:
                desc = place.description[:50] + "..." if len(place.description) > 50 else place.description
                item_text += f" - {desc}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, place.id)
            self.list_widget.addItem(item)

    def _on_selection_changed(self):
        """Handle selection change."""
        has_selection = bool(self.list_widget.selectedItems())
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def _add_place(self):
        """Add new place."""
        editor = PlaceEditor(available_factions=self.available_factions,
                            available_planets=self.available_planets, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            place = editor.get_place()
            self.places_list.append(place)
            self._update_list()
            self.content_changed.emit()

    def _edit_place(self):
        """Edit selected place."""
        items = self.list_widget.selectedItems()
        if not items:
            return

        place_id = items[0].data(Qt.ItemDataRole.UserRole)
        place = next((p for p in self.places_list if p.id == place_id), None)
        if not place:
            return

        editor = PlaceEditor(place=place, available_factions=self.available_factions,
                            available_planets=self.available_planets, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_list()
            self.content_changed.emit()

    def _remove_place(self):
        """Remove selected place."""
        items = self.list_widget.selectedItems()
        if not items:
            return

        current_row = self.list_widget.row(items[0])
        place_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.places_list = [p for p in self.places_list if p.id != place_id]
        self._update_list()

        # Select next available place if any exist
        if self.list_widget.count() > 0:
            next_row = min(current_row, self.list_widget.count() - 1)
            self.list_widget.setCurrentRow(next_row)

        self.content_changed.emit()

    def set_available_factions(self, factions: List[Faction]):
        """Set available factions for place association."""
        self.available_factions = factions
        self._update_list()

    def set_available_planets(self, planets: List[str]):
        """Set available planets for place association."""
        self.available_planets = planets

    def load_places(self, places_list: List[Place]):
        """Load places list."""
        self.places_list = places_list
        self._update_list()

    def get_places(self) -> List[Place]:
        """Get places list."""
        return self.places_list
