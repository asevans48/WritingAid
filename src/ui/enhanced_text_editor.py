"""Enhanced text editor with context menu and Word support."""

from PyQt6.QtWidgets import (
    QTextEdit, QMenu, QDialog, QVBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QTextBrowser,
    QHBoxLayout, QMessageBox
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QAction, QTextCursor, QTextCharFormat, QColor
from typing import Optional, Callable
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io


class ContextLookupDialog(QDialog):
    """Dialog for displaying context lookup results."""

    def __init__(self, title: str, content: str, parent=None):
        """Initialize context lookup dialog."""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(600, 400)

        layout = QVBoxLayout(self)

        # Content display
        self.content_browser = QTextBrowser()
        self.content_browser.setMarkdown(content)
        self.content_browser.setOpenExternalLinks(False)
        layout.addWidget(self.content_browser)

        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)


class QuickReferenceDialog(QDialog):
    """Dialog for quick reference selection."""

    def __init__(self, items: list, item_type: str, parent=None):
        """Initialize quick reference dialog."""
        super().__init__(parent)
        self.setWindowTitle(f"Select {item_type}")
        self.setMinimumSize(400, 300)
        self.selected_item = None

        layout = QVBoxLayout(self)

        label = QLabel(f"Select a {item_type} to view:")
        layout.addWidget(label)

        # Item list
        self.item_list = QListWidget()
        for item in items:
            self.item_list.addItem(item)
        self.item_list.itemDoubleClicked.connect(self._on_item_selected)
        layout.addWidget(self.item_list)

        # Buttons
        button_layout = QHBoxLayout()

        select_button = QPushButton("Select")
        select_button.clicked.connect(self._on_item_selected)
        button_layout.addWidget(select_button)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)

    def _on_item_selected(self):
        """Handle item selection."""
        current_item = self.item_list.currentItem()
        if current_item:
            self.selected_item = current_item.text()
            self.accept()


