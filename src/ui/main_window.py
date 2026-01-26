"""Main application window for Writer Platform."""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QTabWidget,
    QMenu, QFileDialog, QMessageBox, QToolBar, QSplitter,
    QLabel, QSystemTrayIcon
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QThread
from PyQt6.QtGui import QAction, QKeySequence, QIcon
from pathlib import Path
from typing import Optional

from src.models.project import WriterProject, Manuscript
from src.ui.comprehensive_worldbuilding_widget import ComprehensiveWorldBuildingWidget
from src.ui.characters_widget import CharactersWidget
from src.ui.story_planning_widget import StoryPlanningWidget
from src.ui.manuscript_editor import ManuscriptEditor
from src.ui.image_generator_widget import ImageGeneratorWidget
from src.ui.grader_widget import GraderWidget
from src.ui.agent_manager_widget import AgentManagerWidget
from src.ui.find_replace_dialog import FindReplaceDialog
from src.ui.settings_dialog import SettingsDialog
from src.ui.chat_widget import ChatWidget
from src.ui.attributions_tab import AttributionsTab
from src.ui.window_manager import WindowManager
from src.ui.secondary_window import SecondaryWindow
from src.ui.import_guide_dialog import ImportGuideDialog
from src.ui.json_import_dialog import JSONImportDialog
from src.export.manuscript_exporter import ManuscriptExporter
from src.export.llm_context_exporter import LLMContextExporter
from src.ui.export_summary_dialog import ExportSummaryDialog
from src.ui.styles import get_modern_style, get_icon
from src.config import get_ai_config


