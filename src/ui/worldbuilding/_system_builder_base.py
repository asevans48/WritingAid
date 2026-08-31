"""Shared building blocks for the faction-linked "system" builders
(justice / government / services). Mirrors the existing politics /
economy builders' shape (a left list of systems + a right editor) but
factors the common shell so each concrete builder only declares its
fields and how to make a fresh model + editor.
"""

from __future__ import annotations

import uuid
from typing import Callable, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSplitter,
    QVBoxLayout, QWidget,
)

from src.ui.worldbuilding._record_dialog import FieldSpec, edit_record


def populate_faction_combo(combo: QComboBox, factions: list,
                           selected_id: str = "") -> None:
    """Fill a combo with '(none)' + faction names, restoring the
    selection that matches ``selected_id`` (stored as itemData)."""
    combo.blockSignals(True)
    try:
        combo.clear()
        combo.addItem("(none)", "")
        for f in (factions or []):
            try:
                label = f"{f.name} ({f.faction_type.value})"
            except Exception:
                label = getattr(f, "name", "Faction")
            combo.addItem(label, f.id)
        if selected_id:
            for i in range(combo.count()):
                if combo.itemData(i) == selected_id:
                    combo.setCurrentIndex(i)
                    break
    finally:
        combo.blockSignals(False)


class StringListWidget(QWidget):
    """A titled list of free-text strings with Add / Remove."""

    content_changed = pyqtSignal()

    def __init__(self, title: str, prompt: str, parent=None) -> None:
        super().__init__(parent)
        self._prompt = prompt
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel(title))
        self._list = QListWidget()
        v.addWidget(self._list)
        row = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        rem = QPushButton("Remove")
        rem.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(rem)
        v.addLayout(row)

    def _add(self) -> None:
        text, ok = QInputDialog.getText(self, "Add", self._prompt)
        if ok and text.strip():
            self._list.addItem(text.strip())
            self.content_changed.emit()

    def _remove(self) -> None:
        i = self._list.currentRow()
        if i >= 0:
            self._list.takeItem(i)
            self.content_changed.emit()

    def set_items(self, items: List[str]) -> None:
        self._list.clear()
        for it in (items or []):
            self._list.addItem(it)

    def get_items(self) -> List[str]:
        return [self._list.item(i).text()
                for i in range(self._list.count())]


