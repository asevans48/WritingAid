"""Politics builder with government tree structure."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox,
    QFormLayout, QGroupBox, QScrollArea, QSplitter, QInputDialog,
    QTreeWidget, QTreeWidgetItem, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal
from typing import List, Optional
import uuid

from src.models.worldbuilding_objects import PoliticalSystem, GovernmentBranch


class GovernmentBranchEditor(QWidget):
    """Editor for a government branch."""

    content_changed = pyqtSignal()

    def __init__(self, branch: GovernmentBranch):
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
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "Executive", "Legislative", "Judicial", "Military",
            "Administrative", "Ceremonial", "Other"
        ])
        form.addRow("Type:", self.type_combo)

        # Head
        self.head_edit = QLineEdit()
        self.head_edit.setPlaceholderText("Character name or title")
        form.addRow("Head:", self.head_edit)

        # Headquarters
        self.hq_edit = QLineEdit()
        form.addRow("Headquarters:", self.hq_edit)

        layout.addLayout(form)

        # Members
        members_group = QGroupBox("Members")
        members_layout = QVBoxLayout(members_group)

        self.members_list = QListWidget()
        members_layout.addWidget(self.members_list)

        members_btn_layout = QHBoxLayout()
        add_member_btn = QPushButton("Add Member")
        add_member_btn.clicked.connect(self._add_member)
        members_btn_layout.addWidget(add_member_btn)

        remove_member_btn = QPushButton("Remove")
        remove_member_btn.clicked.connect(self._remove_member)
        members_btn_layout.addWidget(remove_member_btn)

        members_layout.addLayout(members_btn_layout)
        layout.addWidget(members_group)

        # Powers
        powers_group = QGroupBox("Powers & Authorities")
        powers_layout = QVBoxLayout(powers_group)

        self.powers_list = QListWidget()
        powers_layout.addWidget(self.powers_list)

        powers_btn_layout = QHBoxLayout()
        add_power_btn = QPushButton("Add Power")
        add_power_btn.clicked.connect(self._add_power)
        powers_btn_layout.addWidget(add_power_btn)

        remove_power_btn = QPushButton("Remove")
        remove_power_btn.clicked.connect(self._remove_power)
        powers_btn_layout.addWidget(remove_power_btn)

        powers_layout.addLayout(powers_btn_layout)
        layout.addWidget(powers_group)

        # Description
        desc_label = QLabel("Description:")
        layout.addWidget(desc_label)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(100)
        layout.addWidget(self.description_edit)

    def _load_branch(self):
        """Load branch data."""
        self.name_edit.setText(self.branch.name)
        self.type_combo.setCurrentText(self.branch.branch_type)
        if self.branch.head:
            self.head_edit.setText(self.branch.head)
        if self.branch.headquarters:
            self.hq_edit.setText(self.branch.headquarters)
        self.description_edit.setPlainText(self.branch.description)

        for member in self.branch.members:
            self.members_list.addItem(member)

        for power in self.branch.powers:
            self.powers_list.addItem(power)

    def _add_member(self):
        """Add member."""
        name, ok = QInputDialog.getText(self, "Add Member", "Enter character name:")
        if ok and name:
            self.members_list.addItem(name)

    def _remove_member(self):
        """Remove member."""
        current = self.members_list.currentRow()
        if current >= 0:
            self.members_list.takeItem(current)

    def _add_power(self):
        """Add power."""
        text, ok = QInputDialog.getText(self, "Add Power", "Enter power/authority:")
        if ok and text:
            self.powers_list.addItem(text)

    def _remove_power(self):
        """Remove power."""
        current = self.powers_list.currentRow()
        if current >= 0:
            self.powers_list.takeItem(current)

    def save_to_model(self):
        """Save to branch model."""
        self.branch.name = self.name_edit.text()
        self.branch.branch_type = self.type_combo.currentText()
        self.branch.head = self.head_edit.text()
        self.branch.headquarters = self.hq_edit.text()
        self.branch.description = self.description_edit.toPlainText()

        self.branch.members = [
            self.members_list.item(i).text()
            for i in range(self.members_list.count())
        ]

        self.branch.powers = [
            self.powers_list.item(i).text()
            for i in range(self.powers_list.count())
        ]


class GovernmentTreeWidget(QWidget):
    """Tree visualization of government structure."""

    branch_selected = pyqtSignal(str)  # branch ID

    def __init__(self, political_system: PoliticalSystem):
        """Initialize government tree."""
        super().__init__()
        self.political_system = political_system
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel("Government Structure")
        label.setStyleSheet("font-weight: 600; font-size: 13px; padding: 8px;")
        layout.addWidget(label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Branch", "Type", "Head"])
        self.tree.setStyleSheet("""
            QTreeWidget {
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
            }
            QTreeWidget::item {
                padding: 8px;
            }
            QTreeWidget::item:selected {
                background-color: #6366f1;
                color: white;
            }
        """)
        self.tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree)

        # Add/Remove branch buttons
        btn_layout = QHBoxLayout()

        add_child_btn = QPushButton("Add Sub-Branch")
        add_child_btn.clicked.connect(self._add_sub_branch)
        btn_layout.addWidget(add_child_btn)

        remove_btn = QPushButton("Remove Branch")
        remove_btn.clicked.connect(self._remove_branch)
        btn_layout.addWidget(remove_btn)

        layout.addLayout(btn_layout)

    def load_tree(self):
        """Load political system into tree."""
        self.tree.clear()

        # Create map of branches by ID
        branches_by_id = {branch.id: branch for branch in self.political_system.branches}

        # Find top-level branches (no parent)
        top_level_branches = [b for b in self.political_system.branches if not b.parent_branch_id]

        for branch in top_level_branches:
            item = self._create_tree_item(branch)
            self.tree.addTopLevelItem(item)
            self._load_sub_branches(branch, item, branches_by_id)

        self.tree.expandAll()

    def _create_tree_item(self, branch: GovernmentBranch) -> QTreeWidgetItem:
        """Create tree widget item from branch."""
        head = branch.head if branch.head else "Vacant"

        item = QTreeWidgetItem([branch.name, branch.branch_type, head])
        item.setData(0, Qt.ItemDataRole.UserRole, branch.id)
        return item

    def _load_sub_branches(self, parent_branch: GovernmentBranch, parent_item: QTreeWidgetItem, branches_map: dict):
        """Recursively load sub-branches."""
        for sub_id in parent_branch.sub_branches:
            sub_branch = branches_map.get(sub_id)
            if sub_branch:
                child_item = self._create_tree_item(sub_branch)
                parent_item.addChild(child_item)
                self._load_sub_branches(sub_branch, child_item, branches_map)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle item click."""
        branch_id = item.data(0, Qt.ItemDataRole.UserRole)
        if branch_id:
            self.branch_selected.emit(branch_id)

    def _add_sub_branch(self):
        """Add sub-branch to selected branch."""
        current_item = self.tree.currentItem()
        if not current_item:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No Selection", "Please select a parent branch first.")
            return

        parent_id = current_item.data(0, Qt.ItemDataRole.UserRole)

        name, ok = QInputDialog.getText(self, "New Branch", "Enter branch name:")
        if ok and name:
            # Create new branch
            new_branch = GovernmentBranch(
                id=str(uuid.uuid4()),
                name=name,
                branch_type="Other",
                parent_branch_id=parent_id
            )
            self.political_system.branches.append(new_branch)

            # Add to parent's sub-branches
            parent_branch = next((b for b in self.political_system.branches if b.id == parent_id), None)
            if parent_branch:
                parent_branch.sub_branches.append(new_branch.id)

            # Reload tree
            self.load_tree()

    def _remove_branch(self):
        """Remove selected branch and all sub-branches."""
        current_item = self.tree.currentItem()
        if not current_item:
            return

        branch_id = current_item.data(0, Qt.ItemDataRole.UserRole)

        # Find and remove branch
        branch = next((b for b in self.political_system.branches if b.id == branch_id), None)
        if branch:
            # Remove from parent's sub-branches list
            if branch.parent_branch_id:
                parent = next((b for b in self.political_system.branches if b.id == branch.parent_branch_id), None)
                if parent and branch_id in parent.sub_branches:
                    parent.sub_branches.remove(branch_id)

            # Recursively remove all sub-branches
            self._remove_branch_recursive(branch_id)

            # Reload tree
            self.load_tree()

    def _remove_branch_recursive(self, branch_id: str):
        """Recursively remove branch and all sub-branches."""
        branch = next((b for b in self.political_system.branches if b.id == branch_id), None)
        if branch:
            # Remove all sub-branches first
            for sub_id in branch.sub_branches[:]:
                self._remove_branch_recursive(sub_id)

            # Remove this branch
            self.political_system.branches = [b for b in self.political_system.branches if b.id != branch_id]


