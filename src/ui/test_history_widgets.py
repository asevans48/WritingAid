"""Shared widgets for storing + reviewing model-test results.

Two surfaces use these:
  * The Local Models Hub (after Run Test, the rating panel
    appears next to the output).
  * The Training Studio's Step-4 Model Management (same panel,
    same dialog).

Keeping them in a single module means a UX tweak ships to both
places automatically — and ratings entered in either surface read
back from the same JSON store.

Two public classes:

  * :class:`TestRatingPanel` — compact post-test widget with a
    1-5 star rating, a category picker (with sensible defaults +
    free entry), a notes field, and a Save button. Emits ``saved``
    with the saved :class:`TestResult` so the host UI can refresh
    its history pane.

  * :class:`TestHistoryDialog` — full per-model browser. Top:
    overall + per-category aggregates as a stats panel. Bottom:
    sortable list of every test for the model with inline
    re-rate / re-categorize / delete actions.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QPlainTextEdit, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox, QFormLayout, QMessageBox, QDialogButtonBox,
    QLineEdit, QSizePolicy, QFrame,
)

from src.data import model_test_store as store
from src.data.model_test_store import (
    TestResult, ModelStats, CategoryStats, DEFAULT_CATEGORIES,
)


# ── Star rating widget ─────────────────────────────────────


class _StarRating(QWidget):
    """1-5 star picker rendered as five tiny buttons.

    Clicking a star sets the rating to that value; clicking the
    same star twice clears it (rating=0). The host widget reads
    the value via :meth:`value` and listens to :attr:`changed`.
    """
    changed = pyqtSignal(int)

    def __init__(self, initial: int = 0, parent=None):
        super().__init__(parent)
        self._value = max(0, min(5, int(initial or 0)))
        self._buttons: List[QPushButton] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for i in range(1, 6):
            btn = QPushButton("☆")
            btn.setFixedSize(28, 28)
            btn.setStyleSheet(
                "QPushButton { font-size: 18px; "
                "background: transparent; border: none; }"
                "QPushButton:hover { color: #f59e0b; }")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked=False, idx=i: self._on_click(idx))
            layout.addWidget(btn)
            self._buttons.append(btn)
        layout.addStretch()
        self._render()

    def _on_click(self, idx: int):
        new = 0 if idx == self._value else idx
        self.set_value(new)

    def value(self) -> int:
        return self._value

    def set_value(self, v: int):
        v = max(0, min(5, int(v or 0)))
        if v == self._value:
            return
        self._value = v
        self._render()
        self.changed.emit(v)

    def _render(self):
        for i, btn in enumerate(self._buttons, start=1):
            if i <= self._value:
                btn.setText("★")
                btn.setStyleSheet(
                    "QPushButton { font-size: 18px; color: #f59e0b; "
                    "background: transparent; border: none; }"
                    "QPushButton:hover { color: #d97706; }")
            else:
                btn.setText("☆")
                btn.setStyleSheet(
                    "QPushButton { font-size: 18px; color: #d1d5db; "
                    "background: transparent; border: none; }"
                    "QPushButton:hover { color: #f59e0b; }")


# ── Rating panel (post-test) ──────────────────────────────


class TestRatingPanel(QWidget):
    """Compact "rate + save this test result" widget.

    Hosted below the test output in both the Hub and Studio. The
    user clicks Run, output appears, panel becomes active. Once
    they save (with or without a rating), the panel emits
    :attr:`saved` and the host can refresh whatever stats it
    shows.

    Calling :meth:`set_pending_test` swaps in fresh data — used
    after each new Run Test press to point the panel at the new
    output.
    """
    saved = pyqtSignal(object)  # TestResult

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending: Optional[dict] = None
        self._build_ui()
        self.setEnabled(False)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #f9fafb; "
            "border: 1px solid #e5e7eb; border-radius: 6px; }")
        body = QVBoxLayout(frame)
        body.setContentsMargins(12, 10, 12, 10)
        body.setSpacing(6)

        title = QLabel("<b>Rate this test</b>")
        body.addWidget(title)

        # Stars + category on one row.
        first_row = QHBoxLayout()
        first_row.addWidget(QLabel("Rating:"))
        self._stars = _StarRating()
        first_row.addWidget(self._stars)
        first_row.addSpacing(20)
        first_row.addWidget(QLabel("Category:"))
        self._category_combo = QComboBox()
        self._category_combo.setEditable(True)
        for c in DEFAULT_CATEGORIES:
            self._category_combo.addItem(c)
        self._category_combo.setMinimumWidth(160)
        first_row.addWidget(self._category_combo, 1)
        body.addLayout(first_row)

        # Notes.
        body.addWidget(QLabel("Notes (optional):"))
        self._notes = QPlainTextEdit()
        self._notes.setMaximumHeight(60)
        self._notes.setPlaceholderText(
            "What worked, what didn't, things to fix next time…")
        body.addWidget(self._notes)

        # Save / discard.
        actions = QHBoxLayout()
        actions.addStretch()
        self._discard_btn = QPushButton("Skip")
        self._discard_btn.setToolTip(
            "Don't save this test. The output stays on screen but "
            "no record is added to the history.")
        self._discard_btn.clicked.connect(self._on_discard)
        actions.addWidget(self._discard_btn)

        self._save_btn = QPushButton("💾 Save test")
        self._save_btn.setStyleSheet(
            "QPushButton { background-color: #16a34a; color: white; "
            "padding: 4px 12px; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background-color: #15803d; }")
        self._save_btn.clicked.connect(self._on_save)
        actions.addWidget(self._save_btn)
        body.addLayout(actions)

        outer.addWidget(frame)

    # ── Public API ────────────────────────────────────────

    def set_pending_test(self, *,
                          model_name: str,
                          model_path: str = "",
                          prompt: str,
                          response: str,
                          intent_used: str = "",
                          generation_params: Optional[dict] = None,
                          duration_ms: int = 0,
                          default_category: str = ""):
        """Prime the panel for a freshly-run test.

        Re-enables the panel (it's disabled when no test is
        pending). The stars / notes get reset; the category combo
        is set to the suggested default if one was provided
        (typically the model's intent), or kept as the user's
        previous pick.
        """
        self._pending = {
            "model_name": model_name,
            "model_path": model_path,
            "prompt": prompt,
            "response": response,
            "intent_used": intent_used,
            "generation_params": dict(generation_params or {}),
            "duration_ms": duration_ms,
        }
        self._stars.set_value(0)
        self._notes.clear()
        if default_category:
            # Add it to the combo if missing.
            idx = self._category_combo.findText(default_category)
            if idx < 0:
                self._category_combo.addItem(default_category)
                idx = self._category_combo.findText(default_category)
            if idx >= 0:
                self._category_combo.setCurrentIndex(idx)
        self.setEnabled(True)

    def clear(self):
        self._pending = None
        self.setEnabled(False)
        self._stars.set_value(0)
        self._notes.clear()

    # ── Slots ─────────────────────────────────────────────

    def _on_save(self):
        if not self._pending:
            return
        category = self._category_combo.currentText().strip()
        if not category:
            category = "other"
        try:
            saved = store.save_test_result(
                model_name=self._pending["model_name"],
                model_path=self._pending["model_path"],
                category=category,
                prompt=self._pending["prompt"],
                response=self._pending["response"],
                rating=self._stars.value(),
                notes=self._notes.toPlainText().strip(),
                intent_used=self._pending["intent_used"],
                generation_params=self._pending["generation_params"],
                duration_ms=self._pending["duration_ms"],
            )
        except Exception as e:
            QMessageBox.warning(
                self, "Could not save test",
                f"Test couldn't be saved to ~/.creativeos/"
                f"model_tests.json:\n{e}")
            return
        self.saved.emit(saved)
        self.clear()

    def _on_discard(self):
        self.clear()


# ── History dialog ────────────────────────────────────────


class TestHistoryDialog(QDialog):
    """Per-model test history with overall + per-category stats.

    Top half: stats panel showing totals and the per-category
    breakdown (count, n rated, mean rating).
    Bottom half: sortable table of every test for this model with
    inline actions to re-rate, re-categorize, or delete.
    """

    def __init__(self, model_name: str, parent=None):
        super().__init__(parent)
        self.model_name = model_name
        self.setWindowTitle(f"Test history — {model_name}")
        self.setMinimumSize(920, 620)
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel(f"<b>{self.model_name}</b>")
        f = title.font(); f.setPointSize(14); title.setFont(f)
        layout.addWidget(title)

        # Stats panel.
        self._stats_box = QGroupBox("Stats")
        self._stats_layout = QVBoxLayout(self._stats_box)
        layout.addWidget(self._stats_box)

        # History table.
        layout.addWidget(QLabel("<b>All test runs</b>"))
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "When", "Category", "Rating", "Prompt", "Response",
            "Notes", "Actions"])
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSortingEnabled(True)
        layout.addWidget(self._table, 1)

        # Footer actions.
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        layout.addWidget(bb)

    # ── Refresh ──────────────────────────────────────────

    def _refresh(self):
        s = store.compute_stats(self.model_name)
        self._render_stats(s)
        self._render_table(s)

    def _render_stats(self, s: ModelStats):
        # Clear old children.
        while self._stats_layout.count():
            item = self._stats_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if s.n_tests == 0:
            self._stats_layout.addWidget(QLabel(
                "<i>No test history yet for this model. Run a "
                "test from the Hub or Step 4, then save it to "
                "build a history.</i>"))
            return

        overall = QLabel(
            f"<b>Overall</b>: {s.n_tests} tests · "
            f"{s.n_rated} rated · "
            f"<b>{s.mean_rating:.2f}/5</b> mean rating  "
            f"<span style='color:#6b7280;font-size:11px;'>"
            f"(distribution: "
            f"{', '.join(f'{n}★×{s.rating_distribution.get(n, 0)}' for n in (5,4,3,2,1) if s.rating_distribution.get(n, 0))}"
            f")</span>")
        overall.setStyleSheet(
            "background: #ecfdf5; border-left: 3px solid #10b981; "
            "padding: 6px 10px; border-radius: 3px;")
        overall.setWordWrap(True)
        self._stats_layout.addWidget(overall)

        if s.by_category:
            self._stats_layout.addWidget(
                QLabel("<b>By category</b>"))
            cat_table = QTableWidget()
            cat_table.setColumnCount(4)
            cat_table.setHorizontalHeaderLabels([
                "Category", "Tests", "Rated", "Mean rating"])
            cat_table.setRowCount(len(s.by_category))
            for i, cs in enumerate(s.by_category):
                cat_table.setItem(i, 0, QTableWidgetItem(cs.category))
                cat_table.setItem(i, 1, QTableWidgetItem(str(cs.n_tests)))
                cat_table.setItem(i, 2, QTableWidgetItem(str(cs.n_rated)))
                mean_str = (f"{cs.mean_rating:.2f}/5"
                            if cs.n_rated else "—")
                cat_table.setItem(i, 3, QTableWidgetItem(mean_str))
            cat_table.setMaximumHeight(
                32 * (len(s.by_category) + 1) + 2)
            cat_table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.Stretch)
            for col in range(1, 4):
                cat_table.horizontalHeader().setSectionResizeMode(
                    col, QHeaderView.ResizeMode.ResizeToContents)
            cat_table.setEditTriggers(
                QTableWidget.EditTrigger.NoEditTriggers)
            self._stats_layout.addWidget(cat_table)

    def _render_table(self, s: ModelStats):
        # Note: we re-load the records here so the rows include
        # the test_id (which ModelStats doesn't carry).
        records = store.load_results(model_name=self.model_name)
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(records))
        for row, r in enumerate(records):
            ts = (r.created_at or "").replace("T", " ")[:16]
            self._table.setItem(row, 0, QTableWidgetItem(ts))
            self._table.setItem(row, 1, QTableWidgetItem(r.category))
            rating_str = ("☆ unrated" if r.rating == 0
                          else "★" * r.rating + "☆" * (5 - r.rating))
            rating_item = QTableWidgetItem(rating_str)
            self._table.setItem(row, 2, rating_item)
            self._table.setItem(
                row, 3, QTableWidgetItem(_truncate(r.prompt, 80)))
            self._table.setItem(
                row, 4, QTableWidgetItem(_truncate(r.response, 100)))
            self._table.setItem(
                row, 5, QTableWidgetItem(_truncate(r.notes, 60)))

            # Actions cell — Edit + Delete inline buttons.
            cell = QWidget()
            row_lay = QHBoxLayout(cell)
            row_lay.setContentsMargins(2, 2, 2, 2)
            row_lay.setSpacing(2)
            edit_btn = QPushButton("✎")
            edit_btn.setFixedSize(24, 24)
            edit_btn.setToolTip("Re-rate / re-categorize / edit notes")
            edit_btn.clicked.connect(
                lambda _checked=False, rid=r.id: self._on_edit(rid))
            row_lay.addWidget(edit_btn)
            del_btn = QPushButton("🗑")
            del_btn.setFixedSize(24, 24)
            del_btn.setToolTip("Delete this test record")
            del_btn.setStyleSheet(
                "QPushButton { color: #b91c1c; }")
            del_btn.clicked.connect(
                lambda _checked=False, rid=r.id: self._on_delete(rid))
            row_lay.addWidget(del_btn)
            self._table.setCellWidget(row, 6, cell)
        self._table.setSortingEnabled(True)

    # ── Slots ─────────────────────────────────────────────

    def _on_edit(self, test_id: str):
        rec = next((r for r in store.load_results(
                    model_name=self.model_name)
                    if r.id == test_id), None)
        if rec is None:
            return
        dlg = _RowEditDialog(rec, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh()

    def _on_delete(self, test_id: str):
        if QMessageBox.question(
                self, "Delete record",
                "Permanently delete this test result?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel
                ) != QMessageBox.StandardButton.Yes:
            return
        if store.delete_test(test_id):
            self._refresh()


class _RowEditDialog(QDialog):
    """Inline editor for one test record. Lets the user fix the
    category / rating / notes after the fact — common workflow when
    a test was saved unrated and later judged."""

    def __init__(self, record: TestResult, parent=None):
        super().__init__(parent)
        self.record = record
        self.setWindowTitle("Edit test record")
        self.setMinimumWidth(520)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Read-only context.
        layout.addWidget(QLabel(
            f"<b>Prompt:</b> {_truncate(self.record.prompt, 200)}"))
        resp = QLabel(
            f"<b>Response:</b> {_truncate(self.record.response, 400)}")
        resp.setWordWrap(True)
        layout.addWidget(resp)

        # Editable fields.
        form = QFormLayout()
        self._stars = _StarRating(initial=self.record.rating)
        form.addRow("Rating:", self._stars)

        self._category_combo = QComboBox()
        self._category_combo.setEditable(True)
        for c in store.list_categories():
            self._category_combo.addItem(c)
        idx = self._category_combo.findText(self.record.category or "other")
        if idx < 0 and self.record.category:
            self._category_combo.addItem(self.record.category)
            idx = self._category_combo.findText(self.record.category)
        self._category_combo.setCurrentIndex(max(0, idx))
        form.addRow("Category:", self._category_combo)

        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setPlainText(self.record.notes)
        self._notes_edit.setMaximumHeight(80)
        form.addRow("Notes:", self._notes_edit)
        layout.addLayout(form)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Save)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self._on_save)
        layout.addWidget(bb)

    def _on_save(self):
        ok = store.update_test_rating(
            self.record.id,
            rating=self._stars.value(),
            category=self._category_combo.currentText().strip().lower(),
            notes=self._notes_edit.toPlainText().strip())
        if not ok:
            QMessageBox.warning(
                self, "Update failed",
                "Couldn't update the record. It may have been "
                "deleted by another tool — re-open the history "
                "dialog to refresh.")
            return
        self.accept()


def _truncate(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    if len(s) <= n:
        return s
    return s[:n - 1] + "…"
