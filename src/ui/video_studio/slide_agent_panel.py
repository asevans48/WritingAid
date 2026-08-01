"""In-editor slide assistant — a chat panel where the user asks for
slide changes in plain language and a (possibly small, local) LLM
applies them through the deterministic ``slide_agent`` tools.

The model only ever emits JSON tool calls; ``slide_agent`` validates
and clamps every argument, so even a 4–8B model produces safe,
production-ready edits. On each turn the panel rebuilds the system
prompt from the LIVE deck state so the model always sees the current
slides / groups.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QFrame, QLabel, QPlainTextEdit, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)

from src.video_studio.slide_agent import (
    build_agent_system_prompt, run_agent_turn,
)


class _AgentWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, llm_provider, prompt: str, system_prompt: str):
        super().__init__()
        self._llm_provider = llm_provider
        self._prompt = prompt
        self._system = system_prompt

    def run(self):
        try:
            llm = self._llm_provider() if self._llm_provider else None
            if llm is None:
                self.error.emit(
                    "No LLM configured. Set up a model in Settings.")
                return
            # Low temperature → the model sticks to the tool format.
            resp = llm.generate_text(
                prompt=self._prompt,
                system_prompt=self._system,
                temperature=0.2,
                max_tokens=1200,
            )
            self.finished.emit((resp or "").strip())
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class SlideAgentPanel(QFrame):
    """Chat surface that turns natural-language requests into deck
    edits via ``slide_agent``. Emits ``deckChanged`` after applying
    tools so the host can refresh + autosave."""

    deckChanged = pyqtSignal()

    def __init__(
        self,
        deck,
        llm_provider: Optional[Callable[[], Any]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._deck = deck
        self._llm_provider = llm_provider
        self._history: List[dict] = []
        self._worker: Optional[_AgentWorker] = None
        self._build_ui()
        self._update_enabled()

    def set_llm_provider(self, provider) -> None:
        self._llm_provider = provider
        self._update_enabled()

    # -- UI ------------------------------------------------------------
    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        intro = QLabel(
            "Ask the assistant to build or edit slides — e.g. "
            "“Add a title card 'The Chase' on dark blue, caption "
            "slide 2 'The alley' with an outline, and fade between "
            "groups.” It edits the deck directly.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#64748b; font-size:11px;")
        v.addWidget(intro)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        v.addWidget(self._log, stretch=1)
        self._input = QPlainTextEdit()
        self._input.setPlaceholderText(
            "Describe the slides / edits you want…")
        self._input.setMaximumHeight(72)
        v.addWidget(self._input)
        self._send_btn = QPushButton("Send to assistant")
        self._send_btn.clicked.connect(self._on_send)
        v.addWidget(self._send_btn)
        self._status = QLabel("")
        self._status.setStyleSheet("color:#64748b; font-size:11px;")
        v.addWidget(self._status)

    def _update_enabled(self) -> None:
        ok = self._llm_provider is not None
        self._send_btn.setEnabled(ok)
        self._input.setEnabled(ok)
        if not ok:
            self._status.setText(
                "No model configured — set one up in Settings to use "
                "the assistant.")
        else:
            self._status.setText("")

    # -- chat flow -----------------------------------------------------
    def _on_send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text or self._llm_provider is None:
            return
        self._append("You", text)
        self._input.clear()
        self._send_btn.setEnabled(False)
        self._status.setText("Thinking…")
        # Rebuild the system prompt from the LIVE deck each turn so the
        # model sees current slide / group numbers.
        system = build_agent_system_prompt(self._deck)
        # Fold a short history into the prompt so the chat feels
        # continuous without re-sending the (large) tool spec.
        hist = ""
        for m in self._history[-6:]:
            who = "User" if m["role"] == "user" else "Assistant"
            hist += f"\n{who}: {m['content']}"
        self._history.append({"role": "user", "content": text})
        prompt = (hist + f"\nUser: {text}").strip() if hist else text
        self._worker = _AgentWorker(
            self._llm_provider, prompt, system)
        self._worker.finished.connect(self._on_response)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_response(self, response: str) -> None:
        self._history.append(
            {"role": "assistant", "content": response})
        # Apply any tool calls to the deck.
        try:
            results, summary = run_agent_turn(self._deck, response)
        except Exception as exc:  # noqa: BLE001
            results, summary = [], ""
            self._append("System", f"Could not apply edits: {exc}")
        # Show the model's prose (minus any raw JSON block).
        prose = self._strip_json(response)
        if prose:
            self._append("Assistant", prose)
        if summary:
            self._append("Applied", summary)
            n_ok = sum(1 for r in results if r.get("ok"))
            self._status.setText(f"Applied {n_ok} edit(s).")
            self.deckChanged.emit()
        elif not prose:
            self._append("Assistant", response or "(no reply)")
        if not summary:
            self._status.setText("")
        self._send_btn.setEnabled(True)

    def _on_error(self, msg: str) -> None:
        self._append("System", f"Error: {msg}")
        self._send_btn.setEnabled(True)
        self._status.setText("")

    @staticmethod
    def _strip_json(text: str) -> str:
        """Remove fenced ```json blocks so the chat log shows only the
        model's sentence, not the raw tool JSON."""
        import re
        cleaned = re.sub(
            r"```(?:json)?\s*.*?```", "", text or "",
            flags=re.DOTALL | re.IGNORECASE)
        return cleaned.strip()

    def _append(self, who: str, text: str) -> None:
        colors = {
            "You": "#4f46e5", "Assistant": "#0f766e",
            "Applied": "#166534", "System": "#b91c1c"}
        color = colors.get(who, "#334155")
        safe = (text or "").replace("&", "&amp;").replace(
            "<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        self._log.append(
            f'<div style="margin:4px 0;"><b style="color:{color};">'
            f'{who}:</b> {safe}</div>')
        cur = self._log.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self._log.setTextCursor(cur)
