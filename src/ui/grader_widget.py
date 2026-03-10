"""Grader widget for comprehensive manuscript critique with AI integration."""

import json
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QTextEdit, QTextBrowser, QComboBox, QGroupBox,
    QMessageBox, QCheckBox, QLineEdit, QProgressBar,
    QScrollArea, QFileDialog
)
from PyQt6.QtCore import pyqtSignal, QThread, Qt, QUrl

from src.ai.chapter_analysis_agent import (
    ChapterAnalysisAgent, ChapterAnalysis, CritiqueContext,
    SuggestionType, LineItemSuggestion
)
from src.config.ai_config import get_ai_config
from src.ai.craft_explanations import CRAFT_EXPLANATIONS
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
                if chapter_title != "__PROJECT_GLOBAL__":
                    result[chapter_title] = data.get("context", {})
        return result

    def get_project_context(self, project_path: str) -> Optional[Dict[str, Any]]:
        """Get saved project-wide critique context.

        Args:
            project_path: Path to the project file

        Returns:
            Dictionary with context fields or None if not found
        """
        return self.get_context(project_path, "__PROJECT_GLOBAL__")

    def save_project_context(self, project_path: str, context: Dict[str, Any]):
        """Save project-wide critique context.

        Args:
            project_path: Path to the project file
            context: Dictionary with style, tone, voice, etc.
        """
        self.save_context(project_path, "__PROJECT_GLOBAL__", context)

    def delete_project_context(self, project_path: str):
        """Delete saved project-wide context."""
        self.delete_context(project_path, "__PROJECT_GLOBAL__")

    # === Critique Results Storage ===

    def _get_critique_key(self, project_path: str, chapter_title: str) -> str:
        """Generate a unique key for critique results (separate from context)."""
        key_source = f"CRITIQUE::{project_path}::{chapter_title}"
        return hashlib.sha256(key_source.encode()).hexdigest()[:16]

    def save_critique(
        self,
        project_path: str,
        chapter_title: str,
        critique_data: Dict[str, Any],
        critique_type: str = "general"
    ) -> str:
        """Save critique results for a chapter.

        Args:
            project_path: Path to the project file
            chapter_title: Title of the chapter
            critique_data: Serialized critique data (analysis or line suggestions)
            critique_type: Type of critique ("general", "line_by_line", "quick_stats")

        Returns:
            The critique ID (timestamp-based)
        """
        from datetime import datetime

        key = self._get_critique_key(project_path, chapter_title)
        critique_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Get or create critique history for this chapter
        if key not in self._metadata:
            self._metadata[key] = {
                "project_path": project_path,
                "chapter_title": chapter_title,
                "critiques": {}
            }

        # Save critique with ID
        self._metadata[key]["critiques"][critique_id] = {
            "type": critique_type,
            "timestamp": datetime.now().isoformat(),
            "data": critique_data
        }

        # Keep only the last 10 critiques per chapter
        critiques = self._metadata[key]["critiques"]
        if len(critiques) > 10:
            sorted_ids = sorted(critiques.keys())
            for old_id in sorted_ids[:-10]:
                del critiques[old_id]

        self._save()
        return critique_id

    def get_critique(
        self,
        project_path: str,
        chapter_title: str,
        critique_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get a saved critique.

        Args:
            project_path: Path to the project file
            chapter_title: Title of the chapter
            critique_id: Specific critique ID, or None for the latest

        Returns:
            Critique data dict with type, timestamp, and data fields
        """
        key = self._get_critique_key(project_path, chapter_title)
        entry = self._metadata.get(key)

        if not entry or "critiques" not in entry:
            return None

        critiques = entry["critiques"]
        if not critiques:
            return None

        if critique_id:
            return critiques.get(critique_id)
        else:
            # Return the latest critique
            latest_id = max(critiques.keys())
            return critiques.get(latest_id)

    def list_critiques(
        self,
        project_path: str,
        chapter_title: str
    ) -> List[Dict[str, str]]:
        """List all saved critiques for a chapter.

        Returns:
            List of dicts with id, type, and timestamp
        """
        key = self._get_critique_key(project_path, chapter_title)
        entry = self._metadata.get(key)

        if not entry or "critiques" not in entry:
            return []

        result = []
        for cid, cdata in entry["critiques"].items():
            result.append({
                "id": cid,
                "type": cdata.get("type", "unknown"),
                "timestamp": cdata.get("timestamp", "")
            })

        # Sort by ID (which is timestamp-based) descending
        result.sort(key=lambda x: x["id"], reverse=True)
        return result

    def delete_critique(
        self,
        project_path: str,
        chapter_title: str,
        critique_id: str
    ):
        """Delete a specific critique."""
        key = self._get_critique_key(project_path, chapter_title)
        entry = self._metadata.get(key)

        if entry and "critiques" in entry and critique_id in entry["critiques"]:
            del entry["critiques"][critique_id]
            self._save()


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
        line_by_line: bool = False,
        manuscript_context: str = "",
        chapter_synopsis: str = ""
    ):
        super().__init__()
        self.text = text
        self.title = title
        self.critique_context = critique_context
        self.focus_areas = focus_areas
        self.detailed = detailed
        self.line_by_line = line_by_line
        self.manuscript_context = manuscript_context
        self.chapter_synopsis = chapter_synopsis

    def run(self):
        """Run critique analysis."""
        try:
            self.progress.emit("Initializing critique model...")

            # Get LLM client based on settings (same logic as ChatWorker)
            from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig
            ai_config = get_ai_config()
            settings = ai_config.get_settings()

            # Check if AI is disabled
            if ai_config.is_ai_disabled():
                self.error.emit("AI features are disabled. Enable them in Settings > AI Settings.")
                return

            # Check if local models are preferred and configured
            prefer_local = settings.get("prefer_local_model", False)
            enable_local = settings.get("enable_local_models", False)
            local_model_id = settings.get("local_model_id", "")

            if prefer_local and enable_local and local_model_id:
                # Use local model - detect if it's an MLX model
                is_mlx_model = "mlx" in local_model_id.lower()

                hf_config = HuggingFaceConfig(
                    model_id=local_model_id,
                    use_local=True,
                    device=settings.get("local_model_device", "auto"),
                    quantization=settings.get("local_model_quantization", "none") if settings.get("local_model_quantization") != "none" else None,
                    trust_remote_code=settings.get("local_model_trust_remote_code", False)
                )

                # Use MLX provider for MLX models, HuggingFace for others
                provider = LLMProvider.MLX_LOCAL if is_mlx_model else LLMProvider.HUGGINGFACE_LOCAL
                llm = LLMClient(
                    provider=provider,
                    hf_config=hf_config
                )
            else:
                # Use cloud provider
                default_provider = settings.get("default_llm", "claude")
                api_key = ai_config.get_api_key(default_provider)

                if not api_key:
                    self.error.emit(f"No API key configured for {default_provider}. Please add your API key in Settings > AI Settings, or enable local models.")
                    return

                # Map provider name to enum
                provider_map = {
                    "claude": LLMProvider.CLAUDE,
                    "chatgpt": LLMProvider.CHATGPT,
                    "openai": LLMProvider.CHATGPT,
                    "gemini": LLMProvider.GEMINI
                }
                llm = LLMClient(provider=provider_map.get(default_provider, LLMProvider.CLAUDE))

            # Create agent
            agent = ChapterAnalysisAgent(primary_llm=llm)

            if self.line_by_line:
                # Line-by-line analysis mode using two-stage approach
                # Pass progress callback to get detailed status updates
                def progress_update(msg: str):
                    self.progress.emit(msg)

                line_suggestions = agent.analyze_lines(
                    text=self.text,
                    critique_context=self.critique_context,
                    progress_callback=progress_update,
                    manuscript_context=self.manuscript_context,
                    chapter_synopsis=self.chapter_synopsis
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
                    focus_areas=self.focus_areas,
                    manuscript_context=self.manuscript_context,
                    chapter_synopsis=self.chapter_synopsis
                )
                self.progress.emit("Complete!")
                self.finished.emit(analysis)

        except Exception as e:
            self.error.emit(str(e))


class GraderWidget(QWidget):
    """Widget for comprehensive manuscript and chapter critique."""

    content_changed = pyqtSignal()
    go_to_line_requested = pyqtSignal(int)  # Emits line number to navigate to
    ask_about_suggestion = pyqtSignal(str, str, str, str)  # type, original_text, suggestion, explanation

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
        self._content_provider: Optional[callable] = None  # Callback to get fresh content
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

        # Context scope and save/load controls
        context_controls_layout = QHBoxLayout()

        # Context scope selector
        scope_label = QLabel("Save to:")
        scope_label.setStyleSheet("font-size: 11px;")
        context_controls_layout.addWidget(scope_label)

        self.context_scope_combo = QComboBox()
        self.context_scope_combo.addItem("This Chapter", "chapter")
        self.context_scope_combo.addItem("Entire Project", "project")
        self.context_scope_combo.setToolTip("Choose where to save/load context from")
        self.context_scope_combo.setStyleSheet("font-size: 11px; min-width: 100px;")
        self.context_scope_combo.currentIndexChanged.connect(self._on_context_scope_changed)
        context_controls_layout.addWidget(self.context_scope_combo)

        context_controls_layout.addStretch()

        # Import from chapter planner button
        self.import_planner_btn = QPushButton("Import from Planner")
        self.import_planner_btn.setToolTip("Import tone, voice, style from this chapter's planner")
        self.import_planner_btn.clicked.connect(self._import_from_chapter_planner)
        self.import_planner_btn.setStyleSheet("""
            QPushButton {
                background-color: #8b5cf6;
                color: white;
                padding: 5px 12px;
                border-radius: 3px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #7c3aed; }
        """)
        context_controls_layout.addWidget(self.import_planner_btn)

        self.save_context_btn = QPushButton("Save Context")
        self.save_context_btn.setToolTip("Save this context (persists across sessions)")
        self.save_context_btn.clicked.connect(self._save_context)
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
        context_controls_layout.addWidget(self.save_context_btn)

        self.load_context_btn = QPushButton("Load")
        self.load_context_btn.setToolTip("Load saved context")
        self.load_context_btn.clicked.connect(self._load_context)
        self.load_context_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: white;
                padding: 5px 12px;
                border-radius: 3px;
            }
            QPushButton:hover { background-color: #047857; }
        """)
        context_controls_layout.addWidget(self.load_context_btn)

        self.clear_context_btn = QPushButton("Clear")
        self.clear_context_btn.setToolTip("Clear all context fields")
        self.clear_context_btn.clicked.connect(self._clear_context_fields)
        context_controls_layout.addWidget(self.clear_context_btn)

        context_layout.addLayout(context_controls_layout)

        # Status label on its own row
        self.context_status_label = QLabel("")
        self.context_status_label.setStyleSheet("color: #059669; font-size: 11px;")
        context_layout.addWidget(self.context_status_label)

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

        self.results_display = QTextBrowser()
        self.results_display.setOpenExternalLinks(False)  # Handle links ourselves
        self.results_display.setOpenLinks(False)
        self.results_display.anchorClicked.connect(self._handle_link_click)
        self.results_display.setMinimumHeight(300)
        results_layout.addWidget(self.results_display)

        # Export and save/load buttons
        export_layout = QHBoxLayout()

        # Save/Load critique buttons on the left
        self.save_critique_btn = QPushButton("Save Critique")
        self.save_critique_btn.setToolTip("Save this critique to work on later")
        self.save_critique_btn.clicked.connect(self._save_critique_results)
        self.save_critique_btn.setEnabled(False)
        self.save_critique_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: 500;
            }
            QPushButton:hover { background-color: #2563eb; }
            QPushButton:disabled { background-color: #9ca3af; color: #e5e7eb; }
        """)
        export_layout.addWidget(self.save_critique_btn)

        self.load_critique_btn = QPushButton("Load Critique")
        self.load_critique_btn.setToolTip("Load a previously saved critique")
        self.load_critique_btn.clicked.connect(self._load_critique_results)
        self.load_critique_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: 500;
            }
            QPushButton:hover { background-color: #047857; }
        """)
        export_layout.addWidget(self.load_critique_btn)

        # Saved critique indicator
        self.saved_critique_label = QLabel("")
        self.saved_critique_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        export_layout.addWidget(self.saved_critique_label)

        export_layout.addStretch()

        self.export_btn = QPushButton("Export to File")
        self.export_btn.setToolTip("Export critique as markdown file")
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
        # WriterProject uses 'project_path' to store the path to project.json
        if project and hasattr(project, 'project_path') and project.project_path:
            self._project_path = str(project.project_path)
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

    def _build_manuscript_context(self) -> tuple:
        """Build manuscript_context string and chapter_synopsis from the current project.

        Returns:
            (manuscript_context, chapter_synopsis) — both strings, may be empty.
        """
        if not self.project:
            return "", ""

        context_parts = []
        chapter_synopsis = ""

        sp = self.project.story_planning
        if sp.main_plot:
            context_parts.append(f"Main Plot: {sp.main_plot[:400]}")
        if sp.themes:
            context_parts.append(f"Themes: {', '.join(sp.themes[:6])}")
        if sp.subplots:
            context_parts.append(f"Subplots: {', '.join(s.title for s in sp.subplots[:5])}")
        if hasattr(sp, 'promises') and sp.promises:
            lines = [f"- {p.title}: {p.description[:100]}" for p in sp.promises[:5]]
            context_parts.append("Story Promises:\n" + "\n".join(lines))

        if self.project.characters:
            char_lines = []
            for c in self.project.characters[:12]:
                line = f"- {c.name} ({c.character_type})"
                if c.personality:
                    line += f": {c.personality[:100]}"
                char_lines.append(line)
            context_parts.append("Characters:\n" + "\n".join(char_lines))

        if self.project.manuscript and self.project.manuscript.chapters:
            total = len(self.project.manuscript.chapters)
            for i, ch in enumerate(self.project.manuscript.chapters):
                if ch.title == self._current_chapter_title:
                    context_parts.append(f"Chapter {i + 1} of {total} in the manuscript")
                    if i > 0:
                        context_parts.append(
                            f"Previous chapter: \"{self.project.manuscript.chapters[i - 1].title}\""
                        )
                    if i < total - 1:
                        context_parts.append(
                            f"Next chapter: \"{self.project.manuscript.chapters[i + 1].title}\""
                        )
                    # Chapter synopsis from planning
                    if hasattr(ch, 'planning') and ch.planning:
                        if ch.planning.description:
                            chapter_synopsis = ch.planning.description[:400]
                        elif ch.planning.outline:
                            chapter_synopsis = ch.planning.outline[:400]
                    break

        # Heuristic synopsis if no planning data
        if not chapter_synopsis and self._current_chapter_text:
            paras = [p.strip() for p in self._current_chapter_text.split('\n\n') if p.strip()]
            if paras:
                chapter_synopsis = paras[0][:300]
                if len(paras) > 1:
                    chapter_synopsis += f" …{paras[-1][:200]}"

        return "\n\n".join(context_parts), chapter_synopsis

    def set_content_provider(self, provider: callable):
        """Set a callback to get fresh chapter content.

        The provider should return a tuple of (content: str, title: str).
        """
        self._content_provider = provider

    def _refresh_content(self):
        """Refresh chapter content from the manuscript editor.

        This ensures we're always critiquing the latest content,
        even if the user edited after switching to this tab.
        """
        if self._content_provider is not None:
            try:
                content, title = self._content_provider()
                if content:  # Only update if we got content
                    self._current_chapter_text = content
                    self._current_chapter_title = title
                    word_count = len(content.split())
                    self.chapter_info_label.setText(f"Chapter: {title} ({word_count:,} words)")
            except Exception as e:
                print(f"Error refreshing content: {e}")

    def _on_type_changed(self, content_type: str):
        """Handle content type change."""
        is_custom = content_type == "Custom Text"
        self.custom_text_edit.setVisible(is_custom)
        self.chapter_info_label.setVisible(not is_custom)

    def _get_critique(self):
        """Get AI critique of the content."""
        # Refresh content from manuscript editor to ensure we have latest text
        content_type = self.type_combo.currentText()
        if content_type != "Custom Text":
            self._refresh_content()

        # Get content
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

        # Build manuscript context from project data
        ms_context, ch_synopsis = self._build_manuscript_context()

        # Start worker
        self._worker = CritiqueWorker(
            text=text,
            title=title,
            critique_context=critique_context,
            focus_areas=focus_areas if focus_areas else None,
            detailed=self.detailed_check.isChecked(),
            manuscript_context=ms_context,
            chapter_synopsis=ch_synopsis
        )
        self._worker.finished.connect(self._on_critique_finished)
        self._worker.error.connect(self._on_critique_error)
        self._worker.progress.connect(self._on_critique_progress)
        self._worker.start()

    def _get_line_by_line_critique(self):
        """Get line-by-line AI critique with reasoning for each edit."""
        # Refresh content from manuscript editor to ensure we have latest text
        content_type = self.type_combo.currentText()
        if content_type != "Custom Text":
            self._refresh_content()

        # Get content
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

        # Build manuscript context from project data
        ms_context, ch_synopsis = self._build_manuscript_context()

        # Start worker in line-by-line mode
        self._worker = CritiqueWorker(
            text=text,
            title=title,
            critique_context=critique_context,
            focus_areas=None,  # Line-by-line doesn't use focus areas
            detailed=True,
            line_by_line=True,  # Enable line-by-line mode
            manuscript_context=ms_context,
            chapter_synopsis=ch_synopsis
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
            # Line-by-line results - convert to ChapterAnalysis for storage
            suggestions = result.get("suggestions", [])

            # Store as ChapterAnalysis for save/export compatibility
            self._last_analysis = ChapterAnalysis(
                overall_assessment="Line-by-line analysis",
                strengths=[],
                areas_for_improvement=[],
                line_item_suggestions=suggestions,
                pacing_notes="",
                character_consistency_notes="",
                estimated_cost=0.0
            )

            html = self._format_line_by_line_html(suggestions)
            progress_html = self._get_progress_comparison(self._last_analysis)
            if progress_html:
                html += progress_html
            self.results_display.setHtml(html)
        else:
            # Standard ChapterAnalysis
            self._last_analysis = result
            html = self._format_analysis_html(result)
            progress_html = self._get_progress_comparison(result)
            if progress_html:
                html += progress_html
            self.results_display.setHtml(html)

        # Enable save/export buttons
        self.save_critique_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        self.saved_critique_label.setText("")  # Clear any previous status

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
            .location-link { display: inline-block; background-color: #8b5cf6; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; margin-right: 8px; cursor: pointer; text-decoration: none; }
            .location-link:hover { background-color: #7c3aed; }
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
            show_tips = get_ai_config().get_settings().get("show_craft_tips", True)
            html += "<h2>Line-Item Suggestions</h2>"
            html += "<p style='color: #6b7280; font-size: 12px;'>Click location badges to navigate to the text.</p>"
            for idx, suggestion in enumerate(analysis.line_item_suggestions):
                priority_class = f"priority-{suggestion.priority}"
                example_html = ""
                if suggestion.example_fix:
                    example_html = f"<div style='background-color: #ecfdf5; padding: 8px; margin: 8px 0; border-radius: 4px; border-left: 3px solid #10b981;'><strong style='color: #059669;'>Example:</strong> <em>\"{suggestion.example_fix}\"</em></div>"

                # Create clickable location link
                # Use line number if available, otherwise paragraph number
                if suggestion.line_number and suggestion.line_number > 0:
                    location_link = f"<a href='goto:line:{suggestion.line_number}' class='location-link'>Line {suggestion.line_number}</a>"
                elif suggestion.paragraph_number and suggestion.paragraph_number > 0:
                    location_link = f"<a href='goto:para:{suggestion.paragraph_number}' class='location-link'>Para {suggestion.paragraph_number}</a>"
                else:
                    location_link = ""

                learning_links = self._learning_links_html(suggestion, idx, show_tips)

                html += f"""
                <div class='suggestion {priority_class}'>
                    {location_link}
                    <span class='type'>[{suggestion.suggestion_type.value.replace('_', ' ').title()}]</span>
                    <span style='float: right; font-size: 11px;'>Priority: {suggestion.priority.upper()}</span><br>
                    <span class='quote'>"{suggestion.original_text}"</span><br>
                    <strong>Suggestion:</strong> {suggestion.suggestion}<br>
                    {example_html}
                    <em>Why:</em> {suggestion.explanation}
                    {learning_links}
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
            .line-number { display: inline-block; background-color: #8b5cf6; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; margin-right: 8px; cursor: pointer; }
            .line-number:hover { background-color: #7c3aed; }
            a.goto-link { color: white; text-decoration: none; }
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

        show_tips = get_ai_config().get_settings().get("show_craft_tips", True)
        html += f"<h2>Line-by-Line Analysis</h2>"
        html += f"<p style='color: #6b7280; font-size: 13px; margin-bottom: 15px;'>{len(suggestions)} line(s) flagged for potential revision. Click line numbers to navigate.</p>"

        for idx, suggestion in enumerate(suggestions):
            priority_class = f"priority-{suggestion.priority}"
            line_num = suggestion.line_number if suggestion.line_number else 0

            # Make line number clickable
            if line_num > 0:
                line_num_display = f"<a href='goto:line:{line_num}' class='goto-link'>Line {line_num}</a>"
            else:
                line_num_display = "Section"

            # Get issue type display
            issue_type = suggestion.suggestion_type.value.replace('_', ' ').title()

            example_html = ""
            if suggestion.example_fix:
                example_html = f"""
                <div style='background-color: #ecfdf5; padding: 10px; margin: 8px 0; border-radius: 4px; border-left: 3px solid #10b981;'>
                    <span style='color: #059669; font-weight: bold;'>Example revision:</span><br>
                    <em style='color: #065f46;'>"{suggestion.example_fix}"</em>
                </div>
                """

            learning_links = self._learning_links_html(suggestion, idx, show_tips)

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
                {example_html}
                {learning_links}
            </div>
            """

        return html

    def _learning_links_html(self, suggestion: 'LineItemSuggestion', idx: int, show_craft_tips: bool) -> str:
        """Return HTML for 'Learn about' and 'Ask about this' links."""
        parts = []
        if show_craft_tips and suggestion.suggestion_type in CRAFT_EXPLANATIONS:
            type_val = suggestion.suggestion_type.value
            type_display = type_val.replace('_', ' ').title()
            parts.append(
                f"<a href='crafttip:{type_val}' style='font-size: 11px; color: #2563eb; "
                f"text-decoration: none;'>Learn about {type_display}</a>"
            )
        parts.append(
            f"<a href='askabout:{idx}' style='font-size: 11px; color: #6366f1; "
            f"text-decoration: none;'>Ask about this</a>"
        )
        return (
            "<div style='margin-top: 6px; padding-top: 4px; "
            "border-top: 1px solid #e5e7eb;'>"
            + " &nbsp;&middot;&nbsp; ".join(parts)
            + "</div>"
        )

    def _get_progress_comparison(self, current_analysis: 'ChapterAnalysis') -> str:
        """Compare current critique type counts with the most recent saved critique.

        Returns HTML string with comparison, or empty string if no previous data.
        """
        if not self._project_path or not self._current_chapter_title:
            return ""

        try:
            latest = self._metadata_store.get_critique(
                self._project_path, self._current_chapter_title
            )
            if not latest or "data" not in latest:
                return ""

            prev_counts = latest["data"].get("suggestion_type_counts", {})
            if not prev_counts:
                return ""
        except Exception:
            return ""

        # Count current suggestion types
        current_counts: Dict[str, int] = {}
        for s in current_analysis.line_item_suggestions:
            key = s.suggestion_type.value
            current_counts[key] = current_counts.get(key, 0) + 1

        # Build comparison
        improvements = []
        regressions = []
        for type_key in sorted(set(list(prev_counts.keys()) + list(current_counts.keys()))):
            prev = prev_counts.get(type_key, 0)
            curr = current_counts.get(type_key, 0)
            display = type_key.replace('_', ' ').title()
            if curr < prev:
                improvements.append(f"{prev - curr} fewer {display} issues")
            elif curr > prev:
                regressions.append(f"{curr - prev} new {display} issues")

        if not improvements and not regressions:
            return ""

        html = (
            "<div style='background-color: #f0fdf4; border: 1px solid #bbf7d0; "
            "border-radius: 6px; padding: 10px; margin: 10px 0;'>"
            "<strong style='color: #166534;'>Progress vs. Last Critique:</strong><br>"
        )
        for imp in improvements:
            html += f"<span style='color: #059669;'>&#9650; {imp}</span><br>"
        for reg in regressions:
            html += f"<span style='color: #dc2626;'>&#9660; {reg}</span><br>"
        html += "</div>"
        return html

    def _save_critique_results(self):
        """Save the current critique results for later reference."""
        if not self._last_analysis:
            QMessageBox.warning(self, "No Critique", "No critique results to save.")
            return

        if not self._project_path:
            QMessageBox.warning(self, "No Project", "Please save your project first.")
            return

        chapter_title = self._current_chapter_title or "Custom Text"

        # Serialize the analysis
        critique_data = self._serialize_analysis(self._last_analysis)

        # Determine critique type
        critique_type = "line_by_line" if self._last_analysis.line_item_suggestions and \
            any(s.line_number for s in self._last_analysis.line_item_suggestions) else "general"

        # Save it
        critique_id = self._metadata_store.save_critique(
            self._project_path,
            chapter_title,
            critique_data,
            critique_type
        )

        self.saved_critique_label.setText(f"✓ Saved ({critique_id})")

    def _load_critique_results(self):
        """Load a previously saved critique."""
        if not self._project_path:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return

        chapter_title = self._current_chapter_title or "Custom Text"

        # Get list of saved critiques
        critiques = self._metadata_store.list_critiques(self._project_path, chapter_title)

        if not critiques:
            QMessageBox.information(
                self, "No Saved Critiques",
                f"No saved critiques found for '{chapter_title}'."
            )
            return

        # Show selection dialog
        from PyQt6.QtWidgets import QInputDialog
        from datetime import datetime

        # Format options for display
        options = []
        for c in critiques:
            try:
                dt = datetime.fromisoformat(c["timestamp"])
                formatted_time = dt.strftime("%b %d, %Y %I:%M %p")
            except (ValueError, KeyError):
                formatted_time = c.get("timestamp", "Unknown time")

            options.append(f"{formatted_time} ({c['type']})")

        selected, ok = QInputDialog.getItem(
            self,
            "Load Critique",
            "Select a saved critique to load:",
            options,
            0,  # Default to most recent
            False  # Not editable
        )

        if not ok or not selected:
            return

        # Get the critique ID from selection
        selected_idx = options.index(selected)
        critique_id = critiques[selected_idx]["id"]

        # Load the critique
        critique_entry = self._metadata_store.get_critique(
            self._project_path,
            chapter_title,
            critique_id
        )

        if not critique_entry or "data" not in critique_entry:
            QMessageBox.warning(self, "Load Failed", "Could not load the selected critique.")
            return

        # Deserialize and display
        try:
            analysis = self._deserialize_analysis(critique_entry["data"])
            self._last_analysis = analysis
            self._display_analysis(analysis)
            self.save_critique_btn.setEnabled(True)
            self.export_btn.setEnabled(True)

            # Show load status
            try:
                dt = datetime.fromisoformat(critique_entry["timestamp"])
                formatted_time = dt.strftime("%b %d %I:%M %p")
            except (ValueError, KeyError):
                formatted_time = "unknown time"

            self.saved_critique_label.setText(f"Loaded from {formatted_time}")
        except Exception as e:
            QMessageBox.warning(self, "Load Failed", f"Error loading critique: {e}")

    def _serialize_analysis(self, analysis: ChapterAnalysis) -> Dict[str, Any]:
        """Serialize a ChapterAnalysis to a dictionary for storage."""
        # Count suggestion types for progress tracking
        type_counts: Dict[str, int] = {}
        for s in analysis.line_item_suggestions:
            key = s.suggestion_type.value
            type_counts[key] = type_counts.get(key, 0) + 1

        return {
            "overall_assessment": analysis.overall_assessment,
            "strengths": analysis.strengths,
            "areas_for_improvement": analysis.areas_for_improvement,
            "pacing_notes": analysis.pacing_notes,
            "character_consistency_notes": analysis.character_consistency_notes,
            "estimated_cost": analysis.estimated_cost,
            "suggestion_type_counts": type_counts,
            "line_item_suggestions": [
                {
                    "line_number": s.line_number,
                    "paragraph_number": s.paragraph_number,
                    "suggestion_type": s.suggestion_type.value,
                    "original_text": s.original_text,
                    "suggestion": s.suggestion,
                    "explanation": s.explanation,
                    "priority": s.priority,
                    "reasoning": s.reasoning,
                    "example_fix": s.example_fix
                }
                for s in analysis.line_item_suggestions
            ]
        }

    def _deserialize_analysis(self, data: Dict[str, Any]) -> ChapterAnalysis:
        """Deserialize a ChapterAnalysis from a dictionary."""
        suggestions = []
        for s in data.get("line_item_suggestions", []):
            try:
                stype = SuggestionType(s["suggestion_type"])
            except (ValueError, KeyError):
                stype = SuggestionType.STYLE

            suggestions.append(LineItemSuggestion(
                line_number=s.get("line_number"),
                paragraph_number=s.get("paragraph_number", 1),
                suggestion_type=stype,
                original_text=s.get("original_text", ""),
                suggestion=s.get("suggestion", ""),
                explanation=s.get("explanation", ""),
                priority=s.get("priority", "medium"),
                reasoning=s.get("reasoning", ""),
                example_fix=s.get("example_fix", "")
            ))

        return ChapterAnalysis(
            overall_assessment=data.get("overall_assessment", ""),
            strengths=data.get("strengths", []),
            areas_for_improvement=data.get("areas_for_improvement", []),
            line_item_suggestions=suggestions,
            pacing_notes=data.get("pacing_notes", ""),
            character_consistency_notes=data.get("character_consistency_notes", ""),
            estimated_cost=data.get("estimated_cost", 0.0)
        )

    def _display_analysis(self, analysis: ChapterAnalysis):
        """Display a ChapterAnalysis in the results area."""
        # Check if this is line-by-line (has line numbers) or general analysis
        has_line_numbers = any(
            s.line_number and s.line_number > 0
            for s in analysis.line_item_suggestions
        )

        if has_line_numbers:
            # Display as line-by-line analysis
            html = self._format_line_by_line_html(analysis.line_item_suggestions)
        else:
            # Display as general analysis
            html = self._format_analysis_html(analysis)

        self.results_display.setHtml(html)

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
                if suggestion.example_fix:
                    md += f"**Example revision:** \"{suggestion.example_fix}\"\n\n"
                md += f"*Why:* {suggestion.explanation}\n\n"
                md += "---\n\n"

        if analysis.pacing_notes:
            md += f"## Pacing Notes\n\n{analysis.pacing_notes}\n\n"

        if analysis.character_consistency_notes:
            md += f"## Character Consistency\n\n{analysis.character_consistency_notes}\n\n"

        return md

    def _get_quick_stats(self):
        """Get quick local statistics (ProWritingAid-style analysis without AI)."""
        # Refresh content from manuscript editor to ensure we have latest text
        content_type = self.type_combo.currentText()
        if content_type != "Custom Text":
            self._refresh_content()

        # Get content
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
        """Load saved context for the current chapter (or fallback to project context)."""
        self.context_status_label.setText("")

        if not self._project_path or not self._current_chapter_title:
            return

        # First try chapter-specific context
        saved_data = self._metadata_store.get_context(
            self._project_path,
            self._current_chapter_title
        )

        if saved_data and "context" in saved_data:
            self._set_context_from_dict(saved_data["context"])
            self.context_status_label.setText("✓ Loaded chapter context")
            self.context_scope_combo.setCurrentIndex(0)  # Set to "This Chapter"
            return

        # Fallback to project-wide context
        project_data = self._metadata_store.get_project_context(self._project_path)
        if project_data and "context" in project_data:
            self._set_context_from_dict(project_data["context"])
            self.context_status_label.setText("✓ Using project context")
            self.context_scope_combo.setCurrentIndex(1)  # Set to "Entire Project"
            return

        # No saved context - clear fields
        self._clear_context_fields(silent=True)

    def _on_context_scope_changed(self, index: int):
        """Handle context scope combo box change."""
        scope = self.context_scope_combo.currentData()
        if scope == "chapter":
            self.save_context_btn.setToolTip("Save this context for the current chapter")
            self.load_context_btn.setToolTip("Load saved context for this chapter")
        else:
            self.save_context_btn.setToolTip("Save this context for the entire project")
            self.load_context_btn.setToolTip("Load saved project-wide context")

    def _save_context(self):
        """Save context based on current scope selection."""
        scope = self.context_scope_combo.currentData()

        if not self._project_path:
            QMessageBox.warning(
                self, "No Project",
                "Please save your project first before saving context."
            )
            return

        context = self._get_context_dict()

        # Only save if there's actual content
        if not any(v for v in context.values()):
            self.context_status_label.setText("Nothing to save")
            return

        if scope == "chapter":
            if not self._current_chapter_title:
                QMessageBox.warning(
                    self, "No Chapter",
                    "Please select a chapter first, or choose 'Entire Project' scope."
                )
                return
            self._metadata_store.save_context(
                self._project_path,
                self._current_chapter_title,
                context
            )
            self.context_status_label.setText(f"✓ Saved for '{self._current_chapter_title}'")
        else:
            # Project-wide
            self._metadata_store.save_project_context(self._project_path, context)
            self.context_status_label.setText("✓ Saved as project-wide context")

    def _load_context(self):
        """Load context based on current scope selection."""
        scope = self.context_scope_combo.currentData()

        if not self._project_path:
            QMessageBox.warning(
                self, "No Project",
                "Please open a project first."
            )
            return

        if scope == "chapter":
            if not self._current_chapter_title:
                QMessageBox.warning(
                    self, "No Chapter",
                    "Please select a chapter first, or choose 'Entire Project' scope."
                )
                return
            saved_data = self._metadata_store.get_context(
                self._project_path,
                self._current_chapter_title
            )
            if saved_data and "context" in saved_data:
                self._set_context_from_dict(saved_data["context"])
                self.context_status_label.setText(f"✓ Loaded context for '{self._current_chapter_title}'")
            else:
                self.context_status_label.setText("No saved chapter context found")
        else:
            # Project-wide
            project_data = self._metadata_store.get_project_context(self._project_path)
            if project_data and "context" in project_data:
                self._set_context_from_dict(project_data["context"])
                self.context_status_label.setText("✓ Loaded project-wide context")
            else:
                self.context_status_label.setText("No saved project context found")

    def _import_from_chapter_planner(self):
        """Import tone, voice, style from the current chapter's planner."""
        if not self.project:
            QMessageBox.warning(
                self, "No Project",
                "Please open a project first."
            )
            return

        if not self._current_chapter_title:
            QMessageBox.warning(
                self, "No Chapter",
                "Please select a chapter first."
            )
            return

        # Find the chapter in the project manuscript
        chapter = None
        for ch in self.project.manuscript.chapters:
            if ch.title == self._current_chapter_title:
                chapter = ch
                break

        if not chapter:
            self.context_status_label.setText("Chapter not found in project")
            return

        # Get planning data from chapter
        planning_data = getattr(chapter, 'planning_data', {}) or {}

        # Import available fields
        imported = []

        tone = planning_data.get('tone', '')
        if tone:
            self.tone_edit.setText(tone)
            imported.append('tone')

        voice = planning_data.get('voice', '')
        if voice:
            self.voice_edit.setText(voice)
            imported.append('voice')

        style = planning_data.get('style', '')
        if style:
            self.style_edit.setText(style)
            imported.append('style')

        # Import pacing as part of additional instructions if present
        pacing = planning_data.get('pacing', '')
        if pacing:
            current_additional = self.additional_edit.toPlainText()
            pacing_note = f"Pacing: {pacing}"
            if current_additional and pacing_note not in current_additional:
                self.additional_edit.setPlainText(f"{current_additional}\n{pacing_note}")
            elif not current_additional:
                self.additional_edit.setPlainText(pacing_note)
            imported.append('pacing')

        # Import POV character as part of characters if present
        pov_char = planning_data.get('pov_character', '')
        if pov_char:
            current_chars = self.characters_edit.toPlainText()
            pov_note = f"POV: {pov_char}"
            if current_chars and pov_note not in current_chars:
                self.characters_edit.setPlainText(f"{pov_note}\n{current_chars}")
            elif not current_chars:
                self.characters_edit.setPlainText(pov_note)
            imported.append('POV character')

        # Import featured characters
        featured_chars = planning_data.get('characters_featured', [])
        if featured_chars:
            current_chars = self.characters_edit.toPlainText()
            chars_text = ', '.join(featured_chars)
            if current_chars and chars_text not in current_chars:
                self.characters_edit.setPlainText(f"{current_chars}\nFeatured: {chars_text}")
            elif not current_chars:
                self.characters_edit.setPlainText(f"Featured: {chars_text}")
            imported.append('characters')

        if imported:
            self.context_status_label.setText(f"✓ Imported: {', '.join(imported)}")
        else:
            self.context_status_label.setText("No planner metadata found for this chapter")

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

    def _handle_link_click(self, url: QUrl):
        """Handle clicks on links in the results display.

        Args:
            url: The clicked URL
        """
        url_str = url.toString()

        # Handle goto:line:N links (sentence-based navigation)
        if url_str.startswith("goto:line:"):
            try:
                line_num = int(url_str.split(":")[-1])
                self.go_to_line_requested.emit(line_num)
            except ValueError:
                pass

        # Handle goto:para:N links (paragraph-based navigation)
        elif url_str.startswith("goto:para:"):
            try:
                para_num = int(url_str.split(":")[-1])
                # Emit with negative number to signal paragraph mode
                # The receiver will handle this specially
                self.go_to_line_requested.emit(-para_num)
            except ValueError:
                pass

        # Handle crafttip:TYPE links — show educational dialog
        elif url_str.startswith("crafttip:"):
            type_val = url_str.split(":", 1)[1]
            try:
                tip = CRAFT_EXPLANATIONS.get(SuggestionType(type_val))
            except ValueError:
                tip = None
            if tip:
                title = type_val.replace('_', ' ').title()
                msg = (
                    f"{tip['principle']}\n\n"
                    f"Before:\n\"{tip['before']}\"\n\n"
                    f"After:\n\"{tip['after']}\""
                )
                QMessageBox.information(self, f"Craft Tip: {title}", msg)

        # Handle askabout:IDX links — send to Chapter Focus chat
        elif url_str.startswith("askabout:"):
            try:
                idx = int(url_str.split(":")[1])
                if self._last_analysis and idx < len(self._last_analysis.line_item_suggestions):
                    s = self._last_analysis.line_item_suggestions[idx]
                    self.ask_about_suggestion.emit(
                        s.suggestion_type.value,
                        s.original_text,
                        s.suggestion,
                        s.explanation
                    )
            except (ValueError, IndexError):
                pass

    def load_data(self, data):
        """Load grader data (placeholder for future use)."""

    def get_data(self):
        """Get grader data (placeholder for future use)."""
        return None
