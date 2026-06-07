"""Embeddable conversation panel for iterative AI refinement.

Designed for use inside the scene editor and action editor dialogs.
Users chat with the AI to refine prompts, descriptions, character
details, and generation parameters. The AI has full context about the
scene/action and can apply suggestions directly to the form fields.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)


class _ConversationWorker(QThread):
    """Background LLM call for the conversation panel."""
    finished = pyqtSignal(str)  # assistant response
    error = pyqtSignal(str)

    def __init__(
        self,
        llm_provider: Callable[[], Any],
        messages: list[dict[str, str]],
        system_prompt: str,
    ):
        super().__init__()
        self._llm_provider = llm_provider
        self._messages = messages
        self._system_prompt = system_prompt

    def run(self):
        try:
            llm = self._llm_provider()
            if llm is None:
                self.error.emit("No LLM configured. Set up a model in Settings.")
                return

            # Build a single prompt from conversation history
            history_text = ""
            for msg in self._messages[:-1]:
                role = msg["role"]
                content = msg["content"]
                if role == "user":
                    history_text += f"\n\nUser: {content}"
                else:
                    history_text += f"\n\nAssistant: {content}"

            current_user_msg = self._messages[-1]["content"]
            full_prompt = history_text + f"\n\nUser: {current_user_msg}" if history_text else current_user_msg

            response = llm.generate_text(
                prompt=full_prompt,
                system_prompt=self._system_prompt,
                temperature=0.7,
                max_tokens=1500,
            )
            self.finished.emit(response.strip())
        except Exception as exc:
            self.error.emit(str(exc))


class CreativeConversationPanel(QFrame):
    """Chat panel for iterative creative refinement.

    Embed in a dialog's layout. Wire ``llm_provider`` (a callable
    returning an LLMClient) and call ``set_context()`` to provide
    scene/action details. The panel maintains multi-turn history and
    lets the user ask the AI to refine prompts, suggest changes, etc.

    Signals:
        apply_suggestion(field, value) — emitted when the AI suggests
            a concrete change and the user clicks "Apply". The host
            dialog should update its form field accordingly.
    """

    apply_suggestion = pyqtSignal(str, str)  # field_name, new_value

    def __init__(
        self,
        llm_provider: Optional[Callable[[], Any]] = None,
        context_mode: str = "scene",  # "scene" or "action"
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._llm_provider = llm_provider
        self._context_mode = context_mode
        self._context: dict[str, str] = {}
        self._messages: list[dict[str, str]] = []
        self._worker: Optional[_ConversationWorker] = None
        self._build_ui()
        self._update_enabled_state()

    def set_llm_provider(self, provider: Callable[[], Any]) -> None:
        self._llm_provider = provider
        self._update_enabled_state()

    def set_context(self, context: dict[str, str]) -> None:
        """Update the scene/action context available to the AI.

        Keys should include relevant fields like 'name', 'description',
        'prompt', 'character_details', 'setting_details', etc.
        """
        self._context = context

    def clear_history(self) -> None:
        self._messages.clear()
        self._history_edit.clear()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "CreativeConversationPanel { "
            "  background: #fafafe; border: 1px solid #e5e7eb; "
            "  border-radius: 6px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        title = QLabel("AI Chat")
        title.setStyleSheet(
            "font-weight: bold; font-size: 12px; color: #4f46e5;")
        header.addWidget(title)
        header.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(50)
        clear_btn.setStyleSheet("font-size: 10px;")
        clear_btn.clicked.connect(self.clear_history)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        # Conversation history
        self._history_edit = QTextEdit()
        self._history_edit.setReadOnly(True)
        self._history_edit.setStyleSheet(
            "QTextEdit { background: white; border: 1px solid #e5e7eb; "
            "border-radius: 4px; padding: 4px; font-size: 11px; }"
        )
        self._history_edit.setMinimumHeight(120)
        layout.addWidget(self._history_edit, stretch=1)

        # Input area
        self._input_edit = QPlainTextEdit()
        self._input_edit.setPlaceholderText(
            "Ask AI to refine the prompt, suggest improvements, "
            "adjust character descriptions…"
        )
        self._input_edit.setMaximumHeight(80)
        self._input_edit.setStyleSheet(
            "QPlainTextEdit { border: 1px solid #d1d5db; "
            "border-radius: 4px; padding: 4px; font-size: 11px; }"
        )
        layout.addWidget(self._input_edit)

        # Send row
        send_row = QHBoxLayout()
        send_row.setSpacing(4)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #6b7280; font-size: 10px;")
        send_row.addWidget(self._status_label)
        send_row.addStretch()

        self._send_btn = QPushButton("Send")
        self._send_btn.setFixedWidth(60)
        self._send_btn.setStyleSheet(
            "QPushButton { background: #4f46e5; color: white; "
            "border-radius: 4px; padding: 4px 10px; font-weight: bold; "
            "font-size: 11px; }"
            "QPushButton:hover { background: #4338ca; }"
            "QPushButton:disabled { background: #9ca3af; }"
        )
        self._send_btn.clicked.connect(self._on_send)
        send_row.addWidget(self._send_btn)

        self._apply_btn = QPushButton("Apply Last")
        self._apply_btn.setFixedWidth(72)
        self._apply_btn.setToolTip(
            "Apply the AI's last suggestion to the prompt field")
        self._apply_btn.setStyleSheet(
            "QPushButton { background: #10b981; color: white; "
            "border-radius: 4px; padding: 4px 10px; font-weight: bold; "
            "font-size: 11px; }"
            "QPushButton:hover { background: #059669; }"
            "QPushButton:disabled { background: #9ca3af; }"
        )
        self._apply_btn.clicked.connect(self._on_apply_last)
        self._apply_btn.setEnabled(False)
        send_row.addWidget(self._apply_btn)

        layout.addLayout(send_row)

    def _update_enabled_state(self):
        has_llm = self._llm_provider is not None
        self._send_btn.setEnabled(has_llm)
        self._input_edit.setEnabled(has_llm)
        if not has_llm:
            self._input_edit.setPlaceholderText(
                "No LLM configured — set up a model in Settings to chat.")

    # ------------------------------------------------------------------
    # Conversation logic
    # ------------------------------------------------------------------
    def _build_system_prompt(self) -> str:
        ctx = self._context
        mode_label = "scene" if self._context_mode == "scene" else "action beat"

        parts = [
            f"You are an AI creative director helping refine a video {mode_label}. "
            "The user is iteratively improving the generation prompt and visual direction. "
            "Be concise and specific. When suggesting changes, output the improved text "
            "directly so it can be copied into the field.\n",
            "CURRENT STATE:",
        ]

        if ctx.get("name"):
            parts.append(f"Name: {ctx['name']}")
        if ctx.get("description"):
            parts.append(f"Description: {ctx['description']}")
        if ctx.get("prompt"):
            parts.append(f"Generation prompt: {ctx['prompt']}")
        if ctx.get("character_details"):
            parts.append(f"Character details: {ctx['character_details']}")
        if ctx.get("setting_details"):
            parts.append(f"Setting details: {ctx['setting_details']}")
        if ctx.get("additional_instructions"):
            parts.append(f"Additional instructions: {ctx['additional_instructions']}")
        if ctx.get("source_prose"):
            parts.append(f"Source prose excerpt: {ctx['source_prose'][:500]}")
        if ctx.get("style"):
            parts.append(f"Visual style: {ctx['style']}")
        if ctx.get("character_refs"):
            parts.append(f"Characters in scene: {ctx['character_refs']}")

        parts.append(
            "\nRULES:\n"
            "- When suggesting a new prompt, wrap it in triple backticks.\n"
            "- Focus on VISUAL direction: lighting, camera, color, composition.\n"
            "- Maintain character consistency — always include physical descriptors.\n"
            "- Be direct. One paragraph max unless the user asks for more.\n"
            "- If the user says 'apply' or 'use that', confirm which field to update."
        )

        return "\n".join(parts)

    def _on_send(self):
        text = self._input_edit.toPlainText().strip()
        if not text or not self._llm_provider:
            return

        # Add user message
        self._messages.append({"role": "user", "content": text})
        self._append_to_history("You", text)
        self._input_edit.clear()

        # Start worker
        self._send_btn.setEnabled(False)
        self._status_label.setText("Thinking…")

        self._worker = _ConversationWorker(
            llm_provider=self._llm_provider,
            messages=self._messages,
            system_prompt=self._build_system_prompt(),
        )
        self._worker.finished.connect(self._on_response)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_response(self, response: str):
        self._messages.append({"role": "assistant", "content": response})
        self._append_to_history("AI", response)
        self._send_btn.setEnabled(True)
        self._apply_btn.setEnabled(True)
        self._status_label.setText("")

    def _on_error(self, msg: str):
        self._append_to_history("System", f"Error: {msg}")
        self._send_btn.setEnabled(True)
        self._status_label.setText("")

    def _on_apply_last(self):
        """Extract the last AI suggestion and emit apply_suggestion.

        Looks for text in triple backticks first; falls back to the
        full response. Emits with field="prompt" by default — the host
        dialog can interpret differently based on context.
        """
        if not self._messages:
            return
        # Find last assistant message
        last_ai = ""
        for msg in reversed(self._messages):
            if msg["role"] == "assistant":
                last_ai = msg["content"]
                break
        if not last_ai:
            return

        # Extract code block if present
        extracted = last_ai
        if "```" in last_ai:
            parts = last_ai.split("```")
            if len(parts) >= 3:
                extracted = parts[1].strip()
                # Remove language hint if present (e.g. ```text\n...)
                if "\n" in extracted:
                    first_line = extracted.split("\n", 1)[0].strip()
                    if len(first_line) < 15 and " " not in first_line:
                        extracted = extracted.split("\n", 1)[1]

        self.apply_suggestion.emit("prompt", extracted.strip())
        self._status_label.setText("Applied to prompt field.")

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------
    def _append_to_history(self, sender: str, text: str):
        cursor = self._history_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._history_edit.setTextCursor(cursor)

        if sender == "You":
            color = "#4f46e5"
            bg = "#eef2ff"
        elif sender == "AI":
            color = "#065f46"
            bg = "#ecfdf5"
        else:
            color = "#dc2626"
            bg = "#fef2f2"

        html = (
            f'<div style="margin: 4px 0; padding: 6px 8px; '
            f'background: {bg}; border-radius: 4px;">'
            f'<b style="color: {color};">{sender}:</b> '
            f'{_escape_html(text)}</div>'
        )
        self._history_edit.insertHtml(html)
        # Scroll to bottom
        scrollbar = self._history_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


def _escape_html(text: str) -> str:
    """Minimal HTML escape preserving backtick blocks as <pre>."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Convert triple-backtick blocks to <pre> for readability
    if "```" in text:
        parts = text.split("```")
        result_parts = []
        for i, part in enumerate(parts):
            if i % 2 == 1:
                # Inside backticks — strip leading language hint
                lines = part.strip().split("\n")
                if lines and len(lines[0]) < 15 and " " not in lines[0]:
                    part = "\n".join(lines[1:])
                else:
                    part = "\n".join(lines)
                result_parts.append(
                    f'<pre style="background: #f3f4f6; padding: 4px; '
                    f'border-radius: 3px; white-space: pre-wrap; '
                    f'font-size: 10px;">{part}</pre>')
            else:
                result_parts.append(part.replace("\n", "<br>"))
        return "".join(result_parts)
    return text.replace("\n", "<br>")
