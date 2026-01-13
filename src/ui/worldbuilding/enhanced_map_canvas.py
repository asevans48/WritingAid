"""Enhanced map canvas with spherical projection and terrain drawing."""

from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsPixmapItem,
    QGraphicsEllipseItem, QGraphicsPolygonItem, QGraphicsPathItem,
    QGraphicsRectItem, QMenu, QColorDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF, QLineF
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QPixmap, QPainterPath,
    QTransform, QPolygonF, QImage, QFont
)
from typing import List, Optional, Dict, Tuple, Any
import math

from src.models.worldbuilding_objects import (
    WorldMap, MapPlace, MapLandmark, MapEvent, Planet, ClimateZone
)
from src.ui.worldbuilding.map_builder import MapElementItem, MapLandmarkItem
import os


class MapProjection:
    """Handle map projection calculations."""

    @staticmethod
    def mercator_to_sphere(x: float, y: float, width: float, height: float) -> Tuple[float, float]:
        """Convert flat Mercator coordinates to latitude/longitude."""
        lon = (x / width) * 360 - 180
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / height)))
        lat = math.degrees(lat_rad)
        return lat, lon

    @staticmethod
    def sphere_to_mercator(lat: float, lon: float, width: float, height: float) -> Tuple[float, float]:
        """Convert latitude/longitude to flat Mercator coordinates."""
        # Clamp latitude to avoid singularities at poles
        lat = max(-85, min(85, lat))

        x = ((lon + 180) / 360) * width
        lat_rad = math.radians(lat)
        y = (1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) * height / 2
        return x, y


class TerrainBrushItem(QGraphicsPathItem):
    """Drawable terrain feature (mountains, forests, etc)."""

    def __init__(self, terrain_type: str, color: QColor):
        super().__init__()
        self.terrain_type = terrain_type
        self.setPath(QPainterPath())

        # Set appearance based on terrain type
        if terrain_type == "mountain":
            pen = QPen(QColor("#8B4513"), 3)  # Brown
            self.setPen(pen)
            self.setBrush(QBrush(QColor(139, 69, 19, 100)))  # Semi-transparent brown
        elif terrain_type == "forest":
            pen = QPen(QColor("#228B22"), 2)  # Forest green
            self.setPen(pen)
            self.setBrush(QBrush(QColor(34, 139, 34, 100)))
        elif terrain_type == "water":
            pen = QPen(QColor("#4169E1"), 2)  # Royal blue
            self.setPen(pen)
            self.setBrush(QBrush(QColor(65, 105, 225, 80)))
        elif terrain_type == "desert":
            pen = QPen(QColor("#EDC9AF"), 2)  # Desert sand
            self.setPen(pen)
            self.setBrush(QBrush(QColor(237, 201, 175, 100)))
        else:  # Custom
            pen = QPen(color, 2)
            self.setPen(pen)
            self.setBrush(QBrush(color))

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)


class FactionBorderItem(QGraphicsPathItem):
    """Irregular faction border."""

    def __init__(self, faction_id: str, faction_name: str, border_color: QColor):
        super().__init__()
        self.faction_id = faction_id
        self.faction_name = faction_name
        self.border_color = border_color

        pen = QPen(border_color, 3)
        pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)

        # Semi-transparent fill
        fill_color = QColor(border_color)
        fill_color.setAlpha(30)
        self.setBrush(QBrush(fill_color))

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setToolTip(f"<b>{faction_name}</b><br>Territory Border")


class ShapeItem(QGraphicsItem):
    """Basic shape item (circle, rectangle, or polygon).

    Supports projection-aware rendering for spherical maps.
    """

    def __init__(self, shape_type: str, color: QColor, name: str = "", projection_aware: bool = False):
        super().__init__()
        self.shape_type = shape_type  # "circle", "rectangle", "polygon"
        self.shape_color = color
        self.shape_name = name
        self.points: List[QPointF] = []
        self.rect = QRectF()
        self.projection_aware = projection_aware  # If True, adapts to projection mode
        self.map_width = 0
        self.map_height = 0

        pen = QPen(color, 2)
        self.pen_color = color
        self.brush_color = QColor(color)
        self.brush_color.setAlpha(60)

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setToolTip(f"{shape_type.capitalize()}: {name}" if name else shape_type.capitalize())

    def boundingRect(self) -> QRectF:
        if self.shape_type in ["circle", "rectangle"] and self.rect.isValid():
            return self.rect.adjusted(-5, -5, 5, 5)
        elif self.shape_type == "polygon" and self.points:
            poly = QPolygonF(self.points)
            return poly.boundingRect().adjusted(-5, -5, 5, 5)
        return QRectF()

    def paint(self, painter: QPainter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.pen_color, 2))
        painter.setBrush(QBrush(self.brush_color))

        # If projection-aware and in sphere mode, clip to ellipse
        if self.projection_aware and self.map_width > 0 and self.map_height > 0:
            # Check if canvas is in sphere mode (would need to be passed in)
            # For now, just draw normally - full projection support would need canvas reference
            pass

        if self.shape_type == "circle" and self.rect.isValid():
            painter.drawEllipse(self.rect)
        elif self.shape_type == "rectangle" and self.rect.isValid():
            painter.drawRect(self.rect)
        elif self.shape_type == "polygon" and len(self.points) > 2:
            painter.drawPolygon(QPolygonF(self.points))

    def set_rect(self, rect: QRectF):
        """Set the rectangle for circle or rectangle shapes."""
        self.prepareGeometryChange()
        self.rect = rect
        self.update()

    def set_points(self, points: List[QPointF]):
        """Set points for polygon shape."""
        self.prepareGeometryChange()
        self.points = points
        self.update()


