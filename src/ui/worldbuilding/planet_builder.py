"""Planet builder with continents, moons, climate, and visual map."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox, QSpinBox,
    QGroupBox, QFormLayout, QTabWidget, QMessageBox, QFileDialog,
    QScrollArea, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from typing import List
import uuid

from src.models.worldbuilding_objects import Planet, Moon, Continent, City, ClimateZone, PlanetType, ClimatePreset


class PlanetEditor(QWidget):
    """Editor for a single planet with all details."""

    content_changed = pyqtSignal()

    def __init__(self, planet: Planet, available_climate_presets=None, available_flora=None, available_fauna=None):
        """Initialize planet editor.

        Args:
            planet: Planet to edit
            available_climate_presets: List of ClimatePreset objects
            available_flora: List of Flora objects
            available_fauna: List of Fauna objects
        """
        super().__init__()
        self.planet = planet
        self.available_climate_presets = available_climate_presets or []
        self.available_flora = available_flora or []
        self.available_fauna = available_fauna or []
        self._init_ui()
        self._load_planet()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        # Tabs for organization
        tabs = QTabWidget()

        # Basic Info Tab
        basic_tab = self._create_basic_tab()
        tabs.addTab(basic_tab, "Basic Info")

        # Moons Tab
        moons_tab = self._create_moons_tab()
        tabs.addTab(moons_tab, "Moons")

        # Geography Tab
        geography_tab = self._create_geography_tab()
        tabs.addTab(geography_tab, "Geography")

        # Climate Tab
        climate_tab = self._create_climate_tab()
        tabs.addTab(climate_tab, "Climate")

        # Flora & Fauna Tab
        biology_tab = self._create_biology_tab()
        tabs.addTab(biology_tab, "Flora & Fauna")

        # Visual Tab
        visual_tab = self._create_visual_tab()
        tabs.addTab(visual_tab, "Maps & Images")

        layout.addWidget(tabs)

    def _create_basic_tab(self) -> QWidget:
        """Create basic info tab."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_widget = QWidget()
        layout = QFormLayout(scroll_widget)

        # Basic Information
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self.content_changed.emit)
        layout.addRow("Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value.title() for t in PlanetType])
        self.type_combo.currentTextChanged.connect(self.content_changed.emit)
        layout.addRow("Type:", self.type_combo)

        # Stellar System
        from PyQt6.QtWidgets import QCheckBox

        self.star_system_edit = QLineEdit()
        self.star_system_edit.setPlaceholderText("e.g., Sol, Alpha Centauri")
        layout.addRow("Star System:", self.star_system_edit)

        self.primary_star_edit = QLineEdit()
        self.primary_star_edit.setPlaceholderText("Primary star name")
        layout.addRow("Primary Star:", self.primary_star_edit)

        self.secondary_stars_edit = QLineEdit()
        self.secondary_stars_edit.setPlaceholderText("Comma-separated for binary/trinary systems")
        layout.addRow("Secondary Stars:", self.secondary_stars_edit)

        self.in_habitable_zone_checkbox = QCheckBox("Planet is in habitable (life-bearing) zone")
        layout.addRow("", self.in_habitable_zone_checkbox)

        # Orbital Mechanics
        separator1 = QLabel("<b>Orbital Mechanics</b>")
        layout.addRow(separator1)

        self.orbital_distance_edit = QLineEdit()
        self.orbital_distance_edit.setPlaceholderText("e.g., 1 AU, 150 million km")
        layout.addRow("Orbital Distance:", self.orbital_distance_edit)

        self.orbital_period_edit = QLineEdit()
        self.orbital_period_edit.setPlaceholderText("e.g., 365.25 days")
        layout.addRow("Orbital Period (Year):", self.orbital_period_edit)

        self.rotation_period_edit = QLineEdit()
        self.rotation_period_edit.setPlaceholderText("e.g., 24 hours")
        layout.addRow("Rotation Period (Day):", self.rotation_period_edit)

        self.axial_tilt_edit = QLineEdit()
        self.axial_tilt_edit.setPlaceholderText("e.g., 23.5 degrees")
        layout.addRow("Axial Tilt:", self.axial_tilt_edit)

        self.orbital_eccentricity_edit = QLineEdit()
        self.orbital_eccentricity_edit.setPlaceholderText("e.g., 0.0167 (0 = perfect circle)")
        layout.addRow("Orbital Eccentricity:", self.orbital_eccentricity_edit)

        self.retrograde_checkbox = QCheckBox("Retrograde rotation (spins backwards)")
        layout.addRow("", self.retrograde_checkbox)

        # Physical Properties
        separator2 = QLabel("<b>Physical Properties</b>")
        layout.addRow(separator2)

        self.diameter_edit = QLineEdit()
        self.diameter_edit.setPlaceholderText("e.g., 12,742 km")
        layout.addRow("Diameter:", self.diameter_edit)

        self.mass_edit = QLineEdit()
        self.mass_edit.setPlaceholderText("e.g., 5.97 × 10^24 kg")
        layout.addRow("Mass:", self.mass_edit)

        self.gravity_edit = QLineEdit()
        self.gravity_edit.setPlaceholderText("e.g., 9.8 m/s² or 1.0 g")
        layout.addRow("Gravity:", self.gravity_edit)

        self.atmosphere_edit = QTextEdit()
        self.atmosphere_edit.setMaximumHeight(80)
        self.atmosphere_edit.setPlaceholderText("Atmospheric composition (e.g., 78% N2, 21% O2, 1% Ar)")
        layout.addRow("Atmosphere:", self.atmosphere_edit)

        self.atmospheric_pressure_edit = QLineEdit()
        self.atmospheric_pressure_edit.setPlaceholderText("e.g., 1 atm, 101.3 kPa")
        layout.addRow("Atmospheric Pressure:", self.atmospheric_pressure_edit)

        self.magnetic_field_edit = QLineEdit()
        self.magnetic_field_edit.setPlaceholderText("e.g., Strong, Weak, None")
        layout.addRow("Magnetic Field:", self.magnetic_field_edit)

        # Geography
        separator3 = QLabel("<b>Geography</b>")
        layout.addRow(separator3)

        self.ocean_coverage_edit = QLineEdit()
        self.ocean_coverage_edit.setPlaceholderText("e.g., 71%")
        layout.addRow("Ocean Coverage:", self.ocean_coverage_edit)

        self.land_coverage_edit = QLineEdit()
        self.land_coverage_edit.setPlaceholderText("e.g., 29%")
        layout.addRow("Land Coverage:", self.land_coverage_edit)

        # Population
        separator4 = QLabel("<b>Life & Population</b>")
        layout.addRow(separator4)

        self.population_edit = QLineEdit()
        self.population_edit.setPlaceholderText("e.g., 8000000000")
        layout.addRow("Population:", self.population_edit)

        self.dominant_species_edit = QLineEdit()
        self.dominant_species_edit.setPlaceholderText("Comma-separated species names")
        layout.addRow("Dominant Species:", self.dominant_species_edit)

        # Description
        separator5 = QLabel("<b>Description</b>")
        layout.addRow(separator5)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("General description of the planet...")
        layout.addRow("Description:", self.description_edit)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Additional notes...")
        self.notes_edit.setMaximumHeight(100)
        layout.addRow("Notes:", self.notes_edit)

        scroll.setWidget(scroll_widget)

        main_layout = QVBoxLayout(widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        return widget

    def _create_moons_tab(self) -> QWidget:
        """Create moons management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Moons list
        label = QLabel("Moons:")
        layout.addWidget(label)

        self.moons_list = QListWidget()
        layout.addWidget(self.moons_list)

        # Buttons
        btn_layout = QHBoxLayout()

        add_moon_btn = QPushButton("Add Moon")
        add_moon_btn.clicked.connect(self._add_moon)
        btn_layout.addWidget(add_moon_btn)

        remove_moon_btn = QPushButton("Remove Moon")
        remove_moon_btn.clicked.connect(self._remove_moon)
        btn_layout.addWidget(remove_moon_btn)

        layout.addLayout(btn_layout)

        # Moon details
        from PyQt6.QtWidgets import QCheckBox
        moon_group = QGroupBox("Moon Details")
        moon_layout = QFormLayout(moon_group)

        self.moon_name_edit = QLineEdit()
        moon_layout.addRow("Name:", self.moon_name_edit)

        self.moon_diameter_edit = QLineEdit()
        self.moon_diameter_edit.setPlaceholderText("e.g., 3,474 km")
        moon_layout.addRow("Diameter:", self.moon_diameter_edit)

        self.moon_mass_edit = QLineEdit()
        self.moon_mass_edit.setPlaceholderText("e.g., 7.34 × 10^22 kg")
        moon_layout.addRow("Mass:", self.moon_mass_edit)

        self.moon_orbit_edit = QLineEdit()
        self.moon_orbit_edit.setPlaceholderText("e.g., 27.3 days")
        moon_layout.addRow("Orbital Period:", self.moon_orbit_edit)

        self.moon_orbital_distance_edit = QLineEdit()
        self.moon_orbital_distance_edit.setPlaceholderText("e.g., 384,400 km")
        moon_layout.addRow("Orbital Distance:", self.moon_orbital_distance_edit)

        self.moon_tidally_locked_checkbox = QCheckBox("Tidally locked (same face always toward planet)")
        moon_layout.addRow("", self.moon_tidally_locked_checkbox)

        self.moon_atmosphere_edit = QTextEdit()
        self.moon_atmosphere_edit.setMaximumHeight(60)
        self.moon_atmosphere_edit.setPlaceholderText("Atmospheric composition (if any)...")
        moon_layout.addRow("Atmosphere:", self.moon_atmosphere_edit)

        self.moon_surface_edit = QTextEdit()
        self.moon_surface_edit.setMaximumHeight(80)
        self.moon_surface_edit.setPlaceholderText("Surface features: craters, maria, mountains, etc...")
        moon_layout.addRow("Surface Features:", self.moon_surface_edit)

        self.moon_desc_edit = QTextEdit()
        self.moon_desc_edit.setMaximumHeight(100)
        self.moon_desc_edit.setPlaceholderText("General description...")
        moon_layout.addRow("Description:", self.moon_desc_edit)

        layout.addWidget(moon_group)

        return widget

    def _create_geography_tab(self) -> QWidget:
        """Create geography tab with continents and cities."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Continents section
        cont_label = QLabel("Continents:")
        layout.addWidget(cont_label)

        self.continents_list = QListWidget()
        layout.addWidget(self.continents_list)

        cont_btn_layout = QHBoxLayout()
        add_cont_btn = QPushButton("Add Continent")
        add_cont_btn.clicked.connect(self._add_continent)
        cont_btn_layout.addWidget(add_cont_btn)

        remove_cont_btn = QPushButton("Remove")
        remove_cont_btn.clicked.connect(self._remove_continent)
        cont_btn_layout.addWidget(remove_cont_btn)

        layout.addLayout(cont_btn_layout)

        # Cities section
        cities_label = QLabel("Major Cities:")
        layout.addWidget(cities_label)

        self.cities_list = QListWidget()
        layout.addWidget(self.cities_list)

        cities_btn_layout = QHBoxLayout()
        add_city_btn = QPushButton("Add City")
        add_city_btn.clicked.connect(self._add_city)
        cities_btn_layout.addWidget(add_city_btn)

        remove_city_btn = QPushButton("Remove")
        remove_city_btn.clicked.connect(self._remove_city)
        cities_btn_layout.addWidget(remove_city_btn)

        layout.addLayout(cities_btn_layout)

        return widget

    def _create_climate_tab(self) -> QWidget:
        """Create climate zones tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Climate preset selector
        preset_group = QGroupBox("Climate Preset")
        preset_layout = QVBoxLayout(preset_group)

        preset_help = QLabel("Apply a climate preset to quickly configure this planet's climate:")
        preset_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        preset_layout.addWidget(preset_help)

        preset_select_layout = QHBoxLayout()
        self.climate_preset_combo = QComboBox()
        self.climate_preset_combo.addItem("-- Select Preset --", None)
        preset_select_layout.addWidget(self.climate_preset_combo)

        apply_preset_btn = QPushButton("Apply Preset")
        apply_preset_btn.clicked.connect(self._apply_climate_preset)
        preset_select_layout.addWidget(apply_preset_btn)

        preset_layout.addLayout(preset_select_layout)
        layout.addWidget(preset_group)

        # Climate zones
        label = QLabel("Climate Zones:")
        layout.addWidget(label)

        self.climate_list = QListWidget()
        layout.addWidget(self.climate_list)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Add Climate Zone")
        add_btn.clicked.connect(self._add_climate)
        btn_layout.addWidget(add_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._remove_climate)
        btn_layout.addWidget(remove_btn)

        layout.addLayout(btn_layout)

        # Planetary climate description
        desc_label = QLabel("Overall Planetary Climate:")
        layout.addWidget(desc_label)

        self.planetary_climate_edit = QTextEdit()
        layout.addWidget(self.planetary_climate_edit)

        return widget

    def _create_biology_tab(self) -> QWidget:
        """Create flora and fauna tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Flora Section
        flora_group = QGroupBox("🌿 Flora (Plant Species)")
        flora_layout = QVBoxLayout(flora_group)

        flora_help = QLabel("Select plant species that exist on this planet:")
        flora_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        flora_layout.addWidget(flora_help)

        self.flora_list = QListWidget()
        self.flora_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        flora_layout.addWidget(self.flora_list)

        flora_btn_layout = QHBoxLayout()
        select_all_flora_btn = QPushButton("Select All")
        select_all_flora_btn.clicked.connect(lambda: self.flora_list.selectAll())
        flora_btn_layout.addWidget(select_all_flora_btn)

        clear_flora_btn = QPushButton("Clear Selection")
        clear_flora_btn.clicked.connect(lambda: self.flora_list.clearSelection())
        flora_btn_layout.addWidget(clear_flora_btn)

        flora_layout.addLayout(flora_btn_layout)
        layout.addWidget(flora_group)

        # Fauna Section
        fauna_group = QGroupBox("🦁 Fauna (Animal Species)")
        fauna_layout = QVBoxLayout(fauna_group)

        fauna_help = QLabel("Select animal species that exist on this planet:")
        fauna_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        fauna_layout.addWidget(fauna_help)

        self.fauna_list = QListWidget()
        self.fauna_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        fauna_layout.addWidget(self.fauna_list)

        fauna_btn_layout = QHBoxLayout()
        select_all_fauna_btn = QPushButton("Select All")
        select_all_fauna_btn.clicked.connect(lambda: self.fauna_list.selectAll())
        fauna_btn_layout.addWidget(select_all_fauna_btn)

        clear_fauna_btn = QPushButton("Clear Selection")
        clear_fauna_btn.clicked.connect(lambda: self.fauna_list.clearSelection())
        fauna_btn_layout.addWidget(clear_fauna_btn)

        fauna_layout.addLayout(fauna_btn_layout)
        layout.addWidget(fauna_group)

        info_label = QLabel(
            "💡 Tip: Create flora and fauna species in the Flora and Fauna tabs first, "
            "then come here to assign them to this planet."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #6b7280; font-size: 10px; padding: 8px; background-color: #f3f4f6; border-radius: 4px;")
        layout.addWidget(info_label)

        layout.addStretch()

        return widget

    def _create_visual_tab(self) -> QWidget:
        """Create visual maps and images tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Planet image
        planet_group = QGroupBox("Planet Image")
        planet_layout = QVBoxLayout(planet_group)

        self.planet_image_label = QLabel("No image")
        self.planet_image_label.setFixedSize(300, 300)
        self.planet_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.planet_image_label.setStyleSheet("border: 1px solid #ccc; background: #f0f0f0;")
        planet_layout.addWidget(self.planet_image_label, alignment=Qt.AlignmentFlag.AlignCenter)

        planet_btn_layout = QHBoxLayout()
        upload_planet_btn = QPushButton("Upload Planet Image")
        upload_planet_btn.clicked.connect(self._upload_planet_image)
        planet_btn_layout.addWidget(upload_planet_btn)

        generate_planet_btn = QPushButton("✨ AI Generate Planet")
        planet_btn_layout.addWidget(generate_planet_btn)

        planet_layout.addLayout(planet_btn_layout)
        layout.addWidget(planet_group)

        # Map image
        map_group = QGroupBox("Continental Map")
        map_layout = QVBoxLayout(map_group)

        self.map_image_label = QLabel("No map")
        self.map_image_label.setFixedSize(400, 300)
        self.map_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.map_image_label.setStyleSheet("border: 1px solid #ccc; background: #f0f0f0;")
        map_layout.addWidget(self.map_image_label, alignment=Qt.AlignmentFlag.AlignCenter)

        map_btn_layout = QHBoxLayout()
        upload_map_btn = QPushButton("Upload Map")
        upload_map_btn.clicked.connect(self._upload_map_image)
        map_btn_layout.addWidget(upload_map_btn)

        generate_map_btn = QPushButton("✨ AI Generate Map")
        map_btn_layout.addWidget(generate_map_btn)

        map_layout.addLayout(map_btn_layout)
        layout.addWidget(map_group)

        layout.addStretch()

        return widget

    def _load_planet(self):
        """Load planet data into fields."""
        self.name_edit.setText(self.planet.name)
        self.type_combo.setCurrentText(self.planet.planet_type.value.title())

        if self.planet.star_system:
            self.star_system_edit.setText(self.planet.star_system)
        if self.planet.diameter:
            self.diameter_edit.setText(self.planet.diameter)
        if self.planet.day_length:
            self.day_length_edit.setText(self.planet.day_length)
        if self.planet.year_length:
            self.year_length_edit.setText(self.planet.year_length)
        if self.planet.atmosphere:
            self.atmosphere_edit.setPlainText(self.planet.atmosphere)
        if self.planet.population:
            self.population_edit.setText(str(self.planet.population))
        if self.planet.description:
            self.description_edit.setPlainText(self.planet.description)

        # Load moons
        for moon in self.planet.moons:
            self.moons_list.addItem(moon.name)

        # Load continents
        for continent in self.planet.continents:
            self.continents_list.addItem(continent.name)

        # Load cities
        for city in self.planet.cities:
            self.cities_list.addItem(city.name)

        # Load climate zones
        for climate in self.planet.climate_zones:
            self.climate_list.addItem(climate.zone_name)

        if self.planet.dominant_climate:
            self.planetary_climate_edit.setPlainText(self.planet.dominant_climate)

        # Load images
        if self.planet.planet_image_path:
            pixmap = QPixmap(self.planet.planet_image_path)
            if not pixmap.isNull():
                self.planet_image_label.setPixmap(
                    pixmap.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio)
                )

        if self.planet.map_image_path:
            pixmap = QPixmap(self.planet.map_image_path)
            if not pixmap.isNull():
                self.map_image_label.setPixmap(
                    pixmap.scaled(400, 300, Qt.AspectRatioMode.KeepAspectRatio)
                )

    def _add_moon(self):
        """Add a new moon."""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Moon", "Enter moon name:")
        if ok and name:
            self.moons_list.addItem(name)

    def _remove_moon(self):
        """Remove selected moon."""
        current = self.moons_list.currentRow()
        if current >= 0:
            self.moons_list.takeItem(current)

    def _add_continent(self):
        """Add a continent."""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Continent", "Enter continent name:")
        if ok and name:
            self.continents_list.addItem(name)

    def _remove_continent(self):
        """Remove selected continent."""
        current = self.continents_list.currentRow()
        if current >= 0:
            self.continents_list.takeItem(current)

    def _add_city(self):
        """Add a city."""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New City", "Enter city name:")
        if ok and name:
            self.cities_list.addItem(name)

    def _remove_city(self):
        """Remove selected city."""
        current = self.cities_list.currentRow()
        if current >= 0:
            self.cities_list.takeItem(current)

    def _add_climate(self):
        """Add a climate zone."""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Climate Zone", "Enter zone name:")
        if ok and name:
            self.climate_list.addItem(name)

    def _remove_climate(self):
        """Remove selected climate zone."""
        current = self.climate_list.currentRow()
        if current >= 0:
            self.climate_list.takeItem(current)

    def _apply_climate_preset(self):
        """Apply selected climate preset to planet."""
        preset_id = self.climate_preset_combo.currentData()
        if not preset_id:
            return

        preset = next((p for p in self.available_climate_presets if p.id == preset_id), None)
        if not preset:
            return

        # Clear existing climate zones
        self.climate_list.clear()

        # Add zones from preset
        for zone in preset.default_zones:
            self.climate_list.addItem(zone)

        # Set planetary climate description
        climate_desc = f"{preset.name}\n\n"
        if preset.temperature_range:
            climate_desc += f"Temperature Range: {preset.temperature_range}\n"
        if preset.precipitation_pattern:
            climate_desc += f"Precipitation: {preset.precipitation_pattern}\n"
        if preset.atmospheric_composition:
            climate_desc += f"Atmosphere: {preset.atmospheric_composition}\n"
        if preset.weather_patterns:
            climate_desc += f"\n{preset.weather_patterns}\n"
        if preset.extreme_events:
            climate_desc += f"\nExtreme Events: {', '.join(preset.extreme_events)}\n"

        self.planetary_climate_edit.setPlainText(climate_desc.strip())

        self.content_changed.emit()

    def set_available_climate_presets(self, presets):
        """Set available climate presets for selection.

        Args:
            presets: List of ClimatePreset objects
        """
        self.available_climate_presets = presets

        # Update combo box
        self.climate_preset_combo.clear()
        self.climate_preset_combo.addItem("-- Select Preset --", None)

        for preset in presets:
            self.climate_preset_combo.addItem(preset.name, preset.id)

    def _upload_planet_image(self):
        """Upload planet image."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Planet Image", "",
            "Images (*.png *.jpg *.jpeg)"
        )
        if file_path:
            pixmap = QPixmap(file_path)
            self.planet_image_label.setPixmap(
                pixmap.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio)
            )
            self.planet.planet_image_path = file_path

    def _upload_map_image(self):
        """Upload map image."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Map Image", "",
            "Images (*.png *.jpg *.jpeg)"
        )
        if file_path:
            pixmap = QPixmap(file_path)
            self.map_image_label.setPixmap(
                pixmap.scaled(400, 300, Qt.AspectRatioMode.KeepAspectRatio)
            )
            self.planet.map_image_path = file_path

    def save_to_model(self):
        """Save all data to planet model."""
        from src.models.worldbuilding_objects import Moon, Continent, City, Climate, PlanetType

        self.planet.name = self.name_edit.text()
        self.planet.planet_type = PlanetType(self.type_combo.currentText().lower().replace(" ", "_"))
        self.planet.star_system = self.star_system_edit.text()
        self.planet.diameter = self.diameter_edit.text()
        self.planet.day_length = self.day_length_edit.text()
        self.planet.year_length = self.year_length_edit.text()
        self.planet.atmosphere = self.atmosphere_edit.toPlainText()
        try:
            self.planet.population = int(self.population_edit.text()) if self.population_edit.text() else None
        except ValueError:
            self.planet.population = None
        self.planet.description = self.description_edit.toPlainText()
        self.planet.dominant_climate = self.planetary_climate_edit.toPlainText()

        # Save moons (simplified - just names for now)
        self.planet.moons = [
            Moon(name=self.moons_list.item(i).text())
            for i in range(self.moons_list.count())
        ]

        # Save continents (simplified)
        self.planet.continents = [
            Continent(name=self.continents_list.item(i).text())
            for i in range(self.continents_list.count())
        ]

        # Save cities (simplified)
        self.planet.cities = [
            City(name=self.cities_list.item(i).text(), continent="")
            for i in range(self.cities_list.count())
        ]

        # Save climate zones (simplified)
        self.planet.climates = [
            Climate(zone_name=self.climate_list.item(i).text())
            for i in range(self.climate_list.count())
        ]


class PlanetBuilderWidget(QWidget):
    """Widget for managing all planets."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize planet builder."""
        super().__init__()
        self.planets: List[Planet] = []
        self.available_climate_presets: List = []  # List of ClimatePreset objects
        self.available_star_systems: List = []  # List of StarSystem objects
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QHBoxLayout(self)

        # Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Planet list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        label = QLabel("Planets & Stars")
        label.setStyleSheet("font-weight: 600; font-size: 13px;")
        left_layout.addWidget(label)

        self.planet_list = QListWidget()
        self.planet_list.currentItemChanged.connect(self._on_planet_selected)
        left_layout.addWidget(self.planet_list)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Add Planet")
        add_btn.clicked.connect(self._add_planet)
        btn_layout.addWidget(add_btn)

        remove_btn = QPushButton("🗑️")
        remove_btn.setMaximumWidth(40)
        remove_btn.clicked.connect(self._remove_planet)
        btn_layout.addWidget(remove_btn)

        import_btn = QPushButton("📥 Import")
        import_btn.setToolTip("Import planets from JSON file")
        import_btn.clicked.connect(self._import_planets)
        btn_layout.addWidget(import_btn)

        left_layout.addLayout(btn_layout)

        left_panel.setMaximumWidth(250)
        splitter.addWidget(left_panel)

        # Right: Planet editor
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)

        placeholder = QLabel("Add or select a planet")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor_scroll.setWidget(placeholder)

        splitter.addWidget(self.editor_scroll)

        layout.addWidget(splitter)

    def _add_planet(self):
        """Add new planet."""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Planet", "Enter planet name:")

        if ok and name:
            planet = Planet(
                id=str(uuid.uuid4()),
                name=name,
                planet_type=PlanetType.TERRESTRIAL
            )
            self.planets.append(planet)

            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, planet.id)
            self.planet_list.addItem(item)

            self.planet_list.setCurrentItem(item)

    def _remove_planet(self):
        """Remove selected planet."""
        current = self.planet_list.currentItem()
        if current:
            planet_id = current.data(Qt.ItemDataRole.UserRole)
            self.planets = [p for p in self.planets if p.id != planet_id]
            self.planet_list.takeItem(self.planet_list.row(current))

            # Show placeholder
            placeholder = QLabel("Add or select a planet")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.editor_scroll.setWidget(placeholder)

    def _on_planet_selected(self, current, previous):
        """Handle planet selection."""
        if not current:
            return

        # Save previous planet
        if previous and hasattr(self, 'current_editor') and self.current_editor:
            self.current_editor.save_to_model()

        # Load selected planet
        planet_id = current.data(Qt.ItemDataRole.UserRole)
        planet = next((p for p in self.planets if p.id == planet_id), None)

        if planet:
            self.current_editor = PlanetEditor(planet, available_climate_presets=self.available_climate_presets)
            self.current_editor.content_changed.connect(self.content_changed.emit)
            self.editor_scroll.setWidget(self.current_editor)

    def get_planets(self):
        """Get all planets."""
        if hasattr(self, 'current_editor') and self.current_editor:
            self.current_editor.save_to_model()
        return self.planets

    def _import_planets(self):
        """Import planets from JSON file."""
        from src.ui.worldbuilding.worldbuilding_importer import show_import_dialog
        from src.models.worldbuilding_objects import CompleteWorldBuilding

        temp_wb = CompleteWorldBuilding(planets=self.planets)
        result = show_import_dialog(self, temp_wb, target_section="planets")

        if result and result.imported_counts.get("planets", 0) > 0:
            self.planets = temp_wb.planets
            self.load_planets(self.planets)
            self.content_changed.emit()

    def load_planets(self, planets):
        """Load planets."""
        self.planets = planets
        self.planet_list.clear()

        for planet in planets:
            item = QListWidgetItem(planet.name)
            item.setData(Qt.ItemDataRole.UserRole, planet.id)
            self.planet_list.addItem(item)

    def set_available_climate_presets(self, presets):
        """Set available climate presets for planet climate selection.

        Args:
            presets: List of ClimatePreset objects
        """
        self.available_climate_presets = presets

        # Update current editor if it exists
        if hasattr(self, 'current_editor') and self.current_editor:
            self.current_editor.set_available_climate_presets(presets)
