"""Characters widget with image upload and AI image generation."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox,
    QFileDialog, QGroupBox, QFormLayout, QScrollArea, QMessageBox,
    QProgressBar, QDialog, QDialogButtonBox
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread
from PyQt6.QtGui import QPixmap
from typing import List, Optional, TYPE_CHECKING
import uuid
from pathlib import Path
from datetime import datetime

from src.models.project import Character, LoveInterest

if TYPE_CHECKING:
    from src.models.project import WriterProject


class ImageGenerationWorker(QThread):
    """Background worker for generating character images."""

    finished = pyqtSignal(object)  # Path or None
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        character: Character,
        save_path: Path,
        image_type: str = "portrait"  # "portrait" or "full_body"
    ):
        """Initialize image generation worker.

        Args:
            character: Character to generate image for
            save_path: Where to save the generated image
            image_type: Type of image - "portrait" (head/shoulders) or "full_body"
        """
        super().__init__()
        self.character = character
        self.save_path = save_path
        self.image_type = image_type

    def run(self):
        """Run image generation in background."""
        try:
            self.progress.emit("Initializing image generation...")

            from src.ai.image_generation_agent import get_image_generation_agent

            agent = get_image_generation_agent()

            # Build additional prompt based on image type
            # CRITICAL: Emphasize SINGLE character and story-appropriate framing
            if self.image_type == "full_body":
                additional_prompt = (
                    "solo full body character portrait, single person standing pose, "
                    "character design sheet, showing complete outfit and posture from head to toe, "
                    "personality shown through stance and expression, "
                    "neutral or contextual background, cinematic lighting, "
                    "character concept art style"
                )
            else:
                additional_prompt = (
                    "solo head and shoulders portrait, single character headshot, "
                    "professional character portrait, detailed facial features and expression, "
                    "personality captured in eyes and expression, "
                    "neutral or atmospheric background, soft cinematic lighting, "
                    "portrait photography or digital painting style"
                )

            self.progress.emit(f"Generating {self.image_type} image for {self.character.name}...")

            # Generate the image
            result_path = agent.generate_character_image(
                character=self.character,
                additional_prompt=additional_prompt,
                save_path=self.save_path
            )

            if result_path and result_path.exists():
                self.progress.emit("Image generated successfully!")
                self.finished.emit(result_path)
            else:
                self.error.emit("Image generation failed - no output file created")

        except Exception as e:
            self.error.emit(f"Image generation error: {str(e)}")


class _LoveInterestDialog(QDialog):
    """Dialog for adding / editing a single love interest."""

    RELATIONSHIP_TYPES = [
        "spouse", "partner", "lover", "fiancé(e)", "crush",
        "unrequited love", "ex-partner", "forbidden love",
        "romantic interest", "one-sided attraction", "affair",
        "arranged marriage", "soulmate",
    ]
    STATUSES = [
        "active", "past", "complicated", "forbidden", "secret",
        "broken-off", "unconsummated", "rekindling",
    ]

    def __init__(self, available_characters: List[Character],
                 existing: Optional[LoveInterest] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Love Interest")
        self.setMinimumWidth(480)
        self._available = available_characters
        self._existing = existing

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Character picker
        self.char_combo = QComboBox()
        for c in available_characters:
            label = c.name or "(unnamed)"
            if c.character_type:
                label += f" ({c.character_type})"
            self.char_combo.addItem(label, c.id)
        if existing:
            for i in range(self.char_combo.count()):
                if self.char_combo.itemData(i) == existing.character_id:
                    self.char_combo.setCurrentIndex(i)
                    break
        form.addRow("Character:", self.char_combo)

        # Relationship type (editable so user can invent their own)
        self.rel_type_combo = QComboBox()
        self.rel_type_combo.setEditable(True)
        self.rel_type_combo.addItems(self.RELATIONSHIP_TYPES)
        if existing and existing.relationship_type:
            self.rel_type_combo.setEditText(existing.relationship_type)
        form.addRow("Relationship:", self.rel_type_combo)

        # Status
        self.status_combo = QComboBox()
        self.status_combo.setEditable(True)
        self.status_combo.addItems(self.STATUSES)
        if existing and existing.status:
            self.status_combo.setEditText(existing.status)
        form.addRow("Status:", self.status_combo)

        # Started (free-text narrative reference)
        self.started_edit = QLineEdit()
        self.started_edit.setPlaceholderText(
            "When it began (e.g. 'Chapter 3', 'childhood', 'spring of the war')")
        if existing:
            self.started_edit.setText(existing.started)
        form.addRow("Began:", self.started_edit)

        # Description
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText(
            "How they met, what they mean to each other, the shape of the bond...")
        self.desc_edit.setMaximumHeight(110)
        if existing:
            self.desc_edit.setPlainText(existing.description)
        form.addRow("Description:", self.desc_edit)

        # Tension (obstacles, conflicts)
        self.tension_edit = QTextEdit()
        self.tension_edit.setPlaceholderText(
            "Obstacles, conflicts, stakes — what keeps it from being simple")
        self.tension_edit.setMaximumHeight(90)
        if existing:
            self.tension_edit.setPlainText(existing.tension)
        form.addRow("Tension:", self.tension_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_love_interest(self) -> Optional[LoveInterest]:
        char_id = self.char_combo.currentData()
        if not char_id:
            return None
        return LoveInterest(
            character_id=char_id,
            relationship_type=self.rel_type_combo.currentText().strip() or "romantic interest",
            status=self.status_combo.currentText().strip() or "active",
            description=self.desc_edit.toPlainText().strip(),
            tension=self.tension_edit.toPlainText().strip(),
            started=self.started_edit.text().strip(),
        )


class CharacterWidget(QWidget):
    """Widget for editing a single character."""

    content_changed = pyqtSignal()

    def __init__(self, character: Character,
                 project_path: Optional[Path] = None, project=None,
                 available_characters: Optional[List[Character]] = None):
        """Initialize character widget.

        Args:
            character: The character to edit
            project_path: Path to the project directory for saving generated images
            project: The WriterProject (for accessing chapters in personality arc)
            available_characters: Other characters in the project (for love interests)
        """
        super().__init__()
        self.character = character
        self._project_path = project_path
        self._available_characters: List[Character] = available_characters or []
        self._project = project
        self._image_worker: Optional[ImageGenerationWorker] = None
        self._init_ui()
        self._load_character()

    def _init_ui(self):
        """Initialize user interface."""
        # Main layout with scroll area
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create scroll area for all content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Content widget inside scroll area
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)

        # Character image
        image_group = QGroupBox("Character Image")
        image_layout = QVBoxLayout()

        self.image_label = QLabel("No image")
        self.image_label.setFixedSize(200, 200)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("border: 1px solid #ccc; background: #f0f0f0;")
        image_layout.addWidget(self.image_label)

        # Image buttons row
        image_buttons_layout = QHBoxLayout()

        upload_button = QPushButton("Upload")
        upload_button.setToolTip("Upload an existing image file")
        upload_button.clicked.connect(self._upload_image)
        image_buttons_layout.addWidget(upload_button)

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setToolTip("Generate character image using AI")
        self.generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #8b5cf6;
                color: white;
                padding: 5px 12px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #7c3aed; }
            QPushButton:disabled { background-color: #9ca3af; }
        """)
        self.generate_btn.clicked.connect(self._generate_image)
        image_buttons_layout.addWidget(self.generate_btn)

        image_layout.addLayout(image_buttons_layout)

        # Image type selection
        type_layout = QHBoxLayout()
        type_label = QLabel("Type:")
        type_label.setStyleSheet("font-size: 11px;")
        type_layout.addWidget(type_label)

        self.image_type_combo = QComboBox()
        self.image_type_combo.addItem("Portrait (Head/Shoulders)", "portrait")
        self.image_type_combo.addItem("Full Body", "full_body")
        self.image_type_combo.setToolTip("Choose the type of character image to generate")
        self.image_type_combo.setStyleSheet("font-size: 11px;")
        type_layout.addWidget(self.image_type_combo)
        type_layout.addStretch()

        image_layout.addLayout(type_layout)

        # Progress bar for generation
        self.image_progress = QProgressBar()
        self.image_progress.setRange(0, 0)  # Indeterminate
        self.image_progress.setVisible(False)
        self.image_progress.setMaximumHeight(10)
        image_layout.addWidget(self.image_progress)

        # Status label
        self.image_status_label = QLabel("")
        self.image_status_label.setStyleSheet("font-size: 11px; color: #6b7280;")
        self.image_status_label.setWordWrap(True)
        image_layout.addWidget(self.image_status_label)

        image_group.setLayout(image_layout)
        layout.addWidget(image_group)

        # Basic info
        info_group = QGroupBox("Basic Information")
        info_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self.content_changed.emit)
        info_layout.addRow("Name:", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Protagonist", "Antagonist", "Major", "Minor"])
        self.type_combo.currentTextChanged.connect(self.content_changed.emit)
        info_layout.addRow("Type:", self.type_combo)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # Physical Description (important for image generation)
        appearance_group = QGroupBox("Physical Description")
        appearance_layout = QVBoxLayout()

        self.physical_desc_edit = QTextEdit()
        self.physical_desc_edit.setPlaceholderText(
            "Physical appearance details for image generation:\n"
            "- Age, build, height\n"
            "- Hair color/style, eye color, skin tone\n"
            "- Distinguishing features\n"
            "- Typical clothing/style"
        )
        self.physical_desc_edit.setMaximumHeight(100)
        self.physical_desc_edit.textChanged.connect(self.content_changed.emit)
        appearance_layout.addWidget(self.physical_desc_edit)

        appearance_group.setLayout(appearance_layout)
        layout.addWidget(appearance_group)

        # Personality
        personality_group = QGroupBox("Personality")
        personality_layout = QVBoxLayout()

        self.personality_edit = QTextEdit()
        self.personality_edit.setPlaceholderText("General personality description...")
        self.personality_edit.setMaximumHeight(80)
        self.personality_edit.textChanged.connect(self.content_changed.emit)
        personality_layout.addWidget(self.personality_edit)

        # Structured personality fields
        form_layout = QFormLayout()

        self.traits_edit = QLineEdit()
        self.traits_edit.setPlaceholderText("brave, impulsive, loyal, sarcastic...")
        self.traits_edit.textChanged.connect(self.content_changed.emit)
        form_layout.addRow("Traits:", self.traits_edit)

        self.motivations_edit = QLineEdit()
        self.motivations_edit.setPlaceholderText("What drives this character...")
        self.motivations_edit.textChanged.connect(self.content_changed.emit)
        form_layout.addRow("Motivations:", self.motivations_edit)

        self.fears_edit = QLineEdit()
        self.fears_edit.setPlaceholderText("What they fear or avoid...")
        self.fears_edit.textChanged.connect(self.content_changed.emit)
        form_layout.addRow("Fears:", self.fears_edit)

        self.speaking_style_edit = QLineEdit()
        self.speaking_style_edit.setPlaceholderText("Dialect, vocabulary, sentence patterns...")
        self.speaking_style_edit.textChanged.connect(self.content_changed.emit)
        form_layout.addRow("Speaking style:", self.speaking_style_edit)

        self.emotional_baseline_edit = QLineEdit()
        self.emotional_baseline_edit.setPlaceholderText("Default emotional state (e.g. guarded optimism)...")
        self.emotional_baseline_edit.textChanged.connect(self.content_changed.emit)
        form_layout.addRow("Baseline mood:", self.emotional_baseline_edit)

        personality_layout.addLayout(form_layout)

        personality_group.setLayout(personality_layout)
        layout.addWidget(personality_group)

        # Personality Arc
        arc_group = QGroupBox("Personality Arc (how the character changes)")
        arc_layout = QVBoxLayout()

        self.arc_list = QListWidget()
        self.arc_list.setMaximumHeight(120)
        self.arc_list.currentRowChanged.connect(self._on_arc_snapshot_selected)
        arc_layout.addWidget(self.arc_list)

        self.arc_detail = QTextEdit()
        self.arc_detail.setPlaceholderText(
            "Select or add a personality snapshot to see details.\n"
            "Use 'Assess from Writing' to auto-generate, or add/edit manually."
        )
        self.arc_detail.setMaximumHeight(120)
        self.arc_detail.textChanged.connect(self._on_arc_detail_edited)
        arc_layout.addWidget(self.arc_detail)

        arc_btn_layout = QHBoxLayout()

        self.assess_btn = QPushButton("Assess from Writing")
        self.assess_btn.setToolTip("Use AI to analyze this character's personality in a selected chapter")
        self.assess_btn.clicked.connect(self._assess_personality)
        arc_btn_layout.addWidget(self.assess_btn)

        add_snapshot_btn = QPushButton("+ Add Snapshot")
        add_snapshot_btn.setToolTip("Manually add a personality snapshot for a chapter")
        add_snapshot_btn.clicked.connect(self._add_manual_snapshot)
        arc_btn_layout.addWidget(add_snapshot_btn)

        remove_snapshot_btn = QPushButton("Remove")
        remove_snapshot_btn.setToolTip("Remove the selected personality snapshot")
        remove_snapshot_btn.clicked.connect(self._remove_snapshot)
        arc_btn_layout.addWidget(remove_snapshot_btn)

        arc_btn_layout.addStretch()
        arc_layout.addLayout(arc_btn_layout)

        arc_group.setLayout(arc_layout)
        layout.addWidget(arc_group)

        # Backstory
        backstory_group = QGroupBox("Backstory")
        backstory_layout = QVBoxLayout()

        self.backstory_edit = QTextEdit()
        self.backstory_edit.setPlaceholderText("Character history and background...")
        self.backstory_edit.textChanged.connect(self.content_changed.emit)
        backstory_layout.addWidget(self.backstory_edit)

        backstory_group.setLayout(backstory_layout)
        layout.addWidget(backstory_group)

        # ── Story Arc Engine (Truby / Lisa Cron / K.M. Weiland / Save the Cat) ──
        arc_engine_group = QGroupBox(
            "Story Arc Engine — what powers their transformation")
        arc_engine_form = QFormLayout()

        self.want_edit = QLineEdit()
        self.want_edit.setPlaceholderText(
            "External goal — what they THINK they want (e.g. the throne)")
        self.want_edit.textChanged.connect(self.content_changed.emit)
        arc_engine_form.addRow("Want:", self.want_edit)

        self.need_edit = QLineEdit()
        self.need_edit.setPlaceholderText(
            "Internal truth — what they actually need (e.g. to forgive himself)")
        self.need_edit.textChanged.connect(self.content_changed.emit)
        arc_engine_form.addRow("Need:", self.need_edit)

        self.lie_edit = QTextEdit()
        self.lie_edit.setPlaceholderText(
            "False belief driving their behaviour (e.g. 'I can only be loved if I am useful')")
        self.lie_edit.setMaximumHeight(60)
        self.lie_edit.textChanged.connect(self.content_changed.emit)
        arc_engine_form.addRow("Lie they believe:", self.lie_edit)

        self.ghost_edit = QTextEdit()
        self.ghost_edit.setPlaceholderText(
            "Formative wound — the past event that created the lie")
        self.ghost_edit.setMaximumHeight(60)
        self.ghost_edit.textChanged.connect(self.content_changed.emit)
        arc_engine_form.addRow("Ghost / Wound:", self.ghost_edit)

        self.arc_type_combo = QComboBox()
        self.arc_type_combo.setEditable(True)
        self.arc_type_combo.addItems([
            "", "Positive change", "Flat / Steadfast", "Negative change",
            "Fall", "Corruption", "Disillusionment", "Redemption",
        ])
        self.arc_type_combo.currentTextChanged.connect(self.content_changed.emit)
        arc_engine_form.addRow("Arc type:", self.arc_type_combo)

        arc_engine_group.setLayout(arc_engine_form)
        layout.addWidget(arc_engine_group)

        # ── Character Depth (makes them feel real) ──
        depth_group = QGroupBox("Character Depth — what makes them feel real")
        depth_form = QFormLayout()

        self.moral_code_edit = QLineEdit()
        self.moral_code_edit.setPlaceholderText(
            "Lines they won't cross / what they stand for")
        self.moral_code_edit.textChanged.connect(self.content_changed.emit)
        depth_form.addRow("Moral code:", self.moral_code_edit)

        self.worldview_edit = QLineEdit()
        self.worldview_edit.setPlaceholderText(
            "Philosophical lens — how they see the world")
        self.worldview_edit.textChanged.connect(self.content_changed.emit)
        depth_form.addRow("Worldview:", self.worldview_edit)

        self.secret_edit = QTextEdit()
        self.secret_edit.setPlaceholderText(
            "What they hide — from others, or from themselves")
        self.secret_edit.setMaximumHeight(60)
        self.secret_edit.textChanged.connect(self.content_changed.emit)
        depth_form.addRow("Secret:", self.secret_edit)

        self.contradictions_edit = QLineEdit()
        self.contradictions_edit.setPlaceholderText(
            "Internal inconsistencies (brutal but tender, pious but vain)")
        self.contradictions_edit.textChanged.connect(self.content_changed.emit)
        depth_form.addRow("Contradictions:", self.contradictions_edit)

        self.defining_relationship_edit = QLineEdit()
        self.defining_relationship_edit.setPlaceholderText(
            "The bond that shapes them most (mentor, sibling, lost love)")
        self.defining_relationship_edit.textChanged.connect(self.content_changed.emit)
        depth_form.addRow("Defining relationship:", self.defining_relationship_edit)

        self.quirks_edit = QLineEdit()
        self.quirks_edit.setPlaceholderText(
            "Distinctive mannerisms, tics, phrases")
        self.quirks_edit.textChanged.connect(self.content_changed.emit)
        depth_form.addRow("Quirks:", self.quirks_edit)

        depth_group.setLayout(depth_form)
        layout.addWidget(depth_group)

        # ── Love Interests ──
        love_group = QGroupBox("Love Interests — romantic bonds with other characters")
        love_layout = QVBoxLayout()

        self.love_list = QListWidget()
        self.love_list.setMaximumHeight(150)
        self.love_list.itemDoubleClicked.connect(self._edit_love_interest)
        love_layout.addWidget(self.love_list)

        love_btn_row = QHBoxLayout()
        self.add_love_btn = QPushButton("➕ Add Love Interest")
        self.add_love_btn.clicked.connect(self._add_love_interest)
        love_btn_row.addWidget(self.add_love_btn)

        self.edit_love_btn = QPushButton("✏️ Edit")
        self.edit_love_btn.clicked.connect(self._edit_love_interest)
        love_btn_row.addWidget(self.edit_love_btn)

        self.remove_love_btn = QPushButton("🗑 Remove")
        self.remove_love_btn.clicked.connect(self._remove_love_interest)
        love_btn_row.addWidget(self.remove_love_btn)
        love_btn_row.addStretch()
        love_layout.addLayout(love_btn_row)

        love_group.setLayout(love_layout)
        layout.addWidget(love_group)

        # Notes
        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout()

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Additional notes...")
        self.notes_edit.textChanged.connect(self.content_changed.emit)
        notes_layout.addWidget(self.notes_edit)

        notes_group.setLayout(notes_layout)
        layout.addWidget(notes_group)

        # Strengthen individual character button
        self.strengthen_char_btn = QPushButton("🤖 Strengthen This Character")
        self.strengthen_char_btn.setToolTip(
            "AI scans your manuscript for this character's personality,\n"
            "traits, physical details, speaking style, and backstory"
        )
        self.strengthen_char_btn.clicked.connect(self._strengthen_this_character)
        layout.addWidget(self.strengthen_char_btn)

        # Set content widget to scroll area and add to main layout
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

    def _load_character(self):
        """Load character data into widgets.

        Blocks signals during population to prevent textChanged cascades
        from triggering save_to_model with half-loaded data.
        """
        editable_widgets = [
            self.name_edit, self.type_combo, self.physical_desc_edit,
            self.personality_edit, self.backstory_edit, self.notes_edit,
            self.traits_edit, self.motivations_edit, self.fears_edit,
            self.speaking_style_edit, self.emotional_baseline_edit,
            self.want_edit, self.need_edit, self.lie_edit, self.ghost_edit,
            self.arc_type_combo, self.moral_code_edit, self.worldview_edit,
            self.secret_edit, self.contradictions_edit,
            self.defining_relationship_edit, self.quirks_edit,
        ]
        for w in editable_widgets:
            w.blockSignals(True)
        try:
            self._load_character_fields()
        finally:
            for w in editable_widgets:
                w.blockSignals(False)

    def _load_character_fields(self):
        """Populate all fields from the character model (no signal management)."""
        self.name_edit.setText(self.character.name)
        self.type_combo.setCurrentText(self.character.character_type.capitalize())
        self.physical_desc_edit.setPlainText(self.character.physical_description)
        self.personality_edit.setPlainText(self.character.personality)
        self.backstory_edit.setPlainText(self.character.backstory)
        self.notes_edit.setPlainText(self.character.notes)

        # Structured personality fields
        self.traits_edit.setText(", ".join(self.character.personality_traits))
        self.motivations_edit.setText(self.character.motivations)
        self.fears_edit.setText(self.character.fears)
        self.speaking_style_edit.setText(self.character.speaking_style)
        self.emotional_baseline_edit.setText(self.character.emotional_baseline)

        # Story arc engine fields (getattr for backwards compat with older saves)
        self.want_edit.setText(getattr(self.character, 'want', '') or '')
        self.need_edit.setText(getattr(self.character, 'need', '') or '')
        self.lie_edit.setPlainText(getattr(self.character, 'lie_they_believe', '') or '')
        self.ghost_edit.setPlainText(getattr(self.character, 'ghost', '') or '')
        arc_val = getattr(self.character, 'character_arc', '') or ''
        if arc_val:
            idx = self.arc_type_combo.findText(arc_val)
            if idx >= 0:
                self.arc_type_combo.setCurrentIndex(idx)
            else:
                self.arc_type_combo.setEditText(arc_val)
        else:
            self.arc_type_combo.setCurrentIndex(0)

        # Depth fields
        self.moral_code_edit.setText(getattr(self.character, 'moral_code', '') or '')
        self.worldview_edit.setText(getattr(self.character, 'worldview', '') or '')
        self.secret_edit.setPlainText(getattr(self.character, 'secret', '') or '')
        self.contradictions_edit.setText(getattr(self.character, 'contradictions', '') or '')
        self.defining_relationship_edit.setText(
            getattr(self.character, 'defining_relationship', '') or '')
        self.quirks_edit.setText(getattr(self.character, 'quirks', '') or '')

        # Personality arc
        self._refresh_arc_list()

        # Love interests
        self._refresh_love_list()

        if self.character.image_path and Path(self.character.image_path).exists():
            pixmap = QPixmap(self.character.image_path)
            self.image_label.setPixmap(
                pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio)
            )
        else:
            self.image_label.setText("No image")
            self.image_label.setPixmap(QPixmap())

    def _upload_image(self):
        """Upload character image."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Character Image",
            "",
            "Image Files (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )

        if file_path:
            self.character.image_path = file_path
            pixmap = QPixmap(file_path)
            self.image_label.setPixmap(
                pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio)
            )
            self.content_changed.emit()

    def _strengthen_this_character(self):
        """Strengthen this individual character from manuscript context."""
        if not self._project:
            QMessageBox.information(self, "No Project", "Open a project first.")
            return

        try:
            self.save_to_model()
        except RuntimeError:
            pass

        self.strengthen_char_btn.setEnabled(False)
        self.strengthen_char_btn.setText("🤖 Scanning...")

        self._char_strengthen_worker = _SingleCharacterWorker(
            self.character, self._project
        )
        # Phase 1 (background): gather evidence, traits, associations
        # Phase 2 (main thread): run LLM synthesis
        self._char_strengthen_worker.evidence_ready.connect(self._on_evidence_ready)
        self._char_strengthen_worker.finished.connect(self._on_char_strengthen_done)
        self._char_strengthen_worker.error.connect(self._on_char_strengthen_error)
        self._char_strengthen_worker.start()

    def _on_evidence_ready(self, name: str, all_sents: list, existing_fields: dict):
        """Fill ONLY fields the LLM left empty. Never overwrite LLM output."""
        self.strengthen_char_btn.setText("🤖 Finishing...")

        report = [f"Found {len(all_sents)} mention(s)"]
        if hasattr(self._char_strengthen_worker, '_ai_report'):
            report.extend(self._char_strengthen_worker._ai_report)

        # Report what the AI filled
        for f in ['personality', 'physical_description', 'speaking_style',
                  'backstory', 'motivations', 'fears', 'emotional_baseline']:
            val = getattr(self.character, f, '') or ''
            if val:
                report.append(f"  {f}: {val[:60]}...")

        traits = getattr(self.character, 'personality_traits', [])
        if traits:
            report.append(f"  traits: {', '.join(traits[:6])}")

        self._on_char_strengthen_done("\n".join(report))

    def _on_char_strengthen_done(self, report: str):
        """Handle strengthen completion."""
        self.strengthen_char_btn.setEnabled(True)
        self.strengthen_char_btn.setText("🤖 Strengthen This Character")

        # Debug: check what's actually on the model before reloading UI
        print(f"[Strengthen Done] Character model state:")
        for f in ['personality', 'physical_description', 'speaking_style',
                  'backstory', 'motivations', 'fears', 'emotional_baseline',
                  'personality_traits']:
            val = getattr(self.character, f, '')
            preview = str(val)[:80] if val else '(empty)'
            print(f"  {f}: {preview}")

        try:
            # Reload everything — this already blocks signals on the new fields too
            self._load_character()
            print(f"[Strengthen Done] UI widgets updated via _load_character")
        except RuntimeError as e:
            print(f"[Strengthen Done] Widget update failed: {e}")

        # Emit content changed so the project knows to save
        self.content_changed.emit()
        QMessageBox.information(self, f"'{self.character.name}' Strengthened", report)

    def _on_char_strengthen_error(self, msg: str):
        self.strengthen_char_btn.setEnabled(True)
        self.strengthen_char_btn.setText("🤖 Strengthen This Character")
        QMessageBox.warning(self, "Error", msg)

    def _generate_image(self):
        """Generate character image using AI."""
        # Save current data to model first
        self.save_to_model()

        # Check if we have physical description
        if not self.character.physical_description.strip():
            reply = QMessageBox.question(
                self,
                "No Physical Description",
                "No physical description provided. The AI will generate a generic image.\n\n"
                "Would you like to add a physical description first?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.physical_desc_edit.setFocus()
                return

        # Determine save location
        if self._project_path:
            # Save in project's images directory
            images_dir = self._project_path / "images" / "characters"
        else:
            # Save in default location
            images_dir = Path.home() / ".writer_platform" / "generated_images" / "characters"

        images_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() else "_" for c in self.character.name)
        save_path = images_dir / f"{safe_name}_{timestamp}.png"

        # Get image type
        image_type = self.image_type_combo.currentData()

        # Disable button and show progress
        self.generate_btn.setEnabled(False)
        self.image_progress.setVisible(True)
        self.image_status_label.setText("Starting image generation...")

        # Create and start worker
        self._image_worker = ImageGenerationWorker(
            character=self.character,
            save_path=save_path,
            image_type=image_type
        )
        self._image_worker.finished.connect(self._on_image_generated)
        self._image_worker.error.connect(self._on_image_error)
        self._image_worker.progress.connect(self._on_image_progress)
        self._image_worker.start()

    def _on_image_progress(self, message: str):
        """Handle progress update from image generation."""
        self.image_status_label.setText(message)

    def _on_image_generated(self, image_path: Path):
        """Handle successful image generation."""
        self.image_progress.setVisible(False)
        self.generate_btn.setEnabled(True)

        if image_path and image_path.exists():
            # Update character model with new image path
            self.character.image_path = str(image_path)

            # Display the image
            pixmap = QPixmap(str(image_path))
            self.image_label.setPixmap(
                pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio)
            )

            self.image_status_label.setText(f"✓ Image saved: {image_path.name}")
            self.image_status_label.setStyleSheet("font-size: 11px; color: #059669;")
            self.content_changed.emit()
        else:
            self.image_status_label.setText("Image generation completed but file not found")
            self.image_status_label.setStyleSheet("font-size: 11px; color: #dc2626;")

    def _on_image_error(self, error: str):
        """Handle image generation error."""
        self.image_progress.setVisible(False)
        self.generate_btn.setEnabled(True)
        self.image_status_label.setText(f"Error: {error}")
        self.image_status_label.setStyleSheet("font-size: 11px; color: #dc2626;")

        QMessageBox.warning(
            self,
            "Image Generation Failed",
            f"Failed to generate image:\n\n{error}\n\n"
            "Make sure image generation is configured in Settings > Image Generation."
        )

    def save_to_model(self):
        """Save widget data to character model."""
        try:
            self.character.name = self.name_edit.text()
            self.character.character_type = self.type_combo.currentText().lower()
            self.character.physical_description = self.physical_desc_edit.toPlainText()
            self.character.personality = self.personality_edit.toPlainText()
            self.character.backstory = self.backstory_edit.toPlainText()
            self.character.notes = self.notes_edit.toPlainText()

            # Structured personality fields
            traits_text = self.traits_edit.text().strip()
            self.character.personality_traits = [
                t.strip() for t in traits_text.split(',') if t.strip()
            ] if traits_text else []
            self.character.motivations = self.motivations_edit.text().strip()
            self.character.fears = self.fears_edit.text().strip()
            self.character.speaking_style = self.speaking_style_edit.text().strip()
            self.character.emotional_baseline = self.emotional_baseline_edit.text().strip()

            # Story arc engine fields
            self.character.want = self.want_edit.text().strip()
            self.character.need = self.need_edit.text().strip()
            self.character.lie_they_believe = self.lie_edit.toPlainText().strip()
            self.character.ghost = self.ghost_edit.toPlainText().strip()
            self.character.character_arc = self.arc_type_combo.currentText().strip()

            # Depth fields
            self.character.moral_code = self.moral_code_edit.text().strip()
            self.character.worldview = self.worldview_edit.text().strip()
            self.character.secret = self.secret_edit.toPlainText().strip()
            self.character.contradictions = self.contradictions_edit.text().strip()
            self.character.defining_relationship = self.defining_relationship_edit.text().strip()
            self.character.quirks = self.quirks_edit.text().strip()

            self.character.updated_at = datetime.now()
        except RuntimeError:
            # Widget has been deleted — character model retains last saved state
            pass

    # --- Personality Arc Methods ---

    # --- Love Interest Methods ---

    def _refresh_love_list(self):
        """Refresh the love interests list widget."""
        self.love_list.clear()
        for li in getattr(self.character, 'love_interests', []):
            other = next(
                (c for c in self._available_characters if c.id == li.character_id),
                None)
            other_name = other.name if other else "(unknown character)"
            status = f" [{li.status}]" if li.status and li.status != "active" else ""
            label = f"{other_name} — {li.relationship_type}{status}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, li.character_id)
            self.love_list.addItem(item)

    def _add_love_interest(self):
        """Open dialog to add a new love interest."""
        if not self._available_characters:
            QMessageBox.information(
                self, "No Other Characters",
                "Add other characters to the project before creating a "
                "love-interest link.")
            return

        existing_ids = {li.character_id for li in
                        getattr(self.character, 'love_interests', [])}
        selectable = [c for c in self._available_characters
                      if c.id not in existing_ids]
        if not selectable:
            QMessageBox.information(
                self, "No More Characters",
                "This character already has love-interest links to every "
                "other character.")
            return

        dlg = _LoveInterestDialog(selectable, None, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_li = dlg.get_love_interest()
            if new_li:
                self.character.love_interests.append(new_li)
                self._refresh_love_list()
                self.content_changed.emit()

    def _edit_love_interest(self):
        """Edit the currently selected love interest."""
        item = self.love_list.currentItem()
        if not item:
            return
        target_id = item.data(Qt.ItemDataRole.UserRole)
        li = next((x for x in self.character.love_interests
                   if x.character_id == target_id), None)
        if not li:
            return

        # Allow picking any other character (including the currently linked one)
        dlg = _LoveInterestDialog(self._available_characters, li, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_love_interest()
            if updated:
                # Replace by character_id match
                for i, x in enumerate(self.character.love_interests):
                    if x.character_id == target_id:
                        self.character.love_interests[i] = updated
                        break
                self._refresh_love_list()
                self.content_changed.emit()

    def _remove_love_interest(self):
        """Remove the currently selected love interest."""
        item = self.love_list.currentItem()
        if not item:
            return
        target_id = item.data(Qt.ItemDataRole.UserRole)
        self.character.love_interests = [
            x for x in self.character.love_interests
            if x.character_id != target_id
        ]
        self._refresh_love_list()
        self.content_changed.emit()

    def _refresh_arc_list(self):
        """Refresh the personality arc list widget."""
        self.arc_list.clear()
        for snap in self.character.personality_arc:
            label = f"Ch{snap.chapter_number}: {snap.chapter_title}"
            if snap.emotional_state:
                label += f" — {snap.emotional_state}"
            if snap.is_ai_generated:
                label += " (AI)"
            item = QListWidgetItem(label)
            self.arc_list.addItem(item)

    def _on_arc_snapshot_selected(self, row: int):
        """Show details for the selected arc snapshot."""
        if row < 0 or row >= len(self.character.personality_arc):
            self.arc_detail.clear()
            return

        snap = self.character.personality_arc[row]
        parts = []
        if snap.traits_active:
            parts.append(f"Active traits: {', '.join(snap.traits_active)}")
        if snap.emotional_state:
            parts.append(f"Emotional state: {snap.emotional_state}")
        if snap.behavior_examples:
            parts.append(f"\nBehavior examples:\n{snap.behavior_examples}")
        if snap.growth_notes:
            parts.append(f"\nGrowth notes: {snap.growth_notes}")
        if snap.ai_assessment:
            parts.append(f"\nFull assessment:\n{snap.ai_assessment}")

        self.arc_detail.blockSignals(True)
        self.arc_detail.setPlainText("\n".join(parts))
        self.arc_detail.blockSignals(False)

    def _on_arc_detail_edited(self):
        """Save manual edits to the selected arc snapshot's assessment."""
        row = self.arc_list.currentRow()
        if row < 0 or row >= len(self.character.personality_arc):
            return
        snap = self.character.personality_arc[row]
        snap.ai_assessment = self.arc_detail.toPlainText()
        snap.is_ai_generated = False  # Mark as user-edited
        self.content_changed.emit()

    def _add_manual_snapshot(self):
        """Add a manual personality snapshot."""
        from src.models.project import PersonalitySnapshot

        # Let user pick a chapter
        chapters = self._get_chapters()
        if not chapters:
            QMessageBox.information(self, "No Chapters", "No chapters available.")
            return

        items = [f"{ch.number}. {ch.title}" for ch in chapters]
        from PyQt6.QtWidgets import QInputDialog
        choice, ok = QInputDialog.getItem(
            self, "Select Chapter",
            "Which chapter does this snapshot describe?",
            items, 0, False
        )
        if not ok:
            return

        idx = items.index(choice)
        ch = chapters[idx]

        snap = PersonalitySnapshot(
            chapter_id=ch.id,
            chapter_number=ch.number,
            chapter_title=ch.title,
        )
        self.character.personality_arc.append(snap)
        self.character.personality_arc.sort(key=lambda s: s.chapter_number)
        self._refresh_arc_list()
        self.content_changed.emit()

    def _remove_snapshot(self):
        """Remove the selected personality snapshot."""
        row = self.arc_list.currentRow()
        if row < 0 or row >= len(self.character.personality_arc):
            return
        self.character.personality_arc.pop(row)
        self._refresh_arc_list()
        self.arc_detail.clear()
        self.content_changed.emit()

    def _assess_personality(self):
        """Use AI to assess personality from a chapter's text."""
        chapters = self._get_chapters()
        if not chapters:
            QMessageBox.information(self, "No Chapters", "No chapters available.")
            return

        items = [f"{ch.number}. {ch.title}" for ch in chapters]
        from PyQt6.QtWidgets import QInputDialog
        choice, ok = QInputDialog.getItem(
            self, "Assess from Chapter",
            f"Analyze {self.character.name}'s personality in which chapter?",
            items, 0, False
        )
        if not ok:
            return

        idx = items.index(choice)
        ch = chapters[idx]

        # Load chapter content
        content = ch.content
        if not content or not content.strip():
            QMessageBox.warning(
                self, "Empty Chapter",
                "This chapter has no content to analyze."
            )
            return

        # Save current edits first
        self.save_to_model()

        # Initialize LLM
        try:
            from src.config.ai_config import get_ai_config
            from src.ai.llm_client import LLMClient, LLMProvider
            from src.ai.mlx_utils import can_use_mlx

            config = get_ai_config()
            if config.is_ai_disabled():
                QMessageBox.warning(self, "AI Disabled", "AI is disabled in settings.")
                return

            settings = config.get_settings()
            provider = settings.get("default_llm", "claude")
            api_key = config.get_api_key(provider)

            if api_key:
                provider_enum = {
                    "claude": LLMProvider.CLAUDE,
                    "chatgpt": LLMProvider.CHATGPT,
                    "openai": LLMProvider.CHATGPT,
                    "gemini": LLMProvider.GEMINI,
                }.get(provider, LLMProvider.CLAUDE)
                llm_client = LLMClient(
                    provider=provider_enum, api_key=api_key,
                    model=settings.get(f"{provider}_model", None)
                )
            elif can_use_mlx():
                local_model = settings.get(
                    "local_model_id", "mlx-community/Qwen2.5-7B-Instruct-4bit"
                )
                llm_client = LLMClient(provider=LLMProvider.MLX_LOCAL, model=local_model)
            else:
                QMessageBox.warning(self, "No AI", "No AI provider configured.")
                return
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to initialize AI:\n{e}")
            return

        # Build prior arc context
        prior = [
            {
                'number': s.chapter_number,
                'title': s.chapter_title,
                'emotional_state': s.emotional_state,
                'growth_notes': s.growth_notes,
            }
            for s in self.character.personality_arc
            if s.chapter_number < ch.number
        ]

        # Run assessment in a thread
        self.assess_btn.setEnabled(False)
        self.assess_btn.setText("Analyzing...")

        self._assess_worker = _PersonalityAssessWorker(
            self.character, content, ch.id, ch.number, ch.title, llm_client, prior
        )
        self._assess_worker.finished.connect(self._on_assessment_complete)
        self._assess_worker.error.connect(self._on_assessment_error)
        self._assess_worker.start()

    def _on_assessment_complete(self, snapshot):
        """Handle completed personality assessment."""
        self.assess_btn.setEnabled(True)
        self.assess_btn.setText("Assess from Writing")

        # Replace existing snapshot for same chapter, or append
        self.character.personality_arc = [
            s for s in self.character.personality_arc
            if s.chapter_id != snapshot.chapter_id
        ]
        self.character.personality_arc.append(snapshot)
        self.character.personality_arc.sort(key=lambda s: s.chapter_number)
        self._refresh_arc_list()

        # Select the new snapshot
        for i, s in enumerate(self.character.personality_arc):
            if s.chapter_id == snapshot.chapter_id:
                self.arc_list.setCurrentRow(i)
                break

        self.content_changed.emit()

    def _on_assessment_error(self, error_msg: str):
        """Handle assessment error."""
        self.assess_btn.setEnabled(True)
        self.assess_btn.setText("Assess from Writing")
        QMessageBox.warning(self, "Assessment Failed", f"AI assessment failed:\n\n{error_msg}")

    def _get_chapters(self):
        """Get chapters from the project."""
        if self._project and hasattr(self._project, 'manuscript'):
            return self._project.manuscript.chapters
        return []


