"""Power hierarchy builder with tree visualization."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox, QSpinBox,
    QFormLayout, QGroupBox, QScrollArea, QSplitter, QInputDialog,
    QTreeWidget, QTreeWidgetItem
)
from PyQt6.QtCore import Qt, pyqtSignal
from typing import List, Optional, Dict
import uuid

from src.models.worldbuilding_objects import PowerHierarchy, HierarchyNode


class HierarchyNodeEditor(QWidget):
    """Editor for a hierarchy node."""

    content_changed = pyqtSignal()

    def __init__(self, node: HierarchyNode):
        """Initialize node editor."""
        super().__init__()
        self.node = node
        self._init_ui()
        self._load_node()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        form = QFormLayout()

        # Title
        self.title_edit = QLineEdit()
        self.title_edit.textChanged.connect(self.content_changed.emit)
        form.addRow("Title/Position:", self.title_edit)

        # Held by
        self.held_by_edit = QLineEdit()
        self.held_by_edit.setPlaceholderText("Character name")
        form.addRow("Held By:", self.held_by_edit)

        # Faction
        self.faction_edit = QLineEdit()
        self.faction_edit.setPlaceholderText("Faction ID")
        form.addRow("Faction:", self.faction_edit)

        # Power level
        self.power_spin = QSpinBox()
        self.power_spin.setMaximum(100)
        self.power_spin.setMinimum(0)
        form.addRow("Power Level (0-100):", self.power_spin)

        layout.addLayout(form)

        # Responsibilities
        resp_group = QGroupBox("Responsibilities")
        resp_layout = QVBoxLayout(resp_group)

        self.responsibilities_list = QListWidget()
        resp_layout.addWidget(self.responsibilities_list)

        resp_btn_layout = QHBoxLayout()
        add_resp_btn = QPushButton("Add")
        add_resp_btn.clicked.connect(self._add_responsibility)
        resp_btn_layout.addWidget(add_resp_btn)

        remove_resp_btn = QPushButton("Remove")
        remove_resp_btn.clicked.connect(self._remove_responsibility)
        resp_btn_layout.addWidget(remove_resp_btn)

        resp_layout.addLayout(resp_btn_layout)
        layout.addWidget(resp_group)

        # Description
        desc_label = QLabel("Description:")
        layout.addWidget(desc_label)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(100)
        layout.addWidget(self.description_edit)

    def _load_node(self):
        """Load node data."""
        self.title_edit.setText(self.node.title)
        if self.node.held_by:
            self.held_by_edit.setText(self.node.held_by)
        if self.node.faction:
            self.faction_edit.setText(self.node.faction)
        self.power_spin.setValue(self.node.power_level)
        self.description_edit.setPlainText(self.node.description)

        for resp in self.node.responsibilities:
            self.responsibilities_list.addItem(resp)

    def _add_responsibility(self):
        """Add responsibility."""
        text, ok = QInputDialog.getText(self, "Add Responsibility", "Enter responsibility:")
        if ok and text:
            self.responsibilities_list.addItem(text)

    def _remove_responsibility(self):
        """Remove responsibility."""
        current = self.responsibilities_list.currentRow()
        if current >= 0:
            self.responsibilities_list.takeItem(current)

    def save_to_model(self):
        """Save to node model."""
        self.node.title = self.title_edit.text()
        self.node.held_by = self.held_by_edit.text()
        self.node.faction = self.faction_edit.text()
        self.node.power_level = self.power_spin.value()
        self.node.description = self.description_edit.toPlainText()

        self.node.responsibilities = [
            self.responsibilities_list.item(i).text()
            for i in range(self.responsibilities_list.count())
        ]


class HierarchyTreeWidget(QWidget):
    """Tree visualization of hierarchy."""

    node_selected = pyqtSignal(str)  # node ID

    def __init__(self, hierarchy: PowerHierarchy):
        """Initialize hierarchy tree."""
        super().__init__()
        self.hierarchy = hierarchy
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel("Hierarchy Tree")
        label.setStyleSheet("font-weight: 600; font-size: 13px; padding: 8px;")
        layout.addWidget(label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Position", "Held By", "Power"])
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

        # Add/Remove node buttons
        btn_layout = QHBoxLayout()

        add_child_btn = QPushButton("Add Child Node")
        add_child_btn.clicked.connect(self._add_child_node)
        btn_layout.addWidget(add_child_btn)

        remove_node_btn = QPushButton("Remove Node")
        remove_node_btn.clicked.connect(self._remove_node)
        btn_layout.addWidget(remove_node_btn)

        layout.addLayout(btn_layout)

    def load_hierarchy(self):
        """Load hierarchy into tree."""
        self.tree.clear()

        # Find root node
        root_node = next((n for n in self.hierarchy.nodes if n.id == self.hierarchy.root_node_id), None)
        if root_node:
            root_item = self._create_tree_item(root_node)
            self.tree.addTopLevelItem(root_item)
            self._load_children(root_node, root_item)
            self.tree.expandAll()

    def _create_tree_item(self, node: HierarchyNode) -> QTreeWidgetItem:
        """Create tree widget item from node."""
        held_by = node.held_by if node.held_by else "Vacant"
        power = f"{node.power_level}%"

        item = QTreeWidgetItem([node.title, held_by, power])
        item.setData(0, Qt.ItemDataRole.UserRole, node.id)
        return item

    def _load_children(self, parent_node: HierarchyNode, parent_item: QTreeWidgetItem):
        """Recursively load child nodes."""
        for child_id in parent_node.children_ids:
            child_node = next((n for n in self.hierarchy.nodes if n.id == child_id), None)
            if child_node:
                child_item = self._create_tree_item(child_node)
                parent_item.addChild(child_item)
                self._load_children(child_node, child_item)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle item click."""
        node_id = item.data(0, Qt.ItemDataRole.UserRole)
        if node_id:
            self.node_selected.emit(node_id)

    def _add_child_node(self):
        """Add child node to selected node."""
        current_item = self.tree.currentItem()
        if not current_item:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No Selection", "Please select a parent node first.")
            return

        parent_id = current_item.data(0, Qt.ItemDataRole.UserRole)

        title, ok = QInputDialog.getText(self, "New Node", "Enter position title:")
        if ok and title:
            # Create new node
            new_node = HierarchyNode(
                id=str(uuid.uuid4()),
                title=title,
                parent_id=parent_id
            )
            self.hierarchy.nodes.append(new_node)

            # Add to parent's children
            parent_node = next((n for n in self.hierarchy.nodes if n.id == parent_id), None)
            if parent_node:
                parent_node.children_ids.append(new_node.id)

            # Reload tree
            self.load_hierarchy()

    def _remove_node(self):
        """Remove selected node and all children."""
        current_item = self.tree.currentItem()
        if not current_item:
            return

        node_id = current_item.data(0, Qt.ItemDataRole.UserRole)
        if node_id == self.hierarchy.root_node_id:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Cannot Remove", "Cannot remove the root node.")
            return

        # Find and remove node
        node = next((n for n in self.hierarchy.nodes if n.id == node_id), None)
        if node:
            # Remove from parent's children list
            if node.parent_id:
                parent = next((n for n in self.hierarchy.nodes if n.id == node.parent_id), None)
                if parent and node_id in parent.children_ids:
                    parent.children_ids.remove(node_id)

            # Recursively remove all children
            self._remove_node_recursive(node_id)

            # Reload tree
            self.load_hierarchy()

    def _remove_node_recursive(self, node_id: str):
        """Recursively remove node and all children."""
        node = next((n for n in self.hierarchy.nodes if n.id == node_id), None)
        if node:
            # Remove all children first
            for child_id in node.children_ids[:]:
                self._remove_node_recursive(child_id)

            # Remove this node
            self.hierarchy.nodes = [n for n in self.hierarchy.nodes if n.id != node_id]