class ChatWorker(QThread):
    """Background worker for AI chat operations with full project context."""
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    # System prompts for different modes
    SYSTEM_PROMPTS = {
        "general": """You are a helpful creative writing assistant integrated into a writer's platform.
You have access to the author's full project context including plot, characters, worldbuilding, and manuscript chapters.

You help authors with:
- Answering questions about their story, characters, and world
- Analyzing chapters for consistency, pacing, and character development
- Brainstorming ideas that fit their established story
- Providing feedback on specific passages or the overall narrative
- Suggesting improvements that align with their style and voice
- Identifying plot holes or inconsistencies across chapters

Be encouraging, creative, and constructive. Reference specific details from their project when relevant.
Keep responses focused and actionable.""",

        "chapter_focus": """You are a focused chapter editor and writing coach. You are helping the author work on their CURRENT CHAPTER.

Your role is to:
- Answer specific questions about this chapter's content, pacing, and structure
- Help identify issues with character voice, dialogue, or scene transitions
- Suggest improvements to specific paragraphs or sections
- Check consistency with established characters, plot points, and world details
- Help with word choice, sentence rhythm, and prose flow
- Identify areas that need more development or could be tightened

Focus your responses specifically on the current chapter. When referencing the broader story, explain how it connects to this chapter.
Be specific and cite passages when giving feedback. Maintain the author's voice and style.""",

        "writer": """You are a skilled creative writer working as a ghostwriter/collaborator. Your job is to WRITE prose based on the author's outline, world, and characters.

=== SCENE-BY-SCENE WRITING ===
If a CHAPTER OUTLINE or SCENE LIST is provided:
1. Write each scene as a complete, immersive unit
2. Follow the scene order in the outline
3. Flesh out each scene with rich sensory details, character actions, and dialogue
4. Create smooth, natural transitions between scenes (time skips, location changes, or flowing action)
5. Mark your progress: mention which scene you're writing if continuing later

If NO outline is provided:
1. Infer the scene structure from the user's prompt
2. Break the writing into logical scenes with clear beats
3. Ask clarifying questions if the scene direction is unclear

=== POINT OF VIEW - STRICT REQUIREMENT ===
You MUST follow the specified NARRATIVE POV exactly. This is non-negotiable.

NARRATIVE POV RULES:
- FIRST PERSON: Use "I/we/my/me". The POV character narrates their own story.
- THIRD PERSON LIMITED: Use "he/she/they/his/her/their" for the POV character. NEVER use "I" or "my" except in dialogue. Write their thoughts as: "She wondered if..." NOT "I wonder if..."
- THIRD PERSON OMNISCIENT: Use "he/she/they". Can access multiple characters' thoughts.
- SECOND PERSON: Use "you/your". The reader is the protagonist.

CRITICAL: If Third Person is specified, NEVER write "I thought" or "I felt" or "I saw" outside of dialogue. Use the character's name or pronouns: "Marcus thought", "She felt", "He saw".

CHARACTER POV: Write from this character's perspective only. The reader experiences the story through their senses and thoughts (but in the correct narrative voice).

If TEXT BEFORE CURSOR is provided:
- Match the existing narrative voice and pronouns exactly
- Continue mid-sentence or mid-paragraph if that's where it ends
- Maintain the same tense (past/present) as the existing text
- If the existing text uses "she/he", continue using "she/he" - do NOT switch to "I"

=== SHOW DON'T TELL - CRITICAL ===
NEVER write: "She felt angry" or "He was nervous"
INSTEAD write: "Her jaw tightened, fingers curling into fists" or "He drummed his fingers on the table, eyes darting to the door"

Apply this to:
- Emotions: Show through body language, actions, dialogue subtext, physiological responses
- Character traits: Reveal through choices, reactions, and speech patterns
- Atmosphere: Build through sensory details (what they see, hear, smell, feel, taste)
- Backstory: Weave in through natural conversation, memories triggered by present events
- Relationships: Demonstrate through interactions, not exposition

=== WRITING STYLE (from chapter planning) ===
If WRITING STYLE metadata is provided in the context (Tone, Voice, Style, Pacing), follow it exactly:
- TONE: The emotional quality/mood to convey (e.g., "dark and brooding", "lighthearted", "tense")
- VOICE: The narrative personality (e.g., "sardonic", "lyrical", "matter-of-fact")
- STYLE: Prose approach (e.g., "short punchy sentences", "flowery descriptions", "sparse")
- PACING: How fast scenes should move (e.g., "slow contemplative", "rapid-fire action")

If no style metadata is provided, analyze the existing chapter content to match the author's established style.

=== PROSE GUIDELINES ===
1. Follow the specified Tone, Voice, Style, and Pacing from WRITING STYLE above
2. Stay consistent with characters - their voice, speech patterns, motivations, quirks
3. Incorporate worldbuilding naturally through character interaction with the environment
4. Write natural, character-appropriate dialogue with distinct voices
5. Maintain POV consistency throughout

=== SCENE STRUCTURE ===
Each scene should have:
- A clear goal or purpose (what changes by the end?)
- Grounding in setting (where are we? what's the atmosphere?)
- Character action and reaction
- Tension or forward momentum
- A hook or pivot point leading to the next beat

=== TRANSITIONS ===
Between scenes, use:
- Time transitions: "Three days later..." or "By the time the sun set..."
- Space transitions: Describe arrival at new location through character senses
- Emotional bridges: End one scene with an emotion, begin next with its consequence
- Action continuity: End mid-action, resume with result

=== OUTPUT FORMAT - CRITICAL ===
Output ONLY the prose content. Do NOT include:
- Chapter titles, headers, or "Chapter X" labels
- Scene numbers, scene headings, or "Scene X" labels
- The prompts or instructions you were given
- Metadata, notes, or author commentary
- Preambles like "Here's the scene..." or "I'll write..."
- Closing remarks like "Let me know if you want more..."

Just write the prose exactly as it would appear in the final manuscript.

When asked to write:
- Produce actual prose, not summaries
- Write at least several paragraphs per scene
- End at a natural scene break or beat

When asked to continue:
- Pick up exactly where the text ends
- If mid-scene, complete it before transitioning
- Maintain narrative momentum"""
    }

    def __init__(self, message: str, context: dict = None, mode: str = "general"):
        super().__init__()
        self.message = message
        self.context = context or {}
        self.mode = mode

    def _build_context_prompt(self) -> str:
        """Build comprehensive context from project data."""
        parts = []

        # Project info
        if self.context.get('project_name'):
            parts.append(f"PROJECT: {self.context['project_name']}")
            if self.context.get('project_description'):
                parts.append(f"Description: {self.context['project_description'][:300]}")

        # Plot/Story planning
        if self.context.get('plot_summary'):
            parts.append(f"\nPLOT OUTLINE:\n{self.context['plot_summary'][:2000]}")

        # Characters
        if self.context.get('characters'):
            chars = self.context['characters'][:1500]
            parts.append(f"\nMAIN CHARACTERS:\n{chars}")

        # Worldbuilding
        if self.context.get('worldbuilding'):
            wb = self.context['worldbuilding'][:1500]
            parts.append(f"\nWORLDBUILDING:\n{wb}")

        # Current chapter context
        if self.context.get('current_chapter_title'):
            parts.append(f"\nCURRENT CHAPTER: {self.context['current_chapter_title']}")

            # Chapter planning/outline (critical for writer mode)
            if self.context.get('chapter_planning'):
                planning = self.context['chapter_planning']
                parts.append("\n=== CHAPTER OUTLINE (Follow this scene-by-scene) ===")

                if planning.get('description'):
                    parts.append(f"Chapter Goal: {planning['description']}")

                if planning.get('pov_character'):
                    parts.append(f"POV Character: {planning['pov_character']}")

                if planning.get('scene_list'):
                    parts.append("\nSCENE LIST (write in order):")
                    for i, scene in enumerate(planning['scene_list'], 1):
                        parts.append(f"  {i}. {scene}")

                if planning.get('events'):
                    parts.append("\nSTORY EVENTS/BEATS:")
                    for event in planning['events']:
                        status = "✓" if event.get('completed') else "○"
                        parts.append(f"  {status} {event['text']}")
                        if event.get('description'):
                            parts.append(f"      {event['description'][:150]}")

                if planning.get('outline') and not planning.get('scene_list'):
                    # Fallback to text outline if no scene list
                    parts.append(f"\nOUTLINE:\n{planning['outline'][:1000]}")

                if planning.get('characters_featured'):
                    parts.append(f"\nFeatured Characters: {', '.join(planning['characters_featured'])}")

                if planning.get('locations'):
                    parts.append(f"Locations: {', '.join(planning['locations'])}")

                if planning.get('themes'):
                    parts.append(f"Themes: {', '.join(planning['themes'])}")

                # Writing style metadata (critical for writer mode)
                style_parts = []
                if planning.get('tone'):
                    style_parts.append(f"Tone: {planning['tone']}")
                if planning.get('voice'):
                    style_parts.append(f"Voice: {planning['voice']}")
                if planning.get('style'):
                    style_parts.append(f"Style: {planning['style']}")
                if planning.get('pacing'):
                    style_parts.append(f"Pacing: {planning['pacing']}")

                if style_parts:
                    parts.append("\n=== WRITING STYLE (Follow these guidelines) ===")
                    parts.extend(style_parts)

            # Writer mode: POV settings (override chapter defaults if specified)
            if self.mode == "writer":
                pov_parts = []
                char_pov = self.context.get('writer_character_pov')
                narrative_pov = self.context.get('writer_narrative_pov')

                if char_pov:
                    pov_parts.append(f"Character POV: {char_pov}")
                elif planning and planning.get('pov_character'):
                    pov_parts.append(f"Character POV: {planning['pov_character']} (from chapter)")

                if narrative_pov:
                    pov_map = {
                        'first_person': 'First Person (I/we)',
                        'third_person_limited': 'Third Person Limited (follows one character)',
                        'third_person_omniscient': 'Third Person Omniscient (all-knowing)',
                        'second_person': 'Second Person (you)'
                    }
                    pov_parts.append(f"Narrative POV: {pov_map.get(narrative_pov, narrative_pov)}")

                if pov_parts:
                    parts.append("\n=== POINT OF VIEW ===\n" + "\n".join(pov_parts))

            # Writer mode: Preceding text for continuity
            if self.mode == "writer" and self.context.get('preceding_text'):
                parts.append(f"\n=== TEXT IMMEDIATELY BEFORE CURSOR (continue from here) ===\n{self.context['preceding_text']}")

                if self.context.get('content_before_summary'):
                    parts.append(f"\n{self.context['content_before_summary']}")

            # Previous chapter ending for continuity
            if self.context.get('previous_chapter_ending'):
                parts.append(f"\n=== PREVIOUS CHAPTER ENDING (for continuity) ===\n...{self.context['previous_chapter_ending']}")

            # Current chapter content
            if self.context.get('current_chapter_content'):
                content = self.context['current_chapter_content']
                if len(content) > 2000:
                    parts.append(f"\n=== CURRENT CHAPTER CONTENT ===\n{content[:1000]}...")
                    parts.append(f"...(content continues)...\n...{content[-500:]}")
                else:
                    parts.append(f"\n=== CURRENT CHAPTER CONTENT ===\n{content}")

        # All chapters summary (for cross-chapter questions)
        if self.context.get('all_chapters'):
            chapters_info = self.context['all_chapters'][:1500]
            parts.append(f"\nMANUSCRIPT CHAPTERS:\n{chapters_info}")

        return "\n".join(parts) if parts else ""

    def run(self):
        """Process the chat message with AI."""
        try:
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
                provider = provider_map.get(default_provider, LLMProvider.CLAUDE)

                llm = LLMClient(
                    provider=provider,
                    api_key=api_key,
                    model=ai_config.get_model(default_provider)
                )

            # Build system prompt based on mode
            system_prompt = self.SYSTEM_PROMPTS.get(self.mode, self.SYSTEM_PROMPTS["general"])

            # Add project context
            context_prompt = self._build_context_prompt()
            if context_prompt:
                system_prompt += f"\n\n{'='*60}\nPROJECT CONTEXT:\n{'='*60}\n{context_prompt}"

            # For writer mode, add extra emphasis on current chapter
            if self.mode == "writer" and self.context.get('current_chapter_content'):
                system_prompt += "\n\nIMPORTANT: Write prose that seamlessly continues or fits with the existing chapter content above."

            # Generate response
            response = llm.generate_text(
                prompt=self.message,
                system_prompt=system_prompt,
                max_tokens=settings.get("max_tokens", 2000),
                temperature=settings.get("temperature", 0.7)
            )

            self.finished.emit(response)

        except Exception as e:
            self.error.emit(f"Error: {str(e)}")


