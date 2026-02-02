"""Manuscript editor with chapter navigation and revision system."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTextEdit, QToolBar, QComboBox, QSpinBox,
    QMessageBox, QInputDialog, QGroupBox, QSplitter, QFileDialog,
    QDialog, QMenu, QCheckBox, QLineEdit, QScrollArea, QFrame,
    QProgressBar, QRadioButton, QButtonGroup, QTabWidget,
    QApplication
)
from PyQt6.QtCore import pyqtSignal, Qt, QSize
from PyQt6.QtGui import QFont, QTextCursor, QAction, QTextCharFormat, QColor, QPainter, QTextDocument
from typing import List, Optional
import uuid
from pathlib import Path

from src.models.project import Manuscript, Chapter, Annotation, ChapterTodo, StoryEvent
from src.ui.enhanced_text_editor import EnhancedTextEditor, CheckMode
from src.ui.annotations import AnnotationDialog
from src.ui.annotation_list_dialog import AnnotationListDialog
from src.ui.chapter_planner_widget import ChapterPlannerWidget
from src.ai.chapter_memory import ChapterMemoryManager
from src.utils.markdown_editor import MarkdownStyle, toggle_inline_style
from src.utils.thesaurus import get_synonyms, get_antonyms


class AnnotationMarginArea(QWidget):
    """Custom widget for displaying annotation indicators in the margin."""

    annotation_clicked = pyqtSignal(int)  # line_number

    def __init__(self, editor):
        """Initialize margin area."""
        super().__init__(editor)
        self.editor = editor
        self.annotations = []

    def set_annotations(self, annotations):
        """Set annotations to display."""
        self.annotations = annotations
        self.update()

    def sizeHint(self):
        """Return size hint for margin."""
        return QSize(30, 0)

    def paintEvent(self, event):
        """Paint annotation indicators."""
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor(250, 250, 250))

        # Get document
        document = self.editor.document()

        # Iterate through all blocks in document
        block = document.begin()
        block_number = 0

        while block.isValid():
            line_number = block_number + 1

            # Check if this line has annotations
            line_annotations = [a for a in self.annotations if a.line_number == line_number]

            if line_annotations:
                # Get the block's position in the editor
                cursor = QTextCursor(block)
                rect = self.editor.cursorRect(cursor)

                # Only draw if within visible area
                if rect.top() >= -rect.height() and rect.top() <= self.height():
                    # Draw plus indicator
                    painter.setPen(QColor(100, 100, 255))
                    painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
                    painter.drawText(0, rect.top(), self.width(), rect.height(),
                                   Qt.AlignmentFlag.AlignCenter, "+")

            block = block.next()
            block_number += 1

    def mousePressEvent(self, event):
        """Handle click on annotation indicator."""
        # Get document
        document = self.editor.document()

        # Find which line was clicked by iterating through blocks
        block = document.begin()
        block_number = 0
        click_y = event.pos().y()

        while block.isValid():
            line_number = block_number + 1

            # Get the block's position in the editor
            cursor = QTextCursor(block)
            rect = self.editor.cursorRect(cursor)

            # Check if click was in this block's area
            if rect.top() <= click_y <= rect.top() + rect.height():
                # Check if this line has annotations
                if any(a.line_number == line_number for a in self.annotations):
                    self.annotation_clicked.emit(line_number)
                break

            block = block.next()
            block_number += 1


class ChapterEditor(QWidget):
    """Editor for a single chapter with formatting and AI hints."""

    content_changed = pyqtSignal()
    word_count_changed = pyqtSignal(int)
    annotations_changed = pyqtSignal()  # Signal when annotations are added/edited/deleted
    _prose_analysis_ready = pyqtSignal(str)  # Signal to deliver prose analysis result to main thread
    _character_analysis_ready = pyqtSignal(str)
    _world_analysis_ready = pyqtSignal(str)
    _plot_analysis_ready = pyqtSignal(str)

    def __init__(self, chapter: Chapter, project=None):
        """Initialize chapter editor."""
        super().__init__()
        self.chapter = chapter
        self.project = project
        self._llm_client = None
        self._prose_analysis_ready.connect(self._on_prose_analysis_complete)
        self._character_analysis_ready.connect(self._on_character_analysis_complete)
        self._world_analysis_ready.connect(self._on_world_analysis_complete)
        self._plot_analysis_ready.connect(self._on_plot_analysis_complete)
        self._init_ui()
        self._init_ai()
        self._load_chapter()

    def _init_ui(self):
        """Initialize user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Main horizontal splitter - editor on left, planner on right
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left side - editor container
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar - compact for small screens
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet("QToolBar { spacing: 2px; }")

        # Font family - compact
        self.font_combo = QComboBox()
        self.font_combo.addItems(["Arial", "Times New Roman", "Courier New", "Georgia", "Verdana"])
        self.font_combo.setMaximumWidth(100)
        self.font_combo.currentTextChanged.connect(self._change_font_family)
        toolbar.addWidget(self.font_combo)

        # Font size - compact
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 72)
        self.font_size_spin.setValue(12)
        self.font_size_spin.setMaximumWidth(50)
        # Block signals initially to prevent spurious valueChanged during initialization
        self.font_size_spin.blockSignals(True)
        self.font_size_spin.valueChanged.connect(self._change_font_size)
        self.font_size_spin.blockSignals(False)
        toolbar.addWidget(self.font_size_spin)

        toolbar.addSeparator()

        # Formatting buttons - compact with single letter + styling
        bold_action = QAction("B", self)
        bold_action.setShortcut("Ctrl+B")
        bold_action.setToolTip("Bold (Ctrl+B)")
        bold_action.triggered.connect(self._toggle_bold)
        toolbar.addAction(bold_action)

        italic_action = QAction("I", self)
        italic_action.setShortcut("Ctrl+I")
        italic_action.setToolTip("Italic (Ctrl+I)")
        italic_action.triggered.connect(self._toggle_italic)
        toolbar.addAction(italic_action)

        underline_action = QAction("U", self)
        underline_action.setShortcut("Ctrl+U")
        underline_action.setToolTip("Underline (Ctrl+U)")
        underline_action.triggered.connect(self._toggle_underline)
        toolbar.addAction(underline_action)

        toolbar.addSeparator()

        # Heading style dropdown - compact
        self.heading_combo = QComboBox()
        self.heading_combo.addItems(["Normal", "Title", "H1", "H2", "H3", "H4"])
        self.heading_combo.setToolTip("Apply heading style (exports properly to Word, HTML, Markdown)")
        self.heading_combo.setMaximumWidth(70)
        # Use activated instead of currentTextChanged so we can apply the same style multiple times
        self.heading_combo.activated.connect(self._on_heading_combo_activated)
        toolbar.addWidget(self.heading_combo)

        toolbar.addSeparator()

        # Writing checks toggle buttons (3-state: On-demand=green, Realtime=blue, Off=white)
        # Style templates for button states
        self._check_button_styles = {
            CheckMode.ON_DEMAND: "background-color: #86efac; color: black; font-weight: bold; padding: 2px 6px; border-radius: 3px;",
            CheckMode.REALTIME: "background-color: #93c5fd; color: black; font-weight: bold; padding: 2px 6px; border-radius: 3px;",
            CheckMode.OFF: "background-color: #f3f4f6; color: #6b7280; padding: 2px 6px; border-radius: 3px;",
        }

        self.spell_check_btn = QPushButton("ABC")
        self.spell_check_btn.setToolTip("Spell check: Click to cycle (Green=On-demand, Blue=Realtime, White=Off)")
        self.spell_check_btn.clicked.connect(self._toggle_spell_check)
        self._update_check_button_style(self.spell_check_btn, CheckMode.ON_DEMAND)
        toolbar.addWidget(self.spell_check_btn)

        self.grammar_check_btn = QPushButton("Gr")
        self.grammar_check_btn.setToolTip("Grammar check: Click to cycle (Green=On-demand, Blue=Realtime, White=Off)")
        self.grammar_check_btn.clicked.connect(self._toggle_grammar_check)
        self._update_check_button_style(self.grammar_check_btn, CheckMode.ON_DEMAND)
        toolbar.addWidget(self.grammar_check_btn)

        self.overuse_check_btn = QPushButton("Ov")
        self.overuse_check_btn.setToolTip("Overuse detection: Click to cycle (Green=On-demand, Blue=Realtime, White=Off)")
        self.overuse_check_btn.clicked.connect(self._toggle_overuse_check)
        self._update_check_button_style(self.overuse_check_btn, CheckMode.ON_DEMAND)
        toolbar.addWidget(self.overuse_check_btn)

        # Recheck button - compact with emoji
        self.recheck_btn = QPushButton("🔄")
        self.recheck_btn.setToolTip("Rerun all on-demand checks on this chapter")
        self.recheck_btn.setMinimumWidth(28)
        self.recheck_btn.setMaximumWidth(32)
        self.recheck_btn.setStyleSheet("font-size: 14px; padding: 2px;")
        self.recheck_btn.clicked.connect(self._recheck_writing)
        toolbar.addWidget(self.recheck_btn)

        toolbar.addSeparator()

        # AI Rephrase action - compact
        rephrase_action = QAction("✨", self)
        rephrase_action.setShortcut("Ctrl+R")
        rephrase_action.setToolTip("AI Rephrase selected text (Ctrl+R)")
        rephrase_action.triggered.connect(self._rephrase_selection)
        toolbar.addAction(rephrase_action)

        toolbar.addSeparator()

        # Annotation actions - compact
        annotation_action = QAction("📝", self)
        annotation_action.setShortcut("Ctrl+Shift+N")
        annotation_action.triggered.connect(lambda: self._add_annotation())
        annotation_action.setToolTip("Add annotation at current line (Ctrl+Shift+N)")
        toolbar.addAction(annotation_action)

        view_annotations_action = QAction("📋", self)
        view_annotations_action.triggered.connect(self._view_annotations_list)
        view_annotations_action.setToolTip("View all annotations")
        toolbar.addAction(view_annotations_action)

        toolbar.addSeparator()

        # Text-to-Speech actions - compact with emoji styling
        emoji_btn_style = "font-size: 14px; padding: 2px;"

        self.tts_speak_btn = QPushButton("🔊")
        self.tts_speak_btn.setToolTip("Read chapter aloud (or selection if text is selected)")
        self.tts_speak_btn.setMinimumWidth(28)
        self.tts_speak_btn.setMaximumWidth(32)
        self.tts_speak_btn.setStyleSheet(emoji_btn_style)
        self.tts_speak_btn.clicked.connect(self._tts_speak_chapter)
        toolbar.addWidget(self.tts_speak_btn)

        self.tts_stop_btn = QPushButton("⏹")
        self.tts_stop_btn.setToolTip("Stop reading")
        self.tts_stop_btn.setMinimumWidth(28)
        self.tts_stop_btn.setMaximumWidth(32)
        self.tts_stop_btn.setStyleSheet(emoji_btn_style)
        self.tts_stop_btn.clicked.connect(self._tts_stop)
        toolbar.addWidget(self.tts_stop_btn)

        self.tts_generate_btn = QPushButton("🎙")
        self.tts_generate_btn.setToolTip("Generate TTS document for this chapter")
        self.tts_generate_btn.setMinimumWidth(28)
        self.tts_generate_btn.setMaximumWidth(32)
        self.tts_generate_btn.setStyleSheet(emoji_btn_style)
        self.tts_generate_btn.clicked.connect(self._tts_generate_document)
        toolbar.addWidget(self.tts_generate_btn)

        editor_layout.addWidget(toolbar)

        # Chapter title
        title_layout = QHBoxLayout()
        title_label = QLabel("Chapter Title:")
        title_layout.addWidget(title_label)

        self.title_edit = QTextEdit()
        self.title_edit.setMaximumHeight(40)
        self.title_edit.setPlaceholderText("Enter chapter title...")
        self.title_edit.textChanged.connect(self.content_changed.emit)
        title_layout.addWidget(self.title_edit)

        editor_layout.addLayout(title_layout)

        # Main editor with annotation margin
        editor_container = QHBoxLayout()
        editor_container.setContentsMargins(0, 0, 0, 0)
        editor_container.setSpacing(0)

        # Main editor - use enhanced editor
        self.editor = EnhancedTextEditor()
        self.editor.setPlaceholderText("Start writing your chapter...")
        self.editor.textChanged.connect(self._on_text_changed)

        # Connect TTS progress signal for status updates
        self.editor.tts_progress.connect(self._on_tts_progress)
        self.editor.tts_started.connect(self._on_tts_started)
        self.editor.tts_stopped.connect(self._on_tts_stopped)
        self.editor.tts_error.connect(self._on_tts_error_display)

        # Set default font
        font = QFont("Times New Roman", 12)
        self.editor.setFont(font)

        # Override the EnhancedTextEditor's context menu with our own
        # Disconnect the default handler first
        try:
            self.editor.customContextMenuRequested.disconnect()
        except:
            pass

        # Connect our custom context menu
        self.editor.customContextMenuRequested.connect(self._show_context_menu)

        # Set up context lookup callbacks if project is available
        if self.project:
            self._setup_context_lookup()

        # Annotation margin area
        self.annotation_margin = AnnotationMarginArea(self.editor)
        self.annotation_margin.annotation_clicked.connect(self._on_margin_clicked)

        # Connect editor updates to margin repaints
        # QTextEdit uses verticalScrollBar signals instead of updateRequest
        self.editor.verticalScrollBar().valueChanged.connect(self._update_margin_area_scroll)
        self.editor.textChanged.connect(self.annotation_margin.update)

        editor_container.addWidget(self.annotation_margin)
        editor_container.addWidget(self.editor)

        editor_layout.addLayout(editor_container)

        # Bottom toolbar - compact buttons for small screens
        bottom_toolbar = QHBoxLayout()
        bottom_toolbar.setSpacing(4)

        # Word count
        self.word_count_label = QLabel("Words: 0")
        self.word_count_label.setStyleSheet("font-size: 11px;")
        bottom_toolbar.addWidget(self.word_count_label)

        bottom_toolbar.addStretch()

        # Compact button style
        compact_btn_style = "font-size: 11px; padding: 3px 6px;"

        # Import from Word button
        import_word_button = QPushButton("Import")
        import_word_button.setToolTip("Import from Word document")
        import_word_button.setStyleSheet(compact_btn_style)
        import_word_button.clicked.connect(self._import_from_word)
        bottom_toolbar.addWidget(import_word_button)

        # Export to Word button
        export_word_button = QPushButton("Export")
        export_word_button.setToolTip("Export to Word document")
        export_word_button.setStyleSheet(compact_btn_style)
        export_word_button.clicked.connect(self._export_to_word)
        bottom_toolbar.addWidget(export_word_button)

        # AI Hints button
        hints_button = QPushButton("Hints")
        hints_button.setToolTip("Get AI writing hints")
        hints_button.setStyleSheet(compact_btn_style)
        hints_button.clicked.connect(self._request_ai_hints)
        bottom_toolbar.addWidget(hints_button)

        # Check Promises button (AI)
        check_promises_button = QPushButton("Check")
        check_promises_button.setToolTip("Check chapter against story promises and character consistency")
        check_promises_button.setStyleSheet(compact_btn_style)
        check_promises_button.clicked.connect(self._check_promises)
        bottom_toolbar.addWidget(check_promises_button)

        # Prose Analysis button (AI)
        prose_analysis_button = QPushButton("Prose")
        prose_analysis_button.setToolTip("Analyze tone, style, and voice of this chapter using AI")
        prose_analysis_button.setStyleSheet(compact_btn_style)
        prose_analysis_button.clicked.connect(self._analyze_prose)
        bottom_toolbar.addWidget(prose_analysis_button)

        # Character Analysis button (AI)
        char_analysis_button = QPushButton("Chars")
        char_analysis_button.setToolTip("Check character consistency against character profiles")
        char_analysis_button.setStyleSheet(compact_btn_style)
        char_analysis_button.clicked.connect(self._analyze_characters)
        bottom_toolbar.addWidget(char_analysis_button)

        # World Analysis button (AI)
        world_analysis_button = QPushButton("World")
        world_analysis_button.setToolTip("Check worldbuilding consistency in this chapter")
        world_analysis_button.setStyleSheet(compact_btn_style)
        world_analysis_button.clicked.connect(self._analyze_world)
        bottom_toolbar.addWidget(world_analysis_button)

        # Plot Analysis button (AI)
        plot_analysis_button = QPushButton("Plot")
        plot_analysis_button.setToolTip("Check plot adherence and pacing against story plan")
        plot_analysis_button.setStyleSheet(compact_btn_style)
        plot_analysis_button.clicked.connect(self._analyze_plot)
        bottom_toolbar.addWidget(plot_analysis_button)

        # Save draft button
        save_revision_button = QPushButton("Save Draft")
        save_revision_button.setToolTip("Save current content as a new draft")
        save_revision_button.setStyleSheet(compact_btn_style)
        save_revision_button.clicked.connect(self._save_revision)
        bottom_toolbar.addWidget(save_revision_button)

        # View drafts button
        view_revisions_button = QPushButton("Drafts")
        view_revisions_button.setToolTip("View and manage drafts")
        view_revisions_button.setStyleSheet(compact_btn_style)
        view_revisions_button.clicked.connect(self._view_revisions)
        bottom_toolbar.addWidget(view_revisions_button)

        # Toggle planner button - make it stand out but compact
        self.toggle_planner_btn = QPushButton("📋 Plan")
        self.toggle_planner_btn.setCheckable(True)
        self.toggle_planner_btn.setToolTip("Show/hide chapter planner panel")
        self.toggle_planner_btn.setStyleSheet("""
            QPushButton {
                background-color: #8b5cf6;
                color: white;
                font-weight: bold;
                padding: 3px 8px;
                border-radius: 3px;
                font-size: 11px;
            }
            QPushButton:checked {
                background-color: #7c3aed;
            }
            QPushButton:hover {
                background-color: #7c3aed;
            }
        """)
        self.toggle_planner_btn.clicked.connect(self._toggle_planner)
        bottom_toolbar.addWidget(self.toggle_planner_btn)

        editor_layout.addLayout(bottom_toolbar)

        # Add editor widget to splitter
        self.main_splitter.addWidget(editor_widget)

        # Right side - Chapter Planner (initially hidden)
        self.planner_widget = ChapterPlannerWidget()
        self.planner_widget.plan_changed.connect(self._on_plan_changed)
        self.planner_widget.setVisible(False)
        self.planner_widget.setMinimumWidth(300)

        # Set up planner callbacks
        self.planner_widget.set_context_provider(self._get_planner_context)
        self.planner_widget.set_chapter_content_provider(lambda: self.editor.toPlainText())

        self.main_splitter.addWidget(self.planner_widget)

        # Set initial splitter sizes (100% editor when planner hidden)
        self.main_splitter.setSizes([1000, 0])

        layout.addWidget(self.main_splitter)

    def _toggle_planner(self):
        """Toggle the chapter planner visibility."""
        is_visible = self.planner_widget.isVisible()
        self.planner_widget.setVisible(not is_visible)

        if not is_visible:
            # Show planner - set sizes to 60/40
            self.main_splitter.setSizes([600, 400])
            self.toggle_planner_btn.setText("📋 Hide Planner")
            self.toggle_planner_btn.setChecked(True)
        else:
            # Hide planner
            self.main_splitter.setSizes([1000, 0])
            self.toggle_planner_btn.setText("📋 Plan Chapter")
            self.toggle_planner_btn.setChecked(False)

    def _on_plan_changed(self):
        """Handle plan content changes."""
        self.content_changed.emit()

    def _get_planner_context(self) -> dict:
        """Get context for the planner AI assistant.

        Uses AI-generated summaries if available for efficient context management.
        """
        context = {
            'chapter_title': self.chapter.title,
            'plot': '',
            'worldbuilding': '',
            'characters': ''
        }

        if not self.project:
            return context

        # Try to use AI-generated summaries if available and up-to-date
        use_ai_summary = (hasattr(self.project, 'ai_summary') and
                         self.project.ai_summary and
                         not self.project.ai_summary.is_empty())

        if use_ai_summary:
            summary = self.project.ai_summary
            print("✓ Using AI-generated summaries (efficient context)")

            # Use condensed summaries
            context['plot'] = summary.plot_summary or ""
            context['worldbuilding'] = summary.worldbuilding_summary or ""
            context['characters'] = summary.character_summary or ""

            # Add themes if available
            if summary.themes_summary:
                if context['plot']:
                    context['plot'] += f"\n\nThemes: {summary.themes_summary}"
                else:
                    context['plot'] = f"Themes: {summary.themes_summary}"

        else:
            # Fallback to manual extraction (less efficient, longer context)
            print("⚠ Using manual extraction (AI summary not available)")

            # Get plot outline from StoryPlanning model
            if hasattr(self.project, 'story_planning') and self.project.story_planning:
                plot_parts = []
                if self.project.story_planning.main_plot:
                    # Truncate for manual extraction
                    plot_text = self.project.story_planning.main_plot
                    if len(plot_text) > 500:
                        plot_text = plot_text[:500] + "..."
                    plot_parts.append(f"Plot: {plot_text}")
                if self.project.story_planning.themes:
                    plot_parts.append(f"Themes: {', '.join(self.project.story_planning.themes)}")
                if plot_parts:
                    context['plot'] = '\n'.join(plot_parts)

            # Get worldbuilding summary
            if hasattr(self.project, 'worldbuilding') and self.project.worldbuilding:
                wb_parts = []
                if self.project.worldbuilding.mythology:
                    wb_parts.append(f"Mythology: {self.project.worldbuilding.mythology[:150]}...")
                if self.project.worldbuilding.history:
                    wb_parts.append(f"History: {self.project.worldbuilding.history[:150]}...")
                if wb_parts:
                    context['worldbuilding'] = '\n'.join(wb_parts)

            # Get characters summary
            if hasattr(self.project, 'characters') and self.project.characters:
                char_parts = []
                for char in self.project.characters[:8]:  # Limit to 8 for manual extraction
                    name = getattr(char, 'name', 'Unknown')
                    role = getattr(char, 'role', '')
                    char_parts.append(f"- {name}: {role}")
                if char_parts:
                    context['characters'] = '\n'.join(char_parts)

        return context

    def _init_ai(self):
        """Initialize AI client for the planner."""
        # Always set up the AI handler for the planner (works with both cloud and local models)
        self.planner_widget.set_ai_handler(self._handle_planner_ai_request)

        # Initialize project summarizer with AI handler
        from src.ai.project_summarizer import get_project_summarizer
        self._summarizer = get_project_summarizer()
        self._summarizer.set_ai_handler(self._handle_summarization_request)

        # Check if summary needs update and generate if needed
        if self.project and self._summarizer.needs_update(self.project):
            print("Project summary is outdated or missing - will regenerate on next save")

        # Try to initialize cloud LLM if configured
        try:
            from src.config.ai_config import get_ai_config
            from src.ai.llm_client import LLMClient, LLMProvider

            config = get_ai_config()
            settings = config.get_settings()
            provider = settings.get("default_llm", "claude")

            api_key = config.get_api_key(provider)

            if api_key:
                provider_enum = {
                    "claude": LLMProvider.CLAUDE,
                    "chatgpt": LLMProvider.CHATGPT,
                    "openai": LLMProvider.CHATGPT,
                    "gemini": LLMProvider.GEMINI
                }.get(provider.lower(), LLMProvider.CLAUDE)

                self._llm_client = LLMClient(
                    provider=provider_enum,
                    api_key=api_key,
                    model=config.get_model(provider)
                )
                print(f"Initialized cloud LLM: {provider}")
            else:
                print("No cloud LLM API key configured - will use local models only")
                self._llm_client = None

        except Exception as e:
            print(f"Failed to initialize cloud LLM for planner: {e}")
            print("Will use local models instead")
            self._llm_client = None

    def _handle_planner_ai_request(self, prompt: str, model_name: str) -> str:
        """Handle AI requests from the planner widget.

        Args:
            prompt: The full prompt including context
            model_name: Selected model name from dropdown (e.g., "Local SLM", "Claude (Anthropic)")

        Returns:
            AI response text or empty string on error
        """
        # Check user preference for chapter planning (Settings > Model Settings > Chapter Planning)
        from src.config.ai_config import get_ai_config
        config = get_ai_config()
        settings = config.get_settings()
        use_local_for_planning = settings.get("use_local_for_chapter_planning", False)

        # Determine routing
        will_use_local = model_name == "Local SLM" or use_local_for_planning or not self._llm_client

        # Log routing decision
        print(f"\n{'#'*70}")
        print(f"# CHAPTER PLANNER REQUEST")
        print(f"{'#'*70}")
        print(f"📝 Request from: {'User dropdown' if model_name == 'Local SLM' else 'Settings preference' if use_local_for_planning else 'Auto (no cloud API)'}")
        print(f"🎯 Will use: {'LOCAL MODEL' if will_use_local else f'CLOUD LLM ({self._llm_client._provider.value if self._llm_client else 'Unknown'})'}")
        print(f"{'#'*70}\n")

        # Route to local model if requested via dropdown OR configured in settings
        if model_name == "Local SLM" or use_local_for_planning:
            return self._handle_local_model_request(prompt)

        # Use cloud LLM if configured
        if not self._llm_client:
            # No cloud LLM configured - try local model as fallback
            print("⚠️  No cloud LLM configured - falling back to local model")
            return self._handle_local_model_request(prompt)

        try:
            print(f"☁️  Using cloud LLM: {self._llm_client._provider.value}")
            response = self._llm_client.generate(prompt)
            print(f"✓ Cloud LLM response received ({len(response)} chars)\n")
            return response
        except Exception as e:
            print(f"✗ Cloud LLM error: {e}")
            print(f"⚠️  Falling back to local model")
            return self._handle_local_model_request(prompt)

    def _handle_local_model_request(self, prompt: str) -> str:
        """Handle AI requests using local model.

        Automatically selects between reasoning and storytelling models based on task type.

        Args:
            prompt: The full prompt including context

        Returns:
            AI response text or empty string on error
        """
        try:
            print("[DEBUG] _handle_local_model_request: Starting...")
            from src.config.ai_config import get_ai_config
            print("[DEBUG] _handle_local_model_request: get_ai_config imported")
            from src.ai.rephrasing_agent import RephrasingAgent
            print("[DEBUG] _handle_local_model_request: RephrasingAgent imported")

            # Use the correct config (ai_config, not genai_config)
            ai_config = get_ai_config()
            settings = ai_config.get_settings()
            print(f"[DEBUG] _handle_local_model_request: ai_config loaded")

            # Get storytelling and reasoning model IDs from settings
            storytelling_model_id = settings.get("storytelling_model_id")
            reasoning_model_id = settings.get("reasoning_model_id")
            local_model_id = settings.get("local_model_id")
            print(f"[DEBUG] storytelling_model_id: {storytelling_model_id}")
            print(f"[DEBUG] reasoning_model_id: {reasoning_model_id}")
            print(f"[DEBUG] local_model_id: {local_model_id}")

            # Detect if this is a reasoning task (analytical) or creative task
            prompt_lower = prompt.lower()

            # Strong reasoning indicators - analytical/critique tasks
            reasoning_keywords = [
                'analyze', 'critique', 'review the chapter', 'evaluate', 'assess',
                'consistency check', 'continuity check', 'logic', 'plot holes',
                'find problems', 'find issues', 'check for errors', 'review for',
                'identify weaknesses', 'identify strengths'
            ]

            # Creative indicators - writing/generation tasks
            creative_keywords = [
                'write', 'create', 'generate', 'draft', 'describe', 'narrate',
                'develop', 'expand', 'continue', 'finish', 'compose', 'craft',
                'help me write', 'plan a chapter', 'outline a scene', 'brainstorm ideas'
            ]

            # Check creative first (prioritize writing tasks for a writing tool)
            is_creative_task = any(keyword in prompt_lower for keyword in creative_keywords)
            is_reasoning_task = any(keyword in prompt_lower for keyword in reasoning_keywords) and not is_creative_task
            print(f"[DEBUG] _handle_local_model_request: Task detection complete (reasoning={is_reasoning_task})")

            # Choose model based on task type
            if is_reasoning_task:
                # Try reasoning model first, fall back to storytelling model
                model_id = reasoning_model_id or storytelling_model_id or local_model_id
                model_type = "reasoning" if reasoning_model_id else "storytelling"
            else:
                # Use storytelling model for creative tasks
                model_id = storytelling_model_id or local_model_id
                model_type = "storytelling"

            print(f"[DEBUG] _handle_local_model_request: Model ID selected: {model_id}")

            if not model_id:
                return ("No local model configured. Please select a model in Settings > Hugging Face / Local Models.\n\n"
                        "Storytelling Models (Creative Writing):\n"
                        "⭐ mistralai/Ministral-3-8B-Instruct-2512 (16GB) - Latest Mistral\n"
                        "📝 Qwen/Qwen2.5-7B-Instruct (14GB, 128K context) - Long chapters\n\n"
                        "Reasoning Models (Planning & Critique):\n"
                        "🧠 deepseek-ai/DeepSeek-R1-Distill-Qwen-7B (14GB) - Plot analysis\n"
                        "🧠 microsoft/Phi-4-reasoning-plus (28GB) - Story planning\n\n"
                        "General Models:\n"
                        "• google/gemma-3-4b-it (8GB VRAM)\n"
                        "• microsoft/Phi-3.5-mini-instruct (6GB VRAM)")

            # Initialize rephrasing agent with appropriate model
            agent = RephrasingAgent()
            agent.local_model_id = model_id

            # Prominent logging for chapter planner
            task_icon = "🧠" if is_reasoning_task else "✍️"
            print(f"\n{'='*70}")
            print(f"{'='*70}")
            print(f"{task_icon} CHAPTER PLANNER AI ASSISTANT")
            print(f"{'='*70}")
            print(f"📦 Model: {model_id}")
            print(f"📋 Task Type: {'Reasoning/Analysis' if is_reasoning_task else 'Creative/Storytelling'}")
            print(f"🎯 Model Category: {model_type.upper()}")

            # Check if model is cached
            from src.ai.rephrasing_agent import _model_cache
            cached_model, _, cached_device = _model_cache.get_model(model_id)
            if cached_model:
                print(f"💾 Cache Status: ✓ CACHED (instant load)")
                print(f"🖥️  Device: {cached_device.upper()}")
            else:
                print(f"💾 Cache Status: Not cached (will load - may take 30-120s)")
                # Try to detect what device will be used
                try:
                    from src.ai.device_utils import detect_device
                    device_name, _, _ = detect_device()
                    print(f"🖥️  Will use device: {device_name.upper()}")
                except:
                    print(f"🖥️  Device: Detecting...")

            print(f"{'='*70}\n")

            # Use the agent's local model to generate a response
            # Reasoning tasks may need more tokens for chain-of-thought
            max_tokens = 2048 if is_reasoning_task else 1024

            try:
                response = agent._generate_local(prompt, max_tokens=max_tokens)

                # Final success message with response preview
                print(f"\n{'='*70}")
                print(f"✅ CHAPTER PLANNER RESPONSE COMPLETE")
                print(f"{'='*70}")
                print(f"📦 Model: {model_id}")
                print(f"📝 Response: {len(response)} characters")
                print(f"📄 Response content preview:")
                print(f"   First 200 chars: {repr(response[:200])}")
                if len(response) > 200:
                    print(f"   Last 100 chars: {repr(response[-100:])}")
                print(f"   Is empty/whitespace: {not response.strip()}")
                print(f"{'='*70}\n")

                return response
            except Exception as model_err:
                error_msg = str(model_err)
                if "out of memory" in error_msg.lower():
                    return (f"Model '{model_id}' is too large for your GPU.\n\n"
                            f"Try a smaller model:\n"
                            f"For Storytelling:\n"
                            f"• google/gemma-3-4b-it (~8GB)\n"
                            f"• microsoft/Phi-3.5-mini-instruct (~6GB)\n\n"
                            f"For Reasoning:\n"
                            f"• deepseek-ai/DeepSeek-R1-Distill-Qwen-7B (~14GB)\n"
                            f"• mistralai/Ministral-3-8B-Reasoning-2512 (~16GB)")
                raise

        except Exception as e:
            print(f"Local model error: {e}")
            import traceback
            traceback.print_exc()
            return f"Local model error: {str(e)}\n\nPlease check your model configuration in Settings."

    def _handle_summarization_request(self, prompt: str) -> str:
        """Handle AI requests from the project summarizer.

        Uses local models for summarization (no cloud LLM needed for this background task).

        Args:
            prompt: Summarization prompt

        Returns:
            AI response text
        """
        # Always use local model for summarization (efficient background task)
        try:
            from src.config.genai_config import GenAIConfig
            from src.ai.rephrasing_agent import RephrasingAgent

            config = GenAIConfig()

            if not config.get("enable_local_models", False):
                return ""  # Silently skip if local models not enabled

            # Use storytelling model for summarization (good at narrative understanding)
            model_id = config.get("storytelling_model_id") or config.get("local_model_id")

            if not model_id:
                return ""  # Silently skip if no model configured

            agent = RephrasingAgent()
            agent.local_model_id = model_id

            # Log summarization model usage
            print(f"\n📊 Project Summarization - Using model:")
            print(f"   Model: {model_id}")
            print(f"   Purpose: AI-generated project summary")

            # Summarization needs moderate token output
            response = agent._generate_local(prompt, max_tokens=512)
            print(f"   ✓ Summary generated ({len(response)} chars)\n")
            return response

        except Exception as e:
            print(f"Summarization error: {e}")
            return ""  # Return empty on error to avoid blocking

    def update_project_summary(self):
        """Update project AI summary if needed.

        Should be called when:
        - Project is saved
        - Major changes to plot/characters/worldbuilding
        - User manually requests update
        """
        if not hasattr(self, '_summarizer'):
            return

        if self.project:
            updated = self._summarizer.update_project_summary(self.project)
            if updated:
                print("✓ Project summary updated successfully")
                # Save the updated summary
                if hasattr(self, '_project_manager') and self._project_manager:
                    self._project_manager.save_project()

    def _load_chapter(self):
        """Load chapter data into editor.

        Content is stored as Markdown - the highlighter renders it visually.
        """
        self.title_edit.setPlainText(self.chapter.title)
        # Load plain text content (now with Markdown formatting)
        self.editor.setPlainText(self.chapter.content)
        # Load chapter planning data (separate from content)
        planning_data = {
            'outline': self.chapter.planning.outline or self.chapter.plan,  # Fall back to legacy plan
            'events': [
                {
                    'id': event.id,
                    'text': event.text,
                    'description': event.description,
                    'completed': event.completed,
                    'stage': event.stage,
                    'arc_position': event.arc_position,
                    'order': event.order
                }
                for event in self.chapter.planning.events
            ],
            'description': self.chapter.planning.description,
            'todos': [
                {
                    'id': todo.id,
                    'text': todo.text,
                    'completed': todo.completed,
                    'priority': todo.priority
                }
                for todo in self.chapter.planning.todos
            ],
            'notes': self.chapter.planning.notes,
            'characters_featured': self.chapter.planning.characters_featured,
            'locations': self.chapter.planning.locations,
            'pov_character': self.chapter.planning.pov_character,
            'timeline_position': self.chapter.planning.timeline_position,
        }
        self.planner_widget.set_planning_data(planning_data)
        self._update_word_count()
        self._update_margin_annotations()
        self._highlight_annotated_lines()
        # Perform initial writing check (for on-demand mode)
        self.editor.do_initial_check()

    def _on_text_changed(self):
        """Handle text changes."""
        self._update_word_count()
        self.content_changed.emit()

    def _update_word_count(self):
        """Update word count display."""
        text = self.editor.toPlainText()
        words = len([w for w in text.split() if w])
        self.chapter.word_count = words
        self.word_count_label.setText(f"Words: {words}")
        self.word_count_changed.emit(words)

    def _change_font_family(self, family: str):
        """Change font family."""
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            fmt = cursor.charFormat()
            fmt.setFontFamily(family)
            cursor.setCharFormat(fmt)
        else:
            font = self.editor.font()
            font.setFamily(family)
            self.editor.setFont(font)

    def _change_font_size(self, size: int):
        """Change font size."""
        # Ensure size is valid (positive) - Qt sometimes passes -1 during initialization
        if size <= 0:
            return  # Skip invalid sizes instead of setting default

        try:
            cursor = self.editor.textCursor()
            if cursor.hasSelection():
                fmt = cursor.charFormat()
                # Only set if size is valid
                if size > 0:
                    fmt.setFontPointSize(size)
                    cursor.setCharFormat(fmt)
            else:
                font = self.editor.font()
                # Double-check size before setting
                if size > 0 and size <= 72:
                    font.setPointSize(size)
                    self.editor.setFont(font)
        except Exception as e:
            # Silently catch any font-related errors during initialization
            pass

    def _toggle_bold(self):
        """Toggle bold formatting using Markdown ** markers."""
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            new_text = toggle_inline_style(selected_text, MarkdownStyle.BOLD)
            cursor.insertText(new_text)
        else:
            # No selection - insert ** markers and position cursor between them
            cursor.insertText("****")
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 2)
            self.editor.setTextCursor(cursor)

    def _toggle_italic(self):
        """Toggle italic formatting using Markdown * markers."""
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            new_text = toggle_inline_style(selected_text, MarkdownStyle.ITALIC)
            cursor.insertText(new_text)
        else:
            # No selection - insert * markers and position cursor between them
            cursor.insertText("**")
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 1)
            self.editor.setTextCursor(cursor)

    def _toggle_underline(self):
        """Toggle underline formatting."""
        cursor = self.editor.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontUnderline(not fmt.fontUnderline())
        cursor.mergeCharFormat(fmt)

    def _on_heading_combo_activated(self, index: int):
        """Handle heading combo box selection (activated fires even for same selection)."""
        style = self.heading_combo.itemText(index)
        self.editor.apply_heading(style)

    def _apply_heading_style(self, style: str):
        """Apply heading style to current paragraph."""
        self.editor.apply_heading(style)

    def _update_check_button_style(self, button: QPushButton, mode: CheckMode):
        """Update button style based on check mode."""
        button.setStyleSheet(self._check_button_styles[mode])

    def _cycle_check_mode(self, current_mode: CheckMode) -> CheckMode:
        """Cycle to the next check mode: ON_DEMAND -> REALTIME -> OFF -> ON_DEMAND."""
        if current_mode == CheckMode.ON_DEMAND:
            return CheckMode.REALTIME
        elif current_mode == CheckMode.REALTIME:
            return CheckMode.OFF
        else:
            return CheckMode.ON_DEMAND

    def _toggle_spell_check(self):
        """Cycle spell checking mode."""
        current_mode = self.editor.get_spell_mode()
        new_mode = self._cycle_check_mode(current_mode)
        self.editor.set_spell_mode(new_mode)
        self._update_check_button_style(self.spell_check_btn, new_mode)

    def _toggle_grammar_check(self):
        """Cycle grammar checking mode."""
        current_mode = self.editor.get_grammar_mode()
        new_mode = self._cycle_check_mode(current_mode)
        self.editor.set_grammar_mode(new_mode)
        self._update_check_button_style(self.grammar_check_btn, new_mode)

    def _toggle_overuse_check(self):
        """Cycle overused word detection mode."""
        current_mode = self.editor.get_overuse_mode()
        new_mode = self._cycle_check_mode(current_mode)
        self.editor.set_overuse_mode(new_mode)
        self._update_check_button_style(self.overuse_check_btn, new_mode)

    def _recheck_writing(self):
        """Rerun all on-demand checks on the chapter."""
        # Update full text for overuse analysis
        current_text = self.editor.toPlainText()
        self.editor.overuse_detector.update_cache(current_text)
        self.editor.writing_highlighter.update_full_text(current_text)
        # Clear ignored errors to recheck everything
        self.editor.writing_highlighter.clear_ignored()
        # Also clear the overuse detector's ignored words
        self.editor.overuse_detector._ignored_words.clear()
        # Trigger full recheck (includes heavy grammar checking if available)
        self.editor.writing_highlighter.do_full_recheck()

    def _replace_selection_with(self, replacement: str):
        """Replace the current selection with the given text, preserving case.

        Args:
            replacement: The text to replace the selection with
        """
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            return

        original = cursor.selectedText()

        # Preserve the case of the original word
        if original.isupper():
            # ALL CAPS
            replacement = replacement.upper()
        elif original and original[0].isupper():
            # Title Case (capitalize first letter)
            replacement = replacement.capitalize()
        # else: keep lowercase

        cursor.insertText(replacement)

    def _rephrase_selection(self):
        """Open rephrase dialog for selected text."""
        cursor = self.editor.textCursor()
        selected_text = cursor.selectedText()

        if not selected_text or len(selected_text.strip()) < 3:
            QMessageBox.information(
                self,
                "No Selection",
                "Please select some text to rephrase."
            )
            return

        # Open rephrase dialog
        from src.ui.rephrase_dialog import RephraseDialog
        dialog = RephraseDialog(selected_text, self.project, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            replacement = dialog.get_selected_text()
            if replacement:
                cursor.insertText(replacement)

    def _show_context_menu(self, position):
        """Show custom context menu with annotation option."""
        # Get cursor at click position
        cursor = self.editor.cursorForPosition(position)
        line_number = cursor.blockNumber() + 1

        # Create context menu
        menu = QMenu(self.editor)

        # Add annotation action
        add_annotation_action = menu.addAction("📝 Add Annotation")
        add_annotation_action.triggered.connect(lambda: self._add_annotation(line_number))

        # Check if there are annotations on this line
        line_annotations = [a for a in self.chapter.annotations if a.line_number == line_number]

        if line_annotations:
            view_annotations_action = menu.addAction(f"📋 View Annotations ({len(line_annotations)})")
            view_annotations_action.triggered.connect(lambda: self._on_margin_clicked(line_number))

        menu.addSeparator()

        # Standard edit actions
        undo_action = menu.addAction("Undo")
        undo_action.triggered.connect(self.editor.undo)
        undo_action.setEnabled(self.editor.document().isUndoAvailable())

        redo_action = menu.addAction("Redo")
        redo_action.triggered.connect(self.editor.redo)
        redo_action.setEnabled(self.editor.document().isRedoAvailable())

        menu.addSeparator()

        # Copy/Paste actions
        if cursor.hasSelection():
            cut_action = menu.addAction("Cut")
            cut_action.triggered.connect(self.editor.cut)

            copy_action = menu.addAction("Copy")
            copy_action.triggered.connect(self.editor.copy)

        paste_action = menu.addAction("Paste")
        paste_action.triggered.connect(self.editor.paste)

        menu.addSeparator()

        # Context lookup menu
        lookup_menu = menu.addMenu("Look Up Context")

        # Get selected text
        selected_text = cursor.selectedText()

        if selected_text:
            # Lookup selected text
            lookup_selected = lookup_menu.addAction(f'Look Up "{selected_text[:30]}..."')
            lookup_selected.triggered.connect(lambda: self._lookup_selected_text(selected_text))

            # Find similar content (semantic search)
            find_similar = lookup_menu.addAction(f'Find Similar Content')
            find_similar.triggered.connect(lambda: self._find_similar_content(selected_text))

            lookup_menu.addSeparator()

        # Character lookup
        character_action = lookup_menu.addAction("Character Reference")
        character_action.triggered.connect(self._lookup_character)

        # Worldbuilding lookup
        worldbuilding_action = lookup_menu.addAction("Worldbuilding Reference")
        worldbuilding_action.triggered.connect(self._lookup_worldbuilding)

        # Plot lookup
        plot_action = lookup_menu.addAction("Plot Reference")
        plot_action.triggered.connect(self._lookup_plot)

        # Technology lookup
        tech_action = lookup_menu.addAction("Technology Reference")
        tech_action.triggered.connect(self._lookup_technology)

        # Advanced search
        lookup_menu.addSeparator()
        advanced_search = lookup_menu.addAction("Advanced Search...")
        advanced_search.triggered.connect(self._show_advanced_search)

        # AI Rephrase option (only if text selected)
        text_cursor = self.editor.textCursor()
        if text_cursor.hasSelection():
            menu.addSeparator()

            # Get the selected text for thesaurus lookup
            selected_text = text_cursor.selectedText().strip()

            # Thesaurus/Synonyms submenu - only for single words (no spaces)
            # Strip punctuation for display but keep original for replacement
            import re
            clean_word = re.sub(r'^[^\w]+|[^\w]+$', '', selected_text)

            if clean_word and ' ' not in clean_word and len(clean_word) <= 30:
                synonyms = get_synonyms(clean_word, max_results=12)
                antonyms = get_antonyms(clean_word, max_results=5)

                # Always show the thesaurus menu for single words
                display_word = clean_word[:15] + "..." if len(clean_word) > 15 else clean_word
                thesaurus_menu = menu.addMenu(f"📖 Synonyms for \"{display_word}\"")

                if synonyms:
                    for synonym in synonyms:
                        action = thesaurus_menu.addAction(synonym)
                        # Capture synonym in lambda
                        action.triggered.connect(
                            lambda checked, s=synonym: self._replace_selection_with(s)
                        )

                    if antonyms:
                        thesaurus_menu.addSeparator()
                        antonyms_submenu = thesaurus_menu.addMenu("Antonyms")
                        for antonym in antonyms:
                            action = antonyms_submenu.addAction(antonym)
                            action.triggered.connect(
                                lambda checked, a=antonym: self._replace_selection_with(a)
                            )
                else:
                    # Show "no synonyms found" when word not in thesaurus
                    no_syn_action = thesaurus_menu.addAction("(no synonyms found)")
                    no_syn_action.setEnabled(False)

            rephrase_action = menu.addAction("✨ Rephrase with AI...")
            rephrase_action.triggered.connect(self._rephrase_selection)

            # Heading style submenu
            heading_menu = menu.addMenu("Heading Style")
            for level in ["Normal", "Heading 1", "Heading 2", "Heading 3"]:
                action = heading_menu.addAction(level)
                action.triggered.connect(lambda checked, l=level: self.editor.apply_heading(l))

            # TTS options for selected text
            menu.addSeparator()
            tts_menu = menu.addMenu("🔊 Text to Speech")

            # Capture the selected text now (not lazily in lambda)
            selected_text = text_cursor.selectedText()

            speak_selection_action = tts_menu.addAction("Read Selection Aloud")
            speak_selection_action.triggered.connect(lambda checked, txt=selected_text: self._tts_speak_selection(txt))

            generate_tts_selection = tts_menu.addAction("Generate TTS Doc from Selection...")
            generate_tts_selection.triggered.connect(lambda checked, txt=selected_text: self._tts_generate_from_selection(txt))

        # TTS options always available (for full chapter)
        if not text_cursor.hasSelection():
            menu.addSeparator()
            tts_menu = menu.addMenu("🔊 Text to Speech")

        speak_chapter_action = tts_menu.addAction("Read Entire Chapter")
        speak_chapter_action.triggered.connect(self._tts_speak_chapter)

        generate_tts_chapter = tts_menu.addAction("Generate TTS Doc for Chapter...")
        generate_tts_chapter.triggered.connect(self._tts_generate_document)

        stop_tts_action = tts_menu.addAction("Stop Playback")
        stop_tts_action.triggered.connect(self._tts_stop)

        # Show menu at cursor position
        menu.exec(self.editor.mapToGlobal(position))

    def _request_ai_hints(self):
        """Request AI hints for improving the chapter."""
        # TODO: Integrate with AI client
        QMessageBox.information(
            self,
            "AI Hints",
            "AI chapter hints will be integrated soon."
        )

    def _check_promises(self):
        """Check chapter against story promises and character consistency."""
        if not self.project:
            QMessageBox.warning(
                self,
                "No Project",
                "Please save the project first to enable promise checking."
            )
            return

        # Get promises and characters from project
        promises = []
        if hasattr(self.project, 'story_planning') and self.project.story_planning:
            for p in self.project.story_planning.promises:
                promises.append({
                    'promise_type': p.promise_type,
                    'title': p.title,
                    'description': p.description,
                    'related_characters': p.related_characters
                })

        characters = []
        if hasattr(self.project, 'characters'):
            for c in self.project.characters:
                characters.append({
                    'name': c.name,
                    'character_type': c.character_type,
                    'personality': c.personality,
                    'backstory': c.backstory
                })

        if not promises and not characters:
            QMessageBox.information(
                self,
                "No Promises Defined",
                "No story promises or characters defined.\n\n"
                "Add promises in Story Planning > Promises tab,\n"
                "and add characters in the Characters section."
            )
            return

        # Get chapter content
        chapter_content = self.editor.toPlainText()
        if not chapter_content.strip():
            QMessageBox.warning(self, "Empty Chapter", "Please write some content first.")
            return

        # Get plot outline if available
        plot_outline = ""
        if hasattr(self.project, 'story_planning') and self.project.story_planning:
            plot_outline = self.project.story_planning.main_plot

        # Show the promise check dialog
        dialog = PromiseCheckDialog(
            chapter_title=self.chapter.title,
            chapter_content=chapter_content,
            promises=promises,
            characters=characters,
            plot_outline=plot_outline,
            parent=self
        )
        dialog.exec()

    def _analyze_prose(self):
        """Analyze the tone, style, and voice of the current chapter using AI."""
        text = self.editor.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "Empty Chapter", "Please write some content first.")
            return

        # Use a representative sample if the chapter is very long
        word_count = len(text.split())
        if word_count > 3000:
            # Take first ~1500 words and last ~500 words for analysis
            words = text.split()
            sample = ' '.join(words[:1500]) + "\n\n[...]\n\n" + ' '.join(words[-500:])
            sample_note = f"(Analyzed sample: first 1500 + last 500 of {word_count} words)"
        else:
            sample = text
            sample_note = f"({word_count} words)"

        # Build prose profile context if the project has targets set
        profile_context = ""
        profile_comparison_section = ""
        project = self.project if hasattr(self, 'project') and self.project else None
        if project and hasattr(project, 'prose_profile'):
            pp = project.prose_profile
            targets = []
            if pp.tone:
                targets.append(f"- **Target Tone:** {pp.tone}")
            if pp.style:
                targets.append(f"- **Target Style:** {pp.style}")
            if pp.voice:
                targets.append(f"- **Target Voice:** {pp.voice}")
            if pp.genre:
                targets.append(f"- **Target Genre:** {pp.genre}")
            if pp.notes:
                targets.append(f"- **Additional Notes:** {pp.notes}")
            if targets:
                profile_context = "\n\nPROJECT PROSE TARGETS (the author's intended direction):\n" + "\n".join(targets) + "\n"
                profile_comparison_section = """

## Alignment with Project Targets
Compare this chapter's actual prose against the author's stated targets above. For each target dimension (tone, style, voice, genre), rate the alignment as Strong Match, Partial Match, or Divergent. Explain specifically where the prose aligns and where it drifts. If there are gaps, suggest concrete adjustments the author could make to close them. Be honest — if the prose already nails a target, say so; if it misses, explain exactly how."""

        prompt = f"""Analyze the following prose excerpt and provide a detailed assessment of THIS chapter's prose only. For every claim you make, explain your reasoning and cite short phrases from the text as evidence. Do not simply label — justify each observation. Focus exclusively on what is written in this chapter — do not reference characters, events, or content from other chapters or the broader project.
{profile_context}
PROSE {sample_note}:
---
{sample}
---

Provide your analysis in these sections:

## Tone
Describe the emotional tone of the writing (e.g. dark, lighthearted, melancholic, tense, whimsical, foreboding, intimate, detached). Cite 2-3 short phrases that establish this tone and explain why each phrase produces that effect.

## Style
Describe the prose style. Consider sentence structure (short/punchy vs. flowing/complex), use of imagery, figurative language, level of detail, pacing, and paragraph rhythm. Is it minimalist, ornate, literary, conversational, cinematic? Explain what specific choices lead you to this conclusion.

## Voice
Describe the narrative voice. What personality comes through? Is it authoritative, confessional, sardonic, empathetic, clinical, poetic? How does the narrator relate to the reader? Point to specific passages that reveal the voice.

## Genre
Identify the genre and subgenre this prose belongs to. Consider the full range: literary fiction, dark fantasy, psychological thriller, magical realism, space opera, contemporary romance, horror, western, noir, dystopian, historical fiction, mystery, adventure, satire, southern gothic, cyberpunk, urban fantasy, military fiction, etc. Explain what genre signals are present — subject matter, tropes, conventions, setting cues, character archetypes, and reader expectations being set up. If the prose blends or subverts genre conventions, describe how and why that works or creates tension.
{profile_comparison_section}
## Comparable Authors
Name 2-3 published authors whose style this prose most resembles. For each, explain specifically which aspects align (e.g. sentence rhythm, imagery density, emotional register, thematic concerns, subject matter treatment) and which aspects diverge.

## Strengths
List 2-3 specific things this prose does well. For each, quote a brief example from the text and explain why it works.

## Areas to Watch
List 2-3 aspects the writer should be mindful of (not necessarily weaknesses, but tendencies that could become issues at scale). For each, explain the risk and suggest what to watch for. Be constructive."""

        # Show a progress indicator
        self._prose_analysis_dialog = ProseAnalysisDialog(
            chapter_title=self.chapter.title, parent=self)
        self._prose_analysis_dialog.show()
        self._prose_analysis_dialog.set_loading()

        # Run AI request in background thread
        import threading

        def run_analysis():
            try:
                # Route through the same AI handler as chapter planner
                # Walk up to find ManuscriptEditor for the AI handler
                handler = self._get_ai_handler()
                if handler:
                    result = handler(prompt, "Auto")
                else:
                    result = self._fallback_local_analysis(prompt)

                self._prose_analysis_ready.emit(result)

            except Exception as e:
                self._prose_analysis_ready.emit(f"Analysis failed: {str(e)}")

        thread = threading.Thread(target=run_analysis, daemon=True)
        thread.start()

    def _get_ai_handler(self):
        """Find the AI handler by walking up to the ManuscriptEditor."""
        parent = self.parent()
        while parent:
            if hasattr(parent, '_handle_planner_ai_request'):
                return parent._handle_planner_ai_request
            parent = parent.parent() if hasattr(parent, 'parent') else None
        return None

    def _fallback_local_analysis(self, prompt: str) -> str:
        """Fallback to local model if no handler found."""
        try:
            from src.ai.rephrasing_agent import RephrasingAgent
            from src.config.ai_config import get_ai_config
            config = get_ai_config()
            settings = config.get_settings()
            model_id = settings.get("reasoning_model_id") or settings.get("storytelling_model_id") or settings.get("local_model_id")
            if not model_id:
                return "No AI model configured. Please set up a model in Settings > Hugging Face / Local Models."
            agent = RephrasingAgent()
            agent.local_model_id = model_id
            return agent._generate_local(prompt, max_tokens=2048)
        except Exception as e:
            return f"Local model error: {str(e)}"

    def _on_prose_analysis_complete(self, result: str):
        """Handle prose analysis result on the main thread."""
        if hasattr(self, '_prose_analysis_dialog') and self._prose_analysis_dialog:
            self._prose_analysis_dialog.set_result(result)

    # ------------------------------------------------------------------
    # Character Analysis
    # ------------------------------------------------------------------

    def _get_chapter_sample(self):
        """Get chapter text, sampling if very long. Returns (sample, note) or None."""
        text = self.editor.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "Empty Chapter", "Please write some content first.")
            return None
        word_count = len(text.split())
        if word_count > 3000:
            words = text.split()
            sample = ' '.join(words[:1500]) + "\n\n[...]\n\n" + ' '.join(words[-500:])
            note = f"(Analyzed sample: first 1500 + last 500 of {word_count} words)"
        else:
            sample = text
            note = f"({word_count} words)"
        return sample, note

    def _build_character_context(self):
        """Build character reference data from the project."""
        project = self.project if hasattr(self, 'project') and self.project else None
        if not project or not project.characters:
            return ""

        parts = []
        for ch in project.characters:
            desc = [f"**{ch.name}** ({ch.character_type})"]
            if ch.personality:
                desc.append(f"  Personality: {ch.personality[:200]}")
            if ch.backstory:
                desc.append(f"  Backstory: {ch.backstory[:200]}")
            if ch.physical_description:
                desc.append(f"  Appearance: {ch.physical_description[:150]}")
            if ch.social_network:
                rels = ", ".join(f"{k}: {v}" for k, v in list(ch.social_network.items())[:5])
                desc.append(f"  Relationships: {rels}")
            if ch.notes:
                desc.append(f"  Notes: {ch.notes[:150]}")
            parts.append("\n".join(desc))

        return "\n\n".join(parts)

    def _analyze_characters(self):
        """Analyze character consistency against character profiles."""
        result = self._get_chapter_sample()
        if result is None:
            return
        sample, sample_note = result

        char_context = self._build_character_context()
        if not char_context:
            QMessageBox.warning(
                self, "No Characters",
                "No characters defined in the project. Add characters first.")
            return

        # Include chapter planning characters if set
        planning_chars = ""
        if self.chapter.planning and self.chapter.planning.characters_featured:
            planning_chars = f"\n\nCHARACTERS EXPECTED IN THIS CHAPTER:\n- " + "\n- ".join(
                self.chapter.planning.characters_featured)

        # Prose profile for voice context
        prose_context = ""
        project = self.project if hasattr(self, 'project') and self.project else None
        if project and hasattr(project, 'prose_profile') and project.prose_profile.voice:
            prose_context = f"\n\nPROJECT VOICE: {project.prose_profile.voice}"

        prompt = f"""Analyze the following chapter for CHARACTER CONSISTENCY against the established character profiles below.

CRITICAL SCOPE RULE: ONLY analyze characters who actually appear, speak, or are mentioned BY NAME in the chapter text below. The character profiles are reference material — do NOT discuss characters who are absent from this chapter. Every observation MUST cite specific text from the chapter as evidence.

CHARACTER PROFILES (reference only — use these to check consistency for characters who appear):
{char_context}
{planning_chars}{prose_context}

CHAPTER TEXT {sample_note}:
---
{sample}
---

Provide your analysis in these sections:

## Characters Present
List ONLY the characters who appear, speak, or are mentioned by name in this chapter. For each, note whether they have a defined profile above or are new/unnamed. Do NOT list characters from the profiles who are absent.

## Personality Consistency
For each character PRESENT IN THIS CHAPTER who has a profile, check whether their behavior, speech patterns, and actions are consistent with their defined personality. Cite dialogue or actions that align or conflict. Flag anything out of character.

## Relationship Consistency
Check whether character interactions IN THIS CHAPTER match the defined relationships (allies, enemies, family, etc.). Only assess relationships between characters who actually interact here.

## Backstory & Knowledge Consistency
Flag any moments in this chapter where a character demonstrates knowledge, skills, or references history that contradicts their backstory or established abilities.

## Physical Description Consistency
Note any physical descriptions IN THIS CHAPTER and check they match the character profiles. Flag contradictions (e.g., eye color, build, distinguishing features). Skip this section if no physical descriptions appear.

## Voice Distinctiveness
Assess whether characters who speak in this chapter have distinct voices in dialogue. Do they sound different from each other? Are speech patterns consistent with their personality and background?

## Advice
Provide 2-3 specific, actionable suggestions for improving character consistency or deepening characterization in THIS chapter. Focus only on what's written here."""

        self._character_analysis_dialog = ProseAnalysisDialog(
            chapter_title=f"Character Analysis - {self.chapter.title}", parent=self)
        self._character_analysis_dialog.show()
        self._character_analysis_dialog.set_loading()

        import threading

        def run_analysis():
            try:
                handler = self._get_ai_handler()
                if handler:
                    result = handler(prompt, "Auto")
                else:
                    result = self._fallback_local_analysis(prompt)
                self._character_analysis_ready.emit(result)
            except Exception as e:
                self._character_analysis_ready.emit(f"Analysis failed: {str(e)}")

        thread = threading.Thread(target=run_analysis, daemon=True)
        thread.start()

    def _on_character_analysis_complete(self, result: str):
        """Handle character analysis result."""
        if hasattr(self, '_character_analysis_dialog') and self._character_analysis_dialog:
            self._character_analysis_dialog.set_result(result)

    # ------------------------------------------------------------------
    # World Analysis
    # ------------------------------------------------------------------

    def _build_world_context(self):
        """Build worldbuilding reference data from the project."""
        project = self.project if hasattr(self, 'project') and self.project else None
        if not project:
            return ""

        wb = project.worldbuilding
        parts = []

        # Places
        if wb.places:
            place_descs = []
            for p in wb.places[:10]:
                desc = f"- **{p.name}** ({p.place_type.value if hasattr(p.place_type, 'value') else p.place_type}): {p.description[:150]}"
                if p.climate:
                    desc += f" | Climate: {p.climate}"
                if p.atmosphere:
                    desc += f" | Atmosphere: {p.atmosphere[:80]}"
                place_descs.append(desc)
            parts.append("PLACES:\n" + "\n".join(place_descs))

        # Factions
        if wb.factions:
            faction_descs = []
            for f in wb.factions[:8]:
                desc = f"- **{f.name}** ({f.faction_type.value if hasattr(f.faction_type, 'value') else f.faction_type}): {f.description[:150]}"
                if f.leader:
                    desc += f" | Leader: {f.leader}"
                faction_descs.append(desc)
            parts.append("FACTIONS:\n" + "\n".join(faction_descs))

        # Technologies
        if wb.technologies:
            tech_descs = [f"- **{t.name}**: {t.description[:100]}" for t in wb.technologies[:8]]
            parts.append("TECHNOLOGIES:\n" + "\n".join(tech_descs))

        # Cultures
        if wb.cultures:
            culture_descs = [f"- **{c.name}**: {c.description[:150]}" for c in wb.cultures[:6]]
            parts.append("CULTURES:\n" + "\n".join(culture_descs))

        # Historical Events
        if wb.historical_events:
            event_descs = [f"- **{e.name}** ({e.date}): {e.description[:100]}" for e in wb.historical_events[:8]]
            parts.append("HISTORICAL EVENTS:\n" + "\n".join(event_descs))

        # Planets
        if wb.star_systems or getattr(wb, 'planets_elements', None):
            planet_parts = []
            for ss in wb.star_systems[:4]:
                planet_parts.append(f"- **{ss.name}** ({ss.system_type}): {ss.description[:100]}")
                for planet in ss.planets[:3]:
                    planet_parts.append(f"  - **{planet.name}** ({planet.planet_type.value if hasattr(planet.planet_type, 'value') else planet.planet_type}): {planet.description[:80]}")
            if planet_parts:
                parts.append("STAR SYSTEMS & PLANETS:\n" + "\n".join(planet_parts))

        # Flora & Fauna
        if wb.flora:
            flora_descs = [f"- **{fl.name}**: {fl.description[:80]}" for fl in wb.flora[:6]]
            parts.append("FLORA:\n" + "\n".join(flora_descs))
        if wb.fauna:
            fauna_descs = [f"- **{fa.name}**: {fa.description[:80]}" for fa in wb.fauna[:6]]
            parts.append("FAUNA:\n" + "\n".join(fauna_descs))

        # Myths
        if wb.myths:
            myth_descs = [f"- **{m.name}** ({m.myth_type}): {m.description[:100]}" for m in wb.myths[:6]]
            parts.append("MYTHS & LEGENDS:\n" + "\n".join(myth_descs))

        # Legacy text fields as fallback
        for field_name in ['mythology', 'climate', 'history', 'politics', 'military', 'economy']:
            val = getattr(wb, field_name, '')
            if val and val.strip():
                parts.append(f"{field_name.upper()}:\n{val[:300]}")

        return "\n\n".join(parts)

    def _analyze_world(self):
        """Analyze worldbuilding consistency in this chapter."""
        result = self._get_chapter_sample()
        if result is None:
            return
        sample, sample_note = result

        world_context = self._build_world_context()
        if not world_context:
            QMessageBox.warning(
                self, "No Worldbuilding",
                "No worldbuilding data defined in the project. Add places, factions, or other elements first.")
            return

        # Include chapter planning locations if set
        planning_locs = ""
        if self.chapter.planning and self.chapter.planning.locations:
            planning_locs = f"\n\nLOCATIONS EXPECTED IN THIS CHAPTER:\n- " + "\n- ".join(
                self.chapter.planning.locations)

        prompt = f"""Analyze the following chapter for WORLDBUILDING CONSISTENCY against the established world elements below.

CRITICAL SCOPE RULE: ONLY analyze world elements that are actually referenced, described, or relevant to what happens in this chapter. The worldbuilding data is reference material — do NOT discuss places, factions, technologies, or elements that never appear in this chapter. Every observation MUST cite specific text from the chapter as evidence.

ESTABLISHED WORLDBUILDING (reference only — use these to check consistency for elements that appear):
{world_context}
{planning_locs}

CHAPTER TEXT {sample_note}:
---
{sample}
---

Provide your analysis in these sections:

## World Elements Present
List ONLY the places, factions, technologies, cultures, creatures, and world-specific elements that are actually mentioned or described in this chapter. Note whether each has a defined profile in the worldbuilding data. Do NOT list worldbuilding elements that are absent from this chapter.

## Geographic & Setting Consistency
For locations that appear IN THIS CHAPTER, check that descriptions match the established profiles — climate, atmosphere, features, size, population. Flag any contradictions. Skip if no established locations appear.

## Faction & Political Consistency
For factions referenced IN THIS CHAPTER, check that behaviors, alliances, enemies, and power dynamics match the established worldbuilding. Skip if no factions appear.

## Technology & Magic Consistency
For technologies or magical systems used IN THIS CHAPTER, verify consistency with established rules and tech level. Flag anachronisms. Skip if none appear.

## Cultural Consistency
For cultural elements referenced IN THIS CHAPTER, check alignment with established cultures. Skip if none appear.

## Historical Accuracy
For historical references made IN THIS CHAPTER, check against established events and dates. Skip if none appear.

## Undeveloped World Elements
Note any NEW world elements introduced in this chapter that don't have profiles in the worldbuilding data. Suggest which ones should be formally added.

## Advice
Provide 2-3 specific, actionable suggestions for improving worldbuilding in THIS chapter. Focus on what's actually written — consider immersion, sensory details, and showing the world through character interaction rather than exposition."""

        self._world_analysis_dialog = ProseAnalysisDialog(
            chapter_title=f"World Analysis - {self.chapter.title}", parent=self)
        self._world_analysis_dialog.show()
        self._world_analysis_dialog.set_loading()

        import threading

        def run_analysis():
            try:
                handler = self._get_ai_handler()
                if handler:
                    result = handler(prompt, "Auto")
                else:
                    result = self._fallback_local_analysis(prompt)
                self._world_analysis_ready.emit(result)
            except Exception as e:
                self._world_analysis_ready.emit(f"Analysis failed: {str(e)}")

        thread = threading.Thread(target=run_analysis, daemon=True)
        thread.start()

    def _on_world_analysis_complete(self, result: str):
        """Handle world analysis result."""
        if hasattr(self, '_world_analysis_dialog') and self._world_analysis_dialog:
            self._world_analysis_dialog.set_result(result)

    # ------------------------------------------------------------------
    # Plot Analysis
    # ------------------------------------------------------------------

    def _build_plot_context(self):
        """Build plot reference data from the project."""
        project = self.project if hasattr(self, 'project') and self.project else None
        if not project:
            return ""

        sp = project.story_planning
        parts = []

        # Main plot
        if sp.main_plot:
            parts.append(f"MAIN PLOT:\n{sp.main_plot}")

        # Themes
        if sp.themes:
            parts.append("THEMES:\n- " + "\n- ".join(sp.themes))

        # Freytag pyramid events
        fp = sp.freytag_pyramid
        if fp.events:
            event_parts = []
            for evt in fp.events:
                event_parts.append(
                    f"- [{evt.stage.upper()}] **{evt.title}**: {evt.description[:120]}"
                    + (f" (Outcome: {evt.outcome[:80]})" if evt.outcome else "")
                )
            parts.append("PLOT EVENTS (Freytag Pyramid):\n" + "\n".join(event_parts))
        else:
            # Legacy text fields
            for stage in ['exposition', 'rising_action', 'climax', 'falling_action', 'resolution']:
                val = getattr(fp, stage, '')
                if val and val.strip():
                    parts.append(f"{stage.upper().replace('_', ' ')}:\n{val[:200]}")

        # Subplots
        if sp.subplots:
            subplot_parts = []
            for sub in sp.subplots:
                subplot_parts.append(
                    f"- **{sub.title}** ({sub.status}): {sub.description[:120]}"
                    + (f" | Connection: {sub.connection_to_main[:80]}" if sub.connection_to_main else "")
                )
            parts.append("SUBPLOTS:\n" + "\n".join(subplot_parts))

        # Story promises
        if sp.promises:
            promise_parts = [f"- [{p.promise_type}] **{p.title}**: {p.description[:100]}" for p in sp.promises]
            parts.append("STORY PROMISES:\n" + "\n".join(promise_parts))

        return "\n\n".join(parts)

    def _build_chapter_plan_context(self):
        """Build the chapter-specific planning context."""
        cp = self.chapter.planning
        if not cp:
            return ""

        parts = []
        if cp.description:
            parts.append(f"CHAPTER DESCRIPTION: {cp.description}")
        if cp.events:
            event_parts = [
                f"- [{e.stage}] {e.text}: {e.description[:100]}" + (" ✓" if e.completed else "")
                for e in cp.events
            ]
            parts.append("PLANNED EVENTS:\n" + "\n".join(event_parts))
        if cp.scene_list:
            parts.append("PLANNED SCENES:\n- " + "\n- ".join(cp.scene_list))
        if cp.themes:
            parts.append("CHAPTER THEMES:\n- " + "\n- ".join(cp.themes))
        if cp.pov_character:
            parts.append(f"POV CHARACTER: {cp.pov_character}")
        if cp.timeline_position:
            parts.append(f"TIMELINE POSITION: {cp.timeline_position}")
        if cp.tone:
            parts.append(f"CHAPTER TONE: {cp.tone}")
        if cp.notes:
            parts.append(f"NOTES: {cp.notes[:300]}")

        return "\n".join(parts)

    def _analyze_plot(self):
        """Analyze plot adherence and pacing against story plan."""
        result = self._get_chapter_sample()
        if result is None:
            return
        sample, sample_note = result

        plot_context = self._build_plot_context()
        chapter_plan = self._build_chapter_plan_context()

        if not plot_context and not chapter_plan:
            QMessageBox.warning(
                self, "No Plot Data",
                "No story planning or chapter plan defined. Add a main plot, events, or chapter plan first.")
            return

        # Prose profile for pacing context
        prose_context = ""
        project = self.project if hasattr(self, 'project') and self.project else None
        if project and hasattr(project, 'prose_profile'):
            pp = project.prose_profile
            ctx_parts = []
            if pp.genre:
                ctx_parts.append(f"Genre: {pp.genre}")
            if pp.tone:
                ctx_parts.append(f"Target Tone: {pp.tone}")
            if ctx_parts:
                prose_context = "\n\nPROSE PROFILE:\n" + "\n".join(ctx_parts)

        # Get chapter number for arc position context
        chapter_position = ""
        if self.chapter.number:
            total = 0
            if project and project.manuscript and project.manuscript.chapters:
                total = len(project.manuscript.chapters)
            chapter_position = f"\n\nCHAPTER POSITION: Chapter {self.chapter.number}" + (f" of {total}" if total else "")

        prompt = f"""Analyze the following chapter for PLOT ADHERENCE AND PACING against the story plan below.

CRITICAL SCOPE RULE: ONLY analyze what actually happens in this chapter. The story plan is reference material for checking alignment — do NOT summarize or discuss plot events, subplots, or promises that are not touched by this chapter. Every observation MUST cite specific text from the chapter as evidence.

STORY PLAN (reference only — use to check alignment):
{plot_context}

CHAPTER PLAN:
{chapter_plan if chapter_plan else "(No specific chapter plan set)"}
{prose_context}{chapter_position}

CHAPTER TEXT {sample_note}:
---
{sample}
---

Provide your analysis in these sections:

## Plot Events in This Chapter
List which planned plot events or chapter events actually occur in this chapter. For each, note if it's fully executed, partially addressed, or just hinted at. Cite the relevant text. Only list events that are actually present.

## Plot Advancement
Assess how this chapter advances the main plot based on what's written. Does it move the story forward meaningfully, or does it stall? What story questions does it raise or answer? Cite specific moments.

## Subplot Progress
Identify which subplots (if any) are advanced in this chapter. Only discuss subplots that are actually touched here. Are connections to the main plot maintained?

## Pacing Assessment
Evaluate the pacing of this chapter as written. Is it well-balanced between action, dialogue, reflection, and description? Flag specific sections that drag or feel rushed, citing the text.

## Story Promise Fulfillment
Check whether this chapter works toward fulfilling any story promises that are relevant to its content. Only discuss promises that are actually touched here.

## Theme Integration
Assess how themes are expressed in this chapter through action and character. Only discuss themes that are actually present in the text.

## Structural Position
Evaluate whether this chapter's content is appropriate for its position in the narrative arc. Is the tension level right for where we are in the story?

## Advice
Provide 3-4 specific, actionable suggestions for improving THIS chapter's plot effectiveness. Focus on what's written — consider missing beats, pacing adjustments, tension opportunities, foreshadowing, and scene ordering. Do not suggest adding content from other parts of the story plan that don't belong in this chapter."""

        self._plot_analysis_dialog = ProseAnalysisDialog(
            chapter_title=f"Plot Analysis - {self.chapter.title}", parent=self)
        self._plot_analysis_dialog.show()
        self._plot_analysis_dialog.set_loading()

        import threading

        def run_analysis():
            try:
                handler = self._get_ai_handler()
                if handler:
                    result = handler(prompt, "Auto")
                else:
                    result = self._fallback_local_analysis(prompt)
                self._plot_analysis_ready.emit(result)
            except Exception as e:
                self._plot_analysis_ready.emit(f"Analysis failed: {str(e)}")

        thread = threading.Thread(target=run_analysis, daemon=True)
        thread.start()

    def _on_plot_analysis_complete(self, result: str):
        """Handle plot analysis result."""
        if hasattr(self, '_plot_analysis_dialog') and self._plot_analysis_dialog:
            self._plot_analysis_dialog.set_result(result)

    def _lookup_selected_text(self, text: str):
        """Look up context for selected text."""
        if hasattr(self.editor, 'lookup_context_callback') and self.editor.lookup_context_callback:
            from src.ui.enhanced_text_editor import ContextLookupDialog
            result = self.editor.lookup_context_callback(text)
            dialog = ContextLookupDialog(f"Context for: {text}", result, self)
            dialog.exec()

    def _lookup_character(self):
        """Look up character reference."""
        if not hasattr(self.editor, 'get_character_list_callback') or not self.editor.get_character_list_callback:
            QMessageBox.information(self, "Not Available", "Character lookup not configured.")
            return

        from src.ui.enhanced_text_editor import ContextLookupDialog, QuickReferenceDialog
        characters = self.editor.get_character_list_callback()
        if not characters:
            QMessageBox.information(self, "No Characters", "No characters defined in your project yet.")
            return

        dialog = QuickReferenceDialog(characters, "Character", self)
        if dialog.exec() and dialog.selected_item:
            if hasattr(self.editor, 'lookup_characters_callback') and self.editor.lookup_characters_callback:
                result = self.editor.lookup_characters_callback(dialog.selected_item)
                ref_dialog = ContextLookupDialog(f"Character: {dialog.selected_item}", result, self)
                ref_dialog.exec()

    def _lookup_worldbuilding(self):
        """Look up worldbuilding reference."""
        if not hasattr(self.editor, 'get_worldbuilding_sections_callback') or not self.editor.get_worldbuilding_sections_callback:
            QMessageBox.information(self, "Not Available", "Worldbuilding lookup not configured.")
            return

        from src.ui.enhanced_text_editor import ContextLookupDialog, QuickReferenceDialog
        sections = self.editor.get_worldbuilding_sections_callback()
        if not sections:
            QMessageBox.information(self, "No Worldbuilding", "No worldbuilding sections defined yet.")
            return

        dialog = QuickReferenceDialog(sections, "Worldbuilding Section", self)
        if dialog.exec() and dialog.selected_item:
            if hasattr(self.editor, 'lookup_worldbuilding_callback') and self.editor.lookup_worldbuilding_callback:
                result = self.editor.lookup_worldbuilding_callback(dialog.selected_item)
                ref_dialog = ContextLookupDialog(f"Worldbuilding: {dialog.selected_item}", result, self)
                ref_dialog.exec()

    def _lookup_plot(self):
        """Look up plot reference."""
        if hasattr(self.editor, 'lookup_plot_callback') and self.editor.lookup_plot_callback:
            from src.ui.enhanced_text_editor import ContextLookupDialog
            result = self.editor.lookup_plot_callback()
            dialog = ContextLookupDialog("Plot Reference", result, self)
            dialog.exec()

    def _lookup_technology(self):
        """Look up technology reference."""
        if not self.project:
            QMessageBox.information(self, "Not Available", "No project loaded.")
            return

        from src.ui.enhanced_text_editor import ContextLookupDialog, QuickReferenceDialog

        wb = self.project.worldbuilding
        if not hasattr(wb, 'technologies') or not wb.technologies:
            QMessageBox.information(self, "No Technologies", "No technologies defined in worldbuilding.")
            return

        tech_names = [t.name for t in wb.technologies]
        dialog = QuickReferenceDialog(tech_names, "Technology", self)
        if dialog.exec() and dialog.selected_item:
            tech = next((t for t in wb.technologies if t.name == dialog.selected_item), None)
            if tech:
                result = f"""
**{tech.name}**
Type: {tech.technology_type.value.replace('_', ' ').title() if hasattr(tech.technology_type, 'value') else tech.technology_type}

**Description:**
{tech.description}

**How It Works:**
{tech.how_it_works or 'Not documented'}

**Factions with Access:**
{', '.join(tech.factions_with_access) if tech.factions_with_access else 'All'}

**Impact Level:** {tech.game_changing_level}/100
**Destructive Level:** {tech.destructive_level}/100

**Limitations:**
{tech.limitations or 'None specified'}

**Story Importance:**
{tech.story_importance or 'Not specified'}
                """.strip()
                ref_dialog = ContextLookupDialog(f"Technology: {tech.name}", result, self)
                ref_dialog.exec()

    def _find_similar_content(self, text: str):
        """Find content similar to the highlighted text using semantic search."""
        if not self.project:
            QMessageBox.warning(self, "No Project", "Please load a project first.")
            return

        # Show the similarity search dialog
        dialog = SimilaritySearchDialog(
            search_text=text,
            project=self.project,
            parent=self
        )
        dialog.exec()

    def _show_advanced_search(self):
        """Show advanced search dialog for project content."""
        if not self.project:
            QMessageBox.warning(self, "No Project", "Please load a project first.")
            return

        dialog = AdvancedSearchDialog(project=self.project, parent=self)
        dialog.exec()

    def _save_revision(self):
        """Save current content as a revision."""
        notes, ok = QInputDialog.getText(
            self,
            "Save Draft",
            "Enter draft notes (optional):"
        )

        if ok:
            self.save_to_model()
            html = self.editor.toHtml() if hasattr(self.editor, 'toHtml') else ""
            project_dir = self._get_project_dir()
            self.chapter.add_revision(notes, html_content=html, project_dir=project_dir)
            QMessageBox.information(
                self,
                "Draft Saved",
                f"Draft #{len(self.chapter.revisions)} saved."
            )

    def _view_revisions(self):
        """Open the revision management dialog."""
        from src.ui.revision_dialog import RevisionDialog

        # Get project directory
        project_dir = self._get_project_dir()

        # Get current editor content
        current_content = self.editor.toPlainText() if hasattr(self.editor, 'toPlainText') else self.chapter.content
        current_html = self.editor.toHtml() if hasattr(self.editor, 'toHtml') else self.chapter.html_content

        dialog = RevisionDialog(
            chapter=self.chapter,
            project_dir=project_dir,
            current_content=current_content,
            current_html=current_html,
            parent=self
        )

        # Handle revision restore
        def on_restore(content, html):
            if html:
                self.editor.setHtml(html)
            else:
                self.editor.setPlainText(content)
            self.content_changed.emit()

        # Handle edit alongside
        def on_edit_alongside(rev_number):
            self._enter_side_by_side(rev_number)

        dialog.revision_restored.connect(on_restore)
        dialog.edit_alongside.connect(on_edit_alongside)
        dialog.exec()

        # If revisions were modified, mark content changed so project saves
        self.content_changed.emit()

    def _get_project_dir(self):
        """Get the project directory path."""
        # First check own project reference
        if self.project and hasattr(self.project, 'project_path') and self.project.project_path:
            return Path(self.project.project_path).parent
        # Walk up to find ManuscriptEditor
        parent = self.parent()
        while parent:
            if hasattr(parent, 'project') and parent.project:
                if hasattr(parent.project, 'project_path') and parent.project.project_path:
                    return Path(parent.project.project_path).parent
            parent = parent.parent() if hasattr(parent, 'parent') else None
        return None

    # --- Side-by-side editing ---

    def _is_wide_screen(self) -> bool:
        """Check if the screen is wide enough for horizontal side-by-side."""
        screen = QApplication.primaryScreen()
        if screen:
            return screen.availableGeometry().width() >= 1400
        return True

    def _enter_side_by_side(self, reference_revision_number: int):
        """Enter side-by-side editing mode: current draft left/top, older draft right/bottom."""
        if hasattr(self, '_side_by_side_mode') and self._side_by_side_mode:
            self._exit_side_by_side()

        self._side_by_side_mode = True
        self._reference_revision = reference_revision_number

        # Load reference content and metadata
        project_dir = self._get_project_dir()
        ref_content = ""
        ref_notes = ""
        ref_html = ""
        ref_date = ""
        if project_dir:
            ref_content = self.chapter.load_revision_content(
                project_dir, reference_revision_number) or ""
        for rev in self.chapter.revisions:
            if rev.revision_number == reference_revision_number:
                ref_notes = rev.notes or ""
                ref_html = rev.html_content or ""
                ref_date = rev.timestamp.strftime("%b %d, %Y %H:%M") if rev.timestamp else ""
                if not ref_content:
                    ref_content = rev.content
                break

        # Determine layout orientation based on screen width
        use_horizontal = self._is_wide_screen()
        orientation = Qt.Orientation.Horizontal if use_horizontal else Qt.Orientation.Vertical

        # --- Build the side-by-side container ---
        self._sbs_container = QWidget()
        sbs_outer = QVBoxLayout(self._sbs_container)
        sbs_outer.setContentsMargins(0, 0, 0, 0)
        sbs_outer.setSpacing(4)

        # --- Search bar ---
        search_bar = QHBoxLayout()
        search_bar.setSpacing(4)

        search_label = QLabel("Find:")
        search_label.setStyleSheet("font-size: 11px; font-weight: bold; padding: 2px;")
        search_bar.addWidget(search_label)

        self._sbs_search_field = QLineEdit()
        self._sbs_search_field.setPlaceholderText("Search in drafts...")
        self._sbs_search_field.setStyleSheet("""
            QLineEdit {
                padding: 4px 8px; border: 1px solid #d1d5db; border-radius: 4px;
                font-size: 11px; background: white;
            }
            QLineEdit:focus { border: 2px solid #6366f1; }
        """)
        self._sbs_search_field.returnPressed.connect(self._sbs_search_next)
        search_bar.addWidget(self._sbs_search_field)

        self._sbs_search_scope = QComboBox()
        self._sbs_search_scope.addItems(["Both Drafts", "Current Draft", "Older Draft"])
        self._sbs_search_scope.setStyleSheet("font-size: 11px; padding: 2px;")
        self._sbs_search_scope.setMaximumWidth(120)
        search_bar.addWidget(self._sbs_search_scope)

        search_next_btn = QPushButton("Next")
        search_next_btn.setStyleSheet(
            "font-size: 11px; padding: 3px 8px; background: #6366f1; color: white;"
            " border: none; border-radius: 4px;")
        search_next_btn.clicked.connect(self._sbs_search_next)
        search_bar.addWidget(search_next_btn)

        search_prev_btn = QPushButton("Prev")
        search_prev_btn.setStyleSheet(
            "font-size: 11px; padding: 3px 8px; background: #6366f1; color: white;"
            " border: none; border-radius: 4px;")
        search_prev_btn.clicked.connect(self._sbs_search_prev)
        search_bar.addWidget(search_prev_btn)

        self._sbs_search_status = QLabel("")
        self._sbs_search_status.setStyleSheet("font-size: 10px; color: #6b7280;")
        search_bar.addWidget(self._sbs_search_status)

        search_bar.addStretch()

        close_sbs_btn = QPushButton("Close Side-by-Side")
        close_sbs_btn.setStyleSheet("""
            QPushButton {
                background-color: #ef4444; color: white; border: none;
                border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: 500;
            }
            QPushButton:hover { background-color: #dc2626; }
        """)
        close_sbs_btn.clicked.connect(self._exit_side_by_side)
        search_bar.addWidget(close_sbs_btn)

        sbs_outer.addLayout(search_bar)

        # --- Splitter with two panes ---
        self._sbs_splitter = QSplitter(orientation)

        # === Left/Top pane: CURRENT DRAFT ===
        current_pane_widget = QWidget()
        current_pane_layout = QVBoxLayout(current_pane_widget)
        current_pane_layout.setContentsMargins(0, 0, 0, 0)
        current_pane_layout.setSpacing(2)

        current_label = QLabel("Current Draft (latest)")
        current_label.setStyleSheet(
            "font-weight: bold; font-size: 12px; color: #059669; padding: 4px 8px;"
            "background-color: #ecfdf5; border-radius: 4px;")
        current_pane_layout.addWidget(current_label)

        # We'll reparent the main editor + annotation margin into this pane
        # Store original parent so we can restore on exit
        self._sbs_original_editor_parent = self.editor.parent()
        self._sbs_original_margin_parent = self.annotation_margin.parent()
        self._sbs_original_editor_layout = self._sbs_original_editor_parent.layout() if self._sbs_original_editor_parent else None

        # Wrap editor + margin in a new horizontal layout
        current_editor_row = QHBoxLayout()
        current_editor_row.setContentsMargins(0, 0, 0, 0)
        current_editor_row.setSpacing(0)
        self.annotation_margin.setParent(None)
        self.editor.setParent(None)
        current_editor_row.addWidget(self.annotation_margin)
        current_editor_row.addWidget(self.editor)
        current_pane_layout.addLayout(current_editor_row)

        current_wc = len(self.editor.toPlainText().split()) if self.editor.toPlainText().strip() else 0
        self._current_wc_label = QLabel(f"Words: {current_wc}")
        self._current_wc_label.setStyleSheet("font-size: 11px; color: #6b7280; padding: 2px;")
        current_pane_layout.addWidget(self._current_wc_label)

        self._sbs_splitter.addWidget(current_pane_widget)

        # === Right/Bottom pane: OLDER DRAFT ===
        older_pane_widget = QWidget()
        older_pane_layout = QVBoxLayout(older_pane_widget)
        older_pane_layout.setContentsMargins(0, 0, 0, 0)
        older_pane_layout.setSpacing(2)

        # Header with label + action buttons
        older_header = QHBoxLayout()
        older_title = f"Older Draft #{reference_revision_number}"
        if ref_notes:
            older_title += f" - {ref_notes}"
        if ref_date:
            older_title += f"  ({ref_date})"
        older_label = QLabel(older_title)
        older_label.setStyleSheet(
            "font-weight: bold; font-size: 12px; color: #b45309; padding: 4px 8px;"
            "background-color: #fffbeb; border-radius: 4px;")
        older_header.addWidget(older_label)
        older_header.addStretch()

        # Toggle editable
        self._ref_edit_btn = QPushButton("Make Editable")
        self._ref_edit_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1; color: white; border: none;
                border-radius: 4px; padding: 4px 10px; font-size: 11px;
            }
            QPushButton:hover { background-color: #4f46e5; }
        """)
        self._ref_edit_btn.clicked.connect(self._toggle_reference_editable)
        older_header.addWidget(self._ref_edit_btn)

        # Delete draft
        delete_rev_btn = QPushButton("Delete Draft")
        delete_rev_btn.setStyleSheet("""
            QPushButton {
                background-color: #ef4444; color: white; border: none;
                border-radius: 4px; padding: 4px 10px; font-size: 11px;
            }
            QPushButton:hover { background-color: #dc2626; }
        """)
        delete_rev_btn.clicked.connect(self._delete_reference_revision)
        older_header.addWidget(delete_rev_btn)

        older_pane_layout.addLayout(older_header)

        # Older draft text pane
        self._reference_pane = QTextEdit()
        self._reference_pane.setReadOnly(True)
        self._reference_pane.setFont(QFont("Times New Roman", 12))
        if ref_html:
            self._reference_pane.setHtml(ref_html)
        else:
            self._reference_pane.setPlainText(ref_content)
        self._reference_pane.setStyleSheet("""
            QTextEdit {
                background-color: #fffdf7;
                border: 2px solid #fde68a;
                border-radius: 4px;
                padding: 8px;
            }
        """)
        older_pane_layout.addWidget(self._reference_pane)

        ref_wc = len(ref_content.split()) if ref_content.strip() else 0
        self._ref_wc_label = QLabel(f"Words: {ref_wc}  |  Read-only")
        self._ref_wc_label.setStyleSheet("font-size: 11px; color: #6b7280; padding: 2px;")
        older_pane_layout.addWidget(self._ref_wc_label)

        self._sbs_splitter.addWidget(older_pane_widget)

        # Equal sizing
        self._sbs_splitter.setSizes([500, 500])
        sbs_outer.addWidget(self._sbs_splitter)

        # --- Insert the side-by-side container into the editor's place ---
        # The editor_widget (containing toolbar, title, editor_container, bottom_toolbar)
        # is in the main_splitter. We insert our sbs_container into the editor_layout
        # in place of the original editor_container.
        # We stored editor_container as a QHBoxLayout at line ~298, but we need
        # to find the parent widget that holds everything.
        # The main_splitter's first widget is editor_widget.
        editor_widget = self.main_splitter.widget(0)
        if editor_widget and editor_widget.layout():
            # Insert sbs_container before the bottom toolbar (at index 2, after toolbar + title)
            # The layout is: toolbar(0), title_layout(1), editor_container(2), bottom_toolbar(3)
            editor_widget.layout().insertWidget(2, self._sbs_container)

    def _toggle_reference_editable(self):
        """Toggle the older draft pane between read-only and editable."""
        if not hasattr(self, '_reference_pane') or not self._reference_pane:
            return

        is_readonly = self._reference_pane.isReadOnly()
        self._reference_pane.setReadOnly(not is_readonly)

        if is_readonly:
            self._ref_edit_btn.setText("Make Read-Only")
            self._reference_pane.setStyleSheet("""
                QTextEdit {
                    background-color: #ffffff;
                    border: 2px solid #f59e0b;
                    border-radius: 4px;
                    padding: 8px;
                }
            """)
            wc = len(self._reference_pane.toPlainText().split()) if self._reference_pane.toPlainText().strip() else 0
            self._ref_wc_label.setText(f"Words: {wc}  |  Editable")
        else:
            self._ref_edit_btn.setText("Make Editable")
            self._reference_pane.setStyleSheet("""
                QTextEdit {
                    background-color: #fffdf7;
                    border: 2px solid #fde68a;
                    border-radius: 4px;
                    padding: 8px;
                }
            """)
            wc = len(self._reference_pane.toPlainText().split()) if self._reference_pane.toPlainText().strip() else 0
            self._ref_wc_label.setText(f"Words: {wc}  |  Read-only")

    def _delete_reference_revision(self):
        """Delete the older draft currently shown in the reference pane."""
        if not hasattr(self, '_reference_revision') or not self._reference_revision:
            return

        rev_num = self._reference_revision

        if rev_num == self.chapter.active_revision_number:
            QMessageBox.warning(
                self, "Cannot Delete",
                "Cannot delete the active draft.")
            return

        reply = QMessageBox.question(
            self, "Delete Draft",
            f"Permanently delete Draft #{rev_num}?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Delete file from disk
        project_dir = self._get_project_dir()
        for rev in self.chapter.revisions:
            if rev.revision_number == rev_num and rev.file_path and project_dir:
                full_path = project_dir / rev.file_path
                if full_path.exists():
                    full_path.unlink()

        self.chapter.revisions = [
            r for r in self.chapter.revisions if r.revision_number != rev_num
        ]

        self._exit_side_by_side()
        self.content_changed.emit()

    def _sbs_search_next(self):
        """Search forward in one or both draft panes."""
        self._sbs_do_search(forward=True)

    def _sbs_search_prev(self):
        """Search backward in one or both draft panes."""
        self._sbs_do_search(forward=False)

    def _sbs_do_search(self, forward: bool = True):
        """Execute search across selected draft panes."""
        if not hasattr(self, '_sbs_search_field'):
            return
        query = self._sbs_search_field.text()
        if not query:
            return

        scope = self._sbs_search_scope.currentText()
        flags = QTextDocument.FindFlag(0)
        if not forward:
            flags = QTextDocument.FindFlag.FindBackward

        found_in = []

        if scope in ("Both Drafts", "Current Draft"):
            if self.editor.find(query, flags):
                found_in.append("current")

        if scope in ("Both Drafts", "Older Draft"):
            if hasattr(self, '_reference_pane') and self._reference_pane:
                if self._reference_pane.find(query, flags):
                    found_in.append("older")

        if found_in:
            label_parts = [{"current": "Current", "older": "Older"}[f] for f in found_in]
            self._sbs_search_status.setText(f"Found in: {', '.join(label_parts)}")
            self._sbs_search_status.setStyleSheet("font-size: 10px; color: #059669;")
        else:
            self._sbs_search_status.setText("Not found")
            self._sbs_search_status.setStyleSheet("font-size: 10px; color: #ef4444;")

    def _exit_side_by_side(self):
        """Exit side-by-side editing mode, restoring the editor to its original position."""
        if not hasattr(self, '_side_by_side_mode') or not self._side_by_side_mode:
            return

        self._side_by_side_mode = False

        # Reparent editor + margin back to their original container
        if hasattr(self, '_sbs_original_editor_layout') and self._sbs_original_editor_layout:
            self.annotation_margin.setParent(None)
            self.editor.setParent(None)
            self._sbs_original_editor_layout.addWidget(self.annotation_margin)
            self._sbs_original_editor_layout.addWidget(self.editor)

        # Remove the side-by-side container
        if hasattr(self, '_sbs_container') and self._sbs_container:
            self._sbs_container.setParent(None)
            self._sbs_container.deleteLater()
            self._sbs_container = None
            self._reference_pane = None
            self._sbs_splitter = None

    def _import_from_word(self):
        """Import chapter content from Word document."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import from Word",
            "",
            "Word Documents (*.docx);;All Files (*)"
        )

        if file_path:
            success = self.editor.import_from_docx(file_path)
            if success:
                QMessageBox.information(
                    self,
                    "Import Successful",
                    "Chapter content imported from Word document."
                )
                self.content_changed.emit()
            else:
                QMessageBox.critical(
                    self,
                    "Import Failed",
                    "Failed to import Word document. Check the console for details."
                )

    def _export_to_word(self):
        """Export chapter content to Word document."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export to Word",
            f"{self.chapter.title}.docx",
            "Word Documents (*.docx);;All Files (*)"
        )

        if file_path:
            success = self.editor.export_to_docx(file_path, self.chapter.title)
            if success:
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Chapter exported to: {file_path}"
                )
            else:
                QMessageBox.critical(
                    self,
                    "Export Failed",
                    "Failed to export to Word document. Check the console for details."
                )

    def _setup_context_lookup(self):
        """Set up context lookup callbacks for RAG system."""
        from src.ai.rag_system import RAGSystem

        # Get memory manager from parent if available
        memory_manager = None
        parent = self.parent()
        while parent:
            if hasattr(parent, 'memory_manager'):
                memory_manager = parent.memory_manager
                break
            parent = parent.parent()

        # Create RAG system with memory manager for faster lookups
        rag = RAGSystem(self.project, memory_manager=memory_manager)

        # Define callback functions
        def lookup_worldbuilding(section_name: str) -> str:
            result = rag.get_quick_reference("worldbuilding", section_name)
            return result if result else f"No worldbuilding information found for: {section_name}"

        def lookup_characters(character_name: str) -> str:
            result = rag.get_quick_reference("character", character_name)
            return result if result else f"No character information found for: {character_name}"

        def lookup_plot() -> str:
            sp = self.project.story_planning
            plot_text = f"""
**Main Plot:**
{sp.main_plot}

**Story Structure (Freytag's Pyramid):**

**Exposition:**
{sp.freytag_pyramid.exposition}

**Rising Action:**
{sp.freytag_pyramid.rising_action}

**Climax:**
{sp.freytag_pyramid.climax}

**Falling Action:**
{sp.freytag_pyramid.falling_action}

**Resolution:**
{sp.freytag_pyramid.resolution}
            """.strip()
            return plot_text

        def lookup_context(query: str) -> str:
            return rag.summarize_context(query, max_results=5)

        def get_character_list() -> list:
            return [c.name for c in self.project.characters]

        def get_worldbuilding_sections() -> list:
            sections = [
                "Mythology", "Planets", "Climate", "History",
                "Politics", "Military", "Economy", "Power Hierarchy"
            ]
            sections.extend(self.project.worldbuilding.custom_sections.keys())
            return sections

        # Set callbacks on editor
        self.editor.set_callbacks(
            lookup_worldbuilding=lookup_worldbuilding,
            lookup_characters=lookup_characters,
            lookup_plot=lookup_plot,
            lookup_context=lookup_context,
            get_character_list=get_character_list,
            get_worldbuilding_sections=get_worldbuilding_sections
        )

    def _add_annotation(self, line_number: int = None):
        """Add annotation at current line or specified line."""
        if line_number is None:
            cursor = self.editor.textCursor()
            line_number = cursor.blockNumber() + 1

        dialog = AnnotationDialog(
            line_number=line_number,
            available_characters=self.project.characters if self.project else [],
            available_chapters=self.project.manuscript.chapters if self.project else [],
            available_myths=self.project.worldbuilding.myths if self.project else [],
            available_places=self.project.worldbuilding.places if self.project else [],
            parent=self
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            annotation = dialog.get_annotation()
            self.chapter.annotations.append(annotation)
            self._update_margin_annotations()
            self._highlight_annotated_lines()
            self.content_changed.emit()
            self.annotations_changed.emit()

    def _on_margin_clicked(self, line_number: int):
        """Handle click on annotation margin - show annotations for that line."""
        line_annotations = [a for a in self.chapter.annotations if a.line_number == line_number]

        if not line_annotations:
            return

        # If only one annotation, edit it directly
        if len(line_annotations) == 1:
            self._edit_annotation(line_annotations[0])
        else:
            # Show selection dialog
            from PyQt6.QtWidgets import QListWidget, QDialog, QVBoxLayout, QPushButton
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Annotations at Line {line_number}")
            layout = QVBoxLayout(dialog)

            list_widget = QListWidget()
            for ann in line_annotations:
                type_icon = {"note": "📝", "attribution": "🔗", "recommendation": "💡"}
                icon = type_icon.get(ann.annotation_type, "📝")
                preview = ann.content[:50] + "..." if len(ann.content) > 50 else ann.content
                list_widget.addItem(f"{icon} {preview}")

            list_widget.itemDoubleClicked.connect(lambda: (self._edit_annotation(line_annotations[list_widget.currentRow()]), dialog.accept()))
            layout.addWidget(list_widget)

            btn = QPushButton("Close")
            btn.clicked.connect(dialog.accept)
            layout.addWidget(btn)

            dialog.exec()

    def _edit_annotation(self, annotation: Annotation):
        """Edit an annotation."""
        dialog = AnnotationDialog(
            annotation=annotation,
            line_number=annotation.line_number,
            available_characters=self.project.characters if self.project else [],
            available_chapters=self.project.manuscript.chapters if self.project else [],
            available_myths=self.project.worldbuilding.myths if self.project else [],
            available_places=self.project.worldbuilding.places if self.project else [],
            parent=self
        )

        # Connect delete signal
        dialog.delete_requested.connect(lambda: self._delete_annotation(annotation.id))

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._update_margin_annotations()
            self._highlight_annotated_lines()
            self.content_changed.emit()
            self.annotations_changed.emit()

    def _delete_annotation(self, annotation_id: str):
        """Delete annotation."""
        self.chapter.annotations = [a for a in self.chapter.annotations if a.id != annotation_id]
        self._update_margin_annotations()
        self._highlight_annotated_lines()
        self.content_changed.emit()
        self.annotations_changed.emit()

    def _update_margin_annotations(self):
        """Update annotation margin."""
        self.annotation_margin.set_annotations(self.chapter.annotations)

    def _update_margin_area_scroll(self):
        """Update margin area when editor scrolls."""
        self.annotation_margin.update()

    def _view_annotations_list(self):
        """Open annotation list dialog."""
        dialog = AnnotationListDialog(self.chapter.annotations, self)

        # Connect signals
        dialog.jump_to_line.connect(self._jump_to_line)
        dialog.edit_annotation.connect(lambda ann_id: self._edit_annotation_by_id_and_refresh(ann_id, dialog))
        dialog.delete_annotation.connect(lambda ann_id: self._delete_annotation_and_refresh(ann_id, dialog))

        dialog.exec()

    def _edit_annotation_by_id_and_refresh(self, annotation_id: str, dialog):
        """Edit annotation and refresh the dialog."""
        annotation = next((a for a in self.chapter.annotations if a.id == annotation_id), None)
        if annotation:
            edit_dialog = AnnotationDialog(
                annotation=annotation,
                line_number=annotation.line_number,
                available_characters=self.project.characters if self.project else [],
                available_chapters=self.project.manuscript.chapters if self.project else [],
                available_myths=self.project.worldbuilding.myths if self.project else [],
                available_places=self.project.worldbuilding.places if self.project else [],
                parent=self
            )

            # Connect delete signal - delete and refresh both dialogs
            edit_dialog.delete_requested.connect(lambda: self._delete_annotation_and_refresh(annotation.id, dialog))

            if edit_dialog.exec() == QDialog.DialogCode.Accepted:
                self._update_margin_annotations()
                self._highlight_annotated_lines()
                self.content_changed.emit()
                self.annotations_changed.emit()
                dialog.set_annotations(self.chapter.annotations)

    def _delete_annotation_and_refresh(self, annotation_id: str, dialog):
        """Delete annotation and refresh the dialog."""
        self.chapter.annotations = [a for a in self.chapter.annotations if a.id != annotation_id]
        self._update_margin_annotations()
        self._highlight_annotated_lines()
        self.content_changed.emit()
        self.annotations_changed.emit()
        dialog.set_annotations(self.chapter.annotations)

    def _jump_to_line(self, line_number: int):
        """Jump to specific line in editor."""
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.MoveAnchor, line_number - 1)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _edit_annotation_by_id(self, annotation_id: str):
        """Edit annotation by ID."""
        annotation = next((a for a in self.chapter.annotations if a.id == annotation_id), None)
        if annotation:
            self._edit_annotation(annotation)

    def _highlight_annotated_lines(self):
        """Highlight lines that have annotations."""
        # Store current cursor position
        old_cursor = self.editor.textCursor()
        old_position = old_cursor.position()

        # Clear all formatting first
        cursor = QTextCursor(self.editor.document())
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextCharFormat()
        cursor.setCharFormat(fmt)

        # Highlight annotated lines
        for annotation in self.chapter.annotations:
            cursor = QTextCursor(self.editor.document())
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.MoveAnchor, annotation.line_number - 1)
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)

            # Color based on type
            fmt = QTextCharFormat()
            if annotation.annotation_type == "attribution":
                fmt.setBackground(QColor(230, 244, 255, 100))  # Light blue
            elif annotation.annotation_type == "recommendation":
                fmt.setBackground(QColor(255, 250, 230, 100))  # Light yellow
            else:
                fmt.setBackground(QColor(240, 240, 240, 100))  # Light gray

            cursor.mergeCharFormat(fmt)

        # Restore cursor position
        new_cursor = self.editor.textCursor()
        new_cursor.setPosition(old_position)
        self.editor.setTextCursor(new_cursor)

    # ==================== Text-to-Speech Methods ====================

    def _tts_speak_chapter(self):
        """Speak the chapter or selected text aloud."""
        if not self.editor.is_tts_available():
            QMessageBox.warning(
                self,
                "TTS Not Available",
                "Text-to-Speech is not available.\n\n"
                "Install with: pip install pyttsx3 edge-tts"
            )
            return

        # Stop any ongoing playback first
        self.editor.stop_speaking()

        # Check if there's selected text
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText().replace('\u2029', '\n')
        else:
            text = self.editor.toPlainText()

        if not text.strip():
            QMessageBox.information(self, "No Text", "No text to read aloud.")
            return

        self.editor.speak_text(text)

    def _tts_stop(self):
        """Stop TTS playback."""
        if self.editor.is_tts_available():
            self.editor.stop_speaking()

    def _tts_generate_document(self):
        """Generate a TTS document for this chapter."""
        text = self.editor.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "No Content", "The chapter is empty.")
            return

        # Get chapter name for file naming
        chapter_name = self.chapter.title or f"chapter_{self.chapter.id[:8]}"

        # Show the TTS document generator dialog
        self.editor.show_tts_document_generator(text)

    def _tts_speak_selection(self, selected_text: str):
        """Speak selected text aloud."""
        if not self.editor.is_tts_available():
            QMessageBox.warning(
                self,
                "TTS Not Available",
                "Text-to-Speech is not available.\n\n"
                "Install with: pip install pyttsx3 edge-tts"
            )
            return

        # Stop any ongoing playback first
        self.editor.stop_speaking()

        # Replace paragraph separator with newline
        text = selected_text.replace('\u2029', '\n')
        if not text.strip():
            QMessageBox.information(self, "No Text", "No text selected to read aloud.")
            return

        self.editor.speak_text(text)

    def _tts_generate_from_selection(self, selected_text: str):
        """Generate a TTS document from selected text."""
        # Replace paragraph separator with newline
        text = selected_text.replace('\u2029', '\n')
        if not text.strip():
            QMessageBox.information(self, "No Selection", "No text selected.")
            return

        # Show the TTS document generator dialog with selection
        self.editor.show_tts_document_generator(text)

    def get_current_chapter_name(self) -> str:
        """Get the current chapter name for TTS file naming."""
        return self.chapter.title or f"chapter_{self.chapter.id[:8]}"

    def _on_tts_progress(self, message: str):
        """Handle TTS progress update - show status on Read button."""
        self.tts_speak_btn.setText(f"🔊 {message}")
        self.tts_speak_btn.setEnabled(False)

    def _on_tts_started(self):
        """Handle TTS playback started."""
        self.tts_speak_btn.setText("🔊 Playing...")
        self.tts_speak_btn.setEnabled(False)
        self.tts_stop_btn.setEnabled(True)

    def _on_tts_stopped(self):
        """Handle TTS playback stopped."""
        self.tts_speak_btn.setText("🔊 Read")
        self.tts_speak_btn.setEnabled(True)
        self.tts_stop_btn.setEnabled(True)

    def _on_tts_error_display(self, error: str):
        """Handle TTS error - display to user."""
        self.tts_speak_btn.setText("🔊 Read")
        self.tts_speak_btn.setEnabled(True)
        QMessageBox.warning(self, "TTS Error", f"Text-to-Speech error:\n\n{error}")

    # ==================== End TTS Methods ====================

    def save_to_model(self):
        """Save editor content to chapter model.

        Content is stored as plain text with Markdown formatting.
        Planning data is saved separately and NOT exported with manuscript.
        """
        # Check if Qt widgets are still valid (not deleted)
        try:
            self.chapter.title = self.title_edit.toPlainText()
            # Save plain text content (contains Markdown formatting)
            self.chapter.content = self.editor.toPlainText()

            # Save planning data (separate from content, not exported)
            planning_data = self.planner_widget.get_planning_data()
        except RuntimeError:
            # Widget has been deleted, skip saving
            return

        # Update the planning object
        self.chapter.planning.outline = planning_data.get('outline', '')
        self.chapter.planning.description = planning_data.get('description', '')
        self.chapter.planning.notes = planning_data.get('notes', '')
        self.chapter.planning.pov_character = planning_data.get('pov_character', '')
        self.chapter.planning.timeline_position = planning_data.get('timeline_position', '')
        self.chapter.planning.characters_featured = planning_data.get('characters_featured', [])
        self.chapter.planning.locations = planning_data.get('locations', [])

        # Convert event dicts back to StoryEvent objects
        events_data = planning_data.get('events', [])
        self.chapter.planning.events = [
            StoryEvent(
                id=event.get('id', str(uuid.uuid4())),
                text=event.get('text', ''),
                description=event.get('description', ''),
                completed=event.get('completed', False),
                stage=event.get('stage', 'rising'),
                arc_position=event.get('arc_position', 50),
                order=event.get('order', i)
            )
            for i, event in enumerate(events_data)
        ]

        # Convert todo dicts back to ChapterTodo objects
        todos_data = planning_data.get('todos', [])
        self.chapter.planning.todos = [
            ChapterTodo(
                id=todo.get('id', str(uuid.uuid4())),
                text=todo.get('text', ''),
                completed=todo.get('completed', False),
                priority=todo.get('priority', 'normal')
            )
            for todo in todos_data
        ]

        # Also update legacy plan field for backward compatibility
        self.chapter.plan = planning_data.get('outline', '')

        self._update_word_count()


class ManuscriptEditor(QWidget):
    """Main manuscript editor with chapter navigation."""

    content_changed = pyqtSignal()
    annotations_changed = pyqtSignal()  # Signal when any annotation changes
    chapter_switched = pyqtSignal()  # Signal when switching between chapters (triggers auto-save)

    def __init__(self, project=None):
        """Initialize manuscript editor."""
        super().__init__()
        self.manuscript: Optional[Manuscript] = None
        self.project = project
        self.current_chapter_editor: Optional[ChapterEditor] = None
        self._current_chapter_id: Optional[str] = None

        # Initialize memory manager for chapter caching and key points
        self.memory_manager = ChapterMemoryManager(
            project=project,
            cache_size=5,  # Keep 5 chapters in memory
            cache_memory_mb=50.0  # Up to 50MB of chapter content
        )
        self._init_ui()

    def set_project(self, project):
        """Set the project for context lookup."""
        self.project = project
        self.memory_manager.set_project(project)

    def _init_ui(self):
        """Initialize user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Minimal header - compact
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(16, 8, 16, 8)

        # Total word count (moved to left, more prominent)
        self.total_word_count_label = QLabel("Total: 0 words")
        self.total_word_count_label.setStyleSheet("font-size: 13px; font-weight: 500; color: #6b7280;")
        header_layout.addWidget(self.total_word_count_label)

        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Splitter for chapter list and editor
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel - chapter list (compact)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        chapters_label = QLabel("Chapters")
        chapters_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #1a1a1a; padding: 4px;")
        left_layout.addWidget(chapters_label)

        self.chapter_list = QListWidget()
        self.chapter_list.currentItemChanged.connect(self._on_chapter_selected)
        self.chapter_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chapter_list.customContextMenuRequested.connect(self._show_chapter_context_menu)
        left_layout.addWidget(self.chapter_list)

        # Chapter buttons (simplified - compact for small screens)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(2)

        compact_ch_btn_style = "font-size: 11px; padding: 2px 5px;"

        add_button = QPushButton("+")
        add_button.setToolTip("Add new chapter at end")
        add_button.setStyleSheet(compact_ch_btn_style)
        add_button.clicked.connect(self._add_chapter)
        button_layout.addWidget(add_button)

        move_up_button = QPushButton("↑")
        move_up_button.setToolTip("Move chapter up")
        move_up_button.setStyleSheet(compact_ch_btn_style)
        move_up_button.clicked.connect(self._move_chapter_up)
        button_layout.addWidget(move_up_button)

        move_down_button = QPushButton("↓")
        move_down_button.setToolTip("Move chapter down")
        move_down_button.setStyleSheet(compact_ch_btn_style)
        move_down_button.clicked.connect(self._move_chapter_down)
        button_layout.addWidget(move_down_button)

        left_layout.addLayout(button_layout)

        # Hint label
        hint_label = QLabel("Right-click chapter for more options")
        hint_label.setStyleSheet("color: #999; font-size: 10px; font-style: italic;")
        left_layout.addWidget(hint_label)

        left_panel.setMaximumWidth(250)
        splitter.addWidget(left_panel)

        # Right panel - chapter editor
        self.editor_container = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_container)
        self.editor_layout.setContentsMargins(0, 0, 0, 0)

        placeholder = QLabel("Add or select a chapter to begin writing")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #999; font-size: 16px;")
        self.editor_layout.addWidget(placeholder)

        splitter.addWidget(self.editor_container)

        # Set splitter sizes
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter, stretch=1)

    def _show_chapter_context_menu(self, position):
        """Show context menu for chapter list."""
        item = self.chapter_list.itemAt(position)
        if not item:
            return

        menu = QMenu(self)

        # Rename action
        rename_action = menu.addAction("Rename")
        rename_action.triggered.connect(self._rename_chapter)

        # Insert before action
        insert_action = menu.addAction("Insert Before")
        insert_action.triggered.connect(self._insert_chapter)

        menu.addSeparator()

        # Draft actions
        new_rev_action = menu.addAction("New Draft")
        new_rev_action.triggered.connect(self._new_revision_from_context)

        revisions_action = menu.addAction("Drafts...")
        revisions_action.triggered.connect(self._view_revisions_from_context)

        menu.addSeparator()

        # Delete action
        delete_action = menu.addAction("Delete Chapter")
        delete_action.triggered.connect(self._remove_chapter)

        menu.exec(self.chapter_list.mapToGlobal(position))

    def _get_context_chapter(self):
        """Get the chapter for the currently selected list item."""
        item = self.chapter_list.currentItem()
        if not item:
            return None
        chapter_id = item.data(Qt.ItemDataRole.UserRole)
        for ch in self.manuscript.chapters:
            if ch.id == chapter_id:
                return ch
        return None

    def _get_project_dir(self):
        """Get the project directory path."""
        if hasattr(self, 'project') and self.project and hasattr(self.project, 'project_path'):
            return Path(self.project.project_path).parent
        # Fallback: try to find from any chapter's file_path
        for ch in self.manuscript.chapters:
            if ch.folder_path or ch.file_path:
                return None  # We need project_path set
        return None

    def _new_revision_from_context(self):
        """Create a new revision for the selected chapter via context menu."""
        chapter = self._get_context_chapter()
        if not chapter:
            return

        project_dir = self._get_project_dir()

        notes, ok = QInputDialog.getText(
            self, "New Draft",
            f"Create a new blank draft for '{chapter.title}'.\n"
            "Draft notes (optional):",
            text=""
        )
        if not ok:
            return

        # If this chapter is currently in the editor, save its content first
        if self.current_chapter_editor and hasattr(self.current_chapter_editor, 'chapter') and \
                self.current_chapter_editor.chapter and self.current_chapter_editor.chapter.id == chapter.id:
            self.current_chapter_editor.save_to_model()

        chapter.create_blank_revision(project_dir=project_dir, notes=notes or "New draft")

        # If chapter is open in editor, enter side-by-side mode
        if self.current_chapter_editor and hasattr(self.current_chapter_editor, 'chapter') and \
                self.current_chapter_editor.chapter and self.current_chapter_editor.chapter.id == chapter.id:
            # The previous active revision number (before the blank one)
            prev_rev = chapter.active_revision_number - 1 if chapter.active_revision_number > 1 else 1
            self.current_chapter_editor._enter_side_by_side(prev_rev)

        self.content_changed.emit()

    def _view_revisions_from_context(self):
        """Open revision dialog for the selected chapter via context menu."""
        chapter = self._get_context_chapter()
        if not chapter:
            return

        # If this chapter is currently in the editor, use the editor's method
        if self.current_chapter_editor and hasattr(self.current_chapter_editor, 'chapter') and \
                self.current_chapter_editor.chapter and self.current_chapter_editor.chapter.id == chapter.id:
            self.current_chapter_editor._view_revisions()
        else:
            # Open dialog directly for a chapter not currently displayed
            project_dir = self._get_project_dir()
            from src.ui.revision_dialog import RevisionDialog
            dialog = RevisionDialog(
                chapter=chapter,
                project_dir=project_dir,
                current_content=chapter.content,
                current_html=chapter.html_content,
                parent=self
            )
            dialog.exec()
            self.content_changed.emit()

    def _add_chapter(self):
        """Add new chapter at the end."""
        if not self.manuscript:
            QMessageBox.warning(
                self,
                "No Manuscript",
                "Please create or load a project first."
            )
            return

        chapter_num = len(self.manuscript.chapters) + 1
        title, ok = QInputDialog.getText(
            self,
            "New Chapter",
            f"Enter title for Chapter {chapter_num}:",
            text=f"Chapter {chapter_num}"
        )

        if ok:
            chapter = Chapter(
                id=str(uuid.uuid4()),
                number=chapter_num,
                title=title
            )
            self.manuscript.chapters.append(chapter)

            item = QListWidgetItem(f"{chapter_num}. {title}")
            item.setData(Qt.ItemDataRole.UserRole, chapter.id)
            self.chapter_list.addItem(item)

            self.chapter_list.setCurrentItem(item)
            self.content_changed.emit()

    def _insert_chapter(self):
        """Insert chapter before selected chapter."""
        if not self.manuscript:
            QMessageBox.warning(
                self,
                "No Manuscript",
                "Please create or load a project first."
            )
            return

        current_row = self.chapter_list.currentRow()
        if current_row < 0:
            self._add_chapter()
            return

        chapter_num = current_row + 1
        title, ok = QInputDialog.getText(
            self,
            "Insert Chapter",
            f"Enter title for new Chapter {chapter_num}:",
            text=f"Chapter {chapter_num}"
        )

        if ok:
            chapter = Chapter(
                id=str(uuid.uuid4()),
                number=chapter_num,
                title=title
            )
            self.manuscript.chapters.insert(current_row, chapter)
            self._renumber_chapters()

            item = QListWidgetItem(f"{chapter_num}. {title}")
            item.setData(Qt.ItemDataRole.UserRole, chapter.id)
            self.chapter_list.insertItem(current_row, item)

            self.chapter_list.setCurrentItem(item)
            self.content_changed.emit()

    def _rename_chapter(self):
        """Rename selected chapter."""
        current_item = self.chapter_list.currentItem()
        if not current_item:
            QMessageBox.information(
                self,
                "No Selection",
                "Please select a chapter to rename."
            )
            return

        chapter_id = current_item.data(Qt.ItemDataRole.UserRole)
        chapter = next(
            (c for c in self.manuscript.chapters if c.id == chapter_id),
            None
        )

        if not chapter:
            return

        new_title, ok = QInputDialog.getText(
            self,
            "Rename Chapter",
            f"Enter new title for Chapter {chapter.number}:",
            text=chapter.title
        )

        if ok and new_title.strip():
            chapter.title = new_title.strip()
            current_item.setText(f"{chapter.number}. {chapter.title}")

            # Update the chapter editor title if it's currently displayed
            if self.current_chapter_editor and self.current_chapter_editor.chapter.id == chapter_id:
                self.current_chapter_editor.title_edit.setPlainText(chapter.title)

            self.content_changed.emit()

    def _remove_chapter(self):
        """Remove selected chapter and its folder from disk."""
        current_item = self.chapter_list.currentItem()
        if not current_item:
            return

        chapter_id = current_item.data(Qt.ItemDataRole.UserRole)
        chapter = None
        for ch in self.manuscript.chapters:
            if ch.id == chapter_id:
                chapter = ch
                break

        # Build warning message
        rev_count = len(chapter.revisions) if chapter else 0
        folder_info = ""
        if chapter and chapter.folder_path:
            folder_info = (
                f"\n\nThis will permanently delete the chapter folder "
                f"and all {rev_count} revision(s) from disk."
            )

        reply = QMessageBox.warning(
            self,
            "Delete Chapter",
            f"Are you sure you want to delete '{current_item.text()}'?"
            f"{folder_info}\n\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Delete chapter folder from disk
            if chapter and chapter.folder_path:
                project_dir = self._get_project_dir()
                if project_dir:
                    chapter.delete_folder(project_dir)

            self.manuscript.chapters = [
                c for c in self.manuscript.chapters if c.id != chapter_id
            ]

            # Block signals to prevent selection change from triggering save on deleted widgets
            self.chapter_list.blockSignals(True)

            row = self.chapter_list.row(current_item)
            self.chapter_list.takeItem(row)

            self._renumber_chapters()
            self._clear_editor()

            # Re-enable signals
            self.chapter_list.blockSignals(False)

            self.content_changed.emit()

    def _move_chapter_up(self):
        """Move selected chapter up."""
        current_row = self.chapter_list.currentRow()
        if current_row <= 0:
            return

        # Save current editor content before reordering
        if self.current_chapter_editor:
            self.current_chapter_editor.save_to_model()

        # Block signals during reorder to prevent spurious chapter switches
        self.chapter_list.blockSignals(True)

        # Swap in manuscript
        self.manuscript.chapters[current_row], self.manuscript.chapters[current_row - 1] = \
            self.manuscript.chapters[current_row - 1], self.manuscript.chapters[current_row]

        # Rebuild list items to ensure IDs match manuscript order
        self._rebuild_chapter_list()

        # Select the moved chapter (now at new position)
        self.chapter_list.setCurrentRow(current_row - 1)

        # Re-enable signals
        self.chapter_list.blockSignals(False)

        self.content_changed.emit()

    def _move_chapter_down(self):
        """Move selected chapter down."""
        current_row = self.chapter_list.currentRow()
        if current_row < 0 or current_row >= self.chapter_list.count() - 1:
            return

        # Save current editor content before reordering
        if self.current_chapter_editor:
            self.current_chapter_editor.save_to_model()

        # Block signals during reorder to prevent spurious chapter switches
        self.chapter_list.blockSignals(True)

        # Swap in manuscript
        self.manuscript.chapters[current_row], self.manuscript.chapters[current_row + 1] = \
            self.manuscript.chapters[current_row + 1], self.manuscript.chapters[current_row]

        # Rebuild list items to ensure IDs match manuscript order
        self._rebuild_chapter_list()

        # Select the moved chapter (now at new position)
        self.chapter_list.setCurrentRow(current_row + 1)

        # Re-enable signals
        self.chapter_list.blockSignals(False)

        self.content_changed.emit()

    def _rebuild_chapter_list(self):
        """Rebuild the chapter list from manuscript.chapters to ensure sync."""
        self.chapter_list.clear()
        for i, chapter in enumerate(self.manuscript.chapters, 1):
            chapter.number = i
            item = QListWidgetItem(f"{i}. {chapter.title}")
            item.setData(Qt.ItemDataRole.UserRole, chapter.id)
            self.chapter_list.addItem(item)

    def _renumber_chapters(self):
        """Renumber all chapters sequentially."""
        for i, chapter in enumerate(self.manuscript.chapters, 1):
            chapter.number = i
            item = self.chapter_list.item(i - 1)
            if item:
                item.setText(f"{i}. {chapter.title}")

    def _on_chapter_selected(self, current, previous):
        """Handle chapter selection change."""
        if not current:
            return

        # Save previous chapter and notify memory manager
        if self.current_chapter_editor and self._current_chapter_id:
            self.current_chapter_editor.save_to_model()
            self._update_total_word_count()
            # Notify memory manager of chapter exit (saves state, marks for re-analysis if changed)
            self.memory_manager.on_chapter_exit(self._current_chapter_id, save_content=True)
            # Emit signal to trigger project auto-save
            self.chapter_switched.emit()

        # Load selected chapter
        chapter_id = current.data(Qt.ItemDataRole.UserRole)
        chapter = next(
            (c for c in self.manuscript.chapters if c.id == chapter_id),
            None
        )

        if chapter:
            # Notify memory manager of chapter entry (preloads cache, generates summary)
            self.memory_manager.on_chapter_enter(chapter_id)

            # Try to load content from cache first for faster display
            cached_content = self.memory_manager.get_chapter_content(chapter_id)
            if cached_content is not None and not chapter.content:
                chapter.content = cached_content

            self._clear_editor()
            self._current_chapter_id = chapter_id
            self.current_chapter_editor = ChapterEditor(chapter, self.project)
            self.current_chapter_editor.content_changed.connect(self._on_content_changed)
            self.current_chapter_editor.content_changed.connect(self.content_changed.emit)
            self.current_chapter_editor.annotations_changed.connect(self.annotations_changed.emit)
            self.current_chapter_editor.word_count_changed.connect(
                lambda _: self._update_total_word_count()
            )
            self.editor_layout.addWidget(self.current_chapter_editor)

            # Preload adjacent chapters in background for faster navigation
            self.memory_manager.preload_adjacent(chapter_id, count=1)

    def _on_content_changed(self):
        """Handle content changes - update memory manager cache."""
        if self._current_chapter_id and self.current_chapter_editor:
            new_content = self.current_chapter_editor.editor.toPlainText()
            self.memory_manager.on_content_changed(self._current_chapter_id, new_content)

    def _clear_editor(self):
        """Clear the editor area."""
        while self.editor_layout.count():
            item = self.editor_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _update_total_word_count(self):
        """Update total manuscript word count."""
        if not self.manuscript:
            return

        total = sum(chapter.word_count for chapter in self.manuscript.chapters)
        self.manuscript.total_word_count = total
        self.total_word_count_label.setText(f"Total Words: {total:,}")

    def load_manuscript(self, manuscript: Manuscript):
        """Load manuscript into editor."""
        self.manuscript = manuscript
        self._current_chapter_id = None
        self.chapter_list.clear()

        # Reset memory manager for new manuscript
        if self.project:
            self.memory_manager.set_project(self.project)

        for chapter in manuscript.chapters:
            item = QListWidgetItem(f"{chapter.number}. {chapter.title}")
            item.setData(Qt.ItemDataRole.UserRole, chapter.id)
            self.chapter_list.addItem(item)

            # Pre-populate cache with chapter content for faster initial load
            if chapter.content:
                self.memory_manager.cache.put(chapter.id, chapter.content)

        self._update_total_word_count()

    def get_manuscript(self) -> Manuscript:
        """Get manuscript data."""
        # Save current chapter
        if self.current_chapter_editor:
            self.current_chapter_editor.save_to_model()

        self._update_total_word_count()
        return self.manuscript

    def get_memory_stats(self) -> dict:
        """Get memory manager statistics for debugging/monitoring."""
        return self.memory_manager.get_cache_stats()

    def get_chapter_summary(self, chapter_id: str):
        """Get summary for a specific chapter (key points, characters, etc.)."""
        return self.memory_manager.get_summary(chapter_id)

    def get_all_key_points(self, max_points: int = 20):
        """Get the most important key points across all chapters."""
        return self.memory_manager.get_key_points_for_context(max_points)

    def get_current_chapter_info(self) -> tuple:
        """Get current chapter content and title.

        Returns:
            Tuple of (content: str, title: str) or ("", "") if no chapter selected
        """
        if not self.current_chapter_editor:
            return "", ""

        # Save current content first
        self.current_chapter_editor.save_to_model()

        chapter = self.current_chapter_editor.chapter
        return chapter.content or "", chapter.title or "Untitled Chapter"

    def search_key_points(self, query: str, point_types=None):
        """Search key points across all chapters."""
        return self.memory_manager.search_key_points(query, point_types)

    def get_current_editor(self) -> Optional['EnhancedTextEditor']:
        """Get the current chapter's text editor, if any."""
        if self.current_chapter_editor:
            return self.current_chapter_editor.editor
        return None

    def get_selected_text(self) -> str:
        """Get currently selected text from the editor."""
        editor = self.get_current_editor()
        if editor:
            cursor = editor.textCursor()
            return cursor.selectedText()
        return ""

    def find_text(self, text: str, case_sensitive: bool = False, whole_word: bool = False) -> bool:
        """Find text in the current chapter editor.

        Args:
            text: Text to find
            case_sensitive: Whether to match case
            whole_word: Whether to match whole words only

        Returns:
            True if text was found, False otherwise
        """
        editor = self.get_current_editor()
        if not editor or not text:
            return False

        # Build find flags
        from PyQt6.QtGui import QTextDocument
        flags = QTextDocument.FindFlag(0)
        if case_sensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if whole_word:
            flags |= QTextDocument.FindFlag.FindWholeWords

        # Try to find from current cursor position
        found = editor.find(text, flags)

        # If not found, wrap around to beginning
        if not found:
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            editor.setTextCursor(cursor)
            found = editor.find(text, flags)

        return found

    def replace_text(self, find_text: str, replace_text: str,
                     case_sensitive: bool = False, whole_word: bool = False) -> bool:
        """Replace current selection (if it matches) and find next.

        Args:
            find_text: Text to find
            replace_text: Text to replace with
            case_sensitive: Whether to match case
            whole_word: Whether to match whole words only

        Returns:
            True if replacement was made, False otherwise
        """
        editor = self.get_current_editor()
        if not editor or not find_text:
            return False

        cursor = editor.textCursor()
        selected = cursor.selectedText()

        # Check if current selection matches
        if case_sensitive:
            matches = selected == find_text
        else:
            matches = selected.lower() == find_text.lower()

        if matches:
            cursor.insertText(replace_text)
            editor.setTextCursor(cursor)

        # Find next occurrence
        return self.find_text(find_text, case_sensitive, whole_word)

    def replace_all_text(self, find_text: str, replace_text: str,
                         case_sensitive: bool = False, whole_word: bool = False) -> int:
        """Replace all occurrences of text.

        Args:
            find_text: Text to find
            replace_text: Text to replace with
            case_sensitive: Whether to match case
            whole_word: Whether to match whole words only

        Returns:
            Number of replacements made
        """
        editor = self.get_current_editor()
        if not editor or not find_text:
            return 0

        # Start from beginning
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        editor.setTextCursor(cursor)

        # Build find flags
        from PyQt6.QtGui import QTextDocument
        flags = QTextDocument.FindFlag(0)
        if case_sensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if whole_word:
            flags |= QTextDocument.FindFlag.FindWholeWords

        count = 0

        # Use document's find for efficiency
        cursor.beginEditBlock()
        while editor.find(find_text, flags):
            cursor = editor.textCursor()
            cursor.insertText(replace_text)
            count += 1
        cursor.endEditBlock()

        return count


class ProseAnalysisDialog(QDialog):
    """Scrollable, copyable dialog for displaying prose analysis results."""

    def __init__(self, chapter_title: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Prose Analysis - {chapter_title}" if chapter_title else "Prose Analysis")
        self.setMinimumSize(650, 500)
        self.resize(750, 600)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header
        header = QLabel(f"Prose Analysis: {chapter_title}")
        header.setStyleSheet("font-weight: bold; font-size: 14px; padding: 4px;")
        layout.addWidget(header)

        # Results area - scrollable and copyable
        self._results = QTextEdit()
        self._results.setReadOnly(True)
        self._results.setFont(QFont("Segoe UI", 11))
        self._results.setStyleSheet("""
            QTextEdit {
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 12px;
                background-color: #fefefe;
                line-height: 1.6;
            }
        """)
        layout.addWidget(self._results)

        # Bottom buttons
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 16px; border-radius: 6px; font-size: 12px;
                background-color: #6366f1; color: white; border: none;
            }
            QPushButton:hover { background-color: #4f46e5; }
        """)
        copy_btn.clicked.connect(self._copy_results)
        btn_bar.addWidget(copy_btn)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 16px; border-radius: 6px; font-size: 12px;
                background-color: #e5e7eb; border: none;
            }
            QPushButton:hover { background-color: #d1d5db; }
        """)
        close_btn.clicked.connect(self.close)
        btn_bar.addWidget(close_btn)

        layout.addLayout(btn_bar)

    def set_loading(self):
        """Show a loading state."""
        self._results.setHtml(
            '<div style="text-align: center; padding: 40px; color: #6b7280;">'
            '<p style="font-size: 16px;">Analyzing prose...</p>'
            '<p style="font-size: 12px;">This may take a moment depending on your AI model.</p>'
            '</div>'
        )

    def set_result(self, text: str):
        """Display the analysis result with markdown-like formatting."""
        # Convert markdown headers and bold to HTML for display
        html = self._markdown_to_html(text)
        self._results.setHtml(html)

    def _markdown_to_html(self, text: str) -> str:
        """Convert basic markdown to HTML for display."""
        import re
        lines = text.split('\n')
        html_lines = []
        in_list = False

        for line in lines:
            stripped = line.strip()

            # Headers
            if stripped.startswith('## '):
                if in_list:
                    html_lines.append('</ul>')
                    in_list = False
                html_lines.append(
                    f'<h3 style="color: #4f46e5; margin-top: 16px; margin-bottom: 4px;">'
                    f'{stripped[3:]}</h3>')
                continue
            if stripped.startswith('# '):
                if in_list:
                    html_lines.append('</ul>')
                    in_list = False
                html_lines.append(
                    f'<h2 style="color: #312e81; margin-top: 20px; margin-bottom: 6px;">'
                    f'{stripped[2:]}</h2>')
                continue

            # List items
            if stripped.startswith('- ') or stripped.startswith('* '):
                if not in_list:
                    html_lines.append('<ul style="margin: 4px 0;">')
                    in_list = True
                item_text = stripped[2:]
                item_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', item_text)
                item_text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', item_text)
                html_lines.append(f'<li style="margin: 2px 0;">{item_text}</li>')
                continue

            # Numbered list items
            if re.match(r'^\d+\.\s', stripped):
                if not in_list:
                    html_lines.append('<ul style="margin: 4px 0;">')
                    in_list = True
                item_text = re.sub(r'^\d+\.\s', '', stripped)
                item_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', item_text)
                item_text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', item_text)
                html_lines.append(f'<li style="margin: 2px 0;">{item_text}</li>')
                continue

            # Close list if we hit a non-list line
            if in_list:
                html_lines.append('</ul>')
                in_list = False

            # Empty lines
            if not stripped:
                html_lines.append('<br>')
                continue

            # Regular paragraph with inline formatting
            p = stripped
            p = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', p)
            p = re.sub(r'\*(.+?)\*', r'<em>\1</em>', p)
            p = re.sub(r'"(.+?)"', r'<span style="color: #6d28d9;">&ldquo;\1&rdquo;</span>', p)
            html_lines.append(f'<p style="margin: 4px 0; line-height: 1.5;">{p}</p>')

        if in_list:
            html_lines.append('</ul>')

        return '<div style="font-family: Segoe UI, sans-serif; font-size: 13px;">' + '\n'.join(html_lines) + '</div>'

    def _copy_results(self):
        """Copy the plain text results to clipboard."""
        text = self._results.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "Copied", "Analysis copied to clipboard.")


