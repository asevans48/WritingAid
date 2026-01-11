"""Visual connection system for showing relationships between story elements."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QScrollArea, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor
from typing import List, Dict, Tuple


class ConnectionNode(QWidget):
    """A node representing a story element."""

    clicked = pyqtSignal(str, str)  # type, id

    def __init__(self, node_type: str, node_id: str, title: str, color: str):
        """Initialize connection node."""
        super().__init__()
        self.node_type = node_type
        self.node_id = node_id
        self.title = title
        self.color = color
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)

        # Icon based on type
        icons = {
            'character': '👤',
            'location': '📍',
            'event': '⚡',
            'subplot': '📖'
        }

        icon_label = QLabel(icons.get(self.node_type, '•'))
        icon_label.setStyleSheet("font-size: 20px;")
        layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignCenter)

        title_label = QLabel(self.title)
        title_label.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 500;
            color: {self.color};
            text-align: center;
        """)
        title_label.setWordWrap(True)
        title_label.setMaximumWidth(80)
        layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Style the node
        self.setStyleSheet(f"""
            ConnectionNode {{
                background-color: white;
                border: 2px solid {self.color};
                border-radius: 8px;
                min-width: 80px;
                max-width: 80px;
            }}
            ConnectionNode:hover {{
                background-color: {self.color}15;
            }}
        """)

        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        """Handle click."""
        self.clicked.emit(self.node_type, self.node_id)


class ConnectionMap(QWidget):
    """Visual map showing connections between story elements."""

    node_clicked = pyqtSignal(str, str)  # type, id

    def __init__(self):
        """Initialize connection map."""
        super().__init__()
        self.nodes: List[Tuple[ConnectionNode, int, int]] = []  # node, x, y
        self.connections: List[Tuple[int, int]] = []  # pairs of node indices
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        self.setMinimumHeight(300)
        self.setStyleSheet("""
            ConnectionMap {
                background-color: #fafafa;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
            }
        """)

    def add_node(self, node_type: str, node_id: str, title: str, x: int, y: int):
        """Add a node to the map."""
        colors = {
            'character': '#6366f1',  # Indigo
            'location': '#10b981',   # Green
            'event': '#f59e0b',      # Amber
            'subplot': '#ec4899'     # Pink
        }

        color = colors.get(node_type, '#6b7280')
        node = ConnectionNode(node_type, node_id, title, color)
        node.setParent(self)
        node.move(x, y)
        node.clicked.connect(self.node_clicked.emit)
        node.show()

        self.nodes.append((node, x, y))

    def add_connection(self, from_index: int, to_index: int):
        """Add a connection between two nodes."""
        if from_index < len(self.nodes) and to_index < len(self.nodes):
            self.connections.append((from_index, to_index))
            self.update()

    def paintEvent(self, event):
        """Draw connections between nodes."""
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw connection lines
        pen = QPen(QColor("#cbd5e1"), 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)

        for from_idx, to_idx in self.connections:
            if from_idx < len(self.nodes) and to_idx < len(self.nodes):
                from_node, from_x, from_y = self.nodes[from_idx]
                to_node, to_x, to_y = self.nodes[to_idx]

                # Calculate center points
                from_center_x = from_x + from_node.width() // 2
                from_center_y = from_y + from_node.height() // 2
                to_center_x = to_x + to_node.width() // 2
                to_center_y = to_y + to_node.height() // 2

                painter.drawLine(from_center_x, from_center_y, to_center_x, to_center_y)

    def clear_map(self):
        """Clear all nodes and connections."""
        for node, _, _ in self.nodes:
            node.deleteLater()
        self.nodes.clear()
        self.connections.clear()
        self.update()


class ConnectionVisualizer(QWidget):
    """Widget for visualizing story element connections."""

    def __init__(self):
        """Initialize connection visualizer."""
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(16, 16, 16, 8)

        title = QLabel("Story Connections")
        title.setProperty("subheading", True)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #f9fafb;
            }
        """)
        header_layout.addWidget(refresh_btn)

        layout.addLayout(header_layout)

        # Connection map
        self.connection_map = ConnectionMap()
        layout.addWidget(self.connection_map)

        # Legend
        legend_layout = QHBoxLayout()
        legend_layout.setContentsMargins(16, 8, 16, 16)
        legend_layout.setSpacing(16)

        legend_items = [
            ('👤', 'Characters', '#6366f1'),
            ('📍', 'Locations', '#10b981'),
            ('⚡', 'Events', '#f59e0b'),
            ('📖', 'Subplots', '#ec4899')
        ]

        for icon, label, color in legend_items:
            item_layout = QHBoxLayout()
            item_layout.setSpacing(4)

            icon_label = QLabel(icon)
            item_layout.addWidget(icon_label)

            text_label = QLabel(label)
            text_label.setStyleSheet(f"font-size: 11px; color: {color}; font-weight: 500;")
            item_layout.addWidget(text_label)

            legend_layout.addLayout(item_layout)

        legend_layout.addStretch()
        layout.addLayout(legend_layout)

    def load_project_connections(self, project):
        """Load and visualize project connections."""
        self.connection_map.clear_map()

        # Example layout - can be enhanced with actual relationship data
        # Add character nodes
        x_offset = 50
        y_offset = 50

        for i, char in enumerate(project.characters[:5]):  # Limit for demo
            self.connection_map.add_node(
                'character',
                char.id,
                char.name,
                x_offset + (i * 120),
                y_offset
            )

        # Add subplot nodes
        for i, subplot in enumerate(project.story_planning.subplots[:3]):
            self.connection_map.add_node(
                'subplot',
                subplot.id,
                subplot.title,
                x_offset + 60 + (i * 120),
                y_offset + 150
            )

        # Example connections (can be based on actual relationships)
        if len(self.connection_map.nodes) >= 2:
            self.connection_map.add_connection(0, 1)
