"""Timeline builder for historical events and character life events."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox,
    QFormLayout, QGroupBox, QScrollArea, QInputDialog, QDialog,
    QDialogButtonBox, QMessageBox, QToolBar
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QAction
from typing import List, Optional
import uuid
import re

from src.models.worldbuilding_objects import HistoricalEvent
from src.ui.worldbuilding.filter_sort_widget import FilterSortWidget


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


class HistoricalEventEditorDialog(QDialog):
    """Popup dialog for editing historical events."""

    def __init__(self, event: Optional[HistoricalEvent] = None, parent=None):
        """Initialize editor dialog."""
        super().__init__(parent)
        self.event = event
        self.setWindowTitle("Edit Historical Event" if event else "New Historical Event")
        self.resize(750, 600)
        self._init_ui()
        if event:
            self._load_event()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)

        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(16)

        # Basic Info Section
        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout(basic_group)

        # Name
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Enter event name")
        basic_layout.addRow("Event Name:", self.name_edit)

        # Date
        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText("e.g., Year 1453, 3rd Age, 2145 CE")
        basic_layout.addRow("Date:", self.date_edit)

        # Timestamp (for sorting)
        self.timestamp_edit = QLineEdit()
        self.timestamp_edit.setPlaceholderText("Optional numeric value for sorting/positioning")
        basic_layout.addRow("Timeline Position:", self.timestamp_edit)

        # Event type
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "General", "War", "Treaty", "Discovery", "Disaster",
            "Birth", "Death", "Founding", "Revolution", "Other"
        ])
        basic_layout.addRow("Type:", self.type_combo)

        # Location
        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("Where did this event occur?")
        basic_layout.addRow("Location:", self.location_edit)

        content_layout.addWidget(basic_group)

        # Key Figures Section
        figures_group = QGroupBox("Key Figures (Characters)")
        figures_layout = QVBoxLayout(figures_group)

        self.figures_list = QListWidget()
        self.figures_list.setMaximumHeight(120)
        figures_layout.addWidget(self.figures_list)

        fig_btn_layout = QHBoxLayout()
        add_fig_btn = QPushButton("Add Character")
        add_fig_btn.clicked.connect(self._add_figure)
        fig_btn_layout.addWidget(add_fig_btn)

        remove_fig_btn = QPushButton("Remove")
        remove_fig_btn.clicked.connect(self._remove_figure)
        fig_btn_layout.addWidget(remove_fig_btn)
        fig_btn_layout.addStretch()

        figures_layout.addLayout(fig_btn_layout)
        content_layout.addWidget(figures_group)

        # Description Section
        desc_group = QGroupBox("Description")
        desc_layout = QVBoxLayout(desc_group)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Describe what happened during this event...")
        self.description_edit.setMinimumHeight(150)
        desc_layout.addWidget(self.description_edit)

        content_layout.addWidget(desc_group)

        # Consequences Section
        cons_group = QGroupBox("Consequences & Impact")
        cons_layout = QVBoxLayout(cons_group)

        self.consequences_edit = QTextEdit()
        self.consequences_edit.setPlaceholderText("What were the consequences of this event?")
        self.consequences_edit.setMinimumHeight(100)
        cons_layout.addWidget(self.consequences_edit)

        content_layout.addWidget(cons_group)

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._save_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _load_event(self):
        """Load event data into form."""
        if not self.event:
            return

        self.name_edit.setText(self.event.name)
        self.date_edit.setText(self.event.date)
        if self.event.timestamp is not None:
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

    def _save_and_accept(self):
        """Validate and save."""
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Event name is required.")
            return

        self.accept()

    def get_event(self) -> HistoricalEvent:
        """Get event from form data."""
        event_id = self.event.id if self.event else str(uuid.uuid4())

        try:
            timestamp = int(self.timestamp_edit.text()) if self.timestamp_edit.text().strip() else None
        except ValueError:
            timestamp = None

        key_figures = [
            self.figures_list.item(i).text()
            for i in range(self.figures_list.count())
        ]

        return HistoricalEvent(
            id=event_id,
            name=self.name_edit.text().strip(),
            date=self.date_edit.text().strip(),
            timestamp=timestamp,
            event_type=self.type_combo.currentText().lower(),
            location=self.location_edit.text().strip() or None,
            description=self.description_edit.toPlainText(),
            consequences=self.consequences_edit.toPlainText(),
            key_figures=key_figures
        )


class TimelineBuilderWidget(QWidget):
    """Timeline builder for history with popup editor."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize timeline builder."""
        super().__init__()
        self.events: List[HistoricalEvent] = []
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Header
        header = QLabel("Historical Timeline")
        header.setStyleSheet("font-size: 16px; font-weight: 600; padding: 8px;")
        layout.addWidget(header)

        # Timeline visualization - KEPT AT TOP
        self.timeline_viz = TimelineVisualization()
        layout.addWidget(self.timeline_viz)

        # Filter and sort controls
        self.filter_sort = FilterSortWidget(
            sort_options=["Name", "Date", "Type"],
            filter_placeholder="Search events..."
        )
        self.filter_sort.set_filter_options([
            "All", "General", "War", "Treaty", "Discovery", "Disaster",
            "Birth", "Death", "Founding", "Revolution", "Other"
        ])
        self.filter_sort.filter_changed.connect(self._update_list)
        layout.addWidget(self.filter_sort)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet("QToolBar { spacing: 8px; padding: 4px; }")

        add_action = QAction("Add Event", self)
        add_action.triggered.connect(self._add_event)
        toolbar.addAction(add_action)

        edit_action = QAction("Edit", self)
        edit_action.triggered.connect(self._edit_event)
        toolbar.addAction(edit_action)

        remove_action = QAction("Remove", self)
        remove_action.triggered.connect(self._remove_event)
        toolbar.addAction(remove_action)

        toolbar.addSeparator()

        ai_action = QAction("AI Generate", self)
        ai_action.triggered.connect(self._ai_generate)
        toolbar.addAction(ai_action)

        layout.addWidget(toolbar)

        # Event list
        self.event_list = QListWidget()
        self.event_list.itemDoubleClicked.connect(self._edit_event)
        layout.addWidget(self.event_list)

    def _update_list(self):
        """Update the event list with filtering and sorting."""
        self.event_list.clear()

        def get_text(event):
            return f"{event.name} {event.date} {event.event_type}"

        def get_sort_value(event, sort_by):
            if sort_by == "Name":
                return event.name.lower()
            elif sort_by == "Date":
                return event.timestamp if event.timestamp is not None else 0
            elif sort_by == "Type":
                return event.event_type.lower()
            return event.name.lower()

        def get_type(event):
            return event.event_type.title()

        filtered_events = self.filter_sort.filter_and_sort(
            self.events,
            get_text,
            get_sort_value,
            get_type
        )

        for event in filtered_events:
            display_text = f"{event.name}"
            if event.date:
                display_text += f" ({event.date})"
            display_text += f" - {event.event_type.title()}"

            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, event.id)
            self.event_list.addItem(item)

    def _add_event(self):
        """Add new event via popup dialog."""
        dialog = HistoricalEventEditorDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            event = dialog.get_event()
            self.events.append(event)
            self._update_list()
            self._update_timeline()
            self.content_changed.emit()

    def _edit_event(self):
        """Edit selected event via popup dialog."""
        current = self.event_list.currentItem()
        if not current:
            QMessageBox.information(self, "No Selection", "Please select an event to edit.")
            return

        event_id = current.data(Qt.ItemDataRole.UserRole)
        event = next((e for e in self.events if e.id == event_id), None)

        if event:
            dialog = HistoricalEventEditorDialog(event=event, parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                updated_event = dialog.get_event()
                # Update in list
                for i, e in enumerate(self.events):
                    if e.id == event_id:
                        self.events[i] = updated_event
                        break
                self._update_list()
                self._update_timeline()
                self.content_changed.emit()

    def _remove_event(self):
        """Remove selected event."""
        current = self.event_list.currentItem()
        if not current:
            QMessageBox.information(self, "No Selection", "Please select an event to remove.")
            return

        event_id = current.data(Qt.ItemDataRole.UserRole)
        event = next((e for e in self.events if e.id == event_id), None)

        if event:
            reply = QMessageBox.question(
                self,
                "Confirm Removal",
                f"Remove event '{event.name}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.events = [e for e in self.events if e.id != event_id]
                self._update_list()
                self._update_timeline()
                self.content_changed.emit()

    def _update_timeline(self):
        """Update timeline visualization."""
        self.timeline_viz.set_events(self.events)

    def _ai_generate(self):
        """AI generate event."""
        QMessageBox.information(
            self,
            "AI Generation",
            "AI will generate a new historical event based on your existing timeline."
        )

    def get_events(self) -> List[HistoricalEvent]:
        """Get all events."""
        return self.events

    def load_events(self, events: List[HistoricalEvent]):
        """Load events."""
        self.events = events
        self._update_list()
        self._update_timeline()
