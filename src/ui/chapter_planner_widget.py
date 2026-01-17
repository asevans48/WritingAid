"""Chapter Planner Widget - Plan chapters with AI assistance."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QSplitter, QGroupBox, QComboBox, QMessageBox,
    QProgressBar, QScrollArea, QFrame, QTabWidget, QListWidget,
    QListWidgetItem, QLineEdit, QCheckBox, QSlider, QSpinBox,
    QSizePolicy
)
from PyQt6.QtCore import pyqtSignal, Qt, QRectF, QPointF
from PyQt6.QtGui import QFont, QTextCursor, QPainter, QPen, QBrush, QColor, QPainterPath
from typing import Optional, Callable, List
import threading
import uuid


class TodoItemWidget(QWidget):
    """Widget for a single todo item."""

    changed = pyqtSignal()
    delete_requested = pyqtSignal(str)  # item_id

    def __init__(self, item_id: str, text: str = "", completed: bool = False, priority: str = "normal"):
        super().__init__()
        self.item_id = item_id
        self._init_ui(text, completed, priority)

    def _init_ui(self, text: str, completed: bool, priority: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        # Checkbox
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(completed)
        self.checkbox.stateChanged.connect(self._on_changed)
        layout.addWidget(self.checkbox)

        # Priority indicator
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["low", "normal", "high"])
        self.priority_combo.setCurrentText(priority)
        self.priority_combo.setMaximumWidth(70)
        self.priority_combo.currentTextChanged.connect(self._on_changed)
        layout.addWidget(self.priority_combo)

        # Text
        self.text_edit = QLineEdit(text)
        self.text_edit.setPlaceholderText("Enter task...")
        self.text_edit.textChanged.connect(self._on_changed)
        layout.addWidget(self.text_edit)

        # Delete button
        delete_btn = QPushButton("×")
        delete_btn.setMaximumWidth(25)
        delete_btn.setStyleSheet("color: red;")
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.item_id))
        layout.addWidget(delete_btn)

        self._update_style()

    def _on_changed(self):
        self._update_style()
        self.changed.emit()

    def _update_style(self):
        if self.checkbox.isChecked():
            self.text_edit.setStyleSheet("text-decoration: line-through; color: gray;")
        else:
            priority = self.priority_combo.currentText()
            if priority == "high":
                self.text_edit.setStyleSheet("color: #dc2626; font-weight: bold;")
            elif priority == "low":
                self.text_edit.setStyleSheet("color: #6b7280;")
            else:
                self.text_edit.setStyleSheet("")

    def get_data(self) -> dict:
        return {
            'id': self.item_id,
            'text': self.text_edit.text(),
            'completed': self.checkbox.isChecked(),
            'priority': self.priority_combo.currentText()
        }


class StoryEventWidget(QWidget):
    """Widget for a single story event in the outline."""

    changed = pyqtSignal()
    delete_requested = pyqtSignal(str)  # event_id
    arc_position_changed = pyqtSignal(str, int)  # event_id, position

    # Arc stage constants
    STAGES = ["exposition", "rising", "climax", "falling", "resolution"]
    STAGE_NAMES = {
        "exposition": "Exposition",
        "rising": "Rising Action",
        "climax": "Climax",
        "falling": "Falling Action",
        "resolution": "Resolution"
    }

    def __init__(self, event_id: str, text: str = "", completed: bool = False,
                 stage: str = "rising", arc_position: int = 50, order: int = 0):
        super().__init__()
        self.event_id = event_id
        self.order = order
        self._init_ui(text, completed, stage, arc_position)

    def _init_ui(self, text: str, completed: bool, stage: str, arc_position: int):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Order/number label
        self.order_label = QLabel(f"{self.order + 1}.")
        self.order_label.setMinimumWidth(25)
        self.order_label.setStyleSheet("font-weight: bold; color: #6366f1;")
        layout.addWidget(self.order_label)

        # Checkbox for completion
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(completed)
        self.checkbox.setToolTip("Mark event as written")
        self.checkbox.stateChanged.connect(self._on_changed)
        layout.addWidget(self.checkbox)

        # Event text
        self.text_edit = QLineEdit(text)
        self.text_edit.setPlaceholderText("Describe what happens...")
        self.text_edit.textChanged.connect(self._on_changed)
        layout.addWidget(self.text_edit, 1)

        # Stage selector
        self.stage_combo = QComboBox()
        for s in self.STAGES:
            self.stage_combo.addItem(self.STAGE_NAMES[s], s)
        idx = self.STAGES.index(stage) if stage in self.STAGES else 1
        self.stage_combo.setCurrentIndex(idx)
        self.stage_combo.setMaximumWidth(120)
        self.stage_combo.setToolTip("Arc stage")
        self.stage_combo.currentIndexChanged.connect(self._on_stage_changed)
        layout.addWidget(self.stage_combo)

        # Arc position slider (0-100, where 50 is the climax peak)
        self.arc_slider = QSlider(Qt.Orientation.Horizontal)
        self.arc_slider.setRange(0, 100)
        self.arc_slider.setValue(arc_position)
        self.arc_slider.setMaximumWidth(80)
        self.arc_slider.setToolTip("Position on the chapter arc (left=start, right=end)")
        self.arc_slider.valueChanged.connect(self._on_arc_changed)
        layout.addWidget(self.arc_slider)

        # Delete button
        delete_btn = QPushButton("×")
        delete_btn.setMaximumWidth(25)
        delete_btn.setStyleSheet("color: #ef4444;")
        delete_btn.setToolTip("Remove event")
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.event_id))
        layout.addWidget(delete_btn)

        self._update_style()

    def _on_changed(self):
        self._update_style()
        self.changed.emit()

    def _on_stage_changed(self, idx):
        # Auto-adjust arc position based on stage
        stage = self.stage_combo.currentData()
        default_positions = {
            "exposition": 10,
            "rising": 35,
            "climax": 50,
            "falling": 70,
            "resolution": 90
        }
        self.arc_slider.blockSignals(True)
        self.arc_slider.setValue(default_positions.get(stage, 50))
        self.arc_slider.blockSignals(False)
        self._on_changed()
        self.arc_position_changed.emit(self.event_id, self.arc_slider.value())

    def _on_arc_changed(self, value):
        self.arc_position_changed.emit(self.event_id, value)
        self.changed.emit()

    def _update_style(self):
        if self.checkbox.isChecked():
            self.text_edit.setStyleSheet("text-decoration: line-through; color: #9ca3af;")
            self.order_label.setStyleSheet("font-weight: bold; color: #9ca3af;")
        else:
            stage = self.stage_combo.currentData()
            colors = {
                "exposition": "#3b82f6",  # blue
                "rising": "#22c55e",  # green
                "climax": "#ef4444",  # red
                "falling": "#f97316",  # orange
                "resolution": "#8b5cf6"  # purple
            }
            color = colors.get(stage, "#6366f1")
            self.text_edit.setStyleSheet("")
            self.order_label.setStyleSheet(f"font-weight: bold; color: {color};")

    def set_order(self, order: int):
        """Update the order number."""
        self.order = order
        self.order_label.setText(f"{order + 1}.")

    def get_data(self) -> dict:
        return {
            'id': self.event_id,
            'text': self.text_edit.text(),
            'completed': self.checkbox.isChecked(),
            'stage': self.stage_combo.currentData(),
            'arc_position': self.arc_slider.value(),
            'order': self.order
        }


class ChapterArcWidget(QWidget):
    """Visual representation of the chapter's narrative arc with event markers."""

    event_clicked = pyqtSignal(str)  # event_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.events = []  # List of event dicts with arc_position
        self.setMinimumHeight(120)
        self.setMaximumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_events(self, events: List[dict]):
        """Set the events to display on the arc."""
        self.events = sorted(events, key=lambda e: e.get('arc_position', 50))
        self.update()

    def paintEvent(self, event):
        """Draw the narrative arc and event markers."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        padding = 20
        arc_height = height - 50

        # Draw background
        painter.fillRect(self.rect(), QColor("#fafafa"))

        # Draw arc path (Freytag's pyramid style)
        path = QPainterPath()
        start_x = padding
        end_x = width - padding
        arc_width = end_x - start_x

        # Define the arc shape (rises to climax at center, then falls)
        base_y = height - 25
        peak_y = 25

        # Create smooth arc using quadratic curves
        path.moveTo(start_x, base_y)

        # Rising action to climax
        climax_x = start_x + arc_width * 0.5
        path.quadTo(
            start_x + arc_width * 0.25, base_y - (base_y - peak_y) * 0.3,
            climax_x, peak_y
        )

        # Climax to resolution
        path.quadTo(
            start_x + arc_width * 0.75, base_y - (base_y - peak_y) * 0.3,
            end_x, base_y
        )

        # Draw arc line
        pen = QPen(QColor("#e5e7eb"), 3)
        painter.setPen(pen)
        painter.drawPath(path)

        # Draw filled area under arc
        fill_path = QPainterPath(path)
        fill_path.lineTo(end_x, base_y)
        fill_path.lineTo(start_x, base_y)
        fill_path.closeSubpath()
        painter.fillPath(fill_path, QBrush(QColor("#f3f4f6")))

        # Draw stage labels
        painter.setPen(QPen(QColor("#9ca3af")))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        labels = [
            ("Exposition", 0.08),
            ("Rising", 0.30),
            ("Climax", 0.50),
            ("Falling", 0.70),
            ("Resolution", 0.92)
        ]

        for label, pos in labels:
            x = start_x + arc_width * pos
            painter.drawText(int(x - 30), height - 5, 60, 15,
                           Qt.AlignmentFlag.AlignCenter, label)

        # Draw event markers
        stage_colors = {
            "exposition": QColor("#3b82f6"),
            "rising": QColor("#22c55e"),
            "climax": QColor("#ef4444"),
            "falling": QColor("#f97316"),
            "resolution": QColor("#8b5cf6")
        }

        for event in self.events:
            pos = event.get('arc_position', 50) / 100.0
            stage = event.get('stage', 'rising')
            completed = event.get('completed', False)

            # Calculate x position
            x = start_x + arc_width * pos

            # Calculate y position on the arc
            if pos <= 0.5:
                # Rising portion
                t = pos / 0.5
                y = base_y - (base_y - peak_y) * (t * t)  # Quadratic ease-in
            else:
                # Falling portion
                t = (pos - 0.5) / 0.5
                y = peak_y + (base_y - peak_y) * (t * t)  # Quadratic ease-out

            # Draw marker
            color = stage_colors.get(stage, QColor("#6366f1"))
            if completed:
                color = QColor("#9ca3af")

            painter.setPen(QPen(color.darker(120), 2))
            painter.setBrush(QBrush(color if not completed else QColor("#d1d5db")))

            radius = 8 if not completed else 6
            painter.drawEllipse(QPointF(x, y), radius, radius)

            # Draw event number
            order = event.get('order', 0)
            painter.setPen(QPen(QColor("white" if not completed else "#666")))
            font.setPointSize(7)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(int(x - 10), int(y - 10), 20, 20,
                           Qt.AlignmentFlag.AlignCenter, str(order + 1))

        painter.end()

    def mousePressEvent(self, event):
        """Handle clicks on event markers."""
        pos = event.position()
        width = self.width()
        padding = 20
        arc_width = width - 2 * padding

        for ev in self.events:
            ev_pos = ev.get('arc_position', 50) / 100.0
            x = padding + arc_width * ev_pos

            # Check if click is near this marker
            if abs(pos.x() - x) < 15:
                self.event_clicked.emit(ev.get('id', ''))
                break


class ChapterPlannerWidget(QWidget):
    """Widget for planning chapters with AI assistance."""

    plan_changed = pyqtSignal()  # Emitted when any planning content changes
    check_requested = pyqtSignal(str, str)  # plan, chapter_content - for consistency check

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ai_handler: Optional[Callable] = None
        self._context_provider: Optional[Callable] = None
        self._chapter_content_provider: Optional[Callable] = None
        self._is_processing = False
        self._todo_widgets: List[TodoItemWidget] = []
        self._event_widgets: List[StoryEventWidget] = []
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        header = QLabel("Chapter Planning")
        header.setStyleSheet("font-size: 14px; font-weight: 600; color: #1a1a1a; padding: 4px;")
        layout.addWidget(header)

        # Info label
        info_label = QLabel("Plan your chapter here. Planning data is NOT exported with your manuscript.")
        info_label.setStyleSheet("color: #666; font-size: 11px; font-style: italic; padding: 2px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Main tab widget for different planning sections
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)

        # === TAB 1: Events (Story Arc) ===
        events_tab = QWidget()
        events_layout = QVBoxLayout(events_tab)
        events_layout.setSpacing(8)

        # Arc visualization
        arc_group = QGroupBox("Chapter Arc")
        arc_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        arc_layout = QVBoxLayout(arc_group)

        self.arc_widget = ChapterArcWidget()
        self.arc_widget.event_clicked.connect(self._on_arc_event_clicked)
        arc_layout.addWidget(self.arc_widget)

        events_layout.addWidget(arc_group)

        # Events list
        events_list_group = QGroupBox("Story Events (in order)")
        events_list_layout = QVBoxLayout(events_list_group)

        # Events header with add button
        events_header = QHBoxLayout()
        events_label = QLabel("Add events that happen in this chapter:")
        events_label.setStyleSheet("font-size: 11px; color: #666;")
        events_header.addWidget(events_label)
        events_header.addStretch()

        add_event_btn = QPushButton("+ Add Event")
        add_event_btn.clicked.connect(lambda: self._add_event_item())
        events_header.addWidget(add_event_btn)

        events_list_layout.addLayout(events_header)

        # Scroll area for events
        events_scroll = QScrollArea()
        events_scroll.setWidgetResizable(True)
        events_scroll.setFrameShape(QFrame.Shape.NoFrame)
        events_scroll.setMinimumHeight(150)

        self.events_container = QWidget()
        self.events_list_layout = QVBoxLayout(self.events_container)
        self.events_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.events_list_layout.setSpacing(2)

        events_scroll.setWidget(self.events_container)
        events_list_layout.addWidget(events_scroll)

        events_layout.addWidget(events_list_group)

        # Quick actions for events
        events_actions = QHBoxLayout()

        self.generate_events_btn = QPushButton("Generate Events with AI")
        self.generate_events_btn.setToolTip("Use AI to suggest story events")
        self.generate_events_btn.clicked.connect(self._generate_events)
        events_actions.addWidget(self.generate_events_btn)

        self.reorder_events_btn = QPushButton("Auto-Order by Arc")
        self.reorder_events_btn.setToolTip("Reorder events by their arc position")
        self.reorder_events_btn.clicked.connect(self._reorder_events_by_arc)
        events_actions.addWidget(self.reorder_events_btn)

        events_actions.addStretch()
        events_layout.addLayout(events_actions)

        self.tab_widget.addTab(events_tab, "Events")

        # === TAB 2: Description ===
        description_tab = QWidget()
        description_layout = QVBoxLayout(description_tab)

        desc_label = QLabel("Brief description of what happens in this chapter:")
        desc_label.setStyleSheet("font-weight: 500;")
        description_layout.addWidget(desc_label)

        self.description_editor = QTextEdit()
        self.description_editor.setPlaceholderText(
            "Write a brief summary of this chapter...\n\n"
            "Example: \"Sarah discovers the hidden letter in her grandmother's attic, "
            "leading to a confrontation with her estranged uncle about the family secret.\""
        )
        self.description_editor.setFont(QFont("Segoe UI", 11))
        self.description_editor.setMaximumHeight(150)
        self.description_editor.textChanged.connect(self._on_plan_changed)
        description_layout.addWidget(self.description_editor)

        # POV and Timeline
        meta_layout = QHBoxLayout()

        pov_label = QLabel("POV Character:")
        meta_layout.addWidget(pov_label)
        self.pov_edit = QLineEdit()
        self.pov_edit.setPlaceholderText("Who's perspective?")
        self.pov_edit.textChanged.connect(self._on_plan_changed)
        meta_layout.addWidget(self.pov_edit)

        timeline_label = QLabel("Timeline:")
        meta_layout.addWidget(timeline_label)
        self.timeline_edit = QLineEdit()
        self.timeline_edit.setPlaceholderText("When does this occur?")
        self.timeline_edit.textChanged.connect(self._on_plan_changed)
        meta_layout.addWidget(self.timeline_edit)

        description_layout.addLayout(meta_layout)

        # Characters and Locations
        chars_locs_layout = QHBoxLayout()

        chars_group = QGroupBox("Characters Featured")
        chars_layout = QVBoxLayout(chars_group)
        self.characters_edit = QLineEdit()
        self.characters_edit.setPlaceholderText("Character names, comma-separated")
        self.characters_edit.textChanged.connect(self._on_plan_changed)
        chars_layout.addWidget(self.characters_edit)
        chars_locs_layout.addWidget(chars_group)

        locs_group = QGroupBox("Locations")
        locs_layout = QVBoxLayout(locs_group)
        self.locations_edit = QLineEdit()
        self.locations_edit.setPlaceholderText("Locations, comma-separated")
        self.locations_edit.textChanged.connect(self._on_plan_changed)
        locs_layout.addWidget(self.locations_edit)
        chars_locs_layout.addWidget(locs_group)

        description_layout.addLayout(chars_locs_layout)
        description_layout.addStretch()

        self.tab_widget.addTab(description_tab, "Description")

        # === TAB 3: Todo List ===
        todo_tab = QWidget()
        todo_layout = QVBoxLayout(todo_tab)

        todo_header = QHBoxLayout()
        todo_label = QLabel("Writing Tasks for this Chapter:")
        todo_label.setStyleSheet("font-weight: 500;")
        todo_header.addWidget(todo_label)

        add_todo_btn = QPushButton("+ Add Task")
        add_todo_btn.clicked.connect(self._add_todo_item)
        todo_header.addWidget(add_todo_btn)

        todo_header.addStretch()
        todo_layout.addLayout(todo_header)

        # Scroll area for todos
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.todo_container = QWidget()
        self.todo_list_layout = QVBoxLayout(self.todo_container)
        self.todo_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.todo_list_layout.setSpacing(2)

        scroll.setWidget(self.todo_container)
        todo_layout.addWidget(scroll)

        self.tab_widget.addTab(todo_tab, "Todo List")

        # === TAB 4: Notes ===
        notes_tab = QWidget()
        notes_layout = QVBoxLayout(notes_tab)

        notes_label = QLabel("Research, ideas, and reminders:")
        notes_label.setStyleSheet("font-weight: 500;")
        notes_layout.addWidget(notes_label)

        self.notes_editor = QTextEdit()
        self.notes_editor.setPlaceholderText(
            "Add any notes for this chapter...\n\n"
            "- Research needed\n"
            "- Ideas to explore\n"
            "- Things to remember\n"
            "- Questions to resolve"
        )
        self.notes_editor.setFont(QFont("Segoe UI", 11))
        self.notes_editor.textChanged.connect(self._on_plan_changed)
        notes_layout.addWidget(self.notes_editor)

        self.tab_widget.addTab(notes_tab, "Notes")

        # === TAB 5: AI Assistant ===
        ai_tab = QWidget()
        ai_layout = QVBoxLayout(ai_tab)

        # Model selector
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["Claude (Anthropic)", "GPT-4 (OpenAI)", "Gemini (Google)", "Local SLM"])
        model_layout.addWidget(self.model_combo)
        model_layout.addStretch()
        ai_layout.addLayout(model_layout)

        # Chat history
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setFont(QFont("Segoe UI", 10))
        self.chat_history.setStyleSheet("background-color: #f8f9fa;")
        self.chat_history.setPlaceholderText("AI responses will appear here...")
        ai_layout.addWidget(self.chat_history)

        # Chat input
        input_layout = QHBoxLayout()
        self.chat_input = QTextEdit()
        self.chat_input.setPlaceholderText("Ask AI about your chapter plan...")
        self.chat_input.setMaximumHeight(60)
        input_layout.addWidget(self.chat_input)

        send_btn_layout = QVBoxLayout()
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send_chat_message)
        send_btn_layout.addWidget(self.send_btn)
        send_btn_layout.addStretch()
        input_layout.addLayout(send_btn_layout)

        ai_layout.addLayout(input_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximum(0)
        ai_layout.addWidget(self.progress_bar)

        self.tab_widget.addTab(ai_tab, "AI Assistant")

        layout.addWidget(self.tab_widget)

        # Consistency check section at bottom
        check_frame = QFrame()
        check_frame.setStyleSheet("background-color: #fff3cd; border-radius: 4px; padding: 4px;")
        check_layout = QHBoxLayout(check_frame)
        check_layout.setContentsMargins(8, 4, 8, 4)

        self.check_plan_btn = QPushButton("Check Plan vs Chapter")
        self.check_plan_btn.setToolTip("Verify if your chapter content follows the plan")
        self.check_plan_btn.clicked.connect(self._check_plan_consistency)
        self.check_plan_btn.setStyleSheet("background-color: #ffc107; color: black;")
        check_layout.addWidget(self.check_plan_btn)

        check_layout.addStretch()
        layout.addWidget(check_frame)

    def _on_plan_changed(self):
        """Handle any planning content change."""
        self._update_arc_widget()
        self.plan_changed.emit()

    def _update_arc_widget(self):
        """Update the arc visualization with current events."""
        events = [widget.get_data() for widget in self._event_widgets]
        self.arc_widget.set_events(events)

    def _add_event_item(self, text: str = "", completed: bool = False,
                       stage: str = "rising", arc_position: int = -1,
                       event_id: str = None, order: int = -1):
        """Add a new story event."""
        if event_id is None:
            event_id = str(uuid.uuid4())

        if order < 0:
            order = len(self._event_widgets)

        if arc_position < 0:
            # Auto-calculate based on order and total events
            total = len(self._event_widgets) + 1
            arc_position = int((order + 0.5) / total * 100)

        item = StoryEventWidget(event_id, text, completed, stage, arc_position, order)
        item.changed.connect(self._on_plan_changed)
        item.delete_requested.connect(self._remove_event_item)
        item.arc_position_changed.connect(self._on_event_arc_changed)

        self._event_widgets.append(item)
        self.events_list_layout.addWidget(item)
        self._renumber_events()
        self._on_plan_changed()

    def _remove_event_item(self, event_id: str):
        """Remove a story event."""
        for item in self._event_widgets:
            if item.event_id == event_id:
                self._event_widgets.remove(item)
                item.deleteLater()
                self._renumber_events()
                self._on_plan_changed()
                break

    def _renumber_events(self):
        """Update order numbers for all events."""
        for i, widget in enumerate(self._event_widgets):
            widget.set_order(i)

    def _on_event_arc_changed(self, event_id: str, position: int):
        """Handle arc position change for an event."""
        self._update_arc_widget()

    def _on_arc_event_clicked(self, event_id: str):
        """Handle click on event in arc widget."""
        # Focus the corresponding event widget
        for widget in self._event_widgets:
            if widget.event_id == event_id:
                widget.text_edit.setFocus()
                break

    def _reorder_events_by_arc(self):
        """Reorder events by their arc position."""
        # Get current data sorted by arc position
        events_data = sorted(
            [w.get_data() for w in self._event_widgets],
            key=lambda e: e.get('arc_position', 50)
        )

        # Clear and rebuild
        for widget in self._event_widgets[:]:
            widget.deleteLater()
        self._event_widgets.clear()

        for i, event in enumerate(events_data):
            self._add_event_item(
                text=event.get('text', ''),
                completed=event.get('completed', False),
                stage=event.get('stage', 'rising'),
                arc_position=event.get('arc_position', 50),
                event_id=event.get('id'),
                order=i
            )

    def _add_todo_item(self, text: str = "", completed: bool = False, priority: str = "normal", item_id: str = None):
        """Add a new todo item."""
        if item_id is None:
            item_id = str(uuid.uuid4())

        item = TodoItemWidget(item_id, text, completed, priority)
        item.changed.connect(self._on_plan_changed)
        item.delete_requested.connect(self._remove_todo_item)

        self._todo_widgets.append(item)
        self.todo_list_layout.addWidget(item)
        self._on_plan_changed()

    def _remove_todo_item(self, item_id: str):
        """Remove a todo item."""
        for item in self._todo_widgets:
            if item.item_id == item_id:
                self._todo_widgets.remove(item)
                item.deleteLater()
                self._on_plan_changed()
                break

    def set_planning_data(self, planning_data: dict):
        """Set all planning data from a dictionary."""
        # Events (new format) - check for 'events' key or fall back to parsing outline
        events = planning_data.get('events', [])

        # Clear existing events
        for widget in self._event_widgets[:]:
            widget.deleteLater()
        self._event_widgets.clear()

        if events:
            for i, event in enumerate(events):
                self._add_event_item(
                    text=event.get('text', ''),
                    completed=event.get('completed', False),
                    stage=event.get('stage', 'rising'),
                    arc_position=event.get('arc_position', -1),
                    event_id=event.get('id'),
                    order=i
                )
        else:
            # Try to parse legacy outline format
            outline = planning_data.get('outline', '')
            if outline:
                self._parse_outline_to_events(outline)

        # Description
        self.description_editor.setPlainText(planning_data.get('description', ''))
        self.pov_edit.setText(planning_data.get('pov_character', ''))
        self.timeline_edit.setText(planning_data.get('timeline_position', ''))

        # Characters and locations
        chars = planning_data.get('characters_featured', [])
        self.characters_edit.setText(', '.join(chars) if chars else '')

        locs = planning_data.get('locations', [])
        self.locations_edit.setText(', '.join(locs) if locs else '')

        # Notes
        self.notes_editor.setPlainText(planning_data.get('notes', ''))

        # Todos - clear existing and add new
        for widget in self._todo_widgets[:]:
            widget.deleteLater()
        self._todo_widgets.clear()

        for todo in planning_data.get('todos', []):
            self._add_todo_item(
                text=todo.get('text', ''),
                completed=todo.get('completed', False),
                priority=todo.get('priority', 'normal'),
                item_id=todo.get('id')
            )

        self._update_arc_widget()

    def _parse_outline_to_events(self, outline: str):
        """Parse a legacy text outline into events."""
        lines = outline.strip().split('\n')
        event_lines = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Skip headers and section labels
            if line.startswith('#') or line.endswith(':'):
                continue
            # Check for list items
            if line.startswith(('-', '*', '•')) or (len(line) > 2 and line[0].isdigit() and line[1] in '.):'):
                # Remove bullet/number
                text = line.lstrip('-*•0123456789.): ').strip()
                if text:
                    event_lines.append(text)
            elif len(line) > 10:  # Substantial text line
                event_lines.append(line)

        # Create events from parsed lines
        total = len(event_lines)
        for i, text in enumerate(event_lines):
            # Determine stage based on position
            pos = i / max(total - 1, 1) if total > 1 else 0.5
            if pos < 0.15:
                stage = "exposition"
            elif pos < 0.45:
                stage = "rising"
            elif pos < 0.55:
                stage = "climax"
            elif pos < 0.85:
                stage = "falling"
            else:
                stage = "resolution"

            arc_position = int(pos * 100)
            self._add_event_item(
                text=text,
                stage=stage,
                arc_position=arc_position,
                order=i
            )

    def get_planning_data(self) -> dict:
        """Get all planning data as a dictionary."""
        # Parse comma-separated lists
        chars_text = self.characters_edit.text().strip()
        chars = [c.strip() for c in chars_text.split(',') if c.strip()] if chars_text else []

        locs_text = self.locations_edit.text().strip()
        locs = [l.strip() for l in locs_text.split(',') if l.strip()] if locs_text else []

        # Get events
        events = [widget.get_data() for widget in self._event_widgets]

        # Get todos
        todos = [widget.get_data() for widget in self._todo_widgets]

        # Generate outline text from events for backward compatibility
        outline = self._events_to_outline_text(events)

        return {
            'outline': outline,
            'events': events,
            'description': self.description_editor.toPlainText(),
            'todos': todos,
            'notes': self.notes_editor.toPlainText(),
            'characters_featured': chars,
            'locations': locs,
            'pov_character': self.pov_edit.text(),
            'timeline_position': self.timeline_edit.text(),
            'scene_list': [],  # Could be expanded later
            'themes': []  # Could be expanded later
        }

    def _events_to_outline_text(self, events: list) -> str:
        """Convert events list to outline text for backward compatibility."""
        if not events:
            return ""

        lines = ["# Chapter Outline\n"]
        current_stage = None

        for event in sorted(events, key=lambda e: e.get('arc_position', 50)):
            stage = event.get('stage', 'rising')
            text = event.get('text', '')
            completed = event.get('completed', False)

            if stage != current_stage:
                current_stage = stage
                stage_name = StoryEventWidget.STAGE_NAMES.get(stage, stage.title())
                lines.append(f"\n## {stage_name}\n")

            check = "✓" if completed else "-"
            lines.append(f"{check} {text}")

        return '\n'.join(lines)

    # Legacy methods for backward compatibility
    def set_plan(self, plan: str):
        """Set just the outline (legacy method)."""
        self._parse_outline_to_events(plan)

    def get_plan(self) -> str:
        """Get just the outline (legacy method)."""
        events = [widget.get_data() for widget in self._event_widgets]
        return self._events_to_outline_text(events)

    def set_ai_handler(self, handler: Callable):
        """Set the AI handler function."""
        self._ai_handler = handler

    def set_context_provider(self, provider: Callable):
        """Set function that provides plot/worldbuilding context."""
        self._context_provider = provider

    def set_chapter_content_provider(self, provider: Callable):
        """Set function that provides current chapter content."""
        self._chapter_content_provider = provider

    def _get_context(self) -> dict:
        """Get the current context for AI requests."""
        if self._context_provider:
            return self._context_provider()
        return {}

    def _get_chapter_content(self) -> str:
        """Get the current chapter content."""
        if self._chapter_content_provider:
            return self._chapter_content_provider()
        return ""

    def _append_to_chat(self, role: str, message: str):
        """Append a message to the chat history."""
        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        if role == "user":
            cursor.insertHtml(f'<p style="color: #0066cc;"><b>You:</b> {message}</p>')
        elif role == "assistant":
            cursor.insertHtml(f'<p style="color: #006600;"><b>AI:</b> {message}</p>')
        elif role == "system":
            cursor.insertHtml(f'<p style="color: #666666;"><i>{message}</i></p>')
        elif role == "error":
            cursor.insertHtml(f'<p style="color: #cc0000;"><b>Error:</b> {message}</p>')

        cursor.insertHtml("<br>")
        self.chat_history.setTextCursor(cursor)
        self.chat_history.ensureCursorVisible()

    def _set_processing(self, is_processing: bool):
        """Set processing state."""
        self._is_processing = is_processing
        self.progress_bar.setVisible(is_processing)
        self.send_btn.setEnabled(not is_processing)
        self.generate_events_btn.setEnabled(not is_processing)
        self.check_plan_btn.setEnabled(not is_processing)

    def _generate_events(self):
        """Generate story events using AI."""
        if not self._ai_handler:
            QMessageBox.warning(self, "AI Not Available", "AI handler not configured.")
            return

        context = self._get_context()
        chapter_title = context.get('chapter_title', 'this chapter')

        prompt = f"""Generate a list of 5-8 story events for "{chapter_title}".

