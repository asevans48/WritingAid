"""One manuscript tree on the left of the Write screen (piece D.10).

The chapter list and the row of manuscript tabs above it ("📖 Main
Manuscript", one tab per novella, and **Novellas ▾**) become one tree,
always shown, even with no novellas::

    ▾ 📖 Main Manuscript        12
        1. The Storm
        2. The Pier
    ▸ 📘 The Fall                5
      ＋ New novella…

* **The open manuscript is expanded**, the others collapsed (open one to
  look without switching). Clicking a manuscript row opens it, as its tab
  did; clicking a chapter under another manuscript switches to it and opens
  the chapter. Arrow keys move through the rows; Enter opens.
* **Right-click a manuscript:** every entry of its old tab's menu
  (critique, project critique, continuity across novellas, rename, turn
  main into a novella, description, move main chapters, drop novella, new
  novella).
* **Right-click a chapter:** the chapter menu as it was, plus **Move to ▸**
  (each other manuscript, and "＋ A new novella…").
* **Drag and drop:** a chapter dragged within its manuscript is reordered
  exactly as ↑ / ↓ would; dragged onto another manuscript's row, or between
  its chapters, it moves there (``src/data/chapter_move.py`` does the move;
  nothing is overwritten or lost). Several selected chapters move at once.
  Manuscript rows do not move.
* **After a move** the status bar says "Moved “The Storm” to The Fall" with
  an **Undo** button beside it, and the chapter is opened where it now is.
  A move that fails part-way is put back and says so in a box.

**Nothing removed.** The old chapter list (``chapter_list``) and tab bar
(``subproject_tabs``) are kept, hidden, and the tree drives them (the D.7
pattern of ``write_toolbar``): other code reads and sets them, and the
tree follows. ``+ ↑ ↓`` and ◀ Prev / Next ▶ stay below and above it.

**The trial switch** (rule 11): Settings ▸ Features ▸ *Manuscript tree*.
Ticked (the starting position), the tree; unticked, the tab row, Novellas ▾
and the chapter list exactly as before. Kept as ``write/manuscript_tree``
beside the window positions; a missing or unreadable value means ticked.
"""

from __future__ import annotations

import weakref
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QGroupBox, QHeaderView, QLabel, QMainWindow, QMenu,
    QMessageBox, QPushButton, QStatusBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

SETTING_KEY = "write/manuscript_tree"
STARTS_ON = True                 # the writer, 26 November 2026: the tree is the default

KIND = Qt.ItemDataRole.UserRole
SCOPE = Qt.ItemDataRole.UserRole + 1
CHAPTER = Qt.ItemDataRole.UserRole + 2
MS, CH, NEW = "manuscript", "chapter", "new"

NEW_NOVELLA = "＋ New novella…"
MOVE_TO = "Move to"
MOVE_TO_NEW = "＋ A new novella…"
NOTICE_MS = 30000

_live: "weakref.WeakSet[ManuscriptTree]" = weakref.WeakSet()


# ── The switch ─────────────────────────────────────────────────────────

def _settings():
    from src.ui.ui_kit import _settings as kit_settings
    return kit_settings()


def on() -> bool:
    """True when the tree is shown (the default), False for the old row."""
    try:
        value = _settings().value(SETTING_KEY, None)
    except Exception:
        return STARTS_ON
    if value is None or value == "":
        return STARTS_ON
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    return STARTS_ON


def set_on(value: bool) -> None:
    """Store the switch and apply it to every Write screen now open."""
    try:
        s = _settings()
        s.setValue(SETTING_KEY, "true" if value else "false")
        s.sync()
    except Exception as e:                       # a setting never breaks the app
        print(f"[manuscript tree] could not save the switch: {e}")
    for tree in list(_live):
        try:
            tree.apply(bool(value))
        except RuntimeError:                     # its window is gone
            pass


