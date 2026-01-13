"""Map settings and configuration dialog."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QPushButton, QLabel, QComboBox, QCheckBox, QSpinBox,
    QDialogButtonBox, QColorDialog, QLineEdit, QSlider
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from typing import Optional, List

from src.models.worldbuilding_objects import WorldMap, Planet, GridSettings


class MapSettingsDialog(QDialog):
    """Dialog for configuring map settings."""

    def __init__(self, world_map: WorldMap, available_planets: List[Planet] = None, parent=None):
        super().__init__(parent)
        self.world_map = world_map
        self.available_planets = available_planets or []
        self.setWindowTitle("Map Settings")
        self.resize(500, 600)
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Basic Settings
        basic_group = QGroupBox("Basic Settings")
        basic_layout = QFormLayout()

        self.name_edit = QLineEdit()
        basic_layout.addRow("Map Name:", self.name_edit)

        self.map_type_combo = QComboBox()
        self.map_type_combo.addItems(["World Map", "Location/Town Map"])
        self.map_type_combo.currentIndexChanged.connect(self._on_map_type_changed)
        basic_layout.addRow("Map Type:", self.map_type_combo)

        self.projection_combo = QComboBox()
        self.projection_combo.addItems(["Flat (Mercator)", "Spherical"])
        basic_layout.addRow("Projection:", self.projection_combo)

        self.planet_combo = QComboBox()
        self.planet_combo.addItem("-- No Associated Planet --", None)
        for planet in self.available_planets:
            self.planet_combo.addItem(planet.name, planet.id)
        basic_layout.addRow("Associated Planet:", self.planet_combo)

        self.scale_edit = QLineEdit()
        self.scale_edit.setPlaceholderText("e.g., 1 inch = 50 miles")
        basic_layout.addRow("Map Scale:", self.scale_edit)

        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)

        # Grid Settings
        grid_group = QGroupBox("Grid Overlay")
        grid_layout = QVBoxLayout()

        self.grid_enabled_check = QCheckBox("Show Grid")
        self.grid_enabled_check.toggled.connect(self._on_grid_toggled)
        grid_layout.addWidget(self.grid_enabled_check)

        grid_form = QFormLayout()

        self.grid_type_combo = QComboBox()
        self.grid_type_combo.addItems(["Square", "Hexagonal", "Lat/Long"])
        grid_form.addRow("Grid Type:", self.grid_type_combo)

        self.grid_size_spin = QSpinBox()
        self.grid_size_spin.setRange(10, 200)
        self.grid_size_spin.setValue(50)
        self.grid_size_spin.setSuffix(" px")
        grid_form.addRow("Cell Size:", self.grid_size_spin)

        self.grid_color_btn = QPushButton("Choose Color")
        self.grid_color_btn.clicked.connect(self._choose_grid_color)
        self.grid_color = QColor("#000000")
        self.grid_color_btn.setStyleSheet(f"background-color: {self.grid_color.name()};")
        grid_form.addRow("Grid Color:", self.grid_color_btn)

        self.grid_opacity_spin = QSpinBox()
        self.grid_opacity_spin.setRange(0, 100)
        self.grid_opacity_spin.setValue(30)
        self.grid_opacity_spin.setSuffix("%")
        grid_form.addRow("Opacity:", self.grid_opacity_spin)

        self.snap_to_grid_check = QCheckBox("Snap elements to grid")
        grid_form.addRow("", self.snap_to_grid_check)

        grid_layout.addLayout(grid_form)
        grid_group.setLayout(grid_layout)
        layout.addWidget(grid_group)

        layout.addStretch()

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_settings(self):
        """Load current map settings."""
        self.name_edit.setText(self.world_map.name)

        # Map type - load from map or default to world
        if hasattr(self.world_map, 'map_type'):
            if self.world_map.map_type == "location":
                self.map_type_combo.setCurrentIndex(1)
            else:
                self.map_type_combo.setCurrentIndex(0)
        else:
            self.map_type_combo.setCurrentIndex(0)

        # Projection - load from map or default to flat
        if hasattr(self.world_map, 'projection_mode'):
            if self.world_map.projection_mode == "sphere":
                self.projection_combo.setCurrentIndex(1)
            else:
                self.projection_combo.setCurrentIndex(0)
        else:
            self.projection_combo.setCurrentIndex(0)

        # Associated planet
        if self.world_map.planet_id:
            for i in range(self.planet_combo.count()):
                if self.planet_combo.itemData(i) == self.world_map.planet_id:
                    self.planet_combo.setCurrentIndex(i)
                    break

        # Scale
        if self.world_map.map_scale:
            self.scale_edit.setText(self.world_map.map_scale)

        # Grid settings
        if self.world_map.grid_settings:
            self.grid_enabled_check.setChecked(self.world_map.grid_settings.enabled)

            grid_type_map = {"square": 0, "hex": 1, "latlong": 2}
            idx = grid_type_map.get(self.world_map.grid_settings.grid_type, 0)
            self.grid_type_combo.setCurrentIndex(idx)

            self.grid_size_spin.setValue(self.world_map.grid_settings.cell_size)
            self.grid_color = QColor(self.world_map.grid_settings.color)
            self.grid_color_btn.setStyleSheet(f"background-color: {self.grid_color.name()};")
            self.grid_opacity_spin.setValue(int(self.world_map.grid_settings.opacity * 100))
            self.snap_to_grid_check.setChecked(self.world_map.grid_settings.snap_to_grid)

        # Trigger map type change to enable/disable relevant fields
        self._on_map_type_changed(self.map_type_combo.currentIndex())
        self._on_grid_toggled(self.grid_enabled_check.isChecked())

    def _on_grid_toggled(self, enabled: bool):
        """Enable/disable grid settings."""
        self.grid_type_combo.setEnabled(enabled)
        self.grid_size_spin.setEnabled(enabled)
        self.grid_color_btn.setEnabled(enabled)
        self.grid_opacity_spin.setEnabled(enabled)
        self.snap_to_grid_check.setEnabled(enabled)

    def _on_map_type_changed(self, index: int):
        """Handle map type change."""
        # Disable spherical projection for location maps
        if index == 1:  # Location/Town Map
            self.projection_combo.setEnabled(False)
            self.projection_combo.setCurrentIndex(0)  # Force flat
            self.planet_combo.setEnabled(False)
        else:  # World Map
            self.projection_combo.setEnabled(True)
            self.planet_combo.setEnabled(True)

    def _choose_grid_color(self):
        """Choose grid color."""
        color = QColorDialog.getColor(self.grid_color, self, "Choose Grid Color")
        if color.isValid():
            self.grid_color = color
            self.grid_color_btn.setStyleSheet(f"background-color: {color.name()};")

    def _save(self):
        """Save settings."""
        self.world_map.name = self.name_edit.text().strip()

        # Map type
        map_type_index = self.map_type_combo.currentIndex()
        self.world_map.map_type = "location" if map_type_index == 1 else "world"

        # Projection mode
        projection_index = self.projection_combo.currentIndex()
        self.world_map.projection_mode = "sphere" if projection_index == 1 else "flat"

        # Associated planet
        self.world_map.planet_id = self.planet_combo.currentData()

        # Scale
        self.world_map.map_scale = self.scale_edit.text().strip()

        # Grid settings
        grid_type_map = {0: "square", 1: "hex", 2: "latlong"}

        self.world_map.grid_settings.enabled = self.grid_enabled_check.isChecked()
        self.world_map.grid_settings.grid_type = grid_type_map[self.grid_type_combo.currentIndex()]
        self.world_map.grid_settings.cell_size = self.grid_size_spin.value()
        self.world_map.grid_settings.color = self.grid_color.name()
        self.world_map.grid_settings.opacity = self.grid_opacity_spin.value() / 100.0
        self.world_map.grid_settings.snap_to_grid = self.snap_to_grid_check.isChecked()

        self.accept()


class ShapeToolDialog(QDialog):
    """Dialog for selecting shape drawing tool."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_shape = "circle"
        self.selected_color = QColor("#FF6B6B")
        self.setWindowTitle("Shape Tool")
        self.resize(300, 250)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        label = QLabel("Select shape type to draw:")
        layout.addWidget(label)

        # Shape types
        shape_group = QGroupBox("Shape Types")
        shape_layout = QVBoxLayout()

        self.shape_combo = QComboBox()
        self.shape_combo.addItems([
            "Circle",
            "Rectangle",
            "Polygon"
        ])
        shape_layout.addWidget(self.shape_combo)

        # Color picker
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Color:"))
        self.color_btn = QPushButton("Choose Color")
        self.color_btn.clicked.connect(self._choose_color)
        self.color_btn.setStyleSheet(f"background-color: {self.selected_color.name()};")
        color_layout.addWidget(self.color_btn)
        color_layout.addStretch()
        shape_layout.addLayout(color_layout)

        shape_group.setLayout(shape_layout)
        layout.addWidget(shape_group)

        layout.addStretch()

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choose_color(self):
        """Choose custom color."""
        color = QColorDialog.getColor(self.selected_color, self, "Choose Shape Color")
        if color.isValid():
            self.selected_color = color
            self.color_btn.setStyleSheet(f"background-color: {color.name()};")

    def get_shape_info(self) -> tuple:
        """Get selected shape type and color."""
        shape_text = self.shape_combo.currentText().lower()
        return shape_text, self.selected_color


