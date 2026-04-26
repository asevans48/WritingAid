"""Dialog for AI-powered text rephrasing with multiple options."""

from typing import Optional, List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QListWidget, QListWidgetItem, QGroupBox,
    QRadioButton, QButtonGroup, QProgressBar, QMessageBox,
    QCheckBox, QLineEdit, QFrame, QSplitter, QWidget, QScrollArea,
    QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from src.ai.rephrasing_agent import RephrasingAgent, RephraseStyle, RephraseTone, RephraseResult
from src.ai.mlx_utils import can_use_mlx


class RephraseWorker(QThread):
    """Background worker for rephrasing operation."""

    finished = pyqtSignal(object)  # RephraseResult
    error = pyqtSignal(str)

    def __init__(self, agent: RephrasingAgent, text: str, styles: List[RephraseStyle],
                 tones: List[RephraseTone], custom_tone: str = "",
                 pov: str = "", character_context: str = "",
                 scene_description: str = "", surrounding_before: str = "",
                 surrounding_after: str = ""):
        super().__init__()
        self.agent = agent
        self.text = text
        self.styles = styles
        self.tones = tones
        self.custom_tone = custom_tone
        self.pov = pov
        self.character_context = character_context
        self.scene_description = scene_description
        self.surrounding_before = surrounding_before
        self.surrounding_after = surrounding_after

    def run(self):
        """Run rephrasing in background."""
        try:
            # Log at the start of the worker thread
            print(f"\n{'='*70}")
            print(f"REPHRASING WORKER THREAD STARTING")
            print(f"{'='*70}")
            print(f"Text length: {len(self.text)} chars")
            print(f"Styles: {[s.value for s in self.styles]}")
            print(f"Tones: {[t.value for t in self.tones]}")
            if self.custom_tone:
                print(f"Custom tone: {self.custom_tone}")
            print(f"Using local model: {self.agent.use_local_model}")
            if self.agent.use_local_model:
                print(f"Model ID: {self.agent.local_model_id or '(not set)'}")
            print(f"{'='*70}\n")

            result = self.agent.rephrase(
                text=self.text,
                styles=self.styles,
                tones=self.tones,
                custom_tone=self.custom_tone,
                pov=self.pov,
                character_context=self.character_context,
                scene_description=self.scene_description,
                surrounding_before=self.surrounding_before,
                surrounding_after=self.surrounding_after,
            )

            print(f"\n{'='*70}")
            print(f"✅ REPHRASING WORKER THREAD COMPLETE")
            print(f"{'='*70}")
            print(f"Generated {len(result.options)} options")
            print(f"{'='*70}\n")

            self.finished.emit(result)
        except Exception as e:
            print(f"\n{'='*70}")
            print(f"❌ REPHRASING WORKER THREAD FAILED")
            print(f"{'='*70}")
            print(f"Error: {e}")
            print(f"{'='*70}\n")
            self.error.emit(str(e))


