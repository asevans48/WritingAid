"""Builder for systems of SERVICES — the public / civic services a
faction provides its people: healthcare, education, utilities,
transport, sanitation, emergency response, welfare, and the
infrastructure that carries them."""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QLabel, QLineEdit, QTextEdit, QVBoxLayout,
    QWidget,
)

from src.models.worldbuilding_objects import (
    PublicService, ServiceSystem,
)
from src.ui.worldbuilding._system_builder_base import (
    SubRecordList, SystemBuilderBase, populate_faction_combo,
)


class ServiceSystemEditor(QWidget):
    """Editor for a single service system."""

    content_changed = pyqtSignal()

    def __init__(self, system: ServiceSystem,
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
        form.addRow("Supplied by Faction:", self.faction_combo)

        self.infra_edit = QTextEdit()
        self.infra_edit.setMaximumHeight(70)
        self.infra_edit.setPlaceholderText(
            "roads, aqueducts, power grid, network — the backbone")
        self.infra_edit.textChanged.connect(self.content_changed.emit)
        form.addRow("Infrastructure:", self.infra_edit)

        self.access_edit = QLineEdit()
        self.access_edit.setPlaceholderText(
            "how people reach / qualify for services")
        self.access_edit.textChanged.connect(self.content_changed.emit)
        form.addRow("Accessibility:", self.access_edit)
        v.addLayout(form)

        self.services = SubRecordList(
            "Services",
            [("name", "Name", "line", None),
             ("category", "Category", "choice",
              ["healthcare", "education", "utilities", "transport",
               "sanitation", "emergency", "welfare", "communication"]),
             ("provider", "Provider", "choice",
              ["public", "private", "guild", "religious", "mixed"]),
             ("coverage", "Coverage", "choice",
              ["universal", "urban-only", "wealthy-only", "rationed"]),
             ("quality", "Quality", "choice",
              ["excellent", "adequate", "poor", "failing"]),
             ("funding", "Funding", "line", None),
             ("description", "Description", "text", None)],
            PublicService)
        self.services.content_changed.connect(self.content_changed.emit)
        v.addWidget(self.services)

        v.addWidget(QLabel("Description:"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setMaximumHeight(80)
        self.desc_edit.textChanged.connect(self.content_changed.emit)
        v.addWidget(self.desc_edit)

    def _load(self) -> None:
        populate_faction_combo(
            self.faction_combo, self.available_factions,
            self.system.faction_id)
        self.infra_edit.setPlainText(self.system.infrastructure)
        self.access_edit.setText(self.system.accessibility)
        self.services.set_records(self.system.services)
        self.desc_edit.setPlainText(self.system.description)

    def save_to_model(self) -> None:
        self.system.faction_id = self.faction_combo.currentData() or ""
        self.system.infrastructure = self.infra_edit.toPlainText()
        self.system.accessibility = self.access_edit.text()
        self.system.services = self.services.get_records()
        self.system.description = self.desc_edit.toPlainText()


class ServicesBuilderWidget(SystemBuilderBase):
    """Manages the project's service systems."""

    TITLE = "Service Systems"
    ITEM_NOUN = "service system"
    IMPORT_SECTION = "service_systems"
    REQUIRE_FACTION = True
    FACTION_VERB = "supplied by"

    def _new_system(self, name: str) -> ServiceSystem:
        return ServiceSystem(id=name)

    def _make_editor(self, system) -> QWidget:
        return ServiceSystemEditor(system, self.available_factions)

    def get_service_systems(self) -> List[ServiceSystem]:
        return self.get_systems()

    def load_service_systems(
            self, systems: List[ServiceSystem]) -> None:
        self.load_systems(systems)
