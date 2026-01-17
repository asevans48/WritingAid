"""Persistent collapsible chat widget for AI assistance."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QPushButton, QLabel, QFrame
)
from PyQt6.QtCore import pyqtSignal, Qt


class ChatWidget(QWidget):
    """Collapsible chat interface for AI assistance."""

    message_sent = pyqtSignal(str)
    collapsed_changed = pyqtSignal(bool)  # Emits True when collapsed

    def __init__(self):
        """Initialize chat widget."""
        super().__init__()
        self.setObjectName("chatWidget")
        self._collapsed = False
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

        # Subtitle
        subtitle = QLabel("Your creative writing companion")
        subtitle.setProperty("muted", True)
        subtitle.setStyleSheet("font-size: 11px; color: #a3a3a3;")
        content_layout.addWidget(subtitle)

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
