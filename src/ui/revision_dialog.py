"""Draft management dialog with side-by-side comparison and file-based storage."""

from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget,
    QListWidgetItem, QTextEdit, QLabel, QPushButton, QComboBox,
    QMessageBox, QWidget, QInputDialog
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from src.models.project import Chapter, ChapterRevision


def _age_label(timestamp) -> str:
    """Return a human-readable age string like '3 days ago' or 'just now'."""
    if not timestamp:
        return ""
    now = datetime.now()
    delta = now - timestamp
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"


class RevisionDialog(QDialog):
    """Dialog for managing chapter drafts with side-by-side comparison."""

    revision_restored = pyqtSignal(str, str)  # content, html_content
    edit_alongside = pyqtSignal(int)  # draft_number to show in side-by-side

    def __init__(self, chapter: Chapter, project_dir: Path,
                 current_content: str = "", current_html: str = "",
                 parent=None):
        super().__init__(parent)
        self.chapter = chapter
        self.project_dir = project_dir
        self.current_content = current_content
        self.current_html = current_html
        self._restored = False
        self._edit_alongside_rev = None

        self.setWindowTitle(f"Drafts - {chapter.title}")
        self.setMinimumSize(1000, 650)
        self.resize(1200, 700)

        self._init_ui()
        self._populate_revision_list()
        self._populate_compare_combo()

        if self.revision_list.count() > 0:
            self.revision_list.setCurrentRow(0)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # === Left panel: draft list + buttons ===
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        list_label = QLabel("Drafts")
        list_label.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        left_layout.addWidget(list_label)

        self.revision_list = QListWidget()
        self.revision_list.setMinimumWidth(240)
        self.revision_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #d1d5db;
                border-radius: 6px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 8px 6px;
                border-bottom: 1px solid #e5e7eb;
            }
            QListWidget::item:selected {
                background-color: #6366f1;
                color: white;
            }
        """)
        self.revision_list.currentRowChanged.connect(self._on_revision_selected)
        left_layout.addWidget(self.revision_list)

        btn_style = """
            QPushButton {
                padding: 8px 12px;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 500;
            }
        """

        new_blank_btn = QPushButton("New Blank Draft")
        new_blank_btn.setStyleSheet(btn_style + """
            QPushButton { background-color: #10b981; color: white; border: none; }
            QPushButton:hover { background-color: #059669; }
        """)
        new_blank_btn.clicked.connect(self._create_blank_revision)
        left_layout.addWidget(new_blank_btn)

        snapshot_btn = QPushButton("Snapshot Current Draft")
        snapshot_btn.setStyleSheet(btn_style + """
            QPushButton { background-color: #6366f1; color: white; border: none; }
            QPushButton:hover { background-color: #4f46e5; }
        """)
        snapshot_btn.clicked.connect(self._snapshot_current)
        left_layout.addWidget(snapshot_btn)

        edit_btn = QPushButton("Edit Alongside Selected")
        edit_btn.setStyleSheet(btn_style + """
            QPushButton { background-color: #3b82f6; color: white; border: none; }
            QPushButton:hover { background-color: #2563eb; }
        """)
        edit_btn.clicked.connect(self._edit_alongside_selected)
        left_layout.addWidget(edit_btn)

        restore_btn = QPushButton("Restore Selected")
        restore_btn.setStyleSheet(btn_style + """
            QPushButton { background-color: #f59e0b; color: white; border: none; }
            QPushButton:hover { background-color: #d97706; }
        """)
        restore_btn.clicked.connect(self._restore_selected)
        left_layout.addWidget(restore_btn)

        delete_btn = QPushButton("Delete Selected")
        delete_btn.setStyleSheet(btn_style + """
            QPushButton { background-color: #ef4444; color: white; border: none; }
            QPushButton:hover { background-color: #dc2626; }
        """)
        delete_btn.clicked.connect(self._delete_selected)
        left_layout.addWidget(delete_btn)

        main_splitter.addWidget(left_panel)

        # === Right panel: side-by-side comparison ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        compare_bar = QHBoxLayout()
        compare_bar.addWidget(QLabel("Compare against:"))
        self.compare_combo = QComboBox()
        self.compare_combo.setMinimumWidth(200)
        self.compare_combo.currentIndexChanged.connect(self._on_compare_changed)
        compare_bar.addWidget(self.compare_combo)
        compare_bar.addStretch()

        self.left_wc_label = QLabel("")
        self.left_wc_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        self.right_wc_label = QLabel("")
        self.right_wc_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        compare_bar.addWidget(self.left_wc_label)
        compare_bar.addWidget(QLabel("  |  "))
        compare_bar.addWidget(self.right_wc_label)

        right_layout.addLayout(compare_bar)

        pane_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left pane: selected draft
        left_pane_widget = QWidget()
        left_pane_layout = QVBoxLayout(left_pane_widget)
        left_pane_layout.setContentsMargins(0, 0, 0, 0)
        self.left_pane_label = QLabel("Selected Draft")
        self.left_pane_label.setStyleSheet("font-weight: bold; font-size: 12px; padding: 2px;")
        left_pane_layout.addWidget(self.left_pane_label)

        self.left_pane = QTextEdit()
        self.left_pane.setReadOnly(True)
        self.left_pane.setFont(QFont("Segoe UI", 10))
        self.left_pane.setStyleSheet("""
            QTextEdit {
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 8px;
                background-color: #fefefe;
            }
        """)
        left_pane_layout.addWidget(self.left_pane)
        pane_splitter.addWidget(left_pane_widget)

        # Right pane: compare target
        right_pane_widget = QWidget()
        right_pane_layout = QVBoxLayout(right_pane_widget)
        right_pane_layout.setContentsMargins(0, 0, 0, 0)
        self.right_pane_label = QLabel("Current Draft (latest)")
        self.right_pane_label.setStyleSheet("font-weight: bold; font-size: 12px; padding: 2px;")
        right_pane_layout.addWidget(self.right_pane_label)

        self.right_pane = QTextEdit()
        self.right_pane.setReadOnly(True)
        self.right_pane.setFont(QFont("Segoe UI", 10))
        self.right_pane.setStyleSheet("""
            QTextEdit {
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 8px;
                background-color: #fefefe;
            }
        """)
        right_pane_layout.addWidget(self.right_pane)
        pane_splitter.addWidget(right_pane_widget)

        right_layout.addWidget(pane_splitter)
        main_splitter.addWidget(right_panel)

        main_splitter.setSizes([260, 740])
        layout.addWidget(main_splitter)

        # Bottom close button
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 24px; border-radius: 6px; font-size: 13px;
                background-color: #e5e7eb; border: none;
            }
            QPushButton:hover { background-color: #d1d5db; }
        """)
        close_btn.clicked.connect(self.close)
        bottom_bar.addWidget(close_btn)
        layout.addLayout(bottom_bar)

    def _draft_label_for_rev(self, rev: ChapterRevision) -> str:
        """Build a descriptive label for a draft entry in the list."""
        age = _age_label(rev.timestamp)
        wc = rev.word_count or (len(rev.content.split()) if rev.content else 0)
        date_str = rev.timestamp.strftime("%b %d, %Y %H:%M") if rev.timestamp else ""
        notes_str = f" - {rev.notes}" if rev.notes else ""
        active = " [ACTIVE]" if rev.revision_number == self.chapter.active_revision_number else ""
        return f"Draft #{rev.revision_number}{notes_str}{active}\n{date_str}  ({age})  |  {wc} words"

    def _draft_combo_label(self, rev: ChapterRevision) -> str:
        """Build a label for the compare combo."""
        age = _age_label(rev.timestamp)
        notes_str = f" - {rev.notes}" if rev.notes else ""
        return f"Draft #{rev.revision_number}{notes_str} ({age})"

    def _populate_revision_list(self):
        self.revision_list.clear()

        # Current draft (virtual entry)
        wc = len(self.current_content.split()) if self.current_content else 0
        current_item = QListWidgetItem(f"Current Draft (latest)\n{wc} words")
        current_item.setData(Qt.ItemDataRole.UserRole, "current")
        self.revision_list.addItem(current_item)

        # Saved drafts (newest first)
        for rev in reversed(self.chapter.revisions):
            label = self._draft_label_for_rev(rev)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, rev.revision_number)
            self.revision_list.addItem(item)

    def _populate_compare_combo(self):
        self.compare_combo.clear()
        self.compare_combo.addItem("Current Draft (latest)", "current")

        for rev in reversed(self.chapter.revisions):
            self.compare_combo.addItem(
                self._draft_combo_label(rev),
                rev.revision_number
            )

    def _get_revision_content(self, identifier) -> tuple:
        """Get (plain_text, html_content) for a draft identifier."""
        if identifier == "current":
            return self.current_content, self.current_html

        for rev in self.chapter.revisions:
            if rev.revision_number == identifier:
                # Try loading from disk if content is empty
                if not rev.content and rev.file_path:
                    loaded = self.chapter.load_revision_content(
                        self.project_dir, rev.revision_number)
                    if loaded is not None:
                        rev.content = loaded
                return rev.content, rev.html_content

        return "", ""

    def _word_count(self, text: str) -> int:
        return len(text.split()) if text and text.strip() else 0

    def _pane_title(self, identifier) -> str:
        """Build a pane title with age info."""
        if identifier == "current":
            return "Current Draft (latest)"
        for rev in self.chapter.revisions:
            if rev.revision_number == identifier:
                age = _age_label(rev.timestamp)
                notes = f" - {rev.notes}" if rev.notes else ""
                return f"Draft #{identifier}{notes}  ({age})"
        return f"Draft #{identifier}"

    def _on_revision_selected(self, row: int):
        if row < 0:
            return
        item = self.revision_list.item(row)
        if not item:
            return

        identifier = item.data(Qt.ItemDataRole.UserRole)
        content, html = self._get_revision_content(identifier)

        self.left_pane_label.setText(self._pane_title(identifier))

        if html:
            self.left_pane.setHtml(html)
        else:
            self.left_pane.setPlainText(content)

        self.left_wc_label.setText(f"Selected: {self._word_count(content)} words")

    def _on_compare_changed(self, index: int):
        if index < 0:
            return

        identifier = self.compare_combo.itemData(index)
        content, html = self._get_revision_content(identifier)

        self.right_pane_label.setText(self._pane_title(identifier))

        if html:
            self.right_pane.setHtml(html)
        else:
            self.right_pane.setPlainText(content)

        self.right_wc_label.setText(f"Compare: {self._word_count(content)} words")

    def _create_blank_revision(self):
        notes, ok = QInputDialog.getText(
            self, "New Blank Draft",
            "Draft notes (optional):", text="Blank draft"
        )
        if not ok:
            return

        self.chapter.create_blank_revision(
            project_dir=self.project_dir,
            notes=notes or "Blank draft"
        )

        self._populate_revision_list()
        self._populate_compare_combo()
        self.revision_list.setCurrentRow(1)

    def _snapshot_current(self):
        notes, ok = QInputDialog.getText(
            self, "Snapshot Current Draft",
            "Draft notes (optional):"
        )
        if not ok:
            return

        self.chapter.add_revision(
            notes=notes,
            content=self.current_content,
            html_content=self.current_html,
            project_dir=self.project_dir
        )

        self._populate_revision_list()
        self._populate_compare_combo()

        QMessageBox.information(
            self, "Snapshot Saved",
            f"Current draft saved as Draft #{len(self.chapter.revisions)}."
        )

    def _edit_alongside_selected(self):
        """Open side-by-side editor with selected draft as reference."""
        row = self.revision_list.currentRow()
        if row < 0:
            return

        item = self.revision_list.item(row)
        identifier = item.data(Qt.ItemDataRole.UserRole)

        if identifier == "current":
            QMessageBox.information(
                self, "Already Current",
                "Select an older draft to edit alongside."
            )
            return

        self._edit_alongside_rev = identifier
        self.edit_alongside.emit(identifier)
        self.accept()

    def _restore_selected(self):
        row = self.revision_list.currentRow()
        if row < 0:
            return

        item = self.revision_list.item(row)
        identifier = item.data(Qt.ItemDataRole.UserRole)

        if identifier == "current":
            QMessageBox.information(self, "Already Current",
                                   "This is already the current draft.")
            return

        content, html = self._get_revision_content(identifier)

        reply = QMessageBox.question(
            self, "Restore Draft",
            f"Set Draft #{identifier} as the active draft?\n\n"
            "Your current draft will be auto-saved first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Auto-save current draft
        self.chapter.add_revision(
            notes="Auto-saved before restore",
            content=self.current_content,
            html_content=self.current_html,
            project_dir=self.project_dir
        )

        # Set selected as active
        self.chapter.set_active_revision(identifier, self.project_dir)
        self.current_content = self.chapter.content
        self.current_html = self.chapter.html_content
        self._restored = True
        self.revision_restored.emit(self.chapter.content, self.chapter.html_content)

        self._populate_revision_list()
        self._populate_compare_combo()

        QMessageBox.information(
            self, "Draft Restored",
            f"Draft #{identifier} is now the active draft.\n"
            "Your previous draft was auto-saved."
        )

    def _delete_selected(self):
        row = self.revision_list.currentRow()
        if row < 0:
            return

        item = self.revision_list.item(row)
        identifier = item.data(Qt.ItemDataRole.UserRole)

        if identifier == "current":
            QMessageBox.warning(self, "Cannot Delete",
                               "Cannot delete the current draft.")
            return

        if identifier == self.chapter.active_revision_number:
            QMessageBox.warning(self, "Cannot Delete",
                               "Cannot delete the active draft. Switch to another first.")
            return

        reply = QMessageBox.question(
            self, "Delete Draft",
            f"Permanently delete Draft #{identifier}?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Delete file from disk
        for rev in self.chapter.revisions:
            if rev.revision_number == identifier and rev.file_path:
                full_path = self.project_dir / rev.file_path
                if full_path.exists():
                    full_path.unlink()

        self.chapter.revisions = [
            r for r in self.chapter.revisions
            if r.revision_number != identifier
        ]

        self._populate_revision_list()
        self._populate_compare_combo()

    @property
    def was_restored(self) -> bool:
        return self._restored

    @property
    def edit_alongside_revision(self):
        return self._edit_alongside_rev
