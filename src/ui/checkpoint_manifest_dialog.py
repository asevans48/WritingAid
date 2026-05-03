"""Paragraph-by-paragraph review dialog for the checkpoint feature.

Lets the user walk through every paragraph of a chapter (or
custom text) and decide whether to KEEP it as-is, REJECT it
(drop from output), EDIT it inline, or ASK AI for a rephrased
version. The accepted paragraphs are joined back together and
written into a new ManuscriptDraft so the original draft is
never touched.

This is the v1 MVP. Per-paragraph metadata (a formal
ParagraphCheckpoint model with audit trail) is deferred — for
now the accepted paragraphs become the new draft's content
directly. The dialog itself stays as a one-shot reviewer; the
reviewer's decisions don't persist across opens.
"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QFrame, QScrollArea, QWidget, QMessageBox,
    QLineEdit, QComboBox, QGroupBox, QSizePolicy, QInputDialog,
)


_KEEP = "keep"
_REJECT = "reject"
_EDIT = "edit"


class _ParagraphRow(QFrame):
    """One paragraph card inside the reviewer.

    Layout: muted source paragraph at top (read-only), an editable
    working text box below, and a button strip with Keep / Reject
    / Reset / Ask AI. The card's status (``keep`` / ``reject`` /
    ``edit``) is reflected as a coloured left border so the user
    sees the status of every paragraph at a glance while
    scrolling.
    """

    status_changed = pyqtSignal(int, str)  # (index, new_status)

    def __init__(self, index: int, source_text: str,
                 ask_ai_callback=None, parent=None):
        super().__init__(parent)
        self._index = index
        self._source_text = source_text
        self._status = _KEEP
        self._ask_ai_callback = ask_ai_callback
        self._build_ui()
        self._apply_status_style()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(4)

        head = QLabel(
            f"<b>Paragraph {self._index + 1}</b> "
            f"<span style='color:#6b7280;font-size:10px;'>"
            f"({len(self._source_text)} chars)</span>")
        outer.addWidget(head)

        # Source preview — read-only, muted background.
        src_box = QPlainTextEdit()
        src_box.setReadOnly(True)
        src_box.setPlainText(self._source_text)
        src_box.setStyleSheet(
            "background:#f9fafb;color:#4b5563;font-size:11px;"
            "border:1px solid #e5e7eb;border-radius:4px;")
        src_box.setFixedHeight(
            min(160, 30 + 18 * (self._source_text.count('\n') + 2)))
        outer.addWidget(src_box)

        # Working text — what ends up in the new draft.
        work_label = QLabel(
            "<span style='color:#6b7280;font-size:10px;'>"
            "Your version (edits go in here):</span>")
        outer.addWidget(work_label)
        self._work_box = QPlainTextEdit()
        self._work_box.setPlainText(self._source_text)
        self._work_box.setStyleSheet(
            "background:#fff;color:#1f2937;font-size:12px;"
            "border:1px solid #d1d5db;border-radius:4px;")
        self._work_box.setFixedHeight(
            min(200, 40 + 20 * (self._source_text.count('\n') + 2)))
        # Detect manual edits → flip status to "edit".
        self._work_box.textChanged.connect(self._on_work_changed)
        outer.addWidget(self._work_box)

        # Action strip.
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._keep_btn = self._mk_action_btn(
            "✓ Keep", "#16a34a", _KEEP,
            "Keep this paragraph (uses the working text exactly as "
            "shown above).")
        actions.addWidget(self._keep_btn)
        self._reject_btn = self._mk_action_btn(
            "✗ Reject", "#dc2626", _REJECT,
            "Drop this paragraph from the new draft.")
        actions.addWidget(self._reject_btn)
        reset_btn = QPushButton("↺ Reset to source")
        reset_btn.setStyleSheet(
            "QPushButton { padding:4px 10px;border-radius:4px;"
            "background:transparent;color:#6b7280;"
            "border:1px solid #d1d5db;font-size:11px; }"
            "QPushButton:hover { color:#1f2937;background:#f3f4f6; }")
        reset_btn.clicked.connect(self._reset_work_text)
        actions.addWidget(reset_btn)
        actions.addStretch()
        if self._ask_ai_callback is not None:
            ai_btn = QPushButton("🤖 Ask AI")
            ai_btn.setStyleSheet(
                "QPushButton { padding:4px 10px;border-radius:4px;"
                "background:#eef2ff;color:#4338ca;"
                "border:1px solid #c7d2fe;font-size:11px;"
                "font-weight:bold; }"
                "QPushButton:hover { background:#e0e7ff; }")
            ai_btn.setToolTip(
                "Ask the configured AI to suggest 1-2 rephrased "
                "versions of this paragraph. Pick one to replace "
                "the working text, or close the popup to keep what "
                "you had.")
            ai_btn.clicked.connect(self._on_ask_ai)
            actions.addWidget(ai_btn)
        outer.addLayout(actions)

    def _mk_action_btn(self, label: str, color: str,
                        status: str, tooltip: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setStyleSheet(
            "QPushButton { padding:4px 10px;border-radius:4px;"
            "background:#f3f4f6;color:#374151;"
            "border:1px solid #d1d5db;font-size:11px;"
            "font-weight:bold; }"
            f"QPushButton:checked {{ background:{color};"
            f" color:white;border-color:{color}; }}")
        btn.setToolTip(tooltip)
        btn.clicked.connect(lambda _=False, s=status:
                              self._set_status(s, from_button=True))
        return btn

    def _set_status(self, status: str, *, from_button: bool = False):
        if status == self._status and from_button:
            # Re-clicking the active button is a no-op (keeps the
            # checkable state stable).
            self._sync_button_states()
            return
        self._status = status
        self._sync_button_states()
        self._apply_status_style()
        self.status_changed.emit(self._index, status)

    def _sync_button_states(self):
        self._keep_btn.setChecked(self._status == _KEEP)
        self._reject_btn.setChecked(self._status == _REJECT)

    def _apply_status_style(self):
        colours = {
            _KEEP:   ("#16a34a", "#f0fdf4"),
            _REJECT: ("#dc2626", "#fef2f2"),
            _EDIT:   ("#f59e0b", "#fffbeb"),
        }
        border, bg = colours.get(self._status, ("#e5e7eb", "#fff"))
        self.setStyleSheet(
            f"_ParagraphRow {{ border:1px solid #e5e7eb;"
            f" border-left:4px solid {border};"
            f" border-radius:6px; background:{bg}; }}")

    def _on_work_changed(self):
        # Manual edit: switch to the EDIT status (visually amber)
        # unless the text matches the source exactly.
        if self._work_box.toPlainText().strip() == self._source_text.strip():
            if self._status == _EDIT:
                self._set_status(_KEEP)
        else:
            if self._status != _REJECT:
                self._set_status(_EDIT)

    def _reset_work_text(self):
        self._work_box.blockSignals(True)
        self._work_box.setPlainText(self._source_text)
        self._work_box.blockSignals(False)
        self._set_status(_KEEP)

    def _on_ask_ai(self):
        if self._ask_ai_callback is None:
            return
        try:
            suggestions = self._ask_ai_callback(self._index,
                                                 self._source_text)
        except Exception as e:
            QMessageBox.warning(
                self, "AI suggestion failed",
                f"Could not get a suggestion:\n{e}")
            return
        if not suggestions:
            QMessageBox.information(
                self, "No suggestions",
                "The AI didn't return any rephrased alternatives. "
                "It may not be configured, or the paragraph is too "
                "short to rephrase usefully.")
            return
        # Show suggestions in a simple chooser dialog.
        labels = [f"Suggestion {i + 1}: {s[:80]}{'…' if len(s) > 80 else ''}"
                  for i, s in enumerate(suggestions)]
        item, ok = QInputDialog.getItem(
            self, f"AI suggestions for paragraph {self._index + 1}",
            "Pick a rephrased version (replaces the working text):",
            labels, 0, False)
        if not ok:
            return
        idx = labels.index(item)
        chosen = suggestions[idx]
        self._work_box.blockSignals(True)
        self._work_box.setPlainText(chosen)
        self._work_box.blockSignals(False)
        # Mark as edit since the text differs from source now.
        self._set_status(_EDIT)

    # ── Public accessors ─────────────────────────────────────

    @property
    def status(self) -> str:
        return self._status

    @property
    def working_text(self) -> str:
        return self._work_box.toPlainText().strip()


class CheckpointManifestDialog(QDialog):
    """Paragraph-by-paragraph reviewer that emits a new draft.

    Constructor takes the source text (a chapter's content, or
    arbitrary prose) and an optional ``agent_suite`` for the
    Ask-AI button. On Accept, the dialog joins all kept/edited
    paragraphs into a single string and exposes it via
    :meth:`accepted_text`. The caller is responsible for creating
    the actual ManuscriptDraft from that string — this dialog is
    project-model-agnostic so it can also be used in lighter
    contexts (e.g. one-off review of pasted prose).
    """

    def __init__(self, source_text: str, *,
                 agent_suite=None,
                 source_label: str = "",
                 genre: str = "",
                 parent=None):
        super().__init__(parent)
        from src.utils.paragraphs import split_paragraphs
        self._source_text = source_text
        self._paragraphs: List[str] = split_paragraphs(source_text)
        self._agent_suite = agent_suite
        self._genre = genre
        self._source_label = source_label
        self._rows: List[_ParagraphRow] = []
        self._accepted_text: Optional[str] = None
        self._draft_name = ""
        self._draft_description = ""

        self.setWindowTitle(
            f"Checkpoint Review — {source_label}"
            if source_label else "Checkpoint Review")
        self.setMinimumSize(820, 640)
        self.resize(960, 720)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)

        title = QLabel(
            "<b>Paragraph-by-paragraph review</b>")
        f = title.font(); f.setPointSize(13); title.setFont(f)
        outer.addWidget(title)
        intro = QLabel(
            "Walk each paragraph and choose <b>Keep</b>, "
            "<b>Reject</b>, or edit the working text directly. "
            "Click <b>🤖 Ask AI</b> to get rephrased alternatives "
            "you can drop in. When you're done, save the result "
            "as a new draft — your original is left untouched.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#374151;font-size:12px;padding-bottom:4px;")
        outer.addWidget(intro)

        # Live counter strip — updates as the user toggles statuses.
        self._counter_label = QLabel("")
        self._counter_label.setStyleSheet(
            "background:#f3f4f6;border-radius:4px;padding:6px 10px;"
            "color:#374151;font-size:11px;")
        outer.addWidget(self._counter_label)

        # Scrollable paragraph list.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_inner = QWidget()
        scroll_lay = QVBoxLayout(scroll_inner)
        scroll_lay.setContentsMargins(0, 0, 6, 0)
        scroll_lay.setSpacing(8)

        if not self._paragraphs:
            empty = QLabel(
                "<i>(no paragraphs detected — source text is empty "
                "or whitespace-only)</i>")
            empty.setStyleSheet("color:#6b7280;padding:20px;")
            scroll_lay.addWidget(empty)
        else:
            ai_cb = (self._on_ask_ai
                     if self._agent_suite is not None else None)
            for i, para in enumerate(self._paragraphs):
                row = _ParagraphRow(
                    i, para,
                    ask_ai_callback=ai_cb,
                    parent=self)
                row.status_changed.connect(self._refresh_counter)
                self._rows.append(row)
                scroll_lay.addWidget(row)
            scroll_lay.addStretch()
        scroll.setWidget(scroll_inner)
        outer.addWidget(scroll, 1)

        # Save / Cancel row.
        actions = QHBoxLayout()
        actions.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)
        self._save_btn = QPushButton("✓ Save as new draft…")
        self._save_btn.setStyleSheet(
            "QPushButton { background-color:#10b981;color:white;"
            " padding:6px 14px;border-radius:5px;font-weight:bold; }"
            "QPushButton:hover { background-color:#059669; }"
            "QPushButton:disabled { background-color:#86efac; }")
        self._save_btn.clicked.connect(self._on_save)
        actions.addWidget(self._save_btn)
        outer.addLayout(actions)

        self._refresh_counter()

    def _on_ask_ai(self, index: int, paragraph: str) -> List[str]:
        """Bridge the row's Ask-AI button to AgentSuite. Returns
        a list of rephrased paragraphs (possibly empty)."""
        if self._agent_suite is None:
            return []
        before = self._paragraphs[index - 1] if index > 0 else ""
        after = (self._paragraphs[index + 1]
                 if index + 1 < len(self._paragraphs) else "")
        try:
            return self._agent_suite.suggest_paragraph_improvement(
                paragraph,
                context_before=before,
                context_after=after,
                max_suggestions=2,
                genre=self._genre)
        except Exception as e:
            print(f"[checkpoint] suggest_paragraph_improvement failed: {e}")
            return []

    def _refresh_counter(self, *_):
        if not self._rows:
            self._counter_label.setText(
                "0 paragraphs in source.")
            self._save_btn.setEnabled(False)
            return
        kept = sum(1 for r in self._rows if r.status == _KEEP)
        edited = sum(1 for r in self._rows if r.status == _EDIT)
        rejected = sum(1 for r in self._rows
                        if r.status == _REJECT)
        emit_count = kept + edited
        self._counter_label.setText(
            f"<b>{len(self._rows)}</b> paragraphs in source · "
            f"<span style='color:#16a34a;'>kept {kept}</span> · "
            f"<span style='color:#f59e0b;'>edited {edited}</span> · "
            f"<span style='color:#dc2626;'>rejected {rejected}</span>"
            f"  →  new draft will have <b>{emit_count}</b> paragraphs")
        self._save_btn.setEnabled(emit_count > 0)

    def _on_save(self):
        from src.utils.paragraphs import join_paragraphs
        kept_paragraphs = [
            r.working_text for r in self._rows
            if r.status in (_KEEP, _EDIT) and r.working_text]
        if not kept_paragraphs:
            QMessageBox.information(
                self, "Nothing to save",
                "Every paragraph was rejected (or ended up empty). "
                "Mark at least one as Keep to save a draft.")
            return
        # Ask for a draft name + optional description. Defaults
        # include the source label so the user sees lineage in the
        # drafts list.
        suggested = (f"Checkpoint of {self._source_label}"
                     if self._source_label else "Checkpoint draft")
        name, ok = QInputDialog.getText(
            self, "Save as new draft",
            "Draft name:",
            text=suggested)
        if not ok or not name.strip():
            return
        self._draft_name = name.strip()
        desc, _ok = QInputDialog.getMultiLineText(
            self, "Save as new draft",
            "Optional description (e.g. \"removed exposition heavy "
            "paragraphs from chapter 3\"):",
            "")
        self._draft_description = (desc or "").strip()
        self._accepted_text = join_paragraphs(kept_paragraphs)
        self.accept()

    # ── Public accessors ─────────────────────────────────────

    def accepted_text(self) -> Optional[str]:
        """The joined paragraphs the user kept, or None if the
        dialog was cancelled. Caller writes this into a new
        ManuscriptDraft (or chapter revision)."""
        return self._accepted_text

    def draft_name(self) -> str:
        return self._draft_name

    def draft_description(self) -> str:
        return self._draft_description
