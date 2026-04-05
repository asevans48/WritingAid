"""Magic system builder for managing magic/power systems in the world."""

from typing import List, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QLabel, QLineEdit, QTextEdit, QComboBox, QFormLayout,
    QGroupBox, QDialog, QDialogButtonBox, QListWidgetItem, QScrollArea,
    QCheckBox
)
from PyQt6.QtCore import pyqtSignal, Qt

from src.models.worldbuilding_objects import MagicSystem, MagicType, Faction
from src.ui.worldbuilding.filter_sort_widget import FilterSortWidget


class MagicSystemEditor(QDialog):
    """Dialog for editing a magic system."""

    def __init__(self, magic_system: Optional[MagicSystem] = None, project=None,
                 available_factions: List[Faction] = None, parent=None):
        super().__init__(parent)
        self.magic_system = magic_system or MagicSystem(
            id="",
            name="",
            magic_type=MagicType.HARD,
            description="",
        )
        self._project = project
        self.available_factions = available_factions or []
        self._init_ui()
        if magic_system:
            self._load_magic_system()

    def _init_ui(self):
        self.setWindowTitle("Magic System Editor")
        self.resize(750, 650)

        layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        # Basic info
        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Magic system name")
        basic_layout.addRow("Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value.replace("_", " ").title() for t in MagicType])
        basic_layout.addRow("Type:", self.type_combo)

        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)

        # Description
        desc_group = QGroupBox("Description")
        desc_layout = QVBoxLayout()
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Overview of this magic system...")
        self.description_edit.setMaximumHeight(100)
        desc_layout.addWidget(self.description_edit)
        desc_group.setLayout(desc_layout)
        scroll_layout.addWidget(desc_group)

        # Rules & Mechanics
        rules_group = QGroupBox("Rules & Mechanics")
        rules_layout = QFormLayout()

        self.source_edit = QTextEdit()
        self.source_edit.setPlaceholderText("Where does the power come from? (e.g., ley lines, divine gift, internal energy)")
        self.source_edit.setMaximumHeight(60)
        rules_layout.addRow("Source:", self.source_edit)

        self.rules_edit = QTextEdit()
        self.rules_edit.setPlaceholderText("Core rules and laws of the system...")
        self.rules_edit.setMaximumHeight(80)
        rules_layout.addRow("Rules:", self.rules_edit)

        self.limitations_edit = QTextEdit()
        self.limitations_edit.setPlaceholderText("What it cannot do, hard limits...")
        self.limitations_edit.setMaximumHeight(60)
        rules_layout.addRow("Limitations:", self.limitations_edit)

        self.costs_edit = QTextEdit()
        self.costs_edit.setPlaceholderText("What practitioners pay (energy, lifespan, sanity, materials...)")
        self.costs_edit.setMaximumHeight(60)
        rules_layout.addRow("Costs:", self.costs_edit)

        rules_group.setLayout(rules_layout)
        scroll_layout.addWidget(rules_group)

        # Practitioners
        prac_group = QGroupBox("Practitioners")
        prac_layout = QFormLayout()

        self.who_can_use_edit = QTextEdit()
        self.who_can_use_edit.setPlaceholderText("Who has access? (anyone, bloodlines, trained, chosen...)")
        self.who_can_use_edit.setMaximumHeight(60)
        prac_layout.addRow("Who Can Use:", self.who_can_use_edit)

        self.training_edit = QTextEdit()
        self.training_edit.setPlaceholderText("How practitioners learn and develop their abilities...")
        self.training_edit.setMaximumHeight(60)
        prac_layout.addRow("Training:", self.training_edit)

        self.power_levels_edit = QTextEdit()
        self.power_levels_edit.setPlaceholderText("Tiers or ranks of ability (e.g., novice, adept, master...)")
        self.power_levels_edit.setMaximumHeight(60)
        prac_layout.addRow("Power Levels:", self.power_levels_edit)

        self.branches_edit = QTextEdit()
        self.branches_edit.setPlaceholderText("Sub-disciplines or schools (one per line)")
        self.branches_edit.setMaximumHeight(60)
        prac_layout.addRow("Branches:", self.branches_edit)

        prac_group.setLayout(prac_layout)
        scroll_layout.addWidget(prac_group)

        # Faction associations
        if self.available_factions:
            faction_group = QGroupBox("Associated Factions")
            faction_layout = QVBoxLayout()
            faction_layout.addWidget(QLabel("Which factions practice or control this magic:"))
            self.faction_checkboxes = {}
            for faction in self.available_factions:
                cb = QCheckBox(f"{faction.name} ({faction.faction_type.value})")
                cb.setProperty("faction_id", faction.id)
                self.faction_checkboxes[faction.id] = cb
                faction_layout.addWidget(cb)
            faction_group.setLayout(faction_layout)
            scroll_layout.addWidget(faction_group)
        else:
            self.faction_checkboxes = {}

        # World impact
        impact_group = QGroupBox("World Impact")
        impact_layout = QFormLayout()

        self.cultural_perception_edit = QTextEdit()
        self.cultural_perception_edit.setPlaceholderText("How society views magic (feared, revered, mundane, illegal...)")
        self.cultural_perception_edit.setMaximumHeight(60)
        impact_layout.addRow("Cultural Perception:", self.cultural_perception_edit)

        self.historical_impact_edit = QTextEdit()
        self.historical_impact_edit.setPlaceholderText("How magic has shaped history...")
        self.historical_impact_edit.setMaximumHeight(60)
        impact_layout.addRow("Historical Impact:", self.historical_impact_edit)

        self.relationship_to_tech_edit = QTextEdit()
        self.relationship_to_tech_edit.setPlaceholderText("Does it complement or replace technology?")
        self.relationship_to_tech_edit.setMaximumHeight(60)
        impact_layout.addRow("Relation to Tech:", self.relationship_to_tech_edit)

        impact_group.setLayout(impact_layout)
        scroll_layout.addWidget(impact_group)

        # Story relevance
        story_group = QGroupBox("Story Relevance")
        story_layout = QVBoxLayout()
        self.story_relevance_edit = QTextEdit()
        self.story_relevance_edit.setPlaceholderText("Why this magic system matters to the plot...")
        self.story_relevance_edit.setMaximumHeight(80)
        story_layout.addWidget(self.story_relevance_edit)
        story_group.setLayout(story_layout)
        scroll_layout.addWidget(story_group)

        # Notes
        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout()
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Additional notes...")
        self.notes_edit.setMaximumHeight(60)
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

        # Strengthen button
        from src.ui.worldbuilding.strengthen_element import add_strengthen_button
        add_strengthen_button(
            self, self.magic_system, "magic_system", 
            button_box=buttons, reload_callback=getattr(self, '_load_magic_system', None)
            )

        layout.addWidget(buttons)

    def _load_magic_system(self):
        ms = self.magic_system
        self.name_edit.setText(ms.name)

        # Set type combo
        types = [t.value for t in MagicType]
        if ms.magic_type.value in types:
            self.type_combo.setCurrentIndex(types.index(ms.magic_type.value))

        self.description_edit.setPlainText(ms.description)
        self.source_edit.setPlainText(ms.source)
        self.rules_edit.setPlainText(ms.rules)
        self.limitations_edit.setPlainText(ms.limitations)
        self.costs_edit.setPlainText(ms.costs)
        self.who_can_use_edit.setPlainText(ms.who_can_use)
        self.training_edit.setPlainText(ms.training)
        self.power_levels_edit.setPlainText(ms.power_levels)
        self.branches_edit.setPlainText("\n".join(ms.branches))
        self.cultural_perception_edit.setPlainText(ms.cultural_perception)
        self.historical_impact_edit.setPlainText(ms.historical_impact)
        self.relationship_to_tech_edit.setPlainText(ms.relationship_to_technology)
        self.story_relevance_edit.setPlainText(ms.story_relevance)
        self.notes_edit.setPlainText(ms.notes)

        # Set faction checkboxes
        for faction_id, cb in self.faction_checkboxes.items():
            cb.setChecked(faction_id in ms.associated_factions)

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            self.name_edit.setFocus()
            self.name_edit.setStyleSheet("border: 1px solid red;")
            return

        types = list(MagicType)
        self.magic_system.name = name
        self.magic_system.magic_type = types[self.type_combo.currentIndex()]
        self.magic_system.description = self.description_edit.toPlainText()
        self.magic_system.source = self.source_edit.toPlainText()
        self.magic_system.rules = self.rules_edit.toPlainText()
        self.magic_system.limitations = self.limitations_edit.toPlainText()
        self.magic_system.costs = self.costs_edit.toPlainText()
        self.magic_system.who_can_use = self.who_can_use_edit.toPlainText()
        self.magic_system.training = self.training_edit.toPlainText()
        self.magic_system.power_levels = self.power_levels_edit.toPlainText()

        branches_text = self.branches_edit.toPlainText()
        self.magic_system.branches = [b.strip() for b in branches_text.split("\n") if b.strip()]

        selected_factions = []
        for faction_id, cb in self.faction_checkboxes.items():
            if cb.isChecked():
                selected_factions.append(faction_id)
        self.magic_system.associated_factions = selected_factions

        self.magic_system.cultural_perception = self.cultural_perception_edit.toPlainText()
        self.magic_system.historical_impact = self.historical_impact_edit.toPlainText()
        self.magic_system.relationship_to_technology = self.relationship_to_tech_edit.toPlainText()
        self.magic_system.story_relevance = self.story_relevance_edit.toPlainText()
        self.magic_system.notes = self.notes_edit.toPlainText()

        if not self.magic_system.id:
            self.magic_system.id = name.lower().replace(" ", "-").replace("'", "")

        self.accept()

    def get_magic_system(self) -> MagicSystem:
        return self.magic_system


