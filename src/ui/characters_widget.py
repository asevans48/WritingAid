"""Characters widget with image upload and social networks."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox,
    QFileDialog, QGroupBox, QFormLayout, QScrollArea, QMessageBox
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QPixmap
from typing import List
import uuid
from pathlib import Path

from src.models.project import Character


class CharacterWidget(QWidget):
    """Widget for editing a single character."""

    content_changed = pyqtSignal()

    def __init__(self, character: Character):
        """Initialize character widget."""
        super().__init__()
        self.character = character
        self._init_ui()
        self._load_character()

    def _init_ui(self):
        """Initialize user interface."""
        layout = QVBoxLayout(self)

        # Character image
        image_group = QGroupBox("Character Image")
        image_layout = QVBoxLayout()

        self.image_label = QLabel("No image")
        self.image_label.setFixedSize(200, 200)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("border: 1px solid #ccc; background: #f0f0f0;")
        image_layout.addWidget(self.image_label)

        upload_button = QPushButton("Upload Image")
        upload_button.clicked.connect(self._upload_image)
        image_layout.addWidget(upload_button)

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

    def _load_character(self):
        """Load character data into widgets."""
        self.name_edit.setText(self.character.name)
        self.type_combo.setCurrentText(self.character.character_type.capitalize())
        self.personality_edit.setPlainText(self.character.personality)
        self.backstory_edit.setPlainText(self.character.backstory)
        self.notes_edit.setPlainText(self.character.notes)

        if self.character.image_path and Path(self.character.image_path).exists():
            pixmap = QPixmap(self.character.image_path)
            self.image_label.setPixmap(
                pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio)
            )

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

    def save_to_model(self):
        """Save widget data to character model."""
        self.character.name = self.name_edit.text()
        self.character.character_type = self.type_combo.currentText().lower()
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
        self.current_character_widget = None
        self._init_ui()

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
            self.current_character_widget = CharacterWidget(character)
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
