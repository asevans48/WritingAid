"""Character timeline builder with life events."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox,
    QFormLayout, QGroupBox, QScrollArea, QSplitter, QInputDialog, QSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect
from PyQt6.QtGui import QPainter, QPen, QColor, QFont
from typing import List, Optional
import uuid

from src.models.worldbuilding_objects import CharacterLifeEvent, EnhancedCharacter


class CharacterTimelineVisualization(QWidget):
    """Visual timeline display for character life events."""

    event_clicked = pyqtSignal(str)  # event ID

    def __init__(self):
        """Initialize character timeline visualization."""
        super().__init__()
        self.events: List[CharacterLifeEvent] = []
        self.setMinimumHeight(200)
        self.setStyleSheet("background-color: white; border: 1px solid #e5e7eb; border-radius: 8px;")

    def set_events(self, events: List[CharacterLifeEvent]):
        """Set events to display."""
        # Sort by age if available, otherwise by order added
        self.events = sorted(events, key=lambda e: e.age if e.age is not None else 0)
        self.update()

    def paintEvent(self, event):
        """Draw timeline."""
        super().paintEvent(event)

        if not self.events:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QColor("#9ca3af"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No life events on timeline")
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

        # Draw events
        if len(self.events) > 0:
            spacing = (timeline_end - timeline_start) / max(1, len(self.events) - 1) if len(self.events) > 1 else 0

            for i, evt in enumerate(self.events):
                x = timeline_start + (i * spacing if len(self.events) > 1 else (timeline_end - timeline_start) // 2)

                # Event dot - color by type
                color = self._get_event_color(evt.event_type)
                painter.setBrush(QColor(color))
                painter.setPen(QPen(QColor("white"), 2))
                painter.drawEllipse(int(x - 8), int(line_y - 8), 16, 16)

                # Event name
                font = QFont("Segoe UI", 9)
                painter.setFont(font)
                painter.setPen(QColor("#1a1a1a"))

                # Alternate above/below
                text_y = line_y - 30 if i % 2 == 0 else line_y + 30

                text_rect = QRect(int(x - 60), int(text_y), 120, 40)
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, evt.title)

                # Age
                if evt.age is not None:
                    font_small = QFont("Segoe UI", 8)
                    painter.setFont(font_small)
                    painter.setPen(QColor("#6b7280"))
                    age_y = text_y + 25 if i % 2 == 0 else text_y - 15
                    age_rect = QRect(int(x - 60), int(age_y), 120, 20)
                    painter.drawText(age_rect, Qt.AlignmentFlag.AlignCenter, f"Age {evt.age}")

    def _get_event_color(self, event_type: str) -> str:
        """Get color based on event type."""
        colors = {
            "birth": "#10b981",      # Green
            "death": "#1f2937",      # Dark gray
            "achievement": "#f59e0b", # Amber
            "trauma": "#ef4444",     # Red
            "relationship": "#ec4899", # Pink
            "career": "#6366f1",     # Indigo
            "general": "#6b7280"     # Gray
        }
        return colors.get(event_type.lower(), "#6366f1")


class LifeEventEditor(QWidget):
    """Editor for a single life event."""

    content_changed = pyqtSignal()

    def __init__(self, event: CharacterLifeEvent):
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

        # Title
        self.title_edit = QLineEdit()
        self.title_edit.textChanged.connect(self.content_changed.emit)
        form.addRow("Event Title:", self.title_edit)

        # Date
        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText("e.g., Spring 1453, Year 10, 2145 CE")
        self.date_edit.textChanged.connect(self.content_changed.emit)
        form.addRow("Date:", self.date_edit)

        # Age
        self.age_spin = QSpinBox()
        self.age_spin.setMinimum(0)
        self.age_spin.setMaximum(10000)
        self.age_spin.setSpecialValueText("Unknown")
        form.addRow("Age:", self.age_spin)

        # Event type
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "General", "Birth", "Death", "Achievement", "Trauma",
            "Relationship", "Career", "Education", "Travel", "Other"
        ])
        self.type_combo.currentTextChanged.connect(self.content_changed.emit)
        form.addRow("Type:", self.type_combo)

        # Location
        self.location_edit = QLineEdit()
        form.addRow("Location:", self.location_edit)

        layout.addLayout(form)

        # Witnesses
        witnesses_group = QGroupBox("Witnesses (Other Characters)")
        witnesses_layout = QVBoxLayout(witnesses_group)

        self.witnesses_list = QListWidget()
        witnesses_layout.addWidget(self.witnesses_list)

        wit_btn_layout = QHBoxLayout()
        add_wit_btn = QPushButton("Add Witness")
        add_wit_btn.clicked.connect(self._add_witness)
        wit_btn_layout.addWidget(add_wit_btn)

        remove_wit_btn = QPushButton("Remove")
        remove_wit_btn.clicked.connect(self._remove_witness)
        wit_btn_layout.addWidget(remove_wit_btn)

        witnesses_layout.addLayout(wit_btn_layout)
        layout.addWidget(witnesses_group)

        # Description
        desc_label = QLabel("Description:")
        layout.addWidget(desc_label)

        self.description_edit = QTextEdit()
        self.description_edit.textChanged.connect(self.content_changed.emit)
        layout.addWidget(self.description_edit)

    def _load_event(self):
        """Load event data."""
        self.title_edit.setText(self.event.title)
        self.date_edit.setText(self.event.date)
        if self.event.age is not None:
            self.age_spin.setValue(self.event.age)
        self.type_combo.setCurrentText(self.event.event_type.title())
        if self.event.location:
            self.location_edit.setText(self.event.location)
        self.description_edit.setPlainText(self.event.description)

        for witness in self.event.witnesses:
            self.witnesses_list.addItem(witness)

    def _add_witness(self):
        """Add witness."""
        name, ok = QInputDialog.getText(self, "Add Witness", "Enter character name:")
        if ok and name:
            self.witnesses_list.addItem(name)

    def _remove_witness(self):
        """Remove witness."""
        current = self.witnesses_list.currentRow()
        if current >= 0:
            self.witnesses_list.takeItem(current)

    def save_to_model(self):
        """Save to event model."""
        self.event.title = self.title_edit.text()
        self.event.date = self.date_edit.text()
        self.event.age = self.age_spin.value() if self.age_spin.value() > 0 else None
        self.event.event_type = self.type_combo.currentText().lower()
        self.event.location = self.location_edit.text()
        self.event.description = self.description_edit.toPlainText()

        self.event.witnesses = [
            self.witnesses_list.item(i).text()
            for i in range(self.witnesses_list.count())
        ]


class CharacterTimelineWidget(QWidget):
    """Character timeline builder."""

    content_changed = pyqtSignal()

    def __init__(self, character: EnhancedCharacter):
        """Initialize character timeline builder."""
        super().__init__()
        self.character = character
        self.current_editor: Optional[LifeEventEditor] = None
        self._init_ui()
        self._load_events()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Timeline visualization
        self.timeline_viz = CharacterTimelineVisualization()
        layout.addWidget(self.timeline_viz)

        # Splitter for list and editor
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Event list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)

        label = QLabel("Life Events")
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

        placeholder = QLabel("Add or select a life event")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor_scroll.setWidget(placeholder)

        splitter.addWidget(self.editor_scroll)

        layout.addWidget(splitter)

    def _load_events(self):
        """Load character's life events."""
        self.event_list.clear()
        for event in self.character.life_events:
            item = QListWidgetItem(event.title)
            item.setData(Qt.ItemDataRole.UserRole, id(event))
            self.event_list.addItem(item)
        self._update_timeline()

    def _add_event(self):
        """Add new event."""
        title, ok = QInputDialog.getText(self, "New Life Event", "Enter event title:")

        if ok and title:
            event = CharacterLifeEvent(
                date="",
                age=None,
                event_type="general",
                title=title,
                description=""
            )
            self.character.life_events.append(event)

            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, id(event))
            self.event_list.addItem(item)

            self.event_list.setCurrentItem(item)
            self._update_timeline()

    def _remove_event(self):
        """Remove selected event."""
        current = self.event_list.currentItem()
        if current:
            event_id = current.data(Qt.ItemDataRole.UserRole)
            self.character.life_events = [
                e for e in self.character.life_events if id(e) != event_id
            ]
            self.event_list.takeItem(self.event_list.row(current))
            self._update_timeline()

    def _on_event_selected(self, current, previous):
        """Handle event selection."""
        if not current:
            return

        # Save previous
        if self.current_editor:
            self.current_editor.save_to_model()

        # Load selected
        event_id = current.data(Qt.ItemDataRole.UserRole)
        event = next((e for e in self.character.life_events if id(e) == event_id), None)

        if event:
            self.current_editor = LifeEventEditor(event)
            self.current_editor.content_changed.connect(self.content_changed.emit)
            self.current_editor.content_changed.connect(self._update_timeline)
            self.editor_scroll.setWidget(self.current_editor)

    def _update_timeline(self):
        """Update timeline visualization."""
        self.timeline_viz.set_events(self.character.life_events)

    def _ai_generate(self):
        """AI generate event."""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "AI Generation",
            f"AI will generate a life event for {self.character.name} based on their existing timeline and backstory."
        )

    def get_events(self) -> List[CharacterLifeEvent]:
        """Get all events."""
        if self.current_editor:
            self.current_editor.save_to_model()
        return self.character.life_events
