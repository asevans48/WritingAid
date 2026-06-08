"""Manage hops for one scene in a single dialog.

Right-click on a scene card → "Manage hops…" opens this. Shows
existing outgoing + incoming hops in two lists with Remove
buttons, plus pickers to add new hops to / from any other scene
on the board. Replaces the two-step "Connect to → click another
card" right-click dance for writers who'd rather work from a
list — especially useful when re-wiring after a delete.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
    QWidget,
)


class HopManagerDialog(QDialog):
    """List-based hop editor for one scene.

    The dialog mutates the studio in place — it calls
    ``studio.add_hop`` and ``studio.delete_hop`` directly. Caller
    refreshes the canvas after exec returns and emits
    contentChanged so the project autosave picks up the new
    topology.
    """

    def __init__(
        self,
        studio: Any,
        scene_id: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Manage hops")
        self.setModal(True)
        self.resize(560, 520)
        self._studio = studio
        self._scene_id = scene_id
        self._scene = studio.get_scene(scene_id)
        self._build_ui()
        self._refresh_lists()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        scene_label = (self._scene.name if self._scene else "scene")
        layout.addWidget(QLabel(
            f"<b>{scene_label}</b><br>"
            "Hops are directed edges between scene cards. The "
            "stitcher walks them in BFS order when assembling a "
            "chapter deck, so the order you set here controls "
            "playback sequence."))

        # ── Outgoing hops ────────────────────────────────────────
        out_box = QGroupBox("Outgoing hops (this scene → …)")
        out_v = QVBoxLayout(out_box)
        self._out_list = QListWidget()
        self._out_list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection)
        out_v.addWidget(self._out_list)
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("→ Add hop TO:"))
        self._out_combo = QComboBox()
        out_row.addWidget(self._out_combo, stretch=1)
        self._add_out_btn = QPushButton("+ Add")
        self._add_out_btn.clicked.connect(self._on_add_outgoing)
        out_row.addWidget(self._add_out_btn)
        self._remove_out_btn = QPushButton("Remove selected")
        self._remove_out_btn.clicked.connect(self._on_remove_outgoing)
        out_row.addWidget(self._remove_out_btn)
        out_v.addLayout(out_row)
        layout.addWidget(out_box)

        # ── Incoming hops ────────────────────────────────────────
        in_box = QGroupBox("Incoming hops (… → this scene)")
        in_v = QVBoxLayout(in_box)
        self._in_list = QListWidget()
        self._in_list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection)
        in_v.addWidget(self._in_list)
        in_row = QHBoxLayout()
        in_row.addWidget(QLabel("← Add hop FROM:"))
        self._in_combo = QComboBox()
        in_row.addWidget(self._in_combo, stretch=1)
        self._add_in_btn = QPushButton("+ Add")
        self._add_in_btn.clicked.connect(self._on_add_incoming)
        in_row.addWidget(self._add_in_btn)
        self._remove_in_btn = QPushButton("Remove selected")
        self._remove_in_btn.clicked.connect(self._on_remove_incoming)
        in_row.addWidget(self._remove_in_btn)
        in_v.addLayout(in_row)
        layout.addWidget(in_box)

        # Close button — all edits apply immediately, so there's
        # no Save/Cancel ambiguity.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _other_scenes(self) -> List[Any]:
        return [
            s for s in self._studio.scenes
            if s.id != self._scene_id
        ]

    def _refresh_lists(self) -> None:
        if self._scene is None:
            return
        self._out_list.clear()
        self._in_list.clear()
        self._out_combo.clear()
        self._in_combo.clear()
        # Existing outgoing hops.
        out_hops = [
            h for h in self._studio.hops
            if h.from_scene_id == self._scene_id]
        for h in out_hops:
            other = self._studio.get_scene(h.to_scene_id)
            other_name = other.name if other else f"<missing {h.to_scene_id}>"
            label = (
                f"→ {other_name}"
                + (f"  ({h.label})" if h.label else ""))
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, h.id)
            self._out_list.addItem(item)
        # Existing incoming hops.
        in_hops = [
            h for h in self._studio.hops
            if h.to_scene_id == self._scene_id]
        for h in in_hops:
            other = self._studio.get_scene(h.from_scene_id)
            other_name = other.name if other else f"<missing {h.from_scene_id}>"
            label = (
                f"← {other_name}"
                + (f"  ({h.label})" if h.label else ""))
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, h.id)
            self._in_list.addItem(item)
        # Populate combos with other scenes — filter out scenes
        # that are already connected in that direction so the
        # writer doesn't accidentally double-add.
        existing_out_targets = {h.to_scene_id for h in out_hops}
        existing_in_sources = {h.from_scene_id for h in in_hops}
        for s in self._other_scenes():
            if s.id not in existing_out_targets:
                self._out_combo.addItem(s.name or s.id, s.id)
            if s.id not in existing_in_sources:
                self._in_combo.addItem(s.name or s.id, s.id)
        # Disable Add buttons when there's nothing left to connect.
        self._add_out_btn.setEnabled(self._out_combo.count() > 0)
        self._add_in_btn.setEnabled(self._in_combo.count() > 0)

    def _on_add_outgoing(self) -> None:
        target_id = self._out_combo.currentData()
        if not target_id:
            return
        self._studio.add_hop(
            self._scene_id, target_id, label="next")
        self._refresh_lists()

    def _on_add_incoming(self) -> None:
        source_id = self._in_combo.currentData()
        if not source_id:
            return
        self._studio.add_hop(
            source_id, self._scene_id, label="next")
        self._refresh_lists()

    def _on_remove_outgoing(self) -> None:
        item = self._out_list.currentItem()
        if item is None:
            return
        hop_id = item.data(Qt.ItemDataRole.UserRole)
        self._studio.delete_hop(hop_id)
        self._refresh_lists()

    def _on_remove_incoming(self) -> None:
        item = self._in_list.currentItem()
        if item is None:
            return
        hop_id = item.data(Qt.ItemDataRole.UserRole)
        self._studio.delete_hop(hop_id)
        self._refresh_lists()