class TerrainToolDialog(QDialog):
    """Dialog for selecting terrain drawing tool."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_terrain = "mountain"
        self.selected_color = QColor("#8B4513")
        self.setWindowTitle("Terrain Tool")
        self.resize(300, 250)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        label = QLabel("Select terrain type to draw:")
        layout.addWidget(label)

        # Terrain types
        terrain_group = QGroupBox("Terrain Types")
        terrain_layout = QVBoxLayout()

        self.terrain_combo = QComboBox()
        self.terrain_combo.addItems([
            "Mountain",
            "Forest",
            "Water/River",
            "Desert",
            "Hills",
            "Swamp",
            "Custom"
        ])
        self.terrain_combo.currentTextChanged.connect(self._on_terrain_changed)
        terrain_layout.addWidget(self.terrain_combo)

        # Color picker
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Color:"))
        self.color_btn = QPushButton("Choose Color")
        self.color_btn.clicked.connect(self._choose_color)
        self.color_btn.setStyleSheet(f"background-color: {self.selected_color.name()};")
        color_layout.addWidget(self.color_btn)
        color_layout.addStretch()
        terrain_layout.addLayout(color_layout)

        terrain_group.setLayout(terrain_layout)
        layout.addWidget(terrain_group)

        layout.addStretch()

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_terrain_changed(self, terrain: str):
        """Handle terrain type change."""
        terrain_lower = terrain.lower()
        if "mountain" in terrain_lower:
            self.selected_color = QColor("#8B4513")  # Brown
        elif "forest" in terrain_lower:
            self.selected_color = QColor("#228B22")  # Forest green
        elif "water" in terrain_lower or "river" in terrain_lower:
            self.selected_color = QColor("#4169E1")  # Royal blue
        elif "desert" in terrain_lower:
            self.selected_color = QColor("#EDC9AF")  # Desert sand
        elif "hills" in terrain_lower:
            self.selected_color = QColor("#9F8170")  # Light brown
        elif "swamp" in terrain_lower:
            self.selected_color = QColor("#4A5D23")  # Dark olive green

        self.color_btn.setStyleSheet(f"background-color: {self.selected_color.name()};")
        self.selected_terrain = terrain_lower.split("/")[0]

    def _choose_color(self):
        """Choose custom color."""
        color = QColorDialog.getColor(self.selected_color, self, "Choose Terrain Color")
        if color.isValid():
            self.selected_color = color
            self.color_btn.setStyleSheet(f"background-color: {color.name()};")

    def get_terrain_info(self) -> tuple:
        """Get selected terrain type and color."""
        return self.selected_terrain, self.selected_color


class PenToolDialog(QDialog):
    """Dialog for selecting pen/brush tool settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_color = QColor("#000000")  # Default black
        self.selected_width = 3  # Default width
        self.setWindowTitle("Pen Tool")
        self.resize(300, 200)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        label = QLabel("Configure pen tool:")
        layout.addWidget(label)

        # Settings group
        settings_group = QGroupBox("Pen Settings")
        settings_layout = QVBoxLayout()

        # Color picker
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Color:"))
        self.color_btn = QPushButton("Choose Color")
        self.color_btn.clicked.connect(self._choose_color)
        self.color_btn.setStyleSheet(f"background-color: {self.selected_color.name()}; color: white;")
        color_layout.addWidget(self.color_btn)
        color_layout.addStretch()
        settings_layout.addLayout(color_layout)

        # Width slider
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("Width:"))
        self.width_slider = QSlider(Qt.Orientation.Horizontal)
        self.width_slider.setMinimum(1)
        self.width_slider.setMaximum(20)
        self.width_slider.setValue(self.selected_width)
        self.width_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.width_slider.setTickInterval(2)
        self.width_slider.valueChanged.connect(self._on_width_changed)
        width_layout.addWidget(self.width_slider)

        self.width_label = QLabel(f"{self.selected_width}px")
        self.width_label.setMinimumWidth(40)
        width_layout.addWidget(self.width_label)
        settings_layout.addLayout(width_layout)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        layout.addStretch()

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choose_color(self):
        """Choose pen color."""
        color = QColorDialog.getColor(self.selected_color, self, "Choose Pen Color")
        if color.isValid():
            self.selected_color = color
            # Make button text visible on dark backgrounds
            text_color = "white" if color.lightness() < 128 else "black"
            self.color_btn.setStyleSheet(
                f"background-color: {color.name()}; color: {text_color};"
            )

    def _on_width_changed(self, value: int):
        """Handle width slider change."""
        self.selected_width = value
        self.width_label.setText(f"{value}px")

    def get_pen_info(self) -> tuple:
        """Get selected pen color and width."""
        return self.selected_color, self.selected_width