class RephraseDialog(QDialog):
    """Dialog for rephrasing selected text with AI."""

    def __init__(self, text: str, project=None, parent=None,
                 surrounding_context: tuple = None,
                 chapter_content: str = "", chapter=None):
        """Initialize rephrase dialog.

        Args:
            text: Text to rephrase
            project: Project for context
            parent: Parent widget
            surrounding_context: Tuple of (text_before, text_after) from the document
            chapter_content: Full text of the current chapter (for speaker detection)
            chapter: Chapter object (for arc context)
        """
        super().__init__(parent)
        self.original_text = text
        self.project = project
        self.surrounding_before = surrounding_context[0] if surrounding_context else ""
        self.surrounding_after = surrounding_context[1] if surrounding_context else ""
        self.chapter_content = chapter_content
        self.chapter = chapter
        self.selected_text: Optional[str] = None
        self.result: Optional[RephraseResult] = None
        self.worker: Optional[RephraseWorker] = None
        self._refinement_history: List[str] = []  # Chat history for refinements

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

        # Surrounding context (read-only, collapsible)
        if self.surrounding_before or self.surrounding_after:
            self.context_toggle = QPushButton("Show surrounding context")
            self.context_toggle.setStyleSheet(
                "font-size: 10px; color: #6366f1; border: none; text-align: left; padding: 0;"
            )
            self.context_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            self.context_toggle.clicked.connect(self._toggle_surrounding_context)
            layout.addWidget(self.context_toggle)

            self.context_display = QTextEdit()
            preview = ""
            if self.surrounding_before:
                preview += f"...{self.surrounding_before[-200:]}\n"
            preview += f">>> {self.original_text} <<<\n"
            if self.surrounding_after:
                preview += f"{self.surrounding_after[:200]}..."
            self.context_display.setPlainText(preview)
            self.context_display.setReadOnly(True)
            self.context_display.setMaximumHeight(80)
            self.context_display.setStyleSheet(
                "background-color: #f9fafb; color: #6b7280; font-size: 10px;"
            )
            self.context_display.setVisible(False)
            layout.addWidget(self.context_display)

        # Scene description (optional, user-provided)
        self.scene_desc_edit = QLineEdit()
        self.scene_desc_edit.setPlaceholderText(
            "Describe what's happening in the scene (optional)..."
        )
        self.scene_desc_edit.setToolTip(
            "Brief description of the scene — e.g. 'tense standoff in the throne room' "
            "or 'quiet morning after the battle'. Helps the AI understand context."
        )
        self.scene_desc_edit.setStyleSheet("font-size: 10px; padding: 4px;")
        layout.addWidget(self.scene_desc_edit)

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

        # Tone selection (emotional quality) — checkboxes allow mixing emotions
        tone_group = QGroupBox("Tone (mix any)")
        tone_inner = QVBoxLayout(tone_group)
        tone_inner.setContentsMargins(8, 8, 8, 8)
        tone_inner.setSpacing(2)

        hint = QLabel("Select one or more emotions to blend")
        hint.setStyleSheet("color: #6b7280; font-size: 10px; font-style: italic;")
        tone_inner.addWidget(hint)

        self.tone_checkboxes: dict = {}

        tone_info = [
            (RephraseTone.NEUTRAL,     "Neutral"),
            (RephraseTone.DARK,        "Dark"),
            (RephraseTone.DRAMATIC,    "Dramatic"),
            (RephraseTone.HOPEFUL,     "Hopeful"),
            (RephraseTone.HAPPY,       "Happy"),
            (RephraseTone.PROUD,       "Proud"),
            (RephraseTone.MELANCHOLIC, "Melancholic"),
            (RephraseTone.SORROWFUL,   "Sorrowful"),
            (RephraseTone.NOSTALGIC,   "Nostalgic"),
            (RephraseTone.TENSE,       "Tense"),
            (RephraseTone.WHIMSICAL,   "Whimsical"),
            (RephraseTone.GROSS,       "Gross / Visceral"),
        ]

        for tone_val, label in tone_info:
            cb = QCheckBox(label)
            # Default: Neutral checked
            cb.setChecked(tone_val == RephraseTone.NEUTRAL)
            # Neutral unchecks all others and vice-versa
            cb.toggled.connect(lambda checked, t=tone_val: self._on_tone_toggled(t, checked))
            self.tone_checkboxes[tone_val] = cb
            tone_inner.addWidget(cb)

        # Custom tone — free-text field
        custom_row = QHBoxLayout()
        custom_row.setSpacing(4)

        self.custom_tone_cb = QCheckBox("Custom:")
        self.custom_tone_cb.setToolTip(
            "Describe your own tone in plain language.\n"
            "Examples: \"bittersweet\", \"cold and clinical\", \"breathlessly romantic\""
        )
        self.custom_tone_cb.toggled.connect(self._on_custom_tone_toggled)
        custom_row.addWidget(self.custom_tone_cb)

        self.custom_tone_edit = QLineEdit()
        self.custom_tone_edit.setPlaceholderText("e.g. bittersweet, cold and clinical…")
        self.custom_tone_edit.setEnabled(False)
        self.custom_tone_edit.setToolTip(
            "Type any tone description — the AI will apply it directly to the text."
        )
        custom_row.addWidget(self.custom_tone_edit)
        tone_inner.addLayout(custom_row)

        # Point of View selection
        pov_group = QGroupBox("Point of View")
        pov_inner = QVBoxLayout(pov_group)
        pov_inner.setContentsMargins(8, 8, 8, 8)
        pov_inner.setSpacing(4)

        self.pov_combo = QComboBox()
        self.pov_combo.addItems([
            "Keep original",
            "First person (I/me)",
            "Second person (you)",
            "Third person limited (he/she/they)",
            "Third person omniscient",
            "Third person objective",
        ])
        self.pov_combo.setCurrentIndex(0)
        self.pov_combo.setToolTip("Choose a narrative point of view for the rephrased text")
        pov_inner.addWidget(self.pov_combo)

        # Voice character — whose vocabulary/voice should the text use?
        char_label = QLabel("Character voice:")
        char_label.setStyleSheet("font-size: 10px; color: #6b7280; margin-top: 4px;")
        char_label.setToolTip(
            "Select the character whose voice the text should match.\n"
            "'Auto-detect' reads the surrounding text to identify the speaker."
        )
        pov_inner.addWidget(char_label)

        self.char_list = QListWidget()
        self.char_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.char_list.setMaximumHeight(90)
        self.char_list.setStyleSheet("font-size: 10px;")
        # Add auto-detect as first item
        auto_item = QListWidgetItem("Auto-detect from text")
        auto_item.setData(Qt.ItemDataRole.UserRole, "__auto__")
        self.char_list.addItem(auto_item)
        self._populate_character_list()
        pov_inner.addWidget(self.char_list)

        self.detect_status_label = QLabel("")
        self.detect_status_label.setWordWrap(True)
        self.detect_status_label.setStyleSheet("font-size: 10px; color: #6b7280; font-style: italic;")
        self.detect_status_label.setVisible(False)
        pov_inner.addWidget(self.detect_status_label)

        style_tone_layout.addWidget(pov_group)

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

        # Refinement chat — allows conversational follow-up
        self.refine_group = QGroupBox("Refine Results")
        self.refine_group.setVisible(False)
        refine_layout = QVBoxLayout(self.refine_group)
        refine_layout.setContentsMargins(8, 8, 8, 8)
        refine_layout.setSpacing(4)

        self.refine_history = QTextEdit()
        self.refine_history.setReadOnly(True)
        self.refine_history.setMaximumHeight(60)
        self.refine_history.setStyleSheet("background: #f9fafb; font-size: 10px; color: #4b5563;")
        self.refine_history.setPlaceholderText("Refinement history will appear here...")
        refine_layout.addWidget(self.refine_history)

        refine_input_layout = QHBoxLayout()
        self.refine_edit = QLineEdit()
        self.refine_edit.setPlaceholderText(
            "e.g.: make it darker, this character wouldn't say that, more archaic..."
        )
        self.refine_edit.setStyleSheet("font-size: 11px; padding: 4px;")
        self.refine_edit.returnPressed.connect(self._refine_results)
        refine_input_layout.addWidget(self.refine_edit)

        self.refine_btn = QPushButton("Refine")
        self.refine_btn.setStyleSheet("font-size: 11px; padding: 4px 12px;")
        self.refine_btn.clicked.connect(self._refine_results)
        refine_input_layout.addWidget(self.refine_btn)

        refine_layout.addLayout(refine_input_layout)
        layout.addWidget(self.refine_group)

        # Set scroll widget and add scroll area to main layout
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)

        # Bottom buttons (outside scroll area so always visible)
        # Rating row — feedback on the previewed suggestion. Stored in the
        # rephrase database for transfer learning (positive samples build
        # SFT data; negative samples become DPO "rejected" examples).
        rating_row = QHBoxLayout()
        rating_row.setContentsMargins(16, 4, 16, 4)
        rating_label = QLabel("Rate this suggestion:")
        rating_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        rating_row.addWidget(rating_label)

        self._selected_rating: str = "neutral"

        def _make_rating_btn(emoji: str, label: str, value: str, color: str):
            btn = QPushButton(f"{emoji} {label}")
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #f3f4f6; color: #374151;
                    border: 1px solid #d1d5db; border-radius: 4px;
                    padding: 3px 10px; font-size: 11px;
                }}
                QPushButton:checked {{
                    background-color: {color}; color: white;
                    border-color: {color};
                }}
                QPushButton:hover {{ background-color: #e5e7eb; }}
                QPushButton:checked:hover {{ background-color: {color}; }}
            """)
            btn.clicked.connect(lambda: self._on_rating_clicked(value))
            return btn

        self.rate_excellent_btn = _make_rating_btn("⭐", "Excellent", "excellent", "#10b981")
        self.rate_good_btn = _make_rating_btn("👍", "Good", "good", "#3b82f6")
        self.rate_poor_btn = _make_rating_btn("👎", "Poor", "poor", "#f59e0b")
        self.rate_bad_btn = _make_rating_btn("✖", "Bad", "bad", "#ef4444")
        for b in (self.rate_excellent_btn, self.rate_good_btn,
                  self.rate_poor_btn, self.rate_bad_btn):
            rating_row.addWidget(b)
        rating_row.addStretch()
        main_layout.addLayout(rating_row)

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

            # Get local model ID from settings with platform-specific default
            # MLX model on Apple Silicon, PyTorch model elsewhere
            default_model = "mlx-community/Qwen2.5-7B-Instruct-4bit" if can_use_mlx() else "microsoft/Phi-3-mini-4k-instruct"
            local_model_id = settings.get("local_model_id", default_model)

            # Per-task override: if the user has chosen a 'rephrase'
            # trained model in CreativeOS settings, use it as the
            # local_model_id for this dialog. The resolver falls back
            # through 'general' → empty automatically, and silently
            # ignores models whose directories were deleted.
            try:
                from src.config.creativeos_config import get_creativeos_config
                _ts = get_creativeos_config().task_settings("rephrase")
                if _ts.get("__trained_model_name"):
                    local_model_id = _ts["local_model_id"]
                    print(f"[rephrase] Using task model "
                          f"'{_ts['__trained_model_name']}' "
                          f"(source={_ts['__task_model_source']})")
            except Exception as e:
                print(f"[rephrase] task model lookup failed: {e}")

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

    def _on_tone_toggled(self, tone: RephraseTone, checked: bool):
        """Handle tone checkbox toggled — enforce Neutral mutual-exclusion."""
        if checked and tone == RephraseTone.NEUTRAL:
            # Neutral selected: uncheck all emotional tones and custom
            for t, cb in self.tone_checkboxes.items():
                if t != RephraseTone.NEUTRAL:
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
            self.custom_tone_cb.blockSignals(True)
            self.custom_tone_cb.setChecked(False)
            self.custom_tone_cb.blockSignals(False)
            self.custom_tone_edit.setEnabled(False)
        elif checked and tone != RephraseTone.NEUTRAL:
            # An emotion selected: uncheck Neutral
            neutral_cb = self.tone_checkboxes.get(RephraseTone.NEUTRAL)
            if neutral_cb and neutral_cb.isChecked():
                neutral_cb.blockSignals(True)
                neutral_cb.setChecked(False)
                neutral_cb.blockSignals(False)

    def _on_custom_tone_toggled(self, checked: bool):
        """Handle the Custom tone checkbox — enable/disable the text field."""
        self.custom_tone_edit.setEnabled(checked)
        if checked:
            # Uncheck Neutral when custom is activated
            neutral_cb = self.tone_checkboxes.get(RephraseTone.NEUTRAL)
            if neutral_cb and neutral_cb.isChecked():
                neutral_cb.blockSignals(True)
                neutral_cb.setChecked(False)
                neutral_cb.blockSignals(False)
            self.custom_tone_edit.setFocus()
        else:
            # If nothing else is checked, fall back to Neutral
            any_preset = any(cb.isChecked() for cb in self.tone_checkboxes.values())
            if not any_preset:
                neutral_cb = self.tone_checkboxes.get(RephraseTone.NEUTRAL)
                if neutral_cb:
                    neutral_cb.blockSignals(True)
                    neutral_cb.setChecked(True)
                    neutral_cb.blockSignals(False)

    def _get_selected_tones(self) -> List[RephraseTone]:
        """Get the list of selected preset tones. Falls back to NEUTRAL if none chosen."""
        tones = [t for t, cb in self.tone_checkboxes.items() if cb.isChecked()]
        return tones if tones else [RephraseTone.NEUTRAL]

    def _get_custom_tone(self) -> str:
        """Return the custom tone text if the custom checkbox is checked."""
        if self.custom_tone_cb.isChecked():
            return self.custom_tone_edit.text().strip()
        return ""

    def _get_selected_pov(self) -> str:
        """Return the selected POV string, or empty if 'Keep original'."""
        idx = self.pov_combo.currentIndex()
        if idx <= 0:
            return ""
        return self.pov_combo.currentText()

    def _toggle_surrounding_context(self):
        """Toggle visibility of surrounding context display."""
        visible = not self.context_display.isVisible()
        self.context_display.setVisible(visible)
        self.context_toggle.setText(
            "Hide surrounding context" if visible else "Show surrounding context"
        )

    def _populate_character_list(self):
        """Populate the character list from the project."""
        self.char_list.clear()
        if not self.project or not hasattr(self.project, 'characters'):
            return
        for char in self.project.characters:
            item = QListWidgetItem(f"{char.name} ({char.character_type})")
            item.setData(Qt.ItemDataRole.UserRole, char.id)
            self.char_list.addItem(item)

    def _get_selected_characters_context(self) -> str:
        """Build a context string from selected POV characters' details."""
        selected_ids = []
        use_auto_detect = False
        for item in self.char_list.selectedItems():
            char_id = item.data(Qt.ItemDataRole.UserRole)
            if char_id == "__auto__":
                use_auto_detect = True
            elif char_id:
                selected_ids.append(char_id)

        # If auto-detect is selected, run speaker detection pipeline
        if use_auto_detect:
            detected_ctx = self._detect_speaker_for_rephrase()
            if detected_ctx:
                return detected_ctx

        if not self.project or not hasattr(self.project, 'characters'):
            return ""
        if not selected_ids:
            return ""

        chars_by_id = {c.id: c for c in self.project.characters}
        parts = []
        for cid in selected_ids:
            c = chars_by_id.get(cid)
            if not c:
                continue
            desc = [f"Name: {c.name}", f"Role: {c.character_type}"]
            if c.personality:
                desc.append(f"Personality: {c.personality}")
            if getattr(c, 'personality_traits', None):
                desc.append(f"Key traits: {', '.join(c.personality_traits)}")
            if getattr(c, 'speaking_style', None):
                desc.append(f"Speaking style: {c.speaking_style}")
            if getattr(c, 'motivations', None):
                desc.append(f"Motivations: {c.motivations}")
            if getattr(c, 'emotional_baseline', None):
                desc.append(f"Emotional baseline: {c.emotional_baseline}")
            if getattr(c, 'personality_arc', None):
                # Include the most recent arc snapshot
                latest = c.personality_arc[-1]
                if latest.emotional_state:
                    desc.append(f"Current emotional state: {latest.emotional_state}")
                if latest.growth_notes:
                    desc.append(f"Recent development: {latest.growth_notes[:200]}")
            if c.backstory:
                backstory = c.backstory[:300] + ("..." if len(c.backstory) > 300 else "")
                desc.append(f"Backstory: {backstory}")
            if c.notes:
                desc.append(f"Notes: {c.notes[:200]}")
            parts.append("\n".join(desc))
        return "\n---\n".join(parts)

    def _generate_options(self):
        """Generate rephrasing options."""
        styles = self._get_selected_styles()
        tones = self._get_selected_tones()
        custom_tone = self._get_custom_tone()

        if not styles:
            QMessageBox.warning(
                self,
                "No Styles Selected",
                "Please select at least one rephrasing style."
            )
            return

        # Guard: if custom tone box is checked but empty, warn the user
        if self.custom_tone_cb.isChecked() and not custom_tone:
            QMessageBox.warning(
                self,
                "Custom Tone Empty",
                "You checked \"Custom\" but left the tone field blank.\n"
                "Please describe your custom tone or uncheck the box."
            )
            self.custom_tone_edit.setFocus()
            return

        # Configure agent - only set local model if not using python libraries
        if not self.agent.use_python_libraries:
            self.agent.use_local_model = self.local_radio.isChecked()

        # Log configuration before starting
        print(f"\n{'#'*70}")
        print(f"# REPHRASING DIALOG - STARTING OPERATION")
        print(f"{'#'*70}")
        if self.agent.use_python_libraries:
            print(f"🔧 Mode: Python Libraries Only")
        elif self.agent.use_local_model:
            print(f"🤖 Mode: Local Model")
            print(f"📦 Model: {self.agent.local_model_id or '(not configured)'}")
        else:
            print(f"☁️  Mode: Cloud LLM")
        print(f"📝 Text: {len(self.original_text)} chars")
        print(f"🎨 Styles: {[s.value for s in styles]}")
        pov = self._get_selected_pov()
        character_context = self._get_selected_characters_context()
        scene_description = self.scene_desc_edit.text().strip()
        print(f"🎭 Tones: {[t.value for t in tones]}")
        if custom_tone:
            print(f"✏️  Custom tone: {custom_tone}")
        if pov:
            print(f"👁️  POV: {pov}")
        if character_context:
            print(f"👤 POV Characters: {[item.text() for item in self.char_list.selectedItems()]}")
        if scene_description:
            print(f"🎬 Scene: {scene_description}")
        if self.surrounding_before or self.surrounding_after:
            print(f"📄 Surrounding context: {len(self.surrounding_before)} chars before, {len(self.surrounding_after)} chars after")
        print(f"{'#'*70}\n")

        # Look up offline thesaurus data to give the AI additional word options
        thesaurus_hint = ""
        try:
            from src.utils.thesaurus import get_synonyms, get_antonyms
            import re as _re
            # Extract key words from the selection for lookup
            words = _re.findall(r'\b[a-zA-Z]{3,}\b', self.original_text)
            all_syns, all_ants = [], []
            for w in words[:3]:  # Lookup up to 3 key words
                syns = get_synonyms(w, max_results=8)
                ants = get_antonyms(w, max_results=4)
                if syns:
                    all_syns.append(f"{w}: {', '.join(syns)}")
                if ants:
                    all_ants.append(f"{w}: {', '.join(ants)}")
            if all_syns:
                thesaurus_hint = "Thesaurus synonyms: " + " | ".join(all_syns)
            if all_ants:
                thesaurus_hint += "\nThesaurus antonyms: " + " | ".join(all_ants)
        except Exception:
            pass

        # Append thesaurus data to scene description so it reaches the agent
        if thesaurus_hint:
            scene_description = (
                f"{scene_description}\n{thesaurus_hint}" if scene_description
                else thesaurus_hint
            )

        # Add RAG-based worldbuilding context if available
        rag_context = self._get_rag_worldbuilding()
        if rag_context:
            scene_description = (
                f"{scene_description}\nWORLDBUILDING CONTEXT:\n{rag_context}"
                if scene_description else f"WORLDBUILDING CONTEXT:\n{rag_context}"
            )

        # Show progress
        self.progress_bar.setVisible(True)
        self.generate_btn.setEnabled(False)
        self.results_group.setVisible(False)

        # Run in background
        self.worker = RephraseWorker(
            self.agent,
            self.original_text,
            styles,
            tones,
            custom_tone=custom_tone,
            pov=pov,
            character_context=character_context,
            scene_description=scene_description,
            surrounding_before=self.surrounding_before,
            surrounding_after=self.surrounding_after,
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

        # Show results and refinement
        self.results_group.setVisible(True)
        self.refine_group.setVisible(True)

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

    def _on_rating_clicked(self, value: str):
        """Track which rating button is active (radio-button behavior).

        For negative ratings (poor / bad) we ALSO log the currently
        previewed suggestion as a rejected sample immediately — those
        are the most valuable kind: rows the user explicitly disliked.
        DPO/preference training pairs them with the eventual accepted
        suggestion as the contrastive 'rejected' example.
        """
        # Radio behavior — uncheck the others
        for v, btn in (("excellent", self.rate_excellent_btn),
                       ("good", self.rate_good_btn),
                       ("poor", self.rate_poor_btn),
                       ("bad", self.rate_bad_btn)):
            btn.setChecked(v == value)
        self._selected_rating = value

        # Negative ratings are logged immediately so the user can keep
        # iterating without losing the disliked example.
        if value in ("poor", "bad"):
            preview = self.preview_edit.toPlainText().strip()
            if preview and preview != self.original_text.strip():
                try:
                    self._log_to_rephrase_db(
                        self.original_text, preview,
                        accepted=False, rating=value)
                except Exception as e:
                    print(f"[Rephrase] could not log negative: {e}")

    def _use_selected(self):
        """Use the selected/edited text and (if opted in) log the pair."""
        self.selected_text = self.preview_edit.toPlainText()
        # Capture for transfer-learning DB before closing — opt-in via OS settings
        try:
            # If the user accepted without explicitly rating, treat it as
            # 'good' — they liked it enough to use it.
            rating = self._selected_rating
            if rating in ("neutral", ""):
                rating = "good"
            self._log_to_rephrase_db(
                self.original_text, self.selected_text,
                accepted=True, rating=rating)
        except Exception as e:
            print(f"[Rephrase] could not log to DB: {e}")
        self.accept()

    def _log_to_rephrase_db(self, source: str, output: str,
                            accepted: bool = True, rating: str = "good"):
        """Persist this rephrase pair so the user can later fine-tune a
        model on it. Only runs if collection is enabled in settings.

        Args:
            accepted: True if the user inserted this back into their text.
            rating: One of excellent / good / neutral / poor / bad. Negative
                ratings (poor, bad) become DPO 'rejected' samples.
        """
        from src.data.rephrase_database import (
            get_rephrase_database, is_collection_enabled,
        )
        if not is_collection_enabled():
            return
        if not source or not output or source.strip() == output.strip():
            return

        # Pull the selected style/tone if we have a result handy
        style = ""
        if self.result and self.result.options:
            row = self.results_list.currentRow() if hasattr(self, 'results_list') else 0
            if 0 <= row < len(self.result.options):
                opt = self.result.options[row]
                style = f"{opt.style}/{opt.tone}".strip("/")

        # Genre from project prose profile, if present
        genre = ""
        try:
            if self.project and getattr(self.project, 'prose_profile', None):
                genre = getattr(self.project.prose_profile, 'genre', '') or ""
        except Exception:
            pass

        # Best-effort speaker detection (we already do this for prompts)
        character = ""
        try:
            character = getattr(self, '_detected_character', '') or ""
        except Exception:
            pass

        db = get_rephrase_database()
        db.log_rephrase(
            source_text=source.strip(),
            output_text=output.strip(),
            style=style,
            surrounding_before=self.surrounding_before or "",
            surrounding_after=self.surrounding_after or "",
            character_name=character,
            genre=genre,
            accepted=accepted,
            rating=rating,
            project_path=getattr(getattr(self.project, 'project_path', ''),
                                 '__str__', lambda: '')()
                         if self.project else "",
        )

    def _refine_results(self):
        """Refine the current results with a follow-up instruction."""
        instruction = self.refine_edit.text().strip()
        if not instruction:
            return
        if not self.result or not self.result.options:
            return

        # Get the currently previewed text as the starting point
        current_text = self.preview_edit.toPlainText().strip()
        if not current_text:
            current_text = self.original_text

        # Collect what was previously generated so we can tell the AI to avoid it
        previous_options = [opt.text[:100] for opt in self.result.options]

        # Log to history
        self._refinement_history.append(instruction)
        history_text = "\n".join(
            f"> {h}" for h in self._refinement_history
        )
        self.refine_history.setPlainText(history_text)
        self.refine_edit.clear()

        # Build refinement context that goes into scene_description
        # This is the most natural place since the agent includes it in the prompt
        refinement_block = (
            "CRITICAL REFINEMENT INSTRUCTIONS — follow these exactly:\n"
        )
        for h in self._refinement_history:
            refinement_block += f"  - {h}\n"
        refinement_block += (
            f"\nThe current version is: \"{current_text}\"\n"
            "Generate COMPLETELY DIFFERENT phrasings that address the feedback above.\n"
        )
        if previous_options:
            rejected = ' | '.join(f'"{p}"' for p in previous_options[:5])
            refinement_block += f"Do NOT repeat these: {rejected}\n"

        # Store the original scene desc once, then append refinement
        if not hasattr(self, '_original_scene_desc'):
            self._original_scene_desc = self.scene_desc_edit.text()

        self.scene_desc_edit.setText(
            f"{self._original_scene_desc}\n{refinement_block}" if self._original_scene_desc
            else refinement_block
        )
        self._generate_options()
        # Restore for next user edit
        self.scene_desc_edit.setText(self._original_scene_desc)

    def _detect_speaker_for_rephrase(self) -> str:
        """Detect the speaker from chapter context and return character details.

        This is a synchronous call used during generate_options when
        auto-detect is selected. Returns a character context string.
        """
        if not self.chapter_content:
            return ""

        # Build passage around selection
        sel_pos = self.chapter_content.find(self.original_text)
        if sel_pos >= 0:
            start = max(0, sel_pos - 1500)
            end = min(len(self.chapter_content), sel_pos + len(self.original_text) + 500)
            passage = self.chapter_content[start:end]
        else:
            passage = self.surrounding_before[-1000:] + self.original_text + self.surrounding_after[:500]

        # Try to detect using the agent's LLM if available
        try:
            llm = None
            if hasattr(self.agent, 'llm_client') and self.agent.llm_client:
                llm = self.agent.llm_client
            elif hasattr(self.agent, '_init_cloud_llm'):
                # Try to get any available LLM
                from src.config.ai_config import get_ai_config
                from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig
                config = get_ai_config()
                settings = config.get_settings()

                prefer_local = settings.get("prefer_local_model", False)
                enable_local = settings.get("enable_local_models", False)
                local_model_id = settings.get("local_model_id", "")

                if prefer_local and enable_local and local_model_id:
                    is_mlx = "mlx" in local_model_id.lower()
                    hf_config = HuggingFaceConfig(
                        model_id=local_model_id, use_local=True,
                        device=settings.get("local_model_device", "auto"),
                        quantization=settings.get("local_model_quantization", "none")
                            if settings.get("local_model_quantization") != "none" else None,
                        trust_remote_code=settings.get("local_model_trust_remote_code", False)
                    )
                    provider = LLMProvider.MLX_LOCAL if is_mlx else LLMProvider.HUGGINGFACE_LOCAL
                    llm = LLMClient(provider=provider, hf_config=hf_config)
                else:
                    provider_name = settings.get("default_llm", "claude").lower()
                    api_key = config.get_api_key(provider_name)
                    if api_key:
                        provider_enum = {
                            "claude": LLMProvider.CLAUDE, "chatgpt": LLMProvider.CHATGPT,
                            "openai": LLMProvider.CHATGPT, "gemini": LLMProvider.GEMINI,
                        }.get(provider_name, LLMProvider.CLAUDE)
                        llm = LLMClient(
                            provider=provider_enum, api_key=api_key,
                            model=config.get_model(provider_name)
                        )

            if not llm:
                return ""

            # Detect speaker
            system_prompt = (
                "Read the passage and determine which character is speaking or "
                "thinking near the bracketed text. Base your answer ONLY on the text. "
                "The speaker may be a minor character.\n\n"
                "Respond:\nCHARACTER: <name>\nREASON: <evidence>"
            )
            chars_ref = ""
            if self.project and hasattr(self.project, 'characters'):
                chars_ref = "\n".join(
                    f"- {c.name} ({c.character_type})"
                    for c in self.project.characters
                )

            prompt = f"PASSAGE:\n...{passage}...\n\n"
            if chars_ref:
                prompt += f"Known characters (reference only):\n{chars_ref}\n\n"
            prompt += "Who is speaking?"

            response = llm.generate_text(
                prompt=prompt, system_prompt=system_prompt,
                max_tokens=200, temperature=0.2, task_type="speaker_detect"
            )

            # Parse name
            detected_name = ""
            reason = ""
            for line in response.strip().split('\n'):
                line = line.strip()
                if line.upper().startswith("CHARACTER:"):
                    detected_name = line[len("CHARACTER:"):].strip()
                elif line.upper().startswith("REASON:"):
                    reason = line[len("REASON:"):].strip()

            if not detected_name:
                return ""

            self.detect_status_label.setText(f"Detected: <b>{detected_name}</b> — {reason}")
            self.detect_status_label.setVisible(True)

            # Match to known character
            if self.project and hasattr(self.project, 'characters'):
                name_lower = detected_name.lower()
                for c in self.project.characters:
                    if c.name.lower() == name_lower or name_lower in c.name.lower():
                        # Build full context from known character
                        return self._build_character_context_from_obj(c)

            # Unknown character — infer from text
            infer_prompt = (
                f"Based on this passage, describe {detected_name}'s personality, "
                "speaking style, and emotional state in 3-4 lines."
            )
            inferred = llm.generate_text(
                prompt=f"PASSAGE:\n{passage}\n\n{infer_prompt}",
                system_prompt="You are a literary analyst. Be concise.",
                max_tokens=200, temperature=0.3, task_type="personality_infer"
            )
            return f"Name: {detected_name}\n{inferred.strip()}"

        except Exception as e:
            print(f"Speaker detection for rephrase failed: {e}")
            return ""

    def _build_character_context_from_obj(self, c) -> str:
        """Build character context string from a Character object."""
        desc = [f"Name: {c.name}", f"Role: {c.character_type}"]
        if c.personality:
            desc.append(f"Personality: {c.personality}")
        if getattr(c, 'personality_traits', None):
            desc.append(f"Key traits: {', '.join(c.personality_traits)}")
        if getattr(c, 'speaking_style', None):
            desc.append(f"Speaking style: {c.speaking_style}")
        if getattr(c, 'motivations', None):
            desc.append(f"Motivations: {c.motivations}")
        if getattr(c, 'emotional_baseline', None):
            desc.append(f"Emotional baseline: {c.emotional_baseline}")
        if getattr(c, 'personality_arc', None) and c.personality_arc:
            latest = c.personality_arc[-1]
            if latest.emotional_state:
                desc.append(f"Current emotional state: {latest.emotional_state}")
            if latest.growth_notes:
                desc.append(f"Recent development: {latest.growth_notes[:200]}")
        if c.backstory:
            desc.append(f"Backstory: {c.backstory[:300]}")
        return "\n".join(desc)

    def _get_rag_worldbuilding(self) -> str:
        """Use RAG to retrieve relevant worldbuilding context for the text."""
        if not self.project:
            return ""
        try:
            from src.ai.enhanced_rag import EnhancedRAGSystem
            from src.ai.semantic_search import SearchMethod

            rag = EnhancedRAGSystem(project=self.project)
            rag.rebuild_index()

            query = self.original_text
            if self.surrounding_before:
                query = self.surrounding_before[-200:] + " " + query
            if self.surrounding_after:
                query = query + " " + self.surrounding_after[:200]

            context = rag.get_context_for_ai(
                query=query, max_tokens=1000, method=SearchMethod.HYBRID
            )
            return context if context else ""
        except Exception:
            return ""

    def get_selected_text(self) -> Optional[str]:
        """Get the selected replacement text."""
        return self.selected_text
