"""Manuscript editor with chapter navigation and revision system."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTextEdit, QToolBar, QComboBox, QSpinBox,
    QMessageBox, QInputDialog, QGroupBox, QSplitter, QFileDialog,
    QDialog, QMenu, QCheckBox, QLineEdit, QScrollArea, QFrame,
    QProgressBar, QRadioButton, QButtonGroup, QTabWidget
)
from PyQt6.QtCore import pyqtSignal, Qt, QRect, QSize
from PyQt6.QtGui import QFont, QTextCursor, QAction, QTextCharFormat, QColor, QPainter, QTextFormat
from typing import List, Optional
import uuid

from src.models.project import Manuscript, Chapter, Annotation, ChapterTodo, ChapterPlanning, StoryEvent
from src.ui.enhanced_text_editor import EnhancedTextEditor, CheckMode
from src.ui.annotations import AnnotationDialog
from src.ui.annotation_list_dialog import AnnotationListDialog
from src.ui.chapter_planner_widget import ChapterPlannerWidget
from src.ai.chapter_memory import ChapterMemoryManager
from src.utils.markdown_editor import MarkdownStyle, toggle_inline_style


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

        # Get viewport rect to determine visible area
        viewport_rect = self.editor.viewport().rect()

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

    def __init__(self, chapter: Chapter, project=None):
        """Initialize chapter editor."""
        super().__init__()
        self.chapter = chapter
        self.project = project
        self._llm_client = None
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

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)

        # Font family
        self.font_combo = QComboBox()
        self.font_combo.addItems(["Arial", "Times New Roman", "Courier New", "Georgia", "Verdana"])
        self.font_combo.currentTextChanged.connect(self._change_font_family)
        toolbar.addWidget(QLabel("Font: "))
        toolbar.addWidget(self.font_combo)

        # Font size
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 72)
        self.font_size_spin.setValue(12)
        # Block signals initially to prevent spurious valueChanged during initialization
        self.font_size_spin.blockSignals(True)
        self.font_size_spin.valueChanged.connect(self._change_font_size)
        self.font_size_spin.blockSignals(False)
        toolbar.addWidget(QLabel("Size: "))
        toolbar.addWidget(self.font_size_spin)

        toolbar.addSeparator()

        # Formatting buttons
        bold_action = QAction("Bold", self)
        bold_action.setShortcut("Ctrl+B")
        bold_action.triggered.connect(self._toggle_bold)
        toolbar.addAction(bold_action)

        italic_action = QAction("Italic", self)
        italic_action.setShortcut("Ctrl+I")
        italic_action.triggered.connect(self._toggle_italic)
        toolbar.addAction(italic_action)

        underline_action = QAction("Underline", self)
        underline_action.setShortcut("Ctrl+U")
        underline_action.triggered.connect(self._toggle_underline)
        toolbar.addAction(underline_action)

        toolbar.addSeparator()

        # Heading style dropdown
        toolbar.addWidget(QLabel("Style: "))
        self.heading_combo = QComboBox()
        self.heading_combo.addItems(["Normal", "Title", "Heading 1", "Heading 2", "Heading 3", "Heading 4"])
        self.heading_combo.setToolTip("Apply heading style (exports properly to Word, HTML, Markdown)")
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

        # Recheck button
        self.recheck_btn = QPushButton("🔄 Recheck")
        self.recheck_btn.setToolTip("Rerun all on-demand checks on this chapter")
        self.recheck_btn.clicked.connect(self._recheck_writing)
        toolbar.addWidget(self.recheck_btn)

        toolbar.addSeparator()

        # AI Rephrase action
        rephrase_action = QAction("Rephrase", self)
        rephrase_action.setShortcut("Ctrl+R")
        rephrase_action.setToolTip("Rephrase selected text using AI (Ctrl+R)")
        rephrase_action.triggered.connect(self._rephrase_selection)
        toolbar.addAction(rephrase_action)

        toolbar.addSeparator()

        # Annotation actions
        annotation_action = QAction("📝 Add Note", self)
        annotation_action.setShortcut("Ctrl+Shift+N")
        annotation_action.triggered.connect(lambda: self._add_annotation())
        annotation_action.setToolTip("Add annotation at current line (Ctrl+Shift+N)")
        toolbar.addAction(annotation_action)

        view_annotations_action = QAction("📋 View All", self)
        view_annotations_action.triggered.connect(self._view_annotations_list)
        view_annotations_action.setToolTip("View all annotations")
        toolbar.addAction(view_annotations_action)

        toolbar.addSeparator()

        # Text-to-Speech actions
        self.tts_speak_btn = QPushButton("🔊 Read")
        self.tts_speak_btn.setToolTip("Read chapter aloud (or selection if text is selected)")
        self.tts_speak_btn.clicked.connect(self._tts_speak_chapter)
        toolbar.addWidget(self.tts_speak_btn)

        self.tts_stop_btn = QPushButton("⏹ Stop")
        self.tts_stop_btn.setToolTip("Stop reading")
        self.tts_stop_btn.clicked.connect(self._tts_stop)
        toolbar.addWidget(self.tts_stop_btn)

        self.tts_generate_btn = QPushButton("🎙 Generate TTS")
        self.tts_generate_btn.setToolTip("Generate TTS document for this chapter with voice configuration")
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

        # Bottom toolbar
        bottom_toolbar = QHBoxLayout()

        # Word count
        self.word_count_label = QLabel("Words: 0")
        bottom_toolbar.addWidget(self.word_count_label)

        bottom_toolbar.addStretch()

        # Import from Word button
        import_word_button = QPushButton("Import from Word")
        import_word_button.clicked.connect(self._import_from_word)
        bottom_toolbar.addWidget(import_word_button)

        # Export to Word button
        export_word_button = QPushButton("Export to Word")
        export_word_button.clicked.connect(self._export_to_word)
        bottom_toolbar.addWidget(export_word_button)

        # AI Hints button
        hints_button = QPushButton("Get AI Hints")
        hints_button.clicked.connect(self._request_ai_hints)
        bottom_toolbar.addWidget(hints_button)

        # Check Promises button (AI)
        check_promises_button = QPushButton("Check Promises")
        check_promises_button.setToolTip("Check chapter against story promises and character consistency")
        check_promises_button.clicked.connect(self._check_promises)
        bottom_toolbar.addWidget(check_promises_button)

        # Save revision button
        save_revision_button = QPushButton("Save Revision")
        save_revision_button.clicked.connect(self._save_revision)
        bottom_toolbar.addWidget(save_revision_button)

        # View revisions button
        view_revisions_button = QPushButton("View Revisions")
        view_revisions_button.clicked.connect(self._view_revisions)
        bottom_toolbar.addWidget(view_revisions_button)

        # Toggle planner button - make it stand out
        self.toggle_planner_btn = QPushButton("📋 Plan Chapter")
        self.toggle_planner_btn.setCheckable(True)
        self.toggle_planner_btn.setToolTip("Show/hide chapter planner panel - plan your chapter before writing")
        self.toggle_planner_btn.setStyleSheet("""
            QPushButton {
                background-color: #8b5cf6;
                color: white;
                font-weight: bold;
                padding: 5px 15px;
                border-radius: 4px;
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
        """Get context for the planner AI assistant."""
        context = {
            'chapter_title': self.chapter.title,
            'plot': '',
            'worldbuilding': '',
            'characters': ''
        }

        if self.project:
            # Get plot outline
            if hasattr(self.project, 'story_planning') and self.project.story_planning:
                plot_parts = []
                if self.project.story_planning.get('premise'):
                    plot_parts.append(f"Premise: {self.project.story_planning['premise']}")
                if self.project.story_planning.get('themes'):
                    plot_parts.append(f"Themes: {', '.join(self.project.story_planning['themes'])}")
                if self.project.story_planning.get('outline'):
                    plot_parts.append(f"Outline: {self.project.story_planning['outline']}")
                context['plot'] = '\n'.join(plot_parts)

            # Get worldbuilding summary
            if hasattr(self.project, 'worldbuilding') and self.project.worldbuilding:
                wb_parts = []
                if self.project.worldbuilding.get('setting'):
                    wb_parts.append(f"Setting: {self.project.worldbuilding['setting']}")
                if self.project.worldbuilding.get('magic_system'):
                    wb_parts.append(f"Magic/Technology: {self.project.worldbuilding['magic_system']}")
                context['worldbuilding'] = '\n'.join(wb_parts)

            # Get characters summary
            if hasattr(self.project, 'characters') and self.project.characters:
                char_parts = []
                for char in self.project.characters[:10]:  # Limit to first 10 characters
                    if isinstance(char, dict):
                        name = char.get('name', 'Unknown')
                        role = char.get('role', '')
                        char_parts.append(f"- {name}: {role}")
                context['characters'] = '\n'.join(char_parts)

        return context

    def _init_ai(self):
        """Initialize AI client for the planner."""
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

                # Set up the AI handler for the planner
                self.planner_widget.set_ai_handler(self._handle_planner_ai_request)

        except Exception as e:
            print(f"Failed to initialize AI for planner: {e}")
            self._llm_client = None

    def _handle_planner_ai_request(self, prompt: str, model_name: str) -> str:
        """Handle AI requests from the planner widget.

        Args:
            prompt: The full prompt including context
            model_name: Selected model name from dropdown (for future use)

        Returns:
            AI response text or empty string on error
        """
        if not self._llm_client:
            return "AI not configured. Please set up API keys in Settings."

        try:
            response = self._llm_client.generate(prompt)
            return response
        except Exception as e:
            print(f"AI request error: {e}")
            return f"Error: {str(e)}"

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
            rephrase_action = menu.addAction("Rephrase with AI...")
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
            "Save Revision",
            "Enter revision notes (optional):"
        )

        if ok:
            self.save_to_model()
            self.chapter.add_revision(notes)
            QMessageBox.information(
                self,
                "Revision Saved",
                f"Revision #{len(self.chapter.revisions)} saved."
            )

    def _view_revisions(self):
        """View revision history."""
        if not self.chapter.revisions:
            QMessageBox.information(
                self,
                "No Revisions",
                "No revision history available for this chapter."
            )
            return

        # TODO: Create a proper revision viewer dialog
        revision_list = "\n".join([
            f"Revision {r.revision_number}: {r.timestamp.strftime('%Y-%m-%d %H:%M')} - {r.notes}"
            for r in self.chapter.revisions
        ])

        QMessageBox.information(
            self,
            "Revision History",
            revision_list
        )

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
        self.chapter.title = self.title_edit.toPlainText()
        # Save plain text content (contains Markdown formatting)
        self.chapter.content = self.editor.toPlainText()

        # Save planning data (separate from content, not exported)
        planning_data = self.planner_widget.get_planning_data()

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

        # Chapter buttons (simplified - just add and reorder)
        button_layout = QHBoxLayout()

        add_button = QPushButton("+ Add")
        add_button.setToolTip("Add new chapter at end")
        add_button.clicked.connect(self._add_chapter)
        button_layout.addWidget(add_button)

        move_up_button = QPushButton("Up")
        move_up_button.setToolTip("Move chapter up")
        move_up_button.clicked.connect(self._move_chapter_up)
        button_layout.addWidget(move_up_button)

        move_down_button = QPushButton("Down")
        move_down_button.setToolTip("Move chapter down")
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
        rename_action = menu.addAction("✏️ Rename")
        rename_action.triggered.connect(self._rename_chapter)

        # Insert before action
        insert_action = menu.addAction("📄 Insert Before")
        insert_action.triggered.connect(self._insert_chapter)

        menu.addSeparator()

        # Delete action
        delete_action = menu.addAction("🗑️ Delete")
        delete_action.triggered.connect(self._remove_chapter)

        menu.exec(self.chapter_list.mapToGlobal(position))

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
        """Remove selected chapter."""
        current_item = self.chapter_list.currentItem()
        if not current_item:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete '{current_item.text()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            chapter_id = current_item.data(Qt.ItemDataRole.UserRole)
            self.manuscript.chapters = [
                c for c in self.manuscript.chapters if c.id != chapter_id
            ]

            row = self.chapter_list.row(current_item)
            self.chapter_list.takeItem(row)

            self._renumber_chapters()
            self._clear_editor()
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
