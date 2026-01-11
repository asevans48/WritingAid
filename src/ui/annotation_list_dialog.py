"""Annotation list dialog - view and search all annotations in current chapter."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QLabel, QTextEdit, QSplitter,
    QGroupBox, QMessageBox, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from typing import List

from src.models.project import Annotation


class AnnotationListDialog(QDialog):
    """Dialog for viewing and searching annotations."""

    jump_to_line = pyqtSignal(int)  # line_number
    edit_annotation = pyqtSignal(str)  # annotation_id
    delete_annotation = pyqtSignal(str)  # annotation_id

    def __init__(self, annotations: List[Annotation], parent=None):
        """Initialize annotation list dialog."""
        super().__init__(parent)
        self.annotations = annotations
        self.filtered_annotations = annotations.copy()
        self._init_ui()
        self._update_list()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Annotations")
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)

        # Search bar
        search_layout = QHBoxLayout()
        search_label = QLabel("Search:")
        search_layout.addWidget(search_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search annotations...")
        self.search_input.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self.search_input)

        layout.addLayout(search_layout)

        # Splitter for list and preview
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Annotation list
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)

        list_label = QLabel("Annotations")
        list_label.setStyleSheet("font-weight: bold; margin: 8px 0;")
        list_layout.addWidget(list_label)

        self.annotation_list = QListWidget()
        self.annotation_list.itemClicked.connect(self._on_annotation_clicked)
        self.annotation_list.itemDoubleClicked.connect(self._on_annotation_double_clicked)
        list_layout.addWidget(self.annotation_list)

        splitter.addWidget(list_widget)

        # Right: Preview panel
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(8, 0, 0, 0)

        preview_label = QLabel("Preview")
        preview_label.setStyleSheet("font-weight: bold; margin: 8px 0;")
        preview_layout.addWidget(preview_label)

        self.preview_group = QGroupBox("No annotation selected")
        preview_group_layout = QVBoxLayout()

        self.preview_content = QTextEdit()
        self.preview_content.setReadOnly(True)
        self.preview_content.setPlaceholderText("Select an annotation to view details...")
        preview_group_layout.addWidget(self.preview_content)

        # Action buttons
        button_layout = QHBoxLayout()

        self.jump_button = QPushButton("Jump to Line")
        self.jump_button.clicked.connect(self._jump_to_selected)
        self.jump_button.setEnabled(False)
        button_layout.addWidget(self.jump_button)

        self.edit_button = QPushButton("Edit")
        self.edit_button.clicked.connect(self._edit_selected)
        self.edit_button.setEnabled(False)
        button_layout.addWidget(self.edit_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self._delete_selected)
        self.delete_button.setEnabled(False)
        button_layout.addWidget(self.delete_button)

        preview_group_layout.addLayout(button_layout)

        self.preview_group.setLayout(preview_group_layout)
        preview_layout.addWidget(self.preview_group)

        splitter.addWidget(preview_widget)

        # Set splitter sizes
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

    def _on_search_changed(self, text: str):
        """Handle search text change."""
        text = text.lower().strip()

        if not text:
            self.filtered_annotations = self.annotations.copy()
        else:
            self.filtered_annotations = [
                a for a in self.annotations
                if text in a.content.lower() or
                   text in a.annotation_type.lower() or
                   (a.referenced_name and text in a.referenced_name.lower())
            ]

        self._update_list()

    def _update_list(self):
        """Update annotation list display."""
        self.annotation_list.clear()

        # Sort by line number
        sorted_annotations = sorted(self.filtered_annotations, key=lambda a: a.line_number)

        for annotation in sorted_annotations:
            # Create display text
            type_icon = {"note": "📝", "attribution": "🔗", "recommendation": "💡"}
            icon = type_icon.get(annotation.annotation_type, "📝")

            preview = annotation.content[:50] + "..." if len(annotation.content) > 50 else annotation.content
            text = f"{icon} Line {annotation.line_number}: {preview}"

            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, annotation.id)

            # Color code by type
            if annotation.annotation_type == "attribution":
                item.setBackground(QBrush(QColor(230, 244, 255)))  # Light blue
            elif annotation.annotation_type == "recommendation":
                item.setBackground(QBrush(QColor(255, 250, 230)))  # Light yellow

            self.annotation_list.addItem(item)

    def _on_annotation_clicked(self, item):
        """Handle annotation click."""
        annotation_id = item.data(Qt.ItemDataRole.UserRole)
        annotation = next((a for a in self.annotations if a.id == annotation_id), None)

        if not annotation:
            return

        # Update preview
        type_icon = {"note": "📝", "attribution": "🔗", "recommendation": "💡"}
        icon = type_icon.get(annotation.annotation_type, "📝")

        self.preview_group.setTitle(f"{icon} {annotation.annotation_type.capitalize()} - Line {annotation.line_number}")

        # Build preview text
        preview_text = f"**Content:**\n{annotation.content}\n\n"

        if annotation.annotation_type == "attribution" and annotation.referenced_name:
            preview_text += f"**References:**\n"
            preview_text += f"Type: {annotation.referenced_type or 'Unknown'}\n"
            preview_text += f"Name: {annotation.referenced_name}\n"

        preview_text += f"\n**Location:**\nLine {annotation.line_number}"

        self.preview_content.setMarkdown(preview_text)
        self.jump_button.setEnabled(True)
        self.edit_button.setEnabled(True)
        self.delete_button.setEnabled(True)

    def _on_annotation_double_clicked(self, item):
        """Handle double-click - jump to line."""
        self._jump_to_selected()

    def _jump_to_selected(self):
        """Jump to selected annotation line."""
        current_item = self.annotation_list.currentItem()
        if not current_item:
            return

        annotation_id = current_item.data(Qt.ItemDataRole.UserRole)
        annotation = next((a for a in self.annotations if a.id == annotation_id), None)

        if annotation:
            self.jump_to_line.emit(annotation.line_number)
            self.accept()

    def _edit_selected(self):
        """Edit selected annotation."""
        current_item = self.annotation_list.currentItem()
        if not current_item:
            return

        annotation_id = current_item.data(Qt.ItemDataRole.UserRole)
        self.edit_annotation.emit(annotation_id)
        # Don't close dialog - let the parent refresh it

    def _delete_selected(self):
        """Delete selected annotation."""
        current_item = self.annotation_list.currentItem()
        if not current_item:
            return

        reply = QMessageBox.question(
            self,
            "Delete Annotation",
            "Are you sure you want to delete this annotation?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            annotation_id = current_item.data(Qt.ItemDataRole.UserRole)
            self.delete_annotation.emit(annotation_id)
            # Don't close dialog - let the parent refresh it

    def set_annotations(self, annotations: List[Annotation]):
        """Update annotations and refresh list."""
        self.annotations = annotations
        self._on_search_changed(self.search_input.text())
