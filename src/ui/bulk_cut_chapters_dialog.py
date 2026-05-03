"""Bulk-cut chapters dialog with optional checkpoint-first.

Single-chapter deletion lives on the chapter-list right-click
menu in :class:`ManuscriptEditor`. This dialog handles the
"clear out a whole stretch of chapters at once" workflow — the
user ticks every chapter to drop, sees the totals, and chooses
whether to snapshot the project first.

The bulk delete is destructive (it removes chapter folders and
revisions from disk via ``Chapter.delete_folder``). The dialog's
primary action is intentionally <b>Create checkpoint + delete</b>
so the user gets one-click safety; <b>Delete without checkpoint</b>
is a secondary, less-prominent button for users who already know
the project is checkpointed elsewhere or just want to move fast.

The actual delete loop lives on the caller (the
ManuscriptEditor) because it needs to coordinate with the
in-memory editor state (saving the current chapter, blocking
selection signals during list rebuild, relocating remaining
folders for renumbering). This dialog returns ``(chapter_ids,
make_checkpoint)`` and lets the caller do the work.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QInputDialog, QMessageBox,
    QFrame, QSizePolicy,
)


class BulkCutChaptersDialog(QDialog):
    """Multi-select chapter cut with optional pre-cut checkpoint.

    Constructor takes the list of chapters and the (optional)
    project directory. When the directory is supplied, the
    "Create checkpoint + delete" button is enabled and triggers
    a checkpoint creation before the dialog returns; when it's
    None, only "Delete without checkpoint" is offered (the
    project hasn't been saved to disk yet, so there's nowhere to
    drop a checkpoint zip).

    On accept, the caller queries:
      * :meth:`selected_chapter_ids` — list of chapter ids the
        user ticked
      * :meth:`should_create_checkpoint` — True if the user picked
        the "checkpoint + delete" path
      * :meth:`created_checkpoint_name` — the name the user gave
        the checkpoint (for the caller's status-bar message);
        empty when no checkpoint was created
    """

    def __init__(self, chapters: list, *,
                 project_dir: Optional[Path] = None,
                 project_name: str = "",
                 parent=None):
        super().__init__(parent)
        self._chapters = list(chapters)
        self._project_dir = (Path(project_dir) if project_dir
                              else None)
        self._project_name = project_name or "this project"
        self._checkpoint_created: bool = False
        self._checkpoint_name: str = ""
        self._chosen_ids: List[str] = []
        self.setWindowTitle("Bulk Cut Chapters")
        self.setMinimumSize(560, 480)
        self._build_ui()

    # ── UI ───────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)

        title = QLabel("<b>Bulk cut chapters</b>")
        f = title.font(); f.setPointSize(13); title.setFont(f)
        outer.addWidget(title)
        intro = QLabel(
            f"Tick the chapters you want to remove from "
            f"<b>{self._project_name}</b>. Deletion drops the "
            f"chapter folders and all their revisions from disk "
            f"— it can't be undone from the editor's normal undo "
            f"stack. The recommended path is to take a project "
            f"checkpoint first; one click does both.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#374151;font-size:12px;padding:6px;")
        outer.addWidget(intro)

        # Select-all / select-none helpers
        helper_row = QHBoxLayout()
        all_btn = QPushButton("Select all")
        all_btn.setStyleSheet("padding:4px 10px;font-size:11px;")
        all_btn.clicked.connect(self._select_all)
        helper_row.addWidget(all_btn)
        none_btn = QPushButton("Select none")
        none_btn.setStyleSheet("padding:4px 10px;font-size:11px;")
        none_btn.clicked.connect(self._select_none)
        helper_row.addWidget(none_btn)
        helper_row.addStretch()
        outer.addLayout(helper_row)

        # Chapter list with checkboxes
        self._list = QListWidget()
        self._list.itemChanged.connect(self._refresh_summary)
        for ch in self._chapters:
            wc = len((ch.content or "").split())
            label = (
                f"Ch {ch.number}: {ch.title or '(untitled)'}  "
                f"— {wc:,} words")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ch.id)
            item.setFlags(item.flags()
                           | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._list.addItem(item)
        outer.addWidget(self._list, 1)

        # Live summary line
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(
            "background:#f3f4f6;border-radius:4px;"
            "padding:6px 10px;color:#374151;font-size:11px;")
        outer.addWidget(self._summary_label)

        # Action row. The primary action is the checkpoint-first
        # path because that's the safer default. "Delete without
        # checkpoint" is intentionally less prominent.
        actions = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)
        actions.addStretch()

        self._delete_only_btn = QPushButton("⚠ Delete without checkpoint")
        self._delete_only_btn.setToolTip(
            "Skip the safety checkpoint and delete the ticked "
            "chapters now. Cannot be undone unless you have a "
            "separate backup.")
        self._delete_only_btn.setStyleSheet(
            "QPushButton { padding:6px 14px;border-radius:5px;"
            " color:#b91c1c;background:transparent;"
            " border:1px solid #fca5a5;font-size:11px; }"
            "QPushButton:hover { background:#fef2f2; }"
            "QPushButton:disabled { color:#fca5a5;border-color:#fee2e2; }")
        self._delete_only_btn.setEnabled(False)
        self._delete_only_btn.clicked.connect(self._on_delete_only)
        actions.addWidget(self._delete_only_btn)

        self._cp_then_delete_btn = QPushButton(
            "✓ Create checkpoint + delete")
        self._cp_then_delete_btn.setToolTip(
            "Recommended. Takes a whole-project checkpoint zip "
            "first (you can restore it later from File → Project "
            "Checkpoints), then deletes the ticked chapters.")
        self._cp_then_delete_btn.setStyleSheet(
            "QPushButton { background-color:#10b981;color:white;"
            " padding:6px 14px;border-radius:5px;font-weight:bold; }"
            "QPushButton:hover { background-color:#059669; }"
            "QPushButton:disabled { background-color:#86efac; }")
        self._cp_then_delete_btn.setEnabled(False)
        self._cp_then_delete_btn.clicked.connect(
            self._on_checkpoint_then_delete)
        actions.addWidget(self._cp_then_delete_btn)
        outer.addLayout(actions)

        # If we have no project_dir, the checkpoint button can't
        # work — disable it permanently and make it explain why.
        if self._project_dir is None:
            self._cp_then_delete_btn.setEnabled(False)
            self._cp_then_delete_btn.setToolTip(
                "Project hasn't been saved to disk yet — there's "
                "nowhere to drop a checkpoint zip. Save the "
                "project first (File → Save) to enable this.")

        self._refresh_summary()

    def _select_all(self):
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.CheckState.Checked)

    def _select_none(self):
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _ticked_indices(self) -> List[int]:
        return [i for i in range(self._list.count())
                if self._list.item(i).checkState()
                == Qt.CheckState.Checked]

    def _refresh_summary(self, *_):
        ticked = self._ticked_indices()
        if not ticked:
            self._summary_label.setText(
                "<i>(no chapters ticked — pick at least one)</i>")
            self._delete_only_btn.setEnabled(False)
            self._cp_then_delete_btn.setEnabled(
                self._project_dir is not None and False)
            return
        ticked_chapters = [self._chapters[i] for i in ticked]
        total_words = sum(
            len((ch.content or "").split())
            for ch in ticked_chapters)
        self._summary_label.setText(
            f"<b>{len(ticked)}</b> of {len(self._chapters)} "
            f"chapters ticked · "
            f"<b>{total_words:,}</b> words across them")
        self._delete_only_btn.setEnabled(True)
        if self._project_dir is not None:
            self._cp_then_delete_btn.setEnabled(True)

    # ── Actions ───────────────────────────────────────────────

    def _on_checkpoint_then_delete(self):
        """Create a project checkpoint first, then mark the dialog
        as accepted with the ticked chapter ids. The actual
        deletion happens in the caller."""
        ticked = self._ticked_indices()
        if not ticked:
            return
        suggested = self._suggested_checkpoint_name(ticked)
        name, ok = QInputDialog.getText(
            self, "Checkpoint name",
            "Name for the safety checkpoint (will appear in File "
            "→ Project Checkpoints):",
            text=suggested)
        if not ok or not name.strip():
            return
        try:
            from src.services.project_checkpoint import (
                create_checkpoint,
            )
            cp = create_checkpoint(
                self._project_dir,
                name=name.strip(),
                description=(
                    f"Auto-created before bulk-cutting "
                    f"{len(ticked)} chapter"
                    f"{'s' if len(ticked) != 1 else ''} from "
                    f"{self._project_name}."))
            self._checkpoint_created = True
            self._checkpoint_name = cp.name
        except Exception as e:
            QMessageBox.warning(
                self, "Checkpoint failed",
                f"Couldn't create the safety checkpoint:\n\n{e}\n\n"
                f"Refusing to delete chapters when the safety "
                f"net failed. Save your project and try again, "
                f"or use \"Delete without checkpoint\" if you've "
                f"already backed up elsewhere.")
            return
        self._chosen_ids = self._collect_ticked_ids(ticked)
        self.accept()

    def _on_delete_only(self):
        """Skip checkpoint, just collect ticked ids and accept."""
        ticked = self._ticked_indices()
        if not ticked:
            return
        confirm = QMessageBox.warning(
            self, "Delete without checkpoint?",
            f"Permanently delete {len(ticked)} chapter"
            f"{'s' if len(ticked) != 1 else ''} from "
            f"<b>{self._project_name}</b> with no safety "
            f"checkpoint?<br><br>"
            f"This cannot be undone unless you have a backup "
            f"elsewhere. The recommended path is "
            f"\"Create checkpoint + delete\".",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._chosen_ids = self._collect_ticked_ids(ticked)
        self.accept()

    def _collect_ticked_ids(self, ticked_indices: List[int]) -> List[str]:
        return [self._list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in ticked_indices]

    def _suggested_checkpoint_name(self,
                                    ticked_indices: List[int]) -> str:
        n = len(ticked_indices)
        if n == 1:
            ch = self._chapters[ticked_indices[0]]
            return f"Before cutting Ch{ch.number}"
        first = self._chapters[ticked_indices[0]]
        last = self._chapters[ticked_indices[-1]]
        return (f"Before cutting {n} chapters "
                f"(Ch{first.number}-Ch{last.number})")

    # ── Public accessors ─────────────────────────────────────

    def selected_chapter_ids(self) -> List[str]:
        return list(self._chosen_ids)

    def should_create_checkpoint(self) -> bool:
        return self._checkpoint_created

    def created_checkpoint_name(self) -> str:
        return self._checkpoint_name
