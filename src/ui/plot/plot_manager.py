"""Plot manager with Freytag pyramid, events, and subplots."""

from typing import List
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QLabel, QTabWidget, QSplitter, QListWidgetItem, QInputDialog,
    QTextEdit, QGroupBox, QDialog, QDialogButtonBox, QLineEdit, QFormLayout,
    QScrollArea, QFrame, QToolButton
)
from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont

from src.models.project import FreytagPyramid, PlotEvent, Subplot
from src.ui.plot.freytag_pyramid_visual import FreytagPyramidVisual
from src.ui.plot.plot_event_editor import PlotEventEditor


class CollapsibleSection(QWidget):
    """A collapsible section widget with a toggle button."""

    def __init__(self, title: str = "", parent=None):
        """Initialize collapsible section."""
        super().__init__(parent)
        self.is_collapsed = False

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header with toggle button
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background-color: #f3f4f6;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 4px;
            }
            QFrame:hover {
                background-color: #e5e7eb;
            }
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(8, 4, 8, 4)

        # Toggle button
        self.toggle_btn = QToolButton()
        self.toggle_btn.setStyleSheet("QToolButton { border: none; background: transparent; }")
        self.toggle_btn.setText("▼")
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.clicked.connect(self.toggle)
        header_layout.addWidget(self.toggle_btn)

        # Title label
        self.title_label = QLabel(title)
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        self.title_label.setFont(font)
        header_layout.addWidget(self.title_label)

        header_layout.addStretch()

        main_layout.addWidget(header_frame)

        # Content area
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 8, 0, 8)

        main_layout.addWidget(self.content_widget)

    def toggle(self):
        """Toggle the collapsed state."""
        self.is_collapsed = not self.is_collapsed

        if self.is_collapsed:
            self.toggle_btn.setText("▶")
            self.content_widget.hide()
        else:
            self.toggle_btn.setText("▼")
            self.content_widget.show()

    def set_title(self, title: str):
        """Set the section title."""
        self.title_label.setText(title)

    def add_widget(self, widget: QWidget):
        """Add a widget to the content area."""
        self.content_layout.addWidget(widget)

    def add_layout(self, layout):
        """Add a layout to the content area."""
        self.content_layout.addLayout(layout)


