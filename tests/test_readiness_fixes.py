"""2.2: from a scorecard cell to the fix in the Companion."""

import os
import types
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import readiness as rd
from src.models.project import Chapter, Manuscript, WriterProject

ONE = "The rain fell. She walked slowly to the door. It was quiet.\n\nThe boats rocked.\n"
TWO = "Its a beutiful day and he dont care. The gulls cried over the harbor.\n"


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _project(tmp_path):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    for i, t in enumerate((ONE, TWO)):
        ch = Chapter(id=f"c{i + 1}", number=i + 1, title=f"Chapter {i + 1}",
                     folder_root=p.manuscript.folder_root)
        ch.content = t
        p.manuscript.chapters.append(ch)
    return p


def test_items_become_companion_fixes(tmp_path):
    from src.ui.readiness_fixes import fixes_from_items
    item = rd.Item(start=ONE.index("slowly"), end=ONE.index("slowly") + 6, text="slowly",
                   reason="-ly adverb", kind="adverb", suggestions=["carefully"])
    gone = rd.Item(start=0, end=5, text="Snow!", reason="x")
    cleared = rd.Item(start=0, end=3, text="The", reason="x", verdict="cleared")
    fixes = fixes_from_items("Adverbs", [item, gone, cleared], ONE)
    assert len(fixes) == 1
    f = fixes[0]
    assert f.sentence == "She walked slowly to the door." and f.excerpt == "slowly"
    assert f.options[0].text == "She walked carefully to the door." and not f.options[0].by_ai
    assert f.text.startswith("Adverbs: “slowly”")


def _write_tab(qapp, p):
    from src.ui.manuscript_editor import ManuscriptEditor
    me = ManuscriptEditor()
    me.set_project(p)
    me.load_manuscript(p.manuscript)
    me.open_chapter("c1")
    tabs = types.SimpleNamespace(setCurrentWidget=lambda w: None)
    return me, types.SimpleNamespace(manuscript_editor=me, tab_widget=tabs)


def test_one_click_to_the_sentence_and_accept(qapp, tmp_path):
    from src.ui.readiness_fixes import open_in_companion
    p = _project(tmp_path)
    me, mw = _write_tab(qapp, p)
    report = rd.chapter_report(p, p.manuscript.chapters[1])
    items = report.results["spelling_grammar"].items
    assert open_in_companion(mw, "c2", "Spelling and grammar left", items)
    ce = me.current_chapter_editor
    assert ce.chapter.id == "c2"                                 # the chapter opened
    panel = ce.companion.panel
    queue = ce.companion.queue                                   # D.6: on the next-fix card
    assert len(queue.entries) == len(items) > 0
    assert queue.given.startswith("From the scorecard: Spelling and grammar left")
    assert ce.right_panel.currentWidget() is panel               # the Companion is showing
    assert ce.editor.textCursor().selectedText() == panel.queue.fix.excerpt
    # Accept the editor's own suggestion through the Companion.
    fixes = [queue._fix_for(e) for e in queue.entries]
    fix = next(f for f in fixes if f is not None and f.options)
    before = ce.editor.toPlainText()
    ce.companion.accept_fix(fix, fix.options[0].text)
    qapp.processEvents()
    assert ce.editor.toPlainText() != before
    assert fix.options[0].text in ce.editor.toPlainText()


def test_unsaved_edits_survive_the_switch(qapp, tmp_path):
    from src.ui.readiness_fixes import open_in_companion
    p = _project(tmp_path)
    me, mw = _write_tab(qapp, p)
    me.current_chapter_editor.editor.setPlainText(ONE + "A new line I just typed.\n")
    items = rd.chapter_report(p, p.manuscript.chapters[1]).results["spelling_grammar"].items
    open_in_companion(mw, "c2", "Spelling", items)
    qapp.processEvents()
    assert "A new line I just typed." in p.manuscript.chapters[0].content


def test_double_click_on_a_cell_asks_for_the_companion(qapp, tmp_path, monkeypatch):
    import src.ui.scorecard_widget as sw
    from src.ui.grader_widget import GraderWidget
    from src.ui import background
    monkeypatch.setattr(sw, "_settings", lambda: type("S", (), {
        "value": lambda self, k, d=None: d, "setValue": lambda self, k, v: None})())
    p = _project(tmp_path)
    g = GraderWidget()
    g.set_project(p)
    sc = g.scorecard
    sc.refresh()
    for _ in range(50):
        background.wait_all(5000)
        qapp.processEvents()
        if sc._task is None:
            break
    got = []
    sc.issues.companion_requested.connect(lambda cid, label, items: got.append((cid, label, items)))
    row = sc._row_of("c2")
    col = next(c for c, n in enumerate(sc._column_checks) if n == ["spelling_grammar"])
    sc._fix_cell(row, col)
    assert got and got[0][0] == "c2" and got[0][1] == "Spelling and grammar left"
    assert got[0][2] and all(i.end > i.start for i in got[0][2])
    # A clean cell has nothing to fix: it shows the details instead.
    got.clear()
    sc._fix_cell(sc._row_of("c1"), col)
    assert not got and sc._selected == "c1"


# ── R.5: the revision controller ─────────────────────────────────────────

def test_the_controller_keeps_unsaved_edits_when_it_opens_a_chapter(qapp, tmp_path):
    from src.ui.revision_controller import RevisionController
    p = _project(tmp_path)
    me, mw = _write_tab(qapp, p)
    mw.statusBar = lambda: types.SimpleNamespace(showMessage=lambda *a: None)
    me.current_chapter_editor.editor.setPlainText(ONE + "Edits not yet saved.\n")
    rc = RevisionController(mw)
    assert rc.show_passage("c2", "beutiful", 0)
    qapp.processEvents()
    assert me.current_chapter_editor.chapter.id == "c2"
    assert me.current_chapter_editor.editor.textCursor().selectedText() == "beutiful"
    assert "Edits not yet saved." in p.manuscript.chapters[0].content


def test_main_window_handlers_live_in_the_controller():
    import inspect
    from src.ui.main_window import MainWindow
    for name in ("_go_to_critique_line", "_expand_critique_statement"):
        body = inspect.getsource(getattr(MainWindow, name))
        assert "self.revision." in body and len(body.splitlines()) <= 5


def test_go_to_line_and_expand_through_the_controller(qapp, tmp_path):
    from src.ui.revision_controller import RevisionController
    p = _project(tmp_path)
    me, mw = _write_tab(qapp, p)
    mw.statusBar = lambda: types.SimpleNamespace(showMessage=lambda *a: None)
    rc = RevisionController(mw)
    rc.go_to_line(2)
    # Unchanged from before R.5 (it selects from the space before the sentence).
    assert "She walked slowly to the door" in \
        me.current_chapter_editor.editor.textCursor().selectedText()
    seen = []
    me.current_chapter_editor.expand_statement = lambda s, e: seen.append((s, e))
    rc.expand_statement("", "Chapter 1", "It was quiet.", 0)
    assert seen and ONE[seen[0][0]:seen[0][1]] == "It was quiet."
