"""Mythology builder widget with faction associations."""

from typing import List, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QLabel, QLineEdit, QTextEdit, QFormLayout, QComboBox, QGroupBox,
    QDialog, QDialogButtonBox, QListWidgetItem, QCheckBox, QScrollArea
)
from PyQt6.QtCore import pyqtSignal, Qt

from src.models.worldbuilding_objects import Myth, Faction


class MythEditor(QDialog):
    """Dialog for editing a single myth."""

    def __init__(self, myth: Optional[Myth] = None, available_factions: List[Faction] = None, parent=None):
        """Initialize myth editor.

        Args:
            myth: Myth to edit (None for new myth)
            available_factions: List of all available factions for selection
            parent: Parent widget
        """
        super().__init__(parent)
        self.myth = myth or Myth(
            id="",
            name="",
            myth_type="Creation",
            associated_factions=[],
            key_figures=[],
            time_period="",
            moral_lesson="",
            description="",
            full_text=""
        )
        self.available_factions = available_factions or []
        self._init_ui()
        if myth:
            self._load_myth()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Myth Editor")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)  # Reduced for laptop compatibility

        layout = QVBoxLayout(self)

        # Create scrollable area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        # Basic info
        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name of the myth or legend")
        basic_layout.addRow("Myth Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "Creation", "Hero", "Prophecy", "Deity", "Origin",
            "Epic", "Legend", "Folklore", "Cosmology", "Apocalypse"
        ])
        basic_layout.addRow("Type:", self.type_combo)

        self.time_period_edit = QLineEdit()
        self.time_period_edit.setPlaceholderText("e.g., 'Ancient Times', 'First Age'")
        basic_layout.addRow("Time Period:", self.time_period_edit)

        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)

        # Associated factions
        faction_group = QGroupBox("Associated Factions")
        faction_group.setToolTip("Select which factions believe in or are associated with this myth")
        faction_layout = QVBoxLayout()

        faction_help = QLabel("Select the factions that believe in this myth:")
        faction_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        faction_layout.addWidget(faction_help)

        # Faction checkboxes
        self.faction_checkboxes = {}
        if self.available_factions:
            for faction in self.available_factions:
                checkbox = QCheckBox(f"{faction.name} ({faction.faction_type.value})")
                checkbox.setProperty("faction_id", faction.id)
                self.faction_checkboxes[faction.id] = checkbox
                faction_layout.addWidget(checkbox)
        else:
            no_factions_label = QLabel("No factions available. Create factions first in the Factions tab.")
            no_factions_label.setStyleSheet("color: #ef4444; font-style: italic;")
            faction_layout.addWidget(no_factions_label)

        faction_group.setLayout(faction_layout)
        scroll_layout.addWidget(faction_group)

        # Key figures
        figures_group = QGroupBox("Key Figures")
        figures_layout = QVBoxLayout()

        figures_help = QLabel("Deities, heroes, or characters in this myth (one per line):")
        figures_help.setStyleSheet("color: #6b7280; font-size: 11px;")
        figures_layout.addWidget(figures_help)

        self.key_figures_edit = QTextEdit()
        self.key_figures_edit.setPlaceholderText("e.g.:\nZeus\nAthena\nPrometheus")
        self.key_figures_edit.setMaximumHeight(100)
        figures_layout.addWidget(self.key_figures_edit)

        figures_group.setLayout(figures_layout)
        scroll_layout.addWidget(figures_group)

        # Moral lesson
        moral_group = QGroupBox("Moral Lesson")
        moral_layout = QVBoxLayout()

        self.moral_edit = QTextEdit()
        self.moral_edit.setPlaceholderText("What moral or lesson does this myth teach?")
        self.moral_edit.setMaximumHeight(80)
        moral_layout.addWidget(self.moral_edit)

        moral_group.setLayout(moral_layout)
        scroll_layout.addWidget(moral_group)

        # Description
        desc_group = QGroupBox("Description")
        desc_layout = QVBoxLayout()

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Brief summary of the myth...")
        self.description_edit.setMaximumHeight(100)
        desc_layout.addWidget(self.description_edit)

        desc_group.setLayout(desc_layout)
        scroll_layout.addWidget(desc_group)

        # Full text
        text_group = QGroupBox("Full Myth Text")
        text_layout = QVBoxLayout()

        self.full_text_edit = QTextEdit()
        self.full_text_edit.setPlaceholderText("The complete myth or legend text...")
        self.full_text_edit.setMinimumHeight(150)
        text_layout.addWidget(self.full_text_edit)

        text_group.setLayout(text_layout)
        scroll_layout.addWidget(text_group)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_myth(self):
        """Load myth data into form."""
        self.name_edit.setText(self.myth.name)

        # Set type
        index = self.type_combo.findText(self.myth.myth_type)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)

        self.time_period_edit.setText(self.myth.time_period or "")

        # Check faction checkboxes
        for faction_id in self.myth.associated_factions:
            if faction_id in self.faction_checkboxes:
                self.faction_checkboxes[faction_id].setChecked(True)

        # Key figures
        if self.myth.key_figures:
            self.key_figures_edit.setPlainText("\n".join(self.myth.key_figures))

        self.moral_edit.setPlainText(self.myth.moral_lesson)
        self.description_edit.setPlainText(self.myth.description)
        self.full_text_edit.setPlainText(self.myth.full_text)

    def _save(self):
        """Save myth data."""
        name = self.name_edit.text().strip()
        if not name:
            return  # Don't save without name

        # Generate ID from name if needed
        if not self.myth.id:
            self.myth.id = name.lower().replace(" ", "-").replace("'", "")

        self.myth.name = name
        self.myth.myth_type = self.type_combo.currentText()
        self.myth.time_period = self.time_period_edit.text().strip()

        # Get selected factions
        self.myth.associated_factions = [
            faction_id for faction_id, checkbox in self.faction_checkboxes.items()
            if checkbox.isChecked()
        ]

        # Get key figures
        figures_text = self.key_figures_edit.toPlainText().strip()
        self.myth.key_figures = [f.strip() for f in figures_text.split("\n") if f.strip()]

        self.myth.moral_lesson = self.moral_edit.toPlainText().strip()
        self.myth.description = self.description_edit.toPlainText().strip()
        self.myth.full_text = self.full_text_edit.toPlainText().strip()

        self.accept()

    def get_myth(self) -> Myth:
        """Get the edited myth."""
        return self.myth


