"""Chapter Planner Widget - Plan chapters with AI assistance."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QGroupBox, QComboBox, QMessageBox, QProgressBar,
    QScrollArea, QFrame, QTabWidget, QLineEdit, QCheckBox,
    QSlider, QSizePolicy
)
from PyQt6.QtCore import pyqtSignal, Qt, QPointF, QMimeData, QTimer
from PyQt6.QtGui import QFont, QTextCursor, QPainter, QPen, QBrush, QColor, QPainterPath, QDrag, QPixmap
from typing import Optional, Callable, List
import threading
import uuid

from src.ui.styles import SYSTEM_FONT


# Tags the chapter-planner AI emits when it wants to propose a new
# StoryEvent (chapter beat) for the user to review. Cards render
# with Add / Skip in the AI panel; clicking Add calls
# ``_add_event_item`` so the beat lands on the chapter arc with the
# AI's chosen stage + arc_position.
_VALID_EVENT_STAGES = (
    'exposition', 'rising', 'climax', 'falling', 'resolution')


def _extract_event_suggestions(reply: str):
    """Pull <suggest_event> blocks out of a model reply.

    Returns ``(cleaned_text, [suggestions])`` where ``cleaned_text``
    has the tags stripped (so we render it as normal prose) and
    ``suggestions`` is a list of dicts:
        {"data": <parsed JSON dict>, "raw": <original block text>}
    Bad JSON is captured with ``data=None`` so the user at least sees
    the raw block in the failure card. Multiple blocks are extracted
    in order.
    """
    import re
    import json
    cleaned = reply
    suggestions = []
    pattern = re.compile(
        r"<suggest_event>\s*(.*?)\s*</suggest_event>",
        re.DOTALL | re.IGNORECASE)
    for m in pattern.finditer(reply):
        raw = m.group(1).strip()
        data = None
        try:
            normalized = re.sub(r",\s*}", "}", raw)
            normalized = re.sub(r",\s*]", "]", normalized)
            data = json.loads(normalized)
        except Exception:
            data = None
        suggestions.append({"data": data, "raw": raw})
    cleaned = pattern.sub("", cleaned)
    # Drop any orphan unclosed ``<suggest_event>`` from the cleaned
    # text — those are truncation artifacts and shouldn't show up in
    # the user-visible chat. The continuation loop in
    # ``_send_chat_message`` will re-prompt the model and re-parse
    # against the appended response.
    orphan_open = re.compile(
        r"<suggest_event>(?:(?!</suggest_event>).)*$",
        re.DOTALL | re.IGNORECASE)
    cleaned = orphan_open.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, suggestions


def _response_has_unclosed_suggest_event(text: str) -> bool:
    """True when the response has more open <suggest_event> tags
    than closing tags — i.e. the model got cut off mid-block.

    The chapter-planner uses this to decide whether to loop a
    continuation request before parsing the final reply.
    """
    if not text:
        return False
    import re
    opens = len(re.findall(
        r"<suggest_event>", text, re.IGNORECASE))
    closes = len(re.findall(
        r"</suggest_event>", text, re.IGNORECASE))
    return opens > closes


def _extract_theme_suggestions(reply: str):
    """Pull <suggest_theme> blocks out of a model reply.

    Mirrors ``_extract_event_suggestions``. Each block is a JSON dict
    with ``title`` (required) + optional ``description``, ``statement``,
    ``motifs`` (list). Returns ``(cleaned_text, [suggestions])``.
    """
    import re
    import json
    cleaned = reply
    suggestions = []
    pattern = re.compile(
        r"<suggest_theme>\s*(.*?)\s*</suggest_theme>",
        re.DOTALL | re.IGNORECASE)
    for m in pattern.finditer(reply):
        raw = m.group(1).strip()
        data = None
        try:
            normalized = re.sub(r",\s*}", "}", raw)
            normalized = re.sub(r",\s*]", "]", normalized)
            data = json.loads(normalized)
        except Exception:
            data = None
        suggestions.append({"data": data, "raw": raw})
    cleaned = pattern.sub("", cleaned)
    # Strip orphan unclosed <suggest_theme> from cleaned text — same
    # truncation-tolerance logic as event suggestions.
    orphan_open = re.compile(
        r"<suggest_theme>(?:(?!</suggest_theme>).)*$",
        re.DOTALL | re.IGNORECASE)
    cleaned = orphan_open.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, suggestions


def _response_has_unclosed_suggest_theme(text: str) -> bool:
    """True when <suggest_theme> tags outnumber </suggest_theme>."""
    if not text:
        return False
    import re
    opens = len(re.findall(
        r"<suggest_theme>", text, re.IGNORECASE))
    closes = len(re.findall(
        r"</suggest_theme>", text, re.IGNORECASE))
    return opens > closes


def _truncation_continuation_prompt(partial: str) -> str:
    """Build a continuation prompt for the planner AI.

    Tells the model the previous response was cut off and gives it
    a tail snippet so it knows exactly where to resume — without
    repeating itself. The continuation will be appended to the
    partial verbatim, so the model must NOT echo the snippet.
    """
    tail = (partial or "")[-300:]
    return (
        "Your previous response was cut off mid-stream. Continue "
        "from EXACTLY where you stopped — do not restate, recap, "
        "or repeat anything from before. Resume the partial text "
        "below seamlessly, then close any open <suggest_event> "
        "block and finish the reply naturally.\n\n"
        "PARTIAL RESPONSE (your last ~300 chars; do NOT repeat any "
        "of this — your continuation gets appended directly):\n"
        "---\n"
        f"{tail}\n"
        "---\n\n"
        "CONTINUATION (start writing from immediately after the "
        "last character above):"
    )


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

        # Checkbox with visible styling
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(completed)
        self.checkbox.setStyleSheet("""
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:unchecked {
                border: 2px solid #9ca3af;
                border-radius: 3px;
                background-color: white;
            }
            QCheckBox::indicator:checked {
                border: 2px solid #22c55e;
                border-radius: 3px;
                background-color: #22c55e;
            }
        """)
        self.checkbox.stateChanged.connect(self._on_changed)
        layout.addWidget(self.checkbox)

        # Priority indicator with compact styling
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["low", "normal", "high"])
        self.priority_combo.setCurrentText(priority)
        self.priority_combo.setMaximumWidth(65)
        self.priority_combo.setStyleSheet("font-size: 10px;")
        self.priority_combo.currentTextChanged.connect(self._on_changed)
        layout.addWidget(self.priority_combo)

        # Text
        self.text_edit = QLineEdit(text)
        self.text_edit.setPlaceholderText("Enter task...")
        self.text_edit.setStyleSheet("font-size: 11px;")
        self.text_edit.textChanged.connect(self._on_changed)
        layout.addWidget(self.text_edit)

        # Delete button with visible icon
        delete_btn = QPushButton("🗑")
        delete_btn.setMinimumWidth(24)
        delete_btn.setMaximumWidth(28)
        delete_btn.setToolTip("Delete task")
        delete_btn.setStyleSheet("""
            QPushButton {
                font-size: 12px;
                padding: 2px;
                border: none;
                background: transparent;
            }
            QPushButton:hover {
                background-color: #fee2e2;
                border-radius: 3px;
            }
        """)
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.item_id))
        layout.addWidget(delete_btn)

        self._update_style()

    def _on_changed(self):
        self._update_style()
        self.changed.emit()

    def _update_style(self):
        base_style = "font-size: 11px; "
        if self.checkbox.isChecked():
            self.text_edit.setStyleSheet(base_style + "text-decoration: line-through; color: gray;")
        else:
            priority = self.priority_combo.currentText()
            if priority == "high":
                self.text_edit.setStyleSheet(base_style + "color: #dc2626; font-weight: bold;")
            elif priority == "low":
                self.text_edit.setStyleSheet(base_style + "color: #6b7280;")
            else:
                self.text_edit.setStyleSheet(base_style)

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
    ai_help_requested = pyqtSignal(str)  # event_id - per-beat AI help
    arc_position_changed = pyqtSignal(str, int)  # event_id, position
    drag_started = pyqtSignal(str)  # event_id - for drag and drop reordering

    # Arc stage constants
    STAGES = ["exposition", "rising", "climax", "falling", "resolution"]
    STAGE_NAMES = {
        "exposition": "Exposition",
        "rising": "Rising Action",
        "climax": "Climax",
        "falling": "Falling Action",
        "resolution": "Resolution"
    }

    def __init__(self, event_id: str, text: str = "", description: str = "",
                 completed: bool = False, stage: str = "rising", arc_position: int = 50, order: int = 0):
        super().__init__()
        self.event_id = event_id
        self.order = order
        self._description_visible = False
        self._drag_start_pos = None
        self._init_ui(text, description, completed, stage, arc_position)
        self.setAcceptDrops(True)

    def _init_ui(self, text: str, description: str, completed: bool, stage: str, arc_position: int):
        # Main vertical layout - tight spacing
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 2, 4, 2)
        main_layout.setSpacing(0)

        # Top row with event controls - compact for small screens
        top_row = QWidget()
        layout = QHBoxLayout(top_row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)  # Tighter spacing for small screens

        # Drag handle
        self.drag_handle = QLabel("⋮")
        self.drag_handle.setStyleSheet("color: #9ca3af; font-size: 11px;")
        self.drag_handle.setToolTip("Drag to reorder")
        self.drag_handle.setFixedWidth(12)
        self.drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        layout.addWidget(self.drag_handle)

        # Order/number label
        self.order_label = QLabel(f"{self.order + 1}.")
        self.order_label.setFixedWidth(18)
        self.order_label.setStyleSheet("font-weight: bold; color: #6366f1; font-size: 11px;")
        layout.addWidget(self.order_label)

        # Checkbox for completion
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(completed)
        self.checkbox.setToolTip("Mark event as written")
        self.checkbox.stateChanged.connect(self._on_changed)
        layout.addWidget(self.checkbox)

        # Expand/collapse indicator (combined with text field styling)
        self.expand_indicator = QLabel("▶")
        self.expand_indicator.setStyleSheet("color: #9ca3af; font-size: 8px;")
        self.expand_indicator.setFixedWidth(10)
        layout.addWidget(self.expand_indicator)

        # Event text (clickable to expand description)
        self.text_edit = QLineEdit(text)
        self.text_edit.setPlaceholderText("Event name...")
        self.text_edit.textChanged.connect(self._on_changed)
        self.text_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #e5e7eb;
                border-radius: 3px;
                padding: 2px 4px;
                font-size: 11px;
            }
            QLineEdit:hover {
                border-color: #6366f1;
            }
            QLineEdit:focus {
                border-color: #6366f1;
            }
        """)
        self.text_edit.setMinimumWidth(80)
        layout.addWidget(self.text_edit, 1)

        # Stage selector - abbreviated for small screens
        self.stage_combo = QComboBox()
        stage_abbrev = {
            "exposition": "Expo",
            "rising": "Rise",
            "climax": "Climax",
            "falling": "Fall",
            "resolution": "Resol"
        }
        for s in self.STAGES:
            self.stage_combo.addItem(stage_abbrev[s], s)
        idx = self.STAGES.index(stage) if stage in self.STAGES else 1
        self.stage_combo.setCurrentIndex(idx)
        self.stage_combo.setMaximumWidth(70)
        self.stage_combo.setToolTip("Arc stage")
        self.stage_combo.setStyleSheet("font-size: 10px;")
        self.stage_combo.currentIndexChanged.connect(self._on_stage_changed)
        layout.addWidget(self.stage_combo)

        # Arc position slider (0-100, where 50 is the climax peak)
        self.arc_slider = QSlider(Qt.Orientation.Horizontal)
        self.arc_slider.setRange(0, 100)
        self.arc_slider.setValue(arc_position)
        self.arc_slider.setFixedWidth(50)
        self.arc_slider.setToolTip("Position on arc")
        self.arc_slider.valueChanged.connect(self._on_arc_changed)
        layout.addWidget(self.arc_slider)

        # AI-help button — sends THIS beat to the AI Assistant
        # (outline mode) for clarification questions / refinement.
        # Lives next to the delete button so the per-beat actions
        # cluster on the right edge.
        ai_btn = QPushButton("✨")
        ai_btn.setMinimumWidth(24)
        ai_btn.setMaximumWidth(28)
        ai_btn.setToolTip(
            "Ask the AI Assistant to help with this beat "
            "(opens outline mode focused on this beat).")
        ai_btn.setStyleSheet("""
            QPushButton {
                font-size: 12px;
                padding: 2px;
                border: none;
                background: transparent;
            }
            QPushButton:hover {
                background-color: #ede9fe;
                border-radius: 3px;
            }
        """)
        ai_btn.clicked.connect(
            lambda: self.ai_help_requested.emit(self.event_id))
        layout.addWidget(ai_btn)

        # Delete button with visible icon
        delete_btn = QPushButton("🗑")
        delete_btn.setMinimumWidth(24)
        delete_btn.setMaximumWidth(28)
        delete_btn.setToolTip("Delete event")
        delete_btn.setStyleSheet("""
            QPushButton {
                font-size: 12px;
                padding: 2px;
                border: none;
                background: transparent;
            }
            QPushButton:hover {
                background-color: #fee2e2;
                border-radius: 3px;
            }
        """)
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.event_id))
        layout.addWidget(delete_btn)

        main_layout.addWidget(top_row)

        # Description area (hidden by default) - inline compact design
        self.description_container = QWidget()
        desc_layout = QHBoxLayout(self.description_container)
        desc_layout.setContentsMargins(45, 0, 25, 0)  # Align with text field (compact layout)
        desc_layout.setSpacing(0)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Event details...")
        self.description_edit.setPlainText(description)
        self.description_edit.setFixedHeight(45)
        self.description_edit.setStyleSheet("""
            QTextEdit {
                border: 1px solid #d1d5db;
                border-top: none;
                border-radius: 0 0 3px 3px;
                padding: 2px 6px;
                background-color: #f9fafb;
                font-size: 11px;
            }
            QTextEdit:focus {
                border-color: #6366f1;
                background-color: white;
            }
        """)
        self.description_edit.textChanged.connect(self._on_changed)
        desc_layout.addWidget(self.description_edit)

        self.description_container.setVisible(False)
        main_layout.addWidget(self.description_container)

        # Connect click on text to toggle description
        self.text_edit.mousePressEvent = self._on_text_clicked

        self._update_style()

    def _on_text_clicked(self, event):
        """Handle click on event name to toggle description."""
        # Call original behavior first (focus, selection, etc.)
        QLineEdit.mousePressEvent(self.text_edit, event)
        # Toggle description visibility
        self._toggle_description()

    def _toggle_description(self):
        """Toggle the description area visibility."""
        self._description_visible = not self._description_visible
        self.description_container.setVisible(self._description_visible)
        self.expand_indicator.setText("▼" if self._description_visible else "▶")
        if self._description_visible:
            self.description_edit.setFocus()

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
        base_style = """
            QLineEdit {
                border: 1px solid #e5e7eb;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QLineEdit:hover {
                border-color: #6366f1;
            }
            QLineEdit:focus {
                border-color: #6366f1;
            }
        """
        if self.checkbox.isChecked():
            self.text_edit.setStyleSheet(base_style + "QLineEdit { text-decoration: line-through; color: #9ca3af; }")
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
            self.text_edit.setStyleSheet(base_style)
            self.order_label.setStyleSheet(f"font-weight: bold; color: {color};")

    def set_order(self, order: int):
        """Update the order number."""
        self.order = order
        self.order_label.setText(f"{order + 1}.")

    def get_data(self) -> dict:
        return {
            'id': self.event_id,
            'text': self.text_edit.text(),
            'description': self.description_edit.toPlainText(),
            'completed': self.checkbox.isChecked(),
            'stage': self.stage_combo.currentData(),
            'arc_position': self.arc_slider.value(),
            'order': self.order
        }

    def mousePressEvent(self, event):
        """Start drag operation if on drag handle."""
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if click is on the drag handle area
            handle_rect = self.drag_handle.geometry()
            if handle_rect.contains(event.pos()):
                self._drag_start_pos = event.pos()
                self.drag_handle.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle drag movement."""
        if self._drag_start_pos is not None:
            # Check if we've moved enough to start a drag
            if (event.pos() - self._drag_start_pos).manhattanLength() > 10:
                self._start_drag()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """End potential drag."""
        self._drag_start_pos = None
        self.drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def _start_drag(self):
        """Initiate the drag operation."""
        self._drag_start_pos = None
        self.drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)

        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(self.event_id)
        drag.setMimeData(mime_data)

        # Create a visual representation
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        self.render(pixmap)
        drag.setPixmap(pixmap.scaled(self.width(), 40, Qt.AspectRatioMode.KeepAspectRatio))
        drag.setHotSpot(self.rect().center())

        self.drag_started.emit(self.event_id)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        """Accept drag if it's from another event widget."""
        if event.mimeData().hasText():
            source_id = event.mimeData().text()
            if source_id != self.event_id:  # Don't accept drops on self
                event.acceptProposedAction()
                self.setStyleSheet("background-color: #e0e7ff; border-radius: 4px;")

    def dragLeaveEvent(self, event):
        """Reset styling when drag leaves."""
        self.setStyleSheet("")

    def dropEvent(self, event):
        """Handle drop - emit signal to reorder events."""
        self.setStyleSheet("")
        if event.mimeData().hasText():
            source_id = event.mimeData().text()
            if source_id != self.event_id:
                event.acceptProposedAction()
                # The parent widget will handle the actual reordering
                # We emit our event_id as the drop target
                self.drag_started.emit(f"drop:{source_id}:{self.event_id}")