class HierarchyEditor(QWidget):
    """Editor for a complete hierarchy."""

    content_changed = pyqtSignal()

    def __init__(self, hierarchy: PowerHierarchy):
        """Initialize hierarchy editor."""
        super().__init__()
        self.hierarchy = hierarchy
        self.current_node_editor: Optional[HierarchyNodeEditor] = None
        self._init_ui()
        self._load_hierarchy()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        # Basic info
        info_group = QGroupBox("Hierarchy Info")
        info_layout = QFormLayout(info_group)

        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self.content_changed.emit)
        info_layout.addRow("Name:", self.name_edit)

        self.type_edit = QLineEdit()
        self.type_edit.setPlaceholderText("Government, Corporate, Religious, etc.")
        info_layout.addRow("Type:", self.type_edit)

        self.faction_edit = QLineEdit()
        info_layout.addRow("Faction ID:", self.faction_edit)

        layout.addWidget(info_group)

        # Splitter for tree and node editor
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Hierarchy tree
        self.tree_widget = HierarchyTreeWidget(self.hierarchy)
        self.tree_widget.node_selected.connect(self._on_node_selected)
        splitter.addWidget(self.tree_widget)

        # Right: Node editor
        self.node_editor_scroll = QScrollArea()
        self.node_editor_scroll.setWidgetResizable(True)

        placeholder = QLabel("Select a node to edit")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.node_editor_scroll.setWidget(placeholder)

        splitter.addWidget(self.node_editor_scroll)

        layout.addWidget(splitter)

        # Relations
        relations_layout = QHBoxLayout()

        # Allies
        allies_group = QGroupBox("Allied Hierarchies")
        allies_layout = QVBoxLayout(allies_group)

        self.allies_list = QListWidget()
        allies_layout.addWidget(self.allies_list)

        allies_btn_layout = QHBoxLayout()
        add_ally_btn = QPushButton("Add")
        add_ally_btn.clicked.connect(self._add_ally)
        allies_btn_layout.addWidget(add_ally_btn)

        remove_ally_btn = QPushButton("Remove")
        remove_ally_btn.clicked.connect(self._remove_ally)
        allies_btn_layout.addWidget(remove_ally_btn)

        allies_layout.addLayout(allies_btn_layout)
        relations_layout.addWidget(allies_group)

        # Enemies
        enemies_group = QGroupBox("Enemy Hierarchies")
        enemies_layout = QVBoxLayout(enemies_group)

        self.enemies_list = QListWidget()
        enemies_layout.addWidget(self.enemies_list)

        enemies_btn_layout = QHBoxLayout()
        add_enemy_btn = QPushButton("Add")
        add_enemy_btn.clicked.connect(self._add_enemy)
        enemies_btn_layout.addWidget(add_enemy_btn)

        remove_enemy_btn = QPushButton("Remove")
        remove_enemy_btn.clicked.connect(self._remove_enemy)
        enemies_btn_layout.addWidget(remove_enemy_btn)

        enemies_layout.addLayout(enemies_btn_layout)
        relations_layout.addWidget(enemies_group)

        layout.addLayout(relations_layout)

        # Description
        desc_label = QLabel("Description:")
        layout.addWidget(desc_label)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        layout.addWidget(self.description_edit)

    def _load_hierarchy(self):
        """Load hierarchy data."""
        self.name_edit.setText(self.hierarchy.name)
        self.type_edit.setText(self.hierarchy.hierarchy_type)
        if self.hierarchy.faction_id:
            self.faction_edit.setText(self.hierarchy.faction_id)
        self.description_edit.setPlainText(self.hierarchy.description)

        # Load tree
        self.tree_widget.load_hierarchy()

        # Load allies
        for ally in self.hierarchy.allies:
            self.allies_list.addItem(ally)

        # Load enemies
        for enemy in self.hierarchy.enemies:
            self.enemies_list.addItem(enemy)

    def _on_node_selected(self, node_id: str):
        """Handle node selection."""
        # Save previous
        if self.current_node_editor:
            self.current_node_editor.save_to_model()

        # Load selected
        node = next((n for n in self.hierarchy.nodes if n.id == node_id), None)
        if node:
            self.current_node_editor = HierarchyNodeEditor(node)
            self.current_node_editor.content_changed.connect(self.content_changed.emit)
            self.node_editor_scroll.setWidget(self.current_node_editor)

    def _add_ally(self):
        """Add ally."""
        name, ok = QInputDialog.getText(self, "Add Ally", "Enter hierarchy ID:")
        if ok and name:
            self.allies_list.addItem(name)

    def _remove_ally(self):
        """Remove ally."""
        current = self.allies_list.currentRow()
        if current >= 0:
            self.allies_list.takeItem(current)

    def _add_enemy(self):
        """Add enemy."""
        name, ok = QInputDialog.getText(self, "Add Enemy", "Enter hierarchy ID:")
        if ok and name:
            self.enemies_list.addItem(name)

    def _remove_enemy(self):
        """Remove enemy."""
        current = self.enemies_list.currentRow()
        if current >= 0:
            self.enemies_list.takeItem(current)

    def save_to_model(self):
        """Save to hierarchy model."""
        if self.current_node_editor:
            self.current_node_editor.save_to_model()

        self.hierarchy.name = self.name_edit.text()
        self.hierarchy.hierarchy_type = self.type_edit.text()
        self.hierarchy.faction_id = self.faction_edit.text()
        self.hierarchy.description = self.description_edit.toPlainText()

        self.hierarchy.allies = [
            self.allies_list.item(i).text()
            for i in range(self.allies_list.count())
        ]

        self.hierarchy.enemies = [
            self.enemies_list.item(i).text()
            for i in range(self.enemies_list.count())
        ]