class PromiseCheckDialog(QDialog):
    """Dialog for showing promise check results."""

    def __init__(
        self,
        chapter_title: str,
        chapter_content: str,
        promises: List[dict],
        characters: List[dict],
        plot_outline: str = "",
        parent=None
    ):
        """Initialize promise check dialog.

        Args:
            chapter_title: Title of the chapter being checked
            chapter_content: Content of the chapter
            promises: List of promise dicts
            characters: List of character dicts
            plot_outline: Optional plot outline
            parent: Parent widget
        """
        super().__init__(parent)
        self.chapter_title = chapter_title
        self.chapter_content = chapter_content
        self.promises = promises
        self.characters = characters
        self.plot_outline = plot_outline
        self.result = None
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle(f"Promise Check: {self.chapter_title}")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)

        layout = QVBoxLayout(self)

        # Header
        header = QLabel(f"<h3>Checking: {self.chapter_title}</h3>")
        layout.addWidget(header)

        # Info about what's being checked
        info_text = []
        if self.promises:
            info_text.append(f"• {len(self.promises)} story promises")
        if self.characters:
            info_text.append(f"• {len(self.characters)} character profiles")
        info_label = QLabel("Checking against: " + ", ".join(info_text) if info_text else "No data to check against")
        info_label.setStyleSheet("color: #6b7280; margin-bottom: 10px;")
        layout.addWidget(info_label)

        # Results area (scrollable)
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setPlaceholderText("Click 'Run Check' to analyze the chapter...")
        layout.addWidget(self.results_text, stretch=1)

        # Button layout
        button_layout = QHBoxLayout()

        self.run_button = QPushButton("🔍 Run Check")
        self.run_button.clicked.connect(self._run_check)
        button_layout.addWidget(self.run_button)

        button_layout.addStretch()

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)

        layout.addLayout(button_layout)

    def _run_check(self):
        """Run the promise check."""
        self.run_button.setEnabled(False)
        self.run_button.setText("Checking...")
        self.results_text.setPlainText("Analyzing chapter against promises and character profiles...\n\nThis may take a moment.")

        # Force UI update
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        try:
            # Try to get the LLM client
            from src.ai.llm_client import LLMClient
            from src.ai.chapter_analysis_agent import PromiseChecker

            # Get AI config
            from src.config import get_settings
            settings = get_settings()

            if not settings.get('ai', {}).get('api_key'):
                self.results_text.setPlainText(
                    "⚠️ No AI API key configured.\n\n"
                    "Please configure an API key in Settings > AI Configuration\n"
                    "to use the promise checking feature."
                )
                self.run_button.setEnabled(True)
                self.run_button.setText("🔍 Run Check")
                return

            # Initialize LLM client
            llm = LLMClient(
                api_key=settings['ai']['api_key'],
                provider=settings['ai'].get('provider', 'openai'),
                model=settings['ai'].get('model', 'gpt-4o-mini')
            )

            # Run the check
            checker = PromiseChecker(llm)
            result = checker.check_chapter(
                chapter_content=self.chapter_content,
                chapter_title=self.chapter_title,
                promises=self.promises,
                characters=self.characters,
                plot_outline=self.plot_outline
            )

            # Display results
            self._display_results(result)

        except ImportError as e:
            self.results_text.setPlainText(
                f"⚠️ AI module not available: {e}\n\n"
                "Please ensure AI dependencies are installed."
            )
        except Exception as e:
            self.results_text.setPlainText(
                f"⚠️ Error running check: {e}\n\n"
                "Please check your AI configuration and try again."
            )
        finally:
            self.run_button.setEnabled(True)
            self.run_button.setText("🔍 Run Check")

    def _display_results(self, result):
        """Display the check results."""
        lines = []

        # Overall assessment
        adherence_icons = {
            'excellent': '✅',
            'good': '👍',
            'needs_attention': '⚠️',
            'problematic': '❌'
        }
        icon = adherence_icons.get(result.overall_adherence, '📝')
        lines.append(f"<h3>{icon} Overall: {result.overall_adherence.replace('_', ' ').title()}</h3>")
        lines.append(f"<p>{result.summary}</p>")

        lines.append("<hr/>")

        # Tone and Plot assessment
        lines.append(f"<p><b>Tone Assessment:</b> {result.tone_assessment}</p>")
        lines.append(f"<p><b>Plot Alignment:</b> {result.plot_alignment}</p>")

        # Promise violations
        if result.promise_violations:
            lines.append("<h4>⚠️ Promise Violations</h4>")
            for v in result.promise_violations:
                severity_icon = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(v.severity, '⚪')
                lines.append(f"<div style='margin-left: 10px; margin-bottom: 10px;'>")
                lines.append(f"<b>{severity_icon} {v.promise_title}</b> ({v.promise_type})")
                if v.quote:
                    lines.append(f"<br/><i>\"{v.quote}\"</i>")
                if v.violation_description:
                    lines.append(f"<br/>Issue: {v.violation_description}")
                if v.suggestion:
                    lines.append(f"<br/><span style='color: #059669;'>💡 {v.suggestion}</span>")
                lines.append("</div>")
        else:
            lines.append("<p>✅ No promise violations detected</p>")

        # Character inconsistencies
        if result.character_inconsistencies:
            lines.append("<h4>👤 Character Inconsistencies</h4>")
            for c in result.character_inconsistencies:
                lines.append(f"<div style='margin-left: 10px; margin-bottom: 10px;'>")
                lines.append(f"<b>{c.character_name}</b> ({c.inconsistency_type})")
                if c.quote:
                    lines.append(f"<br/><i>\"{c.quote}\"</i>")
                if c.expected_behavior:
                    lines.append(f"<br/>Expected: {c.expected_behavior}")
                if c.suggestion:
                    lines.append(f"<br/><span style='color: #059669;'>💡 {c.suggestion}</span>")
                lines.append("</div>")
        else:
            lines.append("<p>✅ No character inconsistencies detected</p>")

        self.results_text.setHtml("\n".join(lines))


