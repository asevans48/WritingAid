"""Timeline builder for historical events and character life events."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox,
    QFormLayout, QGroupBox, QScrollArea, QSplitter, QInputDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect
from PyQt6.QtGui import QPainter, QPen, QColor, QFont
from typing import List, Optional
import uuid
from datetime import datetime
import re

from src.models.worldbuilding_objects import HistoricalEvent, CharacterLifeEvent


class TimelineVisualization(QWidget):
    """Visual timeline display."""

    event_clicked = pyqtSignal(str)  # event ID

    def __init__(self):
        """Initialize timeline visualization."""
        super().__init__()
        self.events: List[HistoricalEvent] = []
        self.setMinimumHeight(200)
        self.setStyleSheet("background-color: white; border: 1px solid #e5e7eb; border-radius: 8px;")

    def _parse_date(self, date_str: str) -> Optional[int]:
        """Parse date string to numeric value for sorting and spacing."""
        if not date_str:
            return None

        # Try to extract year from various formats
        # Format: YYYY, Year YYYY, YYYY CE/BCE/AD/BC, etc.
        patterns = [
            r'(\d{1,4})\s*(?:CE|AD)',      # 2024 CE, 100 AD
            r'(\d{1,4})\s*(?:BCE|BC)',     # 500 BCE, 100 BC (negative)
            r'Year\s*(\d+)',               # Year 1453
            r'(\d{1,4})',                  # Just a number: 2024, 1453
        ]

        for pattern in patterns:
            match = re.search(pattern, date_str, re.IGNORECASE)
            if match:
                year = int(match.group(1))
                # If BCE/BC, make negative
                if re.search(r'BCE|BC', date_str, re.IGNORECASE):
                    year = -year
                return year

        return None

    def set_events(self, events: List[HistoricalEvent]):
        """Set events to display."""
        # Parse dates and use as timestamp if available
        for event in events:
            parsed_date = self._parse_date(event.date)
            if parsed_date is not None and event.timestamp is None:
                event.timestamp = parsed_date

        # Sort by timestamp
        self.events = sorted(events, key=lambda e: e.timestamp if e.timestamp is not None else 0)
        self.update()

    def paintEvent(self, event):
        """Draw timeline."""
        super().paintEvent(event)

        if not self.events:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QColor("#9ca3af"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No events on timeline")
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw timeline line
        margin = 50
        line_y = self.height() // 2
        timeline_start = margin
        timeline_end = self.width() - margin

        # Main timeline line
        pen = QPen(QColor("#6366f1"), 3)
        painter.setPen(pen)
        painter.drawLine(timeline_start, line_y, timeline_end, line_y)

        # Draw events with proportional spacing based on timestamps
        if len(self.events) > 0:
            # Get timestamp range
            timestamps = [e.timestamp for e in self.events if e.timestamp is not None]

            if len(timestamps) > 1:
                min_time = min(timestamps)
                max_time = max(timestamps)
                time_range = max_time - min_time

                if time_range > 0:
                    # Use proportional spacing based on actual time
                    for i, evt in enumerate(self.events):
                        if evt.timestamp is not None:
                            # Calculate position based on timestamp
                            time_ratio = (evt.timestamp - min_time) / time_range
                            x = timeline_start + time_ratio * (timeline_end - timeline_start)
                        else:
                            # Fallback to even spacing if no timestamp
                            x = timeline_start + (i * (timeline_end - timeline_start) / max(1, len(self.events) - 1))

                        self._draw_event(painter, evt, x, line_y, i)
                else:
                    # All events at same time, use even spacing
                    for i, evt in enumerate(self.events):
                        spacing = (timeline_end - timeline_start) / max(1, len(self.events) - 1) if len(self.events) > 1 else 0
                        x = timeline_start + (i * spacing if len(self.events) > 1 else (timeline_end - timeline_start) // 2)
                        self._draw_event(painter, evt, x, line_y, i)
            else:
                # Single event or no timestamps, use even spacing
                for i, evt in enumerate(self.events):
                    spacing = (timeline_end - timeline_start) / max(1, len(self.events) - 1) if len(self.events) > 1 else 0
                    x = timeline_start + (i * spacing if len(self.events) > 1 else (timeline_end - timeline_start) // 2)
                    self._draw_event(painter, evt, x, line_y, i)

    def _draw_event(self, painter: QPainter, evt: HistoricalEvent, x: float, line_y: int, index: int):
        """Draw a single event on the timeline."""
        # Event dot
        painter.setBrush(QColor("#6366f1"))
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawEllipse(int(x - 8), int(line_y - 8), 16, 16)

        # Event name
        font = QFont("Segoe UI", 9)
        painter.setFont(font)
        painter.setPen(QColor("#1a1a1a"))

        # Alternate above/below
        text_y = line_y - 30 if index % 2 == 0 else line_y + 30

        text_rect = QRect(int(x - 60), int(text_y), 120, 40)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, evt.name)

        # Date
        font_small = QFont("Segoe UI", 8)
        painter.setFont(font_small)
        painter.setPen(QColor("#6b7280"))
        date_y = text_y + 25 if index % 2 == 0 else text_y - 15
        date_rect = QRect(int(x - 60), int(date_y), 120, 20)
        painter.drawText(date_rect, Qt.AlignmentFlag.AlignCenter, evt.date)


class HistoricalEventEditor(QWidget):
    """Editor for a historical event."""

    content_changed = pyqtSignal()

    def __init__(self, event: HistoricalEvent):
        """Initialize editor."""
        super().__init__()
        self.event = event
        self._init_ui()
        self._load_event()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()

        # Name
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self.content_changed.emit)
        form.addRow("Event Name:", self.name_edit)

        # Date
        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText("e.g., Year 1453, 3rd Age, 2145 CE")
        self.date_edit.textChanged.connect(self.content_changed.emit)
        form.addRow("Date:", self.date_edit)

        # Timestamp (for sorting)
        self.timestamp_edit = QLineEdit()
        self.timestamp_edit.setPlaceholderText("Optional numeric value for sorting")
        form.addRow("Timeline Position:", self.timestamp_edit)

        # Event type
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "General", "War", "Treaty", "Discovery", "Disaster",
            "Birth", "Death", "Founding", "Revolution", "Other"
        ])
        self.type_combo.currentTextChanged.connect(self.content_changed.emit)
        form.addRow("Type:", self.type_combo)

        # Location
        self.location_edit = QLineEdit()
        form.addRow("Location:", self.location_edit)

        layout.addLayout(form)

        # Key Figures
        figures_group = QGroupBox("Key Figures (Characters)")
        figures_layout = QVBoxLayout(figures_group)

        self.figures_list = QListWidget()
        figures_layout.addWidget(self.figures_list)

        fig_btn_layout = QHBoxLayout()
        add_fig_btn = QPushButton("Add Character")
        add_fig_btn.clicked.connect(self._add_figure)
        fig_btn_layout.addWidget(add_fig_btn)

        remove_fig_btn = QPushButton("Remove")
        remove_fig_btn.clicked.connect(self._remove_figure)
        fig_btn_layout.addWidget(remove_fig_btn)

        figures_layout.addLayout(fig_btn_layout)
        layout.addWidget(figures_group)

        # Description
        desc_label = QLabel("Description:")
        layout.addWidget(desc_label)

        self.description_edit = QTextEdit()
        self.description_edit.textChanged.connect(self.content_changed.emit)
        layout.addWidget(self.description_edit)

        # Consequences
        cons_label = QLabel("Consequences:")
        layout.addWidget(cons_label)

        self.consequences_edit = QTextEdit()
        self.consequences_edit.setMaximumHeight(100)
        layout.addWidget(self.consequences_edit)

    def _load_event(self):
        """Load event data."""
        self.name_edit.setText(self.event.name)
        self.date_edit.setText(self.event.date)
        if self.event.timestamp:
            self.timestamp_edit.setText(str(self.event.timestamp))
        self.type_combo.setCurrentText(self.event.event_type.title())
        if self.event.location:
            self.location_edit.setText(self.event.location)
        self.description_edit.setPlainText(self.event.description)
        self.consequences_edit.setPlainText(self.event.consequences)

        for figure in self.event.key_figures:
            self.figures_list.addItem(figure)

    def _add_figure(self):
        """Add key figure."""
        name, ok = QInputDialog.getText(self, "Add Character", "Enter character name:")
        if ok and name:
            self.figures_list.addItem(name)

    def _remove_figure(self):
        """Remove key figure."""
        current = self.figures_list.currentRow()
        if current >= 0:
            self.figures_list.takeItem(current)

    def save_to_model(self):
        """Save to event model."""
        self.event.name = self.name_edit.text()
        self.event.date = self.date_edit.text()

        try:
            self.event.timestamp = int(self.timestamp_edit.text()) if self.timestamp_edit.text() else None
        except:
            self.event.timestamp = None

        self.event.event_type = self.type_combo.currentText().lower()
        self.event.location = self.location_edit.text()
        self.event.description = self.description_edit.toPlainText()
        self.event.consequences = self.consequences_edit.toPlainText()

        self.event.key_figures = [
            self.figures_list.item(i).text()
            for i in range(self.figures_list.count())
        ]


class TimelineBuilderWidget(QWidget):
    """Timeline builder for history."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize timeline builder."""
        super().__init__()
        self.events: List[HistoricalEvent] = []
        self.current_editor: Optional[HistoricalEventEditor] = None
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Timeline visualization
        self.timeline_viz = TimelineVisualization()
        layout.addWidget(self.timeline_viz)

        # Splitter for list and editor
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Event list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)

        label = QLabel("Historical Events")
        label.setStyleSheet("font-weight: 600; font-size: 13px;")
        left_layout.addWidget(label)

        self.event_list = QListWidget()
        self.event_list.currentItemChanged.connect(self._on_event_selected)
        left_layout.addWidget(self.event_list)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Add Event")
        add_btn.clicked.connect(self._add_event)
        btn_layout.addWidget(add_btn)

        ai_btn = QPushButton("✨ AI Generate")
        ai_btn.clicked.connect(self._ai_generate)
        btn_layout.addWidget(ai_btn)

        remove_btn = QPushButton("🗑️")
        remove_btn.setMaximumWidth(40)
        remove_btn.clicked.connect(self._remove_event)
        btn_layout.addWidget(remove_btn)

        left_layout.addLayout(btn_layout)

        left_panel.setMaximumWidth(280)
        splitter.addWidget(left_panel)

        # Right: Event editor
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)

        placeholder = QLabel("Add or select an event")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor_scroll.setWidget(placeholder)

        splitter.addWidget(self.editor_scroll)

        layout.addWidget(splitter)

    def _add_event(self):
        """Add new event."""
        name, ok = QInputDialog.getText(self, "New Event", "Enter event name:")

        if ok and name:
            event = HistoricalEvent(
                id=str(uuid.uuid4()),
                name=name,
                date="",
                timestamp=len(self.events)  # Default position
            )
            self.events.append(event)

            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, event.id)
            self.event_list.addItem(item)

            self.event_list.setCurrentItem(item)
            self._update_timeline()

    def _remove_event(self):
        """Remove selected event."""
        current = self.event_list.currentItem()
        if current:
            event_id = current.data(Qt.ItemDataRole.UserRole)
            self.events = [e for e in self.events if e.id != event_id]
            self.event_list.takeItem(self.event_list.row(current))
            self._update_timeline()
            self.content_changed.emit()

    def _on_event_selected(self, current, previous):
        """Handle event selection."""
        if not current:
            return

        # Save previous
        if self.current_editor:
            self.current_editor.save_to_model()

        # Load selected
        event_id = current.data(Qt.ItemDataRole.UserRole)
        event = next((e for e in self.events if e.id == event_id), None)

        if event:
            self.current_editor = HistoricalEventEditor(event)
            self.current_editor.content_changed.connect(self.content_changed.emit)
            self.current_editor.content_changed.connect(self._update_timeline)
            self.editor_scroll.setWidget(self.current_editor)

    def _update_timeline(self):
        """Update timeline visualization."""
        self.timeline_viz.set_events(self.events)

    def _ai_generate(self):
        """AI generate event."""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "AI Generation",
            "AI will generate a new historical event based on your existing timeline."
        )

    def get_events(self) -> List[HistoricalEvent]:
        """Get all events."""
        if self.current_editor:
            self.current_editor.save_to_model()
        return self.events

    def load_events(self, events: List[HistoricalEvent]):
        """Load events."""
        self.events = events
        self.event_list.clear()

        for event in events:
            item = QListWidgetItem(event.name)
            item.setData(Qt.ItemDataRole.UserRole, event.id)
            self.event_list.addItem(item)

        self._update_timeline()
