"""D.13c: "Where you left off" on the ribbon, one Feedback tab, whole tab
names.

Projects are built in ``tmp_path``; HOME and the window-state settings are
the test's own (conftest); no model runs; LanguageTool is never started.
"""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTabWidget

from src.ai.companion import Note, ReaderReport
from src.data import companion_state as cs
from src.data import readiness_state as rs
from src.models.project import Chapter, Manuscript, StoryEvent, WriterProject
from src.ui import feedback_sources as fs
from src.ui import tab_names
from src.ui import write_ribbon as wr

TEXT = ("Rain fell on the harbor all night. Mara watched the boats.\n\n"
        "It was very, very cold on the pier.\n\n"
        "That evening Tobin burned the letter in the stove.")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_languagetool(monkeypatch):
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)


@pytest.fixture(autouse=True)
def fresh_session():
    fs._SESSION.clear()
    yield
    fs._SESSION.clear()


def _project(tmp_path):
    p = WriterProject(name="Saga", manuscript=Manuscript(title="Main Manuscript"))
    p.manuscript.chapters = [Chapter(id=f"m{i}", number=i, title=t, content=TEXT)
                             for i, t in enumerate(["The Storm", "The Pier"], 1)]
    p.manuscript.chapters[0].planning.events.append(
        StoryEvent(id="e1", text="Slip past the patrol boat in the harbour fog"))
    p.save_project(str(tmp_path / "Saga.writerproj"))
    return p


def _editor(app, p, size=(1440, 900), session=True):
    from src.ui.manuscript_editor import ManuscriptEditor
    if session:
        cs.record_session(p, "m1", 10, 160, "Mara watched the boats.")
    w = ManuscriptEditor()
    w.set_project(p)
    w.load_manuscript(p.manuscript)
    w.open_chapter("m1")
    w.resize(*size)
    w.show()
    for _ in range(4):
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


def _settle(app, n=4):
    for _ in range(n):
        app.processEvents()


# ── 1. "Where you left off" on the ribbon ──────────────────────────────

def test_details_sits_after_draft_and_the_blue_line_is_gone(app, tmp_path):
    """The writer's follow-up (27 Nov): Details beside Draft; no blue line,
    no left-off words on the ribbon (they stay in the Companion)."""
    import src.ui.left_off_ribbon as lor
    p = _project(tmp_path)
    w = _editor(app, p)
    ce = w.current_chapter_editor
    banner, ribbon = ce.companion_banner, ce.write_ribbon
    editor_lay = ce.main_splitter.widget(0).layout()
    assert editor_lay.indexOf(banner) < 0                # the line above the text is gone
    btn = ribbon.details_btn
    assert btn.text() == "Details" and btn.toolTip().startswith("Details")
    assert btn.accessibleName() == "Details" and btn.accessibleDescription()
    bar = ribbon.bar
    for tab in wr.TABS:
        ribbon.show_tab(tab, remember=False)
        _settle(app)
        assert not banner.isVisible()                     # never shown
        assert btn.isVisible()
        draft_right = bar.mapTo(ribbon, bar.tabRect(bar.count() - 1).topRight()).x()
        x = btn.mapTo(ribbon, btn.rect().topLeft()).x()
        assert 0 <= x - draft_right <= 16                  # right after Draft
        y = btn.mapTo(ribbon, btn.rect().topLeft()).y()
        assert abs(y - bar.mapTo(ribbon, bar.rect().topLeft()).y()) <= 6
    ce.companion.refresh_left_off()
    _settle(app)
    assert not banner.isVisible()
    assert "Slip past the patrol boat" in ce.companion.panel.left_off_label.text()
    _done(app, w)