class TreeOption:
    """Settings ▸ Features ▸ Manuscript tree (two call lines in
    ``SettingsDialog``, as ``ImproveOption``)."""

    def __init__(self, layout):
        group = QGroupBox("Manuscript tree")
        lay = QVBoxLayout()
        self.box = QCheckBox("Show the main manuscript, novellas and chapters as one tree "
                             "on the Write screen")
        self.box.setToolTip("Untick for the row of manuscript tabs and Novellas ▾ above "
                            "the chapter list, as they were.")
        self.box.setChecked(on())
        lay.addWidget(self.box)
        group.setLayout(lay)
        layout.addWidget(group)

    def save(self) -> None:
        try:
            if self.box.isChecked() != on():
                set_on(self.box.isChecked())
        except Exception as e:                   # noqa: BLE001
            print(f"[manuscript tree] could not save: {e}")


# ── Install (the call line in ``ManuscriptEditor._init_ui``) ────────────

def install(manuscript_editor: Any) -> None:
    me = manuscript_editor
    try:
        tree = ManuscriptTree(me)
        lay = me.chapter_list.parentWidget().layout()
        at = lay.indexOf(me.chapter_list)
        lay.insertWidget(at + 1, tree, 1)
        notice = QLabel()
        notice.setWordWrap(True)
        notice.setVisible(False)
        notice.setTextFormat(Qt.TextFormat.RichText)
        notice.linkActivated.connect(lambda _l: tree.undo_last())
        lay.insertWidget(at + 2, notice)
        tree.notice = notice
        me.manuscript_tree = tree

        refresh_tabs = me._refresh_subproject_tabs   # the tabs are rebuilt: so is the tree

        def refresh():
            refresh_tabs()
            tree.after_tabs_refresh()
        me._refresh_subproject_tabs = refresh
        model = me.chapter_list.model()
        for sig in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.dataChanged):
            sig.connect(lambda *_: tree.schedule())
        me.chapter_list.currentItemChanged.connect(lambda *_: tree.follow_list())
        _live.add(tree)
        tree.apply(on(), initial=True)
    except Exception as e:                       # never break the Write tab
        print(f"[manuscript tree] not installed: {e}")


def add_move_menu(manuscript_editor: Any, menu: QMenu) -> None:
    """**Move to ▸** in a chapter's right-click menu (the call line in
    ``_show_chapter_context_menu``). Only with the tree on."""
    tree = getattr(manuscript_editor, "manuscript_tree", None)
    try:
        if tree is not None and tree.is_on:
            tree.fill_move_menu(menu)
    except Exception as e:                       # the menu still opens
        print(f"[manuscript tree] no Move to: {e}")


@contextmanager
def _list_points_at(lst: Any, item: Any, global_pos: QPoint):
    """Let the old chapter menu, which asks the (hidden) list where it was
    clicked, open for ``item`` at ``global_pos``."""
    lst.itemAt = lambda _p: item
    lst.mapToGlobal = lambda _p: global_pos
    try:
        yield
    finally:
        del lst.itemAt
        del lst.mapToGlobal


# ── The tree ───────────────────────────────────────────────────────────