class HierarchyBuilderWidget(QWidget):
    """Widget for managing power hierarchies."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize hierarchy builder."""
        super().__init__()
        self.hierarchies: List[PowerHierarchy] = []
        self.current_editor: Optional[HierarchyEditor] = None
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QHBoxLayout(self)

        # Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Hierarchy list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        label = QLabel("Power Hierarchies")
        label.setStyleSheet("font-weight: 600; font-size: 13px;")
        left_layout.addWidget(label)

        self.hierarchy_list = QListWidget()
        self.hierarchy_list.currentItemChanged.connect(self._on_hierarchy_selected)
        left_layout.addWidget(self.hierarchy_list)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Add Hierarchy")
        add_btn.clicked.connect(self._add_hierarchy)
        btn_layout.addWidget(add_btn)

        remove_btn = QPushButton("🗑️")
        remove_btn.setMaximumWidth(40)
        remove_btn.clicked.connect(self._remove_hierarchy)
        btn_layout.addWidget(remove_btn)

        left_layout.addLayout(btn_layout)

        left_panel.setMaximumWidth(250)
        splitter.addWidget(left_panel)

        # Right: Hierarchy editor
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)

        placeholder = QLabel("Add or select a hierarchy")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor_scroll.setWidget(placeholder)

        splitter.addWidget(self.editor_scroll)

        layout.addWidget(splitter)

    def _add_hierarchy(self):
        """Add new hierarchy."""
        name, ok = QInputDialog.getText(self, "New Hierarchy", "Enter hierarchy name:")

        if ok and name:
            # Create root node
            root_node = HierarchyNode(
                id=str(uuid.uuid4()),
                title="Root",
                power_level=100
            )

            hierarchy = PowerHierarchy(
                id=str(uuid.uuid4()),
                name=name,
                hierarchy_type="",
                root_node_id=root_node.id,
                nodes=[root_node]
            )
            self.hierarchies.append(hierarchy)

            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, hierarchy.id)
            self.hierarchy_list.addItem(item)

            self.hierarchy_list.setCurrentItem(item)

    def _remove_hierarchy(self):
        """Remove selected hierarchy."""
        current = self.hierarchy_list.currentItem()
        if current:
            hierarchy_id = current.data(Qt.ItemDataRole.UserRole)
            self.hierarchies = [h for h in self.hierarchies if h.id != hierarchy_id]
            self.hierarchy_list.takeItem(self.hierarchy_list.row(current))

            # Show placeholder
            placeholder = QLabel("Add or select a hierarchy")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.editor_scroll.setWidget(placeholder)

    def _on_hierarchy_selected(self, current, previous):
        """Handle hierarchy selection."""
        if not current:
            return

        # Save previous
        if self.current_editor:
            self.current_editor.save_to_model()

        # Load selected
        hierarchy_id = current.data(Qt.ItemDataRole.UserRole)
        hierarchy = next((h for h in self.hierarchies if h.id == hierarchy_id), None)

        if hierarchy:
            self.current_editor = HierarchyEditor(hierarchy)
            self.current_editor.content_changed.connect(self.content_changed.emit)
            self.editor_scroll.setWidget(self.current_editor)

    def get_hierarchies(self) -> List[PowerHierarchy]:
        """Get all hierarchies."""
        if self.current_editor:
            self.current_editor.save_to_model()
        return self.hierarchies

    def load_hierarchies(self, hierarchies: List[PowerHierarchy]):
        """Load hierarchies."""
        self.hierarchies = hierarchies
        self.hierarchy_list.clear()

        for hierarchy in hierarchies:
            item = QListWidgetItem(hierarchy.name)
            item.setData(Qt.ItemDataRole.UserRole, hierarchy.id)
            self.hierarchy_list.addItem(item)
