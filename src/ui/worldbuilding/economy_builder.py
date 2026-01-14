"""Economy builder with popup dialog editing."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QScrollArea, QInputDialog,
    QMessageBox, QDialog, QDialogButtonBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont
from typing import List, Optional, Dict, Tuple
import uuid
import math

from src.models.worldbuilding_objects import Economy, Good, TradeRoute, EconomyType, Faction
from src.ui.worldbuilding.filter_sort_widget import FilterSortWidget


class TradeRouteGraph(QWidget):
    """Visual graph showing trade routes between economies."""

    def __init__(self):
        """Initialize trade route graph."""
        super().__init__()
        self.economies: List[Economy] = []
        self.factions: List[Faction] = []
        self.economy_positions: Dict[str, Tuple[float, float]] = {}
        self.setMinimumHeight(400)
        self.setMinimumWidth(500)
        self.setStyleSheet("background-color: white; border: 1px solid #e5e7eb; border-radius: 8px;")

    def set_data(self, economies: List[Economy], factions: List[Faction]):
        """Set economies and factions to display."""
        self.economies = economies
        self.factions = factions
        self._calculate_positions()
        self.update()

    def _get_faction_name(self, faction_id: str) -> str:
        """Get faction name from ID."""
        faction = next((f for f in self.factions if f.id == faction_id), None)
        return faction.name if faction else faction_id[:8]

    def _calculate_positions(self):
        """Calculate circular positions for economies."""
        if not self.economies:
            return

        num_economies = len(self.economies)
        center_x = self.width() / 2
        center_y = self.height() / 2
        radius = min(self.width(), self.height()) / 2.5

        for i, economy in enumerate(self.economies):
            angle = (2 * math.pi * i) / num_economies - math.pi / 2  # Start at top
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            self.economy_positions[economy.id] = (x, y)

    def paintEvent(self, event):
        """Draw trade route graph."""
        super().paintEvent(event)

        if not self.economies:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QColor("#9ca3af"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Add economies to see trade network")
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Build faction->economy mapping for drawing routes
        faction_to_economy = {}
        for economy in self.economies:
            faction_to_economy[economy.faction_id] = economy.id

        # Draw trade routes first (behind nodes)
        for economy in self.economies:
            from_pos = self.economy_positions.get(economy.id)
            if not from_pos:
                continue

            # Draw trade routes
            for route in economy.trade_routes:
                # Find the economy by its faction ID
                to_economy_id = faction_to_economy.get(route.to_faction)
                if not to_economy_id:
                    continue

                to_pos = self.economy_positions.get(to_economy_id)
                if to_pos:
                    # Color based on route type
                    if route.route_type == "export":
                        color = "#3b82f6"  # Blue for exports
                    elif route.route_type == "import":
                        color = "#f59e0b"  # Amber for imports
                    else:
                        color = "#10b981"  # Green for bilateral

                    pen = QPen(QColor(color), 2)
                    painter.setPen(pen)
                    painter.drawLine(
                        int(from_pos[0]), int(from_pos[1]),
                        int(to_pos[0]), int(to_pos[1])
                    )

            # Draw trade partner connections (green, solid)
            for partner_id in economy.trade_partners:
                to_economy_id = faction_to_economy.get(partner_id)
                if not to_economy_id:
                    continue
                to_pos = self.economy_positions.get(to_economy_id)
                if to_pos:
                    pen = QPen(QColor("#10b981"), 1)  # Green, thinner
                    pen.setStyle(Qt.PenStyle.DotLine)
                    painter.setPen(pen)
                    painter.drawLine(
                        int(from_pos[0]), int(from_pos[1]),
                        int(to_pos[0]), int(to_pos[1])
                    )

            # Draw embargo connections (red, dashed)
            for embargo_id in economy.embargoes:
                to_economy_id = faction_to_economy.get(embargo_id)
                if not to_economy_id:
                    continue
                to_pos = self.economy_positions.get(to_economy_id)
                if to_pos:
                    pen = QPen(QColor("#ef4444"), 2)  # Red
                    pen.setStyle(Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    painter.drawLine(
                        int(from_pos[0]), int(from_pos[1]),
                        int(to_pos[0]), int(to_pos[1])
                    )

        # Draw economy nodes
        for economy in self.economies:
            pos = self.economy_positions.get(economy.id)
            if not pos:
                continue

            x, y = pos

            # Node color based on economy type
            color = self._get_economy_color(economy.economy_type)

            # Node circle
            painter.setBrush(QColor(color))
            painter.setPen(QPen(QColor("white"), 3))
            painter.drawEllipse(int(x - 20), int(y - 20), 40, 40)

            # Economy name below
            font = QFont("Segoe UI", 9, QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QColor("#1a1a1a"))

            # Shortened name
            name = economy.name[:15] if len(economy.name) > 15 else economy.name
            text_rect = QRectF(x - 60, y + 25, 120, 20)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, name)

            # Faction name (smaller, below economy name)
            font_small = QFont("Segoe UI", 8)
            painter.setFont(font_small)
            painter.setPen(QColor("#6b7280"))
            faction_name = self._get_faction_name(economy.faction_id)
            faction_name = faction_name[:12] if len(faction_name) > 12 else faction_name
            faction_rect = QRectF(x - 60, y + 42, 120, 20)
            painter.drawText(faction_rect, Qt.AlignmentFlag.AlignCenter, f"({faction_name})")

    def _get_economy_color(self, economy_type: EconomyType) -> str:
        """Get color based on economy type."""
        colors = {
            EconomyType.FEUDAL: "#8b5cf6",       # Purple
            EconomyType.CAPITALIST: "#3b82f6",   # Blue
            EconomyType.SOCIALIST: "#ef4444",    # Red
            EconomyType.COMMUNIST: "#dc2626",    # Darker red
            EconomyType.BARTER: "#f59e0b",       # Amber
            EconomyType.MIXED: "#10b981",        # Green
            EconomyType.TRIBAL: "#14b8a6",       # Teal
            EconomyType.MERCANTILE: "#6366f1",   # Indigo
            EconomyType.INDUSTRIAL: "#71717a",   # Gray
            EconomyType.POST_SCARCITY: "#ec4899", # Pink
            EconomyType.OTHER: "#6b7280"         # Gray
        }
        return colors.get(economy_type, "#6b7280")

    def resizeEvent(self, event):
        """Recalculate positions on resize."""
        super().resizeEvent(event)
        self._calculate_positions()


class TradeRouteGraphDialog(QDialog):
    """Popup dialog showing trade route network graph."""

    def __init__(self, economies: List[Economy], factions: List[Faction], parent=None):
        """Initialize dialog."""
        super().__init__(parent)
        self.setWindowTitle("Trade Network")
        self.resize(800, 650)
        self._init_ui(economies, factions)

    def _init_ui(self, economies: List[Economy], factions: List[Faction]):
        """Initialize UI."""
        layout = QVBoxLayout(self)

        # Legend
        legend_layout = QHBoxLayout()
        legend_layout.addWidget(QLabel("Legend:"))

        bilateral_label = QLabel("━ Bilateral Trade")
        bilateral_label.setStyleSheet("color: #10b981; font-weight: bold;")
        legend_layout.addWidget(bilateral_label)

        export_label = QLabel("━ Export")
        export_label.setStyleSheet("color: #3b82f6; font-weight: bold;")
        legend_layout.addWidget(export_label)

        import_label = QLabel("━ Import")
        import_label.setStyleSheet("color: #f59e0b; font-weight: bold;")
        legend_layout.addWidget(import_label)

        embargo_label = QLabel("- - Embargo")
        embargo_label.setStyleSheet("color: #ef4444; font-weight: bold;")
        legend_layout.addWidget(embargo_label)

        legend_layout.addStretch()
        layout.addLayout(legend_layout)

        # Graph
        self.graph = TradeRouteGraph()
        self.graph.set_data(economies, factions)
        layout.addWidget(self.graph)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class GoodEditorDialog(QDialog):
    """Dialog for editing a good."""

    def __init__(self, good: Good, parent=None):
        super().__init__(parent)
        self.good = good
        self.setWindowTitle("Edit Good")
        self.resize(400, 350)
        self._init_ui()
        self._load_good()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name of the good/resource")
        form.addRow("Name:*", self.name_edit)

        self.category_edit = QLineEdit()
        self.category_edit.setPlaceholderText("Raw material, manufactured, service, luxury, etc.")
        form.addRow("Category:", self.category_edit)

        self.value_spin = QDoubleSpinBox()
        self.value_spin.setMaximum(9999999.99)
        self.value_spin.setDecimals(2)
        form.addRow("Value:", self.value_spin)

        self.unit_edit = QLineEdit()
        self.unit_edit.setPlaceholderText("units, kg, tons, barrels, etc.")
        form.addRow("Unit:", self.unit_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(100)
        self.description_edit.setPlaceholderText("Description of this good...")
        form.addRow("Description:", self.description_edit)

        layout.addLayout(form)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_good(self):
        self.name_edit.setText(self.good.name)
        self.category_edit.setText(self.good.category)
        if self.good.value:
            self.value_spin.setValue(self.good.value)
        self.unit_edit.setText(self.good.unit)
        self.description_edit.setPlainText(self.good.description)

    def _save(self):
        if not self.name_edit.text().strip():
            return
        self.good.name = self.name_edit.text().strip()
        self.good.category = self.category_edit.text().strip()
        self.good.value = self.value_spin.value() if self.value_spin.value() > 0 else None
        self.good.unit = self.unit_edit.text().strip()
        self.good.description = self.description_edit.toPlainText().strip()
        self.accept()


class TradeRouteEditorDialog(QDialog):
    """Dialog for editing a trade route."""

    def __init__(self, route: TradeRoute, available_factions: List[Faction], available_goods: List[str], parent=None):
        super().__init__(parent)
        self.route = route
        self.available_factions = available_factions
        self.available_goods = available_goods
        self.setWindowTitle("Edit Trade Route")
        self.resize(450, 400)
        self._init_ui()
        self._load_route()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        # To Faction - combo
        self.to_faction_combo = QComboBox()
        self.to_faction_combo.setEditable(False)
        self.to_faction_combo.addItem("-- Select Faction --", "")
        for faction in self.available_factions:
            self.to_faction_combo.addItem(faction.name, faction.id)
        form.addRow("To Faction:*", self.to_faction_combo)

        self.route_type_combo = QComboBox()
        self.route_type_combo.addItems(["bilateral", "export", "import"])
        form.addRow("Route Type:", self.route_type_combo)

        self.volume_spin = QDoubleSpinBox()
        self.volume_spin.setMaximum(9999999.99)
        self.volume_spin.setDecimals(2)
        form.addRow("Volume:", self.volume_spin)

        self.value_spin = QDoubleSpinBox()
        self.value_spin.setMaximum(9999999.99)
        self.value_spin.setDecimals(2)
        form.addRow("Trade Value:", self.value_spin)

        layout.addLayout(form)

        # Goods traded
        goods_group = QGroupBox("Goods Traded")
        goods_layout = QVBoxLayout(goods_group)

        self.goods_list = QListWidget()
        self.goods_list.setMaximumHeight(120)
        goods_layout.addWidget(self.goods_list)

        goods_btn_layout = QHBoxLayout()

        add_good_btn = QPushButton("+ Add Good")
        add_good_btn.clicked.connect(self._add_good)
        goods_btn_layout.addWidget(add_good_btn)

        remove_good_btn = QPushButton("- Remove")
        remove_good_btn.clicked.connect(self._remove_good)
        goods_btn_layout.addWidget(remove_good_btn)

        goods_btn_layout.addStretch()
        goods_layout.addLayout(goods_btn_layout)
        layout.addWidget(goods_group)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_route(self):
        # Set faction in combo
        for i in range(self.to_faction_combo.count()):
            if self.to_faction_combo.itemData(i) == self.route.to_faction:
                self.to_faction_combo.setCurrentIndex(i)
                break

        self.route_type_combo.setCurrentText(self.route.route_type)
        if self.route.volume:
            self.volume_spin.setValue(self.route.volume)
        if self.route.value:
            self.value_spin.setValue(self.route.value)

        for good in self.route.goods:
            self.goods_list.addItem(good)

    def _add_good(self):
        if self.available_goods:
            good, ok = QInputDialog.getItem(
                self, "Add Good", "Select good:",
                self.available_goods, 0, False
            )
            if ok and good:
                self.goods_list.addItem(good)
        else:
            name, ok = QInputDialog.getText(self, "Add Good", "Enter good name:")
            if ok and name:
                self.goods_list.addItem(name)

    def _remove_good(self):
        current = self.goods_list.currentRow()
        if current >= 0:
            self.goods_list.takeItem(current)

    def _save(self):
        if not self.to_faction_combo.currentData():
            return
        self.route.to_faction = self.to_faction_combo.currentData()
        self.route.route_type = self.route_type_combo.currentText()
        self.route.volume = self.volume_spin.value() if self.volume_spin.value() > 0 else None
        self.route.value = self.value_spin.value() if self.value_spin.value() > 0 else None
        self.route.goods = [
            self.goods_list.item(i).text()
            for i in range(self.goods_list.count())
        ]
        self.accept()


class EconomyEditorDialog(QDialog):
    """Dialog for editing an economy."""

    def __init__(self, economy: Optional[Economy] = None, all_economies: List[Economy] = None,
                 available_factions: List[Faction] = None, parent=None):
        super().__init__(parent)
        self.economy = economy or Economy(
            id="",
            name="",
            faction_id="",
            economy_type=EconomyType.MIXED
        )
        self.all_economies = all_economies or []
        self.available_factions = available_factions or []
        self._init_ui()
        if economy:
            self._load_economy()

    def _init_ui(self):
        self.setWindowTitle("Economy Editor")
        self.resize(750, 600)

        layout = QVBoxLayout(self)

        # Create scrollable area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        # Basic Info Section
        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Economy name")
        basic_layout.addRow("Name:*", self.name_edit)

        self.faction_combo = QComboBox()
        self.faction_combo.setEditable(False)
        self.faction_combo.addItem("-- Select Faction --", "")
        for faction in self.available_factions:
            self.faction_combo.addItem(faction.name, faction.id)
        basic_layout.addRow("Faction:*", self.faction_combo)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value.replace("_", " ").title() for t in EconomyType])
        basic_layout.addRow("Economy Type:", self.type_combo)

        self.currency_edit = QLineEdit()
        self.currency_edit.setPlaceholderText("Gold, Credits, Dollars, etc.")
        basic_layout.addRow("Currency:", self.currency_edit)

        self.gdp_spin = QDoubleSpinBox()
        self.gdp_spin.setMaximum(999999999999.99)
        self.gdp_spin.setDecimals(2)
        basic_layout.addRow("GDP:", self.gdp_spin)

        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)

        # Description
        desc_group = QGroupBox("Description")
        desc_layout = QVBoxLayout()

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText("Overview of this economy...")
        desc_layout.addWidget(self.description_edit)

        desc_group.setLayout(desc_layout)
        scroll_layout.addWidget(desc_group)

        # Industries Section
        industries_group = QGroupBox("Major Industries")
        industries_layout = QVBoxLayout()

        self.industries_list = QListWidget()
        self.industries_list.setMaximumHeight(120)
        industries_layout.addWidget(self.industries_list)

        ind_btn_layout = QHBoxLayout()
        add_ind_btn = QPushButton("+ Add Industry")
        add_ind_btn.clicked.connect(self._add_industry)
        ind_btn_layout.addWidget(add_ind_btn)

        remove_ind_btn = QPushButton("- Remove")
        remove_ind_btn.clicked.connect(self._remove_industry)
        ind_btn_layout.addWidget(remove_ind_btn)

        ind_btn_layout.addStretch()
        industries_layout.addLayout(ind_btn_layout)

        industries_group.setLayout(industries_layout)
        scroll_layout.addWidget(industries_group)

        # Goods Section
        goods_group = QGroupBox("Goods & Resources")
        goods_layout = QVBoxLayout()

        goods_help = QLabel("Define goods produced or traded by this economy (double-click to edit).")
        goods_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        goods_layout.addWidget(goods_help)

        self.goods_list = QListWidget()
        self.goods_list.setMaximumHeight(120)
        self.goods_list.itemDoubleClicked.connect(self._edit_good)
        goods_layout.addWidget(self.goods_list)

        goods_btn_layout = QHBoxLayout()
        add_good_btn = QPushButton("+ Add Good")
        add_good_btn.clicked.connect(self._add_good)
        goods_btn_layout.addWidget(add_good_btn)

        edit_good_btn = QPushButton("Edit")
        edit_good_btn.clicked.connect(self._edit_good)
        goods_btn_layout.addWidget(edit_good_btn)

        remove_good_btn = QPushButton("- Remove")
        remove_good_btn.clicked.connect(self._remove_good)
        goods_btn_layout.addWidget(remove_good_btn)

        goods_btn_layout.addStretch()
        goods_layout.addLayout(goods_btn_layout)

        goods_group.setLayout(goods_layout)
        scroll_layout.addWidget(goods_group)

        # Trade Routes Section
        routes_group = QGroupBox("Trade Routes")
        routes_layout = QVBoxLayout()

        routes_help = QLabel("Define trade routes to other factions (double-click to edit).")
        routes_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        routes_layout.addWidget(routes_help)

        self.routes_list = QListWidget()
        self.routes_list.setMaximumHeight(120)
        self.routes_list.itemDoubleClicked.connect(self._edit_route)
        routes_layout.addWidget(self.routes_list)

        routes_btn_layout = QHBoxLayout()
        add_route_btn = QPushButton("+ Add Route")
        add_route_btn.clicked.connect(self._add_route)
        routes_btn_layout.addWidget(add_route_btn)

        edit_route_btn = QPushButton("Edit")
        edit_route_btn.clicked.connect(self._edit_route)
        routes_btn_layout.addWidget(edit_route_btn)

        remove_route_btn = QPushButton("- Remove")
        remove_route_btn.clicked.connect(self._remove_route)
        routes_btn_layout.addWidget(remove_route_btn)

        routes_btn_layout.addStretch()
        routes_layout.addLayout(routes_btn_layout)

        routes_group.setLayout(routes_layout)
        scroll_layout.addWidget(routes_group)

        # Trade Relations Section
        relations_group = QGroupBox("Trade Relations")
        relations_layout = QHBoxLayout()

        # Partners
        partners_widget = QWidget()
        partners_layout = QVBoxLayout(partners_widget)
        partners_layout.setContentsMargins(0, 0, 0, 0)

        partners_label = QLabel("Trade Partners:")
        partners_label.setStyleSheet("font-weight: bold;")
        partners_layout.addWidget(partners_label)

        self.partners_list = QListWidget()
        self.partners_list.setMaximumHeight(100)
        partners_layout.addWidget(self.partners_list)

        partners_btn = QHBoxLayout()
        add_partner_btn = QPushButton("+")
        add_partner_btn.setMaximumWidth(30)
        add_partner_btn.clicked.connect(self._add_partner)
        partners_btn.addWidget(add_partner_btn)

        remove_partner_btn = QPushButton("-")
        remove_partner_btn.setMaximumWidth(30)
        remove_partner_btn.clicked.connect(self._remove_partner)
        partners_btn.addWidget(remove_partner_btn)
        partners_btn.addStretch()
        partners_layout.addLayout(partners_btn)

        relations_layout.addWidget(partners_widget)

        # Embargoes
        embargoes_widget = QWidget()
        embargoes_layout = QVBoxLayout(embargoes_widget)
        embargoes_layout.setContentsMargins(0, 0, 0, 0)

        embargoes_label = QLabel("Embargoes:")
        embargoes_label.setStyleSheet("font-weight: bold;")
        embargoes_layout.addWidget(embargoes_label)

        self.embargoes_list = QListWidget()
        self.embargoes_list.setMaximumHeight(100)
        embargoes_layout.addWidget(self.embargoes_list)

        emb_btn = QHBoxLayout()
        add_emb_btn = QPushButton("+")
        add_emb_btn.setMaximumWidth(30)
        add_emb_btn.clicked.connect(self._add_embargo)
        emb_btn.addWidget(add_emb_btn)

        remove_emb_btn = QPushButton("-")
        remove_emb_btn.setMaximumWidth(30)
        remove_emb_btn.clicked.connect(self._remove_embargo)
        emb_btn.addWidget(remove_emb_btn)
        emb_btn.addStretch()
        embargoes_layout.addLayout(emb_btn)

        relations_layout.addWidget(embargoes_widget)

        relations_group.setLayout(relations_layout)
        scroll_layout.addWidget(relations_group)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_economy(self):
        self.name_edit.setText(self.economy.name)

        # Set faction in combo box
        for i in range(self.faction_combo.count()):
            if self.faction_combo.itemData(i) == self.economy.faction_id:
                self.faction_combo.setCurrentIndex(i)
                break

        type_text = self.economy.economy_type.value.replace("_", " ").title()
        idx = self.type_combo.findText(type_text)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)

        if self.economy.currency:
            self.currency_edit.setText(self.economy.currency)
        if self.economy.gdp:
            self.gdp_spin.setValue(self.economy.gdp)
        self.description_edit.setPlainText(self.economy.description)

        for industry in self.economy.major_industries:
            self.industries_list.addItem(industry)

        self._update_goods_list()
        self._update_routes_list()

        for partner in self.economy.trade_partners:
            # Resolve faction name
            faction = next((f for f in self.available_factions if f.id == partner), None)
            if faction:
                item = QListWidgetItem(faction.name)
                item.setData(Qt.ItemDataRole.UserRole, partner)
                self.partners_list.addItem(item)

        for embargo in self.economy.embargoes:
            # Resolve faction name
            faction = next((f for f in self.available_factions if f.id == embargo), None)
            if faction:
                item = QListWidgetItem(faction.name)
                item.setData(Qt.ItemDataRole.UserRole, embargo)
                self.embargoes_list.addItem(item)

    def _update_goods_list(self):
        self.goods_list.clear()
        for good in self.economy.goods:
            display = f"{good.name}"
            if good.category:
                display += f" ({good.category})"
            if good.value:
                display += f" - {good.value} {good.unit}"
            self.goods_list.addItem(display)

    def _update_routes_list(self):
        self.routes_list.clear()
        for route in self.economy.trade_routes:
            # Resolve faction name
            faction = next((f for f in self.available_factions if f.id == route.to_faction), None)
            faction_name = faction.name if faction else route.to_faction

            goods_count = len(route.goods)
            display = f"To: {faction_name} ({route.route_type})"
            if goods_count > 0:
                display += f" - {goods_count} good{'s' if goods_count != 1 else ''}"
            self.routes_list.addItem(display)

    def _add_industry(self):
        name, ok = QInputDialog.getText(self, "Add Industry", "Enter industry name:")
        if ok and name:
            self.industries_list.addItem(name)

    def _remove_industry(self):
        current = self.industries_list.currentRow()
        if current >= 0:
            self.industries_list.takeItem(current)

    def _add_good(self):
        good = Good(name="New Good", category="")
        dialog = GoodEditorDialog(good, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.economy.goods.append(good)
            self._update_goods_list()

    def _edit_good(self):
        current = self.goods_list.currentRow()
        if current >= 0 and current < len(self.economy.goods):
            good = self.economy.goods[current]
            dialog = GoodEditorDialog(good, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._update_goods_list()

    def _remove_good(self):
        current = self.goods_list.currentRow()
        if current >= 0 and current < len(self.economy.goods):
            self.economy.goods.pop(current)
            self._update_goods_list()

    def _add_route(self):
        available_goods = [g.name for g in self.economy.goods]

        route = TradeRoute(from_faction=self.economy.faction_id, to_faction="")
        dialog = TradeRouteEditorDialog(route, self.available_factions, available_goods, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.economy.trade_routes.append(route)
            self._update_routes_list()

    def _edit_route(self):
        current = self.routes_list.currentRow()
        if current >= 0 and current < len(self.economy.trade_routes):
            route = self.economy.trade_routes[current]
            available_goods = [g.name for g in self.economy.goods]
            dialog = TradeRouteEditorDialog(route, self.available_factions, available_goods, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._update_routes_list()

    def _remove_route(self):
        current = self.routes_list.currentRow()
        if current >= 0 and current < len(self.economy.trade_routes):
            self.economy.trade_routes.pop(current)
            self._update_routes_list()

    def _add_partner(self):
        if not self.available_factions:
            QMessageBox.information(self, "No Factions", "Please create factions first.")
            return

        # Create selection dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Trade Partner")
        layout = QVBoxLayout(dialog)

        faction_list = QListWidget()
        for faction in self.available_factions:
            if faction.id != self.economy.faction_id:  # Don't add self
                faction_list.addItem(f"{faction.name} ({faction.faction_type.value})")
                faction_list.item(faction_list.count() - 1).setData(Qt.ItemDataRole.UserRole, faction.id)

        layout.addWidget(faction_list)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted and faction_list.currentItem():
            faction_id = faction_list.currentItem().data(Qt.ItemDataRole.UserRole)
            faction_name = faction_list.currentItem().text().split(" (")[0]
            # Check if already added
            for i in range(self.partners_list.count()):
                if self.partners_list.item(i).data(Qt.ItemDataRole.UserRole) == faction_id:
                    return
            item = QListWidgetItem(faction_name)
            item.setData(Qt.ItemDataRole.UserRole, faction_id)
            self.partners_list.addItem(item)

    def _remove_partner(self):
        current = self.partners_list.currentRow()
        if current >= 0:
            self.partners_list.takeItem(current)

    def _add_embargo(self):
        if not self.available_factions:
            QMessageBox.information(self, "No Factions", "Please create factions first.")
            return

        # Create selection dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Embargo Target")
        layout = QVBoxLayout(dialog)

        faction_list = QListWidget()
        for faction in self.available_factions:
            if faction.id != self.economy.faction_id:  # Don't add self
                faction_list.addItem(f"{faction.name} ({faction.faction_type.value})")
                faction_list.item(faction_list.count() - 1).setData(Qt.ItemDataRole.UserRole, faction.id)

        layout.addWidget(faction_list)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted and faction_list.currentItem():
            faction_id = faction_list.currentItem().data(Qt.ItemDataRole.UserRole)
            faction_name = faction_list.currentItem().text().split(" (")[0]
            # Check if already added
            for i in range(self.embargoes_list.count()):
                if self.embargoes_list.item(i).data(Qt.ItemDataRole.UserRole) == faction_id:
                    return
            item = QListWidgetItem(faction_name)
            item.setData(Qt.ItemDataRole.UserRole, faction_id)
            self.embargoes_list.addItem(item)

    def _remove_embargo(self):
        current = self.embargoes_list.currentRow()
        if current >= 0:
            self.embargoes_list.takeItem(current)

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            return

        if not self.economy.id:
            self.economy.id = str(uuid.uuid4())

        self.economy.name = name
        self.economy.faction_id = self.faction_combo.currentData() or ""

        type_text = self.type_combo.currentText().lower().replace(" ", "_")
        try:
            self.economy.economy_type = EconomyType(type_text)
        except ValueError:
            self.economy.economy_type = EconomyType.MIXED

        self.economy.currency = self.currency_edit.text().strip()
        self.economy.gdp = self.gdp_spin.value() if self.gdp_spin.value() > 0 else None
        self.economy.description = self.description_edit.toPlainText().strip()

        self.economy.major_industries = [
            self.industries_list.item(i).text()
            for i in range(self.industries_list.count())
        ]

        self.economy.trade_partners = [
            self.partners_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.partners_list.count())
        ]

        self.economy.embargoes = [
            self.embargoes_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.embargoes_list.count())
        ]

        self.accept()

    def get_economy(self) -> Economy:
        """Get the edited economy."""
        return self.economy


class EconomyBuilderWidget(QWidget):
    """Widget for managing economies."""

    content_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.economies: List[Economy] = []
        self.available_factions: List[Faction] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(16, 12, 16, 8)

        header = QLabel("💰 Economies")
        header.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header_layout.addWidget(header)

        subtitle = QLabel("Manage economic systems, goods, and trade routes")
        subtitle.setStyleSheet("font-size: 12px; color: #6b7280;")
        header_layout.addWidget(subtitle)

        layout.addWidget(header_widget)

        # Filter/Sort controls
        self.filter_sort = FilterSortWidget(
            sort_options=["Name", "Type", "Faction"],
            filter_placeholder="Search economies..."
        )
        self.filter_sort.set_filter_options(["All"] + [t.value.replace("_", " ").title() for t in EconomyType])
        self.filter_sort.filter_changed.connect(self._update_list)
        layout.addWidget(self.filter_sort)

        # Toolbar
        toolbar = QHBoxLayout()

        add_btn = QPushButton("Add Economy")
        add_btn.clicked.connect(self._add_economy)
        toolbar.addWidget(add_btn)

        self.edit_btn = QPushButton("Edit")
        self.edit_btn.clicked.connect(self._edit_economy)
        self.edit_btn.setEnabled(False)
        toolbar.addWidget(self.edit_btn)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_economy)
        self.remove_btn.setEnabled(False)
        toolbar.addWidget(self.remove_btn)

        # View Trade Network button
        view_network_btn = QPushButton("View Trade Network")
        view_network_btn.clicked.connect(self._show_trade_network)
        toolbar.addWidget(view_network_btn)

        # Import button
        import_btn = QPushButton("Import")
        import_btn.setToolTip("Import economies from JSON file")
        import_btn.clicked.connect(self._import_economies)
        toolbar.addWidget(import_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Economy list
        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self._edit_economy)
        layout.addWidget(self.list_widget)

    def _update_list(self):
        """Update economy list display."""
        self.list_widget.clear()

        # Get faction name helper
        def get_faction_name(economy):
            faction = next((f for f in self.available_factions if f.id == economy.faction_id), None)
            return faction.name if faction else economy.faction_id

        # Filter and sort
        def get_searchable_text(economy):
            faction_name = get_faction_name(economy)
            return f"{economy.name} {faction_name} {economy.economy_type.value} {economy.description}"

        def get_sort_value(economy, key):
            if key == "Name":
                return economy.name.lower()
            elif key == "Type":
                return economy.economy_type.value
            elif key == "Faction":
                return get_faction_name(economy).lower()
            return economy.name.lower()

        def get_type(economy):
            return economy.economy_type.value.replace("_", " ").title()

        filtered_economies = self.filter_sort.filter_and_sort(
            self.economies, get_searchable_text, get_sort_value, get_type
        )

        for economy in filtered_economies:
            faction_text = get_faction_name(economy)
            type_display = economy.economy_type.value.replace("_", " ").title()

            item_text = f"{economy.name} ({faction_text}) - {type_display}"

            # Add truncated description if available
            if economy.description:
                desc = economy.description[:50] + "..." if len(economy.description) > 50 else economy.description
                item_text += f" - {desc}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, economy.id)
            self.list_widget.addItem(item)

    def _on_selection_changed(self):
        """Handle selection change."""
        has_selection = bool(self.list_widget.selectedItems())
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def _add_economy(self):
        """Add new economy."""
        editor = EconomyEditorDialog(available_factions=self.available_factions,
                                     all_economies=self.economies, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            economy = editor.get_economy()
            self.economies.append(economy)
            self._update_list()
            self.content_changed.emit()

    def _edit_economy(self):
        """Edit selected economy."""
        items = self.list_widget.selectedItems()
        if not items:
            return

        economy_id = items[0].data(Qt.ItemDataRole.UserRole)
        economy = next((e for e in self.economies if e.id == economy_id), None)
        if not economy:
            return

        editor = EconomyEditorDialog(economy=economy, available_factions=self.available_factions,
                                     all_economies=self.economies, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_list()
            self.content_changed.emit()

    def _remove_economy(self):
        """Remove selected economy."""
        items = self.list_widget.selectedItems()
        if not items:
            return

        current_row = self.list_widget.row(items[0])
        economy_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.economies = [e for e in self.economies if e.id != economy_id]
        self._update_list()

        # Select next available economy if any exist
        if self.list_widget.count() > 0:
            next_row = min(current_row, self.list_widget.count() - 1)
            self.list_widget.setCurrentRow(next_row)

        self.content_changed.emit()

    def _show_trade_network(self):
        """Show trade network graph in popup."""
        if not self.economies:
            QMessageBox.information(self, "No Economies", "Add economies to view the trade network.")
            return

        dialog = TradeRouteGraphDialog(self.economies, self.available_factions, self)
        dialog.exec()

    def set_available_factions(self, factions: List[Faction]):
        """Set available factions for economy association."""
        self.available_factions = factions
        self._update_list()

    def load_economies(self, economies: List[Economy]):
        """Load economies list."""
        self.economies = economies
        self._update_list()

    def get_economies(self) -> List[Economy]:
        """Get economies list."""
        return self.economies

    def _import_economies(self):
        """Import economies from JSON file."""
        from src.ui.worldbuilding.worldbuilding_importer import show_import_dialog
        from src.models.worldbuilding_objects import CompleteWorldBuilding

        temp_wb = CompleteWorldBuilding(economies=self.economies)
        result = show_import_dialog(self, temp_wb, target_section="economies")

        if result and result.imported_counts.get("economies", 0) > 0:
            self.economies = temp_wb.economies
            self._update_list()
            self.content_changed.emit()
