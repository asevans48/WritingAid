"""Visual Freytag Pyramid with intensity-based event positioning."""

from typing import List
import math
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPointF, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QBrush, QPainterPath

from src.models.project import PlotEvent


class FreytagPyramidVisual(QWidget):
    """Visual representation of Freytag's Pyramid with plot events."""

    event_clicked = pyqtSignal(str)  # event ID

    def __init__(self):
        """Initialize pyramid visual."""
        super().__init__()
        self.events: List[PlotEvent] = []
        self.setMinimumHeight(350)
        self.setMinimumWidth(600)
        self.setStyleSheet("background-color: white; border: 1px solid #e5e7eb; border-radius: 8px;")

    def set_events(self, events: List[PlotEvent]):
        """Set events to display on pyramid.

        Args:
            events: List of PlotEvent objects
        """
        self.events = events
        self.update()

    def paintEvent(self, event):
        """Draw the Freytag pyramid with events."""
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Define pyramid points
        width = self.width() - 40  # Margins
        height = self.height() - 80
        margin_left = 20
        margin_top = 40

        # Pyramid stages (5 points)
        # Exposition (start) → Rising Action → Climax (peak) → Falling Action → Resolution (end)
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

        # Calculate event positions
        stage_positions = {
            "exposition": (exposition_x, exposition_y, exposition_x, exposition_y),
            "rising_action": (exposition_x, exposition_y, climax_x, climax_y),
            "climax": (climax_x, climax_y, climax_x, climax_y),
            "falling_action": (climax_x, climax_y, resolution_x, resolution_y),
            "resolution": (resolution_x, resolution_y, resolution_x, resolution_y)
        }

        # Group events by stage
        events_by_stage = {}
        for evt in self.events:
            if evt.stage not in events_by_stage:
                events_by_stage[evt.stage] = []
            events_by_stage[evt.stage].append(evt)

        # Sort events within each stage by sort_order
        for stage in events_by_stage:
            events_by_stage[stage].sort(key=lambda e: e.sort_order)

        # Draw events
        for stage, stage_events in events_by_stage.items():
            if stage not in stage_positions:
                continue

            start_x, start_y, end_x, end_y = stage_positions[stage]

            if not stage_events:
                continue

            # Calculate positions along the line
            for idx, evt in enumerate(stage_events):
                # Position along horizontal axis based on sort_order
                if len(stage_events) == 1:
                    t = 0.5  # Center single event
                else:
                    t = idx / (len(stage_events) - 1)

                # Interpolate position
                pos_x = start_x + t * (end_x - start_x)
                pos_y = start_y + t * (end_y - start_y)

                # Adjust Y position based on intensity (0-100)
                # Higher intensity = closer to the pyramid line
                # Lower intensity = further from the pyramid line
                intensity_offset = (100 - evt.intensity) * 0.5  # Scale: 0-50 pixels
                pos_y += intensity_offset

                # Draw event marker
                self._draw_event(painter, pos_x, pos_y, evt)

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

        # Draw event title next to marker
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        painter.setPen(QColor("#1a1a1a"))

        # Truncate long titles
        title = event.title[:20] if len(event.title) > 20 else event.title
        painter.drawText(int(x + size + 5), int(y + 4), title)
