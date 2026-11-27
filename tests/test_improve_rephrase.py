"""D.2c One Improve window: ✨ Rephrase joins as the third tab.

Rephrase is hosted, not rewritten: the tab holds a real ``RephraseDialog``
(``hosted=True``) and forwards picks, edits, ratings and Accept to it. These
tests compare what the old window and the new tab write, row by row, in a
temporary ratings database. Every test uses a scratch HOME (conftest) and
fake models; no real model is ever loaded."""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))

from src.ai import passage_critique as pc
from src.ai.rephrasing_agent import RephraseOption, RephraseResult, RephrasingAgent
from src.models.project import Chapter, Character, WriterProject

PASSAGE = ("The room was almost too dark to see. She almost fell on the last stair. "
           "The attic was big and full of things.")
TEXT = "Mara climbed to the attic. " + PASSAGE + " Voss lit the lamp."
HIGHLIGHT = "almost too dark to see"
OPTIONS = (("It was nearly too dark to see.", "concise"),
           ("Dark pressed in; she could hardly see.", "clearer"),
           ("The darkness was almost complete.", "elaborate"))


def result():
    """Fresh option objects each time, the same words."""
    return RephraseResult(original=HIGHLIGHT, model_used="fake", cost_estimate=0.0,
                          options=[RephraseOption(t, s, "neutral", f"because {s}")
                                   for t, s in OPTIONS])


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def project():
    p = WriterProject(name="Saga")
    p.project_path = "/p/saga.writerproj"
    p.characters = [Character(id="c1", name="Mara", character_type="protagonist")]
    return p


@pytest.fixture
def chapter():
    return Chapter(id="ch", number=1, title="Attic", content=TEXT)


@pytest.fixture
def fake_rephrase(monkeypatch):
    """RephraseDialog with no model: no agent built from settings, no scene
    summary model, no project search."""
    from src.ui import rephrase_dialog as rd
    made = []
    monkeypatch.setattr(rd.RephraseDialog, "_init_agent",
                        lambda self: setattr(self, "agent", RephrasingAgent(project=self.project)))
    monkeypatch.setattr(rd.RephraseDialog, "_moment_llm", lambda self: None)
    monkeypatch.setattr(rd.RephraseDialog, "_get_rag_worldbuilding", lambda self: "")
    monkeypatch.setattr(rd.RephraseDialog, "_get_rag_for_refinement", lambda self, r: "")
    real_init = rd.RephraseDialog.__init__

    def init(self, *a, **k):
        made.append((a, k))
        real_init(self, *a, **k)
    monkeypatch.setattr(rd.RephraseDialog, "__init__", init)
    return made


@pytest.fixture
def merged():
    """Every way in opens the Improve window (the trial switch went in D.11)."""
    from src.ui import improve
    return improve


@pytest.fixture
def collect(monkeypatch):
    import src.data.rephrase_database as rdb
    monkeypatch.setattr(rdb, "is_collection_enabled", lambda: True)
    _rows()
    return _rows


def _rows():
    import sqlite3
    import src.data.rephrase_database as rdb
    db = rdb.get_rephrase_database()
    con = sqlite3.connect(str(db.db_path))
    con.row_factory = sqlite3.Row
    cols = [r[1] for r in con.execute("PRAGMA table_info(rephrases)")]
    skip = {"id", "timestamp", "created_at", "updated_at"}
    rows = [{c: r[c] for c in cols if c not in skip}
            for r in con.execute("SELECT * FROM rephrases ORDER BY id")]
    con.execute("DELETE FROM rephrases")
    con.commit()
    con.close()
    return rows


def select(ed, a, b=None):
    from PyQt6.QtGui import QTextCursor
    b = b or a
    doc = ed.editor.toPlainText()
    c = ed.editor.textCursor()
    c.setPosition(pc.py_to_qt_index(doc, doc.index(a)))
    c.setPosition(pc.py_to_qt_index(doc, doc.index(b) + len(b)), QTextCursor.MoveMode.KeepAnchor)
    ed.editor.setTextCursor(c)


def fire(dlg):
    """The 0.9 s delayed save, now."""
    if dlg._save_timer.isActive():
        dlg._save_timer.stop()
        dlg._flush_pending_rating_save()