Based on the plot outline, worldbuilding, and characters provided, create specific story beats.

For each event, specify:
1. A brief description (1-2 sentences)
2. Which part of the chapter arc it belongs to (exposition, rising action, climax, falling action, or resolution)

Format your response as a numbered list with the arc stage in brackets:
1. [exposition] Description of the first event...
2. [rising] Description of the next event...
3. [climax] The major turning point...
etc.

Make the events specific, actionable, and engaging."""

        self._append_to_chat("system", f"Generating events for {chapter_title}...")
        self._set_processing(True)

        def on_response(response: str):
            self._set_processing(False)
            if response:
                self._parse_ai_events_response(response)
                self._append_to_chat("assistant", "Events generated! Review and adjust as needed.")
            else:
                self._append_to_chat("error", "Failed to generate events.")

        self._run_ai_request(prompt, context, on_response)

    def _parse_ai_events_response(self, response: str):
        """Parse AI response into events."""
        lines = response.strip().split('\n')

        # Clear existing events
        for widget in self._event_widgets[:]:
            widget.deleteLater()
        self._event_widgets.clear()

        stage_map = {
            'exposition': 'exposition',
            'rising': 'rising',
            'rising action': 'rising',
            'climax': 'climax',
            'falling': 'falling',
            'falling action': 'falling',
            'resolution': 'resolution',
            'denouement': 'resolution'
        }

        event_order = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Try to extract stage from brackets
            stage = 'rising'  # default
            text = line

            # Check for [stage] format
            import re
            bracket_match = re.search(r'\[([^\]]+)\]', line)
            if bracket_match:
                stage_text = bracket_match.group(1).lower().strip()
                stage = stage_map.get(stage_text, 'rising')
                text = re.sub(r'\[[^\]]+\]', '', line).strip()

            # Remove leading numbers
            text = re.sub(r'^[\d]+[\.\)\:]?\s*', '', text).strip()

            if text and len(text) > 5:
                # Calculate arc position based on stage
                stage_positions = {
                    'exposition': 10 + event_order * 3,
                    'rising': 25 + event_order * 5,
                    'climax': 50,
                    'falling': 65 + event_order * 3,
                    'resolution': 85 + event_order * 3
                }
                arc_pos = min(stage_positions.get(stage, 50), 95)

                self._add_event_item(
                    text=text,
                    stage=stage,
                    arc_position=arc_pos,
                    order=event_order
                )
                event_order += 1

    def _send_chat_message(self):
        """Send a chat message to the AI."""
        if not self._ai_handler:
            QMessageBox.warning(self, "AI Not Available", "AI handler not configured.")
            return

        message = self.chat_input.toPlainText().strip()
        if not message:
            return

        self.chat_input.clear()
        self._append_to_chat("user", message)

        context = self._get_context()
        context['current_plan'] = self.get_plan()
        context['chapter_content'] = self._get_chapter_content()

        prompt = f"""The user is planning a chapter and asks:

