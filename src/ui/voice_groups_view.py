"""Rated rewrites, by voice (piece V.5).

The voice groups (V.2) shown and managed where the ratings are already
listed: Training Studio ▸ 🔎 Browse rows…, Source: "Rated rewrites, by
voice" (:func:`attach`). It is a way of sorting that list, not a new
window: the search box finds a rating, and the table and its buttons step
aside while the groups are shown.

One tree: proposals (one line each, Accept · Decline), the groups (name,
how alike, ratings, projects), the projects and narrators in each, the
ratings in each, then Unsorted. Every action is on a right-click and in
the one "Voice groups ▾" menu: rename, move, merge, new group, remove a
group, let the app sort a source, keep a project's ratings to itself,
change or remove a rating, rebuild, undo. Every change but removing a
rating can be taken back until the view closes; removing asks first.

The logic is in :mod:`src.data.voice_ratings` (no Qt).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from src.ai import voice_fingerprint as vf
from src.data import voice_ratings as vr
from src.ui import ui_kit

VOICE = "__by_voice__"          # the Source picker's entry
RATINGS = ("excellent", "good", "neutral", "poor", "bad")
ROLE = Qt.ItemDataRole.UserRole


def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _names(items: List[str], n: int = 3) -> str:
    if len(items) <= n:
        return ", ".join(items)
    return ", ".join(items[:n]) + f" and {len(items) - n} more"


class VoiceGroupsView(QWidget):
    """The groups, their sources and ratings, and the writer's changes."""

    named = pyqtSignal()        # V.3: the model named groups in the background

    def __init__(self, db_path: Optional[Path] = None, *, db=None, shared: bool = True,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        if db is None:
            from src.data.rephrase_database import RephraseDatabase
            db = RephraseDatabase(db_path) if db_path else None
            if db is None:
                from src.data.rephrase_database import get_rephrase_database
                db = get_rephrase_database()
        self.db = db
        self.shared = shared
        self._undo: List[Tuple[str, Callable[[], Any]]] = []
        self._data: Dict[str, Any] = {}
        self._query = ""
        self._hits: Optional[set] = None
        self._build()
        self.named.connect(lambda: self.refresh(self._query) if self.isVisible() else None)

    # ── Layout ────────────────────────────────────────────────────────

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(ui_kit.GAP)
        self.header = QLabel("")
        self.header.setWordWrap(True)
        self.header.setStyleSheet(ui_kit.text_style("ink_soft", 12))
        lay.addWidget(self.header)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Voice group · project or narrator · rating", "Ratings",
                                   "How alike · from"])
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.setUniformRowHeights(False)
        self.tree.setWordWrap(False)
        lay.addWidget(self.tree, 1)

        foot = QHBoxLayout()
        self.why = QLabel(vr.WHY_COUNT)
        self.why.setWordWrap(True)
        self.why.setStyleSheet(ui_kit.text_style("ink_faint", 11))
        foot.addWidget(self.why, 1)
        self.menu_btn = QPushButton("Voice groups ▾")
        ui_kit.plain(self.menu_btn)
        self.menu = QMenu(self.menu_btn)
        self.menu.aboutToShow.connect(lambda: self._fill_menu(self.menu, self._selected()))
        self.menu_btn.setMenu(self.menu)
        self.menu_btn.setToolTip("Rename, move, merge, start a group, rebuild, undo "
                                 "(also on a right-click)")
        foot.addWidget(self.menu_btn, 0, Qt.AlignmentFlag.AlignBottom)
        lay.addLayout(foot)

        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self.undo_last)
        QShortcut(QKeySequence.StandardKey.Delete, self.tree, activated=self._delete_key)

    # ── Filling the tree ─────────────────────────────────────────────

    def summary(self) -> str:
        d = self._data
        if not d:
            return ""
        n = len(d.get("groups") or [])
        return (f"<b>{n} voice group{'s' if n != 1 else ''}</b> · "
                f"{d.get('ratings', 0):,} rated rewrites of your own prose · "
                f"{len(d.get('unsorted') or [])} unsorted")

    def refresh(self, query: str = "") -> None:
        """Read the groups and ratings again and redraw (keeps what was open)."""
        self._query = (query or "").strip()
        open_keys = self._open_keys()
        if not self.shared:
            self._data = {}
            self.tree.clear()
            self.header.setText(
                "Voice groups belong to the app's own ratings database. This window is "
                "showing another database; choose the app's database to manage them.")
            self.menu_btn.setEnabled(False)
            return
        try:
            self._data = vr.overview(self.db)
        except Exception as e:                      # never an error dialog for a view
            print(f"[voice groups view] could not read: {e}")
            self._data = {"groups": [], "unsorted": [], "proposals": [], "ratings": 0,
                          "sources": {}, "state": {}}
        all_ids = [i for e in self._data["sources"].values() for i in e["ids"]]
        self._hits = vr.find(self.db, self._query, all_ids) if self._query else None
        self._draw(open_keys)
        self.header.setText(self.summary() if self._data["sources"] or self._data["groups"]
                            else "")

    def _draw(self, open_keys: set) -> None:
        t = self.tree
        t.clear()
        d = self._data
        if not d["groups"] and not d["sources"]:
            item = QTreeWidgetItem(t, ["No rated rewrites are grouped by voice yet. Rate "
                                       "suggestions in the Rephrase window; once "
                                       f"{vr.vg.MIN_SOURCE_RATINGS} passages of a project "
                                       "are rated, it gets a voice group."])
            item.setFirstColumnSpanned(True)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            return
        for i, p in enumerate(d["proposals"]):
            item = QTreeWidgetItem(t)
            item.setData(0, ROLE, ("proposal", i))
            item.setFirstColumnSpanned(True)
            label = QLabel(f"💡 <a href='accept'>Accept</a> · <a href='decline'>Decline</a>"
                           f" &nbsp;{p['text']}")
            label.setToolTip(p["text"])
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setStyleSheet(ui_kit.text_style("ink", 12, extra="padding: 2px;"))
            label.linkActivated.connect(lambda link, i=i: self._on_proposal(i, link))
            t.setItemWidget(item, 0, label)
        for g in d["groups"]:
            self._add_group(g, open_keys)
        if d["unsorted"]:
            un = QTreeWidgetItem(t, ["Unsorted: too few ratings yet, or waiting for room",
                                     f"{sum(e['ratings'] for e in d['unsorted']):,}", ""])
            un.setData(0, ROLE, ("unsorted",))
            f = un.font(0)
            f.setItalic(True)
            un.setFont(0, f)
            un.setToolTip(0, "Used as today (all ratings) until it has enough of its own. "
                             "Move one into a group by hand to use it there now.")
            for e in d["unsorted"]:
                self._add_source(un, e, open_keys, unsorted=True)
            un.setExpanded(("unsorted",) in open_keys or bool(self._query))
            if self._hits is not None and not any(
                    not un.child(i).isHidden() for i in range(un.childCount())):
                un.setHidden(True)

    def _add_group(self, g: Dict[str, Any], open_keys: set) -> None:
        name = g["name"]
        if g["named"] and g["description"] and g["description"] != name:
            name = f"{name} — {g['description']}"
        how = g["strength"]
        if g["projects"]:
            how += " · " + _names(g["projects"])
        item = QTreeWidgetItem(self.tree, [name, f"{g['ratings']:,}", how])
        item.setData(0, ROLE, ("group", g["id"]))
        f = item.font(0)
        f.setBold(True)
        item.setFont(0, f)
        tip = [g["description"] or "No description yet."]
        if g.get("measures") and g["measures"] != g["description"]:
            tip.append(f"Measured: {g['measures']}.")
        if g["writer_named"]:
            tip.append("Named by you.")
        if g["anchor"]:
            tip.append("Yours: the app never merges or removes it (it may suggest a change).")
        if g["examples"]:
            tip.append(f"Defined by {g['examples']} example passage(s).")
        item.setToolTip(0, "\n".join(tip))
        if g["loose"]:
            item.setForeground(2, Qt.GlobalColor.darkYellow)
        for e in g["sources"]:
            self._add_source(item, e, open_keys)
        item.setExpanded(("group", g["id"]) in open_keys or bool(self._query)
                         or len(self._data["groups"]) <= 3)
        if self._hits is not None and not any(
                not item.child(i).isHidden() for i in range(item.childCount())):
            item.setHidden(True)

    def _add_source(self, parent: QTreeWidgetItem, e: Dict[str, Any], open_keys: set,
                    unsorted: bool = False) -> None:
        label = ("🎙 " if e["character_name"] else "📁 ") + e["label"]
        if e["pinned"]:
            label += "  📌"
        if e["private"]:
            label += "  🔒"
        right = []
        if unsorted:
            right.append("waiting: more than "
                         f"{vr.vg.MAX_AUTO_GROUPS} voices" if e["waiting"] else
                         f"needs {e['needs']} more rated passage{'s' if e['needs'] != 1 else ''}"
                         if e["needs"] else "ready at the next rebuild")
        if e["private"]:
            right.append("kept to itself")
        item = QTreeWidgetItem(parent, [label, f"{e['ratings']:,}", " · ".join(right)])
        item.setData(0, ROLE, ("source", e["key"]))
        tip = [f"{e['ratings']} rating(s) of {e['passages']} different passage(s)."]
        if e["pinned"]:
            tip.append("📌 Placed by you: a rebuild leaves it here.")
        if e["private"]:
            tip.append("🔒 This project keeps its ratings to itself: rewrites in other "
                       "projects never learn from them.")
        item.setToolTip(0, "\n".join(tip))
        ids = e["ids"]
        if self._hits is not None:
            ids = [i for i in ids if i in self._hits]
            if not ids:
                item.setHidden(True)
                return
            self._fill_ratings(item, ids)
            item.setExpanded(True)
            return
        if ("source", e["key"]) in open_keys:
            self._fill_ratings(item, ids)
            item.setExpanded(True)
        elif ids:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)

    def _fill_ratings(self, item: QTreeWidgetItem, ids: List[int]) -> None:
        if item.data(1, ROLE) == "filled":
            return
        item.setData(1, ROLE, "filled")
        key = item.data(0, ROLE)[1]
        private = (self._data["sources"].get(key) or {}).get("private")
        for r in vr.ratings_for(self.db, ids):
            when = (r.get("created_at") or "")[:10]
            child = QTreeWidgetItem(item, [f"“{_clip(r.get('output_text'), 90)}”",
                                           r.get("rating") or "", when])
            child.setData(0, ROLE, ("rating", int(r["id"]), key))
            tip = (f"Passage: {_clip(r.get('source_text'), 400)}\n\n"
                   f"Rewrite: {_clip(r.get('output_text'), 400)}")
            if private:
                tip += "\n\n🔒 From a project that keeps its ratings to itself."
            child.setToolTip(0, tip)

    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        tag = item.data(0, ROLE)
        if tag and tag[0] == "source":
            e = self._data["sources"].get(tag[1]) or {}
            self._fill_ratings(item, e.get("ids") or [])

    def _open_keys(self) -> set:
        out = set()

        def walk(item):
            for i in range(item.childCount()):
                c = item.child(i)
                tag = c.data(0, ROLE)
                if c.isExpanded() and tag and tag[0] in ("group", "source", "unsorted"):
                    out.add(tuple(tag[:2]))
                walk(c)
        walk(self.tree.invisibleRootItem())
        return out

    # ── Selection and menus ──────────────────────────────────────────

    def _selected(self) -> List[tuple]:
        return [tuple(i.data(0, ROLE)) for i in self.tree.selectedItems() if i.data(0, ROLE)]

    def _on_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is not None and not item.isSelected():
            self.tree.clearSelection()
            item.setSelected(True)
        menu = QMenu(self)
        self._fill_menu(menu, self._selected())
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _fill_menu(self, menu: QMenu, sel: List[tuple]) -> None:
        menu.clear()
        groups = [t[1] for t in sel if t[0] == "group"]
        sources = [t[1] for t in sel if t[0] == "source"]
        ratings = [t for t in sel if t[0] == "rating"]
        props = [t[1] for t in sel if t[0] == "proposal"]
        enabled = self.shared
        gdata = {g["id"]: g for g in self._data.get("groups") or []}

        if props:
            i = props[0]
            menu.addAction("Accept this suggestion", lambda: self._on_proposal(i, "accept"))
            menu.addAction("Decline it", lambda: self._on_proposal(i, "decline"))
            menu.addSeparator()
        if len(groups) == 1:
            gid = groups[0]
            menu.addAction("Rename…", lambda: self.rename(gid))
        if len(groups) >= 2:
            menu.addAction(f"Merge {len(groups)} groups", lambda: self.merge(groups))
        elif len(groups) == 1 and len(gdata) >= 2:
            sub = menu.addMenu("Merge with")
            for g in self._data["groups"]:
                if g["id"] != groups[0]:
                    sub.addAction(_clip(g["name"], 60),
                                  lambda g2=g["id"], g1=groups[0]: self.merge([g1, g2]))
        if len(groups) == 1:
            gid = groups[0]
            menu.addAction("Remove this group (its projects are sorted again)",
                           lambda: self.remove_group(gid))
        if sources:
            here = {(self._data["sources"].get(k) or {}).get("group") for k in sources}
            sub = menu.addMenu("Move to")
            for g in self._data.get("groups") or []:
                if {g["id"]} != here:
                    sub.addAction(_clip(g["name"], 60), lambda gid=g["id"]: self.move(sources, gid))
            if sub.actions():
                sub.addSeparator()
            sub.addAction("New group…", lambda: self.new_group(sources))
            if any((self._data["sources"].get(k) or {}).get("pinned") for k in sources):
                menu.addAction("Let the app sort it", lambda: self.let_app_sort(sources))
            projects = sorted({(self._data["sources"].get(k) or {}).get("project_path", "")
                               for k in sources} - {""})
            if len(projects) == 1:
                pp = projects[0]
                act = menu.addAction("Keep this project's ratings to itself")
                act.setCheckable(True)
                act.setChecked(vr.is_private(pp))
                act.setToolTip("On: rewrites in other projects never learn from this "
                               "project's ratings. Nothing is deleted or moved.")
                act.toggled.connect(lambda on, pp=pp: self.set_private(pp, on))
        if len(ratings) == 1:
            rid = ratings[0][1]
            sub = menu.addMenu("Change rating")
            current = self._rating_of(rid)
            for value in RATINGS:
                act = sub.addAction(value.capitalize(), lambda v=value: self.change_rating(rid, v))
                act.setCheckable(True)
                act.setChecked(value == current)
        if ratings:
            ids = [t[1] for t in ratings]
            menu.addAction("Remove this rating…" if len(ids) == 1 else
                           f"Remove {len(ids)} ratings…", lambda: self.remove_ratings(ids))
        if not menu.isEmpty():
            menu.addSeparator()
        menu.addAction("New group…", lambda: self.new_group(sources))
        menu.addAction("Rebuild the groups", self.rebuild)
        undo = menu.addAction(f"Undo: {self._undo[-1][0]}" if self._undo else "Undo")
        undo.setEnabled(bool(self._undo))
        undo.triggered.connect(self.undo_last)
        for a in menu.actions():
            if not enabled:
                a.setEnabled(False)

    def _rating_of(self, rid: int) -> str:
        it = self._find_item(("rating", rid))
        return it.text(1) if it is not None else ""

    def _find_item(self, tag: tuple) -> Optional[QTreeWidgetItem]:
        def walk(item):
            for i in range(item.childCount()):
                c = item.child(i)
                d = c.data(0, ROLE)
                if d and tuple(d[:len(tag)]) == tag:
                    return c
                got = walk(c)
                if got is not None:
                    return got
            return None
        return walk(self.tree.invisibleRootItem())

    # ── The writer's changes ─────────────────────────────────────────

    def _done(self, label: str, undo: Optional[Callable[[], Any]]) -> None:
        if undo is not None:
            self._undo.append((label, undo))
        self.refresh(self._query)

    def _group_change(self, label: str, result) -> None:
        if result is None:
            self.refresh(self._query)
            return
        before = result[1]
        self._done(label, lambda: vr.undo(before))

    def _gname(self, gid: str) -> str:
        for g in self._data.get("groups") or []:
            if g["id"] == gid:
                return g["name"]
        return gid

    def rename(self, gid: str, name: Optional[str] = None) -> None:
        if name is None:
            g = next((g for g in self._data.get("groups") or [] if g["id"] == gid), {})
            name, ok = QInputDialog.getText(self, "Rename voice group", "Name:",
                                            QLineEdit.EchoMode.Normal,
                                            g.get("name", "") if g.get("named") else "")
            if not ok:
                return
        if not (name or "").strip():
            return
        self._group_change(f"rename to “{_clip(name, 30)}”", vr.rename(self.db, gid, name))

    def move(self, keys: List[str], gid: str) -> None:
        self._group_change(f"move to “{_clip(self._gname(gid), 30)}”", vr.move(self.db, keys, gid))

    def let_app_sort(self, keys: List[str]) -> None:
        self._group_change("let the app sort it", vr.let_app_sort(self.db, keys))

    def merge(self, gids: List[str], confirm: Optional[bool] = None) -> None:
        if len(gids) < 2:
            return
        state = self._data.get("state") or vr.vgs.load_state()
        if vr.merge_is_loose(self.db, state, gids):
            if confirm is None:
                ans = QMessageBox.question(
                    self, "Merge these groups?", vr.LOOSE_WARNING + "\n\nMerge them anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                confirm = ans == QMessageBox.StandardButton.Yes
            if not confirm:
                return
        self._group_change(f"merge {len(gids)} groups", vr.merge(self.db, gids))

    def remove_group(self, gid: str) -> None:
        self._group_change(f"remove “{_clip(self._gname(gid), 30)}”",
                           vr.remove_group(self.db, gid))

    def new_group(self, keys: Optional[List[str]] = None, *, name: Optional[str] = None,
                  passages: Optional[List[str]] = None) -> Optional[str]:
        keys = list(keys or [])
        if name is None:
            dlg = NewGroupDialog(self._data.get("sources") or {}, keys, parent=self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return None
            name, keys, passages = dlg.values()
        after, before, gid = vr.new_group(self.db, name or "", keys, passages or [])
        self._done("new group", lambda: vr.undo(before))
        return gid

    def rebuild(self) -> None:
        self._group_change("rebuild", vr.rebuild(self.db))
        self.name_later(force=True)

    def name_later(self, force: bool = False) -> None:
        """V.3: with a model free, name new groups on a background thread;
        the names appear when it is done. Only the app's own ratings."""
        if not self.shared:
            return

        def done(_result):
            try:
                self.named.emit()
            except RuntimeError:            # the view has closed
                pass
        try:
            from src.ai import voice_naming
            voice_naming.start_naming(self.db, on_done=done, force=force)
        except Exception as e:
            print(f"[voice groups view] naming not started: {e}")

    def set_private(self, project_path: str, on: bool) -> None:
        old = vr.is_private(project_path)
        if old == on:
            return
        if vr.set_private(project_path, on):
            self._done("keep to itself" if on else "share again",
                       lambda: vr.set_private(project_path, old))
        else:
            self.refresh(self._query)

    def change_rating(self, rid: int, rating: str) -> None:
        old = vr.change_rating(self.db, rid, rating)
        if old is None or old == rating:
            self.refresh(self._query)
            return
        self._done(f"rating → {rating}", lambda: self.db.update_rating(rid, old))

    def remove_ratings(self, ids: List[int], confirm: Optional[bool] = None) -> int:
        if not ids:
            return 0
        if confirm is None:
            what = "this rating" if len(ids) == 1 else f"these {len(ids)} ratings"
            ans = QMessageBox.question(
                self, "Remove rating?",
                f"Remove {what} from the ratings database? Rewrites will no longer learn "
                "from it. This cannot be taken back.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            confirm = ans == QMessageBox.StandardButton.Yes
        if not confirm:
            return 0
        n = sum(1 for i in ids if vr.remove_rating(self.db, i))
        self.refresh(self._query)
        return n

    def undo_last(self) -> None:
        if not self._undo:
            return
        _label, fn = self._undo.pop()
        try:
            fn()
        except Exception as e:
            print(f"[voice groups view] undo failed: {e}")
        self.refresh(self._query)

    def _on_proposal(self, i: int, link: str) -> None:
        props = self._data.get("proposals") or []
        if not (0 <= i < len(props)):
            return
        p = props[i]["proposal"]
        if link == "accept":
            self._group_change("accept the suggestion", vr.accept(self.db, p))
        else:
            self._group_change("decline the suggestion", vr.decline(self.db, p))

    def _delete_key(self) -> None:
        ids = [t[1] for t in self._selected() if t[0] == "rating"]
        if ids:
            self.remove_ratings(ids)


class NewGroupDialog(QDialog):
    """A voice group the writer starts: a name (optional) and what defines
    it: projects, narrators, and/or example passages."""

    def __init__(self, sources: Dict[str, Dict[str, Any]], ticked: List[str] = (),
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("New voice group")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(ui_kit.DIALOG_MARGIN, ui_kit.DIALOG_MARGIN,
                               ui_kit.DIALOG_MARGIN, ui_kit.DIALOG_MARGIN)
        lay.addWidget(QLabel("Name (optional; without one, the group shows a description of its voice):"))
        self.name = QLineEdit()
        lay.addWidget(self.name)
        lay.addWidget(QLabel("Defined by the projects or narrators you tick:"))
        self.list = QListWidget()
        for key, e in sorted(sources.items(), key=lambda kv: kv[1]["label"].lower()):
            it = QListWidgetItem(("🎙 " if e["character_name"] else "📁 ") + e["label"])
            it.setData(ROLE, key)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if key in ticked else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        lay.addWidget(self.list, 1)
        lay.addWidget(QLabel("…and/or example passages (a line of --- between passages; "
                             f"each at least {vf.MIN_WORDS} words):"))
        self.passages = QPlainTextEdit()
        self.passages.setPlaceholderText("Paste a passage written in this voice")
        lay.addWidget(self.passages, 1)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(ui_kit.text_style("warning_ink", 11))
        lay.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        ui_kit.fit_to_screen(self, 520, 560, min_width=360, min_height=320)

    def values(self) -> Tuple[str, List[str], List[str]]:
        keys = [self.list.item(i).data(ROLE) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]
        passages = [p for p in vr.split_passages(self.passages.toPlainText())
                    if vf.vector_of(p) is not None]
        return self.name.text().strip(), keys, passages

    def _ok(self) -> None:
        _name, keys, passages = self.values()
        pasted = vr.split_passages(self.passages.toPlainText())
        if not keys and not passages:
            self.note.setText("Tick a project or narrator, or paste a passage long enough "
                              f"to measure ({vf.MIN_WORDS} words, "
                              f"{vf.MIN_SENTENCES} sentences).")
            return
        if len(passages) < len(pasted) and not getattr(self, "_told_short", False):
            self._told_short = True
            self.note.setText(f"{len(pasted) - len(passages)} of {len(pasted)} passages are too "
                              "short to measure and will be left out. Press OK again to go on.")
            return
        self.accept()


def attach(dlg) -> Optional[VoiceGroupsView]:
    """Add "Rated rewrites, by voice" to the Browse rows dialog's Source
    picker (Training Studio). Choosing it shows the groups in place of the
    table; every other choice shows the table as before."""
    try:
        from src.data import rephrase_database as rd
        combo = dlg.source_combo
        at = combo.findData("rephrase")
        combo.insertItem(at + 1 if at >= 0 else combo.count(), "rated rewrites, by voice", VOICE)
        splitter = dlg.table.parentWidget()
        outer = dlg.layout()
        try:
            shared = Path(dlg.db_path).resolve() == Path(rd.DEFAULT_DB_PATH).resolve()
        except Exception:
            shared = False
        view = VoiceGroupsView(dlg.db_path, shared=shared, parent=dlg)
        outer.insertWidget(outer.indexOf(splitter) + 1, view, 1)
        view.hide()
        table_refresh = dlg._refresh
        tucked = (dlg.prev_btn, dlg.next_btn, dlg.drop_matching_btn, dlg.status_label)

        def refresh():
            on = combo.currentData() == VOICE
            splitter.setVisible(not on)
            view.setVisible(on)
            for w in tucked:
                w.setVisible(not on)
            for w in (dlg.genre_edit, dlg.corpus_combo):
                w.setEnabled(not on)
            if on:
                view.refresh(dlg.query_edit.text())
                view.name_later()
            else:
                table_refresh()

        dlg._refresh = refresh
        dlg.voice_groups_view = view
        dlg.setMinimumSize(640, 420)                # was 1000 × 640: taller than a small screen
        ui_kit.fit_to_screen(dlg, 1100, 760, min_width=640, min_height=420)
        return view
    except Exception as e:                          # the table works as before
        print(f"[voice groups view] not added: {e}")
        return None