def rephrase_rows(win):
    return [i for i, v in enumerate(win.versions) if v.source == "rephrase"]


# ── The tab, its place and its keys ────────────────────────────────────

def _window(project, chapter, tab="rephrase", **kw):
    """The window over TEXT, the highlight widened to its sentence, with
    fake-model workers for the other tabs (no model is ever built)."""
    from src.ui.improve_window import ImproveWindow
    from test_improve_window import workers
    sel = (TEXT.index(HIGHLIGHT), TEXT.index(HIGHLIGHT) + len(HIGHLIGHT))
    start, end = pc.expand_to_sentences(TEXT, *sel)
    if not kw:
        kw, _ = workers(None, None)
    return ImproveWindow(TEXT, start, end, project, chapter, tab=tab, selection=sel, **kw)


def test_rephrase_is_the_third_tab_with_ctrl_3(app, project, chapter, fake_rephrase):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    win = _window(project, chapter, tab="expand")
    assert [win.tabs.tabText(i).split(" (")[0] for i in range(win.tabs.count())] == [
        "💡 Suggestions", "📝 Critique", "✨ Rephrase", "🔍 Expand"]
    assert "Ctrl+3" in win.tabs.tabToolTip(2) and "AI Text Rephrasing" in win.tabs.tabToolTip(2)
    assert fake_rephrase == []                            # nothing of Rephrase runs until shown
    win.show()
    win.activateWindow()
    app.processEvents()
    QTest.keyClick(win, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
    assert win.tab_key() == "rephrase" and len(fake_rephrase) == 1
    win.select_tab("expand")
    win.select_tab("rephrase")
    assert len(fake_rephrase) == 1                        # built once
    win.reject()


def test_the_options_sit_behind_change_options_with_a_summary(app, project, chapter,
                                                              fake_rephrase):
    win = _window(project, chapter)
    tab = win.tab_objects["rephrase"]
    d = tab.dlg
    assert d.hosted is True and not d.isVisible()
    assert not tab.options.is_open()                      # closed by default
    for w in (d.genre_combo, d.pov_combo, d.char_list, d.custom_tone_cb, d.cloud_radio,
              d.local_radio, *d.style_checkboxes.values(), *d.tone_checkboxes.values()):
        assert tab.options.isAncestorOf(w)                # all 25 options are there
    assert tab.widget.isAncestorOf(d.scene_desc_edit) and tab.widget.isAncestorOf(d.generate_btn)
    assert tab.widget.isAncestorOf(d.scene_refresh_btn)
    assert tab.summary.text().startswith("Concise · Clearer · Elaborate · Formal")
    assert "Tone: Neutral" in tab.summary.text() and "POV: keep" in tab.summary.text()
    d.tone_checkboxes[list(d.tone_checkboxes)[1]].setChecked(True)   # Dark
    d.pov_combo.setCurrentIndex(1)
    assert "Tone: Dark" in tab.summary.text() and "First person" in tab.summary.text()
    tab.options.header.click()                            # ▸ Change options, remembered
    win.reject()
    win2 = _window(project, chapter)
    assert win2.tab_objects["rephrase"].options.is_open()
    assert "exactly what you highlighted" in win2.tab_objects["rephrase"].widget.findChildren(
        type(tab.summary))[0].text()
    win2.reject()


def test_options_become_versions_labelled_rephrase_and_diffed_against_the_highlight(
        app, project, chapter, fake_rephrase):
    win = _window(project, chapter)
    d = win.tab_objects["rephrase"].dlg
    assert win.tab_objects["rephrase"].talk.isAncestorOf(d.chat)   # its own Talk it through
    assert not d.chat.send_btn.isEnabled()                # until options exist
    d._on_generation_complete(result())
    assert [win.label(v).split("\n")[0] for v in win.versions] == [
        "Rephrase · concise", "Rephrase · clearer", "Rephrase · elaborate"]
    assert win.why_label.text().startswith("<b>Why:</b> Style: concise | Tone: neutral")
    changes = win.changes_view.toPlainText()
    assert "nearly" in changes and "The room was" not in changes   # against your highlight
    assert d.chat.send_btn.isEnabled()
    win.reject()


def test_edits_stay_with_their_version_and_no_question_is_asked(app, project, chapter,
                                                                 fake_rephrase, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a) or
                        QMessageBox.StandardButton.Cancel)
    win = _window(project, chapter)
    d = win.tab_objects["rephrase"].dlg
    d._on_generation_complete(result())
    win.preview_edit.setPlainText("My own dark line.")
    assert d.preview_edit.toPlainText() == "My own dark line." and d._preview_dirty
    win.version_list.setCurrentRow(1)
    assert win.preview_edit.toPlainText() == OPTIONS[1][0] and d.options_list.currentRow() == 1
    win.version_list.setCurrentRow(0)
    assert win.preview_edit.toPlainText() == "My own dark line."   # kept with its version
    assert d.preview_edit.toPlainText() == "My own dark line." and d._preview_dirty
    assert asked == []                                    # no "Discard your edit?"
    win.reset_btn.click()
    assert d.preview_edit.toPlainText() == OPTIONS[0][0] and not d._preview_dirty
    win.reject()


