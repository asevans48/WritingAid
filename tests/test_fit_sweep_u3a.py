"""U.3a: the screens used most fit 1024 × 600 and 150 % (rule 12).

The side panel needed 1,094 px and Write 971 px at 150 %: the bottom bar's
labels now give up width (``ElidedLabel``), button rows wrap
(``FlowLayout``), the chapter title grows with its text (``grow_with_text``),
and the Critique in its own window scrolls sideways instead of cutting off.
"""

import importlib.util
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
SMALL = (1024, 600)
AT_150 = (960, 600)            # 1440 × 900 at 150 %: what the harness draws
TILED_150 = 960 - 420          # the main window's share beside a screen in its own window
LONG = "The Saltmarsh Wardens and the Drowned Bell Tower of Gallow's Reach"


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from src.ui.styles import get_modern_style
    before = app.styleSheet()
    app.setStyleSheet(get_modern_style())          # sizes as the app draws them
    yield app
    app.setStyleSheet(before)                      # other test files size without it


@pytest.fixture(autouse=True)
def no_languagetool(monkeypatch):
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)


def _settle(app, rounds=6):
    for _ in range(rounds):
        app.processEvents()


def _done(app, widget):
    """Close a screen with its deferred calls run first (Write hands focus
    to the chapter on a 0 ms timer; left pending, it would fire in a later
    test on an editor already gone)."""
    _settle(app)
    widget.close()
    _settle(app)


def _project(novella_name="The Fall"):
    from src.models.project import Chapter, Manuscript, WriterProject
    p = WriterProject(name="Saga", manuscript=Manuscript(title="Main Manuscript"))
    p.manuscript.chapters = [Chapter(id=f"m{i}", number=i, title=t, content="It was cold. " * 30)
                             for i, t in enumerate(["The Storm", LONG, "The Letter"], 1)]
    sp = p.create_subproject(novella_name)
    sp.manuscript.chapters = [Chapter(id=f"f{i}", number=i, title=f"Fall {i}", content="Text.")
                              for i in (1, 2)]
    p._normalize_manuscript_roots()
    return p


# ── The shared parts ─────────────────────────────────────────────────────

def test_an_elided_label_gives_up_its_width_and_shows_the_rest_as_a_tip(app):
    from src.ui.ui_kit import ElidedLabel
    text = "Chapter: FK grade 8.2 · Reading ease 64 (plain English)"
    label = ElidedLabel(text)
    full = label.sizeHint().width()
    assert label.minimumSizeHint().width() < full / 2      # never widens its window
    label.resize(full, 20)
    label.show()
    _settle(app)
    assert not label.is_cut() and label.toolTip() == ""
    label.resize(60, 20)
    _settle(app)
    assert label.is_cut() and label.toolTip() == text      # the whole text, on hover
    label.hide()


def test_an_elided_label_keeps_its_own_tip_and_reads_rich_text_plain(app):
    from PyQt6.QtCore import Qt
    from src.ui.ui_kit import ElidedLabel
    label = ElidedLabel("")
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setText("Chapter: FK grade <b style='color:#059669'>8.2</b>")
    label.setToolTip("Flesch-Kincaid grade level")
    label.resize(40, 20)
    label.show()
    _settle(app)
    assert label.plain_text() == "Chapter: FK grade 8.2"
    assert label.toolTip() == "Flesch-Kincaid grade level"
    label.grab()                                           # draws, elided, without error
    label.hide()


def test_a_short_label_keeps_its_whole_width(app):
    from src.ui.ui_kit import ElidedLabel
    label = ElidedLabel("Words: 67")
    assert label.minimumSizeHint().width() == label.sizeHint().width()


def test_a_flow_row_wraps_instead_of_widening(app):
    from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget
    from src.ui.ui_kit import FlowLayout
    host = QWidget()
    outer = QVBoxLayout(host)
    row = FlowLayout()
    buttons = [QPushButton(t) for t in ("Go to", "💡 Suggest fix", "Mark beat done", "💬 Ask",
                                        "Dismiss")]
    for b in buttons:
        row.addWidget(b)
    outer.addLayout(row)
    widest = max(b.sizeHint().width() for b in buttons)
    assert host.minimumSizeHint().width() <= widest + 30    # one button, not five
    host.resize(widest + 40, 300)
    host.show()
    _settle(app)
    tops = {b.geometry().top() for b in buttons}
    assert len(tops) > 1                                    # it wrapped
    for b in buttons:                                       # nothing cut, nothing outside
        assert b.width() >= b.minimumSizeHint().width()
        assert b.geometry().right() <= host.width()
    for a in buttons:
        for b in buttons:
            if a is not b:
                assert not a.geometry().intersects(b.geometry())
    host.hide()


