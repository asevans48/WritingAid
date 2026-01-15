"""Manuscript editor with chapter navigation and revision system."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTextEdit, QToolBar, QComboBox, QSpinBox,
    QMessageBox, QInputDialog, QGroupBox, QSplitter, QFileDialog,
    QDialog, QMenu
)
from PyQt6.QtCore import pyqtSignal, Qt, QRect, QSize
from PyQt6.QtGui import QFont, QTextCursor, QAction, QTextCharFormat, QColor, QPainter, QTextFormat
from typing import List, Optional
import uuid

from src.models.project import Manuscript, Chapter, Annotation
from src.ui.enhanced_text_editor import EnhancedTextEditor
from src.ui.annotations import AnnotationDialog
from src.ui.annotation_list_dialog import AnnotationListDialog
from src.ai.chapter_memory import ChapterMemoryManager


class AnnotationMarginArea(QWidget):
    """Custom widget for displaying annotation indicators in the margin."""

    annotation_clicked = pyqtSignal(int)  # line_number

    def __init__(self, editor):
        """Initialize margin area."""
        super().__init__(editor)
        self.editor = editor
        self.annotations = []

    def set_annotations(self, annotations):
        """Set annotations to display."""
        self.annotations = annotations
        self.update()

    def sizeHint(self):
        """Return size hint for margin."""
        return QSize(30, 0)

    def paintEvent(self, event):
        """Paint annotation indicators."""
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor(250, 250, 250))

        # Get document
        document = self.editor.document()

        # Get viewport rect to determine visible area
        viewport_rect = self.editor.viewport().rect()

        # Iterate through all blocks in document
        block = document.begin()
        block_number = 0

        while block.isValid():
            line_number = block_number + 1

            # Check if this line has annotations
            line_annotations = [a for a in self.annotations if a.line_number == line_number]

            if line_annotations:
                # Get the block's position in the editor
                cursor = QTextCursor(block)
                rect = self.editor.cursorRect(cursor)

                # Only draw if within visible area
                if rect.top() >= -rect.height() and rect.top() <= self.height():
                    # Draw plus indicator
                    painter.setPen(QColor(100, 100, 255))
                    painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
                    painter.drawText(0, rect.top(), self.width(), rect.height(),
                                   Qt.AlignmentFlag.AlignCenter, "+")

            block = block.next()
            block_number += 1

    def mousePressEvent(self, event):
        """Handle click on annotation indicator."""
        # Get document
        document = self.editor.document()

        # Find which line was clicked by iterating through blocks
        block = document.begin()
        block_number = 0
        click_y = event.pos().y()

        while block.isValid():
            line_number = block_number + 1

            # Get the block's position in the editor
            cursor = QTextCursor(block)
            rect = self.editor.cursorRect(cursor)

            # Check if click was in this block's area
            if rect.top() <= click_y <= rect.top() + rect.height():
                # Check if this line has annotations
                if any(a.line_number == line_number for a in self.annotations):
                    self.annotation_clicked.emit(line_number)
                break

            block = block.next()
            block_number += 1


class ChapterEditor(QWidget):
    """Editor for a single chapter with formatting and AI hints."""

    content_changed = pyqtSignal()
    word_count_changed = pyqtSignal(int)
    annotations_changed = pyqtSignal()  # Signal when annotations are added/edited/deleted

    def __init__(self, chapter: Chapter, project=None):
        """Initialize chapter editor."""
        super().__init__()
        self.chapter = chapter
        self.project = project
        self._init_ui()
        self._load_chapter()

    def _init_ui(self):
        """Initialize user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)

        # Font family
        self.font_combo = QComboBox()
        self.font_combo.addItems(["Arial", "Times New Roman", "Courier New", "Georgia", "Verdana"])
        self.font_combo.currentTextChanged.connect(self._change_font_family)
        toolbar.addWidget(QLabel("Font: "))
        toolbar.addWidget(self.font_combo)

        # Font size
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 72)
        self.font_size_spin.setValue(12)
        # Block signals initially to prevent spurious valueChanged during initialization
        self.font_size_spin.blockSignals(True)
        self.font_size_spin.valueChanged.connect(self._change_font_size)
        self.font_size_spin.blockSignals(False)
        toolbar.addWidget(QLabel("Size: "))
        toolbar.addWidget(self.font_size_spin)

        toolbar.addSeparator()

        # Formatting buttons
        bold_action = QAction("Bold", self)
        bold_action.setShortcut("Ctrl+B")
        bold_action.triggered.connect(self._toggle_bold)
        toolbar.addAction(bold_action)

        italic_action = QAction("Italic", self)
        italic_action.setShortcut("Ctrl+I")
        italic_action.triggered.connect(self._toggle_italic)
        toolbar.addAction(italic_action)

        underline_action = QAction("Underline", self)
        underline_action.setShortcut("Ctrl+U")
        underline_action.triggered.connect(self._toggle_underline)
        toolbar.addAction(underline_action)

        toolbar.addSeparator()

        # Annotation actions
        annotation_action = QAction("📝 Add Note", self)
        annotation_action.setShortcut("Ctrl+Shift+N")
        annotation_action.triggered.connect(lambda: self._add_annotation())
        annotation_action.setToolTip("Add annotation at current line (Ctrl+Shift+N)")
        toolbar.addAction(annotation_action)

        view_annotations_action = QAction("📋 View All", self)
        view_annotations_action.triggered.connect(self._view_annotations_list)
        view_annotations_action.setToolTip("View all annotations")
        toolbar.addAction(view_annotations_action)

        layout.addWidget(toolbar)

        # Chapter title
        title_layout = QHBoxLayout()
        title_label = QLabel("Chapter Title:")
        title_layout.addWidget(title_label)

        self.title_edit = QTextEdit()
        self.title_edit.setMaximumHeight(40)
        self.title_edit.setPlaceholderText("Enter chapter title...")
        self.title_edit.textChanged.connect(self.content_changed.emit)
        title_layout.addWidget(self.title_edit)

        layout.addLayout(title_layout)

        # Main editor with annotation margin
        editor_container = QHBoxLayout()
        editor_container.setContentsMargins(0, 0, 0, 0)
        editor_container.setSpacing(0)

        # Main editor - use enhanced editor
        self.editor = EnhancedTextEditor()
        self.editor.setPlaceholderText("Start writing your chapter...")
        self.editor.textChanged.connect(self._on_text_changed)

        # Set default font
        font = QFont("Times New Roman", 12)
        self.editor.setFont(font)

        # Override the EnhancedTextEditor's context menu with our own
        # Disconnect the default handler first
        try:
            self.editor.customContextMenuRequested.disconnect()
        except:
            pass

        # Connect our custom context menu
        self.editor.customContextMenuRequested.connect(self._show_context_menu)

        # Set up context lookup callbacks if project is available
        if self.project:
            self._setup_context_lookup()

        # Annotation margin area
        self.annotation_margin = AnnotationMarginArea(self.editor)
        self.annotation_margin.annotation_clicked.connect(self._on_margin_clicked)

        # Connect editor updates to margin repaints
        # QTextEdit uses verticalScrollBar signals instead of updateRequest
        self.editor.verticalScrollBar().valueChanged.connect(self._update_margin_area_scroll)
        self.editor.textChanged.connect(self.annotation_margin.update)

        editor_container.addWidget(self.annotation_margin)
        editor_container.addWidget(self.editor)

        layout.addLayout(editor_container)

        # Bottom toolbar
        bottom_toolbar = QHBoxLayout()

        # Word count
        self.word_count_label = QLabel("Words: 0")
        bottom_toolbar.addWidget(self.word_count_label)

        bottom_toolbar.addStretch()

        # Import from Word button
        import_word_button = QPushButton("Import from Word")
        import_word_button.clicked.connect(self._import_from_word)
        bottom_toolbar.addWidget(import_word_button)

        # Export to Word button
        export_word_button = QPushButton("Export to Word")
        export_word_button.clicked.connect(self._export_to_word)
        bottom_toolbar.addWidget(export_word_button)

        # AI Hints button
        hints_button = QPushButton("Get AI Hints")
        hints_button.clicked.connect(self._request_ai_hints)
        bottom_toolbar.addWidget(hints_button)

        # Save revision button
        save_revision_button = QPushButton("Save Revision")
        save_revision_button.clicked.connect(self._save_revision)
        bottom_toolbar.addWidget(save_revision_button)

        # View revisions button
        view_revisions_button = QPushButton("View Revisions")
        view_revisions_button.clicked.connect(self._view_revisions)
        bottom_toolbar.addWidget(view_revisions_button)

        layout.addLayout(bottom_toolbar)

    def _load_chapter(self):
        """Load chapter data into editor."""
        self.title_edit.setPlainText(self.chapter.title)
        self.editor.setPlainText(self.chapter.content)
        self._update_word_count()
        self._update_margin_annotations()
        self._highlight_annotated_lines()

    def _on_text_changed(self):
        """Handle text changes."""
        self._update_word_count()
        self.content_changed.emit()

    def _update_word_count(self):
        """Update word count display."""
        text = self.editor.toPlainText()
        words = len([w for w in text.split() if w])
        self.chapter.word_count = words
        self.word_count_label.setText(f"Words: {words}")
        self.word_count_changed.emit(words)

    def _change_font_family(self, family: str):
        """Change font family."""
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            fmt = cursor.charFormat()
            fmt.setFontFamily(family)
            cursor.setCharFormat(fmt)
        else:
            font = self.editor.font()
            font.setFamily(family)
            self.editor.setFont(font)

    def _change_font_size(self, size: int):
        """Change font size."""
        # Ensure size is valid (positive) - Qt sometimes passes -1 during initialization
        if size <= 0:
            return  # Skip invalid sizes instead of setting default

        try:
            cursor = self.editor.textCursor()
            if cursor.hasSelection():
                fmt = cursor.charFormat()
                # Only set if size is valid
                if size > 0:
                    fmt.setFontPointSize(size)
                    cursor.setCharFormat(fmt)
            else:
                font = self.editor.font()
                # Double-check size before setting
                if size > 0 and size <= 72:
                    font.setPointSize(size)
                    self.editor.setFont(font)
        except Exception as e:
            # Silently catch any font-related errors during initialization
            pass

    def _toggle_bold(self):
        """Toggle bold formatting."""
        cursor = self.editor.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontWeight(QFont.Weight.Normal if fmt.fontWeight() == QFont.Weight.Bold else QFont.Weight.Bold)
        cursor.mergeCharFormat(fmt)

    def _toggle_italic(self):
        """Toggle italic formatting."""
        cursor = self.editor.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontItalic(not fmt.fontItalic())
        cursor.mergeCharFormat(fmt)

    def _toggle_underline(self):
        """Toggle underline formatting."""
        cursor = self.editor.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontUnderline(not fmt.fontUnderline())
        cursor.mergeCharFormat(fmt)

    def _show_context_menu(self, position):
        """Show custom context menu with annotation option."""
        # Get cursor at click position
        cursor = self.editor.cursorForPosition(position)
        line_number = cursor.blockNumber() + 1

        # Create context menu
        menu = QMenu(self.editor)

        # Add annotation action
        add_annotation_action = menu.addAction("📝 Add Annotation")
        add_annotation_action.triggered.connect(lambda: self._add_annotation(line_number))

        # Check if there are annotations on this line
        line_annotations = [a for a in self.chapter.annotations if a.line_number == line_number]

        if line_annotations:
            view_annotations_action = menu.addAction(f"📋 View Annotations ({len(line_annotations)})")
            view_annotations_action.triggered.connect(lambda: self._on_margin_clicked(line_number))

        menu.addSeparator()

        # Standard edit actions
        undo_action = menu.addAction("Undo")
        undo_action.triggered.connect(self.editor.undo)
        undo_action.setEnabled(self.editor.document().isUndoAvailable())

        redo_action = menu.addAction("Redo")
        redo_action.triggered.connect(self.editor.redo)
        redo_action.setEnabled(self.editor.document().isRedoAvailable())

        menu.addSeparator()

        # Copy/Paste actions
        if cursor.hasSelection():
            cut_action = menu.addAction("Cut")
            cut_action.triggered.connect(self.editor.cut)

            copy_action = menu.addAction("Copy")
            copy_action.triggered.connect(self.editor.copy)

        paste_action = menu.addAction("Paste")
        paste_action.triggered.connect(self.editor.paste)

        menu.addSeparator()

        # Context lookup menu
        lookup_menu = menu.addMenu("Look Up Context")

        # Get selected text
        selected_text = cursor.selectedText()

        if selected_text:
            # Lookup selected text
            lookup_selected = lookup_menu.addAction(f'Look Up "{selected_text[:30]}..."')
            lookup_selected.triggered.connect(lambda: self._lookup_selected_text(selected_text))
            lookup_menu.addSeparator()

        # Character lookup
        character_action = lookup_menu.addAction("Character Reference")
        character_action.triggered.connect(self._lookup_character)

        # Worldbuilding lookup
        worldbuilding_action = lookup_menu.addAction("Worldbuilding Reference")
        worldbuilding_action.triggered.connect(self._lookup_worldbuilding)

        # Plot lookup
        plot_action = lookup_menu.addAction("Plot Reference")
        plot_action.triggered.connect(self._lookup_plot)

        # Show menu at cursor position
        menu.exec(self.editor.mapToGlobal(position))

    def _request_ai_hints(self):
        """Request AI hints for improving the chapter."""
        # TODO: Integrate with AI client
        QMessageBox.information(
            self,
            "AI Hints",
            "AI chapter hints will be integrated soon."
        )

    def _lookup_selected_text(self, text: str):
        """Look up context for selected text."""
        if hasattr(self.editor, 'lookup_context_callback') and self.editor.lookup_context_callback:
            from src.ui.enhanced_text_editor import ContextLookupDialog
            result = self.editor.lookup_context_callback(text)
            dialog = ContextLookupDialog(f"Context for: {text}", result, self)
            dialog.exec()

    def _lookup_character(self):
        """Look up character reference."""
        if not hasattr(self.editor, 'get_character_list_callback') or not self.editor.get_character_list_callback:
            QMessageBox.information(self, "Not Available", "Character lookup not configured.")
            return

        from src.ui.enhanced_text_editor import ContextLookupDialog, QuickReferenceDialog
        characters = self.editor.get_character_list_callback()
        if not characters:
            QMessageBox.information(self, "No Characters", "No characters defined in your project yet.")
            return

        dialog = QuickReferenceDialog(characters, "Character", self)
        if dialog.exec() and dialog.selected_item:
            if hasattr(self.editor, 'lookup_characters_callback') and self.editor.lookup_characters_callback:
                result = self.editor.lookup_characters_callback(dialog.selected_item)
                ref_dialog = ContextLookupDialog(f"Character: {dialog.selected_item}", result, self)
                ref_dialog.exec()

    def _lookup_worldbuilding(self):
        """Look up worldbuilding reference."""
        if not hasattr(self.editor, 'get_worldbuilding_sections_callback') or not self.editor.get_worldbuilding_sections_callback:
            QMessageBox.information(self, "Not Available", "Worldbuilding lookup not configured.")
            return

        from src.ui.enhanced_text_editor import ContextLookupDialog, QuickReferenceDialog
        sections = self.editor.get_worldbuilding_sections_callback()
        if not sections:
            QMessageBox.information(self, "No Worldbuilding", "No worldbuilding sections defined yet.")
            return

        dialog = QuickReferenceDialog(sections, "Worldbuilding Section", self)
        if dialog.exec() and dialog.selected_item:
            if hasattr(self.editor, 'lookup_worldbuilding_callback') and self.editor.lookup_worldbuilding_callback:
                result = self.editor.lookup_worldbuilding_callback(dialog.selected_item)
                ref_dialog = ContextLookupDialog(f"Worldbuilding: {dialog.selected_item}", result, self)
                ref_dialog.exec()

    def _lookup_plot(self):
        """Look up plot reference."""
        if hasattr(self.editor, 'lookup_plot_callback') and self.editor.lookup_plot_callback:
            from src.ui.enhanced_text_editor import ContextLookupDialog
            result = self.editor.lookup_plot_callback()
            dialog = ContextLookupDialog("Plot Reference", result, self)
            dialog.exec()

    def _save_revision(self):
        """Save current content as a revision."""
        notes, ok = QInputDialog.getText(
            self,
            "Save Revision",
            "Enter revision notes (optional):"
        )

        if ok:
            self.save_to_model()
            self.chapter.add_revision(notes)
            QMessageBox.information(
                self,
                "Revision Saved",
                f"Revision #{len(self.chapter.revisions)} saved."
            )

    def _view_revisions(self):
        """View revision history."""
        if not self.chapter.revisions:
            QMessageBox.information(
                self,
                "No Revisions",
                "No revision history available for this chapter."
            )
            return

        # TODO: Create a proper revision viewer dialog
        revision_list = "\n".join([
            f"Revision {r.revision_number}: {r.timestamp.strftime('%Y-%m-%d %H:%M')} - {r.notes}"
            for r in self.chapter.revisions
        ])

        QMessageBox.information(
            self,
            "Revision History",
            revision_list
        )

    def _import_from_word(self):
        """Import chapter content from Word document."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import from Word",
            "",
            "Word Documents (*.docx);;All Files (*)"
        )

        if file_path:
            success = self.editor.import_from_docx(file_path)
            if success:
                QMessageBox.information(
                    self,
                    "Import Successful",
                    "Chapter content imported from Word document."
                )
                self.content_changed.emit()
            else:
                QMessageBox.critical(
                    self,
                    "Import Failed",
                    "Failed to import Word document. Check the console for details."
                )

    def _export_to_word(self):
        """Export chapter content to Word document."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export to Word",
            f"{self.chapter.title}.docx",
            "Word Documents (*.docx);;All Files (*)"
        )

        if file_path:
            success = self.editor.export_to_docx(file_path, self.chapter.title)
            if success:
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Chapter exported to: {file_path}"
                )
            else:
                QMessageBox.critical(
                    self,
                    "Export Failed",
                    "Failed to export to Word document. Check the console for details."
                )

    def _setup_context_lookup(self):
        """Set up context lookup callbacks for RAG system."""
        from src.ai.rag_system import RAGSystem

        # Get memory manager from parent if available
        memory_manager = None
        parent = self.parent()
        while parent:
            if hasattr(parent, 'memory_manager'):
                memory_manager = parent.memory_manager
                break
            parent = parent.parent()

        # Create RAG system with memory manager for faster lookups
        rag = RAGSystem(self.project, memory_manager=memory_manager)

        # Define callback functions
        def lookup_worldbuilding(section_name: str) -> str:
            result = rag.get_quick_reference("worldbuilding", section_name)
            return result if result else f"No worldbuilding information found for: {section_name}"

        def lookup_characters(character_name: str) -> str:
            result = rag.get_quick_reference("character", character_name)
            return result if result else f"No character information found for: {character_name}"

        def lookup_plot() -> str:
            sp = self.project.story_planning
            plot_text = f"""
**Main Plot:**
{sp.main_plot}

**Story Structure (Freytag's Pyramid):**

**Exposition:**
{sp.freytag_pyramid.exposition}

**Rising Action:**
{sp.freytag_pyramid.rising_action}

**Climax:**
{sp.freytag_pyramid.climax}

**Falling Action:**
{sp.freytag_pyramid.falling_action}

**Resolution:**
{sp.freytag_pyramid.resolution}
            """.strip()
            return plot_text

        def lookup_context(query: str) -> str:
            return rag.summarize_context(query, max_results=5)

        def get_character_list() -> list:
            return [c.name for c in self.project.characters]

        def get_worldbuilding_sections() -> list:
            sections = [
                "Mythology", "Planets", "Climate", "History",
                "Politics", "Military", "Economy", "Power Hierarchy"
            ]
            sections.extend(self.project.worldbuilding.custom_sections.keys())
            return sections

        # Set callbacks on editor
        self.editor.set_callbacks(
            lookup_worldbuilding=lookup_worldbuilding,
            lookup_characters=lookup_characters,
            lookup_plot=lookup_plot,
            lookup_context=lookup_context,
            get_character_list=get_character_list,
            get_worldbuilding_sections=get_worldbuilding_sections
        )

    def _add_annotation(self, line_number: int = None):
        """Add annotation at current line or specified line."""
        if line_number is None:
            cursor = self.editor.textCursor()
            line_number = cursor.blockNumber() + 1

        dialog = AnnotationDialog(
            line_number=line_number,
            available_characters=self.project.characters if self.project else [],
            available_chapters=self.project.manuscript.chapters if self.project else [],
            available_myths=self.project.worldbuilding.myths if self.project else [],
            available_places=self.project.worldbuilding.places if self.project else [],
            parent=self
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            annotation = dialog.get_annotation()
            self.chapter.annotations.append(annotation)
            self._update_margin_annotations()
            self._highlight_annotated_lines()
            self.content_changed.emit()
            self.annotations_changed.emit()

    def _on_margin_clicked(self, line_number: int):
        """Handle click on annotation margin - show annotations for that line."""
        line_annotations = [a for a in self.chapter.annotations if a.line_number == line_number]

        if not line_annotations:
            return

        # If only one annotation, edit it directly
        if len(line_annotations) == 1:
            self._edit_annotation(line_annotations[0])
        else:
            # Show selection dialog
            from PyQt6.QtWidgets import QListWidget, QDialog, QVBoxLayout, QPushButton
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Annotations at Line {line_number}")
            layout = QVBoxLayout(dialog)

            list_widget = QListWidget()
            for ann in line_annotations:
                type_icon = {"note": "📝", "attribution": "🔗", "recommendation": "💡"}
                icon = type_icon.get(ann.annotation_type, "📝")
                preview = ann.content[:50] + "..." if len(ann.content) > 50 else ann.content
                list_widget.addItem(f"{icon} {preview}")

            list_widget.itemDoubleClicked.connect(lambda: (self._edit_annotation(line_annotations[list_widget.currentRow()]), dialog.accept()))
            layout.addWidget(list_widget)

            btn = QPushButton("Close")
            btn.clicked.connect(dialog.accept)
            layout.addWidget(btn)

            dialog.exec()

    def _edit_annotation(self, annotation: Annotation):
        """Edit an annotation."""
        dialog = AnnotationDialog(
            annotation=annotation,
            line_number=annotation.line_number,
            available_characters=self.project.characters if self.project else [],
            available_chapters=self.project.manuscript.chapters if self.project else [],
            available_myths=self.project.worldbuilding.myths if self.project else [],
            available_places=self.project.worldbuilding.places if self.project else [],
            parent=self
        )

        # Connect delete signal
        dialog.delete_requested.connect(lambda: self._delete_annotation(annotation.id))

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._update_margin_annotations()
            self._highlight_annotated_lines()
            self.content_changed.emit()
            self.annotations_changed.emit()

    def _delete_annotation(self, annotation_id: str):
        """Delete annotation."""
        self.chapter.annotations = [a for a in self.chapter.annotations if a.id != annotation_id]
        self._update_margin_annotations()
        self._highlight_annotated_lines()
        self.content_changed.emit()
        self.annotations_changed.emit()

    def _update_margin_annotations(self):
        """Update annotation margin."""
        self.annotation_margin.set_annotations(self.chapter.annotations)

    def _update_margin_area_scroll(self):
        """Update margin area when editor scrolls."""
        self.annotation_margin.update()

    def _view_annotations_list(self):
        """Open annotation list dialog."""
        dialog = AnnotationListDialog(self.chapter.annotations, self)

        # Connect signals
        dialog.jump_to_line.connect(self._jump_to_line)
        dialog.edit_annotation.connect(lambda ann_id: self._edit_annotation_by_id_and_refresh(ann_id, dialog))
        dialog.delete_annotation.connect(lambda ann_id: self._delete_annotation_and_refresh(ann_id, dialog))

        dialog.exec()

    def _edit_annotation_by_id_and_refresh(self, annotation_id: str, dialog):
        """Edit annotation and refresh the dialog."""
        annotation = next((a for a in self.chapter.annotations if a.id == annotation_id), None)
        if annotation:
            edit_dialog = AnnotationDialog(
                annotation=annotation,
                line_number=annotation.line_number,
                available_characters=self.project.characters if self.project else [],
                available_chapters=self.project.manuscript.chapters if self.project else [],
                available_myths=self.project.worldbuilding.myths if self.project else [],
                available_places=self.project.worldbuilding.places if self.project else [],
                parent=self
            )

            # Connect delete signal - delete and refresh both dialogs
            edit_dialog.delete_requested.connect(lambda: self._delete_annotation_and_refresh(annotation.id, dialog))

            if edit_dialog.exec() == QDialog.DialogCode.Accepted:
                self._update_margin_annotations()
                self._highlight_annotated_lines()
                self.content_changed.emit()
                self.annotations_changed.emit()
                dialog.set_annotations(self.chapter.annotations)

    def _delete_annotation_and_refresh(self, annotation_id: str, dialog):
        """Delete annotation and refresh the dialog."""
        self.chapter.annotations = [a for a in self.chapter.annotations if a.id != annotation_id]
        self._update_margin_annotations()
        self._highlight_annotated_lines()
        self.content_changed.emit()
        self.annotations_changed.emit()
        dialog.set_annotations(self.chapter.annotations)

    def _jump_to_line(self, line_number: int):
        """Jump to specific line in editor."""
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.MoveAnchor, line_number - 1)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _edit_annotation_by_id(self, annotation_id: str):
        """Edit annotation by ID."""
        annotation = next((a for a in self.chapter.annotations if a.id == annotation_id), None)
        if annotation:
            self._edit_annotation(annotation)

    def _highlight_annotated_lines(self):
        """Highlight lines that have annotations."""
        # Store current cursor position
        old_cursor = self.editor.textCursor()
        old_position = old_cursor.position()

        # Clear all formatting first
        cursor = QTextCursor(self.editor.document())
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextCharFormat()
        cursor.setCharFormat(fmt)

        # Highlight annotated lines
        for annotation in self.chapter.annotations:
            cursor = QTextCursor(self.editor.document())
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.MoveAnchor, annotation.line_number - 1)
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)

            # Color based on type
            fmt = QTextCharFormat()
            if annotation.annotation_type == "attribution":
                fmt.setBackground(QColor(230, 244, 255, 100))  # Light blue
            elif annotation.annotation_type == "recommendation":
                fmt.setBackground(QColor(255, 250, 230, 100))  # Light yellow
            else:
                fmt.setBackground(QColor(240, 240, 240, 100))  # Light gray

            cursor.mergeCharFormat(fmt)

        # Restore cursor position
        new_cursor = self.editor.textCursor()
        new_cursor.setPosition(old_position)
        self.editor.setTextCursor(new_cursor)

    def save_to_model(self):
        """Save editor content to chapter model."""
        self.chapter.title = self.title_edit.toPlainText()
        self.chapter.content = self.editor.toPlainText()
        self._update_word_count()