def test_talk_it_through_adds_rephrase_versions_at_the_top_keeping_edits(
        app, project, chapter, fake_rephrase, monkeypatch):
    from src.ui import rephrase_dialog as rd

    class Reply:
        def generate_text(self, *a, **k):
            return "Darker.\n\nVERSION 1 (darker):\nThe dark took the room whole.\nWHY: darker"
    monkeypatch.setattr(rd.RephraseDialog, "_moment_llm", lambda self: Reply())
    win = _window(project, chapter)
    d = win.tab_objects["rephrase"].dlg
    d._on_generation_complete(result())
    win.version_list.setCurrentRow(2)
    win.preview_edit.setPlainText("Kept edit.")
    d.chat.message_sent.emit("make it darker")
    d._chat_worker.wait(5000)
    app.processEvents()
    assert win.label(win.versions[0]).startswith("Rephrase · revised: darker")
    assert win.versions[0].text == "The dark took the room whole."
    assert [v for v in win.versions if v.edited == "Kept edit."]   # nothing lost
    assert "Darker." in d.chat.plain_text()
    win.reject()


# ── Every Rephrase caller opens the window on Rephrase ─────────────────

class Opened:
    """Stands in for ImproveWindow: records how it was opened."""
    seen = []

    def __init__(self, text, start, end, project, chapter, parent, **kw):
        Opened.seen.append(dict(text=text, start=start, end=end, project=project,
                                chapter=chapter, parent=parent, **kw))
        self.replacement = None

    def exec(self):
        return 0


@pytest.fixture
def opened(monkeypatch):
    import src.ui.improve_window as iw
    Opened.seen = []
    monkeypatch.setattr(iw, "ImproveWindow", Opened)
    return Opened.seen


def test_ctrl_r_the_toolbar_and_the_right_click_open_rephrase(app, project, chapter, merged,
                                                              opened):
    from src.ui.manuscript_editor import ChapterEditor
    ed = ChapterEditor(chapter, project=project)
    select(ed, HIGHLIGHT)
    ed._rephrase_selection()                    # ✨, Ctrl+R and right-click ✨ Rephrase with AI…
    got = opened[-1]
    assert got["tab"] == "rephrase" and got["parent"] is ed.window()
    assert got["text"][got["start"]:got["end"]] == "The room was almost too dark to see."
    s = TEXT.index(HIGHLIGHT)
    assert got["selection"] == (s, s + len(HIGHLIGHT))
    args = got["rephrase"]
    assert args["text"] == HIGHLIGHT and args["chapter"] is chapter
    assert args["surrounding_context"] == (TEXT[:s], TEXT[s + len(HIGHLIGHT):][:500])
    assert args["text_before"] == TEXT[:s] and args["chapter_content"] == TEXT
    assert args["instruction"] == ""
    # The shortcut and the ✨ button are still the same action.
    from PyQt6.QtGui import QKeySequence
    from PyQt6.QtWidgets import QToolBar
    acts = [a for tb in ed.findChildren(QToolBar) for a in tb.actions()
            if a.shortcut() == QKeySequence("Ctrl+R")]
    assert len(acts) == 1 and acts[0].text() == "✨"
    acts[0].trigger()
    assert len(opened) == 2 and opened[-1]["tab"] == "rephrase"


