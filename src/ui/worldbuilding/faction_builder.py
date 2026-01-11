"""Faction builder - central hub tying all worldbuilding together."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox, QSpinBox,
    QFormLayout, QGroupBox, QScrollArea, QSplitter, QInputDialog, QTabWidget,
    QDialog, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QBrush
from typing import List, Optional, Dict, Tuple
import uuid
import math

from src.models.worldbuilding_objects import Faction, FactionType


class FactionRelationshipGraph(QWidget):
    """Visual graph showing faction relationships."""

    faction_clicked = pyqtSignal(str)  # faction ID

    def __init__(self):
        """Initialize faction relationship graph."""
        super().__init__()
        self.factions: List[Faction] = []
        self.faction_positions: Dict[str, Tuple[float, float]] = {}
        self.setMinimumHeight(250)
        self.setMaximumHeight(250)
        self.setStyleSheet("background-color: white; border: 1px solid #e5e7eb; border-radius: 8px;")

    def set_factions(self, factions: List[Faction]):
        """Set factions to display."""
        self.factions = factions
        self._calculate_positions()
        self.update()

    def _calculate_positions(self):
        """Calculate circular positions for factions."""
        if not self.factions:
            return

        num_factions = len(self.factions)
        center_x = self.width() / 2
        center_y = self.height() / 2
        radius = min(self.width(), self.height()) / 2.5

        for i, faction in enumerate(self.factions):
            angle = (2 * math.pi * i) / num_factions - math.pi / 2  # Start at top
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            self.faction_positions[faction.id] = (x, y)

    def paintEvent(self, event):
        """Draw faction relationship graph."""
        super().paintEvent(event)

        if not self.factions:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QColor("#9ca3af"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Add factions to see relationship web")
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw relationships first (behind nodes)
        for faction in self.factions:
            from_pos = self.faction_positions.get(faction.id)
            if not from_pos:
                continue

            # Draw ally connections (green)
            for ally_id in faction.allies:
                to_pos = self.faction_positions.get(ally_id)
                if to_pos:
                    pen = QPen(QColor("#10b981"), 2)  # Green
                    painter.setPen(pen)
                    painter.drawLine(
                        int(from_pos[0]), int(from_pos[1]),
                        int(to_pos[0]), int(to_pos[1])
                    )

            # Draw enemy connections (red, dashed)
            for enemy_id in faction.enemies:
                to_pos = self.faction_positions.get(enemy_id)
                if to_pos:
                    pen = QPen(QColor("#ef4444"), 2)  # Red
                    pen.setStyle(Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    painter.drawLine(
                        int(from_pos[0]), int(from_pos[1]),
                        int(to_pos[0]), int(to_pos[1])
                    )

        # Draw faction nodes
        for faction in self.factions:
            pos = self.faction_positions.get(faction.id)
            if not pos:
                continue

            x, y = pos

            # Node color based on type
            color = self._get_faction_color(faction.faction_type)

            # Node circle
            painter.setBrush(QColor(color))
            painter.setPen(QPen(QColor("white"), 3))
            painter.drawEllipse(int(x - 20), int(y - 20), 40, 40)

            # Faction name below
            font = QFont("Segoe UI", 9, QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QColor("#1a1a1a"))

            # Shortened name
            name = faction.name[:15] if len(faction.name) > 15 else faction.name
            text_rect = QRectF(x - 50, y + 25, 100, 25)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, name)

    def _get_faction_color(self, faction_type: FactionType) -> str:
        """Get color based on faction type."""
        colors = {
            FactionType.NATION: "#6366f1",        # Indigo
            FactionType.ORGANIZATION: "#8b5cf6",  # Purple
            FactionType.RELIGION: "#f59e0b",      # Amber
            FactionType.TRIBE: "#10b981",         # Green
            FactionType.CORPORATION: "#3b82f6",   # Blue
            FactionType.INDIVIDUAL: "#ec4899",    # Pink
            FactionType.OTHER: "#6b7280"          # Gray
        }
        return colors.get(faction_type, "#6b7280")

    def resizeEvent(self, event):
        """Recalculate positions on resize."""
        super().resizeEvent(event)
        self._calculate_positions()


class FactionEditor(QWidget):
    """Editor for a faction."""

    content_changed = pyqtSignal()

    def __init__(self, faction: Faction, available_factions: List[Faction] = None):
        """Initialize faction editor.

        Args:
            faction: Faction to edit
            available_factions: List of all available factions for relationship selection
        """
        super().__init__()
        self.faction = faction
        self.available_factions = available_factions or []
        self._init_ui()
        self._load_faction()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        # Tabs
        tabs = QTabWidget()

        # Basic Info Tab
        basic_tab = self._create_basic_tab()
        tabs.addTab(basic_tab, "Basic Info")

        # Territory Tab
        territory_tab = self._create_territory_tab()
        tabs.addTab(territory_tab, "Territory & Resources")

        # Relations Tab
        relations_tab = self._create_relations_tab()
        tabs.addTab(relations_tab, "Relations")

        # Power Tab
        power_tab = self._create_power_tab()
        tabs.addTab(power_tab, "Power & Influence")

        layout.addWidget(tabs)

    def _create_basic_tab(self) -> QWidget:
        """Create basic info tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self.content_changed.emit)
        layout.addRow("Faction Name:", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value.title() for t in FactionType])
        self.type_combo.currentTextChanged.connect(self.content_changed.emit)
        layout.addRow("Type:", self.type_combo)

        self.leader_edit = QLineEdit()
        self.leader_edit.setPlaceholderText("Character name or title")
        layout.addRow("Leader:", self.leader_edit)

        self.founded_edit = QLineEdit()
        self.founded_edit.setPlaceholderText("Year, era, or date")
        layout.addRow("Founded:", self.founded_edit)

        self.capital_edit = QLineEdit()
        self.capital_edit.setPlaceholderText("For nations")
        layout.addRow("Capital:", self.capital_edit)

        self.government_edit = QLineEdit()
        layout.addRow("Government Type:", self.government_edit)

        self.description_edit = QTextEdit()
        layout.addRow("Description:", self.description_edit)

        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(100)
        layout.addRow("Notes:", self.notes_edit)

        return widget

    def _create_territory_tab(self) -> QWidget:
        """Create territory and resources tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Territory
        territory_group = QGroupBox("Territory")
        territory_layout = QVBoxLayout(territory_group)

        territory_help = QLabel("Planets and locations controlled by this faction")
        territory_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        territory_layout.addWidget(territory_help)

        self.territory_list = QListWidget()
        territory_layout.addWidget(self.territory_list)

        terr_btn_layout = QHBoxLayout()
        add_terr_btn = QPushButton("Add Territory")
        add_terr_btn.clicked.connect(self._add_territory)
        terr_btn_layout.addWidget(add_terr_btn)

        remove_terr_btn = QPushButton("Remove")
        remove_terr_btn.clicked.connect(self._remove_territory)
        terr_btn_layout.addWidget(remove_terr_btn)

        territory_layout.addLayout(terr_btn_layout)
        layout.addWidget(territory_group)

        # Resources
        resources_group = QGroupBox("Resources")
        resources_layout = QVBoxLayout(resources_group)

        resources_help = QLabel("Resource name and quantity")
        resources_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        resources_layout.addWidget(resources_help)

        self.resources_list = QListWidget()
        resources_layout.addWidget(self.resources_list)

        res_btn_layout = QHBoxLayout()
        add_res_btn = QPushButton("Add Resource")
        add_res_btn.clicked.connect(self._add_resource)
        res_btn_layout.addWidget(add_res_btn)

        edit_res_btn = QPushButton("Edit")
        edit_res_btn.clicked.connect(self._edit_resource)
        res_btn_layout.addWidget(edit_res_btn)

        remove_res_btn = QPushButton("Remove")
        remove_res_btn.clicked.connect(self._remove_resource)
        res_btn_layout.addWidget(remove_res_btn)

        resources_layout.addLayout(res_btn_layout)
        layout.addWidget(resources_group)

        return widget

    def _create_relations_tab(self) -> QWidget:
        """Create relations tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Allies
        allies_group = QGroupBox("Allied Factions")
        allies_layout = QVBoxLayout(allies_group)

        allies_help = QLabel("Select allied factions from the dropdown")
        allies_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        allies_layout.addWidget(allies_help)

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
        enemies_group = QGroupBox("Enemy Factions")
        enemies_layout = QVBoxLayout(enemies_group)

        enemies_help = QLabel("Select enemy factions from the dropdown")
        enemies_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        enemies_layout.addWidget(enemies_help)

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

        return widget

    def _create_power_tab(self) -> QWidget:
        """Create power and influence tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        self.military_spin = QSpinBox()
        self.military_spin.setMaximum(100)
        self.military_spin.setMinimum(0)
        layout.addRow("Military Strength (0-100):", self.military_spin)

        self.economic_spin = QSpinBox()
        self.economic_spin.setMaximum(100)
        self.economic_spin.setMinimum(0)
        layout.addRow("Economic Power (0-100):", self.economic_spin)

        # Connected systems
        connections_group = QGroupBox("Connected Systems")
        connections_layout = QVBoxLayout(connections_group)

        connections_help = QLabel("This faction is connected to:")
        connections_help.setStyleSheet("font-weight: 600; margin-top: 8px;")
        connections_layout.addWidget(connections_help)

        self.connections_display = QTextEdit()
        self.connections_display.setReadOnly(True)
        self.connections_display.setMaximumHeight(150)
        self.connections_display.setStyleSheet("background-color: #f9fafb; border: 1px solid #e5e7eb;")
        connections_layout.addWidget(self.connections_display)

        refresh_btn = QPushButton("🔄 Refresh Connections")
        refresh_btn.clicked.connect(self._refresh_connections)
        connections_layout.addWidget(refresh_btn)

        layout.addRow(connections_group)

        return widget

    def _load_faction(self):
        """Load faction data."""
        self.name_edit.setText(self.faction.name)
        self.type_combo.setCurrentText(self.faction.faction_type.value.title())
        if self.faction.leader:
            self.leader_edit.setText(self.faction.leader)
        if self.faction.founded_date:
            self.founded_edit.setText(self.faction.founded_date)
        if self.faction.capital:
            self.capital_edit.setText(self.faction.capital)
        if self.faction.government_type:
            self.government_edit.setText(self.faction.government_type)
        self.description_edit.setPlainText(self.faction.description)
        self.notes_edit.setPlainText(self.faction.notes)

        # Territory
        for territory in self.faction.territory:
            self.territory_list.addItem(territory)

        # Resources
        for resource_name, quantity in self.faction.resources.items():
            self.resources_list.addItem(f"{resource_name}: {quantity}")

        # Allies - display faction names instead of IDs
        for ally_id in self.faction.allies:
            faction_name = self._get_faction_name(ally_id)
            item = QListWidgetItem(faction_name)
            item.setData(Qt.ItemDataRole.UserRole, ally_id)  # Store ID in item data
            self.allies_list.addItem(item)

        # Enemies - display faction names instead of IDs
        for enemy_id in self.faction.enemies:
            faction_name = self._get_faction_name(enemy_id)
            item = QListWidgetItem(faction_name)
            item.setData(Qt.ItemDataRole.UserRole, enemy_id)  # Store ID in item data
            self.enemies_list.addItem(item)

        # Power
        self.military_spin.setValue(self.faction.military_strength)
        self.economic_spin.setValue(self.faction.economic_power)

        self._refresh_connections()

    def _add_territory(self):
        """Add territory."""
        name, ok = QInputDialog.getText(self, "Add Territory", "Enter planet/location name:")
        if ok and name:
            self.territory_list.addItem(name)

    def _remove_territory(self):
        """Remove territory."""
        current = self.territory_list.currentRow()
        if current >= 0:
            self.territory_list.takeItem(current)

    def _add_resource(self):
        """Add resource."""
        name, ok = QInputDialog.getText(self, "Add Resource", "Enter resource name:")
        if ok and name:
            quantity, ok2 = QInputDialog.getInt(self, "Resource Quantity", "Enter quantity:", 0, 0, 999999999)
            if ok2:
                self.resources_list.addItem(f"{name}: {quantity}")

    def _edit_resource(self):
        """Edit resource."""
        current = self.resources_list.currentRow()
        if current >= 0:
            item_text = self.resources_list.item(current).text()
            parts = item_text.split(": ")
            if len(parts) == 2:
                name = parts[0]
                current_qty = int(parts[1])

                quantity, ok = QInputDialog.getInt(
                    self, "Edit Resource", f"Enter new quantity for {name}:",
                    current_qty, 0, 999999999
                )
                if ok:
                    self.resources_list.item(current).setText(f"{name}: {quantity}")

    def _remove_resource(self):
        """Remove resource."""
        current = self.resources_list.currentRow()
        if current >= 0:
            self.resources_list.takeItem(current)

    def _add_ally(self):
        """Add ally."""
        # Get list of available factions (exclude self and already allied)
        current_allies = [self.allies_list.item(i).data(Qt.ItemDataRole.UserRole)
                         for i in range(self.allies_list.count())]
        available = [f for f in self.available_factions
                    if f.id != self.faction.id and f.id not in current_allies]

        if not available:
            QMessageBox.information(self, "No Factions", "No available factions to add as allies.")
            return

        # Create dropdown with faction names
        faction_names = [f"{f.name} ({f.faction_type.value})" for f in available]
        faction_name, ok = QInputDialog.getItem(
            self, "Add Ally", "Select faction to add as ally:", faction_names, 0, False
        )

        if ok and faction_name:
            # Find the selected faction
            selected_faction = available[faction_names.index(faction_name)]
            item = QListWidgetItem(selected_faction.name)
            item.setData(Qt.ItemDataRole.UserRole, selected_faction.id)
            self.allies_list.addItem(item)

    def _remove_ally(self):
        """Remove ally."""
        current = self.allies_list.currentRow()
        if current >= 0:
            self.allies_list.takeItem(current)

    def _add_enemy(self):
        """Add enemy."""
        # Get list of available factions (exclude self and already enemies)
        current_enemies = [self.enemies_list.item(i).data(Qt.ItemDataRole.UserRole)
                          for i in range(self.enemies_list.count())]
        available = [f for f in self.available_factions
                    if f.id != self.faction.id and f.id not in current_enemies]

        if not available:
            QMessageBox.information(self, "No Factions", "No available factions to add as enemies.")
            return

        # Create dropdown with faction names
        faction_names = [f"{f.name} ({f.faction_type.value})" for f in available]
        faction_name, ok = QInputDialog.getItem(
            self, "Add Enemy", "Select faction to add as enemy:", faction_names, 0, False
        )

        if ok and faction_name:
            # Find the selected faction
            selected_faction = available[faction_names.index(faction_name)]
            item = QListWidgetItem(selected_faction.name)
            item.setData(Qt.ItemDataRole.UserRole, selected_faction.id)
            self.enemies_list.addItem(item)

    def _remove_enemy(self):
        """Remove enemy."""
        current = self.enemies_list.currentRow()
        if current >= 0:
            self.enemies_list.takeItem(current)

    def _get_faction_name(self, faction_id: str) -> str:
        """Get faction name from ID.

        Args:
            faction_id: Faction ID

        Returns:
            Faction name or ID if not found
        """
        for faction in self.available_factions:
            if faction.id == faction_id:
                return faction.name
        return faction_id  # Fallback to ID if not found

    def _refresh_connections(self):
        """Refresh connections display."""
        connections = []
        connections.append("• Political System (Government)")
        connections.append("• Economic System (Trade & Commerce)")
        connections.append("• Military Forces (Armies & Branches)")
        connections.append("• Power Hierarchy (Leadership Structure)")
        connections.append("• Historical Events (Timeline)")
        connections.append("• Characters (Members & Leaders)")
        connections.append("• Planets (Territory)")
        connections.append("• Mythology (Beliefs & Legends)")

        self.connections_display.setPlainText("\n".join(connections))

    def save_to_model(self):
        """Save to faction model."""
        self.faction.name = self.name_edit.text()
        self.faction.faction_type = FactionType(self.type_combo.currentText().lower())
        self.faction.leader = self.leader_edit.text()
        self.faction.founded_date = self.founded_edit.text()
        self.faction.capital = self.capital_edit.text()
        self.faction.government_type = self.government_edit.text()
        self.faction.description = self.description_edit.toPlainText()
        self.faction.notes = self.notes_edit.toPlainText()
        self.faction.military_strength = self.military_spin.value()
        self.faction.economic_power = self.economic_spin.value()

        self.faction.territory = [
            self.territory_list.item(i).text()
            for i in range(self.territory_list.count())
        ]

        # Parse resources
        self.faction.resources = {}
        for i in range(self.resources_list.count()):
            item_text = self.resources_list.item(i).text()
            parts = item_text.split(": ")
            if len(parts) == 2:
                self.faction.resources[parts[0]] = int(parts[1])

        # Extract ally and enemy IDs from UserRole data
        self.faction.allies = [
            self.allies_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.allies_list.count())
        ]

        self.faction.enemies = [
            self.enemies_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.enemies_list.count())
        ]


class FactionBuilderWidget(QWidget):
    """Widget for managing factions - central hub of worldbuilding."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize faction builder."""
        super().__init__()
        self.factions: List[Faction] = []
        self.current_editor: Optional[FactionEditor] = None
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Faction relationship graph
        self.relationship_graph = FactionRelationshipGraph()
        layout.addWidget(self.relationship_graph)

        # Splitter for list and editor
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Faction list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)

        list_label = QLabel("Factions")
        list_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        left_layout.addWidget(list_label)

        self.faction_list = QListWidget()
        self.faction_list.currentItemChanged.connect(self._on_faction_selected)
        self.faction_list.setStyleSheet("""
            QListWidget {
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
            }
            QListWidget::item {
                padding: 12px;
                border-radius: 6px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background-color: #6366f1;
                color: white;
            }
        """)
        left_layout.addWidget(self.faction_list)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Add Faction")
        add_btn.clicked.connect(self._add_faction)
        btn_layout.addWidget(add_btn)

        remove_btn = QPushButton("🗑️")
        remove_btn.setMaximumWidth(40)
        remove_btn.clicked.connect(self._remove_faction)
        btn_layout.addWidget(remove_btn)

        left_layout.addLayout(btn_layout)

        left_panel.setMaximumWidth(280)
        splitter.addWidget(left_panel)

        # Right: Faction editor
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)

        placeholder = QLabel("Add or select a faction to begin")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #9ca3af; font-size: 14px;")
        self.editor_scroll.setWidget(placeholder)

        splitter.addWidget(self.editor_scroll)

        layout.addWidget(splitter)

    def _add_faction(self):
        """Add new faction."""
        name, ok = QInputDialog.getText(self, "New Faction", "Enter faction name:")

        if ok and name:
            faction = Faction(
                id=str(uuid.uuid4()),
                name=name,
                faction_type=FactionType.NATION
            )
            self.factions.append(faction)

            item = QListWidgetItem(f"{name} ({faction.faction_type.value.title()})")
            item.setData(Qt.ItemDataRole.UserRole, faction.id)
            self.faction_list.addItem(item)

            self.faction_list.setCurrentItem(item)
            self._update_graph()

    def _remove_faction(self):
        """Remove selected faction."""
        current = self.faction_list.currentItem()
        if current:
            faction_id = current.data(Qt.ItemDataRole.UserRole)
            self.factions = [f for f in self.factions if f.id != faction_id]
            self.faction_list.takeItem(self.faction_list.row(current))
            self._update_graph()

            # Show placeholder
            placeholder = QLabel("Add or select a faction to begin")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #9ca3af; font-size: 14px;")
            self.editor_scroll.setWidget(placeholder)

    def _on_faction_selected(self, current, previous):
        """Handle faction selection."""
        if not current:
            return

        # Save previous
        if self.current_editor:
            self.current_editor.save_to_model()
            self._update_graph()

        # Load selected
        faction_id = current.data(Qt.ItemDataRole.UserRole)
        faction = next((f for f in self.factions if f.id == faction_id), None)

        if faction:
            self.current_editor = FactionEditor(faction, available_factions=self.factions)
            self.current_editor.content_changed.connect(self.content_changed.emit)
            self.current_editor.content_changed.connect(self._update_graph)
            self.editor_scroll.setWidget(self.current_editor)

    def _update_graph(self):
        """Update relationship graph."""
        self.relationship_graph.set_factions(self.factions)

    def get_factions(self) -> List[Faction]:
        """Get all factions."""
        if self.current_editor:
            self.current_editor.save_to_model()
        return self.factions

    def load_factions(self, factions: List[Faction]):
        """Load factions."""
        self.factions = factions
        self.faction_list.clear()

        for faction in factions:
            item = QListWidgetItem(f"{faction.name} ({faction.faction_type.value.title()})")
            item.setData(Qt.ItemDataRole.UserRole, faction.id)
            self.faction_list.addItem(item)

        self._update_graph()