class MainWindow(QMainWindow):
    """Main application window with all features."""

    project_changed = pyqtSignal()

    def __init__(self):
        """Initialize main window."""
        super().__init__()

        self.current_project: Optional[WriterProject] = None
        self.ai_config = get_ai_config()
        self.settings = self.ai_config.get_settings()

        # Find/Replace dialogs
        self.find_dialog: Optional[FindReplaceDialog] = None
        self.replace_dialog: Optional[FindReplaceDialog] = None

        # Chat worker for AI assistant
        self._chat_worker: Optional[ChatWorker] = None
        self._pending_mode: str = ""
        self._pending_insert_mode: str = ""

        # Register with window manager
        self.window_manager = WindowManager()
        self.window_manager.set_main_window(self)

        # Apply modern stylesheet
        self.setStyleSheet(get_modern_style())

        self._init_ui()
        self._create_menus()
        self._create_minimal_toolbar()
        self._create_status_bar()
        self._setup_system_tray()

        # Try to load last project, or prompt for new one
        self._startup_load_project()

    def _init_ui(self):
        """Initialize user interface."""
        self.setWindowTitle("Writer Platform")
        self.setMinimumSize(800, 600)  # Reduced from 1200x800 for laptop compatibility

        # Create central widget with splitter for chat
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create splitter for main content and chat
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Create tab widget for main sections with modern styling
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.tab_widget.setDocumentMode(True)  # Cleaner look
        self.tab_widget.setMovable(True)  # Allow tab reordering

        # Enable context menu on tab bar for multi-window support
        self.tab_widget.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_widget.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)

        # Initialize section widgets
        self.worldbuilding_widget = ComprehensiveWorldBuildingWidget()
        self.characters_widget = CharactersWidget()
        self.story_planning_widget = StoryPlanningWidget()
        self.manuscript_editor = ManuscriptEditor()
        self.image_generator = ImageGeneratorWidget()
        self.grader_widget = GraderWidget()
        self.agent_manager = AgentManagerWidget()
        self.attributions_tab = AttributionsTab()

        # Connect grader widget signals
        self.grader_widget.go_to_line_requested.connect(self._go_to_critique_line)

        # Connect attributions tab jump signal
        self.attributions_tab.jump_to_annotation.connect(self._jump_to_annotation)

        # Add tabs with icons for visual appeal
        self.tab_widget.addTab(self.manuscript_editor, f"{get_icon('manuscript')} Write")
        self.tab_widget.addTab(self.story_planning_widget, f"{get_icon('story')} Plot")
        self.tab_widget.addTab(self.characters_widget, f"{get_icon('characters')} Characters")
        self.tab_widget.addTab(self.worldbuilding_widget, f"{get_icon('worldbuilding')} World")
        self.tab_widget.addTab(self.attributions_tab, "📚 Attributions")
        self.tab_widget.addTab(self.image_generator, f"{get_icon('images')} Visuals")
        self.tab_widget.addTab(self.grader_widget, f"{get_icon('grader')} Critique")
        self.tab_widget.addTab(self.agent_manager, f"{get_icon('agents')} Publishing")

        # Create collapsible chat widget
        self.chat_widget = ChatWidget()
        self.chat_widget.setMaximumWidth(400)
        self.chat_widget.setMinimumWidth(300)

        # Add to splitter
        self.main_splitter.addWidget(self.tab_widget)
        self.main_splitter.addWidget(self.chat_widget)

        # Set initial splitter sizes (3:1 ratio)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 1)

        main_layout.addWidget(self.main_splitter)

        # Connect signals
        self._connect_signals()

    def _create_menus(self):
        """Create application menus."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        new_action = QAction("&New Project", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self._new_project)
        file_menu.addAction(new_action)

        open_action = QAction("&Open Project", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_project)
        file_menu.addAction(open_action)

        save_action = QAction("&Save Project", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self._save_project)
        file_menu.addAction(save_action)

        save_as_action = QAction("Save Project &As...", self)
        save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_as_action.triggered.connect(self._save_project_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")

        find_action = QAction("&Find...", self)
        find_action.setShortcut(QKeySequence.StandardKey.Find)
        find_action.triggered.connect(self._show_find_dialog)
        edit_menu.addAction(find_action)

        replace_action = QAction("Find and &Replace...", self)
        replace_action.setShortcut(QKeySequence.StandardKey.Replace)
        replace_action.triggered.connect(self._show_replace_dialog)
        edit_menu.addAction(replace_action)

        edit_menu.addSeparator()

        settings_action = QAction("&Settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._show_settings)
        edit_menu.addAction(settings_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        toggle_chat_action = QAction("Toggle &Chat", self)
        toggle_chat_action.setShortcut(QKeySequence("Ctrl+B"))
        toggle_chat_action.triggered.connect(self._toggle_chat)
        view_menu.addAction(toggle_chat_action)

        view_menu.addSeparator()

        # Multi-window mode toggle
        self.multi_window_action = QAction("&Multi-Window Mode", self)
        self.multi_window_action.setCheckable(True)
        self.multi_window_action.setChecked(False)
        self.multi_window_action.setToolTip("Enable to detach tabs into separate windows")
        self.multi_window_action.triggered.connect(self._toggle_multi_window_mode)
        view_menu.addAction(self.multi_window_action)

        # Export menu
        export_menu = menubar.addMenu("E&xport")

        export_kindle_action = QAction("Export for &Kindle", self)
        export_kindle_action.triggered.connect(lambda: self._export_manuscript("kindle"))
        export_menu.addAction(export_kindle_action)

        export_bn_action = QAction("Export for &Barnes && Noble", self)
        export_bn_action.triggered.connect(lambda: self._export_manuscript("barnes_noble"))
        export_menu.addAction(export_bn_action)

        export_publisher_action = QAction("Export &Publisher Ready", self)
        export_publisher_action.triggered.connect(lambda: self._export_manuscript("publisher"))
        export_menu.addAction(export_publisher_action)

        export_docx_action = QAction("Export as &Word Document", self)
        export_docx_action.triggered.connect(lambda: self._export_manuscript("docx"))
        export_menu.addAction(export_docx_action)

        export_menu.addSeparator()

        export_outline_action = QAction("Export Book &Outline (Chapter Plans)", self)
        export_outline_action.setToolTip("Export all chapter plans as a book outline document")
        export_outline_action.triggered.connect(self._export_book_outline)
        export_menu.addAction(export_outline_action)

        export_menu.addSeparator()

        export_llm_action = QAction("Export for &LLM Context (Markdown)", self)
        export_llm_action.setToolTip("Export worldbuilding, plot, and characters as markdown for AI context")
        export_llm_action.triggered.connect(self._export_llm_context)
        export_menu.addAction(export_llm_action)

        export_summary_action = QAction("Export Project &Summary...", self)
        export_summary_action.setToolTip("Export comprehensive project summary with optional AI/ML summarization")
        export_summary_action.triggered.connect(self._export_project_summary)
        export_menu.addAction(export_summary_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        import_guide_action = QAction("&Import Guide (AI Prompts)", self)
        import_guide_action.setToolTip("Prompts to help build your project with ChatGPT, Claude, or other AI assistants")
        import_guide_action.triggered.connect(self._show_import_guide)
        help_menu.addAction(import_guide_action)

        import_json_action = QAction("Import &JSON Data...", self)
        import_json_action.setToolTip("Import AI-generated JSON data into your project")
        import_json_action.triggered.connect(self._show_json_import)
        help_menu.addAction(import_json_action)

        help_menu.addSeparator()

        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_minimal_toolbar(self):
        """Create minimal, modern toolbar."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(toolbar.iconSize() * 0.9)  # Slightly smaller icons
        self.addToolBar(toolbar)

        # Project name label (editable feel)
        self.project_name_label = QLabel("Untitled Project")
        self.project_name_label.setProperty("heading", True)
        self.project_name_label.setStyleSheet("padding: 4px 12px; font-size: 18px; font-weight: 600;")
        toolbar.addWidget(self.project_name_label)

        toolbar.addSeparator()

        # Minimal action buttons with icons
        save_action = QAction(f"{get_icon('save')} Save", self)
        save_action.setToolTip("Save Project (Ctrl+S)")
        save_action.triggered.connect(self._save_project)
        toolbar.addAction(save_action)

        export_action = QAction(f"{get_icon('export')} Export", self)
        export_action.setToolTip("Export manuscript")
        export_action.triggered.connect(lambda: self._export_manuscript("publisher"))
        toolbar.addAction(export_action)

        toolbar.addSeparator()

        # AI toggle
        ai_action = QAction(f"{get_icon('ai')} AI", self)
        ai_action.setToolTip("Toggle AI Assistant (Ctrl+B)")
        ai_action.triggered.connect(self._toggle_chat)
        toolbar.addAction(ai_action)

        toolbar.addSeparator()

        # Settings
        settings_action = QAction(f"{get_icon('settings')} Settings", self)
        settings_action.setToolTip("Settings & Configuration (Ctrl+,)")
        settings_action.triggered.connect(self._show_settings)
        toolbar.addAction(settings_action)

    def _create_status_bar(self):
        """Create status bar."""
        self.statusBar().showMessage("Ready")

    def _setup_system_tray(self):
        """Set up the system tray icon and menu."""
        # Check if system tray is available
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("System tray is not available")
            return

        # Load icon - try PNG first (better compatibility), then ICO
        assets_dir = Path(__file__).parent.parent.parent / "assets"
        icon_path = assets_dir / "icon.png"
        if not icon_path.exists():
            icon_path = assets_dir / "icon.ico"

        if icon_path.exists():
            icon = QIcon(str(icon_path))
        else:
            # Fallback to application icon
            icon = self.windowIcon()
            print(f"Icon not found at {icon_path}, using window icon")

        # Create system tray icon
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("Writer Platform")

        # Create tray menu
        tray_menu = QMenu()

        # Show/Hide action
        show_action = QAction("Show/Hide", self)
        show_action.triggered.connect(self._toggle_window_visibility)
        tray_menu.addAction(show_action)

        tray_menu.addSeparator()

        # Quick actions
        save_action = QAction("Save Project", self)
        save_action.triggered.connect(self._save_project)
        tray_menu.addAction(save_action)

        tray_menu.addSeparator()

        # Exit action
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self._quit_application)
        tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(tray_menu)

        # Double-click to show/hide
        self.tray_icon.activated.connect(self._on_tray_activated)

        # Show the tray icon
        self.tray_icon.show()

    def _toggle_window_visibility(self):
        """Toggle main window visibility."""
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def _on_tray_activated(self, reason):
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_window_visibility()

    def _quit_application(self):
        """Quit the application properly."""
        # Check for unsaved changes
        if self.current_project and not self._confirm_unsaved_changes():
            return

        # Hide tray icon
        if hasattr(self, 'tray_icon'):
            self.tray_icon.hide()

        # Close the application
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()

    def _connect_signals(self):
        """Connect signals between widgets."""
        # Connect project changes
        self.worldbuilding_widget.content_changed.connect(self._on_content_changed)
        self.characters_widget.content_changed.connect(self._on_content_changed)
        self.story_planning_widget.content_changed.connect(self._on_content_changed)
        self.manuscript_editor.content_changed.connect(self._on_content_changed)

        # Connect annotation changes to update attributions tab
        self.manuscript_editor.annotations_changed.connect(self._on_annotations_changed)

        # Auto-save when switching chapters
        self.manuscript_editor.chapter_switched.connect(self._auto_save_project)

        # Update grader widget when switching to Critique tab
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        # Connect chat to AI assistance
        self.chat_widget.message_sent.connect(self._handle_chat_message)

        # Connect manuscript editor selection changes to chat widget
        self._setup_editor_selection_tracking()

    def _setup_editor_selection_tracking(self):
        """Set up tracking of editor selection state for Writer mode."""
        # This will be called again when chapter changes
        if hasattr(self, 'manuscript_editor') and self.manuscript_editor.current_chapter_editor:
            editor = self.manuscript_editor.current_chapter_editor.editor
            editor.selectionChanged.connect(self._on_editor_selection_changed)

    def _on_editor_selection_changed(self):
        """Handle editor selection change - update chat widget."""
        if hasattr(self, 'manuscript_editor') and self.manuscript_editor.current_chapter_editor:
            editor = self.manuscript_editor.current_chapter_editor.editor
            has_selection = editor.textCursor().hasSelection()
            self.chat_widget.update_selection_state(has_selection)

    def _startup_load_project(self):
        """Load last project on startup, or prompt for new one."""
        from pathlib import Path

        last_path = self.ai_config.get_last_project_path()

        if last_path and Path(last_path).exists():
            try:
                self.current_project = WriterProject.load_project(last_path)
                self._load_project_into_ui()
                self.project_name_label.setText(self.current_project.name)
                self.statusBar().showMessage(f"Loaded: {last_path}")
                return
            except Exception as e:
                # Failed to load, will prompt for new project
                QMessageBox.warning(
                    self,
                    "Could Not Load Project",
                    f"Failed to load last project:\n{last_path}\n\nError: {str(e)}\n\nPlease create a new project."
                )

        # No last project or failed to load - prompt for new one
        self._new_project()

    def _new_project(self):
        """Create new project."""
        if self.current_project and not self._confirm_unsaved_changes():
            return

        from PyQt6.QtWidgets import QInputDialog

        project_name, ok = QInputDialog.getText(
            self, "New Project", "Enter project name:"
        )

        if ok and project_name:
            self.current_project = WriterProject(
                name=project_name,
                manuscript=Manuscript(title=project_name)
            )
            self._load_project_into_ui()
            self.project_name_label.setText(project_name)
            self.statusBar().showMessage(f"Created new project: {project_name}")

    def _open_project(self):
        """Open existing project."""
        if self.current_project and not self._confirm_unsaved_changes():
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Project",
            "",
            "Writer Project Files (*.writerproj);;All Files (*)"
        )

        if file_path:
            try:
                self.current_project = WriterProject.load_project(file_path)
                self._load_project_into_ui()
                self.project_name_label.setText(self.current_project.name)
                self.statusBar().showMessage(f"Opened: {file_path}")
                # Remember this project for next startup
                self.ai_config.set_last_project_path(file_path)
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Error Opening Project",
                    f"Failed to open project:\n{str(e)}"
                )

    def _save_project(self):
        """Save current project."""
        if not self.current_project:
            return

        if self.current_project.project_path:
            self._save_to_path(self.current_project.project_path)
        else:
            self._save_project_as()

    def _save_project_as(self):
        """Save project to new location."""
        if not self.current_project:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project As",
            f"{self.current_project.name}.writerproj",
            "Writer Project Files (*.writerproj);;All Files (*)"
        )

        if file_path:
            self._save_to_path(file_path)

    def _save_to_path(self, file_path: str):
        """Save project to specified path."""
        try:
            self._collect_project_data()
            self.current_project.save_project(file_path)
            self.statusBar().showMessage(f"Saved: {file_path}")
            # Remember this project for next startup
            self.ai_config.set_last_project_path(file_path)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error Saving Project",
                f"Failed to save project:\n{str(e)}"
            )

    def _auto_save_project(self):
        """Auto-save project (e.g., when switching chapters).

        Silently saves without showing status messages to avoid interrupting workflow.
        """
        if not self.current_project:
            return

        if self.current_project.project_path:
            try:
                self._collect_project_data()
                self.current_project.save_project(self.current_project.project_path)
                # Update window title to remove unsaved indicator
                self.setWindowTitle(f"Writer Platform - {self.current_project.name}")
            except Exception as e:
                # Log error but don't interrupt user
                print(f"Auto-save failed: {e}")

    def _load_project_into_ui(self):
        """Load current project data into UI widgets."""
        if not self.current_project:
            return

        # Set project reference on manuscript editor for RAG
        self.manuscript_editor.set_project(self.current_project)

        self.worldbuilding_widget.load_data(self.current_project.worldbuilding)
        self.characters_widget.load_data(self.current_project.characters)
        self.story_planning_widget.load_data(self.current_project.story_planning)
        self.manuscript_editor.load_manuscript(self.current_project.manuscript)
        self.image_generator.load_data(self.current_project.generated_images)
        # Update characters for image generation
        self.image_generator.set_characters(self.current_project.characters)
        self.agent_manager.load_data(self.current_project.agent_contacts)
        self.attributions_tab.set_manuscript(self.current_project.manuscript)

        # Set up grader widget with project reference
        self.grader_widget.set_project(self.current_project)

        # Update chat widget with characters for POV selection
        if self.current_project.characters:
            self.chat_widget.set_characters(self.current_project.characters)

        self.project_changed.emit()

    def _collect_project_data(self):
        """Collect data from UI widgets into project model."""
        if not self.current_project:
            return

        self.current_project.worldbuilding = self.worldbuilding_widget.get_data()
        self.current_project.characters = self.characters_widget.get_data()
        self.current_project.story_planning = self.story_planning_widget.get_data()
        self.current_project.manuscript = self.manuscript_editor.get_manuscript()
        self.current_project.generated_images = self.image_generator.get_data()
        self.current_project.agent_contacts = self.agent_manager.get_data()

    def _confirm_unsaved_changes(self) -> bool:
        """Ask user to confirm discarding unsaved changes."""
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "Do you want to save changes to the current project?",
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel
        )

        if reply == QMessageBox.StandardButton.Save:
            self._save_project()
            return True
        elif reply == QMessageBox.StandardButton.Discard:
            return True
        else:
            return False

    def _on_content_changed(self):
        """Handle content changes in any widget."""
        # Mark project as modified
        if self.current_project:
            window_title = f"Writer Platform - {self.current_project.name}*"
            self.setWindowTitle(window_title)

            # Update characters in image generator when characters change
            characters = self.characters_widget.get_data()
            self.image_generator.set_characters(characters)

    def _on_annotations_changed(self):
        """Handle annotation changes - update attributions tab."""
        if self.current_project:
            self.attributions_tab.set_manuscript(self.current_project.manuscript)
            self._on_content_changed()

    def _on_tab_changed(self, index: int):
        """Handle tab change - update grader widget with current chapter when Critique tab selected."""
        # Check if this is the Critique tab (index 6 based on tab order)
        current_widget = self.tab_widget.widget(index)
        if current_widget == self.grader_widget:
            # Update grader widget with current chapter content
            content, title = self.manuscript_editor.get_current_chapter_info()
            self.grader_widget.set_current_chapter(content, title)

        # Update editor selection tracking when manuscript tab is active
        if index == 0:  # Manuscript tab
            self._setup_editor_selection_tracking()

    def _toggle_chat(self):
        """Toggle chat widget visibility."""
        if self.chat_widget.isVisible():
            self.chat_widget.hide()
        else:
            self.chat_widget.show()

    def _handle_chat_message(self, message: str, mode: str = "general", insert_mode: str = ""):
        """Handle chat message from user.

        Args:
            message: The user's message
            mode: The chat mode (general, chapter_focus, writer)
            insert_mode: For writer mode, how to insert text (replace_selection, insert_at_cursor, append_to_chapter, replace_chapter)
        """
        # Check if already processing
        if self._chat_worker and self._chat_worker.isRunning():
            self.chat_widget.add_message("Assistant", "Please wait, I'm still thinking...")
            return

        # Build comprehensive project context based on mode
        context = self._build_chat_context(mode)

        # For writer mode, add POV settings and cursor context
        if mode == "writer":
            writer_settings = self.chat_widget.get_writer_settings()
            context['writer_character_pov'] = writer_settings.get('character_pov', '')
            context['writer_narrative_pov'] = writer_settings.get('writing_pov', '')

            # Get text before and after cursor for continuity
            if hasattr(self, 'manuscript_editor') and self.manuscript_editor.current_chapter_editor:
                editor = self.manuscript_editor.current_chapter_editor.editor
                cursor = editor.textCursor()
                full_text = editor.toPlainText()

                cursor_pos = cursor.position()
                text_before = full_text[:cursor_pos]
                text_after = full_text[cursor_pos:]

                # Get last 2-3 paragraphs before cursor for continuity
                paragraphs_before = text_before.split('\n\n')
                if paragraphs_before:
                    context['preceding_text'] = '\n\n'.join(paragraphs_before[-3:])[-1500:]

                # Summary of what's written so far
                if text_before:
                    word_count = len(text_before.split())
                    context['content_before_summary'] = f"[{word_count} words written before cursor]"

                # Store cursor position for context
                context['cursor_position'] = cursor_pos
                context['has_content_after'] = bool(text_after.strip())

        # Store insert mode for writer responses
        self._pending_insert_mode = insert_mode if mode == "writer" else ""
        self._pending_mode = mode

        # Show thinking indicator based on mode
        if mode == "writer":
            self.chat_widget.add_message("Assistant", "Writing...")
        elif mode == "chapter_focus":
            self.chat_widget.add_message("Assistant", "Analyzing chapter...")
        else:
            self.chat_widget.add_message("Assistant", "Thinking...")

        # Start background worker with mode
        self._chat_worker = ChatWorker(message, context, mode)
        self._chat_worker.finished.connect(self._on_chat_response)
        self._chat_worker.error.connect(self._on_chat_error)
        self._chat_worker.start()

    def _build_chat_context(self, mode: str = "general") -> dict:
        """Build comprehensive context dict for AI chat, similar to chapter planner.

        Args:
            mode: The chat mode (general, chapter_focus, writer)
        """
        context = {}
        context['mode'] = mode

        if not self.current_project:
            return context

        project = self.current_project

        # Basic project info
        context['project_name'] = project.name
        context['project_description'] = project.description or ""

        # For chapter_focus and writer modes, we want MORE context about the current chapter
        is_chapter_focused = mode in ("chapter_focus", "writer")

        # Try to use AI-generated summaries if available (more efficient)
        use_ai_summary = (hasattr(project, 'ai_summary') and
                         project.ai_summary and
                         not project.ai_summary.is_empty())

        if use_ai_summary:
            summary = project.ai_summary
            context['plot_summary'] = summary.plot_summary or ""
            context['worldbuilding'] = summary.worldbuilding_summary or ""
            context['characters'] = summary.character_summary or ""
        else:
            # Fallback: extract from story planning and worldbuilding
            # Plot from story planning
            if hasattr(project, 'story_planning') and project.story_planning:
                plot_parts = []
                sp = project.story_planning
                if sp.main_plot:
                    plot_parts.append(f"Main Plot: {sp.main_plot}")
                if sp.themes:
                    plot_parts.append(f"Themes: {', '.join(sp.themes)}")
                if sp.subplots:
                    subplots = [f"- {s.title}: {s.description}" for s in sp.subplots[:5]]
                    plot_parts.append("Subplots:\n" + "\n".join(subplots))
                if sp.freytag_pyramid:
                    fp = sp.freytag_pyramid
                    if fp.exposition:
                        plot_parts.append(f"Exposition: {fp.exposition[:200]}")
                    if fp.climax:
                        plot_parts.append(f"Climax: {fp.climax[:200]}")
                context['plot_summary'] = "\n\n".join(plot_parts)

            # Characters - include more detail for writer mode
            if hasattr(project, 'characters') and project.characters:
                char_summaries = []
                char_limit = 15 if is_chapter_focused else 10
                for char in project.characters[:char_limit]:
                    if is_chapter_focused:
                        # Include more character detail for writing
                        char_info = f"- {char.name} ({char.character_type})"
                        if char.personality:
                            char_info += f"\n  Personality: {char.personality[:200]}"
                        if hasattr(char, 'speaking_style') and char.speaking_style:
                            char_info += f"\n  Speech: {char.speaking_style[:100]}"
                        if hasattr(char, 'motivations') and char.motivations:
                            char_info += f"\n  Motivations: {char.motivations[:100]}"
                    else:
                        char_info = f"- {char.name} ({char.character_type})"
                        if char.personality:
                            char_info += f": {char.personality[:100]}"
                    char_summaries.append(char_info)
                context['characters'] = "\n".join(char_summaries)

            # Worldbuilding - include more detail for writer mode
            if hasattr(project, 'worldbuilding') and project.worldbuilding:
                wb = project.worldbuilding
                wb_parts = []
                detail_limit = 500 if is_chapter_focused else 300
                if wb.mythology:
                    wb_parts.append(f"Mythology: {wb.mythology[:detail_limit]}")
                if wb.history:
                    wb_parts.append(f"History: {wb.history[:detail_limit]}")
                if wb.politics:
                    wb_parts.append(f"Politics: {wb.politics[:detail_limit]}")
                if wb.factions:
                    if is_chapter_focused:
                        faction_info = [f"{f.name}: {f.description[:100] if hasattr(f, 'description') and f.description else ''}" for f in wb.factions[:8]]
                    else:
                        faction_info = [f.name for f in wb.factions[:5]]
                    wb_parts.append(f"Factions: {', '.join(faction_info)}")
                if wb.places:
                    if is_chapter_focused:
                        place_info = [f"{p.name}: {p.description[:100] if hasattr(p, 'description') and p.description else ''}" for p in wb.places[:8]]
                    else:
                        place_info = [p.name for p in wb.places[:5]]
                    wb_parts.append(f"Places: {', '.join(place_info)}")
                context['worldbuilding'] = "\n".join(wb_parts)

        # Current chapter context - include MORE for chapter_focus and writer modes
        if hasattr(self, 'manuscript_editor'):
            content, title = self.manuscript_editor.get_current_chapter_info()
            if title:
                context['current_chapter_title'] = title
                if is_chapter_focused:
                    # Include FULL chapter content for focused modes
                    context['current_chapter_content'] = content or ""
                else:
                    # General mode: just include excerpt
                    context['current_chapter_content'] = content[:2000] if content else ""

                # Get chapter planning/outline if available (especially for writer mode)
                if is_chapter_focused and self.manuscript_editor.current_chapter_editor:
                    chapter = self.manuscript_editor.current_chapter_editor.chapter
                    if hasattr(chapter, 'planning') and chapter.planning:
                        planning = chapter.planning
                        context['chapter_planning'] = {
                            'outline': planning.outline,
                            'description': planning.description,
                            'pov_character': planning.pov_character,
                            'scene_list': planning.scene_list,
                            'events': [
                                {
                                    'id': e.id,
                                    'text': e.text,
                                    'description': e.description,
                                    'completed': e.completed,
                                    'stage': e.stage
                                }
                                for e in planning.events
                            ] if planning.events else [],
                            'characters_featured': planning.characters_featured,
                            'locations': planning.locations,
                            'themes': planning.themes,
                            'timeline_position': planning.timeline_position,
                            'notes': planning.notes,
                            # Writing style metadata
                            'tone': getattr(planning, 'tone', ''),
                            'voice': getattr(planning, 'voice', ''),
                            'style': getattr(planning, 'style', ''),
                            'pacing': getattr(planning, 'pacing', '')
                        }

        # All chapters list (for cross-chapter questions)
        if hasattr(project, 'manuscript') and project.manuscript and project.manuscript.chapters:
            chapter_list = []
            for i, ch in enumerate(project.manuscript.chapters[:20]):  # Limit to 20
                word_count = len(ch.content.split()) if ch.content else 0
                chapter_list.append(f"{i+1}. {ch.title} ({word_count} words)")
            context['all_chapters'] = "\n".join(chapter_list)

            # For writer mode, include previous chapter ending for continuity
            if mode == "writer" and hasattr(self, 'manuscript_editor'):
                # Get current chapter index from the chapter list widget
                if hasattr(self.manuscript_editor, 'chapter_list'):
                    current_idx = self.manuscript_editor.chapter_list.currentRow()
                    if current_idx > 0:
                        prev_ch = project.manuscript.chapters[current_idx - 1]
                        if prev_ch.content:
                            # Last 500 chars of previous chapter
                            context['previous_chapter_ending'] = prev_ch.content[-500:]

        return context

    def _on_chat_response(self, response: str):
        """Handle successful AI response."""
        # Check if this was a writer mode request
        if getattr(self, '_pending_mode', '') == 'writer' and hasattr(self, '_pending_insert_mode'):
            self._handle_writer_response(response)
        else:
            # Regular chat response - show in chat
            self.chat_widget.add_message("Assistant", response)

    def _handle_writer_response(self, response: str):
        """Handle AI response in writer mode - insert into editor.

        Args:
            response: The AI-generated text to insert
        """
        insert_mode = getattr(self, '_pending_insert_mode', 'insert_at_cursor')

        # Get the current chapter editor
        if not hasattr(self, 'manuscript_editor') or not self.manuscript_editor.current_chapter_editor:
            self.chat_widget.add_message("Assistant", "No chapter is open. Please select a chapter first.")
            return

        editor = self.manuscript_editor.current_chapter_editor.editor
        word_count = len(response.split())

        try:
            if insert_mode == 'replace_selection':
                # Replace selected text
                cursor = editor.textCursor()
                if cursor.hasSelection():
                    cursor.insertText(response)
                    action = "replaced selection"
                else:
                    # Fallback to insert at cursor if no selection
                    cursor.insertText(response)
                    action = "inserted at cursor"

            elif insert_mode == 'insert_at_cursor':
                # Insert at current cursor position
                cursor = editor.textCursor()
                cursor.insertText(response)
                action = "inserted at cursor"

            elif insert_mode == 'append_to_chapter':
                # Append to end of chapter
                cursor = editor.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                # Add spacing before appending
                current_text = editor.toPlainText()
                if current_text and not current_text.endswith('\n\n'):
                    cursor.insertText('\n\n')
                cursor.insertText(response)
                action = "appended to chapter"

            elif insert_mode == 'replace_chapter':
                # Replace entire chapter content
                editor.setPlainText(response)
                action = "replaced chapter"

            else:
                # Fallback
                cursor = editor.textCursor()
                cursor.insertText(response)
                action = "inserted"

            # Show confirmation in chat (not the full text)
            self.chat_widget.add_message(
                "Assistant",
                f"Done! {word_count} words {action}."
            )

            # Show status bar notification
            self.statusBar().showMessage(f"Writer: {word_count} words {action}", 5000)

        except Exception as e:
            self.chat_widget.add_message("Assistant", f"Error inserting text: {str(e)}")

    def _on_chat_error(self, error: str):
        """Handle AI chat error."""
        self.chat_widget.add_message("Assistant", f"Sorry, I encountered an issue: {error}")

    def _show_find_dialog(self):
        """Show Find dialog."""
        # Only work when on manuscript tab
        if self.tab_widget.currentIndex() != 0:
            self.statusBar().showMessage("Find is only available in the Manuscript tab", 3000)
            return

        if not self.find_dialog:
            self.find_dialog = FindReplaceDialog(self, replace_mode=False)
            self.find_dialog.find_next.connect(self._on_find_next)

        # Pre-populate with selected text
        selected = self.manuscript_editor.get_selected_text()
        if selected:
            self.find_dialog.set_find_text(selected)

        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.activateWindow()

    def _show_replace_dialog(self):
        """Show Find and Replace dialog."""
        # Only work when on manuscript tab
        if self.tab_widget.currentIndex() != 0:
            self.statusBar().showMessage("Find/Replace is only available in the Manuscript tab", 3000)
            return

        if not self.replace_dialog:
            self.replace_dialog = FindReplaceDialog(self, replace_mode=True)
            self.replace_dialog.find_next.connect(self._on_find_next)
            self.replace_dialog.replace_next.connect(self._on_replace_next)
            self.replace_dialog.replace_all.connect(self._on_replace_all)

        # Pre-populate with selected text
        selected = self.manuscript_editor.get_selected_text()
        if selected:
            self.replace_dialog.set_find_text(selected)

        self.replace_dialog.show()
        self.replace_dialog.raise_()
        self.replace_dialog.activateWindow()

    def _on_find_next(self, text: str, case_sensitive: bool, whole_word: bool):
        """Handle find next from dialog."""
        found = self.manuscript_editor.find_text(text, case_sensitive, whole_word)
        dialog = self.find_dialog or self.replace_dialog
        if dialog:
            if found:
                dialog.set_status("")
            else:
                dialog.set_status(f"'{text}' not found")

    def _on_replace_next(self, find_text: str, replace_text: str,
                         case_sensitive: bool, whole_word: bool):
        """Handle replace from dialog."""
        found = self.manuscript_editor.replace_text(find_text, replace_text, case_sensitive, whole_word)
        if self.replace_dialog:
            if not found:
                self.replace_dialog.set_status(f"'{find_text}' not found")
            else:
                self.replace_dialog.set_status("")

    def _on_replace_all(self, find_text: str, replace_text: str,
                        case_sensitive: bool, whole_word: bool):
        """Handle replace all from dialog."""
        count = self.manuscript_editor.replace_all_text(find_text, replace_text, case_sensitive, whole_word)
        if self.replace_dialog:
            if count == 0:
                self.replace_dialog.set_status(f"'{find_text}' not found")
            else:
                self.replace_dialog.set_status(f"Replaced {count} occurrence(s)")

    def _show_settings(self):
        """Show settings dialog."""
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.settings = dialog.get_settings()
            # Save settings persistently
            if self.ai_config.save_settings(self.settings):
                self.statusBar().showMessage("AI settings saved successfully", 3000)
            else:
                QMessageBox.warning(
                    self,
                    "Save Error",
                    "Failed to save AI settings. Check permissions."
                )

    def _export_book_outline(self):
        """Export all chapter plans as a book outline document."""
        if not self.current_project or not self.current_project.manuscript.chapters:
            QMessageBox.warning(
                self,
                "No Chapters",
                "No chapters available to export outline."
            )
            return

        # Collect current manuscript data (includes saving current chapter plans)
        self._collect_project_data()

        # Check if there are any chapter plans
        chapters_with_plans = sum(
            1 for ch in self.current_project.manuscript.chapters
            if ch.plan and ch.plan.strip()
        )

        if chapters_with_plans == 0:
            result = QMessageBox.question(
                self,
                "No Chapter Plans",
                "No chapter plans have been written yet.\n\n"
                "Would you like to export an outline template with chapter titles only?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if result != QMessageBox.StandardButton.Yes:
                return

        # Get output file path
        default_name = f"{self.current_project.manuscript.title}_Outline.docx"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Book Outline",
            default_name,
            "Word Documents (*.docx)"
        )

        if not file_path:
            return

        # Export outline
        exporter = ManuscriptExporter(self.current_project.manuscript)

        try:
            success = exporter.export_outline_to_docx(file_path, include_notes=True)

            if success:
                total_chapters = len(self.current_project.manuscript.chapters)
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Book outline exported successfully!\n\n"
                    f"File: {file_path}\n"
                    f"Total Chapters: {total_chapters}\n"
                    f"Chapters with Plans: {chapters_with_plans}"
                )
            else:
                QMessageBox.critical(
                    self,
                    "Export Failed",
                    "Failed to export outline. Check the console for details."
                )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"An error occurred during export:\n{str(e)}"
            )

    def _export_manuscript(self, format_type: str):
        """Export manuscript in specified format."""
        if not self.current_project or not self.current_project.manuscript.chapters:
            QMessageBox.warning(
                self,
                "No Content",
                "No manuscript content to export."
            )
            return

        # Collect current manuscript data
        self._collect_project_data()

        # Determine file extension and filter
        extensions = {
            "kindle": ("epub", "EPUB Files (*.epub)"),
            "barnes_noble": ("epub", "EPUB Files (*.epub)"),
            "publisher": ("docx", "Word Documents (*.docx)"),
            "docx": ("docx", "Word Documents (*.docx)")
        }

        ext, file_filter = extensions.get(format_type, ("docx", "Word Documents (*.docx)"))

        # Get output file path
        default_name = f"{self.current_project.manuscript.title}.{ext}"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export Manuscript - {format_type.replace('_', ' ').title()}",
            default_name,
            file_filter
        )

        if not file_path:
            return

        # Export manuscript
        exporter = ManuscriptExporter(self.current_project.manuscript)

        try:
            success = False
            if format_type == "kindle":
                success = exporter.export_for_kindle(file_path)
            elif format_type == "barnes_noble":
                success = exporter.export_for_barnes_noble(file_path)
            elif format_type == "publisher":
                success = exporter.export_publisher_ready(file_path)
            elif format_type == "docx":
                success = exporter.export_to_docx(file_path)

            if success:
                stats = exporter.get_manuscript_statistics()
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Manuscript exported successfully!\n\n"
                    f"File: {file_path}\n"
                    f"Chapters: {stats['total_chapters']}\n"
                    f"Words: {stats['total_words']:,}\n"
                    f"Estimated Pages: {stats['estimated_pages']}"
                )
            else:
                QMessageBox.critical(
                    self,
                    "Export Failed",
                    "Failed to export manuscript. Check the console for details."
                )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"An error occurred during export:\n{str(e)}"
            )

    def _export_llm_context(self):
        """Export worldbuilding, plot, and characters to markdown for LLM context."""
        if not self.current_project:
            QMessageBox.warning(
                self,
                "No Project",
                "No project loaded to export."
            )
            return

        # Collect current data from all widgets
        self._collect_project_data()

        # Get output file path
        default_name = f"{self.current_project.name}_LLM_Context.md"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export LLM Context",
            default_name,
            "Markdown Files (*.md);;All Files (*)"
        )

        if file_path:
            try:
                # Export to markdown
                markdown_content = LLMContextExporter.export_to_markdown(
                    self.current_project,
                    file_path
                )

                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"LLM context exported successfully to:\n{file_path}\n\n"
                    f"You can now use this markdown file to provide context to LLMs."
                )
                self.statusBar().showMessage(f"Exported LLM context to {file_path}")

            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Export Error",
                    f"An error occurred during export:\n{str(e)}"
                )

    def _export_project_summary(self):
        """Export project as a comprehensive summary with optional AI/ML summarization."""
        if not self.current_project:
            QMessageBox.warning(
                self,
                "No Project",
                "No project loaded to export."
            )
            return

        # Show export dialog
        dialog = ExportSummaryDialog(self.current_project, self)
        dialog.exec()

    def _show_import_guide(self):
        """Show the import guide dialog with AI prompts."""
        dialog = ImportGuideDialog(self)
        dialog.exec()

    def _show_json_import(self):
        """Show the JSON import dialog."""
        if not self.current_project:
            QMessageBox.warning(
                self,
                "No Project",
                "Please create or open a project before importing data."
            )
            return

        dialog = JSONImportDialog(self, self.current_project)
        dialog.data_imported.connect(self._on_json_imported)
        dialog.exec()

    def _on_json_imported(self, imported_data: dict):
        """Handle successful JSON import."""
        # Refresh all widgets to show imported data
        self._load_project_into_ui()
        self.statusBar().showMessage("Data imported successfully", 5000)

    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Writer Platform",
            "Writer Platform v1.0\n\n"
            "A comprehensive platform for writers to organize books, "
            "short stories, and media.\n\n"
            "Features worldbuilding, character development, story planning, "
            "manuscript editing, AI assistance, and more."
        )

    def _jump_to_annotation(self, chapter_id: str, annotation_id: str):
        """Jump to specific annotation in manuscript editor."""
        # Switch to Write tab
        self.tab_widget.setCurrentWidget(self.manuscript_editor)

        # Find and select the chapter in manuscript editor
        for i in range(self.manuscript_editor.chapter_list.count()):
            item = self.manuscript_editor.chapter_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == chapter_id:
                self.manuscript_editor.chapter_list.setCurrentItem(item)

                # Wait for chapter to load, then jump to annotation
                if self.manuscript_editor.current_chapter_editor:
                    # Find the annotation to get its line number
                    annotation = next(
                        (a for a in self.manuscript_editor.current_chapter_editor.chapter.annotations
                         if a.id == annotation_id),
                        None
                    )
                    if annotation:
                        self.manuscript_editor.current_chapter_editor._jump_to_line(annotation.line_number)
                break

    def _go_to_critique_line(self, sentence_number: int):
        """Navigate to a specific sentence from critique feedback.

        Args:
            sentence_number: The sentence number (1-indexed) from the critique
        """
        import re

        # Switch to Write tab
        self.tab_widget.setCurrentWidget(self.manuscript_editor)

        # Get current chapter editor
        if not self.manuscript_editor.current_chapter_editor:
            return

        editor = self.manuscript_editor.current_chapter_editor.editor
        if not editor:
            return

        # Get the chapter text
        text = editor.toPlainText()
        if not text:
            return

        # Split into sentences the same way the critique does
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        # Get the target sentence (1-indexed)
        if sentence_number < 1 or sentence_number > len(sentences):
            return

        target_sentence = sentences[sentence_number - 1]

        # Find the position of this sentence in the text
        # We need to find the Nth sentence occurrence
        position = 0
        current_sentence = 0
        for match in re.finditer(r'[^.!?]*[.!?]', text):
            sentence_text = match.group().strip()
            if sentence_text:
                current_sentence += 1
                if current_sentence == sentence_number:
                    position = match.start()
                    break

        # If regex approach didn't work, try direct search
        if position == 0 and sentence_number > 1:
            # Find by counting sentences
            pos = 0
            for i in range(sentence_number - 1):
                if i < len(sentences):
                    found = text.find(sentences[i], pos)
                    if found >= 0:
                        pos = found + len(sentences[i])
            position = text.find(target_sentence, pos)

        # Move cursor to the sentence and select it
        cursor = editor.textCursor()
        cursor.setPosition(position)
        cursor.movePosition(cursor.MoveOperation.EndOfBlock, cursor.MoveMode.KeepAnchor)

        # Try to select the whole sentence
        end_pos = position + len(target_sentence)
        if end_pos <= len(text):
            cursor.setPosition(position)
            cursor.setPosition(end_pos, cursor.MoveMode.KeepAnchor)

        editor.setTextCursor(cursor)
        editor.centerCursor()
        editor.setFocus()

        # Show a brief status message
        self.statusBar().showMessage(f"Navigated to sentence {sentence_number}", 3000)

    def _toggle_multi_window_mode(self, checked: bool):
        """Toggle multi-window mode on/off."""
        self.window_manager.set_multi_window_mode(checked)

        if not checked:
            # Merge all tabs back to main window
            self._merge_all_secondary_windows()
            self.statusBar().showMessage("Multi-window mode disabled", 3000)
        else:
            self.statusBar().showMessage(
                "Multi-window mode enabled - Right-click tabs to create new windows",
                5000
            )

    def _merge_all_secondary_windows(self):
        """Merge all secondary windows back to main window."""
        for window in self.window_manager.get_secondary_windows():
            window.close()  # closeEvent will merge tabs back

    def _show_tab_context_menu(self, pos: QPoint):
        """Show context menu for tab operations."""
        tab_bar = self.tab_widget.tabBar()
        tab_index = tab_bar.tabAt(pos)
        if tab_index == -1:
            return

        menu = QMenu(self)

        # Only show Create New Window if multi-window mode is enabled
        if self.window_manager.is_multi_window_mode():
            # Don't allow detaching the last tab
            if self.tab_widget.count() > 1:
                detach_action = menu.addAction("Create New Window")
                detach_action.triggered.connect(lambda: self._detach_tab_to_new_window(tab_index))

        if not menu.isEmpty():
            menu.exec(tab_bar.mapToGlobal(pos))

    def _detach_tab_to_new_window(self, tab_index: int):
        """Detach a tab to a new secondary window."""
        if tab_index < 0 or tab_index >= self.tab_widget.count():
            return

        # Don't allow detaching the last tab
        if self.tab_widget.count() <= 1:
            QMessageBox.warning(
                self,
                "Cannot Detach",
                "Cannot detach the last tab from the main window."
            )
            return

        # Get widget and label
        widget = self.tab_widget.widget(tab_index)
        label = self.tab_widget.tabText(tab_index)

        # Remove from main window
        widget.setParent(None)
        self.tab_widget.removeTab(tab_index)

        # Create new secondary window
        project_name = self.current_project.name if self.current_project else "Writer Platform"
        new_window = SecondaryWindow(project_name, self)
        new_window.add_tab(widget, label)
        new_window.tab_merge_requested.connect(self._handle_tab_merge)
        new_window.show()

        self.statusBar().showMessage(f"Created new window with '{label}' tab", 3000)

    def _handle_tab_merge(self, widget: QWidget, label: str):
        """Handle merging a tab back from a secondary window."""
        self.tab_widget.addTab(widget, label)
        self.statusBar().showMessage(f"Merged '{label}' tab back to main window", 3000)

    def closeEvent(self, event):
        """Handle window close event."""
        if self.current_project and not self._confirm_unsaved_changes():
            event.ignore()
        else:
            # Hide tray icon before closing
            if hasattr(self, 'tray_icon'):
                self.tray_icon.hide()
            # Close all secondary windows
            self.window_manager.close_all_secondary_windows()
            event.accept()