{message}

Help them with their chapter planning. Current events in their outline:
{self.get_plan()}"""

        self._set_processing(True)

        def on_response(response: str):
            self._set_processing(False)
            if response:
                self._append_to_chat("assistant", response)
            else:
                self._append_to_chat("error", "Failed to get response.")

        self._run_ai_request(prompt, context, on_response)

    def _check_plan_consistency(self):
        """Check if the chapter content follows the plan."""
        if not self._ai_handler:
            QMessageBox.warning(self, "AI Not Available", "AI handler not configured.")
            return

        plan = self.get_plan()
        if not plan.strip():
            QMessageBox.warning(self, "No Events", "Please add story events first.")
            return

        chapter_content = self._get_chapter_content()
        if not chapter_content.strip():
            QMessageBox.warning(self, "No Content", "The chapter has no content to check.")
            return

        context = self._get_context()

        prompt = f"""Analyze how well the chapter content follows the planned events.

PLANNED EVENTS:
{plan}

CHAPTER CONTENT:
{chapter_content[:8000]}

Provide:
1. **Events Covered**: Which planned events have been written?
2. **Events Missing**: Which planned events haven't been addressed?
3. **Suggestions**: How to better align the chapter with the plan"""

        self._append_to_chat("system", "Checking plan consistency...")
        self._set_processing(True)
        self.tab_widget.setCurrentIndex(4)  # Switch to AI tab

        def on_response(response: str):
            self._set_processing(False)
            if response:
                self._append_to_chat("assistant", response)
                self.check_requested.emit(plan, chapter_content)
            else:
                self._append_to_chat("error", "Failed to check consistency.")

        self._run_ai_request(prompt, context, on_response)

    def _run_ai_request(self, prompt: str, context: dict, callback: Callable):
        """Run an AI request in a background thread."""
        def run():
            try:
                context_parts = []
                if context.get('plot'):
                    context_parts.append(f"PLOT:\n{context['plot']}")
                if context.get('worldbuilding'):
                    context_parts.append(f"WORLDBUILDING:\n{context['worldbuilding']}")
                if context.get('characters'):
                    context_parts.append(f"CHARACTERS:\n{context['characters']}")
                if context.get('current_plan'):
                    context_parts.append(f"CURRENT OUTLINE:\n{context['current_plan']}")

                full_context = "\n\n".join(context_parts)
                full_prompt = f"{full_context}\n\n---\n\n{prompt}" if full_context else prompt

                result = self._ai_handler(full_prompt, self.model_combo.currentText())

                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, lambda: callback(result))

            except Exception as e:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, lambda: callback(None))
                print(f"AI request error: {e}")

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def clear_chat(self):
        """Clear the chat history."""
        self.chat_history.clear()
