"""Find shows how often the text appears in the chapter in focus."""

import os
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TEXT = ("Cut the rope. She said, \"Cut it out.\" He cut it out of the net, then cut it "
        "out again.\n\nThe cutter drifted. CUT IT OUT, she wrote.")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def editor(app):
    from src.models.project import Chapter, WriterProject
    from src.ui.manuscript_editor import ManuscriptEditor
    proj = WriterProject(name="t")
    proj.manuscript.chapters = [Chapter(id="c1", number=1, title="Other", content="cut cut cut"),
                                Chapter(id="c2", number=2, title="The Pier", content=TEXT)]
    me = ManuscriptEditor(proj)
    me.load_manuscript(proj.manuscript)
    me.open_chapter("c2")
    return me


@pytest.mark.parametrize("text,case,whole,total", [
    ("cut", False, False, 6),          # includes "cutter"
    ("cut", False, True, 5),
    ("cut", True, True, 2),
    ("cut it out", False, False, 4),
    ("cut it out", True, False, 2),
    ("rope", False, False, 1),
    ("anchor", False, False, 0),
])
def test_counts_in_the_chapter_in_focus(editor, text, case, whole, total):
    assert editor.count_matches(text, case, whole)[0] == total


def test_selected_match_is_numbered(editor):
    assert editor.find_text("cut it out")
    assert editor.count_matches("cut it out") == (4, 1)
    editor.find_text("cut it out")
    assert editor.count_matches("cut it out") == (4, 2)


def win_for(editor, dialog):
    from src.ui.main_window import MainWindow
    win = NS(manuscript_editor=editor, find_dialog=dialog, replace_dialog=None,
             sender=lambda: None)
    win._match_status = lambda *a: MainWindow._match_status(win, *a)
    return win, MainWindow


def test_enter_in_find_shows_the_count(editor, app):
    from src.ui.find_replace_dialog import FindReplaceDialog
    dialog = FindReplaceDialog(replace_mode=False)
    win, MainWindow = win_for(editor, dialog)
    MainWindow._on_find_next(win, "cut", False, True)
    assert dialog.status_label.text() == "1 of 5 matches in “The Pier”"
    MainWindow._on_find_next(win, "cut it out", False, False)
    assert dialog.status_label.text().endswith("of 4 matches in “The Pier”")
    MainWindow._on_find_next(win, "rope", False, False)
    assert dialog.status_label.text() == "1 of 1 match in “The Pier”"
    MainWindow._on_find_next(win, "anchor", False, False)
    assert dialog.status_label.text() == "“anchor” not found in “The Pier” (0 matches)"


def test_count_follows_the_chapter_in_focus(editor, app):
    from src.ui.find_replace_dialog import FindReplaceDialog
    dialog = FindReplaceDialog(replace_mode=False)
    win, MainWindow = win_for(editor, dialog)
    editor.open_chapter("c1")
    MainWindow._on_find_next(win, "cut", False, True)
    assert dialog.status_label.text() == "1 of 3 matches in “Other”"


def test_replace_shows_what_is_left(editor, app):
    from src.ui.find_replace_dialog import FindReplaceDialog
    dialog = FindReplaceDialog(replace_mode=True)
    win, MainWindow = win_for(editor, dialog)
    win.replace_dialog, win.find_dialog = dialog, None
    editor.find_text("cut it out")
    MainWindow._on_replace_next(win, "cut it out", "stop it", False, False)
    assert dialog.status_label.text().endswith("of 3 matches in “The Pier”")