def test_a_style_flags_rewrite_opens_rephrase_with_the_hint(app, project, chapter, merged,
                                                            opened):
    """The hover card's ✨ Rewrite with AI and the next-fix card's More
    options on a style flag both send ``style_rewrite_requested``."""
    from src.ui.manuscript_editor import ChapterEditor
    ed = ChapterEditor(chapter, project=project)
    doc = ed.editor.toPlainText()
    i = doc.index("She almost fell")
    ed.editor.style_rewrite_requested.emit(i, i + len("She almost fell on the last stair."),
                                           "Fix the qualifier: “almost”")
    got = opened[-1]
    assert got["tab"] == "rephrase"
    assert got["rephrase"]["instruction"] == "Fix the qualifier: “almost”"
    assert got["rephrase"]["text"] == "She almost fell on the last stair."


def test_a_stored_switch_off_from_before_still_opens_rephrase_in_the_improve_window(
        app, project, chapter, opened):
    """A settings file from before D.11 with the switch off: Ctrl+R opens
    the Improve window on Rephrase, and the stored value is left alone."""
    from src.ui import improve, ui_kit
    from src.ui.manuscript_editor import ChapterEditor
    ui_kit._settings().setValue(improve.SETTING_KEY, "false")
    ed = ChapterEditor(chapter, project=project)
    select(ed, HIGHLIGHT)
    ed._rephrase_selection()
    assert opened[-1]["tab"] == "rephrase" and opened[-1]["rephrase"]["text"] == HIGHLIGHT
    assert ui_kit._settings().value(improve.SETTING_KEY) == "false"


def test_the_draft_windows_rephrase_opens_the_whole_window_and_writes_the_draft(
        app, project, chapter, merged, fake_rephrase, monkeypatch):
    import src.ui.improve_window as iw
    from src.models.project import Manuscript
    from src.ui.draft_editor_window import DraftEditorPanel
    project.manuscript = Manuscript(chapters=[chapter])
    panel = DraftEditorPanel(project)
    panel._current_chapter = chapter
    panel.editor.setPlainText(TEXT)
    panel._set_dirty(False)
    select(panel, HIGHLIGHT)
    seen = {}

    def run(win):
        seen["tabs"] = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        seen["parent"] = win.parent()
        d = win.tab_objects["rephrase"].dlg
        d._on_generation_complete(result())
        win._accept()
        return win.result()
    monkeypatch.setattr(iw.ImproveWindow, "exec", run)
    panel._rephrase_selection()
    assert len(seen["tabs"]) == 4                         # Suggestions and Expand too
    assert seen["parent"] is panel.window()
    assert panel.editor.toPlainText() == TEXT.replace(HIGHLIGHT, OPTIONS[0][0])
    assert panel._dirty
    kw = fake_rephrase[-1][1]
    assert kw["chapter"] is chapter and kw["text_before"] == TEXT[:TEXT.index(HIGHLIGHT)]


# ── Same text, same rows (rule 15, the ratings database) ───────────────

