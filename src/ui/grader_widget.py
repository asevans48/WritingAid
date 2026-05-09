"""Grader widget for comprehensive manuscript critique with AI integration."""

import json
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QTextEdit, QTextBrowser, QComboBox, QGroupBox,
    QMessageBox, QCheckBox, QLineEdit, QProgressBar,
    QScrollArea, QFileDialog, QListWidget, QListWidgetItem,
    QRadioButton, QButtonGroup, QTabWidget,
    QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, QThread, Qt, QUrl

from src.ai.chapter_analysis_agent import (
    CritiqueContext, SuggestionType,
    ReportType, GENRE_PROFILES, resolve_genre_profile,
    ReportSection, ChapterReport, CritiqueReport,
    CritiqueOrchestrator,
)
from src.ui.rating_bar import RatingBar
from src.config.ai_config import get_ai_config
from src.ai.craft_explanations import CRAFT_EXPLANATIONS

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
    """Background worker driving the report-driven critique flow.

    Pulls an LLM client (cloud or local) using the same selection
    logic the chat path uses, builds a CritiqueOrchestrator, and
    runs the selected reports across the supplied chapter set.
    Emits ``finished(CritiqueReport)`` on success.
    """
    finished = pyqtSignal(object)  # CritiqueReport
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        chapters: List[Dict[str, Any]],
        report_types: List[ReportType],
        genre_key: str,
        critique_context: Optional[CritiqueContext],
        manuscript_context: str = "",
        chapter_synopses: Optional[Dict[str, str]] = None,
        story_planning: Optional[Any] = None,
        rag_provider: Optional[Any] = None,
        force_dashboard: bool = False,
    ):
        super().__init__()
        self.chapters = chapters
        self.report_types = report_types
        self.genre_key = genre_key
        self.critique_context = critique_context
        self.manuscript_context = manuscript_context
        self.chapter_synopses = chapter_synopses or {}
        self.story_planning = story_planning
        self.rag_provider = rag_provider
        self.force_dashboard = force_dashboard

    def _build_llm(self) -> Optional[Any]:
        """Construct an LLM client using the saved AI settings.

        Returns ``None`` when AI is disabled or no provider is
        configured — the orchestrator interprets ``None`` as
        dashboard mode (no narrative).
        """
        from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig
        ai_config = get_ai_config()
        settings = ai_config.get_settings()
        if ai_config.is_ai_disabled():
            return None
        prefer_local = settings.get("prefer_local_model", False)
        enable_local = settings.get("enable_local_models", False)
        local_model_id = settings.get("local_model_id", "")
        if prefer_local and enable_local and local_model_id:
            is_mlx_model = "mlx" in local_model_id.lower()
            hf_config = HuggingFaceConfig(
                model_id=local_model_id,
                use_local=True,
                device=settings.get("local_model_device", "auto"),
                quantization=settings.get(
                    "local_model_quantization", "none")
                if settings.get("local_model_quantization") != "none"
                else None,
                trust_remote_code=settings.get(
                    "local_model_trust_remote_code", False),
            )
            provider = (LLMProvider.MLX_LOCAL if is_mlx_model
                        else LLMProvider.HUGGINGFACE_LOCAL)
            return LLMClient(provider=provider, hf_config=hf_config)
        default_provider = settings.get("default_llm", "claude")
        api_key = ai_config.get_api_key(default_provider)
        if not api_key:
            return None
        provider_map = {
            "claude": LLMProvider.CLAUDE,
            "chatgpt": LLMProvider.CHATGPT,
            "openai": LLMProvider.CHATGPT,
            "gemini": LLMProvider.GEMINI,
        }
        return LLMClient(
            provider=provider_map.get(default_provider, LLMProvider.CLAUDE))

    def run(self):
        """Drive the orchestrator on the worker thread."""
        try:
            self.progress.emit("Initializing critique…")
            llm = None
            if not self.force_dashboard:
                llm = self._build_llm()
                if llm is None:
                    self.progress.emit(
                        "No LLM configured — running dashboard mode.")
                else:
                    # Honour the per-task model override the same way the
                    # chat path does; critique is plot/structural analysis.
                    try:
                        from src.ai.task_llm import build_task_llm_override
                        override = build_task_llm_override("plot")
                        if override is not None:
                            self.progress.emit(
                                "Using your plot-task model for critique…")
                            llm = override
                    except Exception:
                        pass
            orchestrator = CritiqueOrchestrator(
                primary_llm=llm,
                project=self._project_proxy(),
                rag_provider=self.rag_provider,
                chapter_synopses=self.chapter_synopses,
            )

            def progress_cb(msg: str):
                self.progress.emit(msg)

            report = orchestrator.run(
                chapters=self.chapters,
                report_types=self.report_types,
                genre_key_or_text=self.genre_key,
                manuscript_context=self.manuscript_context,
                critique_context=self.critique_context,
                progress_cb=progress_cb,
            )
            self.progress.emit("Complete.")
            self.finished.emit(report)
        except Exception as e:  # pragma: no cover — defensive
            self.error.emit(str(e))

    def _project_proxy(self):
        """Lightweight stand-in passed to PlotAnalyzer for promises lookup."""
        if self.story_planning is None:
            return None

        class _Proxy:
            pass
        proxy = _Proxy()
        proxy.story_planning = self.story_planning
        return proxy


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
        self._last_report: Optional[CritiqueReport] = None
        self._metadata_store = get_critique_metadata_store()
        self._content_provider: Optional[callable] = None  # Callback to get fresh content
        self._init_ui()
        # Auto-sync genre dropdown from the Style/Genre free-text
        # field — typing "hard-boiled noir" auto-selects Thriller, etc.
        self.style_edit.editingFinished.connect(self._sync_genre_from_style)
        # Set initial scope visibility (Single chapter is the default).
        self._on_scope_changed()

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
        header = QLabel("Writing Critique & Reports")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 5px;")
        layout.addWidget(header)

        description = QLabel(
            "Pick a scope (one chapter, several, or the whole manuscript), "
            "choose which reports to run, and the critique engine produces "
            "an embellished narrative report when an LLM is configured — "
            "or a metrics dashboard when one isn't."
        )
        description.setWordWrap(True)
        description.setStyleSheet("padding: 5px; color: #666;")
        layout.addWidget(description)

        # ── Scope ────────────────────────────────────────────────
        scope_group = QGroupBox("Scope")
        scope_outer = QVBoxLayout()
        scope_radio_row = QHBoxLayout()
        self.scope_radio_group = QButtonGroup(self)
        self.scope_single_radio = QRadioButton("Current chapter")
        self.scope_multi_radio = QRadioButton("Selected chapters")
        self.scope_manuscript_radio = QRadioButton("Full manuscript")
        self.scope_custom_radio = QRadioButton("Custom text")
        self.scope_single_radio.setChecked(True)
        for i, rb in enumerate([
            self.scope_single_radio, self.scope_multi_radio,
            self.scope_manuscript_radio, self.scope_custom_radio,
        ]):
            self.scope_radio_group.addButton(rb, i)
            rb.toggled.connect(self._on_scope_changed)
            scope_radio_row.addWidget(rb)
        scope_radio_row.addStretch()
        scope_outer.addLayout(scope_radio_row)

        # Current chapter info (for Single scope)
        self.chapter_info_label = QLabel("No chapter selected")
        self.chapter_info_label.setStyleSheet(
            "color: #666; font-style: italic; padding: 5px;")
        scope_outer.addWidget(self.chapter_info_label)

        # Multi-select chapter picker (for Selected chapters scope)
        self.chapter_picker = QListWidget()
        self.chapter_picker.setSelectionMode(
            QListWidget.SelectionMode.MultiSelection)
        self.chapter_picker.setMaximumHeight(140)
        self.chapter_picker.setVisible(False)
        scope_outer.addWidget(self.chapter_picker)

        # Custom-text fallback (for Custom text scope)
        self.custom_text_edit = QTextEdit()
        self.custom_text_edit.setPlaceholderText(
            "Paste text to critique here…")
        self.custom_text_edit.setMaximumHeight(150)
        self.custom_text_edit.setVisible(False)
        scope_outer.addWidget(self.custom_text_edit)

        # Manuscript info label (for Full manuscript scope)
        self.manuscript_info_label = QLabel("")
        self.manuscript_info_label.setStyleSheet(
            "color: #666; font-style: italic; padding: 5px;")
        self.manuscript_info_label.setVisible(False)
        scope_outer.addWidget(self.manuscript_info_label)

        scope_group.setLayout(scope_outer)
        layout.addWidget(scope_group)

        # ── Reports + Genre ──────────────────────────────────────
        reports_group = QGroupBox("Reports to run")
        reports_outer = QVBoxLayout()

        # Genre selector row
        genre_row = QHBoxLayout()
        genre_row.addWidget(QLabel("Genre profile:"))
        self.genre_combo = QComboBox()
        for key, profile in GENRE_PROFILES.items():
            self.genre_combo.addItem(profile.name, key)
        self.genre_combo.setToolTip(
            "Genre tunes pacing / voice / dialog thresholds. "
            "Auto-fills from the Style/Genre field below if it matches "
            "a known genre.")
        genre_row.addWidget(self.genre_combo)
        genre_row.addStretch()

        # Force-dashboard mode (skip the LLM even when one is configured)
        self.force_dashboard_check = QCheckBox("Dashboard only (skip LLM narrative)")
        self.force_dashboard_check.setToolTip(
            "Run the deterministic metrics+findings dashboard without "
            "calling the LLM, even if one is configured.")
        genre_row.addWidget(self.force_dashboard_check)
        reports_outer.addLayout(genre_row)

        # Report-type checkbox grid
        reports_grid = QGridLayout()
        self.report_checkboxes: Dict[ReportType, QCheckBox] = {}
        report_items = [
            (ReportType.PACING, "Pacing", "Genre-aware sentence-rhythm analysis."),
            (ReportType.VOICE, "Writer's Voice", "Diction, syntax habits, voice consistency."),
            (ReportType.TENSION, "Tension & Stakes", "Moment-to-moment friction; what hangs over the chapter."),
            (ReportType.PLOT, "Plot & Promises", "What changes; promise tracking; structural concerns."),
            (ReportType.DIALOG, "Dialog", "Density, tag hygiene, voice differentiation, subtext."),
            (ReportType.STYLE, "Sentence Style", "Passive, adverbs, clichés, echoes, readability."),
        ]
        for i, (rt, label, tooltip) in enumerate(report_items):
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.setToolTip(tooltip)
            self.report_checkboxes[rt] = cb
            reports_grid.addWidget(cb, i // 3, i % 3)
        reports_outer.addLayout(reports_grid)

        # Select-all / clear shortcuts
        select_row = QHBoxLayout()
        all_btn = QPushButton("All")
        all_btn.setStyleSheet(
            "QPushButton { padding: 3px 8px; font-size: 11px; }")
        all_btn.clicked.connect(self._select_all_reports)
        none_btn = QPushButton("None")
        none_btn.setStyleSheet(
            "QPushButton { padding: 3px 8px; font-size: 11px; }")
        none_btn.clicked.connect(self._select_no_reports)
        select_row.addWidget(all_btn)
        select_row.addWidget(none_btn)
        select_row.addStretch()
        reports_outer.addLayout(select_row)

        reports_group.setLayout(reports_outer)
        layout.addWidget(reports_group)

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

        # ── Run row ──────────────────────────────────────────────
        run_row = QHBoxLayout()
        run_row.addStretch()
        self.critique_btn = QPushButton("Run Critique")
        self.critique_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                padding: 10px 22px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #4f46e5; }
            QPushButton:disabled { background-color: #9ca3af; }
        """)
        self.critique_btn.setToolTip(
            "Run the selected reports across the chosen scope.")
        self.critique_btn.clicked.connect(self._run_reports)
        run_row.addWidget(self.critique_btn)
        layout.addLayout(run_row)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        # ── Results: tabbed ──────────────────────────────────────
        results_group = QGroupBox("Critique Results")
        results_layout = QVBoxLayout()

        self.results_tabs = QTabWidget()
        self.results_tabs.setMinimumHeight(360)
        self.results_tabs.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # The Summary tab is permanent; per-report tabs are added on
        # each run.
        self._summary_browser = QTextBrowser()
        self._summary_browser.setOpenExternalLinks(False)
        self._summary_browser.setOpenLinks(False)
        self._summary_browser.anchorClicked.connect(self._handle_link_click)
        self._summary_browser.setHtml(
            "<p style='color:#888'>No critique run yet. Pick a scope, "
            "select reports, and click <b>Run Critique</b>.</p>")
        self.results_tabs.addTab(self._summary_browser, "Summary")
        # Backwards-compat alias used by older helpers (e.g. _quick_stats).
        self.results_display = self._summary_browser
        results_layout.addWidget(self.results_tabs)

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
        # Refresh chapter picker and manuscript info so the multi /
        # manuscript scopes are immediately usable.
        self._populate_chapter_list()

    def _sync_genre_from_style(self):
        """Update the Genre dropdown when the Style/Genre field changes.

        Uses ``resolve_genre_profile`` so common synonyms ("hard-boiled
        noir" → thriller, "epic fantasy" → fantasy) auto-select the
        right profile. Leaves the dropdown alone if the user has
        already picked something more specific than what the text
        resolves to.
        """
        text = self.style_edit.text().strip()
        if not text:
            return
        profile = resolve_genre_profile(text)
        idx = self.genre_combo.findData(profile.key)
        if idx >= 0:
            self.genre_combo.setCurrentIndex(idx)

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

    def _on_scope_changed(self, _checked: bool = False):
        """Show/hide scope-dependent inputs based on the selected radio.

        Single → chapter-info label only.
        Selected chapters → multi-select chapter picker.
        Full manuscript → manuscript info label.
        Custom text → free-text editor.
        """
        is_single = self.scope_single_radio.isChecked()
        is_multi = self.scope_multi_radio.isChecked()
        is_manu = self.scope_manuscript_radio.isChecked()
        is_custom = self.scope_custom_radio.isChecked()
        self.chapter_info_label.setVisible(is_single)
        self.chapter_picker.setVisible(is_multi)
        self.custom_text_edit.setVisible(is_custom)
        self.manuscript_info_label.setVisible(is_manu)
        if is_multi or is_manu:
            self._populate_chapter_list()

    def _select_all_reports(self):
        for cb in self.report_checkboxes.values():
            cb.setChecked(True)

    def _select_no_reports(self):
        for cb in self.report_checkboxes.values():
            cb.setChecked(False)

    def _populate_chapter_list(self):
        """Refresh the chapter picker + manuscript info from the current project."""
        self.chapter_picker.clear()
        if (not self.project or not self.project.manuscript
                or not self.project.manuscript.chapters):
            self.manuscript_info_label.setText(
                "No chapters loaded for this project.")
            return
        chapters = self.project.manuscript.chapters
        total_words = 0
        for i, ch in enumerate(chapters):
            wc = ch.word_count or len((ch.content or "").split())
            total_words += wc
            label = f"{ch.number:02d}. {ch.title} ({wc:,} words)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, i)  # index in chapters
            self.chapter_picker.addItem(item)
            # Pre-select the current chapter when first populating
            if (self._current_chapter_title
                    and ch.title == self._current_chapter_title):
                item.setSelected(True)
        self.manuscript_info_label.setText(
            f"{len(chapters)} chapter(s), {total_words:,} words total. "
            "Reports run chapter by chapter.")

    def _get_chapters_for_run(self) -> List[Dict[str, Any]]:
        """Return [{title, text, index}] based on the selected scope."""
        # Pull the latest content for the current chapter
        if (self.scope_single_radio.isChecked()
                or self.scope_custom_radio.isChecked()):
            self._refresh_content()

        if self.scope_custom_radio.isChecked():
            text = self.custom_text_edit.toPlainText().strip()
            if not text:
                return []
            return [{"title": "Custom Text", "text": text, "index": 0}]

        if self.scope_single_radio.isChecked():
            if not self._current_chapter_text:
                return []
            return [{
                "title": self._current_chapter_title or "Current Chapter",
                "text": self._current_chapter_text,
                "index": 0,
            }]

        if (not self.project or not self.project.manuscript
                or not self.project.manuscript.chapters):
            return []
        chapters = self.project.manuscript.chapters

        if self.scope_manuscript_radio.isChecked():
            indices = list(range(len(chapters)))
        else:  # scope_multi_radio
            indices = []
            for i in range(self.chapter_picker.count()):
                item = self.chapter_picker.item(i)
                if item.isSelected():
                    indices.append(item.data(Qt.ItemDataRole.UserRole))

        results: List[Dict[str, Any]] = []
        for idx in indices:
            if 0 <= idx < len(chapters):
                ch = chapters[idx]
                content = ch.content or ""
                # Fall back to disk if content wasn't preloaded.
                if not content and self._project_path:
                    try:
                        from pathlib import Path
                        proj_dir = Path(self._project_path).parent
                        ch.load_content_from_file(proj_dir)
                        content = ch.content or ""
                    except Exception as e:
                        print(f"[critique] failed to load content for "
                              f"{ch.title}: {e}")
                if content.strip():
                    results.append({
                        "title": ch.title or f"Chapter {ch.number}",
                        "text": content,
                        "index": idx,
                    })
        return results

    def _collect_critique_context(self) -> Optional[CritiqueContext]:
        """Gather the context fields into a CritiqueContext object."""
        ctx = CritiqueContext(
            style=self.style_edit.text().strip(),
            tone=self.tone_edit.text().strip(),
            voice=self.voice_edit.text().strip(),
            plot_goals=self.plot_edit.toPlainText().strip(),
            characters=self.characters_edit.toPlainText().strip(),
            worldbuilding=self.worldbuilding_edit.toPlainText().strip(),
            additional_instructions=self.additional_edit.toPlainText().strip(),
        )
        # All-empty → return None so the agent skips the AUTHOR CONTEXT
        # block in prompts.
        if not any([
            ctx.style, ctx.tone, ctx.voice, ctx.plot_goals, ctx.characters,
            ctx.worldbuilding, ctx.additional_instructions,
        ]):
            return None
        return ctx

    def _make_rag_provider(self):
        """Build a RAG provider callable bound to the main window's RAG.

        Returns ``(query, source_types) → str`` or ``None`` if RAG isn't
        available. The orchestrator calls this once per chapter per
        report so the model only sees report-relevant chunks.
        """
        try:
            mw = self.window()
            if mw is not None and hasattr(mw, "_rag_top_chunks_per_type"):
                return lambda query, source_types: (
                    mw._rag_top_chunks_per_type(
                        query=query,
                        source_types=source_types,
                        top_k=6,
                        max_chars_per_chunk=600,
                        max_total_chars=2500,
                    )
                )
        except Exception as e:
            print(f"[critique] RAG provider unavailable: {e}")
        return None

    def _build_chapter_synopses(self) -> Dict[str, str]:
        """Map chapter title → planning synopsis for PlotAnalyzer."""
        synopses: Dict[str, str] = {}
        if not self.project or not self.project.manuscript:
            return synopses
        for ch in self.project.manuscript.chapters:
            if hasattr(ch, "planning") and ch.planning:
                if ch.planning.description:
                    synopses[ch.title] = ch.planning.description[:400]
                elif ch.planning.outline:
                    synopses[ch.title] = ch.planning.outline[:400]
        return synopses

    def _run_reports(self):
        """Entry point for the new Reports flow."""
        chapters = self._get_chapters_for_run()
        if not chapters:
            QMessageBox.warning(
                self, "Nothing to critique",
                "No content found for the selected scope. Choose a "
                "chapter, select chapters from the picker, or paste "
                "custom text.")
            return
        report_types = [
            rt for rt, cb in self.report_checkboxes.items()
            if cb.isChecked()
        ]
        if not report_types:
            QMessageBox.warning(
                self, "No reports selected",
                "Select at least one report to run.")
            return
        critique_context = self._collect_critique_context()
        ms_context, _ = self._build_manuscript_context()
        chapter_synopses = self._build_chapter_synopses()
        rag_provider = self._make_rag_provider()
        # Genre key — prefer the dropdown selection; the dropdown is
        # auto-synced from the Style/Genre field elsewhere.
        genre_key = self.genre_combo.currentData() or "default"

        # Show progress, lock the run button.
        self.progress_bar.setVisible(True)
        self.status_label.setVisible(True)
        self.status_label.setText("Starting critique…")
        self.critique_btn.setEnabled(False)

        story_planning = (
            self.project.story_planning if self.project else None)

        self._worker = CritiqueWorker(
            chapters=chapters,
            report_types=report_types,
            genre_key=genre_key,
            critique_context=critique_context,
            manuscript_context=ms_context,
            chapter_synopses=chapter_synopses,
            story_planning=story_planning,
            rag_provider=rag_provider,
            force_dashboard=self.force_dashboard_check.isChecked(),
        )
        self._worker.finished.connect(self._on_critique_finished)
        self._worker.error.connect(self._on_critique_error)
        self._worker.progress.connect(self._on_critique_progress)
        self._worker.start()

    def _on_critique_progress(self, message: str):
        """Handle progress updates."""
        self.status_label.setText(message)

    def _on_critique_finished(self, result):
        """Handle CritiqueReport arrival from the worker."""
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)
        self.critique_btn.setEnabled(True)
        if not isinstance(result, CritiqueReport):
            QMessageBox.warning(
                self, "Critique",
                "Unexpected result shape from critique worker.")
            return
        self._last_report = result
        self._render_critique_report(result)
        self.save_critique_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        self.saved_critique_label.setText("")

    def _on_critique_error(self, error: str):
        """Handle worker error."""
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)
        self.critique_btn.setEnabled(True)
        QMessageBox.critical(
            self, "Critique Failed",
            f"Failed to generate critique:\n\n{error}")

    # ── Report rendering ─────────────────────────────────────────

    REPORT_TAB_LABELS = {
        ReportType.PACING: "Pacing",
        ReportType.VOICE: "Voice",
        ReportType.TENSION: "Tension",
        ReportType.PLOT: "Plot",
        ReportType.DIALOG: "Dialog",
        ReportType.STYLE: "Style",
    }

    REPORT_STYLE_BLOCK = """
    <style>
        body { font-family: -apple-system, sans-serif; }
        h2 { color: #1f2937; margin-top: 14px; margin-bottom: 6px; }
        h3 { color: #374151; margin-top: 12px; margin-bottom: 4px; }
        h4 { color: #4b5563; margin: 8px 0 4px; font-size: 13px; }
        .chapter-block { background:#f8fafc; border:1px solid #e2e8f0;
                         border-radius:6px; padding:10px 12px; margin:10px 0; }
        .chapter-title { font-weight:600; color:#1f2937; font-size:14px; }
        .chapter-meta { color:#6b7280; font-size:11px; }
        .summary { color:#1f2937; margin:6px 0; }
        .narrative { color:#1f2937; margin:8px 0;
                     padding:10px; background:#fff; border-left:3px solid #6366f1;
                     border-radius:4px; white-space:pre-wrap; }
        .findings, .suggestions { margin:6px 0; }
        .findings li { color:#dc2626; margin:2px 0; }
        .findings li.ok { color:#059669; }
        .suggestions li { color:#0369a1; margin:2px 0; }
        .metric-table { font-size:12px; border-collapse:collapse; margin:6px 0; }
        .metric-table td { padding:2px 8px; border-bottom:1px solid #f1f5f9; }
        .metric-table td:first-child { color:#6b7280; }
        .metric-table td:last-child { color:#1f2937; font-weight:500; }
        .badge { display:inline-block; padding:2px 8px; border-radius:10px;
                 font-size:11px; font-weight:600; margin-right:6px; }
        .badge-llm { background:#ede9fe; color:#5b21b6; }
        .badge-dash { background:#fef3c7; color:#92400e; }
        .badge-genre { background:#e0f2fe; color:#075985; }
        .empty { color:#888; padding:8px; }
    </style>
    """

    def _clear_report_tabs(self):
        """Drop everything except the permanent Summary tab."""
        while self.results_tabs.count() > 1:
            self.results_tabs.removeTab(1)

    def _render_critique_report(self, report: CritiqueReport):
        """Render a CritiqueReport into the tabbed results pane.

        Each per-report tab gets the rendered HTML on top + a rating
        bar at the bottom so the author can mark the report excellent
        / good / poor / bad and save it to the training database.

        The Summary tab also gets its own rating bar — the overall
        narrative is independently rateable.
        """
        self._clear_report_tabs()
        # Summary tab — rebuild it as a Widget so we can attach a
        # rating bar at the bottom alongside the existing browser.
        self._refresh_summary_tab(report)
        # Per-report tabs
        for rt in self.REPORT_TAB_LABELS.keys():
            sections = [
                s for c in report.chapters for s in c.sections
                if s.report_type == rt
            ]
            if not sections:
                continue
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(0, 0, 0, 0)
            tab_layout.setSpacing(4)

            browser = QTextBrowser()
            browser.setOpenExternalLinks(False)
            browser.setOpenLinks(False)
            browser.anchorClicked.connect(self._handle_link_click)
            browser.setHtml(self._format_report_tab_html(rt, sections, report))
            tab_layout.addWidget(browser)

            # Per-report rating bar — captures the user's judgment of
            # this analysis specifically (so e.g. a great pacing report
            # but a weak voice report can be rated independently).
            rating_bar = RatingBar(
                label=f"Rate this {self.REPORT_TAB_LABELS[rt]} report:",
                compact=False)
            rating_bar.rated.connect(
                lambda value, rt=rt, sections=sections, report=report:
                    self._persist_critique_rating(
                        rating_bar, value, rt, sections, report))
            tab_layout.addWidget(rating_bar)

            self.results_tabs.addTab(tab, self.REPORT_TAB_LABELS[rt])

    def _refresh_summary_tab(self, report: CritiqueReport):
        """Replace the Summary tab content with browser + overall rating bar."""
        # Build a fresh tab widget for index 0
        new_tab = QWidget()
        layout = QVBoxLayout(new_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._summary_browser = QTextBrowser()
        self._summary_browser.setOpenExternalLinks(False)
        self._summary_browser.setOpenLinks(False)
        self._summary_browser.anchorClicked.connect(self._handle_link_click)
        self._summary_browser.setHtml(self._format_summary_html(report))
        layout.addWidget(self._summary_browser)

        rating_bar = RatingBar(
            label="Rate this critique overall:",
            compact=False)
        rating_bar.rated.connect(
            lambda value: self._persist_critique_rating(
                rating_bar, value, None, None, report))
        layout.addWidget(rating_bar)

        # Replace the existing Summary tab if present, otherwise insert.
        if self.results_tabs.count() == 0:
            self.results_tabs.addTab(new_tab, "Summary")
        else:
            # Remove the old summary tab (always at index 0)
            self.results_tabs.removeTab(0)
            self.results_tabs.insertTab(0, new_tab, "Summary")
            self.results_tabs.setCurrentIndex(0)
        # Keep the back-compat alias
        self.results_display = self._summary_browser

    def _persist_critique_rating(
        self,
        rating_bar: RatingBar,
        value: str,
        rt: 'Optional[ReportType]',
        sections: 'Optional[List[ReportSection]]',
        report: CritiqueReport,
    ):
        """Log critique ratings to the rephrase database for training.

        For per-report tabs, this writes ONE row per chapter section
        — pairing the actual LLM prompt the analyzer sent (captured on
        ``section.prompt`` at execute time) with the report content
        the model produced (narrative + findings + suggestions). The
        rows go to the dedicated ``SOURCE_CRITIQUE`` bucket so the
        trainer can filter / weight them independently.

        For the Summary (overall) tab, a single row is written using
        the cross-chapter rollup as the output and a constructed
        instruction as the source — the overall narrative is built
        from per-section summaries, not from a single LLM call, so
        there's no captured prompt for it.
        """
        from src.data.rephrase_database import (
            get_rephrase_database, is_collection_enabled, SOURCE_CRITIQUE,
        )

        # Save toggle off → just acknowledge in the bar; no DB write.
        if not rating_bar.is_save_enabled():
            rating_bar.set_status(f"Rated {value} (not saved)", ok=True)
            return

        if not is_collection_enabled():
            rating_bar.set_status(
                "Rated. Enable data collection in Creative OS "
                "settings to save for training.", ok=False)
            return

        try:
            db = get_rephrase_database()
            saved = 0
            if rt is None or not sections:
                # Summary tab — write one row for the overall rollup.
                # No real LLM prompt was used (the orchestrator
                # synthesised the summary from per-section data), so
                # we construct an instruction that mirrors what the
                # rollup is. Tagged ``critique_kind=overall`` and
                # ``prompt_kind=synthesised`` so the trainer can
                # down-weight or skip if it only wants real prompts.
                if report.has_llm:
                    source_text = (
                        f"Write a manuscript-level rollup of per-chapter "
                        f"critiques. Genre profile: {report.genre.name} — "
                        f"{report.genre.notes}\n\n"
                        + "\n\n".join(
                            f"Chapter: {c.chapter_title}\n"
                            + "\n".join(
                                f"  - [{s.report_type.value}] "
                                f"{(s.summary or '').strip()}"
                                for s in c.sections)
                            for c in report.chapters))
                    prompt_kind = "real_synthesised"
                else:
                    source_text = (
                        f"Summarise this critique report at manuscript "
                        f"level. Genre profile: {report.genre.name}. "
                        f"{len(report.chapters)} chapter(s).")
                    prompt_kind = "dashboard_synthesised"
                output_text = report.overall_summary or "(no summary)"
                notes = (
                    f"critique_kind=overall genre={report.genre.key} "
                    f"chapters={len(report.chapters)} "
                    f"has_llm={report.has_llm} prompt_kind={prompt_kind}")
                if output_text and output_text != "(no summary)":
                    db.log(
                        source_text=source_text,
                        output_text=output_text,
                        source_type=SOURCE_CRITIQUE,
                        rating=value,
                        accepted=value in ("excellent", "good"),
                        notes=notes,
                        project_path=self._project_path,
                        genre=report.genre.key,
                    )
                    saved = 1
            else:
                # Per-report tab — one row per chapter section. Each
                # row is a real (prompt, output) pair when the LLM
                # narrative ran, or a (synthesised_instruction,
                # findings) pair when in dashboard mode.
                for s in sections:
                    output_pieces = []
                    if s.narrative:
                        output_pieces.append(s.narrative)
                    if s.findings:
                        output_pieces.append(
                            "Findings:\n"
                            + "\n".join(f"- {f}" for f in s.findings))
                    if s.suggestions:
                        output_pieces.append(
                            "Suggested actions:\n"
                            + "\n".join(f"- {x}" for x in s.suggestions))
                    output_text = "\n\n".join(p for p in output_pieces if p)
                    if not output_text.strip():
                        continue

                    # Prefer the captured LLM prompt; fall back to a
                    # synthesised instruction when no LLM was used.
                    if s.prompt and s.prompt.strip():
                        source_text = s.prompt
                        prompt_kind = "real"
                    else:
                        source_text = (
                            f"Produce a {rt.value} critique of this "
                            f"chapter for the {report.genre.name} genre. "
                            f"Use the metrics provided as ground truth, "
                            f"name specific issues with quoted phrases, "
                            f"and end with concrete next-revision "
                            f"actions.\n\n"
                            f"Chapter: {s.chapter_title}\n"
                            f"Metrics:\n"
                            + "\n".join(f"- {k}: {v}"
                                        for k, v in s.metrics.items()))
                        prompt_kind = "dashboard_synthesised"
                    notes = (
                        f"critique_kind={rt.value} "
                        f"genre={report.genre.key} "
                        f"chapter_title={s.chapter_title} "
                        f"chapters={len(report.chapters)} "
                        f"has_llm={report.has_llm} "
                        f"prompt_kind={prompt_kind}")
                    db.log(
                        source_text=source_text,
                        output_text=output_text,
                        source_type=SOURCE_CRITIQUE,
                        rating=value,
                        accepted=value in ("excellent", "good"),
                        notes=notes,
                        project_path=self._project_path,
                        genre=report.genre.key,
                    )
                    saved += 1
            label = (f"{rt.value} critique" if rt
                     else "overall critique")
            rating_bar.set_status(
                f"Saved {saved} row(s) as {value} for training",
                ok=True)
            print(f"[critique] rated {label} as {value} "
                  f"(persisted {saved} rows to SOURCE_CRITIQUE)")
        except Exception as e:
            rating_bar.set_status(f"Save failed: {e}", ok=False)

    def _format_summary_html(self, report: CritiqueReport) -> str:
        """Build the Summary tab — manuscript rollup + per-chapter highlights."""
        mode_badge = (
            '<span class="badge badge-llm">LLM narrative</span>'
            if report.has_llm
            else '<span class="badge badge-dash">Dashboard mode</span>')
        genre_badge = (
            f'<span class="badge badge-genre">{report.genre.name}</span>')
        n_chapters = len(report.chapters)
        total_words = sum(c.word_count for c in report.chapters)
        lines = [self.REPORT_STYLE_BLOCK]
        lines.append(
            f"<h2>Critique Summary</h2>"
            f"<p>{mode_badge}{genre_badge}"
            f"<span style='color:#6b7280; font-size:11px;'>"
            f"{n_chapters} chapter{'s' if n_chapters != 1 else ''}, "
            f"{total_words:,} words</span></p>"
        )
        lines.append(
            f"<p style='color:#4b5563;'>"
            f"<em>{report.genre.notes}</em></p>")
        if report.overall_summary:
            lines.append(
                f"<h3>Overall</h3>"
                f"<div class='narrative'>{self._escape_html(report.overall_summary)}</div>")
        # Per-chapter rollup
        for c in report.chapters:
            lines.append(
                f"<div class='chapter-block'>"
                f"<div class='chapter-title'>{self._escape_html(c.chapter_title)}</div>"
                f"<div class='chapter-meta'>{c.word_count:,} words · "
                f"{len(c.sections)} report section(s)</div>")
            for s in c.sections:
                lines.append(
                    f"<div style='margin-top:6px;'>"
                    f"<strong>{self.REPORT_TAB_LABELS.get(s.report_type, s.report_type.value)}:</strong> "
                    f"{self._escape_html(s.summary or '(no summary)')}</div>")
            lines.append("</div>")
        return "\n".join(lines)

    def _format_report_tab_html(
        self,
        rt: ReportType,
        sections: List[ReportSection],
        report: CritiqueReport,
    ) -> str:
        """Build a single per-report tab — one chapter block per section."""
        lines = [self.REPORT_STYLE_BLOCK]
        title = self.REPORT_TAB_LABELS.get(rt, rt.value.title())
        lines.append(
            f"<h2>{title} — {report.genre.name}</h2>"
            f"<p style='color:#6b7280; font-size:11px;'>"
            f"{len(sections)} chapter section(s).</p>")
        for s in sections:
            lines.append(self._format_section_html(s))
        return "\n".join(lines)

    def _format_section_html(self, section: ReportSection) -> str:
        """Render one ReportSection as a chapter-block HTML."""
        parts = [
            f"<div class='chapter-block'>"
            f"<div class='chapter-title'>{self._escape_html(section.chapter_title)}</div>"
        ]
        if section.summary:
            parts.append(
                f"<div class='summary'>{self._escape_html(section.summary)}</div>")
        if section.narrative:
            parts.append(
                f"<h4>Narrative</h4>"
                f"<div class='narrative'>{self._escape_html(section.narrative)}</div>")
        if section.findings:
            parts.append("<h4>Findings</h4><ul class='findings'>")
            for f in section.findings:
                ok = "Risk:" not in f and "exceed" not in f.lower() and "below" not in f.lower()
                cls = " class='ok'" if ok else ""
                parts.append(
                    f"<li{cls}>{self._escape_html(f)}</li>")
            parts.append("</ul>")
        if section.suggestions:
            parts.append("<h4>Suggested actions</h4><ul class='suggestions'>")
            for s in section.suggestions:
                parts.append(f"<li>{self._escape_html(s)}</li>")
            parts.append("</ul>")
        if section.metrics:
            parts.append("<h4>Metrics</h4><table class='metric-table'>")
            for k, v in section.metrics.items():
                if isinstance(v, float):
                    val = f"{v:.2f}"
                elif isinstance(v, list):
                    val = ", ".join(str(x) for x in v)
                else:
                    val = str(v)
                parts.append(
                    f"<tr><td>{self._escape_html(k.replace('_', ' '))}</td>"
                    f"<td>{self._escape_html(val)}</td></tr>")
            parts.append("</table>")
        parts.append("</div>")
        return "\n".join(parts)

    @staticmethod
    def _escape_html(text: Any) -> str:
        """Minimal HTML escape; preserves newlines for narrative blocks."""
        if text is None:
            return ""
        s = str(text)
        return (s.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;")
                 .replace("\n", "<br>"))

    # ── Save / Load / Export for CritiqueReport ──────────────────

    def _save_critique_results(self):
        """Persist the most recent CritiqueReport into the metadata store."""
        if not self._last_report:
            QMessageBox.warning(
                self, "No Critique", "No critique results to save.")
            return
        if not self._project_path:
            QMessageBox.warning(
                self, "No Project", "Please save your project first.")
            return
        chapter_title = (
            self._last_report.chapters[0].chapter_title
            if self._last_report.chapters else "Custom Text")
        critique_data = self._serialize_report(self._last_report)
        critique_id = self._metadata_store.save_critique(
            self._project_path,
            chapter_title,
            critique_data,
            critique_type="reports",
        )
        self.saved_critique_label.setText(f"✓ Saved ({critique_id})")

    def _load_critique_results(self):
        """Load a previously saved CritiqueReport from the metadata store."""
        if not self._project_path:
            QMessageBox.warning(
                self, "No Project", "Please open a project first.")
            return
        from PyQt6.QtWidgets import QInputDialog
        from datetime import datetime
        # Aggregate critiques across chapters so the picker can show
        # everything saved for this project at once.
        all_entries: List[tuple] = []  # (label, chapter_title, id)
        if (self.project and self.project.manuscript
                and self.project.manuscript.chapters):
            chapter_titles = [c.title for c in self.project.manuscript.chapters]
        else:
            chapter_titles = []
        if self._current_chapter_title:
            chapter_titles.append(self._current_chapter_title)
        chapter_titles.extend(["Custom Text"])
        seen = set()
        for ct in chapter_titles:
            if ct in seen:
                continue
            seen.add(ct)
            for c in self._metadata_store.list_critiques(
                    self._project_path, ct):
                try:
                    dt = datetime.fromisoformat(c["timestamp"])
                    pretty = dt.strftime("%b %d, %Y %I:%M %p")
                except (ValueError, KeyError):
                    pretty = c.get("timestamp", "?")
                all_entries.append(
                    (f"[{ct}] {pretty} ({c.get('type', '?')})",
                     ct, c["id"]))
        if not all_entries:
            QMessageBox.information(
                self, "No Saved Critiques",
                "No saved critiques found for this project.")
            return
        # Most recent first
        all_entries.sort(key=lambda e: e[2], reverse=True)
        labels = [e[0] for e in all_entries]
        selected, ok = QInputDialog.getItem(
            self, "Load Critique",
            "Select a saved critique to load:",
            labels, 0, False)
        if not ok or not selected:
            return
        idx = labels.index(selected)
        _, ct, cid = all_entries[idx]
        entry = self._metadata_store.get_critique(
            self._project_path, ct, cid)
        if not entry or "data" not in entry:
            QMessageBox.warning(
                self, "Load Failed",
                "Could not load the selected critique.")
            return
        try:
            report = self._deserialize_report(entry["data"])
            self._last_report = report
            self._render_critique_report(report)
            self.save_critique_btn.setEnabled(True)
            self.export_btn.setEnabled(True)
            try:
                dt = datetime.fromisoformat(entry["timestamp"])
                pretty = dt.strftime("%b %d %I:%M %p")
            except (ValueError, KeyError):
                pretty = "unknown time"
            self.saved_critique_label.setText(f"Loaded from {pretty}")
        except Exception as e:
            QMessageBox.warning(
                self, "Load Failed", f"Error loading critique: {e}")

    def _serialize_report(self, report: CritiqueReport) -> Dict[str, Any]:
        """Convert a CritiqueReport to a JSON-safe dict."""
        return {
            "schema_version": 2,
            "genre_key": report.genre.key,
            "has_llm": report.has_llm,
            "overall_summary": report.overall_summary,
            "estimated_cost": report.estimated_cost,
            "chapters": [
                {
                    "chapter_title": c.chapter_title,
                    "chapter_index": c.chapter_index,
                    "word_count": c.word_count,
                    "sections": [
                        {
                            "report_type": s.report_type.value,
                            "summary": s.summary,
                            "narrative": s.narrative,
                            "metrics": s.metrics,
                            "findings": s.findings,
                            "suggestions": s.suggestions,
                        }
                        for s in c.sections
                    ],
                }
                for c in report.chapters
            ],
        }

    def _deserialize_report(self, data: Dict[str, Any]) -> CritiqueReport:
        """Rehydrate a CritiqueReport from saved JSON."""
        genre_key = data.get("genre_key", "default")
        genre = (GENRE_PROFILES.get(genre_key)
                 or GENRE_PROFILES["default"])
        chapters: List[ChapterReport] = []
        for c in data.get("chapters", []):
            sections = []
            for s in c.get("sections", []):
                try:
                    rt = ReportType(s.get("report_type", "style"))
                except ValueError:
                    rt = ReportType.STYLE
                sections.append(ReportSection(
                    report_type=rt,
                    chapter_title=c.get("chapter_title", ""),
                    chapter_index=c.get("chapter_index", 0),
                    summary=s.get("summary", ""),
                    narrative=s.get("narrative", ""),
                    metrics=s.get("metrics", {}) or {},
                    findings=s.get("findings", []) or [],
                    suggestions=s.get("suggestions", []) or [],
                ))
            chapters.append(ChapterReport(
                chapter_title=c.get("chapter_title", ""),
                chapter_index=c.get("chapter_index", 0),
                word_count=c.get("word_count", 0),
                sections=sections,
            ))
        return CritiqueReport(
            chapters=chapters,
            genre=genre,
            overall_summary=data.get("overall_summary", ""),
            has_llm=data.get("has_llm", False),
            estimated_cost=data.get("estimated_cost", 0.0),
        )

    def _export_critique(self):
        """Export the current CritiqueReport to a Markdown file."""
        if not self._last_report:
            QMessageBox.warning(self, "No Critique", "No critique to export.")
            return
        first_title = (
            self._last_report.chapters[0].chapter_title
            if self._last_report.chapters else "custom")
        suggested_name = (
            f"critique_{first_title or 'custom'}.md".replace(" ", "_"))
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Critique", suggested_name,
            "Markdown (*.md);;Text (*.txt)")
        if not file_path:
            return
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self._format_report_markdown(self._last_report))
            QMessageBox.information(
                self, "Export Complete",
                f"Critique exported to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(
                self, "Export Failed",
                f"Failed to export critique:\n{e}")

    def _format_report_markdown(self, report: CritiqueReport) -> str:
        """Render a CritiqueReport as Markdown for export."""
        out = ["# Writing Critique Report",
               "",
               f"**Genre profile:** {report.genre.name} — {report.genre.notes}",
               f"**Mode:** "
               + ("LLM-narrative" if report.has_llm else "Dashboard"),
               ""]
        if report.overall_summary:
            out.extend(["## Overall Summary", "",
                        report.overall_summary, ""])
        for c in report.chapters:
            out.append(f"## {c.chapter_title}")
            out.append(
                f"*{c.word_count:,} words · "
                f"{len(c.sections)} report section(s)*\n")
            for s in c.sections:
                label = self.REPORT_TAB_LABELS.get(
                    s.report_type, s.report_type.value.title())
                out.append(f"### {label}")
                if s.summary:
                    out.append(s.summary + "\n")
                if s.narrative:
                    out.append(s.narrative + "\n")
                if s.findings:
                    out.append("**Findings:**\n")
                    out.extend([f"- {f}" for f in s.findings])
                    out.append("")
                if s.suggestions:
                    out.append("**Suggested actions:**\n")
                    out.extend([f"- {x}" for x in s.suggestions])
                    out.append("")
                if s.metrics:
                    out.append("**Metrics:**\n")
                    for k, v in s.metrics.items():
                        if isinstance(v, float):
                            out.append(f"- {k}: {v:.2f}")
                        else:
                            out.append(f"- {k}: {v}")
                    out.append("")
        return "\n".join(out)

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

        # Note: the legacy ``askabout:`` and line-item link handlers
        # were removed when the old line-by-line flow was replaced
        # with the report-driven critique. The current report HTML
        # doesn't emit those links.

    def load_data(self, data):
        """Load grader data (placeholder for future use)."""

    def get_data(self):
        """Get grader data (placeholder for future use)."""
        return None
