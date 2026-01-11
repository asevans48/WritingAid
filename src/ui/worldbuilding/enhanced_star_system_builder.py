"""Enhanced star system builder with integrated planet and star management."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QDialog, QDialogButtonBox, QLabel, QLineEdit,
    QTextEdit, QComboBox, QFormLayout, QGroupBox,
    QTabWidget, QInputDialog, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from typing import List, Optional
import uuid

from src.models.worldbuilding_objects import StarSystem, Star, Planet, PlanetType, ClimateZone


class PlanetEditorDialog(QDialog):
    """Comprehensive dialog for editing planet details."""

    def __init__(self, planet: Optional[Planet] = None,
                 available_flora: List = None,
                 available_fauna: List = None,
                 available_climate_presets: List = None,
                 parent=None):
        """Initialize planet editor."""
        super().__init__(parent)
        self.planet = planet or Planet(
            id="",
            name="",
            planet_type=PlanetType.TERRESTRIAL
        )
        self.available_flora = available_flora or []
        self.available_fauna = available_fauna or []
        self.available_climate_presets = available_climate_presets or []
        self._init_ui()
        if planet:
            self._load_planet()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Planet Editor")
        self.setMinimumSize(800, 700)

        main_layout = QVBoxLayout(self)

        # Tabs for different sections
        tabs = QTabWidget()

        # Basic Info Tab
        basic_tab = self._create_basic_tab()
        tabs.addTab(basic_tab, "Basic Info")

        # Climate Tab
        climate_tab = self._create_climate_tab()
        tabs.addTab(climate_tab, "🌤️ Climate")

        # Biology Tab
        biology_tab = self._create_biology_tab()
        tabs.addTab(biology_tab, "🌿 Biology")

        main_layout.addWidget(tabs)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def _create_basic_tab(self):
        """Create basic info tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Planet name (e.g., Earth, Mars, Kepler-442b)")
        layout.addRow("Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "Terrestrial",
            "Gas Giant",
            "Ice Giant",
            "Desert",
            "Ocean",
            "Jungle",
            "Arctic",
            "Volcanic",
            "Artificial"
        ])
        layout.addRow("Planet Type:", self.type_combo)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Describe this planet...")
        self.description_edit.setMaximumHeight(200)
        layout.addRow("Description:", self.description_edit)

        return widget

    def _create_climate_tab(self):
        """Create climate management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        help_label = QLabel("Define climate zones for this planet (e.g., Tropical, Temperate, Arctic)")
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #6b7280; font-size: 11px; margin-bottom: 8px;")
        layout.addWidget(help_label)

        # Climate zones list with buttons
        list_layout = QHBoxLayout()

        self.climate_list = QListWidget()
        list_layout.addWidget(self.climate_list)

        btn_layout = QVBoxLayout()
        add_climate_btn = QPushButton("➕ Add Zone")
        add_climate_btn.clicked.connect(self._add_climate_zone)
        btn_layout.addWidget(add_climate_btn)

        edit_climate_btn = QPushButton("✏️ Edit Zone")
        edit_climate_btn.clicked.connect(self._edit_climate_zone)
        btn_layout.addWidget(edit_climate_btn)

        remove_climate_btn = QPushButton("🗑️ Remove Zone")
        remove_climate_btn.clicked.connect(self._remove_climate_zone)
        btn_layout.addWidget(remove_climate_btn)

        btn_layout.addStretch()
        list_layout.addLayout(btn_layout)

        layout.addLayout(list_layout)

        return widget

    def _create_biology_tab(self):
        """Create biology tab for flora and fauna."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Flora section
        flora_group = QGroupBox("🌿 Flora Species")
        flora_layout = QVBoxLayout(flora_group)

        flora_help = QLabel("Select flora species native to this planet")
        flora_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        flora_layout.addWidget(flora_help)

        self.flora_list = QListWidget()
        self.flora_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        flora_layout.addWidget(self.flora_list)

        # Populate flora list
        for flora in self.available_flora:
            item = QListWidgetItem(flora.name)
            item.setData(Qt.ItemDataRole.UserRole, flora.id)
            self.flora_list.addItem(item)

        layout.addWidget(flora_group)

        # Fauna section
        fauna_group = QGroupBox("🦁 Fauna Species")
        fauna_layout = QVBoxLayout(fauna_group)

        fauna_help = QLabel("Select fauna species native to this planet")
        fauna_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        fauna_layout.addWidget(fauna_help)

        self.fauna_list = QListWidget()
        self.fauna_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        fauna_layout.addWidget(self.fauna_list)

        # Populate fauna list
        for fauna in self.available_fauna:
            item = QListWidgetItem(fauna.name)
            item.setData(Qt.ItemDataRole.UserRole, fauna.id)
            self.fauna_list.addItem(item)

        layout.addWidget(fauna_group)

        return widget

    def _add_climate_zone(self):
        """Add a new climate zone."""
        zone_name, ok = QInputDialog.getText(self, "New Climate Zone", "Enter zone name (e.g., Tropical, Temperate):")
        if ok and zone_name:
            climate_zone = ClimateZone(
                zone_name=zone_name,
                description=""
            )
            if not hasattr(self.planet, 'climate_zones'):
                self.planet.climate_zones = []
            self.planet.climate_zones.append(climate_zone)
            self._refresh_climate_list()

    def _edit_climate_zone(self):
        """Edit selected climate zone."""
        current = self.climate_list.currentItem()
        if not current:
            return

        index = self.climate_list.currentRow()
        zone = self.planet.climate_zones[index]

        # Simple edit - just name for now
        zone_name, ok = QInputDialog.getText(self, "Edit Climate Zone", "Zone name:", text=zone.zone_name)
        if ok and zone_name:
            zone.zone_name = zone_name
            self._refresh_climate_list()

    def _remove_climate_zone(self):
        """Remove selected climate zone."""
        current = self.climate_list.currentItem()
        if not current:
            return

        index = self.climate_list.currentRow()
        self.planet.climate_zones.pop(index)
        self._refresh_climate_list()

    def _refresh_climate_list(self):
        """Refresh climate zones list display."""
        self.climate_list.clear()
        if hasattr(self.planet, 'climate_zones'):
            for zone in self.planet.climate_zones:
                item = QListWidgetItem(zone.zone_name)
                self.climate_list.addItem(item)

    def _load_planet(self):
        """Load planet data into form."""
        self.name_edit.setText(self.planet.name)

        # Planet type
        type_map = {
            PlanetType.TERRESTRIAL: 0,
            PlanetType.GAS_GIANT: 1,
            PlanetType.ICE_GIANT: 2,
            PlanetType.DESERT: 3,
            PlanetType.OCEAN: 4,
            PlanetType.JUNGLE: 5,
            PlanetType.ARCTIC: 6,
            PlanetType.VOLCANIC: 7,
            PlanetType.ARTIFICIAL: 8
        }
        self.type_combo.setCurrentIndex(type_map.get(self.planet.planet_type, 0))

        self.description_edit.setPlainText(self.planet.description)

        # Load climate zones
        self._refresh_climate_list()

        # Select flora species
        if hasattr(self.planet, 'flora_species') and self.planet.flora_species:
            for i in range(self.flora_list.count()):
                item = self.flora_list.item(i)
                flora_id = item.data(Qt.ItemDataRole.UserRole)
                if flora_id in self.planet.flora_species:
                    item.setSelected(True)

        # Select fauna species
        if hasattr(self.planet, 'fauna_species') and self.planet.fauna_species:
            for i in range(self.fauna_list.count()):
                item = self.fauna_list.item(i)
                fauna_id = item.data(Qt.ItemDataRole.UserRole)
                if fauna_id in self.planet.fauna_species:
                    item.setSelected(True)

    def _save(self):
        """Save planet data."""
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter a planet name.")
            return

        if not self.planet.id:
            self.planet.id = str(uuid.uuid4())

        self.planet.name = name

        # Planet type
        type_map = [
            PlanetType.TERRESTRIAL,
            PlanetType.GAS_GIANT,
            PlanetType.ICE_GIANT,
            PlanetType.DESERT,
            PlanetType.OCEAN,
            PlanetType.JUNGLE,
            PlanetType.ARCTIC,
            PlanetType.VOLCANIC,
            PlanetType.ARTIFICIAL
        ]
        self.planet.planet_type = type_map[self.type_combo.currentIndex()]

        self.planet.description = self.description_edit.toPlainText().strip()

        # Save selected flora
        selected_flora = []
        for i in range(self.flora_list.count()):
            item = self.flora_list.item(i)
            if item.isSelected():
                flora_id = item.data(Qt.ItemDataRole.UserRole)
                selected_flora.append(flora_id)
        self.planet.flora_species = selected_flora

        # Save selected fauna
        selected_fauna = []
        for i in range(self.fauna_list.count()):
            item = self.fauna_list.item(i)
            if item.isSelected():
                fauna_id = item.data(Qt.ItemDataRole.UserRole)
                selected_fauna.append(fauna_id)
        self.planet.fauna_species = selected_fauna

        self.accept()

    def get_planet(self) -> Planet:
        """Get the edited planet."""
        return self.planet


