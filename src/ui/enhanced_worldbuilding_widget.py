"""Enhanced worldbuilding widget with individual elements and AI generation."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTextEdit, QInputDialog, QMessageBox,
    QSplitter, QFrame, QComboBox, QScrollArea
)
from PyQt6.QtCore import pyqtSignal, Qt
from typing import Dict, List
import uuid


class WorldElement(QWidget):
    """Individual worldbuilding element (e.g., a specific god, planet, event)."""

    content_changed = pyqtSignal()

    def __init__(self, element_id: str, name: str, element_type: str):
        """Initialize world element."""
        super().__init__()
        self.element_id = element_id
        self.name = name
        self.element_type = element_type
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header with name
        header_layout = QHBoxLayout()

        self.name_label = QLabel(self.name)
        self.name_label.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header_layout.addWidget(self.name_label)

        header_layout.addStretch()

        # Type badge
        type_badge = QLabel(self.element_type)
        type_badge.setStyleSheet("""
            background-color: #e0e7ff;
            color: #6366f1;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 500;
        """)
        header_layout.addWidget(type_badge)

        layout.addLayout(header_layout)

        # Description editor
        desc_label = QLabel("Description:")
        desc_label.setStyleSheet("font-size: 12px; font-weight: 500; color: #6b7280;")
        layout.addWidget(desc_label)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(f"Describe this {self.element_type.lower()}...")
        self.description_edit.setStyleSheet("""
            QTextEdit {
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 12px;
                font-size: 13px;
            }
        """)
        self.description_edit.textChanged.connect(self.content_changed.emit)
        layout.addWidget(self.description_edit)

        # AI enhance button
        ai_button = QPushButton("✨ AI Enhance")
        ai_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 500;
                color: #6366f1;
            }
            QPushButton:hover {
                background-color: #f3f4f6;
                border-color: #6366f1;
            }
        """)
        ai_button.clicked.connect(self._enhance_with_ai)
        layout.addWidget(ai_button)

    def _enhance_with_ai(self):
        """Enhance element with AI."""
        # TODO: Integrate with AI
        QMessageBox.information(
            self,
            "AI Enhancement",
            "AI enhancement will expand and improve this element's description."
        )

    def get_content(self) -> str:
        """Get element content."""
        return self.description_edit.toPlainText()

    def set_content(self, content: str):
        """Set element content."""
        self.description_edit.setPlainText(content)


class WorldBuildingSection(QWidget):
    """A section with individual elements (e.g., Mythology with multiple gods)."""

    content_changed = pyqtSignal()

    def __init__(self, section_name: str):
        """Initialize section."""
        super().__init__()
        self.section_name = section_name
        self.elements: Dict[str, Dict] = {}  # element_id -> {name, content, widget}
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Splitter for list and details
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Element list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        # Section label
        section_label = QLabel(f"{self.section_name} Elements")
        section_label.setStyleSheet("font-size: 13px; font-weight: 600; padding: 4px;")
        left_layout.addWidget(section_label)

        # Element list
        self.element_list = QListWidget()
        self.element_list.setStyleSheet("""
            QListWidget {
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 8px;
                border-radius: 6px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background-color: #6366f1;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #f3f4f6;
            }
        """)
        self.element_list.currentItemChanged.connect(self._on_element_selected)
        left_layout.addWidget(self.element_list)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        add_button = QPushButton("➕ Add")
        add_button.setStyleSheet(self._get_button_style())
        add_button.clicked.connect(self._add_element)
        button_layout.addWidget(add_button)

        ai_gen_button = QPushButton("✨ AI Generate")
        ai_gen_button.setStyleSheet(self._get_button_style())
        ai_gen_button.clicked.connect(self._ai_generate_element)
        button_layout.addWidget(ai_gen_button)

        remove_button = QPushButton("🗑️")
        remove_button.setStyleSheet(self._get_button_style())
        remove_button.setMaximumWidth(40)
        remove_button.clicked.connect(self._remove_element)
        button_layout.addWidget(remove_button)

        left_layout.addLayout(button_layout)

        left_panel.setMaximumWidth(280)
        splitter.addWidget(left_panel)

        # Right: Element details
        self.details_scroll = QScrollArea()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setStyleSheet("border: none; background-color: #fafafa;")

        placeholder = QLabel(f"Add or select a {self.section_name.lower()} element")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #9ca3af; font-size: 14px;")
        self.details_scroll.setWidget(placeholder)

        splitter.addWidget(self.details_scroll)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

    def _get_button_style(self) -> str:
        """Get button style."""
        return """
            QPushButton {
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #f9fafb;
                border-color: #6366f1;
            }
        """

    def _add_element(self):
        """Add new element."""
        name, ok = QInputDialog.getText(
            self,
            f"New {self.section_name} Element",
            f"Enter element name:"
        )

        if ok and name:
            element_id = str(uuid.uuid4())
            self._create_element(element_id, name, "")

    def _create_element(self, element_id: str, name: str, content: str):
        """Create and add element."""
        # Create widget
        element_widget = WorldElement(element_id, name, self.section_name)
        element_widget.set_content(content)
        element_widget.content_changed.connect(self.content_changed.emit)

        # Store element
        self.elements[element_id] = {
            'name': name,
            'content': content,
            'widget': element_widget
        }

        # Add to list
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, element_id)
        self.element_list.addItem(item)

        # Select it
        self.element_list.setCurrentItem(item)

    def _remove_element(self):
        """Remove selected element."""
        current_item = self.element_list.currentItem()
        if not current_item:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete '{current_item.text()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            element_id = current_item.data(Qt.ItemDataRole.UserRole)
            if element_id in self.elements:
                del self.elements[element_id]

            row = self.element_list.row(current_item)
            self.element_list.takeItem(row)

            # Show placeholder
            placeholder = QLabel(f"Add or select a {self.section_name.lower()} element")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #9ca3af; font-size: 14px;")
            self.details_scroll.setWidget(placeholder)

    def _on_element_selected(self, current, previous):
        """Handle element selection."""
        if not current:
            return

        element_id = current.data(Qt.ItemDataRole.UserRole)
        if element_id in self.elements:
            widget = self.elements[element_id]['widget']
            self.details_scroll.setWidget(widget)

    def _ai_generate_element(self):
        """Generate element with AI."""
        # TODO: Integrate with AI agent
        QMessageBox.information(
            self,
            "AI Generation",
            f"AI will generate a new {self.section_name.lower()} element based on your existing worldbuilding."
        )

    def get_elements(self) -> Dict[str, str]:
        """Get all elements as dict."""
        result = {}
        for element_id, data in self.elements.items():
            widget = data['widget']
            result[data['name']] = widget.get_content()
        return result

    def load_elements(self, elements: Dict[str, str]):
        """Load elements from dict."""
        for name, content in elements.items():
            element_id = str(uuid.uuid4())
            self._create_element(element_id, name, content)


