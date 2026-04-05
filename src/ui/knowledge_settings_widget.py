"""NLTK-downloader-style UI for managing knowledge base datasets.

Shows a package list with status, size estimates, disk usage,
and allows downloading, removing, and importing custom datasets.
"""

from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QMessageBox, QLineEdit, QTreeWidget, QTreeWidgetItem,
    QCheckBox, QFileDialog, QHeaderView
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QColor
from typing import Optional


class _DownloadWorker(QThread):
    """Background worker for downloading/importing a dataset."""

    progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(str, int)  # dataset_id, article_count
    error = pyqtSignal(str)

    def __init__(self, dataset_id: str, api_key: str = "",
                 custom_file: str = "", custom_source: str = "",
                 project=None):
        super().__init__()
        self.dataset_id = dataset_id
        self.api_key = api_key
        self.custom_file = custom_file
        self.custom_source = custom_source
        self.project = project

    def run(self):
        try:
            from src.knowledge.knowledge_store import get_knowledge_store

            store = get_knowledge_store()

            if self.custom_file:
                # Import a user-provided file
                from src.knowledge.dataset_importer import import_custom_file
                articles = import_custom_file(
                    self.custom_file, self.custom_source,
                    progress=lambda m, c, t: self.progress.emit(m, c, t)
                )
                source_name = self.custom_source or Path(self.custom_file).stem
                store.remove_source(source_name)
                store.add_articles_batch(articles)
                size = Path(self.custom_file).stat().st_size / (1024 * 1024)
                store.set_source_status(source_name, "installed", len(articles), size)
                self.finished.emit(source_name, len(articles))
            else:
                # Import a registered dataset
                from src.knowledge.dataset_registry import get_dataset_by_id
                from src.knowledge.dataset_importer import import_dataset

                info = get_dataset_by_id(self.dataset_id)
                if not info:
                    self.error.emit(f"Unknown dataset: {self.dataset_id}")
                    return

                store.set_source_status(info.id, "downloading")
                self.progress.emit(f"Downloading {info.name}...", 0, 1)

                articles = import_dataset(
                    info, api_key=self.api_key,
                    progress=lambda m, c, t: self.progress.emit(m, c, t),
                    project=self.project
                )

                self.progress.emit("Indexing...", 0, 1)
                store.remove_source(info.id)
                store.add_articles_batch(articles)
                store.set_source_status(
                    info.id, "installed", len(articles), info.size_estimate_mb
                )
                self.finished.emit(info.id, len(articles))

        except Exception as e:
            self.error.emit(str(e))


