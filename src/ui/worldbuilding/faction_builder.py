"""Faction builder - central hub tying all worldbuilding together."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox, QSpinBox,
    QFormLayout, QGroupBox, QScrollArea, QInputDialog, QTabWidget,
    QDialog, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont
from typing import List, Optional, Dict, Tuple
import uuid
import math

from src.models.worldbuilding_objects import Faction, FactionType
from src.ui.worldbuilding.filter_sort_widget import FilterSortWidget


class FactionRelationshipGraph(QWidget):
    """Visual graph showing faction relationships."""

    faction_clicked = pyqtSignal(str)  # faction ID

    def __init__(self):
        """Initialize faction relationship graph."""
        super().__init__()
        self.factions: List[Faction] = []
        self.faction_positions: Dict[str, Tuple[float, float]] = {}
        self.setMinimumHeight(400)
        self.setMinimumWidth(500)
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
            FactionType.ECONOMIC_CLASS: "#14b8a6", # Teal
            FactionType.MINORITY_GROUP: "#f97316", # Orange
            FactionType.POLITICAL_PARTY: "#dc2626", # Red
            FactionType.GUILD: "#ca8a04",         # Yellow/Gold
            FactionType.MILITARY: "#059669",      # Emerald
            FactionType.CRIMINAL: "#7c3aed",      # Violet
            FactionType.RESISTANCE: "#be185d",    # Rose
            FactionType.INDIVIDUAL: "#ec4899",    # Pink
            FactionType.OTHER: "#6b7280"          # Gray
        }
        return colors.get(faction_type, "#6b7280")

    def resizeEvent(self, event):
        """Recalculate positions on resize."""
        super().resizeEvent(event)
        self._calculate_positions()


class FactionRelationshipGraphDialog(QDialog):
    """Popup dialog showing faction relationship graph."""

    def __init__(self, factions: List[Faction], parent=None):
        """Initialize dialog."""
        super().__init__(parent)
        self.setWindowTitle("Faction Relationships")
        self.resize(800, 600)
        self._init_ui(factions)

    def _init_ui(self, factions: List[Faction]):
        """Initialize UI."""
        layout = QVBoxLayout(self)

        # Legend
        legend_layout = QHBoxLayout()
        legend_layout.addWidget(QLabel("Legend:"))

        ally_label = QLabel("━ Allies")
        ally_label.setStyleSheet("color: #10b981; font-weight: bold;")
        legend_layout.addWidget(ally_label)

        enemy_label = QLabel("- - Enemies")
        enemy_label.setStyleSheet("color: #ef4444; font-weight: bold;")
        legend_layout.addWidget(enemy_label)

        legend_layout.addStretch()
        layout.addLayout(legend_layout)

        # Graph
        self.graph = FactionRelationshipGraph()
        self.graph.set_factions(factions)
        layout.addWidget(self.graph)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class FactionEditor(QDialog):
    """Dialog for editing a faction."""

    def __init__(self, faction: Optional[Faction] = None, available_factions: List[Faction] = None, parent=None):
        """Initialize faction editor dialog."""
        super().__init__(parent)
        self.faction = faction or Faction(
            id="",
            name="",
            faction_type=FactionType.NATION
        )
        self.available_factions = available_factions or []
        self._init_ui()
        if faction:
            self._load_faction()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Faction Editor")
        self.resize(750, 600)

        layout = QVBoxLayout(self)

        # Create scrollable area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        # Tabs for organization
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

        scroll_layout.addWidget(tabs)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _create_basic_tab(self) -> QWidget:
        """Create basic info tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Faction name")
        layout.addRow("Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value.title() for t in FactionType])
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
        self.description_edit.setMaximumHeight(100)
        self.description_edit.setPlaceholderText("Description of this faction...")
        layout.addRow("Description:", self.description_edit)

        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)
        self.notes_edit.setPlaceholderText("Additional notes...")
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
        self.territory_list.setMaximumHeight(120)
        territory_layout.addWidget(self.territory_list)

        terr_btn_layout = QHBoxLayout()
        add_terr_btn = QPushButton("Add Territory")
        add_terr_btn.clicked.connect(self._add_territory)
        terr_btn_layout.addWidget(add_terr_btn)

        remove_terr_btn = QPushButton("Remove")
        remove_terr_btn.clicked.connect(self._remove_territory)
        terr_btn_layout.addWidget(remove_terr_btn)
        terr_btn_layout.addStretch()

        territory_layout.addLayout(terr_btn_layout)
        layout.addWidget(territory_group)

        # Resources
        resources_group = QGroupBox("Resources")
        resources_layout = QVBoxLayout(resources_group)

        resources_help = QLabel("Resource name and quantity")
        resources_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        resources_layout.addWidget(resources_help)

        self.resources_list = QListWidget()
        self.resources_list.setMaximumHeight(120)
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
        res_btn_layout.addStretch()

        resources_layout.addLayout(res_btn_layout)
        layout.addWidget(resources_group)

        layout.addStretch()
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
        self.allies_list.setMaximumHeight(120)
        allies_layout.addWidget(self.allies_list)

        allies_btn_layout = QHBoxLayout()
        add_ally_btn = QPushButton("Add Ally")
        add_ally_btn.clicked.connect(self._add_ally)
        allies_btn_layout.addWidget(add_ally_btn)

        remove_ally_btn = QPushButton("Remove")
        remove_ally_btn.clicked.connect(self._remove_ally)
        allies_btn_layout.addWidget(remove_ally_btn)
        allies_btn_layout.addStretch()

        allies_layout.addLayout(allies_btn_layout)
        layout.addWidget(allies_group)

        # Enemies
        enemies_group = QGroupBox("Enemy Factions")
        enemies_layout = QVBoxLayout(enemies_group)

        enemies_help = QLabel("Select enemy factions from the dropdown")
        enemies_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        enemies_layout.addWidget(enemies_help)

        self.enemies_list = QListWidget()
        self.enemies_list.setMaximumHeight(120)
        enemies_layout.addWidget(self.enemies_list)

        enemies_btn_layout = QHBoxLayout()
        add_enemy_btn = QPushButton("Add Enemy")
        add_enemy_btn.clicked.connect(self._add_enemy)
        enemies_btn_layout.addWidget(add_enemy_btn)

        remove_enemy_btn = QPushButton("Remove")
        remove_enemy_btn.clicked.connect(self._remove_enemy)
        enemies_btn_layout.addWidget(remove_enemy_btn)
        enemies_btn_layout.addStretch()

        enemies_layout.addLayout(enemies_btn_layout)
        layout.addWidget(enemies_group)

        layout.addStretch()
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

        # Connected systems info
        connections_group = QGroupBox("Connected Systems")
        connections_layout = QVBoxLayout(connections_group)

        connections_help = QLabel("This faction connects to:")
        connections_help.setStyleSheet("font-weight: 600; margin-top: 8px;")
        connections_layout.addWidget(connections_help)

        connections_info = QLabel(
            "• Political System (Government)\n"
            "• Economic System (Trade & Commerce)\n"
            "• Military Forces (Armies & Branches)\n"
            "• Power Hierarchy (Leadership Structure)\n"
            "• Historical Events (Timeline)\n"
            "• Characters (Members & Leaders)\n"
            "• Planets (Territory)\n"
            "• Mythology (Beliefs & Legends)"
        )
        connections_info.setStyleSheet("color: #6b7280; font-size: 11px; padding: 8px;")
        connections_layout.addWidget(connections_info)

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
            item.setData(Qt.ItemDataRole.UserRole, ally_id)
            self.allies_list.addItem(item)

        # Enemies - display faction names instead of IDs
        for enemy_id in self.faction.enemies:
            faction_name = self._get_faction_name(enemy_id)
            item = QListWidgetItem(faction_name)
            item.setData(Qt.ItemDataRole.UserRole, enemy_id)
            self.enemies_list.addItem(item)

        # Power
        self.military_spin.setValue(self.faction.military_strength)
        self.economic_spin.setValue(self.faction.economic_power)

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
        """Get faction name from ID."""
        for faction in self.available_factions:
            if faction.id == faction_id:
                return faction.name
        return faction_id

    def _save(self):
        """Save faction data."""
        name = self.name_edit.text().strip()
        if not name:
            return

        if not self.faction.id:
            self.faction.id = str(uuid.uuid4())

        self.faction.name = name
        self.faction.faction_type = FactionType(self.type_combo.currentText().lower())
        self.faction.leader = self.leader_edit.text().strip()
        self.faction.founded_date = self.founded_edit.text().strip()
        self.faction.capital = self.capital_edit.text().strip()
        self.faction.government_type = self.government_edit.text().strip()
        self.faction.description = self.description_edit.toPlainText().strip()
        self.faction.notes = self.notes_edit.toPlainText().strip()
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

        self.accept()

    def get_faction(self) -> Faction:
        """Get the edited faction."""
        return self.faction


