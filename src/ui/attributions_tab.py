"""Attributions tab - view all annotations and attributions across all chapters."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QComboBox, QTextEdit, QSplitter, QGroupBox,
    QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal
from typing import List, Dict

from src.models.project import Manuscript, Annotation


class AttributionsTab(QWidget):
    """Tab for viewing all annotations and attributions across chapters."""

    jump_to_annotation = pyqtSignal(str, str)  # chapter_id, annotation_id

    def __init__(self, parent=None):
        """Initialize attributions tab."""
        super().__init__(parent)
        self.manuscript = None
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QLabel("📚 Annotations & Attributions")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(header)

        # Filter controls
        filter_layout = QHBoxLayout()

        filter_label = QLabel("Filter by:")
        filter_layout.addWidget(filter_label)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Notes", "Attributions", "Recommendations"])
        self.filter_combo.currentTextChanged.connect(self._update_display)
        filter_layout.addWidget(self.filter_combo)

        filter_layout.addStretch()

        stats_label = QLabel()
        self.stats_label = QLabel("0 annotations")
        self.stats_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        filter_layout.addWidget(self.stats_label)

        layout.addLayout(filter_layout)

        # Splitter for tree and preview
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Tree view of annotations
        tree_widget = QWidget()
        tree_layout = QVBoxLayout(tree_widget)
        tree_layout.setContentsMargins(0, 0, 0, 0)

        tree_label = QLabel("Annotations by Chapter")
        tree_label.setStyleSheet("font-weight: bold; margin: 8px 0;")
        tree_layout.addWidget(tree_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Chapter / Line", "Type", "Preview"])
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 100)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        tree_layout.addWidget(self.tree)

        splitter.addWidget(tree_widget)

        # Right: Preview panel
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(8, 0, 0, 0)

        preview_label = QLabel("Annotation Preview")
        preview_label.setStyleSheet("font-weight: bold; margin: 8px 0;")
        preview_layout.addWidget(preview_label)

        self.preview_group = QGroupBox("No annotation selected")
        preview_group_layout = QVBoxLayout()

        self.preview_content = QTextEdit()
        self.preview_content.setReadOnly(True)
        self.preview_content.setPlaceholderText("Select an annotation to view details...")
        preview_group_layout.addWidget(self.preview_content)

        self.jump_button = QPushButton("Jump to Chapter")
        self.jump_button.clicked.connect(self._jump_to_selected)
        self.jump_button.setEnabled(False)
        preview_group_layout.addWidget(self.jump_button)

        self.preview_group.setLayout(preview_group_layout)
        preview_layout.addWidget(self.preview_group)

        splitter.addWidget(preview_widget)

        # Set splitter sizes
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

    def set_manuscript(self, manuscript: Manuscript):
        """Set manuscript and update display."""
        self.manuscript = manuscript
        self._update_display()

    def _update_display(self):
        """Update tree view with annotations."""
        self.tree.clear()
        self.selected_chapter_id = None
        self.selected_annotation_id = None

        if not self.manuscript:
            self.stats_label.setText("No manuscript loaded")
            return

        # Get filter
        filter_type = self.filter_combo.currentText().lower()

        # Collect all annotations
        total_annotations = 0
        type_counts = {"notes": 0, "attributions": 0, "recommendations": 0}

        for chapter in self.manuscript.chapters:
            if not chapter.annotations:
                continue

            # Filter annotations
            filtered_annotations = chapter.annotations
            if filter_type != "all":
                filtered_annotations = [
                    a for a in chapter.annotations
                    if (filter_type == "notes" and a.annotation_type == "note") or
                       (filter_type == "attributions" and a.annotation_type == "attribution") or
                       (filter_type == "recommendations" and a.annotation_type == "recommendation")
                ]

            if not filtered_annotations:
                continue

            # Create chapter item
            chapter_item = QTreeWidgetItem(self.tree)
            chapter_item.setText(0, f"Chapter {chapter.number}: {chapter.title}")
            chapter_item.setText(1, f"{len(filtered_annotations)} items")
            chapter_item.setExpanded(True)

            # Sort annotations by line number
            sorted_annotations = sorted(filtered_annotations, key=lambda a: a.line_number)

            # Add annotation items
            for annotation in sorted_annotations:
                ann_item = QTreeWidgetItem(chapter_item)

                # Type icon
                type_icon = {"note": "📝", "attribution": "🔗", "recommendation": "💡"}
                icon = type_icon.get(annotation.annotation_type, "📝")

                ann_item.setText(0, f"{icon} Line {annotation.line_number}")
                ann_item.setText(1, annotation.annotation_type.capitalize())

                # Preview (first 50 chars)
                preview = annotation.content[:50] + "..." if len(annotation.content) > 50 else annotation.content
                ann_item.setText(2, preview)

                # Store IDs
                ann_item.setData(0, Qt.ItemDataRole.UserRole, (chapter.id, annotation.id))

                total_annotations += 1
                type_counts[annotation.annotation_type + "s"] = type_counts.get(annotation.annotation_type + "s", 0) + 1

        # Update stats
        stats_parts = [f"{total_annotations} total"]
        if filter_type == "all":
            if type_counts["notes"] > 0:
                stats_parts.append(f"{type_counts['notes']} notes")
            if type_counts["attributions"] > 0:
                stats_parts.append(f"{type_counts['attributions']} attributions")
            if type_counts["recommendations"] > 0:
                stats_parts.append(f"{type_counts['recommendations']} recommendations")

        self.stats_label.setText(", ".join(stats_parts))

    def _on_item_clicked(self, item, column):
        """Handle tree item click."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            self.preview_content.clear()
            self.preview_group.setTitle("No annotation selected")
            self.jump_button.setEnabled(False)
            return

        chapter_id, annotation_id = data
        self.selected_chapter_id = chapter_id
        self.selected_annotation_id = annotation_id

        # Find annotation
        chapter = next((c for c in self.manuscript.chapters if c.id == chapter_id), None)
        if not chapter:
            return

        annotation = next((a for a in chapter.annotations if a.id == annotation_id), None)
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

        preview_text += f"\n**Location:**\n"
        preview_text += f"Chapter {chapter.number}: {chapter.title}, Line {annotation.line_number}"

        self.preview_content.setMarkdown(preview_text)
        self.jump_button.setEnabled(True)

    def _on_item_double_clicked(self, item, column):
        """Handle double-click - jump to annotation."""
        self._jump_to_selected()

    def _jump_to_selected(self):
        """Jump to selected annotation in chapter."""
        if self.selected_chapter_id and self.selected_annotation_id:
            self.jump_to_annotation.emit(self.selected_chapter_id, self.selected_annotation_id)
