"""Star system builder widget for managing star systems and their planets."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QDialog, QDialogButtonBox, QLabel, QLineEdit,
    QTextEdit, QComboBox, QFormLayout, QGroupBox, QScrollArea, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from typing import List, Optional

from src.models.worldbuilding_objects import StarSystem, Star, Planet


class StarSystemEditor(QDialog):
    """Dialog for editing star system details."""

    def __init__(self, star_system: Optional[StarSystem] = None,
                 available_stars: List[Star] = None,
                 available_planets: List[Planet] = None,
                 parent=None):
        """Initialize star system editor."""
        super().__init__(parent)
        self.star_system = star_system or StarSystem(
            id="",
            name="",
            system_type="single"
        )
        self.available_stars = available_stars or []
        self.available_planets = available_planets or []
        self._init_ui()
        if star_system:
            self._load_system()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Star System Editor")
        self.setMinimumSize(800, 700)

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
        self.name_edit.setPlaceholderText("System name (e.g., Solar System, Alpha Centauri)")
        basic_layout.addRow("Name:*", self.name_edit)

        self.system_type_combo = QComboBox()
        self.system_type_combo.addItems(["Single", "Binary", "Trinary", "Multiple"])
        basic_layout.addRow("System Type:", self.system_type_combo)

        self.galaxy_edit = QLineEdit()
        self.galaxy_edit.setPlaceholderText("e.g., Milky Way, Andromeda, or custom galaxy name")
        basic_layout.addRow("Galaxy:", self.galaxy_edit)

        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)

        # Location
        location_group = QGroupBox("Location")
        location_layout = QFormLayout()

        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("e.g., Orion Arm, Galactic Core")
        location_layout.addRow("Location in Galaxy:", self.location_edit)

        self.distance_edit = QLineEdit()
        self.distance_edit.setPlaceholderText("e.g., 4.37 light years")
        location_layout.addRow("Distance from Earth:", self.distance_edit)

        location_group.setLayout(location_layout)
        scroll_layout.addWidget(location_group)

        # Stars
        stars_group = QGroupBox("Stars in System")
        stars_layout = QVBoxLayout()

        stars_help = QLabel("Select the stars that make up this system. For binary/trinary systems, select multiple stars.")
        stars_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        stars_help.setWordWrap(True)
        stars_layout.addWidget(stars_help)

        # Primary star selection
        primary_layout = QHBoxLayout()
        primary_layout.addWidget(QLabel("Primary Star:"))
        self.primary_star_combo = QComboBox()
        self.primary_star_combo.addItem("(None)", None)
        for star in self.available_stars:
            self.primary_star_combo.addItem(star.name, star.id)
        primary_layout.addWidget(self.primary_star_combo)
        primary_layout.addStretch()
        stars_layout.addLayout(primary_layout)

        # Companion stars (for binary/multiple systems)
        companion_label = QLabel("Companion Stars:")
        stars_layout.addWidget(companion_label)

        self.companion_stars_list = QListWidget()
        self.companion_stars_list.setMaximumHeight(120)
        self.companion_stars_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for star in self.available_stars:
            item = QListWidgetItem(star.name)
            item.setData(Qt.ItemDataRole.UserRole, star.id)
            self.companion_stars_list.addItem(item)
        stars_layout.addWidget(self.companion_stars_list)

        stars_group.setLayout(stars_layout)
        scroll_layout.addWidget(stars_group)

        # Habitable Zone
        habitable_group = QGroupBox("Habitable Zone")
        habitable_layout = QFormLayout()

        self.habitable_inner_edit = QLineEdit()
        self.habitable_inner_edit.setPlaceholderText("e.g., 0.95 AU")
        habitable_layout.addRow("Inner Boundary:", self.habitable_inner_edit)

        self.habitable_outer_edit = QLineEdit()
        self.habitable_outer_edit.setPlaceholderText("e.g., 1.37 AU")
        habitable_layout.addRow("Outer Boundary:", self.habitable_outer_edit)

        habitable_help = QLabel("AU = Astronomical Unit (Earth's distance from Sun)")
        habitable_help.setStyleSheet("color: #6b7280; font-size: 10px;")
        habitable_layout.addRow(habitable_help)

        habitable_group.setLayout(habitable_layout)
        scroll_layout.addWidget(habitable_group)

        # Planets
        planets_group = QGroupBox("Planets in System")
        planets_layout = QVBoxLayout()

        planets_help = QLabel("Planets that orbit in this system. Add planets here - they will be organized under this system.")
        planets_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        planets_help.setWordWrap(True)
        planets_layout.addWidget(planets_help)

        # Planet list with add/remove buttons
        planet_list_layout = QHBoxLayout()

        self.planets_list = QListWidget()
        self.planets_list.setMaximumHeight(150)
        for planet in self.available_planets:
            item = QListWidgetItem(planet.name)
            item.setData(Qt.ItemDataRole.UserRole, planet.id)
            self.planets_list.addItem(item)
        planet_list_layout.addWidget(self.planets_list)

        # Buttons for planet management
        planet_btn_layout = QVBoxLayout()
        add_planet_btn = QPushButton("➕ Add")
        add_planet_btn.setToolTip("Add existing planet to this system")
        add_planet_btn.clicked.connect(self._add_planet_to_system)
        planet_btn_layout.addWidget(add_planet_btn)

        remove_planet_btn = QPushButton("➖ Remove")
        remove_planet_btn.setToolTip("Remove planet from this system")
        remove_planet_btn.clicked.connect(self._remove_planet_from_system)
        planet_btn_layout.addWidget(remove_planet_btn)

        planet_btn_layout.addStretch()
        planet_list_layout.addLayout(planet_btn_layout)

        planets_layout.addLayout(planet_list_layout)

        planets_group.setLayout(planets_layout)
        scroll_layout.addWidget(planets_group)

        # Description
        desc_group = QGroupBox("Description")
        desc_layout = QVBoxLayout()

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Describe this star system...")
        self.description_edit.setMaximumHeight(100)
        desc_layout.addWidget(self.description_edit)

        desc_group.setLayout(desc_layout)
        scroll_layout.addWidget(desc_group)

        # Notes
        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout()

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Additional notes...")
        self.notes_edit.setMaximumHeight(80)
        notes_layout.addWidget(self.notes_edit)

        notes_group.setLayout(notes_layout)
        scroll_layout.addWidget(notes_group)

        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def _load_system(self):
        """Load star system data into form."""
        self.name_edit.setText(self.star_system.name)

        # System type
        type_index = ["single", "binary", "trinary", "multiple"].index(
            self.star_system.system_type.lower()
        ) if self.star_system.system_type.lower() in ["single", "binary", "trinary", "multiple"] else 0
        self.system_type_combo.setCurrentIndex(type_index)

        self.galaxy_edit.setText(self.star_system.galaxy or "")
        self.location_edit.setText(self.star_system.location or "")
        self.distance_edit.setText(self.star_system.distance_from_earth or "")

        # Primary star
        if self.star_system.primary_star:
            for i in range(self.primary_star_combo.count()):
                if self.primary_star_combo.itemData(i) == self.star_system.primary_star:
                    self.primary_star_combo.setCurrentIndex(i)
                    break

        # Companion stars
        for i in range(self.companion_stars_list.count()):
            item = self.companion_stars_list.item(i)
            star_id = item.data(Qt.ItemDataRole.UserRole)
            if star_id in self.star_system.companion_stars:
                item.setSelected(True)

        # Planets - populate list with planets in this system
        self._refresh_planet_list()
        for planet_id in self.star_system.planet_ids:
            # Find planet in available planets
            planet = next((p for p in self.available_planets if p.id == planet_id), None)
            if planet:
                item = QListWidgetItem(planet.name)
                item.setData(Qt.ItemDataRole.UserRole, planet.id)
                self.planets_list.addItem(item)

        # Habitable zone
        self.habitable_inner_edit.setText(self.star_system.habitable_zone_inner or "")
        self.habitable_outer_edit.setText(self.star_system.habitable_zone_outer or "")

        # Description and notes
        self.description_edit.setPlainText(self.star_system.description)
        self.notes_edit.setPlainText(self.star_system.notes)

    def _refresh_planet_list(self):
        """Refresh the planet list display."""
        self.planets_list.clear()
        for planet_id in self.star_system.planet_ids:
            planet = next((p for p in self.available_planets if p.id == planet_id), None)
            if planet:
                item = QListWidgetItem(planet.name)
                item.setData(Qt.ItemDataRole.UserRole, planet.id)
                self.planets_list.addItem(item)

    def _add_planet_to_system(self):
        """Add a planet to this system."""
        from PyQt6.QtWidgets import QInputDialog

        # Get list of planets not yet in this system
        available = [p for p in self.available_planets if p.id not in self.star_system.planet_ids]
        if not available:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No Planets", "All available planets are already in this system.")
            return

        planet_names = [p.name for p in available]
        planet_name, ok = QInputDialog.getItem(
            self,
            "Add Planet",
            "Select a planet to add to this system:",
            planet_names,
            0,
            False
        )

        if ok and planet_name:
            planet = next(p for p in available if p.name == planet_name)
            self.star_system.planet_ids.append(planet.id)
            self._refresh_planet_list()

    def _remove_planet_from_system(self):
        """Remove selected planet from this system."""
        current_item = self.planets_list.currentItem()
        if not current_item:
            return

        planet_id = current_item.data(Qt.ItemDataRole.UserRole)
        if planet_id in self.star_system.planet_ids:
            self.star_system.planet_ids.remove(planet_id)
            self._refresh_planet_list()

    def _save(self):
        """Save star system data."""
        name = self.name_edit.text().strip()
        if not name:
            return

        if not self.star_system.id:
            import uuid
            self.star_system.id = str(uuid.uuid4())

        self.star_system.name = name

        # System type
        type_map = {0: "single", 1: "binary", 2: "trinary", 3: "multiple"}
        self.star_system.system_type = type_map[self.system_type_combo.currentIndex()]

        self.star_system.galaxy = self.galaxy_edit.text().strip() or None
        self.star_system.location = self.location_edit.text().strip() or None
        self.star_system.distance_from_earth = self.distance_edit.text().strip() or None

        # Primary star
        self.star_system.primary_star = self.primary_star_combo.currentData()

        # Companion stars
        self.star_system.companion_stars = []
        for i in range(self.companion_stars_list.count()):
            item = self.companion_stars_list.item(i)
            if item.isSelected():
                star_id = item.data(Qt.ItemDataRole.UserRole)
                self.star_system.companion_stars.append(star_id)

        # Planets are already managed via _add_planet_to_system/_remove_planet_from_system
        # No need to collect them here as they're updated in real-time

        # Habitable zone
        self.star_system.habitable_zone_inner = self.habitable_inner_edit.text().strip() or None
        self.star_system.habitable_zone_outer = self.habitable_outer_edit.text().strip() or None

        # Description and notes
        self.star_system.description = self.description_edit.toPlainText().strip()
        self.star_system.notes = self.notes_edit.toPlainText().strip()

        self.accept()

    def get_star_system(self) -> StarSystem:
        """Get the edited star system."""
        return self.star_system


class StarSystemBuilderWidget(QWidget):
    """Widget for managing star systems."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize star system builder."""
        super().__init__()
        self.star_systems: List[StarSystem] = []
        self.available_stars: List[Star] = []
        self.available_planets: List[Planet] = []
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(16, 12, 16, 8)

        header = QLabel("⭐ Star Systems")
        header.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header_layout.addWidget(header)

        subtitle = QLabel("Manage star systems containing stars and planets")
        subtitle.setStyleSheet("font-size: 12px; color: #6b7280;")
        header_layout.addWidget(subtitle)

        layout.addWidget(header_widget)

        # Toolbar
        toolbar = QHBoxLayout()

        add_btn = QPushButton("➕ Add System")
        add_btn.clicked.connect(self._add_system)
        toolbar.addWidget(add_btn)

        self.edit_btn = QPushButton("✏️ Edit")
        self.edit_btn.clicked.connect(self._edit_system)
        self.edit_btn.setEnabled(False)
        toolbar.addWidget(self.edit_btn)

        self.remove_btn = QPushButton("🗑️ Remove")
        self.remove_btn.clicked.connect(self._remove_system)
        self.remove_btn.setEnabled(False)
        toolbar.addWidget(self.remove_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # System list
        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self._edit_system)
        layout.addWidget(self.list_widget)

    def _add_system(self):
        """Add new star system."""
        editor = StarSystemEditor(
            available_stars=self.available_stars,
            available_planets=self.available_planets,
            parent=self
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            system = editor.get_star_system()
            self.star_systems.append(system)
            self._update_list()
            self.content_changed.emit()

    def _edit_system(self):
        """Edit selected star system."""
        items = self.list_widget.selectedItems()
        if not items:
            return

        system_id = items[0].data(Qt.ItemDataRole.UserRole)
        system = next((s for s in self.star_systems if s.id == system_id), None)
        if not system:
            return

        editor = StarSystemEditor(
            star_system=system,
            available_stars=self.available_stars,
            available_planets=self.available_planets,
            parent=self
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_list()
            self.content_changed.emit()

    def _remove_system(self):
        """Remove selected star system."""
        items = self.list_widget.selectedItems()
        if not items:
            return

        system_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.star_systems = [s for s in self.star_systems if s.id != system_id]
        self._update_list()
        self.content_changed.emit()

    def _update_list(self):
        """Update star system list display."""
        self.list_widget.clear()

        for system in self.star_systems:
            # Create display text with key info
            planet_count = len(system.planet_ids)
            star_count = 1 if system.primary_star else 0
            star_count += len(system.companion_stars)

            galaxy_text = f" in {system.galaxy}" if system.galaxy else ""
            item_text = f"{system.name} ({system.system_type}, {star_count} stars, {planet_count} planets{galaxy_text})"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, system.id)
            self.list_widget.addItem(item)

    def _on_selection_changed(self):
        """Handle selection change."""
        has_selection = bool(self.list_widget.selectedItems())
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def set_available_stars(self, stars: List[Star]):
        """Set available stars for selection."""
        self.available_stars = stars

    def set_available_planets(self, planets: List[Planet]):
        """Set available planets for selection."""
        self.available_planets = planets

    def load_star_systems(self, systems: List[StarSystem]):
        """Load star systems list."""
        self.star_systems = systems
        self._update_list()

    def get_star_systems(self) -> List[StarSystem]:
        """Get star systems list."""
        return self.star_systems
