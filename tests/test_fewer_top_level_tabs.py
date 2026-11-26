"""D.4 Fewer top-level tabs: ten tabs become five groups, every screen is
still reached by its tab, its menu entry and its signal; one way to put a
screen (or a group) in its own window; old tab numbers, settings and
projects still open; the old ten tabs are one switch away."""

import os
import pwd
import shutil
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))     # test_project_compat

from PyQt6.QtWidgets import QMainWindow, QMessageBox, QTabWidget, QWidget  # noqa: E402

from src.ui import screen_groups as sg  # noqa: E402

# The ten tabs as the main window added them before D.4 (old index order).
OLD = [("write", "manuscript_editor", "✍️ Write"), ("plot", "story_planning_widget", "📖 Plot"),
       ("characters", "characters_widget", "👥 Characters"),
       ("world", "worldbuilding_widget", "🌍 World"),
       ("attributions", "attributions_tab", "📚 Attributions"),
       ("visuals", "image_generator", "🎨 Visuals"),
       ("prose_profile", "prose_profile_widget", "🎯 Prose Profile"),
       ("critique", "grader_widget", "📊 Critique"),
       ("video_studio", "video_studio_widget", "🎬 Video Studio"),
       ("publishing", "agent_manager", "📧 Publishing")]
ATTR = {k: a for k, a, _ in OLD}


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_boxes(monkeypatch):
    """No prompt may appear: opening an old layout asks nothing."""
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, **k: pytest.fail("a message box was shown")))


def _shell(app):
    """A main window holding the ten tabs exactly as before D.4."""
    win = QMainWindow()
    win.tab_widget = QTabWidget()
    win.setCentralWidget(win.tab_widget)
    for key, attr, label in OLD:
        w = QWidget()
        w.setObjectName(key)
        setattr(win, attr, w)
        win.tab_widget.addTab(w, label)
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    return win


def _labels(tabs):
    return [tabs.tabText(i) for i in range(tabs.count())]


def _close(win):
    groups = getattr(win, "screen_groups", None)
    if groups is not None:
        groups.bring_all_back()
    win.close()
    win.deleteLater()


# ── The five groups ───────────────────────────────────────────────────

def test_ten_tabs_become_five_groups_with_the_screens_unchanged_inside(app):
    win = _shell(app)
    groups = sg.install(win)
    assert _labels(win.tab_widget) == ["✍️ Write", "📖 Story", "📊 Revise", "📧 Publish", "🎬 Studio"]
    story, revise, studio = groups.groups["story"], groups.groups["revise"], groups.groups["studio"]
    assert _labels(story.inner) == ["📖 Plot", "👥 Characters", "🌍 World"]       # names kept
    assert _labels(revise.inner) == ["📊 Critique", "🎯 Prose Profile", "📚 Attributions"]
    assert _labels(studio.inner) == ["🎨 Visuals", "🎬 Video Studio"]
    assert set(groups.groups) == {"story", "revise", "studio"}   # Write, Publish: no inner bar
    write_page = QTabWidget.widget(win.tab_widget, 0)
    assert not write_page.findChildren(QTabWidget)
    assert win.manuscript_editor.isVisibleTo(win)               # Write as it was, first
    _close(win)


@pytest.mark.parametrize("key", [k for k, _, _ in OLD])
def test_every_screen_is_reached_by_name_wherever_it_now_lives(app, key):
    win = _shell(app)
    sg.install(win)
    widget = getattr(win, ATTR[key])
    sg.show(win, widget)                                        # the one call
    assert sg.current_screen(win) is widget and widget.isVisibleTo(win)
    sg.show(win, win.manuscript_editor)
    win.tab_widget.setCurrentWidget(widget)                     # older code, unchanged
    assert win.tab_widget.currentWidget() is widget and widget.isVisibleTo(win)
    _close(win)


@pytest.mark.parametrize("old", range(10))
def test_each_old_tab_number_opens_the_screen_it_meant(app, old):
    win = _shell(app)
    groups = sg.install(win)
    assert sg.old_tab(win, old) is getattr(win, OLD[old][1])
    groups.show_old_tab(old)
    assert sg.current_screen(win) is getattr(win, OLD[old][1])
    _close(win)


def test_an_unknown_old_number_is_nothing(app):
    win = _shell(app)
    sg.install(win)
    for bad in (-1, 10, True, "2", None):
        assert sg.old_tab(win, bad) is None
    _close(win)