class _PersonalityAssessWorker(QThread):
    """Background worker for personality assessment."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, character, content, ch_id, ch_num, ch_title, llm_client, prior):
        super().__init__()
        self.character = character
        self.content = content
        self.ch_id = ch_id
        self.ch_num = ch_num
        self.ch_title = ch_title
        self.llm_client = llm_client
        self.prior = prior

    def run(self):
        try:
            from src.ai.personality_assessor import assess_personality
            snapshot = assess_personality(
                self.character, self.content,
                self.ch_id, self.ch_num, self.ch_title,
                self.llm_client, self.prior
            )
            self.finished.emit(snapshot)
        except Exception as e:
            self.error.emit(str(e))


class CharactersWidget(QWidget):
    """Widget for managing all characters."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize characters widget."""
        super().__init__()
        self.characters: List[Character] = []
        self.current_character_widget: Optional[CharacterWidget] = None
        self._project = None
        self._project_path: Optional[Path] = None
        self._init_ui()

    def set_project(self, project: 'WriterProject'):
        """Set the project for accessing project path and chapter data.

        Args:
            project: The writer project
        """
        self._project = project
        if project and hasattr(project, 'project_path') and project.project_path:
            self._project_path = Path(project.project_path).parent
        else:
            self._project_path = None

    def _init_ui(self):
        """Initialize user interface."""
        layout = QHBoxLayout(self)

        # Left panel - character list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        list_label = QLabel("Characters")
        list_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px;")
        left_layout.addWidget(list_label)

        self.character_list = QListWidget()
        self.character_list.currentItemChanged.connect(self._on_character_selected)
        left_layout.addWidget(self.character_list)

        # Buttons
        button_layout = QHBoxLayout()

        add_button = QPushButton("Add")
        add_button.clicked.connect(self._add_character)
        button_layout.addWidget(add_button)

        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self._remove_character)
        button_layout.addWidget(remove_button)

        left_layout.addLayout(button_layout)

        self.strengthen_btn = QPushButton("🤖 Strengthen")
        self.strengthen_btn.setToolTip(
            "AI scans your manuscript to:\n"
            "• Enrich existing characters with personality, traits, descriptions\n"
            "• Discover new characters mentioned in chapters"
        )
        self.strengthen_btn.clicked.connect(self._strengthen_characters)
        left_layout.addWidget(self.strengthen_btn)

        left_panel.setMaximumWidth(250)
        layout.addWidget(left_panel)

        # Right panel - character details
        self.details_scroll = QScrollArea()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setWidget(QLabel("Select or add a character"))

        layout.addWidget(self.details_scroll, stretch=1)

    def _add_character(self):
        """Add new character."""
        from PyQt6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self,
            "New Character",
            "Enter character name:"
        )

        if ok and name:
            character = Character(
                id=str(uuid.uuid4()),
                name=name,
                character_type="minor"
            )
            self.characters.append(character)

            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, character.id)
            self.character_list.addItem(item)

            self.character_list.setCurrentItem(item)
            self.content_changed.emit()

    def _remove_character(self):
        """Remove selected character."""
        current_item = self.character_list.currentItem()
        if not current_item:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete '{current_item.text()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            character_id = current_item.data(Qt.ItemDataRole.UserRole)
            self.characters = [c for c in self.characters if c.id != character_id]

            row = self.character_list.row(current_item)
            self.character_list.takeItem(row)

            self.details_scroll.setWidget(QLabel("Select or add a character"))
            self.content_changed.emit()

    def _on_character_selected(self, current, previous):
        """Handle character selection change."""
        if not current:
            return

        # Save previous character
        if self.current_character_widget:
            self.current_character_widget.save_to_model()

        # Load selected character
        character_id = current.data(Qt.ItemDataRole.UserRole)
        character = next((c for c in self.characters if c.id == character_id), None)

        if character:
            # Other characters (for love-interest picker) — exclude self
            others = [c for c in self.characters if c.id != character.id]
            self.current_character_widget = CharacterWidget(
                character,
                project_path=self._project_path,
                project=self._project,
                available_characters=others,
            )
            self.current_character_widget.content_changed.connect(self.content_changed.emit)
            self.details_scroll.setWidget(self.current_character_widget)

    def _strengthen_characters(self):
        """Scan manuscript to enrich existing characters and discover new ones."""
        if not self._project:
            QMessageBox.information(self, "No Project", "Open a project first.")
            return

        if not hasattr(self._project, 'manuscript') or not self._project.manuscript.chapters:
            QMessageBox.information(self, "No Chapters", "Write some chapters first.")
            return

        # Save current character before analysis
        if self.current_character_widget:
            try:
                self.current_character_widget.save_to_model()
            except RuntimeError:
                pass

        self.strengthen_btn.setEnabled(False)
        self.strengthen_btn.setText("🤖 Analyzing...")

        self._strengthen_worker = _CharacterStrengthenWorker(
            self._project, self.characters
        )
        self._strengthen_worker.finished.connect(self._on_strengthen_done)
        self._strengthen_worker.error.connect(self._on_strengthen_error)
        self._strengthen_worker.start()

    def _on_strengthen_done(self, report: str, new_characters: list):
        """Handle strengthen completion."""
        self.strengthen_btn.setEnabled(True)
        self.strengthen_btn.setText("🤖 Strengthen")

        # Add any new characters
        for char in new_characters:
            self.characters.append(char)
            item = QListWidgetItem(char.name)
            item.setData(Qt.ItemDataRole.UserRole, char.id)
            self.character_list.addItem(item)

        # Refresh current character display if it was enriched
        if self.current_character_widget:
            try:
                self.current_character_widget._load_character()
            except RuntimeError:
                pass

        if new_characters or "Enriched" in report:
            self.content_changed.emit()

        QMessageBox.information(self, "Characters Strengthened", report)

    def _on_strengthen_error(self, msg: str):
        self.strengthen_btn.setEnabled(True)
        self.strengthen_btn.setText("🤖 Strengthen")
        QMessageBox.warning(self, "Error", msg)

    def load_data(self, characters: List[Character]):
        """Load characters data."""
        self.characters = characters
        self.character_list.clear()

        for character in characters:
            item = QListWidgetItem(character.name)
            item.setData(Qt.ItemDataRole.UserRole, character.id)
            self.character_list.addItem(item)

    def get_data(self) -> List[Character]:
        """Get characters data."""
        # Save current character (may fail if widget is being destroyed)
        if self.current_character_widget:
            try:
                self.current_character_widget.save_to_model()
            except RuntimeError:
                pass

        return self.characters


