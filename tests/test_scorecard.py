"""2.1: the scorecard on the Critique tab's front page."""

import os
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.models.project import Chapter, Manuscript, WriterProject

TEXT = ("Its a beutiful day and he dont care. The rain fell on the roofs of the town.\n"
        "The night was very dark and terribly cold and frightening and so very lonely.\n") * 6
CLEAN = ("The rain fell on the roofs of the town. She walked to the harbor.\n"
         "Gulls turned over the water and the boats came in one by one.\n") * 10


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _project(tmp_path, texts=(TEXT, CLEAN), novella=None):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    for i, t in enumerate(texts):
        ch = Chapter(id=str(uuid.uuid4()), number=i + 1, title=f"Chapter {i + 1}",
                     folder_root=p.manuscript.folder_root)
        ch.content = t
        p.manuscript.chapters.append(ch)
    if novella is not None:
        sp = p.create_subproject("Novella")
        for i, t in enumerate(novella):
            ch = Chapter(id=str(uuid.uuid4()), number=i + 1, title=f"N{i + 1}",
                         folder_root=sp.manuscript.folder_root)
            ch.content = t
            sp.manuscript.chapters.append(ch)
    return p


def _wait(qapp, sc):
    from src.ui import background
    for _ in range(200):
        background.wait_all(5000)
        qapp.processEvents()
        if sc._task is None:
            return
    raise AssertionError("the check never finished")


@pytest.fixture
def grader(qapp, monkeypatch, tmp_path):
    import src.ui.scorecard_widget as sw
    store = {}

    class Settings:                                     # never the writer's real settings
        def value(self, k, d=None):
            return store.get(k, d)

        def setValue(self, k, v):
            store[k] = v
    monkeypatch.setattr(sw, "_settings", lambda: Settings())
    from src.ui.grader_widget import GraderWidget
    g = GraderWidget()
    g.resize(1200, 900)
    yield g
    g.close()


def test_the_grid_matches_the_report(qapp, grader, tmp_path):
    from src.ai import readiness as rd
    import src.ui.scorecard_widget as sc_module
    p = _project(tmp_path)
    grader.set_project(p)
    sc = grader.scorecard
    sc.refresh()
    _wait(qapp, sc)
    report = sc.report
    assert report is not None and len(report.chapters) == 2
    t = sc.table
    g = rd.grid(report)
    assert t.rowCount() == 2 and t.columnCount() == len(g.columns)
    for c, spec in enumerate(g.columns):
        assert spec.label in t.horizontalHeaderItem(c).text()
        assert spec.description.split(".")[0] in t.horizontalHeaderItem(c).toolTip()
        for r, (ch, cells) in enumerate(g.rows):
            assert t.item(r, c).text() == str(cells[c].count)
    assert t.verticalHeaderItem(0).text() == "1. Chapter 1"
    assert sc.figure_label.text() == f"{round(report.readiness * 100)}%" == "50%"
    assert "ready for readers" in sc.figure_caption.text()
    assert any(w.text() == sc_module.HONEST_LINE for w in sc.findChildren(type(sc.figure_caption)))
    assert "A scan" in sc.note_label.text() and "Overly descriptive" in sc.note_label.text()


def test_publishable_is_never_used_for_the_number(qapp, grader, tmp_path):
    from PyQt6.QtWidgets import QLabel
    grader.set_project(_project(tmp_path))
    grader.scorecard.refresh()
    _wait(qapp, grader.scorecard)
    texts = " ".join(w.text() for w in grader.scorecard.findChildren(QLabel)).lower()
    assert "publishable" not in texts


def test_an_empty_project_shows_a_helpful_message(qapp, grader, tmp_path):
    p = _project(tmp_path, texts=())
    grader.set_project(p)
    grader.scorecard.refresh()
    _wait(qapp, grader.scorecard)
    sc = grader.scorecard
    assert not sc.table.isVisibleTo(sc) and sc.empty.isVisibleTo(sc)
    assert "no chapters yet" in sc.empty.text().lower()


def test_no_project_shows_a_helpful_message(qapp, grader):
    sc = grader.scorecard
    assert sc.empty.isVisibleTo(sc) and "Open a project" in sc.empty.text()


def test_each_manuscript_has_its_own_grid(qapp, grader, tmp_path):
    p = _project(tmp_path, texts=(CLEAN,), novella=(TEXT, CLEAN, CLEAN))
    grader.set_project(p)
    sc = grader.scorecard
    assert sc.manuscript_combo.count() == 2 and sc.manuscript_combo.isVisibleTo(sc)
    sc.refresh()
    _wait(qapp, sc)
    assert sc.table.rowCount() == 1 and sc.figure_label.text() == "100%"
    sc.manuscript_combo.setCurrentIndex(1)
    _wait(qapp, sc)
    assert sc.report.scope == p.subprojects[0].id and sc.table.rowCount() == 3