def test_a_title_box_is_as_tall_as_its_text(app):
    from PyQt6.QtWidgets import QTextEdit
    from src.ui.ui_kit import grow_with_text
    edit = QTextEdit()
    grow_with_text(edit)
    edit.resize(300, 40)
    edit.setPlainText("Chapter 1")
    edit.show()
    _settle(app)
    one = edit.height()
    assert edit.verticalScrollBar().maximum() == 0          # the whole line shows
    edit.setPlainText(LONG + " " + LONG)
    _settle(app)
    assert edit.height() > one                              # a long title wraps and shows
    assert edit.height() <= one + 3 * edit.fontMetrics().lineSpacing()
    edit.hide()


# ── The Write screen and its side panel ─────────────────────────────────

def test_the_side_panel_fits_a_small_screen_and_150_percent(app):
    from src.ui.manuscript_editor import ChapterEditor
    p = _project()
    ed = ChapterEditor(p.manuscript.chapters[0], project=p)
    ed.resize(*SMALL)
    ed.show()
    for panel in (ed.companion.panel, ed.planner_widget, ed.feedback_widget):
        ed._show_right_panel(panel)
        _settle(app)
        need = ed.minimumSizeHint()
        assert need.width() <= AT_150[0] and need.height() <= AT_150[1], need   # was 1,094
    # The status line's words ("Chapter:", "Words:") elide, so a longer word fits.
    assert ed.readability_label.minimumSizeHint().width() < 80
    assert ed.grammar_status_label.minimumSizeHint().width() < 80
    _done(app, ed)


def test_the_companions_note_buttons_wrap_in_a_narrow_panel(app):
    from src.ui.manuscript_editor import ChapterEditor
    from src.ui.ui_kit import FlowLayout
    p = _project()
    ed = ChapterEditor(p.manuscript.chapters[0], project=p)
    ed.resize(*SMALL)
    ed.show()
    ed._show_right_panel(ed.companion.panel)
    _settle(app)
    panel = ed.companion.panel
    rows = [lay for lay in panel.findChildren(FlowLayout)]
    assert rows, "the notes' buttons are a wrapping row"
    assert panel.minimumSizeHint().width() <= 300           # the panel's own minimum
    _done(app, ed)


def test_write_fits_the_main_windows_share_when_tiled_at_150_percent(app):
    from src.ui.manuscript_editor import ManuscriptEditor
    p = _project()
    w = ManuscriptEditor()
    w.set_project(p)
    w.load_manuscript(p.manuscript)
    w.open_chapter("m1")
    w.resize(*SMALL)
    w.show()
    _settle(app)
    need = w.minimumSizeHint()
    assert need.width() <= TILED_150 and need.height() <= SMALL[1], need          # was 971
    ce = w.findChild(__import__("src.ui.manuscript_editor", fromlist=["x"]).ChapterEditor)
    title = ce.title_edit
    assert title.verticalScrollBar().maximum() == 0          # the title is not cut
    _done(app, w)


def test_the_manuscript_tree_elides_long_names_and_shows_the_undo_line(app):
    from PyQt6.QtCore import Qt
    from src.ui.manuscript_editor import ManuscriptEditor
    p = _project(novella_name=LONG)
    for n in range(6):
        p.create_subproject(f"Novella {n}: {LONG}")
    w = ManuscriptEditor()
    w.set_project(p)
    w.load_manuscript(p.manuscript)
    w.open_chapter("m1")
    w.resize(*SMALL)
    w.show()
    _settle(app)
    tree = w.manuscript_tree
    tree.rebuild()
    tree.announce(f"Moved “{LONG}” to {LONG}")
    _settle(app)
    assert w.minimumSizeHint().width() <= SMALL[0]           # long names do not widen Write
    assert tree.textElideMode() == Qt.TextElideMode.ElideRight
    item = tree.topLevelItem(1)
    assert tree.visualItemRect(item).width() < tree.fontMetrics().horizontalAdvance(item.text(0))
    notice = tree.notice
    assert notice.isVisible() and notice.wordWrap() and "undo" in notice.text().lower()
    assert notice.geometry().bottom() <= w.left_panel.height()       # on screen, not cut
    assert notice.height() >= notice.heightForWidth(notice.width()) - 2
    _done(app, w)


