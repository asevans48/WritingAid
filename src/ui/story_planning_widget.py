"""Story planning widget with enhanced Freytag pyramid, visual events, and subplots."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QTextEdit, QPushButton, QLabel, QScrollArea
)
from PyQt6.QtCore import pyqtSignal
from typing import List

from src.models.project import StoryPlanning
from src.ui.plot import PlotManagerWidget


class StoryPlanningWidget(QWidget):
    """Widget for story planning with visual Freytag pyramid and detailed event tracking."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize story planning widget."""
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        """Initialize user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(16, 12, 16, 8)

        header = QLabel("📖 Story Planning")
        header.setStyleSheet("font-size: 18px; font-weight: 600; color: #1a1a1a;")
        header_layout.addWidget(header)

        explanation = QLabel(
            "Plan your story's structure with visual pyramid, detailed events, and subplot tracking"
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet("color: #6b7280; font-size: 12px;")
        header_layout.addWidget(explanation)

        layout.addWidget(header_widget)

        # Main plot summary (optional high-level overview)
        main_plot_group = QGroupBox("Main Plot Summary")
        main_plot_layout = QVBoxLayout()

        help_text = QLabel("High-level overview of your main plot (optional):")
        help_text.setStyleSheet("color: #6b7280; font-size: 11px;")
        main_plot_layout.addWidget(help_text)

        self.main_plot_edit = QTextEdit()
        self.main_plot_edit.setPlaceholderText(
            "Optional: Provide a high-level summary of your main plot. "
            "Use the pyramid and events below for detailed planning."
        )
        self.main_plot_edit.setMaximumHeight(100)
        self.main_plot_edit.textChanged.connect(self.content_changed.emit)
        main_plot_layout.addWidget(self.main_plot_edit)

        main_plot_group.setLayout(main_plot_layout)
        layout.addWidget(main_plot_group)

        # Enhanced plot manager with visual pyramid
        self.plot_manager = PlotManagerWidget()
        self.plot_manager.content_changed.connect(self.content_changed.emit)
        layout.addWidget(self.plot_manager, stretch=1)

    def load_data(self, story_planning: StoryPlanning):
        """Load story planning data.

        Args:
            story_planning: StoryPlanning object with plot and subplot data
        """
        self.main_plot_edit.setPlainText(story_planning.main_plot)
        self.plot_manager.load_plot_data(
            story_planning.freytag_pyramid,
            story_planning.subplots,
            story_planning.promises
        )

    def get_data(self) -> StoryPlanning:
        """Get story planning data.

        Returns:
            StoryPlanning object with all data
        """
        freytag_pyramid, subplots, promises = self.plot_manager.get_plot_data()

        return StoryPlanning(
            main_plot=self.main_plot_edit.toPlainText(),
            freytag_pyramid=freytag_pyramid,
            subplots=subplots,
            promises=promises
        )

    def set_available_characters(self, characters: List[str]):
        """Set available characters for event association.

        Args:
            characters: List of character names
        """
        self.plot_manager.set_available_characters(characters)
