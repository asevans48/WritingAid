"""Economy builder with trade network graph visualization."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QScrollArea, QSplitter, QInputDialog, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QBrush
from typing import List, Optional, Dict, Tuple
import uuid
import math

from src.models.worldbuilding_objects import Economy, Good, TradeRoute, EconomyType


class TradeNetworkGraph(QWidget):
    """Visual trade network graph showing factions and trade routes."""

    faction_clicked = pyqtSignal(str)  # faction ID

    def __init__(self):
        """Initialize trade network graph."""
        super().__init__()
        self.economies: List[Economy] = []
        self.faction_positions: Dict[str, Tuple[float, float]] = {}
        self.setMinimumHeight(400)
        self.setStyleSheet("background-color: white; border: 1px solid #e5e7eb; border-radius: 8px;")

    def set_economies(self, economies: List[Economy]):
        """Set economies to display."""
        self.economies = economies
        self._calculate_positions()
        self.update()

    def _calculate_positions(self):
        """Calculate circular positions for factions."""
        if not self.economies:
            return

        num_economies = len(self.economies)
        center_x = self.width() / 2
        center_y = self.height() / 2
        radius = min(self.width(), self.height()) / 3

        for i, economy in enumerate(self.economies):
            angle = (2 * math.pi * i) / num_economies
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            self.faction_positions[economy.faction_id] = (x, y)

    def paintEvent(self, event):
        """Draw trade network."""
        super().paintEvent(event)

        if not self.economies:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QColor("#9ca3af"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No economies in trade network")
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw trade routes first (behind nodes)
        for economy in self.economies:
            from_pos = self.faction_positions.get(economy.faction_id)
            if not from_pos:
                continue

            for route in economy.trade_routes:
                to_pos = self.faction_positions.get(route.to_faction)
                if not to_pos:
                    continue

                # Draw route line
                pen = QPen(QColor("#6366f1"), 2)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawLine(
                    int(from_pos[0]), int(from_pos[1]),
                    int(to_pos[0]), int(to_pos[1])
                )

                # Draw arrow
                self._draw_arrow(painter, from_pos, to_pos)

                # Draw route info at midpoint
                mid_x = (from_pos[0] + to_pos[0]) / 2
                mid_y = (from_pos[1] + to_pos[1]) / 2

                # Small label with goods count
                goods_count = len(route.goods)
                if goods_count > 0:
                    font_small = QFont("Segoe UI", 8)
                    painter.setFont(font_small)
                    painter.setPen(QColor("#6b7280"))
                    painter.drawText(
                        int(mid_x - 20), int(mid_y - 5),
                        f"{goods_count} good{'s' if goods_count != 1 else ''}"
                    )

        # Draw faction nodes
        for economy in self.economies:
            pos = self.faction_positions.get(economy.faction_id)
            if not pos:
                continue

            x, y = pos

            # Node circle
            painter.setBrush(QColor("#6366f1"))
            painter.setPen(QPen(QColor("white"), 3))
            painter.drawEllipse(int(x - 25), int(y - 25), 50, 50)

            # Faction name
            font = QFont("Segoe UI", 10, QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QColor("#1a1a1a"))

            # Get shortened faction name (ID)
            faction_name = economy.faction_id[:12] if len(economy.faction_id) > 12 else economy.faction_id

            text_rect = QRectF(x - 60, y + 35, 120, 30)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, faction_name)

            # Economy type badge
            font_small = QFont("Segoe UI", 8)
            painter.setFont(font_small)
            painter.setPen(QColor("#6b7280"))
            type_text = economy.economy_type.value.title()
            type_rect = QRectF(x - 60, y + 55, 120, 20)
            painter.drawText(type_rect, Qt.AlignmentFlag.AlignCenter, type_text)

    def _draw_arrow(self, painter: QPainter, from_pos: Tuple[float, float], to_pos: Tuple[float, float]):
        """Draw arrow indicating trade direction."""
        # Calculate arrow position (2/3 along the line)
        arrow_x = from_pos[0] + 0.66 * (to_pos[0] - from_pos[0])
        arrow_y = from_pos[1] + 0.66 * (to_pos[1] - from_pos[1])

        # Calculate angle
        dx = to_pos[0] - from_pos[0]
        dy = to_pos[1] - from_pos[1]
        angle = math.atan2(dy, dx)

        # Arrow size
        arrow_size = 10

        # Arrow points
        point1_x = arrow_x - arrow_size * math.cos(angle - math.pi / 6)
        point1_y = arrow_y - arrow_size * math.sin(angle - math.pi / 6)
        point2_x = arrow_x - arrow_size * math.cos(angle + math.pi / 6)
        point2_y = arrow_y - arrow_size * math.sin(angle + math.pi / 6)

        painter.setBrush(QColor("#6366f1"))
        painter.setPen(QPen(QColor("#6366f1"), 2))
        points = [
            QPointF(arrow_x, arrow_y),
            QPointF(point1_x, point1_y),
            QPointF(point2_x, point2_y)
        ]
        painter.drawPolygon(points)

    def resizeEvent(self, event):
        """Recalculate positions on resize."""
        super().resizeEvent(event)
        self._calculate_positions()


class GoodEditor(QWidget):
    """Editor for a tradeable good."""

    content_changed = pyqtSignal()

    def __init__(self, good: Good):
        """Initialize good editor."""
        super().__init__()
        self.good = good
        self._init_ui()
        self._load_good()

    def _init_ui(self):
        """Initialize UI."""
        layout = QFormLayout(self)

        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self.content_changed.emit)
        layout.addRow("Good Name:", self.name_edit)

        self.category_edit = QLineEdit()
        self.category_edit.setPlaceholderText("Raw material, manufactured, service, etc.")
        layout.addRow("Category:", self.category_edit)

        self.value_spin = QDoubleSpinBox()
        self.value_spin.setMaximum(9999999.99)
        layout.addRow("Value:", self.value_spin)

        self.unit_edit = QLineEdit()
        self.unit_edit.setPlaceholderText("units, kg, tons, etc.")
        layout.addRow("Unit:", self.unit_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        layout.addRow("Description:", self.description_edit)

    def _load_good(self):
        """Load good data."""
        self.name_edit.setText(self.good.name)
        self.category_edit.setText(self.good.category)
        if self.good.value:
            self.value_spin.setValue(self.good.value)
        self.unit_edit.setText(self.good.unit)
        self.description_edit.setPlainText(self.good.description)

    def save_to_model(self):
        """Save to good model."""
        self.good.name = self.name_edit.text()
        self.good.category = self.category_edit.text()
        self.good.value = self.value_spin.value() if self.value_spin.value() > 0 else None
        self.good.unit = self.unit_edit.text()
        self.good.description = self.description_edit.toPlainText()


class TradeRouteEditor(QWidget):
    """Editor for a trade route."""

    content_changed = pyqtSignal()

    def __init__(self, route: TradeRoute, available_goods: List[str]):
        """Initialize route editor."""
        super().__init__()
        self.route = route
        self.available_goods = available_goods
        self._init_ui()
        self._load_route()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.to_faction_edit = QLineEdit()
        form.addRow("To Faction:", self.to_faction_edit)

        self.route_type_combo = QComboBox()
        self.route_type_combo.addItems(["Bilateral", "Export", "Import"])
        form.addRow("Route Type:", self.route_type_combo)

        self.volume_spin = QDoubleSpinBox()
        self.volume_spin.setMaximum(9999999.99)
        form.addRow("Volume:", self.volume_spin)

        self.value_spin = QDoubleSpinBox()
        self.value_spin.setMaximum(9999999.99)
        form.addRow("Value:", self.value_spin)

        layout.addLayout(form)

        # Goods traded
        goods_group = QGroupBox("Goods Traded")
        goods_layout = QVBoxLayout(goods_group)

        self.goods_list = QListWidget()
        goods_layout.addWidget(self.goods_list)

        goods_btn_layout = QHBoxLayout()
        add_good_btn = QPushButton("Add Good")
        add_good_btn.clicked.connect(self._add_good)
        goods_btn_layout.addWidget(add_good_btn)

        remove_good_btn = QPushButton("Remove")
        remove_good_btn.clicked.connect(self._remove_good)
        goods_btn_layout.addWidget(remove_good_btn)

        goods_layout.addLayout(goods_btn_layout)
        layout.addWidget(goods_group)

    def _load_route(self):
        """Load route data."""
        self.to_faction_edit.setText(self.route.to_faction)
        self.route_type_combo.setCurrentText(self.route.route_type.title())
        if self.route.volume:
            self.volume_spin.setValue(self.route.volume)
        if self.route.value:
            self.value_spin.setValue(self.route.value)

        for good in self.route.goods:
            self.goods_list.addItem(good)

    def _add_good(self):
        """Add good to route."""
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
        """Remove good from route."""
        current = self.goods_list.currentRow()
        if current >= 0:
            self.goods_list.takeItem(current)

    def save_to_model(self):
        """Save to route model."""
        self.route.to_faction = self.to_faction_edit.text()
        self.route.route_type = self.route_type_combo.currentText().lower()
        self.route.volume = self.volume_spin.value() if self.volume_spin.value() > 0 else None
        self.route.value = self.value_spin.value() if self.value_spin.value() > 0 else None

        self.route.goods = [
            self.goods_list.item(i).text()
            for i in range(self.goods_list.count())
        ]


class EconomyEditor(QWidget):
    """Editor for an economy."""

    content_changed = pyqtSignal()

    def __init__(self, economy: Economy, all_economies: List[Economy]):
        """Initialize economy editor."""
        super().__init__()
        self.economy = economy
        self.all_economies = all_economies
        self._init_ui()
        self._load_economy()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        # Tabs
        tabs = QTabWidget()

        # Basic Info Tab
        basic_tab = self._create_basic_tab()
        tabs.addTab(basic_tab, "Basic Info")

        # Goods Tab
        goods_tab = self._create_goods_tab()
        tabs.addTab(goods_tab, "Goods & Resources")

        # Trade Routes Tab
        routes_tab = self._create_routes_tab()
        tabs.addTab(routes_tab, "Trade Routes")

        # Relations Tab
        relations_tab = self._create_relations_tab()
        tabs.addTab(relations_tab, "Trade Relations")

        layout.addWidget(tabs)

    def _create_basic_tab(self) -> QWidget:
        """Create basic info tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        self.faction_edit = QLineEdit()
        layout.addRow("Faction ID:", self.faction_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value.title() for t in EconomyType])
        layout.addRow("Economy Type:", self.type_combo)

        self.currency_edit = QLineEdit()
        layout.addRow("Currency:", self.currency_edit)

        self.gdp_spin = QDoubleSpinBox()
        self.gdp_spin.setMaximum(999999999999.99)
        layout.addRow("GDP:", self.gdp_spin)

        self.description_edit = QTextEdit()
        layout.addRow("Description:", self.description_edit)

        return widget

    def _create_goods_tab(self) -> QWidget:
        """Create goods management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Major Industries
        industries_group = QGroupBox("Major Industries")
        industries_layout = QVBoxLayout(industries_group)

        self.industries_list = QListWidget()
        industries_layout.addWidget(self.industries_list)

        ind_btn_layout = QHBoxLayout()
        add_ind_btn = QPushButton("Add Industry")
        add_ind_btn.clicked.connect(self._add_industry)
        ind_btn_layout.addWidget(add_ind_btn)

        remove_ind_btn = QPushButton("Remove")
        remove_ind_btn.clicked.connect(self._remove_industry)
        ind_btn_layout.addWidget(remove_ind_btn)

        industries_layout.addLayout(ind_btn_layout)
        layout.addWidget(industries_group)

        # Goods
        goods_label = QLabel("Produced Goods:")
        layout.addWidget(goods_label)

        self.goods_list = QListWidget()
        self.goods_list.currentItemChanged.connect(self._on_good_selected)
        layout.addWidget(self.goods_list)

        goods_btn_layout = QHBoxLayout()
        add_good_btn = QPushButton("Add Good")
        add_good_btn.clicked.connect(self._add_good)
        goods_btn_layout.addWidget(add_good_btn)

        remove_good_btn = QPushButton("Remove")
        remove_good_btn.clicked.connect(self._remove_good)
        goods_btn_layout.addWidget(remove_good_btn)

        layout.addLayout(goods_btn_layout)

        # Good editor area
        self.good_editor_scroll = QScrollArea()
        self.good_editor_scroll.setWidgetResizable(True)
        self.good_editor_scroll.setMaximumHeight(200)

        placeholder = QLabel("Select a good to edit")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.good_editor_scroll.setWidget(placeholder)

        layout.addWidget(self.good_editor_scroll)

        return widget

    def _create_routes_tab(self) -> QWidget:
        """Create trade routes tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        label = QLabel("Trade Routes:")
        layout.addWidget(label)

        self.routes_list = QListWidget()
        self.routes_list.currentItemChanged.connect(self._on_route_selected)
        layout.addWidget(self.routes_list)

        routes_btn_layout = QHBoxLayout()
        add_route_btn = QPushButton("Add Route")
        add_route_btn.clicked.connect(self._add_route)
        routes_btn_layout.addWidget(add_route_btn)

        remove_route_btn = QPushButton("Remove")
        remove_route_btn.clicked.connect(self._remove_route)
        routes_btn_layout.addWidget(remove_route_btn)

        layout.addLayout(routes_btn_layout)

        # Route editor area
        self.route_editor_scroll = QScrollArea()
        self.route_editor_scroll.setWidgetResizable(True)

        placeholder = QLabel("Select a route to edit")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.route_editor_scroll.setWidget(placeholder)

        layout.addWidget(self.route_editor_scroll)

        return widget

    def _create_relations_tab(self) -> QWidget:
        """Create trade relations tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Trade Partners
        partners_group = QGroupBox("Trade Partners")
        partners_layout = QVBoxLayout(partners_group)

        self.partners_list = QListWidget()
        partners_layout.addWidget(self.partners_list)

        partners_btn_layout = QHBoxLayout()
        add_partner_btn = QPushButton("Add Partner")
        add_partner_btn.clicked.connect(self._add_partner)
        partners_btn_layout.addWidget(add_partner_btn)

        remove_partner_btn = QPushButton("Remove")
        remove_partner_btn.clicked.connect(self._remove_partner)
        partners_btn_layout.addWidget(remove_partner_btn)

        partners_layout.addLayout(partners_btn_layout)
        layout.addWidget(partners_group)

        # Embargoes
        embargoes_group = QGroupBox("Embargoes")
        embargoes_layout = QVBoxLayout(embargoes_group)

        self.embargoes_list = QListWidget()
        embargoes_layout.addWidget(self.embargoes_list)

        emb_btn_layout = QHBoxLayout()
        add_emb_btn = QPushButton("Add Embargo")
        add_emb_btn.clicked.connect(self._add_embargo)
        emb_btn_layout.addWidget(add_emb_btn)

        remove_emb_btn = QPushButton("Remove")
        remove_emb_btn.clicked.connect(self._remove_embargo)
        emb_btn_layout.addWidget(remove_emb_btn)

        embargoes_layout.addLayout(emb_btn_layout)
        layout.addWidget(embargoes_group)

        return widget

    def _load_economy(self):
        """Load economy data."""
        self.faction_edit.setText(self.economy.faction_id)
        self.type_combo.setCurrentText(self.economy.economy_type.value.title())
        if self.economy.currency:
            self.currency_edit.setText(self.economy.currency)
        if self.economy.gdp:
            self.gdp_spin.setValue(self.economy.gdp)
        self.description_edit.setPlainText(self.economy.description)

        # Load industries
        for industry in self.economy.major_industries:
            self.industries_list.addItem(industry)

        # Load goods
        for good in self.economy.goods:
            self.goods_list.addItem(good.name)

        # Load routes
        for route in self.economy.trade_routes:
            self.routes_list.addItem(f"{route.from_faction} -> {route.to_faction}")

        # Load partners
        for partner in self.economy.trade_partners:
            self.partners_list.addItem(partner)

        # Load embargoes
        for embargo in self.economy.embargoes:
            self.embargoes_list.addItem(embargo)

    def _add_industry(self):
        """Add industry."""
        name, ok = QInputDialog.getText(self, "Add Industry", "Enter industry name:")
        if ok and name:
            self.industries_list.addItem(name)

    def _remove_industry(self):
        """Remove industry."""
        current = self.industries_list.currentRow()
        if current >= 0:
            self.industries_list.takeItem(current)

    def _add_good(self):
        """Add good."""
        name, ok = QInputDialog.getText(self, "Add Good", "Enter good name:")
        if ok and name:
            good = Good(name=name, category="")
            self.economy.goods.append(good)
            self.goods_list.addItem(name)

    def _remove_good(self):
        """Remove good."""
        current = self.goods_list.currentRow()
        if current >= 0 and current < len(self.economy.goods):
            self.economy.goods.pop(current)
            self.goods_list.takeItem(current)

    def _on_good_selected(self, current, previous):
        """Handle good selection."""
        if not current:
            return

        idx = self.goods_list.row(current)
        if idx >= 0 and idx < len(self.economy.goods):
            good = self.economy.goods[idx]
            editor = GoodEditor(good)
            editor.content_changed.connect(self.content_changed.emit)
            self.good_editor_scroll.setWidget(editor)

    def _add_route(self):
        """Add trade route."""
        route = TradeRoute(from_faction=self.economy.faction_id, to_faction="")
        self.economy.trade_routes.append(route)
        self.routes_list.addItem(f"{route.from_faction} -> [New Route]")

    def _remove_route(self):
        """Remove route."""
        current = self.routes_list.currentRow()
        if current >= 0 and current < len(self.economy.trade_routes):
            self.economy.trade_routes.pop(current)
            self.routes_list.takeItem(current)

    def _on_route_selected(self, current, previous):
        """Handle route selection."""
        if not current:
            return

        idx = self.routes_list.row(current)
        if idx >= 0 and idx < len(self.economy.trade_routes):
            route = self.economy.trade_routes[idx]
            available_goods = [g.name for g in self.economy.goods]
            editor = TradeRouteEditor(route, available_goods)
            editor.content_changed.connect(self.content_changed.emit)
            self.route_editor_scroll.setWidget(editor)

    def _add_partner(self):
        """Add trade partner."""
        name, ok = QInputDialog.getText(self, "Add Partner", "Enter faction ID:")
        if ok and name:
            self.partners_list.addItem(name)

    def _remove_partner(self):
        """Remove partner."""
        current = self.partners_list.currentRow()
        if current >= 0:
            self.partners_list.takeItem(current)

    def _add_embargo(self):
        """Add embargo."""
        name, ok = QInputDialog.getText(self, "Add Embargo", "Enter faction ID:")
        if ok and name:
            self.embargoes_list.addItem(name)

    def _remove_embargo(self):
        """Remove embargo."""
        current = self.embargoes_list.currentRow()
        if current >= 0:
            self.embargoes_list.takeItem(current)

    def save_to_model(self):
        """Save to economy model."""
        self.economy.faction_id = self.faction_edit.text()
        self.economy.economy_type = EconomyType(self.type_combo.currentText().lower().replace(" ", "_"))
        self.economy.currency = self.currency_edit.text()
        self.economy.gdp = self.gdp_spin.value() if self.gdp_spin.value() > 0 else None
        self.economy.description = self.description_edit.toPlainText()

        self.economy.major_industries = [
            self.industries_list.item(i).text()
            for i in range(self.industries_list.count())
        ]

        self.economy.trade_partners = [
            self.partners_list.item(i).text()
            for i in range(self.partners_list.count())
        ]

        self.economy.embargoes = [
            self.embargoes_list.item(i).text()
            for i in range(self.embargoes_list.count())
        ]


class EconomyBuilderWidget(QWidget):
    """Widget for managing economies with trade network visualization."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize economy builder."""
        super().__init__()
        self.economies: List[Economy] = []
        self.current_editor: Optional[EconomyEditor] = None
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Trade network visualization
        self.trade_network = TradeNetworkGraph()
        layout.addWidget(self.trade_network)

        # Splitter for list and editor
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Economy list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        label = QLabel("Economies")
        label.setStyleSheet("font-weight: 600; font-size: 13px;")
        left_layout.addWidget(label)

        self.economy_list = QListWidget()
        self.economy_list.currentItemChanged.connect(self._on_economy_selected)
        left_layout.addWidget(self.economy_list)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Add Economy")
        add_btn.clicked.connect(self._add_economy)
        btn_layout.addWidget(add_btn)

        remove_btn = QPushButton("🗑️")
        remove_btn.setMaximumWidth(40)
        remove_btn.clicked.connect(self._remove_economy)
        btn_layout.addWidget(remove_btn)

        left_layout.addLayout(btn_layout)

        left_panel.setMaximumWidth(250)
        splitter.addWidget(left_panel)

        # Right: Economy editor
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)

        placeholder = QLabel("Add or select an economy")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor_scroll.setWidget(placeholder)

        splitter.addWidget(self.editor_scroll)

        layout.addWidget(splitter)

    def _add_economy(self):
        """Add new economy."""
        faction_id, ok = QInputDialog.getText(self, "New Economy", "Enter faction ID:")

        if ok and faction_id:
            economy = Economy(
                id=str(uuid.uuid4()),
                faction_id=faction_id,
                economy_type=EconomyType.MIXED
            )
            self.economies.append(economy)

            item = QListWidgetItem(faction_id)
            item.setData(Qt.ItemDataRole.UserRole, economy.id)
            self.economy_list.addItem(item)

            self.economy_list.setCurrentItem(item)
            self._update_network()

    def _remove_economy(self):
        """Remove selected economy."""
        current = self.economy_list.currentItem()
        if current:
            economy_id = current.data(Qt.ItemDataRole.UserRole)
            self.economies = [e for e in self.economies if e.id != economy_id]
            self.economy_list.takeItem(self.economy_list.row(current))
            self._update_network()

            # Show placeholder
            placeholder = QLabel("Add or select an economy")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.editor_scroll.setWidget(placeholder)

    def _on_economy_selected(self, current, previous):
        """Handle economy selection."""
        if not current:
            return

        # Save previous
        if self.current_editor:
            self.current_editor.save_to_model()

        # Load selected
        economy_id = current.data(Qt.ItemDataRole.UserRole)
        economy = next((e for e in self.economies if e.id == economy_id), None)

        if economy:
            self.current_editor = EconomyEditor(economy, self.economies)
            self.current_editor.content_changed.connect(self.content_changed.emit)
            self.current_editor.content_changed.connect(self._update_network)
            self.editor_scroll.setWidget(self.current_editor)

    def _update_network(self):
        """Update trade network visualization."""
        self.trade_network.set_economies(self.economies)

    def get_economies(self) -> List[Economy]:
        """Get all economies."""
        if self.current_editor:
            self.current_editor.save_to_model()
        return self.economies

    def load_economies(self, economies: List[Economy]):
        """Load economies."""
        self.economies = economies
        self.economy_list.clear()

        for economy in economies:
            item = QListWidgetItem(economy.faction_id)
            item.setData(Qt.ItemDataRole.UserRole, economy.id)
            self.economy_list.addItem(item)

        self._update_network()
