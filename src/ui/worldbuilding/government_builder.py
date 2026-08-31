"""Builder for systems of GOVERNMENT — the administrative machinery
of a faction: its type, tiers, agencies/ministries, and how leaders
are chosen. Complements the Politics builder (parties + branches)."""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QLabel, QLineEdit, QTextEdit, QVBoxLayout,
    QWidget,
)

from src.models.worldbuilding_objects import (
    GovernmentAgency, GovernmentSystem,
)
from src.ui.worldbuilding._system_builder_base import (
    StringListWidget, SubRecordList, SystemBuilderBase,
    populate_faction_combo,
)


class GovernmentSystemEditor(QWidget):
    """Editor for a single government system."""

    content_changed = pyqtSignal()

    def __init__(self, system: GovernmentSystem,
                 available_factions: Optional[List] = None):
        super().__init__()
        self.system = system
        self.available_factions = available_factions or []
        self._init_ui()
        self._load()

    def set_available_factions(self, factions: List) -> None:
        self.available_factions = factions or []
        populate_faction_combo(
            self.faction_combo, self.available_factions,
            self.system.faction_id)

    def _init_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        self.faction_combo = QComboBox()
        self.faction_combo.currentIndexChanged.connect(
            lambda _: self.content_changed.emit())
        form.addRow("Associated Faction:", self.faction_combo)

        self.type_edit = QLineEdit()
        self.type_edit.setPlaceholderText(
            "federal republic, absolute monarchy, council, "
            "technocracy, theocracy...")
        self.type_edit.textChanged.connect(self.content_changed.emit)
        form.addRow("Government Type:", self.type_edit)

        self.structure_edit = QTextEdit()
        self.structure_edit.setMaximumHeight(70)
        self.structure_edit.setPlaceholderText(
            "How power is distributed — centralized vs federal, etc.")
        self.structure_edit.textChanged.connect(
            self.content_changed.emit)
        form.addRow("Structure:", self.structure_edit)

        self.selection_edit = QLineEdit()
        self.selection_edit.setPlaceholderText(
            "succession, election, appointment, lottery...")
        self.selection_edit.textChanged.connect(
            self.content_changed.emit)
        form.addRow("Leadership Selection:", self.selection_edit)

        self.seat_edit = QLineEdit()
        self.seat_edit.setPlaceholderText("capital / seat of power")
        self.seat_edit.textChanged.connect(self.content_changed.emit)
        form.addRow("Seat of Power:", self.seat_edit)

        self.citizenship_edit = QLineEdit()
        self.citizenship_edit.setPlaceholderText(
            "who counts as a citizen and how")
        self.citizenship_edit.textChanged.connect(
            self.content_changed.emit)
        form.addRow("Citizenship:", self.citizenship_edit)
        v.addLayout(form)

        self.levels = StringListWidget(
            "Tiers of Government (e.g., National, Provincial, City)",
            "Enter a tier of government:")
        self.levels.content_changed.connect(self.content_changed.emit)
        v.addWidget(self.levels)

        self.agencies = SubRecordList(
            "Agencies & Ministries",
            [("name", "Name", "line", None),
             ("purpose", "Purpose", "line", None),
             ("head", "Head", "line", None),
             ("description", "Description", "text", None)],
            GovernmentAgency)
        self.agencies.content_changed.connect(self.content_changed.emit)
        v.addWidget(self.agencies)

        v.addWidget(QLabel("Description:"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setMaximumHeight(80)
        self.desc_edit.textChanged.connect(self.content_changed.emit)
        v.addWidget(self.desc_edit)

    def _load(self) -> None:
        populate_faction_combo(
            self.faction_combo, self.available_factions,
            self.system.faction_id)
        self.type_edit.setText(self.system.government_type)
        self.structure_edit.setPlainText(self.system.structure)
        self.selection_edit.setText(self.system.leadership_selection)
        self.seat_edit.setText(self.system.seat_of_power)
        self.citizenship_edit.setText(self.system.citizenship)
        self.levels.set_items(self.system.levels)
        self.agencies.set_records(self.system.agencies)
        self.desc_edit.setPlainText(self.system.description)

    def save_to_model(self) -> None:
        self.system.faction_id = self.faction_combo.currentData() or ""
        self.system.government_type = self.type_edit.text()
        self.system.structure = self.structure_edit.toPlainText()
        self.system.leadership_selection = self.selection_edit.text()
        self.system.seat_of_power = self.seat_edit.text()
        self.system.citizenship = self.citizenship_edit.text()
        self.system.levels = self.levels.get_items()
        self.system.agencies = self.agencies.get_records()
        self.system.description = self.desc_edit.toPlainText()


class GovernmentBuilderWidget(SystemBuilderBase):
    """Manages the project's government systems."""

    TITLE = "Government Systems"
    ITEM_NOUN = "government system"
    IMPORT_SECTION = "government_systems"

    def _new_system(self, name: str) -> GovernmentSystem:
        return GovernmentSystem(id=name)

    def _make_editor(self, system) -> QWidget:
        return GovernmentSystemEditor(system, self.available_factions)

    def get_government_systems(self) -> List[GovernmentSystem]:
        return self.get_systems()

    def load_government_systems(
            self, systems: List[GovernmentSystem]) -> None:
        self.load_systems(systems)