class EnhancedStarSystemEditor(QDialog):
    """Dialog for editing complete star systems with stars and planets."""

    def __init__(self, star_system: Optional[StarSystem] = None,
                 available_flora: List = None,
                 available_fauna: List = None,
                 available_climate_presets: List = None,
                 parent=None):
        """Initialize enhanced star system editor."""
        super().__init__(parent)
        self.star_system = star_system or StarSystem(
            id="",
            name="",
            system_type="single"
        )
        # Ensure we have planets and stars lists
        if not hasattr(self.star_system, 'planets'):
            self.star_system.planets = []
        if not hasattr(self.star_system, 'stars'):
            self.star_system.stars = []

        self.available_flora = available_flora or []
        self.available_fauna = available_fauna or []
        self.available_climate_presets = available_climate_presets or []
        self._init_ui()
        if star_system:
            self._load_system()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Star System Editor")
        self.setMinimumSize(900, 750)

        main_layout = QVBoxLayout(self)

        # Tabs for different sections
        tabs = QTabWidget()

        # Basic Info Tab
        basic_tab = self._create_basic_tab()
        tabs.addTab(basic_tab, "Basic Info")

        # Stars Tab
        stars_tab = self._create_stars_tab()
        tabs.addTab(stars_tab, "⭐ Stars")

        # Planets Tab
        planets_tab = self._create_planets_tab()
        tabs.addTab(planets_tab, "🌍 Planets")

        # Key Facts Tab
        facts_tab = self._create_facts_tab()
        tabs.addTab(facts_tab, "📊 Key Facts")

        main_layout.addWidget(tabs)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def _create_basic_tab(self):
        """Create basic info tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("System name (e.g., Solar System, Alpha Centauri)")
        layout.addRow("Name:*", self.name_edit)

        self.system_type_combo = QComboBox()
        self.system_type_combo.addItems(["Single", "Binary", "Trinary", "Multiple"])
        layout.addRow("System Type:", self.system_type_combo)

        self.galaxy_edit = QLineEdit()
        self.galaxy_edit.setPlaceholderText("e.g., Milky Way, Andromeda")
        layout.addRow("Galaxy:", self.galaxy_edit)

        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("e.g., Orion Arm, Galactic Core")
        layout.addRow("Location in Galaxy:", self.location_edit)

        self.distance_edit = QLineEdit()
        self.distance_edit.setPlaceholderText("e.g., 4.37 light years")
        layout.addRow("Distance from Earth:", self.distance_edit)

        self.habitable_inner_edit = QLineEdit()
        self.habitable_inner_edit.setPlaceholderText("e.g., 0.95 AU")
        layout.addRow("Habitable Zone (Inner):", self.habitable_inner_edit)

        self.habitable_outer_edit = QLineEdit()
        self.habitable_outer_edit.setPlaceholderText("e.g., 1.37 AU")
        layout.addRow("Habitable Zone (Outer):", self.habitable_outer_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Describe this star system...")
        self.description_edit.setMaximumHeight(120)
        layout.addRow("Description:", self.description_edit)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Additional notes...")
        self.notes_edit.setMaximumHeight(80)
        layout.addRow("Notes:", self.notes_edit)

        return widget

    def _create_stars_tab(self):
        """Create stars management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        help_label = QLabel("Manage the stars in this system. For binary/trinary systems, add multiple stars.")
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #6b7280; font-size: 11px; margin-bottom: 8px;")
        layout.addWidget(help_label)

        # Stars list with buttons
        list_layout = QHBoxLayout()

        self.stars_list = QListWidget()
        list_layout.addWidget(self.stars_list)

        btn_layout = QVBoxLayout()
        add_star_btn = QPushButton("➕ Add Star")
        add_star_btn.clicked.connect(self._add_star)
        btn_layout.addWidget(add_star_btn)

        edit_star_btn = QPushButton("✏️ Edit Star")
        edit_star_btn.clicked.connect(self._edit_star)
        btn_layout.addWidget(edit_star_btn)

        remove_star_btn = QPushButton("🗑️ Remove Star")
        remove_star_btn.clicked.connect(self._remove_star)
        btn_layout.addWidget(remove_star_btn)

        btn_layout.addStretch()
        list_layout.addLayout(btn_layout)

        layout.addLayout(list_layout)

        return widget

    def _create_planets_tab(self):
        """Create planets management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        help_label = QLabel("Manage the planets orbiting in this system.")
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #6b7280; font-size: 11px; margin-bottom: 8px;")
        layout.addWidget(help_label)

        # Planets list with buttons
        list_layout = QHBoxLayout()

        self.planets_list = QListWidget()
        list_layout.addWidget(self.planets_list)

        btn_layout = QVBoxLayout()
        add_planet_btn = QPushButton("➕ Add Planet")
        add_planet_btn.clicked.connect(self._add_planet)
        btn_layout.addWidget(add_planet_btn)

        edit_planet_btn = QPushButton("✏️ Edit Planet")
        edit_planet_btn.clicked.connect(self._edit_planet)
        btn_layout.addWidget(edit_planet_btn)

        remove_planet_btn = QPushButton("🗑️ Remove Planet")
        remove_planet_btn.clicked.connect(self._remove_planet)
        btn_layout.addWidget(remove_planet_btn)

        btn_layout.addStretch()
        list_layout.addLayout(btn_layout)

        layout.addLayout(list_layout)

        return widget

    def _create_facts_tab(self):
        """Create key facts tab for inter-planetary distances and other data."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        help_label = QLabel("Key facts about this system (distances between planets, notable features, etc.)")
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #6b7280; font-size: 11px; margin-bottom: 8px;")
        layout.addWidget(help_label)

        self.key_facts_edit = QTextEdit()
        self.key_facts_edit.setPlaceholderText(
            "Examples:\n"
            "- Distance Earth to Mars: 0.52 AU (avg)\n"
            "- Distance Mars to Jupiter: 3.68 AU (avg)\n"
            "- Notable asteroids: Ceres, Vesta\n"
            "- Unique features: Kuiper Belt, Oort Cloud"
        )
        layout.addWidget(self.key_facts_edit)

        return widget

    def _add_star(self):
        """Add a new star."""
        name, ok = QInputDialog.getText(self, "New Star", "Enter star name:")
        if ok and name:
            star = Star(
                id=str(uuid.uuid4()),
                name=name,
                spectral_class="G"
            )
            if not hasattr(self.star_system, 'stars'):
                self.star_system.stars = []
            self.star_system.stars.append(star)
            self._refresh_stars_list()

    def _edit_star(self):
        """Edit selected star."""
        current = self.stars_list.currentItem()
        if not current:
            return

        star_id = current.data(Qt.ItemDataRole.UserRole)
        star = next((s for s in self.star_system.stars if s.id == star_id), None)
        if star:
            # Simple edit for now - just name
            name, ok = QInputDialog.getText(self, "Edit Star", "Star name:", text=star.name)
            if ok and name:
                star.name = name
                self._refresh_stars_list()

    def _remove_star(self):
        """Remove selected star."""
        current = self.stars_list.currentItem()
        if not current:
            return

        star_id = current.data(Qt.ItemDataRole.UserRole)
        self.star_system.stars = [s for s in self.star_system.stars if s.id != star_id]
        self._refresh_stars_list()

    def _add_planet(self):
        """Add a new planet."""
        editor = PlanetEditorDialog(
            available_flora=self.available_flora,
            available_fauna=self.available_fauna,
            available_climate_presets=self.available_climate_presets,
            parent=self
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            planet = editor.get_planet()
            if not hasattr(self.star_system, 'planets'):
                self.star_system.planets = []
            self.star_system.planets.append(planet)
            self._refresh_planets_list()

    def _edit_planet(self):
        """Edit selected planet."""
        current = self.planets_list.currentItem()
        if not current:
            return

        planet_id = current.data(Qt.ItemDataRole.UserRole)
        planet = next((p for p in self.star_system.planets if p.id == planet_id), None)
        if planet:
            editor = PlanetEditorDialog(
                planet=planet,
                available_flora=self.available_flora,
                available_fauna=self.available_fauna,
                available_climate_presets=self.available_climate_presets,
                parent=self
            )
            if editor.exec() == QDialog.DialogCode.Accepted:
                self._refresh_planets_list()

    def _remove_planet(self):
        """Remove selected planet."""
        current = self.planets_list.currentItem()
        if not current:
            return

        planet_id = current.data(Qt.ItemDataRole.UserRole)
        self.star_system.planets = [p for p in self.star_system.planets if p.id != planet_id]
        self._refresh_planets_list()

    def _refresh_stars_list(self):
        """Refresh stars list display."""
        self.stars_list.clear()
        if hasattr(self.star_system, 'stars'):
            for star in self.star_system.stars:
                item = QListWidgetItem(f"{star.name} ({star.spectral_class})")
                item.setData(Qt.ItemDataRole.UserRole, star.id)
                self.stars_list.addItem(item)

    def _refresh_planets_list(self):
        """Refresh planets list display."""
        self.planets_list.clear()
        if hasattr(self.star_system, 'planets'):
            for planet in self.star_system.planets:
                type_str = planet.planet_type.value.replace("_", " ").title()
                item = QListWidgetItem(f"{planet.name} ({type_str})")
                item.setData(Qt.ItemDataRole.UserRole, planet.id)
                self.planets_list.addItem(item)

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
        self.habitable_inner_edit.setText(self.star_system.habitable_zone_inner or "")
        self.habitable_outer_edit.setText(self.star_system.habitable_zone_outer or "")
        self.description_edit.setPlainText(self.star_system.description)
        self.notes_edit.setPlainText(self.star_system.notes)

        # Load key facts if available
        if hasattr(self.star_system, 'key_facts'):
            self.key_facts_edit.setPlainText(self.star_system.key_facts or "")

        # Refresh lists
        self._refresh_stars_list()
        self._refresh_planets_list()

    def _save(self):
        """Save star system data."""
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter a system name.")
            return

        if not self.star_system.id:
            self.star_system.id = str(uuid.uuid4())

        self.star_system.name = name

        # System type
        type_map = {0: "single", 1: "binary", 2: "trinary", 3: "multiple"}
        self.star_system.system_type = type_map[self.system_type_combo.currentIndex()]

        self.star_system.galaxy = self.galaxy_edit.text().strip() or None
        self.star_system.location = self.location_edit.text().strip() or None
        self.star_system.distance_from_earth = self.distance_edit.text().strip() or None
        self.star_system.habitable_zone_inner = self.habitable_inner_edit.text().strip() or None
        self.star_system.habitable_zone_outer = self.habitable_outer_edit.text().strip() or None
        self.star_system.description = self.description_edit.toPlainText().strip()
        self.star_system.notes = self.notes_edit.toPlainText().strip()

        # Save key facts
        self.star_system.key_facts = self.key_facts_edit.toPlainText().strip()

        self.accept()

    def get_star_system(self) -> StarSystem:
        """Get the edited star system."""
        return self.star_system


class EnhancedStarSystemBuilderWidget(QWidget):
    """Enhanced widget for managing star systems with integrated stars and planets."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize enhanced star system builder."""
        super().__init__()
        self.star_systems: List[StarSystem] = []
        self.available_flora: List = []
        self.available_fauna: List = []
        self.available_climate_presets: List = []
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

        subtitle = QLabel("Manage complete star systems with stars, planets, and astronomical data")
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
        editor = EnhancedStarSystemEditor(
            available_flora=self.available_flora,
            available_fauna=self.available_fauna,
            available_climate_presets=self.available_climate_presets,
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

        editor = EnhancedStarSystemEditor(
            star_system=system,
            available_flora=self.available_flora,
            available_fauna=self.available_fauna,
            available_climate_presets=self.available_climate_presets,
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
            # Count stars and planets
            star_count = len(system.stars) if hasattr(system, 'stars') else 0
            planet_count = len(system.planets) if hasattr(system, 'planets') else 0

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

    def set_available_flora(self, flora: List):
        """Set available flora."""
        self.available_flora = flora

    def set_available_fauna(self, fauna: List):
        """Set available fauna."""
        self.available_fauna = fauna

    def set_available_climate_presets(self, presets: List):
        """Set available climate presets."""
        self.available_climate_presets = presets

    def load_star_systems(self, systems: List[StarSystem]):
        """Load star systems list."""
        self.star_systems = systems
        self._update_list()

    def get_star_systems(self) -> List[StarSystem]:
        """Get star systems list."""
        return self.star_systems
