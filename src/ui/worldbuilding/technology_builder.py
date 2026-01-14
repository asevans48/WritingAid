"""Technology builder for managing technologies and innovations."""

from typing import List, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QLabel, QLineEdit, QTextEdit, QComboBox, QSlider, QFormLayout,
    QGroupBox, QDialog, QDialogButtonBox, QListWidgetItem, QScrollArea,
    QCheckBox
)
from PyQt6.QtCore import pyqtSignal, Qt

from src.models.worldbuilding_objects import Technology, TechnologyType, Faction
from src.ui.worldbuilding.filter_sort_widget import FilterSortWidget


class TechnologyEditor(QDialog):
    """Dialog for editing a technology."""

    def __init__(self, technology: Optional[Technology] = None, available_factions: List[Faction] = None, parent=None):
        """Initialize technology editor.

        Args:
            technology: Technology to edit (None for new)
            available_factions: List of Faction objects
            parent: Parent widget
        """
        super().__init__(parent)
        self.technology = technology or Technology(
            id="",
            name="",
            technology_type=TechnologyType.OTHER,
            description="",
            factions_with_access=[],
            inventor_faction=None,
            game_changing_level=50,
            destructive_level=50,
            development_date="",
            tech_level="",
            prerequisites=[],
            applications=[],
            limitations="",
            side_effects="",
            story_relevance="",
            notes=""
        )
        self.available_factions = available_factions or []
        self._init_ui()
        if technology:
            self._load_technology()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Technology Editor")
        self.resize(750, 600)

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
        self.name_edit.setPlaceholderText("Technology name")
        basic_layout.addRow("Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value.replace("_", " ").title() for t in TechnologyType])
        basic_layout.addRow("Type:", self.type_combo)

        self.tech_level_edit = QLineEdit()
        self.tech_level_edit.setPlaceholderText("e.g., 'Medieval', 'Modern', 'Sci-Fi'")
        basic_layout.addRow("Tech Level:", self.tech_level_edit)

        self.development_date_edit = QLineEdit()
        self.development_date_edit.setPlaceholderText("When was it invented?")
        basic_layout.addRow("Development Date:", self.development_date_edit)

        self.cost_to_build_edit = QTextEdit()
        self.cost_to_build_edit.setPlaceholderText("Resources, time, money, or other costs to build/create this technology...")
        self.cost_to_build_edit.setMaximumHeight(60)
        basic_layout.addRow("Cost to Build:", self.cost_to_build_edit)

        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)

        # Description
        desc_group = QGroupBox("Description")
        desc_layout = QVBoxLayout()

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Describe how this technology works...")
        self.description_edit.setMaximumHeight(100)
        desc_layout.addWidget(self.description_edit)

        desc_group.setLayout(desc_layout)
        scroll_layout.addWidget(desc_group)

        # Faction associations
        faction_group = QGroupBox("Faction Access")
        faction_layout = QVBoxLayout()

        # Inventor faction
        inventor_layout = QHBoxLayout()
        inventor_label = QLabel("Inventor Faction:")
        inventor_layout.addWidget(inventor_label)

        self.inventor_combo = QComboBox()
        self.inventor_combo.addItem("-- None --", None)
        for faction in self.available_factions:
            self.inventor_combo.addItem(f"{faction.name} ({faction.faction_type.value})", faction.id)
        inventor_layout.addWidget(self.inventor_combo)

        faction_layout.addLayout(inventor_layout)

        # Factions with access
        access_help = QLabel("Factions that have access to this technology:")
        access_help.setStyleSheet("color: #6b7280; font-size: 11px; margin-top: 8px;")
        faction_layout.addWidget(access_help)

        self.faction_checkboxes = {}
        if self.available_factions:
            for faction in self.available_factions:
                checkbox = QCheckBox(f"{faction.name} ({faction.faction_type.value})")
                checkbox.setProperty("faction_id", faction.id)
                self.faction_checkboxes[faction.id] = checkbox
                faction_layout.addWidget(checkbox)
        else:
            no_factions_label = QLabel("No factions available. Create factions first.")
            no_factions_label.setStyleSheet("color: #ef4444; font-style: italic;")
            faction_layout.addWidget(no_factions_label)

        faction_group.setLayout(faction_layout)
        scroll_layout.addWidget(faction_group)

        # Impact ratings
        ratings_group = QGroupBox("Impact Ratings")
        ratings_layout = QVBoxLayout()

        # Game-changing slider
        gc_label = QLabel("Game-Changing Level (0=Benign, 100=Game-Changing):")
        gc_label.setStyleSheet("font-weight: 600; margin-top: 8px;")
        ratings_layout.addWidget(gc_label)

        gc_slider_layout = QHBoxLayout()
        self.game_changing_slider = QSlider(Qt.Orientation.Horizontal)
        self.game_changing_slider.setRange(0, 100)
        self.game_changing_slider.setValue(50)
        self.game_changing_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.game_changing_slider.setTickInterval(10)
        gc_slider_layout.addWidget(self.game_changing_slider)

        self.gc_label = QLabel("50")
        self.gc_label.setMinimumWidth(30)
        self.game_changing_slider.valueChanged.connect(lambda v: self.gc_label.setText(str(v)))
        gc_slider_layout.addWidget(self.gc_label)

        ratings_layout.addLayout(gc_slider_layout)

        # Destructive slider
        dest_label = QLabel("Destructive Level (0=Helpful, 100=Destructive):")
        dest_label.setStyleSheet("font-weight: 600; margin-top: 8px;")
        ratings_layout.addWidget(dest_label)

        dest_slider_layout = QHBoxLayout()
        self.destructive_slider = QSlider(Qt.Orientation.Horizontal)
        self.destructive_slider.setRange(0, 100)
        self.destructive_slider.setValue(50)
        self.destructive_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.destructive_slider.setTickInterval(10)
        dest_slider_layout.addWidget(self.destructive_slider)

        self.dest_label = QLabel("50")
        self.dest_label.setMinimumWidth(30)
        self.destructive_slider.valueChanged.connect(lambda v: self.dest_label.setText(str(v)))
        dest_slider_layout.addWidget(self.dest_label)

        ratings_layout.addLayout(dest_slider_layout)

        ratings_group.setLayout(ratings_layout)
        scroll_layout.addWidget(ratings_group)

        # Applications
        app_group = QGroupBox("Applications & Uses")
        app_layout = QVBoxLayout()

        app_help = QLabel("How is this technology used? (one per line):")
        app_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        app_layout.addWidget(app_help)

        self.applications_edit = QTextEdit()
        self.applications_edit.setPlaceholderText("e.g.:\nLong-distance communication\nMilitary coordination\nTrading information")
        self.applications_edit.setMaximumHeight(80)
        app_layout.addWidget(self.applications_edit)

        app_group.setLayout(app_layout)
        scroll_layout.addWidget(app_group)

        # Limitations & Side Effects
        limits_group = QGroupBox("Limitations & Side Effects")
        limits_layout = QFormLayout()

        self.limitations_edit = QTextEdit()
        self.limitations_edit.setPlaceholderText("What can't this technology do?")
        self.limitations_edit.setMaximumHeight(70)
        limits_layout.addRow("Limitations:", self.limitations_edit)

        self.side_effects_edit = QTextEdit()
        self.side_effects_edit.setPlaceholderText("Unintended consequences or drawbacks...")
        self.side_effects_edit.setMaximumHeight(70)
        limits_layout.addRow("Side Effects:", self.side_effects_edit)

        limits_group.setLayout(limits_layout)
        scroll_layout.addWidget(limits_group)

        # Story relevance
        story_group = QGroupBox("Story Relevance")
        story_layout = QVBoxLayout()

        self.story_edit = QTextEdit()
        self.story_edit.setPlaceholderText("Why does this technology matter to your story?")
        self.story_edit.setMaximumHeight(80)
        story_layout.addWidget(self.story_edit)

        story_group.setLayout(story_layout)
        scroll_layout.addWidget(story_group)

        # Notes
        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout()

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Additional notes...")
        self.notes_edit.setMaximumHeight(70)
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

    def _load_technology(self):
        """Load technology data into form."""
        self.name_edit.setText(self.technology.name)

        # Set type
        type_index = list(TechnologyType).index(self.technology.technology_type)
        self.type_combo.setCurrentIndex(type_index)

        self.tech_level_edit.setText(self.technology.tech_level or "")
        self.development_date_edit.setText(self.technology.development_date or "")
        self.cost_to_build_edit.setPlainText(self.technology.cost_to_build or "")
        self.description_edit.setPlainText(self.technology.description)

        # Inventor faction
        if self.technology.inventor_faction:
            index = self.inventor_combo.findData(self.technology.inventor_faction)
            if index >= 0:
                self.inventor_combo.setCurrentIndex(index)

        # Factions with access
        for faction_id in self.technology.factions_with_access:
            if faction_id in self.faction_checkboxes:
                self.faction_checkboxes[faction_id].setChecked(True)

        # Ratings
        self.game_changing_slider.setValue(self.technology.game_changing_level)
        self.destructive_slider.setValue(self.technology.destructive_level)

        # Applications
        if self.technology.applications:
            self.applications_edit.setPlainText("\n".join(self.technology.applications))

        self.limitations_edit.setPlainText(self.technology.limitations)
        self.side_effects_edit.setPlainText(self.technology.side_effects)
        self.story_edit.setPlainText(self.technology.story_relevance)
        self.notes_edit.setPlainText(self.technology.notes)

    def _save(self):
        """Save technology data."""
        name = self.name_edit.text().strip()
        if not name:
            return  # Don't save without name

        # Generate ID from name if needed
        if not self.technology.id:
            self.technology.id = name.lower().replace(" ", "-")

        self.technology.name = name

        # Get type from combo
        type_list = list(TechnologyType)
        self.technology.technology_type = type_list[self.type_combo.currentIndex()]

        self.technology.tech_level = self.tech_level_edit.text().strip()
        self.technology.development_date = self.development_date_edit.text().strip()
        self.technology.cost_to_build = self.cost_to_build_edit.toPlainText().strip()
        self.technology.description = self.description_edit.toPlainText().strip()

        # Inventor faction
        self.technology.inventor_faction = self.inventor_combo.currentData()

        # Get selected factions
        self.technology.factions_with_access = [
            faction_id for faction_id, checkbox in self.faction_checkboxes.items()
            if checkbox.isChecked()
        ]

        # Ratings
        self.technology.game_changing_level = self.game_changing_slider.value()
        self.technology.destructive_level = self.destructive_slider.value()

        # Applications
        app_text = self.applications_edit.toPlainText().strip()
        self.technology.applications = [a.strip() for a in app_text.split("\n") if a.strip()]

        self.technology.limitations = self.limitations_edit.toPlainText().strip()
        self.technology.side_effects = self.side_effects_edit.toPlainText().strip()
        self.technology.story_relevance = self.story_edit.toPlainText().strip()
        self.technology.notes = self.notes_edit.toPlainText().strip()

        self.accept()

    def get_technology(self) -> Technology:
        """Get the edited technology."""
        return self.technology


