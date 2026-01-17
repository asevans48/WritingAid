"""Chapter Planner Widget - Plan chapters with AI assistance."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QSplitter, QGroupBox, QComboBox, QMessageBox,
    QProgressBar, QScrollArea, QFrame
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont, QTextCursor
from typing import Optional, Callable
import threading


class ChapterPlannerWidget(QWidget):
    """Widget for planning chapters with AI assistance."""

    plan_changed = pyqtSignal()  # Emitted when plan content changes
    check_requested = pyqtSignal(str, str)  # plan, chapter_content - for consistency check

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ai_handler: Optional[Callable] = None
        self._context_provider: Optional[Callable] = None
        self._chapter_content_provider: Optional[Callable] = None
        self._is_processing = False
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Header
        header = QLabel("Chapter Plan")
        header.setStyleSheet("font-size: 14px; font-weight: 600; color: #1a1a1a; padding: 4px;")
        layout.addWidget(header)

        # Info label
        info_label = QLabel("Plan your chapter here. This is NOT exported with your manuscript.")
        info_label.setStyleSheet("color: #666; font-size: 11px; font-style: italic; padding: 2px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Main splitter - plan editor on top, AI chat on bottom
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Plan editor section
        plan_group = QGroupBox("Plan / Outline")
        plan_layout = QVBoxLayout(plan_group)

        self.plan_editor = QTextEdit()
        self.plan_editor.setPlaceholderText(
            "Write your chapter plan here...\n\n"
            "Suggested sections:\n"
            "- Scene goals\n"
            "- Characters involved\n"
            "- Key events / beats\n"
            "- Emotional arc\n"
            "- Foreshadowing / callbacks\n"
            "- Notes for revision"
        )
        self.plan_editor.setFont(QFont("Segoe UI", 11))
        self.plan_editor.textChanged.connect(self._on_plan_changed)
        plan_layout.addWidget(self.plan_editor)

        # Plan action buttons
        plan_buttons = QHBoxLayout()

        self.generate_plan_btn = QPushButton("Generate Plan with AI")
        self.generate_plan_btn.setToolTip("Use AI to generate a chapter plan based on your plot and worldbuilding")
        self.generate_plan_btn.clicked.connect(self._generate_plan)
        plan_buttons.addWidget(self.generate_plan_btn)

        self.expand_plan_btn = QPushButton("Expand Plan")
        self.expand_plan_btn.setToolTip("Ask AI to expand and add detail to your current plan")
        self.expand_plan_btn.clicked.connect(self._expand_plan)
        plan_buttons.addWidget(self.expand_plan_btn)

        plan_buttons.addStretch()
        plan_layout.addLayout(plan_buttons)

        splitter.addWidget(plan_group)

        # AI Chat section for plan assistance
        chat_group = QGroupBox("AI Plan Assistant")
        chat_layout = QVBoxLayout(chat_group)

        # Model selector
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["Claude (Anthropic)", "GPT-4 (OpenAI)", "Gemini (Google)", "Local SLM"])
        self.model_combo.setToolTip("Select which AI model to use for planning assistance")
        model_layout.addWidget(self.model_combo)
        model_layout.addStretch()
        chat_layout.addLayout(model_layout)

        # Chat history
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setFont(QFont("Segoe UI", 10))
        self.chat_history.setStyleSheet("background-color: #f8f9fa;")
        self.chat_history.setPlaceholderText("AI responses will appear here...")
        chat_layout.addWidget(self.chat_history)

        # Chat input
        input_layout = QHBoxLayout()
        self.chat_input = QTextEdit()
        self.chat_input.setPlaceholderText("Ask AI about your chapter plan...")
        self.chat_input.setMaximumHeight(80)
        self.chat_input.setFont(QFont("Segoe UI", 10))
        input_layout.addWidget(self.chat_input)

        # Send button
        send_btn_layout = QVBoxLayout()
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send_chat_message)
        self.send_btn.setMinimumHeight(40)
        send_btn_layout.addWidget(self.send_btn)
        send_btn_layout.addStretch()
        input_layout.addLayout(send_btn_layout)

        chat_layout.addLayout(input_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximum(0)  # Indeterminate
        chat_layout.addWidget(self.progress_bar)

        splitter.addWidget(chat_group)

        # Set splitter sizes (60% plan, 40% chat)
        splitter.setSizes([300, 200])

        layout.addWidget(splitter)

        # Consistency check section
        check_frame = QFrame()
        check_frame.setStyleSheet("background-color: #fff3cd; border-radius: 4px; padding: 8px;")
        check_layout = QHBoxLayout(check_frame)
        check_layout.setContentsMargins(8, 8, 8, 8)

        check_label = QLabel("Verify your chapter follows the plan:")
        check_layout.addWidget(check_label)

        self.check_plan_btn = QPushButton("Check Plan Consistency")
        self.check_plan_btn.setToolTip("Ask AI to verify if your chapter content follows the plan")
        self.check_plan_btn.clicked.connect(self._check_plan_consistency)
        self.check_plan_btn.setStyleSheet("background-color: #ffc107; color: black;")
        check_layout.addWidget(self.check_plan_btn)

        check_layout.addStretch()
        layout.addWidget(check_frame)

    def _on_plan_changed(self):
        """Handle plan text changes."""
        self.plan_changed.emit()

    def set_plan(self, plan: str):
        """Set the plan content."""
        self.plan_editor.setPlainText(plan)

    def get_plan(self) -> str:
        """Get the current plan content."""
        return self.plan_editor.toPlainText()

    def set_ai_handler(self, handler: Callable):
        """Set the AI handler function for chat and generation.

        Handler signature: handler(prompt: str, context: dict, callback: Callable[[str], None])
        """
        self._ai_handler = handler

    def set_context_provider(self, provider: Callable):
        """Set function that provides plot/worldbuilding context.

        Provider signature: provider() -> dict with keys: 'plot', 'worldbuilding', 'characters', 'chapter_title'
        """
        self._context_provider = provider

    def set_chapter_content_provider(self, provider: Callable):
        """Set function that provides current chapter content.

        Provider signature: provider() -> str
        """
        self._chapter_content_provider = provider

    def _get_context(self) -> dict:
        """Get the current context for AI requests."""
        if self._context_provider:
            return self._context_provider()
        return {}

    def _get_chapter_content(self) -> str:
        """Get the current chapter content."""
        if self._chapter_content_provider:
            return self._chapter_content_provider()
        return ""

    def _append_to_chat(self, role: str, message: str):
        """Append a message to the chat history."""
        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        if role == "user":
            cursor.insertHtml(f'<p style="color: #0066cc;"><b>You:</b> {message}</p>')
        elif role == "assistant":
            cursor.insertHtml(f'<p style="color: #006600;"><b>AI:</b> {message}</p>')
        elif role == "system":
            cursor.insertHtml(f'<p style="color: #666666;"><i>{message}</i></p>')
        elif role == "error":
            cursor.insertHtml(f'<p style="color: #cc0000;"><b>Error:</b> {message}</p>')

        cursor.insertHtml("<br>")
        self.chat_history.setTextCursor(cursor)
        self.chat_history.ensureCursorVisible()

    def _set_processing(self, is_processing: bool):
        """Set processing state."""
        self._is_processing = is_processing
        self.progress_bar.setVisible(is_processing)
        self.send_btn.setEnabled(not is_processing)
        self.generate_plan_btn.setEnabled(not is_processing)
        self.expand_plan_btn.setEnabled(not is_processing)
        self.check_plan_btn.setEnabled(not is_processing)

    def _generate_plan(self):
        """Generate a chapter plan using AI."""
        if not self._ai_handler:
            QMessageBox.warning(self, "AI Not Available", "AI handler not configured.")
            return

        context = self._get_context()
        if not context:
            QMessageBox.warning(
                self, "No Context",
                "No plot or worldbuilding context available. Please add some context to your project first."
            )
            return

        chapter_title = context.get('chapter_title', 'this chapter')

        prompt = f"""Generate a detailed chapter plan for "{chapter_title}".

