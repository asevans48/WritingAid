"""Builder for systems of JUSTICE — the courts, laws, enforcement,
punishments, and rights that make up a faction's legal order."""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QLabel, QLineEdit, QTextEdit, QVBoxLayout,
    QWidget,
)

from src.models.worldbuilding_objects import (
    Court, JusticeSystem, Law,
)
from src.ui.worldbuilding._system_builder_base import (
    StringListWidget, SubRecordList, SystemBuilderBase,
    populate_faction_combo,
)


class JusticeSystemEditor(QWidget):
    """Editor for a single justice system."""

    content_changed = pyqtSignal()

    def __init__(self, system: JusticeSystem,
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
        form.addRow("Attached to Faction:", self.faction_combo)

        self.type_edit = QLineEdit()
        self.type_edit.setPlaceholderText(
            "adversarial, inquisitorial, restorative, trial-by-combat, "
            "theocratic, tribal")
        self.type_edit.textChanged.connect(self.content_changed.emit)
        form.addRow("Justice Type:", self.type_edit)

        self.code_edit = QTextEdit()
        self.code_edit.setMaximumHeight(70)
        self.code_edit.textChanged.connect(self.content_changed.emit)
        form.addRow("Legal Code:", self.code_edit)

        self.enforcement_edit = QLineEdit()
        self.enforcement_edit.setPlaceholderText(
            "city guard, inquisitors, sheriffs, magistrates...")
        self.enforcement_edit.textChanged.connect(
            self.content_changed.emit)
        form.addRow("Enforcement:", self.enforcement_edit)
        v.addLayout(form)

        self.laws = SubRecordList(
            "Laws & Statutes",
            [("name", "Name", "line", None),
             ("category", "Category", "choice",
              ["criminal", "civil", "property", "trade", "religious",
               "family", "martial"]),
             ("penalty", "Penalty", "line", None),
             ("description", "Description", "text", None)],
            Law)
        self.laws.content_changed.connect(self.content_changed.emit)
        v.addWidget(self.laws)

        self.courts = SubRecordList(
            "Courts & Tribunals",
            [("name", "Name", "line", None),
             ("level", "Level", "choice",
              ["supreme", "high", "provincial", "local", "magistrate",
               "tribunal"]),
             ("jurisdiction", "Jurisdiction", "line", None),
             ("presiding", "Presiding", "line", None),
             ("description", "Description", "text", None)],
            Court)
        self.courts.content_changed.connect(self.content_changed.emit)
        v.addWidget(self.courts)

        self.punishments = StringListWidget(
            "Punishments", "Enter a punishment:")
        self.punishments.content_changed.connect(
            self.content_changed.emit)
        v.addWidget(self.punishments)

        self.rights = StringListWidget(
            "Rights (of the accused / citizens)", "Enter a right:")
        self.rights.content_changed.connect(self.content_changed.emit)
        v.addWidget(self.rights)

        v.addWidget(QLabel("Description:"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setMaximumHeight(80)
        self.desc_edit.textChanged.connect(self.content_changed.emit)
        v.addWidget(self.desc_edit)

    def _load(self) -> None:
        populate_faction_combo(
            self.faction_combo, self.available_factions,
            self.system.faction_id)
        self.type_edit.setText(self.system.justice_type)
        self.code_edit.setPlainText(self.system.legal_code)
        self.enforcement_edit.setText(self.system.enforcement)
        self.laws.set_records(self.system.laws)
        self.courts.set_records(self.system.courts)
        self.punishments.set_items(self.system.punishments)
        self.rights.set_items(self.system.rights)
        self.desc_edit.setPlainText(self.system.description)

    def save_to_model(self) -> None:
        self.system.faction_id = self.faction_combo.currentData() or ""
        self.system.justice_type = self.type_edit.text()
        self.system.legal_code = self.code_edit.toPlainText()
        self.system.enforcement = self.enforcement_edit.text()
        self.system.laws = self.laws.get_records()
        self.system.courts = self.courts.get_records()
        self.system.punishments = self.punishments.get_items()
        self.system.rights = self.rights.get_items()
        self.system.description = self.desc_edit.toPlainText()


class JusticeBuilderWidget(SystemBuilderBase):
    """Manages the project's justice systems."""

    TITLE = "Justice Systems"
    ITEM_NOUN = "justice system"
    IMPORT_SECTION = "justice_systems"
    REQUIRE_FACTION = True
    FACTION_VERB = "attached to"

    def _new_system(self, name: str) -> JusticeSystem:
        return JusticeSystem(id=name)

    def _make_editor(self, system) -> QWidget:
        return JusticeSystemEditor(system, self.available_factions)

    # Convenience aliases matching the other builders' verb style.
    def get_justice_systems(self) -> List[JusticeSystem]:
        return self.get_systems()

    def load_justice_systems(self, systems: List[JusticeSystem]) -> None:
        self.load_systems(systems)