class ManuscriptTree(QTreeWidget):

    def __init__(self, manuscript_editor: Any):
        super().__init__(manuscript_editor.chapter_list.parentWidget())
        self.me = manuscript_editor
        self.is_on = True
        self.notice: Optional[QLabel] = None
        self._last = None                        # the last move, for Undo
        self._menu_chapters: Optional[List[Tuple[Optional[str], str]]] = None
        self._expanded = set()                   # manuscripts opened by hand
        self._active_seen = object()
        self._building = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.rebuild)

        self.setObjectName("manuscriptTree")
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.setIndentation(14)
        self.setAllColumnsShowFocus(True)        # one highlight across the row
        self.setExpandsOnDoubleClick(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.itemClicked.connect(self._clicked)
        self.itemActivated.connect(lambda item, _c: self.activate(item))
        self.itemExpanded.connect(lambda i: self._expanded_changed(i, True))
        self.itemCollapsed.connect(lambda i: self._expanded_changed(i, False))
        self.setToolTip("Click to open · drag a chapter to reorder it or move it to "
                        "another manuscript · right-click for more")
        from src.ui.ui_kit import PALETTE
        self.setStyleSheet(
            "QTreeWidget#manuscriptTree { background: white; border: 1px solid "
            f"{PALETTE['border']}; border-radius: 8px; outline: none; padding: 4px; }}"
            " QTreeWidget#manuscriptTree::item { padding: 5px 4px; border: none; "
            f"color: {PALETTE['text_dark']}; }}"
            " QTreeWidget#manuscriptTree::item:selected { background: "
            f"{PALETTE['primary']}; color: white; }}"
            " QTreeWidget#manuscriptTree::item:hover:!selected { background: "
            "rgba(99, 102, 241, 0.1); }")

    # ── switching between the tree and the old row ──

    def apply(self, value: bool, initial: bool = False) -> None:
        me = self.me
        self.is_on = value
        self.setVisible(value)
        me.chapter_list.setVisible(not value)
        btn = getattr(me, "novellas_menu_btn", None)
        if btn is not None:
            btn.setVisible(not value)
        if self.notice is not None and not value:
            self.notice.setVisible(False)
        if value:
            me.subproject_tabs.setVisible(False)
        elif not initial:
            me._refresh_subproject_tabs()        # the tab bar shows or hides as before
        self.rebuild()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentItem() is not None:
            self.activate(self.currentItem())    # arrows move; Enter opens
            event.accept()
            return
        super().keyPressEvent(event)

    def after_tabs_refresh(self) -> None:
        if self.is_on:
            self.me.subproject_tabs.setVisible(False)
        self.schedule()

    # ── building ──

    def schedule(self) -> None:
        if self.is_on and not self._building:
            self._timer.start()

    def _project(self):
        p = self.me.project
        return p if p is not None and hasattr(p, "iter_manuscripts") else None

    def _active(self) -> Optional[str]:
        p = self._project()
        return (getattr(p, "active_subproject_id", None) or None) if p else None

    def _list_rows(self) -> List[Tuple[str, str]]:
        lst = self.me.chapter_list
        return [(lst.item(i).data(Qt.ItemDataRole.UserRole), lst.item(i).text())
                for i in range(lst.count())]

    def rebuild(self) -> None:
        if not self.is_on:
            return
        self._timer.stop()
        me, project = self.me, self._project()
        active = self._active()
        if active != self._active_seen:          # a new manuscript open: only it expanded
            self._expanded = set()
            self._active_seen = active
        self._building = True
        self.blockSignals(True)
        try:
            self.clear()
            if project is not None:
                manuscripts = project.iter_manuscripts()
            elif me.manuscript is not None:
                manuscripts = [(None, me.manuscript)]
            else:
                manuscripts = []
            current = None
            open_id = me._current_chapter_id
            for scope, ms in manuscripts:
                is_active = scope == active
                if scope is None:
                    name = f"📖 {getattr(ms, 'title', '') or 'Main Manuscript'}"
                    sp = None
                else:
                    sp = project.get_subproject(scope)
                    name = f"📘 {sp.name if sp else scope}"
                rows = (self._list_rows() if is_active
                        else [(c.id, f"{c.number}. {c.title}") for c in ms.chapters])
                top = QTreeWidgetItem([name, str(len(rows))])
                top.setData(0, KIND, MS)
                top.setData(0, SCOPE, scope or "")
                top.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                             | Qt.ItemFlag.ItemIsDropEnabled)
                top.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                words = sum(getattr(c, "word_count", 0) or 0 for c in ms.chapters)
                kind = "Main manuscript" if scope is None else (sp.kind.capitalize() if sp else "Novella")
                tip = f"{kind} — {len(ms.chapters)} chapter(s), {words:,} words"
                if sp is not None and sp.description:
                    tip += f"\n\n{sp.description}"
                tip += "\n\nClick to open · right-click for more"
                for col in (0, 1):
                    top.setToolTip(col, tip)
                f = top.font(0)
                f.setBold(True)
                top.setFont(0, f)
                for cid, text in rows:
                    child = QTreeWidgetItem([text, ""])
                    child.setData(0, KIND, CH)
                    child.setData(0, SCOPE, scope or "")
                    child.setData(0, CHAPTER, cid)
                    child.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                                   | Qt.ItemFlag.ItemIsDragEnabled)
                    top.addChild(child)
                    if is_active and cid == open_id:
                        current = child
                self.addTopLevelItem(top)
                top.setExpanded(is_active or scope in self._expanded)
                if is_active and current is None:
                    current = top
            if project is not None and hasattr(project, "create_subproject"):
                new = QTreeWidgetItem([NEW_NOVELLA, ""])
                new.setData(0, KIND, NEW)
                new.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                             | Qt.ItemFlag.ItemIsDropEnabled)
                from PyQt6.QtGui import QBrush, QColor
                from src.ui.ui_kit import PALETTE
                new.setForeground(0, QBrush(QColor(PALETTE["ink_faint"])))
                new.setToolTip(0, "Start a new novella in this project's universe. It gets its "
                                  "own chapters; worldbuilding, characters and plot planning "
                                  "are shared.\nDrop chapters here to move them into a new novella.")
                self.addTopLevelItem(new)
            if current is not None:
                self.setCurrentItem(current)
        finally:
            self.blockSignals(False)
            self._building = False

    def follow_list(self) -> None:
        """The chapter list's selection changed (Prev / Next, + , another
        screen opening a chapter): show it in the tree."""
        if not self.is_on or self._building:
            return
        cid = self.me._current_chapter_id
        item = self.chapter_item(self._active(), cid) if cid else None
        if item is None:
            lst = self.me.chapter_list.currentItem()
            if lst is not None:
                item = self.chapter_item(self._active(), lst.data(Qt.ItemDataRole.UserRole))
        if item is None:
            self.schedule()
            return
        self.blockSignals(True)
        self.setCurrentItem(item)
        self.blockSignals(False)

    # ── finding rows ──

    def manuscript_item(self, scope: Optional[str]) -> Optional[QTreeWidgetItem]:
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            if it.data(0, KIND) == MS and (it.data(0, SCOPE) or None) == (scope or None):
                return it
        return None

    def chapter_item(self, scope: Optional[str], cid: str) -> Optional[QTreeWidgetItem]:
        top = self.manuscript_item(scope)
        if top is None:
            return None
        for i in range(top.childCount()):
            if top.child(i).data(0, CHAPTER) == cid:
                return top.child(i)
        return None

    def new_novella_item(self) -> Optional[QTreeWidgetItem]:
        for i in range(self.topLevelItemCount()):
            if self.topLevelItem(i).data(0, KIND) == NEW:
                return self.topLevelItem(i)
        return None

    @staticmethod
    def where(item: QTreeWidgetItem) -> Tuple[str, Optional[str], Optional[str]]:
        return item.data(0, KIND), (item.data(0, SCOPE) or None), item.data(0, CHAPTER)

    def selected_chapters(self) -> List[Tuple[Optional[str], str]]:
        out = []
        for it in self.selectedItems():
            kind, scope, cid = self.where(it)
            if kind == CH:
                out.append((scope, cid))
        return out

    def _expanded_changed(self, item, expanded: bool) -> None:
        if self._building or item.data(0, KIND) != MS:
            return
        scope = item.data(0, SCOPE) or None
        (self._expanded.add if expanded else self._expanded.discard)(scope)

    # ── opening ──

    def _clicked(self, item, _column) -> None:
        mods = _modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                   | Qt.KeyboardModifier.MetaModifier):
            return                               # selecting several, not opening
        if item.data(0, KIND) == MS:             # a click on the ▸ only opens the row
            x = self.viewport().mapFromGlobal(QCursor.pos()).x()
            if x < self.visualItemRect(item).x():
                return
        self.activate(item)

    def activate(self, item: QTreeWidgetItem) -> None:
        """Open what the row is: a manuscript, a chapter, or a new novella."""
        try:
            kind, scope, cid = self.where(item)
            if kind == MS:
                self.open_manuscript(scope)
            elif kind == CH:
                self.open_chapter(scope, cid)
            elif kind == NEW:
                self.me._create_subproject()
        except Exception as e:                   # never escape a slot
            print(f"[manuscript tree] could not open: {e}")

    def open_manuscript(self, scope: Optional[str]) -> bool:
        """The tab's own switch: select its tab, which calls
        ``_on_subproject_tab_changed`` and so ``switch_subproject``."""
        tabs = self.me.subproject_tabs
        for i in range(tabs.count()):
            if (tabs.tabData(i) or None) == (scope or None):
                if tabs.currentIndex() != i:
                    tabs.setCurrentIndex(i)
                self.schedule()
                return True
        return False

    def open_chapter(self, scope: Optional[str], cid: str) -> bool:
        me = self.me
        if (scope or None) != self._active() and self._project() is not None:
            me._last_chapter_by_scope[scope or None] = cid   # the switch opens it
            self.open_manuscript(scope)
        lst = me.chapter_list
        for row in range(lst.count()):
            if lst.item(row).data(Qt.ItemDataRole.UserRole) == cid:
                lst.setCurrentRow(row)
                return True
        return False

    # ── right-click ──

    def _context_menu(self, pos: QPoint) -> None:
        try:
            item = self.itemAt(pos)
            if item is None:
                return
            kind, scope, cid = self.where(item)
            global_pos = self.viewport().mapToGlobal(pos)
            if kind == MS:
                menu, actions = self.manuscript_menu(scope)
                chosen = menu.exec(global_pos)
                if chosen in actions:
                    actions[chosen]()
            elif kind == CH:
                self.chapter_menu(scope, cid, global_pos)
            elif kind == NEW:
                self.me._create_subproject()
        except Exception as e:
            print(f"[manuscript tree] menu failed: {e}")

    def manuscript_menu(self, scope: Optional[str]):
        """Every entry of the manuscript tab's old right-click menu
        (``_show_subproject_tab_menu``), calling the same methods."""
        me, project = self.me, self.me.project
        menu = QMenu(self)
        actions: Dict[Any, Any] = {}
        if project is None or not hasattr(project, "subprojects"):
            return menu, actions
        from src.ai.continuity_analysis import has_cross_manuscript_content
        label = project.scope_label(scope)
        a = menu.addAction(
            f"🧐 Critique {'main manuscript' if scope is None else 'this novella'} “{label}”…")
        actions[a] = lambda: me.manuscript_critique_requested.emit(scope or "", False)
        if scope is None and has_cross_manuscript_content(project):
            a = menu.addAction("🧐 Critique main project + continuity across novellas…")
            actions[a] = lambda: me.manuscript_critique_requested.emit("", True)
            a = menu.addAction("🔗 Check continuity across novellas…")
            actions[a] = lambda: me.manuscript_critique_requested.emit("__continuity__", True)
        menu.addSeparator()
        a = menu.addAction("Rename…")
        actions[a] = lambda: me._rename_subproject(scope)
        if scope is None and project.get_main_manuscript().chapters:
            a = menu.addAction("Turn main manuscript into a novella…")
            actions[a] = me._turn_main_into_novella
        if scope is not None:
            a = menu.addAction("Edit description…")
            actions[a] = lambda: me._edit_subproject_description(scope)
            sp = project.get_subproject(scope)
            main = project.get_main_manuscript()
            if sp is not None and main.chapters:
                a = menu.addAction(
                    f"Move main chapters into this novella ({len(main.chapters)})…")
                actions[a] = lambda: me._move_main_into_existing(scope)
            menu.addSeparator()
            a = menu.addAction("Drop novella and its content…")
            actions[a] = lambda: me._delete_subproject(scope)
        menu.addSeparator()
        a = menu.addAction(NEW_NOVELLA)
        actions[a] = me._create_subproject
        return menu, actions

    def chapter_menu(self, scope: Optional[str], cid: str, global_pos: QPoint) -> None:
        """The chapter's old right-click menu, unchanged, plus Move to ▸."""
        me = self.me
        chosen = self.selected_chapters()
        self._menu_chapters = chosen if (scope, cid) in chosen else [(scope, cid)]
        try:
            if (scope or None) != self._active() and self._project() is not None:
                self.open_chapter(scope, cid)
            lst = me.chapter_list
            item = next((lst.item(r) for r in range(lst.count())
                         if lst.item(r).data(Qt.ItemDataRole.UserRole) == cid), None)
            if item is None:
                return
            with _list_points_at(lst, item, global_pos):
                me._show_chapter_context_menu(QPoint(0, 0))
        finally:
            self._menu_chapters = None

    def fill_move_menu(self, menu: QMenu) -> QMenu:
        me, project = self.me, self._project()
        chapters = self._menu_chapters
        if not chapters:
            ch = me._get_context_chapter()
            chapters = [(self._active(), ch.id)] if ch is not None else []
        sub = QMenu(MOVE_TO, menu)
        sub.setToolTip("Move the chapter, with its drafts, saved copies, notes and "
                       "annotations, to another manuscript. Undo is offered after.")
        if project is None or not chapters:
            sub.setEnabled(False)
        else:
            here = {s for s, _c in chapters}
            for scope, _ms in project.iter_manuscripts():
                if len(here) == 1 and scope in here:
                    continue
                name = (f"📖 {project.get_main_manuscript().title or 'Main Manuscript'}"
                        if scope is None else f"📘 {project.scope_label(scope)}")
                act = sub.addAction(name)
                act.triggered.connect(
                    lambda _=False, s=scope, c=list(chapters): self.move_to(c, s))
            sub.addSeparator()
            act = sub.addAction(MOVE_TO_NEW)
            act.triggered.connect(lambda _=False, c=list(chapters): self.move_to_new_novella(c))
            if me._active_draft is not None:
                sub.setEnabled(False)
                sub.setToolTip("Switch “Editing:” back to the manuscript to move its chapters.")
        delete = next((a for a in menu.actions() if a.text() == "Delete Chapter"), None)
        acts = menu.actions()
        before = None
        if delete is not None:
            i = acts.index(delete)
            before = acts[i - 1] if i > 0 and acts[i - 1].isSeparator() else delete
        if before is not None:
            menu.insertMenu(before, sub)
            menu.insertSeparator(sub.menuAction())
        else:
            menu.addSeparator()
            menu.addMenu(sub)
        return sub

    # ── drag and drop ──

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def dropEvent(self, event) -> None:
        try:
            item = self.itemAt(event.position().toPoint())
            target = self.drop_target(item, self.dropIndicatorPosition())
            dragged = self.selected_chapters()
            # The tree is rebuilt from the project: Qt itself moves nothing.
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            if target is not None and dragged:
                QTimer.singleShot(0, lambda: self.handle_drop(dragged, *target))
        except Exception as e:
            print(f"[manuscript tree] drop failed: {e}")
            event.ignore()

    def drop_target(self, item, indicator) -> Optional[Tuple[str, Optional[str], Optional[int]]]:
        """Where a drop lands: ("into", scope, index) — index None = after
        the last chapter — or ("new", None, None) for a new novella."""
        if item is None:
            return None
        P = QAbstractItemView.DropIndicatorPosition
        kind, scope, cid = self.where(item)
        if kind == NEW:
            return ("new", None, None) if indicator == P.OnItem else None
        if kind == MS:
            if indicator == P.AboveItem:
                i = self.indexOfTopLevelItem(item)
                prev = self.topLevelItem(i - 1) if i > 0 else None
                return ("into", self.where(prev)[1], None) if prev is not None else None
            if indicator == P.BelowItem and item.isExpanded() and item.childCount():
                return ("into", scope, 0)
            return ("into", scope, None)
        parent = item.parent()
        row = parent.indexOfChild(item) if parent is not None else 0
        return ("into", scope, row if indicator == P.AboveItem else row + 1)

    def handle_drop(self, chapters: List[Tuple[Optional[str], str]], how: str,
                    scope: Optional[str], index: Optional[int]) -> None:
        try:
            if how == "new":
                self.move_to_new_novella(chapters)
            elif all((s or None) == (scope or None) for s, _c in chapters):
                self.reorder([c for _s, c in chapters], scope, index)
            else:
                self.move_to(chapters, scope, index)
        except Exception as e:                   # never escape a slot
            print(f"[manuscript tree] drop failed: {e}")

    def reorder(self, chapter_ids: List[str], scope: Optional[str],
                index: Optional[int]) -> None:
        """Within one manuscript: the same steps as ↑ / ↓."""
        me = self.me
        if (scope or None) != self._active() and self._project() is not None:
            self.open_manuscript(scope)
        lst = me.chapter_list
        ids = [lst.item(r).data(Qt.ItemDataRole.UserRole) for r in range(lst.count())]
        picked = [c for c in ids if c in set(chapter_ids)]
        if not picked:
            return
        at = len(ids) if index is None else max(0, min(index, len(ids)))
        rest = [c for c in ids if c not in picked]
        at -= sum(1 for c in ids[:at] if c in picked)
        order = rest[:at] + picked + rest[at:]
        if order == ids:
            return
        open_id = me._current_chapter_id
        for pos, cid in enumerate(order):
            cur = next(r for r in range(lst.count())
                       if lst.item(r).data(Qt.ItemDataRole.UserRole) == cid)
            while cur > pos:
                lst.blockSignals(True)
                lst.setCurrentRow(cur)
                lst.blockSignals(False)
                me._move_chapter_up()
                cur -= 1
        lst.blockSignals(True)
        for r in range(lst.count()):
            if lst.item(r).data(Qt.ItemDataRole.UserRole) == open_id:
                lst.setCurrentRow(r)
        lst.blockSignals(False)
        me._update_nav_buttons()
        self.rebuild()

    # ── moving between manuscripts ──

    def _titles(self, chapters) -> List[str]:
        project = self._project()
        out = []
        for scope, cid in chapters:
            ms = project.get_manuscript_for(scope) if project else None
            ch = next((c for c in ms.chapters if c.id == cid), None) if ms else None
            out.append(ch.title if ch is not None else cid)
        return out

    def _prepare(self) -> None:
        """Save the open chapter and let every listener save, then close
        the editor so nothing holds a chapter that is about to move."""
        me = self.me
        me._flush_current_chapter()
        me._sync_active_draft_out()
        me._release_main_editor()

    def _after(self, open_id: Optional[str]) -> None:
        me, project = self.me, self.me.project
        me.load_manuscript(project.manuscript)
        me.subprojects_changed.emit()
        if open_id:
            scope, _ch = project.find_chapter_with_scope(open_id)
            me._last_chapter_by_scope[scope or None] = open_id
            if not me.open_chapter(open_id) and me.chapter_list.count():
                me.chapter_list.setCurrentRow(0)
        elif me.chapter_list.count():
            me.chapter_list.setCurrentRow(0)
        self.rebuild()

    def move_to(self, chapters: List[Tuple[Optional[str], str]], target: Optional[str],
                index: Optional[int] = None) -> bool:
        """Move ``chapters`` into manuscript ``target`` (None = main) at
        ``index`` (None = after the last), with Undo offered after."""
        me, project = self.me, self._project()
        if project is None:
            return False
        if me._active_draft is not None:
            QMessageBox.information(
                me, "Move Chapters", "You are editing a draft. Switch “Editing:” back to "
                "the manuscript to move its chapters.")
            return False
        chapters = [(s or None, c) for s, c in chapters if (s or None) != (target or None)]
        if not chapters:
            return False
        titles = self._titles(chapters)
        reopen = me._current_chapter_id
        self._prepare()
        from src.data import chapter_move
        try:
            result = chapter_move.move_chapters(project, chapters, target, index,
                                                project_file=project.project_path or None)
        except Exception as e:
            self._after(reopen)
            QMessageBox.critical(
                me, "Move Failed",
                f"“{titles[0]}”" + (f" and {len(titles) - 1} more" if len(titles) > 1 else "")
                + " could not be moved, so everything was put back as it was.\n\n" + str(e))
            return False
        if result is None:
            self._after(reopen)
            return False
        for m in result.renamed:
            try:
                me.memory_manager.cache.remove(m.original_id)
            except Exception:
                pass
        self._after(result.moved[0].chapter_id)
        where = project.scope_label(target) if target else (
            project.get_main_manuscript().title or "Main Manuscript")
        what = f"“{titles[0]}”" if len(titles) == 1 else f"{len(titles)} chapters"
        self._last = result
        self.announce(f"Moved {what} to {where}")
        return True

    def move_to_new_novella(self, chapters: List[Tuple[Optional[str], str]]) -> bool:
        me, project = self.me, self._project()
        if project is None or not chapters:
            return False
        if me._active_draft is not None:
            return self.move_to(chapters, None)          # says why not
        named = me._ask_novella_name_and_description("New Novella")
        if named is None:
            return False
        me._flush_current_chapter()
        sp = project.create_subproject(*named)
        me.subprojects_changed.emit()
        if not self.move_to(chapters, sp.id):
            me._discard_new_subproject(sp)
            return False
        return True

    def undo_last(self) -> bool:
        """Undo on the status bar: the same move back to the same place."""
        me, project, result = self.me, self._project(), self._last
        if project is None or result is None:
            return False
        self._last = None
        self._hide_notice()
        reopen = me._current_chapter_id
        self._prepare()
        from src.data import chapter_move
        try:
            back = chapter_move.undo(project, result, project_file=project.project_path or None)
        except Exception as e:
            self._after(reopen)
            QMessageBox.critical(me, "Undo Failed",
                                 "The move could not be undone, so the chapters were left "
                                 f"where they are now.\n\n{e}")
            return False
        self._after(back[0] if back else reopen)
        self.announce("Put back where it was.", undo=False)
        return True

    # ── the status-bar line ──

    def _status_bar(self) -> Optional[QStatusBar]:
        win = self.me.window()
        if isinstance(win, QMainWindow) and win.findChild(QStatusBar) is not None:
            return win.statusBar()
        return None

    def announce(self, text: str, undo: bool = True) -> None:
        bar = self._status_bar()
        if bar is None:                           # no status bar: a line under the tree
            if self.notice is not None:
                self.notice.setText(text + (" · <a href='undo'>Undo</a>" if undo else ""))
                self.notice.setVisible(True)
            return
        win = self.me.window()
        btn = getattr(win, "_tree_undo_btn", None)
        if btn is None:
            btn = QPushButton("Undo")
            btn.setFlat(True)
            btn.setStyleSheet("QPushButton { text-decoration: underline; padding: 0 6px; }")
            bar.addPermanentWidget(btn)
            win._tree_undo_btn = btn
            bar.messageChanged.connect(
                lambda m, w=win, b=btn: b.setVisible(bool(m) and m == getattr(w, "_tree_undo_text", None)))
        try:
            btn.clicked.disconnect()
        except TypeError:
            pass
        btn.clicked.connect(lambda _=False: self.undo_last())
        win._tree_undo_text = text if undo else None
        bar.showMessage(text, NOTICE_MS)
        btn.setVisible(undo)

    def _hide_notice(self) -> None:
        if self.notice is not None:
            self.notice.setVisible(False)
        win = self.me.window()
        btn = getattr(win, "_tree_undo_btn", None)
        if btn is not None:
            btn.setVisible(False)
            win._tree_undo_text = None


def _modifiers():
    from PyQt6.QtWidgets import QApplication
    return QApplication.keyboardModifiers()