Based on the plot outline, worldbuilding, and characters provided, create a comprehensive plan that includes:

1. **Scene Goals**: What should this chapter accomplish in the story?
2. **Characters**: Which characters appear and what are their motivations?
3. **Key Events/Beats**: List the main events in order
4. **Emotional Arc**: How should the reader feel throughout?
5. **Foreshadowing/Callbacks**: Any setup or payoff needed?
6. **Setting Details**: Important worldbuilding elements to include
7. **Dialogue Notes**: Key conversations or reveals
8. **Revision Notes**: Things to watch for during editing

Make the plan specific and actionable."""

        self._append_to_chat("system", f"Generating plan for {chapter_title}...")
        self._set_processing(True)

        def on_response(response: str):
            self._set_processing(False)
            if response:
                self.plan_editor.setPlainText(response)
                self._append_to_chat("assistant", "Plan generated and added to the editor.")
            else:
                self._append_to_chat("error", "Failed to generate plan.")

        self._run_ai_request(prompt, context, on_response)

    def _expand_plan(self):
        """Expand the current plan with more detail."""
        if not self._ai_handler:
            QMessageBox.warning(self, "AI Not Available", "AI handler not configured.")
            return

        current_plan = self.get_plan()
        if not current_plan.strip():
            QMessageBox.warning(self, "No Plan", "Please write a basic plan first before expanding.")
            return

        context = self._get_context()
        context['current_plan'] = current_plan

        prompt = f"""Expand and add more detail to this chapter plan:

