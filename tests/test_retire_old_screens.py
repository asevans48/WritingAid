"""D.11 Retire the old screens.

The ten-tab mode, the old analysis windows, the old Improve windows' paths,
and the manuscript tab row with Novellas ▾ are gone with their three
switches. What these tests hold:

* a settings file and a saved window layout from before (ten tabs asked
  for, every switch off, the windows' old places) open cleanly in the real
  main window, every value is left where it was, and a project from before
  opens, saves and reopens byte for byte;
* "Move main chapters into this novella" moves every main chapter with
  ``chapter_move.move_chapters`` (renamed in place, never copied), the
  main manuscript's drafts with them, offers Undo, and loses nothing when a
  step fails.

No model runs; HOME is a scratch folder for the real main window.
"""

from __future__ import annotations

import os
import pwd
import shutil
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))     # test_project_compat

from PyQt6.QtWidgets import QMessageBox  # noqa: E402

from src.models.project import Chapter, Manuscript, ManuscriptDraft, WriterProject  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    """No LanguageTool server is started by these tests."""
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)


# ── Settings and layouts saved before the piece ──────────────────────

def _old_settings():
    """What the window-settings file held before D.11: the ten tabs asked
    for, the three trial switches off, and where the windows were left."""
    from PyQt6.QtCore import QByteArray
    from PyQt6.QtWidgets import QMainWindow
    placed = QMainWindow()
    placed.setGeometry(260, 140, 700, 540)
    geometry = placed.saveGeometry()
    placed.deleteLater()
    return {
        "screen_groups/arrangement": "ten",
        "improve/merged": "false",
        "write/manuscript_tree": "false",
        "screen_groups/last/story": "characters",
        "screen_windows/plot/geometry": QByteArray(geometry),
        "critique_window/geometry": QByteArray(geometry),
        "critique_window/out": "true",
        "improve_window/rect": [40, 60, 1100, 780],
        "improve_window/screen": "",
        "d6/style_tab_moved_note_shown": "1",
    }


def _store(values):
    from src.ui import ui_kit
    s = ui_kit._settings()
    for k, v in values.items():
        s.setValue(k, v)
    s.sync()
    return s


def _same(stored, value) -> bool:
    if isinstance(value, list):
        return [int(x) for x in stored] == value
    return stored == value


def _real_home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


@pytest.fixture
def main_window(app, monkeypatch):
    if Path.home() == _real_home():
        pytest.skip("needs HOME set to a scratch folder (the main window reads settings)")
    old = _old_settings()
    _store(old)
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)
    boxes = []
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: boxes.append(_n) or QMessageBox.StandardButton.No))
    from PyQt6.QtWidgets import QToolTip
    from src.ui import screen_groups as sg
    from src.ui.main_window import MainWindow
    style, tips = app.styleSheet(), QToolTip.palette()
    monkeypatch.setattr(MainWindow, "_startup_load_project", lambda self: None)
    monkeypatch.setattr(MainWindow, "_confirm_unsaved_changes", lambda self: True)
    win = MainWindow()
    win.resize(1280, 800)
    win.show()
    app.processEvents()
    yield win, old, boxes
    sg.bring_all_back(win)
    try:
        win._video_studio_autosave_timer.stop()
    except Exception:
        pass
    win.hide()
    win.deleteLater()
    app.processEvents()
    app.setStyleSheet(style)
    QToolTip.setPalette(tips)


def test_old_settings_and_layout_open_cleanly_in_the_main_window(app, main_window, monkeypatch):
    from test_project_compat import _v1_project_dir
    from src.ui import screen_groups as sg, ui_kit
    win, old, boxes = main_window
    # Five groups, whatever was stored; Story opens on the screen last used.
    assert win.tab_widget.count() == 5
    assert [sg._plain_name(win.tab_widget.tabText(i)) for i in range(5)] == \
        ["Write", "Story", "Revise", "Publish", "Studio"]
    sg.show(win, win.story_planning_widget)
    win.screen_groups.detach(win.screen_groups.screens["plot"])        # its old place
    assert win.story_planning_widget.window() is win.screen_groups.screens["plot"].window
    win.screen_groups.bring_back(win.screen_groups.screens["plot"])
    # A project from before: the tree, not the tab row.
    d, path = _v1_project_dir()
    files = sorted(d.glob("chapters/*/*.md"))
    before = {f: f.read_bytes() for f in files}
    from src.models.project import WriterProject
    win.current_project = WriterProject.load_project(str(path))
    win._load_project_into_ui()
    app.processEvents()
    me = win.manuscript_editor
    assert not me.manuscript_tree.isHidden()             # shown (the sidebar may be folded)
    assert me.subproject_tabs.isHidden() and me.chapter_list.isHidden()
    # Ctrl+R opens the Improve window, the switch stored off notwithstanding.
    import src.ui.improve_window as iw
    opened = []

    class Seen:
        def __init__(self, *a, **k):
            opened.append(k.get("tab"))

        def exec(self):
            return 0
    monkeypatch.setattr(iw, "ImproveWindow", Seen)
    me.open_chapter(win.current_project.manuscript.chapters[0].id)
    ce = me.current_chapter_editor
    cur = ce.editor.textCursor()
    cur.setPosition(0)
    cur.setPosition(8, cur.MoveMode.KeepAnchor)
    ce.editor.setTextCursor(cur)
    ce._rephrase_selection()
    assert opened == ["rephrase"]
    assert boxes == []                                                  # no prompt
    # Saves and reopens unchanged; every stored value is still there.
    win.current_project.save_project(str(path))
    WriterProject.load_project(str(path))
    assert {f: f.read_bytes() for f in files} == before
    s = ui_kit._settings()
    for k, v in old.items():
        if k in ("screen_windows/plot/geometry", "critique_window/geometry",
                 "screen_groups/last/story"):
            assert s.value(k) is not None, k          # written again as the screens were used
        else:
            assert _same(s.value(k), v), (k, s.value(k))
    shutil.rmtree(d)