class SimilaritySearchDialog(QDialog):
    """Dialog for finding similar content using semantic search."""

    def __init__(self, search_text: str, project, parent=None):
        """Initialize similarity search dialog.

        Args:
            search_text: Text to find similar content for
            project: The writer project
            parent: Parent widget
        """
        super().__init__(parent)
        self.search_text = search_text
        self.project = project
        self.rag_system = None
        self._init_ui()
        self._run_search()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Find Similar Content")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)

        layout = QVBoxLayout(self)

        # Header
        header = QLabel("<h3>Finding Similar Content</h3>")
        layout.addWidget(header)

        # Search text display
        search_frame = QGroupBox("Search Text")
        search_layout = QVBoxLayout(search_frame)
        search_label = QLabel(self.search_text[:500] + ("..." if len(self.search_text) > 500 else ""))
        search_label.setWordWrap(True)
        search_label.setStyleSheet("font-style: italic; color: #4b5563;")
        search_layout.addWidget(search_label)
        layout.addWidget(search_frame)

        # Results area
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setPlaceholderText("Searching...")
        layout.addWidget(self.results_text, stretch=1)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _run_search(self):
        """Run the similarity search."""
        try:
            from src.ai.enhanced_rag import EnhancedRAGSystem
            from src.ai.semantic_search import SearchMethod

            # Initialize RAG system
            self.rag_system = EnhancedRAGSystem(self.project)
            self.rag_system.rebuild_index()

            # Find similar content
            results = self.rag_system.find_similar(
                self.search_text,
                top_k=10,
                method=SearchMethod.HYBRID
            )

            self._display_results(results)

        except Exception as e:
            self.results_text.setPlainText(f"Error during search: {str(e)}")

    def _display_results(self, results):
        """Display search results."""
        if not results:
            self.results_text.setHtml(
                "<p>No similar content found in your project.</p>"
                "<p style='color: #6b7280;'>Try adding more content to your "
                "worldbuilding, characters, or plot sections.</p>"
            )
            return

        lines = [f"<p>Found {len(results)} similar items:</p><hr/>"]

        for i, result in enumerate(results, 1):
            score_pct = int(result.relevance_score * 100)
            type_icon = self._get_type_icon(result.source_type)

            lines.append(f"<div style='margin-bottom: 15px; padding: 10px; background-color: #f9fafb; border-radius: 6px;'>")
            lines.append(f"<h4>{type_icon} {result.source_name}</h4>")
            lines.append(f"<p style='color: #6b7280; font-size: 11px;'>"
                        f"Type: {result.source_type.replace('_', ' ').title()} | "
                        f"Match: {score_pct}% | Method: {result.match_type}</p>")

            # Show matched terms if available
            if result.matched_terms:
                terms = ", ".join(result.matched_terms[:5])
                lines.append(f"<p style='color: #059669; font-size: 11px;'>Matched: {terms}</p>")

            # Show content preview
            content_preview = result.content[:400]
            if len(result.content) > 400:
                content_preview += "..."
            lines.append(f"<p>{content_preview}</p>")
            lines.append("</div>")

        self.results_text.setHtml("\n".join(lines))

    def _get_type_icon(self, source_type: str) -> str:
        """Get icon for source type."""
        icons = {
            "character": "👤",
            "faction": "⚔️",
            "place": "🗺️",
            "technology": "🔬",
            "culture": "🎭",
            "historical_event": "📜",
            "flora": "🌿",
            "fauna": "🦁",
            "myth": "📖",
            "star_system": "⭐",
            "military": "🎖️",
            "economy": "💰",
            "political_system": "🏛️",
            "plot": "📊",
            "plot_event": "📍",
            "subplot": "🔀",
            "promise": "🤝",
            "worldbuilding": "🌍",
            "chapter_key_point": "📝",
            "themes": "🎨"
        }
        return icons.get(source_type, "📄")