{current_plan}

Add more specific details, scene-by-scene breakdowns, dialogue suggestions, and sensory details to include. Keep the same structure but make it more comprehensive and actionable."""

        self._append_to_chat("system", "Expanding plan...")
        self._set_processing(True)

        def on_response(response: str):
            self._set_processing(False)
            if response:
                self.plan_editor.setPlainText(response)
                self._append_to_chat("assistant", "Plan expanded.")
            else:
                self._append_to_chat("error", "Failed to expand plan.")

        self._run_ai_request(prompt, context, on_response)

    def _send_chat_message(self):
        """Send a chat message to the AI."""
        if not self._ai_handler:
            QMessageBox.warning(self, "AI Not Available", "AI handler not configured.")
            return

        message = self.chat_input.toPlainText().strip()
        if not message:
            return

        self.chat_input.clear()
        self._append_to_chat("user", message)

        context = self._get_context()
        context['current_plan'] = self.get_plan()
        context['chapter_content'] = self._get_chapter_content()

        prompt = f"""The user is working on a chapter plan and has a question:

{message}

Help them with their chapter planning. You have access to their current plan, chapter content, plot, worldbuilding, and character information."""

        self._set_processing(True)

        def on_response(response: str):
            self._set_processing(False)
            if response:
                self._append_to_chat("assistant", response)
            else:
                self._append_to_chat("error", "Failed to get response.")

        self._run_ai_request(prompt, context, on_response)

    def _check_plan_consistency(self):
        """Check if the chapter content follows the plan."""
        if not self._ai_handler:
            QMessageBox.warning(self, "AI Not Available", "AI handler not configured.")
            return

        plan = self.get_plan()
        if not plan.strip():
            QMessageBox.warning(self, "No Plan", "Please create a plan first.")
            return

        chapter_content = self._get_chapter_content()
        if not chapter_content.strip():
            QMessageBox.warning(self, "No Content", "The chapter has no content to check.")
            return

        context = self._get_context()
        context['current_plan'] = plan
        context['chapter_content'] = chapter_content

        prompt = f"""Analyze how well the chapter content follows the chapter plan.

CHAPTER PLAN:
{plan}

CHAPTER CONTENT:
{chapter_content[:8000]}  # Limit content length

Please provide:
1. **Plan Elements Met**: Which parts of the plan are successfully implemented?
2. **Plan Elements Missing**: Which parts of the plan are not yet in the chapter?
3. **Unexpected Additions**: Any content that wasn't in the plan (good or concerning)?
4. **Consistency Issues**: Any contradictions between plan and content?
5. **Recommendations**: Specific suggestions for alignment

Be specific and constructive."""

        self._append_to_chat("system", "Checking plan consistency...")
        self._set_processing(True)

        def on_response(response: str):
            self._set_processing(False)
            if response:
                self._append_to_chat("assistant", response)
                self.check_requested.emit(plan, chapter_content)
            else:
                self._append_to_chat("error", "Failed to check consistency.")

        self._run_ai_request(prompt, context, on_response)

    def _run_ai_request(self, prompt: str, context: dict, callback: Callable):
        """Run an AI request in a background thread."""
        def run():
            try:
                # Build the full context string
                context_parts = []
                if context.get('plot'):
                    context_parts.append(f"PLOT OUTLINE:\n{context['plot']}")
                if context.get('worldbuilding'):
                    context_parts.append(f"WORLDBUILDING:\n{context['worldbuilding']}")
                if context.get('characters'):
                    context_parts.append(f"CHARACTERS:\n{context['characters']}")
                if context.get('current_plan'):
                    context_parts.append(f"CURRENT PLAN:\n{context['current_plan']}")

                full_context = "\n\n".join(context_parts)
                full_prompt = f"{full_context}\n\n---\n\n{prompt}" if full_context else prompt

                # Call the AI handler
                result = self._ai_handler(full_prompt, self.model_combo.currentText())

                # Schedule callback on main thread
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, lambda: callback(result))

            except Exception as e:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, lambda: callback(None))
                print(f"AI request error: {e}")

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def clear_chat(self):
        """Clear the chat history."""
        self.chat_history.clear()