def test_the_detailed_critique_is_one_click_away(qapp, grader, tmp_path):
    p = _project(tmp_path)
    grader.set_project(p)
    grader.show()
    qapp.processEvents()
    setup = grader.critique_setup
    assert not setup.is_open()                       # folded by default
    assert grader.critique_btn.isVisibleTo(grader)  # Run Critique stays on the page
    assert grader.results_tabs.isVisibleTo(grader)
    setup.header.click()
    assert setup.is_open() and grader.scope_multi_radio.isVisibleTo(grader)
    # A chapter's row prepares its detailed critique.
    _wait(qapp, grader.scorecard)
    setup.set_open(False)
    grader.scorecard._choose_row(1)
    assert setup.is_open() and grader.scope_multi_radio.isChecked()
    chosen = [grader.chapter_picker.item(i).data(0x0100 + 1)
              for i in range(grader.chapter_picker.count())
              if grader.chapter_picker.item(i).isSelected()]
    assert chosen == [p.manuscript.chapters[1].id]


def test_the_setup_section_remembers_being_open(qapp, monkeypatch):
    import src.ui.scorecard_widget as sw
    store = {}

    class Settings:
        def value(self, k, d=None):
            return store.get(k, d)

        def setValue(self, k, v):
            store[k] = v
    monkeypatch.setattr(sw, "_settings", lambda: Settings())
    from src.ui.grader_widget import GraderWidget
    g = GraderWidget()
    g.critique_setup.header.click()
    assert store[sw.SETUP_KEY] == "true"
    assert GraderWidget().critique_setup.is_open()


def test_narrow_window_collapses_stages(qapp, grader, tmp_path):
    from src.ai import readiness as rd
    grader.set_project(_project(tmp_path))
    sc = grader.scorecard
    sc.refresh()
    _wait(qapp, sc)
    stages = rd.grid(sc.report).stages()
    sc._narrow = True
    sc._expanded.clear()
    sc._fill_grid(sc.report)
    assert sc.table.columnCount() == len(stages)
    sc._toggle_stage("copyedit")
    assert sc.table.columnCount() == len(stages) - 1 + len(dict(stages)["copyedit"])
    assert "copyedit" in sc.ribbon.text()


def test_live_text_of_the_open_chapter_is_checked(qapp, grader, tmp_path):
    p = _project(tmp_path, texts=(TEXT,))

    class Ed:
        def __init__(self):
            from src.ui.enhanced_text_editor import EnhancedTextEditor
            self.editor = EnhancedTextEditor()
            self.editor.setPlainText(CLEAN)
            self.chapter = p.manuscript.chapters[0]

    class ME:
        current_chapter_editor = Ed()
    grader.set_project(p)
    grader.scorecard.set_live_source(ME())
    grader.scorecard.refresh()
    _wait(qapp, grader.scorecard)
    assert grader.scorecard.figure_label.text() == "100%"         # the live (clean) text


# ── The issues under the grid ────────────────────────────────────────────

def _checked(qapp, grader, p, live=None):
    grader.set_project(p)
    sc = grader.scorecard
    if live is not None:
        sc.set_live_source(live)
    sc.refresh()
    _wait(qapp, sc)
    return sc


def _col(sc, name):
    return next(c for c, names in enumerate(sc._column_checks) if names == [name])


def test_clicking_a_chapter_lists_what_was_found(qapp, grader, tmp_path):
    p = _project(tmp_path)
    sc = _checked(qapp, grader, p)
    assert "Click a chapter" in sc.issues.toPlainText()
    sc._select_row(0, None)
    text = sc.issues.toPlainText()
    assert "1. Chapter 1" in text and "Spelling and grammar left" in text
    assert "beutiful" in text and "Its a beutiful day" in text          # the word in its sentence
    assert "Overly descriptive" in text and "terribly cold" in text      # the sentence itself
    assert "Show in chapter" in text and "Ways to expand it" in text
    assert "×6" in text                                                   # one entry per word
    assert sc.selected_row() == 0 and sc.table.verticalHeaderItem(0).font().bold()
    assert not sc.table.verticalHeaderItem(1).font().bold()