class ManuscriptEditor(QWidget):
    """Main manuscript editor with chapter navigation."""

    content_changed = pyqtSignal()
    annotations_changed = pyqtSignal()  # Signal when any annotation changes

    def __init__(self, project=None):
        """Initialize manuscript editor."""
        super().__init__()
        self.manuscript: Optional[Manuscript] = None
        self.project = project
        self.current_chapter_editor: Optional[ChapterEditor] = None
        self._current_chapter_id: Optional[str] = None

        # Initialize memory manager for chapter caching and key points
        self.memory_manager = ChapterMemoryManager(
            project=project,
            cache_size=5,  # Keep 5 chapters in memory
            cache_memory_mb=50.0  # Up to 50MB of chapter content
        )
        self._init_ui()

    def set_project(self, project):
        """Set the project for context lookup."""
        self.project = project
        self.memory_manager.set_project(project)

    def _init_ui(self):
        """Initialize user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Minimal header - compact
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(16, 8, 16, 8)

        # Total word count (moved to left, more prominent)
        self.total_word_count_label = QLabel("Total: 0 words")
        self.total_word_count_label.setStyleSheet("font-size: 13px; font-weight: 500; color: #6b7280;")
        header_layout.addWidget(self.total_word_count_label)

        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Splitter for chapter list and editor
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel - chapter list (compact)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        chapters_label = QLabel("Chapters")
        chapters_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #1a1a1a; padding: 4px;")
        left_layout.addWidget(chapters_label)

        self.chapter_list = QListWidget()
        self.chapter_list.currentItemChanged.connect(self._on_chapter_selected)
        self.chapter_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chapter_list.customContextMenuRequested.connect(self._show_chapter_context_menu)
        left_layout.addWidget(self.chapter_list)

        # Chapter buttons (simplified - just add and reorder)
        button_layout = QHBoxLayout()

        add_button = QPushButton("+ Add")
        add_button.setToolTip("Add new chapter at end")
        add_button.clicked.connect(self._add_chapter)
        button_layout.addWidget(add_button)

        move_up_button = QPushButton("Up")
        move_up_button.setToolTip("Move chapter up")
        move_up_button.clicked.connect(self._move_chapter_up)
        button_layout.addWidget(move_up_button)

        move_down_button = QPushButton("Down")
        move_down_button.setToolTip("Move chapter down")
        move_down_button.clicked.connect(self._move_chapter_down)
        button_layout.addWidget(move_down_button)

        left_layout.addLayout(button_layout)

        # Hint label
        hint_label = QLabel("Right-click chapter for more options")
        hint_label.setStyleSheet("color: #999; font-size: 10px; font-style: italic;")
        left_layout.addWidget(hint_label)

        left_panel.setMaximumWidth(250)
        splitter.addWidget(left_panel)

        # Right panel - chapter editor
        self.editor_container = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_container)
        self.editor_layout.setContentsMargins(0, 0, 0, 0)

        placeholder = QLabel("Add or select a chapter to begin writing")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #999; font-size: 16px;")
        self.editor_layout.addWidget(placeholder)

        splitter.addWidget(self.editor_container)

        # Set splitter sizes
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter, stretch=1)

    def _show_chapter_context_menu(self, position):
        """Show context menu for chapter list."""
        item = self.chapter_list.itemAt(position)
        if not item:
            return

        menu = QMenu(self)

        # Rename action
        rename_action = menu.addAction("✏️ Rename")
        rename_action.triggered.connect(self._rename_chapter)

        # Insert before action
        insert_action = menu.addAction("📄 Insert Before")
        insert_action.triggered.connect(self._insert_chapter)

        menu.addSeparator()

        # Delete action
        delete_action = menu.addAction("🗑️ Delete")
        delete_action.triggered.connect(self._remove_chapter)

        menu.exec(self.chapter_list.mapToGlobal(position))

    def _add_chapter(self):
        """Add new chapter at the end."""
        if not self.manuscript:
            QMessageBox.warning(
                self,
                "No Manuscript",
                "Please create or load a project first."
            )
            return

        chapter_num = len(self.manuscript.chapters) + 1
        title, ok = QInputDialog.getText(
            self,
            "New Chapter",
            f"Enter title for Chapter {chapter_num}:",
            text=f"Chapter {chapter_num}"
        )

        if ok:
            chapter = Chapter(
                id=str(uuid.uuid4()),
                number=chapter_num,
                title=title
            )
            self.manuscript.chapters.append(chapter)

            item = QListWidgetItem(f"{chapter_num}. {title}")
            item.setData(Qt.ItemDataRole.UserRole, chapter.id)
            self.chapter_list.addItem(item)

            self.chapter_list.setCurrentItem(item)
            self.content_changed.emit()

    def _insert_chapter(self):
        """Insert chapter before selected chapter."""
        if not self.manuscript:
            QMessageBox.warning(
                self,
                "No Manuscript",
                "Please create or load a project first."
            )
            return

        current_row = self.chapter_list.currentRow()
        if current_row < 0:
            self._add_chapter()
            return

        chapter_num = current_row + 1
        title, ok = QInputDialog.getText(
            self,
            "Insert Chapter",
            f"Enter title for new Chapter {chapter_num}:",
            text=f"Chapter {chapter_num}"
        )

        if ok:
            chapter = Chapter(
                id=str(uuid.uuid4()),
                number=chapter_num,
                title=title
            )
            self.manuscript.chapters.insert(current_row, chapter)
            self._renumber_chapters()

            item = QListWidgetItem(f"{chapter_num}. {title}")
            item.setData(Qt.ItemDataRole.UserRole, chapter.id)
            self.chapter_list.insertItem(current_row, item)

            self.chapter_list.setCurrentItem(item)
            self.content_changed.emit()

    def _rename_chapter(self):
        """Rename selected chapter."""
        current_item = self.chapter_list.currentItem()
        if not current_item:
            QMessageBox.information(
                self,
                "No Selection",
                "Please select a chapter to rename."
            )
            return

        chapter_id = current_item.data(Qt.ItemDataRole.UserRole)
        chapter = next(
            (c for c in self.manuscript.chapters if c.id == chapter_id),
            None
        )

        if not chapter:
            return

        new_title, ok = QInputDialog.getText(
            self,
            "Rename Chapter",
            f"Enter new title for Chapter {chapter.number}:",
            text=chapter.title
        )

        if ok and new_title.strip():
            chapter.title = new_title.strip()
            current_item.setText(f"{chapter.number}. {chapter.title}")

            # Update the chapter editor title if it's currently displayed
            if self.current_chapter_editor and self.current_chapter_editor.chapter.id == chapter_id:
                self.current_chapter_editor.title_edit.setPlainText(chapter.title)

            self.content_changed.emit()

    def _remove_chapter(self):
        """Remove selected chapter."""
        current_item = self.chapter_list.currentItem()
        if not current_item:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete '{current_item.text()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            chapter_id = current_item.data(Qt.ItemDataRole.UserRole)
            self.manuscript.chapters = [
                c for c in self.manuscript.chapters if c.id != chapter_id
            ]

            row = self.chapter_list.row(current_item)
            self.chapter_list.takeItem(row)

            self._renumber_chapters()
            self._clear_editor()
            self.content_changed.emit()

    def _move_chapter_up(self):
        """Move selected chapter up."""
        current_row = self.chapter_list.currentRow()
        if current_row <= 0:
            return

        # Save current editor content before reordering
        if self.current_chapter_editor:
            self.current_chapter_editor.save_to_model()

        # Block signals during reorder to prevent spurious chapter switches
        self.chapter_list.blockSignals(True)

        # Swap in manuscript
        self.manuscript.chapters[current_row], self.manuscript.chapters[current_row - 1] = \
            self.manuscript.chapters[current_row - 1], self.manuscript.chapters[current_row]

        # Rebuild list items to ensure IDs match manuscript order
        self._rebuild_chapter_list()

        # Select the moved chapter (now at new position)
        self.chapter_list.setCurrentRow(current_row - 1)

        # Re-enable signals
        self.chapter_list.blockSignals(False)

        self.content_changed.emit()

    def _move_chapter_down(self):
        """Move selected chapter down."""
        current_row = self.chapter_list.currentRow()
        if current_row < 0 or current_row >= self.chapter_list.count() - 1:
            return

        # Save current editor content before reordering
        if self.current_chapter_editor:
            self.current_chapter_editor.save_to_model()

        # Block signals during reorder to prevent spurious chapter switches
        self.chapter_list.blockSignals(True)

        # Swap in manuscript
        self.manuscript.chapters[current_row], self.manuscript.chapters[current_row + 1] = \
            self.manuscript.chapters[current_row + 1], self.manuscript.chapters[current_row]

        # Rebuild list items to ensure IDs match manuscript order
        self._rebuild_chapter_list()

        # Select the moved chapter (now at new position)
        self.chapter_list.setCurrentRow(current_row + 1)

        # Re-enable signals
        self.chapter_list.blockSignals(False)

        self.content_changed.emit()

    def _rebuild_chapter_list(self):
        """Rebuild the chapter list from manuscript.chapters to ensure sync."""
        self.chapter_list.clear()
        for i, chapter in enumerate(self.manuscript.chapters, 1):
            chapter.number = i
            item = QListWidgetItem(f"{i}. {chapter.title}")
            item.setData(Qt.ItemDataRole.UserRole, chapter.id)
            self.chapter_list.addItem(item)

    def _renumber_chapters(self):
        """Renumber all chapters sequentially."""
        for i, chapter in enumerate(self.manuscript.chapters, 1):
            chapter.number = i
            item = self.chapter_list.item(i - 1)
            if item:
                item.setText(f"{i}. {chapter.title}")

    def _on_chapter_selected(self, current, previous):
        """Handle chapter selection change."""
        if not current:
            return

        # Save previous chapter and notify memory manager
        if self.current_chapter_editor and self._current_chapter_id:
            self.current_chapter_editor.save_to_model()
            self._update_total_word_count()
            # Notify memory manager of chapter exit (saves state, marks for re-analysis if changed)
            self.memory_manager.on_chapter_exit(self._current_chapter_id, save_content=True)

        # Load selected chapter
        chapter_id = current.data(Qt.ItemDataRole.UserRole)
        chapter = next(
            (c for c in self.manuscript.chapters if c.id == chapter_id),
            None
        )

        if chapter:
            # Notify memory manager of chapter entry (preloads cache, generates summary)
            self.memory_manager.on_chapter_enter(chapter_id)

            # Try to load content from cache first for faster display
            cached_content = self.memory_manager.get_chapter_content(chapter_id)
            if cached_content is not None and not chapter.content:
                chapter.content = cached_content

            self._clear_editor()
            self._current_chapter_id = chapter_id
            self.current_chapter_editor = ChapterEditor(chapter, self.project)
            self.current_chapter_editor.content_changed.connect(self._on_content_changed)
            self.current_chapter_editor.content_changed.connect(self.content_changed.emit)
            self.current_chapter_editor.annotations_changed.connect(self.annotations_changed.emit)
            self.current_chapter_editor.word_count_changed.connect(
                lambda _: self._update_total_word_count()
            )
            self.editor_layout.addWidget(self.current_chapter_editor)

            # Preload adjacent chapters in background for faster navigation
            self.memory_manager.preload_adjacent(chapter_id, count=1)

    def _on_content_changed(self):
        """Handle content changes - update memory manager cache."""
        if self._current_chapter_id and self.current_chapter_editor:
            new_content = self.current_chapter_editor.editor.toPlainText()
            self.memory_manager.on_content_changed(self._current_chapter_id, new_content)

    def _clear_editor(self):
        """Clear the editor area."""
        while self.editor_layout.count():
            item = self.editor_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _update_total_word_count(self):
        """Update total manuscript word count."""
        if not self.manuscript:
            return

        total = sum(chapter.word_count for chapter in self.manuscript.chapters)
        self.manuscript.total_word_count = total
        self.total_word_count_label.setText(f"Total Words: {total:,}")

    def load_manuscript(self, manuscript: Manuscript):
        """Load manuscript into editor."""
        self.manuscript = manuscript
        self._current_chapter_id = None
        self.chapter_list.clear()

        # Reset memory manager for new manuscript
        if self.project:
            self.memory_manager.set_project(self.project)

        for chapter in manuscript.chapters:
            item = QListWidgetItem(f"{chapter.number}. {chapter.title}")
            item.setData(Qt.ItemDataRole.UserRole, chapter.id)
            self.chapter_list.addItem(item)

            # Pre-populate cache with chapter content for faster initial load
            if chapter.content:
                self.memory_manager.cache.put(chapter.id, chapter.content)

        self._update_total_word_count()

    def get_manuscript(self) -> Manuscript:
        """Get manuscript data."""
        # Save current chapter
        if self.current_chapter_editor:
            self.current_chapter_editor.save_to_model()

        self._update_total_word_count()
        return self.manuscript

    def get_memory_stats(self) -> dict:
        """Get memory manager statistics for debugging/monitoring."""
        return self.memory_manager.get_cache_stats()

    def get_chapter_summary(self, chapter_id: str):
        """Get summary for a specific chapter (key points, characters, etc.)."""
        return self.memory_manager.get_summary(chapter_id)

    def get_all_key_points(self, max_points: int = 20):
        """Get the most important key points across all chapters."""
        return self.memory_manager.get_key_points_for_context(max_points)

    def search_key_points(self, query: str, point_types=None):
        """Search key points across all chapters."""
        return self.memory_manager.search_key_points(query, point_types)
