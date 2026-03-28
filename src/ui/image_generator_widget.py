"""Image and cover art generator widget."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTextEdit, QComboBox, QGroupBox,
    QMessageBox, QFileDialog, QScrollArea, QProgressDialog,
    QInputDialog, QMenu
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread
from PyQt6.QtGui import QPixmap, QAction
from typing import List, Optional
from pathlib import Path
import uuid
import logging

from src.models.project import GeneratedImage, Character
from src.ai.image_generation_agent import get_image_generation_agent

logger = logging.getLogger(__name__)


class ImageGenerationWorker(QThread):
    """Worker thread for image generation to avoid blocking UI."""

    finished = pyqtSignal(object)  # Emits Path or None
    error = pyqtSignal(str)

    def __init__(self, image_type: str, prompt: str, style: str = "", character: Optional[Character] = None):
        super().__init__()
        self.image_type = image_type
        self.prompt = prompt
        self.style = style
        self.character = character

    def run(self):
        """Run image generation in background."""
        try:
            agent = get_image_generation_agent()

            if self.image_type == "Character Portrait" and self.character:
                result_path = agent.generate_character_image(
                    character=self.character,
                    additional_prompt=self.style
                )
            else:
                # Scene or cover art
                combined_prompt = self.prompt
                if self.style:
                    combined_prompt = f"{self.prompt}, {self.style}"

                result_path = agent.generate_scene_image(
                    scene_description=combined_prompt,
                    style=""
                )

            self.finished.emit(result_path)

        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            self.error.emit(str(e))


class ImageGeneratorWidget(QWidget):
    """Widget for generating cover art and scene images."""

    content_changed = pyqtSignal()

    def __init__(self, characters: Optional[List[Character]] = None):
        """Initialize image generator widget.

        Args:
            characters: Optional list of characters for portrait generation
        """
        super().__init__()
        self.images: List[GeneratedImage] = []
        self.characters = characters or []
        self.selected_character: Optional[Character] = None
        self.worker: Optional[ImageGenerationWorker] = None
        self._init_ui()

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

        # Header
        header = QLabel("Image & Cover Art Generator")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(header)

        # Generator section
        generator_group = QGroupBox("Generate New Image")
        generator_layout = QVBoxLayout()

        # Image type
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Image Type:"))

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Cover Art", "Character Portrait", "Scene Visualization"])
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        type_layout.addWidget(self.type_combo)

        generator_layout.addLayout(type_layout)

        # Character selection (shown only for character portraits)
        self.character_layout = QHBoxLayout()
        self.character_layout.addWidget(QLabel("Character:"))

        self.character_combo = QComboBox()
        self._update_character_list()
        self.character_combo.currentIndexChanged.connect(self._on_character_selected)
        self.character_layout.addWidget(self.character_combo)

        self.character_widget = QWidget()
        self.character_widget.setLayout(self.character_layout)
        self.character_widget.setVisible(False)  # Hidden by default
        generator_layout.addWidget(self.character_widget)

        # Description
        generator_layout.addWidget(QLabel("Description:"))
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Describe the image you want to generate...")
        self.description_edit.setMaximumHeight(100)
        generator_layout.addWidget(self.description_edit)

        # Style preferences
        generator_layout.addWidget(QLabel("Style Preferences (optional):"))
        self.style_edit = QTextEdit()
        self.style_edit.setPlaceholderText("e.g., photorealistic, oil painting, digital art, fantasy, sci-fi...")
        self.style_edit.setMaximumHeight(60)
        generator_layout.addWidget(self.style_edit)

        # Generate button
        generate_button = QPushButton("Generate Image")
        generate_button.clicked.connect(self._generate_image)
        generator_layout.addWidget(generate_button)

        generator_group.setLayout(generator_layout)
        layout.addWidget(generator_group)

        # Image gallery
        gallery_group = QGroupBox("Generated Images")
        gallery_layout = QHBoxLayout()

        # Image list with context menu
        list_container = QVBoxLayout()

        self.image_list = QListWidget()
        self.image_list.currentItemChanged.connect(self._on_image_selected)
        self.image_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.image_list.customContextMenuRequested.connect(self._show_image_context_menu)
        list_container.addWidget(self.image_list)

        # Rename / Delete buttons
        list_btn_layout = QHBoxLayout()
        rename_btn = QPushButton("Rename")
        rename_btn.setToolTip("Rename the selected image")
        rename_btn.clicked.connect(self._rename_image)
        list_btn_layout.addWidget(rename_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setToolTip("Delete the selected image")
        delete_btn.clicked.connect(self._delete_image)
        list_btn_layout.addWidget(delete_btn)

        list_btn_layout.addStretch()
        list_container.addLayout(list_btn_layout)

        gallery_layout.addLayout(list_container)

        # Image preview
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)

        self.preview_label = QLabel("No image selected")
        self.preview_label.setFixedSize(400, 400)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("border: 1px solid #ccc; background: #f0f0f0;")
        preview_layout.addWidget(self.preview_label)

        self.prompt_display = QTextEdit()
        self.prompt_display.setReadOnly(True)
        self.prompt_display.setMaximumHeight(80)
        self.prompt_display.setPlaceholderText("Image prompt will appear here")
        preview_layout.addWidget(self.prompt_display)

        save_button = QPushButton("Save Image As...")
        save_button.clicked.connect(self._save_image)
        preview_layout.addWidget(save_button)

        gallery_layout.addWidget(preview_widget)

        gallery_group.setLayout(gallery_layout)
        layout.addWidget(gallery_group)

        # Set content widget to scroll area and add to main layout
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

    def _generate_image(self):
        """Generate image using AI."""
        image_type = self.type_combo.currentText()

        # Validate character portrait requirements
        if image_type == "Character Portrait":
            if not self.selected_character:
                QMessageBox.warning(
                    self,
                    "No Character Selected",
                    "Please select a character for portrait generation."
                )
                return
        else:
            # For non-character images, require description
            description = self.description_edit.toPlainText().strip()
            if not description:
                QMessageBox.warning(
                    self,
                    "Missing Description",
                    "Please enter a description for the image."
                )
                return

        # Get inputs
        description = self.description_edit.toPlainText().strip()
        style = self.style_edit.toPlainText().strip()

        # Start generation in worker thread
        self.worker = ImageGenerationWorker(
            image_type=image_type,
            prompt=description,
            style=style,
            character=self.selected_character if image_type == "Character Portrait" else None
        )
        self.worker.finished.connect(self._on_generation_finished)
        self.worker.error.connect(self._on_generation_error)
        self.worker.start()

        # Show progress dialog
        self.progress = QProgressDialog("Generating image...", "Cancel", 0, 0, self)
        self.progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.canceled.connect(self._cancel_generation)
        self.progress.show()

    def _cancel_generation(self):
        """Cancel ongoing generation."""
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
            logger.info("Image generation cancelled by user")

    def _on_generation_finished(self, result_path: Optional[Path]):
        """Handle completion of image generation."""
        if self.progress:
            self.progress.close()

        if result_path and result_path.exists():
            # Create GeneratedImage entry
            image_type = self.type_combo.currentText().lower().replace(" ", "_")
            image = GeneratedImage(
                id=str(uuid.uuid4()),
                image_path=str(result_path),
                prompt=self.description_edit.toPlainText().strip(),
                image_type=image_type,
                associated_id=self.selected_character.id if self.selected_character else None
            )
            self.images.append(image)

            # Update UI
            item = QListWidgetItem(f"{image_type}: {image.id[:8]}")
            item.setData(Qt.ItemDataRole.UserRole, image.id)
            self.image_list.addItem(item)
            self.image_list.setCurrentItem(item)

            self.content_changed.emit()

            QMessageBox.information(
                self,
                "Success",
                f"Image generated successfully!\n\nSaved to: {result_path}"
            )
        else:
            QMessageBox.critical(
                self,
                "Generation Failed",
                "Failed to generate image. Check logs for details."
            )

    def _on_generation_error(self, error_msg: str):
        """Handle generation error."""
        if self.progress:
            self.progress.close()

        QMessageBox.critical(
            self,
            "Error",
            f"Image generation failed:\n\n{error_msg}"
        )

    def _on_image_selected(self, current, previous):
        """Handle image selection."""
        if not current:
            return

        image_id = current.data(Qt.ItemDataRole.UserRole)
        image = next((img for img in self.images if img.id == image_id), None)

        if image:
            pixmap = QPixmap(image.image_path)
            self.preview_label.setPixmap(
                pixmap.scaled(400, 400, Qt.AspectRatioMode.KeepAspectRatio)
            )
            self.prompt_display.setPlainText(image.prompt)

    def _save_image(self):
        """Save selected image to a new location."""
        current_item = self.image_list.currentItem()
        if not current_item:
            return

        image_id = current_item.data(Qt.ItemDataRole.UserRole)
        image = next((img for img in self.images if img.id == image_id), None)
        if not image:
            return

        source = Path(image.image_path)
        if not source.exists():
            QMessageBox.warning(self, "File Not Found", f"Source image not found:\n{source}")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Image", source.name,
            "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*)"
        )
        if file_path:
            import shutil
            try:
                shutil.copy2(str(source), file_path)
                QMessageBox.information(self, "Saved", f"Image saved to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save image:\n{e}")

    def _show_image_context_menu(self, position):
        """Show context menu for image list."""
        item = self.image_list.itemAt(position)
        if not item:
            return

        menu = QMenu(self)
        rename_action = menu.addAction("Rename")
        delete_action = menu.addAction("Delete")
        menu.addSeparator()
        save_action = menu.addAction("Save As...")

        action = menu.exec(self.image_list.mapToGlobal(position))
        if action == rename_action:
            self._rename_image()
        elif action == delete_action:
            self._delete_image()
        elif action == save_action:
            self._save_image()

    def _rename_image(self):
        """Rename the selected image."""
        current_item = self.image_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "No Selection", "Select an image to rename.")
            return

        image_id = current_item.data(Qt.ItemDataRole.UserRole)
        image = next((img for img in self.images if img.id == image_id), None)
        if not image:
            return

        # Use current display name as default
        current_name = current_item.text()
        new_name, ok = QInputDialog.getText(
            self, "Rename Image", "Enter a new name:", text=current_name
        )
        if ok and new_name.strip():
            # Store custom display name on the model
            image.display_name = new_name.strip()
            current_item.setText(new_name.strip())
            self.content_changed.emit()

    def _delete_image(self):
        """Delete the selected image."""
        current_item = self.image_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "No Selection", "Select an image to delete.")
            return

        image_id = current_item.data(Qt.ItemDataRole.UserRole)
        image = next((img for img in self.images if img.id == image_id), None)
        if not image:
            return

        reply = QMessageBox.question(
            self, "Delete Image",
            f"Delete this image?\n\nThis will remove the file from disk.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Remove from disk
        file_path = Path(image.image_path)
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception as e:
                logger.warning(f"Could not delete image file: {e}")

        # Remove from data
        self.images = [img for img in self.images if img.id != image_id]

        # Remove from list
        row = self.image_list.row(current_item)
        self.image_list.takeItem(row)

        # Clear preview
        self.preview_label.setText("No image selected")
        self.preview_label.setPixmap(QPixmap())
        self.prompt_display.clear()

        self.content_changed.emit()

    def _on_type_changed(self, image_type: str):
        """Handle image type change."""
        # Show/hide character selection for character portraits
        self.character_widget.setVisible(image_type == "Character Portrait")

        # Auto-fill description if character is selected
        if image_type == "Character Portrait" and self.selected_character:
            self._update_description_for_character()

    def _on_character_selected(self, index: int):
        """Handle character selection."""
        if index >= 0 and index < len(self.characters):
            self.selected_character = self.characters[index]
            self._update_description_for_character()
        else:
            self.selected_character = None

    def _update_character_list(self):
        """Update character combo box."""
        self.character_combo.clear()
        for char in self.characters:
            self.character_combo.addItem(char.name)

        # Auto-select first character if available
        if self.characters:
            self.character_combo.setCurrentIndex(0)
            self.selected_character = self.characters[0]

    def _update_description_for_character(self):
        """Auto-fill description from character info."""
        if not self.selected_character:
            return

        char = self.selected_character
        parts = []

        if char.physical_description:
            parts.append(char.physical_description)
        else:
            # Fallback to generic description
            parts.append(f"Portrait of {char.name}")

        if char.personality:
            parts.append(f"Personality: {char.personality[:100]}")

        self.description_edit.setPlainText("\n".join(parts))

    def set_characters(self, characters: List[Character]):
        """Update available characters."""
        self.characters = characters
        self._update_character_list()

    def load_data(self, images: List[GeneratedImage]):
        """Load generated images."""
        self.images = images
        self.image_list.clear()

        for image in images:
            label = image.display_name or f"{image.image_type}: {image.id[:8]}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, image.id)
            self.image_list.addItem(item)

    def get_data(self) -> List[GeneratedImage]:
        """Get generated images data."""
        return self.images
