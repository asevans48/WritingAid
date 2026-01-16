"""Plot manager with Freytag pyramid, events, and subplots."""

from typing import List
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QLabel, QTabWidget, QSplitter, QListWidgetItem, QInputDialog,
    QTextEdit, QGroupBox, QDialog, QDialogButtonBox, QLineEdit, QFormLayout,
    QScrollArea, QFrame, QToolButton, QSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont

from src.models.project import FreytagPyramid, PlotEvent, Subplot, StoryPromise
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
        self.promises: List[StoryPromise] = []
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

        # Act configuration controls
        act_config_layout = QHBoxLayout()
        act_config_layout.addWidget(QLabel("Acts:"))

        self.num_acts_spin = QSpinBox()
        self.num_acts_spin.setMinimum(1)
        self.num_acts_spin.setMaximum(7)
        self.num_acts_spin.setValue(3)
        self.num_acts_spin.setToolTip("Number of acts in your story structure")
        self.num_acts_spin.valueChanged.connect(self._on_num_acts_changed)
        act_config_layout.addWidget(self.num_acts_spin)

        act_config_layout.addSpacing(20)

        edit_acts_btn = QPushButton("Edit Act Names")
        edit_acts_btn.clicked.connect(self._edit_act_names)
        act_config_layout.addWidget(edit_acts_btn)

        act_config_layout.addStretch()

        act_config_widget = QWidget()
        act_config_widget.setLayout(act_config_layout)
        pyramid_section.add_widget(act_config_widget)

        self.pyramid_visual = FreytagPyramidVisual()
        self.pyramid_visual.event_clicked.connect(self._on_pyramid_event_clicked)
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

        # Promises tab
        promises_tab = self._create_promises_tab()
        tabs.addTab(promises_tab, "🤝 Promises")

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
        self.event_list.itemDoubleClicked.connect(self._on_event_list_double_clicked)
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

    def _create_promises_tab(self) -> QWidget:
        """Create promises management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Header
        header = QHBoxLayout()
        title = QLabel("Story Promises")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        header.addWidget(title)

        header.addStretch()

        help_text = QLabel("Commitments to readers about tone, plot, genre, and characters")
        help_text.setStyleSheet("font-size: 11px; color: #6b7280;")
        header.addWidget(help_text)

        layout.addLayout(header)

        # Toolbar
        toolbar = QHBoxLayout()

        add_promise_btn = QPushButton("➕ Add Promise")
        add_promise_btn.clicked.connect(self._add_promise)
        toolbar.addWidget(add_promise_btn)

        self.edit_promise_btn = QPushButton("✏️ Edit")
        self.edit_promise_btn.clicked.connect(self._edit_promise)
        self.edit_promise_btn.setEnabled(False)
        toolbar.addWidget(self.edit_promise_btn)

        self.remove_promise_btn = QPushButton("🗑️ Remove")
        self.remove_promise_btn.clicked.connect(self._remove_promise)
        self.remove_promise_btn.setEnabled(False)
        toolbar.addWidget(self.remove_promise_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Promise type sections
        promise_sections_widget = QWidget()
        promise_sections_layout = QVBoxLayout(promise_sections_widget)
        promise_sections_layout.setContentsMargins(0, 0, 0, 0)

        # Info labels about each type
        type_info = QLabel(
            "<b>Types of promises:</b><br/>"
            "• <b>Tone</b> - Emotional atmosphere (dark, humorous, hopeful)<br/>"
            "• <b>Plot</b> - Story structure expectations (mystery solved, hero wins)<br/>"
            "• <b>Genre</b> - Genre conventions (romance will bloom, justice served)<br/>"
            "• <b>Character</b> - Character arcs and consistency (growth, motivations)"
        )
        type_info.setWordWrap(True)
        type_info.setStyleSheet("background-color: #f3f4f6; padding: 10px; border-radius: 6px; font-size: 11px;")
        promise_sections_layout.addWidget(type_info)

        layout.addWidget(promise_sections_widget)

        # Promise list
        self.promise_list = QListWidget()
        self.promise_list.itemSelectionChanged.connect(self._on_promise_selection_changed)
        self.promise_list.itemDoubleClicked.connect(self._edit_promise)
        layout.addWidget(self.promise_list)

        return widget

    def _add_promise(self):
        """Add new story promise."""
        dialog = PromiseEditor(
            available_characters=self.available_characters,
            parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            promise = dialog.get_promise()
            self.promises.append(promise)
            self._update_promise_list()
            self.content_changed.emit()

    def _edit_promise(self):
        """Edit selected promise."""
        items = self.promise_list.selectedItems()
        if not items:
            return

        promise_id = items[0].data(Qt.ItemDataRole.UserRole)
        promise = next((p for p in self.promises if p.id == promise_id), None)
        if not promise:
            return

        dialog = PromiseEditor(
            promise=promise,
            available_characters=self.available_characters,
            parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._update_promise_list()
            self.content_changed.emit()

    def _remove_promise(self):
        """Remove selected promise."""
        items = self.promise_list.selectedItems()
        if not items:
            return

        promise_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.promises = [p for p in self.promises if p.id != promise_id]
        self._update_promise_list()
        self.content_changed.emit()

    def _on_promise_selection_changed(self):
        """Handle promise selection change."""
        has_selection = bool(self.promise_list.selectedItems())
        self.edit_promise_btn.setEnabled(has_selection)
        self.remove_promise_btn.setEnabled(has_selection)

    def _update_promise_list(self):
        """Update the promise list widget."""
        self.promise_list.clear()

        # Group promises by type
        type_icons = {
            "tone": "🎭",
            "plot": "📖",
            "genre": "📚",
            "character": "👤"
        }

        for promise in self.promises:
            icon = type_icons.get(promise.promise_type, "📝")
            item = QListWidgetItem(f"{icon} [{promise.promise_type.title()}] {promise.title}")
            item.setData(Qt.ItemDataRole.UserRole, promise.id)
            if promise.description:
                item.setToolTip(promise.description)
            self.promise_list.addItem(item)

    def _add_event(self):
        """Add new plot event."""
        editor = PlotEventEditor(
            available_characters=self.available_characters,
            available_subplots=self.subplots,
            num_acts=self.freytag_pyramid.num_acts,
            act_names=self.freytag_pyramid.act_names,
            parent=self
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            event = editor.get_event()

            # Set sort_order to next available value for this act/stage if not explicitly set
            # (default from editor is 0, so we check if there are other events with sort_order >= 0)
            same_group_events = [
                e for e in self.freytag_pyramid.events
                if e.act == event.act and e.stage == event.stage
            ]
            if same_group_events:
                max_sort_order = max(e.sort_order for e in same_group_events)
                # Only auto-increment if the user left it at default (0) and there are existing events
                if event.sort_order == 0:
                    event.sort_order = max_sort_order + 1

            self.freytag_pyramid.events.append(event)
            self._update_event_list()
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
            num_acts=self.freytag_pyramid.num_acts,
            act_names=self.freytag_pyramid.act_names,
            parent=self
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_event_list()
            self.content_changed.emit()

    def _remove_event(self):
        """Remove selected event."""
        items = self.event_list.selectedItems()
        if not items:
            return

        event_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.freytag_pyramid.events = [e for e in self.freytag_pyramid.events if e.id != event_id]
        self._update_event_list()
        self.content_changed.emit()

    def _move_event_up(self):
        """Move selected event up in sort order (within same act and stage)."""
        items = self.event_list.selectedItems()
        if not items:
            return

        event_id = items[0].data(Qt.ItemDataRole.UserRole)
        event = next((e for e in self.freytag_pyramid.events if e.id == event_id), None)
        if not event:
            return

        # Find events in the same act AND stage
        same_group_events = [
            e for e in self.freytag_pyramid.events
            if e.act == event.act and e.stage == event.stage
        ]
        same_group_events.sort(key=lambda e: e.sort_order)

        # Find current position
        current_index = next((i for i, e in enumerate(same_group_events) if e.id == event_id), None)
        if current_index is None or current_index == 0:
            return

        # Swap sort orders with the previous event
        prev_event = same_group_events[current_index - 1]
        event.sort_order, prev_event.sort_order = prev_event.sort_order, event.sort_order

        # If they ended up with the same sort_order (both were 0), fix it
        if event.sort_order == prev_event.sort_order:
            prev_event.sort_order = event.sort_order + 1

        self._update_event_list()
        self.content_changed.emit()

        # Re-select the event
        for i in range(self.event_list.count()):
            item = self.event_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == event_id:
                self.event_list.setCurrentItem(item)
                break

    def _move_event_down(self):
        """Move selected event down in sort order (within same act and stage)."""
        items = self.event_list.selectedItems()
        if not items:
            return

        event_id = items[0].data(Qt.ItemDataRole.UserRole)
        event = next((e for e in self.freytag_pyramid.events if e.id == event_id), None)
        if not event:
            return

        # Find events in the same act AND stage
        same_group_events = [
            e for e in self.freytag_pyramid.events
            if e.act == event.act and e.stage == event.stage
        ]
        same_group_events.sort(key=lambda e: e.sort_order)

        # Find current position
        current_index = next((i for i, e in enumerate(same_group_events) if e.id == event_id), None)
        if current_index is None or current_index >= len(same_group_events) - 1:
            return

        # Swap sort orders with the next event
        next_event = same_group_events[current_index + 1]
        event.sort_order, next_event.sort_order = next_event.sort_order, event.sort_order

        # If they ended up with the same sort_order (both were 0), fix it
        if event.sort_order == next_event.sort_order:
            event.sort_order = next_event.sort_order + 1

        self._update_event_list()
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

    def _update_event_list(self, update_pyramid: bool = True):
        """Update event list display.

        Args:
            update_pyramid: If True, also update the visual pyramid (default True)
        """
        self.event_list.clear()

        # Sort events by act, then stage, then sort_order
        stage_order = {"exposition": 0, "rising_action": 1, "climax": 2, "falling_action": 3, "resolution": 4}
        sorted_events = sorted(
            self.freytag_pyramid.events,
            key=lambda e: (e.act, stage_order.get(e.stage, 1), e.sort_order)
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

            # Get act name
            act_name = (self.freytag_pyramid.act_names[event.act - 1]
                       if event.act <= len(self.freytag_pyramid.act_names)
                       else f"Act {event.act}")

            item_text = f"[{act_name}] {event.title} ({stage_display}, Intensity: {event.intensity})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, event.id)
            self.event_list.addItem(item)

        # Also update the visual pyramid to stay in sync
        if update_pyramid:
            self._update_pyramid()

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

    def load_plot_data(
        self,
        freytag_pyramid: FreytagPyramid,
        subplots: List[Subplot],
        promises: List[StoryPromise] = None
    ):
        """Load plot data.

        Args:
            freytag_pyramid: FreytagPyramid object with events
            subplots: List of Subplot objects
            promises: List of StoryPromise objects
        """
        self.freytag_pyramid = freytag_pyramid
        self.subplots = subplots
        self.promises = promises or []

        # Sync act configuration UI
        self.num_acts_spin.blockSignals(True)
        self.num_acts_spin.setValue(freytag_pyramid.num_acts)
        self.num_acts_spin.blockSignals(False)

        # Update pyramid with acts
        self.pyramid_visual.set_acts(freytag_pyramid.num_acts, freytag_pyramid.act_names)

        self._update_event_list()
        self._update_subplot_list()
        self._update_promise_list()

    def get_plot_data(self):
        """Get plot data.

        Returns:
            Tuple of (FreytagPyramid, List[Subplot], List[StoryPromise])
        """
        return self.freytag_pyramid, self.subplots, self.promises

    def set_available_characters(self, characters: List[str]):
        """Set available characters for event association.

        Args:
            characters: List of character names
        """
        self.available_characters = characters

    def _on_num_acts_changed(self, value: int):
        """Handle number of acts change."""
        self.freytag_pyramid.num_acts = value

        # Ensure act_names list has the right length
        while len(self.freytag_pyramid.act_names) < value:
            self.freytag_pyramid.act_names.append(f"Act {len(self.freytag_pyramid.act_names) + 1}")
        self.freytag_pyramid.act_names = self.freytag_pyramid.act_names[:value]

        # Update visual
        self.pyramid_visual.set_acts(value, self.freytag_pyramid.act_names)
        self.content_changed.emit()

    def _edit_act_names(self):
        """Open dialog to edit act names."""
        dialog = ActNamesDialog(
            self.freytag_pyramid.num_acts,
            self.freytag_pyramid.act_names,
            parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.freytag_pyramid.act_names = dialog.get_act_names()
            self.pyramid_visual.set_acts(
                self.freytag_pyramid.num_acts,
                self.freytag_pyramid.act_names
            )
            self.content_changed.emit()

    def _on_event_list_double_clicked(self, item: QListWidgetItem):
        """Handle double-click on event list item."""
        event_id = item.data(Qt.ItemDataRole.UserRole)
        if event_id:
            self._show_event_popup(event_id)

    def _on_pyramid_event_clicked(self, event_id: str):
        """Handle click on event in pyramid visual."""
        event = next((e for e in self.freytag_pyramid.events if e.id == event_id), None)
        if not event:
            return

        self._show_event_popup(event_id)

    def _show_event_popup(self, event_id: str):
        """Show the event description popup.

        Args:
            event_id: ID of the event to show
        """
        event = next((e for e in self.freytag_pyramid.events if e.id == event_id), None)
        if not event:
            return

        popup = EventDescriptionPopup(event, parent=self)
        result = popup.exec()

        if result == QDialog.DialogCode.Accepted:
            # Description was saved
            self._update_pyramid()
            self.content_changed.emit()
        elif result == 2:  # Custom code for "open full editor"
            # Open the full event editor
            self._edit_event_by_id(event_id)

    def _edit_event_by_id(self, event_id: str):
        """Edit an event by its ID.

        Args:
            event_id: ID of the event to edit
        """
        event = next((e for e in self.freytag_pyramid.events if e.id == event_id), None)
        if not event:
            return

        editor = PlotEventEditor(
            event=event,
            available_characters=self.available_characters,
            available_subplots=self.subplots,
            num_acts=self.freytag_pyramid.num_acts,
            act_names=self.freytag_pyramid.act_names,
            parent=self
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_event_list()
            self.content_changed.emit()


class ActNamesDialog(QDialog):
    """Dialog for editing act names."""

    def __init__(self, num_acts: int, act_names: List[str], parent=None):
        """Initialize act names dialog."""
        super().__init__(parent)
        self.num_acts = num_acts
        self.act_names = act_names.copy() if act_names else []
        self.name_edits = []
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Edit Act Names")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        label = QLabel("Customize the names for each act:")
        layout.addWidget(label)

        # Create input fields for each act
        form_layout = QFormLayout()
        for i in range(self.num_acts):
            edit = QLineEdit()
            default_name = self.act_names[i] if i < len(self.act_names) else f"Act {i+1}"
            edit.setText(default_name)
            edit.setPlaceholderText(f"Act {i+1}")
            form_layout.addRow(f"Act {i+1}:", edit)
            self.name_edits.append(edit)

        layout.addLayout(form_layout)

        # Preset buttons
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Presets:"))

        three_act_btn = QPushButton("3-Act Classic")
        three_act_btn.clicked.connect(lambda: self._apply_preset([
            "Act I: Setup", "Act II: Confrontation", "Act III: Resolution"
        ]))
        preset_layout.addWidget(three_act_btn)

        five_act_btn = QPushButton("5-Act Drama")
        five_act_btn.clicked.connect(lambda: self._apply_preset([
            "Act I: Exposition", "Act II: Rising Action", "Act III: Climax",
            "Act IV: Falling Action", "Act V: Denouement"
        ]))
        preset_layout.addWidget(five_act_btn)

        preset_layout.addStretch()
        layout.addLayout(preset_layout)

        layout.addStretch()

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_preset(self, names: List[str]):
        """Apply preset act names."""
        for i, edit in enumerate(self.name_edits):
            if i < len(names):
                edit.setText(names[i])

    def get_act_names(self) -> List[str]:
        """Get the edited act names."""
        return [edit.text().strip() or f"Act {i+1}" for i, edit in enumerate(self.name_edits)]


class EventDescriptionPopup(QDialog):
    """Popup dialog for viewing and editing event description."""

    description_changed = pyqtSignal()

    def __init__(self, event: PlotEvent, parent=None):
        """Initialize event description popup.

        Args:
            event: PlotEvent to display/edit
            parent: Parent widget
        """
        super().__init__(parent)
        self.event = event
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle(f"Event: {self.event.title}")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)

        # Event info header
        info_layout = QFormLayout()

        # Title (read-only display)
        title_label = QLabel(self.event.title)
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        info_layout.addRow("Title:", title_label)

        # Stage and Act
        stage_names = {
            "exposition": "Exposition",
            "rising_action": "Rising Action",
            "climax": "Climax",
            "falling_action": "Falling Action",
            "resolution": "Resolution"
        }
        stage_display = stage_names.get(self.event.stage, self.event.stage)
        info_layout.addRow("Stage:", QLabel(stage_display))
        info_layout.addRow("Act:", QLabel(f"Act {self.event.act}"))
        info_layout.addRow("Intensity:", QLabel(f"{self.event.intensity}%"))

        layout.addLayout(info_layout)

        # Description editor
        desc_group = QGroupBox("Description")
        desc_layout = QVBoxLayout(desc_group)
        self.description_edit = QTextEdit()
        self.description_edit.setPlainText(self.event.description)
        self.description_edit.setPlaceholderText("What happens in this event...")
        desc_layout.addWidget(self.description_edit)
        layout.addWidget(desc_group)

        # Outcome editor
        outcome_group = QGroupBox("Outcome")
        outcome_layout = QVBoxLayout(outcome_group)
        self.outcome_edit = QTextEdit()
        self.outcome_edit.setPlainText(self.event.outcome)
        self.outcome_edit.setPlaceholderText("What changes as a result...")
        self.outcome_edit.setMaximumHeight(100)
        outcome_layout.addWidget(self.outcome_edit)
        layout.addWidget(outcome_group)

        # Characters involved
        if self.event.related_characters:
            chars_label = QLabel(f"Characters: {', '.join(self.event.related_characters)}")
            chars_label.setWordWrap(True)
            chars_label.setStyleSheet("color: #6b7280; font-size: 11px;")
            layout.addWidget(chars_label)

        # Buttons
        button_layout = QHBoxLayout()

        edit_full_btn = QPushButton("Edit Full Event...")
        edit_full_btn.clicked.connect(self._open_full_editor)
        button_layout.addWidget(edit_full_btn)

        button_layout.addStretch()

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save_and_close)
        save_btn.setDefault(True)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _save_and_close(self):
        """Save description changes and close."""
        self.event.description = self.description_edit.toPlainText().strip()
        self.event.outcome = self.outcome_edit.toPlainText().strip()
        self.description_changed.emit()
        self.accept()

    def _open_full_editor(self):
        """Signal that full editor should be opened."""
        # Save any changes first
        self.event.description = self.description_edit.toPlainText().strip()
        self.event.outcome = self.outcome_edit.toPlainText().strip()
        self.done(2)  # Custom return code for "open full editor"


class PromiseEditor(QDialog):
    """Dialog for editing a story promise."""

    PROMISE_TYPES = [
        ("tone", "Tone", "Emotional atmosphere and mood"),
        ("plot", "Plot", "Story structure and events"),
        ("genre", "Genre", "Genre conventions and expectations"),
        ("character", "Character", "Character arcs and consistency"),
    ]

    def __init__(
        self,
        promise: StoryPromise = None,
        available_characters: List[str] = None,
        parent=None
    ):
        """Initialize promise editor.

        Args:
            promise: Existing promise to edit, or None for new promise
            available_characters: List of character names for character promises
            parent: Parent widget
        """
        super().__init__(parent)
        self.promise = promise
        self.available_characters = available_characters or []
        self.is_new = promise is None
        self._init_ui()
        if not self.is_new:
            self._load_promise()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Edit Promise" if not self.is_new else "New Story Promise")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)

        # Create scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)

        # Promise type selector
        self.type_combo = QListWidget()
        self.type_combo.setMaximumHeight(100)
        for type_id, type_name, type_desc in self.PROMISE_TYPES:
            item = QListWidgetItem(f"{type_name} - {type_desc}")
            item.setData(Qt.ItemDataRole.UserRole, type_id)
            self.type_combo.addItem(item)
        self.type_combo.setCurrentRow(0)
        self.type_combo.currentItemChanged.connect(self._on_type_changed)
        form_layout.addRow("Type:*", self.type_combo)

        # Title
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Brief summary of the promise")
        form_layout.addRow("Title:*", self.title_edit)

        # Description
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(
            "Detailed description of what you're committing to...\n\n"
            "Examples:\n"
            "• Tone: The story will maintain a hopeful undertone despite dark themes\n"
            "• Plot: The central mystery will be fully resolved by the end\n"
            "• Genre: Romance will develop gradually with satisfying payoff\n"
            "• Character: Sarah will complete her arc from self-doubt to confidence"
        )
        self.description_edit.setMaximumHeight(150)
        form_layout.addRow("Description:", self.description_edit)

        # Related characters (for character promises)
        self.characters_group = QGroupBox("Related Characters")
        chars_layout = QVBoxLayout(self.characters_group)

        self.characters_list = QListWidget()
        self.characters_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.characters_list.setMaximumHeight(100)
        for char in self.available_characters:
            self.characters_list.addItem(char)
        chars_layout.addWidget(self.characters_list)

        form_layout.addRow(self.characters_group)
        self._update_characters_visibility()

        scroll_area.setWidget(form_widget)
        layout.addWidget(scroll_area)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_type_changed(self, current, previous):
        """Handle promise type change."""
        self._update_characters_visibility()

    def _update_characters_visibility(self):
        """Show/hide characters group based on promise type."""
        current = self.type_combo.currentItem()
        if current:
            promise_type = current.data(Qt.ItemDataRole.UserRole)
            self.characters_group.setVisible(promise_type == "character")

    def _load_promise(self):
        """Load existing promise data into form."""
        if not self.promise:
            return

        # Set type
        for i in range(self.type_combo.count()):
            item = self.type_combo.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == self.promise.promise_type:
                self.type_combo.setCurrentRow(i)
                break

        self.title_edit.setText(self.promise.title)
        self.description_edit.setPlainText(self.promise.description)

        # Select related characters
        for i in range(self.characters_list.count()):
            item = self.characters_list.item(i)
            if item.text() in self.promise.related_characters:
                item.setSelected(True)

    def _save_and_close(self):
        """Validate and save the promise."""
        title = self.title_edit.text().strip()
        if not title:
            self.title_edit.setFocus()
            return

        current_type_item = self.type_combo.currentItem()
        if not current_type_item:
            return

        promise_type = current_type_item.data(Qt.ItemDataRole.UserRole)

        # Get selected characters
        related_characters = [
            item.text() for item in self.characters_list.selectedItems()
        ]

        if self.is_new:
            import uuid
            self.promise = StoryPromise(
                id=str(uuid.uuid4()),
                promise_type=promise_type,
                title=title,
                description=self.description_edit.toPlainText().strip(),
                related_characters=related_characters
            )
        else:
            self.promise.promise_type = promise_type
            self.promise.title = title
            self.promise.description = self.description_edit.toPlainText().strip()
            self.promise.related_characters = related_characters

        self.accept()

    def get_promise(self) -> StoryPromise:
        """Get the edited promise."""
        return self.promise