class _CharacterStrengthenWorker(QThread):
    """Background worker to enrich characters from manuscript and discover new ones."""

    finished = pyqtSignal(str, list)  # report, new_characters
    error = pyqtSignal(str)

    def __init__(self, project, existing_characters: list):
        super().__init__()
        self.project = project
        self.existing = existing_characters

    def run(self):
        try:
            import re
            from collections import Counter
            from src.utils.fuzzy_match import find_similar

            report = []
            new_characters = []

            # Load all chapter text
            chapter_texts = self._get_chapter_texts()
            if not chapter_texts:
                self.finished.emit("No chapter content found.", [])
                return

            all_text = "\n\n".join(chapter_texts.values())
            existing_names = {c.name.lower() for c in self.existing}

            # --- Phase 1: Enrich existing characters from manuscript ---
            enrichable = [
                ("personality", ["personality", "character", "temperament",
                                 "attitude", "demeanor", "manner", "always",
                                 "never", "tended", "way of", "kind of"]),
                ("physical_description", ["looked", "appearance", "wore", "hair",
                                          "eyes", "tall", "short", "scar", "face",
                                          "built", "thin", "muscular", "skin",
                                          "dressed", "beard", "cloak", "uniform"]),
                ("speaking_style", ["said", "spoke", "voice", "accent", "whispered",
                                    "shouted", "muttered", "drawled", "snapped",
                                    "tone", "words", "replied", "asked"]),
                ("backstory", ["remembered", "once", "used to", "before",
                               "years ago", "childhood", "grew up", "born",
                               "mother", "father", "family", "past", "history"]),
                ("motivations", ["wanted", "needed", "determined", "goal",
                                 "driven", "desperate", "hoped", "dreamed",
                                 "must", "sworn", "promised", "vowed"]),
                ("fears", ["feared", "afraid", "terrified", "dreaded",
                           "nightmare", "panic", "anxious", "haunted"]),
            ]

            from src.ai.field_synthesizer import synthesize_character_profile

            for char in self.existing:
                name = char.name
                if not name:
                    continue

                # Find all sentences mentioning this character
                char_sents = []
                for ch_title, ch_text in chapter_texts.items():
                    sents = re.split(r'(?<=[.!?])\s+', ch_text)
                    for s in sents:
                        if name.lower() in s.lower() and 15 < len(s) < 600:
                            char_sents.append((ch_title, s.strip()))

                if not char_sents:
                    continue

                # Gather existing field values
                existing_fields = {}
                for field, _ in enrichable:
                    val = getattr(char, field, '') or ''
                    if val and len(val) < 200:
                        existing_fields[field] = val

                # Single LLM call for full profile
                profile = synthesize_character_profile(
                    name=name,
                    manuscript_sentences=char_sents,
                    existing_fields=existing_fields,
                )

                enriched_fields = []
                for field, content in profile.items():
                    if not hasattr(char, field):
                        continue
                    current = getattr(char, field, '') or ''
                    if len(current) > 200:
                        continue
                    if content and content != current:
                        try:
                            setattr(char, field, synthesized)
                            enriched_fields.append(field)
                        except (AttributeError, TypeError, ValueError):
                            pass

                if enriched_fields:
                    report.append(
                        f"Enriched '{name}': {', '.join(enriched_fields)} "
                        f"({len(char_sents)} mentions)"
                    )

                # Extract personality traits (add to existing)
                existing_traits = set(getattr(char, 'personality_traits', []) or [])
                trait_keywords = [
                    "brave", "cowardly", "kind", "cruel", "clever", "stubborn",
                    "loyal", "treacherous", "gentle", "fierce", "proud", "humble",
                    "cautious", "reckless", "patient", "impatient", "generous",
                    "selfish", "honest", "deceptive", "calm", "anxious",
                    "confident", "insecure", "sarcastic", "earnest", "cold",
                    "warm", "quiet", "loud", "serious", "playful", "cynical",
                    "optimistic", "brooding", "compassionate", "ruthless",
                    "disciplined", "chaotic", "cheerful",
                ]
                found_traits = Counter()
                for _, sent in char_sents:
                    for trait in trait_keywords:
                        if trait in sent.lower():
                            found_traits[trait] += 1
                new_traits = [t for t, _ in found_traits.most_common(8)
                              if t not in existing_traits]
                if new_traits:
                    try:
                        char.personality_traits = list(existing_traits) + new_traits[:5]
                        report.append(f"Traits for '{name}': {', '.join(new_traits[:5])}")
                    except (AttributeError, TypeError):
                        pass

            # --- Phase 2: Discover new characters in manuscript ---
            # Only count names that appear MID-SENTENCE with dialogue/action verbs.
            # This avoids sentence-start capitalized words (He, She, The, etc.)
            # Pattern: punctuation or lowercase word, then Name + verb
            action_pattern = re.compile(
                r'(?<=[a-z,;:"\'\s])\b([A-Z][a-z]{2,15})\s+'
                r'(?:said|spoke|whispered|shouted|asked|replied|answered|'
                r'muttered|nodded|shook|turned|looked|walked|stepped|'
                r'stood|sat|smiled|frowned|stared|glanced|watched|'
                r'waited|thought|felt|knew|heard|saw|grinned|paused)\b'
            )
            # Dialogue: "..." said Name / "..." Name said
            dialogue_pattern = re.compile(
                r'[""]\s*(?:said|asked|replied|whispered|shouted)\s+'
                r'([A-Z][a-z]{2,15})\b'
            )
            # Possessive: Name's (strong character signal)
            possessive_pattern = re.compile(
                r"\b([A-Z][a-z]{2,15})(?:'s|'s)\s+\w"
            )

            name_counts = Counter()
            for ch_text in chapter_texts.values():
                for match in action_pattern.finditer(ch_text):
                    name_counts[match.group(1)] += 1
                for match in dialogue_pattern.finditer(ch_text):
                    name_counts[match.group(1)] += 1
                for match in possessive_pattern.finditer(ch_text):
                    name_counts[match.group(1)] += 1

            # Comprehensive skip list — ALL common English words that could
            # be capitalized at sentence start or in other contexts
            skip_words = {
                # Pronouns
                "he", "she", "his", "her", "him", "they", "them", "their",
                "its", "who", "whom", "whose",
                # Articles / determiners
                "the", "this", "that", "these", "those", "each", "every",
                "some", "any", "all", "both", "few", "many", "much",
                # Conjunctions / prepositions
                "and", "but", "for", "nor", "yet", "with", "from", "into",
                "onto", "upon", "about", "after", "before", "between",
                "through", "during", "against", "along", "among",
                # Common verbs
                "was", "were", "had", "have", "has", "been", "being",
                "would", "could", "should", "will", "can", "may", "might",
                "shall", "must", "did", "does", "said", "told", "made",
                "came", "went", "got", "took", "gave", "let", "put",
                "ran", "saw", "set", "sat", "stood", "thought", "felt",
                "knew", "heard", "found", "left", "kept", "began",
                # Common adverbs / adjectives
                "not", "just", "very", "also", "even", "still", "only",
                "then", "now", "here", "there", "when", "where", "what",
                "how", "why", "more", "most", "less", "well", "long",
                # Common nouns (non-name)
                "one", "two", "three", "time", "day", "night", "way",
                "man", "men", "woman", "women", "hand", "head", "eye",
                "eyes", "face", "room", "door", "back", "down", "part",
                "side", "end", "home", "house", "life", "world", "place",
                "chapter", "page", "section", "act", "scene", "part",
                # Story structure words
                "once", "first", "last", "next", "another", "other",
                "something", "nothing", "everything", "someone", "anyone",
                "everyone", "no one", "perhaps", "however", "although",
            }

            discovered = []
            for name, count in name_counts.most_common(30):
                if count < 2:
                    continue
                if name.lower() in existing_names:
                    continue
                if name.lower() in skip_words:
                    continue
                if find_similar(name, [c.name for c in self.existing], threshold=0.7):
                    continue
                if len(name) < 3:
                    continue
                discovered.append((name, count))

            # Create new characters from discoveries with proper profiles
            from src.ai.field_synthesizer import synthesize_character_profile

            for name, count in discovered[:8]:
                # Gather ALL context sentences for this name
                context_sents = []
                chapters_appeared = set()
                for ch_title, ch_text in chapter_texts.items():
                    sents = re.split(r'(?<=[.!?])\s+', ch_text)
                    for s in sents:
                        if name in s and 15 < len(s) < 600:
                            context_sents.append((ch_title, s.strip()))
                            chapters_appeared.add(ch_title)

                if not context_sents:
                    continue

                # Determine major vs minor based on manuscript presence
                if count >= 10 or len(chapters_appeared) >= 3:
                    char_type = "major"
                elif count >= 5 or len(chapters_appeared) >= 2:
                    char_type = "supporting"
                else:
                    char_type = "minor"

                # Single LLM call for full profile
                profile = synthesize_character_profile(
                    name=name,
                    manuscript_sentences=context_sents,
                )

                new_char = Character(
                    id=str(uuid.uuid4()),
                    name=name,
                    character_type=char_type,
                    personality=profile.get('personality', ''),
                    physical_description=profile.get('physical_description', ''),
                    backstory=profile.get('backstory', ''),
                    speaking_style=profile.get('speaking_style', ''),
                )
                new_characters.append(new_char)
                existing_names.add(name.lower())
                report.append(
                    f"Discovered '{name}' ({char_type}, {count} mentions "
                    f"in {len(chapters_appeared)} chapter(s))"
                )

            if not report:
                report.append("No changes needed — characters look solid.")

            self.finished.emit("\n".join(report), new_characters)

        except Exception as e:
            self.error.emit(str(e))

    def _get_chapter_texts(self) -> dict:
        if not hasattr(self.project, 'manuscript'):
            return {}
        from pathlib import Path
        project_dir = None
        if hasattr(self.project, 'project_path') and self.project.project_path:
            project_dir = Path(self.project.project_path).parent
        result = {}
        for ch in self.project.manuscript.chapters:
            content = getattr(ch, 'content', '')
            if not content and project_dir:
                try:
                    ch.load_content_from_file(project_dir)
                    content = getattr(ch, 'content', '')
                except Exception:
                    pass
            if content:
                title = getattr(ch, 'title', f"Ch {getattr(ch, 'number', '?')}")
                result[title] = content
        return result


