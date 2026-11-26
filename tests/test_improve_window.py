"""D.2b One Improve window: Suggestions, Critique and Expand in one window,
behind a trial switch, with the old windows one tick away.

Every test uses a scratch HOME (conftest), temporary stores, and fake
models; no real model is ever loaded."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))     # test_project_compat

from src.ai import passage_critique as pc
from src.models.project import Chapter, Character, WriterProject

ROOT = Path(__file__).resolve().parent.parent

PASSAGE = ("The room was almost too dark to see. She almost fell on the last stair. "
           "The attic was big and full of things.")
TEXT = "Mara climbed to the attic. " + PASSAGE + " Voss lit the lamp."

CRITIQUE = ("WHAT WORKS:\n- Quick.\n\nWHAT DOESN'T WORK:\n- The dark is told.\n\n"
            "SUGGESTION 1:\nShe climbed into the dark attic and nearly fell on the last "
            "stair.\nWHY: a\n\nSUGGESTION 2:\nThe attic was dark, and she almost fell on the "
            "last stair.\nWHY: b\n\nSUGGESTION 3:\nShe stumbled on the last stair of the dark "
            "attic.\nWHY: c")

REVIEW = """**STATEMENT [1]:** "The room was almost too dark to see."
VERDICT: overly descriptive
WHY: "Almost too dark" tells; the dark should cost her something.
EXPANSION 1 (show the effect): She felt for the rafters with both hands, blind past her own wrists.

STATEMENT [2]: She almost fell on the last stair.
VERDICT: fine — it's an action
WHY: The near fall is an event.

