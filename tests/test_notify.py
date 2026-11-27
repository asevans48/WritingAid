"""D.9: messages that need no click go to the status bar; nothing is lost."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QMainWindow, QMessageBox, QWidget

from src.models.project import Chapter, WriterProject
from src.ui import notify


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    notify.clear()
    notify.set_for_session(False)
    boxes = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: boxes.append(a))
    yield boxes
    notify.set_for_session(None)
    notify.clear()


@pytest.fixture
def window(app):
    win = QMainWindow()
    win.statusBar()
    inner = QWidget()
    win.setCentralWidget(inner)
    yield win, inner
    win.close()


def test_done_goes_to_the_status_bar_and_the_list_not_a_box(window, fresh):
    win, inner = window
    notify.done(inner, "Copied", "Analysis copied to clipboard.")
    assert fresh == []
    assert win.statusBar().currentMessage() == "Analysis copied to clipboard."
    assert [(m.kind, m.title) for m in notify.recent()] == [("done", "Copied")]


def test_a_written_file_gets_show_file(window, fresh, tmp_path):
    win, inner = window
    path = str(tmp_path / "out.docx")
    notify.done(inner, "Export Successful", f"Exported to:\n{path}", path=path)
    btn = win._notify_show_file_btn
    assert not btn.isHidden() and btn.toolTip() == path
    win.statusBar().showMessage("Saved: elsewhere")      # another message replaces it
    assert btn.isHidden()
    assert "Show file" in notify.recent_html()


def test_nothing_to_do_is_quiet_and_html_is_plain(window, fresh):
    win, inner = window
    notify.empty(inner, "No Draft", "Draft <b>X</b> &amp; more\n\nhere")
    assert fresh == []
    assert win.statusBar().currentMessage() == "Draft X & more here"


def test_newest_first_and_kept(window):
    _, inner = window
    for n in range(3):
        notify.empty(inner, f"T{n}", "x")
    assert [m.title for m in notify.recent()] == ["T2", "T1", "T0"]


def test_switch_on_brings_every_box_back(window, fresh):
    _, inner = window
    notify.set_for_session(True)
    notify.done(inner, "Copied", "Analysis copied to clipboard.")
    notify.empty(inner, "No Selection", "Select some text first.")
    assert [a[1] for a in fresh] == ["Copied", "No Selection"]
    assert len(notify.recent()) == 2                      # still listed


def test_no_status_bar_anywhere_still_shows_the_box(app, fresh, monkeypatch):
    monkeypatch.setattr(notify, "_main_window", lambda parent: None)
    notify.empty(QWidget(), "No Selection", "Select some text first.")
    assert [a[1] for a in fresh] == ["No Selection"]


def test_never_creates_a_status_bar_on_a_window_without_one(app):
    from PyQt6.QtWidgets import QStatusBar
    plain = QMainWindow()
    inner = QWidget()
    plain.setCentralWidget(inner)
    assert notify._main_window(inner) is not plain
    assert plain.findChild(QStatusBar) is None


def test_switch_default_off_and_in_settings(app):
    notify.set_for_session(None)
    from PyQt6.QtWidgets import QVBoxLayout
    holder = QWidget()
    lay = QVBoxLayout(holder)
    opt = notify.BoxesOption(lay, {})
    assert opt.values() == {notify.KEY_BOXES: False}
    assert notify.BoxesOption(lay, {notify.KEY_BOXES: True}).values()[notify.KEY_BOXES]


def test_recent_messages_dialog(app, window):
    _, inner = window
    notify.done(inner, "Copied", "Analysis copied to clipboard.")
    dlg = notify.show_recent(None)
    from PyQt6.QtWidgets import QTextBrowser
    assert "Analysis copied" in dlg.findChild(QTextBrowser).toPlainText()
    dlg.close()


# ── On the Write tab ──────────────────────────────────────────────────

def test_write_tab_select_text_first_opens_no_box(app, fresh, tmp_path):
    from src.ui.manuscript_editor import ManuscriptEditor
    p = WriterProject(name="Saga")
    p.manuscript.chapters = [Chapter(id="c1", number=1, title="One", content="Rain fell.")]
    p.project_path = str(tmp_path / "Saga.writerproj")
    win = QMainWindow()
    win.statusBar()
    me = ManuscriptEditor()
    win.setCentralWidget(me)
    me.set_project(p)
    me.load_manuscript(p.manuscript)
    me.open_chapter("c1")
    ce = me.current_chapter_editor
    ce._rephrase_selection()
    assert fresh == []
    assert notify.recent()[0].title == "No Selection"
    assert "select some text" in win.statusBar().currentMessage().lower()
    win.close()


def test_a_box_that_stays_is_not_touched():
    """Moving chapters is work the writer must not miss: it stays a box."""
    # D.12: the move (and this box) went to the manuscript tree's module.
    src = open("src/ui/manuscript_tree.py", encoding="utf-8").read()
    i = src.index('"Chapters Moved"')
    assert "QMessageBox.information(" in src[i - 80:i]


def test_help_menu_has_recent_messages(app):
    from PyQt6.QtWidgets import QMenu
    menu = QMenu()
    act = notify.install_menu(menu, None)
    assert act.text().startswith("Recent")


def test_a_notice_is_seen_longer_on_a_tinted_bar_with_no_box(window, fresh):
    """The writer's choice for "Draft #N saved" and "Created draft …":
    visible, but no box."""
    win, inner = window
    notify.notice(inner, "Draft Saved", "Draft #3 saved.")
    assert fresh == []
    assert win.statusBar().currentMessage() == "Draft #3 saved."
    assert "font-weight: bold" in win.statusBar().styleSheet()
    win.statusBar().showMessage("Saved: elsewhere")           # the next message is plain
    assert win.statusBar().styleSheet() == ""
    assert notify.recent()[0].kind == "notice"


def test_the_two_draft_messages_are_notices():
    me = open("src/ui/manuscript_editor.py", encoding="utf-8").read()
    mw = open("src/ui/main_window.py", encoding="utf-8").read()
    for src, title in ((me, '"Draft Saved"'), (me, '"Draft Created"'), (mw, '"Draft Created"')):
        i = src.index(title)
        assert "notify.notice(" in src[i - 80:i], title


# ── Second session: the other screens ─────────────────────────────────

def test_a_dialog_without_a_status_bar_still_gets_its_box(window, fresh):
    """Behind a dialog the main window's bar may be hidden: a box, as before."""
    from PyQt6.QtWidgets import QDialog
    win, _ = window
    dlg = QDialog(win)
    notify.empty(dlg, "No Selection", "Please select a speaker to edit.")
    assert [a[1] for a in fresh] == ["No Selection"]
    assert win.statusBar().currentMessage() == ""
    assert notify.recent()[0].title == "No Selection"       # still listed
    dlg.deleteLater()