def test_accept_writes_the_same_text_and_the_same_rows_as_the_old_window(
        app, project, chapter, fake_rephrase, collect, monkeypatch):
    """The delayed save with its "edited" mark, a Poor rating then Accept,
    and the "neutral" row for the unedited option: the rows the old window
    wrote (compared column by column in D.2c; the old window's path went in
    D.11, so they are stated here), and the same chapter text."""
    import src.ui.improve_window as iw
    from PyQt6.QtWidgets import QMessageBox
    from src.ui import improve
    from src.ui.manuscript_editor import ChapterEditor
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or
                        QMessageBox.StandardButton.Yes)

    def new(win):
        d = win.tab_objects["rephrase"].dlg
        d._on_generation_complete(result())
        rows = rephrase_rows(win)
        win.version_list.setCurrentRow(rows[0])
        win.rate_buttons["excellent"].click()
        win.preview_edit.setPlainText(OPTIONS[0][0] + " Edited.")
        fire(d)
        win.version_list.setCurrentRow(rows[1])
        win.rate_buttons["poor"].click()
        win.preview_edit.setPlainText("Black as pitch, nearly.")
        win._accept()
        return win.result()

    monkeypatch.setattr(iw.ImproveWindow, "exec", new)
    new_ed = ChapterEditor(Chapter(id="b", number=1, title="B", content=TEXT), project=project)
    select(new_ed, HIGHLIGHT)
    new_ed._rephrase_selection()
    after = collect()
    assert asked == []                                    # the tab asks nothing
    assert [(r["rating"], r["accepted"]) for r in after] == [
        ("excellent", 1), ("poor", 0), ("poor", 1), ("neutral", 0)]
    assert "edited" in after[0]["style"] and after[-1]["output_text"] == OPTIONS[1][0]
    # Each row carries the style of the option rated (option 1, then option 2).
    assert [r["style"] for r in after] == ["concise/neutral | edited", "clearer/neutral | edited",
                                           "clearer/neutral | edited", "clearer/neutral"]
    assert new_ed.editor.toPlainText() == TEXT.replace(HIGHLIGHT, "Black as pitch, nearly.")
    ((new_a, new_k),) = fake_rephrase                    # the old window's arguments, hosted
    assert new_a[0] == HIGHLIGHT and new_a[1] is project and new_k.pop("hosted") is True
    assert new_k.pop("chapter").id == "b"
    i = TEXT.index(HIGHLIGHT)
    j = i + len(HIGHLIGHT)
    assert new_k == dict(surrounding_context=(TEXT[max(0, i - 500):i], TEXT[j:j + 500]),
                         chapter_content=TEXT, instruction="", text_before=TEXT[:i])


def test_an_unrated_accept_and_closing_with_a_rating_waiting_match_the_old_window(
        app, project, chapter, fake_rephrase, collect, monkeypatch):
    import src.ui.improve_window as iw
    from src.ui import improve
    from src.ui.manuscript_editor import ChapterEditor

    def new_accept(win):
        win.tab_objects["rephrase"].dlg._on_generation_complete(result())
        win.version_list.setCurrentRow(rephrase_rows(win)[2])
        win._accept()
        return win.result()

    def new_close(win):
        win.tab_objects["rephrase"].dlg._on_generation_complete(result())
        win.rate_buttons["good"].click()
        win.reject()                                      # saved as it closes
        return win.result()

    rows, texts = {}, {}
    for name, new in (("accept", new_accept), ("close", new_close)):
        monkeypatch.setattr(iw.ImproveWindow, "exec", new)
        ed2 = ChapterEditor(Chapter(id=name, number=1, title="B", content=TEXT), project=project)
        select(ed2, HIGHLIGHT)
        collect()                                         # start from no rows
        ed2._rephrase_selection()
        rows[name] = collect()
        texts[name] = ed2.editor.toPlainText()
    # What the old window wrote (D.2c compared them row by row).
    assert [(r["rating"], r["accepted"]) for r in rows["accept"]] == [("good", 1)]
    assert rows["accept"][0]["output_text"] == OPTIONS[2][0]
    assert texts["accept"] == TEXT.replace(HIGHLIGHT, OPTIONS[2][0])
    assert [(r["rating"], r["accepted"]) for r in rows["close"]] == [("good", 1)]
    assert texts["close"] == TEXT


def test_a_rating_shows_its_delayed_save_in_the_windows_status(app, project, chapter,
                                                               fake_rephrase, collect):
    win = _window(project, chapter)
    d = win.tab_objects["rephrase"].dlg
    d._on_generation_complete(result())
    win.rate_buttons["good"].click()
    assert "after you finish editing" in win.rating_status.text()
    fire(d)
    assert win.rating_status.text() == "✓ Saved as good for training"
    assert collect()[0]["rating"] == "good"
    win.reject()