class EnhancedTextEditor(QTextEdit):
    """Enhanced text editor with context menu and Word support."""

    context_lookup_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        """Initialize enhanced text editor."""
        super().__init__(parent)

        # Callbacks for context lookup
        self.lookup_worldbuilding_callback: Optional[Callable] = None
        self.lookup_characters_callback: Optional[Callable] = None
        self.lookup_plot_callback: Optional[Callable] = None
        self.lookup_context_callback: Optional[Callable] = None
        self.get_character_list_callback: Optional[Callable] = None
        self.get_worldbuilding_sections_callback: Optional[Callable] = None

        # Enable rich text
        self.setAcceptRichText(True)

        # Set up context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, position):
        """Show custom context menu."""
        menu = QMenu(self)

        # Standard edit actions
        undo_action = QAction("Undo", self)
        undo_action.triggered.connect(self.undo)
        undo_action.setEnabled(self.document().isUndoAvailable())
        menu.addAction(undo_action)

        redo_action = QAction("Redo", self)
        redo_action.triggered.connect(self.redo)
        redo_action.setEnabled(self.document().isRedoAvailable())
        menu.addAction(redo_action)

        menu.addSeparator()

        cut_action = QAction("Cut", self)
        cut_action.triggered.connect(self.cut)
        cut_action.setEnabled(self.textCursor().hasSelection())
        menu.addAction(cut_action)

        copy_action = QAction("Copy", self)
        copy_action.triggered.connect(self.copy)
        copy_action.setEnabled(self.textCursor().hasSelection())
        menu.addAction(copy_action)

        paste_action = QAction("Paste", self)
        paste_action.triggered.connect(self.paste)
        menu.addAction(paste_action)

        menu.addSeparator()

        # Context lookup menu
        lookup_menu = menu.addMenu("Look Up Context")

        # Get selected text
        cursor = self.textCursor()
        selected_text = cursor.selectedText()

        if selected_text:
            # Lookup selected text
            lookup_selected = QAction(f'Look Up "{selected_text[:30]}..."', self)
            lookup_selected.triggered.connect(lambda: self._lookup_selected_text(selected_text))
            lookup_menu.addAction(lookup_selected)
            lookup_menu.addSeparator()

        # Character lookup
        character_action = QAction("Character Reference", self)
        character_action.triggered.connect(self._lookup_character)
        lookup_menu.addAction(character_action)

        # Worldbuilding lookup
        worldbuilding_action = QAction("Worldbuilding Reference", self)
        worldbuilding_action.triggered.connect(self._lookup_worldbuilding)
        lookup_menu.addAction(worldbuilding_action)

        # Plot lookup
        plot_action = QAction("Plot Reference", self)
        plot_action.triggered.connect(self._lookup_plot)
        lookup_menu.addAction(plot_action)

        menu.exec(self.mapToGlobal(position))

    def _lookup_selected_text(self, text: str):
        """Look up context for selected text."""
        if self.lookup_context_callback:
            result = self.lookup_context_callback(text)
            dialog = ContextLookupDialog(f"Context for: {text}", result, self)
            dialog.exec()

    def _lookup_character(self):
        """Look up character reference."""
        if not self.get_character_list_callback:
            QMessageBox.information(self, "Not Available", "Character lookup not configured.")
            return

        characters = self.get_character_list_callback()
        if not characters:
            QMessageBox.information(self, "No Characters", "No characters defined in your project yet.")
            return

        dialog = QuickReferenceDialog(characters, "Character", self)
        if dialog.exec() and dialog.selected_item:
            if self.lookup_characters_callback:
                result = self.lookup_characters_callback(dialog.selected_item)
                ref_dialog = ContextLookupDialog(f"Character: {dialog.selected_item}", result, self)
                ref_dialog.exec()

    def _lookup_worldbuilding(self):
        """Look up worldbuilding reference."""
        if not self.get_worldbuilding_sections_callback:
            QMessageBox.information(self, "Not Available", "Worldbuilding lookup not configured.")
            return

        sections = self.get_worldbuilding_sections_callback()
        if not sections:
            QMessageBox.information(self, "No Worldbuilding", "No worldbuilding sections defined yet.")
            return

        dialog = QuickReferenceDialog(sections, "Worldbuilding Section", self)
        if dialog.exec() and dialog.selected_item:
            if self.lookup_worldbuilding_callback:
                result = self.lookup_worldbuilding_callback(dialog.selected_item)
                ref_dialog = ContextLookupDialog(f"Worldbuilding: {dialog.selected_item}", result, self)
                ref_dialog.exec()

    def _lookup_plot(self):
        """Look up plot reference."""
        if self.lookup_plot_callback:
            result = self.lookup_plot_callback()
            dialog = ContextLookupDialog("Plot Reference", result, self)
            dialog.exec()

    def import_from_docx(self, file_path: str) -> bool:
        """Import content from Word document."""
        try:
            doc = Document(file_path)

            # Clear current content
            self.clear()

            # Import paragraphs with formatting
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)

            for para in doc.paragraphs:
                # Handle paragraph alignment
                if para.alignment == WD_ALIGN_PARAGRAPH.CENTER:
                    block_format = cursor.blockFormat()
                    block_format.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    cursor.setBlockFormat(block_format)

                # Process runs (formatted text segments)
                for run in para.runs:
                    # Create text format
                    char_format = QTextCharFormat()

                    # Font family
                    if run.font.name:
                        char_format.setFontFamily(run.font.name)

                    # Font size
                    if run.font.size and run.font.size.pt and run.font.size.pt > 0:
                        char_format.setFontPointSize(run.font.size.pt)

                    # Bold
                    if run.font.bold:
                        char_format.setFontWeight(700)

                    # Italic
                    if run.font.italic:
                        char_format.setFontItalic(True)

                    # Underline
                    if run.font.underline:
                        char_format.setFontUnderline(True)

                    # Color
                    if run.font.color and run.font.color.rgb:
                        rgb = run.font.color.rgb
                        color = QColor(rgb[0], rgb[1], rgb[2])
                        char_format.setForeground(color)

                    # Insert text with formatting
                    cursor.insertText(run.text, char_format)

                # New paragraph
                cursor.insertBlock()

            return True

        except Exception as e:
            print(f"Error importing Word document: {e}")
            return False

    def export_to_docx(self, file_path: str, title: str = "") -> bool:
        """Export content to Word document with formatting."""
        try:
            doc = Document()

            # Add title if provided
            if title:
                heading = doc.add_heading(title, 1)

            # Get HTML content
            html_content = self.toHtml()

            # Parse and convert (simplified - preserves basic formatting)
            text_content = self.toPlainText()

            # Add paragraphs
            paragraphs = text_content.split('\n')
            for para_text in paragraphs:
                if para_text.strip():
                    para = doc.add_paragraph(para_text)

            doc.save(file_path)
            return True

        except Exception as e:
            print(f"Error exporting to Word: {e}")
            return False

    def paste_from_word(self):
        """Paste content from Word with formatting preserved."""
        # Qt automatically handles rich text paste from clipboard
        # This method can be extended for special handling
        self.paste()

    def set_callbacks(
        self,
        lookup_worldbuilding: Optional[Callable] = None,
        lookup_characters: Optional[Callable] = None,
        lookup_plot: Optional[Callable] = None,
        lookup_context: Optional[Callable] = None,
        get_character_list: Optional[Callable] = None,
        get_worldbuilding_sections: Optional[Callable] = None
    ):
        """Set callback functions for context lookup."""
        self.lookup_worldbuilding_callback = lookup_worldbuilding
        self.lookup_characters_callback = lookup_characters
        self.lookup_plot_callback = lookup_plot
        self.lookup_context_callback = lookup_context
        self.get_character_list_callback = get_character_list
        self.get_worldbuilding_sections_callback = get_worldbuilding_sections
