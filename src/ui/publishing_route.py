"""The publishing route, asked once per manuscript (piece 1.1).

Shown at the top of the Publishing tab's "Publishing Actions": for the main
manuscript and each novella, how it will be published (agent submission or
self-publishing), with its length beside what is typical for its genre and
route. Length is information, never a pass or fail.
"""

from __future__ import annotations

from typing import Any, List, Optional

from PyQt6.QtWidgets import QComboBox, QGridLayout, QLabel, QVBoxLayout, QWidget

from src.data import publishing_goal as pg
from src.ui.ui_kit import PALETTE


class RouteForm(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Any = None
        self._combos: List[QComboBox] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        intro = QLabel("How will you publish each manuscript? The app tailors its checks "
                       "and exports to the route.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {PALETTE['ink_soft']};")
        outer.addWidget(intro)
        self._grid = QGridLayout()
        self._grid.setColumnStretch(2, 1)
        outer.addLayout(self._grid)

    def set_project(self, project: Any) -> None:
        self.project = project
        self.refresh()

    def showEvent(self, event):
        self.refresh()                       # new novellas, words, genre
        super().showEvent(event)

    def refresh(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._combos = []
        if self.project is None:
            return
        try:
            rows = pg.manuscripts(self.project)
        except Exception as e:               # never break the tab
            print(f"[publishing-route] {e}")
            return
        for row, (scope, name, _ms) in enumerate(rows):
            goal = pg.publishing_goal(self.project, scope)
            label = QLabel(f"{name}:")
            combo = QComboBox()
            for key, text in pg.ROUTES.items():
                combo.addItem(text + (" (default)" if key == pg.DEFAULT_ROUTE else ""), key)
            combo.setCurrentIndex(max(0, combo.findData(goal.route)))
            combo.currentIndexChanged.connect(
                lambda _i, s=scope, c=combo: self._changed(s, c))
            info = QLabel(goal.length_note)
            info.setWordWrap(True)
            info.setStyleSheet(f"color: {PALETTE['ink_faint']};")
            self._grid.addWidget(label, row, 0)
            self._grid.addWidget(combo, row, 1)
            self._grid.addWidget(info, row, 2)
            self._combos.append(combo)

    def _changed(self, scope: Optional[str], combo: QComboBox) -> None:
        try:
            if self.project is not None:
                pg.set_route(self.project, scope, combo.currentData())
                self.refresh()
        except Exception as e:               # an exception escaping a slot aborts PyQt6
            print(f"[publishing-route] could not save: {e}")