def test_examples_are_asked_for_as_before_and_the_tooltip_says_where_from(
        app, project, chapter, fake_rephrase, monkeypatch):
    """V.4: the same examples_prompt call (before, after, character_name)."""
    import src.ai.rewrite_quality as rq
    from src.ui import rephrase_dialog as rd
    calls = []

    def examples(*a, **k):
        calls.append((a, {key: v for key, v in k.items() if key != "note"}))
        if k.get("note") is not None:
            k["note"]["from"] = "from your voice group “Harbour”"
        return ""
    monkeypatch.setattr(rq, "examples_prompt", examples)

    class Worker:
        def __init__(self, *a, **kw):
            self.finished = self.error = self

        def connect(self, *_):
            pass

        def start(self):
            pass
    monkeypatch.setattr(rd, "RephraseWorker", Worker)
    s = TEXT.index(HIGHLIGHT)
    e = s + len(HIGHLIGHT)
    old = rd.RephraseDialog(HIGHLIGHT, project, None,
                            surrounding_context=(TEXT[max(0, s - 500):s], TEXT[e:e + 500]),
                            chapter_content=TEXT, chapter=chapter, text_before=TEXT[:s])
    old._generate_options()
    win = _window(project, chapter)
    d = win.tab_objects["rephrase"].dlg
    d._generate_options()
    assert len(calls) == 2 and calls[0] == calls[1]
    assert set(calls[0][1]) >= {"before", "after", "character_name"}
    d._on_generation_complete(result())
    assert "Harbour" in win.rate_buttons["good"].toolTip()
    win.reject()


def test_with_no_model_rephrase_uses_the_python_libraries_and_suggestions_links_to_it(
        app, project, chapter, monkeypatch):
    from src.ui import rephrase_dialog as rd
    from src.config import ai_config

    class Off:
        def get_settings(self):
            return {}

        def is_ai_disabled(self):
            return True
    monkeypatch.setattr(ai_config, "get_ai_config", lambda: Off())
    monkeypatch.setattr(rd.RephraseDialog, "_moment_llm", lambda self: None)
    from test_improve_window import workers
    factories, _ = workers(None, None)
    win = _window(project, chapter, tab="suggestions", **factories)
    assert "Rephrase</a> still works" in win.status_label.text() or win.tab_key() == "expand"
    win.select_tab("suggestions")
    assert "<a href='rephrase'>" in win.status_label.text()
    win.status_label.linkActivated.emit("rephrase")
    assert win.tab_key() == "rephrase"
    d = win.tab_objects["rephrase"].dlg
    assert d.agent.use_python_libraries
    assert "Python libraries" in win.status_label.text()
    assert "Python libraries" in win.tab_objects["rephrase"].summary.text()
    win.reject()


def test_the_window_builds_no_model_for_rephrase(app, project, chapter, fake_rephrase):
    win = _window(project, chapter)
    assert isinstance(win.tab_objects["rephrase"].dlg.agent, RephrasingAgent)
    assert not hasattr(win, "llm") and not hasattr(win.tab_objects["rephrase"], "llm")
    win.reject()


def test_context_shows_the_text_around_the_passage(app, project, chapter, fake_rephrase):
    win = _window(project, chapter)
    assert win.context_link.isVisibleTo(win) or not win.isVisible()
    assert win.context_view.isHidden()
    win._toggle_context()
    assert not win.context_view.isHidden()
    text = win.context_view.toPlainText()
    assert "Mara climbed to the attic." in text and ">>> The room was" in text
    assert "hide context" in win.context_link.text()
    win.reject()


def test_fits_a_small_screen_on_the_rephrase_tab(app, project, chapter, fake_rephrase):
    from PyQt6.QtGui import QGuiApplication
    win = _window(project, chapter)
    avail = QGuiApplication.primaryScreen().availableGeometry()
    assert win.width() <= avail.width() and win.height() <= avail.height()
    d = win.tab_objects["rephrase"].dlg
    assert win.scroll_area.isAncestorOf(d.scene_desc_edit)     # the middle scrolls
    for button in (win.accept_btn, win.close_btn):
        assert not win.scroll_area.isAncestorOf(button)
    line = d.scene_desc_edit.fontMetrics().lineSpacing()
    assert d.scene_desc_edit.maximumHeight() >= line * 4        # follows the text size
    win.reject()


def test_one_look_lists_the_rephrase_tab():
    from test_one_look import CLEANED
    assert "src/ui/improve_rephrase.py" in CLEANED
