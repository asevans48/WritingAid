"""Dialog for AI-powered text rephrasing with multiple options."""

from typing import Optional, List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QListWidget, QListWidgetItem, QGroupBox,
    QRadioButton, QButtonGroup, QProgressBar, QMessageBox,
    QCheckBox, QFrame, QSplitter, QWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from src.ai.rephrasing_agent import RephrasingAgent, RephraseStyle, RephraseResult


class RephraseWorker(QThread):
    """Background worker for rephrasing operation."""

    finished = pyqtSignal(object)  # RephraseResult
    error = pyqtSignal(str)

    def __init__(self, agent: RephrasingAgent, text: str, styles: List[RephraseStyle], context: str):
        super().__init__()
        self.agent = agent
        self.text = text
        self.styles = styles
        self.context = context

    def run(self):
        """Run rephrasing in background."""
        try:
            result = self.agent.rephrase(
                text=self.text,
                styles=self.styles,
                context=self.context
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class RephraseDialog(QDialog):
    """Dialog for rephrasing selected text with AI."""

    def __init__(self, text: str, project=None, parent=None):
        """Initialize rephrase dialog.

        Args:
            text: Text to rephrase
            project: Project for context
            parent: Parent widget
        """
        super().__init__(parent)
        self.original_text = text
        self.project = project
        self.selected_text: Optional[str] = None
        self.result: Optional[RephraseResult] = None
        self.worker: Optional[RephraseWorker] = None

        self._init_ui()
        self._init_agent()

    def _init_ui(self):
        """Initialize the UI."""
        self.setWindowTitle("Rephrase Text")
        self.setMinimumSize(700, 600)
        self.resize(800, 650)

        layout = QVBoxLayout(self)

        # Header
        header = QLabel("<h2>AI Text Rephrasing</h2>")
        layout.addWidget(header)

        desc = QLabel(
            "Select styles to generate rephrasing options. "
            "You can edit the result before applying."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #6b7280; margin-bottom: 10px;")
        layout.addWidget(desc)

        # Original text display
        original_group = QGroupBox("Original Text")
        original_layout = QVBoxLayout(original_group)
        self.original_display = QTextEdit()
        self.original_display.setPlainText(self.original_text)
        self.original_display.setReadOnly(True)
        self.original_display.setMaximumHeight(100)
        self.original_display.setStyleSheet("background-color: #f3f4f6;")
        original_layout.addWidget(self.original_display)
        layout.addWidget(original_group)

        # Style selection
        style_group = QGroupBox("Rephrasing Styles")
        style_layout = QHBoxLayout(style_group)

        self.style_checkboxes = {}
        styles_left = QVBoxLayout()
        styles_right = QVBoxLayout()

        style_info = [
            (RephraseStyle.CONCISE, "Concise - Shorter, tighter phrasing"),
            (RephraseStyle.CLEARER, "Clearer - Easier to understand"),
            (RephraseStyle.ELABORATE, "Elaborate - More detail and description"),
            (RephraseStyle.DRAMATIC, "Dramatic - More impactful"),
            (RephraseStyle.FORMAL, "Formal - Professional tone"),
            (RephraseStyle.CASUAL, "Casual - Conversational tone"),
            (RephraseStyle.POETIC, "Poetic - Lyrical and artistic"),
            (RephraseStyle.ACTIVE_VOICE, "Active Voice - Convert passive to active"),
        ]

        for i, (style, label) in enumerate(style_info):
            cb = QCheckBox(label)
            cb.setChecked(i < 4)  # First 4 checked by default
            self.style_checkboxes[style] = cb

            if i < 4:
                styles_left.addWidget(cb)
            else:
                styles_right.addWidget(cb)

        style_layout.addLayout(styles_left)
        style_layout.addLayout(styles_right)
        layout.addWidget(style_group)

        # Model selection
        model_layout = QHBoxLayout()

        model_group = QGroupBox("AI Model")
        model_inner = QHBoxLayout(model_group)

        self.model_button_group = QButtonGroup(self)

        self.cloud_radio = QRadioButton("Cloud LLM (faster, API costs)")
        self.cloud_radio.setChecked(True)
        self.model_button_group.addButton(self.cloud_radio, 0)
        model_inner.addWidget(self.cloud_radio)

        self.local_radio = QRadioButton("Local SLM (slower, no costs)")
        self.model_button_group.addButton(self.local_radio, 1)
        model_inner.addWidget(self.local_radio)

        model_layout.addWidget(model_group)

        # Generate button
        self.generate_btn = QPushButton("Generate Options")
        self.generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            QPushButton:disabled {
                background-color: #9ca3af;
            }
        """)
        self.generate_btn.clicked.connect(self._generate_options)
        model_layout.addWidget(self.generate_btn)

        layout.addLayout(model_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Results section
        self.results_group = QGroupBox("Rephrasing Options")
        self.results_group.setVisible(False)
        results_layout = QVBoxLayout(self.results_group)

        # Splitter for options list and preview
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Options list
        self.options_list = QListWidget()
        self.options_list.currentRowChanged.connect(self._on_option_selected)
        splitter.addWidget(self.options_list)

        # Preview/edit area
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        preview_label = QLabel("<b>Preview & Edit:</b>")
        preview_layout.addWidget(preview_label)

        self.preview_edit = QTextEdit()
        self.preview_edit.setPlaceholderText("Select an option to preview and edit...")
        preview_layout.addWidget(self.preview_edit)

        self.style_label = QLabel("")
        self.style_label.setStyleSheet("color: #6b7280; font-style: italic;")
        preview_layout.addWidget(self.style_label)

        splitter.addWidget(preview_widget)
        splitter.setSizes([250, 450])

        results_layout.addWidget(splitter)
        layout.addWidget(self.results_group)

        # Bottom buttons
        button_layout = QHBoxLayout()

        self.use_btn = QPushButton("Use Selected")
        self.use_btn.setEnabled(False)
        self.use_btn.clicked.connect(self._use_selected)
        self.use_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:disabled {
                background-color: #9ca3af;
            }
        """)
        button_layout.addWidget(self.use_btn)

        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _init_agent(self):
        """Initialize the rephrasing agent."""
        try:
            from src.config.ai_config import get_ai_config
            from src.ai.llm_client import LLMClient, LLMProvider

            config = get_ai_config()
            settings = config.get_settings()
            provider = settings.get("default_llm", "claude")

            # Get API key
            api_key = config.get_api_key(provider)

            if api_key:
                provider_enum = {
                    "claude": LLMProvider.CLAUDE,
                    "chatgpt": LLMProvider.CHATGPT,
                    "openai": LLMProvider.CHATGPT,
                    "gemini": LLMProvider.GEMINI
                }.get(provider.lower(), LLMProvider.CLAUDE)

                llm = LLMClient(
                    provider=provider_enum,
                    api_key=api_key,
                    model=config.get_model(provider)
                )

                self.agent = RephrasingAgent(
                    llm_client=llm,
                    project=self.project
                )
            else:
                # No API key - will need to use local model
                self.agent = RephrasingAgent(project=self.project)
                self.cloud_radio.setEnabled(False)
                self.local_radio.setChecked(True)

        except Exception as e:
            print(f"Failed to initialize rephrasing agent: {e}")
            self.agent = RephrasingAgent(project=self.project)
            self.cloud_radio.setEnabled(False)
            self.local_radio.setChecked(True)

    def _get_selected_styles(self) -> List[RephraseStyle]:
        """Get list of selected styles."""
        styles = []
        for style, checkbox in self.style_checkboxes.items():
            if checkbox.isChecked():
                styles.append(style)
        return styles

    def _generate_options(self):
        """Generate rephrasing options."""
        styles = self._get_selected_styles()

        if not styles:
            QMessageBox.warning(
                self,
                "No Styles Selected",
                "Please select at least one rephrasing style."
            )
            return

        # Configure agent
        self.agent.use_local_model = self.local_radio.isChecked()

        # Show progress
        self.progress_bar.setVisible(True)
        self.generate_btn.setEnabled(False)
        self.results_group.setVisible(False)

        # Get context if available
        context = ""
        if self.project:
            # Could add chapter context, character names, etc.
            pass

        # Run in background
        self.worker = RephraseWorker(
            self.agent,
            self.original_text,
            styles,
            context
        )
        self.worker.finished.connect(self._on_generation_complete)
        self.worker.error.connect(self._on_generation_error)
        self.worker.start()

    def _on_generation_complete(self, result: RephraseResult):
        """Handle completed generation."""
        self.progress_bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        self.result = result

        # Populate options list
        self.options_list.clear()
        for i, option in enumerate(result.options):
            # Truncate for display
            display_text = option.text[:80] + "..." if len(option.text) > 80 else option.text
            item = QListWidgetItem(f"{i+1}. [{option.style}] {display_text}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.options_list.addItem(item)

        # Show results
        self.results_group.setVisible(True)

        # Select first option
        if self.options_list.count() > 0:
            self.options_list.setCurrentRow(0)

    def _on_generation_error(self, error: str):
        """Handle generation error."""
        self.progress_bar.setVisible(False)
        self.generate_btn.setEnabled(True)

        QMessageBox.critical(
            self,
            "Generation Failed",
            f"Failed to generate rephrasing options:\n\n{error}\n\n"
            "Try selecting 'Local SLM' if you don't have an API key configured."
        )

    def _on_option_selected(self, row: int):
        """Handle option selection."""
        if row < 0 or not self.result:
            self.preview_edit.clear()
            self.style_label.clear()
            self.use_btn.setEnabled(False)
            return

        option = self.result.options[row]
        self.preview_edit.setPlainText(option.text)
        self.style_label.setText(f"Style: {option.style} - {option.explanation}")
        self.use_btn.setEnabled(True)

    def _use_selected(self):
        """Use the selected/edited text."""
        self.selected_text = self.preview_edit.toPlainText()
        self.accept()

    def get_selected_text(self) -> Optional[str]:
        """Get the selected replacement text."""
        return self.selected_text