class LatLongGridItem(QGraphicsItem):
    """Latitude/longitude grid overlay."""

    def __init__(self, width: float, height: float, lat_spacing: int = 30, lon_spacing: int = 30):
        super().__init__()
        self.map_width = width
        self.map_height = height
        self.lat_spacing = lat_spacing
        self.lon_spacing = lon_spacing
        self.visible_grid = True

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.map_width, self.map_height)

    def paint(self, painter: QPainter, option, widget):
        if not self.visible_grid:
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Get the current scale factor from the view to make labels scale-invariant
        scale_factor = 1.0
        if widget and hasattr(widget.parent(), 'transform'):
            transform = widget.parent().transform()
            scale_factor = transform.m11()  # Get x-axis scale

        # Grid lines - thicker and more visible
        pen = QPen(QColor(0, 0, 0, 120), 2 / scale_factor)
        pen.setStyle(Qt.PenStyle.SolidLine)
        painter.setPen(pen)

        # Draw latitude lines
        for lat in range(-90, 91, self.lat_spacing):
            x1, y = MapProjection.sphere_to_mercator(lat, -180, self.map_width, self.map_height)
            x2, _ = MapProjection.sphere_to_mercator(lat, 180, self.map_width, self.map_height)
            painter.drawLine(int(0), int(y), int(self.map_width), int(y))

            # Label all lines with scale-invariant font size
            font = QFont("Arial", int(10 / scale_factor), QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QColor(0, 0, 0, 200))
            label = f"{abs(lat)}°{'N' if lat > 0 else 'S' if lat < 0 else ''}"
            painter.drawText(int(10 / scale_factor), int(y - 5 / scale_factor), label)

        # Draw longitude lines
        pen = QPen(QColor(0, 0, 0, 120), 2 / scale_factor)
        pen.setStyle(Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        for lon in range(-180, 181, self.lon_spacing):
            x, y1 = MapProjection.sphere_to_mercator(-85, lon, self.map_width, self.map_height)
            _, y2 = MapProjection.sphere_to_mercator(85, lon, self.map_width, self.map_height)
            painter.drawLine(int(x), int(y1), int(x), int(y2))

            # Label all lines with scale-invariant font size
            font = QFont("Arial", int(10 / scale_factor), QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QColor(0, 0, 0, 200))
            label = f"{abs(lon)}°{'E' if lon > 0 else 'W' if lon < 0 else ''}"
            painter.drawText(int(x + 5 / scale_factor), int(25 / scale_factor), label)


class ClimateZoneOverlay(QGraphicsItem):
    """Visual overlay for climate zones."""

    def __init__(self, width: float, height: float, climate_zones: List[ClimateZone] = None):
        super().__init__()
        self.map_width = width
        self.map_height = height
        self.climate_zones = climate_zones or []
        self.visible_zones = False

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.map_width, self.map_height)

    def paint(self, painter: QPainter, option, widget):
        if not self.visible_zones or not self.climate_zones:
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Climate zone colors
        zone_colors = {
            "tropical": QColor(255, 0, 0, 40),  # Red
            "subtropical": QColor(255, 165, 0, 40),  # Orange
            "temperate": QColor(0, 255, 0, 40),  # Green
            "continental": QColor(255, 255, 0, 40),  # Yellow
            "polar": QColor(0, 0, 255, 40),  # Blue
            "arctic": QColor(200, 200, 255, 40),  # Light blue
            "desert": QColor(237, 201, 175, 40),  # Tan
        }

        for zone in self.climate_zones:
            # Get zone boundaries (simplified - could be more complex)
            zone_name_lower = zone.zone_name.lower()
            color = zone_colors.get(zone_name_lower, QColor(128, 128, 128, 40))

            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)

            # Draw zone based on typical latitudes
            if "tropical" in zone_name_lower:
                # -23.5 to 23.5 degrees
                _, y1 = MapProjection.sphere_to_mercator(23.5, 0, self.map_width, self.map_height)
                _, y2 = MapProjection.sphere_to_mercator(-23.5, 0, self.map_width, self.map_height)
                painter.drawRect(0, int(y1), int(self.map_width), int(y2 - y1))
            elif "polar" in zone_name_lower or "arctic" in zone_name_lower:
                # > 66.5 degrees N/S
                _, y1 = MapProjection.sphere_to_mercator(90, 0, self.map_width, self.map_height)
                _, y2 = MapProjection.sphere_to_mercator(66.5, 0, self.map_width, self.map_height)
                painter.drawRect(0, int(y1), int(self.map_width), int(y2 - y1))

                _, y3 = MapProjection.sphere_to_mercator(-66.5, 0, self.map_width, self.map_height)
                _, y4 = MapProjection.sphere_to_mercator(-90, 0, self.map_width, self.map_height)
                painter.drawRect(0, int(y3), int(self.map_width), int(y4 - y3))


