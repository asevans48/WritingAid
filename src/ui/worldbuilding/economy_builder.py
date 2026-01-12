"""Economy builder with trade network graph visualization."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QScrollArea, QSplitter, QInputDialog, QTabWidget,
    QStackedWidget, QMessageBox, QDialog, QDialogButtonBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF, QTimer
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
        self.setMinimumHeight(150)
        self.setMaximumHeight(200)
        self.setStyleSheet("background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px;")

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
            angle = (2 * math.pi * i) / num_economies - math.pi / 2  # Start from top
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
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No economies - add one below")
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

        # Draw faction nodes
        for economy in self.economies:
            pos = self.faction_positions.get(economy.faction_id)
            if not pos:
                continue

            x, y = pos

            # Node circle - smaller for compact view
            painter.setBrush(QColor("#6366f1"))
            painter.setPen(QPen(QColor("white"), 2))
            painter.drawEllipse(int(x - 15), int(y - 15), 30, 30)

            # Faction name below node
            font = QFont("Segoe UI", 8)
            painter.setFont(font)
            painter.setPen(QColor("#1a1a1a"))

            faction_name = economy.faction_id[:10] if len(economy.faction_id) > 10 else economy.faction_id
            text_rect = QRectF(x - 40, y + 18, 80, 20)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, faction_name)

    def resizeEvent(self, event):
        """Recalculate positions on resize."""
        super().resizeEvent(event)
        self._calculate_positions()


class GoodEditorDialog(QDialog):
    """Dialog for editing a good."""

    def __init__(self, good: Good, parent=None):
        super().__init__(parent)
        self.good = good
        self.setWindowTitle("Edit Good")
        self.setMinimumWidth(350)
        self.setMaximumWidth(500)
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

    def __init__(self, route: TradeRoute, available_factions: List[str], available_goods: List[str], parent=None):
        super().__init__(parent)
        self.route = route
        self.available_factions = available_factions
        self.available_goods = available_goods
        self.setWindowTitle("Edit Trade Route")
        self.setMinimumWidth(380)
        self.setMaximumWidth(550)
        self.setMinimumHeight(350)
        self._init_ui()
        self._load_route()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        # To Faction - combo if available, otherwise text
        self.to_faction_combo = QComboBox()
        self.to_faction_combo.setEditable(True)
        if self.available_factions:
            self.to_faction_combo.addItems(self.available_factions)
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

        layout.addStretch()

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_route(self):
        self.to_faction_combo.setCurrentText(self.route.to_faction)
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
        if not self.to_faction_combo.currentText().strip():
            return
        self.route.to_faction = self.to_faction_combo.currentText().strip()
        self.route.route_type = self.route_type_combo.currentText()
        self.route.volume = self.volume_spin.value() if self.volume_spin.value() > 0 else None
        self.route.value = self.value_spin.value() if self.value_spin.value() > 0 else None
        self.route.goods = [
            self.goods_list.item(i).text()
            for i in range(self.goods_list.count())
        ]
        self.accept()


class EconomyEditor(QWidget):
    """Editor for an economy - redesigned for clarity."""

    content_changed = pyqtSignal()

    def __init__(self, economy: Economy, all_economies: List[Economy]):
        super().__init__()
        self.economy = economy
        self.all_economies = all_economies
        self._init_ui()
        self._load_economy()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(12)

        # Basic Info Section
        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout()
        basic_layout.setSpacing(8)

        self.faction_edit = QLineEdit()
        self.faction_edit.setPlaceholderText("Faction this economy belongs to")
        self.faction_edit.textChanged.connect(self._on_change)
        basic_layout.addRow("Faction ID:*", self.faction_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value.replace("_", " ").title() for t in EconomyType])
        self.type_combo.currentTextChanged.connect(self._on_change)
        basic_layout.addRow("Economy Type:", self.type_combo)

        self.currency_edit = QLineEdit()
        self.currency_edit.setPlaceholderText("Gold, Credits, Dollars, etc.")
        self.currency_edit.textChanged.connect(self._on_change)
        basic_layout.addRow("Currency:", self.currency_edit)

        self.gdp_spin = QDoubleSpinBox()
        self.gdp_spin.setMaximum(999999999999.99)
        self.gdp_spin.setDecimals(2)
        self.gdp_spin.valueChanged.connect(self._on_change)
        basic_layout.addRow("GDP:", self.gdp_spin)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText("Overview of this economy...")
        self.description_edit.textChanged.connect(self._on_change)
        basic_layout.addRow("Description:", self.description_edit)

        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)

        # Industries Section
        industries_group = QGroupBox("Major Industries")
        industries_layout = QVBoxLayout()

        self.industries_list = QListWidget()
        self.industries_list.setMinimumHeight(60)
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

        goods_help = QLabel("Define goods produced or traded by this economy.")
        goods_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        goods_layout.addWidget(goods_help)

        self.goods_list = QListWidget()
        self.goods_list.setMinimumHeight(80)
        self.goods_list.setMaximumHeight(150)
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

        routes_help = QLabel("Define trade routes to other factions.")
        routes_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        routes_layout.addWidget(routes_help)

        self.routes_list = QListWidget()
        self.routes_list.setMinimumHeight(80)
        self.routes_list.setMaximumHeight(150)
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
        self.partners_list.setMinimumHeight(60)
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
        self.embargoes_list.setMinimumHeight(60)
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

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Save button - prominent at bottom
        save_layout = QHBoxLayout()
        save_layout.addStretch()

        self.save_btn = QPushButton("Save Economy")
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                border: none;
                padding: 10px 24px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 13px;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            QPushButton:pressed {
                background-color: #4338ca;
            }
        """)
        self.save_btn.clicked.connect(self._save_clicked)
        save_layout.addWidget(self.save_btn)

        self.save_status = QLabel("")
        self.save_status.setStyleSheet("color: #059669; font-size: 12px; margin-left: 8px;")
        save_layout.addWidget(self.save_status)

        save_layout.addStretch()
        layout.addLayout(save_layout)

    def _load_economy(self):
        self.faction_edit.setText(self.economy.faction_id)

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
            self.partners_list.addItem(partner)

        for embargo in self.economy.embargoes:
            self.embargoes_list.addItem(embargo)

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
            goods_count = len(route.goods)
            display = f"To: {route.to_faction} ({route.route_type})"
            if goods_count > 0:
                display += f" - {goods_count} good{'s' if goods_count != 1 else ''}"
            self.routes_list.addItem(display)

    def _on_change(self):
        self.save_to_model()
        self.content_changed.emit()

    def _add_industry(self):
        name, ok = QInputDialog.getText(self, "Add Industry", "Enter industry name:")
        if ok and name:
            self.industries_list.addItem(name)
            self._on_change()

    def _remove_industry(self):
        current = self.industries_list.currentRow()
        if current >= 0:
            self.industries_list.takeItem(current)
            self._on_change()

    def _add_good(self):
        good = Good(name="New Good", category="")
        dialog = GoodEditorDialog(good, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.economy.goods.append(good)
            self._update_goods_list()
            self._on_change()

    def _edit_good(self):
        current = self.goods_list.currentRow()
        if current >= 0 and current < len(self.economy.goods):
            good = self.economy.goods[current]
            dialog = GoodEditorDialog(good, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._update_goods_list()
                self._on_change()

    def _remove_good(self):
        current = self.goods_list.currentRow()
        if current >= 0 and current < len(self.economy.goods):
            self.economy.goods.pop(current)
            self._update_goods_list()
            self._on_change()

    def _add_route(self):
        available_factions = [e.faction_id for e in self.all_economies if e.id != self.economy.id]
        available_goods = [g.name for g in self.economy.goods]

        route = TradeRoute(from_faction=self.economy.faction_id, to_faction="")
        dialog = TradeRouteEditorDialog(route, available_factions, available_goods, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.economy.trade_routes.append(route)
            self._update_routes_list()
            self._on_change()

    def _edit_route(self):
        current = self.routes_list.currentRow()
        if current >= 0 and current < len(self.economy.trade_routes):
            route = self.economy.trade_routes[current]
            available_factions = [e.faction_id for e in self.all_economies if e.id != self.economy.id]
            available_goods = [g.name for g in self.economy.goods]
            dialog = TradeRouteEditorDialog(route, available_factions, available_goods, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._update_routes_list()
                self._on_change()

    def _remove_route(self):
        current = self.routes_list.currentRow()
        if current >= 0 and current < len(self.economy.trade_routes):
            self.economy.trade_routes.pop(current)
            self._update_routes_list()
            self._on_change()

    def _add_partner(self):
        available = [e.faction_id for e in self.all_economies if e.id != self.economy.id]
        if available:
            name, ok = QInputDialog.getItem(self, "Add Partner", "Select faction:", available, 0, True)
        else:
            name, ok = QInputDialog.getText(self, "Add Partner", "Enter faction ID:")
        if ok and name:
            self.partners_list.addItem(name)
            self._on_change()

    def _remove_partner(self):
        current = self.partners_list.currentRow()
        if current >= 0:
            self.partners_list.takeItem(current)
            self._on_change()

    def _add_embargo(self):
        available = [e.faction_id for e in self.all_economies if e.id != self.economy.id]
        if available:
            name, ok = QInputDialog.getItem(self, "Add Embargo", "Select faction:", available, 0, True)
        else:
            name, ok = QInputDialog.getText(self, "Add Embargo", "Enter faction ID:")
        if ok and name:
            self.embargoes_list.addItem(name)
            self._on_change()

    def _remove_embargo(self):
        current = self.embargoes_list.currentRow()
        if current >= 0:
            self.embargoes_list.takeItem(current)
            self._on_change()

    def save_to_model(self):
        self.economy.faction_id = self.faction_edit.text().strip()

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
            self.partners_list.item(i).text()
            for i in range(self.partners_list.count())
        ]

        self.economy.embargoes = [
            self.embargoes_list.item(i).text()
            for i in range(self.embargoes_list.count())
        ]

    def _save_clicked(self):
        """Handle explicit save button click."""
        self.save_to_model()
        self.content_changed.emit()
        self.save_status.setText("Saved!")
        QTimer.singleShot(2000, lambda: self.save_status.setText(""))


class EconomyBuilderWidget(QWidget):
    """Widget for managing economies with trade network visualization."""

    content_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.economies: List[Economy] = []
        self.current_editor: Optional[EconomyEditor] = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("Economy Builder")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        help_label = QLabel("Manage economies, goods, and trade routes")
        help_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        help_label.setWordWrap(True)
        header_layout.addWidget(help_label)

        layout.addLayout(header_layout)

        # Trade network visualization - compact at top
        network_group = QGroupBox("Trade Network Overview")
        network_layout = QVBoxLayout(network_group)
        network_layout.setContentsMargins(8, 8, 8, 8)

        self.trade_network = TradeNetworkGraph()
        network_layout.addWidget(self.trade_network)

        layout.addWidget(network_group)

        # Main content area - list + editor splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Economy list (compact)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        list_label = QLabel("Economies")
        list_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        left_layout.addWidget(list_label)

        self.economy_list = QListWidget()
        self.economy_list.currentItemChanged.connect(self._on_economy_selected)
        left_layout.addWidget(self.economy_list)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._add_economy)
        btn_layout.addWidget(add_btn)

        remove_btn = QPushButton("- Remove")
        remove_btn.clicked.connect(self._remove_economy)
        btn_layout.addWidget(remove_btn)

        left_layout.addLayout(btn_layout)

        left_panel.setMinimumWidth(140)
        left_panel.setMaximumWidth(250)
        splitter.addWidget(left_panel)

        # Right: Economy editor (takes most space)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.editor_stack = QStackedWidget()

        # Placeholder
        placeholder = QWidget()
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_label = QLabel("Select an economy to edit or click '+ Add' to create one")
        placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_label.setStyleSheet("color: #6b7280; font-size: 14px;")
        placeholder_layout.addWidget(placeholder_label)
        self.editor_stack.addWidget(placeholder)

        right_layout.addWidget(self.editor_stack)
        splitter.addWidget(right_panel)

        # Set splitter proportions - editor gets more space
        splitter.setStretchFactor(0, 1)  # List
        splitter.setStretchFactor(1, 3)  # Editor

        # Set initial sizes for responsiveness (list:editor ratio)
        splitter.setSizes([200, 600])

        layout.addWidget(splitter, 1)  # Splitter takes remaining space

    def _add_economy(self):
        faction_id, ok = QInputDialog.getText(self, "New Economy", "Enter faction ID:")

        if ok and faction_id.strip():
            economy = Economy(
                id=str(uuid.uuid4()),
                faction_id=faction_id.strip(),
                economy_type=EconomyType.MIXED
            )
            self.economies.append(economy)

            item = QListWidgetItem(faction_id.strip())
            item.setData(Qt.ItemDataRole.UserRole, economy.id)
            self.economy_list.addItem(item)

            self.economy_list.setCurrentItem(item)
            self._update_network()
            self.content_changed.emit()

    def _remove_economy(self):
        current = self.economy_list.currentItem()
        if not current:
            return

        economy_id = current.data(Qt.ItemDataRole.UserRole)
        economy = next((e for e in self.economies if e.id == economy_id), None)

        if economy:
            reply = QMessageBox.question(
                self,
                "Remove Economy",
                f"Are you sure you want to remove the economy for '{economy.faction_id}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

        current_row = self.economy_list.row(current)
        self.economies = [e for e in self.economies if e.id != economy_id]
        self.economy_list.takeItem(current_row)
        self._update_network()

        self.current_editor = None

        # Select next or show placeholder
        if self.economy_list.count() > 0:
            next_row = min(current_row, self.economy_list.count() - 1)
            self.economy_list.setCurrentRow(next_row)
        else:
            self.editor_stack.setCurrentIndex(0)

        self.content_changed.emit()

    def _on_economy_selected(self, current, previous):
        if not current:
            self.editor_stack.setCurrentIndex(0)
            return

        # Save previous
        if self.current_editor:
            self.current_editor.save_to_model()

        # Load selected
        economy_id = current.data(Qt.ItemDataRole.UserRole)
        economy = next((e for e in self.economies if e.id == economy_id), None)

        if economy:
            self.current_editor = EconomyEditor(economy, self.economies)
            self.current_editor.content_changed.connect(self._on_editor_changed)

            # Remove old editor if exists
            if self.editor_stack.count() > 1:
                old_widget = self.editor_stack.widget(1)
                self.editor_stack.removeWidget(old_widget)
                old_widget.deleteLater()

            self.editor_stack.addWidget(self.current_editor)
            self.editor_stack.setCurrentIndex(1)

    def _on_editor_changed(self):
        # Update list item text
        current = self.economy_list.currentItem()
        if current and self.current_editor:
            current.setText(self.current_editor.economy.faction_id)
        self._update_network()
        self.content_changed.emit()

    def _update_network(self):
        self.trade_network.set_economies(self.economies)

    def get_economies(self) -> List[Economy]:
        if self.current_editor:
            self.current_editor.save_to_model()
        return self.economies

    def load_economies(self, economies: List[Economy]):
        self.economies = economies
        self.economy_list.clear()
        self.current_editor = None

        for economy in economies:
            item = QListWidgetItem(economy.faction_id)
            item.setData(Qt.ItemDataRole.UserRole, economy.id)
            self.economy_list.addItem(item)

        self._update_network()

        # Reset to placeholder
        if self.editor_stack.count() > 1:
            old_widget = self.editor_stack.widget(1)
            self.editor_stack.removeWidget(old_widget)
            old_widget.deleteLater()
        self.editor_stack.setCurrentIndex(0)
