"""6.2: marks become notes. No model, no speech engine: the marks are made
through the 6.1 store, and Suggestions is replaced by a fake."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import chapter_stages as cst
from src.ai import readiness as rd
from src.data import companion_state, listen_marks
from src.models.project import Chapter, Manuscript, WriterProject

TEXT = ("The storm broke at dusk. Mara ran to the pier.\n"
        "Dr. Voss waited there. Nobody slept.\n")
HEARD = "Mara ran to the pier."


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))
    from src.ui import companion_panel, notify
    monkeypatch.setattr(companion_panel, "_companion_ai_enabled", lambda: False)
    for name in ("empty", "notice", "done"):
        monkeypatch.setattr(notify, name, lambda *a, **k: None)
    from src.utils.proofing import LanguageToolEngine
    monkeypatch.setattr(LanguageToolEngine, "ensure_started", lambda self: False)


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _project(tmp_path):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    ch = Chapter(id="c1", number=1, title="Harbor", folder_root=p.manuscript.folder_root)
    ch.content = TEXT
    p.manuscript.chapters.append(ch)
    return p


def _mark(p, words=HEARD):
    at = TEXT.index(words)
    m = listen_marks.new_mark(words, at, at + len(words), TEXT.count("\n", 0, at))
    listen_marks.add(p, "c1", m)
    return m


def wait_tasks(app):
    from src.ui import background, companion_panel
    for _ in range(20):
        for t in list(companion_panel._RUNNING):
            t.wait(10000)
        background.wait_all(10000)
        app.processEvents()
        if not companion_panel._RUNNING:
            return


def chapter_editor(app, project):
    from src.ui.manuscript_editor import ChapterEditor
    ed = ChapterEditor(project.manuscript.chapters[0], project=project)
    ed.resize(1100, 700)
    ed.show()
    app.processEvents()
    return ed


def _heard(ed):
    return [n for n in ed.companion.panel.notes if n.kind == "heard"]


def _fake_suggestions(ed, monkeypatch, replacement="Mara sprinted for the pier."):
    asked = []

    def fake(start, end, focus="", selection=None):
        asked.append((ed.editor.toPlainText()[start:end], focus))
        return ed._replace_span(ed.editor.toPlainText(), start, end, replacement, "Suggestions")
    monkeypatch.setattr(ed, "suggest_for_span", fake)
    return asked


# ── Without Qt ──────────────────────────────────────────────────────

def test_a_mark_is_a_heard_note_and_a_line_stage_entry(tmp_path):
    from src.ui import heard_notes
    p = _project(tmp_path)
    m = _mark(p)
    notes = heard_notes.notes_for(p, "c1", TEXT)
    assert len(notes) == 1 and notes[0].kind == "heard" and notes[0].excerpt == HEARD
    assert notes[0].paragraph == 0 and HEARD in notes[0].text
    assert notes[0].key == f"heard:{m['id']}"
    entries = heard_notes.entries_for(p, "c1", TEXT)
    assert [(e.check, e.stage) for e in entries] == [("heard", "line")]
    assert entries[0].item.text == HEARD and entries[0].item.suggestions == []
    # Moved text: found again. Changed text: still a note, not in the queue.
    moved = "A new line.\n" + TEXT
    assert heard_notes.notes_for(p, "c1", moved)[0].paragraph == 1
    changed = TEXT.replace("ran to", "walked to")
    notes = heard_notes.notes_for(p, "c1", changed)
    assert len(notes) == 1 and listen_marks.CHANGED_LABEL in notes[0].text
    assert heard_notes.entries_for(p, "c1", changed) == []
    assert listen_marks.marks(p, "c1")                     # kept


def test_no_marks_means_nothing_and_nothing_is_written(tmp_path):
    from src.ui import heard_notes
    p = _project(tmp_path)
    assert heard_notes.notes_for(p, "c1", TEXT) == []
    assert heard_notes.entries_for(p, "c1", TEXT) == []
    assert not os.path.exists(companion_state.state_path(p))


# ── In the Companion ────────────────────────────────────────────────

def test_the_mark_is_in_the_notes_and_in_the_queue_at_the_line_stage(app, tmp_path):
    p = _project(tmp_path)
    cst.set_stage(p, None, ["c1"], "line")
    _mark(p)
    ed = chapter_editor(app, p)
    heard = _heard(ed)
    assert len(heard) == 1
    assert ed.companion.panel.notes_list.item(
        ed.companion.panel.notes.index(heard[0])).text().startswith("👂")
    queue = ed.companion.queue
    queue.find()
    wait_tasks(app)
    marks = [e for e in queue.entries if e.check == "heard"]
    assert len(marks) == 1 and marks[0].stage == "line" and marks[0].item.text == HEARD


def test_at_another_stage_it_stays_a_note_only(app, tmp_path):
    p = _project(tmp_path)
    cst.set_stage(p, None, ["c1"], "copyedit")
    _mark(p)
    ed = chapter_editor(app, p)
    ed.companion.queue.find()
    wait_tasks(app)
    assert _heard(ed)
    assert not [e for e in ed.companion.queue.entries if e.check == "heard"]


def test_suggest_fix_on_the_note_fixes_it_and_it_does_not_come_back(app, tmp_path, monkeypatch):
    p = _project(tmp_path)
    _mark(p)
    ed = chapter_editor(app, p)
    asked = _fake_suggestions(ed, monkeypatch)
    panel = ed.companion.panel
    panel.notes_list.setCurrentRow(panel.notes.index(_heard(ed)[0]))
    panel._fix_note()
    assert asked and asked[0][0] == HEARD and "read aloud" in asked[0][1]
    assert "Mara sprinted for the pier." in ed.editor.toPlainText()
    assert listen_marks.marks(p, "c1") == [] and not _heard(ed)
    again = chapter_editor(app, p)                       # after a restart
    assert not _heard(again)


def test_suggest_fix_turned_down_keeps_the_mark(app, tmp_path, monkeypatch):
    p = _project(tmp_path)
    _mark(p)
    ed = chapter_editor(app, p)
    monkeypatch.setattr(ed, "suggest_for_span", lambda *a, **k: False)
    panel = ed.companion.panel
    panel.notes_list.setCurrentRow(panel.notes.index(_heard(ed)[0]))
    panel._fix_note()
    assert len(listen_marks.marks(p, "c1")) == 1 and _heard(ed)


def test_dismiss_clears_the_mark_only(app, tmp_path):
    p = _project(tmp_path)
    _mark(p)
    other = _mark(p, "Nobody slept.")
    ed = chapter_editor(app, p)
    panel = ed.companion.panel
    first = next(n for n in _heard(ed) if n.excerpt == HEARD)
    panel.notes_list.setCurrentRow(panel.notes.index(first))
    panel._dismiss_note()
    assert [m["id"] for m in listen_marks.marks(p, "c1")] == [other["id"]]
    assert [n.excerpt for n in _heard(ed)] == ["Nobody slept."]
    assert not any(k.startswith("heard") for k in companion_state.dismissed(p))


def test_a_changed_mark_stays_until_dismissed(app, tmp_path):
    p = _project(tmp_path)
    _mark(p)
    p.manuscript.chapters[0].content = TEXT.replace("ran to", "walked to")
    ed = chapter_editor(app, p)
    heard = _heard(ed)
    assert len(heard) == 1 and listen_marks.CHANGED_LABEL in heard[0].text
    ed.companion.queue.find()
    wait_tasks(app)
    assert not [e for e in ed.companion.queue.entries if e.check == "heard"]
    panel = ed.companion.panel
    panel.notes_list.setCurrentRow(panel.notes.index(heard[0]))
    panel._fix_note()                                    # the text has changed: nothing
    assert len(listen_marks.marks(p, "c1")) == 1
    panel.notes_list.setCurrentRow(panel.notes.index(_heard(ed)[0]))
    panel._dismiss_note()
    assert listen_marks.marks(p, "c1") == []


def _card_on_mark(ed, app):
    queue = ed.companion.queue
    queue.find()
    wait_tasks(app)
    entry = next(e for e in queue.entries if e.check == "heard")
    queue.index = queue.entries.index(entry)
    queue.show()
    return queue, entry


def test_on_the_card_more_options_fixes_it(app, tmp_path, monkeypatch):
    p = _project(tmp_path)
    cst.set_stage(p, None, ["c1"], "line")
    _mark(p)
    ed = chapter_editor(app, p)
    queue, _entry = _card_on_mark(ed, app)
    card = ed.companion.panel.queue
    assert card.fix is not None and not card.fix.options     # no suggested fix
    assert not card.accept_btn.isEnabled()
    asked = _fake_suggestions(ed, monkeypatch)
    queue.more(card.fix)
    assert asked and asked[0][0] == HEARD
    assert listen_marks.marks(p, "c1") == []
    assert not [e for e in queue.entries if e.check == "heard"] and not _heard(ed)


def test_on_the_card_skip_keeps_it_and_accept_clears_it(app, tmp_path):
    p = _project(tmp_path)
    cst.set_stage(p, None, ["c1"], "line")
    _mark(p)
    ed = chapter_editor(app, p)
    queue, entry = _card_on_mark(ed, app)
    queue.skip()
    assert len(listen_marks.marks(p, "c1")) == 1
    assert any(e.check == "heard" for e in queue.entries)
    queue.index = next(i for i, e in enumerate(queue.entries) if e.check == "heard")
    queue.show()
    card = ed.companion.panel.queue
    card.edit()                                          # ✎ edit the sentence
    card.options.lineEdit().setText("Mara raced to the pier.")
    card._show_option()
    card._accept()
    wait_tasks(app)
    assert "Mara raced to the pier." in ed.editor.toPlainText()
    assert listen_marks.marks(p, "c1") == [] and not _heard(ed)
    assert not [e for e in queue.entries if e.check == "heard"]


def test_not_a_problem_on_the_card_clears_only_this_mark(app, tmp_path):
    from src.data import readiness_state as rs
    p = _project(tmp_path)
    cst.set_stage(p, None, ["c1"], "line")
    _mark(p)
    ed = chapter_editor(app, p)
    queue, entry = _card_on_mark(ed, app)
    queue.dismiss()
    assert listen_marks.marks(p, "c1") == [] and not _heard(ed)
    assert "Mark cleared" in ed.companion.panel.queue.status.text() or \
        ed.companion.panel.queue.fix is None
    assert "heard:" not in json.dumps(rs.load(p).get("dismissed", {}))   # nothing remembered


def test_marks_made_while_listening_show_when_listening_stops(app, tmp_path):
    from src.ui import heard_notes
    p = _project(tmp_path)
    cst.set_stage(p, None, ["c1"], "line")
    ed = chapter_editor(app, p)
    ed.companion.queue.find()
    wait_tasks(app)
    assert not _heard(ed)
    _mark(p)
    heard_notes.refresh(ed)
    assert len(_heard(ed)) == 1
    assert any(e.check == "heard" for e in ed.companion.queue.entries)


def test_other_companion_state_is_kept(tmp_path):
    from src.ui import heard_notes
    p = _project(tmp_path)
    data = companion_state.load(p)
    data["something_else"] = {"kept": True}
    companion_state.save(p, data)
    m = _mark(p)
    note = heard_notes.notes_for(p, "c1", TEXT)[0]

    class CC:
        project, chapter, queue = p, p.manuscript.chapters[0], None
        def _show_notes(self): pass
    heard_notes.note_cleared(CC(), note)
    assert listen_marks.marks(p, "c1") == []
    saved = json.load(open(companion_state.state_path(p), encoding="utf-8"))
    assert saved["something_else"] == {"kept": True}
    assert m["id"] not in json.dumps(saved)


def test_with_a_model_the_card_offers_rewrites_in_the_writer_s_voice(app, tmp_path, monkeypatch):
    """The model tier, with a fake: the card asks for rewrites of the
    marked sentence as for any finding (no real model is called)."""
    from src.ai import companion
    from src.ui import companion_panel
    p = _project(tmp_path)
    cst.set_stage(p, None, ["c1"], "line")
    _mark(p)
    ed = chapter_editor(app, p)
    monkeypatch.setattr(companion_panel, "_companion_ai_enabled", lambda: True)
    monkeypatch.setattr(ed.companion, "_llm", lambda: object())
    asked = []

    def fake_options(llm, project, chapter, text, fix, voice=None, compact=False):
        asked.append(fix.text)
        return [companion.FixOption("Mara raced for the pier.", "Livelier.", by_ai=True)]
    monkeypatch.setattr(companion, "suggest_fix_options", fake_options)
    import src.ai.chapter_analysis_agent as caa
    monkeypatch.setattr(caa, "is_local_llm", lambda llm: False)
    _card_on_mark(ed, app)
    wait_tasks(app)
    card = ed.companion.panel.queue
    assert asked and "Marked while listening" in asked[0]
    assert card.fix.options and card.option_text() == "Mara raced for the pier."