class SubplotEditor(QDialog):
    """Dialog for editing a subplot."""

    def __init__(self, subplot: Subplot = None, parent=None):
        """Initialize subplot editor."""
        super().__init__(parent)
        self.subplot = subplot or Subplot(
            id="",
            title="",
            description="",
            connection_to_main="",
            related_characters=[],
            events=[],
            status="active"
        )
        self._init_ui()
        if subplot:
            self._load_subplot()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Subplot Editor")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        main_layout = QVBoxLayout(self)

        # Create scroll area for form content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Subplot title")
        form_layout.addRow("Title:*", self.title_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Describe this subplot...")
        self.description_edit.setMaximumHeight(100)
        form_layout.addRow("Description:", self.description_edit)

        self.connection_edit = QTextEdit()
        self.connection_edit.setPlaceholderText("How does this subplot connect to the main plot?")
        self.connection_edit.setMaximumHeight(80)
        form_layout.addRow("Connection to Main Plot:", self.connection_edit)

        self.characters_edit = QTextEdit()
        self.characters_edit.setPlaceholderText("Character names (one per line)")
        self.characters_edit.setMaximumHeight(80)
        form_layout.addRow("Related Characters:", self.characters_edit)

        # Set form widget to scroll area
        scroll_area.setWidget(form_widget)
        main_layout.addWidget(scroll_area)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def _load_subplot(self):
        """Load subplot data."""
        self.title_edit.setText(self.subplot.title)
        self.description_edit.setPlainText(self.subplot.description)
        self.connection_edit.setPlainText(self.subplot.connection_to_main)

        if self.subplot.related_characters:
            self.characters_edit.setPlainText("\n".join(self.subplot.related_characters))

    def _save(self):
        """Save subplot."""
        title = self.title_edit.text().strip()
        if not title:
            return

        if not self.subplot.id:
            import uuid
            self.subplot.id = str(uuid.uuid4())

        self.subplot.title = title
        self.subplot.description = self.description_edit.toPlainText().strip()
        self.subplot.connection_to_main = self.connection_edit.toPlainText().strip()

        char_text = self.characters_edit.toPlainText().strip()
        self.subplot.related_characters = [c.strip() for c in char_text.split("\n") if c.strip()]

        self.accept()

    def get_subplot(self) -> Subplot:
        """Get the edited subplot."""
        return self.subplot


class PlotManagerWidget(QWidget):
    """Widget for managing plot structure with events and subplots."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize plot manager."""
        super().__init__()
        self.freytag_pyramid = FreytagPyramid()
        self.subplots: List[Subplot] = []
        self.available_characters: List[str] = []
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        # Main layout with scroll area
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create scroll area for all content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Content widget inside scroll area
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Visual pyramid at top - collapsible
        pyramid_section = CollapsibleSection("📊 Freytag's Pyramid")
        self.pyramid_visual = FreytagPyramidVisual()
        pyramid_section.add_widget(self.pyramid_visual)

        layout.addWidget(pyramid_section)

        # Tabs for events and subplots
        tabs = QTabWidget()

        # Events tab
        events_tab = self._create_events_tab()
        tabs.addTab(events_tab, "📍 Plot Events")

        # Subplots tab
        subplots_tab = self._create_subplots_tab()
        tabs.addTab(subplots_tab, "🔀 Subplots")

        layout.addWidget(tabs)

        # Set content widget to scroll area and add to main layout
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

    def _create_events_tab(self) -> QWidget:
        """Create events management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Header
        header = QHBoxLayout()
        title = QLabel("Plot Events")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        header.addWidget(title)

        header.addStretch()

        help_text = QLabel("Manage key events in your story's dramatic structure")
        help_text.setStyleSheet("font-size: 11px; color: #6b7280;")
        header.addWidget(help_text)

        layout.addLayout(header)

        # Toolbar
        toolbar = QHBoxLayout()

        add_btn = QPushButton("➕ Add Event")
        add_btn.clicked.connect(self._add_event)
        toolbar.addWidget(add_btn)

        self.edit_event_btn = QPushButton("✏️ Edit")
        self.edit_event_btn.clicked.connect(self._edit_event)
        self.edit_event_btn.setEnabled(False)
        toolbar.addWidget(self.edit_event_btn)

        self.remove_event_btn = QPushButton("🗑️ Remove")
        self.remove_event_btn.clicked.connect(self._remove_event)
        self.remove_event_btn.setEnabled(False)
        toolbar.addWidget(self.remove_event_btn)

        toolbar.addSeparator = QFrame()
        toolbar.addSeparator.setFrameShape(QFrame.Shape.VLine)
        toolbar.addWidget(toolbar.addSeparator)

        self.move_event_up_btn = QPushButton("⬆ Move Up")
        self.move_event_up_btn.clicked.connect(self._move_event_up)
        self.move_event_up_btn.setEnabled(False)
        toolbar.addWidget(self.move_event_up_btn)

        self.move_event_down_btn = QPushButton("⬇ Move Down")
        self.move_event_down_btn.clicked.connect(self._move_event_down)
        self.move_event_down_btn.setEnabled(False)
        toolbar.addWidget(self.move_event_down_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Event list
        self.event_list = QListWidget()
        self.event_list.itemSelectionChanged.connect(self._on_event_selection_changed)
        self.event_list.itemDoubleClicked.connect(self._edit_event)
        layout.addWidget(self.event_list)

        return widget

    def _create_subplots_tab(self) -> QWidget:
        """Create subplots management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Header
        header = QHBoxLayout()
        title = QLabel("Subplots")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        header.addWidget(title)

        header.addStretch()

        help_text = QLabel("Secondary storylines tied to the main plot")
        help_text.setStyleSheet("font-size: 11px; color: #6b7280;")
        header.addWidget(help_text)

        layout.addLayout(header)

        # Toolbar
        toolbar = QHBoxLayout()

        add_subplot_btn = QPushButton("➕ Add Subplot")
        add_subplot_btn.clicked.connect(self._add_subplot)
        toolbar.addWidget(add_subplot_btn)

        self.edit_subplot_btn = QPushButton("✏️ Edit")
        self.edit_subplot_btn.clicked.connect(self._edit_subplot)
        self.edit_subplot_btn.setEnabled(False)
        toolbar.addWidget(self.edit_subplot_btn)

        self.remove_subplot_btn = QPushButton("🗑️ Remove")
        self.remove_subplot_btn.clicked.connect(self._remove_subplot)
        self.remove_subplot_btn.setEnabled(False)
        toolbar.addWidget(self.remove_subplot_btn)

        toolbar_separator = QFrame()
        toolbar_separator.setFrameShape(QFrame.Shape.VLine)
        toolbar.addWidget(toolbar_separator)

        self.move_subplot_up_btn = QPushButton("⬆ Move Up")
        self.move_subplot_up_btn.clicked.connect(self._move_subplot_up)
        self.move_subplot_up_btn.setEnabled(False)
        toolbar.addWidget(self.move_subplot_up_btn)

        self.move_subplot_down_btn = QPushButton("⬇ Move Down")
        self.move_subplot_down_btn.clicked.connect(self._move_subplot_down)
        self.move_subplot_down_btn.setEnabled(False)
        toolbar.addWidget(self.move_subplot_down_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Subplot list
        self.subplot_list = QListWidget()
        self.subplot_list.itemSelectionChanged.connect(self._on_subplot_selection_changed)
        self.subplot_list.itemDoubleClicked.connect(self._edit_subplot)
        layout.addWidget(self.subplot_list)

        return widget

    def _add_event(self):
        """Add new plot event."""
        editor = PlotEventEditor(
            available_characters=self.available_characters,
            available_subplots=self.subplots,
            parent=self
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            event = editor.get_event()
            self.freytag_pyramid.events.append(event)
            self._update_event_list()
            self._update_pyramid()
            self.content_changed.emit()

    def _edit_event(self):
        """Edit selected event."""
        items = self.event_list.selectedItems()
        if not items:
            return

        event_id = items[0].data(Qt.ItemDataRole.UserRole)
        event = next((e for e in self.freytag_pyramid.events if e.id == event_id), None)
        if not event:
            return

        editor = PlotEventEditor(
            event=event,
            available_characters=self.available_characters,
            available_subplots=self.subplots,
            parent=self
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_event_list()
            self._update_pyramid()
            self.content_changed.emit()

    def _remove_event(self):
        """Remove selected event."""
        items = self.event_list.selectedItems()
        if not items:
            return

        event_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.freytag_pyramid.events = [e for e in self.freytag_pyramid.events if e.id != event_id]
        self._update_event_list()
        self._update_pyramid()
        self.content_changed.emit()

    def _move_event_up(self):
        """Move selected event up in sort order."""
        items = self.event_list.selectedItems()
        if not items:
            return

        event_id = items[0].data(Qt.ItemDataRole.UserRole)
        event = next((e for e in self.freytag_pyramid.events if e.id == event_id), None)
        if not event or event.sort_order <= 0:
            return

        # Find events in the same stage
        same_stage_events = [e for e in self.freytag_pyramid.events if e.stage == event.stage]
        same_stage_events.sort(key=lambda e: e.sort_order)

        # Find current position
        current_index = next((i for i, e in enumerate(same_stage_events) if e.id == event_id), None)
        if current_index is None or current_index == 0:
            return

        # Swap sort orders
        prev_event = same_stage_events[current_index - 1]
        event.sort_order, prev_event.sort_order = prev_event.sort_order, event.sort_order

        self._update_event_list()
        self._update_pyramid()
        self.content_changed.emit()

        # Re-select the event
        for i in range(self.event_list.count()):
            item = self.event_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == event_id:
                self.event_list.setCurrentItem(item)
                break

    def _move_event_down(self):
        """Move selected event down in sort order."""
        items = self.event_list.selectedItems()
        if not items:
            return

        event_id = items[0].data(Qt.ItemDataRole.UserRole)
        event = next((e for e in self.freytag_pyramid.events if e.id == event_id), None)
        if not event:
            return

        # Find events in the same stage
        same_stage_events = [e for e in self.freytag_pyramid.events if e.stage == event.stage]
        same_stage_events.sort(key=lambda e: e.sort_order)

        # Find current position
        current_index = next((i for i, e in enumerate(same_stage_events) if e.id == event_id), None)
        if current_index is None or current_index >= len(same_stage_events) - 1:
            return

        # Swap sort orders
        next_event = same_stage_events[current_index + 1]
        event.sort_order, next_event.sort_order = next_event.sort_order, event.sort_order

        self._update_event_list()
        self._update_pyramid()
        self.content_changed.emit()

        # Re-select the event
        for i in range(self.event_list.count()):
            item = self.event_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == event_id:
                self.event_list.setCurrentItem(item)
                break

    def _add_subplot(self):
        """Add new subplot."""
        editor = SubplotEditor(parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            subplot = editor.get_subplot()
            self.subplots.append(subplot)
            self._update_subplot_list()
            self.content_changed.emit()

    def _edit_subplot(self):
        """Edit selected subplot."""
        items = self.subplot_list.selectedItems()
        if not items:
            return

        subplot_id = items[0].data(Qt.ItemDataRole.UserRole)
        subplot = next((s for s in self.subplots if s.id == subplot_id), None)
        if not subplot:
            return

        editor = SubplotEditor(subplot=subplot, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_subplot_list()
            self.content_changed.emit()

    def _remove_subplot(self):
        """Remove selected subplot."""
        items = self.subplot_list.selectedItems()
        if not items:
            return

        subplot_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.subplots = [s for s in self.subplots if s.id != subplot_id]
        self._update_subplot_list()
        self.content_changed.emit()

    def _move_subplot_up(self):
        """Move selected subplot up in the list."""
        items = self.subplot_list.selectedItems()
        if not items:
            return

        subplot_id = items[0].data(Qt.ItemDataRole.UserRole)

        # Find current index
        current_index = next((i for i, s in enumerate(self.subplots) if s.id == subplot_id), None)
        if current_index is None or current_index == 0:
            return

        # Swap with previous subplot
        self.subplots[current_index], self.subplots[current_index - 1] = \
            self.subplots[current_index - 1], self.subplots[current_index]

        self._update_subplot_list()
        self.content_changed.emit()

        # Re-select the subplot
        for i in range(self.subplot_list.count()):
            item = self.subplot_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == subplot_id:
                self.subplot_list.setCurrentItem(item)
                break

    def _move_subplot_down(self):
        """Move selected subplot down in the list."""
        items = self.subplot_list.selectedItems()
        if not items:
            return

        subplot_id = items[0].data(Qt.ItemDataRole.UserRole)

        # Find current index
        current_index = next((i for i, s in enumerate(self.subplots) if s.id == subplot_id), None)
        if current_index is None or current_index >= len(self.subplots) - 1:
            return

        # Swap with next subplot
        self.subplots[current_index], self.subplots[current_index + 1] = \
            self.subplots[current_index + 1], self.subplots[current_index]

        self._update_subplot_list()
        self.content_changed.emit()

        # Re-select the subplot
        for i in range(self.subplot_list.count()):
            item = self.subplot_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == subplot_id:
                self.subplot_list.setCurrentItem(item)
                break

    def _update_event_list(self):
        """Update event list display."""
        self.event_list.clear()

        # Sort events by stage and sort_order
        stage_order = {"exposition": 0, "rising_action": 1, "climax": 2, "falling_action": 3, "resolution": 4}
        sorted_events = sorted(
            self.freytag_pyramid.events,
            key=lambda e: (stage_order.get(e.stage, 1), e.sort_order)
        )

        for event in sorted_events:
            stage_names = {
                "exposition": "Exposition",
                "rising_action": "Rising Action",
                "climax": "Climax",
                "falling_action": "Falling Action",
                "resolution": "Resolution"
            }
            stage_display = stage_names.get(event.stage, event.stage)

            item_text = f"{event.title} ({stage_display}, Intensity: {event.intensity})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, event.id)
            self.event_list.addItem(item)

    def _update_subplot_list(self):
        """Update subplot list display."""
        self.subplot_list.clear()

        for subplot in self.subplots:
            status_emoji = "✅" if subplot.status == "resolved" else "🔄" if subplot.status == "active" else "❌"
            item_text = f"{status_emoji} {subplot.title}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, subplot.id)
            self.subplot_list.addItem(item)

    def _update_pyramid(self):
        """Update visual pyramid with events."""
        self.pyramid_visual.set_events(self.freytag_pyramid.events)

    def _on_event_selection_changed(self):
        """Handle event selection change."""
        has_selection = bool(self.event_list.selectedItems())
        self.edit_event_btn.setEnabled(has_selection)
        self.remove_event_btn.setEnabled(has_selection)
        self.move_event_up_btn.setEnabled(has_selection)
        self.move_event_down_btn.setEnabled(has_selection)

    def _on_subplot_selection_changed(self):
        """Handle subplot selection change."""
        has_selection = bool(self.subplot_list.selectedItems())
        self.edit_subplot_btn.setEnabled(has_selection)
        self.remove_subplot_btn.setEnabled(has_selection)
        self.move_subplot_up_btn.setEnabled(has_selection)
        self.move_subplot_down_btn.setEnabled(has_selection)

    def load_plot_data(self, freytag_pyramid: FreytagPyramid, subplots: List[Subplot]):
        """Load plot data.

        Args:
            freytag_pyramid: FreytagPyramid object with events
            subplots: List of Subplot objects
        """
        self.freytag_pyramid = freytag_pyramid
        self.subplots = subplots
        self._update_event_list()
        self._update_subplot_list()
        self._update_pyramid()

    def get_plot_data(self):
        """Get plot data.

        Returns:
            Tuple of (FreytagPyramid, List[Subplot])
        """
        return self.freytag_pyramid, self.subplots

    def set_available_characters(self, characters: List[str]):
        """Set available characters for event association.

        Args:
            characters: List of character names
        """
        self.available_characters = characters