def test_the_settings_page_has_no_trial_switches_left():
    """Settings ▸ Features lost its three switches; nothing else changed
    there (checked in the source: a full SettingsDialog is never built)."""
    src = (Path(__file__).parent.parent / "src" / "ui" / "settings_dialog.py").read_text()
    for gone in ("TabsOption", "ImproveOption", "TreeOption", "tabs_option", "improve_option",
                 "tree_option"):
        assert gone not in src, gone
    assert "BoxesOption" in src and "HabitOption" in src and "habit_option.save()" in src


# ── Move main chapters into this novella (rule 15) ───────────────────

def _project(tmp_path, drafts=True):
    path = tmp_path / "Saga.writerproj"
    p = WriterProject(name="Saga", manuscript=Manuscript(title="Main Manuscript"))
    p.manuscript.chapters = [Chapter(id=f"m{i}", number=i, title=t, content=f"Main {i}.")
                             for i, t in enumerate(["The Storm", "The Pier", "The Letter"], 1)]
    fall = p.create_subproject("The Fall")
    fall.manuscript.chapters = [Chapter(id="f1", number=1, title="Fall 1", content="Fall 1.")]
    p._normalize_manuscript_roots()
    if drafts:
        p.drafts = [ManuscriptDraft(id="d1", name="Main draft",
                                    chapters=[Chapter(id="x", number=1, title="X", content="x")]),
                    ManuscriptDraft(id="d2", name="Fall draft", subproject_id=fall.id)]
    p.save_project(str(path))
    p.save_project(str(path))
    for ch in p.manuscript.chapters:                       # a saved copy and a note too
        folder = tmp_path / ch.folder_path
        (folder / "backup_1.md").write_text(f"Older {ch.title}.")
        (folder / "notes.txt").write_text(f"Notes for {ch.title}.")
    return p


_KEEP = []        # windows outlive their test, so no editor's worker thread is cut off


def _editor(app, p):
    from PyQt6.QtWidgets import QMainWindow
    from src.ui.manuscript_editor import ManuscriptEditor
    win = QMainWindow()
    _KEEP.append(win)
    w = ManuscriptEditor()
    win.setCentralWidget(w)
    win.statusBar()
    w.set_project(p)
    w.load_manuscript(p.manuscript)
    w.open_chapter("m1")
    win.resize(1440, 900)
    win.show()
    app.processEvents()
    w.manuscript_tree.rebuild()
    return win, w


def _files(root: Path):
    return {str(f.relative_to(root)): f.read_bytes() for f in root.rglob("*")
            if f.is_file() and "chapter_" in str(f.relative_to(root))}


def _ids(p, scope):
    return [c.id for c in p.get_manuscript_for(scope).chapters]


@pytest.fixture
def answer(monkeypatch):
    """The question before the move, answered Yes (or No); other boxes recorded."""
    said = {"reply": QMessageBox.StandardButton.Yes, "boxes": []}
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: said["boxes"].append(("question", a[2])) or said["reply"]))
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: said["boxes"].append((_n, a[1] if len(a) > 1 else ""))))
    return said


def test_the_entry_is_where_it_was_and_calls_the_same_method(app, tmp_path, answer, monkeypatch):
    p = _project(tmp_path)
    _win, w = _editor(app, p)
    fall = p.subprojects[0].id
    menu, actions = w.manuscript_tree.manuscript_menu(fall)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert "Move main chapters into this novella (3)…" in texts
    called = []
    monkeypatch.setattr(w, "_move_main_into_existing", lambda s: called.append(s))
    act = next(a for a in actions if a.text().startswith("Move main chapters"))
    actions[act]()
    assert called == [fall]


