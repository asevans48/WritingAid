"""AI Debug Panel — shows the full context sent to the AI for each interaction.

Displays system prompt, RAG results, character context, worldbuilding context,
token estimates, and timing for each AI chat turn. Toggled via Settings or
a keyboard shortcut.
"""

from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QTabWidget, QPushButton, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QSplitter
)
from PyQt6.QtCore import Qt
from typing import Optional
from datetime import datetime


class AIDebugPanel(QDockWidget):
    """Dockable panel showing AI debug information."""

    def __init__(self, parent=None):
        super().__init__("AI Debug", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._turns: list = []
        self._init_ui()

    def _init_ui(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel("<b>AI Debug</b>"))
        header.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        clear_btn.clicked.connect(self._clear)
        header.addWidget(clear_btn)

        self.turn_label = QLabel("No turns yet")
        self.turn_label.setStyleSheet("font-size: 11px; color: #6b7280;")
        header.addWidget(self.turn_label)
        layout.addLayout(header)

        # Tabs for different views
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabBar::tab { font-size: 11px; padding: 4px 8px; }")

        # Turn list
        self.turn_list = QTreeWidget()
        self.turn_list.setHeaderLabels(["Time", "Mode", "User Message", "Tokens (est)"])
        self.turn_list.setRootIsDecorated(False)
        self.turn_list.setAlternatingRowColors(True)
        h = self.turn_list.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.turn_list.currentItemChanged.connect(self._on_turn_selected)
        self.tabs.addTab(self.turn_list, "Turns")

        # System prompt view
        self.system_prompt_view = QTextEdit()
        self.system_prompt_view.setReadOnly(True)
        self.system_prompt_view.setStyleSheet("font-family: monospace; font-size: 11px;")
        self.tabs.addTab(self.system_prompt_view, "System Prompt")

        # Context view (what was sent as project context)
        self.context_view = QTextEdit()
        self.context_view.setReadOnly(True)
        self.context_view.setStyleSheet("font-family: monospace; font-size: 11px;")
        self.tabs.addTab(self.context_view, "Context")

        # RAG results view
        self.rag_view = QTextEdit()
        self.rag_view.setReadOnly(True)
        self.rag_view.setStyleSheet("font-family: monospace; font-size: 11px;")
        self.tabs.addTab(self.rag_view, "RAG Results")

        # Response view
        self.response_view = QTextEdit()
        self.response_view.setReadOnly(True)
        self.response_view.setStyleSheet("font-family: monospace; font-size: 11px;")
        self.tabs.addTab(self.response_view, "Response")

        layout.addWidget(self.tabs)
        self.setWidget(widget)

    def log_turn(self, mode: str, user_message: str, system_prompt: str,
                 context: dict, response: str, elapsed_ms: int = 0):
        """Log an AI interaction turn with all its context.

        Args:
            mode: Chat mode (general, chapter_focus, writer)
            user_message: The user's message
            system_prompt: Full system prompt sent to the LLM
            context: The context dict from _build_chat_context
            response: The AI's response
            elapsed_ms: Time taken in milliseconds
        """
        # Estimate tokens (rough: 1 token ≈ 4 chars)
        prompt_chars = len(system_prompt) + len(user_message)
        response_chars = len(response)
        est_prompt_tokens = prompt_chars // 4
        est_response_tokens = response_chars // 4
        est_total = est_prompt_tokens + est_response_tokens

        turn = {
            "time": datetime.now(),
            "mode": mode,
            "user_message": user_message,
            "system_prompt": system_prompt,
            "context": dict(context) if context else {},
            "response": response,
            "elapsed_ms": elapsed_ms,
            "est_prompt_tokens": est_prompt_tokens,
            "est_response_tokens": est_response_tokens,
            "est_total_tokens": est_total,
        }
        self._turns.append(turn)

        # Add to turn list
        item = QTreeWidgetItem()
        item.setText(0, turn["time"].strftime("%H:%M:%S"))
        item.setText(1, mode)
        item.setText(2, user_message[:80] + ("..." if len(user_message) > 80 else ""))
        item.setText(3, f"~{est_total:,}")
        item.setData(0, Qt.ItemDataRole.UserRole, len(self._turns) - 1)
        self.turn_list.addTopLevelItem(item)
        self.turn_list.setCurrentItem(item)

        self.turn_label.setText(f"{len(self._turns)} turns")

    def _on_turn_selected(self, current, previous):
        """Show details for the selected turn."""
        if not current:
            return
        idx = current.data(0, Qt.ItemDataRole.UserRole)
        if idx is None or idx >= len(self._turns):
            return

        turn = self._turns[idx]

        # System prompt
        self.system_prompt_view.setPlainText(turn["system_prompt"])

        # Context breakdown
        ctx = turn["context"]
        parts = []
        parts.append(f"Mode: {turn['mode']}")
        parts.append(f"Elapsed: {turn['elapsed_ms']}ms")
        parts.append(f"Est. prompt tokens: ~{turn['est_prompt_tokens']:,}")
        parts.append(f"Est. response tokens: ~{turn['est_response_tokens']:,}")
        parts.append(f"Est. total tokens: ~{turn['est_total_tokens']:,}")
        parts.append("")

        for key in sorted(ctx.keys()):
            val = ctx[key]
            if isinstance(val, str):
                preview = val[:500] + ("..." if len(val) > 500 else "")
                parts.append(f"--- {key} ({len(val)} chars) ---")
                parts.append(preview)
                parts.append("")
            elif isinstance(val, list):
                parts.append(f"--- {key} ({len(val)} items) ---")
                parts.append(str(val[:5]))
                parts.append("")
            else:
                parts.append(f"--- {key} ---")
                parts.append(str(val))
                parts.append("")

        self.context_view.setPlainText("\n".join(parts))

        # RAG results
        rag = ctx.get("rag_context", "") or ctx.get("semantic_context", "")
        if rag:
            self.rag_view.setPlainText(rag)
        else:
            self.rag_view.setPlainText("(no RAG context for this turn)")

        # Response
        self.response_view.setPlainText(turn["response"])

    def _clear(self):
        """Clear all logged turns."""
        self._turns.clear()
        self.turn_list.clear()
        self.system_prompt_view.clear()
        self.context_view.clear()
        self.rag_view.clear()
        self.response_view.clear()
        self.turn_label.setText("No turns yet")
