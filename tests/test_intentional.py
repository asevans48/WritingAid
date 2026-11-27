"""4.1: "This is intentional" — a quirk becomes a rule of the book and is
never flagged again (any chapter, after a restart); taking it back takes
back both."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import editor_pass
from src.ai import fix_queue
from src.ai import intentional
from src.ai import readiness as rd
from src.data import readiness_state as rs
from src.models.project import Chapter, Manuscript, WriterProject
from src.utils.editor_flags import CheckMode

ONE = "She walked very quickly to the door. Teh lamp was low.\n"
TWO = "It was very late. The tide was very high.\n"


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))
    from src.ui import companion_panel
    monkeypatch.setattr(companion_panel, "_companion_ai_enabled", lambda: False)


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _project(tmp_path, name="Book"):
    p = WriterProject(name=name, manuscript=Manuscript(title=name))
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    p.project_path = str(folder / f"{name}.writerproj")
    for n, text in ((1, ONE), (2, TWO)):
        ch = Chapter(id=f"c{n}", number=n, title=f"Ch {n}", folder_root=p.manuscript.folder_root)
        ch.content = text
        p.manuscript.chapters.append(ch)
    return p


def _report_keys(p, cid):
    ch = next(c for c in p.manuscript.chapters if c.id == cid)
    return {i.key for r in rd.chapter_report(p, ch).results.values() for i in r.items
            if not i.dismissed}


def _editor(app, p, index=0):
    from src.ui.manuscript_editor import ChapterEditor
    ed = ChapterEditor(p.manuscript.chapters[index], project=p)
    ed.resize(1100, 700)
    ed.show()
    ed.editor.set_project_vocabulary(p)
    ed.editor.writing_highlighter.set_style_mode(CheckMode.REALTIME)
    ed.editor.do_initial_check()
    app.processEvents()
    return ed


def wait_tasks(app):
    """Let the Companion's background work finish (as test_next_fixes does),
    so no task outlives its editor."""
    from src.ui import background, companion_panel
    for _ in range(20):
        for t in list(companion_panel._RUNNING):
            t.wait(10000)
        background.wait_all(10000)
        app.processEvents()
        if not companion_panel._RUNNING:
            return


def _close(app, *eds):
    wait_tasks(app)
    for ed in eds:
        ed.close()
    wait_tasks(app)


def _flag_words(ed):
    hl = ed.editor.writing_highlighter
    out = []
    block = ed.editor.document().begin()
    while block.isValid():
        errors, _ = hl.paragraph_flags(block.text(), block.blockNumber(), block.position())
        out += [(e.error_type.value, getattr(e, "style_kind", ""), e.word.lower()) for e in errors]
        block = block.next()
    return out


def _menu_at(ed, word, monkeypatch):
    from PyQt6.QtGui import QTextCursor
    from PyQt6.QtWidgets import QMenu
    from src.ui import write_menu
    text = ed.editor.toPlainText()
    c = QTextCursor(ed.editor.document())
    c.setPosition(text.index(word) + 1)
    ed.editor.setTextCursor(c)
    shown = {}
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: shown.setdefault("menu", self))
    write_menu.show(ed, ed.editor.cursorRect(c).center())
    return shown["menu"]


def _action(menu, label):
    return next((a for a in menu.actions() if a.text() == label), None)


# ── The store, without Qt ───────────────────────────────────────────

def test_mark_dismisses_the_pattern_everywhere_and_adds_a_line_take_back_removes_both(tmp_path):
    p = _project(tmp_path)
    other = _project(tmp_path, "Other")
    assert "intensifier:very" in _report_keys(p, "c1") and "intensifier:very" in _report_keys(p, "c2")
    saved, rule = intentional.mark(p, "intensifier:very", "very", "Weak intensifier",
                                   "Weak intensifiers", "Ch 1", category="style", word="very")
    assert saved and rule is not None and "very" in rule.text and rule.source == "intended"
    assert rule in p.style_sheet
    for cid in ("c1", "c2"):                                     # every chapter
        assert "intensifier:very" not in _report_keys(p, cid)
    stored = rs.load(p)["dismissed"]["intensifier:very"]         # on disk: lasts a restart
    assert stored["as"] == intentional.INTENDED and stored["rule"] == rule.id
    assert "intensifier:very" in intentional.intended_keys(p)
    assert any(d["key"] == "intensifier:very" for d in editor_pass.intended(p))  # in the brief
    assert "intensifier:very" in _report_keys(other, "c2")       # another project: no effect
    saved, gone = intentional.unmark(p, "intensifier:very")
    assert saved and gone == rule.id and rule not in p.style_sheet
    assert "intensifier:very" in _report_keys(p, "c2")
    assert "intensifier:very" not in intentional.intended_keys(p)


def test_spelling_and_repeated_words_are_allowed_and_a_writer_s_own_rule_is_kept(tmp_path):
    from src.ai import style_sheet as ss
    p = _project(tmp_path)
    _, rule = intentional.mark(p, "spelling:teh", "Teh", "", "Spelling", category="spelling",
                               word="Teh")
    assert rule.kind == "allow" and rule.subject == "teh"
    own = ss.add(p, "allow vethari")
    _, again = intentional.mark(p, "spelling:vethari", "vethari", category="spelling",
                                word="vethari")
    assert again is None                                   # already there: nothing linked
    intentional.unmark(p, "spelling:vethari")
    assert own in p.style_sheet                            # the writer's own rule stays


def test_deleting_the_line_flags_it_again_and_rewording_keeps_it(tmp_path):
    p = _project(tmp_path)
    _, rule = intentional.mark(p, "intensifier:very", "very", label="Weak intensifiers",
                               category="style", word="very")
    assert intentional.reword(p, rule.id, "My narrator says very; leave it.").text == \
        "My narrator says very; leave it."
    assert "intensifier:very" in intentional.intended_keys(p)    # rewording changes no rule
    assert intentional.rule_removed(p, rule.id)
    assert "intensifier:very" not in rs.load(p).get("dismissed", {})


def test_an_older_readiness_file_and_project_open_and_an_older_reader_still_reads(tmp_path):
    p = _project(tmp_path)
    path = rs.readiness_path(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written before 4.1: a Critique "intended" without "as", and a 3.3 "not a problem".
    path.write_text(json.dumps({"format_version": 1, "manuscripts": {}, "dismissed": {
        "pov_slip:she knew": {"text": "she knew", "reason": "r", "label": "POV", "chapter": "Ch 1",
                              "at": "2026-11-01"},
        "intensifier:very": {"text": "very", "reason": "r", "label": "W", "chapter": "",
                             "at": "2026-11-01", "as": "not a problem"}}}), encoding="utf-8")
    # Both hide the underline (the writer, 24 Nov: Not a problem hides it too).
    assert intentional.intended_keys(p) == {"pov_slip:she knew", "intensifier:very"}
    intentional.mark(p, "adverb:quickly", "quickly", label="Adverbs", category="style")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["dismissed"]) == {"pov_slip:she knew", "intensifier:very", "adverb:quickly"}
    assert data["dismissed"]["pov_slip:she knew"] == {
        "text": "she knew", "reason": "r", "label": "POV", "chapter": "Ch 1", "at": "2026-11-01"}
    # An older app reads "dismissed" as {key: {...}} and skips "not a problem": still true.
    old_reader = [k for k, v in data["dismissed"].items() if v.get("as") != "not a problem"]
    assert set(old_reader) == {"pov_slip:she knew", "adverb:quickly"}
    # The project file: the rule is an ordinary StyleRule (no new field).
    proj = tmp_path / "Book" / "Book.writerproj"
    p.save_project(str(proj))
    back = WriterProject.load_project(str(proj))
    assert [r.text for r in back.style_sheet] == [r.text for r in p.style_sheet]
    assert back.manuscript.chapters[0].content == ONE
    assert "adverb:quickly" in intentional.intended_keys(back)       # after a restart


def test_not_a_problem_still_writes_what_it_wrote(tmp_path):
    p = _project(tmp_path)
    item = rd.Item(start=0, end=4, text="very", reason="r", kind="intensifier",
                   key="intensifier:very")
    entry = fix_queue.Entry("intensifiers", "Weak intensifiers", "line", "polish", item)
    assert fix_queue.dismiss(p, entry, "Ch 1")
    stored = rs.load(p)["dismissed"]["intensifier:very"]
    assert set(stored) == {"text", "reason", "label", "chapter", "at", "as"}
    assert stored["as"] == fix_queue.NOT_A_PROBLEM and not p.style_sheet
    assert "intensifier:very" in intentional.intended_keys(p)   # hides the underline too
    assert fix_queue.undismiss(p, "intensifier:very")
    assert "intensifier:very" not in rs.load(p)["dismissed"]


# ── In the editor's right-click menu ────────────────────────────────

def test_right_click_this_is_intentional_never_flags_it_again(app, tmp_path, monkeypatch):
    p = _project(tmp_path)
    ed = _editor(app, p)
    assert ("style", "intensifier", "very") in _flag_words(ed)
    menu = _menu_at(ed, "very", monkeypatch)
    action = _action(menu, "📌 This is intentional")
    assert action is not None and action.isEnabled()
    messages = []
    ed.editor.style_sheet_changed.connect(messages.append)
    action.trigger()
    app.processEvents()
    assert ("style", "intensifier", "very") not in _flag_words(ed)     # this chapter
    assert any("very" in r.text and r.source == "intended" for r in p.style_sheet)
    assert messages and "style sheet" in messages[0]
    assert "intensifier:very" in rs.load(p)["dismissed"]
    # Another chapter, in a fresh editor (as after a restart): not flagged.
    ed2 = _editor(app, p, 1)
    assert not any(w == "very" for _t, _k, w in _flag_words(ed2))
    assert "intensifier:very" not in _report_keys(p, "c2")
    # The Companion's style sheet lists it.
    assert any("very" in ed.companion.panel.sheet_list.item(i).text()
               for i in range(ed.companion.panel.sheet_list.count()))
    _close(app, ed, ed2)


def test_a_spelling_flag_marked_intentional_is_allowed(app, tmp_path, monkeypatch):
    p = _project(tmp_path)
    ed = _editor(app, p)
    assert ("spelling", "", "teh") in _flag_words(ed)
    _action(_menu_at(ed, "Teh", monkeypatch), "📌 This is intentional").trigger()
    app.processEvents()
    assert ("spelling", "", "teh") not in _flag_words(ed)
    assert any(r.kind == "allow" and r.subject == "teh" for r in p.style_sheet)
    _close(app, ed)


def test_deleting_the_line_in_the_companion_flags_it_again(app, tmp_path, monkeypatch):
    p = _project(tmp_path)
    ed = _editor(app, p)
    _action(_menu_at(ed, "very", monkeypatch), "📌 This is intentional").trigger()
    app.processEvents()
    panel = ed.companion.panel
    panel.refresh_style_sheet()
    row = next(i for i in range(panel.sheet_list.count())
               if "very" in panel.sheet_list.item(i).text())
    panel.sheet_list.setCurrentRow(row)
    from PyQt6.QtWidgets import QMessageBox      # D.14: Delete asks first; answered Yes
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Yes))
    panel._delete_rule()
    app.processEvents()
    assert not p.style_sheet
    assert ("style", "intensifier", "very") in _flag_words(ed)
    _close(app, ed)


# ── The Critique and the next-fix card call the same function ───────

def test_the_critique_s_that_s_intended_adds_the_line_and_take_that_back_removes_it(app, tmp_path):
    from src.ui.scorecard_widget import ScorecardWidget
    p = _project(tmp_path)
    report = rd.book_report(p)
    sc = ScorecardWidget()
    sc.project, sc.report = p, report
    sc._selected = "c1"
    item = next(i for r in report.chapters[0].results.values() for i in r.items
                if i.key == "intensifier:very")
    check = next(n for n, r in report.chapters[0].results.items() if item in r.items)
    sc.issues.intended_requested.emit(item, check, True)
    assert rs.load(p)["dismissed"]["intensifier:very"]["as"] == "intended"
    assert any("very" in r.text for r in p.style_sheet)
    assert "style sheet" in sc.status_label.text()
    sc.issues.intended_requested.emit(item, check, False)            # take that back
    assert "intensifier:very" not in rs.load(p).get("dismissed", {})
    assert not p.style_sheet


def test_the_next_fix_card_offers_it_after_not_a_problem(app, tmp_path):
    p = _project(tmp_path)
    ed = _editor(app, p)
    queue = ed.companion.queue
    queue.find()
    wait_tasks(app)
    queue.index = next(n for n, e in enumerate(queue.entries) if e.item.key == "intensifier:very")
    queue.show()
    queue.dismiss()
    assert "It's intentional" in ed.companion.panel.queue.status.text()
    ed.companion.panel.queue.status.linkActivated.emit("intended")
    stored = rs.load(p)["dismissed"]["intensifier:very"]
    assert stored["as"] == "intended" and stored.get("rule")
    assert any("very" in r.text for r in p.style_sheet)
    queue.undo_dismiss()                                             # takes back both
    wait_tasks(app)
    assert "intensifier:very" not in rs.load(p).get("dismissed", {}) and not p.style_sheet
    _close(app, ed)


def test_the_brief_lists_a_quirk_once(tmp_path):
    p = _project(tmp_path)
    from src.ai import style_sheet as ss
    ss.add(p, "Dialect in Mara's speech is on purpose")
    intentional.mark(p, "intensifier:very", "very", label="Weak intensifiers",
                     category="style", word="very")
    text = editor_pass.brief(p, None, rd.book_report(p))
    choices = text.split("## Deliberate choices")[1].split("## Style sheet")[0]
    assert "- Dialect in Mara's speech is on purpose" in choices     # notes no longer blank
    assert choices.count("very") == 1                                # as "Intended", not twice
