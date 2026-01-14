"""Additional widgets for map builder - event/landmark editors and main widget."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QFileDialog, QColorDialog,
    QSlider, QCheckBox, QGroupBox, QListWidget, QSplitter, QMenu, QInputDialog,
    QMessageBox, QToolBar, QDockWidget, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QColor
from typing import List, Optional
import uuid
import os

from src.models.worldbuilding_objects import (
    WorldMap, MapPlace, MapLandmark, MapEvent, MapLayer,
    PlaceType, LandmarkType, EventType, MarkerStyle, GridSettings,
    Faction, Planet, EnhancedCharacter
)
from src.ui.worldbuilding.map_builder import MapCanvas, PlaceEditorDialog
from src.ui.worldbuilding.enhanced_map_canvas import EnhancedMapCanvas


class LandmarkEditorDialog(QDialog):
    """Dialog for editing a landmark."""

    def __init__(self, landmark: Optional[MapLandmark] = None, parent=None):
        super().__init__(parent)
        self.landmark = landmark or MapLandmark(
            id=str(uuid.uuid4()),
            name="",
            landmark_type=LandmarkType.BUILDING,
            points=[(0, 0)]
        )
        self.setWindowTitle("Landmark Editor")
        self.resize(500, 400)
        self._init_ui()
        if landmark:
            self._load_landmark()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name of the landmark")
        form.addRow("Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value.replace("_", " ").title() for t in LandmarkType])
        form.addRow("Type:", self.type_combo)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText("Description...")
        form.addRow("Description:", self.description_edit)

        layout.addLayout(form)

        # Marker style
        style_group = QGroupBox("Marker Style")
        style_layout = QFormLayout()

        self.color_btn = QPushButton("Choose Color")
        self.color_btn.clicked.connect(self._choose_color)
        self.current_color = QColor("#10b981")
        self.color_btn.setStyleSheet(f"background-color: {self.current_color.name()};")
        style_layout.addRow("Color:", self.color_btn)

        self.line_width_spin = QSpinBox()
        self.line_width_spin.setRange(1, 10)
        self.line_width_spin.setValue(2)
        style_layout.addRow("Line Width:", self.line_width_spin)

        style_group.setLayout(style_layout)
        layout.addWidget(style_group)

        # Tags
        tags_group = QGroupBox("Tags")
        tags_layout = QVBoxLayout()
        self.tags_list = QListWidget()
        self.tags_list.setMaximumHeight(80)
        tags_layout.addWidget(self.tags_list)

        tags_btn_layout = QHBoxLayout()
        add_tag_btn = QPushButton("+ Add Tag")
        add_tag_btn.clicked.connect(self._add_tag)
        tags_btn_layout.addWidget(add_tag_btn)

        remove_tag_btn = QPushButton("- Remove")
        remove_tag_btn.clicked.connect(self._remove_tag)
        tags_btn_layout.addWidget(remove_tag_btn)
        tags_btn_layout.addStretch()

        tags_layout.addLayout(tags_btn_layout)
        tags_group.setLayout(tags_layout)
        layout.addWidget(tags_group)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_landmark(self):
        self.name_edit.setText(self.landmark.name)

        type_text = self.landmark.landmark_type.value.replace("_", " ").title()
        idx = self.type_combo.findText(type_text)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)

        self.description_edit.setPlainText(self.landmark.description)

        # Marker style
        self.current_color = QColor(self.landmark.marker_style.color)
        self.color_btn.setStyleSheet(f"background-color: {self.current_color.name()};")
        self.line_width_spin.setValue(self.landmark.line_width)

        # Tags
        for tag in self.landmark.tags:
            self.tags_list.addItem(tag)

    def _choose_color(self):
        color = QColorDialog.getColor(self.current_color, self, "Choose Marker Color")
        if color.isValid():
            self.current_color = color
            self.color_btn.setStyleSheet(f"background-color: {color.name()};")

    def _add_tag(self):
        tag, ok = QInputDialog.getText(self, "Add Tag", "Enter tag:")
        if ok and tag:
            self.tags_list.addItem(tag)

    def _remove_tag(self):
        current = self.tags_list.currentRow()
        if current >= 0:
            self.tags_list.takeItem(current)

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            return

        self.landmark.name = name

        type_text = self.type_combo.currentText().lower().replace(" ", "_")
        try:
            self.landmark.landmark_type = LandmarkType(type_text)
        except ValueError:
            self.landmark.landmark_type = LandmarkType.BUILDING

        self.landmark.description = self.description_edit.toPlainText().strip()

        # Marker style
        self.landmark.marker_style.color = self.current_color.name()
        self.landmark.line_width = self.line_width_spin.value()

        # Tags
        self.landmark.tags = [
            self.tags_list.item(i).text()
            for i in range(self.tags_list.count())
        ]

        self.accept()

    def get_landmark(self) -> MapLandmark:
        return self.landmark


class EventEditorDialog(QDialog):
    """Dialog for editing an event."""

    def __init__(self, event: Optional[MapEvent] = None,
                 available_factions: List[Faction] = None,
                 available_characters: List[EnhancedCharacter] = None,
                 parent=None):
        super().__init__(parent)
        self.event = event or MapEvent(
            id=str(uuid.uuid4()),
            name="",
            event_type=EventType.BATTLE,
            x=0,
            y=0
        )
        self.available_factions = available_factions or []
        self.available_characters = available_characters or []
        self.setWindowTitle("Event Editor")
        self.resize(500, 500)
        self._init_ui()
        if event:
            self._load_event()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name of the event")
        form.addRow("Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value.title() for t in EventType])
        form.addRow("Type:", self.type_combo)

        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText("Date or era (e.g., '1453', 'Age of Heroes')")
        form.addRow("Date/Era:", self.date_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText("Description...")
        form.addRow("Description:", self.description_edit)

        layout.addLayout(form)

        # Marker style
        style_group = QGroupBox("Marker Style")
        style_layout = QFormLayout()

        self.color_btn = QPushButton("Choose Color")
        self.color_btn.clicked.connect(self._choose_color)
        self.current_color = QColor("#ef4444")
        self.color_btn.setStyleSheet(f"background-color: {self.current_color.name()};")
        style_layout.addRow("Color:", self.color_btn)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(10, 50)
        self.size_spin.setValue(20)
        style_layout.addRow("Size:", self.size_spin)

        style_group.setLayout(style_layout)
        layout.addWidget(style_group)

        # Associated factions
        factions_group = QGroupBox("Associated Factions")
        factions_layout = QVBoxLayout()
        self.factions_list = QListWidget()
        self.factions_list.setMaximumHeight(80)
        factions_layout.addWidget(self.factions_list)

        factions_btn_layout = QHBoxLayout()
        add_faction_btn = QPushButton("+ Add Faction")
        add_faction_btn.clicked.connect(self._add_faction)
        factions_btn_layout.addWidget(add_faction_btn)

        remove_faction_btn = QPushButton("- Remove")
        remove_faction_btn.clicked.connect(self._remove_faction)
        factions_btn_layout.addWidget(remove_faction_btn)
        factions_btn_layout.addStretch()

        factions_layout.addLayout(factions_btn_layout)
        factions_group.setLayout(factions_layout)
        layout.addWidget(factions_group)

        # Tags
        tags_group = QGroupBox("Tags")
        tags_layout = QVBoxLayout()
        self.tags_list = QListWidget()
        self.tags_list.setMaximumHeight(60)
        tags_layout.addWidget(self.tags_list)

        tags_btn_layout = QHBoxLayout()
        add_tag_btn = QPushButton("+ Add Tag")
        add_tag_btn.clicked.connect(self._add_tag)
        tags_btn_layout.addWidget(add_tag_btn)

        remove_tag_btn = QPushButton("- Remove")
        remove_tag_btn.clicked.connect(self._remove_tag)
        tags_btn_layout.addWidget(remove_tag_btn)
        tags_btn_layout.addStretch()

        tags_layout.addLayout(tags_btn_layout)
        tags_group.setLayout(tags_layout)
        layout.addWidget(tags_group)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_event(self):
        self.name_edit.setText(self.event.name)

        type_text = self.event.event_type.value.title()
        idx = self.type_combo.findText(type_text)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)

        if self.event.date:
            self.date_edit.setText(self.event.date)

        self.description_edit.setPlainText(self.event.description)

        # Marker style
        self.current_color = QColor(self.event.marker_style.color)
        self.color_btn.setStyleSheet(f"background-color: {self.current_color.name()};")
        self.size_spin.setValue(self.event.marker_style.size)

        # Factions
        for faction_id in self.event.associated_factions:
            faction = next((f for f in self.available_factions if f.id == faction_id), None)
            if faction:
                item = QListWidgetItem(faction.name)
                item.setData(Qt.ItemDataRole.UserRole, faction.id)
                self.factions_list.addItem(item)

        # Tags
        for tag in self.event.tags:
            self.tags_list.addItem(tag)

    def _choose_color(self):
        color = QColorDialog.getColor(self.current_color, self, "Choose Marker Color")
        if color.isValid():
            self.current_color = color
            self.color_btn.setStyleSheet(f"background-color: {color.name()};")

    def _add_faction(self):
        if not self.available_factions:
            QMessageBox.information(self, "No Factions", "Please create factions first.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Select Faction")
        layout = QVBoxLayout(dialog)

        faction_list = QListWidget()
        for faction in self.available_factions:
            faction_list.addItem(f"{faction.name} ({faction.faction_type.value})")
            faction_list.item(faction_list.count() - 1).setData(Qt.ItemDataRole.UserRole, faction.id)

        layout.addWidget(faction_list)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted and faction_list.currentItem():
            faction_id = faction_list.currentItem().data(Qt.ItemDataRole.UserRole)
            faction_name = faction_list.currentItem().text().split(" (")[0]

            # Check if already added
            for i in range(self.factions_list.count()):
                if self.factions_list.item(i).data(Qt.ItemDataRole.UserRole) == faction_id:
                    return

            item = QListWidgetItem(faction_name)
            item.setData(Qt.ItemDataRole.UserRole, faction_id)
            self.factions_list.addItem(item)

    def _remove_faction(self):
        current = self.factions_list.currentRow()
        if current >= 0:
            self.factions_list.takeItem(current)

    def _add_tag(self):
        tag, ok = QInputDialog.getText(self, "Add Tag", "Enter tag:")
        if ok and tag:
            self.tags_list.addItem(tag)

    def _remove_tag(self):
        current = self.tags_list.currentRow()
        if current >= 0:
            self.tags_list.takeItem(current)

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            return

        self.event.name = name

        type_text = self.type_combo.currentText().lower()
        try:
            self.event.event_type = EventType(type_text)
        except ValueError:
            self.event.event_type = EventType.BATTLE

        self.event.date = self.date_edit.text().strip()
        self.event.description = self.description_edit.toPlainText().strip()

        # Marker style
        self.event.marker_style.color = self.current_color.name()
        self.event.marker_style.size = self.size_spin.value()

        # Factions
        self.event.associated_factions = [
            self.factions_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.factions_list.count())
        ]

        # Tags
        self.event.tags = [
            self.tags_list.item(i).text()
            for i in range(self.tags_list.count())
        ]

        self.accept()

    def get_event(self) -> MapEvent:
        return self.event


class MapBuilderWidget(QWidget):
    """Main map builder widget with canvas, toolbar, and sidebar."""

    content_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.maps: List[WorldMap] = []
        self.current_map: Optional[WorldMap] = None

        # Data from worldbuilding
        self.available_factions: List[Faction] = []
        self.available_planets: List[Planet] = []
        self.available_characters: List[EnhancedCharacter] = []

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(16, 12, 16, 8)

        header = QLabel("🗺️ Maps")
        header.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header_layout.addWidget(header)

        subtitle = QLabel("Create and manage interactive maps with places, landmarks, and events")
        subtitle.setStyleSheet("font-size: 12px; color: #6b7280;")
        header_layout.addWidget(subtitle)

        layout.addWidget(header_widget)

        # Map tabs
        self.map_tabs = QTabWidget()
        self.map_tabs.setTabsClosable(True)
        self.map_tabs.tabCloseRequested.connect(self._close_map_tab)
        self.map_tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.map_tabs)

        # Toolbar for map management
        toolbar = QHBoxLayout()

        new_map_btn = QPushButton("+ New Map")
        new_map_btn.clicked.connect(self._create_new_map)
        toolbar.addWidget(new_map_btn)

        load_image_btn = QPushButton("Load Base Image")
        load_image_btn.clicked.connect(self._load_base_image)
        toolbar.addWidget(load_image_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Add welcome placeholder
        self._show_welcome()

    def _show_welcome(self):
        """Show welcome message when no maps are open."""
        welcome = QWidget()
        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        label = QLabel("No maps open\n\nClick '+ New Map' to create your first map")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #6b7280; font-size: 14px;")
        welcome_layout.addWidget(label)

        self.map_tabs.addTab(welcome, "Welcome")

    def _create_new_map(self):
        """Create a new map."""
        name, ok = QInputDialog.getText(self, "New Map", "Enter map name:")
        if not ok or not name.strip():
            return

        world_map = WorldMap(
            id=str(uuid.uuid4()),
            name=name.strip()
        )

        self.maps.append(world_map)
        self._add_map_tab(world_map)
        self.content_changed.emit()

    def _add_map_tab(self, world_map: WorldMap):
        """Add a map tab."""
        # Remove welcome tab if present
        if self.map_tabs.count() == 1 and self.map_tabs.tabText(0) == "Welcome":
            self.map_tabs.removeTab(0)

        # Create map view widget
        map_widget = QWidget()
        map_layout = QVBoxLayout(map_widget)
        map_layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)

        # Map type indicator
        map_type_text = "🗺️ World Map" if not hasattr(world_map, 'map_type') or world_map.map_type == "world" else "🏘️ Location Map"
        map_type_label = QLabel(f"  {map_type_text}  ")
        map_type_label.setStyleSheet("font-weight: bold; color: #1a1a1a; padding: 4px;")
        toolbar.addWidget(map_type_label)

        toolbar.addSeparator()

        # Tool actions
        select_action = QAction("Select", self)
        select_action.setCheckable(True)
        select_action.setChecked(True)
        select_action.triggered.connect(lambda: self._set_tool("select"))
        toolbar.addAction(select_action)

        pan_action = QAction("Pan", self)
        pan_action.setCheckable(True)
        pan_action.triggered.connect(lambda: self._set_tool("pan"))
        toolbar.addAction(pan_action)

        toolbar.addSeparator()

        add_place_action = QAction("+ Place", self)
        add_place_action.triggered.connect(self._add_place)
        toolbar.addAction(add_place_action)

        add_landmark_action = QAction("+ Landmark", self)
        add_landmark_action.triggered.connect(self._add_landmark)
        toolbar.addAction(add_landmark_action)

        add_event_action = QAction("+ Event", self)
        add_event_action.triggered.connect(self._add_event)
        toolbar.addAction(add_event_action)

        toolbar.addSeparator()

        # Navigation tool
        pan_action = QAction("Pan (Hand Tool)", self)
        pan_action.setCheckable(True)
        pan_action.triggered.connect(self._toggle_pan)
        toolbar.addAction(pan_action)
        self.pan_action = pan_action

        toolbar.addSeparator()

        # Drawing tools
        draw_terrain_action = QAction("Draw Terrain", self)
        draw_terrain_action.triggered.connect(self._draw_terrain)
        toolbar.addAction(draw_terrain_action)

        draw_border_action = QAction("Draw Border", self)
        draw_border_action.triggered.connect(self._draw_border)
        toolbar.addAction(draw_border_action)

        # Shape drawing tool
        draw_shape_action = QAction("Draw Shape", self)
        draw_shape_action.triggered.connect(self._draw_shape)
        toolbar.addAction(draw_shape_action)

        # Freehand drawing tool
        freehand_action = QAction("Freehand Shape", self)
        freehand_action.setToolTip("Draw freehand - automatically converts to circle, rectangle, or polygon")
        freehand_action.triggered.connect(self._draw_freehand)
        toolbar.addAction(freehand_action)

        # Pen/brush drawing tool
        pen_action = QAction("Pen Tool", self)
        pen_action.setToolTip("Freehand pen - draw continuous lines for annotations, routes, and details")
        pen_action.triggered.connect(self._draw_pen)
        toolbar.addAction(pen_action)

        toolbar.addSeparator()

        # Map settings
        map_settings_action = QAction("Map Settings", self)
        map_settings_action.triggered.connect(self._open_map_settings)
        toolbar.addAction(map_settings_action)

        # View options
        view_menu_btn = QPushButton("View Options")
        view_menu = QMenu(self)

        self.show_grid_action = QAction("Show Grid", self, checkable=True)
        self.show_grid_action.triggered.connect(self._toggle_grid)
        view_menu.addAction(self.show_grid_action)

        self.show_latlong_action = QAction("Show Lat/Long", self, checkable=True)
        self.show_latlong_action.triggered.connect(self._toggle_latlong)
        view_menu.addAction(self.show_latlong_action)

        self.show_climate_action = QAction("Show Climate Zones", self, checkable=True)
        self.show_climate_action.triggered.connect(self._toggle_climate)
        view_menu.addAction(self.show_climate_action)

        view_menu_btn.setMenu(view_menu)
        toolbar.addWidget(view_menu_btn)

        toolbar.addSeparator()

        # Reset view button
        reset_view_action = QAction("Reset View", self)
        reset_view_action.triggered.connect(self._reset_view)
        toolbar.addAction(reset_view_action)

        toolbar.addSeparator()

        undo_action = QAction("Undo", self)
        undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        undo_action.triggered.connect(self._undo)
        toolbar.addAction(undo_action)

        redo_action = QAction("Redo", self)
        redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        redo_action.triggered.connect(self._redo)
        toolbar.addAction(redo_action)

        toolbar.addSeparator()

        import_action = QAction("Import Maps", self)
        import_action.setToolTip("Import maps from JSON file")
        import_action.triggered.connect(self._import_maps)
        toolbar.addAction(import_action)

        map_layout.addWidget(toolbar)

        # Splitter for canvas and sidebar
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Canvas - use enhanced canvas with projection and drawing support
        canvas = EnhancedMapCanvas()

        # Get associated planet if available
        planet = None
        if world_map.planet_id and self.available_planets:
            planet = next((p for p in self.available_planets if p.id == world_map.planet_id), None)

        # Apply projection mode if available
        if hasattr(world_map, 'projection_mode'):
            canvas.set_projection_mode(world_map.projection_mode)

        canvas.load_map(world_map, planet)
        canvas.element_clicked.connect(self._on_element_clicked)
        canvas.content_changed.connect(self.content_changed)
        splitter.addWidget(canvas)

        # Sidebar
        sidebar = self._create_sidebar(world_map)
        splitter.addWidget(sidebar)

        # Set splitter sizes (canvas gets 70%)
        splitter.setSizes([700, 300])

        map_layout.addWidget(splitter)

        # Store canvas reference
        map_widget.canvas = canvas
        map_widget.world_map = world_map

        # Add tab
        self.map_tabs.addTab(map_widget, world_map.name)
        self.map_tabs.setCurrentWidget(map_widget)

    def _create_sidebar(self, world_map: WorldMap) -> QWidget:
        """Create sidebar with element tree."""
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)

        sidebar_title = QLabel("Map Elements")
        sidebar_title.setStyleSheet("font-weight: 600; font-size: 13px;")
        sidebar_layout.addWidget(sidebar_title)

        # Element tree
        element_tree = QTreeWidget()
        element_tree.setHeaderLabels(["Name", "Type"])
        element_tree.itemDoubleClicked.connect(self._on_tree_item_double_clicked)

        sidebar_layout.addWidget(element_tree)

        # Update tree with elements
        self._update_element_tree(element_tree, world_map)

        # Refresh button
        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(lambda: self._update_element_tree(element_tree, world_map))
        sidebar_layout.addWidget(refresh_btn)

        sidebar.element_tree = element_tree
        return sidebar

    def _update_element_tree(self, tree: QTreeWidget, world_map: WorldMap):
        """Update element tree with current map elements."""
        tree.clear()

        # Places
        places_item = QTreeWidgetItem(["Places", ""])
        places_item.setExpanded(True)
        for place in world_map.places:
            item = QTreeWidgetItem([place.name, place.place_type.value])
            item.setData(0, Qt.ItemDataRole.UserRole, ("place", place))
            places_item.addChild(item)
        tree.addTopLevelItem(places_item)

        # Landmarks
        landmarks_item = QTreeWidgetItem(["Landmarks", ""])
        landmarks_item.setExpanded(True)
        for landmark in world_map.landmarks:
            item = QTreeWidgetItem([landmark.name, landmark.landmark_type.value])
            item.setData(0, Qt.ItemDataRole.UserRole, ("landmark", landmark))
            landmarks_item.addChild(item)
        tree.addTopLevelItem(landmarks_item)

        # Events
        events_item = QTreeWidgetItem(["Events", ""])
        events_item.setExpanded(True)
        for event in world_map.events:
            item = QTreeWidgetItem([event.name, event.event_type.value])
            item.setData(0, Qt.ItemDataRole.UserRole, ("event", event))
            events_item.addChild(item)
        tree.addTopLevelItem(events_item)

    def _set_tool(self, tool: str):
        """Set current tool mode."""
        current_widget = self.map_tabs.currentWidget()
        if hasattr(current_widget, 'canvas'):
            current_widget.canvas.set_tool_mode(tool)

    def _add_place(self):
        """Add a new place to the map."""
        current_widget = self.map_tabs.currentWidget()
        if not hasattr(current_widget, 'canvas'):
            return

        # Create place at center of view
        center = current_widget.canvas.mapToScene(
            current_widget.canvas.viewport().rect().center()
        )

        dialog = PlaceEditorDialog(available_factions=self.available_factions, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            place = dialog.get_place()
            place.x = center.x()
            place.y = center.y()

            current_widget.world_map.places.append(place)
            current_widget.canvas.refresh_elements()
            self.content_changed.emit()

    def _add_landmark(self):
        """Add a new landmark to the map."""
        current_widget = self.map_tabs.currentWidget()
        if not hasattr(current_widget, 'canvas'):
            return

        center = current_widget.canvas.mapToScene(
            current_widget.canvas.viewport().rect().center()
        )

        dialog = LandmarkEditorDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            landmark = dialog.get_landmark()
            landmark.points = [(center.x(), center.y())]

            current_widget.world_map.landmarks.append(landmark)
            current_widget.canvas.refresh_elements()
            self.content_changed.emit()

    def _add_event(self):
        """Add a new event to the map."""
        current_widget = self.map_tabs.currentWidget()
        if not hasattr(current_widget, 'canvas'):
            return

        center = current_widget.canvas.mapToScene(
            current_widget.canvas.viewport().rect().center()
        )

        dialog = EventEditorDialog(
            available_factions=self.available_factions,
            available_characters=self.available_characters,
            parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            event = dialog.get_event()
            event.x = center.x()
            event.y = center.y()

            current_widget.world_map.events.append(event)
            current_widget.canvas.refresh_elements()
            self.content_changed.emit()

    def _on_element_clicked(self, element, element_type: str):
        """Handle element click - open editor."""
        if element_type == "place":
            dialog = PlaceEditorDialog(place=element, available_factions=self.available_factions, parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._refresh_current_canvas()
        elif element_type == "landmark":
            dialog = LandmarkEditorDialog(landmark=element, parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._refresh_current_canvas()
        elif element_type == "event":
            dialog = EventEditorDialog(
                event=element,
                available_factions=self.available_factions,
                available_characters=self.available_characters,
                parent=self
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._refresh_current_canvas()

    def _on_tree_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle tree item double click."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data:
            element_type, element = data
            self._on_element_clicked(element, element_type)

    def _load_base_image(self):
        """Load a base map image."""
        current_widget = self.map_tabs.currentWidget()
        if not hasattr(current_widget, 'canvas'):
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Base Map Image",
            "",
            "Images (*.png *.jpg *.jpeg *.webp);;All Files (*)"
        )

        if file_path:
            current_widget.world_map.image_path = file_path
            current_widget.canvas.load_map(current_widget.world_map)
            self.content_changed.emit()

    def _close_map_tab(self, index: int):
        """Close a map tab."""
        if self.map_tabs.count() <= 1:
            return

        widget = self.map_tabs.widget(index)
        if hasattr(widget, 'world_map'):
            reply = QMessageBox.question(
                self,
                "Close Map",
                f"Close '{widget.world_map.name}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.map_tabs.removeTab(index)

        if self.map_tabs.count() == 0:
            self._show_welcome()

    def _on_tab_changed(self, index: int):
        """Handle tab change."""
        widget = self.map_tabs.widget(index)
        if hasattr(widget, 'world_map'):
            self.current_map = widget.world_map

    def _refresh_current_canvas(self):
        """Refresh current canvas."""
        current_widget = self.map_tabs.currentWidget()
        if hasattr(current_widget, 'canvas'):
            current_widget.canvas.refresh_elements()
            self.content_changed.emit()

    def _undo(self):
        """Undo last action."""
        current_widget = self.map_tabs.currentWidget()
        if hasattr(current_widget, 'canvas'):
            current_widget.canvas.undo()

    def _redo(self):
        """Redo last undone action."""
        current_widget = self.map_tabs.currentWidget()
        if hasattr(current_widget, 'canvas'):
            current_widget.canvas.redo()

    def _draw_terrain(self):
        """Start terrain drawing mode."""
        from src.ui.worldbuilding.map_settings_dialog import TerrainToolDialog

        dialog = TerrainToolDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            terrain_type, color = dialog.get_terrain_info()
            current_widget = self.map_tabs.currentWidget()
            if hasattr(current_widget, 'canvas'):
                current_widget.canvas.set_tool_mode("draw_terrain", terrain_type)
                current_widget.canvas.current_terrain_color = color

    def _draw_border(self):
        """Start faction border drawing mode."""
        if not self.available_factions:
            QMessageBox.information(self, "No Factions", "Please create factions first.")
            return

        # Let user select faction
        from PyQt6.QtWidgets import QInputDialog

        faction_names = [f.name for f in self.available_factions]
        faction_name, ok = QInputDialog.getItem(
            self, "Select Faction", "Choose faction for border:",
            faction_names, 0, False
        )

        if ok and faction_name:
            current_widget = self.map_tabs.currentWidget()
            if hasattr(current_widget, 'canvas'):
                current_widget.canvas.set_tool_mode("draw_border")

    def _draw_shape(self):
        """Start shape drawing mode."""
        from src.ui.worldbuilding.map_settings_dialog import ShapeToolDialog
        from PyQt6.QtWidgets import QMessageBox

        current_widget = self.map_tabs.currentWidget()
        if not hasattr(current_widget, 'canvas'):
            return

        dialog = ShapeToolDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            shape_type, color = dialog.get_shape_info()
            current_widget.canvas.current_shape_color = color
            current_widget.canvas.set_tool_mode(f"draw_{shape_type}", shape_type=shape_type)

            # Show instructions for polygon
            if shape_type == "polygon":
                QMessageBox.information(
                    self,
                    "Draw Polygon",
                    "Click to add points to the polygon.\nRight-click to finish drawing."
                )

    def _draw_freehand(self):
        """Start freehand drawing mode."""
        from src.ui.worldbuilding.map_settings_dialog import ShapeToolDialog
        from PyQt6.QtWidgets import QMessageBox

        current_widget = self.map_tabs.currentWidget()
        if not hasattr(current_widget, 'canvas'):
            return

        # Let user pick color
        dialog = ShapeToolDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            _, color = dialog.get_shape_info()
            current_widget.canvas.current_shape_color = color
            current_widget.canvas.set_tool_mode("draw_freehand")

            QMessageBox.information(
                self,
                "Freehand Drawing",
                "Draw a shape freehand:\n\n"
                "• Draw a rough circle → converts to circle\n"
                "• Draw a rough rectangle → converts to rectangle\n"
                "• Draw irregular shape → converts to polygon\n\n"
                "Release mouse to finish drawing."
            )

    def _draw_pen(self):
        """Start pen drawing mode."""
        from src.ui.worldbuilding.map_settings_dialog import PenToolDialog
        from PyQt6.QtWidgets import QMessageBox

        current_widget = self.map_tabs.currentWidget()
        if not hasattr(current_widget, 'canvas'):
            return

        # Let user configure pen
        dialog = PenToolDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            color, width = dialog.get_pen_info()
            current_widget.canvas.current_pen_color = color
            current_widget.canvas.current_pen_width = width
            current_widget.canvas.set_tool_mode("draw_pen")

            QMessageBox.information(
                self,
                "Pen Tool",
                "Pen tool active:\n\n"
                "• Click and drag to draw continuous lines\n"
                "• Release mouse to finish a stroke\n"
                "• Tool stays active for multiple strokes\n"
                "• Great for routes, annotations, and details\n\n"
                "Click another tool to exit pen mode."
            )

    def _open_map_settings(self):
        """Open map settings dialog."""
        from src.ui.worldbuilding.map_settings_dialog import MapSettingsDialog

        current_widget = self.map_tabs.currentWidget()
        if not hasattr(current_widget, 'world_map'):
            return

        dialog = MapSettingsDialog(
            current_widget.world_map,
            self.available_planets,
            self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Update canvas with new settings including planet data and projection
            if hasattr(current_widget, 'canvas'):
                planet = None
                if current_widget.world_map.planet_id and self.available_planets:
                    planet = next((p for p in self.available_planets if p.id == current_widget.world_map.planet_id), None)

                # Apply projection mode
                if hasattr(current_widget.world_map, 'projection_mode'):
                    current_widget.canvas.set_projection_mode(current_widget.world_map.projection_mode)

                current_widget.canvas.load_map(current_widget.world_map, planet)
            self.content_changed.emit()

            # Update tab name if changed
            index = self.map_tabs.indexOf(current_widget)
            self.map_tabs.setTabText(index, current_widget.world_map.name)

    def _toggle_grid(self, checked: bool):
        """Toggle grid visibility."""
        current_widget = self.map_tabs.currentWidget()
        if hasattr(current_widget, 'canvas') and hasattr(current_widget.canvas, 'toggle_grid'):
            current_widget.canvas.toggle_grid(checked)

    def _toggle_latlong(self, checked: bool):
        """Toggle lat/long grid visibility."""
        current_widget = self.map_tabs.currentWidget()
        if hasattr(current_widget, 'canvas') and hasattr(current_widget.canvas, 'toggle_lat_long_grid'):
            current_widget.canvas.toggle_lat_long_grid(checked)

    def _toggle_climate(self, checked: bool):
        """Toggle climate zones visibility."""
        current_widget = self.map_tabs.currentWidget()
        if hasattr(current_widget, 'canvas') and hasattr(current_widget.canvas, 'toggle_climate_zones'):
            current_widget.canvas.toggle_climate_zones(checked)

    def _toggle_pan(self, checked: bool):
        """Toggle pan mode."""
        current_widget = self.map_tabs.currentWidget()
        if hasattr(current_widget, 'canvas'):
            if checked:
                current_widget.canvas.set_tool_mode("pan")
            else:
                current_widget.canvas.set_tool_mode("select")

    def _reset_view(self):
        """Reset zoom and center view."""
        current_widget = self.map_tabs.currentWidget()
        if hasattr(current_widget, 'canvas') and hasattr(current_widget.canvas, 'reset_view'):
            current_widget.canvas.reset_view()

    def set_available_factions(self, factions: List[Faction]):
        """Set available factions from worldbuilding."""
        self.available_factions = factions

    def set_available_planets(self, planets: List[Planet]):
        """Set available planets from worldbuilding."""
        self.available_planets = planets

    def set_available_characters(self, characters: List[EnhancedCharacter]):
        """Set available characters from worldbuilding."""
        self.available_characters = characters

    def load_maps(self, maps: List[WorldMap]):
        """Load maps list."""
        # Ensure maps is never None (backward compatibility)
        self.maps = maps if maps is not None else []

        # Clear existing tabs
        while self.map_tabs.count() > 0:
            self.map_tabs.removeTab(0)

        if not self.maps:
            self._show_welcome()
        else:
            for world_map in self.maps:
                self._add_map_tab(world_map)

    def get_maps(self) -> List[WorldMap]:
        """Get maps list."""
        # Ensure we always return a list (backward compatibility)
        return self.maps if self.maps is not None else []

    def _import_maps(self):
        """Import maps from JSON file."""
        from src.ui.worldbuilding.worldbuilding_importer import show_import_dialog
        from src.models.worldbuilding_objects import CompleteWorldBuilding

        temp_wb = CompleteWorldBuilding(maps=self.maps)
        result = show_import_dialog(self, temp_wb, target_section="maps")

        if result and result.imported_counts.get("maps", 0) > 0:
            self.maps = temp_wb.maps
            self.load_maps(self.maps)
            self.content_changed.emit()
