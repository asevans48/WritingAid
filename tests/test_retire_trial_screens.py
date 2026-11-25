"""D.6 Retire the trial screens: the Style tab and Today's three fixes go;
everything they did is reachable from the Companion's card and the
✓ Checks ▾ menu; old tab numbers, settings and projects still open."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))     # test_project_compat

TEXT = ("She very quickly ran to the door in order to escape. The map was taken by the "
        "guards at dawn.\nHe walked slowly. He walked slowly again.")



def _existing(p):
    """A project from before decision 3 (24 Nov 2026): it keeps every style
    check ticked, as these tests expect; a new one ticks only those meeting
    4 in 5 (tests/test_check_switches.py)."""
    from datetime import datetime
    p.created_at = datetime(2026, 3, 1)
    return p

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)
    from src.ai import readiness as rd
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))


def _editor(app, text=TEXT):
    from src.models.project import Chapter, WriterProject
    from src.ui.manuscript_editor import ChapterEditor
    p = _existing(WriterProject(name="t"))
    p.manuscript.chapters.append(Chapter(id="c1", number=1, title="One", content=text))
    ed = ChapterEditor(p.manuscript.chapters[0], project=p)
    ed.resize(1100, 700)
    ed.show()
    app.processEvents()
    return ed


def _wait(app):
    from src.ui import background, companion_panel
    for _ in range(20):
        for t in list(companion_panel._RUNNING):
            t.wait(10000)
        background.wait_all(10000)
        app.processEvents()
        if not companion_panel._RUNNING:
            return


def _menu_action(ed, text):
    return next(a for a in ed.checks_menu.actions() if a.text() == text)


# ── The side panel: three tabs, old numbers still mean what they meant ──

def test_the_side_panel_has_no_style_tab(app):
    ed = _editor(app)
    tabs = [ed.right_panel.tabText(i) for i in range(ed.right_panel.count())]
    assert tabs[0] == "Planner" and tabs[1] == "Feedback" and tabs[2].startswith("Companion")
    assert not hasattr(ed, "style_panel")


@pytest.mark.parametrize("old, name", [(0, "planner"), (1, "companion"), (2, "feedback"),
                                       (3, "companion")])
def test_each_old_tab_number_opens_the_tab_it_meant(app, old, name):
    ed = _editor(app)
    want = {"planner": ed.planner_widget, "feedback": ed.feedback_widget,
            "companion": ed.companion.panel}[name]
    ed._show_right_panel(old)                       # the Style tab's 1 opens the Companion
    assert ed.side_panel_open() and ed.right_panel.currentWidget() is want
    ed._show_right_panel(ed.feedback_widget)        # a widget is used as it is
    assert ed.right_panel.currentWidget() is ed.feedback_widget


# ── The old menu entry is a shortcut to the new home ─────────────────

def test_style_issues_panel_opens_every_style_issue_on_the_card_with_a_note_once(app):
    from src.ui import retired_screens, ui_kit
    settings = ui_kit._settings()
    settings.setValue("geometry/SomeWindow", "kept")          # saved before the piece
    settings.sync()
    ed = _editor(app)
    _menu_action(ed, "Style issues panel…").trigger()
    queue, card = ed.companion.queue, ed.companion.panel.queue
    assert ed.right_panel.currentWidget() is ed.companion.panel
    assert ed.companion.panel.sections["fixes"].is_open()
    assert queue.given == "Every style issue in this chapter"
    kinds = {e.item.kind for e in queue.entries}
    assert {"intensifier", "adverb", "wordy", "passive"} <= kinds   # every kind, any stage
    assert card.status.text().startswith(retired_screens.NOTE)
    _menu_action(ed, "Style issues panel…").trigger()            # the note shows once
    assert retired_screens.NOTE not in card.status.text()
    assert ui_kit._settings().value("geometry/SomeWindow") == "kept"   # nothing deleted
    card.find_requested.emit()                                   # Check again: the stage queue
    assert queue.given == ""
    _wait(app)


# ── Capability checklist: the Style tab ───────────────────────────────

def test_every_style_tab_action_has_a_home(app):
    from src.utils.style_checks import KINDS
    ed = _editor(app)
    # Highlight in text: ✓ Checks ▾ → Style.
    ed._check_actions["style"].setChecked(True)
    assert ed.editor.get_style_mode().name != "OFF"
    # Switch each check, its count, the summary: ✓ Checks ▾ → Style checks.
    sub = ed._style_summary_action.parent()
    sub.aboutToShow.emit()
    assert set(ed._style_check_actions) == set(KINDS)
    assert "issues" in ed._style_summary_action.text() and "/1,000 words" in \
        ed._style_summary_action.text()
    assert ed._style_check_actions["adverb"].text().endswith(")")
    # Check consistency: ✓ Checks ▾ (and Analyze ▾), unchanged.
    assert _menu_action(ed, "Check consistency (names, spellings)…")
    # The list, stepping through it, Go to: the card.
    queue, card = ed.companion.queue, ed.companion.panel.queue
    queue.show_style_issues()
    n = len(queue.entries)
    assert n >= 4 and card.fix is not None
    first = queue.entries[queue.index].key
    queue.skip()
    assert queue.entries[queue.index].key != first
    queue.back()
    card.goto_btn.click()
    assert ed.editor.textCursor().hasSelection()
    # Show only one check's issues: the card's "Only …" link.
    assert "href='only'" in card.status.text()
    card.only_requested.emit()
    assert len({e.check for e in queue.entries}) == 1 and queue.given.startswith("Only ")
    # Ignore: Not a problem; Undo puts it back.
    queue.show_style_issues()
    entry = queue.entries[queue.index]
    queue.dismiss()
    hl = ed.editor.writing_highlighter
    assert any(k == entry.item.kind for k, _t in hl._style_ignored)
    queue.undo_dismiss()
    assert not any(k == entry.item.kind for k, _t in hl._style_ignored)
    assert queue.given                                           # still the style list
    # ✨ Rewrite with AI: 💡 More options… sends the Style tab's own request.
    asked = []
    ed.editor.style_rewrite_requested.disconnect()
    ed.editor.style_rewrite_requested.connect(lambda a, b, why: asked.append(why))
    queue.index = [e.item.kind for e in queue.entries].index("passive")
    queue.show()
    queue.more(card.fix)
    assert asked and asked[0].startswith("Fix the passive")
    # Fix: Accept.
    queue.index = [e.item.kind for e in queue.entries].index("wordy")
    queue.show()
    card._accept()
    _wait(app)
    assert "in order to" not in ed.editor.toPlainText()


# ── Capability checklist: Today's three fixes ─────────────────────────

def test_every_three_fixes_action_has_a_home(app, monkeypatch):
    from src.ui import companion_panel
    ed = _editor(app)
    cc, card = ed.companion, ed.companion.panel.queue
    monkeypatch.setattr(companion_panel, "_companion_ai_enabled", lambda: True)
    cc._no_model = False
    cc.queue.chapter_loaded()
    assert "href='three'" in card.status.text()                 # find them: a link on the card
    cc._no_model = True                                          # no model: quick picks
    card.three_requested.emit()
    _wait(app)
    assert cc.queue.given.startswith(cc.THREE) and 0 < len(cc.queue.entries) <= 3
    assert card.fix is not None                                  # pick one, see its rewrite
    card.edit()                                                  # edit it…
    assert card.options.isVisibleTo(card)
    assert card.more_btn.isVisibleTo(card) and card.goto_btn.isVisibleTo(card)  # More options…, Go to
    before = ed.editor.toPlainText()
    card.options.lineEdit().setText((card.fix.sentence or card.fix.excerpt) + " Then nothing.")
    card.options.lineEdit().textEdited.emit("x")
    card._accept()                                               # …and Accept
    _wait(app)
    assert ed.editor.toPlainText() != before and "Then nothing." in ed.editor.toPlainText()


def test_a_rewrite_s_warnings_show_on_the_card(app):
    from src.ai.companion import Fix, FixOption
    ed = _editor(app)
    fix = Fix("Wordy", excerpt="in order to", paragraph=0,
              sentence="She very quickly ran to the door in order to escape.",
              options=[FixOption("She ran to the door to escape.", notes=["drops a word"])])
    ed.companion.queue.show_fixes([fix], "From the scorecard")
    assert "drops a word" in ed.companion.panel.queue.change.text()


# ── Older projects and settings ──────────────────────────────────────

def test_a_project_from_before_the_piece_opens_and_saves_unchanged(app):
    import shutil
    from test_project_compat import _v1_project_dir
    from src.models.project import WriterProject
    from src.ui.manuscript_editor import ManuscriptEditor
    d, path = _v1_project_dir()
    files = sorted(d.glob("chapters/*/*.md"))
    before = {f: f.read_bytes() for f in files}
    p = WriterProject.load_project(str(path))
    w = ManuscriptEditor()
    w.set_project(p)
    w.load_manuscript(p.manuscript)
    w.open_chapter(p.manuscript.chapters[0].id)
    ce = w.current_chapter_editor
    ce._show_right_panel(1)                          # the old Style tab's number
    assert ce.right_panel.currentWidget() is ce.companion.panel
    ce._open_style_panel()
    app.processEvents()
    p.save_project(str(path))
    again = WriterProject.load_project(str(path))
    assert {f: f.read_bytes() for f in files} == before
    assert len(again.manuscript.chapters) == len(p.manuscript.chapters)
    w.deleteLater()
    shutil.rmtree(d)


# ── The counting rule (decision 11) ───────────────────────────────────

def _harness():
    spec = importlib.util.spec_from_file_location("screen_harness",
                                                  ROOT / "scripts" / "screen_harness.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_grouped_submenu_counts_as_one_entry(app):
    from PyQt6.QtWidgets import QMenu
    h = _harness()
    menu = QMenu()
    improve = menu.addMenu("✨ Improve this")
    for t in ("Rephrase", "Suggestions", "Overly descriptive?"):
        improve.addAction(t)
    syn = menu.addMenu("📖 Synonyms for \"cold\"")
    for t in ("chilly", "icy", "frigid"):
        syn.addAction(t)
    syn.addMenu("Antonyms").addAction("warm")
    menu.addAction("Paste")
    assert h._menu_items(menu) == 3 + 1 + 1            # Improve's three, synonyms one, Paste
    assert h._menu_items(menu, itemised=True) == 3 + 4 + 1
    assert h.grouped("Style checks") and h.grouped("Novellas ▾") and not h.grouped("More")
