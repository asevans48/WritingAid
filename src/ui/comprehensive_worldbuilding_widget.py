"""Comprehensive worldbuilding widget with specialized components."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QMessageBox, QComboBox, QStackedWidget
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread

from src.ui.worldbuilding.faction_builder import FactionBuilderWidget
from src.ui.worldbuilding.timeline_builder import TimelineBuilderWidget
from src.ui.worldbuilding.military_builder import MilitaryBuilderWidget
from src.ui.worldbuilding.economy_builder import EconomyBuilderWidget
from src.ui.worldbuilding.hierarchy_builder import HierarchyBuilderWidget
from src.ui.worldbuilding.politics_builder import PoliticsBuilderWidget
from src.ui.worldbuilding.government_builder import GovernmentBuilderWidget
from src.ui.worldbuilding.justice_builder import JusticeBuilderWidget
from src.ui.worldbuilding.services_builder import ServicesBuilderWidget
from src.ui.worldbuilding.mythology_builder import MythologyBuilderWidget
from src.ui.worldbuilding.climate_preset_builder import ClimatePresetBuilderWidget
from src.ui.worldbuilding.technology_builder import TechnologyBuilderWidget
from src.ui.worldbuilding.flora_builder import FloraBuilderWidget
from src.ui.worldbuilding.fauna_builder import FaunaBuilderWidget
from src.ui.worldbuilding.enhanced_star_system_builder import EnhancedStarSystemBuilderWidget
from src.ui.worldbuilding.culture_builder import CultureBuilderWidget
from src.ui.worldbuilding.place_builder import PlaceBuilderWidget
from src.ui.worldbuilding.map_builder_widgets import MapBuilderWidget
from src.ui.worldbuilding.magic_system_builder import MagicSystemBuilderWidget
from src.ui.worldbuilding.encyclopedia_widget import EncyclopediaWidget


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

        self.strengthen_btn = QPushButton("🤖 Strengthen World")
        self.strengthen_btn.setToolTip(
            "AI analyzes your manuscript and worldbuilding to find:\n"
            "• Duplicate/similar elements to merge\n"
            "• Thin entries to enrich from the story text\n"
            "• Gaps and inconsistencies to fill\n"
            "Uses the encyclopedia and RAG for reference."
        )
        self.strengthen_btn.setStyleSheet(
            "font-size: 12px; padding: 4px 12px; font-weight: bold;"
        )
        self.strengthen_btn.clicked.connect(self._strengthen_worldbuilding)
        header_layout.addWidget(self.strengthen_btn)

        subtitle = QLabel("Build your universe with interconnected systems")
        subtitle.setStyleSheet("font-size: 12px; color: #6b7280;")
        header_layout.addWidget(subtitle)

        layout.addWidget(header)

        # Section selector (dropdown) + stacked widget
        selector_row = QHBoxLayout()
        selector_row.setContentsMargins(16, 0, 16, 4)

        selector_label = QLabel("Section:")
        selector_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        selector_row.addWidget(selector_label)

        self.section_combo = QComboBox()
        self.section_combo.setStyleSheet("font-size: 12px; padding: 4px 8px; min-width: 200px;")
        selector_row.addWidget(self.section_combo, stretch=1)
        selector_row.addStretch()

        layout.addLayout(selector_row)

        self.stack = QStackedWidget()

        # Define all sections: (display_name, widget_attr, widget_class)
        sections = [
            ("Factions", "factions_widget", FactionBuilderWidget),
            ("Star Systems", "star_systems_widget", EnhancedStarSystemBuilderWidget),
            ("History & Timeline", "history_widget", TimelineBuilderWidget),
            ("Military", "military_widget", MilitaryBuilderWidget),
            ("Economy", "economy_widget", EconomyBuilderWidget),
            ("Power Hierarchies", "hierarchy_widget", HierarchyBuilderWidget),
            ("Politics", "politics_widget", PoliticsBuilderWidget),
            ("Government", "government_widget", GovernmentBuilderWidget),
            ("Justice", "justice_widget", JusticeBuilderWidget),
            ("Services", "services_widget", ServicesBuilderWidget),
            ("Mythology", "mythology_widget", MythologyBuilderWidget),
            ("Technology", "technology_widget", TechnologyBuilderWidget),
            ("Magic Systems", "magic_system_widget", MagicSystemBuilderWidget),
            ("Climate Presets", "climate_preset_widget", ClimatePresetBuilderWidget),
            ("Flora", "flora_widget", FloraBuilderWidget),
            ("Fauna", "fauna_widget", FaunaBuilderWidget),
            ("Culture", "culture_widget", CultureBuilderWidget),
            ("Places & Landmarks", "places_widget", PlaceBuilderWidget),
            ("Maps", "maps_widget", MapBuilderWidget),
            ("Encyclopedia", "encyclopedia_widget", EncyclopediaWidget),
        ]

        for display_name, attr_name, widget_class in sections:
            widget = widget_class()
            widget.content_changed.connect(self.content_changed.emit)
            setattr(self, attr_name, widget)
            self.stack.addWidget(widget)
            self.section_combo.addItem(display_name)

        self.section_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)

        layout.addWidget(self.stack, stretch=1)

        # Connect faction changes to update other widgets
        self.factions_widget.content_changed.connect(self._update_mythology_factions)
        self.factions_widget.content_changed.connect(self._update_technology_factions)
        self.factions_widget.content_changed.connect(self._update_culture_factions)
        self.factions_widget.content_changed.connect(self._update_military_factions)
        self.factions_widget.content_changed.connect(self._update_economy_factions)
        self.factions_widget.content_changed.connect(self._update_places_factions)
        self.factions_widget.content_changed.connect(self._update_maps_factions)
        self.factions_widget.content_changed.connect(self._update_magic_system_factions)
        self.factions_widget.content_changed.connect(self._update_politics_factions)
        self.factions_widget.content_changed.connect(self._update_government_factions)
        self.factions_widget.content_changed.connect(self._update_justice_factions)
        self.factions_widget.content_changed.connect(self._update_services_factions)

        # Connect flora/fauna/climate changes to update star systems
        self.flora_widget.content_changed.connect(self._update_star_system_flora)
        self.fauna_widget.content_changed.connect(self._update_star_system_fauna)
        self.climate_preset_widget.content_changed.connect(self._update_star_system_climates)

        # Connect star system changes to update culture and flora/fauna planets
        self.star_systems_widget.content_changed.connect(self._update_culture_planets)
        self.star_systems_widget.content_changed.connect(self._update_flora_planets)
        self.star_systems_widget.content_changed.connect(self._update_fauna_planets)
        self.star_systems_widget.content_changed.connect(self._update_places_planets)
        self.star_systems_widget.content_changed.connect(self._update_maps_planets)

    def _update_mythology_factions(self):
        """Update available factions in mythology widget."""
        factions = self.factions_widget.get_factions()
        faction_ids = {f.id for f in factions}

        # Clean up references to deleted factions in myths
        for myth in self.mythology_widget.get_myths():
            myth.associated_factions = [
                fid for fid in myth.associated_factions if fid in faction_ids
            ]

        self.mythology_widget.set_available_factions(factions)
        # Refresh the mythology list to show updated faction associations
        self.mythology_widget._update_list()

    def _update_technology_factions(self):
        """Update available factions in technology widget."""
        factions = self.factions_widget.get_factions()
        faction_ids = {f.id for f in factions}

        # Clean up references to deleted factions in technologies
        for tech in self.technology_widget.get_technologies():
            tech.factions_with_access = [
                fid for fid in tech.factions_with_access if fid in faction_ids
            ]
            # Also clean up inventor faction if deleted
            if tech.inventor_faction and tech.inventor_faction not in faction_ids:
                tech.inventor_faction = None

        self.technology_widget.set_available_factions(factions)
        # Refresh the technology list to show updated faction associations
        if hasattr(self.technology_widget, '_update_list'):
            self.technology_widget._update_list()

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

    def _update_culture_factions(self):
        """Update available factions in culture widget."""
        factions = self.factions_widget.get_factions()
        self.culture_widget.set_available_factions(factions)

    def _update_politics_factions(self):
        """Update available factions in politics widget."""
        factions = self.factions_widget.get_factions()
        if hasattr(self.politics_widget, 'set_available_factions'):
            self.politics_widget.set_available_factions(factions)

    def _update_government_factions(self):
        """Update available factions in government widget."""
        self.government_widget.set_available_factions(
            self.factions_widget.get_factions())

    def _update_justice_factions(self):
        """Update available factions in justice widget."""
        self.justice_widget.set_available_factions(
            self.factions_widget.get_factions())

    def _update_services_factions(self):
        """Update available factions in services widget."""
        self.services_widget.set_available_factions(
            self.factions_widget.get_factions())

    def _update_military_factions(self):
        """Update available factions in military widget."""
        factions = self.factions_widget.get_factions()
        self.military_widget.set_available_factions(factions)

    def _update_economy_factions(self):
        """Update available factions in economy widget."""
        factions = self.factions_widget.get_factions()
        self.economy_widget.set_available_factions(factions)

    def _update_places_factions(self):
        """Update available factions in places widget."""
        factions = self.factions_widget.get_factions()
        self.places_widget.set_available_factions(factions)

    def _update_culture_planets(self):
        """Update available planets in culture widget."""
        planet_names = self._get_all_planet_names()
        self.culture_widget.set_available_planets(planet_names)

    def _update_flora_planets(self):
        """Update available planets in flora widget."""
        planet_names = self._get_all_planet_names()
        self.flora_widget.set_available_planets(planet_names)

    def _update_fauna_planets(self):
        """Update available planets in fauna widget."""
        planet_names = self._get_all_planet_names()
        self.fauna_widget.set_available_planets(planet_names)

    def _update_places_planets(self):
        """Update available planets in places widget."""
        planet_names = self._get_all_planet_names()
        self.places_widget.set_available_planets(planet_names)

    def _update_maps_factions(self):
        """Update available factions in maps widget."""
        factions = self.factions_widget.get_factions()
        self.maps_widget.set_available_factions(factions)

    def _update_maps_planets(self):
        """Update available planets in maps widget."""
        # Get actual Planet objects, not just names
        planets = []
        star_systems = self.star_systems_widget.get_star_systems()
        for system in star_systems:
            planets.extend(system.planets)
        self.maps_widget.set_available_planets(planets)

    def _update_magic_system_factions(self):
        """Update available factions in magic system widget."""
        factions = self.factions_widget.get_factions()
        faction_ids = {f.id for f in factions}

        # Clean up references to deleted factions
        for ms in self.magic_system_widget.get_magic_systems():
            ms.associated_factions = [
                fid for fid in ms.associated_factions if fid in faction_ids
            ]

        self.magic_system_widget.set_available_factions(factions)
        if hasattr(self.magic_system_widget, '_update_list'):
            self.magic_system_widget._update_list()

    def _get_all_planet_names(self) -> list:
        """Get all planet names from star systems."""
        planet_names = []
        star_systems = self.star_systems_widget.get_star_systems()
        for system in star_systems:
            for planet in system.planets:
                planet_names.append(planet.name)
        return planet_names

    def load_data(self, worldbuilding):
        """Load worldbuilding data."""
        # Load factions first (needed by other widgets)
        if hasattr(worldbuilding, 'factions'):
            self.factions_widget.load_factions(worldbuilding.factions)
            self._update_mythology_factions()
            self._update_technology_factions()
            self._update_military_factions()
            self._update_economy_factions()
            self._update_places_factions()
            self._update_culture_factions()
            self._update_maps_factions()
            self._update_magic_system_factions()

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

        # Load magic systems
        if hasattr(worldbuilding, 'magic_systems'):
            self.magic_system_widget.load_magic_systems(worldbuilding.magic_systems)

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
            # Update planets for culture, flora, fauna, and maps
            self._update_culture_planets()
            self._update_flora_planets()
            self._update_fauna_planets()
            self._update_maps_planets()

        # Load economies
        if hasattr(worldbuilding, 'economies'):
            self.economy_widget.load_economies(worldbuilding.economies)

        # Load cultures
        if hasattr(worldbuilding, 'cultures'):
            self.culture_widget.load_cultures(worldbuilding.cultures)

        # Load armies (military forces)
        if hasattr(worldbuilding, 'armies'):
            self.military_widget.load_armies(worldbuilding.armies)

        # Load places (landmarks and points of interest)
        if hasattr(worldbuilding, 'places'):
            self.places_widget.load_places(worldbuilding.places)
            self._update_places_planets()

        # Load maps (backward compatibility - default to empty list if not present)
        if hasattr(worldbuilding, 'maps') and worldbuilding.maps is not None:
            self.maps_widget.load_maps(worldbuilding.maps)
        else:
            self.maps_widget.load_maps([])

        # Load historical events (timeline)
        if hasattr(worldbuilding, 'historical_events'):
            self.history_widget.load_events(worldbuilding.historical_events)

        # Load power hierarchies
        if hasattr(worldbuilding, 'hierarchies'):
            self.hierarchy_widget.load_hierarchies(worldbuilding.hierarchies)

        # Load political systems (with available factions for the picker)
        if hasattr(worldbuilding, 'political_systems'):
            self._update_politics_factions()
            self.politics_widget.load_political_systems(worldbuilding.political_systems)

        # Load government / justice / service systems (faction-linked)
        if hasattr(worldbuilding, 'government_systems'):
            self._update_government_factions()
            self.government_widget.load_government_systems(
                worldbuilding.government_systems)
        if hasattr(worldbuilding, 'justice_systems'):
            self._update_justice_factions()
            self.justice_widget.load_justice_systems(
                worldbuilding.justice_systems)
        if hasattr(worldbuilding, 'service_systems'):
            self._update_services_factions()
            self.services_widget.load_service_systems(
                worldbuilding.service_systems)

        # Load encyclopedia custom entries
        if hasattr(worldbuilding, 'custom_encyclopedia'):
            self.encyclopedia_widget.load_custom_entries(worldbuilding.custom_encyclopedia)

    def get_data(self):
        """Get worldbuilding data."""
        from src.models.project import WorldBuilding

        # Return worldbuilding data structure
        worldbuilding = WorldBuilding(
            factions=self.factions_widget.get_factions(),
            myths=self.mythology_widget.get_myths(),
            technologies=self.technology_widget.get_technologies(),
            magic_systems=self.magic_system_widget.get_magic_systems(),
            climate_presets=self.climate_preset_widget.get_presets(),
            flora=self.flora_widget.get_flora(),
            fauna=self.fauna_widget.get_fauna(),
            stars=[],  # Stars are now embedded in star_systems
            star_systems=self.star_systems_widget.get_star_systems(),
            cultures=self.culture_widget.get_cultures(),
            armies=self.military_widget.get_armies(),  # Military forces
            economies=self.economy_widget.get_economies(),  # Economic systems
            places=self.places_widget.get_places(),  # Places and landmarks
            maps=self.maps_widget.get_maps(),  # Interactive maps
            historical_events=self.history_widget.get_events(),  # Timeline events
            hierarchies=self.hierarchy_widget.get_hierarchies(),  # Power hierarchies
            political_systems=self.politics_widget.get_political_systems(),  # Political systems
            government_systems=self.government_widget.get_government_systems(),  # Systems of government
            justice_systems=self.justice_widget.get_justice_systems(),  # Systems of justice
            service_systems=self.services_widget.get_service_systems(),  # Public / civic services
            mythology_elements={},  # Deprecated - kept for backwards compatibility
            planets_elements={},  # Deprecated - planets now embedded in star_systems
            climate_elements={},  # Deprecated - climate now managed via presets
            history_elements={},  # Deprecated - now using historical_events list
            politics_elements={},  # TODO: Convert systems to dict
            military_elements={},  # TODO: Convert armies to dict
            economy_elements={},  # TODO: Convert economies to dict
            power_hierarchy_elements={},  # TODO: Convert hierarchies to dict
            custom_encyclopedia=self.encyclopedia_widget.get_custom_entries()
        )

        return worldbuilding

    # --- Strengthen Worldbuilding ---

    def set_project(self, project):
        """Set the project reference (needed for strengthen feature)."""
        self._project = project

    def _strengthen_worldbuilding(self):
        """Run AI analysis to merge duplicates, enrich thin entries, and fill gaps."""
        project = getattr(self, '_project', None)
        if not project:
            QMessageBox.information(
                self, "No Project",
                "Open a project first so the AI can analyze your manuscript and worldbuilding."
            )
            return

        reply = QMessageBox.question(
            self, "Strengthen Worldbuilding",
            "The AI will analyze your manuscript and worldbuilding to:\n\n"
            "• Merge duplicate/similar elements\n"
            "• Enrich thin entries using details from your chapters\n"
            "• Fill gaps using the encyclopedia and RAG\n\n"
            "This may take a minute. Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.strengthen_btn.setEnabled(False)
        self.strengthen_btn.setText("🤖 Analyzing...")

        self._strengthen_worker = _StrengthenWorker(project)
        self._strengthen_worker.finished.connect(self._on_strengthen_complete)
        self._strengthen_worker.error.connect(self._on_strengthen_error)
        self._strengthen_worker.start()

    def _on_strengthen_complete(self, report: str, merges: int, enrichments: int):
        """Handle strengthen completion."""
        self.strengthen_btn.setEnabled(True)
        self.strengthen_btn.setText("🤖 Strengthen World")

        if merges > 0 or enrichments > 0:
            # Reload data to reflect changes
            if hasattr(self, '_project') and self._project:
                self.load_data(self._project.worldbuilding)
            self.content_changed.emit()

        QMessageBox.information(
            self, "Worldbuilding Strengthened",
            f"Analysis complete:\n\n"
            f"• {merges} duplicate(s) merged\n"
            f"• {enrichments} element(s) enriched\n\n"
            f"{report}"
        )

    def _on_strengthen_error(self, error_msg: str):
        """Handle strengthen error."""
        self.strengthen_btn.setEnabled(True)
        self.strengthen_btn.setText("🤖 Strengthen World")
        QMessageBox.warning(self, "Error", f"Strengthen failed:\n\n{error_msg}")


class _StrengthenWorker(QThread):
    """Background worker that analyzes and strengthens worldbuilding.

    Phase 1: Merge duplicates across all element types (including characters)
    Phase 2: Index proper nouns from manuscript text and cross-reference
    Phase 3: Enrich ALL elements with thin fields from manuscript mentions
    Phase 4: Use RAG (encyclopedia + knowledge store) to fill remaining gaps
    """

    finished = pyqtSignal(str, int, int)  # report, merges, enrichments
    error = pyqtSignal(str)

    def __init__(self, project):
        super().__init__()
        self.project = project

    def run(self):
        try:
            from src.utils.fuzzy_match import find_similar, _normalize
            import re

            report_lines = []
            merges = 0
            enrichments = 0

            wb = self.project.worldbuilding

            # All element lists including characters
            element_lists = {
                "characters": self.project.characters,
                "factions": getattr(wb, 'factions', []) or [],
                "places": getattr(wb, 'places', []) or [],
                "cultures": getattr(wb, 'cultures', []) or [],
                "technologies": getattr(wb, 'technologies', []) or [],
                "myths": getattr(wb, 'myths', []) or [],
                "magic_systems": getattr(wb, 'magic_systems', []) or [],
                "flora": getattr(wb, 'flora', []) or [],
                "fauna": getattr(wb, 'fauna', []) or [],
            }

            # --- Phase 1: Find and merge duplicates ---
            for category, elements in element_lists.items():
                if not elements or len(elements) < 2:
                    continue

                seen = {}
                to_remove = []

                for elem in elements:
                    name = getattr(elem, 'name', '')
                    if not name:
                        continue
                    norm = _normalize(name)

                    if norm in seen:
                        original = seen[norm]
                        merged_fields = self._merge_element(original, elem)
                        report_lines.append(
                            f"Merged {category}: '{name}' → '{original.name}'"
                            + (f" ({', '.join(merged_fields)})" if merged_fields else "")
                        )
                        to_remove.append(elem)
                        merges += 1
                    else:
                        match_name = find_similar(
                            name, [s.name for s in seen.values()], threshold=0.8
                        )
                        if match_name:
                            norm_match = _normalize(match_name)
                            original = seen.get(norm_match)
                            if original:
                                merged_fields = self._merge_element(original, elem)
                                report_lines.append(
                                    f"Merged {category}: '{name}' ≈ '{original.name}'"
                                    + (f" ({', '.join(merged_fields)})" if merged_fields else "")
                                )
                                to_remove.append(elem)
                                merges += 1
                                continue
                        seen[norm] = elem

                for elem in to_remove:
                    if elem in elements:
                        elements.remove(elem)

            # --- Phase 2: Load and index manuscript text ---
            chapter_texts = self._get_chapter_texts()
            if not chapter_texts:
                report_lines.append("(no chapter content found — skipping manuscript enrichment)")

            all_text = "\n\n".join(chapter_texts.values())

            # Build a name index: element_name -> list of (chapter_title, sentences)
            name_index = {}
            all_names = []
            for category, elements in element_lists.items():
                for elem in elements:
                    name = getattr(elem, 'name', '')
                    if name and len(name) > 2:
                        all_names.append((name, category, elem))

            for name, category, elem in all_names:
                mentions = []
                for ch_title, ch_text in chapter_texts.items():
                    sents = self._find_sentences(name, ch_text)
                    if sents:
                        mentions.append((ch_title, sents))
                if mentions:
                    name_index[name] = (category, elem, mentions)

            # --- Phase 2b: Discover untracked proper nouns in manuscript ---
            if all_text:
                untracked = self._discover_untracked_nouns(all_text, all_names)
                if untracked:
                    report_lines.append(
                        f"Potential untracked elements in manuscript: "
                        f"{', '.join(n for n, _ in untracked[:10])}"
                    )

            # --- Phase 2c: Find correlated concepts near existing elements ---
            # For each element, look at surrounding sentences for related terms
            # that aren't tracked but describe aspects of the element
            # (e.g., "cybernetics" → "implants", "targeting eyes", "subdermals")
            if all_text and name_index:
                correlations = self._find_correlated_concepts(name_index, all_text)
                for elem_name, related_terms in correlations.items():
                    category, elem, _ = name_index[elem_name]
                    # Add correlated terms to the element's notes
                    notes = getattr(elem, 'notes', '') or ''
                    terms_str = ", ".join(related_terms)
                    addition = f"Related concepts from manuscript: {terms_str}"
                    if addition not in notes:
                        try:
                            if notes:
                                setattr(elem, 'notes', f"{notes}\n\n{addition}")
                            else:
                                setattr(elem, 'notes', addition)
                            report_lines.append(
                                f"Correlated {category}: '{elem_name}' "
                                f"← {terms_str}"
                            )
                            enrichments += 1
                        except (AttributeError, TypeError, ValueError):
                            pass

            # --- Phase 3: Enrich ALL thin fields from manuscript ---
            enrichable_fields = {
                "characters": ["personality", "backstory", "physical_description",
                               "speaking_style", "motivations"],
                "factions": ["description", "notes"],
                "places": ["description", "atmosphere", "cultural_significance"],
                "cultures": ["description", "social_structure"],
                "technologies": ["description", "limitations"],
                "myths": ["description"],
                "magic_systems": ["description", "rules", "limitations"],
                "flora": ["description"],
                "fauna": ["description", "behavior"],
            }

            from src.ai.field_synthesizer import synthesize_field, get_llm_client
            llm = get_llm_client()

            for name, (category, elem, mentions) in name_index.items():
                all_sents = []
                for ch_title, sents in mentions:
                    for s in sents:
                        all_sents.append(f"[{ch_title}] {s}")
                evidence = " ... ".join(all_sents[:5])[:800]

                fields_to_check = enrichable_fields.get(category, ["description"])
                for field in fields_to_check:
                    if not hasattr(elem, field):
                        continue
                    current = getattr(elem, field, '') or ''
                    if len(current) > 200:
                        continue

                    synthesized = synthesize_field(
                        element_name=name,
                        element_type=category.rstrip('s'),
                        field_name=field,
                        manuscript_evidence=evidence,
                        existing_content=current,
                        llm_client=llm
                    )

                    if synthesized and synthesized != current:
                        try:
                            setattr(elem, field, synthesized)
                            report_lines.append(
                                f"Enriched {category}: '{name}'.{field} "
                                f"({len(mentions)} chapter mentions)"
                            )
                            enrichments += 1
                        except (AttributeError, TypeError, ValueError):
                            pass

            # --- Phase 4: RAG / encyclopedia / knowledge store ---
            try:
                from src.config.ai_config import get_ai_config
                kb_enabled = get_ai_config().get_settings().get(
                    "enable_knowledge_base", True
                )
            except Exception:
                kb_enabled = True

            try:
                from src.ai.enhanced_rag import EnhancedRAGSystem
                from src.ai.semantic_search import SearchMethod

                rag = EnhancedRAGSystem(project=self.project)
                rag.rebuild_index()

                # Map each element type to its primary text field
                primary_field = {
                    "characters": "backstory",
                    "factions": "description",
                    "places": "description",
                    "cultures": "description",
                    "technologies": "description",
                    "myths": "description",
                    "magic_systems": "description",
                    "flora": "description",
                    "fauna": "description",
                }

                for category, elements in element_lists.items():
                    field = primary_field.get(category, "description")
                    for elem in elements:
                        name = getattr(elem, 'name', '')
                        current = getattr(elem, field, None)

                        if not hasattr(elem, field) or not name:
                            continue
                        # Skip if already has encyclopedia reference
                        if current and "Reference:" in str(current):
                            continue

                        query = f"{category.rstrip('s')} {name}"
                        context = rag.get_context_for_ai(
                            query, max_tokens=600, method=SearchMethod.HYBRID
                        )
                        if not context:
                            continue

                        useful_lines = []
                        for line in context.split('\n'):
                            line = line.strip()
                            if not line or line.startswith('RELEVANT') or line == '---':
                                continue
                            if line.startswith('[') and ']' in line:
                                continue
                            useful_lines.append(line)

                        if useful_lines:
                            enc_ref = " ".join(useful_lines[:3])[:400]
                            # Get manuscript evidence if any
                            ms_evidence = ""
                            if name in name_index:
                                _, _, ms_mentions = name_index[name]
                                ms_sents = []
                                for ct, ss in ms_mentions:
                                    for s in ss:
                                        ms_sents.append(f"[{ct}] {s}")
                                ms_evidence = " ... ".join(ms_sents[:3])[:400]

                            synthesized = synthesize_field(
                                element_name=name,
                                element_type=category.rstrip('s'),
                                field_name=field,
                                manuscript_evidence=ms_evidence,
                                encyclopedia_reference=enc_ref,
                                existing_content=current or '',
                                llm_client=llm
                            )

                            if synthesized and synthesized != (current or ''):
                                try:
                                    setattr(elem, field, synthesized)
                                    source_label = "manuscript + encyclopedia" if ms_evidence else "encyclopedia"
                                    report_lines.append(
                                        f"Enriched {category}: '{name}'.{field} from {source_label}"
                                    )
                                    enrichments += 1
                                except (AttributeError, TypeError, ValueError):
                                    pass

            except Exception as e:
                report_lines.append(f"(RAG enrichment skipped: {e})")

            if not report_lines:
                report = "No changes needed — worldbuilding looks solid."
            else:
                report = "\n".join(report_lines)

            self.finished.emit(report, merges, enrichments)

        except Exception as e:
            self.error.emit(str(e))

    def _merge_element(self, target, source) -> list:
        """Merge non-empty fields from source into target (fill gaps only)."""
        merged = []
        for field in vars(source):
            if field.startswith('_') or field in ('id', 'name', 'created_at', 'updated_at'):
                continue
            src_val = getattr(source, field, None)
            tgt_val = getattr(target, field, None)

            if src_val and (tgt_val is None or tgt_val == "" or tgt_val == [] or tgt_val == 0):
                try:
                    setattr(target, field, src_val)
                    merged.append(field)
                except (AttributeError, TypeError):
                    pass
        return merged

    def _get_chapter_texts(self) -> dict:
        """Get chapter texts indexed by title.

        Loads content from disk if not already in memory.
        """
        if not hasattr(self.project, 'manuscript'):
            return {}

        from pathlib import Path
        project_dir = None
        if hasattr(self.project, 'project_path') and self.project.project_path:
            project_dir = Path(self.project.project_path).parent

        result = {}
        for ch in self.project.manuscript.chapters:
            content = getattr(ch, 'content', '')

            # If content is empty, try loading from disk
            if not content and project_dir:
                try:
                    ch.load_content_from_file(project_dir)
                    content = getattr(ch, 'content', '')
                except Exception:
                    pass

            if content:
                title = getattr(ch, 'title', f"Chapter {getattr(ch, 'number', '?')}")
                result[title] = content
        return result

    def _find_sentences(self, name: str, text: str) -> list:
        """Find sentences mentioning the name."""
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)
        matches = []
        name_lower = name.lower()
        for sentence in sentences:
            if name_lower in sentence.lower() and 20 < len(sentence.strip()) < 500:
                matches.append(sentence.strip())
                if len(matches) >= 3:
                    break
        return matches

    def _discover_untracked_nouns(self, text: str, known_names: list) -> list:
        """Find capitalized phrases in the manuscript that aren't tracked elements.

        Returns list of (name, count) tuples for potential new worldbuilding entries.
        """
        import re
        from src.utils.fuzzy_match import find_similar

        # Extract capitalized phrases (2-4 words, likely proper nouns)
        # Pattern: two or more capitalized words in sequence
        pattern = r'\b([A-Z][a-z]+(?:\s+(?:of|the|and|de|von|van)\s+)?(?:[A-Z][a-z]+\s*){1,3})\b'
        found = re.findall(pattern, text)

        # Count occurrences
        from collections import Counter
        counts = Counter(found)

        # Filter: must appear 2+ times, not be a known element
        known_set = {n.lower() for n, _, _ in known_names}
        # Also exclude common English phrases that get capitalized at sentence starts
        common_skip = {
            "the", "and", "but", "she", "her", "his", "they", "them",
            "this", "that", "what", "when", "where", "how", "who",
            "was", "were", "had", "have", "been", "could", "would",
        }

        untracked = []
        for phrase, count in counts.most_common(30):
            phrase_clean = phrase.strip()
            if count < 2:
                continue
            if phrase_clean.lower() in known_set:
                continue
            if any(w.lower() in common_skip for w in phrase_clean.split()):
                continue
            if len(phrase_clean) < 4:
                continue
            # Check fuzzy match against known names
            if find_similar(phrase_clean, [n for n, _, _ in known_names], threshold=0.7):
                continue
            untracked.append((phrase_clean, count))

        return untracked[:15]

    def _find_correlated_concepts(self, name_index: dict, all_text: str) -> dict:
        """Find terms that co-occur with existing elements in nearby sentences.

        For each element, looks at the sentences where it's mentioned and
        extracts notable nouns/phrases that appear in those same sentences
        or adjacent ones. These are likely related concepts that describe
        aspects, components, or variants of the element.

        Example: "cybernetics" sentences also mention "implants",
        "targeting eyes", "subdermals" → those are correlated.

        Returns:
            Dict of {element_name: [related_term, ...]}
        """
        import re
        from collections import Counter

        # Split entire text into sentences once
        sentences = re.split(r'(?<=[.!?])\s+', all_text)

        # Build a set of all existing element names (to exclude from correlations)
        all_elem_names = {n.lower() for n in name_index}

        # Common words to skip
        stopwords = {
            "the", "and", "but", "was", "were", "had", "have", "has", "been",
            "they", "them", "their", "she", "her", "his", "him", "its",
            "this", "that", "with", "from", "into", "onto", "upon",
            "could", "would", "should", "will", "just", "then", "than",
            "very", "much", "more", "most", "also", "only", "even",
            "said", "like", "back", "over", "down", "some", "what",
            "when", "where", "which", "while", "about", "after", "before",
            "through", "between", "being", "other", "there", "here",
            "know", "knew", "think", "thought", "look", "looked",
            "made", "make", "came", "come", "went", "gone", "going",
            "around", "still", "every", "never", "always", "something",
            "nothing", "anything", "everything", "someone", "anyone",
        }

        correlations = {}

        for elem_name, (category, elem, mentions) in name_index.items():
            elem_lower = elem_name.lower()
            nearby_words = Counter()

            # Collect all sentences mentioning this element + neighbors
            for i, sent in enumerate(sentences):
                if elem_lower not in sent.lower():
                    continue

                # Look at this sentence + 1 before and 1 after
                window = []
                if i > 0:
                    window.append(sentences[i - 1])
                window.append(sent)
                if i < len(sentences) - 1:
                    window.append(sentences[i + 1])

                # Extract notable terms from the window
                for s in window:
                    # Find multi-word terms (2-3 words, at least one interesting)
                    terms = re.findall(r'\b([a-z][\w-]*(?:\s+[a-z][\w-]*){0,2})\b', s.lower())
                    for term in terms:
                        term = term.strip()
                        words = term.split()
                        # Skip if too short, is the element itself, or all stopwords
                        if len(term) < 4:
                            continue
                        if term == elem_lower or term in all_elem_names:
                            continue
                        if all(w in stopwords for w in words):
                            continue
                        if len(words) == 1 and words[0] in stopwords:
                            continue
                        nearby_words[term] += 1

            # Keep terms that appear 2+ times near this element
            # (appearing once could be coincidental)
            related = [
                term for term, count in nearby_words.most_common(20)
                if count >= 2 and len(term) > 4
            ]

            if related:
                correlations[elem_name] = related[:8]

        return correlations