class KnowledgeSettingsWidget(QWidget):
    """NLTK-downloader-style UI for managing knowledge base datasets."""

    def __init__(self):
        super().__init__()
        self._worker: Optional[_DownloadWorker] = None
        self._project = None
        self._init_ui()
        self._refresh()

    def set_project(self, project):
        """Set the current project (needed for project-specific downloads)."""
        self._project = project

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Header + enable toggle
        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("<b>Knowledge Base Manager</b>"))
        header_row.addStretch()

        self.enable_cb = QCheckBox("Enable knowledge base for AI tools")
        self.enable_cb.setChecked(True)
        self.enable_cb.setToolTip(
            "When enabled, AI thesaurus, rephrase, chat, and worldbuilding agents\n"
            "search downloaded datasets for relevant reference material."
        )
        header_row.addWidget(self.enable_cb)
        layout.addLayout(header_row)

        desc = QLabel(
            "Download reference datasets for AI-powered writing assistance. "
            "The AI tools search these via RAG when generating suggestions."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(desc)

        # Disk usage bar
        usage_row = QHBoxLayout()
        usage_row.addWidget(QLabel("Disk usage:"))
        self.usage_label = QLabel("calculating...")
        self.usage_label.setStyleSheet("font-size: 11px; color: #6b7280;")
        usage_row.addWidget(self.usage_label)
        usage_row.addStretch()
        layout.addLayout(usage_row)

        # Dataset tree — NLTK-downloader style
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Dataset", "Status", "Articles", "Size (MB)"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree, stretch=1)

        # Action buttons
        btn_row = QHBoxLayout()

        self.download_btn = QPushButton("Download Selected")
        self.download_btn.clicked.connect(self._download_selected)
        btn_row.addWidget(self.download_btn)

        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(self.remove_btn)

        btn_row.addStretch()

        import_btn = QPushButton("Import Custom File...")
        import_btn.setToolTip("Import a CSV, TSV, or JSON file as a custom knowledge source")
        import_btn.clicked.connect(self._import_custom)
        btn_row.addWidget(import_btn)

        layout.addLayout(btn_row)

        # Britannica API key (shown when Britannica is selected)
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("Britannica API Key:"))
        self.brit_key_edit = QLineEdit()
        self.brit_key_edit.setPlaceholderText("From encyclopaediaapi.com (free, non-commercial)")
        self.brit_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_row.addWidget(self.brit_key_edit)
        layout.addLayout(key_row)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(6)
        layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("font-size: 11px; color: #6b7280;")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

    def _refresh(self):
        """Rebuild the dataset tree from the registry and store status."""
        from src.knowledge.dataset_registry import get_datasets_by_category
        from src.knowledge.knowledge_store import get_knowledge_store

        store = get_knowledge_store()
        statuses = store.get_source_status()

        self.tree.clear()
        total_size = 0.0

        # Built-in encyclopedia (always first)
        builtin = QTreeWidgetItem(self.tree)
        builtin.setText(0, "Built-in Worldbuilding Encyclopedia")
        builtin.setText(1, "Always available")
        builtin.setText(2, "62")
        builtin.setText(3, "< 1")
        builtin.setForeground(1, QColor("#059669"))
        builtin.setFlags(builtin.flags() & ~Qt.ItemFlag.ItemIsSelectable)

        # Registered datasets by category
        by_cat = get_datasets_by_category()
        for cat_name, datasets in sorted(by_cat.items()):
            cat_item = QTreeWidgetItem(self.tree)
            cat_item.setText(0, cat_name)
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)

            for ds in datasets:
                item = QTreeWidgetItem(cat_item)
                item.setData(0, Qt.ItemDataRole.UserRole, ds.id)
                item.setText(0, ds.name)
                item.setToolTip(0, ds.description)

                st = statuses.get(ds.id, {})
                if st.get("status") == "installed":
                    count = st.get("article_count", 0)
                    size = st.get("size_mb", ds.size_estimate_mb)
                    item.setText(1, "Installed")
                    item.setText(2, f"{count:,}")
                    item.setText(3, f"{size:.1f}")
                    item.setForeground(1, QColor("#059669"))
                    total_size += size
                else:
                    item.setText(1, "Not installed")
                    item.setText(2, "—")
                    item.setText(3, f"~{ds.size_estimate_mb:.0f}")
                    item.setForeground(1, QColor("#9ca3af"))

                if ds.requires_package:
                    item.setToolTip(1, f"Requires: pip install {ds.requires_package}")

        # Custom datasets from the store
        custom_sources = {
            name: info for name, info in statuses.items()
            if name not in {ds.id for cat in by_cat.values() for ds in cat}
            and info.get("status") == "installed"
        }
        if custom_sources:
            custom_cat = QTreeWidgetItem(self.tree)
            custom_cat.setText(0, "Custom Imports")
            custom_cat.setFlags(custom_cat.flags() & ~Qt.ItemFlag.ItemIsSelectable)

            for name, info in custom_sources.items():
                item = QTreeWidgetItem(custom_cat)
                item.setData(0, Qt.ItemDataRole.UserRole, name)
                item.setText(0, name)
                item.setText(1, "Installed")
                count = info.get("article_count", 0)
                size = info.get("size_mb", 0)
                item.setText(2, f"{count:,}")
                item.setText(3, f"{size:.1f}")
                item.setForeground(1, QColor("#059669"))
                total_size += size

        self.tree.expandAll()

        # Update disk usage
        db_path = store.db_path
        db_size = db_path.stat().st_size / (1024 * 1024) if db_path.exists() else 0
        self.usage_label.setText(
            f"{db_size:.1f} MB on disk ({store.get_article_count():,} total articles)"
        )

    def _get_selected_dataset_id(self) -> Optional[str]:
        """Get the dataset ID of the selected tree item."""
        item = self.tree.currentItem()
        if not item:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _download_selected(self):
        """Download the selected dataset."""
        ds_id = self._get_selected_dataset_id()
        if not ds_id:
            QMessageBox.information(self, "No Selection", "Select a dataset to download.")
            return

        if self._worker and self._worker.isRunning():
            QMessageBox.warning(self, "Busy", "A download is already in progress.")
            return

        from src.knowledge.dataset_registry import get_dataset_by_id
        info = get_dataset_by_id(ds_id)

        api_key = ""
        if info and info.requires_api_key:
            api_key = self.brit_key_edit.text().strip()
            if not api_key:
                QMessageBox.warning(self, "API Key Required",
                                    f"{info.name} requires an API key.")
                return

        if info and info.requires_package:
            try:
                __import__(info.requires_package)
            except ImportError:
                QMessageBox.warning(
                    self, "Package Required",
                    f"This dataset requires the '{info.requires_package}' package.\n\n"
                    f"Install it with: pip install {info.requires_package}"
                )
                return

        self._start_worker(ds_id, api_key=api_key)

    def _remove_selected(self):
        """Remove the selected dataset."""
        ds_id = self._get_selected_dataset_id()
        if not ds_id:
            QMessageBox.information(self, "No Selection", "Select a dataset to remove.")
            return

        reply = QMessageBox.question(
            self, "Remove Dataset",
            f"Remove all articles from '{ds_id}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from src.knowledge.knowledge_store import get_knowledge_store
        store = get_knowledge_store()
        store.remove_source(ds_id)
        self._refresh()

    def _import_custom(self):
        """Import a custom CSV/TSV/JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Knowledge File", "",
            "Data Files (*.csv *.tsv *.json *.tab);;All Files (*)"
        )
        if not file_path:
            return

        source_name = Path(file_path).stem
        self._start_worker("__custom__", custom_file=file_path, custom_source=source_name)

    def _start_worker(self, dataset_id: str, api_key: str = "",
                      custom_file: str = "", custom_source: str = ""):
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText("Starting...")
        self.progress_label.setVisible(True)
        self.download_btn.setEnabled(False)

        self._worker = _DownloadWorker(
            dataset_id, api_key=api_key,
            custom_file=custom_file, custom_source=custom_source,
            project=self._project
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, message: str, current: int, total: int):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
        self.progress_label.setText(message)

    def _on_finished(self, source: str, count: int):
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.download_btn.setEnabled(True)
        self._refresh()
        QMessageBox.information(self, "Import Complete",
                                f"Imported {count:,} articles from '{source}'.")

    def _on_error(self, msg: str):
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.download_btn.setEnabled(True)
        QMessageBox.warning(self, "Import Failed", f"Error: {msg}")

    # --- Settings persistence ---

    def get_britannica_key(self) -> str:
        return self.brit_key_edit.text().strip()

    def set_britannica_key(self, key: str):
        self.brit_key_edit.setText(key or "")

    def is_knowledge_enabled(self) -> bool:
        return self.enable_cb.isChecked()

    def set_knowledge_enabled(self, enabled: bool):
        self.enable_cb.setChecked(enabled)