class FactionBuilderWidget(QWidget):
    """Widget for managing factions - central hub of worldbuilding."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize faction builder."""
        super().__init__()
        self.factions: List[Faction] = []
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(16, 12, 16, 8)

        header = QLabel("Factions")
        header.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header_layout.addWidget(header)

        subtitle = QLabel("Central hub - factions connect to all other worldbuilding elements")
        subtitle.setStyleSheet("font-size: 12px; color: #6b7280;")
        header_layout.addWidget(subtitle)

        layout.addWidget(header_widget)

        # Filter/Sort controls
        self.filter_sort = FilterSortWidget(
            sort_options=["Name", "Type"],
            filter_placeholder="Search factions..."
        )
        self.filter_sort.set_filter_options(["All"] + [t.value.title() for t in FactionType])
        self.filter_sort.filter_changed.connect(self._update_list)
        layout.addWidget(self.filter_sort)

        # Toolbar
        toolbar = QHBoxLayout()

        add_btn = QPushButton("Add Faction")
        add_btn.clicked.connect(self._add_faction)
        toolbar.addWidget(add_btn)

        self.edit_btn = QPushButton("Edit")
        self.edit_btn.clicked.connect(self._edit_faction)
        self.edit_btn.setEnabled(False)
        toolbar.addWidget(self.edit_btn)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_faction)
        self.remove_btn.setEnabled(False)
        toolbar.addWidget(self.remove_btn)

        toolbar.addSpacing(16)

        # View Relationships Graph button
        view_graph_btn = QPushButton("View Relationship Graph")
        view_graph_btn.clicked.connect(self._show_relationship_graph)
        toolbar.addWidget(view_graph_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Faction list
        self.faction_list = QListWidget()
        self.faction_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.faction_list.itemDoubleClicked.connect(self._edit_faction)
        self.faction_list.setStyleSheet("""
            QListWidget {
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
            }
            QListWidget::item {
                padding: 8px;
                border-radius: 4px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background-color: #6366f1;
                color: white;
            }
        """)
        layout.addWidget(self.faction_list)

    def _update_list(self):
        """Update faction list display."""
        self.faction_list.clear()

        # Filter and sort functions
        def get_searchable_text(faction):
            return f"{faction.name} {faction.faction_type.value} {faction.description or ''}"

        def get_sort_value(faction, key):
            if key == "Name":
                return faction.name.lower()
            elif key == "Type":
                return faction.faction_type.value
            return faction.name.lower()

        def get_type(faction):
            return faction.faction_type.value.title()

        filtered_factions = self.filter_sort.filter_and_sort(
            self.factions, get_searchable_text, get_sort_value, get_type
        )

        for faction in filtered_factions:
            type_display = faction.faction_type.value.title()

            # Add ally/enemy counts
            relations_text = ""
            if faction.allies or faction.enemies:
                parts = []
                if faction.allies:
                    parts.append(f"{len(faction.allies)} allies")
                if faction.enemies:
                    parts.append(f"{len(faction.enemies)} enemies")
                relations_text = f" - {', '.join(parts)}"

            item_text = f"{faction.name} ({type_display}){relations_text}"

            # Add truncated description if available
            if faction.description:
                desc = faction.description[:50] + "..." if len(faction.description) > 50 else faction.description
                item_text += f" - {desc}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, faction.id)
            self.faction_list.addItem(item)

    def _on_selection_changed(self):
        """Handle selection change."""
        has_selection = bool(self.faction_list.selectedItems())
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def _add_faction(self):
        """Add new faction."""
        editor = FactionEditor(available_factions=self.factions, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            faction = editor.get_faction()
            self.factions.append(faction)
            self._update_list()
            self.content_changed.emit()

    def _edit_faction(self):
        """Edit selected faction."""
        items = self.faction_list.selectedItems()
        if not items:
            return

        faction_id = items[0].data(Qt.ItemDataRole.UserRole)
        faction = next((f for f in self.factions if f.id == faction_id), None)
        if not faction:
            return

        editor = FactionEditor(faction=faction, available_factions=self.factions, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_list()
            self.content_changed.emit()

    def _remove_faction(self):
        """Remove selected faction."""
        items = self.faction_list.selectedItems()
        if not items:
            return

        faction_id = items[0].data(Qt.ItemDataRole.UserRole)
        faction_name = next((f.name for f in self.factions if f.id == faction_id), "")

        # Confirm deletion
        reply = QMessageBox.question(
            self,
            "Remove Faction",
            f"Are you sure you want to remove '{faction_name}'?\n\n"
            "This will also remove references to this faction from:\n"
            "• Other factions' allies and enemies lists\n"
            "• Mythology associations\n"
            "• Technology associations",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Remove faction references from other factions
        for faction in self.factions:
            if faction_id in faction.allies:
                faction.allies.remove(faction_id)
            if faction_id in faction.enemies:
                faction.enemies.remove(faction_id)

        current_row = self.faction_list.row(items[0])
        self.factions = [f for f in self.factions if f.id != faction_id]
        self._update_list()

        # Select next available faction if any exist
        if self.faction_list.count() > 0:
            next_row = min(current_row, self.faction_list.count() - 1)
            self.faction_list.setCurrentRow(next_row)

        self.content_changed.emit()

    def _show_relationship_graph(self):
        """Show faction relationship graph in popup."""
        if not self.factions:
            QMessageBox.information(self, "No Factions", "Add factions to view the relationship graph.")
            return

        dialog = FactionRelationshipGraphDialog(self.factions, self)
        dialog.exec()

    def get_factions(self) -> List[Faction]:
        """Get all factions."""
        return self.factions

    def load_factions(self, factions: List[Faction]):
        """Load factions."""
        self.factions = factions
        self._update_list()
