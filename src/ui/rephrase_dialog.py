"""Dialog for AI-powered text rephrasing with multiple options."""

from typing import Optional, List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QListWidget, QListWidgetItem, QGroupBox,
    QRadioButton, QButtonGroup, QProgressBar, QMessageBox,
    QCheckBox, QFrame, QSplitter, QWidget, QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from src.ai.rephrasing_agent import RephrasingAgent, RephraseStyle, RephraseTone, RephraseResult


class RephraseWorker(QThread):
    """Background worker for rephrasing operation."""

    finished = pyqtSignal(object)  # RephraseResult
    error = pyqtSignal(str)

    def __init__(self, agent: RephrasingAgent, text: str, styles: List[RephraseStyle],
                 tone: RephraseTone, context: str):
        super().__init__()
        self.agent = agent
        self.text = text
        self.styles = styles
        self.tone = tone
        self.context = context

    def run(self):
        """Run rephrasing in background."""
        try:
            result = self.agent.rephrase(
                text=self.text,
                styles=self.styles,
                tone=self.tone,
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
        # Smaller minimum for laptops (14" MacBook Pro, smaller Windows laptops)
        self.setMinimumSize(500, 350)
        self.resize(750, 600)

        # Main dialog layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Create scroll area for the content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        # Container widget for scroll area
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header - more compact
        header = QLabel("<b style='font-size: 14pt;'>AI Text Rephrasing</b>")
        layout.addWidget(header)

        desc = QLabel(
            "Select styles to generate rephrasing options. "
            "You can edit the result before applying."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #6b7280; margin-bottom: 6px; font-size: 11px;")
        layout.addWidget(desc)

        # Original text display - more compact
        original_group = QGroupBox("Original Text")
        original_layout = QVBoxLayout(original_group)
        original_layout.setContentsMargins(8, 8, 8, 8)
        self.original_display = QTextEdit()
        self.original_display.setPlainText(self.original_text)
        self.original_display.setReadOnly(True)
        self.original_display.setMaximumHeight(80)
        self.original_display.setMinimumHeight(50)
        self.original_display.setStyleSheet("background-color: #f3f4f6;")
        original_layout.addWidget(self.original_display)
        layout.addWidget(original_group)

        # Style and Tone selection in horizontal layout
        style_tone_layout = QHBoxLayout()
        style_tone_layout.setSpacing(8)

        # Style selection (structural approach) - compact labels
        style_group = QGroupBox("Writing Style")
        style_inner = QVBoxLayout(style_group)
        style_inner.setContentsMargins(8, 8, 8, 8)
        style_inner.setSpacing(2)

        self.style_checkboxes = {}
        style_info = [
            (RephraseStyle.CONCISE, "Concise"),
            (RephraseStyle.CLEARER, "Clearer"),
            (RephraseStyle.ELABORATE, "Elaborate"),
            (RephraseStyle.FORMAL, "Formal"),
            (RephraseStyle.CASUAL, "Casual"),
            (RephraseStyle.POETIC, "Poetic"),
            (RephraseStyle.ACTIVE_VOICE, "Active Voice"),
        ]

        for i, (style, label) in enumerate(style_info):
            cb = QCheckBox(label)
            cb.setChecked(i < 4)  # First 4 checked by default
            self.style_checkboxes[style] = cb
            style_inner.addWidget(cb)

        style_tone_layout.addWidget(style_group)

        # Tone selection (emotional quality) - compact labels
        tone_group = QGroupBox("Tone")
        tone_inner = QVBoxLayout(tone_group)
        tone_inner.setContentsMargins(8, 8, 8, 8)
        tone_inner.setSpacing(2)

        self.tone_button_group = QButtonGroup(self)
        self.tone_radios = {}

        tone_info = [
            (RephraseTone.NEUTRAL, "Neutral"),
            (RephraseTone.DARK, "Dark"),
            (RephraseTone.DRAMATIC, "Dramatic"),
            (RephraseTone.HOPEFUL, "Hopeful"),
            (RephraseTone.MELANCHOLIC, "Melancholic"),
            (RephraseTone.TENSE, "Tense"),
            (RephraseTone.WHIMSICAL, "Whimsical"),
        ]

        for i, (tone, label) in enumerate(tone_info):
            radio = QRadioButton(label)
            if i == 0:  # Neutral selected by default
                radio.setChecked(True)
            self.tone_button_group.addButton(radio, i)
            self.tone_radios[tone] = radio
            tone_inner.addWidget(radio)

        style_tone_layout.addWidget(tone_group)
        layout.addLayout(style_tone_layout)

        # Model selection
        model_layout = QHBoxLayout()

        model_group = QGroupBox("AI Model")
        model_inner = QVBoxLayout(model_group)

        # Python libraries mode indicator (hidden by default)
        self.python_mode_label = QLabel("Using Python libraries (nltk/nlpaug) - AI is disabled in settings")
        self.python_mode_label.setStyleSheet(
            "color: #0369a1; background-color: #e0f2fe; padding: 6px; "
            "border-radius: 4px; font-weight: bold;"
        )
        self.python_mode_label.setVisible(False)
        model_inner.addWidget(self.python_mode_label)

        # Radio buttons row
        radio_row = QHBoxLayout()
        self.model_button_group = QButtonGroup(self)

        self.cloud_radio = QRadioButton("Cloud LLM (faster, API costs)")
        self.cloud_radio.setChecked(True)
        self.model_button_group.addButton(self.cloud_radio, 0)
        radio_row.addWidget(self.cloud_radio)

        self.local_radio = QRadioButton("Local SLM (slower, no costs)")
        self.model_button_group.addButton(self.local_radio, 1)
        radio_row.addWidget(self.local_radio)

        model_inner.addLayout(radio_row)
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

        # Set scroll widget and add scroll area to main layout
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)

        # Bottom buttons (outside scroll area so always visible)
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(16, 8, 16, 16)

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

        main_layout.addLayout(button_layout)

    def _init_agent(self):
        """Initialize the rephrasing agent."""
        try:
            from src.config.ai_config import get_ai_config
            from src.ai.llm_client import LLMClient, LLMProvider

            config = get_ai_config()
            settings = config.get_settings()

            # Check if AI is disabled entirely
            disable_all_ai = config.is_ai_disabled()

            if disable_all_ai:
                # Use Python libraries only mode
                self.agent = RephrasingAgent(
                    project=self.project,
                    use_python_libraries=True
                )
                self.cloud_radio.setEnabled(False)
                self.local_radio.setEnabled(False)
                self.cloud_radio.setVisible(False)
                self.local_radio.setVisible(False)
                # Show Python mode indicator
                self.python_mode_label.setVisible(True)
                return

            provider = settings.get("default_llm", "claude")

            # Get local model ID from settings
            local_model_id = settings.get("local_model_id", "microsoft/Phi-3-mini-4k-instruct")

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
                    project=self.project,
                    local_model_id=local_model_id
                )
            else:
                # No API key - will need to use local model
                self.agent = RephrasingAgent(
                    project=self.project,
                    local_model_id=local_model_id
                )
                self.cloud_radio.setEnabled(False)
                self.local_radio.setChecked(True)

        except Exception as e:
            print(f"Failed to initialize rephrasing agent: {e}")
            self.agent = RephrasingAgent(project=self.project, use_python_libraries=True)
            self.cloud_radio.setEnabled(False)
            self.local_radio.setEnabled(False)
            self.cloud_radio.setVisible(False)
            self.local_radio.setVisible(False)
            self.python_mode_label.setText("Using Python libraries (AI initialization failed)")
            self.python_mode_label.setVisible(True)

    def _get_selected_styles(self) -> List[RephraseStyle]:
        """Get list of selected styles."""
        styles = []
        for style, checkbox in self.style_checkboxes.items():
            if checkbox.isChecked():
                styles.append(style)
        return styles

    def _get_selected_tone(self) -> RephraseTone:
        """Get the selected tone."""
        for tone, radio in self.tone_radios.items():
            if radio.isChecked():
                return tone
        return RephraseTone.NEUTRAL

    def _generate_options(self):
        """Generate rephrasing options."""
        styles = self._get_selected_styles()
        tone = self._get_selected_tone()

        if not styles:
            QMessageBox.warning(
                self,
                "No Styles Selected",
                "Please select at least one rephrasing style."
            )
            return

        # Configure agent - only set local model if not using python libraries
        if not self.agent.use_python_libraries:
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
            tone,
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
        if row < 0 or not self.result or row >= len(self.result.options):
            self.preview_edit.clear()
            self.style_label.clear()
            self.use_btn.setEnabled(False)
            return

        option = self.result.options[row]
        self.preview_edit.setPlainText(option.text)
        self.style_label.setText(f"Style: {option.style} | Tone: {option.tone} — {option.explanation}")
        self.use_btn.setEnabled(True)

    def _use_selected(self):
        """Use the selected/edited text."""
        self.selected_text = self.preview_edit.toPlainText()
        self.accept()

    def get_selected_text(self) -> Optional[str]:
        """Get the selected replacement text."""
        return self.selected_text
