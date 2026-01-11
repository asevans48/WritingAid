"""Annotation system for manuscript editor - notes and attributions at specific lines."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit,
    QDialog, QDialogButtonBox, QComboBox, QFormLayout, QListWidget,
    QListWidgetItem, QSplitter, QGroupBox, QMessageBox, QLineEdit,
    QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QTextCharFormat, QColor, QBrush
from typing import List, Optional, Dict
import uuid

from src.models.project import Annotation


class AnnotationDialog(QDialog):
    """Dialog for creating/editing annotations."""

    delete_requested = pyqtSignal()  # Signal when user wants to delete

    def __init__(self, annotation: Optional[Annotation] = None,
                 line_number: int = 1,
                 available_characters: List = None,
                 available_chapters: List = None,
                 available_myths: List = None,
                 parent=None):
        """Initialize annotation dialog."""
        super().__init__(parent)
        self.is_editing = annotation is not None  # Track if editing existing annotation
        self.annotation = annotation or Annotation(
            id=str(uuid.uuid4()),
            line_number=line_number
        )
        self.available_characters = available_characters or []
        self.available_chapters = available_chapters or []
        self.available_myths = available_myths or []
        self._init_ui()
        if annotation:
            self._load_annotation()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Annotation Editor")
        self.setMinimumSize(600, 500)

        main_layout = QVBoxLayout(self)

        # Scroll area for form
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        form_widget = QWidget()
        layout = QVBoxLayout(form_widget)

        # Line number and type
        header_layout = QFormLayout()

        self.line_label = QLabel(f"Line {self.annotation.line_number}")
        self.line_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        header_layout.addRow("Location:", self.line_label)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Note", "Attribution", "Recommendation"])
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        header_layout.addRow("Type:", self.type_combo)

        layout.addLayout(header_layout)

        # Content
        content_label = QLabel("Content:")
        content_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(content_label)

        self.content_edit = QTextEdit()
        self.content_edit.setPlaceholderText("Enter your note, attribution, or recommendation...")
        self.content_edit.setMinimumHeight(150)
        layout.addWidget(self.content_edit)

        # Attribution section (shown only for attribution type)
        self.attribution_group = QGroupBox("Attribution Details")
        attribution_layout = QFormLayout()

        self.ref_type_combo = QComboBox()
        self.ref_type_combo.addItems(["None", "Character", "Chapter", "Myth/Legend", "Worldbuilding Element"])
        self.ref_type_combo.currentTextChanged.connect(self._on_ref_type_changed)
        attribution_layout.addRow("Reference Type:", self.ref_type_combo)

        self.ref_name_combo = QComboBox()
        self.ref_name_combo.setEditable(True)
        attribution_layout.addRow("Reference:", self.ref_name_combo)

        self.attribution_group.setLayout(attribution_layout)
        self.attribution_group.setVisible(False)
        layout.addWidget(self.attribution_group)

        scroll_area.setWidget(form_widget)
        main_layout.addWidget(scroll_area)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        # Add Delete button if editing existing annotation
        if self.is_editing:
            delete_button = buttons.addButton("Delete", QDialogButtonBox.ButtonRole.DestructiveRole)
            delete_button.clicked.connect(self._delete)

        main_layout.addWidget(buttons)

    def _on_type_changed(self, type_text: str):
        """Handle annotation type change."""
        is_attribution = type_text == "Attribution"
        self.attribution_group.setVisible(is_attribution)

    def _on_ref_type_changed(self, ref_type: str):
        """Handle reference type change."""
        self.ref_name_combo.clear()

        if ref_type == "Character":
            self.ref_name_combo.addItems([c.name for c in self.available_characters])
        elif ref_type == "Chapter":
            self.ref_name_combo.addItems([f"Chapter {c.number}: {c.title}" for c in self.available_chapters])
        elif ref_type == "Myth/Legend":
            self.ref_name_combo.addItems([m.name for m in self.available_myths])
        elif ref_type == "Worldbuilding Element":
            self.ref_name_combo.setEditable(True)
            self.ref_name_combo.setPlaceholderText("Enter element name...")

    def _load_annotation(self):
        """Load annotation data into form."""
        type_map = {"note": "Note", "attribution": "Attribution", "recommendation": "Recommendation"}
        self.type_combo.setCurrentText(type_map.get(self.annotation.annotation_type, "Note"))
        self.content_edit.setPlainText(self.annotation.content)

        if self.annotation.referenced_type:
            ref_type_map = {
                "character": "Character",
                "chapter": "Chapter",
                "myth": "Myth/Legend",
                "worldbuilding": "Worldbuilding Element"
            }
            self.ref_type_combo.setCurrentText(ref_type_map.get(self.annotation.referenced_type, "None"))
            if self.annotation.referenced_name:
                self.ref_name_combo.setCurrentText(self.annotation.referenced_name)

    def _save(self):
        """Save annotation."""
        content = self.content_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "Empty Content", "Please enter annotation content.")
            return

        type_map = {"Note": "note", "Attribution": "attribution", "Recommendation": "recommendation"}
        self.annotation.annotation_type = type_map[self.type_combo.currentText()]
        self.annotation.content = content

        if self.annotation.annotation_type == "attribution":
            ref_type = self.ref_type_combo.currentText()
            if ref_type != "None":
                ref_type_map = {
                    "Character": "character",
                    "Chapter": "chapter",
                    "Myth/Legend": "myth",
                    "Worldbuilding Element": "worldbuilding"
                }
                self.annotation.referenced_type = ref_type_map.get(ref_type)
                self.annotation.referenced_name = self.ref_name_combo.currentText()

                # Try to find ID for the reference
                if ref_type == "Character":
                    char = next((c for c in self.available_characters if c.name == self.annotation.referenced_name), None)
                    if char:
                        self.annotation.referenced_id = char.id
                elif ref_type == "Chapter":
                    # Extract chapter number from "Chapter X: Title"
                    try:
                        chapter_num = int(self.annotation.referenced_name.split(":")[0].replace("Chapter", "").strip())
                        chapter = self.available_chapters[chapter_num - 1] if chapter_num <= len(self.available_chapters) else None
                        if chapter:
                            self.annotation.referenced_id = chapter.id
                    except:
                        pass
                elif ref_type == "Myth/Legend":
                    myth = next((m for m in self.available_myths if m.name == self.annotation.referenced_name), None)
                    if myth:
                        self.annotation.referenced_id = myth.id

        self.accept()

    def _delete(self):
        """Handle delete request."""
        reply = QMessageBox.question(
            self,
            "Delete Annotation",
            "Are you sure you want to delete this annotation?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit()
            self.reject()  # Close dialog

    def get_annotation(self) -> Annotation:
        """Get the annotation."""
        return self.annotation


class AnnotationSidebar(QWidget):
    """Sidebar widget for displaying and managing annotations."""

    annotation_clicked = pyqtSignal(str)  # annotation ID
    annotation_deleted = pyqtSignal(str)  # annotation ID
    add_annotation_requested = pyqtSignal(int)  # line number

    def __init__(self, parent=None):
        """Initialize annotation sidebar."""
        super().__init__(parent)
        self.annotations: List[Annotation] = []
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Header
        header = QLabel("Annotations")
        header.setStyleSheet("font-size: 14px; font-weight: bold; padding: 4px;")
        layout.addWidget(header)

        # Add button
        add_btn = QPushButton("+ Add at Current Line")
        add_btn.clicked.connect(lambda: self.add_annotation_requested.emit(1))
        layout.addWidget(add_btn)

        # Annotation list
        self.annotation_list = QListWidget()
        self.annotation_list.itemClicked.connect(self._on_annotation_clicked)
        layout.addWidget(self.annotation_list)

        # Delete button
        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self._delete_selected)
        layout.addWidget(delete_btn)

    def set_annotations(self, annotations: List[Annotation]):
        """Set annotations to display."""
        self.annotations = annotations
        self._update_list()

    def _update_list(self):
        """Update annotation list display."""
        self.annotation_list.clear()

        # Sort by line number
        sorted_annotations = sorted(self.annotations, key=lambda a: a.line_number)

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
        self.annotation_clicked.emit(annotation_id)

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
            self.annotation_deleted.emit(annotation_id)
