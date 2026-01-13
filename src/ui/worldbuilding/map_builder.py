"""Interactive map builder with drag-and-drop elements."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsPixmapItem, QGraphicsEllipseItem, QGraphicsPolygonItem,
    QGraphicsLineItem, QToolBar, QDockWidget, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QFileDialog, QColorDialog,
    QSlider, QCheckBox, QGroupBox, QListWidget, QSplitter, QMenu, QInputDialog,
    QMessageBox, QGraphicsPathItem
)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF, QLineF, QTimer
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QPixmap, QPainterPath, QAction,
    QTransform, QPolygonF, QFont, QImage, QKeySequence
)
from typing import List, Optional, Dict, Tuple, Any
import uuid
import os
from pathlib import Path

from src.models.worldbuilding_objects import (
    WorldMap, MapPlace, MapLandmark, MapEvent, MapLayer,
    PlaceType, LandmarkType, EventType, MarkerStyle, GridSettings,
    Faction, Planet
)


class MapUndoCommand:
    """Base class for undo commands."""

    def __init__(self, description: str):
        self.description = description

    def undo(self):
        """Undo the command."""
        pass

    def redo(self):
        """Redo the command."""
        pass


class AddElementCommand(MapUndoCommand):
    """Command to add an element to the map."""

    def __init__(self, canvas, element, element_type: str):
        super().__init__(f"Add {element_type}")
        self.canvas = canvas
        self.element = element
        self.element_type = element_type

    def undo(self):
        if self.element_type == "place":
            self.canvas.current_map.places.remove(self.element)
        elif self.element_type == "landmark":
            self.canvas.current_map.landmarks.remove(self.element)
        elif self.element_type == "event":
            self.canvas.current_map.events.remove(self.element)
        self.canvas.refresh_elements()

    def redo(self):
        if self.element_type == "place":
            self.canvas.current_map.places.append(self.element)
        elif self.element_type == "landmark":
            self.canvas.current_map.landmarks.append(self.element)
        elif self.element_type == "event":
            self.canvas.current_map.events.append(self.element)
        self.canvas.refresh_elements()


class MoveElementCommand(MapUndoCommand):
    """Command to move an element."""

    def __init__(self, element, old_pos: Tuple[float, float], new_pos: Tuple[float, float]):
        super().__init__("Move element")
        self.element = element
        self.old_pos = old_pos
        self.new_pos = new_pos

    def undo(self):
        if hasattr(self.element, 'x'):
            self.element.x, self.element.y = self.old_pos
        elif hasattr(self.element, 'points') and len(self.element.points) > 0:
            dx = self.old_pos[0] - self.new_pos[0]
            dy = self.old_pos[1] - self.new_pos[1]
            self.element.points = [(x + dx, y + dy) for x, y in self.element.points]

    def redo(self):
        if hasattr(self.element, 'x'):
            self.element.x, self.element.y = self.new_pos
        elif hasattr(self.element, 'points') and len(self.element.points) > 0:
            dx = self.new_pos[0] - self.old_pos[0]
            dy = self.new_pos[1] - self.old_pos[1]
            self.element.points = [(x + dx, y + dy) for x, y in self.element.points]


class MapElementItem(QGraphicsEllipseItem):
    """Graphical representation of a map element."""

    def __init__(self, element: Any, element_type: str):
        size = element.marker_style.size if hasattr(element, 'marker_style') else 20
        super().__init__(-size/2, -size/2, size, size)
        self.element = element
        self.element_type = element_type

        # Set position
        if hasattr(element, 'x'):
            self.setPos(element.x, element.y)
        elif hasattr(element, 'points') and len(element.points) > 0:
            self.setPos(element.points[0][0], element.points[0][1])

        # Set appearance
        color = QColor(element.marker_style.color if hasattr(element, 'marker_style') else "#3b82f6")
        self.setBrush(QBrush(color))
        self.setPen(QPen(Qt.GlobalColor.white, 2))

        # Make draggable
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

        # Tooltip
        tooltip = f"<b>{element.name}</b><br>{element_type.title()}"
        if element.description:
            tooltip += f"<br>{element.description[:100]}"
        self.setToolTip(tooltip)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # Update element position
            pos = self.pos()
            if hasattr(self.element, 'x'):
                self.element.x = pos.x()
                self.element.y = pos.y()
        return super().itemChange(change, value)


class MapLandmarkItem(QGraphicsPathItem):
    """Graphical representation of a landmark (can be line or point)."""

    def __init__(self, landmark: MapLandmark):
        super().__init__()
        self.landmark = landmark

        # Create path from points
        path = QPainterPath()
        if len(landmark.points) > 0:
            path.moveTo(landmark.points[0][0], landmark.points[0][1])
            for x, y in landmark.points[1:]:
                path.lineTo(x, y)

        self.setPath(path)

        # Set appearance
        color = QColor(landmark.marker_style.color)
        pen = QPen(color, landmark.line_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.setPen(pen)

        # Make selectable
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

        # Tooltip
        tooltip = f"<b>{landmark.name}</b><br>Landmark: {landmark.landmark_type.value.title()}"
        if landmark.description:
            tooltip += f"<br>{landmark.description[:100]}"
        self.setToolTip(tooltip)


class MapCanvas(QGraphicsView):
    """Interactive map canvas with zoom and pan."""

    element_clicked = pyqtSignal(object, str)  # element, element_type
    element_moved = pyqtSignal(object)
    content_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene()
        self.setScene(self.scene)

        # Current map
        self.current_map: Optional[WorldMap] = None
        self.base_map_item: Optional[QGraphicsPixmapItem] = None

        # Undo/redo
        self.undo_stack: List[MapUndoCommand] = []
        self.redo_stack: List[MapUndoCommand] = []
        self.max_undo = 20

        # Tool mode
        self.tool_mode = "select"  # select, add_place, add_landmark, add_event, pan

        # Configure view
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Panning state
        self._is_panning = False
        self._pan_start_pos = QPointF()

    def load_map(self, world_map: WorldMap):
        """Load a map onto the canvas."""
        self.current_map = world_map
        self.scene.clear()
        self.base_map_item = None

        # Load base map image if specified
        if world_map.image_path and os.path.exists(world_map.image_path):
            pixmap = QPixmap(world_map.image_path)
            if not pixmap.isNull():
                self.base_map_item = self.scene.addPixmap(pixmap)
                self.base_map_item.setZValue(-1)  # Behind everything
                world_map.width = pixmap.width()
                world_map.height = pixmap.height()
                self.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())

        # Refresh all elements
        self.refresh_elements()

    def refresh_elements(self):
        """Refresh all map elements on the canvas."""
        if not self.current_map:
            return

        # Remove existing element items (keep base map)
        for item in list(self.scene.items()):
            if item != self.base_map_item:
                self.scene.removeItem(item)

        # Add places
        for place in self.current_map.places:
            item = MapElementItem(place, "place")
            self.scene.addItem(item)

        # Add landmarks
        for landmark in self.current_map.landmarks:
            if len(landmark.points) > 1:
                item = MapLandmarkItem(landmark)
                self.scene.addItem(item)
            else:
                item = MapElementItem(landmark, "landmark")
                self.scene.addItem(item)

        # Add events
        for event in self.current_map.events:
            item = MapElementItem(event, "event")
            self.scene.addItem(item)

        self.content_changed.emit()

    def set_tool_mode(self, mode: str):
        """Set the current tool mode."""
        self.tool_mode = mode
        if mode == "pan":
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def wheelEvent(self, event):
        """Handle mouse wheel for zooming."""
        # Zoom factor
        zoom_in_factor = 1.15
        zoom_out_factor = 1 / zoom_in_factor

        # Calculate zoom
        if event.angleDelta().y() > 0:
            zoom_factor = zoom_in_factor
        else:
            zoom_factor = zoom_out_factor

        # Apply zoom
        self.scale(zoom_factor, zoom_factor)

    def mousePressEvent(self, event):
        """Handle mouse press."""
        if event.button() == Qt.MouseButton.LeftButton and self.tool_mode == "select":
            item = self.itemAt(event.pos())
            if isinstance(item, (MapElementItem, MapLandmarkItem)):
                if isinstance(item, MapElementItem):
                    self.element_clicked.emit(item.element, item.element_type)
                elif isinstance(item, MapLandmarkItem):
                    self.element_clicked.emit(item.landmark, "landmark")

        super().mousePressEvent(event)

    def execute_command(self, command: MapUndoCommand):
        """Execute a command and add to undo stack."""
        command.redo()
        self.undo_stack.append(command)
        if len(self.undo_stack) > self.max_undo:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.content_changed.emit()

    def undo(self):
        """Undo last command."""
        if self.undo_stack:
            command = self.undo_stack.pop()
            command.undo()
            self.redo_stack.append(command)
            self.content_changed.emit()

    def redo(self):
        """Redo last undone command."""
        if self.redo_stack:
            command = self.redo_stack.pop()
            command.redo()
            self.undo_stack.append(command)
            self.content_changed.emit()


class PlaceEditorDialog(QDialog):
    """Dialog for editing a place."""

    def __init__(self, place: Optional[MapPlace] = None, available_factions: List[Faction] = None, parent=None):
        super().__init__(parent)
        self.place = place or MapPlace(
            id=str(uuid.uuid4()),
            name="",
            place_type=PlaceType.SETTLEMENT,
            x=0,
            y=0
        )
        self.available_factions = available_factions or []
        self.setWindowTitle("Place Editor")
        self.resize(500, 450)
        self._init_ui()
        if place:
            self._load_place()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name of the place")
        form.addRow("Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value.replace("_", " ").title() for t in PlaceType])
        form.addRow("Type:", self.type_combo)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText("Description...")
        form.addRow("Description:", self.description_edit)

        self.population_spin = QSpinBox()
        self.population_spin.setMaximum(999999999)
        form.addRow("Population:", self.population_spin)

        self.faction_combo = QComboBox()
        self.faction_combo.addItem("-- No Faction --", "")
        for faction in self.available_factions:
            self.faction_combo.addItem(faction.name, faction.id)
        form.addRow("Faction:", self.faction_combo)

        # Marker style
        style_group = QGroupBox("Marker Style")
        style_layout = QFormLayout()

        self.color_btn = QPushButton("Choose Color")
        self.color_btn.clicked.connect(self._choose_color)
        self.current_color = QColor("#3b82f6")
        self.color_btn.setStyleSheet(f"background-color: {self.current_color.name()};")
        style_layout.addRow("Color:", self.color_btn)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(10, 50)
        self.size_spin.setValue(20)
        style_layout.addRow("Size:", self.size_spin)

        style_group.setLayout(style_layout)
        layout.addLayout(form)
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

    def _load_place(self):
        self.name_edit.setText(self.place.name)

        type_text = self.place.place_type.value.replace("_", " ").title()
        idx = self.type_combo.findText(type_text)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)

        self.description_edit.setPlainText(self.place.description)

        if self.place.population:
            self.population_spin.setValue(self.place.population)

        # Set faction
        for i in range(self.faction_combo.count()):
            if self.faction_combo.itemData(i) == self.place.faction_id:
                self.faction_combo.setCurrentIndex(i)
                break

        # Marker style
        self.current_color = QColor(self.place.marker_style.color)
        self.color_btn.setStyleSheet(f"background-color: {self.current_color.name()};")
        self.size_spin.setValue(self.place.marker_style.size)

        # Tags
        for tag in self.place.tags:
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

        self.place.name = name

        type_text = self.type_combo.currentText().lower().replace(" ", "_")
        try:
            self.place.place_type = PlaceType(type_text)
        except ValueError:
            self.place.place_type = PlaceType.SETTLEMENT

        self.place.description = self.description_edit.toPlainText().strip()
        self.place.population = self.population_spin.value() if self.population_spin.value() > 0 else None
        self.place.faction_id = self.faction_combo.currentData()

        # Marker style
        self.place.marker_style.color = self.current_color.name()
        self.place.marker_style.size = self.size_spin.value()

        # Tags
        self.place.tags = [
            self.tags_list.item(i).text()
            for i in range(self.tags_list.count())
        ]

        self.accept()

    def get_place(self) -> MapPlace:
        return self.place


# Due to length, continuing in next part...
