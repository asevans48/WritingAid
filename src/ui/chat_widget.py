"""Persistent collapsible chat widget for AI assistance."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QLineEdit,
    QPushButton, QLabel, QFrame
)
from PyQt6.QtCore import pyqtSignal, Qt


class ChatWidget(QWidget):
    """Collapsible chat interface for AI assistance."""

    message_sent = pyqtSignal(str)

    def __init__(self):
        """Initialize chat widget."""
        super().__init__()
        self.setObjectName("chatWidget")
        self._init_ui()

    def _init_ui(self):
        """Initialize user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header with icon
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)

        title = QLabel("✨ AI Assistant")
        title.setProperty("subheading", True)
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #6366f1;")
        header_layout.addWidget(title)

        subtitle = QLabel("Your creative writing companion")
        subtitle.setProperty("muted", True)
        subtitle.setStyleSheet("font-size: 11px; color: #a3a3a3;")
        header_layout.addWidget(subtitle)

        layout.addLayout(header_layout)

        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #e5e7eb; max-height: 1px;")
        layout.addWidget(separator)

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
        layout.addWidget(self.chat_history)

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
        layout.addWidget(self.input_field)

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
        layout.addWidget(send_button)

    def _send_message(self):
        """Send user message."""
        message = self.input_field.text().strip()
        if message:
            self.add_message("You", message)
            self.input_field.clear()
            self.message_sent.emit(message)

    def add_message(self, sender: str, message: str):
        """Add message to chat history with modern bubble styling."""
        is_user = sender == "You"

        # Different styling for user vs AI
        if is_user:
            bubble_style = "background-color: #6366f1; color: white; border-radius: 12px 12px 4px 12px; padding: 8px 12px; margin: 4px 0 4px 40px; display: inline-block;"
            formatted = f'<div style="text-align: right;"><span style="{bubble_style}">{message}</span></div>'
        else:
            bubble_style = "background-color: white; color: #1a1a1a; border: 1px solid #e5e7eb; border-radius: 12px 12px 12px 4px; padding: 8px 12px; margin: 4px 40px 4px 0; display: inline-block;"
            formatted = f'<div style="text-align: left;"><span style="{bubble_style}"><strong style="color: #6366f1;">AI:</strong> {message}</span></div>'

        self.chat_history.append(formatted)
