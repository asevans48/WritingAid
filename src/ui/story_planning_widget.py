"""Story planning widget with enhanced Freytag pyramid, visual events, and subplots."""

from PyQt6.QtCore import pyqtSignal, QSettings
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QLabel
)
from typing import List

from src.models.project import StoryPlanning
from src.ui.plot import PlotManagerWidget
from src.ui.plot.plot_manager import CollapsibleSection


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

        # Main plot summary (optional high-level overview) — wrapped
        # in a CollapsibleSection so users can hide it once they've
        # written it (frees up vertical space on laptop displays).
        # Default state is restored from QSettings so it sticks.
        self._main_plot_section = CollapsibleSection(
            "📝 Main Plot Summary")

        help_text = QLabel(
            "High-level overview of your main plot (optional):")
        help_text.setStyleSheet("color: #6b7280; font-size: 11px;")
        self._main_plot_section.add_widget(help_text)

        self.main_plot_edit = QTextEdit()
        self.main_plot_edit.setPlaceholderText(
            "Optional: Provide a high-level summary of your main plot. "
            "Use the pyramid and events below for detailed planning.")
        self.main_plot_edit.setMaximumHeight(100)
        self.main_plot_edit.textChanged.connect(self.content_changed.emit)
        self._main_plot_section.add_widget(self.main_plot_edit)
        layout.addWidget(self._main_plot_section)

        # Restore prior collapse state. Default = expanded (False)
        # for first-time users so they discover the feature.
        self._collapse_settings = QSettings(
            "WritingAid", "StoryPlanningWidget")
        if self._collapse_settings.value(
                "mainPlotCollapsed", False, type=bool):
            self._main_plot_section.toggle()
        # Persist whenever the user toggles it.
        self._main_plot_section.toggle_btn.clicked.connect(
            lambda: self._collapse_settings.setValue(
                "mainPlotCollapsed",
                self._main_plot_section.is_collapsed))

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
            story_planning.promises,
            getattr(story_planning, 'tensions', None) or [],
        )

    def get_data(self) -> StoryPlanning:
        """Get story planning data.

        Returns:
            StoryPlanning object with all data
        """
        freytag_pyramid, subplots, promises, tensions = (
            self.plot_manager.get_plot_data())

        return StoryPlanning(
            main_plot=self.main_plot_edit.toPlainText(),
            freytag_pyramid=freytag_pyramid,
            subplots=subplots,
            promises=promises,
            tensions=tensions,
        )

    def set_available_characters(self, characters: List[str]):
        """Set available characters for event association.

        Args:
            characters: List of character names
        """
        self.plot_manager.set_available_characters(characters)

    def set_ai_context_provider(self, provider):
        """Forward the host's AI context provider to the plot manager.

        The plot manager owns the Discuss-with-AI tab; this widget is
        the host of the plot manager and just passes the provider
        through so main_window doesn't need to know that the AI tab
        lives one level deeper.
        """
        self.plot_manager.set_ai_context_provider(provider)

    def refresh_ai_status(self):
        """Forward to the plot manager's AI tab status refresh.

        main_window calls this after a project loads so the AI tab's
        context-status banner reflects the freshly-loaded project
        instead of whatever was true when the widget was constructed
        (typically nothing — the widget is built before any project
        is open).
        """
        self.plot_manager.refresh_ai_status()

    def set_ai_create_callback(self, callback):
        """Forward the host's create callback to the plot manager.

        Called when the user clicks "Add to project" on a plot-AI
        suggestion card; main_window handles the actual element
        creation and returns True/False back to the card.
        """
        self.plot_manager.set_ai_create_callback(callback)
