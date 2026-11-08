"""Consistency dialog — names, spellings, hyphenation, capitalisation,
numbers and punctuation style across the manuscript (or whole project).

Groups are listed by kind; expand one to see every occurrence (double-
click to jump to it), pick the form to keep, and "Change all".
"""

from __future__ import annotations

from typing import Callable, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSplitter, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from src.utils.consistency_checks import KIND_LABELS, ConsistencyChecker, ConsistencyGroup


class ConsistencyDialog(QDialog):
    def __init__(self, chapters_provider: Callable[[str], list], canon_names: List[str],
                 navigate: Callable[[str, int, int], None],
                 apply_changes: Callable[[ConsistencyGroup, str], int],
                 has_novellas: bool = False, ignored: Optional[set] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Consistency check")
        self.resize(820, 560)
        self.setModal(False)
        self.chapters_provider = chapters_provider
        self.canon_names = canon_names
        self.navigate = navigate
        self.apply_changes = apply_changes
        self.ignored = ignored if ignored is not None else set()
        self.groups: List[ConsistencyGroup] = []

        v = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Check:"))
        self.scope = QComboBox()
        self.scope.addItem("This manuscript", "manuscript")
        if has_novellas:
            self.scope.addItem("Whole project (main + novellas)", "project")
        self.scope.currentIndexChanged.connect(lambda _i: self.run())
        top.addWidget(self.scope)
        top.addStretch()
        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #4b5563;")
        top.addWidget(self.summary)
        recheck = QPushButton("Re-check")
        recheck.clicked.connect(self.run)
        top.addWidget(recheck)
        v.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Issue", "Changes"])
        self.tree.setColumnWidth(0, 430)
        self.tree.currentItemChanged.connect(lambda cur, _prev: self._on_select(cur))
        self.tree.itemDoubleClicked.connect(lambda item, _c: self._jump(item))
        split.addWidget(self.tree)

        side = QWidget()
        sv = QVBoxLayout(side)
        self.detail = QLabel("Select an issue.")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: #374151;")
        sv.addWidget(self.detail)
        sv.addWidget(QLabel("Keep this form:"))
        self.target = QComboBox()
        self.target.currentIndexChanged.connect(lambda _i: self._update_apply_label())
        sv.addWidget(self.target)
        self.apply_btn = QPushButton("Change all")
        self.apply_btn.clicked.connect(self._apply)
        sv.addWidget(self.apply_btn)
        self.ignore_btn = QPushButton("Ignore this issue")
        self.ignore_btn.clicked.connect(self._ignore)
        sv.addWidget(self.ignore_btn)
        self.jump_btn = QPushButton("Go to occurrence")
        self.jump_btn.clicked.connect(lambda: self._jump(self.tree.currentItem()))
        sv.addWidget(self.jump_btn)
        sv.addStretch()
        hint = QLabel("Double-click an occurrence to jump to it in the manuscript. "
                      "Changes apply to every chapter, including ones that aren't open, "
                      "and can be undone per chapter in the editor.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6b7280; font-size: 11px;")
        sv.addWidget(hint)
        split.addWidget(side)
        split.setSizes([560, 260])
        v.addWidget(split, 1)
        self._set_controls(None)
        self.run()

    # ── checking ─────────────────────────────────────────────────

    def run(self) -> None:
        chapters = self.chapters_provider(self.scope.currentData() or "manuscript")
        self.groups = ConsistencyChecker(chapters, self.canon_names,
                                         ignored=self.ignored).run()
        self.tree.clear()
        by_kind = {}
        for g in self.groups:
            by_kind.setdefault(g.kind, []).append(g)
        bold = QFont()
        bold.setBold(True)
        for kind, label in KIND_LABELS.items():
            groups = by_kind.get(kind)
            if not groups:
                continue
            head = QTreeWidgetItem([f"{label} ({len(groups)})", ""])
            head.setFont(0, bold)
            head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(head)
            for g in groups:
                item = QTreeWidgetItem([g.title + ("  (review)" if g.review else ""),
                                        str(len(g.changes()))])
                item.setData(0, Qt.ItemDataRole.UserRole, ("group", g))
                if g.review:
                    item.setForeground(0, QColor("#6b7280"))
                head.addChild(item)
                for occ in g.occurrences[:200]:
                    text = self._context(chapters, occ)
                    child = QTreeWidgetItem([f"{occ.chapter_title}: {text}", ""])
                    child.setData(0, Qt.ItemDataRole.UserRole, ("occ", g, occ))
                    child.setForeground(0, QColor("#374151"))
                    item.addChild(child)
            head.setExpanded(True)
        total = sum(len(g.changes()) for g in self.groups)
        self.summary.setText(f"{len(self.groups)} issue(s), {total} change(s) suggested"
                             if self.groups else "No consistency issues found.")
        self._set_controls(None)

    @staticmethod
    def _context(chapters, occ) -> str:
        text = next((c[2] for c in chapters if c[0] == occ.chapter_id), "")
        a, b = max(0, occ.start - 35), min(len(text), occ.end + 35)
        snippet = text[a:occ.start] + "【" + text[occ.start:occ.end] + "】" + text[occ.end:b]
        return snippet.replace("\n", " ").strip()

    # ── selection / actions ──────────────────────────────────────

    def _selected_group(self, item=None) -> Optional[ConsistencyGroup]:
        item = item or self.tree.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        return data[1] if data else None

    def _set_controls(self, group: Optional[ConsistencyGroup]) -> None:
        self.target.blockSignals(True)
        self.target.clear()
        if group is not None:
            for t in group.targets:
                self.target.addItem(t if group.kind not in ("numbers", "punctuation")
                                    else {"words": "spell out (three)", "curly": "curly “ ”",
                                          "straight": 'straight " "'}.get(t, t), t)
            self.detail.setText(f"<b>{group.title}</b><br>{group.message}")
        else:
            self.detail.setText("Select an issue.")
        self.target.blockSignals(False)
        for w in (self.target, self.apply_btn, self.ignore_btn):
            w.setEnabled(group is not None)
        item = self.tree.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        self.jump_btn.setEnabled(bool(data and data[0] == "occ"))
        self._update_apply_label()

    def _update_apply_label(self) -> None:
        g = self._selected_group()
        target = self.target.currentData()
        n = len(g.changes(target)) if (g and target) else 0
        self.apply_btn.setText(f"Change all ({n})" if g else "Change all")
        self.apply_btn.setEnabled(bool(g and n))

    def _on_select(self, item) -> None:
        self._set_controls(self._selected_group(item))

    def _jump(self, item) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if data and data[0] == "occ":
            occ = data[2]
            self.navigate(occ.chapter_id, occ.start, occ.end)

    def _apply(self) -> None:
        g = self._selected_group()
        target = self.target.currentData()
        if g is None or not target:
            return
        n = self.apply_changes(g, target)
        self.run()
        self.summary.setText(f"Changed {n} occurrence(s). " + self.summary.text())

    def _ignore(self) -> None:
        g = self._selected_group()
        if g is None:
            return
        self.ignored.add(g.key)
        self.run()
