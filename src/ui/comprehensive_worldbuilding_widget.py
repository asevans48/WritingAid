"""Comprehensive worldbuilding widget with specialized components."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget
)
from PyQt6.QtCore import pyqtSignal

from src.ui.worldbuilding.faction_builder import FactionBuilderWidget
from src.ui.worldbuilding.timeline_builder import TimelineBuilderWidget
from src.ui.worldbuilding.military_builder import MilitaryBuilderWidget
from src.ui.worldbuilding.economy_builder import EconomyBuilderWidget
from src.ui.worldbuilding.hierarchy_builder import HierarchyBuilderWidget
from src.ui.worldbuilding.politics_builder import PoliticsBuilderWidget
from src.ui.worldbuilding.mythology_builder import MythologyBuilderWidget
from src.ui.worldbuilding.climate_preset_builder import ClimatePresetBuilderWidget
from src.ui.worldbuilding.technology_builder import TechnologyBuilderWidget
from src.ui.worldbuilding.flora_builder import FloraBuilderWidget
from src.ui.worldbuilding.fauna_builder import FaunaBuilderWidget
from src.ui.worldbuilding.enhanced_star_system_builder import EnhancedStarSystemBuilderWidget


class ComprehensiveWorldBuildingWidget(QWidget):
    """Comprehensive worldbuilding with specialized components."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize comprehensive worldbuilding widget."""
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 8)

        title = QLabel("🌍 Worldbuilding")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        subtitle = QLabel("Build your universe with interconnected systems")
        subtitle.setStyleSheet("font-size: 12px; color: #6b7280;")
        header_layout.addWidget(subtitle)

        layout.addWidget(header)

        # Tabs for different worldbuilding components
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        # Factions - Central Hub
        self.factions_widget = FactionBuilderWidget()
        self.factions_widget.content_changed.connect(self.content_changed.emit)
        self.tabs.addTab(self.factions_widget, "⚔️ Factions")

        # Star Systems - Contains stars, planets, and all astronomical data
        self.star_systems_widget = EnhancedStarSystemBuilderWidget()
        self.star_systems_widget.content_changed.connect(self.content_changed.emit)
        self.tabs.addTab(self.star_systems_widget, "⭐ Systems")

        # History Timeline
        self.history_widget = TimelineBuilderWidget()
        self.history_widget.content_changed.connect(self.content_changed.emit)
        self.tabs.addTab(self.history_widget, "📅 History")

        # Military
        self.military_widget = MilitaryBuilderWidget()
        self.military_widget.content_changed.connect(self.content_changed.emit)
        self.tabs.addTab(self.military_widget, "🪖 Military")

        # Economy
        self.economy_widget = EconomyBuilderWidget()
        self.economy_widget.content_changed.connect(self.content_changed.emit)
        self.tabs.addTab(self.economy_widget, "💰 Economy")

        # Power Hierarchies
        self.hierarchy_widget = HierarchyBuilderWidget()
        self.hierarchy_widget.content_changed.connect(self.content_changed.emit)
        self.tabs.addTab(self.hierarchy_widget, "👑 Hierarchies")

        # Politics
        self.politics_widget = PoliticsBuilderWidget()
        self.politics_widget.content_changed.connect(self.content_changed.emit)
        self.tabs.addTab(self.politics_widget, "🏛️ Politics")

        # Mythology - Enhanced with faction associations
        self.mythology_widget = MythologyBuilderWidget()
        self.mythology_widget.content_changed.connect(self.content_changed.emit)
        self.tabs.addTab(self.mythology_widget, "📖 Mythology")

        # Technology - Track important technologies and which factions have them
        self.technology_widget = TechnologyBuilderWidget()
        self.technology_widget.content_changed.connect(self.content_changed.emit)
        self.tabs.addTab(self.technology_widget, "🔬 Technology")

        # Climate Presets - Reusable climate templates
        self.climate_preset_widget = ClimatePresetBuilderWidget()
        self.climate_preset_widget.content_changed.connect(self.content_changed.emit)
        self.tabs.addTab(self.climate_preset_widget, "🌤️ Climate Presets")

        # Flora - Plant species and vegetation
        self.flora_widget = FloraBuilderWidget()
        self.flora_widget.content_changed.connect(self.content_changed.emit)
        self.tabs.addTab(self.flora_widget, "🌿 Flora")

        # Fauna - Animal species and creatures
        self.fauna_widget = FaunaBuilderWidget()
        self.fauna_widget.content_changed.connect(self.content_changed.emit)
        self.tabs.addTab(self.fauna_widget, "🦁 Fauna")

        layout.addWidget(self.tabs)

        # Connect faction changes to update other widgets
        self.factions_widget.content_changed.connect(self._update_mythology_factions)
        self.factions_widget.content_changed.connect(self._update_technology_factions)

        # Connect flora/fauna/climate changes to update star systems
        self.flora_widget.content_changed.connect(self._update_star_system_flora)
        self.fauna_widget.content_changed.connect(self._update_star_system_fauna)
        self.climate_preset_widget.content_changed.connect(self._update_star_system_climates)

    def _update_mythology_factions(self):
        """Update available factions in mythology widget."""
        factions = self.factions_widget.get_factions()
        self.mythology_widget.set_available_factions(factions)

    def _update_technology_factions(self):
        """Update available factions in technology widget."""
        factions = self.factions_widget.get_factions()
        self.technology_widget.set_available_factions(factions)

    def _update_star_system_flora(self):
        """Update available flora in star system widget."""
        flora = self.flora_widget.get_flora()
        if hasattr(self.star_systems_widget, 'set_available_flora'):
            self.star_systems_widget.set_available_flora(flora)

    def _update_star_system_fauna(self):
        """Update available fauna in star system widget."""
        fauna = self.fauna_widget.get_fauna()
        if hasattr(self.star_systems_widget, 'set_available_fauna'):
            self.star_systems_widget.set_available_fauna(fauna)

    def _update_star_system_climates(self):
        """Update available climate presets in star system widget."""
        presets = self.climate_preset_widget.get_presets()
        if hasattr(self.star_systems_widget, 'set_available_climate_presets'):
            self.star_systems_widget.set_available_climate_presets(presets)

    def load_data(self, worldbuilding):
        """Load worldbuilding data."""
        # Load factions first (needed by other widgets)
        if hasattr(worldbuilding, 'factions'):
            self.factions_widget.load_factions(worldbuilding.factions)
            self._update_mythology_factions()
            self._update_technology_factions()

        # Load climate presets
        if hasattr(worldbuilding, 'climate_presets'):
            self.climate_preset_widget.load_presets(worldbuilding.climate_presets)
            self._update_star_system_climates()

        # Load mythology
        if hasattr(worldbuilding, 'myths'):
            self.mythology_widget.load_myths(worldbuilding.myths)

        # Load technology
        if hasattr(worldbuilding, 'technologies'):
            self.technology_widget.load_technologies(worldbuilding.technologies)

        # Load flora
        if hasattr(worldbuilding, 'flora'):
            self.flora_widget.load_flora(worldbuilding.flora)
            self._update_star_system_flora()

        # Load fauna
        if hasattr(worldbuilding, 'fauna'):
            self.fauna_widget.load_fauna(worldbuilding.fauna)
            self._update_star_system_fauna()

        # Load star systems (contains all astronomical data)
        if hasattr(worldbuilding, 'star_systems'):
            self.star_systems_widget.load_star_systems(worldbuilding.star_systems)

    def get_data(self):
        """Get worldbuilding data."""
        from src.models.project import WorldBuilding

        # Return worldbuilding data structure
        worldbuilding = WorldBuilding(
            factions=self.factions_widget.get_factions(),
            myths=self.mythology_widget.get_myths(),
            technologies=self.technology_widget.get_technologies(),
            climate_presets=self.climate_preset_widget.get_presets(),
            flora=self.flora_widget.get_flora(),
            fauna=self.fauna_widget.get_fauna(),
            stars=[],  # Stars are now embedded in star_systems
            star_systems=self.star_systems_widget.get_star_systems(),
            mythology_elements={},  # Deprecated - kept for backwards compatibility
            planets_elements={},  # Deprecated - planets now embedded in star_systems
            climate_elements={},  # Deprecated - climate now managed via presets
            history_elements={},  # TODO: Convert events to dict
            politics_elements={},  # TODO: Convert systems to dict
            military_elements={},  # TODO: Convert armies to dict
            economy_elements={},  # TODO: Convert economies to dict
            power_hierarchy_elements={}  # TODO: Convert hierarchies to dict
        )

        return worldbuilding
