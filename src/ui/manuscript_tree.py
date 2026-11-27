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

**Always on** (D.11). The trial switch (Settings ▸ Features ▸ *Manuscript
tree*), the tab row and Novellas ▾ were retired; every entry they had is
on the tree's right-click. The switch's stored ``write/manuscript_tree``
(``SETTING_KEY``) is left in place and no longer read.

**Move main chapters into this novella** (a novella row's menu) moves
every main chapter with ``chapter_move.move_chapters``, the main
manuscript's drafts with them, and offers Undo (``move_main_into``, D.11).
**Turn main manuscript into a novella…** (the main row's menu, the first
novella's "Move into …", and the offer after dropping the last novella)
makes the novella and then does the same move (``turn_main_into_novella``,
D.12). Each question says what Undo covers and what it does not
(``undo_note``).

**Undo lasts until the next save** (D.14). The status bar's Undo still goes
after 30 seconds or when another message replaces it; the last move also
stays on the tree's right-click ("Undo the last move (…)", on a manuscript
row and under a chapter's Move to ▸) until the writer next saves the
project (File ▸ Save Project, Ctrl+S, the toolbar's Save, Save As:
``forget_last``), the next move, another project being opened, or the app
closing. The autosaves do not end it: they run after every move and
chapter switch, so they would end it at once. Undo after a move that made
a novella ("Turn main manuscript into a novella…", the first novella's
"Move into …", Move to ▸ ＋ A new novella…) also removes that novella if
it holds nothing of its own, and otherwise keeps it and says why ("kept:
it has Critique reports"). What counts is ``src/data/novella_content.py``
(D.14b): chapters, drafts, files in its folder, anything saved for it
beside the project, or a name or description changed since.

**Renaming a chapter** (D.13, in place of the Chapter Title row): double-click
it, press F2, or right-click ▸ Rename…, and its title is edited in the
tree. Enter keeps it, Esc cancels, an empty title is refused. The title is
saved as the title box saved it (``set_chapter_title``): the chapter, the
tree, the open editor, the window's "unsaved" mark and so autosave, and
everything that reads the title (exports, the Critique). The status bar
says "Renamed …" with Undo; Ctrl+Z in the tree does the same. Each
chapter's full title is in its tooltip.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QAction, QCursor, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPushButton, QStatusBar, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem,
)

SETTING_KEY = "write/manuscript_tree"   # the retired switch (D.10); left in place, unread (D.11)

KIND = Qt.ItemDataRole.UserRole
SCOPE = Qt.ItemDataRole.UserRole + 1
CHAPTER = Qt.ItemDataRole.UserRole + 2
MS, CH, NEW = "manuscript", "chapter", "new"

NEW_NOVELLA = "＋ New novella…"
MOVE_TO = "Move to"
MOVE_TO_NEW = "＋ A new novella…"
NOTICE_MS = 30000
RENAME = "Rename…"
CHAPTER_WORD = "chapter"                 # decision 18: the word in one place


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
        notice.linkActivated.connect(lambda _l: tree.run_undo())
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
        tree.show_tree()
    except Exception as e:                       # never break the Write tab
        print(f"[manuscript tree] not installed: {e}")


def add_move_menu(manuscript_editor: Any, menu: QMenu) -> None:
    """**Move to ▸** in a chapter's right-click menu (the call line in
    ``_show_chapter_context_menu``)."""
    tree = getattr(manuscript_editor, "manuscript_tree", None)
    try:
        if tree is not None:
            tree.fill_move_menu(menu)
            tree.rename_in_place(menu)
    except Exception as e:                       # the menu still opens
        print(f"[manuscript tree] no Move to: {e}")


def set_chapter_title(manuscript_editor: Any, chapter: Any, title: str) -> None:
    """Give ``chapter`` its new title everywhere the Chapter Title box did:
    the chapter, its row in the (hidden) chapter list and so the tree, the
    open editor's title (which is what it saves), and the "unsaved" mark
    and autosave through ``content_changed``."""
    me = manuscript_editor
    chapter.title = title
    in_list = False
    lst = me.chapter_list
    for r in range(lst.count()):
        item = lst.item(r)
        if item.data(Qt.ItemDataRole.UserRole) == chapter.id and me.manuscript is not None \
                and any(c is chapter for c in me.manuscript.chapters):
            item.setText(f"{chapter.number}. {title}")
            in_list = True
    ce = me.current_chapter_editor
    if in_list and ce is not None and getattr(ce, "chapter", None) is chapter:
        ce.title_edit.setPlainText(title)        # emits content_changed, as typing in it did
    else:
        me.content_changed.emit()


UNDO_MENU = "Undo the last move"
UNTIL_SAVED = ("until you next save the project yourself (Save Project, Ctrl+S; the app's "
               "own autosaves don't count), make another move or close the app")


def undo_note(n_drafts: int, novella: str = "", new: bool = False) -> str:
    """What Undo covers, for the questions before moving the whole main
    manuscript (D.12, D.14). Undo is the status bar's button (``announce``):
    it shows for ``NOTICE_MS`` and goes when another message replaces it.
    The last move also stays on the tree's right-click (``UNDO_MENU``) until
    the writer next saves the project (``forget_last``, from File ▸ Save
    Project / Save As; the autosaves, which run after every move and
    chapter switch, do not end it), the next move, or the app closing.
    A novella the move made is removed by Undo if it holds nothing of its
    own (``novella_content.holds``, D.14b). Chapters can always be moved back by hand (Move to ▸); a
    draft's manuscript cannot be changed by hand, so after Undo has gone
    the drafts stay with the novella."""
    where = f"“{novella}”" if novella else "the new novella"
    what = "the chapters and drafts" if n_drafts else "the chapters"
    seconds = NOTICE_MS // 1000
    text = (f"Undo, on the status bar for {seconds} seconds (until another message replaces "
            f"it), puts {what} back"
            + (f" and removes {where} (unless something has been added to it or saved "
               f"for it since)." if new else "."))
    text += (f" It is also on the manuscript tree's right-click (“{UNDO_MENU}”) {UNTIL_SAVED}.")
    text += (" After that you can still move the chapters back (right-click ▸ Move to)"
             + (f", but the drafts stay with {where}." if n_drafts else "."))
    return text


def forget_last(manuscript_editor: Any) -> None:
    """The writer saved the project (the call line in ``MainWindow._save_to_path``):
    the last move is no longer offered for Undo (D.14)."""
    tree = getattr(manuscript_editor, "manuscript_tree", None)
    try:
        if tree is not None:
            tree.forget_last()
    except Exception as e:                       # saving never fails because of this
        print(f"[manuscript tree] could not forget the last move: {e}")


def _move_question(project: Any, novella: str, new: bool, after: str = "") -> str:
    main = project.get_main_manuscript()
    n_drafts = len(project.drafts_for_scope(None))
    into = f"a new novella '{novella}'" if new else f"'{novella}'"
    return (f"Move the main manuscript's {len(main.chapters)} chapter(s) and "
            f"{n_drafts} draft(s) into {into}?{after}\n\n"
            "The folders are moved, not copied, and the main manuscript will be empty "
            "afterwards. " + undo_note(n_drafts, novella, new))


def move_main_into(manuscript_editor: Any, sp_id: str) -> bool:
    """"Move main chapters into this novella" (the call line in
    ``ManuscriptEditor._move_main_into_existing``): ask once, then move every
    main chapter with the tree's move, the main manuscript's drafts with
    them, and offer Undo (D.11; it used to copy, check and delete)."""
    me = manuscript_editor
    project = me.project
    sp = project.get_subproject(sp_id) if project is not None else None
    main = project.get_main_manuscript() if project is not None else None
    if sp is None or main is None or not main.chapters:
        return False
    tree = getattr(me, "manuscript_tree", None)
    if tree is None:                             # never moved without the tree's Undo
        QMessageBox.information(me, "Move Chapters", "The manuscript tree is not available, "
                                "so nothing was moved.")
        return False
    after = (f" They'll follow its {len(sp.manuscript.chapters)} existing "
             f"chapter(s)." if sp.manuscript.chapters else "")
    reply = QMessageBox.question(
        me, "Move chapters", _move_question(project, sp.name, False, after),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return False
    try:
        return tree.move_main_into(sp_id)
    except Exception as e:                       # never escape a slot
        print(f"[manuscript tree] move main chapters failed: {e}")
        return False


def turn_main_question(project: Any, novella: str) -> str:
    """The question "Turn main manuscript into a novella…" asks (the call
    line in ``ManuscriptEditor._turn_main_into_novella``)."""
    return _move_question(project, novella, True)


def turn_main_into_novella(manuscript_editor: Any, name: str, description: str = "") -> bool:
    """Make novella ``name`` and move every main chapter (and the main
    manuscript's drafts) into it with the tree's move, with Undo (the call
    line in ``ManuscriptEditor._create_novella_from_main``; D.12, it used to
    copy, check and delete through ``move_main_content_to_subproject``).
    The question has been asked. Ends on the novella, on its first chapter.
    If the move cannot be made, the new novella is taken away again and
    nothing else has changed."""
    me = manuscript_editor
    project = me.project
    if project is None or not project.get_main_manuscript().chapters:
        return False
    tree = getattr(me, "manuscript_tree", None)
    if tree is None:                             # never moved without the tree's Undo
        QMessageBox.information(me, "Move Chapters", "The manuscript tree is not available, "
                                "so nothing was moved.")
        return False
    if tree.draft_open():                        # says why not, makes nothing (as D.10)
        return False
    me._flush_current_chapter()
    sp = project.create_subproject(name, description)
    me.subprojects_changed.emit()
    try:
        moved = tree.move_main_into(sp.id)
    except Exception as e:                       # never escape a slot
        print(f"[manuscript tree] turn main into a novella failed: {e}")
        moved = False
    if moved:
        tree.remember_made(sp)                   # Undo removes it while still empty (D.14, D.14b)
        # The box the writer chose to keep for this move (D.9); Undo stays
        # on the status bar, its time started again once the box is closed.
        QMessageBox.information(
            me, "Chapters Moved",
            f"Moved {len(sp.manuscript.chapters)} chapter(s) into '{sp.name}'. The main "
            f"manuscript is now empty.\n\nUndo is on the status bar for "
            f"{NOTICE_MS // 1000} seconds, and on the manuscript tree's right-click "
            f"{UNTIL_SAVED}.")
        tree.announce_again()
        return True
    if not moved:
        me._discard_new_subproject(sp)
        try:                                     # the file as it was, novella gone too
            if project.project_path and project.get_subproject(sp.id) is None:
                project.save_project(project.project_path)
        except Exception as e:
            print(f"[manuscript tree] could not save after taking the novella away: {e}")
        return False
    return True


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
        self.notice: Optional[QLabel] = None
        self._last = None                        # the last move, for Undo
        self._last_drafts = None                 # (drafts, novella id) moved with it
        self._last_made = None                   # a novella the move made (D.14)
        self._made_as = None                     # what it was given then (D.14b)
        self._last_project = None                # the project it was made in
        self._last_label = ""                    # "“The Storm” to The Fall", for the menu
        self._announced = ""                     # the last line shown with Undo
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
        # D.13: a chapter's title is edited in place (double-click, F2, Rename…).
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                             | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setItemDelegateForColumn(0, _TitleDelegate(self))
        self._undo_fn = self.undo_last           # what the status bar's Undo does
        self._last_rename = None                 # (chapter, old title, new title)
        self._rebuild_after_edit = False
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

    # ── shown in place of the old row and list ──

    def show_tree(self) -> None:
        self.setVisible(True)
        self.me.chapter_list.setVisible(False)
        self.me.subproject_tabs.setVisible(False)
        self.rebuild()

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Undo) and self._last_rename is not None:
            self.undo_rename()                   # Ctrl+Z after a rename
            event.accept()
            return
        if event.key() == Qt.Key.Key_F2 and self.currentItem() is not None \
                and self.currentItem().data(0, KIND) == CH \
                and self.state() != QAbstractItemView.State.EditingState:
            self.editItem(self.currentItem(), 0)  # F2 on every platform (on a Mac, Qt's
            event.accept()                       # edit key is Enter, which opens here)
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentItem() is not None:
            self.activate(self.currentItem())    # arrows move; Enter opens
            event.accept()
            return
        super().keyPressEvent(event)

    def after_tabs_refresh(self) -> None:
        self.me.subproject_tabs.setVisible(False)
        self.schedule()

    # ── building ──

    def schedule(self) -> None:
        if not self._building:
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
        self._timer.stop()
        if self.state() == QAbstractItemView.State.EditingState:
            self._rebuild_after_edit = True      # never close a title being typed
            return
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
                                   | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsEditable)
                    child.setToolTip(0, f"{text}\n\nClick to open · double-click or F2 to "
                                        "rename · drag to move · right-click for more")
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
        if self._building:
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
        (retired with the tab row in D.11), calling the same methods."""
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
        if self.undo_available():                # D.14: until the next save
            menu.addSeparator()
            a = menu.addAction(self.undo_menu_text())
            actions[a] = self.undo_last
        menu.addSeparator()
        a = menu.addAction(NEW_NOVELLA)
        actions[a] = me._create_subproject
        return menu, actions

    def chapter_menu(self, scope: Optional[str], cid: str, global_pos: QPoint) -> None:
        """The chapter's old right-click menu, unchanged, plus Move to ▸."""
        me = self.me
        chosen = self.selected_chapters()
        self._menu_chapters = chosen if (scope, cid) in chosen else [(scope, cid)]
        self._menu_target = (scope, cid)
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
            self._menu_target = None

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
        if self.undo_available():                # D.14: until the next save
            undo = QAction(self.undo_menu_text(), menu)
            undo.triggered.connect(lambda _=False: self.run_undo_last())
            if before is not None:
                menu.insertAction(before, undo)
            else:
                menu.addAction(undo)
        return sub

    # ── renaming a chapter (D.13) ──

    def chapter_object(self, scope: Optional[str], cid: str):
        """The Chapter a row stands for (the open manuscript's, or a draft's
        while one is open, as the list shows it)."""
        me, project = self.me, self._project()
        if project is None or (scope or None) == self._active():
            ms = me.manuscript
        else:
            ms = project.get_manuscript_for(scope)
        return next((c for c in getattr(ms, "chapters", None) or [] if c.id == cid), None)

    def rename_chapter(self, scope: Optional[str], cid: str, title: str) -> bool:
        """The edited title, kept: refused when empty, nothing when the same."""
        chapter = self.chapter_object(scope, cid)
        if chapter is None:
            return False
        title = " ".join((title or "").split())
        if not title:
            self.announce(f"A {CHAPTER_WORD} needs a title, so “{chapter.title}” was kept.",
                          undo=False)
            return False
        if title == chapter.title:
            return False
        old = chapter.title
        set_chapter_title(self.me, chapter, title)
        self._last_rename = (chapter, old, title)
        self.schedule()
        self.announce(f"Renamed “{old}” to “{title}”", undo_fn=self.undo_rename)
        return True

    def undo_rename(self) -> bool:
        """The last rename's Undo (the status bar's, or Ctrl+Z in the tree)."""
        last, self._last_rename = self._last_rename, None
        if last is None:
            return False
        chapter, old, new = last
        self._hide_notice()
        if chapter.title != new:                 # renamed again since: leave it
            return False
        set_chapter_title(self.me, chapter, old)
        self.schedule()
        self.announce(f"Put back “{old}”", undo=False)
        return True

    def edit_title(self, scope: Optional[str], cid: str) -> bool:
        """Start editing a chapter's title in place."""
        item = self.chapter_item(scope, cid)
        if item is None:
            return False
        self.setCurrentItem(item)
        self.scrollToItem(item)
        self.setFocus()
        self.editItem(item, 0)
        return True

    def rename_in_place(self, menu: QMenu) -> None:
        """The chapter menu's Rename becomes "Rename…", editing the title in
        the tree (the box it asked in before is still ``_rename_chapter``)."""
        act = next((a for a in menu.actions() if a.text() == "Rename"), None)
        target = getattr(self, "_menu_target", None)
        if act is None or target is None:
            return
        act.setText(RENAME)
        act.setToolTip("Edit the title here in the tree (or double-click it, or press F2)")
        try:
            act.triggered.disconnect()
        except TypeError:
            pass
        scope, cid = target
        act.triggered.connect(
            lambda _=False: QTimer.singleShot(0, lambda: self.edit_title(scope, cid)))

    def closeEditor(self, editor, hint) -> None:   # noqa: N802 — Qt's name
        super().closeEditor(editor, hint)
        if self._rebuild_after_edit:
            self._rebuild_after_edit = False
            self.schedule()

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
        if self.draft_open():
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
        self._last_drafts = None
        self._last_made = None
        self._last_project = project
        self._last_label = f"{what} to {where}"
        self.announce(f"Moved {what} to {where}")
        return True

    def draft_open(self) -> bool:
        """While "Editing:" shows a draft no chapter moves: says so."""
        me = self.me
        if me._active_draft is None:
            return False
        QMessageBox.information(
            me, "Move Chapters", "You are editing a draft. Switch “Editing:” back to "
            "the manuscript to move its chapters.")
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
        self.remember_made(sp)                   # Undo removes it while still empty (D.14, D.14b)
        return True

    def move_main_into(self, sp_id: str) -> bool:
        """Every main chapter into novella ``sp_id``, after its own chapters,
        through ``move_to`` (``chapter_move.move_chapters``: folders renamed in
        place, nothing overwritten, everything put back on failure). The main
        manuscript's drafts go with it, as they always did; Undo brings them
        back too."""
        project = self._project()
        if project is None or project.get_subproject(sp_id) is None:
            return False
        chapters = [(None, c.id) for c in project.get_main_manuscript().chapters]
        drafts = [d for d in getattr(project, "drafts", []) if d.subproject_id is None]
        if not chapters or not self.move_to(chapters, sp_id):
            return False
        if drafts:
            for d in drafts:
                d.subproject_id = sp_id
            try:
                if project.project_path:
                    project.save_project(project.project_path)
            except Exception as e:                # the chapters moved; the drafts stay with main
                for d in drafts:
                    d.subproject_id = None
                QMessageBox.warning(self.me, "Drafts Not Moved",
                                    "The chapters were moved, but the main manuscript's drafts "
                                    f"could not be, so they stay with it.\n\n{e}")
                return True
            self._last_drafts = (drafts, sp_id)
            self.me.subprojects_changed.emit()
            try:
                self.me._refresh_draft_selector()
            except Exception:
                pass
        return True

    def undo_available(self) -> bool:
        """The last move can still be undone: there is one, made in the
        project that is open, not ended by a save (D.14)."""
        return (self._last is not None and self._project() is not None
                and self._last_project is self._project())

    def undo_menu_text(self) -> str:
        return f"{UNDO_MENU} ({self._last_label})" if self._last_label else UNDO_MENU

    def forget_last(self) -> None:
        """The writer saved: the last move is no longer offered (D.14)."""
        self._last = self._last_drafts = self._last_made = self._last_project = None
        self._made_as = None
        self._last_label = ""
        if self._undo_fn == self.undo_last:
            self._hide_notice()

    def run_undo_last(self) -> None:
        try:
            self.undo_last()
        except Exception as e:                   # never escape a slot
            print(f"[manuscript tree] undo failed: {e}")

    def undo_last(self) -> bool:
        """Undo (the status bar's, or the tree's right-click until the next
        save): the same move back to the same place; a novella the move
        made is removed too, if it holds nothing of its own (D.14b)."""
        me, project, result = self.me, self._project(), self._last
        if project is None or result is None or not self.undo_available():
            return False
        if self.draft_open():                    # says why not; Undo stays
            return False
        self._last = None
        self._last_project = None
        self._last_label = ""
        made, self._last_made = self._last_made, None
        drafts, self._last_drafts = self._last_drafts, None
        self._hide_notice()
        reopen = me._current_chapter_id
        self._prepare()
        from src.data import chapter_move
        for d in (drafts[0] if drafts else []):  # saved with the chapters put back
            if d.subproject_id == drafts[1]:
                d.subproject_id = None
        try:
            back = chapter_move.undo(project, result, project_file=project.project_path or None)
            if drafts and project.project_path:
                project.save_project(project.project_path)
        except Exception as e:
            for d in (drafts[0] if drafts else []):
                if d.subproject_id is None:
                    d.subproject_id = drafts[1]
            self._after(reopen)
            QMessageBox.critical(me, "Undo Failed",
                                 "The move could not be undone, so the chapters were left "
                                 f"where they are now.\n\n{e}")
            return False
        self._after(back[0] if back else reopen)
        said = "Put back where it was." if back else (
            "Nothing was put back: the moved chapters are no longer there.")
        if made:
            said += " " + self._drop_made(made)
        self.announce(said.strip(), undo=False)
        return True

    def remember_made(self, sp: Any) -> None:
        """The novella this move made, and what it was given (D.14b)."""
        from src.data import novella_content
        self._last_made = sp.id
        self._made_as = novella_content.snapshot(sp)

    def _drop_made(self, sp_id: str) -> str:
        """After Undo: take away the novella the move made if it holds
        nothing of its own (``novella_content.holds``: no chapters, drafts,
        files but its ``subproject.json``, nothing saved for it beside the
        project, nothing changed since it was made), else keep it and say
        why (D.14, D.14b). Nothing that held anything is deleted from disk."""
        me, project = self.me, self._project()
        sp = project.get_subproject(sp_id) if project is not None else None
        if sp is None:
            return ""
        name = f"“{sp.name}”"
        made, self._made_as = getattr(self, "_made_as", None), None
        from src.data import novella_content
        try:
            try:
                project_dir = me._get_project_dir()
            except Exception:
                project_dir = None
            what = novella_content.holds(project, sp_id, project_dir, made)
        except Exception as e:                   # unsure: kept
            print(f"[manuscript tree] could not tell what the novella holds: {e}")
            what = ["something that could not be checked"]
        if what:
            return f"{name} was kept: {novella_content.because(what)}."
        try:
            if project.active_subproject_id == sp_id:
                me.switch_subproject(None)
            me._discard_new_subproject(sp)
            if project.project_path and project.get_subproject(sp_id) is None:
                project.save_project(project.project_path)
        except Exception as e:
            print(f"[manuscript tree] could not remove the empty novella: {e}")
            return ""
        self.rebuild()
        return f"{name} was removed."

    # ── the status-bar line ──

    def _status_bar(self) -> Optional[QStatusBar]:
        win = self.me.window()
        if isinstance(win, QMainWindow) and win.findChild(QStatusBar) is not None:
            return win.statusBar()
        return None

    def announce_again(self) -> None:
        """Show the last move's line and Undo once more, for its full time
        (after a box that was open while the first one ran)."""
        if self._last is not None and self._announced:
            self.announce(self._announced)

    def run_undo(self) -> None:
        try:
            self._undo_fn()
        except Exception as e:                   # never escape a slot
            print(f"[manuscript tree] undo failed: {e}")

    def announce(self, text: str, undo: bool = True, undo_fn=None) -> None:
        """The status-bar line, with Undo: a move's (``undo_last``) unless
        ``undo_fn`` is given (a rename's)."""
        self._undo_fn = undo_fn or self.undo_last
        self._announced = text if undo and undo_fn is None else ""
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
        btn.clicked.connect(lambda _=False: self.run_undo())
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


class _TitleDelegate(QStyledItemDelegate):
    """Edits a chapter row's title alone (the row reads "3. The Storm").
    Enter keeps it, Esc cancels; the tree is rebuilt from the chapter."""

    def __init__(self, tree: ManuscriptTree):
        super().__init__(tree)
        self.tree = tree

    def createEditor(self, parent, option, index):   # noqa: N802 — Qt's name
        if index.data(KIND) != CH:
            return None
        edit = QLineEdit(parent)
        edit.setPlaceholderText(f"The {CHAPTER_WORD}'s title")
        return edit

    def setEditorData(self, editor, index) -> None:   # noqa: N802
        chapter = self.tree.chapter_object(index.data(SCOPE) or None, index.data(CHAPTER))
        editor.setText(chapter.title if chapter is not None else "")
        editor.selectAll()

    def setModelData(self, editor, model, index) -> None:   # noqa: N802
        try:
            self.tree.rename_chapter(index.data(SCOPE) or None, index.data(CHAPTER),
                                     editor.text())
        except Exception as e:                   # never escape a slot
            print(f"[manuscript tree] rename failed: {e}")


def _has_files(manuscript_editor: Any, sp_id: str) -> bool:
    """Any file in the novella's folder but its own ``subproject.json``."""
    try:
        project_dir = manuscript_editor._get_project_dir()
    except Exception:
        project_dir = None
    if not project_dir:
        return False
    folder = project_dir / "subprojects" / sp_id
    return folder.is_dir() and any(p.is_file() and p.name != "subproject.json"
                                   for p in folder.rglob("*"))


def _modifiers():
    from PyQt6.QtWidgets import QApplication
    return QApplication.keyboardModifiers()
