"""The Critique in its own window, beside Write; links to each problem."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def mw(app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget
    from src.ui import critique_window
    store = {}

    class Settings:
        def value(self, k, d=None):
            return store.get(k, d)

        def setValue(self, k, v):
            store[k] = v
    monkeypatch.setattr(critique_window, "_settings", lambda: Settings())
    from src.ui.grader_widget import GraderWidget
    win = QMainWindow()
    win.tab_widget = QTabWidget()
    win.setCentralWidget(win.tab_widget)
    win.write = QWidget()
    win.tab_widget.addTab(win.write, "Write")
    win.grader_widget = GraderWidget()
    win.tab_widget.addTab(win.grader_widget, "Critique")
    win.resize(1200, 800)
    win.show()
    critique_window.install(win)
    win.store = store
    yield win
    if win.critique_popout.window is not None:
        win.critique_popout.bring_back()
    win.close()


def test_pop_out_moves_the_whole_critique_and_back(app, mw):
    pop = mw.critique_popout
    scorecard = mw.grader_widget.scorecard
    assert pop.button.text() == "⧉ Own window"
    assert scorecard.isVisibleTo(mw.grader_widget)
    mw.tab_widget.setCurrentWidget(mw.grader_widget)
    pop.button.click()
    app.processEvents()
    assert pop.window is not None and pop.window.isVisible()
    assert scorecard.window() is pop.window                     # the same scorecard, moved
    assert mw.tab_widget.currentWidget() is mw.write            # Write, beside it
    assert pop.note.isVisibleTo(mw.grader_widget)               # the tab says where it went
    assert pop.button.text() == "⧉ Back to the tab"
    assert mw.store.get("critique_window/out") == "true"
    pop.window.close()                                          # closing brings it back
    app.processEvents()
    assert pop.window is None and scorecard.window() is mw
    assert not pop.note.isVisibleTo(mw.grader_widget)
    assert mw.tab_widget.currentWidget() is mw.grader_widget
    assert "critique_window/geometry" in mw.store               # opens there next time


def test_choosing_the_tab_while_out_raises_the_window_and_links_bring_write_forward(app, mw):
    pop = mw.critique_popout
    pop.pop_out()
    raised = []
    pop.raise_window = lambda: raised.append(True)
    mw.tab_widget.setCurrentWidget(mw.grader_widget)
    assert raised
    forward = []
    mw.activateWindow = lambda: forward.append(True)
    mw.grader_widget.scorecard.issues.show_requested.emit("c1", "x", 0)
    assert forward


def test_the_menu_entry_toggles_it(app, mw):
    from PyQt6.QtWidgets import QMenu
    from src.ui import critique_window
    menu = QMenu()
    critique_window.add_to_menu(mw, menu)
    act = menu.actions()[-1]
    assert act.text() == "Critique in Its Own Window"
    act.trigger()
    assert mw.critique_popout.is_out
    menu2 = QMenu()
    critique_window.add_to_menu(mw, menu2)
    assert menu2.actions()[-1].text() == "Bring the Critique Back to Its Tab"
    menu2.actions()[-1].trigger()
    assert not mw.critique_popout.is_out


def test_each_finding_links_to_its_place_and_repeats_link_to_each(app):
    from src.ai import readiness as rd
    from src.ui.readiness_issues import ChapterIssues
    text = "Teh rain fell. Teh boats came in. Teh tide turned."
    items = [rd.Item(start=i, end=i + 3, text="Teh", reason="Possible misspelling.",
                     kind="spelling", key="spelling:teh")
             for i in (0, 15, 34)]
    from types import SimpleNamespace as NS
    rd._load_checks()
    spec = rd.REGISTRY.get("spelling_grammar")
    if spec is None:
        pytest.skip("no spelling check")
    result = NS(status="problem", count=3, found=3, measure=None, message="", error="",
                items=items)
    ch = NS(chapter_id="c1", number=1, title="One", words=10, text_hash="", is_opening=False,
            results={"spelling_grammar": result}, stage="", scope=None)
    view = ChapterIssues()
    view._chapter, view._links, view._titles = ch, [], {}
    html = view._check_html("spelling_grammar", result, text, ch)
    shows = [i for kind, i in view._links if kind == "show"]
    assert [i.start for i in shows[-3:]] == [0, 15, 34]          # each place
    assert "Each place:" in html and "<a href='issue:" in html
    got = []
    view.show_requested.connect(lambda cid, t, at: got.append((cid, at)))
    from PyQt6.QtCore import QUrl
    last = len(view._links) - 1
    view._on_link(QUrl(f"issue:{last}"))
    assert got == [("c1", 34)]


def test_a_finding_without_a_place_still_links_to_the_chapter(app):
    from types import SimpleNamespace as NS
    from src.ai import readiness as rd
    from src.ui.readiness_issues import ChapterIssues
    item = rd.Item(start=0, end=0, text="He walked to the door.", reason="Nothing changes.",
                   kind="", key="")
    ch = NS(chapter_id="c1")
    assert ChapterIssues._showable(item, ch)
    assert not ChapterIssues._showable(item, NS(chapter_id=rd.BOOK_ROW))
