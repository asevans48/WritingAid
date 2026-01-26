"""Characters widget with image upload and AI image generation."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox,
    QFileDialog, QGroupBox, QFormLayout, QScrollArea, QMessageBox,
    QProgressBar
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread
from PyQt6.QtGui import QPixmap
from typing import List, Optional, TYPE_CHECKING
import uuid
import shutil
from pathlib import Path
from datetime import datetime

from src.models.project import Character

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


class CharacterWidget(QWidget):
    """Widget for editing a single character."""

    content_changed = pyqtSignal()

    def __init__(self, character: Character, project_path: Optional[Path] = None):
        """Initialize character widget.

        Args:
            character: The character to edit
            project_path: Path to the project directory for saving generated images
        """
        super().__init__()
        self.character = character
        self._project_path = project_path
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
        self.personality_edit.setPlaceholderText("Describe personality traits, quirks, motivations...")
        self.personality_edit.textChanged.connect(self.content_changed.emit)
        personality_layout.addWidget(self.personality_edit)

        personality_group.setLayout(personality_layout)
        layout.addWidget(personality_group)

        # Backstory
        backstory_group = QGroupBox("Backstory")
        backstory_layout = QVBoxLayout()

        self.backstory_edit = QTextEdit()
        self.backstory_edit.setPlaceholderText("Character history and background...")
        self.backstory_edit.textChanged.connect(self.content_changed.emit)
        backstory_layout.addWidget(self.backstory_edit)

        backstory_group.setLayout(backstory_layout)
        layout.addWidget(backstory_group)

        # Notes
        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout()

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Additional notes...")
        self.notes_edit.textChanged.connect(self.content_changed.emit)
        notes_layout.addWidget(self.notes_edit)

        notes_group.setLayout(notes_layout)
        layout.addWidget(notes_group)

        # AI help button
        ai_button = QPushButton("Get AI Character Development Help")
        ai_button.clicked.connect(self._request_ai_help)
        layout.addWidget(ai_button)

        # Set content widget to scroll area and add to main layout
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

    def _load_character(self):
        """Load character data into widgets."""
        self.name_edit.setText(self.character.name)
        self.type_combo.setCurrentText(self.character.character_type.capitalize())
        self.physical_desc_edit.setPlainText(self.character.physical_description)
        self.personality_edit.setPlainText(self.character.personality)
        self.backstory_edit.setPlainText(self.character.backstory)
        self.notes_edit.setPlainText(self.character.notes)

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

    def _request_ai_help(self):
        """Request AI help for character development."""
        # TODO: Integrate with AI client
        QMessageBox.information(
            self,
            "AI Help",
            "AI character development assistance will be integrated soon."
        )

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
        self.character.name = self.name_edit.text()
        self.character.character_type = self.type_combo.currentText().lower()
        self.character.physical_description = self.physical_desc_edit.toPlainText()
        self.character.personality = self.personality_edit.toPlainText()
        self.character.backstory = self.backstory_edit.toPlainText()
        self.character.notes = self.notes_edit.toPlainText()


class CharactersWidget(QWidget):
    """Widget for managing all characters."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize characters widget."""
        super().__init__()
        self.characters: List[Character] = []
        self.current_character_widget: Optional[CharacterWidget] = None
        self._project_path: Optional[Path] = None
        self._init_ui()

    def set_project(self, project: 'WriterProject'):
        """Set the project for accessing project path.

        Args:
            project: The writer project
        """
        if project and hasattr(project, 'project_path') and project.project_path:
            # project_path points to project.json, get parent directory
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
            self.current_character_widget = CharacterWidget(
                character,
                project_path=self._project_path
            )
            self.current_character_widget.content_changed.connect(self.content_changed.emit)
            self.details_scroll.setWidget(self.current_character_widget)

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
        # Save current character
        if self.current_character_widget:
            self.current_character_widget.save_to_model()

        return self.characters