def test_a_tool_window_without_a_status_bar_still_gets_its_box(window, fresh):
    """Training Studio, Model Hub and the pop-out Draft Editor have no bar."""
    win, _ = window
    tool = QMainWindow()
    inner = QWidget()
    tool.setCentralWidget(inner)
    notify.empty(inner, "No Selection", "Select a row first.")
    assert [a[1] for a in fresh] == ["No Selection"]
    assert win.statusBar().currentMessage() == ""
    tool.close()


def test_print_with_no_chapters_opens_no_box(window, fresh):
    from types import SimpleNamespace
    from src.ui.print_manuscript import print_manuscript
    win, inner = window
    assert print_manuscript(inner, SimpleNamespace(chapters=[])) is False
    assert fresh == []
    assert "no chapters" in win.statusBar().currentMessage()


def test_editor_lookup_with_no_characters_opens_no_box(window, fresh):
    from src.ui.enhanced_text_editor import EnhancedTextEditor
    win, _ = window
    ed = EnhancedTextEditor()
    win.setCentralWidget(ed)
    ed.get_character_list_callback = lambda: []
    ed._lookup_character()
    assert fresh == []
    assert "No characters" in win.statusBar().currentMessage()
    ed.get_character_list_callback = None             # "not configured" stays a box
    ed._lookup_character()
    assert [a[1] for a in fresh] == ["Not Available"]


def test_second_session_boxes_that_stay_are_not_touched():
    """Not set up, work not done, data changed, saving: still boxes."""
    for path, title in (
            ("src/ui/enhanced_text_editor.py", '"Not Available"'),
            ("src/ui/video_studio/studio_widget.py", '"No image model configured"'),
            ("src/ui/video_studio/studio_widget.py", '"Slide deck reset"'),
            ("src/ui/characters_widget.py", '"Characters Strengthened"'),
            ("src/ui/image_generator_widget.py", '"Saved"')):
        src = open(path, encoding="utf-8").read()
        i = src.index(title)
        assert "QMessageBox.information(" in src[i - 120:i], (path, title)