def test_each_group_remembers_the_screen_last_used_in_it(app):
    win = _shell(app)
    sg.install(win)
    sg.show(win, win.characters_widget)
    sg.show(win, win.prose_profile_widget)
    _close(win)
    again = _shell(app)                                          # the next start
    groups = sg.install(again)
    assert sg.current_screen(again) is again.manuscript_editor     # it still starts on Write
    QTabWidget.setCurrentWidget(again.tab_widget, groups.groups["story"].slot)
    assert sg.current_screen(again) is again.characters_widget
    QTabWidget.setCurrentWidget(again.tab_widget, groups.groups["revise"].slot)
    assert sg.current_screen(again) is again.prose_profile_widget
    _close(again)


def test_choosing_an_inner_tab_tells_the_main_window(app):
    win = _shell(app)
    seen = []
    win._on_tab_changed = lambda index: seen.append(sg.current_screen(win))
    groups = sg.install(win)
    QTabWidget.setCurrentWidget(win.tab_widget, groups.groups["revise"].slot)
    groups.groups["revise"].inner.setCurrentWidget(groups.screens["attributions"].slot)
    assert seen and seen[-1] is win.attributions_tab
    _close(win)


# ── One way to detach ────────────────────────────────────────────────

def test_a_single_screen_goes_out_and_back(app):
    win = _shell(app)
    groups = sg.install(win)
    unit = groups.screens["characters"]
    sg.show(win, win.characters_widget)
    groups.detach(unit)
    app.processEvents()
    assert unit.window is not None and win.characters_widget.window() is unit.window
    assert unit.window.windowTitle() == "Characters"
    assert sg.current_screen(win) is win.manuscript_editor     # Write, beside it
    assert unit.slot.note.isVisibleTo(win) is False             # Story is not showing
    raised = []
    unit.raise_window = lambda: raised.append(True)
    sg.show(win, win.characters_widget)                         # choosing it raises it
    assert raised and unit.slot.note.isVisibleTo(win)           # "Show it · Bring it back here"
    del unit.raise_window
    unit.window.close()                                         # closing brings it back
    app.processEvents()
    assert unit.window is None and win.characters_widget.window() is win
    assert sg.current_screen(win) is win.characters_widget
    assert sg._settings().value(sg.GEOMETRY_KEY.format(key="characters")) is not None
    _close(win)


def test_a_whole_group_goes_out_and_a_screen_inside_it_too(app):
    win = _shell(app)
    groups = sg.install(win)
    story = groups.groups["story"]
    groups.detach(story)
    assert story.window is not None and story.window.windowTitle() == "Story"
    assert win.story_planning_widget.window() is story.window
    assert win.worldbuilding_widget.window() is story.window
    world = groups.screens["world"]
    groups.detach(world)                                        # one screen out of the group
    assert win.worldbuilding_widget.window() is world.window
    sg.show(win, win.worldbuilding_widget)
    assert sg.current_screen(win) is win.worldbuilding_widget
    groups.bring_back(story)
    assert win.story_planning_widget.window() is win
    groups.bring_back(world)
    assert win.worldbuilding_widget.window() is win
    _close(win)


def test_right_click_a_tab_offers_its_own_window_without_multi_window_mode(app, monkeypatch):
    from PyQt6.QtWidgets import QMenu
    win = _shell(app)
    groups = sg.install(win)
    menus = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: menus.append(self))
    bar = win.tab_widget.tabBar()
    sg.tab_menu(win, bar.tabRect(1).center())                  # the Story group
    assert [a.text() for a in menus[-1].actions()] == ["Open “Story” in Its Own Window"]
    menus[-1].actions()[0].trigger()
    assert groups.groups["story"].is_out
    inner = groups.groups["story"].inner
    groups._inner_menu(inner, inner.tabBar().tabRect(1).center())   # Characters, inside it
    texts = [a.text() for a in menus[-1].actions()]
    assert texts == ["Open “Characters” in Its Own Window", "Bring “Story” Back to the Main Window"]
    menus[-1].actions()[1].trigger()
    assert not groups.groups["story"].is_out
    sg.tab_menu(win, bar.tabRect(0).center())                  # Write can go too
    assert [a.text() for a in menus[-1].actions()] == ["Open “Write” in Its Own Window"]
    sg.detach_tab(win, 4)                                       # Multi-Window's entry: Studio
    assert groups.groups["studio"].is_out
    sg.bring_all_back(win)                                      # Multi-Window Mode switched off
    assert not any(u.is_out for u in groups.all_units())
    _close(win)


