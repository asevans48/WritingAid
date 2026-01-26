"""Persistent collapsible chat widget for AI assistance."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QPushButton, QLabel, QFrame, QComboBox, QToolButton
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QIcon
from enum import Enum
from typing import List, Dict, Optional
from datetime import datetime
from src.ai.conversation_store import (
    ConversationStore, RatedConversation, ConversationMessage,
    ConversationMetadata, ConversationRating, MessageRole,
    create_conversation_from_messages
)
from src.config import get_ai_config


class ChatMode(Enum):
    """Available chat assistant modes."""
    GENERAL = "general"
    CHAPTER_FOCUS = "chapter_focus"
    WRITER = "writer"


class WriterInsertMode(Enum):
    """How to insert AI-generated text in Writer mode."""
    REPLACE_SELECTION = "replace_selection"  # Replace selected text
    INSERT_AT_CURSOR = "insert_at_cursor"    # Insert at cursor position
    APPEND_TO_CHAPTER = "append_to_chapter"  # Append to end of chapter
    REPLACE_CHAPTER = "replace_chapter"      # Replace entire chapter


class WritingPOV(Enum):
    """Narrative point of view options."""
    FIRST_PERSON = "first_person"
    THIRD_PERSON_LIMITED = "third_person_limited"
    THIRD_PERSON_OMNISCIENT = "third_person_omniscient"
    SECOND_PERSON = "second_person"


WRITING_POV_INFO = {
    WritingPOV.FIRST_PERSON: {
        "name": "First Person",
        "description": "I/We - narrator is a character in the story"
    },
    WritingPOV.THIRD_PERSON_LIMITED: {
        "name": "Third Person Limited",
        "description": "He/She/They - follows one character's perspective"
    },
    WritingPOV.THIRD_PERSON_OMNISCIENT: {
        "name": "Third Person Omniscient",
        "description": "He/She/They - all-knowing narrator, access to all thoughts"
    },
    WritingPOV.SECOND_PERSON: {
        "name": "Second Person",
        "description": "You - reader as protagonist (rare)"
    }
}


# Mode descriptions for UI
CHAT_MODE_INFO = {
    ChatMode.GENERAL: {
        "name": "General Assistant",
        "subtitle": "Your creative writing companion",
        "placeholder": "Ask me anything about your project...",
        "description": "General questions, agentic tasks, project-wide assistance"
    },
    ChatMode.CHAPTER_FOCUS: {
        "name": "Chapter Focus",
        "subtitle": "Focused on current chapter",
        "placeholder": "Ask about this chapter...",
        "description": "Discuss, analyze, and improve the current chapter"
    },
    ChatMode.WRITER: {
        "name": "Writer Mode",
        "subtitle": "AI-assisted writing",
        "placeholder": "Describe what to write or continue...",
        "description": "Write or complete chapters based on your outline and world"
    }
}


class ChatWidget(QWidget):
    """Collapsible chat interface for AI assistance."""

    message_sent = pyqtSignal(str, str, str)  # message, mode, insert_mode
    collapsed_changed = pyqtSignal(bool)  # Emits True when collapsed
    mode_changed = pyqtSignal(str)  # Emits mode name when changed

    def __init__(self):
        """Initialize chat widget."""
        super().__init__()
        self.setObjectName("chatWidget")
        self._collapsed = False
        self._current_mode = ChatMode.GENERAL
        self._insert_mode = WriterInsertMode.INSERT_AT_CURSOR
        self._has_selection = False  # Track if editor has selection

        # Conversation tracking for training data collection
        self._conversation_store = ConversationStore()
        self._current_conversation: List[Dict[str, str]] = []
        self._system_prompt: Optional[str] = None
        self._last_response_id: Optional[str] = None  # Track last AI response for rating
        self._project_name: Optional[str] = None
        self._ai_config = get_ai_config()

        self._init_ui()

    def _init_ui(self):
        """Initialize user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Collapsed state button (vertical AI button)
        self.collapsed_btn = QPushButton("🤖\nA\nI")
        self.collapsed_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 12px;
                font-weight: bold;
                padding: 8px 4px;
                min-height: 80px;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
        """)
        self.collapsed_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapsed_btn.clicked.connect(self._toggle_collapse)
        self.collapsed_btn.setVisible(False)  # Hidden initially
        layout.addWidget(self.collapsed_btn, 0, Qt.AlignmentFlag.AlignTop)

        # Collapsible header bar
        self.header_frame = QFrame()
        self.header_frame.setStyleSheet("""
            QFrame {
                background-color: #6366f1;
                border-radius: 6px;
            }
        """)
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(8)

        # Toggle button with title
        self.toggle_btn = QPushButton("◀ ✨ AI Assistant")
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: white;
                border: none;
                font-size: 13px;
                font-weight: 600;
                text-align: left;
                padding: 2px;
            }
            QPushButton:hover {
                color: #e0e7ff;
            }
        """)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle_collapse)
        header_layout.addWidget(self.toggle_btn)
        header_layout.addStretch()

        layout.addWidget(self.header_frame)

        # Content container (collapsible)
        self.content_widget = QWidget()
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(0, 4, 0, 0)
        content_layout.setSpacing(8)

        # Mode selector
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(6)

        mode_label = QLabel("Mode:")
        mode_label.setStyleSheet("font-size: 11px; color: #6b7280; font-weight: 500;")
        mode_layout.addWidget(mode_label)

        self.mode_combo = QComboBox()
        self.mode_combo.setStyleSheet("""
            QComboBox {
                padding: 4px 8px;
                font-size: 11px;
                border-radius: 4px;
                border: 1px solid #d1d5db;
                background-color: white;
                min-width: 120px;
            }
            QComboBox:hover {
                border-color: #6366f1;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 4px;
            }
        """)
        for mode in ChatMode:
            self.mode_combo.addItem(CHAT_MODE_INFO[mode]["name"], mode.value)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()

        content_layout.addLayout(mode_layout)

        # Subtitle (dynamic based on mode)
        self.subtitle = QLabel(CHAT_MODE_INFO[self._current_mode]["subtitle"])
        self.subtitle.setProperty("muted", True)
        self.subtitle.setStyleSheet("font-size: 11px; color: #a3a3a3;")
        content_layout.addWidget(self.subtitle)

        # Mode description
        self.mode_description = QLabel(CHAT_MODE_INFO[self._current_mode]["description"])
        self.mode_description.setWordWrap(True)
        self.mode_description.setStyleSheet("font-size: 10px; color: #9ca3af; font-style: italic; margin-bottom: 4px;")
        content_layout.addWidget(self.mode_description)

        # Writer mode insert options (only visible in Writer mode)
        self.insert_mode_widget = QWidget()
        insert_layout = QHBoxLayout(self.insert_mode_widget)
        insert_layout.setContentsMargins(0, 4, 0, 4)
        insert_layout.setSpacing(6)

        insert_label = QLabel("Insert:")
        insert_label.setStyleSheet("font-size: 11px; color: #6b7280; font-weight: 500;")
        insert_layout.addWidget(insert_label)

        self.insert_combo = QComboBox()
        self.insert_combo.setStyleSheet("""
            QComboBox {
                padding: 4px 8px;
                font-size: 11px;
                border-radius: 4px;
                border: 1px solid #d1d5db;
                background-color: white;
                min-width: 140px;
            }
            QComboBox:hover {
                border-color: #6366f1;
            }
        """)
        self.insert_combo.addItem("At Cursor", WriterInsertMode.INSERT_AT_CURSOR.value)
        self.insert_combo.addItem("Append to Chapter", WriterInsertMode.APPEND_TO_CHAPTER.value)
        self.insert_combo.addItem("Replace Chapter", WriterInsertMode.REPLACE_CHAPTER.value)
        self.insert_combo.currentIndexChanged.connect(self._on_insert_mode_changed)
        insert_layout.addWidget(self.insert_combo)
        insert_layout.addStretch()

        content_layout.addWidget(self.insert_mode_widget)
        self.insert_mode_widget.setVisible(False)  # Hidden by default (only in Writer mode)

        # POV options widget (only visible in Writer mode)
        self.pov_widget = QWidget()
        pov_layout = QVBoxLayout(self.pov_widget)
        pov_layout.setContentsMargins(0, 4, 0, 4)
        pov_layout.setSpacing(6)

        # Character POV row
        char_pov_layout = QHBoxLayout()
        char_pov_layout.setSpacing(6)
        char_pov_label = QLabel("Character:")
        char_pov_label.setStyleSheet("font-size: 11px; color: #6b7280; font-weight: 500;")
        char_pov_layout.addWidget(char_pov_label)

        self.char_pov_combo = QComboBox()
        self.char_pov_combo.setStyleSheet("""
            QComboBox {
                padding: 4px 8px;
                font-size: 11px;
                border-radius: 4px;
                border: 1px solid #d1d5db;
                background-color: white;
                min-width: 120px;
            }
            QComboBox:hover {
                border-color: #6366f1;
            }
        """)
        self.char_pov_combo.addItem("(From chapter)", "")
        char_pov_layout.addWidget(self.char_pov_combo)
        char_pov_layout.addStretch()
        pov_layout.addLayout(char_pov_layout)

        # Writing POV row
        writing_pov_layout = QHBoxLayout()
        writing_pov_layout.setSpacing(6)
        writing_pov_label = QLabel("Narrative:")
        writing_pov_label.setStyleSheet("font-size: 11px; color: #6b7280; font-weight: 500;")
        writing_pov_layout.addWidget(writing_pov_label)

        self.writing_pov_combo = QComboBox()
        self.writing_pov_combo.setStyleSheet("""
            QComboBox {
                padding: 4px 8px;
                font-size: 11px;
                border-radius: 4px;
                border: 1px solid #d1d5db;
                background-color: white;
                min-width: 140px;
            }
            QComboBox:hover {
                border-color: #6366f1;
            }
        """)
        self.writing_pov_combo.addItem("(From chapter)", "")
        for pov in WritingPOV:
            self.writing_pov_combo.addItem(WRITING_POV_INFO[pov]["name"], pov.value)
        writing_pov_layout.addWidget(self.writing_pov_combo)
        writing_pov_layout.addStretch()
        pov_layout.addLayout(writing_pov_layout)

        content_layout.addWidget(self.pov_widget)
        self.pov_widget.setVisible(False)  # Hidden by default (only in Writer mode)

        # Selection indicator (shown when text is selected in Writer mode)
        self.selection_indicator = QLabel("Text selected - will replace selection")
        self.selection_indicator.setStyleSheet(
            "font-size: 10px; color: #059669; font-weight: 500; "
            "background-color: #d1fae5; padding: 4px 8px; border-radius: 4px;"
        )
        content_layout.addWidget(self.selection_indicator)
        self.selection_indicator.setVisible(False)

        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #e5e7eb; max-height: 1px;")
        content_layout.addWidget(separator)

        # Chat history with modern styling
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setPlaceholderText("Start a conversation...")
        self.chat_history.setStyleSheet("""
            QTextEdit {
                background-color: #fafafa;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 12px;
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        content_layout.addWidget(self.chat_history)

        # Input area with modern styling
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask me anything...")
        self.input_field.returnPressed.connect(self._send_message)
        self.input_field.setStyleSheet("""
            QLineEdit {
                padding: 10px 12px;
                font-size: 13px;
                border-radius: 8px;
                border: 1px solid #e5e7eb;
                background-color: white;
            }
            QLineEdit:focus {
                border: 2px solid #6366f1;
            }
        """)
        content_layout.addWidget(self.input_field)

        # Rating widget (hidden by default, shown after AI responses)
        self.rating_widget = QFrame()
        self.rating_widget.setStyleSheet("""
            QFrame {
                background-color: #f3f4f6;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 4px;
            }
        """)
        rating_layout = QHBoxLayout(self.rating_widget)
        rating_layout.setContentsMargins(8, 4, 8, 4)
        rating_layout.setSpacing(6)

        rating_label = QLabel("Rate this response:")
        rating_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        rating_layout.addWidget(rating_label)

        self.rating_excellent_btn = QPushButton("⭐ Excellent")
        self.rating_excellent_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.rating_excellent_btn.clicked.connect(lambda: self._rate_response(ConversationRating.EXCELLENT))
        rating_layout.addWidget(self.rating_excellent_btn)

        self.rating_good_btn = QPushButton("👍 Good")
        self.rating_good_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        self.rating_good_btn.clicked.connect(lambda: self._rate_response(ConversationRating.GOOD))
        rating_layout.addWidget(self.rating_good_btn)

        self.rating_skip_btn = QPushButton("Skip")
        self.rating_skip_btn.setStyleSheet("""
            QPushButton {
                background-color: #6b7280;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        self.rating_skip_btn.clicked.connect(self._hide_rating_widget)
        rating_layout.addWidget(self.rating_skip_btn)

        rating_layout.addStretch()

        self.rating_widget.setVisible(False)  # Hidden by default
        content_layout.addWidget(self.rating_widget)

        # Send button with modern styling
        send_button = QPushButton("Send")
        send_button.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: 500;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            QPushButton:pressed {
                background-color: #4338ca;
            }
        """)
        send_button.clicked.connect(self._send_message)
        content_layout.addWidget(send_button)

        layout.addWidget(self.content_widget)

    def _toggle_collapse(self):
        """Toggle between collapsed and expanded state."""
        self._collapsed = not self._collapsed
        self.content_widget.setVisible(not self._collapsed)
        self.header_frame.setVisible(not self._collapsed)
        self.collapsed_btn.setVisible(self._collapsed)

        if self._collapsed:
            self.setMinimumWidth(36)
            self.setMaximumWidth(40)
        else:
            self.setMinimumWidth(300)
            self.setMaximumWidth(400)

        self.collapsed_changed.emit(self._collapsed)

    def is_collapsed(self) -> bool:
        """Return whether the widget is collapsed."""
        return self._collapsed

    def set_collapsed(self, collapsed: bool):
        """Set the collapsed state."""
        if collapsed != self._collapsed:
            self._toggle_collapse()

    def _on_mode_changed(self, index: int):
        """Handle mode selection change."""
        mode_value = self.mode_combo.itemData(index)
        self._current_mode = ChatMode(mode_value)

        # Update UI elements for new mode
        mode_info = CHAT_MODE_INFO[self._current_mode]
        self.subtitle.setText(mode_info["subtitle"])
        self.mode_description.setText(mode_info["description"])
        self.input_field.setPlaceholderText(mode_info["placeholder"])

        # Show/hide writer mode options
        is_writer_mode = self._current_mode == ChatMode.WRITER
        self.insert_mode_widget.setVisible(is_writer_mode and not self._has_selection)
        self.pov_widget.setVisible(is_writer_mode)
        self.selection_indicator.setVisible(is_writer_mode and self._has_selection)

        # Clear chat history when switching modes
        self.chat_history.clear()

        # Emit mode changed signal
        self.mode_changed.emit(mode_value)

    def _on_insert_mode_changed(self, index: int):
        """Handle insert mode selection change."""
        insert_value = self.insert_combo.itemData(index)
        self._insert_mode = WriterInsertMode(insert_value)

    def update_selection_state(self, has_selection: bool):
        """Update UI based on whether editor has text selected.

        Args:
            has_selection: True if text is selected in the editor
        """
        self._has_selection = has_selection

        # Only relevant in Writer mode
        if self._current_mode == ChatMode.WRITER:
            self.insert_mode_widget.setVisible(not has_selection)
            self.selection_indicator.setVisible(has_selection)

    def get_insert_mode(self) -> str:
        """Get the current insert mode for Writer mode.

        Returns:
            Insert mode value, or 'replace_selection' if text is selected
        """
        if self._has_selection:
            return WriterInsertMode.REPLACE_SELECTION.value
        return self._insert_mode.value

    def get_current_mode(self) -> str:
        """Get the current chat mode value."""
        return self._current_mode.value

    def set_mode(self, mode: str):
        """Set the chat mode programmatically."""
        for i in range(self.mode_combo.count()):
            if self.mode_combo.itemData(i) == mode:
                self.mode_combo.setCurrentIndex(i)
                break

    def _send_message(self):
        """Send user message."""
        message = self.input_field.text().strip()
        if message:
            self.add_message("You", message)
            self.input_field.clear()
            insert_mode = self.get_insert_mode() if self._current_mode == ChatMode.WRITER else ""
            self.message_sent.emit(message, self._current_mode.value, insert_mode)

    def add_message(self, sender: str, message: str, system_prompt: Optional[str] = None):
        """Add message to chat history with modern bubble styling.

        Args:
            sender: "You" for user, "Assistant" for AI
            message: The message content
            system_prompt: Optional system prompt (for AI responses)
        """
        is_user = sender == "You"

        # Track message for training data collection
        if is_user:
            # User message
            self._current_conversation.append({
                "role": "user",
                "content": message
            })
        else:
            # AI response - also track system prompt if provided
            if system_prompt:
                # Add system message at start if not already present
                if not self._current_conversation or self._current_conversation[0].get("role") != "system":
                    self._current_conversation.insert(0, {
                        "role": "system",
                        "content": system_prompt
                    })

            self._current_conversation.append({
                "role": "assistant",
                "content": message
            })

        # Different styling for user vs AI
        if is_user:
            bubble_style = "background-color: #6366f1; color: white; border-radius: 12px 12px 4px 12px; padding: 8px 12px; margin: 4px 0 4px 40px; display: inline-block;"
            formatted = f'<div style="text-align: right;"><span style="{bubble_style}">{message}</span></div>'
        else:
            bubble_style = "background-color: white; color: #1a1a1a; border: 1px solid #e5e7eb; border-radius: 12px 12px 12px 4px; padding: 8px 12px; margin: 4px 40px 4px 0; display: inline-block;"
            formatted = f'<div style="text-align: left;"><span style="{bubble_style}"><strong style="color: #6366f1;">AI:</strong> {message}</span></div>'

            # Check if training is enabled to show rating widget
            settings = self._ai_config.get_settings()
            enable_training = settings.get("enable_conversation_collection", False)

            if enable_training:
                # Show rating widget for user to rate this response
                self.rating_widget.setVisible(True)

        self.chat_history.append(formatted)

    def set_characters(self, characters: list):
        """Populate character POV dropdown from project characters.

        Args:
            characters: List of character objects with 'name' attribute
        """
        current_selection = self.char_pov_combo.currentData()
        self.char_pov_combo.clear()
        self.char_pov_combo.addItem("(From chapter)", "")

        for char in characters:
            name = getattr(char, 'name', str(char))
            self.char_pov_combo.addItem(name, name)

        # Restore selection if still valid
        if current_selection:
            for i in range(self.char_pov_combo.count()):
                if self.char_pov_combo.itemData(i) == current_selection:
                    self.char_pov_combo.setCurrentIndex(i)
                    break

    def get_character_pov(self) -> str:
        """Get the selected character POV.

        Returns:
            Character name or empty string if using chapter default
        """
        return self.char_pov_combo.currentData() or ""

    def get_writing_pov(self) -> str:
        """Get the selected writing POV.

        Returns:
            Writing POV value or empty string if using chapter default
        """
        return self.writing_pov_combo.currentData() or ""

    def get_writer_settings(self) -> dict:
        """Get all Writer mode settings.

        Returns:
            Dict with insert_mode, character_pov, writing_pov
        """
        return {
            "insert_mode": self.get_insert_mode(),
            "character_pov": self.get_character_pov(),
            "writing_pov": self.get_writing_pov()
        }

    def set_project_name(self, project_name: str):
        """Set the current project name for training data metadata.

        Args:
            project_name: Name of the current project
        """
        self._project_name = project_name

    def _hide_rating_widget(self):
        """Hide the rating widget (skip rating)."""
        self.rating_widget.setVisible(False)
        # Clear current conversation without saving
        self._current_conversation = []

    def _rate_response(self, rating: ConversationRating):
        """Rate the current AI response and save to training data.

        Args:
            rating: The rating to assign (EXCELLENT or GOOD typically)
        """
        if not self._current_conversation:
            print("No conversation to rate")
            return

        # Hide rating widget
        self.rating_widget.setVisible(False)

        # Create metadata for this conversation
        settings = self._ai_config.get_settings()
        metadata = ConversationMetadata(
            project_name=self._project_name or "Unknown Project",
            task_type=self._current_mode.value,  # general, chapter_focus, writer
            provider=settings.get("default_llm", "claude"),
            model_name=self._ai_config.get_model(settings.get("default_llm", "claude")),
            temperature=settings.get("temperature", 0.7),
            max_tokens=settings.get("max_tokens", 2000),
        )

        # Create conversation from tracked messages
        conversation = create_conversation_from_messages(
            messages=self._current_conversation,
            metadata=metadata
        )

        # Rate it
        conversation.rating = rating
        conversation.rated_at = datetime.now()

        # Save to store
        try:
            conv_id = self._conversation_store.add_conversation(conversation)
            print(f"Saved rated conversation {conv_id} with rating: {rating.value}")

            # Show feedback to user
            self.chat_history.append(
                f'<div style="text-align: center; color: #10b981; font-size: 11px; margin: 4px 0;">'
                f'✓ Response rated as {rating.value.title()} and saved for training</div>'
            )

        except Exception as e:
            print(f"Failed to save conversation: {e}")
            self.chat_history.append(
                f'<div style="text-align: center; color: #ef4444; font-size: 11px; margin: 4px 0;">'
                f'Failed to save rating: {str(e)}</div>'
            )

        # Clear current conversation for next exchange
        self._current_conversation = []

    def clear_conversation(self):
        """Clear the current conversation tracking (start fresh)."""
        self._current_conversation = []
        self.rating_widget.setVisible(False)
