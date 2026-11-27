"""D.10: one manuscript tree on the left of the Write screen.

The tree replaces the row of manuscript tabs and Novellas ▾; the old chapter
list and tab bar are kept, hidden, and driven by it. The switch in
Settings ▸ Features brings the old row back exactly. Projects are built in
``tmp_path``; no model runs.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt

from src.models.project import Chapter, Manuscript, WriterProject
from src.ui import manuscript_tree as mt


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _project(tmp_path, novellas=True):
    path = tmp_path / "Saga.writerproj"
    p = WriterProject(name="Saga", manuscript=Manuscript(title="Main Manuscript"))
    p.manuscript.chapters = [Chapter(id=f"m{i}", number=i, title=t, content=f"Main {i}.")
                             for i, t in enumerate(["The Storm", "The Pier", "The Letter"], 1)]
    if novellas:
        fall = p.create_subproject("The Fall")
        fall.manuscript.chapters = [Chapter(id=f"f{i}", number=i, title=f"Fall {i}",
                                            content=f"Fall {i}.") for i in (1, 2)]
        p._normalize_manuscript_roots()
    p.save_project(str(path))
    p.save_project(str(path))
    return p


def _editor(app, p):
    from src.ui.manuscript_editor import ManuscriptEditor
    w = ManuscriptEditor()
    w.set_project(p)
    w.load_manuscript(p.manuscript)
    w.open_chapter(p.manuscript.chapters[0].id)
    w.resize(1440, 900)
    w.show()
    app.processEvents()
    w.manuscript_tree.rebuild()
    return w


@pytest.fixture
def boxes(monkeypatch):
    """No box may block: record them instead."""
    from PyQt6.QtWidgets import QMessageBox
    shown = []
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: shown.append((_n, a[1] if len(a) > 1 else "")) or
            QMessageBox.StandardButton.No))
    return shown


def _rows(tree):
    out = []
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        out.append((top.text(0), top.text(1)))
        for j in range(top.childCount()):
            out.append(("  " + top.child(j).text(0), ""))
    return out


def _ids(p, scope):
    return [c.id for c in p.get_manuscript_for(scope).chapters]


# ── What the writer sees ─────────────────────────────────────────────

def test_the_tree_shows_every_manuscript_and_chapter(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    tree = w.manuscript_tree
    assert tree.isVisibleTo(w) and not w.chapter_list.isVisibleTo(w)
    fall = p.subprojects[0].id
    assert _rows(tree)[:4] == [("📖 Main Manuscript", "3"), ("  1. The Storm", ""),
                               ("  2. The Pier", ""), ("  3. The Letter", "")]
    assert _rows(tree)[4] == ("📘 The Fall", "2")
    assert tree.topLevelItem(2).text(0) == mt.NEW_NOVELLA
    # The open manuscript is expanded, the others collapsed; the open chapter is current.
    assert tree.manuscript_item(None).isExpanded()
    assert not tree.manuscript_item(fall).isExpanded()
    assert tree.manuscript_item(fall).childCount() == 2
    assert tree.currentItem().data(0, mt.CHAPTER) == "m1"
    assert "chapter(s)" in tree.manuscript_item(fall).toolTip(0)


def test_with_no_novellas_main_shows_its_chapters_underneath(app, tmp_path):
    p = _project(tmp_path, novellas=False)
    w = _editor(app, p)
    tree = w.manuscript_tree
    assert [r[0] for r in _rows(tree)] == ["📖 Main Manuscript", "  1. The Storm",
                                           "  2. The Pier", "  3. The Letter", mt.NEW_NOVELLA]


def test_the_old_row_is_gone_and_the_counts_fall(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    from PyQt6.QtWidgets import QPushButton, QTabBar, QToolButton
    buttons = [b.text() for b in w.findChildren((QPushButton, QToolButton))
               if b.isVisibleTo(w) and (b.text().strip() or not b.icon().isNull())]
    assert "Novellas ▾" not in buttons and len(buttons) == 18, buttons
    assert not any(b.isVisibleTo(w) for b in w.findChildren(QTabBar))
    # Kept, hidden, and still kept right: other code reads them.
    assert w.subproject_tabs.count() == 2 and w.chapter_list.count() == 3


def test_the_switch_off_shows_the_old_row_exactly_as_before(app, tmp_path):
    mt.set_on(False)
    p = _project(tmp_path)
    w = _editor(app, p)
    from PyQt6.QtWidgets import QPushButton, QToolButton
    buttons = [b.text() for b in w.findChildren((QPushButton, QToolButton))
               if b.isVisibleTo(w) and (b.text().strip() or not b.icon().isNull())]
    assert "Novellas ▾" in buttons and len(buttons) == 19
    assert w.subproject_tabs.isVisibleTo(w) and w.chapter_list.isVisibleTo(w)
    assert not w.manuscript_tree.isVisibleTo(w)
    # No Move to ▸ in the old chapter menu.
    from PyQt6.QtWidgets import QMenu
    menu = QMenu()
    mt.add_move_menu(w, menu)
    assert not menu.actions()
    # And back on, live.
    mt.set_on(True)
    app.processEvents()
    assert w.manuscript_tree.isVisibleTo(w) and not w.subproject_tabs.isVisibleTo(w)
    assert not w.novellas_menu_btn.isVisibleTo(w)


def test_the_switch_starts_on_and_reads_bad_values_as_on(app, monkeypatch):
    assert mt.on() is True
    mt.set_on(False)
    assert mt.on() is False
    mt._settings().setValue(mt.SETTING_KEY, "perhaps")
    assert mt.on() is True

    def broken():
        raise RuntimeError("unreadable")
    monkeypatch.setattr(mt, "_settings", broken)
    assert mt.on() is True


def test_the_settings_option(app):
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    host = QWidget()
    lay = QVBoxLayout(host)
    opt = mt.TreeOption(lay)
    assert opt.box.isChecked()
    opt.box.setChecked(False)
    opt.save()
    assert mt.on() is False


# ── Opening ──────────────────────────────────────────────────────────

def test_clicking_a_chapter_in_another_manuscript_switches_and_opens_it(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    fall = p.subprojects[0].id
    events = []
    w.subproject_about_to_switch.connect(
        lambda: events.append(("about", p.active_subproject_id, w._current_chapter_id)))
    w.subproject_switched.connect(lambda: events.append(("switched", p.active_subproject_id)))
    w.current_chapter_editor.editor.setPlainText("Main 1, edited before switching.")
    tree = w.manuscript_tree
    tree.manuscript_item(fall).setExpanded(True)
    tree.activate(tree.chapter_item(fall, "f2"))
    app.processEvents()
    assert p.active_subproject_id == fall and w._current_chapter_id == "f2"
    # The outgoing manuscript was saved as the tab switch always did.
    assert events[0] == ("about", None, "m1") and events[-1] == ("switched", fall)
    assert p.get_main_manuscript().chapters[0].content == "Main 1, edited before switching."
    assert w.subproject_tabs.tabData(w.subproject_tabs.currentIndex()) == fall
    tree.rebuild()
    assert tree.manuscript_item(fall).isExpanded() and not tree.manuscript_item(None).isExpanded()


def test_clicking_a_manuscript_row_opens_it_and_new_novella_row_starts_one(app, tmp_path, monkeypatch):
    p = _project(tmp_path)
    w = _editor(app, p)
    fall = p.subprojects[0].id
    tree = w.manuscript_tree
    tree.activate(tree.manuscript_item(fall))
    app.processEvents()
    assert p.active_subproject_id == fall and w._current_chapter_id == "f1"
    made = []
    monkeypatch.setattr(w, "_create_subproject", lambda: made.append(True))
    tree.rebuild()
    tree.activate(tree.new_novella_item())
    assert made


def test_prev_next_and_plus_move_the_tree_with_the_list(app, tmp_path, monkeypatch):
    p = _project(tmp_path)
    w = _editor(app, p)
    tree = w.manuscript_tree
    w.next_chapter_btn.click()
    app.processEvents()
    assert tree.currentItem().data(0, mt.CHAPTER) == "m2"
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("The Tide", True)))
    w._add_chapter()
    app.processEvents()
    assert tree.manuscript_item(None).childCount() == 4
    assert tree.manuscript_item(None).text(1) == "4"


def test_keyboard_arrows_move_and_enter_opens(app, tmp_path):
    from PyQt6.QtTest import QTest
    p = _project(tmp_path)
    w = _editor(app, p)
    tree = w.manuscript_tree
    tree.setFocus()
    QTest.keyClick(tree, Qt.Key.Key_Down)
    QTest.keyClick(tree, Qt.Key.Key_Down)
    assert tree.currentItem().data(0, mt.CHAPTER) == "m3"
    assert w._current_chapter_id == "m1"                # moved, not opened
    QTest.keyClick(tree, Qt.Key.Key_Return)
    app.processEvents()
    assert w._current_chapter_id == "m3"


# ── Right-click ──────────────────────────────────────────────────────

def _labels(menu):
    out = []
    for a in menu.actions():
        if a.isSeparator():
            continue
        out.append(a.text())
    return out


@pytest.mark.parametrize("which", ["main", "novella"])
def test_a_manuscript_rows_menu_has_every_entry_of_its_old_tab_menu(app, tmp_path, monkeypatch, which):
    p = _project(tmp_path)
    w = _editor(app, p)
    scope = None if which == "main" else p.subprojects[0].id
    from PyQt6.QtWidgets import QMenu
    captured = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: captured.append(_labels(self)))
    mt.set_on(False)
    app.processEvents()
    tabs = w.subproject_tabs
    i = next(i for i in range(tabs.count()) if (tabs.tabData(i) or None) == scope)
    w._show_subproject_tab_menu(tabs.tabRect(i).center())
    old = captured[-1]
    mt.set_on(True)
    menu, actions = w.manuscript_tree.manuscript_menu(scope)
    assert _labels(menu) == old and len(actions) == len(old)
    assert any("Critique" in t for t in old) and "Rename…" in old and mt.NEW_NOVELLA in old


def test_a_manuscript_rows_entries_call_the_same_methods(app, tmp_path, monkeypatch):
    p = _project(tmp_path)
    w = _editor(app, p)
    fall = p.subprojects[0].id
    called = []
    for name in ("_rename_subproject", "_edit_subproject_description", "_move_main_into_existing",
                 "_delete_subproject", "_create_subproject"):
        monkeypatch.setattr(w, name, lambda *a, _n=name: called.append(_n))
    critiques = []
    w.manuscript_critique_requested.connect(lambda s, c: critiques.append((s, c)))
    menu, actions = w.manuscript_tree.manuscript_menu(fall)
    for act, run in actions.items():
        run()
    assert called == ["_rename_subproject", "_edit_subproject_description",
                      "_move_main_into_existing", "_delete_subproject", "_create_subproject"]
    assert critiques == [(fall, False)]


def test_a_chapters_menu_is_the_old_one_plus_move_to(app, tmp_path, monkeypatch):
    p = _project(tmp_path)
    w = _editor(app, p)
    fall = p.subprojects[0].id
    from PyQt6.QtWidgets import QMenu
    captured = []

    def fake_exec(self, *a):
        captured.append(self)
        return None
    monkeypatch.setattr(QMenu, "exec", fake_exec)
    tree = w.manuscript_tree
    item = tree.chapter_item(None, "m2")
    tree.chapter_menu(None, "m2", tree.viewport().mapToGlobal(tree.visualItemRect(item).center()))
    menu = captured[-1]
    labels = _labels(menu)
    for old in ("Rename", "Insert Before", "New Draft", "Drafts...", "Delete Chapter",
                "🗑 Bulk Cut Chapters…"):
        assert old in labels
    assert labels.index(mt.MOVE_TO) < labels.index("Delete Chapter")
    sub = next(a.menu() for a in menu.actions() if a.text() == mt.MOVE_TO)
    assert _labels(sub) == ["📘 The Fall", mt.MOVE_TO_NEW]
    assert w._current_chapter_id == "m2"                 # it opened, as the old menu did
    assert "itemAt" not in vars(w.chapter_list)          # the list is itself again
    # Choosing The Fall moves it.
    next(a for a in sub.actions() if a.text() == "📘 The Fall").trigger()
    app.processEvents()
    assert _ids(p, fall) == ["f1", "f2", "m2"]


# ── Drag and drop, and Move to ▸ ─────────────────────────────────────

def test_reorder_by_drag_matches_up_and_down(app, tmp_path):
    a = _project(tmp_path / "a")
    b = _project(tmp_path / "b")
    wa, wb = _editor(app, a), _editor(app, b)
    # Drag "The Storm" below "The Letter".
    tree = wa.manuscript_tree
    P = tree.dropIndicatorPosition().__class__
    target = tree.drop_target(tree.chapter_item(None, "m3"), P.BelowItem)
    assert target == ("into", None, 3)
    tree.handle_drop([(None, "m1")], *target)
    # ↓ twice on the other.
    wb.chapter_list.setCurrentRow(0)
    wb._move_chapter_down()
    wb._move_chapter_down()
    order = lambda p: [(c.id, c.number, c.folder_path) for c in p.manuscript.chapters]
    assert order(a) == order(b)
    assert [c.id for c in a.manuscript.chapters] == ["m2", "m3", "m1"]
    a.save_project(a.project_path)
    b.save_project(b.project_path)
    for c in a.manuscript.chapters:
        assert (tmp_path / "a" / c.folder_path / "revision_001.md").read_text() == \
            (tmp_path / "b" / c.folder_path / "revision_001.md").read_text()


def test_drop_targets(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    tree = w.manuscript_tree
    fall = p.subprojects[0].id
    P = tree.dropIndicatorPosition().__class__
    assert tree.drop_target(tree.manuscript_item(fall), P.OnItem) == ("into", fall, None)
    assert tree.drop_target(tree.chapter_item(None, "m2"), P.AboveItem) == ("into", None, 1)
    assert tree.drop_target(tree.manuscript_item(None), P.BelowItem) == ("into", None, 0)
    assert tree.drop_target(tree.manuscript_item(fall), P.AboveItem) == ("into", None, None)
    assert tree.drop_target(tree.new_novella_item(), P.OnItem) == ("new", None, None)
    assert tree.drop_target(None, P.OnItem) is None
    # Manuscript rows cannot be dragged; chapters can.
    assert not tree.manuscript_item(None).flags() & Qt.ItemFlag.ItemIsDragEnabled
    assert tree.chapter_item(None, "m1").flags() & Qt.ItemFlag.ItemIsDragEnabled


@pytest.mark.parametrize("how", ["drag", "menu"])
def test_move_main_to_novella_then_on_and_back_with_undo(app, tmp_path, boxes, how):
    p = _project(tmp_path)
    w = _editor(app, p)
    tree = w.manuscript_tree
    fall = p.subprojects[0].id
    d = tmp_path
    before = {str(f.relative_to(d)): f.read_bytes() for f in d.rglob("*")
              if f.is_file() and "chapter_" in str(f)}
    w.current_chapter_editor.editor.setPlainText("Main 1, written just now.")

    if how == "drag":
        tree.handle_drop([(None, "m1")], "into", fall, None)
    else:
        tree.move_to([(None, "m1")], fall)
    app.processEvents()
    assert _ids(p, None) == ["m2", "m3"] and _ids(p, fall) == ["f1", "f2", "m1"]
    # The open chapter was saved first, and is open where it now is.
    assert p.find_chapter("m1").content == "Main 1, written just now."
    assert (d / "subprojects" / fall / "chapters" / "chapter_003" / "revision_001.md").read_text() \
        == "Main 1, written just now."
    assert p.active_subproject_id == fall and w._current_chapter_id == "m1"
    assert tree.notice.isVisibleTo(w)
    assert "Moved “The Storm” to The Fall" in tree.notice.text() and "Undo" in tree.notice.text()

    assert tree.undo_last()
    app.processEvents()
    assert _ids(p, None) == ["m1", "m2", "m3"] and _ids(p, fall) == ["f1", "f2"]
    assert w._current_chapter_id == "m1" and p.active_subproject_id is None
    assert not boxes


def test_novella_to_novella_and_novella_to_main_by_drag(app, tmp_path, boxes, monkeypatch):
    p = _project(tmp_path)
    fall = p.subprojects[0].id
    ash = p.create_subproject("Ash Wardens")
    p.save_project(p.project_path)
    w = _editor(app, p)
    tree = w.manuscript_tree
    tree.handle_drop([(fall, "f1"), (fall, "f2")], "into", ash.id, None)
    app.processEvents()
    assert _ids(p, ash.id) == ["f1", "f2"] and _ids(p, fall) == []
    assert "2 chapters" in tree.notice.text()
    tree.rebuild()
    P = tree.dropIndicatorPosition().__class__
    target = tree.drop_target(tree.chapter_item(None, "m1"), P.BelowItem) \
        if tree.chapter_item(None, "m1") else ("into", None, 1)
    tree.handle_drop([(ash.id, "f2")], *target)
    app.processEvents()
    assert _ids(p, None) == ["m1", "f2", "m2", "m3"]
    q = WriterProject.load_project(p.project_path)
    assert [c.content for c in q.get_main_manuscript().chapters][1] == "Fall 2."


def test_move_to_a_new_novella(app, tmp_path, boxes, monkeypatch):
    p = _project(tmp_path)
    w = _editor(app, p)
    monkeypatch.setattr(w, "_ask_novella_name_and_description", lambda *a, **k: ("Tide", ""))
    w.manuscript_tree.move_to_new_novella([(None, "m3")])
    app.processEvents()
    sp = next(s for s in p.subprojects if s.name == "Tide")
    assert _ids(p, sp.id) == ["m3"] and _ids(p, None) == ["m1", "m2"]


def test_a_failed_move_is_put_back_and_says_so_in_a_box(app, tmp_path, boxes, monkeypatch):
    p = _project(tmp_path)
    w = _editor(app, p)
    fall = p.subprojects[0].id
    from src.data import chapter_move as cm
    real = cm._rename
    calls = []

    def flaky(s, t):
        calls.append(s)
        if len(calls) == 2:
            raise OSError("the disk said no")
        real(s, t)
    monkeypatch.setattr(cm, "_rename", flaky)
    assert not w.manuscript_tree.move_to([(None, "m1")], fall)
    assert _ids(p, None) == ["m1", "m2", "m3"] and _ids(p, fall) == ["f1", "f2"]
    assert boxes and boxes[0][0] == "critical" and boxes[0][1] == "Move Failed"
    assert w._current_chapter_id == "m1"


def test_a_failed_new_novella_move_drops_the_empty_novella(app, tmp_path, boxes, monkeypatch):
    p = _project(tmp_path)
    w = _editor(app, p)
    monkeypatch.setattr(w, "_ask_novella_name_and_description", lambda *a, **k: ("Tide", ""))
    from src.data import chapter_move as cm
    monkeypatch.setattr(cm, "_rename", lambda s, t: (_ for _ in ()).throw(OSError("no")))
    assert not w.manuscript_tree.move_to_new_novella([(None, "m1")])
    assert [s.name for s in p.subprojects] == ["The Fall"]


def test_no_move_while_a_draft_is_open(app, tmp_path, boxes):
    p = _project(tmp_path)
    w = _editor(app, p)
    draft = p.create_draft_from_current("Try")
    w.switch_to_draft(draft)
    assert not w.manuscript_tree.move_to([(None, "m1")], p.subprojects[0].id)
    assert boxes and boxes[0][0] == "information"
    assert _ids(p, None) == ["m1", "m2", "m3"]


def test_the_undo_line_goes_on_the_status_bar_in_the_main_window(app, tmp_path, boxes):
    from PyQt6.QtWidgets import QMainWindow
    p = _project(tmp_path)
    w = _editor(app, p)
    win = QMainWindow()
    win.setCentralWidget(w)
    win.statusBar()
    win.show()
    app.processEvents()
    fall = p.subprojects[0].id
    assert w.manuscript_tree.move_to([(None, "m2")], fall)
    assert win.statusBar().currentMessage() == "Moved “The Pier” to The Fall"
    assert win._tree_undo_btn.isVisible()
    win._tree_undo_btn.click()
    app.processEvents()
    assert _ids(p, None) == ["m1", "m2", "m3"]
    assert not win._tree_undo_btn.isVisible()


# ── Before the piece ─────────────────────────────────────────────────

def test_a_project_from_before_opens_in_the_tree_and_saves_unchanged(app, tmp_path):
    import json
    p = _project(tmp_path)
    path = p.project_path
    raw = json.loads(open(path).read())
    q = WriterProject.load_project(path)
    w = _editor(app, q)
    assert w.manuscript_tree.manuscript_item(None).childCount() == 3
    w.get_manuscript()
    q.save_project(path)
    r = WriterProject.load_project(path)
    assert [c.content for c in r.get_main_manuscript().chapters] == ["Main 1.", "Main 2.", "Main 3."]
    assert set(json.loads(open(path).read())) == set(raw)