STATEMENT [3]: The attic was big and full of things.
VERDICT: Overly descriptive
WHY: Vague summary.
EXPANSION 1 (sensory detail): Trunks stood shoulder to shoulder under the eaves.
"""


class FakeLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.prompts.append(prompt)
        if not self.replies:
            raise RuntimeError("no reply")
        return self.replies.pop(0)


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
def merged():
    from src.ui import improve
    improve.set_merged(True)
    return improve


def span():
    s = TEXT.index(PASSAGE)
    return s, s + len(PASSAGE)


def workers(llm=None, review_llm=None, log=None):
    """Fake-model workers that run at once, counting how often each runs."""
    from src.ui.overdescription_panel import MoreWorker, ReviewWorker
    from src.ui.passage_critique_dialog import SuggestionWorker
    log = log if log is not None else []

    class Suggest(SuggestionWorker):
        def __init__(self, *a):
            super().__init__(*a, llm_factory=lambda: (llm, "" if llm else "AI features are "
                                                       "turned off."),
                             search_factory=lambda p: None)

        def start(self):
            log.append(("suggest", self.review))
            self.run()

    class Review(ReviewWorker):
        def __init__(self, *a):
            the = review_llm
            super().__init__(*a, llm_factory=lambda: (the, "" if the else "AI is off"))

        def start(self):
            log.append(("review",))
            self.run()

    class More(MoreWorker):
        def start(self):
            log.append(("more",))
            self.run()

    return dict(suggestion_worker=Suggest, review_worker=Review, more_worker=More), log


def window(project, chapter, tab="suggestions", llm=None, review_llm=None, log=None, **kw):
    from src.ui.improve_window import ImproveWindow
    factories, log = workers(llm, review_llm, log)
    s, e = span()
    win = ImproveWindow(TEXT, s, e, project, chapter, tab=tab, **factories, **kw)
    return win, log


# ── The trial switch ───────────────────────────────────────────────────

def test_the_switch_starts_on_in_the_app():
    """Shipped as decision 16 says (conftest turns it off for older tests)."""
    spec = importlib.util.spec_from_file_location("improve_fresh", ROOT / "src/ui/improve.py")
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    assert fresh.STARTS_ON is True
    assert fresh.TABS == ("suggestions", "critique", "rephrase", "expand")


def test_the_switch_missing_unreadable_and_set(monkeypatch):
    from src.ui import improve
    monkeypatch.setattr(improve, "STARTS_ON", True)
    assert improve.merged() is True                       # missing: the starting position
    improve.set_merged(False)
    assert improve.merged() is False
    improve.set_merged(True)
    assert improve.merged() is True
    improve._settings().setValue(improve.SETTING_KEY, "perhaps")
    assert improve.merged() is True                       # unreadable value: the default

    def broken():
        raise OSError("disk gone")
    monkeypatch.setattr(improve, "_settings", broken)
    assert improve.merged() is True


def test_the_settings_option(app):
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    from src.ui import improve
    holder = QWidget()
    option = improve.ImproveOption(QVBoxLayout(holder))
    assert not option.box.isChecked()                     # tests start with it off
    option.box.setChecked(True)
    option.save()
    assert improve.merged()
    assert "Suggestions and Overly descriptive?" in option.box.text()


# ── Every caller lands on the right tab, over the right window ─────────

class Recorder:
    """Stands in for ImproveWindow: records how it was opened, and accepts."""
    opened = []
    reply = "It was dark."
    tool = "suggestions"

    def __init__(self, text, start, end, project, chapter, parent, **kw):
        self.args = dict(text=text, start=start, end=end, project=project, chapter=chapter,
                         parent=parent, **kw)
        Recorder.opened.append(self.args)
        self.replacement, self.span = Recorder.reply, (start, end)
        self.tool = Recorder.tool

    def exec(self):
        from PyQt6.QtWidgets import QDialog
        return QDialog.DialogCode.Accepted


@pytest.fixture
def recorder(monkeypatch):
    import src.ui.improve_window as iw
    Recorder.opened, Recorder.reply, Recorder.tool = [], "It was dark.", "suggestions"
    monkeypatch.setattr(iw, "ImproveWindow", Recorder)
    return Recorder


def select(ed, a, b):
    from PyQt6.QtGui import QTextCursor
    doc = ed.editor.toPlainText()
    c = ed.editor.textCursor()
    c.setPosition(pc.py_to_qt_index(doc, doc.index(a)))
    c.setPosition(pc.py_to_qt_index(doc, doc.index(b) + len(b)), QTextCursor.MoveMode.KeepAnchor)
    ed.editor.setTextCursor(c)


def test_right_click_suggestions_and_expand_open_their_tabs(app, project, chapter, merged,
                                                            recorder):
    from src.ui.manuscript_editor import ChapterEditor
    ed = ChapterEditor(chapter, project=project)
    select(ed, "almost too dark", "almost too dark")
    ed._suggest_for_selection()                           # ✨ Improve this ▸ Suggestions…
    first = recorder.opened[-1]
    assert first["tab"] == "suggestions"
    assert first["text"][first["start"]:first["end"]] == "The room was almost too dark to see."
    assert first["selection"] is not None                 # the "widened" note
    assert first["parent"] is ed.window()                 # over the window the writer is in
    assert "It was dark." in ed.editor.toPlainText()      # through _replace_span

    select(ed, "She almost fell", "She almost fell")
    ed._expand_selection()                                # ✨ Improve this ▸ Overly descriptive?…
    assert recorder.opened[-1]["tab"] == "expand"
    doc = ed.editor.toPlainText()
    i = doc.index("The attic was big")
    ed.expand_statement(i, i + len("The attic was big and full of things."))  # Critique links
    assert recorder.opened[-1]["tab"] == "expand"
    assert ed.suggest_for_span(i, i + 5, focus="make it felt") is True
    assert recorder.opened[-1]["focus"] == "make it felt"


def test_the_companion_opens_suggestions_with_a_focus_and_accept_anywhere_counts(
        app, project, chapter, merged, recorder):
    from src.ai import companion as cp
    from src.ui.manuscript_editor import ChapterEditor
    chapter.content = ("Mara rowed hard toward the pier. The water was almost too dark to see. "
                       "Tobin waited on the steps.")
    ed = ChapterEditor(chapter, project=project)
    ed.resize(1000, 600)
    ed.show()
    recorder.tool = "expand"                              # accepted from another tab
    fix = cp.Fix("Overly descriptive — tells", excerpt="almost too dark", paragraph=0)
    ed.companion.queue.show_fixes([fix], "The three that matter most")
    ed.companion.queue.more(fix)                          # next-fix card's 💡 More options…
    assert recorder.opened[-1]["tab"] == "suggestions"
    assert recorder.opened[-1]["focus"] == "Overly descriptive — tells"
    note = cp.Note("pov", "Head-hop?", 0, "Tobin waited")
    ed.companion.panel.set_notes([note])
    ed.companion.panel.notes_list.setCurrentRow(0)
    ed.companion.panel._fix_note()                        # Notes ▸ 💡 Suggest fix
    assert recorder.opened[-1]["focus"] == "Head-hop?"
    assert ed.companion.panel.notes == []                 # the note is cleared
    from src.ai import overdescription as od
    ed.editor.setPlainText("Fog. It was very, very cold.")
    flag = od.scan(ed.editor.toPlainText())[0]
    ed.companion.expand_flag(flag)                        # Companion ▸ Expand…
    assert recorder.opened[-1]["tab"] == "expand"


def test_the_switch_off_opens_the_old_windows_as_before(app, project, chapter, monkeypatch,
                                                         recorder):
    from PyQt6.QtWidgets import QDialog
    from src.ui import improve
    from src.ui import overdescription_panel as op
    from src.ui import passage_critique_dialog as pd
    from src.ui.manuscript_editor import ChapterEditor
    improve.set_merged(False)
    seen = []

    class Old:
        def __init__(self, text, start, end, *a, **k):
            seen.append((type(self).__name__, text[start:end], k.get("focus", "")))
            self.replacement = "It was dark."

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(pd, "PassageCritiqueDialog", type("PassageCritiqueDialog", (Old,), {}))
    monkeypatch.setattr(op, "ExpandStatementDialog", type("ExpandStatementDialog", (Old,), {}))
    ed = ChapterEditor(chapter, project=project)
    s, e = span()
    i = ed.editor.toPlainText().index("The room")
    assert ed.suggest_for_span(i, i + len("The room was almost too dark to see."), focus="f")
    i = ed.editor.toPlainText().index("She almost")
    assert ed.expand_statement(i, i + len("She almost fell on the last stair."))
    assert [n for n, _, _ in seen] == ["PassageCritiqueDialog", "ExpandStatementDialog"]
    assert recorder.opened == []


# ── Same text, same call (rule 15) ─────────────────────────────────────

def test_accept_goes_through_replace_span_with_the_tools_name(app, project, chapter, merged,
                                                              monkeypatch):
    from src.ui import improve
    from src.ui.improve_window import ImproveWindow
    from src.ui.manuscript_editor import ChapterEditor
    ed = ChapterEditor(chapter, project=project)
    calls = []
    real = ed._replace_span
    monkeypatch.setattr(ed, "_replace_span", lambda *a: calls.append(a) or real(*a))
    factories, _ = workers(FakeLLM(CRITIQUE, REVIEW))

    def made(*a, **k):
        win = ImproveWindow(*a, **k, **factories)
        win.exec = lambda: (win._accept(), win.result())[1]
        return win
    doc = ed.editor.toPlainText()
    s, e = doc.index(PASSAGE), doc.index(PASSAGE) + len(PASSAGE)
    assert improve.open(ed, "suggestions", doc, s, e, window_factory=made)
    assert calls[-1][1:] == (s, e, "She climbed into the dark attic and nearly fell on the last "
                                    "stair.", "Suggestions")
    assert "She climbed into the dark attic" in ed.editor.toPlainText()


def test_expand_alone_accepts_as_overly_descriptive_and_a_changed_chapter_inserts_nothing(
        app, project, chapter, merged, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from src.ui import improve
    from src.ui.improve_window import ImproveWindow
    from src.ui.manuscript_editor import ChapterEditor
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: told.append(a[1]))
    ed = ChapterEditor(chapter, project=project)
    factories, log = workers(None, None)

    def made(*a, **k):
        win = ImproveWindow(*a, **k, **factories)

        def run():
            panel = win.tab_objects["expand"].panel
            panel.flag_list.setCurrentRow(0)
            panel.preview.setPlainText("She could not see her own hands.")
            panel._accept()                               # Apply to passage
            ed.editor.insertPlainText("x")               # the chapter changes meanwhile
            win._accept()
            return win.result()
        win.exec = run
        return win
    doc = ed.editor.toPlainText()
    s, e = doc.index(PASSAGE), doc.index(PASSAGE) + len(PASSAGE)
    assert improve.open(ed, "expand", doc, s, e, window_factory=made) is False
    assert told == ["Overly descriptive"]                 # today's message, its title
    assert "own hands" not in ed.editor.toPlainText()
    assert log == [("review",)]                           # Suggestions never ran


# ── Same rating rows ───────────────────────────────────────────────────

def _rows():
    import sqlite3
    import src.data.rephrase_database as rd
    db = rd.get_rephrase_database()
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


def test_suggestion_ratings_and_accept_write_the_same_rows_as_the_old_window(
        app, project, chapter, monkeypatch):
    import src.data.rephrase_database as rd
    from src.ui.passage_critique_dialog import PassageCritiqueDialog
    monkeypatch.setattr(rd, "is_collection_enabled", lambda: True)
    _rows()
    factories, _ = workers(FakeLLM(CRITIQUE, REVIEW))
    s, e = span()
    old = PassageCritiqueDialog(TEXT, s, e, project, chapter,
                                worker_factory=factories["suggestion_worker"])
    old.suggestion_list.setCurrentRow(1)
    old.rate_buttons["excellent"].click()
    old.suggestion_list.setCurrentRow(2)
    old.rate_buttons["bad"].click()
    old.suggestion_list.setCurrentRow(1)
    old._use_selected()
    before = _rows()
    win, _ = window(project, chapter, llm=FakeLLM(CRITIQUE, REVIEW))
    win.version_list.setCurrentRow(1)
    win.rate_buttons["excellent"].click()
    win.version_list.setCurrentRow(2)
    win.rate_buttons["bad"].click()
    win.version_list.setCurrentRow(1)
    win._accept()
    after = _rows()
    assert before and after == before
    assert win.replacement == old.replacement and win.tool == "suggestions"
    assert {r["style"] for r in after} == {"suggestion"}


def test_applied_expansions_and_avoided_phrases_are_saved_as_before(app, project, chapter,
                                                                    monkeypatch):
    import src.data.rephrase_database as rd
    import src.ai.rewrite_quality as rq
    from src.ui.overdescription_panel import ExpandStatementDialog
    monkeypatch.setattr(rd, "is_collection_enabled", lambda: True)
    avoided = []
    monkeypatch.setattr(rq, "add_avoid_phrase", lambda p: avoided.append(p) or True)
    _rows()
    factories, _ = workers(None, FakeLLM(REVIEW))
    s, e = span()
    old = ExpandStatementDialog(TEXT, s, e, project, chapter,
                                worker_factory=factories["review_worker"],
                                more_factory=factories["more_worker"])
    old.panel.flag_list.setCurrentRow(0)
    old.panel._accept()
    before = _rows()
    win, _ = window(project, chapter, tab="expand", review_llm=FakeLLM(REVIEW))
    panel = win.tab_objects["expand"].panel
    assert panel.accept_btn.text() == "Apply to passage"
    panel.flag_list.setCurrentRow(0)
    panel._accept()
    assert _rows() == before and before[0]["style"] == "expansion"
    assert win.label(win.versions[0]).startswith("Your text, expanded")
    win._avoid_phrase(phrase="blind past")
    assert avoided == ["blind past"] and "blind past" in win.rating_status.text()


def test_an_expand_version_can_be_rated_before_suggestions_ran(app, project, chapter,
                                                               monkeypatch):
    import src.data.rephrase_database as rd
    monkeypatch.setattr(rd, "is_collection_enabled", lambda: True)
    _rows()
    win, log = window(project, chapter, tab="expand", review_llm=FakeLLM(REVIEW))
    panel = win.tab_objects["expand"].panel
    panel.flag_list.setCurrentRow(0)
    panel._accept()
    _rows()                                               # the applied expansion's row
    win.rate_buttons["good"].click()
    rows = _rows()
    assert [(r["style"], r["rating"]) for r in rows] == [("expansion", "good")]
    assert rows[0]["output_text"].startswith("She felt for the rafters")
    win._accept()
    assert win.tool == "expand" and _rows() == []          # Accept adds no row, as before
    assert ("suggest", True) not in log and ("suggest", False) not in log


# ── Models, examples, no model, no wasted calls ───────────────────────

def test_each_tab_uses_its_old_model_and_the_window_builds_none(app, project, chapter,
                                                                 monkeypatch, merged):
    from src.ui import background
    from src.ui import passage_critique_dialog as pd
    from src.ui.improve_window import ImproveWindow
    started = []
    monkeypatch.setattr(background, "start", lambda w: started.append(w) or w)
    import src.ui.improve_tabs as it
    monkeypatch.setattr(it.background, "start", lambda w: started.append(w) or w)
    s, e = span()
    win = ImproveWindow(TEXT, s, e, project, chapter, tab="expand")
    assert type(started[-1]).__name__ == "ReviewWorker"
    assert started[-1].llm_factory is pd._build_llm
    win.select_tab("suggestions")
    assert type(started[-1]).__name__ == "SuggestionWorker"
    assert started[-1].llm_factory is pd._build_llm
    assert started[-1].review is False                    # Expand already reviewing
    assert not hasattr(win, "llm")
    win.reject()


def test_examples_are_asked_for_as_before_and_the_tooltip_says_where_from(app, project, chapter,
                                                                         monkeypatch):
    import src.ai.rewrite_quality as rq
    from src.ui.passage_critique_dialog import PassageCritiqueDialog
    calls = []

    def examples(*a, **k):
        calls.append((a, {key: v for key, v in k.items() if key != "note"}))
        if k.get("note") is not None:
            k["note"]["from"] = "from your voice group “Harbour”"
        return ""
    monkeypatch.setattr(rq, "examples_prompt", examples)
    factories, _ = workers(FakeLLM(CRITIQUE, REVIEW))
    s, e = span()
    PassageCritiqueDialog(TEXT, s, e, project, chapter,
                          worker_factory=factories["suggestion_worker"])
    win, _ = window(project, chapter, llm=FakeLLM(CRITIQUE, REVIEW))
    assert len(calls) == 2 and calls[0] == calls[1]
    assert "Harbour" in win.rate_buttons["good"].toolTip()


def test_with_no_model_suggestions_points_to_the_word_scan(app, project, chapter):
    win, log = window(project, chapter, llm=None)
    assert "Expand" in win.status_label.text() or win.tab_key() == "expand"
    assert win.tab_key() == "expand"                      # flags found: shown, as before
    panel = win.tab_objects["expand"].panel
    assert panel.flag_list.count() >= 1 and "no AI" in panel.status.text()
    assert not panel.more_btn.isEnabled()
    assert "AI features are turned off" in win.tab_objects["critique"].discussion.toPlainText()
    win.select_tab("suggestions")
    assert "Expand" in win.status_label.text()
    assert log == [("suggest", True)]                     # one run; the scan came with it


def test_no_wasted_calls(app, project, chapter):
    win, log = window(project, chapter, tab="expand", llm=FakeLLM(CRITIQUE),
                      review_llm=FakeLLM(REVIEW))
    assert log == [("review",)]
    win.select_tab("critique")                            # the Critique is Suggestions' call
    assert log == [("review",), ("suggest", False)]
    for key in ("suggestions", "expand", "critique", "suggestions"):
        win.select_tab(key)
    assert log == [("review",), ("suggest", False)]
    assert win.tabs.tabText(3).startswith("🔍 Expand (2)")    # fourth, since D.2c
    assert "What works" in win.tab_objects["critique"].discussion.toPlainText()

    win2, log2 = window(project, chapter, llm=FakeLLM(CRITIQUE, REVIEW))
    win2.select_tab("expand")
    assert log2 == [("suggest", True)]                    # its review filled Expand
    assert win2.tab_objects["expand"].panel.flag_list.count() == 2


# ── The window itself ──────────────────────────────────────────────────

def test_tabs_in_the_writers_order_with_the_expand_tooltip(app, project, chapter):
    win, _ = window(project, chapter, llm=FakeLLM(CRITIQUE, REVIEW))
    assert [win.tabs.tabText(i).split(" (")[0] for i in range(win.tabs.count())] == [
        "💡 Suggestions", "📝 Critique", "✨ Rephrase", "🔍 Expand"]     # Rephrase: D.2c
    assert "Overly descriptive?" in win.tabs.tabToolTip(3)
    assert "Ctrl+4" in win.tabs.tabToolTip(3) and "Ctrl+2" in win.tabs.tabToolTip(1)
    assert win.windowTitle().startswith("Improve — The room was")


def test_edits_stay_with_their_version_and_reset_restores(app, project, chapter):
    win, _ = window(project, chapter, llm=FakeLLM(CRITIQUE, REVIEW))
    first = win.versions[0].text
    win.preview_edit.setPlainText("My own words.")
    assert win.edited_badge.isVisibleTo(win) and win.reset_btn.isEnabled()
    assert "✏" in win.version_list.item(0).text()
    win.version_list.setCurrentRow(1)
    assert win.preview_edit.toPlainText() == win.versions[1].text
    win.version_list.setCurrentRow(0)
    assert win.preview_edit.toPlainText() == "My own words."      # no question, nothing lost
    win.reset_btn.click()
    assert win.preview_edit.toPlainText() == first and not win.reset_btn.isEnabled()


def test_talk_it_through_adds_versions_at_the_top(app, project, chapter):
    reply = ("Here is a darker take.\n\nVERSION 1 (darker):\nThe dark swallowed the stair; "
             "she fell.\nWHY: darker")
    win, _ = window(project, chapter, llm=FakeLLM(CRITIQUE, REVIEW, reply))
    talk = win.tab_objects["suggestions"].talk
    assert talk.send_btn.isEnabled()
    talk.input.setText("make it darker")
    talk._send()
    w = win.tab_objects["suggestions"]._chat_worker
    w.wait(5000)
    app.processEvents()
    assert "darker take" in talk.plain_text()
    assert win.versions[0].kind == "revised"
    assert "revised" in win.version_list.item(0).text()


def test_keys(app, project, chapter, monkeypatch):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from src.ai.rephrasing_agent import RephrasingAgent
    from src.ui import rephrase_dialog as rd
    monkeypatch.setattr(rd.RephraseDialog, "_init_agent",      # no model for Rephrase
                        lambda self: setattr(self, "agent", RephrasingAgent()))
    monkeypatch.setattr(rd.RephraseDialog, "_moment_llm", lambda self: None)
    win, log = window(project, chapter, llm=FakeLLM(CRITIQUE, REVIEW, CRITIQUE))
    win.show()
    win.activateWindow()
    app.processEvents()
    QTest.keyClick(win, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert win.tab_key() == "critique"
    QTest.keyClick(win, Qt.Key.Key_4, Qt.KeyboardModifier.ControlModifier)
    assert win.tab_key() == "expand"
    QTest.keyClick(win, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
    assert win.tab_key() == "rephrase"                    # Rephrase joined in D.2c
    QTest.keyClick(win, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    focus = win.tab_objects["suggestions"].focus_edit
    focus.setFocus()
    focus.setText("more dread")
    QTest.keyClick(focus, Qt.Key.Key_Return)              # Return in Focus: Regenerate…
    assert log[-1] == ("suggest", False) and win.result() == 0   # …never Accept
    assert win.isVisible()
    win.preview_edit.setFocus()
    QTest.keyClick(win.preview_edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert win.replacement and win.result() == 1
    win2, _ = window(project, chapter, llm=FakeLLM(CRITIQUE, REVIEW))
    win2.show()
    QTest.keyClick(win2, Qt.Key.Key_Escape)
    assert win2.result() == 0 and win2.replacement is None


def test_fits_a_small_screen_and_keeps_accept_in_view(app, project, chapter):
    from PyQt6.QtGui import QGuiApplication
    win, _ = window(project, chapter, llm=FakeLLM(CRITIQUE, REVIEW))
    avail = QGuiApplication.primaryScreen().availableGeometry()
    assert win.width() <= avail.width() and win.height() <= avail.height()
    for button in (win.accept_btn, win.close_btn):
        assert not win.scroll_area.isAncestorOf(button)  # never scrolled away
    assert win.accept_btn.isDefault()
    # A narrow window: Talk it through is a closed section; wide: a column.
    win.resize(1000, 560)
    win._place_talk()
    assert win.talk_section.isVisibleTo(win) and not win.talk_column.isVisibleTo(win)
    win.resize(1400, 800)
    win._place_talk()
    assert win.talk_column.isVisibleTo(win) and not win.talk_section.isVisibleTo(win)
    assert win.talk_column.isAncestorOf(win.tab_objects["suggestions"].talk)


def test_closing_early_drops_the_late_result(app, project, chapter):
    from src.ui.improve_window import ImproveWindow
    from src.ui.passage_critique_dialog import SuggestionWorker
    held = []

    class Later(SuggestionWorker):
        def __init__(self, *a):
            super().__init__(*a, llm_factory=lambda: (FakeLLM(CRITIQUE, REVIEW), ""),
                             search_factory=lambda p: None)

        def start(self):
            held.append(self)                             # finishes after the window closed
    s, e = span()
    win = ImproveWindow(TEXT, s, e, project, chapter, suggestion_worker=Later)
    win.reject()
    held[0].run()
    app.processEvents()
    assert win.versions == [] and win.replacement is None


def test_one_look_lists_the_new_modules():
    from test_one_look import CLEANED
    for name in ("src/ui/improve.py", "src/ui/improve_window.py", "src/ui/improve_tabs.py"):
        assert name in CLEANED


def test_a_project_from_before_the_piece_opens_and_saves_unchanged(app, merged, recorder):
    """The window stores nothing in the project; an old project opens,
    goes through the Improve window, saves and reopens with every chapter
    file byte-for-byte the same."""
    import shutil
    from test_project_compat import _v1_project_dir
    from src.models.project import WriterProject
    from src.ui.manuscript_editor import ChapterEditor
    d, path = _v1_project_dir()
    files = sorted(d.glob("chapters/*/*.md"))
    before = {f: f.read_bytes() for f in files}
    p = WriterProject.load_project(str(path))
    ed = ChapterEditor(p.manuscript.chapters[0], project=p)
    recorder.opened.clear()

    class No(Recorder):
        def exec(self):
            return 0
    import src.ui.improve_window as iw
    iw.ImproveWindow = No
    doc = ed.editor.toPlainText()
    assert ed.suggest_for_span(0, len(doc)) is False and recorder.opened
    p.save_project(str(path))
    WriterProject.load_project(str(path))
    assert {f: f.read_bytes() for f in files} == before
    shutil.rmtree(d)
