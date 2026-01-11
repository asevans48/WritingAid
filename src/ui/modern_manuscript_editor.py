"""Modern, minimal manuscript editor focused on creativity."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from src.ui.enhanced_text_editor import EnhancedTextEditor


class MinimalChapterCard(QWidget):
    """Minimal chapter card for sidebar."""

    clicked = pyqtSignal(str)  # Emits chapter ID

    def __init__(self, chapter_id: str, number: int, title: str, word_count: int):
        """Initialize chapter card."""
        super().__init__()
        self.chapter_id = chapter_id
        self._init_ui(number, title, word_count)

    def _init_ui(self, number: int, title: str, word_count: int):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)

        # Chapter number and title
        header = QLabel(f"{number}. {title}")
        header.setStyleSheet("font-weight: 600; font-size: 13px; color: #1a1a1a;")
        layout.addWidget(header)

        # Word count
        count_label = QLabel(f"{word_count:,} words")
        count_label.setProperty("muted", True)
        count_label.setStyleSheet("font-size: 11px; color: #a3a3a3;")
        layout.addWidget(count_label)

        # Style the card
        self.setStyleSheet("""
            MinimalChapterCard {
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
            }
            MinimalChapterCard:hover {
                border-color: #6366f1;
                background-color: #fafafa;
            }
        """)

        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        """Handle click."""
        self.clicked.emit(self.chapter_id)


class ModernWritingInterface(QWidget):
    """Distraction-free writing interface."""

    content_changed = pyqtSignal()
    word_count_changed = pyqtSignal(int)

    def __init__(self):
        """Initialize writing interface."""
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 20, 40, 20)  # More breathing room
        layout.setSpacing(16)

        # Minimal header
        header_layout = QHBoxLayout()

        # Chapter title (minimal)
        self.chapter_title = QLabel()
        self.chapter_title.setStyleSheet("font-size: 20px; font-weight: 600; color: #1a1a1a;")
        header_layout.addWidget(self.chapter_title)

        header_layout.addStretch()

        # Word count badge
        self.word_count_badge = QLabel("0 words")
        self.word_count_badge.setStyleSheet("""
            background-color: #f3f4f6;
            color: #6b7280;
            padding: 6px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 500;
        """)
        header_layout.addWidget(self.word_count_badge)

        layout.addLayout(header_layout)

        # Writing editor - large, clean
        self.editor = EnhancedTextEditor()
        self.editor.setPlaceholderText("Start writing...")

        # Large, comfortable font for writing
        font = QFont("Georgia", 14)  # Serif for better reading
        font.setStyleHint(QFont.StyleHint.Serif)
        self.editor.setFont(font)

        # Minimal editor styling
        self.editor.setStyleSheet("""
            EnhancedTextEditor {
                background-color: white;
                border: none;
                padding: 20px;
                line-height: 1.8;
                color: #1a1a1a;
            }
        """)

        self.editor.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.editor)

        # Floating action bar (minimal, bottom)
        action_bar = QFrame()
        action_bar.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                padding: 8px;
            }
        """)

        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(12, 8, 12, 8)
        action_layout.setSpacing(8)

        # Context lookup button
        context_btn = QPushButton("🔍 Context")
        context_btn.setStyleSheet(self._get_mini_button_style())
        action_layout.addWidget(context_btn)

        # AI hints button
        ai_btn = QPushButton("✨ AI Hints")
        ai_btn.setStyleSheet(self._get_mini_button_style())
        action_layout.addWidget(ai_btn)

        action_layout.addStretch()

        # Save revision button
        revision_btn = QPushButton("💾 Save Revision")
        revision_btn.setStyleSheet(self._get_mini_button_style())
        action_layout.addWidget(revision_btn)

        layout.addWidget(action_bar)

    def _get_mini_button_style(self) -> str:
        """Get style for mini action buttons."""
        return """
            QPushButton {
                background-color: transparent;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 500;
                color: #6b7280;
            }
            QPushButton:hover {
                background-color: #f9fafb;
                border-color: #6366f1;
                color: #6366f1;
            }
        """

    def _on_text_changed(self):
        """Handle text changes."""
        text = self.editor.toPlainText()
        word_count = len([w for w in text.split() if w])

        self.word_count_badge.setText(f"{word_count:,} words")
        self.word_count_changed.emit(word_count)
        self.content_changed.emit()

    def set_chapter(self, title: str):
        """Set current chapter."""
        self.chapter_title.setText(title)

    def set_content(self, content: str):
        """Set editor content."""
        self.editor.setPlainText(content)

    def get_content(self) -> str:
        """Get editor content."""
        return self.editor.toPlainText()
