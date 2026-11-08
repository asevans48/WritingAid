"""Style panel — every style issue in the chapter, ProWritingAid-style.

Counts per check (each check toggles its highlighting), a list of every
issue to step through, and one-click fixes: apply the suggested
replacement, ✨ rewrite the sentence with AI (the rephrase dialog, with
the author's voice), or ignore it.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)

from src.utils.style_checks import KINDS, sentences_with_offsets, summarize


class StyleIssuesPanel(QWidget):
    consistency_requested = pyqtSignal()

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self._issues: List[Tuple[int, int, object]] = []   # (doc start, doc end, StyleIssue)
        self._filter: Optional[str] = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(800)
        self._timer.timeout.connect(self.refresh)
        editor.textChanged.connect(self._schedule)
        self._build()

    # ── UI ───────────────────────────────────────────────────────

    def _build(self) -> None:
        from src.ui.enhanced_text_editor import CheckMode
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        top = QHBoxLayout()
        self.highlight_cb = QCheckBox("Highlight in text")
        self.highlight_cb.setChecked(self.editor.get_style_mode() != CheckMode.OFF)
        self.highlight_cb.toggled.connect(self._on_highlight_toggled)
        top.addWidget(self.highlight_cb)
        top.addStretch()
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("font-size: 11px; color: #4b5563;")
        top.addWidget(self.summary_label)
        v.addLayout(top)

        grid = QGridLayout()
        grid.setSpacing(2)
        self.kind_boxes = {}
        for i, (kind, (label, color, sentence_level)) in enumerate(KINDS.items()):
            swatch = QLabel("▆" if sentence_level else "﹏")
            swatch.setStyleSheet(f"color: {color if not sentence_level else '#64748b'};"
                                 + (f"background:{color};" if sentence_level else "")
                                 + "font-size: 11px; padding: 0 2px;")
            cb = QCheckBox(label)
            cb.setStyleSheet("font-size: 11px;")
            cb.setChecked(kind in self.editor.writing_highlighter._style_kinds)
            cb.toggled.connect(self._on_kinds_changed)
            cb.setToolTip("Untick to stop highlighting (and listing) this check.")
            show = QPushButton("0")
            show.setFlat(True)
            show.setStyleSheet("font-size: 11px; color: #2563eb; padding: 0 4px;")
            show.setToolTip("Show only these issues (click again to show all)")
            show.clicked.connect(lambda _=False, k=kind: self._toggle_filter(k))
            row, col = divmod(i, 2)
            grid.addWidget(swatch, row, col * 3)
            grid.addWidget(cb, row, col * 3 + 1)
            grid.addWidget(show, row, col * 3 + 2)
            self.kind_boxes[kind] = (cb, show)
        v.addLayout(grid)

        self.list = QListWidget()
        self.list.setStyleSheet("font-size: 11px;")
        self.list.currentRowChanged.connect(self._on_row)
        self.list.itemDoubleClicked.connect(lambda _i: self._fix())
        v.addWidget(self.list, 1)

        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("font-size: 11px; color: #374151; padding: 2px;")
        v.addWidget(self.detail)

        btns = QHBoxLayout()
        self.fix_btn = QPushButton("Fix")
        self.fix_btn.setToolTip("Apply the suggested change (double-click an issue does the same)")
        self.fix_btn.clicked.connect(self._fix)
        self.ai_btn = QPushButton("✨ Rewrite with AI…")
        self.ai_btn.setToolTip("Rewrite the sentence in your voice, aimed at this issue")
        self.ai_btn.clicked.connect(self._rewrite)
        self.ignore_btn = QPushButton("Ignore")
        self.ignore_btn.clicked.connect(self._ignore)
        for b in (self.fix_btn, self.ai_btn, self.ignore_btn):
            b.setStyleSheet("font-size: 11px; padding: 3px 6px;")
            btns.addWidget(b)
        btns.addStretch()
        v.addLayout(btns)
        consistency = QPushButton("🔍 Check consistency (names, spellings, style)…")
        consistency.setStyleSheet("font-size: 11px; padding: 3px 6px;")
        consistency.clicked.connect(self.consistency_requested.emit)
        v.addWidget(consistency)
        self._update_buttons()

    # ── data ─────────────────────────────────────────────────────

    def _schedule(self) -> None:
        if self.isVisible():
            self._timer.start()
        else:
            self._dirty = True

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def collect(self) -> List[Tuple[int, int, object]]:
        hl = self.editor.writing_highlighter
        out = []
        block = self.editor.document().begin()
        while block.isValid():
            pos = block.position()
            for issue in hl.style_issues_for(block.text()):
                out.append((pos + issue.start, pos + issue.end, issue))
            block = block.next()
        return out

    def refresh(self) -> None:
        self._dirty = False
        self._issues = self.collect()
        words = len(self.editor.toPlainText().split())
        summ = summarize([i for _, _, i in self._issues], words)
        self.summary_label.setText(
            f"{summ['total']} issue{'s' if summ['total'] != 1 else ''}"
            + (f" · {summ['per_1000']}/1,000 words" if words else ""))
        for kind, (cb, show) in self.kind_boxes.items():
            show.setText(str(summ["by_kind"].get(kind, 0)))
            show.setStyleSheet("font-size: 11px; padding: 0 4px; color: "
                               + ("#111827; font-weight: bold;" if self._filter == kind else "#2563eb;"))
        current = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        self._shown = []
        for start, end, issue in self._issues:
            if self._filter and issue.kind != self._filter:
                continue
            label, color, sentence_level = KINDS[issue.kind]
            snippet = issue.text if len(issue.text) <= 70 else issue.text[:67] + "…"
            item = QListWidgetItem(f"{label}: {snippet}")
            item.setForeground(QColor(color if not sentence_level else "#334155"))
            item.setToolTip(issue.message)
            self.list.addItem(item)
            self._shown.append((start, end, issue))
        self.list.blockSignals(False)
        if self._shown:
            self.list.setCurrentRow(min(max(current, 0), len(self._shown) - 1))
        self._update_buttons()

    def _selected(self):
        row = self.list.currentRow()
        if 0 <= row < len(getattr(self, "_shown", [])):
            return self._shown[row]
        return None

    def _update_buttons(self) -> None:
        sel = self._selected()
        self.fix_btn.setEnabled(bool(sel and sel[2].suggestions))
        self.ai_btn.setEnabled(sel is not None)
        self.ignore_btn.setEnabled(sel is not None)
        if sel:
            fix = sel[2].suggestions[0] if sel[2].suggestions else None
            self.fix_btn.setText("Fix" if fix is None else
                                 (f"Fix → “{fix}”" if fix else f"Delete “{sel[2].text}”"))
            self.detail.setText(sel[2].message)
        else:
            self.fix_btn.setText("Fix")
            self.detail.setText("No style issues." if not self._issues else "")

    # ── actions ──────────────────────────────────────────────────

    def _on_highlight_toggled(self, on: bool) -> None:
        from src.ui.enhanced_text_editor import CheckMode
        self.editor.set_style_mode(CheckMode.ON_DEMAND if on else CheckMode.OFF)
        self.highlight_changed()

    def highlight_changed(self) -> None:
        """Hook for the host to restyle its toolbar button."""

    def sync_highlight(self) -> None:
        from src.ui.enhanced_text_editor import CheckMode
        self.highlight_cb.blockSignals(True)
        self.highlight_cb.setChecked(self.editor.get_style_mode() != CheckMode.OFF)
        self.highlight_cb.blockSignals(False)

    def _on_kinds_changed(self) -> None:
        kinds = {k for k, (cb, _) in self.kind_boxes.items() if cb.isChecked()}
        self.editor.writing_highlighter.set_style_kinds(kinds)
        self.refresh()

    def _toggle_filter(self, kind: str) -> None:
        self._filter = None if self._filter == kind else kind
        self.refresh()

    def _on_row(self, _row: int) -> None:
        sel = self._selected()
        self._update_buttons()
        if sel is None:
            return
        cursor = self.editor.textCursor()
        cursor.setPosition(sel[0])
        cursor.setPosition(sel[1], QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()

    def _span_still_matches(self, start: int, end: int, text: str) -> bool:
        cur = self.editor.textCursor()
        cur.setPosition(start)
        cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        return cur.selectedText().replace(" ", "\n") == text

    def _fix(self) -> None:
        sel = self._selected()
        if not sel or not sel[2].suggestions:
            return
        start, end, issue = sel
        if not self._span_still_matches(start, end, issue.text):
            self.refresh()
            return
        cur = self.editor.textCursor()
        cur.setPosition(start)
        cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.editor._replace_word(cur, issue.suggestions[0])
        self.refresh()

    def _rewrite(self) -> None:
        sel = self._selected()
        if not sel:
            return
        start, end, issue = sel
        block = self.editor.document().findBlock(start)
        rel = start - block.position()
        s0, e0 = start, end
        for a, b, _ in sentences_with_offsets(block.text()):
            if a <= rel < b:
                s0, e0 = min(start, block.position() + a), max(end, block.position() + b)
                break
        label = KINDS[issue.kind][0].lower()
        self.editor.style_rewrite_requested.emit(s0, e0, f"Fix the {label}: {issue.message}")

    def _ignore(self) -> None:
        sel = self._selected()
        if not sel:
            return
        self.editor.writing_highlighter.ignore_style_issue(sel[2].kind, sel[2].text)
        self.refresh()