class TechnologyBuilderWidget(QWidget):
    """Widget for managing technologies."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize technology builder widget."""
        super().__init__()
        self.technologies: List[Technology] = []
        self.available_factions: List[Faction] = []
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QHBoxLayout()
        title = QLabel("🔬 Technologies & Innovations")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header.addWidget(title)

        header.addStretch()

        subtitle = QLabel("Track important technologies and which factions have them")
        subtitle.setStyleSheet("font-size: 12px; color: #6b7280;")
        header.addWidget(subtitle)

        layout.addLayout(header)

        # Help text
        help_text = QLabel(
            "Manage key technologies in your world. Rate their impact as game-changing or benign, "
            "destructive or helpful, and track which factions have access."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #6b7280; font-size: 11px; margin-bottom: 8px;")
        layout.addWidget(help_text)

        # Filter/Sort controls
        self.filter_sort = FilterSortWidget(
            sort_options=["Name", "Type", "Tech Level"],
            filter_placeholder="Search technologies..."
        )
        self.filter_sort.set_filter_options(["All"] + [t.value.replace("_", " ").title() for t in TechnologyType])
        self.filter_sort.filter_changed.connect(self._update_list)
        layout.addWidget(self.filter_sort)

        # Toolbar
        toolbar = QHBoxLayout()

        self.add_btn = QPushButton("➕ Add Technology")
        self.add_btn.clicked.connect(self._add_technology)
        toolbar.addWidget(self.add_btn)

        self.edit_btn = QPushButton("✏️ Edit")
        self.edit_btn.clicked.connect(self._edit_technology)
        self.edit_btn.setEnabled(False)
        toolbar.addWidget(self.edit_btn)

        self.remove_btn = QPushButton("🗑️ Remove")
        self.remove_btn.clicked.connect(self._remove_technology)
        self.remove_btn.setEnabled(False)
        toolbar.addWidget(self.remove_btn)

        toolbar.addStretch()

        import_btn = QPushButton("📥 Import")
        import_btn.clicked.connect(self._import_technologies)
        toolbar.addWidget(import_btn)

        layout.addLayout(toolbar)

        # Technology list
        self.tech_list = QListWidget()
        self.tech_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.tech_list.itemDoubleClicked.connect(self._edit_technology)
        layout.addWidget(self.tech_list)

    def set_available_factions(self, factions: List[Faction]):
        """Set available factions for technology association.

        Args:
            factions: List of Faction objects
        """
        self.available_factions = factions

    def load_technologies(self, technologies: List[Technology]):
        """Load technologies into widget.

        Args:
            technologies: List of Technology objects
        """
        self.technologies = technologies
        self._update_list()

    def get_technologies(self) -> List[Technology]:
        """Get all technologies.

        Returns:
            List of Technology objects
        """
        return self.technologies

    def _import_technologies(self):
        """Import technologies from JSON file."""
        from src.ui.worldbuilding.worldbuilding_importer import show_import_dialog
        from src.models.worldbuilding_objects import CompleteWorldBuilding

        temp_wb = CompleteWorldBuilding(technologies=self.technologies)
        result = show_import_dialog(self, temp_wb, target_section="technologies")
        if result and result.imported_counts.get("technologies", 0) > 0:
            self.technologies = temp_wb.technologies
            self._update_list()
            self.content_changed.emit()

    def _update_list(self):
        """Update technology list display."""
        self.tech_list.clear()

        # Filter and sort functions
        def get_searchable_text(tech):
            faction_names = [f.name for f in self.available_factions if f.id in tech.factions_with_access]
            return f"{tech.name} {tech.technology_type.value} {tech.tech_level or ''} {' '.join(faction_names)} {tech.description or ''}"

        def get_sort_value(tech, key):
            if key == "Name":
                return tech.name.lower()
            elif key == "Type":
                return tech.technology_type.value
            elif key == "Tech Level":
                return tech.tech_level or ""
            return tech.name.lower()

        def get_type(tech):
            return tech.technology_type.value.replace("_", " ").title()

        filtered_techs = self.filter_sort.filter_and_sort(
            self.technologies, get_searchable_text, get_sort_value, get_type
        )

        for tech in filtered_techs:
            # Get faction names
            faction_names = []
            for faction_id in tech.factions_with_access[:3]:  # Show first 3
                faction = next((f for f in self.available_factions if f.id == faction_id), None)
                if faction:
                    faction_names.append(faction.name)

            factions_text = f" • {', '.join(faction_names)}" if faction_names else ""
            if len(tech.factions_with_access) > 3:
                factions_text += "..."

            # Rating indicators
            gc_indicator = "🌟" if tech.game_changing_level > 70 else ""
            dest_indicator = "⚠️" if tech.destructive_level > 70 else "✅" if tech.destructive_level < 30 else ""

            item_text = f"{gc_indicator}{dest_indicator} {tech.name} ({tech.technology_type.value.replace('_', ' ').title()}){factions_text}"

            # Add truncated description if available
            if tech.description:
                desc = tech.description[:50] + "..." if len(tech.description) > 50 else tech.description
                item_text += f" - {desc}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, tech.id)
            self.tech_list.addItem(item)

    def _on_selection_changed(self):
        """Handle selection change."""
        has_selection = bool(self.tech_list.selectedItems())
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def _add_technology(self):
        """Add new technology."""
        editor = TechnologyEditor(available_factions=self.available_factions, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            tech = editor.get_technology()
            self.technologies.append(tech)
            self._update_list()
            self.content_changed.emit()

    def _edit_technology(self):
        """Edit selected technology."""
        items = self.tech_list.selectedItems()
        if not items:
            return

        tech_id = items[0].data(Qt.ItemDataRole.UserRole)
        tech = next((t for t in self.technologies if t.id == tech_id), None)
        if not tech:
            return

        editor = TechnologyEditor(technology=tech, available_factions=self.available_factions, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_list()
            self.content_changed.emit()

    def _remove_technology(self):
        """Remove selected technology."""
        items = self.tech_list.selectedItems()
        if not items:
            return

        current_row = self.tech_list.row(items[0])
        tech_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.technologies = [t for t in self.technologies if t.id != tech_id]
        self._update_list()

        # Select next available technology if any exist
        if self.tech_list.count() > 0:
            next_row = min(current_row, self.tech_list.count() - 1)
            self.tech_list.setCurrentRow(next_row)

        self.content_changed.emit()