class GridOverlay(QGraphicsItem):
    """Square or hexagonal grid overlay."""

    def __init__(self, width: float, height: float, grid_type: str = "square",
                 cell_size: int = 50, color: str = "#000000", opacity: float = 0.3):
        super().__init__()
        self.map_width = width
        self.map_height = height
        self.grid_type = grid_type
        self.cell_size = cell_size
        self.grid_color = QColor(color)
        self.grid_color.setAlpha(int(opacity * 255))
        self.visible_grid = True

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.map_width, self.map_height)

    def paint(self, painter: QPainter, option, widget):
        if not self.visible_grid:
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.grid_color, 1)
        painter.setPen(pen)

        if self.grid_type == "square":
            # Draw vertical lines
            x = 0
            while x <= self.map_width:
                painter.drawLine(int(x), 0, int(x), int(self.map_height))
                x += self.cell_size

            # Draw horizontal lines
            y = 0
            while y <= self.map_height:
                painter.drawLine(0, int(y), int(self.map_width), int(y))
                y += self.cell_size

        elif self.grid_type == "hex":
            # Simplified hexagonal grid
            hex_height = self.cell_size * 0.866  # sqrt(3)/2
            hex_width = self.cell_size

            row = 0
            y = 0
            while y <= self.map_height:
                col = 0
                x = (self.cell_size / 2) if (row % 2 == 1) else 0

                while x <= self.map_width:
                    # Draw hexagon center point
                    painter.drawPoint(int(x), int(y))
                    x += hex_width
                    col += 1

                y += hex_height
                row += 1


