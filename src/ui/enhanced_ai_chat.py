"""Enhanced AI chat widget with agent suite integration."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QPushButton, QLabel, QFrame, QComboBox, QCheckBox, QGroupBox,
    QMessageBox, QProgressBar
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread
from PyQt6.QtGui import QTextCursor
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.project import WriterProject
    from src.ai.agent_suite import AgentSuite


class AIWorker(QThread):
    """Worker thread for AI operations to keep UI responsive."""

    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, agent_suite: 'AgentSuite', message: str):
        super().__init__()
        self.agent_suite = agent_suite
        self.message = message

    def run(self):
        """Execute AI request in background."""
        try:
            response = self.agent_suite.chat(self.message)
            self.response_ready.emit(response)
        except Exception as e:
            self.error_occurred.emit(str(e))


class EnhancedAIChatWidget(QWidget):
    """Enhanced AI chat widget with agent suite integration.

    Features:
    - Conversational interface for worldbuilding
    - Cost tracking and display
    - Local/cloud model selection
    - Mode selection for specialized agents
    """

    def __init__(self, project: Optional['WriterProject'] = None):
        super().__init__()
        self.project = project
        self.agent_suite: Optional['AgentSuite'] = None
        self.worker: Optional[AIWorker] = None
        self._init_ui()

    def _init_ui(self):
        """Initialize user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)

        title = QLabel("🤖 AI Agent Suite")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #6366f1;")
        header_layout.addWidget(title)

        subtitle = QLabel("Cost-effective worldbuilding assistant")
        subtitle.setStyleSheet("font-size: 11px; color: #a3a3a3;")
        header_layout.addWidget(subtitle)

        layout.addLayout(header_layout)

        # Configuration section
        config_group = QGroupBox("Configuration")
        config_layout = QVBoxLayout()

        # Local model toggle
        self.local_model_check = QCheckBox("Use Local Model (Cost Savings)")
        self.local_model_check.setToolTip(
            "Enable local SLM for simple tasks to reduce cloud API costs.\n"
            "Requires ~4GB RAM and initial model download."
        )
        self.local_model_check.stateChanged.connect(self._on_config_changed)
        config_layout.addWidget(self.local_model_check)

        # Model selection
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Local Model:"))
        self.local_model_combo = QComboBox()
        self.local_model_combo.addItems([
            "microsoft/Phi-3.5-mini-instruct",
            "Qwen/Qwen2.5-3B-Instruct",
            "meta-llama/Llama-3.2-3B-Instruct"
        ])
        self.local_model_combo.setEnabled(False)
        self.local_model_check.toggled.connect(self.local_model_combo.setEnabled)
        model_layout.addWidget(self.local_model_combo)
        config_layout.addLayout(model_layout)

        config_group.setLayout(config_layout)
        layout.addWidget(config_group)

        # Status bar
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-size: 11px; color: #10b981;")
        status_layout.addWidget(self.status_label)

        status_layout.addStretch()

        self.cost_label = QLabel("Session Cost: $0.0000")
        self.cost_label.setStyleSheet("font-size: 11px; color: #6b7280;")
        status_layout.addWidget(self.cost_label)

        layout.addLayout(status_layout)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #e5e7eb; max-height: 1px;")
        layout.addWidget(separator)

        # Chat history
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setPlaceholderText(
            "Welcome! I can help you with:\n"
            "• Creating characters, factions, and places\n"
            "• Analyzing chapters for improvements\n"
            "• Worldbuilding recommendations\n"
            "• Consistency checking\n\n"
            "Just start chatting naturally!"
        )
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

        # Progress bar for AI processing
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #e5e7eb;
                border-radius: 4px;
                text-align: center;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #6366f1;
            }
        """)
        layout.addWidget(self.progress_bar)

        # Input area
        input_layout = QHBoxLayout()

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
        input_layout.addWidget(self.input_field)

        self.send_button = QPushButton("Send")
        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: 500;
                font-size: 13px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            QPushButton:pressed {
                background-color: #4338ca;
            }
            QPushButton:disabled {
                background-color: #9ca3af;
            }
        """)
        self.send_button.clicked.connect(self._send_message)
        input_layout.addWidget(self.send_button)

        layout.addLayout(input_layout)

        # Action buttons
        action_layout = QHBoxLayout()

        clear_btn = QPushButton("Clear Chat")
        clear_btn.clicked.connect(self._clear_chat)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #6b7280;
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #f3f4f6;
            }
        """)
        action_layout.addWidget(clear_btn)

        export_btn = QPushButton("Export Conversation")
        export_btn.clicked.connect(self._export_conversation)
        export_btn.setStyleSheet(clear_btn.styleSheet())
        action_layout.addWidget(export_btn)

        action_layout.addStretch()

        stats_btn = QPushButton("View Cost Stats")
        stats_btn.clicked.connect(self._show_cost_stats)
        stats_btn.setStyleSheet(clear_btn.styleSheet())
        action_layout.addWidget(stats_btn)

        layout.addLayout(action_layout)

    def _on_config_changed(self):
        """Handle configuration changes."""
        # Reinitialize agent suite if already created
        if self.agent_suite:
            reply = QMessageBox.question(
                self,
                "Reinitialize Agent?",
                "Changing configuration will restart the agent and clear the conversation. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self._initialize_agent()

    def set_project(self, project: 'WriterProject'):
        """Set the project for agent context.

        Args:
            project: WriterProject to use for context
        """
        self.project = project
        if self.agent_suite:
            self.agent_suite.project = project
            self._add_system_message("Project context updated.")

    def _initialize_agent(self):
        """Initialize or reinitialize the agent suite."""
        try:
            self.status_label.setText("Initializing agent...")
            self.status_label.setStyleSheet("font-size: 11px; color: #f59e0b;")

            from src.ai.agent_suite import create_agent_suite

            use_local = self.local_model_check.isChecked()
            local_model = self.local_model_combo.currentText()

            self.agent_suite = create_agent_suite(
                project=self.project,
                use_local_model=use_local,
                local_model_id=local_model
            )

            self.status_label.setText("Agent ready")
            self.status_label.setStyleSheet("font-size: 11px; color: #10b981;")

            if use_local:
                self._add_system_message(
                    f"Agent initialized with local model: {local_model}\n"
                    "Simple tasks will use local model for cost savings."
                )
            else:
                self._add_system_message("Agent initialized in cloud-only mode.")

        except Exception as e:
            self.status_label.setText("Initialization failed")
            self.status_label.setStyleSheet("font-size: 11px; color: #ef4444;")
            QMessageBox.critical(
                self,
                "Initialization Error",
                f"Failed to initialize AI agent:\n{str(e)}\n\n"
                "Please check your AI configuration in Settings."
            )

    def _send_message(self):
        """Send user message to agent."""
        message = self.input_field.text().strip()
        if not message:
            return

        # Initialize agent if not done yet
        if not self.agent_suite:
            self._initialize_agent()
            if not self.agent_suite:
                return  # Initialization failed

        # Clear input
        self.input_field.clear()

        # Add user message to chat
        self._add_user_message(message)

        # Disable input during processing
        self.input_field.setEnabled(False)
        self.send_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Processing...")
        self.status_label.setStyleSheet("font-size: 11px; color: #f59e0b;")

        # Create worker thread for AI request
        self.worker = AIWorker(self.agent_suite, message)
        self.worker.response_ready.connect(self._on_response_ready)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _on_response_ready(self, response: str):
        """Handle AI response."""
        self._add_ai_message(response)
        self._cleanup_after_response()
        self._update_cost_display()

    def _on_error(self, error: str):
        """Handle AI error."""
        self._add_system_message(f"Error: {error}", is_error=True)
        self._cleanup_after_response()

    def _cleanup_after_response(self):
        """Re-enable UI after response."""
        self.input_field.setEnabled(True)
        self.send_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Ready")
        self.status_label.setStyleSheet("font-size: 11px; color: #10b981;")
        self.input_field.setFocus()

    def _add_user_message(self, message: str):
        """Add user message to chat history."""
        formatted = f'<div style="text-align: right; margin: 8px 0;">'
        formatted += f'<span style="background-color: #6366f1; color: white; '
        formatted += f'border-radius: 12px 12px 4px 12px; padding: 8px 12px; '
        formatted += f'display: inline-block; max-width: 70%;">{message}</span></div>'

        self.chat_history.append(formatted)
        self._scroll_to_bottom()

    def _add_ai_message(self, message: str):
        """Add AI message to chat history."""
        # Convert markdown-like formatting to HTML
        formatted_msg = message.replace('\n', '<br>')
        formatted_msg = formatted_msg.replace('**', '<strong>').replace('**', '</strong>')

        formatted = f'<div style="text-align: left; margin: 8px 0;">'
        formatted += f'<span style="background-color: white; color: #1a1a1a; '
        formatted += f'border: 1px solid #e5e7eb; border-radius: 12px 12px 12px 4px; '
        formatted += f'padding: 8px 12px; display: inline-block; max-width: 80%;">'
        formatted += f'<strong style="color: #6366f1;">AI:</strong><br>{formatted_msg}</span></div>'

        self.chat_history.append(formatted)
        self._scroll_to_bottom()

    def _add_system_message(self, message: str, is_error: bool = False):
        """Add system message to chat history."""
        color = "#ef4444" if is_error else "#6b7280"
        formatted = f'<div style="text-align: center; margin: 12px 0;">'
        formatted += f'<span style="color: {color}; font-size: 11px; font-style: italic;">'
        formatted += f'{message}</span></div>'

        self.chat_history.append(formatted)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """Scroll chat history to bottom."""
        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.chat_history.setTextCursor(cursor)

    def _update_cost_display(self):
        """Update cost display."""
        if self.agent_suite:
            cost_summary = self.agent_suite.get_cost_summary()
            total = cost_summary.get("session_total", 0.0)
            self.cost_label.setText(f"Session Cost: ${total:.4f}")

    def _clear_chat(self):
        """Clear chat history."""
        reply = QMessageBox.question(
            self,
            "Clear Chat",
            "Clear conversation history? This will also reset cost tracking.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.chat_history.clear()
            if self.agent_suite:
                self.agent_suite.reset_session()
            self._update_cost_display()
            self._add_system_message("Chat cleared.")

    def _export_conversation(self):
        """Export conversation to file."""
        if not self.agent_suite or not self.agent_suite.conversation_history:
            QMessageBox.information(
                self,
                "No Conversation",
                "No conversation to export."
            )
            return

        from PyQt6.QtWidgets import QFileDialog
        from pathlib import Path

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Conversation",
            "",
            "JSON Files (*.json)"
        )

        if file_path:
            success = self.agent_suite.export_conversation(Path(file_path))
            if success:
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Conversation exported to:\n{file_path}"
                )
            else:
                QMessageBox.critical(
                    self,
                    "Export Failed",
                    "Failed to export conversation."
                )

    def _show_cost_stats(self):
        """Show detailed cost statistics."""
        if not self.agent_suite:
            QMessageBox.information(
                self,
                "No Stats",
                "Agent not initialized yet."
            )
            return

        stats = self.agent_suite.get_cost_summary()

        msg = f"""**Session Cost Summary**

**Total Cost:** ${stats.get('session_total', 0):.4f}

**Chapter Analysis Cost:** ${stats.get('chapter_agent_cost', 0):.4f}

**Worldbuilding Agent:**
"""

        wb_stats = stats.get('worldbuilding_agent', {})
        if wb_stats:
            msg += f"""
- Total Cost: ${wb_stats.get('total_cost_usd', 0):.4f}
- Local Model Calls: {wb_stats.get('local_model_calls', 0)}
- Cloud Model Calls: {wb_stats.get('cloud_model_calls', 0)}
- Cost Savings: {wb_stats.get('cost_savings_pct', 0):.1f}%
"""
        else:
            msg += "\n- No worldbuilding operations yet"

        msg += f"""

**Configuration:**
- Local Model Enabled: {'Yes' if stats.get('local_model_enabled') else 'No'}
- Primary Provider: {stats.get('primary_provider', 'unknown')}
"""

        QMessageBox.information(self, "Cost Statistics", msg)