class ChapterArcWidget(QWidget):
    """Visual representation of the chapter's narrative arc with event markers."""

    event_clicked = pyqtSignal(str)  # event_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.events = []  # List of event dicts with arc_position
        self.setMinimumHeight(90)  # Compact for small screens
        self.setMaximumHeight(130)
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
        padding = 15  # Reduced padding for small screens
        arc_height = height - 40

        # Draw background
        painter.fillRect(self.rect(), QColor("#fafafa"))

        # Draw arc path (Freytag's pyramid style)
        path = QPainterPath()
        start_x = padding
        end_x = width - padding
        arc_width = end_x - start_x

        # Define the arc shape (rises to climax at center, then falls)
        base_y = height - 20  # Reduced bottom margin
        peak_y = 20  # Reduced top margin

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

        # Draw stage labels - abbreviated for compact display
        painter.setPen(QPen(QColor("#9ca3af")))
        font = painter.font()
        font.setPointSize(7)  # Smaller font for small screens
        painter.setFont(font)

        labels = [
            ("Expo", 0.08),
            ("Rise", 0.30),
            ("Climax", 0.50),
            ("Fall", 0.70),
            ("End", 0.92)
        ]

        for label, pos in labels:
            x = start_x + arc_width * pos
            painter.drawText(int(x - 25), height - 3, 50, 12,
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

            # Calculate y position on the arc by evaluating the actual Bezier curves
            if pos <= 0.5:
                # Rising portion: quadratic Bezier from (start_x, base_y)
                # control (start_x + arc_width*0.25, base_y - (base_y-peak_y)*0.3)
                # to (climax_x, peak_y)
                t = pos / 0.5
                p0y = base_y
                p1y = base_y - (base_y - peak_y) * 0.3
                p2y = peak_y
                y = (1 - t) * (1 - t) * p0y + 2 * (1 - t) * t * p1y + t * t * p2y
            else:
                # Falling portion: quadratic Bezier from (climax_x, peak_y)
                # control (start_x + arc_width*0.75, base_y - (base_y-peak_y)*0.3)
                # to (end_x, base_y)
                t = (pos - 0.5) / 0.5
                p0y = peak_y
                p1y = base_y - (base_y - peak_y) * 0.3
                p2y = base_y
                y = (1 - t) * (1 - t) * p0y + 2 * (1 - t) * t * p1y + t * t * p2y

            # Draw marker
            color = stage_colors.get(stage, QColor("#6366f1"))
            if completed:
                color = QColor("#9ca3af")

            painter.setPen(QPen(color.darker(120), 2))
            painter.setBrush(QBrush(color if not completed else QColor("#d1d5db")))

            radius = 7 if not completed else 5  # Slightly smaller for compact arc
            painter.drawEllipse(QPointF(x, y), radius, radius)

            # Draw event number
            order = event.get('order', 0)
            painter.setPen(QPen(QColor("white" if not completed else "#666")))
            font.setPointSize(6)  # Smaller font for compact markers
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(int(x - 8), int(y - 8), 16, 16,
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
    # User clicked the per-beat ✨ AI-help button on a StoryEventWidget.
    # Carries (event_id, event_text, event_description, event_stage)
    # so the receiver can route to outline-mode chat with focused
    # beat context.
    beat_ai_help_requested = pyqtSignal(str, str, str, str)
    # Emitted when the user clicks "Clear Plot Arc" and confirms.
    # The receiver (MainWindow) is responsible for wiping the
    # current chapter's planning.events + planning.outline AND
    # blanking the AI-Assistant outline panel — the planner widget
    # only owns its own UI state.
    events_cleared = pyqtSignal()
    _ai_response_ready = pyqtSignal(object)  # Internal signal for thread-safe callback delivery

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ai_handler: Optional[Callable] = None
        self._context_provider: Optional[Callable] = None
        self._chapter_content_provider: Optional[Callable] = None
        self._is_processing = False
        self._current_callback: Optional[Callable] = None
        self._todo_widgets: List[TodoItemWidget] = []
        self._event_widgets: List[StoryEventWidget] = []
        # AI conversation state — kept separate from the visible
        # chat_history widget so we can compact older turns into a
        # summary without disturbing what the user can scroll back
        # to read.
        self._ai_history: List[dict] = []  # [{role, content}]
        self._ai_history_summary: str = ""
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # === Upper portion: scrollable planning content ===
        upper_widget = QWidget()
        upper_layout = QVBoxLayout(upper_widget)
        upper_layout.setContentsMargins(0, 0, 0, 0)
        upper_layout.setSpacing(4)

        # Header
        header = QLabel("Chapter Planning")
        header.setStyleSheet("font-size: 14px; font-weight: 600; color: #1a1a1a; padding: 4px;")
        upper_layout.addWidget(header)

        # Info label
        info_label = QLabel("Plan your chapter here. Planning data is NOT exported with your manuscript.")
        info_label.setStyleSheet("color: #666; font-size: 11px; font-style: italic; padding: 2px;")
        info_label.setWordWrap(True)
        upper_layout.addWidget(info_label)

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

        # Events header with add button - compact for small screens
        events_header = QHBoxLayout()
        events_header.setSpacing(4)
        events_label = QLabel("Chapter events:")
        events_label.setStyleSheet("font-size: 11px; color: #666;")
        events_header.addWidget(events_label)
        events_header.addStretch()

        add_event_btn = QPushButton("+ Add")
        add_event_btn.setStyleSheet("font-size: 11px; padding: 2px 6px;")
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

        # Quick actions for events - compact buttons for small screens
        events_actions = QHBoxLayout()
        events_actions.setSpacing(4)

        self.generate_events_btn = QPushButton("AI Generate")
        self.generate_events_btn.setToolTip("Generate story events with AI")
        self.generate_events_btn.setStyleSheet("font-size: 11px; padding: 3px 6px;")
        self.generate_events_btn.clicked.connect(self._generate_events)
        events_actions.addWidget(self.generate_events_btn)

        self.reorder_events_btn = QPushButton("Auto-Order")
        self.reorder_events_btn.setToolTip("Reorder events by arc position")
        self.reorder_events_btn.setStyleSheet("font-size: 11px; padding: 3px 6px;")
        self.reorder_events_btn.clicked.connect(self._reorder_events_by_arc)
        events_actions.addWidget(self.reorder_events_btn)

        events_actions.addStretch()

        # Clear Plot Arc — destructive: drops every beat AND blanks
        # the AI-Assistant outline panel for this chapter. Lives at
        # the right of the row + uses red styling so the user can't
        # confuse it with the additive "Generate" / "Auto-Order"
        # actions on the left.
        self.clear_events_btn = QPushButton("Clear Plot Arc")
        self.clear_events_btn.setToolTip(
            "Remove every beat from this chapter's plot arc and "
            "drop the matching outline. The chapter prose is left "
            "untouched.")
        self.clear_events_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 3px 8px; "
            " color: #b91c1c; border: 1px solid #fecaca; "
            " border-radius: 3px; background: #fef2f2; } "
            "QPushButton:hover { background: #fee2e2; "
            " border-color: #fca5a5; } "
            "QPushButton:disabled { color: #9ca3af; "
            " background: transparent; border-color: #e5e7eb; }")
        self.clear_events_btn.clicked.connect(
            self._on_clear_events_clicked)
        events_actions.addWidget(self.clear_events_btn)

        events_layout.addLayout(events_actions)

        self.tab_widget.addTab(events_tab, "Events")

        # === TAB 2: Description ===
        description_tab = QWidget()
        description_layout = QVBoxLayout(description_tab)
        description_layout.setSpacing(4)

        desc_label = QLabel("Chapter summary:")
        desc_label.setStyleSheet("font-weight: 500; font-size: 11px;")
        description_layout.addWidget(desc_label)

        self.description_editor = QTextEdit()
        self.description_editor.setPlaceholderText(
            "Brief summary of what happens in this chapter..."
        )
        self.description_editor.setFont(QFont(SYSTEM_FONT, 10))
        self.description_editor.setMaximumHeight(100)  # Reduced for small screens
        self.description_editor.textChanged.connect(self._on_plan_changed)
        description_layout.addWidget(self.description_editor)

        # POV and Timeline - compact layout
        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(4)

        pov_label = QLabel("POV:")
        pov_label.setStyleSheet("font-size: 11px;")
        meta_layout.addWidget(pov_label)
        self.pov_edit = QLineEdit()
        self.pov_edit.setPlaceholderText("Perspective")
        self.pov_edit.setStyleSheet("font-size: 11px;")
        self.pov_edit.textChanged.connect(self._on_plan_changed)
        meta_layout.addWidget(self.pov_edit)

        timeline_label = QLabel("When:")
        timeline_label.setStyleSheet("font-size: 11px;")
        meta_layout.addWidget(timeline_label)
        self.timeline_edit = QLineEdit()
        self.timeline_edit.setPlaceholderText("Timeline")
        self.timeline_edit.setStyleSheet("font-size: 11px;")
        self.timeline_edit.textChanged.connect(self._on_plan_changed)
        meta_layout.addWidget(self.timeline_edit)

        description_layout.addLayout(meta_layout)

        # Characters and Locations - compact layout
        chars_locs_layout = QHBoxLayout()
        chars_locs_layout.setSpacing(4)

        chars_group = QGroupBox("Characters")
        chars_group.setStyleSheet("QGroupBox { font-size: 11px; }")
        chars_layout = QVBoxLayout(chars_group)
        chars_layout.setContentsMargins(4, 8, 4, 4)
        self.characters_edit = QLineEdit()
        self.characters_edit.setPlaceholderText("Names, comma-separated")
        self.characters_edit.setStyleSheet("font-size: 11px;")
        self.characters_edit.textChanged.connect(self._on_plan_changed)
        chars_layout.addWidget(self.characters_edit)
        chars_locs_layout.addWidget(chars_group)

        locs_group = QGroupBox("Locations")
        locs_group.setStyleSheet("QGroupBox { font-size: 11px; }")
        locs_layout = QVBoxLayout(locs_group)
        locs_layout.setContentsMargins(4, 8, 4, 4)
        self.locations_edit = QLineEdit()
        self.locations_edit.setPlaceholderText("Places, comma-separated")
        self.locations_edit.setStyleSheet("font-size: 11px;")
        self.locations_edit.textChanged.connect(self._on_plan_changed)
        locs_layout.addWidget(self.locations_edit)
        chars_locs_layout.addWidget(locs_group)

        description_layout.addLayout(chars_locs_layout)

        # Themes row — chapter-level thematic threads. The Plan AI can
        # propose themes via <suggest_theme> blocks, and the writer +
        # research agents pull these into the brief so each scene has
        # something to land thematically.
        themes_group = QGroupBox("Themes")
        themes_group.setStyleSheet("QGroupBox { font-size: 11px; }")
        themes_outer = QVBoxLayout(themes_group)
        themes_outer.setContentsMargins(4, 8, 4, 4)
        self.themes_edit = QLineEdit()
        self.themes_edit.setPlaceholderText(
            "Themes for this chapter, comma-separated "
            "(e.g. \"loyalty has a cost, inheritance survives refusal\")")
        self.themes_edit.setStyleSheet("font-size: 11px;")
        self.themes_edit.setToolTip(
            "Thematic threads the chapter should land. The writer "
            "agent uses these to anchor scenes; the research brief "
            "surfaces them under THEMES TO LAND. Ask the Plan AI to "
            "propose themes — it can emit <suggest_theme> blocks.")
        self.themes_edit.textChanged.connect(self._on_plan_changed)
        themes_outer.addWidget(self.themes_edit)
        description_layout.addWidget(themes_group)

        # Writing Style Metadata section
        style_group = QGroupBox("Writing Style (for AI Writer)")
        style_group.setStyleSheet("QGroupBox { font-size: 11px; font-weight: bold; }")
        style_layout = QVBoxLayout(style_group)
        style_layout.setContentsMargins(4, 8, 4, 4)
        style_layout.setSpacing(4)

        # Tone and Voice row
        tone_voice_layout = QHBoxLayout()
        tone_voice_layout.setSpacing(4)

        tone_label = QLabel("Tone:")
        tone_label.setStyleSheet("font-size: 11px;")
        tone_voice_layout.addWidget(tone_label)
        self.tone_edit = QLineEdit()
        self.tone_edit.setPlaceholderText("e.g., dark, hopeful, tense")
        self.tone_edit.setStyleSheet("font-size: 11px;")
        self.tone_edit.setToolTip("Emotional quality/mood of the chapter")
        self.tone_edit.textChanged.connect(self._on_plan_changed)
        tone_voice_layout.addWidget(self.tone_edit)

        voice_label = QLabel("Voice:")
        voice_label.setStyleSheet("font-size: 11px;")
        tone_voice_layout.addWidget(voice_label)
        self.voice_edit = QLineEdit()
        self.voice_edit.setPlaceholderText("e.g., sardonic, lyrical")
        self.voice_edit.setStyleSheet("font-size: 11px;")
        self.voice_edit.setToolTip("Narrative voice/personality")
        self.voice_edit.textChanged.connect(self._on_plan_changed)
        tone_voice_layout.addWidget(self.voice_edit)

        style_layout.addLayout(tone_voice_layout)

        # Style and Pacing row
        style_pacing_layout = QHBoxLayout()
        style_pacing_layout.setSpacing(4)

        prose_label = QLabel("Style:")
        prose_label.setStyleSheet("font-size: 11px;")
        style_pacing_layout.addWidget(prose_label)
        self.style_edit = QLineEdit()
        self.style_edit.setPlaceholderText("e.g., sparse, flowery")
        self.style_edit.setStyleSheet("font-size: 11px;")
        self.style_edit.setToolTip("Prose style notes")
        self.style_edit.textChanged.connect(self._on_plan_changed)
        style_pacing_layout.addWidget(self.style_edit)

        pacing_label = QLabel("Pacing:")
        pacing_label.setStyleSheet("font-size: 11px;")
        style_pacing_layout.addWidget(pacing_label)
        self.pacing_edit = QLineEdit()
        self.pacing_edit.setPlaceholderText("e.g., slow build, rapid")
        self.pacing_edit.setStyleSheet("font-size: 11px;")
        self.pacing_edit.setToolTip("Pacing notes for this chapter")
        self.pacing_edit.textChanged.connect(self._on_plan_changed)
        style_pacing_layout.addWidget(self.pacing_edit)

        style_layout.addLayout(style_pacing_layout)

        description_layout.addWidget(style_group)
        description_layout.addStretch()

        self.tab_widget.addTab(description_tab, "Description")

        # === TAB 3: Todo List ===
        todo_tab = QWidget()
        todo_layout = QVBoxLayout(todo_tab)
        todo_layout.setSpacing(4)

        todo_header = QHBoxLayout()
        todo_header.setSpacing(4)
        todo_label = QLabel("Writing Tasks:")
        todo_label.setStyleSheet("font-weight: 500; font-size: 11px;")
        todo_header.addWidget(todo_label)

        add_todo_btn = QPushButton("+ Add")
        add_todo_btn.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        add_todo_btn.clicked.connect(lambda: self._add_todo_item())
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

        # === TAB 4: Notes (organized by subject, collapsible) ===
        notes_tab = QWidget()
        notes_layout = QVBoxLayout(notes_tab)
        notes_layout.setSpacing(4)
        notes_layout.setContentsMargins(2, 4, 2, 2)

        # Top toolbar: subject selector + add/remove buttons
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        toolbar.addWidget(QLabel("Subject:"))
        self.subject_combo = QComboBox()
        self.subject_combo.setMinimumWidth(90)
        self.subject_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.subject_combo.setStyleSheet("font-size: 11px;")
        self.subject_combo.currentIndexChanged.connect(self._on_subject_selected)
        toolbar.addWidget(self.subject_combo)

        self.add_subject_btn = QPushButton("+")
        self.add_subject_btn.setFixedSize(24, 24)
        self.add_subject_btn.setToolTip("Add subject")
        self.add_subject_btn.setStyleSheet("font-weight: bold; font-size: 14px; padding: 0;")
        self.add_subject_btn.clicked.connect(self._add_note_subject)
        toolbar.addWidget(self.add_subject_btn)

        self.rename_subject_btn = QPushButton("Aa")
        self.rename_subject_btn.setFixedSize(24, 24)
        self.rename_subject_btn.setToolTip("Rename subject")
        self.rename_subject_btn.setStyleSheet("font-size: 10px; padding: 0;")
        self.rename_subject_btn.clicked.connect(self._rename_note_subject)
        toolbar.addWidget(self.rename_subject_btn)

        self.remove_subject_btn = QPushButton("\u2212")
        self.remove_subject_btn.setFixedSize(24, 24)
        self.remove_subject_btn.setToolTip("Remove subject")
        self.remove_subject_btn.setStyleSheet("font-weight: bold; font-size: 14px; padding: 0;")
        self.remove_subject_btn.clicked.connect(self._remove_note_subject)
        toolbar.addWidget(self.remove_subject_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedHeight(20)
        sep.setStyleSheet("color: #d1d5db;")
        toolbar.addWidget(sep)

        self.add_note_btn = QPushButton("+ Note")
        self.add_note_btn.setFixedHeight(24)
        self.add_note_btn.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        self.add_note_btn.clicked.connect(self._add_note_entry)
        toolbar.addWidget(self.add_note_btn)

        notes_layout.addLayout(toolbar)

        # Scrollable area for collapsible note entries
        self.notes_scroll = QScrollArea()
        self.notes_scroll.setWidgetResizable(True)
        self.notes_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.notes_container = QWidget()
        self.notes_entries_layout = QVBoxLayout(self.notes_container)
        self.notes_entries_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.notes_entries_layout.setSpacing(3)
        self.notes_entries_layout.setContentsMargins(0, 0, 0, 0)
        self.notes_scroll.setWidget(self.notes_container)
        notes_layout.addWidget(self.notes_scroll)

        # Internal state for notes
        self._notes_data: list = []  # List of subject dicts
        self._current_subject_index: int = -1
        self._note_entry_widgets: list = []  # List of {'frame', 'editor', 'title_edit', 'body_widget'}

        self.tab_widget.addTab(notes_tab, "Notes")

        # === TAB 5: Subplots ===
        subplots_tab = QWidget()
        subplots_layout = QVBoxLayout(subplots_tab)
        subplots_layout.setSpacing(4)
        subplots_layout.setContentsMargins(2, 4, 2, 2)

        subplots_header = QHBoxLayout()
        subplots_header.setSpacing(4)
        subplots_label = QLabel("Subplot Notes:")
        subplots_label.setStyleSheet("font-weight: 500; font-size: 11px;")
        subplots_label.setToolTip("Track how subplots progress in this chapter")
        subplots_header.addWidget(subplots_label)
        subplots_header.addStretch()

        add_subplot_btn = QPushButton("+ Subplot")
        add_subplot_btn.setFixedHeight(24)
        add_subplot_btn.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        add_subplot_btn.clicked.connect(self._add_subplot_note)
        subplots_header.addWidget(add_subplot_btn)

        subplots_layout.addLayout(subplots_header)

        # Scrollable area for subplot entries
        self.subplots_scroll = QScrollArea()
        self.subplots_scroll.setWidgetResizable(True)
        self.subplots_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.subplots_container = QWidget()
        self.subplots_entries_layout = QVBoxLayout(self.subplots_container)
        self.subplots_entries_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.subplots_entries_layout.setSpacing(3)
        self.subplots_entries_layout.setContentsMargins(0, 0, 0, 0)
        self.subplots_scroll.setWidget(self.subplots_container)
        subplots_layout.addWidget(self.subplots_scroll)

        # Internal state for subplots
        self._subplot_data: list = []  # List of subplot note dicts
        self._subplot_entry_widgets: list = []

        self.tab_widget.addTab(subplots_tab, "Subplots")

        upper_layout.addWidget(self.tab_widget)

        # Wrap upper portion in a scroll area so it scrolls when AI panel is expanded
        upper_scroll = QScrollArea()
        upper_scroll.setWidget(upper_widget)
        upper_scroll.setWidgetResizable(True)
        upper_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        upper_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        layout.addWidget(upper_scroll, 1)  # stretch factor 1 — takes remaining space

        # === COLLAPSIBLE AI ASSISTANT PANEL ===
        self.ai_panel = QFrame()
        self.ai_panel.setStyleSheet("""
            QFrame#ai_panel {
                border: 1px solid #8b5cf6;
                border-radius: 4px;
                background-color: #faf5ff;
            }
        """)
        self.ai_panel.setObjectName("ai_panel")
        ai_panel_layout = QVBoxLayout(self.ai_panel)
        ai_panel_layout.setContentsMargins(4, 4, 4, 4)
        ai_panel_layout.setSpacing(4)

        # Collapsible header bar
        ai_header = QHBoxLayout()
        ai_header.setSpacing(4)

        self.ai_toggle_btn = QPushButton("🤖 AI Assistant ▶")
        self.ai_toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: #8b5cf6;
                color: white;
                font-weight: bold;
                font-size: 11px;
                padding: 4px 8px;
                border-radius: 3px;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #7c3aed;
            }
        """)
        self.ai_toggle_btn.clicked.connect(self._toggle_ai_panel)
        ai_header.addWidget(self.ai_toggle_btn)
        ai_header.addStretch()

        # Clear button — wipes the visible chat history AND the
        # tracked _ai_history list (so the model isn't fed
        # already-discarded turns next time). Doesn't touch the
        # chapter's actual planning data; only the conversation.
        self.clear_chat_btn = QPushButton("🗑 Clear")
        self.clear_chat_btn.setStyleSheet(
            "QPushButton { padding: 3px 10px; font-size: 11px; "
            " border: 1px solid #d1d5db; border-radius: 4px; "
            " background: white; color: #374151; }"
            "QPushButton:hover { border-color: #6b7280; "
            " color: #111827; }")
        self.clear_chat_btn.setToolTip(
            "Clear the AI chat history (transcript + tracked "
            "context). Your planning data is unaffected.")
        self.clear_chat_btn.clicked.connect(
            self._clear_ai_conversation)
        ai_header.addWidget(self.clear_chat_btn)
        ai_panel_layout.addLayout(ai_header)

        # Collapsible content container
        self.ai_content = QWidget()
        ai_content_layout = QVBoxLayout(self.ai_content)
        ai_content_layout.setContentsMargins(0, 4, 0, 0)
        ai_content_layout.setSpacing(4)

        # Model info label - model is now configured in Settings
        info_label = QLabel("💡 Using model from Settings > Model Configuration")
        info_label.setStyleSheet(
            "font-size: 10px; color: #6b7280; padding: 4px; "
            "background-color: #f0f9ff; border-radius: 4px;"
        )
        info_label.setWordWrap(True)
        ai_content_layout.addWidget(info_label)

        # Chat history
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setFont(QFont(SYSTEM_FONT, 9))
        self.chat_history.setStyleSheet("background-color: #f8f9fa;")
        self.chat_history.setPlaceholderText("AI responses...")
        self.chat_history.setMinimumHeight(100)
        self.chat_history.setMaximumHeight(250)
        ai_content_layout.addWidget(self.chat_history)

        # Event-suggestion cards land in this dedicated panel below
        # the chat. Sits empty until the AI emits a <suggest_event>
        # block — then a card appears with the proposed beat + Add /
        # Skip buttons. The chat stays a plain QTextEdit (cheap +
        # familiar) and the cards live separately so they can host
        # real buttons without rebuilding the transcript as a widget
        # column.
        self._event_suggestions_panel = QWidget()
        self._event_suggestions_layout = QVBoxLayout(
            self._event_suggestions_panel)
        self._event_suggestions_layout.setContentsMargins(0, 0, 0, 0)
        self._event_suggestions_layout.setSpacing(4)
        ai_content_layout.addWidget(self._event_suggestions_panel)

        # Chat input - compact
        input_layout = QHBoxLayout()
        input_layout.setSpacing(4)
        self.chat_input = QTextEdit()
        self.chat_input.setPlaceholderText("Ask about your plan...")
        self.chat_input.setMaximumHeight(50)
        self.chat_input.setFont(QFont(SYSTEM_FONT, 10))
        input_layout.addWidget(self.chat_input)

        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet("font-size: 11px; padding: 3px 8px;")
        self.send_btn.clicked.connect(self._send_chat_message)
        input_layout.addWidget(self.send_btn)

        ai_content_layout.addLayout(input_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximum(0)
        self.progress_bar.setMaximumHeight(8)
        ai_content_layout.addWidget(self.progress_bar)

        ai_panel_layout.addWidget(self.ai_content)

        # Start collapsed
        self.ai_content.setVisible(False)
        self._ai_expanded = False

        layout.addWidget(self.ai_panel)

        # Consistency check section at bottom - compact for small screens
        check_frame = QFrame()
        check_frame.setStyleSheet("background-color: #fff3cd; border-radius: 3px;")
        check_layout = QHBoxLayout(check_frame)
        check_layout.setContentsMargins(6, 3, 6, 3)

        self.check_plan_btn = QPushButton("Check vs Chapter")
        self.check_plan_btn.setToolTip("Verify if chapter content follows the plan")
        self.check_plan_btn.clicked.connect(self._check_plan_consistency)
        self.check_plan_btn.setStyleSheet("background-color: #ffc107; color: black; font-size: 11px; padding: 3px 8px;")
        check_layout.addWidget(self.check_plan_btn)

        check_layout.addStretch()
        layout.addWidget(check_frame)

    def _on_plan_changed(self):
        """Handle any planning content change."""
        self._update_arc_widget()
        self.plan_changed.emit()

    # --- Notes subject/entry management ---

    def _add_note_subject(self):
        """Add a new subject with a default name, editable in the combo box."""
        self._save_current_entries()
        count = len(self._notes_data) + 1
        name = f"Subject {count}"
        subject = {
            'id': uuid.uuid4().hex[:8],
            'name': name,
            'entries': []
        }
        self._notes_data.append(subject)
        self.subject_combo.blockSignals(True)
        self.subject_combo.addItem(name)
        self.subject_combo.setCurrentIndex(len(self._notes_data) - 1)
        self.subject_combo.blockSignals(False)
        self._current_subject_index = len(self._notes_data) - 1
        self._refresh_note_entries()
        # Let user immediately rename by making combo editable and selecting text
        self.subject_combo.setEditable(True)
        self.subject_combo.lineEdit().editingFinished.connect(self._finish_subject_edit)
        QTimer.singleShot(0, lambda: (self.subject_combo.lineEdit().selectAll(), self.subject_combo.lineEdit().setFocus()))
        self._on_plan_changed()

    def _remove_note_subject(self):
        """Remove the selected subject and its notes."""
        row = self.subject_combo.currentIndex()
        if row < 0 or row >= len(self._notes_data):
            return
        name = self._notes_data[row]['name']
        reply = QMessageBox.question(
            self, "Remove Subject",
            f"Remove \"{name}\" and all its notes?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._notes_data.pop(row)
            self.subject_combo.blockSignals(True)
            self.subject_combo.removeItem(row)
            self.subject_combo.blockSignals(False)
            if self._notes_data:
                new_row = min(row, len(self._notes_data) - 1)
                self._current_subject_index = new_row
                self.subject_combo.setCurrentIndex(new_row)
            else:
                self._current_subject_index = -1
            self._refresh_note_entries()
            self._on_plan_changed()

    def _rename_note_subject(self):
        """Rename the selected subject inline via the combo box."""
        row = self.subject_combo.currentIndex()
        if row < 0 or row >= len(self._notes_data):
            return
        self.subject_combo.setEditable(True)
        self.subject_combo.lineEdit().editingFinished.connect(self._finish_subject_edit)
        QTimer.singleShot(0, lambda: (self.subject_combo.lineEdit().selectAll(), self.subject_combo.lineEdit().setFocus()))

    def _finish_subject_edit(self):
        """Commit the inline subject name edit."""
        if not self.subject_combo.isEditable():
            return
        line_edit = self.subject_combo.lineEdit()
        new_name = line_edit.text().strip()
        row = self.subject_combo.currentIndex()
        # Disconnect to avoid repeat calls
        try:
            line_edit.editingFinished.disconnect(self._finish_subject_edit)
        except TypeError:
            pass
        self.subject_combo.setEditable(False)
        if new_name and 0 <= row < len(self._notes_data):
            self._notes_data[row]['name'] = new_name
            self.subject_combo.setItemText(row, new_name)
            self._on_plan_changed()

    def _on_subject_selected(self, row: int):
        """Handle subject selection change."""
        self._save_current_entries()
        self._current_subject_index = row
        self._refresh_note_entries()

    def _add_note_entry(self):
        """Add a new note entry to the current subject."""
        if self._current_subject_index < 0:
            # Auto-create a General subject if none exists
            subject = {
                'id': uuid.uuid4().hex[:8],
                'name': 'General',
                'entries': []
            }
            self._notes_data.append(subject)
            self.subject_combo.blockSignals(True)
            self.subject_combo.addItem('General')
            self.subject_combo.setCurrentIndex(0)
            self.subject_combo.blockSignals(False)
            self._current_subject_index = 0

        entry = {'id': uuid.uuid4().hex[:8], 'title': '', 'content': '', 'collapsed': False}
        self._notes_data[self._current_subject_index]['entries'].append(entry)
        self._add_note_entry_widget(entry, len(self._note_entry_widgets), focus_title=True)
        self._on_plan_changed()

    def _remove_note_entry(self, index: int):
        """Remove a note entry by index."""
        if self._current_subject_index < 0:
            return
        subject = self._notes_data[self._current_subject_index]
        if 0 <= index < len(subject['entries']):
            subject['entries'].pop(index)
            self._refresh_note_entries()
            self._on_plan_changed()

    def _toggle_note_collapsed(self, index: int):
        """Toggle collapse state of a note entry."""
        if self._current_subject_index < 0:
            return
        subject = self._notes_data[self._current_subject_index]
        if 0 <= index < len(subject['entries']):
            subject['entries'][index]['collapsed'] = not subject['entries'][index].get('collapsed', False)
            # Update the widget visibility
            if index < len(self._note_entry_widgets):
                w = self._note_entry_widgets[index]
                collapsed = subject['entries'][index]['collapsed']
                w['body_widget'].setVisible(not collapsed)
                w['toggle_btn'].setText("\u25b6" if collapsed else "\u25bc")

    def _save_current_entries(self):
        """Save text and title from entry widgets back into the data model."""
        if self._current_subject_index < 0 or self._current_subject_index >= len(self._notes_data):
            return
        subject = self._notes_data[self._current_subject_index]
        for i, widget_info in enumerate(self._note_entry_widgets):
            if i < len(subject['entries']):
                subject['entries'][i]['content'] = widget_info['editor'].toPlainText()
                subject['entries'][i]['title'] = widget_info['title_edit'].text()

    def _refresh_note_entries(self):
        """Rebuild the note entry widgets for the current subject."""
        for widget_info in self._note_entry_widgets:
            widget_info['frame'].deleteLater()
        self._note_entry_widgets.clear()

        if self._current_subject_index < 0 or self._current_subject_index >= len(self._notes_data):
            return

        subject = self._notes_data[self._current_subject_index]
        for i, entry in enumerate(subject['entries']):
            self._add_note_entry_widget(entry, i)

    def _add_note_entry_widget(self, entry: dict, index: int, focus_title: bool = False):
        """Create a collapsible, titled note entry widget."""
        collapsed = entry.get('collapsed', False)
        title = entry.get('title', '') or ''

        # Prevent macOS from stealing window focus when new widgets appear
        wa_no_activate = Qt.WidgetAttribute.WA_ShowWithoutActivating

        frame = QFrame()
        frame.setAttribute(wa_no_activate)
        frame.setStyleSheet("""
            QFrame#noteCard {
                border: 1px solid #d1d5db;
                border-radius: 4px;
                background: #fefefe;
            }
        """)
        frame.setObjectName("noteCard")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        # Header bar: toggle + inline title edit + delete
        header = QWidget()
        header.setAttribute(wa_no_activate)
        header.setStyleSheet("background: #f3f4f6; border-top-left-radius: 4px; border-top-right-radius: 4px;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(6, 3, 4, 3)
        header_layout.setSpacing(4)

        toggle_btn = QPushButton("\u25b6" if collapsed else "\u25bc")
        toggle_btn.setFixedSize(18, 18)
        toggle_btn.setStyleSheet("border: none; font-size: 9px; color: #6b7280; padding: 0;")
        toggle_btn.setToolTip("Collapse/expand")
        toggle_btn.setAttribute(wa_no_activate)
        toggle_btn.clicked.connect(lambda _, idx=index: self._toggle_note_collapsed(idx))
        header_layout.addWidget(toggle_btn)

        title_edit = QLineEdit(title)
        title_edit.setAttribute(wa_no_activate)
        title_edit.setPlaceholderText("Note title...")
        title_edit.setStyleSheet(
            "font-weight: 600; font-size: 11px; color: #374151; background: transparent;"
            "border: none; padding: 0px 2px;"
        )
        title_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header_layout.addWidget(title_edit)

        del_btn = QPushButton("\u00d7")
        del_btn.setFixedSize(20, 18)
        del_btn.setToolTip("Remove note")
        del_btn.setAttribute(wa_no_activate)
        del_btn.setStyleSheet("border: none; font-size: 13px; font-weight: bold; color: #9ca3af; padding: 0;")
        del_btn.clicked.connect(lambda _, idx=index: self._remove_note_entry(idx))
        header_layout.addWidget(del_btn)

        frame_layout.addWidget(header)

        # Body: text editor (hidden when collapsed)
        body_widget = QWidget()
        body_widget.setAttribute(wa_no_activate)
        body_layout = QVBoxLayout(body_widget)
        body_layout.setContentsMargins(6, 4, 6, 6)
        body_layout.setSpacing(0)

        editor = QTextEdit()
        editor.setAttribute(wa_no_activate)
        editor.setPlainText(entry.get('content', ''))
        editor.setPlaceholderText("Write your note here...")
        editor.setFont(QFont(SYSTEM_FONT, 10))
        editor.setMinimumHeight(50)
        editor.setMaximumHeight(140)
        editor.setStyleSheet("border: none; background: transparent;")
        body_layout.addWidget(editor)

        body_widget.setVisible(not collapsed)
        frame_layout.addWidget(body_widget)

        # Add to layout, then connect change signals (avoids spurious signals during construction)
        self.notes_entries_layout.addWidget(frame)
        title_edit.textChanged.connect(self._on_plan_changed)
        editor.textChanged.connect(self._on_plan_changed)

        self._note_entry_widgets.append({
            'frame': frame,
            'editor': editor,
            'title_edit': title_edit,
            'toggle_btn': toggle_btn,
            'body_widget': body_widget,
        })

        if focus_title:
            def _restore_focus():
                title_edit.setFocus()
                title_edit.selectAll()
            QTimer.singleShot(0, _restore_focus)

    def _get_notes_data(self) -> list:
        """Return the current notes data, saving any in-progress edits."""
        self._save_current_entries()
        import copy
        return copy.deepcopy(self._notes_data)

    # --- Subplot note management ---

    def _add_subplot_note(self):
        """Add a new subplot note entry."""
        self._save_subplot_entries()
        entry = {
            'id': uuid.uuid4().hex[:8],
            'title': '',
            'content': '',
            'subplot_id': '',
            'status': 'active',
            'collapsed': False
        }
        self._subplot_data.append(entry)
        self._add_subplot_entry_widget(entry, len(self._subplot_data) - 1, focus_title=True)
        self._on_plan_changed()

    def _remove_subplot_note(self, index: int):
        """Remove a subplot note entry."""
        self._save_subplot_entries()
        if 0 <= index < len(self._subplot_data):
            self._subplot_data.pop(index)
            self._refresh_subplot_entries()
            self._on_plan_changed()

    def _toggle_subplot_collapsed(self, index: int):
        """Toggle collapse state of a subplot entry."""
        self._save_subplot_entries()
        if 0 <= index < len(self._subplot_data):
            self._subplot_data[index]['collapsed'] = not self._subplot_data[index].get('collapsed', False)
            if index < len(self._subplot_entry_widgets):
                w = self._subplot_entry_widgets[index]
                collapsed = self._subplot_data[index]['collapsed']
                w['body_widget'].setVisible(not collapsed)
                w['toggle_btn'].setText("\u25b6" if collapsed else "\u25bc")

    def _save_subplot_entries(self):
        """Persist widget edits to data model."""
        for i, w in enumerate(self._subplot_entry_widgets):
            if i < len(self._subplot_data):
                self._subplot_data[i]['title'] = w['title_edit'].text()
                self._subplot_data[i]['content'] = w['editor'].toPlainText()
                self._subplot_data[i]['status'] = w['status_combo'].currentText()

    def _refresh_subplot_entries(self):
        """Rebuild subplot entry widgets from data."""
        for w in self._subplot_entry_widgets:
            w['frame'].deleteLater()
        self._subplot_entry_widgets.clear()
        for i, entry in enumerate(self._subplot_data):
            self._add_subplot_entry_widget(entry, i)

    def _add_subplot_entry_widget(self, entry: dict, index: int, focus_title: bool = False):
        """Create a collapsible subplot entry widget."""
        collapsed = entry.get('collapsed', False)
        title = entry.get('title', '')
        status = entry.get('status', 'active')

        wa_no_activate = Qt.WidgetAttribute.WA_ShowWithoutActivating

        frame = QFrame()
        frame.setAttribute(wa_no_activate)
        frame.setStyleSheet("""
            QFrame#subplotCard {
                border: 1px solid #c4b5fd;
                border-radius: 4px;
                background: #faf5ff;
            }
        """)
        frame.setObjectName("subplotCard")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        # Header bar
        header = QWidget()
        header.setAttribute(wa_no_activate)
        header.setStyleSheet("background: #ede9fe; border-top-left-radius: 4px; border-top-right-radius: 4px;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(6, 3, 4, 3)
        header_layout.setSpacing(4)

        toggle_btn = QPushButton("\u25b6" if collapsed else "\u25bc")
        toggle_btn.setFixedSize(18, 18)
        toggle_btn.setAttribute(wa_no_activate)
        toggle_btn.setStyleSheet("border: none; font-size: 9px; color: #6d28d9; padding: 0;")
        toggle_btn.setToolTip("Collapse/expand")
        toggle_btn.clicked.connect(lambda _, idx=index: self._toggle_subplot_collapsed(idx))
        header_layout.addWidget(toggle_btn)

        title_edit = QLineEdit(title)
        title_edit.setAttribute(wa_no_activate)
        title_edit.setPlaceholderText("Subplot name...")
        title_edit.setStyleSheet(
            "font-weight: 600; font-size: 11px; color: #5b21b6; background: transparent;"
            "border: none; padding: 0px 2px;"
        )
        title_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header_layout.addWidget(title_edit)

        # Status indicator
        status_combo = QComboBox()
        status_combo.setAttribute(wa_no_activate)
        status_combo.addItems(["active", "resolved", "dormant"])
        status_combo.setCurrentText(status)
        status_combo.setFixedWidth(70)
        status_combo.setStyleSheet("font-size: 9px; padding: 0px 2px; border: 1px solid #c4b5fd; border-radius: 2px;")
        header_layout.addWidget(status_combo)

        del_btn = QPushButton("\u00d7")
        del_btn.setFixedSize(20, 18)
        del_btn.setToolTip("Remove subplot note")
        del_btn.setAttribute(wa_no_activate)
        del_btn.setStyleSheet("border: none; font-size: 13px; font-weight: bold; color: #8b5cf6; padding: 0;")
        del_btn.clicked.connect(lambda _, idx=index: self._remove_subplot_note(idx))
        header_layout.addWidget(del_btn)

        frame_layout.addWidget(header)

        # Body
        body_widget = QWidget()
        body_widget.setAttribute(wa_no_activate)
        body_layout = QVBoxLayout(body_widget)
        body_layout.setContentsMargins(6, 4, 6, 6)
        body_layout.setSpacing(0)

        editor = QTextEdit()
        editor.setAttribute(wa_no_activate)
        editor.setPlainText(entry.get('content', ''))
        editor.setPlaceholderText("How does this subplot progress in this chapter?")
        editor.setFont(QFont(SYSTEM_FONT, 10))
        editor.setMinimumHeight(50)
        editor.setMaximumHeight(140)
        editor.setStyleSheet("border: none; background: transparent;")
        body_layout.addWidget(editor)

        body_widget.setVisible(not collapsed)
        frame_layout.addWidget(body_widget)

        # Add to layout, then connect signals
        self.subplots_entries_layout.addWidget(frame)
        title_edit.textChanged.connect(self._on_plan_changed)
        editor.textChanged.connect(self._on_plan_changed)
        status_combo.currentTextChanged.connect(self._on_plan_changed)

        self._subplot_entry_widgets.append({
            'frame': frame,
            'editor': editor,
            'title_edit': title_edit,
            'status_combo': status_combo,
            'toggle_btn': toggle_btn,
            'body_widget': body_widget,
        })

        if focus_title:
            QTimer.singleShot(0, lambda: (title_edit.setFocus(), title_edit.selectAll()))

    def _get_subplot_data(self) -> list:
        """Return the current subplot data, saving any in-progress edits."""
        self._save_subplot_entries()
        import copy
        return copy.deepcopy(self._subplot_data)

    def _toggle_ai_panel(self):
        """Toggle the AI Assistant panel expand/collapse."""
        self._ai_expanded = not self._ai_expanded
        self.ai_content.setVisible(self._ai_expanded)
        if self._ai_expanded:
            self.ai_toggle_btn.setText("🤖 AI Assistant ▼")
        else:
            self.ai_toggle_btn.setText("🤖 AI Assistant ▶")

    def _update_arc_widget(self):
        """Update the arc visualization with current events."""
        events = [widget.get_data() for widget in self._event_widgets]
        self.arc_widget.set_events(events)

    def add_event_from_external(
        self,
        text: str,
        description: str = "",
        stage: str = "rising",
        arc_position: int = -1,
    ) -> str:
        """Public API for adding a single event to the currently-
        displayed chapter's arc.

        Called by the general AI chat after the user finishes a
        discussion that produces a new beat ("add this as an event
        to chapter 3"). Returns the new event's id so the caller
        can confirm or undo. Empty text returns "" without adding —
        callers should validate before calling.
        """
        text = (text or "").strip()
        if not text:
            return ""
        # Sanity-clamp stage to one of the canonical values so we
        # never end up with garbage from a free-text input.
        stage = (stage or "rising").lower().strip()
        if stage not in (
                "exposition", "rising", "climax", "falling",
                "resolution"):
            stage = "rising"
        # Stage-aware default arc position when none provided.
        if arc_position < 0:
            arc_position = {
                "exposition": 10,
                "rising": 30,
                "climax": 55,
                "falling": 75,
                "resolution": 90,
            }.get(stage, 50)
        else:
            arc_position = max(0, min(100, int(arc_position)))
        new_id = str(uuid.uuid4())
        self._add_event_item(
            text=text,
            description=description or "",
            stage=stage,
            arc_position=arc_position,
            event_id=new_id,
            order=len(self._event_widgets),
        )
        return new_id

    def _add_event_item(self, text: str = "", description: str = "", completed: bool = False,
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

        item = StoryEventWidget(event_id, text, description, completed, stage, arc_position, order)
        item.changed.connect(self._on_plan_changed)
        item.delete_requested.connect(self._remove_event_item)
        item.ai_help_requested.connect(
            self._on_event_ai_help_requested)
        item.arc_position_changed.connect(self._on_event_arc_changed)
        item.drag_started.connect(self._on_event_drag)

        self._event_widgets.append(item)
        self.events_list_layout.addWidget(item)
        self._renumber_events()
        self._on_plan_changed()

    def _on_event_ai_help_requested(self, event_id: str) -> None:
        """User clicked the ✨ button on a StoryEventWidget.

        Forwards the event's title + description + stage up via
        ``beat_ai_help_requested`` so MainWindow can route to the
        outline-mode chat with this beat as the engine-locked focus.
        """
        for w in self._event_widgets:
            if w.event_id != event_id:
                continue
            data = w.get_data() if hasattr(w, "get_data") else {}
            text = (data.get("text")
                    or w.text_edit.text() if hasattr(w, "text_edit")
                    else "")
            desc = (data.get("description") or "")
            stage = (data.get("stage") or "")
            self.beat_ai_help_requested.emit(
                event_id, text, desc, stage)
            return

    def _remove_event_item(self, event_id: str):
        """Remove a story event."""
        for item in self._event_widgets:
            if item.event_id == event_id:
                self._event_widgets.remove(item)
                item.deleteLater()
                self._renumber_events()
                self._on_plan_changed()
                break

    def update_events(self, events) -> None:
        """Replace ONLY the visible events list — leave every other
        planning field (description, POV, characters, notes, etc.)
        alone.

        Used by MainWindow after the AI-Assistant outline panel
        rewrites ``chapter.planning.events`` directly. Without this
        refresh, the planner widget stays out of sync, and the next
        ``save_to_model`` (fired on chapter switch / autosave) would
        read the stale planner UI and clobber the freshly-written
        events with an empty list.

        Accepts a list of either ``StoryEvent`` instances or dicts.
        """
        # Tear down existing event widgets.
        for widget in self._event_widgets[:]:
            widget.deleteLater()
        self._event_widgets.clear()

        for i, event in enumerate(events or []):
            if hasattr(event, "model_dump"):
                data = event.model_dump()
            elif isinstance(event, dict):
                data = event
            else:
                # Fallback: pull common fields off the object.
                data = {
                    "id": getattr(event, "id", None),
                    "text": getattr(event, "text", "") or "",
                    "description": getattr(event, "description", "") or "",
                    "completed": getattr(event, "completed", False),
                    "stage": getattr(event, "stage", "rising"),
                    "arc_position": getattr(event, "arc_position", -1),
                    "order": getattr(event, "order", i),
                }
            self._add_event_item(
                text=data.get("text", "") or "",
                description=data.get("description", "") or "",
                completed=data.get("completed", False),
                stage=data.get("stage", "rising"),
                arc_position=data.get("arc_position", -1),
                event_id=data.get("id"),
                order=i,
            )
        self._update_arc_widget()

    def _on_clear_events_clicked(self):
        """Clear every beat after a confirmation prompt.

        Wipes this widget's event list AND emits ``events_cleared``
        so MainWindow can blank the chapter's planning.events,
        planning.outline, and the AI-Assistant outline panel.
        Chapter prose is intentionally left alone.
        """
        if not self._event_widgets:
            QMessageBox.information(
                self, "Nothing to clear",
                "This chapter has no plot arc beats yet.")
            return
        reply = QMessageBox.question(
            self, "Clear plot arc?",
            "Remove every beat from this chapter's plot arc and "
            "drop the matching outline?\n\n"
            "The chapter's prose stays untouched. This can't be "
            "undone — re-generate or rebuild beats afterwards.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        # Tear down the event widgets.
        for w in self._event_widgets[:]:
            w.deleteLater()
        self._event_widgets.clear()
        self._update_arc_widget()
        # Notify listeners — MainWindow handles the cross-widget
        # cleanup (planning.events / planning.outline / panel).
        # Emit plan_changed too so the standard
        # "planning content changed" wiring (autosave, dirty
        # marker, etc.) still kicks in.
        self.events_cleared.emit()
        self._on_plan_changed()

    def _renumber_events(self):
        """Update order numbers for all events."""
        for i, widget in enumerate(self._event_widgets):
            widget.set_order(i)

    def _on_event_drag(self, signal_data: str):
        """Handle drag and drop reordering of events."""
        if signal_data.startswith("drop:"):
            # Parse the drop signal: "drop:source_id:target_id"
            parts = signal_data.split(":")
            if len(parts) == 3:
                source_id = parts[1]
                target_id = parts[2]
                self._move_event(source_id, target_id)

    def _move_event(self, source_id: str, target_id: str):
        """Move source event to the position of target event."""
        source_widget = None
        target_widget = None
        source_idx = -1
        target_idx = -1

        for i, widget in enumerate(self._event_widgets):
            if widget.event_id == source_id:
                source_widget = widget
                source_idx = i
            if widget.event_id == target_id:
                target_widget = widget
                target_idx = i

        if source_widget and target_widget and source_idx != target_idx:
            # Remove from current position
            self._event_widgets.pop(source_idx)
            self.events_list_layout.removeWidget(source_widget)

            # Recalculate target index after removal
            if source_idx < target_idx:
                target_idx -= 1

            # Insert at new position
            self._event_widgets.insert(target_idx, source_widget)
            self.events_list_layout.insertWidget(target_idx, source_widget)

            # Update order numbers and arc
            self._renumber_events()
            self._update_arc_widget()
            self._on_plan_changed()

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
                description=event.get('description', ''),
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
                    description=event.get('description', ''),
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

        themes = planning_data.get('themes', [])
        self.themes_edit.setText(', '.join(themes) if themes else '')

        # Notes (organized by subject)
        notes_raw = planning_data.get('notes', [])
        if isinstance(notes_raw, str):
            # Legacy string format - migrate to subject-based
            if notes_raw.strip():
                self._notes_data = [{
                    'id': uuid.uuid4().hex[:8],
                    'name': 'General',
                    'entries': [{'id': uuid.uuid4().hex[:8], 'title': 'Note', 'content': notes_raw, 'collapsed': False}]
                }]
            else:
                self._notes_data = []
        elif isinstance(notes_raw, list):
            # Ensure entries have title field (backwards compat with previous format)
            for subject in notes_raw:
                for entry in subject.get('entries', []):
                    if 'title' not in entry:
                        entry['title'] = 'Untitled'
                    if 'collapsed' not in entry:
                        entry['collapsed'] = False
            self._notes_data = notes_raw
        else:
            self._notes_data = []

        self.subject_combo.blockSignals(True)
        self.subject_combo.clear()
        for subject in self._notes_data:
            self.subject_combo.addItem(subject.get('name', 'Untitled'))
        self.subject_combo.blockSignals(False)
        if self._notes_data:
            self._current_subject_index = 0
            self.subject_combo.setCurrentIndex(0)
            self._refresh_note_entries()
        else:
            self._current_subject_index = -1
            self._refresh_note_entries()

        # Writing style metadata
        self.tone_edit.setText(planning_data.get('tone', ''))
        self.voice_edit.setText(planning_data.get('voice', ''))
        self.style_edit.setText(planning_data.get('style', ''))
        self.pacing_edit.setText(planning_data.get('pacing', ''))

        # Subplot notes
        subplot_raw = planning_data.get('subplot_notes', [])
        if isinstance(subplot_raw, list):
            # Ensure entries have required fields (backwards compat)
            for entry in subplot_raw:
                if 'title' not in entry:
                    entry['title'] = ''
                if 'collapsed' not in entry:
                    entry['collapsed'] = False
                if 'status' not in entry:
                    entry['status'] = 'active'
                if 'subplot_id' not in entry:
                    entry['subplot_id'] = ''
            self._subplot_data = subplot_raw
        else:
            self._subplot_data = []
        self._refresh_subplot_entries()

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

        themes_text = self.themes_edit.text().strip()
        themes = [t.strip() for t in themes_text.split(',')
                  if t.strip()] if themes_text else []

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
            'notes': self._get_notes_data(),
            'subplot_notes': self._get_subplot_data(),
            'characters_featured': chars,
            'locations': locs,
            'pov_character': self.pov_edit.text(),
            'timeline_position': self.timeline_edit.text(),
            'scene_list': [],  # Could be expanded later
            'themes': themes,
            # Writing style metadata
            'tone': self.tone_edit.text(),
            'voice': self.voice_edit.text(),
            'style': self.style_edit.text(),
            'pacing': self.pacing_edit.text()
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
            description = event.get('description', '')
            completed = event.get('completed', False)

            if stage != current_stage:
                current_stage = stage
                stage_name = StoryEventWidget.STAGE_NAMES.get(stage, stage.title())
                lines.append(f"\n## {stage_name}\n")

            check = "✓" if completed else "-"
            lines.append(f"{check} {text}")

            # Include description if present
            if description and description.strip():
                # Indent the description under the event
                for desc_line in description.strip().split('\n'):
                    lines.append(f"    {desc_line}")

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

    def _get_context(self, question: str = "") -> dict:
        """Get the current context for AI requests.

        ``question`` is forwarded to the host's context provider so
        the host's RAG layer can pick the most relevant items for
        THIS question. Providers that don't accept the kwarg fall
        back to a no-arg call so older wiring keeps working.
        """
        if not self._context_provider:
            return {}
        try:
            return self._context_provider(question=question) or {}
        except TypeError:
            return self._context_provider() or {}

    def _get_chapter_content(self) -> str:
        """Get the current chapter content."""
        if self._chapter_content_provider:
            return self._chapter_content_provider()
        return ""

    def _collect_chapter_context_block(self) -> str:
        """Snapshot the chapter-specific signals from this widget for
        the AI prompt.

        Bundles together:
          * Chapter description (the writer's intent)
          * POV character, timeline position
          * Tone / voice / style fields
          * Featured characters, locations, themes
          * Planned scene_list (if any)
          * The chapter prose itself (truncated to ~6000 chars
            head + tail when long)

        Returns the formatted block as a single string ready to prepend
        to ``context_parts`` in ``_run_ai_request``. Empty string when
        no signal is set — the prompt then falls back to project-level
        context only, which was the legacy behavior.
        """
        bits: list = []

        # --- Planning fields (cheap reads from the form) ---
        def _val(widget) -> str:
            try:
                if hasattr(widget, "toPlainText"):
                    return (widget.toPlainText() or "").strip()
                if hasattr(widget, "text"):
                    return (widget.text() or "").strip()
            except Exception:
                return ""
            return ""

        description = _val(self.description_editor)
        if description:
            bits.append(f"Chapter description (writer's intent):\n"
                        f"{description}")
        pov = _val(self.pov_edit)
        if pov:
            bits.append(f"POV character: {pov}")
        timeline = _val(self.timeline_edit)
        if timeline:
            bits.append(f"Timeline position: {timeline}")
        tone = _val(self.tone_edit) if hasattr(self, "tone_edit") else ""
        if tone:
            bits.append(f"Tone: {tone}")
        voice = (
            _val(self.voice_edit) if hasattr(self, "voice_edit") else "")
        if voice:
            bits.append(f"Voice: {voice}")
        style = (
            _val(self.style_edit) if hasattr(self, "style_edit") else "")
        if style:
            bits.append(f"Style: {style}")
        characters = (
            _val(self.characters_edit)
            if hasattr(self, "characters_edit") else "")
        if characters:
            bits.append(f"Characters featured: {characters}")
        locations = (
            _val(self.locations_edit)
            if hasattr(self, "locations_edit") else "")
        if locations:
            bits.append(f"Locations: {locations}")
        themes = (
            _val(self.themes_edit)
            if hasattr(self, "themes_edit") else "")
        if themes:
            bits.append(f"Themes: {themes}")

        # --- Existing planned scenes (if any) ---
        scene_list_widget = (
            getattr(self, "scene_list_edit", None)
            or getattr(self, "scene_list_editor", None))
        if scene_list_widget is not None:
            sl = _val(scene_list_widget)
            if sl:
                bits.append(f"Existing planned scene list:\n{sl}")

        # --- Chapter prose (when written) ---
        # This is the load-bearing signal the previous version missed.
        # If text exists, the AI should derive beats from what
        # actually happens, not just from metadata.
        content = self._get_chapter_content()
        if content and content.strip():
            content = content.strip()
            wc = len(content.split())
            if len(content) > 6000:
                # Head + tail keeps the chapter's opening + climax
                # within budget without cutting either end.
                head = content[:3000].rstrip()
                tail = content[-2500:].lstrip()
                content_for_prompt = (
                    f"{head}\n\n"
                    f"... [middle of chapter elided, "
                    f"~{wc - 1000} words omitted] ...\n\n"
                    f"{tail}")
            else:
                content_for_prompt = content
            bits.append(
                f"Chapter prose (the actual text — use this as the "
                f"primary signal for what happens in this chapter):\n"
                f"{content_for_prompt}")

        if not bits:
            return ""
        return "THIS CHAPTER:\n" + "\n\n".join(bits)

    def _append_to_chat(self, role: str, message: str):
        """Append a message to the chat history."""
        print(f"[ChapterPlanner] _append_to_chat called: role={role}, message_len={len(message)}")

        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        if role == "assistant":
            # Convert markdown to HTML for AI responses
            html_content = self._markdown_to_html(message)
            cursor.insertHtml(
                f'<div style="margin: 6px 0;">'
                f'<b style="color: #006600;">AI:</b>'
                f'<div style="color: #1a1a1a; margin-top: 4px;">{html_content}</div>'
                f'</div>'
            )
        else:
            import html
            escaped_message = html.escape(message)
            if role == "user":
                cursor.insertHtml(f'<p style="color: #0066cc;"><b>You:</b> {escaped_message}</p>')
            elif role == "system":
                cursor.insertHtml(f'<p style="color: #666666;"><i>{escaped_message}</i></p>')
            elif role == "error":
                cursor.insertHtml(f'<p style="color: #cc0000;"><b>Error:</b> {escaped_message}</p>')

        cursor.insertHtml("<br>")
        self.chat_history.setTextCursor(cursor)
        self.chat_history.ensureCursorVisible()

        print(f"[ChapterPlanner] _append_to_chat completed")

    def _markdown_to_html(self, text: str) -> str:
        """Convert markdown in AI responses to formatted HTML."""
        import re
        import html as html_mod

        lines = text.split('\n')
        html_lines = []
        in_list = False
        in_code_block = False

        for line in lines:
            stripped = line.strip()

            # Code blocks
            if stripped.startswith('```'):
                if in_code_block:
                    html_lines.append('</pre>')
                    in_code_block = False
                else:
                    if in_list:
                        html_lines.append('</ul>')
                        in_list = False
                    html_lines.append(
                        '<pre style="background-color: #eef2f7; padding: 6px; '
                        'border-radius: 4px; font-family: monospace; font-size: 11px; '
                        'white-space: pre-wrap; margin: 4px 0;">')
                    in_code_block = True
                continue

            if in_code_block:
                escaped = html_mod.escape(stripped)
                html_lines.append(escaped)
                continue

            # Headers
            if stripped.startswith('### '):
                if in_list:
                    html_lines.append('</ul>')
                    in_list = False
                title = html_mod.escape(stripped[4:])
                html_lines.append(
                    f'<div style="color: #4f46e5; font-weight: bold; font-size: 11px; '
                    f'margin-top: 8px; margin-bottom: 2px;">{title}</div>')
                continue
            if stripped.startswith('## '):
                if in_list:
                    html_lines.append('</ul>')
                    in_list = False
                title = html_mod.escape(stripped[3:])
                html_lines.append(
                    f'<div style="color: #4f46e5; font-weight: bold; font-size: 12px; '
                    f'margin-top: 10px; margin-bottom: 2px;">{title}</div>')
                continue
            if stripped.startswith('# '):
                if in_list:
                    html_lines.append('</ul>')
                    in_list = False
                title = html_mod.escape(stripped[2:])
                html_lines.append(
                    f'<div style="color: #312e81; font-weight: bold; font-size: 13px; '
                    f'margin-top: 12px; margin-bottom: 4px;">{title}</div>')
                continue

            # List items (- or *)
            if stripped.startswith('- ') or stripped.startswith('* '):
                if not in_list:
                    html_lines.append('<ul style="margin: 4px 0 4px 16px; padding: 0;">')
                    in_list = True
                item_text = self._inline_markdown(stripped[2:])
                html_lines.append(f'<li style="margin: 2px 0;">{item_text}</li>')
                continue

            # Numbered list items
            if re.match(r'^\d+\.\s', stripped):
                if not in_list:
                    html_lines.append('<ul style="margin: 4px 0 4px 16px; padding: 0;">')
                    in_list = True
                item_text = re.sub(r'^\d+\.\s', '', stripped)
                item_text = self._inline_markdown(item_text)
                html_lines.append(f'<li style="margin: 2px 0;">{item_text}</li>')
                continue

            # Close list on non-list line
            if in_list:
                html_lines.append('</ul>')
                in_list = False

            # Empty lines
            if not stripped:
                html_lines.append('<br>')
                continue

            # Regular paragraph
            p = self._inline_markdown(stripped)
            html_lines.append(f'<div style="margin: 3px 0; line-height: 1.4;">{p}</div>')

        if in_list:
            html_lines.append('</ul>')
        if in_code_block:
            html_lines.append('</pre>')

        return '\n'.join(html_lines)

    def _inline_markdown(self, text: str) -> str:
        """Convert inline markdown (bold, italic, code) to HTML."""
        import re
        import html as html_mod
        # Escape HTML first, then apply markdown
        text = html_mod.escape(text)
        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        # Italic
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        # Inline code
        text = re.sub(
            r'`([^`]+)`',
            r'<code style="background-color: #eef2f7; padding: 1px 3px; border-radius: 3px; font-family: monospace; font-size: 11px;">\1</code>',
            text
        )
        return text

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

        # Detect whether the writer has already written prose; the
        # prompt reads differently when there's text to anchor to vs.
        # when the chapter is still empty. The block was prepended in
        # _run_ai_request from _collect_chapter_context_block.
        has_prose = bool(self._get_chapter_content().strip())
        has_description = bool(
            self.description_editor.toPlainText().strip()
            if hasattr(self, "description_editor") else "")

        if has_prose:
            primary_directive = (
                "PRIMARY DIRECTIVE: recognize the beats that already "
                "exist in the CHAPTER PROSE block above. Each event "
                "you list MUST correspond to a real moment in the "
                "prose — paraphrase a recognizable moment so the "
                "writer can find it in their draft. Do NOT invent "
                "beats that aren't on the page.\n\n"
                "PARTIAL ARCS ARE EXPECTED. The writer may have only "
                "written the opening, only the climax, or skipped "
                "around. Follow these rules:\n"
                "  * If a stage (exposition / rising / climax / "
                "falling / resolution) has no corresponding moment in "
                "the prose, OMIT that stage entirely — do NOT make "
                "one up.\n"
                "  * After your numbered list of recognized beats, "
                "add a single line starting with 'GAPS:' that names "
                "the stages absent from the prose (e.g., "
                "'GAPS: climax, falling, resolution'). Omit the GAPS "
                "line when the arc is complete.\n"
                "  * If the prose ends in the middle of a beat "
                "(scene fades, sentence stops), label that beat "
                "with [partial] instead of a stage name and note "
                "what it appears to be building toward.\n"
                "  * Return AT MOST one event per recognized beat "
                "— don't pad."
            )
        elif has_description:
            primary_directive = (
                "PRIMARY DIRECTIVE: the writer hasn't written prose "
                "yet, but they have given a chapter description above. "
                "Use that description as your structural source — each "
                "event you propose must develop a thread the writer "
                "named, not invent unrelated beats."
            )
        else:
            primary_directive = (
                "PRIMARY DIRECTIVE: there's no chapter prose or "
                "description yet — generate a plausible arc based on "
                "the project context (plot, characters, themes). "
                "Lean toward beats that would set up the next chapter "
                "rather than freelance."
            )

        prompt = f"""Generate 5-8 specific story events for the chapter titled "{chapter_title}".

{primary_directive}

TASK:
Create concrete story beats that:
- Match the chapter's prose, description, and writer-specified
  tone/voice/style (in THIS CHAPTER block above) when present
- Align with the established plot, characters, and worldbuilding
- Show character development and advance the narrative
- Follow a natural chapter arc structure
- Are specific and actionable (not vague)
- Each beat names the character doing the action and where it
  happens (use the chapter's locations / POV when given)

FORMAT YOUR RESPONSE — TWO LINES PER EVENT:
Use a numbered list. The FIRST line of each item is a SHORT TITLE
(3-7 words, evocative, the kind of label a writer would pin to an
index card). The SECOND line is a DESCRIPTION (1-2 sentences with
the concrete action — who does what, where, why it matters).
Indent the description line with two spaces so the parser can tell
it apart from the title.

EXAMPLE FORMAT (do not copy the content — generate beats for the
chapter above):

1. [exposition] The Council Summons
  Mara is brought before the council to answer for her unsanctioned raids on the border villages.

2. [rising] Refusing the Call
  She argues with Bren in the antechamber that taking the mission means abandoning the survivors at Highveld.

3. [climax] The Reckoning
  Mara accepts the council's terms, knowing it will cost her Bren's trust.

4. [falling] The Cold Walk Home
  She leaves through the rain alone, replaying the moment Bren turned away.

5. [resolution] A New Loyalty
  She arrives at her quarters and burns her commission letter, sealing the choice.

Make each title concrete and each description specific to character actions
and scene details — never generic craft advice."""

        self._append_to_chat("system", f"Generating events for {chapter_title}...")
        self._set_processing(True)

        def on_response(response: str):
            self._set_processing(False)
            if response:
                gaps = self._parse_ai_events_response(response)
                if gaps:
                    # Partial arc — tell the writer which stages
                    # weren't found in the prose so they know what
                    # the AI deliberately didn't fabricate.
                    self._append_to_chat(
                        "assistant",
                        f"Events recognized from the chapter. The "
                        f"AI noted that these arc stages aren't yet "
                        f"present in the prose: **{gaps}**. Add "
                        f"beats for those manually when you write "
                        f"them.")
                else:
                    self._append_to_chat(
                        "assistant",
                        "Events generated! Review and adjust as "
                        "needed.")
            else:
                self._append_to_chat("error", "Failed to generate events.")

        self._run_ai_request(prompt, context, on_response)

    def _parse_ai_events_response(self, response: str) -> str:
        """Parse AI response into events.

        Returns the ``GAPS:`` line (with the prefix stripped) when
        the model surfaced one — that's a hint to the writer about
        which arc stages aren't yet on the page. Empty string when
        no GAPS line was returned (full arc, or older prompt format).
        """
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
            'denouement': 'resolution',
            # [partial] is emitted when the prose ends mid-beat;
            # we attach it as a rising-action event but mark the text
            # so it's visible to the writer that this beat is not yet
            # fully on the page.
            'partial': 'rising',
        }
        # Collect any "GAPS: …" line so we can surface it to the user
        # after the recognized beats land. This is the AI naming which
        # stages are still missing from the prose — a hint for the
        # writer, not an event to add to the arc.
        gaps_line: str = ""

        # Regex used to validate whether a line is plausibly an event
        # entry vs. preamble / commentary. Bug we're fixing: the model
        # often opens with "Here are the specific story events for the
        # chapter…" — that line had no number and no stage tag, but
        # the previous parser still added it as a rising-action event
        # because it was non-empty and longer than 5 chars.
        # An event line MUST either:
        #   1. Start with a numbered list marker (1. / 1) / 1: ), OR
        #   2. Start with a recognized [stage] tag (allowing an
        #      optional dash/bullet prefix from looser formats).
        # Lines failing both tests are commentary and skipped.
        import re
        _STAGE_WORDS = (
            r"exposition|rising[\s_-]*action|rising|climax|"
            r"falling[\s_-]*action|falling|resolution|denouement|"
            r"partial")
        _NUMBERED_RE = re.compile(r"^\d+\s*[\.\):]\s+")
        _STAGE_TAG_RE = re.compile(
            r"^[\-*•]?\s*\[(" + _STAGE_WORDS + r")\b",
            re.IGNORECASE)

        def _is_event_line(stripped: str) -> bool:
            # Strip leading markdown bold / italic markers so
            # ``**1.`` and ``__1.`` still pass the numbered check.
            cleaned = re.sub(r"^[\s*_]+", "", stripped)
            if not cleaned:
                return False
            return bool(_NUMBERED_RE.match(cleaned)
                        or _STAGE_TAG_RE.match(cleaned))

        # Two-pass: walk the lines to assemble (title, stage,
        # description) tuples, then add them as widgets at the end.
        # The new prompt asks the model to put a short title on the
        # numbered line and a longer description on the following
        # line(s) — we collect non-event lines after an event as
        # description continuation. Blank lines reset the
        # continuation cursor so the trailing summary block can't
        # bleed into the last event's description.
        events_to_add: List[dict] = []
        current_event: Optional[dict] = None
        event_order = 0

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                # Blank lines break description continuation. The
                # next non-event line will then be skipped as
                # orphan / commentary unless it matches an event.
                current_event = None
                continue

            low = line.lower()
            if low.startswith("gaps:") or low.startswith("**gaps:"):
                gaps_line = re.sub(r"^\**\s*gaps:\s*", "",
                                   line, flags=re.IGNORECASE).strip(
                                       " *")
                current_event = None
                continue

            if not _is_event_line(line):
                # If we're sitting under an event, this is its
                # description continuation. Otherwise it's preamble
                # or trailing commentary — skip silently.
                if current_event is not None:
                    cont = re.sub(r"^[\s\-*•]+", "", line).strip()
                    if cont:
                        if current_event["description"]:
                            current_event["description"] += " " + cont
                        else:
                            current_event["description"] = cont
                continue

            # New event line. Strip list marker + [stage] tag and
            # decide whether the model crammed the description onto
            # the same line via ``Title: description`` or ``Title —
            # description``. Splitting only when the prefix looks
            # short keeps real titles that contain a colon intact.
            stage = 'rising'
            is_partial = False
            text = re.sub(r"^[\s*_]+", "", line)
            text = re.sub(r"^\d+\s*[\.\):]\s*", "", text)
            text = re.sub(r"^[\-*•]\s+", "", text).strip()

            bracket_match = re.match(r'\s*\[([^\]]+)\]\s*', text)
            if bracket_match:
                stage_text = bracket_match.group(1).lower().strip()
                if stage_text == 'partial':
                    is_partial = True
                stage = stage_map.get(stage_text, 'rising')
                text = text[bracket_match.end():].strip()

            title = text
            inline_desc = ""
            # Detect ``title — description`` and ``title: description``
            # patterns the model sometimes uses. Only split when the
            # title side is short enough to plausibly BE a title,
            # protecting titles like "Marcus: A Reckoning" from
            # being chopped at a meaningful punctuation.
            for sep in (" — ", " – ", ": ", " - "):
                idx = title.find(sep)
                if idx > 0 and idx <= 60:
                    inline_desc = title[idx + len(sep):].strip()
                    title = title[:idx].strip()
                    break

            if is_partial:
                title = f"[partial] {title}"

            if not title or len(title) <= 2:
                continue

            stage_positions = {
                'exposition': 10 + event_order * 3,
                'rising': 25 + event_order * 5,
                'climax': 50,
                'falling': 65 + event_order * 3,
                'resolution': 85 + event_order * 3,
            }
            arc_pos = min(stage_positions.get(stage, 50), 95)

            current_event = {
                "text": title,
                "description": inline_desc,
                "stage": stage,
                "arc_position": arc_pos,
                "order": event_order,
            }
            events_to_add.append(current_event)
            event_order += 1

        # Now add each collected event. Doing it in a separate pass
        # keeps the title/description join step clean — we have the
        # full description (head + any continuation lines) at the
        # moment we construct the widget.
        for ev in events_to_add:
            self._add_event_item(
                text=ev["text"],
                description=ev["description"],
                stage=ev["stage"],
                arc_position=ev["arc_position"],
                order=ev["order"],
            )

        return gaps_line

    def _send_chat_message(self):
        """Send a chat message to the AI.

        Capabilities the model is told it has:
          * Reference the chapter's plan + the project's plot map,
            characters, worldbuilding, and any RAG-focused matches
            the host injects into the context.
          * Propose new chapter beats inline via <suggest_event>
            blocks the user can review with Add / Skip cards.

        Conversation history is tracked in ``_ai_history`` (turn
        list) and ``_ai_history_summary`` (compacted older turns),
        so multi-turn discussions stay coherent without blowing
        the context window.
        """
        if not self._ai_handler:
            QMessageBox.warning(self, "AI Not Available", "AI handler not configured.")
            return

        message = self.chat_input.toPlainText().strip()
        if not message:
            return

        self.chat_input.clear()
        # Drop any pending suggestion cards from the previous AI
        # response. Once the user has moved on with a new question,
        # those Add buttons are stale — the new response will bring
        # its own suggestions. Without this, half-considered cards
        # pile up and compete with fresh ones the next round.
        # Cards the user already actioned are gone (banner replaced
        # them), so this is safe.
        self._clear_event_suggestion_cards()
        self._append_to_chat("user", message)
        self._ai_history.append(
            {"role": "user", "content": message})

        # Compact older turns before sending so a long planner
        # session doesn't fill the context window with stale chat.
        self._maybe_compact_ai_history()

        # Pass the user's question so the host's RAG layer can pick
        # the most relevant project items for THIS question (instead
        # of dumping the whole roster).
        context = self._get_context(question=message)
        context['current_plan'] = self.get_plan()
        # Compacted older-turns summary becomes its own context key
        # the prompt builder folds in.
        if self._ai_history_summary:
            context['planner_history_summary'] = (
                self._ai_history_summary)
        # Keep the recent turns (excluding the one we just appended,
        # which becomes the live USER QUESTION) so the model has
        # multi-turn coherence.
        recent_turns = (
            self._ai_history[:-1]
            if self._ai_history else [])
        context['planner_recent_turns'] = recent_turns

        prompt = f"""USER QUESTION:
{message}

INSTRUCTIONS:
You are the chapter-planner sub-agent. Help the user shape this chapter using the project context above (plot map, characters, worldbuilding, current outline, and any RAG-selected items relevant to the question).

WHEN THE DISCUSSION CALLS FOR NEW BEATS:
You may propose new story beats (the events shown on the chapter arc) by emitting one or more inline blocks the user reviews with Add / Skip cards. Use this exact tag and JSON shape:

  <suggest_event>{{"text":"short beat name","description":"one or two sentences on what happens","stage":"exposition|rising|climax|falling|resolution","arc_position":<int 0-100>,"why":"why this beat belongs in the chapter"}}</suggest_event>

Rules for suggestions:
- Only suggest when the discussion genuinely calls for it (e.g. user asks "what should happen first?", "add a beat where Marcus confronts Lena", "what's missing from this chapter?"). Don't pad answers with suggestions.
- For a series of beats (3-6 events covering opening → close), emit one <suggest_event> per beat in order. Cap at 6 per reply.
- ``arc_position`` should be 0 (chapter open) → 100 (chapter end), spread sensibly across the suggested beats.
- ``stage`` should match where the beat falls in the chapter's arc. For a single new beat slotted into an existing chapter, pick the stage that fits its position relative to the events already in the outline.
- Use character names from the CHARACTERS context — don't invent characters.
- The block goes inline in your reply; the rest of your reply stays normal prose so the user can read your reasoning before clicking Add.

WHEN THE DISCUSSION CALLS FOR THEMES:
You may also propose chapter-level themes the writing AI will use to anchor its prose (the writer + research agents pull these into the brief under THEMES TO LAND). Use this exact tag and JSON shape:

  <suggest_theme>{{"title":"short theme label","description":"what the theme is about (1-2 sentences)","statement":"the argument the chapter makes (one sentence — e.g. 'loyalty has a cost when the cost is named')","motifs":["recurring image","phrase","object"]}}</suggest_theme>

Rules for theme suggestions:
- Suggest themes when the user asks "what is this chapter about underneath?", "what should this chapter say?", "give me themes to land", "what theme connects these beats?", or when reviewing the chapter outline reveals a thematic thread that's not yet named.
- ``title`` is a short label (2-5 words) that becomes the entry in the chapter's themes field.
- ``statement`` is the chapter's argument — what point the events make. Specific over generic ("Inheritance survives refusal" beats "Family is hard").
- ``motifs`` (optional) are the recurring images/phrases/objects that signal the theme on the page.
- Themes should grow out of the events / characters / tensions actually in scope for this chapter. Don't invent themes the chapter has no chance to land.
- Cap at 3 theme suggestions per reply (themes earn their space; don't dilute by stacking five).
- Same inline placement as event blocks — the rest of your reply explains your reasoning.

Respond conversationally otherwise — quotes from the project, references to specific characters or plot events by name, and concrete actionable advice the user can adopt or refine."""

        self._set_processing(True)

        # Continuation accounting — if the AI cuts off mid
        # <suggest_event>, we re-prompt it to finish, up to
        # ``_MAX_CONTINUATIONS`` times. Each round's text is
        # accumulated into ``accumulated`` so the final cleaned
        # reply contains every block the model produced across
        # rounds. We stash this state on a per-request key so a
        # rapid second click doesn't tangle two continuations.
        request_state = {
            'accumulated': '',
            'rounds': 0,
            'max_rounds': self._MAX_CONTINUATIONS,
            'context_for_continuation': context,
        }

        def finish(reply_text: str):
            """Final-render path: parse, append to chat, render cards."""
            self._set_processing(False)
            if not reply_text:
                self._append_to_chat(
                    "error", "Failed to get response.")
                return
            # Strip event suggestions first, then theme suggestions
            # from the same reply so the user-visible text never
            # contains either tag.
            cleaned, event_suggestions = _extract_event_suggestions(
                reply_text)
            cleaned, theme_suggestions = _extract_theme_suggestions(
                cleaned)
            if cleaned:
                self._append_to_chat("assistant", cleaned)
            self._ai_history.append({
                "role": "assistant",
                "content": cleaned or reply_text,
            })
            for s in event_suggestions:
                self._add_event_suggestion_card(s)
            for s in theme_suggestions:
                self._add_theme_suggestion_card(s)

        def on_response(response: str):
            print(f"\n[ChapterPlanner] on_response: "
                  f"len={len(response) if response else 0}")
            if not response:
                finish('')
                return
            request_state['accumulated'] += response
            full = request_state['accumulated']
            # If the model left ANY unclosed suggestion tag (event or
            # theme), loop a continuation request — but cap rounds so
            # a perpetually broken response can't spin forever.
            if ((_response_has_unclosed_suggest_event(full)
                 or _response_has_unclosed_suggest_theme(full))
                    and request_state['rounds']
                        < request_state['max_rounds']):
                request_state['rounds'] += 1
                print(f"[ChapterPlanner] response cut off mid-"
                      f"suggestion — requesting continuation "
                      f"(round {request_state['rounds']}/"
                      f"{request_state['max_rounds']})")
                # Show the user we're still working so a long
                # multi-round continuation doesn't look frozen.
                self._append_to_chat(
                    "system",
                    f"(response was cut off — fetching the rest, "
                    f"round {request_state['rounds']}…)")
                cont_prompt = _truncation_continuation_prompt(full)
                self._run_ai_request(
                    cont_prompt,
                    request_state['context_for_continuation'],
                    on_response)
                return
            finish(full)

        self._run_ai_request(prompt, context, on_response)

    # Cap on continuation rounds. 3 is generous — most truncations
    # finish in 1 extra round; the cap exists so a model that
    # genuinely can't close the block (e.g. local model with a
    # too-tight max_tokens setting) doesn't spin forever.
    _MAX_CONTINUATIONS = 3

    # ── AI-conversation maintenance ──────────────────────────

    def _clear_ai_conversation(self):
        """Wipe the visible chat + the tracked history.

        Doesn't touch the chapter's planning data. Suggestion cards
        already added to the panel are dropped too — the user can
        re-ask if they wanted them back.
        """
        self.chat_history.clear()
        self._ai_history = []
        self._ai_history_summary = ""
        self._clear_event_suggestion_cards()

    def _clear_event_suggestion_cards(self):
        """Drop every suggestion card from the panel.

        Called from ``_clear_ai_conversation`` (full reset) AND from
        ``_send_chat_message`` (drop stale cards from the previous
        response when a new prompt is sent). Doesn't touch the chat
        history widget or the conversation history list.
        """
        if not hasattr(self, '_event_suggestions_layout'):
            return
        while self._event_suggestions_layout.count() > 0:
            item = self._event_suggestions_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    # Compaction thresholds — when ``_ai_history`` grows past these,
    # the older window collapses into ``_ai_history_summary`` which
    # ships in the prompt as a separate context key. Recent turns
    # stay verbatim so back-and-forth keeps full nuance.
    _COMPACT_KEEP_RECENT_TURNS = 6
    _COMPACT_TRIGGER_TURNS = 12
    _COMPACT_MAX_CHARS = 12000

    def _maybe_compact_ai_history(self):
        """Trim ``_ai_history`` if it's grown past the budget.

        Heuristic compaction — questions kept verbatim (capped),
        AI replies squeezed to first ~200 + last ~100 chars so
        framing + conclusion both survive. Free + instant; the
        recent-window stays intact for full nuance.
        """
        n = len(self._ai_history)
        total_chars = sum(
            len(t.get('content') or '')
            for t in self._ai_history)
        if (n <= self._COMPACT_TRIGGER_TURNS
                and total_chars <= self._COMPACT_MAX_CHARS):
            return
        cutoff = max(0, n - self._COMPACT_KEEP_RECENT_TURNS)
        if cutoff <= 0:
            return
        old_turns = self._ai_history[:cutoff]
        self._ai_history = self._ai_history[cutoff:]
        summary_lines = []
        for turn in old_turns:
            role = turn.get('role', '?')
            content = (turn.get('content') or '').strip()
            if not content:
                continue
            if role == 'user':
                summary_lines.append(
                    f"Q: {content[:240]}"
                    + ("…" if len(content) > 240 else ""))
            else:
                if len(content) <= 320:
                    body = content
                else:
                    body = (f"{content[:200].rstrip()} "
                            f"… {content[-100:].lstrip()}")
                summary_lines.append(f"A: {body}")
        if summary_lines:
            new_chunk = "\n".join(summary_lines)
            if self._ai_history_summary:
                self._ai_history_summary = (
                    f"{self._ai_history_summary}\n{new_chunk}")
            else:
                self._ai_history_summary = new_chunk
            # Cap cumulative summary so it doesn't grow unbounded.
            if len(self._ai_history_summary) > 4000:
                self._ai_history_summary = (
                    "…[older context trimmed]…\n"
                    + self._ai_history_summary[-4000:])
            print(f"[ChapterPlanner] compacted "
                  f"{len(old_turns)} older turns into a "
                  f"{len(new_chunk)}-char summary "
                  f"({len(self._ai_history)} turns retained)")

    def _add_event_suggestion_card(self, suggestion: dict):
        """Render an Add / Skip card for one <suggest_event>.

        ``suggestion`` is ``{"data": <dict|None>, "raw": <str>}``.
        ``data`` may be None when the AI's JSON failed to parse —
        in that case the card surfaces the raw text + disables Add
        so the user can copy/edit instead.
        """
        from PyQt6.QtWidgets import QHBoxLayout, QFrame
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #f0f9ff; "
            "border: 1px solid #bfdbfe; border-radius: 6px; }")
        v = QVBoxLayout(card)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(4)

        kind_label = QLabel(
            "<span style='background:#dbeafe;color:#1d4ed8;"
            "padding:1px 6px;border-radius:3px;font-size:10px;"
            "font-weight:600;'>+ EVENT</span> suggestion")
        kind_label.setStyleSheet("font-size: 11px;")
        v.addWidget(kind_label)

        data = suggestion.get('data')
        if data:
            text = (data.get('text') or '(unnamed beat)').strip()
            description = (data.get('description') or '').strip()
            stage = (data.get('stage') or '').lower()
            arc = data.get('arc_position', '?')
            why = (data.get('why') or '').strip()
            badge_bits = []
            if stage in _VALID_EVENT_STAGES:
                badge_bits.append(stage)
            if isinstance(arc, (int, float)):
                badge_bits.append(f"arc {int(arc)}")
            badge = (f" <span style='color:#6b7280;font-size:10px;'>"
                     f"({' • '.join(badge_bits)})</span>"
                     if badge_bits else "")
            summary_html = (
                f"<span style='font-size:13px;'>"
                f"<b>{self._html_escape(text)}</b>{badge}</span>")
            if description:
                summary_html += (
                    f"<br/><span style='color:#475569;font-size:11px;'>"
                    f"{self._html_escape(description)}</span>")
            if why:
                summary_html += (
                    f"<br/><span style='color:#9ca3af;"
                    f"font-size:10px;font-style:italic;'>"
                    f"why: {self._html_escape(why)}</span>")
            summary = QLabel(summary_html)
            summary.setWordWrap(True)
            summary.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            v.addWidget(summary)
        else:
            err = QLabel(
                "<i>(couldn't parse the AI's suggestion JSON; raw "
                "text below — copy if you'd like to add it manually)"
                "</i>")
            err.setStyleSheet("color: #b91c1c; font-size: 11px;")
            err.setWordWrap(True)
            v.addWidget(err)
            raw = QLabel(
                f"<pre style='font-size:10px;color:#374151;"
                f"white-space:pre-wrap;'>"
                f"{self._html_escape(suggestion.get('raw', ''))}"
                f"</pre>")
            raw.setWordWrap(True)
            v.addWidget(raw)

        action_row_w = QWidget()
        action_row = QHBoxLayout(action_row_w)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(6)
        action_row.addStretch()

        skip_btn = QPushButton("✕ Skip")
        skip_btn.setStyleSheet(
            "QPushButton { padding: 4px 12px; font-size: 11px; "
            " border: 1px solid #d1d5db; border-radius: 4px; "
            " background: white; color: #374151; }"
            "QPushButton:hover { border-color: #6b7280; }")
        action_row.addWidget(skip_btn)

        add_btn = QPushButton("➕ Add to chapter")
        add_btn.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; "
            " padding: 4px 14px; border-radius: 4px; font-size: 11px;"
            " font-weight: 600; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
            "QPushButton:disabled { background-color: #93c5fd; }")
        add_btn.setEnabled(bool(data))
        if not data:
            add_btn.setToolTip(
                "Can't add — the AI's JSON didn't parse.")
        action_row.addWidget(add_btn)
        v.addWidget(action_row_w)

        def _replace_with_banner(html: str, color: str):
            banner = QLabel(html)
            banner.setStyleSheet(
                f"color: {color}; font-size: 11px; "
                f"padding: 2px 0;")
            banner.setWordWrap(True)
            v.replaceWidget(action_row_w, banner)
            add_btn.setEnabled(False)
            skip_btn.setEnabled(False)
            action_row_w.hide()
            action_row_w.deleteLater()

        def on_add():
            if not data:
                return
            stage = (data.get('stage') or 'rising').lower()
            if stage not in _VALID_EVENT_STAGES:
                stage = 'rising'
            try:
                arc = max(0, min(100, int(
                    data.get('arc_position', -1))))
            except Exception:
                arc = -1
            text = (data.get('text') or '').strip()
            if not text:
                _replace_with_banner(
                    "✗ Skipped: beat name was empty.",
                    "#b91c1c")
                return
            try:
                self._add_event_item(
                    text=text,
                    description=(
                        data.get('description') or '').strip(),
                    completed=False,
                    stage=stage,
                    arc_position=arc,
                )
                _replace_with_banner(
                    f"✓ <b>Added</b> — "
                    f"{self._html_escape(text)}",
                    "#15803d")
            except Exception as e:
                _replace_with_banner(
                    f"✗ Couldn't add — {self._html_escape(str(e))}",
                    "#b91c1c")

        def on_skip():
            _replace_with_banner("— Skipped —", "#6b7280")

        add_btn.clicked.connect(on_add)
        skip_btn.clicked.connect(on_skip)
        self._event_suggestions_layout.addWidget(card)

    def _add_theme_suggestion_card(self, suggestion: dict):
        """Render an Add / Skip card for one <suggest_theme>.

        ``suggestion['data']`` is ``{title: str, description: str,
        statement: str, motifs: [str]}`` (all but ``title`` optional).
        Accepting appends the title to the chapter's themes field
        (comma-separated, deduped). The fuller fields show in the
        card so the user can copy them into the project's structured
        Theme list manually if they want a richer record.
        """
        from PyQt6.QtWidgets import QHBoxLayout, QFrame
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #fdf4ff; "
            "border: 1px solid #f5d0fe; border-radius: 6px; }")
        v = QVBoxLayout(card)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(4)

        kind_label = QLabel(
            "<span style='background:#f3e8ff;color:#7e22ce;"
            "padding:1px 6px;border-radius:3px;font-size:10px;"
            "font-weight:600;'>+ THEME</span> suggestion")
        kind_label.setStyleSheet("font-size: 11px;")
        v.addWidget(kind_label)

        data = suggestion.get('data')
        if data:
            title = (data.get('title') or '(unnamed theme)').strip()
            description = (data.get('description') or '').strip()
            statement = (data.get('statement') or '').strip()
            motifs = data.get('motifs') or []
            summary_html = (
                f"<span style='font-size:13px;'>"
                f"<b>{self._html_escape(title)}</b></span>")
            if description:
                summary_html += (
                    f"<br/><span style='color:#475569;font-size:11px;'>"
                    f"{self._html_escape(description)}</span>")
            if statement:
                summary_html += (
                    f"<br/><span style='color:#7e22ce;font-size:11px;"
                    f"font-style:italic;'>"
                    f"statement: {self._html_escape(statement)}</span>")
            if isinstance(motifs, list) and motifs:
                motif_text = ", ".join(
                    str(m) for m in motifs[:6] if m)
                if motif_text:
                    summary_html += (
                        f"<br/><span style='color:#9ca3af;"
                        f"font-size:10px;'>"
                        f"motifs: {self._html_escape(motif_text)}</span>")
            summary = QLabel(summary_html)
            summary.setWordWrap(True)
            summary.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            v.addWidget(summary)
        else:
            err = QLabel(
                "<i>(couldn't parse the AI's theme JSON; raw text "
                "below — copy if you'd like to add it manually)</i>")
            err.setStyleSheet("color: #b91c1c; font-size: 11px;")
            err.setWordWrap(True)
            v.addWidget(err)
            raw = QLabel(
                f"<pre style='font-size:10px;color:#374151;"
                f"white-space:pre-wrap;'>"
                f"{self._html_escape(suggestion.get('raw', ''))}"
                f"</pre>")
            raw.setWordWrap(True)
            v.addWidget(raw)

        action_row_w = QWidget()
        action_row = QHBoxLayout(action_row_w)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(6)
        action_row.addStretch()

        skip_btn = QPushButton("✕ Skip")
        skip_btn.setStyleSheet(
            "QPushButton { padding: 4px 12px; font-size: 11px; "
            " border: 1px solid #d1d5db; border-radius: 4px; "
            " background: white; color: #374151; }"
            "QPushButton:hover { border-color: #6b7280; }")
        action_row.addWidget(skip_btn)

        add_btn = QPushButton("➕ Add to chapter")
        add_btn.setStyleSheet(
            "QPushButton { background-color: #9333ea; color: white; "
            " padding: 4px 14px; border-radius: 4px; font-size: 11px;"
            " font-weight: 600; }"
            "QPushButton:hover { background-color: #7e22ce; }"
            "QPushButton:disabled { background-color: #d8b4fe; }")
        add_btn.setEnabled(bool(data))
        if not data:
            add_btn.setToolTip(
                "Can't add — the AI's JSON didn't parse.")
        action_row.addWidget(add_btn)
        v.addWidget(action_row_w)

        def _replace_with_banner(html: str, color: str):
            banner = QLabel(html)
            banner.setStyleSheet(
                f"color: {color}; font-size: 11px; padding: 2px 0;")
            banner.setWordWrap(True)
            v.replaceWidget(action_row_w, banner)
            add_btn.setEnabled(False)
            skip_btn.setEnabled(False)
            action_row_w.hide()
            action_row_w.deleteLater()

        def on_add():
            if not data:
                return
            title = (data.get('title') or '').strip()
            if not title:
                _replace_with_banner(
                    "✗ Skipped: theme title was empty.", "#b91c1c")
                return
            # Append to the comma-separated themes_edit field, deduped
            # (case-insensitive). The textChanged signal triggers
            # _on_plan_changed → save logic, so this persists.
            try:
                current = (self.themes_edit.text() or "").strip()
                existing = [t.strip() for t in current.split(",")
                            if t.strip()]
                if title.lower() in {t.lower() for t in existing}:
                    _replace_with_banner(
                        f"✓ Already in chapter: "
                        f"<b>{self._html_escape(title)}</b>",
                        "#15803d")
                    return
                existing.append(title)
                self.themes_edit.setText(", ".join(existing))
                _replace_with_banner(
                    f"✓ <b>Added theme</b> — "
                    f"{self._html_escape(title)}",
                    "#15803d")
            except Exception as e:
                _replace_with_banner(
                    f"✗ Couldn't add — "
                    f"{self._html_escape(str(e))}",
                    "#b91c1c")

        def on_skip():
            _replace_with_banner("— Skipped —", "#6b7280")

        add_btn.clicked.connect(on_add)
        skip_btn.clicked.connect(on_skip)
        self._event_suggestions_layout.addWidget(card)

    @staticmethod
    def _html_escape(text: str) -> str:
        return (str(text).replace("&", "&amp;")
                          .replace("<", "&lt;")
                          .replace(">", "&gt;")
                          .replace("\n", "<br/>"))

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

        # Truncate chapter content smartly (keep beginning and end if too long)
        max_content_length = 6000
        if len(chapter_content) > max_content_length:
            mid_point = max_content_length // 2
            chapter_preview = (
                chapter_content[:mid_point] +
                f"\n\n... [middle section omitted, {len(chapter_content) - max_content_length} chars] ...\n\n" +
                chapter_content[-mid_point:]
            )
        else:
            chapter_preview = chapter_content

        prompt = f"""TASK: Analyze how well the chapter draft follows the planned outline.

PLANNED EVENTS:
{plan}

CHAPTER DRAFT:
{chapter_preview}

ANALYSIS REQUESTED:
1. **Events Successfully Written**: Which planned events are present in the draft?
2. **Missing Events**: Which planned events haven't been addressed yet?
3. **Alignment Issues**: Any scenes that deviate from the plan?
4. **Suggestions**: How to improve alignment with the outline?

Provide specific, constructive feedback."""

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
        """Run an AI request in a background thread with smart context management."""
        # Store callback and connect signal (will be queued automatically for cross-thread)
        self._current_callback = callback
        try:
            # Disconnect any existing connection first
            self._ai_response_ready.disconnect(self._handle_ai_response)
        except:
            pass  # Not connected yet
        self._ai_response_ready.connect(self._handle_ai_response)

        # Capture the chapter's own context BEFORE the worker thread
        # runs — Qt widgets aren't thread-safe to read from worker
        # threads. We snapshot now and hand the resulting string
        # block to the worker.
        chapter_block = self._collect_chapter_context_block()

        def run():
            try:
                # Build context with intelligent truncation
                context_parts = []

                # Chapter-specific signals FIRST so the model anchors
                # to the actual chapter content (prose + description +
                # planning details) before considering broader project
                # context. The previous version put project context at
                # the top and dropped chapter prose entirely — the AI
                # then generated arc beats detached from what the
                # writer had actually written.
                if chapter_block:
                    context_parts.append(chapter_block)

                # Add plot (most important, keep full)
                if context.get('plot'):
                    context_parts.append(f"PLOT OUTLINE:\n{context['plot']}")

                # RAG-focused blocks first (high-signal subset for
                # THIS question) so the model reads them BEFORE the
                # broader rosters and reaches for the right items.
                if context.get('rag_focused_plot_scaffold'):
                    context_parts.append(
                        "PLOT SCAFFOLDING relevant to this question "
                        "(themes / tensions / promises / events):\n"
                        + context['rag_focused_plot_scaffold'][:2000])
                if context.get('rag_focused_characters'):
                    context_parts.append(
                        "CHARACTERS most relevant to this question:\n"
                        + context['rag_focused_characters'][:2500])
                if context.get('rag_focused_worldbuilding'):
                    context_parts.append(
                        "WORLDBUILDING most relevant to this "
                        "question:\n"
                        + context['rag_focused_worldbuilding'][:2800])
                if context.get('rag_focused_subplots'):
                    context_parts.append(
                        "SUBPLOTS most relevant to this question:\n"
                        + context['rag_focused_subplots'][:1600])

                # Add characters (broader roster — limit to avoid
                # context overflow, bumped from 1500 → 3000 since
                # the RAG-focused block above already names the
                # relevant ones).
                if context.get('characters'):
                    char_text = context['characters']
                    if len(char_text) > 3000:
                        char_text = char_text[:3000] + "\n... (more characters not shown)"
                    context_parts.append(
                        f"MAIN CHARACTERS (full roster):\n{char_text}")

                # Add worldbuilding (broader set, same bump).
                if context.get('worldbuilding'):
                    wb_text = context['worldbuilding']
                    if len(wb_text) > 3000:
                        wb_text = wb_text[:3000] + "\n... (more worldbuilding details available)"
                    context_parts.append(
                        f"WORLDBUILDING (full set):\n{wb_text}")

                # Add current outline (important for continuity).
                # The model needs this to know which beats already
                # exist so it can place suggested events sensibly on
                # the arc and avoid duplicating beats.
                if context.get('current_plan'):
                    plan_text = context['current_plan']
                    if len(plan_text) > 2000:
                        plan_text = plan_text[:2000] + "\n... (outline continues)"
                    context_parts.append(f"CURRENT CHAPTER OUTLINE:\n{plan_text}")

                # Compacted older turns from this conversation —
                # see _maybe_compact_ai_history.
                if context.get('planner_history_summary'):
                    context_parts.append(
                        f"EARLIER IN THIS CONVERSATION (compacted):\n"
                        f"{context['planner_history_summary']}")

                # Recent verbatim turns (kept short — the live
                # message is in the prompt below).
                recent = context.get('planner_recent_turns') or []
                if recent:
                    turn_lines = []
                    for t in recent[-6:]:
                        role = (t.get('role') or '?').upper()
                        body = (t.get('content') or '').strip()
                        if not body:
                            continue
                        if len(body) > 600:
                            body = body[:600].rstrip() + " …"
                        turn_lines.append(f"{role}: {body}")
                    if turn_lines:
                        context_parts.append(
                            "RECENT CONVERSATION TURNS:\n"
                            + "\n\n".join(turn_lines))

                # Build full prompt with context
                full_context = "\n\n".join(context_parts)

                if full_context:
                    # Estimate token count (rough: 1 token ≈ 4 chars)
                    estimated_tokens = len(full_context) // 4
                    print(f"Context size: ~{estimated_tokens} tokens ({len(full_context)} chars)")

                    full_prompt = f"{full_context}\n\n{'=' * 60}\n\n{prompt}"
                else:
                    full_prompt = prompt

                # Use configured model from settings (no model selection needed)
                # The handler in manuscript_editor.py will route to appropriate model
                result = self._ai_handler(full_prompt, "Auto")

                print(f"\n[ChapterPlanner] AI request completed in background thread")
                print(f"[ChapterPlanner] Result length: {len(result) if result else 0} chars")
                print(f"[ChapterPlanner] Result preview: {repr(result[:100]) if result else 'None'}")

                # Clean up response: remove echoed prompt/context
                if result:
                    result = self._extract_response_only(result, full_prompt, prompt)

                print(f"[ChapterPlanner] Cleaned result length: {len(result) if result else 0} chars")
                print(f"[ChapterPlanner] Emitting signal to main thread...\n")

                # Emit signal to deliver result to main thread (thread-safe)
                self._ai_response_ready.emit(result)

            except Exception as e:
                print(f"AI request error: {e}")
                import traceback
                traceback.print_exc()
                # Emit None to trigger error handling
                self._ai_response_ready.emit(None)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def _handle_ai_response(self, result):
        """Handle AI response on main thread (slot for _ai_response_ready signal)."""
        print(f"\n[ChapterPlanner] _handle_ai_response called on main thread!")
        print(f"[ChapterPlanner] Result: {repr(result[:100]) if result else 'None'}")

        # Disconnect signal after use
        try:
            self._ai_response_ready.disconnect(self._handle_ai_response)
        except:
            pass  # Already disconnected

        # Capture + clear the callback BEFORE invoking. The callback
        # may re-enter ``_run_ai_request`` (e.g. our continuation
        # loop when a <suggest_event> block was cut off) which
        # writes a fresh callback to ``self._current_callback`` —
        # if we cleared after invoking, we'd overwrite the
        # newly-installed continuation callback back to None and
        # drop the re-entrant response on the floor.
        cb = self._current_callback
        self._current_callback = None
        if cb:
            print(f"[ChapterPlanner] Invoking callback...")
            cb(result)
        else:
            print(f"[ChapterPlanner] ERROR: No callback stored!")

    def clear_chat(self):
        """Clear the chat history."""
        self.chat_history.clear()

    def _extract_response_only(self, full_response: str, full_prompt: str, user_prompt: str) -> str:
        """Extract only the AI's response, removing any echoed prompt/context.

        Args:
            full_response: Complete response from AI (may include echoed input)
            full_prompt: Full prompt sent to AI (context + user prompt)
            user_prompt: Just the user's prompt portion

        Returns:
            Cleaned response with only the AI's actual answer
        """
        if not full_response:
            return full_response

        # Strategy 1: Look for common separator patterns that indicate response start
        # Many models use patterns like "ANALYSIS:", "RESPONSE:", "ANSWER:", etc.
        separators = [
            "ANALYSIS REQUESTED:",
            "ANALYSIS:",
            "RESPONSE:",
            "ANSWER:",
            "SUGGESTIONS:",
            "TASK:",
            "\n\n" + "=" * 60 + "\n\n",  # Our own separator
        ]

        response = full_response

        # Try to find where the actual response starts (after separators)
        for sep in separators:
            if sep in response:
                parts = response.split(sep, 1)
                if len(parts) > 1:
                    # Keep everything after the separator
                    response = parts[1].strip()

        # Strategy 2: If response starts with the context markers, skip them
        context_markers = [
            "PLOT OUTLINE:",
            "MAIN CHARACTERS:",
            "WORLDBUILDING:",
            "CURRENT CHAPTER OUTLINE:",
            "PLANNED EVENTS:",
            "CHAPTER DRAFT:",
            "USER QUESTION:",
            "INSTRUCTIONS:",
        ]

        lines = response.split('\n')
        start_idx = 0

        # Skip lines that look like echoed context
        for i, line in enumerate(lines):
            stripped = line.strip()

            # Skip empty lines
            if not stripped:
                continue

            # Check if this line is a context marker
            is_marker = any(stripped.startswith(marker) for marker in context_markers)
            if is_marker:
                continue  # Skip this line

            # Check if line looks like part of echoed context (all caps heading)
            if stripped.isupper() and len(stripped) < 50 and ':' in stripped:
                continue  # Likely a heading from context

            # Check if it's a separator line (===, ---, etc.)
            if all(c in '=-_*' for c in stripped) and len(stripped) > 10:
                continue

            # If we get here, this looks like actual content
            start_idx = i
            break

        # Reconstruct response from first real content line
        if start_idx > 0:
            response = '\n'.join(lines[start_idx:]).strip()

        return response
