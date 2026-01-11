"""Manuscript editor with chapter navigation and revision system."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTextEdit, QToolBar, QComboBox, QSpinBox,
    QMessageBox, QInputDialog, QGroupBox, QSplitter, QFileDialog
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont, QTextCursor, QAction
from typing import List, Optional
import uuid

from src.models.project import Manuscript, Chapter
from src.ui.enhanced_text_editor import EnhancedTextEditor


class ChapterEditor(QWidget):
    """Editor for a single chapter with formatting and AI hints."""

    content_changed = pyqtSignal()
    word_count_changed = pyqtSignal(int)

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

        # Main editor - use enhanced editor
        self.editor = EnhancedTextEditor()
        self.editor.setPlaceholderText("Start writing your chapter...")
        self.editor.textChanged.connect(self._on_text_changed)

        # Set default font
        font = QFont("Times New Roman", 12)
        self.editor.setFont(font)

        # Set up context lookup callbacks if project is available
        if self.project:
            self._setup_context_lookup()

        layout.addWidget(self.editor)

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

    def _request_ai_hints(self):
        """Request AI hints for improving the chapter."""
        # TODO: Integrate with AI client
        QMessageBox.information(
            self,
            "AI Hints",
            "AI chapter hints will be integrated soon."
        )

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

        # Create RAG system
        rag = RAGSystem(self.project)

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

    def save_to_model(self):
        """Save editor content to chapter model."""
        self.chapter.title = self.title_edit.toPlainText()
        self.chapter.content = self.editor.toPlainText()
        self._update_word_count()


class ManuscriptEditor(QWidget):
    """Main manuscript editor with chapter navigation."""

    content_changed = pyqtSignal()

    def __init__(self, project=None):
        """Initialize manuscript editor."""
        super().__init__()
        self.manuscript: Optional[Manuscript] = None
        self.project = project
        self.current_chapter_editor: Optional[ChapterEditor] = None
        self._init_ui()

    def set_project(self, project):
        """Set the project for context lookup."""
        self.project = project

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
        left_layout.addWidget(self.chapter_list)

        # Chapter buttons
        button_layout = QVBoxLayout()

        add_button = QPushButton("Add Chapter")
        add_button.clicked.connect(self._add_chapter)
        button_layout.addWidget(add_button)

        insert_button = QPushButton("Insert Chapter")
        insert_button.clicked.connect(self._insert_chapter)
        button_layout.addWidget(insert_button)

        rename_button = QPushButton("Rename Chapter")
        rename_button.clicked.connect(self._rename_chapter)
        button_layout.addWidget(rename_button)

        remove_button = QPushButton("Remove Chapter")
        remove_button.clicked.connect(self._remove_chapter)
        button_layout.addWidget(remove_button)

        move_up_button = QPushButton("Move Up")
        move_up_button.clicked.connect(self._move_chapter_up)
        button_layout.addWidget(move_up_button)

        move_down_button = QPushButton("Move Down")
        move_down_button.clicked.connect(self._move_chapter_down)
        button_layout.addWidget(move_down_button)

        left_layout.addLayout(button_layout)

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

        # Swap in manuscript
        self.manuscript.chapters[current_row], self.manuscript.chapters[current_row - 1] = \
            self.manuscript.chapters[current_row - 1], self.manuscript.chapters[current_row]

        # Swap in list
        current_item = self.chapter_list.takeItem(current_row)
        self.chapter_list.insertItem(current_row - 1, current_item)
        self.chapter_list.setCurrentItem(current_item)

        self._renumber_chapters()
        self.content_changed.emit()

    def _move_chapter_down(self):
        """Move selected chapter down."""
        current_row = self.chapter_list.currentRow()
        if current_row < 0 or current_row >= self.chapter_list.count() - 1:
            return

        # Swap in manuscript
        self.manuscript.chapters[current_row], self.manuscript.chapters[current_row + 1] = \
            self.manuscript.chapters[current_row + 1], self.manuscript.chapters[current_row]

        # Swap in list
        current_item = self.chapter_list.takeItem(current_row)
        self.chapter_list.insertItem(current_row + 1, current_item)
        self.chapter_list.setCurrentItem(current_item)

        self._renumber_chapters()
        self.content_changed.emit()

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

        # Save previous chapter
        if self.current_chapter_editor:
            self.current_chapter_editor.save_to_model()
            self._update_total_word_count()

        # Load selected chapter
        chapter_id = current.data(Qt.ItemDataRole.UserRole)
        chapter = next(
            (c for c in self.manuscript.chapters if c.id == chapter_id),
            None
        )

        if chapter:
            self._clear_editor()
            self.current_chapter_editor = ChapterEditor(chapter, self.project)
            self.current_chapter_editor.content_changed.connect(self.content_changed.emit)
            self.current_chapter_editor.word_count_changed.connect(
                lambda _: self._update_total_word_count()
            )
            self.editor_layout.addWidget(self.current_chapter_editor)

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
        self.chapter_list.clear()

        for chapter in manuscript.chapters:
            item = QListWidgetItem(f"{chapter.number}. {chapter.title}")
            item.setData(Qt.ItemDataRole.UserRole, chapter.id)
            self.chapter_list.addItem(item)

        self._update_total_word_count()

    def get_manuscript(self) -> Manuscript:
        """Get manuscript data."""
        # Save current chapter
        if self.current_chapter_editor:
            self.current_chapter_editor.save_to_model()

        self._update_total_word_count()
        return self.manuscript