def test_every_main_chapter_moves_by_rename_with_its_drafts_and_undo_puts_it_all_back(
        app, tmp_path, answer, monkeypatch):
    p = _project(tmp_path)
    win, w = _editor(app, p)
    fall = p.subprojects[0].id
    before = _files(tmp_path)
    copied = []
    monkeypatch.setattr(shutil, "copytree", lambda *a, **k: copied.append(a) or
                        pytest.fail("a chapter was copied"))
    inode = os.stat(tmp_path / p.manuscript.chapters[0].folder_path / "backup_1.md").st_ino

    w._move_main_into_existing(fall)
    app.processEvents()
    assert answer["boxes"][0][0] == "question" and "Undo" in answer["boxes"][0][1]
    assert _ids(p, None) == [] and _ids(p, fall) == ["f1", "m1", "m2", "m3"]
    moved = tmp_path / "subprojects" / fall / "chapters"
    assert (moved / "chapter_002" / "revision_001.md").read_text() == "Main 1."
    assert (moved / "chapter_002" / "backup_1.md").read_text() == "Older The Storm."
    assert (moved / "chapter_004" / "notes.txt").read_text() == "Notes for The Letter."
    assert os.stat(moved / "chapter_002" / "backup_1.md").st_ino == inode   # renamed, not copied
    assert not list((tmp_path / "chapters").glob("chapter_*"))
    assert not copied and not list(tmp_path.glob("*.pre-move-*"))
    # The main manuscript's drafts went with it, as they always did.
    assert [(d.id, d.subproject_id) for d in p.drafts] == [("d1", fall), ("d2", fall)]
    # The novella is open, on the first moved chapter; saved to disk.
    assert p.active_subproject_id == fall and w._current_chapter_id == "m1"
    again = WriterProject.load_project(p.project_path)
    assert [c.id for c in again.get_manuscript_for(fall).chapters] == ["f1", "m1", "m2", "m3"]
    assert {d.id: d.subproject_id for d in again.drafts} == {"d1": fall, "d2": fall}
    # The status bar says so, with Undo.
    assert win.statusBar().currentMessage() == "Moved 3 chapters to The Fall"
    assert win._tree_undo_btn.isVisible()

    win._tree_undo_btn.click()
    app.processEvents()
    assert _ids(p, None) == ["m1", "m2", "m3"] and _ids(p, fall) == ["f1"]
    assert [(d.id, d.subproject_id) for d in p.drafts] == [("d1", None), ("d2", fall)]
    assert _files(tmp_path) == before                                   # every file, back
    again = WriterProject.load_project(p.project_path)
    assert [c.id for c in again.get_main_manuscript().chapters] == ["m1", "m2", "m3"]
    assert {d.id: d.subproject_id for d in again.drafts} == {"d1": None, "d2": fall}


def test_no_to_the_question_moves_nothing(app, tmp_path, answer):
    p = _project(tmp_path)
    _win, w = _editor(app, p)
    before = _files(tmp_path)
    answer["reply"] = QMessageBox.StandardButton.No
    assert not w._move_main_into_existing(p.subprojects[0].id)
    assert _ids(p, None) == ["m1", "m2", "m3"] and _files(tmp_path) == before


def test_a_failure_part_way_puts_everything_back_and_says_so(app, tmp_path, answer, monkeypatch):
    p = _project(tmp_path)
    _win, w = _editor(app, p)
    fall = p.subprojects[0].id
    before = _files(tmp_path)
    from src.data import chapter_move as cm
    real, calls = cm._rename, []

    def flaky(s, t):
        calls.append(s)
        if len(calls) == 3:
            raise OSError("the disk said no")
        real(s, t)
    monkeypatch.setattr(cm, "_rename", flaky)
    assert not w._move_main_into_existing(fall)
    assert _ids(p, None) == ["m1", "m2", "m3"] and _ids(p, fall) == ["f1"]
    assert _files(tmp_path) == before
    assert [(d.id, d.subproject_id) for d in p.drafts] == [("d1", None), ("d2", fall)]
    assert ("critical", "Move Failed") in answer["boxes"]


def test_a_project_without_drafts_and_while_a_draft_is_open(app, tmp_path, answer):
    p = _project(tmp_path, drafts=False)
    _win, w = _editor(app, p)
    fall = p.subprojects[0].id
    assert w._move_main_into_existing(fall)
    assert _ids(p, fall) == ["f1", "m1", "m2", "m3"] and p.drafts == []
    (tmp_path / "second").mkdir()
    q = _project(tmp_path / "second")
    _win2, w2 = _editor(app, q)
    draft = q.create_draft_from_current("Try")
    w2.switch_to_draft(draft)
    answer["boxes"].clear()
    assert not w2._move_main_into_existing(q.subprojects[0].id)        # as D.10's moves
    assert _ids(q, None) == ["m1", "m2", "m3"]
    assert any(b[0] == "information" for b in answer["boxes"])