class EnhancedWorldBuildingWidget(QWidget):
    """Enhanced worldbuilding with individual elements per section."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize worldbuilding widget."""
        super().__init__()
        self.sections: Dict[str, WorldBuildingSection] = {}
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Minimal header
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(16, 12, 16, 8)

        title = QLabel("🌍 Worldbuilding")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        subtitle = QLabel("Build your world with individual elements")
        subtitle.setStyleSheet("font-size: 12px; color: #6b7280;")
        header_layout.addWidget(subtitle)

        layout.addLayout(header_layout)

        # Section selector and content
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(8, 0, 8, 8)

        # Section list (left sidebar)
        section_list_widget = QWidget()
        section_list_layout = QVBoxLayout(section_list_widget)
        section_list_layout.setContentsMargins(0, 0, 0, 0)

        self.section_list = QListWidget()
        self.section_list.setMaximumWidth(180)
        self.section_list.setStyleSheet("""
            QListWidget {
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 8px;
            }
            QListWidget::item {
                padding: 10px 12px;
                border-radius: 6px;
                margin: 2px 0;
            }
            QListWidget::item:selected {
                background-color: #6366f1;
                color: white;
            }
        """)

        # Add standard sections
        sections = [
            "Mythology", "Planets", "Climate", "History",
            "Politics", "Military", "Economy", "Power Hierarchy"
        ]

        for section in sections:
            self.section_list.addItem(section)
            section_widget = WorldBuildingSection(section)
            section_widget.content_changed.connect(self.content_changed.emit)
            self.sections[section] = section_widget

        self.section_list.currentTextChanged.connect(self._on_section_changed)
        section_list_layout.addWidget(self.section_list)

        content_layout.addWidget(section_list_widget)

        # Section content area
        self.content_stack = QWidget()
        self.content_layout = QVBoxLayout(self.content_stack)
        self.content_layout.setContentsMargins(0, 0, 0, 0)

        content_layout.addWidget(self.content_stack, stretch=1)

        layout.addLayout(content_layout, stretch=1)

        # Select first section
        if self.section_list.count() > 0:
            self.section_list.setCurrentRow(0)

    def _on_section_changed(self, section_name: str):
        """Handle section change."""
        # Clear current content
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        # Show selected section
        if section_name in self.sections:
            self.content_layout.addWidget(self.sections[section_name])

    def load_data(self, worldbuilding):
        """Load worldbuilding data."""
        # Map section names to element fields
        element_fields = {
            "Mythology": worldbuilding.mythology_elements,
            "Planets": worldbuilding.planets_elements,
            "Climate": worldbuilding.climate_elements,
            "History": worldbuilding.history_elements,
            "Politics": worldbuilding.politics_elements,
            "Military": worldbuilding.military_elements,
            "Economy": worldbuilding.economy_elements,
            "Power Hierarchy": worldbuilding.power_hierarchy_elements
        }

        # Load elements for each section
        for section_name, elements in element_fields.items():
            if section_name in self.sections:
                self.sections[section_name].load_elements(elements)

    def get_data(self):
        """Get worldbuilding data."""
        from src.models.project import WorldBuilding

        # Collect elements from each section
        worldbuilding = WorldBuilding(
            mythology_elements=self.sections["Mythology"].get_elements(),
            planets_elements=self.sections["Planets"].get_elements(),
            climate_elements=self.sections["Climate"].get_elements(),
            history_elements=self.sections["History"].get_elements(),
            politics_elements=self.sections["Politics"].get_elements(),
            military_elements=self.sections["Military"].get_elements(),
            economy_elements=self.sections["Economy"].get_elements(),
            power_hierarchy_elements=self.sections["Power Hierarchy"].get_elements()
        )

        return worldbuilding