class _SingleCharacterWorker(QThread):
    """Background worker to gather manuscript evidence for a character.

    The heavy text scanning runs in the background, but the LLM call
    happens on the main thread (via the evidence_ready signal) to avoid
    Metal GPU thread conflicts.
    """

    # Emits gathered data for the main thread to run the LLM call
    evidence_ready = pyqtSignal(str, list, dict)  # name, all_sents, existing_fields
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, character, project):
        super().__init__()
        self.character = character
        self.project = project

    def run(self):
        try:
            import re
            from collections import Counter

            name = self.character.name
            if not name:
                self.finished.emit("Character has no name.")
                return

            # Load chapter texts
            chapter_texts = {}
            if hasattr(self.project, 'manuscript'):
                from pathlib import Path
                project_dir = None
                if hasattr(self.project, 'project_path') and self.project.project_path:
                    project_dir = Path(self.project.project_path).parent
                for ch in self.project.manuscript.chapters:
                    content = getattr(ch, 'content', '')
                    if not content and project_dir:
                        try:
                            ch.load_content_from_file(project_dir)
                            content = getattr(ch, 'content', '')
                        except Exception:
                            pass
                    if content:
                        title = getattr(ch, 'title', f"Ch {getattr(ch, 'number', '?')}")
                        chapter_texts[title] = content

            if not chapter_texts:
                self.finished.emit("No chapter content found.")
                return

            # Find all sentences mentioning this character
            all_sents = []
            for ch_title, ch_text in chapter_texts.items():
                sents = re.split(r'(?<=[.!?])\s+', ch_text)
                for s in sents:
                    if name.lower() in s.lower() and 20 < len(s) < 500:
                        all_sents.append((ch_title, s.strip()))

            if not all_sents:
                self.finished.emit(
                    f"'{name}' not found in any chapter text. "
                    "Write some scenes with this character first."
                )
                return

            # Gather existing field values
            existing_fields = {}
            for field in ['personality', 'physical_description', 'speaking_style',
                          'backstory', 'motivations', 'fears', 'emotional_baseline']:
                val = getattr(self.character, field, '') or ''
                if val and len(val) < 200:
                    existing_fields[field] = val

            # Extract traits (no LLM needed)
            traits = set(getattr(self.character, 'personality_traits', []) or [])
            trait_keywords = [
                "brave", "cowardly", "kind", "cruel", "clever",
                "stubborn", "loyal", "gentle", "fierce", "proud",
                "humble", "cautious", "reckless", "generous", "selfish",
                "honest", "calm", "anxious", "confident", "sarcastic",
                "cold", "warm", "quiet", "serious", "playful",
                "cynical", "optimistic", "compassionate", "ruthless",
            ]
            found_traits = Counter()
            for _, sent in all_sents:
                for trait in trait_keywords:
                    if trait in sent.lower():
                        found_traits[trait] += 1
            new_traits = [t for t, _ in found_traits.most_common(6) if t not in traits]
            if new_traits:
                try:
                    self.character.personality_traits = list(traits) + new_traits[:5]
                except (AttributeError, TypeError):
                    pass

            # Find associated names (no LLM needed)
            nearby = Counter()
            skip = {"the", "and", "but", "was", "were", "had", "have", "they",
                    "them", "she", "her", "his", "him", "this", "that", "said"}
            for _, sent in all_sents:
                for w in re.findall(r'\b([A-Z][a-z]{2,15})\b', sent):
                    if w.lower() != name.lower() and w.lower() not in skip:
                        nearby[w] += 1
            associated = [n for n, c in nearby.most_common(10) if c >= 2]
            if associated:
                notes = getattr(self.character, 'notes', '') or ''
                if "associated" not in notes.lower():
                    try:
                        addition = f"Associated with: {', '.join(associated[:8])}"
                        self.character.notes = f"{notes}\n\n{addition}" if notes else addition
                    except (AttributeError, TypeError, ValueError):
                        pass

            # --- LLM synthesis (same pattern as ChatWorker) ---
            self._ai_report = []
            try:
                from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig
                from src.config.ai_config import get_ai_config

                ai_config = get_ai_config()
                settings = ai_config.get_settings()
                prefer_local = settings.get("prefer_local_model", False)
                enable_local = settings.get("enable_local_models", False)
                local_model_id = settings.get("local_model_id", "")

                llm = None
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
                    api_key = ai_config.get_api_key(provider_name)
                    if api_key:
                        provider_enum = {
                            "claude": LLMProvider.CLAUDE, "chatgpt": LLMProvider.CHATGPT,
                            "openai": LLMProvider.CHATGPT, "gemini": LLMProvider.GEMINI,
                        }.get(provider_name, LLMProvider.CLAUDE)
                        llm = LLMClient(
                            provider=provider_enum, api_key=api_key,
                            model=ai_config.get_model(provider_name)
                        )

                if llm:
                    from src.ai.field_synthesizer import synthesize_character_profile

                    print(f"[Strengthen] Calling synthesize_character_profile for '{name}' "
                          f"with {len(all_sents)} sentences, llm={type(llm).__name__}")

                    profile = synthesize_character_profile(
                        name=name,
                        manuscript_sentences=all_sents,
                        existing_fields=existing_fields,
                        llm_client=llm
                    )

                    print(f"[Strengthen] Profile result: {list(profile.keys())} "
                          f"({sum(len(v) for v in profile.values())} total chars)")

                    ai_enriched = []
                    for field, content in profile.items():
                        if not hasattr(self.character, field):
                            continue
                        current = getattr(self.character, field, '') or ''
                        if len(current) > 200:
                            continue
                        if content and content != current:
                            try:
                                setattr(self.character, field, content)
                                ai_enriched.append(field)
                            except (AttributeError, TypeError, ValueError):
                                pass
                    if ai_enriched:
                        self._ai_report.append(f"AI enriched: {', '.join(ai_enriched)}")
            except Exception as e:
                self._ai_report.append(f"(AI synthesis skipped: {e})")

            # Emit evidence for the main thread to fill remaining fields
            print(f"[Worker] Emitting evidence_ready: name='{name}', "
                  f"sents={len(all_sents)}, fields={list(existing_fields.keys())}")
            print(f"[Worker] Character personality on model: "
                  f"'{getattr(self.character, 'personality', '')[:80]}'")
            self.evidence_ready.emit(name, all_sents, existing_fields)

        except Exception as e:
            self.error.emit(str(e))
