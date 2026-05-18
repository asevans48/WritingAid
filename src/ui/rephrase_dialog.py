"""Dialog for AI-powered text rephrasing with multiple options."""

from typing import Optional, List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QListWidget, QListWidgetItem, QGroupBox,
    QRadioButton, QButtonGroup, QProgressBar, QMessageBox,
    QCheckBox, QLineEdit, QFrame, QSplitter, QWidget, QScrollArea,
    QComboBox
)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal

from src.ai.rephrasing_agent import RephrasingAgent, RephraseStyle, RephraseTone, RephraseResult
from src.ai.mlx_utils import can_use_mlx


class RephraseWorker(QThread):
    """Background worker for rephrasing operation."""

    finished = pyqtSignal(object)  # RephraseResult
    error = pyqtSignal(str)

    def __init__(self, agent: RephrasingAgent, text: str, styles: List[RephraseStyle],
                 tones: List[RephraseTone], custom_tone: str = "",
                 pov: str = "", character_context: str = "",
                 pov_character_context: str = "",
                 multi_speaker_attributions: list = None,
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
        # POV character profile (when distinct from the speaker).
        # Defaults empty so existing callers keep working — the
        # agent treats empty == "POV is the speaker".
        self.pov_character_context = pov_character_context
        # Per-line speaker attributions — populated when the
        # rephrase target contains lines from multiple characters.
        # When set, takes priority over character_context (the
        # speakers are already covered with full profiles + line
        # attributions in this list).
        self.multi_speaker_attributions = (
            multi_speaker_attributions or [])
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
                pov_character_context=self.pov_character_context,
                multi_speaker_attributions=(
                    self.multi_speaker_attributions),
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
        # Edit tracking: when the user types into preview_edit, this
        # flips True so we can warn before clobbering the edit on
        # option-switch and so Use Selected logs the edited text
        # rather than the original. Reset to False each time we
        # programmatically populate the preview (option-switch).
        self._preview_dirty: bool = False
        self._original_option_text: str = ""  # what was in preview before edits

        # Debounced training-data save for ratings. Writing on the
        # click instant loses in-flight edits (the user clicks Poor
        # and then keeps correcting the prose) — the corpus row is
        # the high-value piece, so we wait for the edit to settle
        # before persisting. _on_preview_text_changed restarts the
        # timer on each keystroke; _on_option_selected and
        # _refine_results flush pending saves before clobbering
        # the preview so the rating doesn't vanish silently.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(900)
        self._save_timer.timeout.connect(self._flush_pending_rating_save)
        self._pending_rating: str = ""
        self._last_saved_sig: tuple = ()

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

        # Genre dropdown — gives the LLM a register cue and tags the
        # logged rephrase pair with a canonical genre key. Pulled from
        # ``src.data.genres`` so the same taxonomy that drives the
        # Training Studio's filters drives this picker too. The first
        # entry "(use project default)" inherits from the active
        # project's prose_profile.genre (filled in below); selecting
        # a specific genre overrides for this single rephrase.
        genre_row = QHBoxLayout()
        genre_row.setContentsMargins(0, 0, 0, 0)
        genre_label = QLabel("Genre:")
        genre_label.setStyleSheet("font-size: 10px; color: #6b7280;")
        genre_row.addWidget(genre_label)
        self.genre_combo = QComboBox()
        self.genre_combo.addItem("(use project default)", "")
        try:
            from src.data.genres import GENRES, display_name as _gname
            for key in sorted(GENRES.keys()):
                self.genre_combo.addItem(_gname(key), key)
        except Exception:
            pass
        self.genre_combo.setToolTip(
            "Tell the AI which genre to lean into when rephrasing. "
            "Pre-filled from your project's prose profile if set; "
            "pick a specific genre to override for just this "
            "rephrase. Logged with the rephrase pair so future "
            "trained models can route by genre.")
        self.genre_combo.setStyleSheet("font-size: 10px; padding: 2px;")
        # Pre-select from project.prose_profile.genre if available.
        try:
            if (self.project
                    and getattr(self.project, "prose_profile", None)):
                proj_genre = (getattr(
                    self.project.prose_profile, "genre", "")
                    or "").strip().lower()
                if proj_genre:
                    # Try canonical match first, then fuzzy via match_genres.
                    idx = self.genre_combo.findData(proj_genre)
                    if idx < 0:
                        try:
                            from src.data.genres import match_genres
                            matched = match_genres(proj_genre)
                            if matched:
                                idx = self.genre_combo.findData(matched[0])
                        except Exception:
                            pass
                    if idx >= 0:
                        self.genre_combo.setCurrentIndex(idx)
        except Exception:
            pass
        genre_row.addWidget(self.genre_combo, 1)
        layout.addLayout(genre_row)

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

        # Header row for the preview pane: title + edit-state badge +
        # Reset button. Makes it explicit that the preview is
        # editable and gives a one-click way to undo an edit.
        preview_header = QHBoxLayout()
        preview_header.setContentsMargins(0, 0, 0, 0)
        preview_label = QLabel(
            "<b>Preview & Edit</b> "
            "<span style='color:#9ca3af;font-size:11px;'>"
            "— click in the box below to tweak before saving"
            "</span>")
        preview_header.addWidget(preview_label)
        preview_header.addStretch()
        # Edit-state badge: hidden until the user types; flips to
        # "✏️ edited" so the user knows their edit will be saved
        # (instead of the original option text).
        self._edit_badge = QLabel("")
        self._edit_badge.setStyleSheet(
            "background: #fef3c7; color: #92400e; "
            "border-radius: 3px; padding: 1px 6px; font-size: 10px;")
        self._edit_badge.setVisible(False)
        preview_header.addWidget(self._edit_badge)
        # Reset-to-original button — appears when the preview is
        # dirty so the user can revert without re-clicking the row.
        self._reset_edit_btn = QPushButton("↺ Reset")
        self._reset_edit_btn.setToolTip(
            "Restore the option's original text (drops your edits).")
        self._reset_edit_btn.setStyleSheet(
            "QPushButton { padding: 2px 8px; font-size: 10px; "
            " border: 1px solid #d1d5db; border-radius: 3px; "
            " background: white; color: #374151; }"
            "QPushButton:hover { border-color: #6b7280; }")
        self._reset_edit_btn.setVisible(False)
        self._reset_edit_btn.clicked.connect(self._reset_preview_edit)
        preview_header.addWidget(self._reset_edit_btn)
        preview_layout.addLayout(preview_header)

        self.preview_edit = QTextEdit()
        self.preview_edit.setPlaceholderText(
            "Select an option to preview. You can edit the text "
            "directly in this box — your edits override the "
            "selected option when you click Use.")
        self.preview_edit.textChanged.connect(
            self._on_preview_text_changed)
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
        # Surfaces the debounced-save state so the user can see when
        # their rating + edit actually lands in the corpus instead
        # of guessing.
        self._save_status_label = QLabel("")
        self._save_status_label.setStyleSheet(
            "color: #6b7280; font-size: 11px; font-style: italic;")
        rating_row.addWidget(self._save_status_label)
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

    def _get_selected_genre(self) -> str:
        """Return the canonical genre key the user picked, or empty
        when "(use project default)" is selected. The DB-log path
        falls back to project.prose_profile.genre when this returns
        empty so the existing behaviour is preserved."""
        try:
            return self.genre_combo.currentData() or ""
        except Exception:
            return ""

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
        # When the chapter has a configured POV character that
        # differs from the speaker we just detected, ship the POV
        # character's profile separately so the agent can apply
        # speaker rules to dialog and POV rules to narration. The
        # auto-detect speaker pipeline always produces the speaker;
        # the chapter's planning.pov_character is the narration
        # anchor. They're often the same person; when they're not,
        # the agent now handles both correctly.
        pov_character_context = self._build_pov_character_context(
            speaker_context=character_context)

        # Multi-speaker detection: when the rephrase text has 2+
        # quoted lines, run a speaker-attribution LLM call so the
        # agent can keep each speaker's voice distinct. Falls back
        # to the single-speaker path silently when there's nothing
        # multi-speaker to detect or no LLM available.
        multi_speaker_attributions: list = []
        try:
            from src.ai.rephrasing_agent import (
                _text_contains_dialog, _extract_quoted_lines,
            )
            if (_text_contains_dialog(self.original_text)
                    and len(_extract_quoted_lines(
                        self.original_text)) >= 2):
                multi_speaker_attributions = (
                    self._detect_multi_speaker_attributions())
                if multi_speaker_attributions:
                    print(
                        f"🗣  Multi-speaker dialog detected: "
                        f"{[a['speaker_name'] for a in multi_speaker_attributions]}")
                    # Surface the detection result in the UI so the
                    # user sees who got attributed which lines
                    # before the rephrase fires.
                    bits = [
                        f"<b>{a['speaker_name']}</b> "
                        f"({len(a['lines'])} line"
                        f"{'s' if len(a['lines']) != 1 else ''})"
                        for a in multi_speaker_attributions]
                    self.detect_status_label.setText(
                        "Multi-speaker dialog: " + ", ".join(bits))
                    self.detect_status_label.setVisible(True)
        except Exception as e:
            print(f"[multi-speaker] detection failed: {e}")

        scene_description = self.scene_desc_edit.text().strip()

        # Genre cue prepended to scene description so the LLM sees
        # it without changing the agent's signature. Only fires
        # when the user picked a specific genre — "(use project
        # default)" leaves the project's prose_profile.genre alone
        # (the agent already pulls that from the project).
        genre_choice = self._get_selected_genre()
        if genre_choice:
            try:
                from src.data.genres import display_name as _gn
                genre_label = _gn(genre_choice)
            except Exception:
                genre_label = genre_choice
            genre_clause = (
                f"Target genre: {genre_label}. Lean into the prose "
                f"register, vocabulary, and conventions of this genre.")
            scene_description = (
                f"{genre_clause} {scene_description}"
                if scene_description else genre_clause)
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
            pov_character_context=pov_character_context,
            multi_speaker_attributions=(
                multi_speaker_attributions),
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
        """Handle option selection.

        If the user has already edited the preview when they pick a
        different option, ask whether to discard the edit before
        clobbering it. Without the confirm, work would silently
        disappear when the user moused over to compare options. We
        also reset the dirty flag so the freshly-loaded option
        starts un-edited.
        """
        if row < 0 or not self.result or row >= len(self.result.options):
            # Suppress textChanged side-effects while we clear.
            self._loading_preview = True
            self.preview_edit.clear()
            self._loading_preview = False
            self.style_label.clear()
            self.use_btn.setEnabled(False)
            self._set_preview_dirty(False)
            return

        # Persist any pending rating for the option the user is
        # leaving — switching options replaces the preview, so the
        # rating + edit would otherwise vanish before the debounce
        # timer fires.
        if self._pending_rating:
            self._save_timer.stop()
            self._flush_pending_rating_save()

        # Confirm before discarding an in-progress edit.
        if self._preview_dirty:
            from PyQt6.QtWidgets import QMessageBox
            current = self.preview_edit.toPlainText().strip()
            original = (self._original_option_text or '').strip()
            if current and current != original:
                resp = QMessageBox.question(
                    self,
                    "Discard your edit?",
                    "You've edited the preview text. Switching to "
                    "another option will replace your edit.\n\n"
                    "Discard the edit and load the new option?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                if resp != QMessageBox.StandardButton.Yes:
                    # Bounce the selection back to whatever option
                    # the edit came from. Find it by matching the
                    # original text against the options list.
                    self._loading_preview = True
                    try:
                        self._restore_previous_selection()
                    finally:
                        self._loading_preview = False
                    return

        option = self.result.options[row]
        # Programmatic populate — silence the dirty signal.
        self._loading_preview = True
        try:
            self.preview_edit.setPlainText(option.text)
        finally:
            self._loading_preview = False
        self._original_option_text = option.text
        self.style_label.setText(f"Style: {option.style} | Tone: {option.tone} — {option.explanation}")
        self.use_btn.setEnabled(True)
        self._set_preview_dirty(False)
        # Clear the save-status hint so a "✓ Saved as good" from the
        # previous option doesn't linger and mislead the user about
        # the freshly-loaded one.
        self._update_save_status("", ok=True)

    def _restore_previous_selection(self):
        """Re-select the option whose text matches what's currently
        in the preview's saved-original. Called when the user
        cancels the discard-edit confirm so they don't end up with
        the new option highlighted but their old edit shown."""
        if not self.result:
            return
        target = (self._original_option_text or '').strip()
        for i, opt in enumerate(self.result.options):
            if opt.text.strip() == target:
                self.options_list.blockSignals(True)
                try:
                    self.options_list.setCurrentRow(i)
                finally:
                    self.options_list.blockSignals(False)
                return

    def _on_preview_text_changed(self):
        """Track whether the preview has been edited.

        Suppressed while we programmatically setPlainText (the
        ``_loading_preview`` flag) so option-switches don't trip
        the dirty flag falsely.
        """
        if getattr(self, '_loading_preview', False):
            return
        if not self.result:
            return
        current = self.preview_edit.toPlainText()
        is_dirty = current.strip() != (
            self._original_option_text or '').strip()
        if is_dirty != self._preview_dirty:
            self._set_preview_dirty(is_dirty)
        # Keep restarting the debounce while the user is still
        # typing — the row that finally lands in the corpus should
        # be their final text, not whatever was on screen when
        # they clicked the rating button.
        if self._pending_rating:
            self._save_timer.start()
            self._update_save_status(
                f"Saving as {self._pending_rating} after you finish editing…",
                pending=True)

    def _set_preview_dirty(self, dirty: bool) -> None:
        """Flip the dirty flag and update the badge / button label."""
        self._preview_dirty = dirty
        if dirty:
            self._edit_badge.setText("✏️ edited")
            self._edit_badge.setVisible(True)
            self._reset_edit_btn.setVisible(True)
            if hasattr(self, 'use_btn'):
                self.use_btn.setText("✓ Use My Edited Version")
        else:
            self._edit_badge.setVisible(False)
            self._reset_edit_btn.setVisible(False)
            if hasattr(self, 'use_btn'):
                self.use_btn.setText("Use Selected")

    def _reset_preview_edit(self) -> None:
        """Restore the preview to the originally-loaded option text."""
        if self._original_option_text is None:
            return
        self._loading_preview = True
        try:
            self.preview_edit.setPlainText(self._original_option_text)
        finally:
            self._loading_preview = False
        self._set_preview_dirty(False)

    def _on_rating_clicked(self, value: str):
        """Track the active rating and schedule a debounced save.

        Every rating (positive AND negative) queues a write to the
        corpus on a short timer. Edits to the preview restart the
        timer so the row that lands carries the user's final text
        with the was_edited flag set — saving on the click instant
        would lose corrections the user is still typing. The
        contrastive un-edited row that _use_selected normally
        writes is preserved through that path.
        """
        # Radio behavior — uncheck the others
        for v, btn in (("excellent", self.rate_excellent_btn),
                       ("good", self.rate_good_btn),
                       ("poor", self.rate_poor_btn),
                       ("bad", self.rate_bad_btn)):
            btn.setChecked(v == value)
        self._selected_rating = value
        self._pending_rating = value
        self._update_save_status(
            f"Saving as {value} after you finish editing…",
            pending=True)
        self._save_timer.start()

    def _flush_pending_rating_save(self):
        """Persist the queued rated suggestion to the corpus.

        Reads the preview at call time so any edits made while the
        debounce was running are captured, and stamps was_edited
        when the preview is dirty. Called by the timer, by option-
        switch, and by refinement — anywhere the preview is about
        to change or the user has stopped touching it.
        """
        if not self._pending_rating:
            return
        rating = self._pending_rating
        self._pending_rating = ""
        output = self.preview_edit.toPlainText().strip()
        if not output or output == self.original_text.strip():
            self._update_save_status(
                "Nothing saved — preview is empty or matches the source.",
                ok=False)
            return
        accepted = rating in ("excellent", "good")
        was_edited = bool(self._preview_dirty)
        sig = (rating, accepted, hash(output))
        if sig == self._last_saved_sig:
            self._update_save_status(
                f"Already saved as {rating}.", ok=True)
            return
        try:
            self._log_to_rephrase_db(
                self.original_text, output,
                accepted=accepted, rating=rating,
                was_edited=was_edited)
            self._last_saved_sig = sig
            tail = " (edited)" if was_edited else ""
            self._update_save_status(
                f"✓ Saved as {rating}{tail} for training", ok=True)
        except Exception as e:
            self._update_save_status(f"Save failed: {e}", ok=False)

    def _update_save_status(self, text: str, ok: bool = True,
                            pending: bool = False) -> None:
        """Update the inline save-status hint next to the rating row."""
        if not hasattr(self, '_save_status_label'):
            return
        if pending:
            color = "#6b7280"
        else:
            color = "#059669" if ok else "#dc2626"
        self._save_status_label.setText(text)
        self._save_status_label.setStyleSheet(
            f"color: {color}; font-size: 11px; font-style: italic;")

    def _use_selected(self):
        """Use the selected/edited text and (if opted in) log the pair.

        Three cases the rating + edit combination can produce:
          1. Rated + un-edited → log the option's original text at
             that rating.
          2. Rated + edited → log the EDITED text at that rating
             (the edit is what the user actually wants saved).
          3. Un-rated (anything → "good" by default) + un-edited or
             edited → log whichever text is in preview_edit.

        In every case, the saved row reflects what's in the
        preview box at click time. The original (un-edited) option
        is ALSO logged separately as a "good" reference sample
        when it differs from the edit, so the training data
        captures the contrast (this is the same kind of signal
        DPO/preference training looks for).
        """
        # Stop the debounce — _use_selected does the explicit
        # accepted=True write below; letting the timer also fire
        # would race against dialog teardown.
        self._save_timer.stop()
        pending = self._pending_rating
        self._pending_rating = ""

        edited = self.preview_edit.toPlainText()
        was_edited = bool(self._preview_dirty)
        original_option = self._original_option_text or ''
        self.selected_text = edited
        # If the user accepted without explicitly rating, treat it as
        # 'good' — they liked it enough to use it.
        rating = self._selected_rating
        if rating in ("neutral", ""):
            rating = "good"
        try:
            # If a negative rating was queued and would have fired
            # any moment, persist that "rejected" signal first — the
            # user explicitly flagged this suggestion as Poor/Bad
            # even if they're about to use it anyway, and DPO
            # training relies on that signal.
            if pending in ("poor", "bad"):
                neg_sig = (pending, False, hash(edited.strip()))
                if neg_sig != self._last_saved_sig:
                    self._log_to_rephrase_db(
                        self.original_text, edited,
                        accepted=False, rating=pending,
                        was_edited=was_edited)
                    self._last_saved_sig = neg_sig
            # Primary log: the text the user actually committed to.
            primary_sig = (rating, True, hash(edited.strip()))
            if primary_sig != self._last_saved_sig:
                self._log_to_rephrase_db(
                    self.original_text, edited,
                    accepted=True, rating=rating,
                    was_edited=was_edited)
                self._last_saved_sig = primary_sig
            # Secondary log: when the user edited the option, also
            # log the un-edited original at a neutral rating so the
            # training data has both versions as a comparison
            # signal. Skip when they're identical (no edit) or when
            # the original option text matches the source text
            # (would log a no-op).
            if (was_edited
                    and original_option.strip()
                    and original_option.strip() != edited.strip()
                    and original_option.strip()
                        != self.original_text.strip()):
                self._log_to_rephrase_db(
                    self.original_text, original_option,
                    accepted=False, rating="neutral",
                    was_edited=False)
        except Exception as e:
            print(f"[Rephrase] could not log to DB: {e}")
        self.accept()

    def _log_to_rephrase_db(self, source: str, output: str,
                            accepted: bool = True,
                            rating: str = "good",
                            was_edited: bool = False):
        """Persist this rephrase pair so the user can later fine-tune a
        model on it. Only runs if collection is enabled in settings.

        Args:
            accepted: True if the user inserted this back into their text.
            rating: One of excellent / good / neutral / poor / bad. Negative
                ratings (poor, bad) become DPO 'rejected' samples.
            was_edited: True when the saved ``output`` was edited by
                the user from the original AI suggestion. Stamped
                into the row's style field as a tag so training-data
                selection can prefer human-edited examples.
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
        # Tag rows that were edited so training pipelines can
        # weight or filter on human-touched examples. Appended to
        # the style field rather than a new schema column to keep
        # the rephrase DB migration-free.
        if was_edited:
            style = (style + " | edited").strip(" |")

        # Genre — the user's explicit dropdown pick wins. Falls back
        # to the project's prose_profile genre if the dropdown is on
        # "(use project default)". Logged into the rephrase DB so
        # future training runs can route by genre with the same
        # canonical key the Training Studio uses.
        genre = ""
        try:
            genre = self._get_selected_genre()
        except Exception:
            pass
        if not genre:
            try:
                if (self.project
                        and getattr(self.project, 'prose_profile',
                                    None)):
                    genre = getattr(
                        self.project.prose_profile, 'genre', '') or ""
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

        # Refinement will replace the current options + preview, so
        # flush any pending rating for the about-to-be-clobbered
        # suggestion first.
        if self._pending_rating:
            self._save_timer.stop()
            self._flush_pending_rating_save()

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

    def _detect_multi_speaker_attributions(self) -> list:
        """Try to map each quoted line in the rephrase text to a
        speaker, with their character profile.

        Returns ``[]`` when:
          * The text has fewer than 2 quoted lines (no point — the
            single-speaker path handles 0 or 1 line).
          * No LLM is available for the detection call.
          * The detection call fails or returns nothing parseable.

        Otherwise returns a list of dicts the agent's
        ``multi_speaker_attributions`` kwarg expects:
            [{"speaker_name": str, "character_context": str,
              "lines": [str], "evidence": str}, ...]

        One entry per UNIQUE speaker, with all of that speaker's
        attributed lines collected together.
        """
        from src.ai.rephrasing_agent import _extract_quoted_lines
        quoted = _extract_quoted_lines(self.original_text)
        if len(quoted) < 2:
            return []

        # Build a passage with surrounding context — needed to
        # disambiguate "he said" / "she said" tags that the
        # rephrase selection alone wouldn't resolve.
        sel_pos = -1
        if self.chapter_content:
            sel_pos = self.chapter_content.find(self.original_text)
        if sel_pos >= 0:
            start = max(0, sel_pos - 1500)
            end = min(len(self.chapter_content),
                       sel_pos + len(self.original_text) + 800)
            passage = self.chapter_content[start:end]
        else:
            passage = (self.surrounding_before[-1200:]
                       + self.original_text
                       + self.surrounding_after[:600])

        # Reuse the agent's LLM client (avoids re-initialising one).
        llm = None
        if hasattr(self.agent, 'llm_client') and self.agent.llm_client:
            llm = self.agent.llm_client
        if llm is None:
            try:
                llm = self._get_or_build_llm()
            except Exception:
                llm = None
        if llm is None:
            print("[multi-speaker] no LLM available — skipping")
            return []

        chars_ref = ""
        if self.project and hasattr(self.project, 'characters'):
            chars_ref = "\n".join(
                f"- {c.name} ({c.character_type})"
                for c in self.project.characters)

        # Format the quoted lines as a numbered list so the model
        # can refer to each by index in its reply.
        numbered_lines = "\n".join(
            f"{i+1}. \"{q}\""
            for i, q in enumerate(quoted))

        system_prompt = (
            "You map each quoted line to its speaker using ONLY "
            "evidence in the passage. Be conservative — if a line "
            "is genuinely ambiguous, mark it 'unknown' rather than "
            "guessing. The output is consumed by another model and "
            "must follow the format exactly.\n\n"
            "OUTPUT FORMAT — one block per quoted line, in order:\n"
            "  LINE 1: <full line text>\n"
            "  SPEAKER: <name or 'unknown'>\n"
            "  EVIDENCE: <one short phrase from the passage that "
            "ties this line to this speaker, or 'inferred from "
            "alternation' / 'inferred from action beat' / "
            "'unclear'>\n\n"
            "  LINE 2: …\n"
            "  …")

        prompt = (
            f"PASSAGE (with the rephrase target inside it):\n"
            f"...{passage}...\n\n"
            f"QUOTED LINES IN THE REPHRASE TARGET (map each to "
            f"its speaker):\n{numbered_lines}\n\n")
        if chars_ref:
            prompt += (
                f"Known characters in the project (reference only "
                f"— a speaker may also be a minor character not "
                f"listed here):\n{chars_ref}\n\n")
        prompt += "Map each line to its speaker now."

        try:
            response = llm.generate_text(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=600,
                temperature=0.1,
                task_type="multi_speaker_detect")
        except Exception as e:
            print(f"[multi-speaker] LLM call failed: {e}")
            return []

        # Parse the LINE/SPEAKER/EVIDENCE blocks.
        import re
        per_line: list = []  # [(line_text, speaker, evidence)]
        cur = {}
        for raw in response.splitlines():
            line = raw.strip()
            if not line:
                continue
            m = re.match(r'LINE\s*\d+\s*:\s*(.+)$',
                         line, re.IGNORECASE)
            if m:
                if cur.get('line'):
                    per_line.append(
                        (cur['line'],
                         cur.get('speaker', '').strip(),
                         cur.get('evidence', '').strip()))
                cur = {'line': m.group(1).strip().strip('"“”')}
                continue
            m = re.match(r'SPEAKER\s*:\s*(.+)$', line,
                         re.IGNORECASE)
            if m:
                cur['speaker'] = m.group(1).strip()
                continue
            m = re.match(r'EVIDENCE\s*:\s*(.+)$', line,
                         re.IGNORECASE)
            if m:
                cur['evidence'] = m.group(1).strip()
                continue
        if cur.get('line'):
            per_line.append(
                (cur['line'],
                 cur.get('speaker', '').strip(),
                 cur.get('evidence', '').strip()))

        # Group by speaker so each character gets one entry with
        # all their attributed lines.
        by_speaker: dict = {}
        for line_text, speaker, evidence in per_line:
            if not speaker or speaker.lower() in ('unknown', '?'):
                continue
            key = speaker.strip()
            if key not in by_speaker:
                by_speaker[key] = {
                    'speaker_name': key,
                    'lines': [],
                    'evidence_bits': [],
                    'character_context': '',
                }
            by_speaker[key]['lines'].append(line_text)
            if evidence:
                by_speaker[key]['evidence_bits'].append(evidence)

        if len(by_speaker) < 2:
            # Not actually multi-speaker — fall back to single path.
            return []

        # Look each speaker up in the project's characters and
        # build their full profile. Unknown characters get a
        # minimal profile so the agent at least has the name.
        chars_by_name = {}
        if self.project and hasattr(self.project, 'characters'):
            chars_by_name = {
                c.name.lower(): c
                for c in self.project.characters}

        results = []
        for name, info in by_speaker.items():
            ch = chars_by_name.get(name.lower())
            if ch is None:
                # Try fuzzy contains match.
                for cand_name, cand in chars_by_name.items():
                    if (name.lower() in cand_name
                            or cand_name in name.lower()):
                        ch = cand
                        break
            if ch is not None:
                profile = self._build_character_context_from_obj(ch)
            else:
                profile = (
                    f"Name: {name}\n"
                    f"(Speaker not in the project's character "
                    f"roster — voice rules will rely on their "
                    f"attributed lines + general dialog craft.)")
            info['character_context'] = profile
            info['evidence'] = " | ".join(
                info.pop('evidence_bits') or [])
            results.append(info)
        return results

    def _get_or_build_llm(self):
        """Build an LLM client from settings — used by the
        multi-speaker detector when the agent doesn't already
        have one cached."""
        from src.config.ai_config import get_ai_config
        from src.ai.llm_client import (
            LLMClient, LLMProvider, HuggingFaceConfig)
        cfg = get_ai_config()
        s = cfg.get_settings()
        if (s.get("prefer_local_model", False)
                and s.get("enable_local_models", False)
                and s.get("local_model_id")):
            mid = s["local_model_id"]
            is_mlx = "mlx" in mid.lower()
            hf = HuggingFaceConfig(
                model_id=mid, use_local=True,
                device=s.get("local_model_device", "auto"),
                quantization=(
                    s.get("local_model_quantization")
                    if s.get("local_model_quantization") not in (
                        "none", None) else None),
                trust_remote_code=s.get(
                    "local_model_trust_remote_code", False))
            provider = (LLMProvider.MLX_LOCAL if is_mlx
                        else LLMProvider.HUGGINGFACE_LOCAL)
            return LLMClient(provider=provider, hf_config=hf)
        provider_name = s.get("default_llm", "claude").lower()
        api_key = cfg.get_api_key(provider_name)
        if not api_key:
            return None
        provider_enum = {
            "claude": LLMProvider.CLAUDE,
            "chatgpt": LLMProvider.CHATGPT,
            "openai": LLMProvider.CHATGPT,
            "gemini": LLMProvider.GEMINI,
        }.get(provider_name, LLMProvider.CLAUDE)
        return LLMClient(
            provider=provider_enum, api_key=api_key,
            model=cfg.get_model(provider_name))

    def _build_pov_character_context(
            self, speaker_context: str = "") -> str:
        """Return the chapter's POV character profile when it
        differs from the speaker.

        Returns an empty string when:
          * The chapter has no configured POV character.
          * The POV character matches whoever is in
            ``speaker_context`` (no point sending two copies).
          * No project / chapter is loaded.

        The agent treats empty as 'POV is the speaker' and applies
        a single set of voice rules — that's the legacy behavior
        and the right default for narration-only or
        single-character scenes. The dual-context path only fires
        when the user has dialog from someone other than the POV
        character, which is the case the user asked us to handle
        properly.
        """
        if not self.chapter:
            return ""
        pov_name = (
            getattr(getattr(self.chapter, 'planning', None),
                    'pov_character', '') or '').strip()
        if not pov_name:
            return ""
        # Don't bother shipping POV separately if the speaker
        # context already names this character — the dual-profile
        # path would just be redundant copies.
        if pov_name and (
                f"Name: {pov_name}" in speaker_context
                or pov_name.lower() in speaker_context.lower()[:200]):
            return ""
        # Find the matching Character object on the project.
        if not self.project or not hasattr(self.project, 'characters'):
            return ""
        for c in self.project.characters:
            if c.name.lower() == pov_name.lower():
                return self._build_character_context_from_obj(c)
        # POV character is named but not in the cast — return what
        # we know so the model still has SOMETHING to anchor
        # narration to.
        return f"Name: {pov_name}\n(POV character — full profile not in cast list)"

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