# ── Dialogs and windows in the sweep ─────────────────────────────────────

def test_the_stage_chooser_wraps_a_long_novella_name(app):
    from src.ui.chapter_stage_ui import ChaptersDialog
    p = _project(novella_name=LONG)
    dlg = ChaptersDialog(p, p.subprojects[0].id)
    need = dlg.minimumSizeHint()
    assert need.width() <= 460, need                          # was 621 with this name
    from PyQt6.QtWidgets import QLabel
    heading = dlg.findChildren(QLabel)[0]
    assert "Gallow's" in heading.text() or "Gallow&#x27;s" in heading.text()
    assert heading.wordWrap()
    dlg.deleteLater()


def test_the_critique_fits_its_own_window_at_420_px(app):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QScrollArea
    from src.ui.grader_widget import GraderWidget
    g = GraderWidget()
    g.set_project(_project())
    g.resize(420, 600)
    g.show()
    _settle(app)
    area = g.findChild(QScrollArea)
    # Whatever cannot narrow further scrolls sideways; nothing is cut off.
    assert area.horizontalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    _done(app, g)


def test_the_rating_row_wraps(app):
    from src.ui.rating_bar import RatingBar
    bar = RatingBar()
    assert bar.minimumSizeHint().width() < bar.sizeHint().width() / 2


def test_add_hierarchy_is_never_cut_short(app):
    """"➕ Add Hierarchy" read "Add Hierarch" at 1024 × 600 (the writer's note)."""
    from PyQt6.QtWidgets import QPushButton
    from src.ui.ui_kit import full_text
    from src.ui.worldbuilding.hierarchy_builder import HierarchyBuilderWidget
    w = HierarchyBuilderWidget()
    w.resize(1024, 560)
    w.show()
    _settle(app)
    # U.3b: in the narrow column it reads "➕ Add" (its full name on hover).
    add = next(b for b in w.findChildren(QPushButton) if "Add Hierarchy" in full_text(b))
    assert add.width() >= add.minimumSizeHint().width()
    _done(app, w)


def _harness():
    spec = importlib.util.spec_from_file_location("screen_harness",
                                                  ROOT / "scripts" / "screen_harness.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Settings is not built in this process: even with its pages on a stand-in,
# its frame leaves background work that later tests trip over. The harness
# draws it in a process of its own (the last test below, "settings").


def test_the_harness_reports_content_cut_off_at_the_side(app):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget
    h = _harness()
    top = QWidget()
    area = QScrollArea()
    QVBoxLayout(top).addWidget(area)
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(QLabel("x" * 300))
    top.resize(200, 200)
    top.show()
    _settle(app)
    assert any("cut off at the side" in p for p in h._check(top, top, app))
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    assert not any("cut off at the side" in p for p in h._check(top, top, app))
    top.close()


def test_the_sweep_screens_are_in_the_harness():
    h = _harness()
    for name in ("write_tree", "write_tiled", "critique_window", "fix_all", "hover_card",
                 "chapter_stages", "settings"):
        assert name in h.SCREENS and name in h.SWEEP_SCREENS


def test_the_sweep_group_passes_the_harness_at_the_small_size(tmp_path):
    """The group draws within 1024 × 600 with no problem (the run at all
    four sizes is the session's; one size keeps the suite quick)."""
    h = _harness()
    names = ["write", "companion", "planner", "feedback", "write_tree", "critique_window",
             "chapter_stages", "settings", "improve_rephrase"]
    results = h.run(names, tmp_path, sizes=[(1024, 600, 1.0)])
    report = results["1024x600"]
    for name in names:
        info = report["screens"][name]
        assert "error" not in info, info
        assert info["problems"] == [], (name, info["problems"])
        assert info["needs"][0] <= 1024 and info["needs"][1] <= 600