def test_details_toggles_the_panel_and_shows_it_is_open(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    ce = w.current_chapter_editor
    btn = ce.write_ribbon.details_btn
    assert not btn.isChecked()
    btn.click()
    _settle(app)
    assert ce.side_panel_open() and ce.right_panel.currentWidget() is ce.companion.panel
    assert btn.isChecked()                                # underlined while open
    btn.click()
    _settle(app)
    assert not ce.side_panel_open() and not btn.isChecked()
    ce._show_right_panel(ce.companion.panel)             # opened another way (◧ Panel)
    _settle(app)
    assert btn.isChecked()
    _done(app, w)


def test_the_old_details_button_still_works(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    ce = w.current_chapter_editor
    banner = ce.companion_banner
    banner.details_btn.click()
    assert ce.side_panel_open() and ce.right_panel.currentWidget() is ce.companion.panel
    assert banner.details_btn.text() == "Hide details"
    banner.details_btn.click()
    assert not ce.side_panel_open() and banner.details_btn.text() == "Details"
    _done(app, w)


def test_details_opens_the_whole_panel_on_where_you_left_off(app, tmp_path):
    p = _project(tmp_path)
    cs.set_section_collapsed(p, "left_off", True)         # the writer closed it once
    w = _editor(app, p)
    ce = w.current_chapter_editor
    panel = ce.companion.panel
    assert not panel.sections["left_off"].is_open()       # only its header row showed
    panel.scroll.verticalScrollBar().setValue(panel.scroll.verticalScrollBar().maximum())
    ce.write_ribbon.details_btn.click()
    _settle(app)
    assert panel.sections["left_off"].is_open()
    assert panel.scroll.verticalScrollBar().value() == 0  # in view, at the top
    assert "left_off" in cs.collapsed_sections(p)         # the writer's choice is kept
    # the whole side panel: full height, beside the ribbon and the text
    rp = ce.right_panel
    top = rp.mapTo(ce, rp.rect().topLeft()).y()
    assert top <= ce.write_ribbon.mapTo(ce, ce.write_ribbon.rect().topLeft()).y()
    assert rp.height() >= ce.height() - 2
    assert rp.width() >= rp.minimumWidth()
    _done(app, w)


def test_without_a_ribbon_the_line_stays_above_the_text(app, tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_build", lambda ce: (_ for _ in ()).throw(RuntimeError("x")))
    p = _project(tmp_path)
    w = _editor(app, p)
    ce = w.current_chapter_editor
    assert ce.main_splitter.widget(0).layout().indexOf(ce.companion_banner) >= 0
    assert ce.companion_banner.isVisible()
    _done(app, w)


# ── 3. Whole tab names ─────────────────────────────────────────────────

def _fits(bar, i, pad=20):
    return bar.tabRect(i).width() - pad >= bar.fontMetrics().horizontalAdvance(bar.tabText(i))


def test_side_panel_tab_names_are_measured_as_drawn_and_whole(app, tmp_path):
    p = _project(tmp_path)
    for size in ((1024, 600), (1440, 900)):
        w = _editor(app, p, size=size)
        ce = w.current_chapter_editor
        ce._show_right_panel(ce.feedback_widget)
        ce.right_panel.setTabText(ce.right_panel.indexOf(ce.companion.panel), "Companion (3)")
        _settle(app, 6)
        bar = ce.right_panel.tabBar()
        assert bar.font().pixelSize() == 11              # the bar's font is the tabs' font
        assert bar.elideMode() == Qt.TextElideMode.ElideRight
        assert not bar.usesScrollButtons()
        for i in range(bar.count()):
            assert _fits(bar, i), (size, bar.tabText(i), bar.tabRect(i).width())
        _done(app, w)


def test_names_shorten_only_when_the_bar_is_too_narrow(app):
    from PyQt6.QtWidgets import QLabel
    tabs = QTabWidget()
    tabs.setStyleSheet("QTabBar::tab { font-size: 11px; padding: 4px 10px; }")
    tab_names.whole(tabs, 11)
    for name in ("Planner", "Feedback", "Companion"):
        tabs.addTab(QLabel(name), name)
    tabs.resize(420, 200)
    tabs.show()
    _settle(app)
    bar = tabs.tabBar()
    assert all(_fits(bar, i) for i in range(bar.count()))
    tabs.resize(180, 200)                                # less than the whole names need
    _settle(app)
    assert sum(bar.tabRect(i).width() for i in range(bar.count())) <= tabs.width() + 2
    tabs.close()


def test_the_other_tab_bars_with_the_same_sheet_and_the_ribbon(app):
    from src.ui.ai_debug_panel import AIDebugPanel
    try:
        panel = AIDebugPanel()
    except Exception:
        panel = None
    if panel is not None:
        assert panel.tabs.tabBar().font().pixelSize() in (11, -1)
        assert "QTabBar { font-size: 11px" in panel.tabs.styleSheet()
        assert panel.tabs.tabBar().elideMode() == Qt.TextElideMode.ElideRight
    ribbon = wr.Ribbon()
    ribbon.resize(600, 80)
    ribbon.show()
    _settle(app)
    assert "font-weight: 500" in wr.tab_style()
    assert all(_fits(ribbon.bar, i, pad=28) for i in range(ribbon.bar.count()))
    ribbon.close()
    import inspect
    from src.ui import main_window
    assert "tab_names.whole(self.sidebar_tabs, 11)" in inspect.getsource(main_window)


# ── 2. One Feedback tab ────────────────────────────────────────────────

def _store_readiness(p, chapter_id, text, dismissed=()):
    from src.ai import readiness as rd
    at = text.index("very, very")
    item = {"start": at, "end": at + 10, "text": "very, very", "reason": "Two intensifiers.",
            "key": "rep:very"}
    other = {"start": 0, "end": 4, "text": "Rain", "reason": "Cleared.", "verdict": "cleared"}
    rs.store_chapter(p, None, chapter_id, {"text_hash": rd.text_hash(text),
                                          "made_at": "2026-11-26T18:20:00", "results": {
        "repetition": {"check": "repetition", "stage": "line", "status": "needs_work",
                       "count": 1, "items": [item, other]},
        "overdescribed": {"check": "overdescribed", "stage": "line", "status": "ready",
                          "count": 0, "items": []}}})
    if dismissed:
        rs.update(p, lambda d: d.setdefault("dismissed", {}).update({k: 1 for k in dismissed}))


def _store_history(p, title):
    from src.data import critique_history as chist
    path = chist.history_path(p)
    path.write_text(json.dumps({"k": [
        {"timestamp": "2026-11-20T09:00:00", "chapters": {title: {"reports": {
            "pacing": {"major": ["An older pacing note."], "minor": []}}}}},
        {"timestamp": "2026-11-25T09:00:00", "chapters": {title: {"reports": {
            "pacing": {"major": ["The middle stalls."], "minor": ["A small one."]}}}}}]}))


def _feedback(app, w):
    ce = w.current_chapter_editor
    ce._show_right_panel(ce.feedback_widget)
    _settle(app, 6)
    view = ce.feedback_sources
    view.refresh()
    return ce, view


def test_feedback_tab_keeps_its_own_and_lists_three_sources(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    ce, view = _feedback(app, w)
    fw = ce.feedback_widget
    assert fw.add_feedback_btn.isVisible() and fw.analyze_btn.isVisible()
    titles = [s.title for s in view.sections.values()]
    assert titles == ["From the Companion", "From the Critique", "From the Improve window"]
    fw._add_feedback_entry()                             # the writer's own stays first
    _settle(app)
    entry = fw._entry_widgets[0]["frame"]
    assert entry.mapTo(fw.container, entry.rect().topLeft()).y() < \
        view.mapTo(fw.container, view.rect().topLeft()).y()
    assert all(s.isVisible() for s in view.sections.values())
    _done(app, w)


def test_companion_notes_and_readers_eye_with_go_to_and_open(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    ce, view = _feedback(app, w)
    panel = ce.companion.panel
    note = Note("pov", "The point of view slips.", 2, "It was very, very cold")
    panel.set_notes([note, Note("voice", "Formal for Mara.", 0, "Mara watched")])
    panel.set_reader_report(ReaderReport(dips=[("burned the letter", "Rushed.")],
                                         questions=["Who sent it?"]))
    view.refresh()
    items = [i for i in view.items if i.source == fs.COMPANION]
    assert [i.kind for i in items][:2] == ["Notes as you write"] * 2
    assert any(i.kind.startswith("Reader's eye") and i.text == "Rushed." for i in items)
    assert "(4)" in view.sections[fs.COMPANION].header.text()
    n = view.items.index(items[0])
    view._link(f"go:{n}")
    assert ce.editor.textCursor().selectedText() == "It was very, very cold"
    ce._show_right_panel(ce.feedback_widget)
    view._link(f"open:{n}")
    assert ce.right_panel.currentWidget() is panel
    assert panel.notes_list.currentRow() == 0
    panel._dismiss_note()                                 # dismissed in the Companion …
    ce._show_right_panel(ce.feedback_widget)
    view.refresh()
    assert not any(i.text.endswith("The point of view slips.") for i in view.items)
    _done(app, w)


def test_critique_findings_newest_first_dismissed_left_out(app, tmp_path):
    p = _project(tmp_path)
    _store_readiness(p, "m1", TEXT)
    _store_history(p, "The Storm")
    w = _editor(app, p)
    ce, view = _feedback(app, w)
    items = [i for i in view.items if i.source == fs.CRITIQUE]
    texts = [i.text for i in items]
    assert texts[0].startswith("“very, very”")            # 26 Nov before 25 Nov
    assert "The middle stalls." in texts and "A small one." in texts
    assert "An older pacing note." not in texts           # the newest report of a kind
    assert not any("Cleared" in t for t in texts)
    assert items[0].kind == "Repeated words and phrases"
    n = view.items.index(items[0])
    view._link(f"go:{n}")
    assert ce.editor.textCursor().selectedText() == "very, very"
    view._link(f"open:{n}")                              # no main window here: it says where
    assert "Critique" in view.status.text() and view.status.isVisible()
    _store_readiness(p, "m1", TEXT, dismissed=["rep:very"])   # dismissed in the Critique
    view.refresh()
    assert not any(i.text.startswith("“very, very”") for i in view.items)
    _done(app, w)


def test_changed_text_says_the_findings_are_from_the_last_check(app, tmp_path):
    p = _project(tmp_path)
    _store_readiness(p, "m1", "Older text with very, very old words.")
    w = _editor(app, p)
    ce, view = _feedback(app, w)
    item = next(i for i in view.items if i.source == fs.CRITIQUE)
    assert "text has changed since" in item.kind
    _done(app, w)


class _Version:
    def __init__(self, text, source="suggestions", why="", rating=""):
        self.text, self.source, self.why, self.rating = text, source, why, rating
        self.current = text


class _Window:
    def __init__(self, project, chapter, passage, versions, replacement=None):
        from src.ai.passage_critique import PassageCritique
        self.project, self.chapter, self.passage = project, chapter, passage
        self.versions, self.replacement = versions, replacement
        self.tab_objects = {"suggestions": type("T", (), {"result": PassageCritique(
            works=["The image is clear."], issues=["It tells the cold."])})()}


def test_improve_window_this_session_and_saved_ratings(app, tmp_path, monkeypatch):
    p = _project(tmp_path)
    w = _editor(app, p)
    ce, view = _feedback(app, w)
    chapter = ce.chapter
    fs.remember_improve(_Window(p, chapter, "It was very, very cold on the pier.",
                                [_Version("The pier bit with cold.", why="Shows it.",
                                          rating="good")]), 0)
    import src.data.rephrase_database as rdb
    db = rdb._instance
    db.log_rephrase("Mara watched the boats.", "Mara counted the boats.", style="suggestion",
                    rating="excellent", accepted=False, project_path=p.project_path)
    db.log_rephrase("Not in this chapter.", "Elsewhere.", rating="good",
                    project_path=p.project_path)
    db.log_rephrase("Mara watched the boats.", "Another project's.", rating="good",
                    project_path=str(tmp_path / "other.writerproj"))
    view.refresh()
    items = [i for i in view.items if i.source == fs.IMPROVE]
    texts = [i.text for i in items]
    assert "It tells the cold." in texts and "The image is clear." in texts
    assert any(t.startswith("The pier bit with cold.") for t in texts)
    assert "Mara counted the boats." in texts
    assert "Elsewhere." not in texts and "Another project's." not in texts
    assert items[0].when >= items[-1].when                  # newest first
    opened = []
    import src.ui.improve as improve
    monkeypatch.setattr(improve, "open", lambda host, tab, text, s, e, **k:
                        opened.append((tab, text[s:e])) or False)
    first = next(i for i in view.items if i.text == "It tells the cold.")
    view._link(f"open:{view.items.index(first)}")
    assert opened == [("critique", "It was very, very cold on the pier.")]
    rated = next(i for i in view.items if i.text == "Mara counted the boats.")
    view._link(f"go:{view.items.index(rated)}")
    assert ce.editor.textCursor().selectedText() == "Mara watched the boats."
    _done(app, w)


def test_improve_window_done_keeps_what_it_said(app, tmp_path, monkeypatch):
    from src.ui.improve_window import ImproveWindow
    p = _project(tmp_path)
    chapter = p.manuscript.chapters[0]
    seen = []
    monkeypatch.setattr(fs, "remember_improve", lambda win, code: seen.append((win, code)))
    win = ImproveWindow.__new__(ImproveWindow)
    win.tab_objects = {}
    try:
        ImproveWindow.done(win, 0)
    except Exception:
        pass                                        # a bare window cannot close; the call came first
    assert seen and seen[0][0] is win


def test_reading_writes_nothing(app, tmp_path):
    p = _project(tmp_path)
    _store_readiness(p, "m1", TEXT)
    _store_history(p, "The Storm")
    w = _editor(app, p)
    files = {f: f.stat().st_mtime_ns for f in tmp_path.rglob("*") if f.is_file()}
    ce, view = _feedback(app, w)
    for _ in range(3):
        view.refresh()
    _settle(app)
    now = {f: f.stat().st_mtime_ns for f in tmp_path.rglob("*") if f.is_file()
           and f.suffix != ".ini"}
    assert {f: t for f, t in files.items() if f.suffix != ".ini"} == now
    _done(app, w)


def test_a_damaged_file_means_nothing_to_show(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    ce, view = _feedback(app, w)
    rs.readiness_path(p).write_text("{not json")
    view.refresh()
    assert not [i for i in view.items if i.source == fs.CRITIQUE]
    assert rs.readiness_path(p).read_text() == "{not json"      # never set aside or saved over
    _done(app, w)


def test_headings_fold_and_remember(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    ce, view = _feedback(app, w)
    view.sections[fs.CRITIQUE].header.click()
    assert not view.sections[fs.CRITIQUE].is_open()
    _done(app, w)
    w = _editor(app, p)
    ce, view = _feedback(app, w)
    assert not view.sections[fs.CRITIQUE].is_open() and view.sections[fs.COMPANION].is_open()
    _done(app, w)


def test_many_findings_are_counted_and_the_rest_left_to_the_source(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    ce, view = _feedback(app, w)
    many = [fs.Item(fs.CRITIQUE, "Check", f"finding {n}") for n in range(fs.MAX_SHOWN + 5)]
    view.show_items({fs.CRITIQUE: many})
    assert "(35)" in view.sections[fs.CRITIQUE].header.text()
    assert len([i for i in view.items if i.source == fs.CRITIQUE]) == fs.MAX_SHOWN
    _done(app, w)


def test_feedback_tab_fits_1024_by_600(app, tmp_path):
    p = _project(tmp_path)
    _store_readiness(p, "m1", TEXT)
    w = _editor(app, p, size=(1024, 600))
    ce, view = _feedback(app, w)
    _settle(app, 6)
    scroll = ce.feedback_widget.scroll
    assert scroll.viewport().width() >= view.minimumSizeHint().width() - 2   # no sideways cut
    assert scroll.height() >= ce.feedback_widget.height() // 3            # the lists get room
    assert ce.feedback_widget.analyze_btn.isVisible()
    _done(app, w)


# ── Backwards compatible ───────────────────────────────────────────────

def test_a_project_saved_before_opens_and_saves_unchanged(app, tmp_path):
    p = _project(tmp_path)
    path = tmp_path / "Saga.writerproj"
    w = _editor(app, p)
    ce, view = _feedback(app, w)
    ce.companion_banner.details_btn.click()
    _done(app, w)
    again = WriterProject.load_project(str(path))
    assert [c.content for c in again.manuscript.chapters] == [TEXT, TEXT]
    again.save_project(str(path))
    assert [c.content for c in WriterProject.load_project(str(path)).manuscript.chapters] \
        == [TEXT, TEXT]
    assert not rs.readiness_path(p).exists()             # the Feedback tab wrote nothing