class SubRecordList(QWidget):
    """A titled list of structured sub-records (laws, courts,
    agencies, services). Each record is a pydantic model; editing goes
    through the generic ``RecordDialog``."""

    content_changed = pyqtSignal()

    def __init__(self, title: str, fields: List[FieldSpec],
                 model_cls, label_key: str = "name", parent=None):
        super().__init__(parent)
        self._fields = fields
        self._model_cls = model_cls
        self._label_key = label_key
        self.records: list = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel(title))
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _: self._edit())
        v.addWidget(self._list)
        row = QHBoxLayout()
        for text, slot in (("Add", self._add), ("Edit", self._edit),
                           ("Remove", self._remove)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        v.addLayout(row)

    def _refresh(self) -> None:
        self._list.clear()
        for r in self.records:
            self._list.addItem(
                getattr(r, self._label_key, "")
                or getattr(r, "id", ""))

    def _values(self, obj) -> dict:
        return {k: (getattr(obj, k, "") or "")
                for k, _l, _kind, _o in self._fields}

    def _add(self) -> None:
        vals = edit_record(self, "Add", self._fields)
        if not vals:
            return
        obj = self._model_cls(id=str(uuid.uuid4()), **vals)
        self.records.append(obj)
        self._refresh()
        self.content_changed.emit()

    def _edit(self) -> None:
        i = self._list.currentRow()
        if not (0 <= i < len(self.records)):
            return
        obj = self.records[i]
        vals = edit_record(self, "Edit", self._fields, self._values(obj))
        if not vals:
            return
        for k, v in vals.items():
            setattr(obj, k, v)
        self._refresh()
        self.content_changed.emit()

    def _remove(self) -> None:
        i = self._list.currentRow()
        if 0 <= i < len(self.records):
            del self.records[i]
            self._refresh()
            self.content_changed.emit()

    def set_records(self, records: list) -> None:
        self.records = list(records or [])
        self._refresh()

    def get_records(self) -> list:
        return self.records


class SystemBuilderBase(QWidget):
    """Left list of faction-linked systems + right editor. Concrete
    builders set the class attributes and implement ``_new_system`` /
    ``_make_editor``."""

    content_changed = pyqtSignal()

    TITLE = "Systems"
    ITEM_NOUN = "system"
    IMPORT_SECTION = ""  # CompleteWorldBuilding field name
    # When True, a system MUST be tied to a faction — creation asks
    # which faction and refuses if none exist yet. FACTION_VERB tunes
    # the wording ("attached to" / "supplied by").
    REQUIRE_FACTION = False
    FACTION_VERB = "attached to"

    def __init__(self):
        super().__init__()
        self.systems: list = []
        self.available_factions: list = []
        self.current_editor = None
        self._init_ui()

    # -- subclass hooks ------------------------------------------------
    def _new_system(self, name: str):
        raise NotImplementedError

    def _make_editor(self, system) -> QWidget:
        raise NotImplementedError

    # -- factions ------------------------------------------------------
    def set_available_factions(self, factions: list) -> None:
        self.available_factions = factions or []
        if self.current_editor and hasattr(
                self.current_editor, "set_available_factions"):
            self.current_editor.set_available_factions(
                self.available_factions)

    # -- UI ------------------------------------------------------------
    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        label = QLabel(self.TITLE)
        label.setStyleSheet("font-weight: 600; font-size: 13px;")
        left_layout.addWidget(label)
        self.system_list = QListWidget()
        self.system_list.currentItemChanged.connect(
            self._on_system_selected)
        left_layout.addWidget(self.system_list)
        btns = QHBoxLayout()
        add_btn = QPushButton("➕ Add")
        add_btn.clicked.connect(self._add_system)
        btns.addWidget(add_btn)
        rem_btn = QPushButton("🗑️")
        rem_btn.setMaximumWidth(40)
        rem_btn.clicked.connect(self._remove_system)
        btns.addWidget(rem_btn)
        if self.IMPORT_SECTION:
            imp_btn = QPushButton("📥 Import")
            imp_btn.clicked.connect(self._import_systems)
            btns.addWidget(imp_btn)
        left_layout.addLayout(btns)
        left.setMaximumWidth(250)
        splitter.addWidget(left)

        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        self._show_placeholder()
        splitter.addWidget(self.editor_scroll)
        layout.addWidget(splitter)

    def _show_placeholder(self) -> None:
        ph = QLabel(f"Add or select a {self.ITEM_NOUN}")
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor_scroll.setWidget(ph)

    def _add_system(self) -> None:
        name, ok = QInputDialog.getText(
            self, f"New {self.ITEM_NOUN}",
            f"Enter {self.ITEM_NOUN} name:")
        if not (ok and name.strip()):
            return
        name = name.strip()
        if any(s.id == name for s in self.systems):
            QMessageBox.warning(
                self, "Duplicate Name",
                f"A {self.ITEM_NOUN} named '{name}' already exists.")
            return
        # A required faction is chosen at creation so the system is
        # never orphaned.
        faction_id = ""
        if self.REQUIRE_FACTION:
            if not self.available_factions:
                QMessageBox.information(
                    self, "Add a faction first",
                    f"A {self.ITEM_NOUN} must be {self.FACTION_VERB} a "
                    "faction. Create a faction in the Factions section "
                    "first, then add this.")
                return
            labels, ids = [], []
            for f in self.available_factions:
                try:
                    labels.append(
                        f"{f.name} ({f.faction_type.value})")
                except Exception:
                    labels.append(getattr(f, "name", "Faction"))
                ids.append(f.id)
            choice, ok2 = QInputDialog.getItem(
                self, "Select Faction",
                f"Which faction is this {self.ITEM_NOUN} "
                f"{self.FACTION_VERB}?",
                labels, 0, False)
            if not ok2:
                return
            faction_id = ids[labels.index(choice)]
        system = self._new_system(name)
        if faction_id:
            system.faction_id = faction_id
        self.systems.append(system)
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, system.id)
        self.system_list.addItem(item)
        self.system_list.setCurrentItem(item)
        self.content_changed.emit()

    def _remove_system(self) -> None:
        current = self.system_list.currentItem()
        if not current:
            return
        sid = current.data(Qt.ItemDataRole.UserRole)
        self.systems = [s for s in self.systems if s.id != sid]
        self.current_editor = None
        self.system_list.takeItem(self.system_list.row(current))
        self._show_placeholder()
        self.content_changed.emit()

    def _on_system_selected(self, current, previous) -> None:
        if not current:
            return
        if self.current_editor and hasattr(
                self.current_editor, "save_to_model"):
            self.current_editor.save_to_model()
        sid = current.data(Qt.ItemDataRole.UserRole)
        system = next((s for s in self.systems if s.id == sid), None)
        if system is None:
            return
        editor = self._make_editor(system)
        editor.content_changed.connect(self.content_changed.emit)
        self.current_editor = editor
        self.editor_scroll.setWidget(editor)

    def get_systems(self) -> list:
        if self.current_editor and hasattr(
                self.current_editor, "save_to_model"):
            self.current_editor.save_to_model()
        return self.systems

    def load_systems(self, systems: list) -> None:
        self.systems = systems or []
        self.system_list.clear()
        self.current_editor = None
        self._show_placeholder()
        for s in self.systems:
            item = QListWidgetItem(s.id)
            item.setData(Qt.ItemDataRole.UserRole, s.id)
            self.system_list.addItem(item)

    def _import_systems(self) -> None:
        from src.ui.worldbuilding.worldbuilding_importer import (
            show_import_dialog)
        from src.models.worldbuilding_objects import CompleteWorldBuilding
        temp = CompleteWorldBuilding(
            **{self.IMPORT_SECTION: self.systems})
        result = show_import_dialog(
            self, temp, target_section=self.IMPORT_SECTION)
        if result and result.imported_counts.get(
                self.IMPORT_SECTION, 0) > 0:
            self.load_systems(getattr(temp, self.IMPORT_SECTION))
            self.content_changed.emit()
