"""Military builder for armies, branches, and conflicts."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox, QSpinBox,
    QFormLayout, QGroupBox, QScrollArea, QSplitter, QInputDialog, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal
from typing import List, Optional
import uuid

from src.models.worldbuilding_objects import Army, MilitaryBranch


class MilitaryBranchEditor(QWidget):
    """Editor for a military branch."""

    content_changed = pyqtSignal()

    def __init__(self, branch: MilitaryBranch):
        """Initialize branch editor."""
        super().__init__()
        self.branch = branch
        self._init_ui()
        self._load_branch()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        form = QFormLayout()

        # Name
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self.content_changed.emit)
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

        layout.addLayout(form)

        # Equipment
        equip_group = QGroupBox("Equipment")
        equip_layout = QVBoxLayout(equip_group)

        self.equipment_list = QListWidget()
        equip_layout.addWidget(self.equipment_list)

        equip_btn_layout = QHBoxLayout()
        add_equip_btn = QPushButton("Add Equipment")
        add_equip_btn.clicked.connect(self._add_equipment)
        equip_btn_layout.addWidget(add_equip_btn)

        remove_equip_btn = QPushButton("Remove")
        remove_equip_btn.clicked.connect(self._remove_equipment)
        equip_btn_layout.addWidget(remove_equip_btn)

        equip_layout.addLayout(equip_btn_layout)
        layout.addWidget(equip_group)

        # Bases
        bases_group = QGroupBox("Bases")
        bases_layout = QVBoxLayout(bases_group)

        self.bases_list = QListWidget()
        bases_layout.addWidget(self.bases_list)

        bases_btn_layout = QHBoxLayout()
        add_base_btn = QPushButton("Add Base")
        add_base_btn.clicked.connect(self._add_base)
        bases_btn_layout.addWidget(add_base_btn)

        remove_base_btn = QPushButton("Remove")
        remove_base_btn.clicked.connect(self._remove_base)
        bases_btn_layout.addWidget(remove_base_btn)

        bases_layout.addLayout(bases_btn_layout)
        layout.addWidget(bases_group)

        # Specialization
        spec_label = QLabel("Specialization:")
        layout.addWidget(spec_label)

        self.specialization_edit = QTextEdit()
        self.specialization_edit.setMaximumHeight(80)
        layout.addWidget(self.specialization_edit)

    def _load_branch(self):
        """Load branch data."""
        self.name_edit.setText(self.branch.name)
        self.type_edit.setText(self.branch.branch_type)
        if self.branch.size:
            self.size_spin.setValue(self.branch.size)
        if self.branch.commander:
            self.commander_edit.setText(self.branch.commander)
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

    def save_to_model(self):
        """Save to branch model."""
        self.branch.name = self.name_edit.text()
        self.branch.branch_type = self.type_edit.text()
        self.branch.size = self.size_spin.value() if self.size_spin.value() > 0 else None
        self.branch.commander = self.commander_edit.text()
        self.branch.specialization = self.specialization_edit.toPlainText()

        self.branch.equipment = [
            self.equipment_list.item(i).text()
            for i in range(self.equipment_list.count())
        ]

        self.branch.bases = [
            self.bases_list.item(i).text()
            for i in range(self.bases_list.count())
        ]


class ArmyEditor(QWidget):
    """Editor for a complete army."""

    content_changed = pyqtSignal()

    def __init__(self, army: Army):
        """Initialize army editor."""
        super().__init__()
        self.army = army
        self._init_ui()
        self._load_army()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

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

    def _create_basic_tab(self) -> QWidget:
        """Create basic info tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self.content_changed.emit)
        layout.addRow("Army Name:", self.name_edit)

        self.faction_edit = QLineEdit()
        self.faction_edit.setPlaceholderText("Faction ID or name")
        layout.addRow("Faction:", self.faction_edit)

        self.strength_spin = QSpinBox()
        self.strength_spin.setMaximum(999999999)
        layout.addRow("Total Strength:", self.strength_spin)

        self.description_edit = QTextEdit()
        layout.addRow("Description:", self.description_edit)

        return widget

    def _create_branches_tab(self) -> QWidget:
        """Create branches management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        label = QLabel("Military Branches:")
        layout.addWidget(label)

        self.branches_list = QListWidget()
        self.branches_list.currentItemChanged.connect(self._on_branch_selected)
        layout.addWidget(self.branches_list)

        btn_layout = QHBoxLayout()
        add_branch_btn = QPushButton("Add Branch")
        add_branch_btn.clicked.connect(self._add_branch)
        btn_layout.addWidget(add_branch_btn)

        remove_branch_btn = QPushButton("Remove Branch")
        remove_branch_btn.clicked.connect(self._remove_branch)
        btn_layout.addWidget(remove_branch_btn)

        layout.addLayout(btn_layout)

        # Branch editor area
        self.branch_editor_scroll = QScrollArea()
        self.branch_editor_scroll.setWidgetResizable(True)

        placeholder = QLabel("Add or select a branch")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.branch_editor_scroll.setWidget(placeholder)

        layout.addWidget(self.branch_editor_scroll)

        return widget

    def _create_relations_tab(self) -> QWidget:
        """Create relations tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Allies
        allies_group = QGroupBox("Allied Forces")
        allies_layout = QVBoxLayout(allies_group)

        self.allies_list = QListWidget()
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

        return widget

    def _create_history_tab(self) -> QWidget:
        """Create military history tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Victories
        victories_group = QGroupBox("Notable Victories")
        victories_layout = QVBoxLayout(victories_group)

        self.victories_list = QListWidget()
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

        return widget

    def _load_army(self):
        """Load army data."""
        self.name_edit.setText(self.army.name)
        self.faction_edit.setText(self.army.faction_id)
        if self.army.total_strength:
            self.strength_spin.setValue(self.army.total_strength)
        self.description_edit.setPlainText(self.army.description)

        # Load branches
        for branch in self.army.branches:
            self.branches_list.addItem(branch.name)

        # Load allies
        for ally in self.army.allies:
            self.allies_list.addItem(ally)

        # Load enemies
        for enemy in self.army.enemies:
            self.enemies_list.addItem(enemy)

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
        name, ok = QInputDialog.getText(self, "New Branch", "Enter branch name:")
        if ok and name:
            branch = MilitaryBranch(name=name, branch_type="")
            self.army.branches.append(branch)
            self.branches_list.addItem(name)

    def _remove_branch(self):
        """Remove branch."""
        current = self.branches_list.currentRow()
        if current >= 0 and current < len(self.army.branches):
            self.army.branches.pop(current)
            self.branches_list.takeItem(current)

    def _on_branch_selected(self, current, previous):
        """Handle branch selection."""
        if not current:
            return

        idx = self.branches_list.row(current)
        if idx >= 0 and idx < len(self.army.branches):
            branch = self.army.branches[idx]
            editor = MilitaryBranchEditor(branch)
            editor.content_changed.connect(self.content_changed.emit)
            self.branch_editor_scroll.setWidget(editor)

    def _add_ally(self):
        """Add ally."""
        name, ok = QInputDialog.getText(self, "Add Ally", "Enter faction ID/name:")
        if ok and name:
            self.allies_list.addItem(name)

    def _remove_ally(self):
        """Remove ally."""
        current = self.allies_list.currentRow()
        if current >= 0:
            self.allies_list.takeItem(current)

    def _add_enemy(self):
        """Add enemy."""
        name, ok = QInputDialog.getText(self, "Add Enemy", "Enter faction ID/name:")
        if ok and name:
            self.enemies_list.addItem(name)

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

    def save_to_model(self):
        """Save to army model."""
        self.army.name = self.name_edit.text()
        self.army.faction_id = self.faction_edit.text()
        self.army.total_strength = self.strength_spin.value() if self.strength_spin.value() > 0 else None
        self.army.description = self.description_edit.toPlainText()

        self.army.allies = [
            self.allies_list.item(i).text()
            for i in range(self.allies_list.count())
        ]

        self.army.enemies = [
            self.enemies_list.item(i).text()
            for i in range(self.enemies_list.count())
        ]

        self.army.active_conflicts = [
            self.conflicts_list.item(i).text()
            for i in range(self.conflicts_list.count())
        ]

        self.army.victories = [
            self.victories_list.item(i).text()
            for i in range(self.victories_list.count())
        ]

        self.army.defeats = [
            self.defeats_list.item(i).text()
            for i in range(self.defeats_list.count())
        ]


class MilitaryBuilderWidget(QWidget):
    """Widget for managing all armies."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize military builder."""
        super().__init__()
        self.armies: List[Army] = []
        self.current_editor: Optional[ArmyEditor] = None
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QHBoxLayout(self)

        # Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Army list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        label = QLabel("Military Forces")
        label.setStyleSheet("font-weight: 600; font-size: 13px;")
        left_layout.addWidget(label)

        self.army_list = QListWidget()
        self.army_list.currentItemChanged.connect(self._on_army_selected)
        left_layout.addWidget(self.army_list)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Add Army")
        add_btn.clicked.connect(self._add_army)
        btn_layout.addWidget(add_btn)

        remove_btn = QPushButton("🗑️")
        remove_btn.setMaximumWidth(40)
        remove_btn.clicked.connect(self._remove_army)
        btn_layout.addWidget(remove_btn)

        left_layout.addLayout(btn_layout)

        left_panel.setMaximumWidth(250)
        splitter.addWidget(left_panel)

        # Right: Army editor
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)

        placeholder = QLabel("Add or select a military force")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor_scroll.setWidget(placeholder)

        splitter.addWidget(self.editor_scroll)

        layout.addWidget(splitter)

    def _add_army(self):
        """Add new army."""
        name, ok = QInputDialog.getText(self, "New Army", "Enter army name:")

        if ok and name:
            army = Army(
                id=str(uuid.uuid4()),
                name=name,
                faction_id=""
            )
            self.armies.append(army)

            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, army.id)
            self.army_list.addItem(item)

            self.army_list.setCurrentItem(item)

    def _remove_army(self):
        """Remove selected army."""
        current = self.army_list.currentItem()
        if current:
            army_id = current.data(Qt.ItemDataRole.UserRole)
            self.armies = [a for a in self.armies if a.id != army_id]
            self.army_list.takeItem(self.army_list.row(current))

            # Show placeholder
            placeholder = QLabel("Add or select a military force")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.editor_scroll.setWidget(placeholder)

    def _on_army_selected(self, current, previous):
        """Handle army selection."""
        if not current:
            return

        # Save previous
        if self.current_editor:
            self.current_editor.save_to_model()

        # Load selected
        army_id = current.data(Qt.ItemDataRole.UserRole)
        army = next((a for a in self.armies if a.id == army_id), None)

        if army:
            self.current_editor = ArmyEditor(army)
            self.current_editor.content_changed.connect(self.content_changed.emit)
            self.editor_scroll.setWidget(self.current_editor)

    def get_armies(self) -> List[Army]:
        """Get all armies."""
        if self.current_editor:
            self.current_editor.save_to_model()
        return self.armies

    def load_armies(self, armies: List[Army]):
        """Load armies."""
        self.armies = armies
        self.army_list.clear()

        for army in armies:
            item = QListWidgetItem(army.name)
            item.setData(Qt.ItemDataRole.UserRole, army.id)
            self.army_list.addItem(item)