def test_clicking_a_cell_shows_that_check_alone(qapp, grader, tmp_path):
    p = _project(tmp_path)
    sc = _checked(qapp, grader, p)
    sc._on_cell(0, _col(sc, "overdescribed"))
    text = sc.issues.toPlainText()
    assert "Overly descriptive" in text and "beutiful" not in text
    link = next(i for i, (k, _) in enumerate(sc.issues._links) if k == "all")
    from PyQt6.QtCore import QUrl
    sc.issues._on_link(QUrl(f"issue:{link}"))
    assert "beutiful" in sc.issues.toPlainText()


def test_links_go_to_the_chapter_and_the_expand_window(qapp, grader, tmp_path):
    from PyQt6.QtCore import QUrl
    p = _project(tmp_path)
    sc = _checked(qapp, grader, p)
    sc._on_cell(0, _col(sc, "spelling_grammar"))
    shown, expanded = [], []
    sc.issues.show_requested.connect(lambda *a: shown.append(a))
    grader.expand_statement_requested.connect(lambda *a: expanded.append(a))
    i = next(n for n, (k, item) in enumerate(sc.issues._links)
             if k == "show" and item.text == "beutiful")
    sc.issues._on_link(QUrl(f"issue:{i}"))
    cid = p.manuscript.chapters[0].id
    assert shown == [(cid, "beutiful", TEXT.index("beutiful"))]
    sc._on_cell(0, _col(sc, "overdescribed"))
    i = next(n for n, (k, _) in enumerate(sc.issues._links) if k == "expand")
    sc.issues._on_link(QUrl(f"issue:{i}"))
    assert expanded and expanded[0][0] == cid and "terribly cold" in expanded[0][2]


def test_a_click_points_the_detailed_critique_at_the_chapter(qapp, grader, tmp_path):
    p = _project(tmp_path)
    sc = _checked(qapp, grader, p)
    sc._select_row(1, None)
    assert grader.scope_multi_radio.isChecked() and not grader.critique_setup.is_open()
    chosen = [grader.chapter_picker.item(i).data(0x0100 + 1)
              for i in range(grader.chapter_picker.count())
              if grader.chapter_picker.item(i).isSelected()]
    assert chosen == [p.manuscript.chapters[1].id]
    assert grader.chapter_picker.count() == 2          # the picker is still there to change


class _Live:
    def __init__(self, chapter, text):
        from src.ui.enhanced_text_editor import EnhancedTextEditor

        class CE:
            pass
        self.current_chapter_editor = CE()
        self.current_chapter_editor.chapter = chapter
        self.current_chapter_editor.editor = EnhancedTextEditor()
        self.current_chapter_editor.editor.setPlainText(text)


def test_opens_on_the_manuscript_and_chapter_being_written(qapp, grader, tmp_path):
    p = _project(tmp_path, texts=(CLEAN,), novella=(CLEAN, TEXT, CLEAN))
    nov_ch = p.subprojects[0].manuscript.chapters[1]
    live = _Live(nov_ch, TEXT)
    grader.set_project(p)
    sc = grader.scorecard
    sc.set_live_source(live)
    grader.show()
    qapp.processEvents()
    _wait(qapp, sc)
    assert sc.scope() == p.subprojects[0].id
    assert sc._selected == nov_ch.id and "2. N2" in sc.issues.toPlainText()
    # The writer picks another chapter; it stays picked while Write is unchanged.
    sc._select_row(0, None)
    grader.hide()
    grader.show()
    qapp.processEvents()
    _wait(qapp, sc)
    assert sc._selected == p.subprojects[0].manuscript.chapters[0].id
    # Clicking the chapter open in Write sets the critique to "Current chapter".
    sc._select_row(1, None)
    assert grader.scope_single_radio.isChecked()


def test_show_passage_selects_it_in_the_editor(qapp, tmp_path):
    from src.ui.readiness_issues import show_passage
    p = _project(tmp_path)
    ch = p.manuscript.chapters[0]
    live = _Live(p.manuscript.chapters[1], CLEAN)
    opened = []

    class ME:
        current_chapter_editor = live.current_chapter_editor

        def open_chapter(self, cid):
            opened.append(cid)
            self.current_chapter_editor = _Live(ch, TEXT).current_chapter_editor

    class Tabs:
        def setCurrentWidget(self, w):
            pass

    class MW:
        manuscript_editor = ME()
        tab_widget = Tabs()

        def statusBar(self):
            raise AssertionError("the passage should be found")
    mw = MW()
    show_passage(mw, ch.id, "beutiful", TEXT.index("beutiful", 200))
    assert opened == [ch.id]
    cur = mw.manuscript_editor.current_chapter_editor.editor.textCursor()
    assert cur.selectedText() == "beutiful"
    assert cur.selectionStart() == TEXT.index("beutiful", 200)
