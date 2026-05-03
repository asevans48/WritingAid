"""Dialog for managing whole-project checkpoints.

Lists every checkpoint zip stored under ``<project_dir>/_checkpoints/``
and provides Create / Restore / Delete actions. Restoring is
destructive so it always takes a fresh "Before restore (auto)"
checkpoint of the current state first — the user can roll the
restore itself back if they regret it.

Backwards compatibility: projects that have never used the
checkpoint feature show an empty list with a clear "no
checkpoints yet" hint. Nothing else in project load/save depends
on the checkpoints directory existing.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QInputDialog, QMessageBox, QFrame,
)


def _human_bytes(n: int) -> str:
    """Render a byte count as a short human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} TB"


def _human_when(iso_str: str) -> str:
    """Render an ISO timestamp as a friendly local-time string."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_str or "(unknown)"


class ProjectCheckpointsDialog(QDialog):
    """Manage project checkpoints.

    Constructor takes the project's directory (the parent of the
    project JSON file) and an optional close-callback the writing
    tool can use to flush in-memory state before a restore. The
    dialog is project-model-agnostic — it only interacts with
    files on disk via :mod:`src.services.project_checkpoint`.
    """

    def __init__(self, project_dir: Path, *,
                 project_name: str = "",
                 on_before_restore=None,
                 on_after_restore=None,
                 parent=None):
        super().__init__(parent)
        self.project_dir = Path(project_dir)
        self.project_name = (
            project_name or self.project_dir.name)
        self._on_before_restore = on_before_restore
        self._on_after_restore = on_after_restore
        self.setWindowTitle("Project Checkpoints")
        self.setMinimumSize(720, 460)
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        outer = QVBoxLayout(self)

        title = QLabel("<b>Project Checkpoints</b>")
        f = title.font(); f.setPointSize(13); title.setFont(f)
        outer.addWidget(title)

        intro = QLabel(
            f"Snapshots of <b>{self.project_name}</b> you can roll "
            f"back to. Each checkpoint is a zip archive of the "
            f"entire project directory at that moment in time. "
            f"Restoring a checkpoint replaces the project's "
            f"current state — but a fresh \"Before restore "
            f"(auto)\" checkpoint is created first so you can "
            f"undo the restore.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#374151;font-size:12px;padding:6px;")
        outer.addWidget(intro)

        # Status / count strip.
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            "background:#f3f4f6;border-radius:4px;padding:6px 10px;"
            "color:#374151;font-size:11px;")
        outer.addWidget(self._status_label)

        # Checkpoint table.
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["Name", "Description", "Created", "Size"])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(False)
        self._table.setColumnWidth(0, 220)
        self._table.setColumnWidth(1, 280)
        self._table.setColumnWidth(2, 130)
        self._table.setColumnWidth(3, 80)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(
            self._refresh_action_states)
        outer.addWidget(self._table, 1)

        # Action row.
        actions = QHBoxLayout()
        self._create_btn = QPushButton("➕ Create checkpoint…")
        self._create_btn.setStyleSheet(
            "QPushButton { background-color:#2563eb;color:white;"
            " padding:6px 14px;border-radius:5px;font-weight:bold; }"
            "QPushButton:hover { background-color:#1d4ed8; }")
        self._create_btn.clicked.connect(self._on_create)
        actions.addWidget(self._create_btn)

        self._refresh_btn = QPushButton("⟳ Refresh")
        self._refresh_btn.clicked.connect(self._refresh)
        actions.addWidget(self._refresh_btn)

        actions.addStretch()

        self._delete_btn = QPushButton("🗑 Delete selected")
        self._delete_btn.setStyleSheet("color:#b91c1c;")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        actions.addWidget(self._delete_btn)

        self._restore_btn = QPushButton("↺ Restore selected")
        self._restore_btn.setStyleSheet(
            "QPushButton { background-color:#dc2626;color:white;"
            " padding:6px 14px;border-radius:5px;font-weight:bold; }"
            "QPushButton:hover { background-color:#b91c1c; }"
            "QPushButton:disabled { background-color:#fca5a5; }")
        self._restore_btn.setEnabled(False)
        self._restore_btn.clicked.connect(self._on_restore)
        actions.addWidget(self._restore_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(close_btn)
        outer.addLayout(actions)

    def _refresh(self):
        from src.services.project_checkpoint import list_checkpoints
        checkpoints = list_checkpoints(self.project_dir)
        self._checkpoints = checkpoints
        self._table.setRowCount(len(checkpoints))
        for row_i, cp in enumerate(checkpoints):
            for col_i, val in enumerate([
                    cp.name,
                    cp.description or "—",
                    _human_when(cp.created_at),
                    _human_bytes(cp.size_bytes)]):
                item = QTableWidgetItem(str(val))
                # Auto-checkpoints get an italic / muted look so the
                # user can distinguish them from explicit ones.
                if cp.name.startswith("Before restore"):
                    f = item.font()
                    f.setItalic(True)
                    item.setFont(f)
                self._table.setItem(row_i, col_i, item)
        if not checkpoints:
            self._status_label.setText(
                "No checkpoints yet. Click <b>➕ Create "
                "checkpoint…</b> to snapshot the current state of "
                "the project.")
        else:
            total = sum(cp.size_bytes for cp in checkpoints)
            self._status_label.setText(
                f"<b>{len(checkpoints)}</b> checkpoint"
                f"{'s' if len(checkpoints) != 1 else ''} · "
                f"total {_human_bytes(total)} on disk")
        self._refresh_action_states()

    def _refresh_action_states(self):
        has_selection = self._table.currentRow() >= 0
        self._restore_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)

    def _selected_checkpoint(self):
        row = self._table.currentRow()
        if row < 0 or row >= len(self._checkpoints):
            return None
        return self._checkpoints[row]

    def _on_create(self):
        name, ok = QInputDialog.getText(
            self, "Create checkpoint",
            "Checkpoint name (short — used in the filename):",
            text=f"Checkpoint {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        if not ok or not name.strip():
            return
        desc, _ok = QInputDialog.getMultiLineText(
            self, "Create checkpoint",
            "Optional description (e.g. \"after first round of "
            "edits\"):",
            "")
        try:
            from src.services.project_checkpoint import create_checkpoint
            cp = create_checkpoint(
                self.project_dir, name=name.strip(),
                description=(desc or "").strip())
        except Exception as e:
            QMessageBox.warning(
                self, "Couldn't create checkpoint", str(e))
            return
        QMessageBox.information(
            self, "Checkpoint created",
            f"Snapshot saved as <b>{cp.name}</b><br>"
            f"({_human_bytes(cp.size_bytes)} on disk).")
        self._refresh()

    def _on_delete(self):
        cp = self._selected_checkpoint()
        if cp is None:
            return
        confirm = QMessageBox.question(
            self, "Delete checkpoint?",
            f"Delete the checkpoint <b>{cp.name}</b>?<br><br>"
            f"This removes the zip archive from disk. Other "
            f"checkpoints are unaffected.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        from src.services.project_checkpoint import delete_checkpoint
        if delete_checkpoint(cp):
            self._refresh()
        else:
            QMessageBox.warning(
                self, "Delete failed",
                "Couldn't remove the checkpoint file. "
                "It may be open in another program or read-only.")

    def _on_restore(self):
        cp = self._selected_checkpoint()
        if cp is None:
            return
        confirm = QMessageBox.question(
            self, "Restore checkpoint?",
            f"Restore the project to the state in <b>{cp.name}</b> "
            f"({_human_when(cp.created_at)})?<br><br>"
            f"<b>This replaces the project's current state.</b> "
            f"A fresh \"Before restore (auto)\" checkpoint will "
            f"be created first so you can undo the restore from "
            f"this dialog.<br><br>"
            f"Close any open editors before continuing — they "
            f"may have stale in-memory state and overwrite the "
            f"restored content if you save.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        # Let the writing tool flush / close anything that might
        # interfere with the restore.
        if self._on_before_restore is not None:
            try:
                self._on_before_restore()
            except Exception as e:
                print(f"[checkpoints] on_before_restore raised: {e}")
        try:
            from src.services.project_checkpoint import (
                restore_checkpoint,
            )
            auto = restore_checkpoint(self.project_dir, cp,
                                       backup_current=True)
        except Exception as e:
            QMessageBox.warning(
                self, "Restore failed",
                f"Could not restore the checkpoint:\n\n{e}\n\n"
                f"Your project is unchanged. The auto-checkpoint "
                f"of pre-restore state was either not needed or "
                f"failed cleanly.")
            return
        if self._on_after_restore is not None:
            try:
                self._on_after_restore()
            except Exception as e:
                print(f"[checkpoints] on_after_restore raised: {e}")
        msg = (f"Restored <b>{cp.name}</b>."
               f" Your previous state was saved as the "
               f"\"Before restore (auto)\" checkpoint —"
               f" select it and click Restore again to undo."
               if auto
               else f"Restored <b>{cp.name}</b>.")
        QMessageBox.information(
            self, "Checkpoint restored", msg)
        self._refresh()
