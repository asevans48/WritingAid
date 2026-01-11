"""Image and cover art generator widget."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTextEdit, QComboBox, QGroupBox,
    QMessageBox, QFileDialog
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QPixmap
from typing import List
import uuid

from src.models.project import GeneratedImage


class ImageGeneratorWidget(QWidget):
    """Widget for generating cover art and scene images."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize image generator widget."""
        super().__init__()
        self.images: List[GeneratedImage] = []
        self._init_ui()

    def _init_ui(self):
        """Initialize user interface."""
        layout = QVBoxLayout(self)

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
        type_layout.addWidget(self.type_combo)

        generator_layout.addLayout(type_layout)

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

        self.image_list = QListWidget()
        self.image_list.currentItemChanged.connect(self._on_image_selected)
        gallery_layout.addWidget(self.image_list)

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

    def _generate_image(self):
        """Generate image using AI."""
        description = self.description_edit.toPlainText().strip()
        if not description:
            QMessageBox.warning(
                self,
                "Missing Description",
                "Please enter a description for the image."
            )
            return

        # TODO: Integrate with AI image generation
        QMessageBox.information(
            self,
            "Image Generation",
            "AI image generation will be integrated soon.\n\n"
            "This will use DALL-E, Stable Diffusion, or similar services."
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
        """Save selected image to file."""
        current_item = self.image_list.currentItem()
        if not current_item:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Image",
            "",
            "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*)"
        )

        if file_path:
            # TODO: Implement image saving
            QMessageBox.information(
                self,
                "Save Image",
                f"Image will be saved to: {file_path}"
            )

    def load_data(self, images: List[GeneratedImage]):
        """Load generated images."""
        self.images = images
        self.image_list.clear()

        for image in images:
            item = QListWidgetItem(f"{image.image_type}: {image.id[:8]}")
            item.setData(Qt.ItemDataRole.UserRole, image.id)
            self.image_list.addItem(item)

    def get_data(self) -> List[GeneratedImage]:
        """Get generated images data."""
        return self.images