class PoliticalSystemEditor(QWidget):
    """Editor for a political system."""

    content_changed = pyqtSignal()

    def __init__(self, political_system: PoliticalSystem):
        """Initialize political system editor."""
        super().__init__()
        self.political_system = political_system
        self.current_branch_editor: Optional[GovernmentBranchEditor] = None
        self._init_ui()
        self._load_system()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        # Tabs
        tabs = QTabWidget()

        # Basic Info Tab
        basic_tab = self._create_basic_tab()
        tabs.addTab(basic_tab, "Basic Info")

        # Government Structure Tab
        structure_tab = self._create_structure_tab()
        tabs.addTab(structure_tab, "Government Structure")

        # Parties Tab
        parties_tab = self._create_parties_tab()
        tabs.addTab(parties_tab, "Political Parties")

        layout.addWidget(tabs)

    def _create_basic_tab(self) -> QWidget:
        """Create basic info tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        self.faction_edit = QLineEdit()
        layout.addRow("Faction ID:", self.faction_edit)

        self.system_type_edit = QLineEdit()
        self.system_type_edit.setPlaceholderText("Democracy, Monarchy, Dictatorship, etc.")
        layout.addRow("System Type:", self.system_type_edit)

        self.constitution_edit = QTextEdit()
        layout.addRow("Constitution/Charter:", self.constitution_edit)

        return widget

    def _create_structure_tab(self) -> QWidget:
        """Create government structure tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Splitter for tree and branch editor
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Government tree
        self.tree_widget = GovernmentTreeWidget(self.political_system)
        self.tree_widget.branch_selected.connect(self._on_branch_selected)
        splitter.addWidget(self.tree_widget)

        # Right: Branch editor
        self.branch_editor_scroll = QScrollArea()
        self.branch_editor_scroll.setWidgetResizable(True)

        placeholder = QLabel("Select a branch to edit")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.branch_editor_scroll.setWidget(placeholder)

        splitter.addWidget(self.branch_editor_scroll)

        layout.addWidget(splitter)

        return widget

    def _create_parties_tab(self) -> QWidget:
        """Create political parties tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Ruling party
        ruling_group = QGroupBox("Ruling Party")
        ruling_layout = QFormLayout(ruling_group)

        self.ruling_party_edit = QLineEdit()
        ruling_layout.addRow("Party Name:", self.ruling_party_edit)

        layout.addWidget(ruling_group)

        # Opposition parties
        opp_label = QLabel("Opposition Parties:")
        layout.addWidget(opp_label)

        self.opposition_list = QListWidget()
        layout.addWidget(self.opposition_list)

        opp_btn_layout = QHBoxLayout()
        add_opp_btn = QPushButton("Add Party")
        add_opp_btn.clicked.connect(self._add_opposition)
        opp_btn_layout.addWidget(add_opp_btn)

        remove_opp_btn = QPushButton("Remove")
        remove_opp_btn.clicked.connect(self._remove_opposition)
        opp_btn_layout.addWidget(remove_opp_btn)

        layout.addLayout(opp_btn_layout)

        return widget

    def _load_system(self):
        """Load political system data."""
        self.faction_edit.setText(self.political_system.faction_id)
        self.system_type_edit.setText(self.political_system.system_type)
        self.constitution_edit.setPlainText(self.political_system.constitution)

        # Load tree
        self.tree_widget.load_tree()

        # Load parties
        if self.political_system.ruling_party:
            self.ruling_party_edit.setText(self.political_system.ruling_party)

        for party in self.political_system.opposition_parties:
            self.opposition_list.addItem(party)

    def _on_branch_selected(self, branch_id: str):
        """Handle branch selection."""
        # Save previous
        if self.current_branch_editor:
            self.current_branch_editor.save_to_model()

        # Load selected
        branch = next((b for b in self.political_system.branches if b.id == branch_id), None)
        if branch:
            self.current_branch_editor = GovernmentBranchEditor(branch)
            self.current_branch_editor.content_changed.connect(self.content_changed.emit)
            self.branch_editor_scroll.setWidget(self.current_branch_editor)

    def _add_opposition(self):
        """Add opposition party."""
        name, ok = QInputDialog.getText(self, "Add Party", "Enter party name:")
        if ok and name:
            self.opposition_list.addItem(name)

    def _remove_opposition(self):
        """Remove opposition party."""
        current = self.opposition_list.currentRow()
        if current >= 0:
            self.opposition_list.takeItem(current)

    def save_to_model(self):
        """Save to political system model."""
        if self.current_branch_editor:
            self.current_branch_editor.save_to_model()

        self.political_system.faction_id = self.faction_edit.text()
        self.political_system.system_type = self.system_type_edit.text()
        self.political_system.constitution = self.constitution_edit.toPlainText()
        self.political_system.ruling_party = self.ruling_party_edit.text()

        self.political_system.opposition_parties = [
            self.opposition_list.item(i).text()
            for i in range(self.opposition_list.count())
        ]


class PoliticsBuilderWidget(QWidget):
    """Widget for managing political systems."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize politics builder."""
        super().__init__()
        self.political_systems: List[PoliticalSystem] = []
        self.current_editor: Optional[PoliticalSystemEditor] = None
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QHBoxLayout(self)

        # Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Systems list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        label = QLabel("Political Systems")
        label.setStyleSheet("font-weight: 600; font-size: 13px;")
        left_layout.addWidget(label)

        self.system_list = QListWidget()
        self.system_list.currentItemChanged.connect(self._on_system_selected)
        left_layout.addWidget(self.system_list)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Add System")
        add_btn.clicked.connect(self._add_system)
        btn_layout.addWidget(add_btn)

        remove_btn = QPushButton("🗑️")
        remove_btn.setMaximumWidth(40)
        remove_btn.clicked.connect(self._remove_system)
        btn_layout.addWidget(remove_btn)

        import_btn = QPushButton("📥 Import")
        import_btn.setToolTip("Import political systems from JSON file")
        import_btn.clicked.connect(self._import_systems)
        btn_layout.addWidget(import_btn)

        left_layout.addLayout(btn_layout)

        left_panel.setMaximumWidth(250)
        splitter.addWidget(left_panel)

        # Right: System editor
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)

        placeholder = QLabel("Add or select a political system")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor_scroll.setWidget(placeholder)

        splitter.addWidget(self.editor_scroll)

        layout.addWidget(splitter)

    def _add_system(self):
        """Add new political system."""
        system_name, ok = QInputDialog.getText(self, "New Political System", "Enter political system name:")

        if ok and system_name:
            # Create default branches
            executive = GovernmentBranch(
                id=str(uuid.uuid4()),
                name="Executive",
                branch_type="Executive"
            )

            legislative = GovernmentBranch(
                id=str(uuid.uuid4()),
                name="Legislative",
                branch_type="Legislative"
            )

            judicial = GovernmentBranch(
                id=str(uuid.uuid4()),
                name="Judicial",
                branch_type="Judicial"
            )

            # Use political system name as the ID
            political_system = PoliticalSystem(
                id=system_name,
                faction_id="",  # Can be linked to faction in editor
                system_type="",
                branches=[executive, legislative, judicial]
            )
            self.political_systems.append(political_system)

            item = QListWidgetItem(system_name)
            item.setData(Qt.ItemDataRole.UserRole, political_system.id)
            self.system_list.addItem(item)

            self.system_list.setCurrentItem(item)

    def _remove_system(self):
        """Remove selected political system."""
        current = self.system_list.currentItem()
        if current:
            system_id = current.data(Qt.ItemDataRole.UserRole)
            self.political_systems = [s for s in self.political_systems if s.id != system_id]
            self.system_list.takeItem(self.system_list.row(current))

            # Clear current editor reference before replacing widget
            self.current_editor = None

            # Show placeholder
            placeholder = QLabel("Add or select a political system")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.editor_scroll.setWidget(placeholder)
            self.content_changed.emit()

    def _on_system_selected(self, current, previous):
        """Handle system selection."""
        if not current:
            return

        # Save previous
        if self.current_editor:
            self.current_editor.save_to_model()

        # Load selected
        system_id = current.data(Qt.ItemDataRole.UserRole)
        political_system = next((s for s in self.political_systems if s.id == system_id), None)

        if political_system:
            self.current_editor = PoliticalSystemEditor(political_system)
            self.current_editor.content_changed.connect(self.content_changed.emit)
            self.editor_scroll.setWidget(self.current_editor)

    def get_political_systems(self) -> List[PoliticalSystem]:
        """Get all political systems."""
        if self.current_editor:
            self.current_editor.save_to_model()
        return self.political_systems

    def _import_systems(self):
        """Import political systems from JSON file."""
        from src.ui.worldbuilding.worldbuilding_importer import show_import_dialog
        from src.models.worldbuilding_objects import CompleteWorldBuilding

        temp_wb = CompleteWorldBuilding(political_systems=self.political_systems)
        result = show_import_dialog(self, temp_wb, target_section="political_systems")

        if result and result.imported_counts.get("political_systems", 0) > 0:
            self.political_systems = temp_wb.political_systems
            self.load_political_systems(self.political_systems)
            self.content_changed.emit()

    def load_political_systems(self, systems: List[PoliticalSystem]):
        """Load political systems."""
        self.political_systems = systems
        self.system_list.clear()

        for system in systems:
            # Display the system ID (which is the political system name)
            item = QListWidgetItem(system.id)
            item.setData(Qt.ItemDataRole.UserRole, system.id)
            self.system_list.addItem(item)
