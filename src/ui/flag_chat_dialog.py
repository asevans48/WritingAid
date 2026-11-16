"""💬 Ask about a flag or note: talk it through, get a better sentence,
or say it's deliberate — and the style sheet remembers."""

from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QTextEdit,
    QVBoxLayout,
)

SYSTEM = ("You are a candid, friendly fiction editor talking with the author about one "
          "flag on one sentence. Explain plainly, respect deliberate choices, and offer "
          "better wording only when asked or clearly useful.")


class FlagChatDialog(QDialog):
    """``category``: spelling | grammar | style | overuse | note."""

    def __init__(self, *, paragraph: str, start: int, end: int, category: str, word: str,
                 reason: str, kind: str = "", project: Any = None,
                 on_replace: Optional[Callable[[str, str], bool]] = None,
                 on_rule: Optional[Callable[[Any], None]] = None,
                 llm_factory: Optional[Callable[[], Any]] = None, parent=None):
        super().__init__(parent)
        from src.ai.word_suggest import sentence_around
        self.paragraph, self.category, self.word, self.reason = paragraph, category, word, reason
        self.kind, self.project = kind, project
        self.sentence = sentence_around(paragraph, start, end).text
        self.on_replace, self.on_rule = on_replace, on_rule
        if llm_factory is None:
            from src.ai.word_suggest import get_llm
            llm_factory = get_llm
        self.llm_factory = llm_factory
        self.turns: list = []
        self.versions: list = []
        self._chat_worker = None
        self.setWindowTitle("Ask about this")
        self.resize(640, 560)
        self._build()

    def _build(self):
        from src.ui.rewrite_chat_panel import ConversationPanel
        layout = QVBoxLayout(self)
        head = QLabel(f"<b>{self.category.title()}</b> · “{self.word[:60]}” — {self.reason}")
        head.setWordWrap(True)
        layout.addWidget(head)
        self.sentence_view = QTextEdit()
        self.sentence_view.setReadOnly(True)
        self.sentence_view.setPlainText(self.sentence)
        self.sentence_view.setMaximumHeight(70)
        layout.addWidget(self.sentence_view)
        self.chat = ConversationPanel("e.g. why is this a problem? · show me three options · "
                                      "it's deliberate, remember that")
        self.chat.message_sent.connect(self.send)
        self.chat.remember_requested.connect(self._remember_memory)
        layout.addWidget(self.chat, 1)
        self.versions_list = QListWidget()
        self.versions_list.setMaximumHeight(110)
        self.versions_list.setWordWrap(True)
        layout.addWidget(self.versions_list)
        row = QHBoxLayout()
        self.use_btn = QPushButton("Use this version")
        self.use_btn.setEnabled(False)
        self.use_btn.clicked.connect(self.use_selected)
        self.versions_list.currentRowChanged.connect(
            lambda r: self.use_btn.setEnabled(0 <= r < len(self.versions)))
        row.addWidget(self.use_btn)
        self.deliberate_btn = QPushButton("📌 It's deliberate — add to my style sheet")
        self.deliberate_btn.clicked.connect(self.mark_deliberate)
        row.addWidget(self.deliberate_btn)
        row.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        layout.addLayout(row)

    # ── conversation ────────────────────────────────────────────────

    def _context(self):
        from src.ai.story_memory import prompt_block
        from src.ai.style_sheet import prompt_block as sheet
        blocks = [("THE FLAG", f"{self.category}: “{self.word}” — {self.reason}"),
                  ("THE PARAGRAPH (the sentence is in it)", self.paragraph)]
        for block in (sheet(self.project), prompt_block(self.project, self.paragraph)):
            if block:
                head, _, body = block.partition("\n")
                blocks.append((head.rstrip(":"), body))
        return blocks

    def send(self, message: str) -> None:
        from src.ai import style_sheet as ss
        from src.ai.rewrite_chat import ChatTurn, chat_turn
        from src.ui.rewrite_chat_panel import run_turn
        self.chat.add_message("You", message)
        added = ""
        if ss.DELIBERATE_CUES.search(message):
            self.mark_deliberate(quiet=True)
            added = self.chat.status.text()
        self._note = added if "style sheet" in added else ""
        self.chat.set_busy(True, f"{self._note} · Thinking…" if self._note else "Thinking…")
        context, sentence = self._context(), self.sentence
        versions = [(v.angle, v.text) for v in self.versions]
        turns = list(self.turns)
        project = self.project

        def check(found):
            from src.ai.rewrite_quality import check_rewrite, known_names_for
            names = known_names_for(project)
            return [check_rewrite(sentence, v.text, known_names=names, focus=message)
                    for v in found]

        def turn():
            llm = self.llm_factory()
            if llm is None:
                return None
            return chat_turn(llm, system=SYSTEM, context=context, passage=sentence,
                             versions=versions, turns=turns, message=message, check=check,
                             rules="Each version replaces only this sentence; keep its point of "
                                   "view, tense and meaning.")

        self.turns.append(ChatTurn("author", message))
        run_turn(self, turn, self._on_reply)

    def _on_reply(self, result, error: str) -> None:
        from src.ai.rewrite_chat import ChatTurn
        self.chat.set_busy(False, getattr(self, "_note", ""))
        if result is None:
            self.chat.add_message("Editor", error or "Talking it through needs a local or "
                                                     "cloud model (Settings › AI). You can "
                                                     "still mark it deliberate.")
            return
        self.chat.add_message("Editor", result.reply)
        self.turns.append(ChatTurn("editor", result.reply))
        for v in result.versions:
            self.versions.insert(0, v)
            note = f"  ⚠ {'; '.join(v.notes)}" if v.notes else ""
            self.versions_list.insertItem(0, QListWidgetItem(v.text + note))
        if result.versions:
            self.versions_list.setCurrentRow(0)

    # ── actions ─────────────────────────────────────────────────────

    def use_selected(self) -> None:
        row = self.versions_list.currentRow()
        if not (0 <= row < len(self.versions)) or self.on_replace is None:
            return
        if self.on_replace(self.sentence, self.versions[row].text):
            self.accept()
        else:
            self.chat.status.setText("The paragraph changed — close this and ask again.")

    def mark_deliberate(self, _checked: bool = False, quiet: bool = False) -> None:
        from src.ai import style_sheet as ss
        if self.project is None:
            self.chat.status.setText("Open a project to use the style sheet.")
            return
        rule = ss.rule_for_flag(self.project, self.category, self.word, self.kind, self.reason)
        if rule is not None and self.on_rule is not None:
            self.on_rule(rule)
        self.chat.status.setText(f"Added to your style sheet: {rule.text}" if rule is not None
                                 else "Already in your style sheet.")

    def _remember_memory(self, text: str) -> None:
        from src.ui.rewrite_chat_panel import remember
        remember(self.chat, self.project, text, "ask")

    def done(self, code: int) -> None:
        if self._chat_worker is not None:
            try:
                self._chat_worker.done.disconnect()
            except TypeError:
                pass
        super().done(code)
