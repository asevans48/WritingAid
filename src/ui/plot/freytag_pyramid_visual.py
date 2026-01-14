"""Visual Freytag Pyramid with intensity-based event positioning and act divisions."""

from typing import List, Dict, Tuple, Optional
import math
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPointF, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QBrush, QPainterPath, QMouseEvent

from src.models.project import PlotEvent


class FreytagPyramidVisual(QWidget):
    """Visual representation of Freytag's Pyramid with plot events and act divisions."""

    event_clicked = pyqtSignal(str)  # event ID

    def __init__(self):
        """Initialize pyramid visual."""
        super().__init__()
        self.events: List[PlotEvent] = []
        self.num_acts = 3
        self.act_names = ["Act I", "Act II", "Act III"]
        self.setMinimumHeight(350)
        self.setMinimumWidth(600)
        self.setStyleSheet("background-color: white; border: 1px solid #e5e7eb; border-radius: 8px;")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Track event positions for click detection
        self._event_positions: Dict[str, Tuple[float, float, float]] = {}  # id -> (x, y, radius)

    def set_events(self, events: List[PlotEvent]):
        """Set events to display on pyramid.

        Args:
            events: List of PlotEvent objects
        """
        self.events = events
        self._event_positions.clear()
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse click to detect event selection."""
        click_x = event.position().x()
        click_y = event.position().y()

        # Check if click is on any event marker
        for event_id, (x, y, radius) in self._event_positions.items():
            distance = math.sqrt((click_x - x) ** 2 + (click_y - y) ** 2)
            if distance <= radius + 5:  # Add small tolerance
                self.event_clicked.emit(event_id)
                return

        super().mousePressEvent(event)

    def set_acts(self, num_acts: int, act_names: List[str]):
        """Set act configuration.

        Args:
            num_acts: Number of acts
            act_names: List of act names
        """
        self.num_acts = num_acts
        self.act_names = act_names if act_names else [f"Act {i+1}" for i in range(num_acts)]
        self.update()

    def paintEvent(self, event):
        """Draw the Freytag pyramid with events."""
        super().paintEvent(event)

        # Clear event positions before redrawing
        self._event_positions.clear()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Define pyramid points
        width = self.width() - 40  # Margins
        height = self.height() - 80
        margin_left = 20
        margin_top = 40

        # Calculate act width for positioning
        act_width = width / self.num_acts

        # Draw act divisions first (background)
        self._draw_act_divisions(painter, margin_left, margin_top, width, height)

        # Pyramid stages scaled to fit within acts
        # The pyramid spans the full width, with key points at:
        # - Exposition at start (0%)
        # - Rising action midpoint (~25%)
        # - Climax at center (~50%)
        # - Falling action midpoint (~75%)
        # - Resolution at end (100%)
        exposition_x = margin_left
        exposition_y = margin_top + height

        rising_mid_x = margin_left + width * 0.25
        rising_mid_y = margin_top + height * 0.6

        climax_x = margin_left + width * 0.5
        climax_y = margin_top  # Peak

        falling_mid_x = margin_left + width * 0.75
        falling_mid_y = margin_top + height * 0.6

        resolution_x = margin_left + width
        resolution_y = margin_top + height

        # Draw pyramid structure
        pen = QPen(QColor("#6b7280"), 3)
        painter.setPen(pen)

        # Draw lines
        painter.drawLine(int(exposition_x), int(exposition_y),
                        int(rising_mid_x), int(rising_mid_y))
        painter.drawLine(int(rising_mid_x), int(rising_mid_y),
                        int(climax_x), int(climax_y))
        painter.drawLine(int(climax_x), int(climax_y),
                        int(falling_mid_x), int(falling_mid_y))
        painter.drawLine(int(falling_mid_x), int(falling_mid_y),
                        int(resolution_x), int(resolution_y))

        # Draw stage labels
        font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#374151"))

        painter.drawText(int(exposition_x), int(exposition_y + 20), "Exposition")
        painter.drawText(int(rising_mid_x - 30), int(rising_mid_y + 25), "Rising Action")
        painter.drawText(int(climax_x - 20), int(climax_y - 10), "Climax")
        painter.drawText(int(falling_mid_x - 30), int(falling_mid_y + 25), "Falling Action")
        painter.drawText(int(resolution_x - 50), int(resolution_y + 20), "Resolution")

        # Group events by act
        events_by_act = {}
        for evt in self.events:
            act_num = evt.act if evt.act and evt.act > 0 else 1  # Default to act 1
            if act_num not in events_by_act:
                events_by_act[act_num] = []
            events_by_act[act_num].append(evt)

        # Sort events within each act by sort_order
        for act in events_by_act:
            events_by_act[act].sort(key=lambda e: e.sort_order)

        # Draw events positioned within their act regions
        for act_num, act_events in events_by_act.items():
            if not act_events:
                continue

            # Calculate act region boundaries
            act_index = min(act_num - 1, self.num_acts - 1)  # 0-based, clamped
            act_start_x = margin_left + act_index * act_width
            act_end_x = act_start_x + act_width

            # Position events within the act region
            for idx, evt in enumerate(act_events):
                # Horizontal position within act (spread events across act width)
                if len(act_events) == 1:
                    t = 0.5  # Center single event
                else:
                    # Add padding from edges
                    padding = 0.15
                    t = padding + (1 - 2 * padding) * (idx / (len(act_events) - 1))

                pos_x = act_start_x + t * act_width

                # Calculate Y position based on pyramid line at this X position
                pyramid_y = self._get_pyramid_y_at_x(
                    pos_x, margin_left, margin_top, width, height
                )

                # Adjust Y position based on intensity (0-100)
                # Higher intensity = closer to the pyramid line
                # Lower intensity = further from the pyramid line (below)
                intensity_offset = (100 - evt.intensity) * 0.4  # Scale: 0-40 pixels
                pos_y = pyramid_y + intensity_offset

                # Draw event marker
                self._draw_event(painter, pos_x, pos_y, evt)

    def _get_pyramid_y_at_x(self, x: float, margin_left: float, margin_top: float,
                            width: float, height: float) -> float:
        """Get the Y coordinate of the pyramid line at a given X position.

        Args:
            x: X coordinate
            margin_left: Left margin
            margin_top: Top margin
            width: Drawing width
            height: Drawing height

        Returns:
            Y coordinate on the pyramid line
        """
        # Pyramid key points
        points = [
            (margin_left, margin_top + height),                    # Exposition (0%)
            (margin_left + width * 0.25, margin_top + height * 0.6),  # Rising mid (25%)
            (margin_left + width * 0.5, margin_top),              # Climax (50%)
            (margin_left + width * 0.75, margin_top + height * 0.6),  # Falling mid (75%)
            (margin_left + width, margin_top + height),           # Resolution (100%)
        ]

        # Find which segment the x falls in
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]

            if x1 <= x <= x2:
                # Linear interpolation
                if x2 == x1:
                    return y1
                t = (x - x1) / (x2 - x1)
                return y1 + t * (y2 - y1)

        # Default to bottom if outside range
        return margin_top + height

    def _draw_event(self, painter: QPainter, x: float, y: float, event: PlotEvent):
        """Draw a single event marker.

        Args:
            painter: QPainter object
            x: X coordinate
            y: Y coordinate
            event: PlotEvent object
        """
        # Event color based on stage
        colors = {
            "exposition": "#3b82f6",      # Blue
            "rising_action": "#10b981",   # Green
            "climax": "#ef4444",          # Red
            "falling_action": "#f59e0b",  # Amber
            "resolution": "#8b5cf6"       # Purple
        }
        color = colors.get(event.stage, "#6b7280")

        # Draw circle
        painter.setBrush(QBrush(QColor(color)))
        painter.setPen(QPen(QColor("white"), 2))

        # Size based on intensity
        size = 8 + (event.intensity / 100) * 8  # 8-16px radius
        painter.drawEllipse(QPointF(x, y), size, size)

        # Save position for click detection
        self._event_positions[event.id] = (x, y, size)

        # Draw event title next to marker
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        painter.setPen(QColor("#1a1a1a"))

        # Truncate long titles
        title = event.title[:20] if len(event.title) > 20 else event.title
        painter.drawText(int(x + size + 5), int(y + 4), title)

    def _draw_act_divisions(self, painter: QPainter, margin_left: float, margin_top: float,
                            width: float, height: float):
        """Draw vertical act division lines and labels.

        Args:
            painter: QPainter object
            margin_left: Left margin
            margin_top: Top margin
            width: Drawing width
            height: Drawing height
        """
        if self.num_acts <= 1:
            return

        # Act colors for background shading
        act_colors = [
            QColor(59, 130, 246, 30),   # Blue
            QColor(16, 185, 129, 30),   # Green
            QColor(239, 68, 68, 30),    # Red
            QColor(245, 158, 11, 30),   # Amber
            QColor(139, 92, 246, 30),   # Purple
        ]

        # Draw act background regions
        act_width = width / self.num_acts
        for i in range(self.num_acts):
            act_x = margin_left + i * act_width
            color = act_colors[i % len(act_colors)]
            painter.fillRect(
                int(act_x), int(margin_top - 20),
                int(act_width), int(height + 40),
                color
            )

        # Draw vertical division lines between acts
        pen = QPen(QColor("#9ca3af"), 2, Qt.PenStyle.DashLine)
        painter.setPen(pen)

        for i in range(1, self.num_acts):
            x = margin_left + i * act_width
            painter.drawLine(int(x), int(margin_top - 20), int(x), int(margin_top + height + 20))

        # Draw act labels at top
        font = QFont("Segoe UI", 11, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#1f2937"))

        for i in range(self.num_acts):
            act_x = margin_left + i * act_width
            act_name = self.act_names[i] if i < len(self.act_names) else f"Act {i+1}"

            # Center the label in the act region
            text_x = act_x + (act_width / 2) - (len(act_name) * 4)
            painter.drawText(int(text_x), int(margin_top - 25), act_name)