def test_the_critique_goes_out_by_either_entry_and_comes_back_the_same_way(app):
    from PyQt6.QtWidgets import QMenu
    from src.ui import critique_window
    win = _shell(app)
    groups = sg.install(win)
    pop = critique_window.install(win)
    assert pop is not None and pop.unit is groups.screens["critique"]
    menu = QMenu()
    critique_window.add_to_menu(win, menu)                     # the Critique menu
    assert menu.actions()[-1].text() == "Critique in Its Own Window"
    menu.actions()[-1].trigger()
    assert pop.is_out and win.grader_widget.window() is pop.window
    assert sg._settings().value(sg.CRITIQUE_OUT_KEY) == "true"
    menu2 = QMenu()
    critique_window.add_to_menu(win, menu2)
    menu2.actions()[-1].trigger()                               # "Bring the Critique Back…"
    assert not pop.is_out and win.grader_widget.window() is win
    groups.detach(groups.screens["critique"])                   # right-click the tab
    assert pop.is_out and win.grader_widget.window() is pop.window
    pop.window.close()
    app.processEvents()
    assert not pop.is_out and sg.current_screen(win) is win.grader_widget
    assert sg._settings().value(sg.CRITIQUE_OUT_KEY) == "false"
    assert sg._settings().value(sg.CRITIQUE_GEOMETRY_KEY) is not None   # the 2.5 key
    _close(win)


# ── The old arrangement, one switch away ─────────────────────────────

def test_the_old_ten_tabs_are_one_switch_away_and_back(app):
    win = _shell(app)
    groups = sg.install(win)
    sg.show(win, win.characters_widget)
    groups.detach(groups.screens["visuals"])
    sg.set_grouped(False, win)
    assert sg._settings().value(sg.ARRANGEMENT_KEY) == "ten"
    assert _labels(win.tab_widget) == [label for _, _, label in OLD]   # as before D.4
    assert not any(u.is_out for u in groups.all_units())               # brought back first
    assert sg.current_screen(win) is win.characters_widget             # still on it
    for key, attr, _ in OLD:
        sg.show(win, getattr(win, attr))
        assert sg.current_screen(win) is getattr(win, attr) and getattr(win, attr).isVisibleTo(win)
    groups.detach(groups.screens["plot"])                              # detaching works here too
    assert win.story_planning_widget.window() is groups.screens["plot"].window
    sg.set_grouped(True, win)
    assert len(_labels(win.tab_widget)) == 5
    for key, attr, _ in OLD:
        sg.show(win, getattr(win, attr))
        assert sg.current_screen(win) is getattr(win, attr)
        assert getattr(win, attr).window() is win and getattr(win, attr).isVisibleTo(win)
    _close(win)


def test_a_main_window_started_with_the_ten_tabs_setting_shows_ten(app):
    sg._set(sg.ARRANGEMENT_KEY, "ten")
    win = _shell(app)
    sg.install(win)
    assert _labels(win.tab_widget) == [label for _, _, label in OLD]
    _close(win)


def test_the_settings_switch(app):
    from PyQt6.QtWidgets import QVBoxLayout
    holder = QWidget()
    lay = QVBoxLayout(holder)
    option = sg.TabsOption(lay)
    assert option.box.isChecked()                                      # groups by default
    win = _shell(app)
    sg.install(win)
    option.box.setChecked(False)
    from src.ui.window_manager import WindowManager
    wm = WindowManager()
    old_main = wm.get_main_window()
    wm._main_window = win
    try:
        option.save()
        assert win.tab_widget.count() == 10
        option.box.setChecked(True)
        option.save()
        assert win.tab_widget.count() == 5
    finally:
        wm._main_window = old_main
    _close(win)


# ── Settings and layouts saved before the piece ──────────────────────

def test_settings_saved_before_the_piece_open_with_nothing_missing_and_no_prompt(app):
    from PyQt6.QtCore import QByteArray
    s = sg._settings()
    placed = QMainWindow()
    placed.setGeometry(300, 120, 640, 520)
    saved = placed.saveGeometry()
    old = {"critique_window/geometry": saved, "critique_window/out": "true",
           "d6/style_tab_moved_note_shown": "1", "suggestions/rect": [10, 20, 700, 600]}
    for k, v in old.items():
        s.setValue(k, v)
    s.sync()
    win = _shell(app)
    groups = sg.install(win)
    assert win.tab_widget.count() == 5                                  # no prompt, grouped
    groups.detach(groups.screens["critique"])
    window = groups.screens["critique"].window
    assert window is not None
    restored = QMainWindow()
    restored.restoreGeometry(saved)
    assert window.geometry().size() == restored.geometry().size()      # where it was left
    groups.bring_back(groups.screens["critique"])
    after = sg._settings()
    for k in old:
        assert after.value(k) is not None, k                            # nothing deleted
    assert isinstance(after.value("critique_window/geometry"), (QByteArray, bytes))
    assert after.value("d6/style_tab_moved_note_shown") == "1"
    _close(win)
    placed.deleteLater()
    restored.deleteLater()


