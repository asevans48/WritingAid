"""Grader widget for comprehensive manuscript critique with AI integration."""

import json
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QTextEdit, QComboBox, QGroupBox,
    QMessageBox, QCheckBox, QLineEdit, QProgressBar,
    QScrollArea, QFileDialog
)
from PyQt6.QtCore import pyqtSignal, QThread, Qt

from src.ai.chapter_analysis_agent import (
    ChapterAnalysisAgent, ChapterAnalysis, CritiqueContext,
    SuggestionType, LineItemSuggestion
)
from src.config.ai_config import get_ai_config
from src.ui.enhanced_text_editor import ProWritingAnalyzer, WritingStats

if TYPE_CHECKING:
    from src.models.project import WriterProject


class CritiqueMetadataStore:
    """Persistent storage for critique context metadata per chapter.

    Stores metadata in ~/.writer_platform/critique_metadata.json
    Keyed by a hash of project path + chapter title for uniqueness.
    """

    def __init__(self):
        """Initialize metadata store."""
        self.config_dir = Path.home() / ".writer_platform"
        self.metadata_file = self.config_dir / "critique_metadata.json"
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        """Load metadata from disk."""
        if not self.metadata_file.exists():
            self._metadata = {}
            return

        try:
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                self._metadata = json.load(f)
        except Exception as e:
            print(f"Error loading critique metadata: {e}")
            self._metadata = {}

    def _save(self):
        """Save metadata to disk."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self._metadata, f, indent=2)
        except Exception as e:
            print(f"Error saving critique metadata: {e}")

    def _get_key(self, project_path: str, chapter_title: str) -> str:
        """Generate a unique key for a chapter.

        Uses hash of project path + chapter title to create a stable key
        that persists across sessions.
        """
        # Use project path + chapter title for uniqueness
        key_source = f"{project_path}::{chapter_title}"
        return hashlib.sha256(key_source.encode()).hexdigest()[:16]

    def get_context(self, project_path: str, chapter_title: str) -> Optional[Dict[str, Any]]:
        """Get saved critique context for a chapter.

        Args:
            project_path: Path to the project file
            chapter_title: Title of the chapter

        Returns:
            Dictionary with context fields or None if not found
        """
        key = self._get_key(project_path, chapter_title)
        return self._metadata.get(key)

    def save_context(
        self,
        project_path: str,
        chapter_title: str,
        context: Dict[str, Any]
    ):
        """Save critique context for a chapter.

        Args:
            project_path: Path to the project file
            chapter_title: Title of the chapter
            context: Dictionary with style, tone, voice, plot_goals,
                    characters, worldbuilding, additional_instructions
        """
        key = self._get_key(project_path, chapter_title)

        # Store with metadata for debugging/display
        self._metadata[key] = {
            "project_path": project_path,
            "chapter_title": chapter_title,
            "context": context
        }
        self._save()

    def delete_context(self, project_path: str, chapter_title: str):
        """Delete saved context for a chapter."""
        key = self._get_key(project_path, chapter_title)
        if key in self._metadata:
            del self._metadata[key]
            self._save()

    def get_all_for_project(self, project_path: str) -> Dict[str, Dict[str, Any]]:
        """Get all saved contexts for a project.

        Returns:
            Dictionary mapping chapter titles to their contexts
        """
        result = {}
        for key, data in self._metadata.items():
            if data.get("project_path") == project_path:
                chapter_title = data.get("chapter_title", "Unknown")
                result[chapter_title] = data.get("context", {})
        return result


# Global instance
_critique_metadata_store: Optional[CritiqueMetadataStore] = None


def get_critique_metadata_store() -> CritiqueMetadataStore:
    """Get global critique metadata store instance."""
    global _critique_metadata_store
    if _critique_metadata_store is None:
        _critique_metadata_store = CritiqueMetadataStore()
    return _critique_metadata_store


class CritiqueWorker(QThread):
    """Background worker for critique operation."""
    finished = pyqtSignal(object)  # ChapterAnalysis or dict with line_suggestions
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        text: str,
        title: str,
        critique_context: Optional[CritiqueContext],
        focus_areas: Optional[List[SuggestionType]],
        detailed: bool = True,
        line_by_line: bool = False
    ):
        super().__init__()
        self.text = text
        self.title = title
        self.critique_context = critique_context
        self.focus_areas = focus_areas
        self.detailed = detailed
        self.line_by_line = line_by_line

    def run(self):
        """Run critique analysis."""
        try:
            self.progress.emit("Initializing critique model...")

            # Get LLM client based on settings
            from src.ai.llm_client import LLMClient, LLMProvider
            ai_config = get_ai_config()
            critique_settings = ai_config.get_critique_model_settings()

            # Determine which LLM to use
            source = critique_settings.get("source", "default")

            if source == "local":
                # Use specific local model
                local_model_id = critique_settings.get("local_model_id", "")
                if local_model_id:
                    llm = LLMClient(provider=LLMProvider.HUGGINGFACE_LOCAL)
                else:
                    llm = self._get_default_llm(ai_config)
            elif source == "cloud":
                # Use specific cloud provider
                provider = critique_settings.get("cloud_provider", "claude")
                provider_map = {
                    "claude": LLMProvider.CLAUDE,
                    "chatgpt": LLMProvider.CHATGPT,
                    "gemini": LLMProvider.GEMINI
                }
                llm = LLMClient(provider=provider_map.get(provider, LLMProvider.CLAUDE))
            else:
                # Use default
                llm = self._get_default_llm(ai_config)

            # Create agent
            agent = ChapterAnalysisAgent(primary_llm=llm)

            if self.line_by_line:
                # Line-by-line analysis mode
                self.progress.emit("Analyzing text line by line...")
                line_suggestions = agent.analyze_lines(
                    text=self.text,
                    critique_context=self.critique_context
                )
                self.progress.emit("Complete!")
                # Return as dict to distinguish from ChapterAnalysis
                self.finished.emit({
                    "type": "line_by_line",
                    "suggestions": line_suggestions
                })
            else:
                # Standard chapter analysis
                self.progress.emit("Analyzing text...")
                self.progress.emit("Generating critique...")
                analysis = agent.analyze_chapter(
                    chapter_text=self.text,
                    chapter_title=self.title,
                    detailed=self.detailed,
                    critique_context=self.critique_context,
                    focus_areas=self.focus_areas
                )
                self.progress.emit("Complete!")
                self.finished.emit(analysis)

        except Exception as e:
            self.error.emit(str(e))

    def _get_default_llm(self, ai_config):
        """Get the default LLM based on settings."""
        from src.ai.llm_client import LLMClient, LLMProvider

        settings = ai_config.get_settings()

        # Check if local models preferred
        if settings.get("prefer_local_model", False) and settings.get("enable_local_models", False):
            return LLMClient(provider=LLMProvider.HUGGINGFACE_LOCAL)

        # Use default cloud provider
        default_provider = settings.get("default_llm", "claude")
        provider_map = {
            "claude": LLMProvider.CLAUDE,
            "chatgpt": LLMProvider.CHATGPT,
            "openai": LLMProvider.CHATGPT,
            "gemini": LLMProvider.GEMINI
        }
        return LLMClient(provider=provider_map.get(default_provider, LLMProvider.CLAUDE))


class GraderWidget(QWidget):
    """Widget for comprehensive manuscript and chapter critique."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize grader widget."""
        super().__init__()
        self.project: Optional['WriterProject'] = None
        self._project_path: str = ""
        self._current_chapter_text = ""
        self._current_chapter_title = ""
        self._worker: Optional[CritiqueWorker] = None
        self._last_analysis: Optional[ChapterAnalysis] = None
        self._last_stats: Optional[WritingStats] = None
        self._metadata_store = get_critique_metadata_store()
        self._init_ui()

    def _init_ui(self):
        """Initialize user interface."""
        # Main scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Header
        header = QLabel("Writing Critique & Feedback")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 5px;")
        layout.addWidget(header)

        description = QLabel(
            "Get comprehensive feedback on your writing with line-item suggestions "
            "for style, tone, plot, characters, worldbuilding, and more."
        )
        description.setWordWrap(True)
        description.setStyleSheet("padding: 5px; color: #666;")
        layout.addWidget(description)

        # Content Selection
        content_group = QGroupBox("Content to Critique")
        content_layout = QVBoxLayout()

        # Content type
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Content:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Current Chapter", "Custom Text"])
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        type_layout.addWidget(self.type_combo)
        type_layout.addStretch()
        content_layout.addLayout(type_layout)

        # Current chapter info
        self.chapter_info_label = QLabel("No chapter selected")
        self.chapter_info_label.setStyleSheet("color: #666; font-style: italic; padding: 5px;")
        content_layout.addWidget(self.chapter_info_label)

        # Custom text input
        self.custom_text_edit = QTextEdit()
        self.custom_text_edit.setPlaceholderText("Paste text to critique here...")
        self.custom_text_edit.setMaximumHeight(150)
        self.custom_text_edit.setVisible(False)
        content_layout.addWidget(self.custom_text_edit)

        content_group.setLayout(content_layout)
        layout.addWidget(content_group)

        # Focus Areas (checkboxes)
        focus_group = QGroupBox("Focus Areas (select what to prioritize)")
        focus_layout = QGridLayout()

        self.focus_checkboxes = {}
        focus_items = [
            (SuggestionType.SHOW_DONT_TELL, "Show Don't Tell"),
            (SuggestionType.PACING, "Pacing"),
            (SuggestionType.DIALOGUE, "Dialogue"),
            (SuggestionType.DESCRIPTION, "Description"),
            (SuggestionType.CHARACTER_VOICE, "Character Voice"),
            (SuggestionType.PLOT, "Plot"),
            (SuggestionType.WORLDBUILDING, "Worldbuilding"),
            (SuggestionType.STYLE, "Style"),
            (SuggestionType.TONE, "Tone"),
            (SuggestionType.VOICE, "Voice"),
            (SuggestionType.TENSION, "Tension"),
            (SuggestionType.CLARITY, "Clarity"),
        ]

        for i, (stype, label) in enumerate(focus_items):
            cb = QCheckBox(label)
            cb.setChecked(True)  # Default all checked
            self.focus_checkboxes[stype] = cb
            focus_layout.addWidget(cb, i // 4, i % 4)

        focus_group.setLayout(focus_layout)
        layout.addWidget(focus_group)

        # Writing Context
        context_group = QGroupBox("Writing Context (helps AI understand your intent)")
        context_layout = QVBoxLayout()

        # Style
        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Style/Genre:"))
        self.style_edit = QLineEdit()
        self.style_edit.setPlaceholderText("e.g., literary fiction, hard-boiled noir, epic fantasy...")
        style_row.addWidget(self.style_edit)
        context_layout.addLayout(style_row)

        # Tone
        tone_row = QHBoxLayout()
        tone_row.addWidget(QLabel("Tone:"))
        self.tone_edit = QLineEdit()
        self.tone_edit.setPlaceholderText("e.g., dark and brooding, hopeful, tense...")
        tone_row.addWidget(self.tone_edit)
        context_layout.addLayout(tone_row)

        # Voice
        voice_row = QHBoxLayout()
        voice_row.addWidget(QLabel("Voice:"))
        self.voice_edit = QLineEdit()
        self.voice_edit.setPlaceholderText("e.g., first-person unreliable narrator, omniscient...")
        voice_row.addWidget(self.voice_edit)
        context_layout.addLayout(voice_row)

        # Plot goals
        context_layout.addWidget(QLabel("Plot Goals (what should this section accomplish):"))
        self.plot_edit = QTextEdit()
        self.plot_edit.setMaximumHeight(60)
        self.plot_edit.setPlaceholderText("e.g., introduce the antagonist, build tension before the climax...")
        context_layout.addWidget(self.plot_edit)

        # Characters
        context_layout.addWidget(QLabel("Key Characters:"))
        self.characters_edit = QTextEdit()
        self.characters_edit.setMaximumHeight(60)
        self.characters_edit.setPlaceholderText("e.g., Maya (protagonist, guarded), Jake (mentor, wise)...")
        context_layout.addWidget(self.characters_edit)

        # Worldbuilding
        context_layout.addWidget(QLabel("Worldbuilding Notes:"))
        self.worldbuilding_edit = QTextEdit()
        self.worldbuilding_edit.setMaximumHeight(60)
        self.worldbuilding_edit.setPlaceholderText("e.g., magic system rules, cultural norms...")
        context_layout.addWidget(self.worldbuilding_edit)

        # Additional instructions
        context_layout.addWidget(QLabel("Additional Instructions:"))
        self.additional_edit = QTextEdit()
        self.additional_edit.setMaximumHeight(60)
        self.additional_edit.setPlaceholderText("Any specific things to look for or ignore...")
        context_layout.addWidget(self.additional_edit)

        # Save/Load context buttons
        context_buttons_layout = QHBoxLayout()
        context_buttons_layout.addStretch()

        self.save_context_btn = QPushButton("Save Context")
        self.save_context_btn.setToolTip("Save this context for the current chapter (persists across sessions)")
        self.save_context_btn.clicked.connect(self._save_chapter_context)
        self.save_context_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                padding: 5px 15px;
                border-radius: 3px;
            }
            QPushButton:hover { background-color: #2563eb; }
            QPushButton:disabled { background-color: #9ca3af; }
        """)
        context_buttons_layout.addWidget(self.save_context_btn)

        self.clear_context_btn = QPushButton("Clear")
        self.clear_context_btn.setToolTip("Clear all context fields")
        self.clear_context_btn.clicked.connect(self._clear_context_fields)
        context_buttons_layout.addWidget(self.clear_context_btn)

        self.context_status_label = QLabel("")
        self.context_status_label.setStyleSheet("color: #059669; font-size: 11px;")
        context_buttons_layout.addWidget(self.context_status_label)

        context_layout.addLayout(context_buttons_layout)

        context_group.setLayout(context_layout)
        layout.addWidget(context_group)

        # Critique Options
        options_layout = QHBoxLayout()

        self.detailed_check = QCheckBox("Detailed Analysis")
        self.detailed_check.setChecked(True)
        self.detailed_check.setToolTip("Detailed analysis provides more line-item suggestions")
        options_layout.addWidget(self.detailed_check)

        options_layout.addStretch()

        # Quick Stats button (local analysis, no AI)
        self.quick_stats_btn = QPushButton("Quick Stats")
        self.quick_stats_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #9ca3af; }
        """)
        self.quick_stats_btn.setToolTip("Fast local analysis: readability, echoes, sticky sentences, adverbs, clichés (no AI)")
        self.quick_stats_btn.clicked.connect(self._get_quick_stats)
        options_layout.addWidget(self.quick_stats_btn)

        # Critique button
        self.critique_btn = QPushButton("Get AI Critique")
        self.critique_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #4f46e5; }
            QPushButton:disabled { background-color: #9ca3af; }
        """)
        self.critique_btn.clicked.connect(self._get_critique)
        options_layout.addWidget(self.critique_btn)

        # Line-by-Line Critique button
        self.line_by_line_btn = QPushButton("Line-by-Line")
        self.line_by_line_btn.setStyleSheet("""
            QPushButton {
                background-color: #8b5cf6;
                color: white;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #7c3aed; }
            QPushButton:disabled { background-color: #9ca3af; }
        """)
        self.line_by_line_btn.setToolTip(
            "Analyze each line individually, providing reasoning for suggested edits.\n"
            "Best for detailed revision work."
        )
        self.line_by_line_btn.clicked.connect(self._get_line_by_line_critique)
        options_layout.addWidget(self.line_by_line_btn)

        layout.addLayout(options_layout)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        # Results Section
        results_group = QGroupBox("Critique Results")
        results_layout = QVBoxLayout()

        self.results_display = QTextEdit()
        self.results_display.setReadOnly(True)
        self.results_display.setMinimumHeight(300)
        self.results_display.setPlaceholderText("Critique results will appear here...")
        results_layout.addWidget(self.results_display)

        # Export buttons
        export_layout = QHBoxLayout()
        export_layout.addStretch()

        self.export_btn = QPushButton("Export Critique")
        self.export_btn.clicked.connect(self._export_critique)
        self.export_btn.setEnabled(False)
        export_layout.addWidget(self.export_btn)

        results_layout.addLayout(export_layout)
        results_group.setLayout(results_layout)
        layout.addWidget(results_group)

        layout.addStretch()
        scroll.setWidget(container)

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def set_project(self, project: 'WriterProject'):
        """Set the project for accessing chapters."""
        self.project = project
        # Store project path for metadata storage
        if project and hasattr(project, 'file_path') and project.file_path:
            self._project_path = str(project.file_path)
        else:
            self._project_path = ""

    def set_current_chapter(self, text: str, title: str):
        """Set the current chapter content for critique."""
        # Save context for previous chapter if it had content
        # (Auto-save when switching chapters)
        if self._current_chapter_title and self._has_context_content():
            self._save_chapter_context(silent=True)

        self._current_chapter_text = text
        self._current_chapter_title = title
        word_count = len(text.split()) if text else 0
        self.chapter_info_label.setText(f"Chapter: {title} ({word_count:,} words)")

        # Load saved context for this chapter
        self._load_chapter_context()

    def _on_type_changed(self, content_type: str):
        """Handle content type change."""
        is_custom = content_type == "Custom Text"
        self.custom_text_edit.setVisible(is_custom)
        self.chapter_info_label.setVisible(not is_custom)

    def _get_critique(self):
        """Get AI critique of the content."""
        # Get content
        content_type = self.type_combo.currentText()

        if content_type == "Custom Text":
            text = self.custom_text_edit.toPlainText()
            title = "Custom Text"
            if not text.strip():
                QMessageBox.warning(self, "No Content", "Please enter text to critique.")
                return
        else:
            if not self._current_chapter_text:
                QMessageBox.warning(
                    self, "No Chapter",
                    "No chapter selected. Please select a chapter in the manuscript editor first."
                )
                return
            text = self._current_chapter_text
            title = self._current_chapter_title

        # Build critique context
        critique_context = CritiqueContext(
            style=self.style_edit.text().strip(),
            tone=self.tone_edit.text().strip(),
            voice=self.voice_edit.text().strip(),
            plot_goals=self.plot_edit.toPlainText().strip(),
            characters=self.characters_edit.toPlainText().strip(),
            worldbuilding=self.worldbuilding_edit.toPlainText().strip(),
            additional_instructions=self.additional_edit.toPlainText().strip()
        )

        # Get selected focus areas
        focus_areas = [
            stype for stype, cb in self.focus_checkboxes.items()
            if cb.isChecked()
        ]

        # Show progress
        self.progress_bar.setVisible(True)
        self.status_label.setVisible(True)
        self.critique_btn.setEnabled(False)

        # Start worker
        self._worker = CritiqueWorker(
            text=text,
            title=title,
            critique_context=critique_context,
            focus_areas=focus_areas if focus_areas else None,
            detailed=self.detailed_check.isChecked()
        )
        self._worker.finished.connect(self._on_critique_finished)
        self._worker.error.connect(self._on_critique_error)
        self._worker.progress.connect(self._on_critique_progress)
        self._worker.start()

    def _get_line_by_line_critique(self):
        """Get line-by-line AI critique with reasoning for each edit."""
        # Get content
        content_type = self.type_combo.currentText()

        if content_type == "Custom Text":
            text = self.custom_text_edit.toPlainText()
            title = "Custom Text"
            if not text.strip():
                QMessageBox.warning(self, "No Content", "Please enter text to critique.")
                return
        else:
            if not self._current_chapter_text:
                QMessageBox.warning(
                    self, "No Chapter",
                    "No chapter selected. Please select a chapter in the manuscript editor first."
                )
                return
            text = self._current_chapter_text
            title = self._current_chapter_title

        # Build critique context
        critique_context = CritiqueContext(
            style=self.style_edit.text().strip(),
            tone=self.tone_edit.text().strip(),
            voice=self.voice_edit.text().strip(),
            plot_goals=self.plot_edit.toPlainText().strip(),
            characters=self.characters_edit.toPlainText().strip(),
            worldbuilding=self.worldbuilding_edit.toPlainText().strip(),
            additional_instructions=self.additional_edit.toPlainText().strip()
        )

        # Show progress
        self.progress_bar.setVisible(True)
        self.status_label.setVisible(True)
        self.critique_btn.setEnabled(False)
        self.line_by_line_btn.setEnabled(False)

        # Start worker in line-by-line mode
        self._worker = CritiqueWorker(
            text=text,
            title=title,
            critique_context=critique_context,
            focus_areas=None,  # Line-by-line doesn't use focus areas
            detailed=True,
            line_by_line=True  # Enable line-by-line mode
        )
        self._worker.finished.connect(self._on_critique_finished)
        self._worker.error.connect(self._on_critique_error)
        self._worker.progress.connect(self._on_critique_progress)
        self._worker.start()

    def _on_critique_progress(self, message: str):
        """Handle progress updates."""
        self.status_label.setText(message)

    def _on_critique_finished(self, result):
        """Handle critique completion.

        Args:
            result: Either a ChapterAnalysis object or a dict with line-by-line results
        """
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)
        self.critique_btn.setEnabled(True)
        self.line_by_line_btn.setEnabled(True)

        # Check if this is a line-by-line result (dict) or standard analysis
        if isinstance(result, dict) and result.get("type") == "line_by_line":
            # Line-by-line results
            suggestions = result.get("suggestions", [])
            html = self._format_line_by_line_html(suggestions)
            self.results_display.setHtml(html)
            self.export_btn.setEnabled(True)
            self._last_analysis = None  # Clear standard analysis
        else:
            # Standard ChapterAnalysis
            self._last_analysis = result
            html = self._format_analysis_html(result)
            self.results_display.setHtml(html)
            self.export_btn.setEnabled(True)

    def _on_critique_error(self, error: str):
        """Handle critique error."""
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)
        self.critique_btn.setEnabled(True)
        self.line_by_line_btn.setEnabled(True)

        QMessageBox.critical(self, "Critique Failed", f"Failed to generate critique:\n\n{error}")

    def _format_analysis_html(self, analysis: ChapterAnalysis) -> str:
        """Format analysis results as HTML."""
        html = """
        <style>
            h2 { color: #1f2937; margin-top: 15px; margin-bottom: 8px; }
            h3 { color: #374151; margin-top: 12px; margin-bottom: 6px; }
            .strength { color: #059669; }
            .improvement { color: #dc2626; }
            .suggestion { background-color: #f3f4f6; padding: 10px; margin: 8px 0; border-radius: 4px; }
            .priority-high { border-left: 3px solid #dc2626; }
            .priority-medium { border-left: 3px solid #f59e0b; }
            .priority-low { border-left: 3px solid #6b7280; }
            .quote { color: #6b7280; font-style: italic; }
            .type { font-weight: bold; color: #6366f1; }
        </style>
        """

        # Overall Assessment
        html += f"<h2>Overall Assessment</h2><p>{analysis.overall_assessment}</p>"

        # Strengths
        if analysis.strengths:
            html += "<h2 class='strength'>Strengths</h2><ul>"
            for s in analysis.strengths:
                html += f"<li class='strength'>{s}</li>"
            html += "</ul>"

        # Areas for Improvement
        if analysis.areas_for_improvement:
            html += "<h2 class='improvement'>Areas for Improvement</h2><ul>"
            for a in analysis.areas_for_improvement:
                html += f"<li>{a}</li>"
            html += "</ul>"

        # Line-Item Suggestions
        if analysis.line_item_suggestions:
            html += "<h2>Line-Item Suggestions</h2>"
            for suggestion in analysis.line_item_suggestions:
                priority_class = f"priority-{suggestion.priority}"
                html += f"""
                <div class='suggestion {priority_class}'>
                    <span class='type'>[{suggestion.suggestion_type.value.replace('_', ' ').title()}]</span>
                    <span style='float: right; font-size: 11px;'>Priority: {suggestion.priority.upper()}</span><br>
                    <span class='quote'>"{suggestion.original_text}"</span><br>
                    <strong>Suggestion:</strong> {suggestion.suggestion}<br>
                    <em>Why:</em> {suggestion.explanation}
                </div>
                """

        # Pacing Notes
        if analysis.pacing_notes:
            html += f"<h2>Pacing Notes</h2><p>{analysis.pacing_notes}</p>"

        # Character Consistency
        if analysis.character_consistency_notes:
            html += f"<h2>Character Consistency</h2><p>{analysis.character_consistency_notes}</p>"

        # Cost estimate
        if analysis.estimated_cost > 0:
            html += f"<p style='color: #6b7280; font-size: 11px; margin-top: 20px;'>Estimated API cost: ${analysis.estimated_cost:.4f}</p>"

        return html

    def _format_line_by_line_html(self, suggestions: List[LineItemSuggestion]) -> str:
        """Format line-by-line suggestions as HTML.

        Args:
            suggestions: List of LineItemSuggestion objects from line-by-line analysis

        Returns:
            HTML formatted string for display
        """
        html = """
        <style>
            h2 { color: #1f2937; margin-top: 15px; margin-bottom: 8px; }
            .line-item { background-color: #f8fafc; padding: 12px; margin: 10px 0; border-radius: 6px; border: 1px solid #e2e8f0; }
            .line-number { display: inline-block; background-color: #8b5cf6; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; margin-right: 8px; }
            .issue-type { display: inline-block; background-color: #6366f1; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-left: 8px; }
            .priority-high { border-left: 4px solid #dc2626; }
            .priority-medium { border-left: 4px solid #f59e0b; }
            .priority-low { border-left: 4px solid #6b7280; }
            .original-text { color: #374151; font-style: italic; margin: 8px 0; padding: 8px; background-color: #fff; border-radius: 4px; border-left: 3px solid #d1d5db; }
            .reasoning { color: #4b5563; margin: 8px 0; }
            .reasoning-label { color: #7c3aed; font-weight: bold; }
            .suggestion-text { color: #059669; margin: 8px 0; }
            .suggestion-label { color: #059669; font-weight: bold; }
            .priority-tag { float: right; font-size: 11px; color: #6b7280; }
            .no-suggestions { color: #059669; padding: 20px; text-align: center; font-size: 16px; }
        </style>
        """

        if not suggestions:
            html += """
            <h2>Line-by-Line Analysis</h2>
            <div class='no-suggestions'>
                ✓ No lines flagged for revision. The text appears well-crafted for its intended style and purpose.
            </div>
            """
            return html

        html += f"<h2>Line-by-Line Analysis</h2>"
        html += f"<p style='color: #6b7280; font-size: 13px; margin-bottom: 15px;'>{len(suggestions)} line(s) flagged for potential revision</p>"

        for suggestion in suggestions:
            priority_class = f"priority-{suggestion.priority}"
            line_num_display = f"Line {suggestion.line_number}" if suggestion.line_number else "Section"

            # Get issue type display
            issue_type = suggestion.suggestion_type.value.replace('_', ' ').title()

            html += f"""
            <div class='line-item {priority_class}'>
                <span class='line-number'>{line_num_display}</span>
                <span class='issue-type'>{issue_type}</span>
                <span class='priority-tag'>Priority: {suggestion.priority.upper()}</span>

                <div class='original-text'>"{suggestion.original_text}"</div>

                <div class='reasoning'>
                    <span class='reasoning-label'>Why this line needs attention:</span><br>
                    {suggestion.reasoning if suggestion.reasoning else suggestion.explanation}
                </div>

                <div class='suggestion-text'>
                    <span class='suggestion-label'>Consider:</span> {suggestion.suggestion}
                </div>
            </div>
            """

        return html

    def _export_critique(self):
        """Export critique results to file."""
        if not self._last_analysis:
            QMessageBox.warning(self, "No Critique", "No critique to export.")
            return

        # Get save path
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Critique",
            f"critique_{self._current_chapter_title or 'custom'}.md",
            "Markdown (*.md);;Text (*.txt)"
        )

        if not file_path:
            return

        try:
            content = self._format_analysis_markdown(self._last_analysis)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            QMessageBox.information(self, "Export Complete", f"Critique exported to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Failed to export critique:\n{e}")

    def _format_analysis_markdown(self, analysis: ChapterAnalysis) -> str:
        """Format analysis as Markdown."""
        md = f"# Writing Critique\n\n"

        md += f"## Overall Assessment\n\n{analysis.overall_assessment}\n\n"

        if analysis.strengths:
            md += "## Strengths\n\n"
            for s in analysis.strengths:
                md += f"- {s}\n"
            md += "\n"

        if analysis.areas_for_improvement:
            md += "## Areas for Improvement\n\n"
            for a in analysis.areas_for_improvement:
                md += f"- {a}\n"
            md += "\n"

        if analysis.line_item_suggestions:
            md += "## Line-Item Suggestions\n\n"
            for suggestion in analysis.line_item_suggestions:
                md += f"### [{suggestion.suggestion_type.value.replace('_', ' ').title()}] - {suggestion.priority.upper()} priority\n\n"
                md += f"> \"{suggestion.original_text}\"\n\n"
                md += f"**Suggestion:** {suggestion.suggestion}\n\n"
                md += f"*Why:* {suggestion.explanation}\n\n"
                md += "---\n\n"

        if analysis.pacing_notes:
            md += f"## Pacing Notes\n\n{analysis.pacing_notes}\n\n"

        if analysis.character_consistency_notes:
            md += f"## Character Consistency\n\n{analysis.character_consistency_notes}\n\n"

        return md

    def _get_quick_stats(self):
        """Get quick local statistics (ProWritingAid-style analysis without AI)."""
        # Get content
        content_type = self.type_combo.currentText()

        if content_type == "Custom Text":
            text = self.custom_text_edit.toPlainText()
            if not text.strip():
                QMessageBox.warning(self, "No Content", "Please enter text to analyze.")
                return
        else:
            if not self._current_chapter_text:
                QMessageBox.warning(
                    self, "No Chapter",
                    "No chapter selected. Please select a chapter in the manuscript editor first."
                )
                return
            text = self._current_chapter_text

        # Run local analysis
        analyzer = ProWritingAnalyzer()
        stats = analyzer.analyze(text)

        # Format and display report
        html = """
        <style>
            h2 { color: #1f2937; margin-top: 15px; margin-bottom: 8px; }
        </style>
        <h2>📊 Writing Statistics Report</h2>
        <p style='color: #666;'>Local analysis - no AI required. Similar to ProWritingAid reports.</p>
        """
        html += analyzer.format_report(stats)

        self.results_display.setHtml(html)
        self.export_btn.setEnabled(True)

        # Store stats for potential export
        self._last_stats = stats

    # Context persistence methods

    def _has_context_content(self) -> bool:
        """Check if any context fields have content."""
        return bool(
            self.style_edit.text().strip() or
            self.tone_edit.text().strip() or
            self.voice_edit.text().strip() or
            self.plot_edit.toPlainText().strip() or
            self.characters_edit.toPlainText().strip() or
            self.worldbuilding_edit.toPlainText().strip() or
            self.additional_edit.toPlainText().strip()
        )

    def _get_context_dict(self) -> Dict[str, str]:
        """Get current context fields as a dictionary."""
        return {
            "style": self.style_edit.text().strip(),
            "tone": self.tone_edit.text().strip(),
            "voice": self.voice_edit.text().strip(),
            "plot_goals": self.plot_edit.toPlainText().strip(),
            "characters": self.characters_edit.toPlainText().strip(),
            "worldbuilding": self.worldbuilding_edit.toPlainText().strip(),
            "additional_instructions": self.additional_edit.toPlainText().strip(),
        }

    def _set_context_from_dict(self, context: Dict[str, str]):
        """Set context fields from a dictionary."""
        self.style_edit.setText(context.get("style", ""))
        self.tone_edit.setText(context.get("tone", ""))
        self.voice_edit.setText(context.get("voice", ""))
        self.plot_edit.setPlainText(context.get("plot_goals", ""))
        self.characters_edit.setPlainText(context.get("characters", ""))
        self.worldbuilding_edit.setPlainText(context.get("worldbuilding", ""))
        self.additional_edit.setPlainText(context.get("additional_instructions", ""))

    def _save_chapter_context(self, silent: bool = False):
        """Save the current context for the current chapter.

        Args:
            silent: If True, don't show status message (used for auto-save)
        """
        if not self._project_path:
            if not silent:
                QMessageBox.warning(
                    self, "No Project",
                    "Please save your project first before saving context metadata."
                )
            return

        if not self._current_chapter_title:
            if not silent:
                QMessageBox.warning(
                    self, "No Chapter",
                    "Please select a chapter first."
                )
            return

        context = self._get_context_dict()

        # Only save if there's actual content
        if not any(v for v in context.values()):
            if not silent:
                self.context_status_label.setText("Nothing to save")
            return

        self._metadata_store.save_context(
            self._project_path,
            self._current_chapter_title,
            context
        )

        if not silent:
            self.context_status_label.setText(f"✓ Saved for '{self._current_chapter_title}'")

    def _load_chapter_context(self):
        """Load saved context for the current chapter."""
        self.context_status_label.setText("")

        if not self._project_path or not self._current_chapter_title:
            return

        saved_data = self._metadata_store.get_context(
            self._project_path,
            self._current_chapter_title
        )

        if saved_data and "context" in saved_data:
            self._set_context_from_dict(saved_data["context"])
            self.context_status_label.setText("✓ Loaded saved context")
        else:
            # Clear fields if no saved context
            self._clear_context_fields(silent=True)

    def _clear_context_fields(self, silent: bool = False):
        """Clear all context input fields.

        Args:
            silent: If True, don't update status label
        """
        self.style_edit.clear()
        self.tone_edit.clear()
        self.voice_edit.clear()
        self.plot_edit.clear()
        self.characters_edit.clear()
        self.worldbuilding_edit.clear()
        self.additional_edit.clear()

        if not silent:
            self.context_status_label.setText("Cleared")

    def load_data(self, data):
        """Load grader data (placeholder for future use)."""

    def get_data(self):
        """Get grader data (placeholder for future use)."""
        return None