class AdvancedSearchDialog(QDialog):
    """Advanced search dialog with filters and options."""

    def __init__(self, project, parent=None):
        """Initialize advanced search dialog.

        Args:
            project: The writer project
            parent: Parent widget
        """
        super().__init__(parent)
        self.project = project
        self.rag_system = None
        self._init_ui()
        self._init_rag()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Advanced Project Search")
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)

        layout = QVBoxLayout(self)

        # Search input
        search_layout = QHBoxLayout()

        self.search_input = QTextEdit()
        self.search_input.setPlaceholderText("Enter search query...")
        self.search_input.setMaximumHeight(80)
        search_layout.addWidget(self.search_input, stretch=1)

        search_btn = QPushButton("🔍 Search")
        search_btn.clicked.connect(self._run_search)
        search_btn.setMinimumHeight(60)
        search_layout.addWidget(search_btn)

        layout.addLayout(search_layout)

        # Filters
        filter_group = QGroupBox("Filter by Type")
        filter_layout = QHBoxLayout(filter_group)

        self.type_checkboxes = {}
        types = [
            ("character", "Characters"),
            ("faction", "Factions"),
            ("place", "Places"),
            ("technology", "Technologies"),
            ("culture", "Cultures"),
            ("historical_event", "History"),
            ("flora", "Flora"),
            ("fauna", "Fauna"),
            ("plot", "Plot"),
            ("promise", "Promises"),
            ("worldbuilding", "Worldbuilding")
        ]

        for type_id, type_name in types:
            cb = QCheckBox(type_name)
            cb.setChecked(True)
            self.type_checkboxes[type_id] = cb
            filter_layout.addWidget(cb)

        layout.addWidget(filter_group)

        # Search method
        method_layout = QHBoxLayout()
        method_layout.addWidget(QLabel("Search Method:"))

        from PyQt6.QtWidgets import QComboBox
        self.method_combo = QComboBox()
        self.method_combo.addItem("Hybrid (Recommended)", "hybrid")
        self.method_combo.addItem("TF-IDF (Keyword-based)", "tfidf")
        self.method_combo.addItem("Semantic (AI Embeddings)", "embedding")
        method_layout.addWidget(self.method_combo)

        method_layout.addStretch()

        # Result count
        method_layout.addWidget(QLabel("Max Results:"))
        self.max_results_spin = QSpinBox()
        self.max_results_spin.setRange(5, 50)
        self.max_results_spin.setValue(15)
        method_layout.addWidget(self.max_results_spin)

        layout.addLayout(method_layout)

        # Results
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setPlaceholderText("Enter a search query and click Search...")
        layout.addWidget(self.results_text, stretch=1)

        # Stats
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(self.stats_label)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _init_rag(self):
        """Initialize RAG system."""
        try:
            from src.ai.enhanced_rag import EnhancedRAGSystem

            self.rag_system = EnhancedRAGSystem(self.project)
            self.rag_system.rebuild_index()

            # Show stats
            stats = self.rag_system.get_stats()
            self.stats_label.setText(
                f"Indexed: {stats['total_documents']} documents | "
                f"Vocabulary: {stats['vocab_size']} terms"
            )

        except Exception as e:
            self.stats_label.setText(f"Error initializing search: {e}")

    def _run_search(self):
        """Run the search."""
        query = self.search_input.toPlainText().strip()
        if not query:
            return

        if not self.rag_system:
            self.results_text.setPlainText("Search system not initialized.")
            return

        try:
            from src.ai.semantic_search import SearchMethod

            # Get selected types
            selected_types = [
                type_id for type_id, cb in self.type_checkboxes.items()
                if cb.isChecked()
            ]

            # Get method
            method_map = {
                "hybrid": SearchMethod.HYBRID,
                "tfidf": SearchMethod.TFIDF,
                "embedding": SearchMethod.EMBEDDING
            }
            method = method_map.get(
                self.method_combo.currentData(),
                SearchMethod.HYBRID
            )

            # Run search
            results = self.rag_system.search(
                query=query,
                method=method,
                top_k=self.max_results_spin.value(),
                source_types=selected_types if selected_types else None
            )

            self._display_results(results, query)

        except Exception as e:
            self.results_text.setPlainText(f"Search error: {str(e)}")

    def _display_results(self, results, query: str):
        """Display search results."""
        if not results:
            self.results_text.setHtml(
                f"<p>No results found for: <b>{query}</b></p>"
            )
            return

        lines = [f"<h3>Results for: {query}</h3>", f"<p>Found {len(results)} matches</p><hr/>"]

        type_icons = {
            "character": "👤", "faction": "⚔️", "place": "🗺️",
            "technology": "🔬", "culture": "🎭", "historical_event": "📜",
            "flora": "🌿", "fauna": "🦁", "myth": "📖", "star_system": "⭐",
            "military": "🎖️", "economy": "💰", "political_system": "🏛️",
            "plot": "📊", "plot_event": "📍", "subplot": "🔀",
            "promise": "🤝", "worldbuilding": "🌍", "chapter_key_point": "📝"
        }

        for result in results:
            icon = type_icons.get(result.source_type, "📄")
            score_pct = int(result.relevance_score * 100)

            lines.append(
                f"<div style='margin-bottom: 12px; padding: 10px; "
                f"background-color: #f9fafb; border-radius: 6px; border-left: 3px solid #6366f1;'>"
            )
            lines.append(f"<h4 style='margin: 0;'>{icon} {result.source_name}</h4>")
            lines.append(
                f"<p style='color: #6b7280; font-size: 11px; margin: 4px 0;'>"
                f"{result.source_type.replace('_', ' ').title()} | "
                f"Relevance: {score_pct}% | {result.match_type}</p>"
            )

            if result.matched_terms:
                terms = ", ".join(f"<b>{t}</b>" for t in result.matched_terms[:5])
                lines.append(f"<p style='color: #059669; font-size: 11px;'>Matched: {terms}</p>")

            # Content preview with query highlighting
            preview = result.content[:500]
            if len(result.content) > 500:
                preview += "..."

            # Simple highlighting of query terms
            for term in query.lower().split():
                if len(term) > 2:
                    import re
                    preview = re.sub(
                        f'({re.escape(term)})',
                        r'<mark>\1</mark>',
                        preview,
                        flags=re.IGNORECASE
                    )

            lines.append(f"<p style='margin-top: 8px;'>{preview}</p>")
            lines.append("</div>")

        self.results_text.setHtml("\n".join(lines))