class MagicSystemBuilderWidget(QWidget):
    """Widget for managing magic systems."""

    content_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.magic_systems: List[MagicSystem] = []
        self.available_factions: List[Faction] = []
        self._init_ui()

    def set_available_factions(self, factions: List[Faction]):
        self.available_factions = factions

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Header
        header = QLabel("✨ Magic Systems")
        header.setStyleSheet("font-size: 14px; font-weight: 600; color: #1a1a1a;")
        layout.addWidget(header)

        subtitle = QLabel("Define the magic, power systems, and supernatural rules of your world")
        subtitle.setStyleSheet("font-size: 11px; color: #6b7280; margin-bottom: 4px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Filter/sort
        self.filter_widget = FilterSortWidget(
            sort_options=["Name", "Type"],
            filter_placeholder="Search magic systems..."
        )
        self.filter_widget.filter_changed.connect(self._update_list)
        layout.addWidget(self.filter_widget)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        add_btn = QPushButton("➕ Add Magic System")
        add_btn.clicked.connect(self._add_magic_system)
        toolbar.addWidget(add_btn)

        self.edit_btn = QPushButton("✏️ Edit")
        self.edit_btn.clicked.connect(self._edit_magic_system)
        self.edit_btn.setEnabled(False)
        toolbar.addWidget(self.edit_btn)

        self.remove_btn = QPushButton("🗑️ Remove")
        self.remove_btn.clicked.connect(self._remove_magic_system)
        self.remove_btn.setEnabled(False)
        toolbar.addWidget(self.remove_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # List
        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self._edit_magic_system)
        layout.addWidget(self.list_widget)

    def _on_selection_changed(self):
        has_selection = len(self.list_widget.selectedItems()) > 0
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def _add_magic_system(self):
        editor = MagicSystemEditor(
            available_factions=self.available_factions,
            parent=self
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            ms = editor.get_magic_system()
            self.magic_systems.append(ms)
            self._update_list()
            self.content_changed.emit()

    def _edit_magic_system(self):
        items = self.list_widget.selectedItems()
        if not items:
            return
        ms_id = items[0].data(Qt.ItemDataRole.UserRole)
        ms = next((m for m in self.magic_systems if m.id == ms_id), None)
        if not ms:
            return

        editor = MagicSystemEditor(
            magic_system=ms,
            available_factions=self.available_factions,
            parent=self
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_list()
            self.content_changed.emit()

    def _remove_magic_system(self):
        items = self.list_widget.selectedItems()
        if not items:
            return
        ms_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.magic_systems = [m for m in self.magic_systems if m.id != ms_id]
        self._update_list()
        self.content_changed.emit()

    def _update_list(self):
        self.list_widget.clear()

        filter_text = self.filter_widget.get_filter_text()
        sort_key = self.filter_widget.get_sort_key()

        items = list(self.magic_systems)

        # Filter by search text
        if filter_text:
            items = [m for m in items if filter_text in m.name.lower() or filter_text in m.description.lower()]

        # Sort
        if sort_key == "Type":
            items.sort(key=lambda m: m.magic_type.value)
        else:
            items.sort(key=lambda m: m.name.lower())

        # Build faction name lookup
        faction_map = {f.id: f.name for f in self.available_factions}

        for ms in items:
            faction_names = [faction_map.get(fid, fid) for fid in ms.associated_factions]
            factions_str = f" • {', '.join(faction_names)}" if faction_names else ""
            desc = f" - {ms.description[:80]}..." if ms.description and len(ms.description) > 80 else (f" - {ms.description}" if ms.description else "")

            display = f"{ms.name} ({ms.magic_type.value.replace('_', ' ').title()}){factions_str}{desc}"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, ms.id)
            self.list_widget.addItem(item)

    def load_magic_systems(self, magic_systems: List[MagicSystem]):
        self.magic_systems = list(magic_systems)
        self._update_list()

    def get_magic_systems(self) -> List[MagicSystem]:
        return list(self.magic_systems)
