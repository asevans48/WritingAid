"""Shared "what is the AI about to see?" preview dialog.

Two surfaces use this:
  * the plot tab's Discuss-with-AI ``Preview context`` button
  * the General Assistant chat panel's ``Preview context`` button

Both want the same thing: open a dialog, show the system prompt and
user-block as plain text the user can read + copy, and ideally show
which RAG-selected items are about to be cited so the user can sanity
check the model's anchors before clicking Ask.

The dialog itself is dumb — it just takes pre-built strings. Each
caller assembles its own context (since the assembly differs between
plot mode and the chat panel) and hands the result here.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QTabWidget, QWidget, QApplication,
)


def show_context_preview(parent,
                         *,
                         title: str = "AI context preview",
                         intro: str = "",
                         system_prompt: str = "",
                         user_block: str = "",
                         rag_summary: str = "",
                         conversation_history: Optional[list] = None) -> None:
    """Open a modal showing exactly what the AI is about to receive.

    Each pane is a tab so the user can flip between system prompt,
    the assembled user-block (the actual prompt body, including the
    RAG-focused subset), and an optional RAG summary that breaks
    down which items per source-type were selected for this
    question. ``conversation_history`` is rendered as a fourth tab
    when supplied so the user sees what previous turns the model
    will see.

    All panes are read-only QTextEdits with monospaced font so
    long blocks wrap naturally and the user can select + copy any
    section into a bug report or a note.
    """
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(820, 620)

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(8, 8, 8, 8)

    if intro:
        intro_label = QLabel(intro)
        intro_label.setWordWrap(True)
        intro_label.setStyleSheet(
            "color:#374151;font-size:11px;padding:6px;"
            "background:#f3f4f6;border-radius:4px;")
        layout.addWidget(intro_label)

    tabs = QTabWidget()

    def _make_pane(text: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        body = QTextEdit()
        body.setReadOnly(True)
        body.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        body.setPlainText(text or "(empty)")
        # Monospaced so the structure (separators, bullet lists)
        # stays readable.
        body.setStyleSheet(
            "QTextEdit { font-family: 'Menlo', 'Consolas', "
            "monospace; font-size: 11px; }")
        v.addWidget(body)
        return w

    # Order: User block first (this is what changes most + what the
    # user wants to verify), system prompt second (slow to change),
    # RAG breakdown third, conversation history fourth.
    user_pane = _make_pane(user_block)
    user_chars = len(user_block) if user_block else 0
    tabs.addTab(user_pane,
                f"📝 User block ({user_chars:,} chars)")

    sys_pane = _make_pane(system_prompt)
    sys_chars = len(system_prompt) if system_prompt else 0
    tabs.addTab(sys_pane,
                f"⚙️ System prompt ({sys_chars:,} chars)")

    if rag_summary:
        rag_pane = _make_pane(rag_summary)
        tabs.addTab(rag_pane, "🔍 RAG breakdown")

    if conversation_history:
        rendered_turns = []
        for i, turn in enumerate(conversation_history, 1):
            role = turn.get('role', '?').upper() if isinstance(
                turn, dict) else '?'
            content = (turn.get('content', '')
                       if isinstance(turn, dict) else str(turn))
            rendered_turns.append(
                f"--- Turn {i} ({role}) ---\n{content}")
        tabs.addTab(
            _make_pane("\n\n".join(rendered_turns)),
            f"💬 History ({len(conversation_history)} turns)")

    layout.addWidget(tabs, stretch=1)

    # Footer: total-size summary + Copy-all + Close.
    total_chars = user_chars + sys_chars + len(rag_summary or "")
    footer = QHBoxLayout()
    size_label = QLabel(
        f"<span style='color:#6b7280;font-size:11px;'>"
        f"Total payload: <b>{total_chars:,}</b> chars across all "
        f"tabs.</span>")
    footer.addWidget(size_label)
    footer.addStretch()

    copy_btn = QPushButton("📋 Copy current tab")
    copy_btn.setStyleSheet(
        "QPushButton { padding: 4px 12px; font-size: 11px; "
        " border: 1px solid #d1d5db; border-radius: 4px; "
        " background: white; color: #374151; }"
        "QPushButton:hover { border-color: #6366f1; "
        " color: #6366f1; }")

    def _copy_current_tab():
        current = tabs.currentWidget()
        if current is None:
            return
        # Each pane is a QWidget wrapping a QTextEdit
        edit = current.findChild(QTextEdit)
        if edit is None:
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(edit.toPlainText())
        copy_btn.setText("✓ Copied")
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(
            1500,
            lambda: copy_btn.setText("📋 Copy current tab"))

    copy_btn.clicked.connect(_copy_current_tab)
    footer.addWidget(copy_btn)

    close_btn = QPushButton("✕ Close")
    close_btn.setStyleSheet(
        "QPushButton { padding: 4px 14px; font-size: 11px; "
        " border: 1px solid #d1d5db; border-radius: 4px; "
        " background: white; color: #374151; }"
        "QPushButton:hover { border-color: #6b7280; }")
    close_btn.clicked.connect(dlg.accept)
    footer.addWidget(close_btn)
    layout.addLayout(footer)

    dlg.exec()


def build_rag_summary(ctx: dict) -> str:
    """Render the RAG-selected blocks (focused per source type) into a
    human-readable summary.

    ``ctx`` is the dict produced by main_window's
    ``_build_chat_context`` (or the plot-AI variant). When none of
    the ``rag_focused_*`` keys are set, returns an empty string so
    the caller can skip the RAG tab.
    """
    rag_keys = (
        ('rag_focused_characters', 'Characters'),
        ('rag_focused_worldbuilding', 'Worldbuilding'),
        ('rag_focused_subplots', 'Subplots'),
        ('rag_focused_chapters', 'Chapter passages'),
    )
    sections = []
    for key, label in rag_keys:
        body = ctx.get(key)
        if not body:
            continue
        sections.append(
            f"=== {label} (top results for the current question) "
            f"===\n{body}")
    # Mixed cross-type RAG (the legacy single-string ``rag_context``)
    # is informational too — show it under its own header.
    mixed = ctx.get('rag_context')
    if mixed:
        sections.append(
            f"=== Mixed RAG (cross-type, encyclopedia included) "
            f"===\n{mixed}")
    if not sections:
        return ""
    return "\n\n".join(sections)