# ── The real main window ─────────────────────────────────────────────

def _real_home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


@pytest.fixture
def main_window(app, monkeypatch):
    if Path.home() == _real_home():
        pytest.skip("needs HOME set to a scratch folder (the main window reads settings)")
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)
    from PyQt6.QtWidgets import QToolTip
    from src.ui.main_window import MainWindow
    # The main window styles the whole application; put that back afterwards
    # so later tests measure widgets as they always have.
    style, tips = app.styleSheet(), QToolTip.palette()
    monkeypatch.setattr(MainWindow, "_startup_load_project", lambda self: None)
    monkeypatch.setattr(MainWindow, "_confirm_unsaved_changes", lambda self: True)
    win = MainWindow()
    win.resize(1280, 800)
    win.show()
    app.processEvents()
    yield win
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


def test_the_main_window_has_five_groups_and_every_entry_lands(app, main_window, tmp_path):
    import json
    from test_project_compat import _v1_project_dir
    from src.models.project import WriterProject
    win = main_window
    assert win.tab_widget.count() == 5
    assert [sg._plain_name(win.tab_widget.tabText(i)) for i in range(5)] == \
        ["Write", "Story", "Revise", "Publish", "Studio"]
    d, path = _v1_project_dir()
    files = sorted(d.glob("chapters/*/*.md"))
    before = {f: f.read_bytes() for f in files}
    win.current_project = WriterProject.load_project(str(path))
    win._load_project_into_ui()
    app.processEvents()
    first = win.current_project.manuscript.chapters[0]
    # Every screen by name.
    for _, attr, _ in OLD:
        sg.show(win, getattr(win, attr))
        assert sg.current_screen(win) is getattr(win, attr)
    # The Critique menu's "Open Critique Tab" and its own-window entry.
    win._populate_review_menu()
    acts = {a.text(): a for a in win.review_menu.actions()}
    sg.show(win, win.manuscript_editor)
    acts["Open Critique Tab"].trigger()
    assert sg.current_screen(win) is win.grader_widget
    acts["Critique in Its Own Window"].trigger()
    assert win.critique_popout.is_out
    assert sg.current_screen(win) is win.manuscript_editor              # Write beside it
    win._populate_review_menu()
    acts = {a.text(): a for a in win.review_menu.actions()}
    acts["Bring the Critique Back to Its Tab"].trigger()
    assert not win.critique_popout.is_out
    # Choosing the Critique tells the Critique which chapter is open.
    told = []
    win.grader_widget.set_current_chapter = lambda content, title: told.append(title)
    sg.show(win, win.manuscript_editor)
    sg.show(win, win.grader_widget)
    assert told
    # Signals that switch to Write: "📝 Open in writer", Go to line, links.
    for go in (lambda: win._jump_to_writer_for_chapter(first.id),
               lambda: win._navigate_to_range(first.id, 0, 3),
               lambda: win._navigate_to_passage(first.id, first.content.split()[0]),
               lambda: win.revision.open_chapter(first.id)):
        sg.show(win, win.characters_widget)
        go()
        app.processEvents()
        assert sg.current_screen(win) is win.manuscript_editor
    # Find works on Write, not elsewhere (as before).
    sg.show(win, win.characters_widget)
    win._show_find_dialog()
    assert win.find_dialog is None
    # Right-click → own window, for a group and for a screen; Multi-Window off brings all back.
    for index in range(win.tab_widget.count()):
        win._detach_tab_to_new_window(index)
    assert all(u.is_out for u in win.screen_groups.groups.values())
    win._toggle_multi_window_mode(False)
    assert not any(u.is_out for u in win.screen_groups.all_units())
    # The old arrangement, live.
    sg.set_grouped(False, win)
    assert win.tab_widget.count() == 10
    sg.set_grouped(True, win)
    assert win.tab_widget.count() == 5
    # The project saves and reopens unchanged.
    win.current_project.save_project(str(path))
    again = WriterProject.load_project(str(path))
    assert {f: f.read_bytes() for f in files} == before
    assert len(again.manuscript.chapters) == len(win.current_project.manuscript.chapters)
    shutil.rmtree(d)
