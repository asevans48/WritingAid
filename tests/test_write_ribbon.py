"""D.13: Write's ribbon (Home · Review · Insert · Draft), the top row and the
Chapter Title row gone, Total on the bottom row, and chapters renamed in the
manuscript tree.

Projects are built in ``tmp_path``; HOME and the window-state settings are
the test's own (conftest); no model runs; LanguageTool is never started.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractItemDelegate, QToolButton, QWidget

from src.models.project import Chapter, Manuscript, WriterProject
from src.ui import manuscript_tree as mt
from src.ui import write_ribbon as wr

TEXT = ("Rain fell on the harbor all night. Mara watched the boats.\n\n"
        "Next morning the ferry came in late, and Voss was on it.\n\n"
        "That evening Tobin burned the letter in the stove.")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_languagetool(monkeypatch):
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)


def _project(tmp_path, novella=True):
    p = WriterProject(name="Saga", manuscript=Manuscript(title="Main Manuscript"))
    p.manuscript.chapters = [Chapter(id=f"m{i}", number=i, title=t, content=TEXT)
                             for i, t in enumerate(["The Storm", "The Pier", "The Letter"], 1)]
    if novella:
        fall = p.create_subproject("The Fall")
        fall.manuscript.chapters = [Chapter(id="f1", number=1, title="Fall 1", content="Fall.")]
    p._normalize_manuscript_roots()
    p.save_project(str(tmp_path / "Saga.writerproj"))
    p.save_project(str(tmp_path / "Saga.writerproj"))
    return p


def _editor(app, p, size=(1440, 900)):
    from src.ui.manuscript_editor import ManuscriptEditor
    w = ManuscriptEditor()
    w.set_project(p)
    w.load_manuscript(p.manuscript)
    w.open_chapter(p.manuscript.chapters[0].id)
    w.resize(*size)
    w.show()
    for _ in range(3):
        app.processEvents()
    return w


def _done(app, w):
    from src.ui import background, companion_panel
    for t in list(companion_panel._RUNNING):
        try:
            t.wait(10000)
        except RuntimeError:
            pass
    background.wait_all(10000)
    w.close()
    w.deleteLater()
    app.processEvents()


def _page_of(ribbon, widget):
    """The ribbon tab a widget sits on, or None."""
    for n, name in enumerate(wr.TABS):
        page = ribbon.stack.widget(n)
        if page.isAncestorOf(widget):
            return name
    return None


# ── The four tabs hold every control ──────────────────────────────────

def test_every_control_is_on_its_tab_and_nothing_is_lost(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    ce = w.current_chapter_editor
    r = ce.write_ribbon
    assert [r.bar.tabText(i) for i in range(r.bar.count())] == ["Home", "Review", "Insert", "Draft"]
    assert r.current() == wr.HOME                       # Home is shown first
    home = [b.text() for b in r.stack.widget(0).findChildren(QToolButton)
            if b.isVisibleTo(r) and b.text()]
    assert home == ["B", "I", "U", wr.IMPROVE]          # D.13b: ✨ with its word
    for widget, tab in ((ce.font_combo, wr.HOME), (ce.font_size_spin, wr.HOME),
                        (ce.heading_combo, wr.HOME), (ce.checks_btn, wr.REVIEW),
                        (ce.tts_speak_btn, wr.REVIEW), (ce.analyze_btn, wr.REVIEW),
                        (ce.view_annotations_btn, wr.INSERT), (ce.scene_break_btn, wr.INSERT),
                        (w.draft_selector, wr.DRAFT), (w.drafts_menu_btn, wr.DRAFT),
                        (w.compare_drafts_btn, wr.DRAFT), (ce.draft_btn, wr.DRAFT)):
        assert _page_of(r, widget) == tab, widget
    annotations = next(t.annotations_btn for t in ce.findChildren(object)
                       if hasattr(t, "annotations_btn"))
    assert _page_of(r, annotations) == wr.INSERT and annotations.text() == wr.ANNOTATION
    # The menus are the same menus, with every entry.
    analyze = [a.text() for a in ce.analyze_btn.menu().actions() if a.text()]
    assert "Critique this chapter (all reports)" in analyze and "Writing hints" in analyze
    draft = [a.text() for a in ce.draft_btn.menu().actions() if a.text()]
    assert draft == ["Save draft", "View drafts…", "Import from Word…", "Export to Word…",
                     "Clean up formatting"]
    # The top row and the Chapter Title row are gone from view; Total sits
    # beside Words on the bottom row; ◂ sits before the tab names.
    assert not w.write_header.isVisibleTo(w)
    assert not ce.title_edit.isVisibleTo(w)
    bottom = ce.ribbon_bottom
    assert bottom.indexOf(w.total_word_count_label) == bottom.indexOf(ce.word_count_label) + 1
    assert w.total_word_count_label.isVisibleTo(w)
    assert w.total_word_count_label.text().startswith("Total: ")
    assert r.lead.indexOf(w.sidebar_toggle_btn) >= 0 and w.sidebar_toggle_btn.isVisibleTo(w)
    # ◧ Panel stays on the bottom row.
    assert bottom.indexOf(ce.toggle_planner_btn) >= 0
    _done(app, w)


def test_the_bottom_rows_counts_and_total(app, tmp_path):
    p = _project(tmp_path)
    for c in p.manuscript.chapters:
        c.word_count = 1000
    w = _editor(app, p)
    total = sum(c.word_count for c in p.manuscript.chapters)    # the open one counted afresh
    assert total > 2000 and w.total_word_count_label.text() == f"Total: {total:,}"
    _done(app, w)


def test_every_shortcut_works_whichever_tab_shows(app, tmp_path):
    from PyQt6.QtWidgets import QToolBar
    p = _project(tmp_path)
    w = _editor(app, p)
    ce = w.current_chapter_editor
    wr.show_tab(w, wr.DRAFT, remember=False)
    keys = {a.shortcut().toString() for a in ce.actions() if a.shortcut().toString()}
    assert {"Ctrl+B", "Ctrl+I", "Ctrl+U", "Ctrl+R", "Ctrl+Shift+N", "Ctrl+Shift+H"} <= keys
    # Each is the toolbar's own action (kept, hidden), so one action per key.
    toolbar = next(iter(ce.findChildren(QToolBar)))
    assert not toolbar.isVisibleTo(w)
    for key in ("Ctrl+B", "Ctrl+R"):
        acts = [a for a in ce.actions() if a.shortcut().toString() == key]
        assert len(acts) == 1 and acts[0] in toolbar.actions()
    # Pressing Ctrl+B with Draft showing fires Bold.
    fired = []
    bold = next(a for a in ce.actions() if a.shortcut().toString() == "Ctrl+B")
    bold.triggered.connect(lambda *_: fired.append(1))
    w.activateWindow()
    ce.editor.setFocus()
    from PyQt6.QtTest import QTest
    QTest.keyClick(ce.editor, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    if w.isActiveWindow():                       # offscreen may not activate a window
        assert fired
    _done(app, w)


# ── The tab last chosen ───────────────────────────────────────────────

def test_the_last_tab_is_remembered_and_junk_means_home(app, tmp_path):
    from src.ui import ui_kit
    p = _project(tmp_path)
    w = _editor(app, p)
    w.current_chapter_editor.write_ribbon.bar.setCurrentIndex(1)       # the writer picks Review
    assert ui_kit._settings().value(wr.TAB_KEY) == wr.REVIEW
    w.open_chapter("m2")                                              # a new chapter editor
    app.processEvents()
    assert w.current_chapter_editor.write_ribbon.current() == wr.REVIEW
    _done(app, w)
    for junk in ("Ribbon", "", 3):
        ui_kit._settings().setValue(wr.TAB_KEY, junk)
        assert wr.saved_tab() == wr.HOME
    ui_kit._settings().remove(wr.TAB_KEY)
    assert wr.saved_tab() == wr.HOME


# ── The top row's widgets go to the open chapter and come back ─────────

def test_the_draft_controls_follow_the_open_chapter_and_survive_switches(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    for cid in ("m2", "m3", "m1", "m2"):
        w.open_chapter(cid)
        app.processEvents()
        ce = w.current_chapter_editor
        assert _page_of(ce.write_ribbon, w.draft_selector) == wr.DRAFT
        assert w.draft_selector.count() >= 1             # alive, filled
    # No chapter open: the old row comes back with them.
    w._release_main_editor()
    for _ in range(3):
        app.processEvents()
    assert w.write_header.isVisibleTo(w)
    for widget in (w.sidebar_toggle_btn, w.total_word_count_label, w.draft_selector,
                   w.drafts_menu_btn, w.compare_drafts_btn):
        assert w.write_header.isAncestorOf(widget) and widget.isVisibleTo(w), widget
    assert not w.new_draft_btn.isVisibleTo(w)            # D.7's hidden buttons stay hidden
    w.open_chapter("m1")
    app.processEvents()
    assert not w.write_header.isVisibleTo(w)
    assert _page_of(w.current_chapter_editor.write_ribbon, w.compare_drafts_btn) == wr.DRAFT
    # The sidebar toggle still hides and shows the tree.
    w.sidebar_toggle_btn.click()
    assert not w.left_panel.isVisible()
    w.sidebar_toggle_btn.click()
    assert w.left_panel.isVisible()
    _done(app, w)


def test_a_standalone_chapter_editor_has_the_ribbon_too(app):
    from src.ui.manuscript_editor import ChapterEditor
    ce = ChapterEditor(Chapter(id="c1", number=1, title="One", content=TEXT),
                       project=WriterProject(name="t"))
    ce.resize(900, 500)
    ce.show()
    app.processEvents()
    r = ce.write_ribbon
    assert _page_of(r, ce.draft_btn) == wr.DRAFT and not r.draft_line.isVisible()
    assert _page_of(r, ce.analyze_btn) == wr.REVIEW
    ce.close()


# ── Insert: Scene break here at the cursor ─────────────────────────────

def test_scene_break_here_marks_and_unmarks_at_the_cursor(app, tmp_path):
    from src.data import scene_marks as sm
    sm._UNDO.clear()
    sm._cache.clear()
    p = _project(tmp_path, novella=False)
    w = _editor(app, p)
    ce = w.current_chapter_editor
    wr.show_tab(w, wr.INSERT, remember=False)
    btn = ce.scene_break_btn
    doc = ce.editor.document()
    c = ce.editor.textCursor()
    c.setPosition(2)
    ce.editor.setTextCursor(c)
    wr.sync_scene_button(ce, btn)
    assert not btn.isEnabled()                            # the first paragraph starts a scene
    block = doc.findBlockByNumber(2)                      # "Next morning…"
    c.setPosition(block.position() + 3)
    ce.editor.setTextCursor(c)
    wr.sync_scene_button(ce, btn)
    # D.13b: the words carry the 🎬 icon
    assert btn.isEnabled() and btn.text() == "🎬 Scene break here"
    btn.click()
    assert len(sm.stored(p, "m1")) == 1 and btn.text() == "🎬 Remove scene break"
    assert ce.editor.toPlainText() == TEXT                # the text is never changed
    btn.click()
    assert sm.stored(p, "m1") == [] and btn.text() == "🎬 Scene break here"
    sm._UNDO.clear()
    _done(app, w)


# ── Fits 1024 × 600 and 150 %; rows wrap rather than cut ───────────────

@pytest.mark.parametrize("size", [(1024, 600), (640, 600)])
def test_every_tab_fits_and_wraps_rather_than_cutting(app, tmp_path, size):
    p = _project(tmp_path)
    w = _editor(app, p, size)
    ce = w.current_chapter_editor
    for tab in wr.TABS:
        wr.show_tab(w, tab, remember=False)
        for _ in range(4):
            app.processEvents()
        need = w.minimumSizeHint()
        assert need.width() <= 1024 and need.height() <= 600, (tab, need)
        page = ce.write_ribbon.stack.currentWidget()
        for child in page.findChildren(QWidget):
            if child.parentWidget() is page and child.isVisibleTo(page):
                assert child.geometry().right() <= page.width(), (tab, child)
                assert child.geometry().bottom() <= page.height(), (tab, child)
    assert ce.editor.viewport().height() > 300
    _done(app, w)


# ── Renaming a chapter in the tree ─────────────────────────────────────

def _line_edit(tree):
    from PyQt6.QtWidgets import QLineEdit
    return next((e for e in tree.findChildren(QLineEdit) if e.isVisible()), None)


def test_f2_renames_in_place_and_it_saves_everywhere(app, tmp_path):
    from PyQt6.QtTest import QTest
    p = _project(tmp_path)
    w = _editor(app, p)
    tree = w.manuscript_tree
    changed = []
    w.content_changed.connect(lambda: changed.append(1))
    tree.setCurrentItem(tree.chapter_item(None, "m1"))
    QTest.keyClick(tree, Qt.Key.Key_F2)
    edit = _line_edit(tree)
    assert edit is not None and edit.text() == "The Storm"      # the title alone, not "1. "
    edit.setText("The Long Storm")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    app.processEvents()
    app.processEvents()
    ch = p.manuscript.chapters[0]
    assert ch.title == "The Long Storm"
    assert w.chapter_list.item(0).text() == "1. The Long Storm"
    assert tree.chapter_item(None, "m1").text(0) == "1. The Long Storm"
    assert "The Long Storm" in tree.chapter_item(None, "m1").toolTip(0)
    assert w.current_chapter_title() == "The Long Storm"
    assert changed                                               # unsaved mark, autosave
    w.current_chapter_editor.save_to_model()                     # the hidden box agrees
    assert ch.title == "The Long Storm"
    p.save_project(p.project_path)
    assert [c.title for c in WriterProject.load_project(p.project_path).manuscript.chapters][0] \
        == "The Long Storm"
    # Ctrl+Z in the tree puts it back.
    QTest.keyClick(tree, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert ch.title == "The Storm" and w.chapter_list.item(0).text() == "1. The Storm"
    _done(app, w)


def test_esc_cancels_and_an_empty_title_is_refused(app, tmp_path):
    from PyQt6.QtTest import QTest
    p = _project(tmp_path)
    w = _editor(app, p)
    tree = w.manuscript_tree
    assert tree.edit_title(None, "m2")
    edit = _line_edit(tree)
    edit.setText("Nope")
    QTest.keyClick(edit, Qt.Key.Key_Escape)
    app.processEvents()
    assert p.manuscript.chapters[1].title == "The Pier"
    assert tree.edit_title(None, "m2")
    edit = _line_edit(tree)
    edit.setText("   ")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    app.processEvents()
    assert p.manuscript.chapters[1].title == "The Pier"
    assert "needs a title" in tree.notice.text()
    _done(app, w)


def test_double_click_and_the_menus_rename_open_the_title_in_place(app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMenu
    p = _project(tmp_path)
    w = _editor(app, p)
    tree = w.manuscript_tree
    from PyQt6.QtWidgets import QAbstractItemView
    assert tree.editTriggers() & QAbstractItemView.EditTrigger.DoubleClicked
    assert tree.chapter_item(None, "m3").flags() & Qt.ItemFlag.ItemIsEditable
    assert not tree.manuscript_item(None).flags() & Qt.ItemFlag.ItemIsEditable
    captured = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: captured.append(self))
    item = tree.chapter_item(None, "m3")
    tree.chapter_menu(None, "m3", tree.viewport().mapToGlobal(tree.visualItemRect(item).center()))
    rename = next(a for a in captured[-1].actions() if a.text() == mt.RENAME)
    rename.trigger()
    for _ in range(3):
        app.processEvents()
    edit = _line_edit(tree)
    assert edit is not None and edit.text() == "The Letter"
    edit.setText("The Last Letter")
    tree.commitData(edit)
    tree.closeEditor(edit, QAbstractItemDelegate.EndEditHint.NoHint)
    assert p.manuscript.chapters[2].title == "The Last Letter"
    _done(app, w)


def test_a_novellas_chapter_renames_without_opening_it(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    tree = w.manuscript_tree
    fall = p.subprojects[0].id
    assert tree.rename_chapter(fall, "f1", "  The   Drop ")
    assert p.get_subproject(fall).manuscript.chapters[0].title == "The Drop"
    assert p.active_subproject_id in (None, "")                 # main stays open
    assert tree.undo_rename()
    assert p.get_subproject(fall).manuscript.chapters[0].title == "Fall 1"
    _done(app, w)


def test_a_new_chapter_still_gets_its_default_title(app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText",            # the writer accepts the default
                        staticmethod(lambda *a, **k: (k.get("text", ""), True)))
    p = _project(tmp_path, novella=False)
    w = _editor(app, p)
    before = len(p.manuscript.chapters)
    w._add_chapter()
    app.processEvents()
    assert len(p.manuscript.chapters) == before + 1
    assert p.manuscript.chapters[-1].title == "Chapter 4"        # as before
    _done(app, w)


# ── Backwards compatible ──────────────────────────────────────────────

def test_a_project_and_settings_from_before_open_save_and_reopen_unchanged(app, tmp_path):
    """Rule 11: a project and window-state settings saved before D.13 open,
    save and reopen with every chapter's text and title unchanged."""
    from src.ui import ui_kit
    p = _project(tmp_path)
    path = p.project_path
    before = {c.id: (c.title, c.content) for c in p.manuscript.chapters}
    s = ui_kit._settings()                        # what an older version left behind
    s.setValue(mt.SETTING_KEY, "false")
    s.setValue("improve_window/rect", [0, 0, 800, 600])
    s.sync()
    loaded = WriterProject.load_project(path)
    w = _editor(app, loaded)
    assert w.current_chapter_editor.write_ribbon.current() == wr.HOME
    w.current_chapter_editor.save_to_model()
    loaded.save_project(path)
    _done(app, w)
    again = WriterProject.load_project(path)
    for c in again.manuscript.chapters:
        if not c.content:
            c.load_content_from_file(tmp_path)
    assert {c.id: (c.title, c.content) for c in again.manuscript.chapters} == before
    assert ui_kit._settings().value(mt.SETTING_KEY) == "false"      # left in place


def test_the_harness_counts_the_shown_tab_and_reports_the_others(tmp_path):
    import importlib.util
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("screen_harness",
                                                  root / "scripts" / "screen_harness.py")
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    results = h.run(["write", "write_review"], tmp_path, sizes=[(1440, 900, 1.0)])
    report = results["1440x900"]
    assert "error" not in report["screens"]["write_review"], report["screens"]["write_review"]
    counts = report["counts"]
    write = counts["screens"]["write"]
    assert write["buttons"] == 12 and write["inner_tabs"] == 4   # 12: Details (27 Nov) and write["menu_items"] == 0
    tabs = counts["write_ribbon"]
    assert list(tabs) == list(wr.TABS)
    assert "🔍 Analyze ▾" in tabs["Review"]["shown"] and "⇅ Split View" in tabs["Draft"]["shown"]
    assert h.compare_counts(counts, json.loads(h.BASELINE.read_text())) == []