class EnhancedMapCanvas(QGraphicsView):
    """Enhanced map canvas with spherical projection and drawing tools."""

    element_clicked = pyqtSignal(object, str)
    content_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene()
        self.setScene(self.scene)

        # Map state
        self.current_map: Optional[WorldMap] = None
        self.base_map_item: Optional[QGraphicsPixmapItem] = None
        self.associated_planet: Optional[Planet] = None

        # Projection mode
        self.projection_mode = "flat"  # "flat" or "sphere"

        # Grid and overlays
        self.grid_overlay: Optional[GridOverlay] = None
        self.lat_long_grid: Optional[LatLongGridItem] = None
        self.climate_overlay: Optional[ClimateZoneOverlay] = None

        # Drawing state
        self.tool_mode = "select"  # select, pan, add_place, draw_terrain, draw_border, draw_circle, draw_rectangle, draw_polygon, draw_freehand, draw_pen
        self.current_terrain_type = "mountain"
        self.current_terrain_color = QColor("#8B4513")  # Default mountain brown
        self.current_shape_color = QColor("#FF6B6B")  # Default shape color
        self.current_pen_color = QColor("#000000")  # Default pen color (black)
        self.current_pen_width = 3  # Default pen width
        self.current_shape_type = "circle"
        self.current_drawing: Optional[QPainterPath] = None
        self.current_drawing_item = None  # Can be QGraphicsPathItem or ShapeItem
        self.drawing_points: List[QPointF] = []
        self.shape_start_pos: Optional[QPointF] = None
        self.is_drawing_pen = False  # Track if currently drawing with pen

        # Undo/redo stacks
        self.undo_stack: List = []
        self.redo_stack: List = []
        self.max_undo = 20

        # Configure view
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def set_projection_mode(self, mode: str):
        """Set projection mode (flat or sphere)."""
        self.projection_mode = mode
        if self.current_map:
            self._apply_projection_view()
            self.refresh_overlays()

    def _apply_projection_view(self):
        """Apply visual projection transformation."""
        if not self.current_map or not self.base_map_item:
            return

        if self.projection_mode == "sphere":
            # Apply elliptical mask to create spherical appearance
            width = self.current_map.width
            height = self.current_map.height

            # Create elliptical clipping path
            path = QPainterPath()
            path.addEllipse(0, 0, width, height)

            # Apply clip to base map
            self.base_map_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsToShape, True)

            # Add a sphere border overlay
            if hasattr(self, 'sphere_border'):
                self.scene.removeItem(self.sphere_border)

            self.sphere_border = self.scene.addEllipse(
                0, 0, width, height,
                QPen(QColor(0, 0, 0, 150), 3),
                QBrush(Qt.BrushStyle.NoBrush)
            )
            self.sphere_border.setZValue(100)
        else:
            # Remove sphere border for flat view
            if hasattr(self, 'sphere_border') and self.sphere_border:
                self.scene.removeItem(self.sphere_border)
                self.sphere_border = None

    def set_associated_planet(self, planet: Optional[Planet]):
        """Set the planet this map is associated with."""
        self.associated_planet = planet
        if planet and self.current_map:
            self.refresh_overlays()

    def load_map(self, world_map: WorldMap, planet: Optional[Planet] = None):
        """Load a map onto the canvas."""
        self.current_map = world_map
        self.associated_planet = planet
        self.scene.clear()
        self.base_map_item = None
        self.lat_long_grid = None
        self.climate_overlay = None
        self.sphere_border = None

        # Load base map image or create blank canvas
        if world_map.image_path and os.path.exists(world_map.image_path):
            pixmap = QPixmap(world_map.image_path)
            if not pixmap.isNull():
                self.base_map_item = self.scene.addPixmap(pixmap)
                self.base_map_item.setZValue(-10)
                world_map.width = pixmap.width()
                world_map.height = pixmap.height()
                self.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())
        else:
            # Create default map size with a blank background - larger for more detail
            if world_map.width == 0:
                world_map.width = 2048
                world_map.height = 1024

            # Create a light background to draw on
            background = QGraphicsRectItem(0, 0, world_map.width, world_map.height)
            background.setBrush(QBrush(QColor(240, 240, 240)))  # Light gray background
            background.setPen(QPen(Qt.PenStyle.NoPen))
            background.setZValue(-10)
            self.scene.addItem(background)
            self.base_map_item = background

            self.scene.setSceneRect(0, 0, world_map.width, world_map.height)

        # Apply projection view (sphere or flat)
        self._apply_projection_view()

        # Add overlays
        self.refresh_overlays()

        # Refresh all elements
        self.refresh_elements()

    def refresh_overlays(self):
        """Refresh grids and overlays."""
        if not self.current_map:
            return

        # Remove old overlays safely
        try:
            if self.grid_overlay and self.grid_overlay.scene():
                self.scene.removeItem(self.grid_overlay)
        except RuntimeError:
            pass  # Item already deleted

        try:
            if self.lat_long_grid and self.lat_long_grid.scene():
                self.scene.removeItem(self.lat_long_grid)
        except RuntimeError:
            pass  # Item already deleted

        try:
            if self.climate_overlay and self.climate_overlay.scene():
                self.scene.removeItem(self.climate_overlay)
        except RuntimeError:
            pass  # Item already deleted

        # Add square/hex grid from map settings
        if self.current_map.grid_settings:
            self.grid_overlay = GridOverlay(
                self.current_map.width,
                self.current_map.height,
                grid_type=self.current_map.grid_settings.grid_type,
                cell_size=self.current_map.grid_settings.cell_size,
                color=self.current_map.grid_settings.color,
                opacity=self.current_map.grid_settings.opacity
            )
            self.grid_overlay.setZValue(4)  # Between background and elements
            self.grid_overlay.visible_grid = self.current_map.grid_settings.enabled
            self.scene.addItem(self.grid_overlay)

        # Add lat/long grid with larger, more visible spacing
        self.lat_long_grid = LatLongGridItem(
            self.current_map.width,
            self.current_map.height,
            lat_spacing=30,
            lon_spacing=30
        )
        self.lat_long_grid.setZValue(5)  # Above background and drawn elements, below sphere border
        self.lat_long_grid.visible_grid = False  # Start hidden
        self.scene.addItem(self.lat_long_grid)

        # Add climate overlay if planet has climate data
        if self.associated_planet and hasattr(self.associated_planet, 'climate_zones'):
            self.climate_overlay = ClimateZoneOverlay(
                self.current_map.width,
                self.current_map.height,
                self.associated_planet.climate_zones
            )
            self.climate_overlay.setZValue(-4)
            self.climate_overlay.visible_zones = False  # Start hidden
            self.scene.addItem(self.climate_overlay)

    def toggle_grid(self, visible: bool):
        """Toggle square/hex grid visibility."""
        if self.grid_overlay:
            self.grid_overlay.visible_grid = visible
            self.grid_overlay.update()

    def toggle_lat_long_grid(self, visible: bool):
        """Toggle latitude/longitude grid visibility."""
        if self.lat_long_grid:
            self.lat_long_grid.visible_grid = visible
            self.lat_long_grid.update()

    def toggle_climate_zones(self, visible: bool):
        """Toggle climate zone overlay visibility."""
        if self.climate_overlay:
            self.climate_overlay.visible_zones = visible
            self.climate_overlay.update()

    def set_tool_mode(self, mode: str, terrain_type: str = "mountain", shape_type: str = "circle"):
        """Set the current tool mode."""
        self.tool_mode = mode
        self.current_terrain_type = terrain_type
        self.current_shape_type = shape_type

        if mode == "pan":
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif mode in ["draw_terrain", "draw_border", "draw_circle", "draw_rectangle", "draw_polygon", "draw_freehand", "draw_pen"]:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            # Select mode or default
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        """Handle mouse press for drawing."""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self.mapToScene(event.pos())

            if self.tool_mode == "draw_terrain":
                self.start_terrain_drawing(pos)
            elif self.tool_mode == "draw_border":
                self.start_border_drawing(pos)
            elif self.tool_mode == "draw_circle":
                self.start_shape_drawing(pos, "circle")
            elif self.tool_mode == "draw_rectangle":
                self.start_shape_drawing(pos, "rectangle")
            elif self.tool_mode == "draw_polygon":
                self.start_polygon_drawing(pos)
            elif self.tool_mode == "draw_freehand":
                self.start_freehand_drawing(pos)
            elif self.tool_mode == "draw_pen":
                self.start_pen_drawing(pos)
        elif event.button() == Qt.MouseButton.RightButton:
            # Finish polygon if in polygon mode, otherwise show context menu
            if self.tool_mode == "draw_polygon" and self.drawing_points:
                self.finish_polygon_drawing()
                self.set_tool_mode("select")
            else:
                self.show_context_menu(event.pos())
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle mouse move for drawing."""
        pos = self.mapToScene(event.pos())

        if self.tool_mode in ["draw_terrain", "draw_border"] and self.current_drawing:
            self.continue_drawing(pos)
        elif self.tool_mode in ["draw_circle", "draw_rectangle"] and self.shape_start_pos:
            self.continue_shape_drawing(pos)
        elif self.tool_mode == "draw_freehand" and self.current_drawing:
            self.continue_freehand_drawing(pos)
        elif self.tool_mode == "draw_pen" and self.is_drawing_pen:
            self.continue_pen_drawing(pos)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release to finish drawing."""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.tool_mode in ["draw_terrain", "draw_border"] and self.current_drawing:
                self.finish_drawing()
                # Auto-return to select mode after drawing
                self.set_tool_mode("select")
            elif self.tool_mode in ["draw_circle", "draw_rectangle"] and self.shape_start_pos:
                self.finish_shape_drawing()
                # Auto-return to select mode after drawing
                self.set_tool_mode("select")
            elif self.tool_mode == "draw_freehand" and self.current_drawing:
                self.finish_freehand_drawing()
                # Auto-return to select mode after drawing
                self.set_tool_mode("select")
            elif self.tool_mode == "draw_pen" and self.is_drawing_pen:
                self.finish_pen_drawing()
                # Don't auto-return to select mode - stay in pen mode for continuous drawing

        super().mouseReleaseEvent(event)

    def start_terrain_drawing(self, pos: QPointF):
        """Start drawing terrain."""
        self.current_drawing = QPainterPath()
        self.current_drawing.moveTo(pos)
        self.drawing_points = [pos]

        # Create temporary drawing item using current color
        self.current_drawing_item = TerrainBrushItem(self.current_terrain_type, self.current_terrain_color)
        self.scene.addItem(self.current_drawing_item)

    def start_border_drawing(self, pos: QPointF):
        """Start drawing faction border."""
        self.current_drawing = QPainterPath()
        self.current_drawing.moveTo(pos)
        self.drawing_points = [pos]

        # Create temporary border item
        self.current_drawing_item = FactionBorderItem("", "New Border", QColor("#FF0000"))
        self.scene.addItem(self.current_drawing_item)

    def continue_drawing(self, pos: QPointF):
        """Continue drawing."""
        if self.current_drawing and self.current_drawing_item:
            self.current_drawing.lineTo(pos)
            self.drawing_points.append(pos)
            self.current_drawing_item.setPath(self.current_drawing)

    def finish_drawing(self):
        """Finish drawing."""
        if self.current_drawing_item:
            # Smooth the path
            smoothed = self.smooth_path(self.drawing_points)
            self.current_drawing_item.setPath(smoothed)

            self.content_changed.emit()

        self.current_drawing = None
        self.current_drawing_item = None
        self.drawing_points.clear()

    def smooth_path(self, points: List[QPointF]) -> QPainterPath:
        """Smooth a path using Bezier curves."""
        if len(points) < 2:
            path = QPainterPath()
            if points:
                path.addEllipse(points[0], 5, 5)
            return path

        path = QPainterPath()
        path.moveTo(points[0])

        # Use quadratic curves for smoothing
        for i in range(1, len(points) - 1):
            control = points[i]
            end = QPointF(
                (points[i].x() + points[i + 1].x()) / 2,
                (points[i].y() + points[i + 1].y()) / 2
            )
            path.quadTo(control, end)

        if len(points) > 1:
            path.lineTo(points[-1])

        return path

    def start_shape_drawing(self, pos: QPointF, shape_type: str):
        """Start drawing a shape (circle or rectangle)."""
        self.shape_start_pos = pos
        self.current_shape_type = shape_type

        # Create temporary shape item
        self.current_drawing_item = ShapeItem(shape_type, self.current_shape_color, f"New {shape_type.title()}")
        self.scene.addItem(self.current_drawing_item)
        self.current_drawing_item.setZValue(3)  # Above base map but below UI overlays

    def continue_shape_drawing(self, pos: QPointF):
        """Update shape as user drags."""
        if not self.shape_start_pos or not self.current_drawing_item:
            return

        if self.current_shape_type == "circle":
            # Calculate radius from start to current position
            dx = pos.x() - self.shape_start_pos.x()
            dy = pos.y() - self.shape_start_pos.y()
            radius = (dx**2 + dy**2)**0.5

            # Update circle
            self.current_drawing_item.rect = QRectF(
                self.shape_start_pos.x() - radius,
                self.shape_start_pos.y() - radius,
                radius * 2,
                radius * 2
            )
        elif self.current_shape_type == "rectangle":
            # Update rectangle from start to current position
            self.current_drawing_item.rect = QRectF(self.shape_start_pos, pos).normalized()

        self.current_drawing_item.update()

    def finish_shape_drawing(self):
        """Finish drawing a shape."""
        if self.current_drawing_item:
            self.content_changed.emit()

        self.shape_start_pos = None
        self.current_drawing_item = None

    def start_polygon_drawing(self, pos: QPointF):
        """Start or continue drawing a polygon."""
        if not self.drawing_points:
            # First point - create new polygon
            self.drawing_points = [pos]
            self.current_drawing_item = ShapeItem("polygon", self.current_shape_color, "New Polygon")
            self.current_drawing_item.points = [pos]
            self.scene.addItem(self.current_drawing_item)
            self.current_drawing_item.setZValue(3)
        else:
            # Add point to existing polygon
            self.drawing_points.append(pos)
            self.current_drawing_item.points = self.drawing_points.copy()
            self.current_drawing_item.update()

    def finish_polygon_drawing(self):
        """Finish drawing a polygon."""
        if self.current_drawing_item and len(self.drawing_points) >= 3:
            # Polygon is complete
            self.content_changed.emit()
        elif self.current_drawing_item:
            # Not enough points, remove it
            self.scene.removeItem(self.current_drawing_item)

        self.drawing_points.clear()
        self.current_drawing_item = None

    def start_freehand_drawing(self, pos: QPointF):
        """Start freehand drawing that will be converted to a shape."""
        self.current_drawing = QPainterPath()
        self.current_drawing.moveTo(pos)
        self.drawing_points = [pos]

        # Create temporary path item to show the stroke
        self.current_drawing_item = QGraphicsPathItem()
        pen = QPen(self.current_shape_color, 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.current_drawing_item.setPen(pen)
        self.scene.addItem(self.current_drawing_item)
        self.current_drawing_item.setZValue(3)

    def continue_freehand_drawing(self, pos: QPointF):
        """Continue freehand drawing."""
        if self.current_drawing and self.current_drawing_item:
            self.current_drawing.lineTo(pos)
            self.drawing_points.append(pos)
            self.current_drawing_item.setPath(self.current_drawing)

    def finish_freehand_drawing(self):
        """Finish freehand drawing and convert to shape."""
        if not self.drawing_points or len(self.drawing_points) < 3:
            # Not enough points, just remove
            if self.current_drawing_item:
                self.scene.removeItem(self.current_drawing_item)
            self.current_drawing = None
            self.current_drawing_item = None
            self.drawing_points.clear()
            return

        # Remove the temporary path item
        if self.current_drawing_item:
            self.scene.removeItem(self.current_drawing_item)

        # If in sphere mode, adjust points to account for projection
        adjusted_points = self.drawing_points
        if self.projection_mode == "sphere" and self.current_map:
            adjusted_points = self._adjust_points_for_projection(self.drawing_points)

        # Analyze the freehand stroke to determine shape type
        shape_type, shape_data = self._analyze_freehand_stroke(adjusted_points)

        # Create the appropriate shape (projection-aware)
        shape_item = ShapeItem(
            shape_type,
            self.current_shape_color,
            f"Freehand {shape_type.title()}",
            projection_aware=True
        )
        self.scene.addItem(shape_item)
        shape_item.setZValue(3)

        # Store map dimensions for projection awareness
        if self.current_map:
            shape_item.map_width = self.current_map.width
            shape_item.map_height = self.current_map.height

        if shape_type == "circle":
            shape_item.set_rect(shape_data)
        elif shape_type == "rectangle":
            shape_item.set_rect(shape_data)
        elif shape_type == "polygon":
            shape_item.set_points(shape_data)

        self.content_changed.emit()

        # Clean up
        self.current_drawing = None
        self.current_drawing_item = None
        self.drawing_points.clear()

    def start_pen_drawing(self, pos: QPointF):
        """Start pen drawing (continuous freehand line)."""
        self.is_drawing_pen = True
        self.current_drawing = QPainterPath()
        self.current_drawing.moveTo(pos)
        self.drawing_points = [pos]

        # Create path item for visual feedback
        pen = QPen(self.current_pen_color, self.current_pen_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self.current_drawing_item = self.scene.addPath(self.current_drawing, pen)
        self.current_drawing_item.setZValue(10)  # Draw on top

    def continue_pen_drawing(self, pos: QPointF):
        """Continue pen drawing by adding line segment."""
        if not self.current_drawing or not self.is_drawing_pen:
            return

        self.current_drawing.lineTo(pos)
        self.drawing_points.append(pos)

        # Update path item
        if self.current_drawing_item:
            self.current_drawing_item.setPath(self.current_drawing)

    def finish_pen_drawing(self):
        """Finish pen drawing and save as permanent path."""
        if not self.drawing_points or len(self.drawing_points) < 2:
            # Not enough points, just remove
            if self.current_drawing_item:
                self.scene.removeItem(self.current_drawing_item)
            self.current_drawing = None
            self.current_drawing_item = None
            self.drawing_points.clear()
            self.is_drawing_pen = False
            return

        # The current_drawing_item is already in the scene with the correct path
        # Just finalize it and update its properties to be permanent
        if self.current_drawing_item:
            # Make it selectable and movable
            self.current_drawing_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self.current_drawing_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            self.current_drawing_item.setZValue(3)  # Normal drawing layer

            # Add to undo stack
            self.undo_stack.append(('add', self.current_drawing_item))
            if len(self.undo_stack) > self.max_undo:
                self.undo_stack.pop(0)
            self.redo_stack.clear()

        self.content_changed.emit()

        # Clean up for next drawing
        self.current_drawing = None
        self.current_drawing_item = None
        self.drawing_points.clear()
        self.is_drawing_pen = False

    def _analyze_freehand_stroke(self, points: List[QPointF]) -> Tuple[str, Any]:
        """Analyze freehand stroke to determine best-fit shape.

        Returns:
            Tuple of (shape_type, shape_data)
            - shape_type: "circle", "rectangle", or "polygon"
            - shape_data: QRectF for circle/rectangle, List[QPointF] for polygon
        """
        if len(points) < 3:
            # Default to small circle
            center = points[0]
            return "circle", QRectF(center.x() - 20, center.y() - 20, 40, 40)

        # Calculate bounding box
        min_x = min(p.x() for p in points)
        max_x = max(p.x() for p in points)
        min_y = min(p.y() for p in points)
        max_y = max(p.y() for p in points)

        width = max_x - min_x
        height = max_y - min_y

        # Check if stroke is closed (end near start)
        start_point = points[0]
        end_point = points[-1]
        distance = ((end_point.x() - start_point.x())**2 + (end_point.y() - start_point.y())**2)**0.5
        is_closed = distance < min(width, height) * 0.2  # Within 20% of smaller dimension

        if not is_closed:
            # Open stroke - create polygon from simplified path
            simplified = self._simplify_points(points, tolerance=10)
            return "polygon", simplified

        # Closed stroke - determine if circle or rectangle

        # Calculate circularity: how close to a circle
        perimeter = self._calculate_perimeter(points)
        area = width * height
        circularity = (4 * math.pi * area) / (perimeter * perimeter) if perimeter > 0 else 0

        # Calculate aspect ratio
        aspect_ratio = width / height if height > 0 else 1.0
        if aspect_ratio > 1:
            aspect_ratio = 1.0 / aspect_ratio

        # Decide shape based on metrics
        if circularity > 0.7:  # Very circular
            # Create circle using bounding box
            center_x = (min_x + max_x) / 2
            center_y = (min_y + max_y) / 2
            radius = max(width, height) / 2
            return "circle", QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2)

        elif aspect_ratio > 0.7:  # Roughly square/rectangular
            # Create rectangle
            return "rectangle", QRectF(min_x, min_y, width, height)

        else:
            # Irregular shape - use simplified polygon
            simplified = self._simplify_points(points, tolerance=15)
            return "polygon", simplified

    def _simplify_points(self, points: List[QPointF], tolerance: float = 10) -> List[QPointF]:
        """Simplify point list using Ramer-Douglas-Peucker algorithm.

        Args:
            points: Original point list
            tolerance: Maximum distance for simplification

        Returns:
            Simplified point list
        """
        if len(points) <= 2:
            return points

        # Find point with maximum distance from line between first and last
        first = points[0]
        last = points[-1]
        max_distance = 0
        max_index = 0

        for i in range(1, len(points) - 1):
            distance = self._perpendicular_distance(points[i], first, last)
            if distance > max_distance:
                max_distance = distance
                max_index = i

        # If max distance is greater than tolerance, recursively simplify
        if max_distance > tolerance:
            # Recursive call
            left = self._simplify_points(points[:max_index + 1], tolerance)
            right = self._simplify_points(points[max_index:], tolerance)

            # Combine results (remove duplicate middle point)
            return left[:-1] + right
        else:
            # All points between first and last can be removed
            return [first, last]

    def _perpendicular_distance(self, point: QPointF, line_start: QPointF, line_end: QPointF) -> float:
        """Calculate perpendicular distance from point to line."""
        # Vector from line_start to line_end
        dx = line_end.x() - line_start.x()
        dy = line_end.y() - line_start.y()

        # Line length squared
        length_sq = dx * dx + dy * dy

        if length_sq == 0:
            # Line is actually a point
            return ((point.x() - line_start.x())**2 + (point.y() - line_start.y())**2)**0.5

        # Parameter t: projection of point onto line
        t = ((point.x() - line_start.x()) * dx + (point.y() - line_start.y()) * dy) / length_sq
        t = max(0, min(1, t))  # Clamp to line segment

        # Closest point on line
        closest_x = line_start.x() + t * dx
        closest_y = line_start.y() + t * dy

        # Distance from point to closest point
        return ((point.x() - closest_x)**2 + (point.y() - closest_y)**2)**0.5

    def _calculate_perimeter(self, points: List[QPointF]) -> float:
        """Calculate perimeter of polygon defined by points."""
        if len(points) < 2:
            return 0

        perimeter = 0
        for i in range(len(points)):
            p1 = points[i]
            p2 = points[(i + 1) % len(points)]
            distance = ((p2.x() - p1.x())**2 + (p2.y() - p1.y())**2)**0.5
            perimeter += distance

        return perimeter

    def _adjust_points_for_projection(self, points: List[QPointF]) -> List[QPointF]:
        """Adjust points for spherical projection distortion.

        When drawing on a sphere view, points near the edges appear distorted.
        This method compensates for that distortion by adjusting the mercator coordinates.

        Args:
            points: Original points drawn on canvas

        Returns:
            Adjusted points that will look correct in both flat and sphere views
        """
        if not self.current_map:
            return points

        width = self.current_map.width
        height = self.current_map.height
        adjusted = []

        for point in points:
            # Convert screen coordinates to lat/lon
            lat, lon = MapProjection.mercator_to_sphere(
                point.x(), point.y(), width, height
            )

            # Apply distortion compensation based on latitude
            # Near poles (high latitude), Mercator stretches horizontally
            lat_factor = math.cos(math.radians(lat))

            # Calculate center of shape for relative positioning
            if len(points) > 1:
                center_x = sum(p.x() for p in points) / len(points)
                center_y = sum(p.y() for p in points) / len(points)
                center_lat, center_lon = MapProjection.mercator_to_sphere(
                    center_x, center_y, width, height
                )
            else:
                center_lat, center_lon = lat, lon

            # Adjust longitude relative to center based on latitude distortion
            if abs(lat) > 60:  # High latitude
                # Compress horizontally near poles
                lon_diff = lon - center_lon
                adjusted_lon = center_lon + (lon_diff * lat_factor)
            else:
                adjusted_lon = lon

            # Convert back to mercator coordinates
            adj_x, adj_y = MapProjection.sphere_to_mercator(
                lat, adjusted_lon, width, height
            )

            adjusted.append(QPointF(adj_x, adj_y))

        return adjusted

    def _apply_spherical_clipping(self, item: QGraphicsItem):
        """Apply spherical clipping to an item for better appearance in sphere mode.

        Args:
            item: Graphics item to clip
        """
        if not self.current_map:
            return

        # Create elliptical clip path
        width = self.current_map.width
        height = self.current_map.height

        clip_path = QPainterPath()
        clip_path.addEllipse(0, 0, width, height)

        # This would need to be applied to the item
        # In practice, items outside the ellipse will be clipped by the view

    def refresh_elements(self):
        """Refresh all map elements."""
        if not self.current_map:
            return

        # Remove existing element items (keep overlays and base)
        for item in list(self.scene.items()):
            if isinstance(item, (MapElementItem, MapLandmarkItem)):
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

    def wheelEvent(self, event):
        """Handle mouse wheel for zooming."""
        zoom_in_factor = 1.15
        zoom_out_factor = 1 / zoom_in_factor

        if event.angleDelta().y() > 0:
            zoom_factor = zoom_in_factor
        else:
            zoom_factor = zoom_out_factor

        self.scale(zoom_factor, zoom_factor)

    def reset_view(self):
        """Reset zoom and center the view on the map."""
        if not self.current_map:
            return

        # Reset transformation
        self.resetTransform()

        # Fit the scene in view
        if self.scene.sceneRect().isValid():
            self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

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

    def show_context_menu(self, pos):
        """Show context menu at position."""
        scene_pos = self.mapToScene(pos)
        items = self.scene.items(scene_pos)

        # Find the first element item
        element_item = None
        for item in items:
            if isinstance(item, (MapElementItem, MapLandmarkItem)):
                element_item = item
                break
            elif isinstance(item, (TerrainBrushItem, FactionBorderItem)):
                element_item = item
                break

        if element_item:
            menu = QMenu(self)
            delete_action = menu.addAction("Delete")

            action = menu.exec(self.mapToGlobal(pos))
            if action == delete_action:
                self.delete_item(element_item)

    def delete_item(self, item):
        """Delete an item from the map."""
        if isinstance(item, MapElementItem):
            # Remove from data model
            element = item.element
            element_type = item.element_type

            if element_type == "place":
                if element in self.current_map.places:
                    self.current_map.places.remove(element)
            elif element_type == "landmark":
                if element in self.current_map.landmarks:
                    self.current_map.landmarks.remove(element)
            elif element_type == "event":
                if element in self.current_map.events:
                    self.current_map.events.remove(element)

            # Remove from scene
            self.scene.removeItem(item)
            self.content_changed.emit()

        elif isinstance(item, MapLandmarkItem):
            # Remove landmark
            if item.landmark in self.current_map.landmarks:
                self.current_map.landmarks.remove(item.landmark)
            self.scene.removeItem(item)
            self.content_changed.emit()

        elif isinstance(item, (TerrainBrushItem, FactionBorderItem)):
            # Remove drawn item (terrain or border)
            self.scene.removeItem(item)
            self.content_changed.emit()

    def keyPressEvent(self, event):
        """Handle key press events."""
        if event.key() == Qt.Key.Key_Delete:
            # Delete selected items
            selected_items = self.scene.selectedItems()
            for item in selected_items:
                if isinstance(item, (MapElementItem, MapLandmarkItem, TerrainBrushItem, FactionBorderItem)):
                    self.delete_item(item)
        else:
            super().keyPressEvent(event)
