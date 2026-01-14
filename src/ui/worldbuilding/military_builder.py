"""Military builder for armies, branches, and conflicts."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox, QSpinBox,
    QFormLayout, QGroupBox, QScrollArea, QInputDialog, QTabWidget,
    QDialog, QDialogButtonBox, QMessageBox, QToolBar
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from typing import List, Optional
import uuid

from src.models.worldbuilding_objects import Army, MilitaryBranch, Faction
from src.ui.worldbuilding.filter_sort_widget import FilterSortWidget


class MilitaryBranchEditor(QDialog):
    """Dialog for editing a military branch."""

    def __init__(self, branch: MilitaryBranch, parent=None):
        """Initialize branch editor."""
        super().__init__(parent)
        self.branch = branch
        self.setWindowTitle("Edit Military Branch")
        self.resize(700, 600)
        self._init_ui()
        self._load_branch()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        form = QFormLayout()

        # Name
        self.name_edit = QLineEdit()
        form.addRow("Branch Name:", self.name_edit)

        # Type
        self.type_edit = QLineEdit()
        self.type_edit.setPlaceholderText("Army, Navy, Air Force, Space Force, etc.")
        form.addRow("Type:", self.type_edit)

        # Size
        self.size_spin = QSpinBox()
        self.size_spin.setMaximum(999999999)
        form.addRow("Size:", self.size_spin)

        # Commander
        self.commander_edit = QLineEdit()
        form.addRow("Commander:", self.commander_edit)

        scroll_layout.addLayout(form)

        # Description
        desc_label = QLabel("Description:")
        scroll_layout.addWidget(desc_label)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText("General description of this military branch...")
        scroll_layout.addWidget(self.description_edit)

        # Equipment
        equip_group = QGroupBox("Equipment")
        equip_layout = QVBoxLayout(equip_group)

        self.equipment_list = QListWidget()
        self.equipment_list.setMaximumHeight(120)
        equip_layout.addWidget(self.equipment_list)

        equip_btn_layout = QHBoxLayout()
        add_equip_btn = QPushButton("Add Equipment")
        add_equip_btn.clicked.connect(self._add_equipment)
        equip_btn_layout.addWidget(add_equip_btn)

        remove_equip_btn = QPushButton("Remove")
        remove_equip_btn.clicked.connect(self._remove_equipment)
        equip_btn_layout.addWidget(remove_equip_btn)

        equip_layout.addLayout(equip_btn_layout)
        scroll_layout.addWidget(equip_group)

        # Bases
        bases_group = QGroupBox("Bases")
        bases_layout = QVBoxLayout(bases_group)

        self.bases_list = QListWidget()
        self.bases_list.setMaximumHeight(120)
        bases_layout.addWidget(self.bases_list)

        bases_btn_layout = QHBoxLayout()
        add_base_btn = QPushButton("Add Base")
        add_base_btn.clicked.connect(self._add_base)
        bases_btn_layout.addWidget(add_base_btn)

        remove_base_btn = QPushButton("Remove")
        remove_base_btn.clicked.connect(self._remove_base)
        bases_btn_layout.addWidget(remove_base_btn)

        bases_layout.addLayout(bases_btn_layout)
        scroll_layout.addWidget(bases_group)

        # Specialization
        spec_label = QLabel("Specialization:")
        scroll_layout.addWidget(spec_label)

        self.specialization_edit = QTextEdit()
        self.specialization_edit.setMaximumHeight(80)
        scroll_layout.addWidget(self.specialization_edit)

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_branch(self):
        """Load branch data."""
        self.name_edit.setText(self.branch.name)
        self.type_edit.setText(self.branch.branch_type)
        if self.branch.size:
            self.size_spin.setValue(self.branch.size)
        if self.branch.commander:
            self.commander_edit.setText(self.branch.commander)
        self.description_edit.setPlainText(self.branch.description)
        self.specialization_edit.setPlainText(self.branch.specialization)

        for equip in self.branch.equipment:
            self.equipment_list.addItem(equip)

        for base in self.branch.bases:
            self.bases_list.addItem(base)

    def _add_equipment(self):
        """Add equipment."""
        name, ok = QInputDialog.getText(self, "Add Equipment", "Enter equipment name:")
        if ok and name:
            self.equipment_list.addItem(name)

    def _remove_equipment(self):
        """Remove equipment."""
        current = self.equipment_list.currentRow()
        if current >= 0:
            self.equipment_list.takeItem(current)

    def _add_base(self):
        """Add base."""
        name, ok = QInputDialog.getText(self, "Add Base", "Enter base location:")
        if ok and name:
            self.bases_list.addItem(name)

    def _remove_base(self):
        """Remove base."""
        current = self.bases_list.currentRow()
        if current >= 0:
            self.bases_list.takeItem(current)

    def _save(self):
        """Save branch data and close dialog."""
        self.branch.name = self.name_edit.text()
        self.branch.branch_type = self.type_edit.text()
        self.branch.size = self.size_spin.value() if self.size_spin.value() > 0 else None
        self.branch.commander = self.commander_edit.text()
        self.branch.description = self.description_edit.toPlainText()
        self.branch.specialization = self.specialization_edit.toPlainText()

        self.branch.equipment = [
            self.equipment_list.item(i).text()
            for i in range(self.equipment_list.count())
        ]

        self.branch.bases = [
            self.bases_list.item(i).text()
            for i in range(self.bases_list.count())
        ]

        self.accept()


class ArmyEditorDialog(QDialog):
    """Popup dialog for editing an army."""

    def __init__(self, army: Optional[Army] = None, available_factions: List[Faction] = None, parent=None):
        """Initialize army editor dialog."""
        super().__init__(parent)
        self.army = army
        self.available_factions = available_factions or []
        self.setWindowTitle("Edit Military Force" if army else "New Military Force")
        self.resize(750, 650)
        self._init_ui()
        if army:
            self._load_army()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)

        # Tabs
        tabs = QTabWidget()

        # Basic Info Tab
        basic_tab = self._create_basic_tab()
        tabs.addTab(basic_tab, "Basic Info")

        # Branches Tab
        branches_tab = self._create_branches_tab()
        tabs.addTab(branches_tab, "Branches")

        # Relations Tab
        relations_tab = self._create_relations_tab()
        tabs.addTab(relations_tab, "Relations & Conflicts")

        # History Tab
        history_tab = self._create_history_tab()
        tabs.addTab(history_tab, "Military History")

        layout.addWidget(tabs)

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._save_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _create_basic_tab(self) -> QWidget:
        """Create basic info tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Enter army name")
        layout.addRow("Army Name:", self.name_edit)

        # Faction selection - use combo box with existing factions
        self.faction_combo = QComboBox()
        self.faction_combo.setEditable(False)
        self.faction_combo.addItem("-- Select Faction --", "")

        # Populate with available factions
        for faction in self.available_factions:
            self.faction_combo.addItem(faction.name, faction.id)

        layout.addRow("Faction:", self.faction_combo)

        self.strength_spin = QSpinBox()
        self.strength_spin.setMaximum(999999999)
        layout.addRow("Total Strength:", self.strength_spin)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Describe this military force...")
        layout.addRow("Description:", self.description_edit)

        return widget

    def _create_branches_tab(self) -> QWidget:
        """Create branches management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        label = QLabel("Military Branches (double-click to edit):")
        layout.addWidget(label)

        self.branches_list = QListWidget()
        self.branches_list.itemDoubleClicked.connect(self._edit_branch_dialog)
        layout.addWidget(self.branches_list)

        btn_layout = QHBoxLayout()
        add_branch_btn = QPushButton("Add Branch")
        add_branch_btn.clicked.connect(self._add_branch)
        btn_layout.addWidget(add_branch_btn)

        edit_branch_btn = QPushButton("Edit Branch")
        edit_branch_btn.clicked.connect(lambda: self._edit_branch_dialog(self.branches_list.currentItem()))
        btn_layout.addWidget(edit_branch_btn)

        remove_branch_btn = QPushButton("Remove Branch")
        remove_branch_btn.clicked.connect(self._remove_branch)
        btn_layout.addWidget(remove_branch_btn)

        layout.addLayout(btn_layout)

        return widget

    def _create_relations_tab(self) -> QWidget:
        """Create relations tab."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)

        # Allies
        allies_group = QGroupBox("Allied Forces")
        allies_layout = QVBoxLayout(allies_group)

        self.allies_list = QListWidget()
        self.allies_list.setMaximumHeight(100)
        allies_layout.addWidget(self.allies_list)

        allies_btn_layout = QHBoxLayout()
        add_ally_btn = QPushButton("Add Ally")
        add_ally_btn.clicked.connect(self._add_ally)
        allies_btn_layout.addWidget(add_ally_btn)

        remove_ally_btn = QPushButton("Remove")
        remove_ally_btn.clicked.connect(self._remove_ally)
        allies_btn_layout.addWidget(remove_ally_btn)

        allies_layout.addLayout(allies_btn_layout)
        layout.addWidget(allies_group)

        # Enemies
        enemies_group = QGroupBox("Enemy Forces")
        enemies_layout = QVBoxLayout(enemies_group)

        self.enemies_list = QListWidget()
        self.enemies_list.setMaximumHeight(100)
        enemies_layout.addWidget(self.enemies_list)

        enemies_btn_layout = QHBoxLayout()
        add_enemy_btn = QPushButton("Add Enemy")
        add_enemy_btn.clicked.connect(self._add_enemy)
        enemies_btn_layout.addWidget(add_enemy_btn)

        remove_enemy_btn = QPushButton("Remove")
        remove_enemy_btn.clicked.connect(self._remove_enemy)
        enemies_btn_layout.addWidget(remove_enemy_btn)

        enemies_layout.addLayout(enemies_btn_layout)
        layout.addWidget(enemies_group)

        # Active Conflicts
        conflicts_group = QGroupBox("Active Conflicts")
        conflicts_layout = QVBoxLayout(conflicts_group)

        self.conflicts_list = QListWidget()
        self.conflicts_list.setMaximumHeight(100)
        conflicts_layout.addWidget(self.conflicts_list)

        conflicts_btn_layout = QHBoxLayout()
        add_conflict_btn = QPushButton("Add Conflict")
        add_conflict_btn.clicked.connect(self._add_conflict)
        conflicts_btn_layout.addWidget(add_conflict_btn)

        remove_conflict_btn = QPushButton("Remove")
        remove_conflict_btn.clicked.connect(self._remove_conflict)
        conflicts_btn_layout.addWidget(remove_conflict_btn)

        conflicts_layout.addLayout(conflicts_btn_layout)
        layout.addWidget(conflicts_group)

        scroll.setWidget(content)

        outer_layout = QVBoxLayout(widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll)

        return widget

    def _create_history_tab(self) -> QWidget:
        """Create military history tab."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)

        # Victories
        victories_group = QGroupBox("Notable Victories")
        victories_layout = QVBoxLayout(victories_group)

        self.victories_list = QListWidget()
        self.victories_list.setMaximumHeight(120)
        victories_layout.addWidget(self.victories_list)

        victories_btn_layout = QHBoxLayout()
        add_victory_btn = QPushButton("Add Victory")
        add_victory_btn.clicked.connect(self._add_victory)
        victories_btn_layout.addWidget(add_victory_btn)

        remove_victory_btn = QPushButton("Remove")
        remove_victory_btn.clicked.connect(self._remove_victory)
        victories_btn_layout.addWidget(remove_victory_btn)

        victories_layout.addLayout(victories_btn_layout)
        layout.addWidget(victories_group)

        # Defeats
        defeats_group = QGroupBox("Notable Defeats")
        defeats_layout = QVBoxLayout(defeats_group)

        self.defeats_list = QListWidget()
        self.defeats_list.setMaximumHeight(120)
        defeats_layout.addWidget(self.defeats_list)

        defeats_btn_layout = QHBoxLayout()
        add_defeat_btn = QPushButton("Add Defeat")
        add_defeat_btn.clicked.connect(self._add_defeat)
        defeats_btn_layout.addWidget(add_defeat_btn)

        remove_defeat_btn = QPushButton("Remove")
        remove_defeat_btn.clicked.connect(self._remove_defeat)
        defeats_btn_layout.addWidget(remove_defeat_btn)

        defeats_layout.addLayout(defeats_btn_layout)
        layout.addWidget(defeats_group)

        scroll.setWidget(content)

        outer_layout = QVBoxLayout(widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll)

        return widget

    def _load_army(self):
        """Load army data."""
        if not self.army:
            return

        self.name_edit.setText(self.army.name)

        # Set faction in combo box
        for i in range(self.faction_combo.count()):
            if self.faction_combo.itemData(i) == self.army.faction_id:
                self.faction_combo.setCurrentIndex(i)
                break

        if self.army.total_strength:
            self.strength_spin.setValue(self.army.total_strength)
        self.description_edit.setPlainText(self.army.description)

        # Load branches with truncated descriptions
        for idx, branch in enumerate(self.army.branches):
            desc = branch.description[:50] + "..." if len(branch.description) > 50 else branch.description
            display_text = f"{branch.name} ({branch.branch_type})"
            if desc:
                display_text += f" - {desc}"

            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, idx)
            self.branches_list.addItem(item)

        # Load allies - display faction names but store faction IDs
        for ally_id in self.army.allies:
            faction = next((f for f in self.available_factions if f.id == ally_id), None)
            if faction:
                item = QListWidgetItem(f"{faction.name} ({faction.faction_type})")
                item.setData(Qt.ItemDataRole.UserRole, ally_id)
                self.allies_list.addItem(item)
            else:
                item = QListWidgetItem(f"Unknown Faction ({ally_id})")
                item.setData(Qt.ItemDataRole.UserRole, ally_id)
                self.allies_list.addItem(item)

        # Load enemies - display faction names but store faction IDs
        for enemy_id in self.army.enemies:
            faction = next((f for f in self.available_factions if f.id == enemy_id), None)
            if faction:
                item = QListWidgetItem(f"{faction.name} ({faction.faction_type})")
                item.setData(Qt.ItemDataRole.UserRole, enemy_id)
                self.enemies_list.addItem(item)
            else:
                item = QListWidgetItem(f"Unknown Faction ({enemy_id})")
                item.setData(Qt.ItemDataRole.UserRole, enemy_id)
                self.enemies_list.addItem(item)

        # Load conflicts
        for conflict in self.army.active_conflicts:
            self.conflicts_list.addItem(conflict)

        # Load victories
        for victory in self.army.victories:
            self.victories_list.addItem(victory)

        # Load defeats
        for defeat in self.army.defeats:
            self.defeats_list.addItem(defeat)

    def _add_branch(self):
        """Add new branch."""
        branch = MilitaryBranch(name="New Branch", branch_type="", description="")
        editor = MilitaryBranchEditor(branch, self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            if not self.army:
                self.army = Army(id=str(uuid.uuid4()), name="", faction_id="")
            self.army.branches.append(branch)
            self._refresh_branch_list()

    def _remove_branch(self):
        """Remove branch."""
        current = self.branches_list.currentRow()
        if self.army and current >= 0 and current < len(self.army.branches):
            self.army.branches.pop(current)
            self._refresh_branch_list()

    def _edit_branch_dialog(self, item):
        """Open dialog to edit branch."""
        if not item or not self.army:
            return

        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is not None and idx < len(self.army.branches):
            branch = self.army.branches[idx]
            editor = MilitaryBranchEditor(branch, self)
            if editor.exec() == QDialog.DialogCode.Accepted:
                self._refresh_branch_list()

    def _refresh_branch_list(self):
        """Refresh the branches list display."""
        self.branches_list.clear()
        if not self.army:
            return
        for idx, branch in enumerate(self.army.branches):
            desc = branch.description[:50] + "..." if len(branch.description) > 50 else branch.description
            display_text = f"{branch.name} ({branch.branch_type})"
            if desc:
                display_text += f" - {desc}"

            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, idx)
            self.branches_list.addItem(item)

    def _add_ally(self):
        """Add ally."""
        if not self.available_factions:
            QMessageBox.information(self, "No Factions", "Please create factions first before adding allies.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Select Allied Faction")
        layout = QVBoxLayout(dialog)

        faction_list = QListWidget()
        for faction in self.available_factions:
            faction_list.addItem(f"{faction.name} ({faction.faction_type})")
            faction_list.item(faction_list.count() - 1).setData(Qt.ItemDataRole.UserRole, faction.id)

        layout.addWidget(faction_list)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted and faction_list.currentItem():
            faction_id = faction_list.currentItem().data(Qt.ItemDataRole.UserRole)
            faction_name = faction_list.currentItem().text()
            # Check if already added
            for i in range(self.allies_list.count()):
                if self.allies_list.item(i).data(Qt.ItemDataRole.UserRole) == faction_id:
                    return
            item = QListWidgetItem(faction_name)
            item.setData(Qt.ItemDataRole.UserRole, faction_id)
            self.allies_list.addItem(item)

    def _remove_ally(self):
        """Remove ally."""
        current = self.allies_list.currentRow()
        if current >= 0:
            self.allies_list.takeItem(current)

    def _add_enemy(self):
        """Add enemy."""
        if not self.available_factions:
            QMessageBox.information(self, "No Factions", "Please create factions first before adding enemies.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Select Enemy Faction")
        layout = QVBoxLayout(dialog)

        faction_list = QListWidget()
        for faction in self.available_factions:
            faction_list.addItem(f"{faction.name} ({faction.faction_type})")
            faction_list.item(faction_list.count() - 1).setData(Qt.ItemDataRole.UserRole, faction.id)

        layout.addWidget(faction_list)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted and faction_list.currentItem():
            faction_id = faction_list.currentItem().data(Qt.ItemDataRole.UserRole)
            faction_name = faction_list.currentItem().text()
            # Check if already added
            for i in range(self.enemies_list.count()):
                if self.enemies_list.item(i).data(Qt.ItemDataRole.UserRole) == faction_id:
                    return
            item = QListWidgetItem(faction_name)
            item.setData(Qt.ItemDataRole.UserRole, faction_id)
            self.enemies_list.addItem(item)

    def _remove_enemy(self):
        """Remove enemy."""
        current = self.enemies_list.currentRow()
        if current >= 0:
            self.enemies_list.takeItem(current)

    def _add_conflict(self):
        """Add conflict."""
        name, ok = QInputDialog.getText(self, "Add Conflict", "Enter conflict name:")
        if ok and name:
            self.conflicts_list.addItem(name)

    def _remove_conflict(self):
        """Remove conflict."""
        current = self.conflicts_list.currentRow()
        if current >= 0:
            self.conflicts_list.takeItem(current)

    def _add_victory(self):
        """Add victory."""
        name, ok = QInputDialog.getText(self, "Add Victory", "Enter battle/campaign name:")
        if ok and name:
            self.victories_list.addItem(name)

    def _remove_victory(self):
        """Remove victory."""
        current = self.victories_list.currentRow()
        if current >= 0:
            self.victories_list.takeItem(current)

    def _add_defeat(self):
        """Add defeat."""
        name, ok = QInputDialog.getText(self, "Add Defeat", "Enter battle/campaign name:")
        if ok and name:
            self.defeats_list.addItem(name)

    def _remove_defeat(self):
        """Remove defeat."""
        current = self.defeats_list.currentRow()
        if current >= 0:
            self.defeats_list.takeItem(current)

    def _save_and_accept(self):
        """Validate and save."""
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Army name is required.")
            return
        self.accept()

    def get_army(self) -> Army:
        """Get army from form data."""
        army_id = self.army.id if self.army else str(uuid.uuid4())
        branches = self.army.branches if self.army else []

        allies = [
            self.allies_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.allies_list.count())
        ]

        enemies = [
            self.enemies_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.enemies_list.count())
        ]

        active_conflicts = [
            self.conflicts_list.item(i).text()
            for i in range(self.conflicts_list.count())
        ]

        victories = [
            self.victories_list.item(i).text()
            for i in range(self.victories_list.count())
        ]

        defeats = [
            self.defeats_list.item(i).text()
            for i in range(self.defeats_list.count())
        ]

        return Army(
            id=army_id,
            name=self.name_edit.text().strip(),
            faction_id=self.faction_combo.currentData() or "",
            total_strength=self.strength_spin.value() if self.strength_spin.value() > 0 else None,
            description=self.description_edit.toPlainText(),
            branches=branches,
            allies=allies,
            enemies=enemies,
            active_conflicts=active_conflicts,
            victories=victories,
            defeats=defeats
        )


# Keep ArmyEditor for backward compatibility (alias to dialog)
ArmyEditor = ArmyEditorDialog


class MilitaryBuilderWidget(QWidget):
    """Widget for managing all armies with popup editor."""

    content_changed = pyqtSignal()

    def __init__(self, available_factions: List[Faction] = None):
        """Initialize military builder."""
        super().__init__()
        self.armies: List[Army] = []
        self.available_factions = available_factions or []
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Header
        header = QLabel("Military Forces")
        header.setStyleSheet("font-size: 16px; font-weight: 600; padding: 8px;")
        layout.addWidget(header)

        # Filter/Sort controls
        self.filter_sort = FilterSortWidget(
            sort_options=["Name", "Faction", "Strength"],
            filter_placeholder="Search armies..."
        )
        self.filter_sort.filter_changed.connect(self._update_list)
        layout.addWidget(self.filter_sort)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet("QToolBar { spacing: 8px; padding: 4px; }")

        add_action = QAction("Add Army", self)
        add_action.triggered.connect(self._add_army)
        toolbar.addAction(add_action)

        edit_action = QAction("Edit", self)
        edit_action.triggered.connect(self._edit_army)
        toolbar.addAction(edit_action)

        remove_action = QAction("Remove", self)
        remove_action.triggered.connect(self._remove_army)
        toolbar.addAction(remove_action)

        toolbar.addSeparator()

        import_action = QAction("Import", self)
        import_action.setToolTip("Import armies from JSON file")
        import_action.triggered.connect(self._import_armies)
        toolbar.addAction(import_action)

        layout.addWidget(toolbar)

        # Army list
        self.army_list = QListWidget()
        self.army_list.itemDoubleClicked.connect(self._edit_army)
        layout.addWidget(self.army_list)

    def _update_list(self):
        """Update army list display with filtering and sorting."""
        self.army_list.clear()

        # Get faction name helper
        def get_faction_name(army):
            faction = next((f for f in self.available_factions if f.id == army.faction_id), None)
            return faction.name if faction else army.faction_id

        # Filter and sort functions
        def get_searchable_text(army):
            faction_name = get_faction_name(army)
            return f"{army.name} {faction_name} {army.description or ''}"

        def get_sort_value(army, key):
            if key == "Name":
                return army.name.lower()
            elif key == "Faction":
                return get_faction_name(army).lower()
            elif key == "Strength":
                return army.total_strength or 0
            return army.name.lower()

        filtered_armies = self.filter_sort.filter_and_sort(
            self.armies, get_searchable_text, get_sort_value
        )

        for army in filtered_armies:
            faction_name = get_faction_name(army)
            display_text = f"{army.name}"
            if faction_name:
                display_text += f" ({faction_name})"
            if army.total_strength:
                display_text += f" - {army.total_strength:,} troops"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, army.id)
            self.army_list.addItem(item)

    def _add_army(self):
        """Add new army via popup dialog."""
        dialog = ArmyEditorDialog(available_factions=self.available_factions, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            army = dialog.get_army()
            self.armies.append(army)
            self._update_list()
            self.content_changed.emit()

    def _edit_army(self):
        """Edit selected army via popup dialog."""
        current = self.army_list.currentItem()
        if not current:
            QMessageBox.information(self, "No Selection", "Please select an army to edit.")
            return

        army_id = current.data(Qt.ItemDataRole.UserRole)
        army = next((a for a in self.armies if a.id == army_id), None)

        if army:
            dialog = ArmyEditorDialog(army=army, available_factions=self.available_factions, parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                updated_army = dialog.get_army()
                # Update in list
                for i, a in enumerate(self.armies):
                    if a.id == army_id:
                        self.armies[i] = updated_army
                        break
                self._update_list()
                self.content_changed.emit()

    def _remove_army(self):
        """Remove selected army."""
        current = self.army_list.currentItem()
        if not current:
            QMessageBox.information(self, "No Selection", "Please select an army to remove.")
            return

        army_id = current.data(Qt.ItemDataRole.UserRole)
        army = next((a for a in self.armies if a.id == army_id), None)

        if army:
            reply = QMessageBox.question(
                self,
                "Confirm Removal",
                f"Remove army '{army.name}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.armies = [a for a in self.armies if a.id != army_id]
                self._update_list()
                self.content_changed.emit()

    def get_armies(self) -> List[Army]:
        """Get all armies."""
        return self.armies

    def _import_armies(self):
        """Import armies from JSON file."""
        from src.ui.worldbuilding.worldbuilding_importer import show_import_dialog
        from src.models.worldbuilding_objects import CompleteWorldBuilding

        temp_wb = CompleteWorldBuilding(armies=self.armies)
        result = show_import_dialog(self, temp_wb, target_section="armies")

        if result and result.imported_counts.get("armies", 0) > 0:
            self.armies = temp_wb.armies
            self._update_list()
            self.content_changed.emit()

    def load_armies(self, armies: List[Army]):
        """Load armies."""
        self.armies = armies
        self._update_list()

    def set_available_factions(self, factions: List[Faction]):
        """Update the list of available factions."""
        self.available_factions = factions
        self._update_list()