class MythologyBuilderWidget(QWidget):
    """Widget for managing mythology and legends."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize mythology builder widget."""
        super().__init__()
        self.myths: List[Myth] = []
        self.available_factions: List[Faction] = []
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QHBoxLayout()
        title = QLabel("📖 Mythology & Legends")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header.addWidget(title)

        header.addStretch()

        subtitle = QLabel("Myths, legends, and belief systems")
        subtitle.setStyleSheet("font-size: 12px; color: #6b7280;")
        header.addWidget(subtitle)

        layout.addLayout(header)

        # Help text
        help_text = QLabel(
            "Create myths and legends for your world. Associate them with factions "
            "to show which cultures believe in which stories."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #6b7280; font-size: 11px; margin-bottom: 8px;")
        layout.addWidget(help_text)

        # Toolbar
        toolbar = QHBoxLayout()

        self.add_btn = QPushButton("➕ Add Myth")
        self.add_btn.clicked.connect(self._add_myth)
        toolbar.addWidget(self.add_btn)

        self.edit_btn = QPushButton("✏️ Edit")
        self.edit_btn.clicked.connect(self._edit_myth)
        self.edit_btn.setEnabled(False)
        toolbar.addWidget(self.edit_btn)

        self.remove_btn = QPushButton("🗑️ Remove")
        self.remove_btn.clicked.connect(self._remove_myth)
        self.remove_btn.setEnabled(False)
        toolbar.addWidget(self.remove_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Myth list
        self.myth_list = QListWidget()
        self.myth_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.myth_list.itemDoubleClicked.connect(self._edit_myth)
        layout.addWidget(self.myth_list)

    def set_available_factions(self, factions: List[Faction]):
        """Set available factions for myth association.

        Args:
            factions: List of all available factions
        """
        self.available_factions = factions

    def load_myths(self, myths: List[Myth]):
        """Load myths into widget.

        Args:
            myths: List of myths to load
        """
        self.myths = myths
        self._update_list()

    def get_myths(self) -> List[Myth]:
        """Get all myths.

        Returns:
            List of myths
        """
        return self.myths

    def _update_list(self):
        """Update myth list display."""
        self.myth_list.clear()

        for myth in self.myths:
            # Get faction names for display
            faction_names = []
            for faction_id in myth.associated_factions:
                faction = next((f for f in self.available_factions if f.id == faction_id), None)
                if faction:
                    faction_names.append(faction.name)

            # Create display text
            factions_text = f" • {', '.join(faction_names)}" if faction_names else ""
            item_text = f"{myth.name} ({myth.myth_type}){factions_text}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, myth.id)
            self.myth_list.addItem(item)

    def _on_selection_changed(self):
        """Handle selection change."""
        has_selection = bool(self.myth_list.selectedItems())
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def _add_myth(self):
        """Add new myth."""
        editor = MythEditor(available_factions=self.available_factions, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            myth = editor.get_myth()
            self.myths.append(myth)
            self._update_list()
            self.content_changed.emit()

    def _edit_myth(self):
        """Edit selected myth."""
        items = self.myth_list.selectedItems()
        if not items:
            return

        myth_id = items[0].data(Qt.ItemDataRole.UserRole)
        myth = next((m for m in self.myths if m.id == myth_id), None)
        if not myth:
            return

        editor = MythEditor(myth=myth, available_factions=self.available_factions, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_list()
            self.content_changed.emit()

    def _remove_myth(self):
        """Remove selected myth."""
        items = self.myth_list.selectedItems()
        if not items:
            return

        myth_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.myths = [m for m in self.myths if m.id != myth_id]
        self._update_list()
        self.content_changed.emit()
