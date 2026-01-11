"""Worldbuilding widget with subsections."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QTextEdit, QPushButton, QLabel, QScrollArea, QInputDialog
)
from PyQt6.QtCore import pyqtSignal
from src.models.project import WorldBuilding


class WorldBuildingWidget(QWidget):
    """Widget for worldbuilding with mythology, planets, climate, history, etc."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize worldbuilding widget."""
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        """Initialize user interface."""
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("Worldbuilding")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(header)

        # Create tabs for subsections
        self.tabs = QTabWidget()

        # Standard worldbuilding sections
        self.sections = {
            "Mythology": QTextEdit(),
            "Planets": QTextEdit(),
            "Climate": QTextEdit(),
            "History": QTextEdit(),
            "Politics": QTextEdit(),
            "Military": QTextEdit(),
            "Economy": QTextEdit(),
            "Power Hierarchy": QTextEdit()
        }

        # Add tabs for each section
        for section_name, editor in self.sections.items():
            editor.setPlaceholderText(f"Enter {section_name.lower()} details...")
            editor.textChanged.connect(self.content_changed.emit)
            self.tabs.addTab(editor, section_name)

        # Custom sections tab
        self.custom_sections_widget = QWidget()
        self.custom_sections = {}
        self._setup_custom_sections()
        self.tabs.addTab(self.custom_sections_widget, "Custom Sections")

        layout.addWidget(self.tabs)

        # AI Help button
        ai_button = QPushButton("Get AI Worldbuilding Help")
        ai_button.clicked.connect(self._request_ai_help)
        layout.addWidget(ai_button)

    def _setup_custom_sections(self):
        """Setup custom sections tab."""
        layout = QVBoxLayout(self.custom_sections_widget)

        # Add section button
        add_button = QPushButton("Add Custom Section")
        add_button.clicked.connect(self._add_custom_section)
        layout.addWidget(add_button)

        # Scroll area for custom sections
        self.custom_scroll = QScrollArea()
        self.custom_scroll.setWidgetResizable(True)
        self.custom_content = QWidget()
        self.custom_layout = QVBoxLayout(self.custom_content)
        self.custom_scroll.setWidget(self.custom_content)
        layout.addWidget(self.custom_scroll)

    def _add_custom_section(self):
        """Add a new custom worldbuilding section."""
        section_name, ok = QInputDialog.getText(
            self,
            "New Section",
            "Enter section name:"
        )

        if ok and section_name:
            editor = QTextEdit()
            editor.setPlaceholderText(f"Enter {section_name} details...")
            editor.setMaximumHeight(200)
            editor.textChanged.connect(self.content_changed.emit)

            # Create container with label
            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.addWidget(QLabel(section_name))
            container_layout.addWidget(editor)

            self.custom_sections[section_name] = editor
            self.custom_layout.addWidget(container)

    def _request_ai_help(self):
        """Request AI help for current worldbuilding section."""
        # TODO: Integrate with AI client
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "AI Help",
            "AI worldbuilding assistance will be integrated soon."
        )

    def load_data(self, worldbuilding: WorldBuilding):
        """Load worldbuilding data into widget."""
        self.sections["Mythology"].setPlainText(worldbuilding.mythology)
        self.sections["Planets"].setPlainText(worldbuilding.planets)
        self.sections["Climate"].setPlainText(worldbuilding.climate)
        self.sections["History"].setPlainText(worldbuilding.history)
        self.sections["Politics"].setPlainText(worldbuilding.politics)
        self.sections["Military"].setPlainText(worldbuilding.military)
        self.sections["Economy"].setPlainText(worldbuilding.economy)
        self.sections["Power Hierarchy"].setPlainText(worldbuilding.power_hierarchy)

        # Load custom sections
        for name, content in worldbuilding.custom_sections.items():
            self._add_custom_section_with_content(name, content)

    def _add_custom_section_with_content(self, name: str, content: str):
        """Add custom section with pre-filled content."""
        editor = QTextEdit()
        editor.setPlainText(content)
        editor.setMaximumHeight(200)
        editor.textChanged.connect(self.content_changed.emit)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.addWidget(QLabel(name))
        container_layout.addWidget(editor)

        self.custom_sections[name] = editor
        self.custom_layout.addWidget(container)

    def get_data(self) -> WorldBuilding:
        """Get worldbuilding data from widget."""
        custom_sections = {
            name: editor.toPlainText()
            for name, editor in self.custom_sections.items()
        }

        return WorldBuilding(
            mythology=self.sections["Mythology"].toPlainText(),
            planets=self.sections["Planets"].toPlainText(),
            climate=self.sections["Climate"].toPlainText(),
            history=self.sections["History"].toPlainText(),
            politics=self.sections["Politics"].toPlainText(),
            military=self.sections["Military"].toPlainText(),
            economy=self.sections["Economy"].toPlainText(),
            power_hierarchy=self.sections["Power Hierarchy"].toPlainText(),
            custom_sections=custom_sections
        )
