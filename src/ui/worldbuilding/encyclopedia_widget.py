"""Worldbuilding Encyclopedia — a browsable, searchable knowledge base.

Ships with a base of worldbuilding reference knowledge (government types,
magic systems, terrain, cultural elements, etc.) and allows users to add
their own project-specific entries.
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QComboBox, QSplitter, QMessageBox, QInputDialog, QDialog,
    QFormLayout, QDialogButtonBox
)
from PyQt6.QtCore import pyqtSignal, Qt


def _load_base_encyclopedia() -> dict:
    """Load the bundled encyclopedia data."""
    data_path = Path(__file__).parent.parent.parent / "data" / "worldbuilding_encyclopedia.json"
    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"version": 1, "categories": []}


class _EntryDialog(QDialog):
    """Dialog for adding/editing a custom encyclopedia entry."""

    def __init__(self, parent=None, entry: dict = None, categories: list = None):
        super().__init__(parent)
        self.setWindowTitle("Encyclopedia Entry" if not entry else "Edit Entry")
        self.setMinimumWidth(450)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Entry title...")
        form.addRow("Title:", self.title_edit)

        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        if categories:
            for c in categories:
                self.category_combo.addItem(c)
        self.category_combo.addItem("Custom")
        form.addRow("Category:", self.category_combo)

        self.summary_edit = QLineEdit()
        self.summary_edit.setPlaceholderText("One-line summary...")
        form.addRow("Summary:", self.summary_edit)

        layout.addLayout(form)

        layout.addWidget(QLabel("Description:"))
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Detailed description...")
        self.description_edit.setMaximumHeight(120)
        layout.addWidget(self.description_edit)

        layout.addWidget(QLabel("Writing Tips:"))
        self.tips_edit = QTextEdit()
        self.tips_edit.setPlaceholderText("How to use this in your writing...")
        self.tips_edit.setMaximumHeight(80)
        layout.addWidget(self.tips_edit)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("Tags (comma-separated)...")
        layout.addWidget(QLabel("Tags:"))
        layout.addWidget(self.tags_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if entry:
            self.title_edit.setText(entry.get("title", ""))
            self.summary_edit.setText(entry.get("summary", ""))
            self.description_edit.setPlainText(entry.get("description", ""))
            self.tips_edit.setPlainText(entry.get("writing_tips", ""))
            self.tags_edit.setText(", ".join(entry.get("tags", [])))
            cat = entry.get("category", "Custom")
            idx = self.category_combo.findText(cat)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            else:
                self.category_combo.setCurrentText(cat)

    def get_entry(self) -> dict:
        return {
            "title": self.title_edit.text().strip(),
            "category": self.category_combo.currentText().strip(),
            "summary": self.summary_edit.text().strip(),
            "description": self.description_edit.toPlainText().strip(),
            "writing_tips": self.tips_edit.toPlainText().strip(),
            "tags": [t.strip() for t in self.tags_edit.text().split(",") if t.strip()],
            "is_custom": True,
        }


class EncyclopediaWidget(QWidget):
    """Browsable, searchable worldbuilding encyclopedia."""

    content_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._base_data = _load_base_encyclopedia()
        self._custom_entries: List[Dict[str, str]] = []
        self._all_entries: List[dict] = []  # Flattened base + custom
        self._filtered: List[dict] = []
        self._init_ui()
        self._rebuild_entries()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("<b>Worldbuilding Encyclopedia</b>"))
        header_layout.addStretch()

        add_btn = QPushButton("+ Add Entry")
        add_btn.setToolTip("Add your own encyclopedia entry")
        add_btn.clicked.connect(self._add_entry)
        header_layout.addWidget(add_btn)

        layout.addLayout(header_layout)

        # Search + filter bar
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(4)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search entries...")
        self.search_edit.textChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.search_edit, stretch=2)

        self.category_filter = QComboBox()
        self.category_filter.addItem("All Categories")
        self.category_filter.currentTextChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.category_filter, stretch=1)

        layout.addLayout(filter_layout)

        # Splitter: entry list | detail view
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Entry list
        self.entry_list = QListWidget()
        self.entry_list.currentRowChanged.connect(self._on_entry_selected)
        splitter.addWidget(self.entry_list)

        # Detail view
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(8, 4, 4, 4)
        detail_layout.setSpacing(4)

        self.detail_title = QLabel("")
        self.detail_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.detail_title.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)

        self.detail_summary = QLabel("")
        self.detail_summary.setStyleSheet("font-size: 11px; color: #6b7280; font-style: italic;")
        self.detail_summary.setWordWrap(True)
        detail_layout.addWidget(self.detail_summary)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        detail_layout.addWidget(self.detail_text)

        # Edit/Delete buttons for custom entries
        btn_row = QHBoxLayout()
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setVisible(False)
        self.edit_btn.clicked.connect(self._edit_entry)
        btn_row.addWidget(self.edit_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setVisible(False)
        self.delete_btn.clicked.connect(self._delete_entry)
        btn_row.addWidget(self.delete_btn)

        btn_row.addStretch()
        detail_layout.addLayout(btn_row)

        splitter.addWidget(detail_widget)
        splitter.setSizes([250, 450])

        layout.addWidget(splitter, stretch=1)

    def _rebuild_entries(self):
        """Flatten base + custom entries into a single searchable list."""
        self._all_entries = []
        categories = set()

        # Base entries
        for cat in self._base_data.get("categories", []):
            cat_name = cat["name"]
            categories.add(cat_name)
            for entry in cat.get("entries", []):
                entry_copy = dict(entry)
                entry_copy["category"] = cat_name
                entry_copy["is_custom"] = False
                self._all_entries.append(entry_copy)

        # Custom entries
        for entry in self._custom_entries:
            entry_copy = dict(entry)
            entry_copy.setdefault("is_custom", True)
            cat_name = entry_copy.get("category", "Custom")
            categories.add(cat_name)
            self._all_entries.append(entry_copy)

        # Update category filter
        current = self.category_filter.currentText()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("All Categories")
        for c in sorted(categories):
            self.category_filter.addItem(c)
        idx = self.category_filter.findText(current)
        if idx >= 0:
            self.category_filter.setCurrentIndex(idx)
        self.category_filter.blockSignals(False)

        self._apply_filter()

    def _apply_filter(self, _=None):
        """Filter entries by search text and category."""
        query = self.search_edit.text().strip().lower()
        cat = self.category_filter.currentText()

        self._filtered = []
        for entry in self._all_entries:
            # Category filter
            if cat != "All Categories" and entry.get("category") != cat:
                continue
            # Search filter
            if query:
                searchable = " ".join([
                    entry.get("title", ""),
                    entry.get("summary", ""),
                    entry.get("description", ""),
                    " ".join(entry.get("tags", [])),
                ]).lower()
                if query not in searchable:
                    continue
            self._filtered.append(entry)

        self.entry_list.clear()
        for entry in self._filtered:
            prefix = "* " if entry.get("is_custom") else ""
            item = QListWidgetItem(f"{prefix}{entry['title']}")
            if entry.get("is_custom"):
                item.setToolTip("Custom entry (project-specific)")
            self.entry_list.addItem(item)

    def _on_entry_selected(self, row: int):
        """Show detail for selected entry."""
        if row < 0 or row >= len(self._filtered):
            self.detail_title.setText("")
            self.detail_summary.setText("")
            self.detail_text.clear()
            self.edit_btn.setVisible(False)
            self.delete_btn.setVisible(False)
            return

        entry = self._filtered[row]
        self.detail_title.setText(entry.get("title", ""))
        self.detail_summary.setText(
            f"{entry.get('category', '')} — {entry.get('summary', '')}"
        )

        # Build rich detail text
        parts = []
        if entry.get("description"):
            parts.append(entry["description"])

        if entry.get("examples"):
            parts.append("\nExamples:")
            for ex in entry["examples"]:
                parts.append(f"  - {ex}")

        if entry.get("writing_tips"):
            parts.append(f"\nWriting Tips:\n{entry['writing_tips']}")

        if entry.get("tags"):
            parts.append(f"\nTags: {', '.join(entry['tags'])}")

        self.detail_text.setPlainText("\n".join(parts))

        is_custom = entry.get("is_custom", False)
        self.edit_btn.setVisible(is_custom)
        self.delete_btn.setVisible(is_custom)

    def _get_category_names(self) -> list:
        """Get all category names."""
        cats = set()
        for cat in self._base_data.get("categories", []):
            cats.add(cat["name"])
        for entry in self._custom_entries:
            cats.add(entry.get("category", "Custom"))
        return sorted(cats)

    def _add_entry(self):
        """Add a custom encyclopedia entry."""
        dialog = _EntryDialog(self, categories=self._get_category_names())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            entry = dialog.get_entry()
            if entry.get("title"):
                self._custom_entries.append(entry)
                self._rebuild_entries()
                self.content_changed.emit()

    def _edit_entry(self):
        """Edit the selected custom entry."""
        row = self.entry_list.currentRow()
        if row < 0 or row >= len(self._filtered):
            return
        entry = self._filtered[row]
        if not entry.get("is_custom"):
            return

        # Find in custom list
        idx = None
        for i, e in enumerate(self._custom_entries):
            if e.get("title") == entry.get("title"):
                idx = i
                break
        if idx is None:
            return

        dialog = _EntryDialog(self, entry=entry, categories=self._get_category_names())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._custom_entries[idx] = dialog.get_entry()
            self._rebuild_entries()
            self.content_changed.emit()

    def _delete_entry(self):
        """Delete the selected custom entry."""
        row = self.entry_list.currentRow()
        if row < 0 or row >= len(self._filtered):
            return
        entry = self._filtered[row]
        if not entry.get("is_custom"):
            return

        reply = QMessageBox.question(
            self, "Delete Entry",
            f"Delete '{entry.get('title', '')}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._custom_entries = [
            e for e in self._custom_entries
            if e.get("title") != entry.get("title")
        ]
        self._rebuild_entries()
        self.content_changed.emit()

    # --- Data load/save ---

    def load_custom_entries(self, entries: List[Dict[str, str]]):
        """Load project-specific custom entries."""
        self._custom_entries = list(entries) if entries else []
        self._rebuild_entries()

    def get_custom_entries(self) -> List[Dict[str, str]]:
        """Get custom entries for project save."""
        return self._custom_entries

    def get_all_entries_for_rag(self) -> List[dict]:
        """Get all entries (base + custom) for RAG indexing."""
        return list(self._all_entries)
