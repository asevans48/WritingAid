"""Listen and mark (piece 6.1). A fake speaker throughout: nothing is
spoken, no engine or model is loaded."""

import json

import pytest

from src.data import listen_marks

TEXT = ("The storm broke at dusk. Mara ran to the pier.\n"
        "Dr. Voss waited there. Nobody slept.")
SENTENCES = ["The storm broke at dusk.", "Mara ran to the pier.",
             "Dr. Voss waited there.", "Nobody slept."]


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    """No boxes, no LanguageTool, and the real speaker can never be built."""
    from src.ui import notify, listen_mark
    for name in ("empty", "notice", "done"):
        monkeypatch.setattr(notify, name, lambda *a, **k: None)
    from src.utils.proofing import LanguageToolEngine
    monkeypatch.setattr(LanguageToolEngine, "ensure_started", lambda self: False)

    def _no_real_speaker(*a, **k):
        raise AssertionError("tests must not use the real speech service")
    monkeypatch.setattr(listen_mark, "SystemSpeaker", _no_real_speaker)


class FakeSpeaker:
    def __init__(self, can_pause=True, available=True):
        self.spoken, self.can_pause, self._available = [], can_pause, available
        self.is_speaking = self.paused = False
        self.began = self.ended = 0
        self.stops = 0
        self.error = ""

    def available(self): return self._available
    def begin(self): self.began += 1
    def end(self): self.ended += 1

    def speak(self, text):
        self.spoken.append(text)
        self.is_speaking = True

    def finish(self):           # the engine says the sentence is done
        self.is_speaking = False

    def pause(self):
        if self.can_pause:
            self.paused = True
        return self.can_pause

    def resume(self):
        if self.paused:
            self.paused = False
            return True
        return False

    def stop(self):
        self.stops += 1
        self.is_speaking = False

    def stopped_elsewhere(self): return False


def _project(tmp_path):
    from src.models.project import Chapter, Manuscript, WriterProject
    p = WriterProject(name="Listen", manuscript=Manuscript(title="Listen"))
    ch = Chapter(id="c1", number=1, title="One", folder_root=p.manuscript.folder_root)
    ch.content = TEXT
    p.manuscript.chapters.append(ch)
    p.save_project(str(tmp_path / "Listen.writerproj"))
    return p


_keep = []


def _editor(tmp_path):
    from src.ui.manuscript_editor import ChapterEditor
    p = _project(tmp_path)
    ed = ChapterEditor(p.manuscript.chapters[0], project=p)
    _keep.append(ed)
    return ed


def _advance(session, speaker):
    speaker.finish()
    session._tick()


def _highlighted(ed):
    from src.ui.listen_mark import _MINE, CURRENT_COLOUR
    from PyQt6.QtGui import QColor
    return [s.cursor.selectedText() for s in ed.editor.extraSelections()
            if s.format.property(_MINE)
            and s.format.background().color() == QColor(CURRENT_COLOUR)]


def test_the_highlight_follows_playback(app, tmp_path):
    from src.ui import listen_mark
    ed = _editor(tmp_path)
    sp = FakeSpeaker()
    s = listen_mark.start(ed, speaker=sp)
    assert s is not None and s.total == 4
    assert sp.spoken == SENTENCES[:1]
    assert _highlighted(ed) == [SENTENCES[0]]
    s._tick()                                   # still speaking: stays put
    assert s.index == 0 and len(sp.spoken) == 1
    for i in range(1, 4):
        _advance(s, sp)
        assert sp.spoken[-1] == SENTENCES[i]
        assert _highlighted(ed) == [SENTENCES[i]]
        assert ed.tts_speak_btn.text().startswith(f"⏸ {i + 1}/4")
    _advance(s, sp)                             # the end of the chapter
    assert not s.running and sp.ended == 1
    assert _highlighted(ed) == []
    assert ed.tts_speak_btn.text() == "🗣 Read Aloud"


def test_the_key_marks_the_current_sentence(app, tmp_path):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from src.ui import listen_mark
    ed = _editor(tmp_path)
    sp = FakeSpeaker()
    s = listen_mark.start(ed, speaker=sp)
    _advance(s, sp)                             # "Mara ran to the pier."
    QTest.keyClick(ed.editor, Qt.Key.Key_M)
    stored = listen_marks.marks(ed.project, "c1")
    assert [m["text"] for m in stored] == [SENTENCES[1]]
    m = stored[0]
    assert TEXT[m["start"]:m["end"]] == SENTENCES[1]
    assert m["paragraph"] == 0 and m["source"] == "listen" and m["id"]
    assert "1 marked" in ed.tts_speak_btn.text()
    _advance(s, sp)
    _advance(s, sp)                             # "Nobody slept." (second paragraph)
    assert s.mark() is True
    assert listen_marks.marks(ed.project, "c1")[1]["paragraph"] == 1
    assert s.mark() is False                    # again: unmarked
    assert [m["text"] for m in listen_marks.marks(ed.project, "c1")] == [SENTENCES[1]]
    # The M did not type into the chapter.
    assert ed.editor.toPlainText() == TEXT


def test_pause_and_resume_keep_the_place(app, tmp_path):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from src.ui import listen_mark
    ed = _editor(tmp_path)
    sp = FakeSpeaker()
    s = listen_mark.start(ed, speaker=sp)
    _advance(s, sp)
    QTest.keyClick(ed.editor, Qt.Key.Key_Space)
    assert s.paused and sp.paused
    assert ed.tts_speak_btn.text().startswith("▶ Resume 2/4")
    sp.finish()
    s._tick()                                   # paused: does not move on
    assert s.index == 1
    ed.tts_speak_btn.click()                    # the Read Aloud button resumes
    assert not s.paused and s.index == 1
    assert _highlighted(ed) == [SENTENCES[1]]
    assert ed.editor.toPlainText() == TEXT      # the space was not typed


def test_an_engine_that_cannot_pause_says_the_sentence_again(app, tmp_path):
    from src.ui import listen_mark
    ed = _editor(tmp_path)
    sp = FakeSpeaker(can_pause=False)
    s = listen_mark.start(ed, speaker=sp)
    _advance(s, sp)
    s.pause()
    assert s.paused and sp.stops >= 1
    s.resume()
    assert sp.spoken[-2:] == [SENTENCES[1], SENTENCES[1]] and s.index == 1


def test_text_undo_and_saved_state_are_unchanged(app, tmp_path):
    from src.ui import listen_mark
    ed = _editor(tmp_path)
    doc = ed.editor.document()
    undo_before, modified_before = doc.availableUndoSteps(), doc.isModified()
    sp = FakeSpeaker()
    s = listen_mark.start(ed, speaker=sp)
    _advance(s, sp)
    s.mark()
    s.pause()
    s.resume()
    s.stop()
    assert ed.editor.toPlainText() == TEXT
    assert doc.availableUndoSteps() == undo_before
    assert doc.isModified() == modified_before
    assert ed.chapter.content == TEXT


def test_esc_and_stop_reading_stop_listening(app, tmp_path):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from src.ui import listen_mark
    ed = _editor(tmp_path)
    sp = FakeSpeaker()
    s = listen_mark.start(ed, speaker=sp)
    QTest.keyClick(ed.editor, Qt.Key.Key_Escape)
    assert not s.running and sp.ended == 1
    s2 = listen_mark.start(ed, speaker=FakeSpeaker())
    listen_mark.stop(ed)                        # what ⏹ Stop reading calls
    assert not s2.running and ed.listen_action.isEnabled()
    # Once stopped, the keys type again.
    QTest.keyClick(ed.editor, Qt.Key.Key_M)
    assert ed.editor.toPlainText() != TEXT


def test_without_a_highlight_the_whole_chapter_is_read(app, tmp_path):
    """No highlight: the whole chapter from the top, wherever the cursor is."""
    from src.ui import listen_mark
    ed = _editor(tmp_path)
    c = ed.editor.textCursor()
    c.setPosition(TEXT.index("Voss"))
    ed.editor.setTextCursor(c)
    sp = FakeSpeaker()
    s = listen_mark.start(ed, speaker=sp)
    assert sp.spoken == [SENTENCES[0]] and s.total == 4
    for _ in range(3):
        _advance(s, sp)
    assert sp.spoken == SENTENCES
    assert ed.editor.textCursor().position() == TEXT.index("Voss")   # not moved
    listen_mark.stop(ed)


def _highlight(ed, start, end):
    from PyQt6.QtGui import QTextCursor
    c = ed.editor.textCursor()
    c.setPosition(start)
    c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    ed.editor.setTextCursor(c)


def test_with_a_highlight_only_the_highlighted_text_is_read(app, tmp_path):
    from src.ui import listen_mark
    ed = _editor(tmp_path)
    a = TEXT.index("Mara")
    b = TEXT.index("Voss waited there.") + len("Voss waited there.")
    _highlight(ed, a, b)
    sp = FakeSpeaker()
    s = listen_mark.start(ed, speaker=sp)
    assert s.total == 2 and sp.spoken == [SENTENCES[1]]
    _advance(s, sp)
    assert sp.spoken == SENTENCES[1:3]
    _advance(s, sp)                       # nothing past the highlight
    assert sp.spoken == SENTENCES[1:3] and not s.running
    # The writer's highlight is back as it was.
    c = ed.editor.textCursor()
    assert (c.selectionStart(), c.selectionEnd()) == (a, b)


def test_a_highlight_mid_sentence_is_read_as_highlighted(app, tmp_path):
    from src.ui import listen_mark
    ed = _editor(tmp_path)
    a = TEXT.index("broke")
    b = TEXT.index("Mara ran") + len("Mara ran")
    _highlight(ed, a, b)
    sp = FakeSpeaker()
    s = listen_mark.start(ed, speaker=sp)
    _advance(s, sp)
    assert sp.spoken == ["broke at dusk.", "Mara ran"]
    listen_mark.stop(ed)


def test_marks_inside_a_highlight(app, tmp_path):
    from src.ui import listen_mark
    ed = _editor(tmp_path)
    a = TEXT.index("Dr. Voss")
    _highlight(ed, a, len(TEXT))
    sp = FakeSpeaker()
    s = listen_mark.start(ed, speaker=sp)
    assert s.mark() is True
    listen_mark.stop(ed)
    ms = listen_marks.marks(ed.project, "c1")
    assert [m["text"] for m in ms] == [SENTENCES[2]]
    assert ms[0]["start"] == a
    assert ed.editor.toPlainText() == TEXT


def test_the_highlight_is_not_drawn_over_the_sentence_being_read(app, tmp_path):
    from src.ui import listen_mark
    ed = _editor(tmp_path)
    a = TEXT.index("Mara")
    _highlight(ed, a, len(TEXT))
    sp = FakeSpeaker()
    listen_mark.start(ed, speaker=sp)
    assert not ed.editor.textCursor().hasSelection()
    assert _highlighted(ed) == [SENTENCES[1]]
    listen_mark.stop(ed)
    assert ed.editor.textCursor().selectionStart() == a


def test_no_voice_offers_nothing_else(app, tmp_path, monkeypatch):
    from src.ui import listen_mark, notify
    told = []
    monkeypatch.setattr(notify, "empty", lambda parent, title, text: told.append(text))
    ed = _editor(tmp_path)
    sp = FakeSpeaker(available=False)
    assert listen_mark.start(ed, speaker=sp) is None
    assert told and "speech voice" in told[0]
    assert sp.spoken == [] and sp.began == 0


def test_the_menu_entries_and_marks_list(app, tmp_path):
    from src.ui import listen_mark
    ed = _editor(tmp_path)
    menu = ed.tts_speak_btn.menu()
    texts = [a.text() for a in menu.actions()]
    assert "👂 Listen and mark" in texts
    assert texts.index("👂 Listen and mark") < texts.index("Read chapters…")
    assert not ed.listen_marks_menu.menuAction().isVisible()
    sp = FakeSpeaker()
    s = listen_mark.start(ed, speaker=sp)
    assert not ed.listen_action.isEnabled()
    s.mark()
    s.stop()
    listen_mark._fill_marks_menu(ed)
    assert ed.listen_marks_menu.menuAction().isVisible()
    entries = ed.listen_marks_menu.actions()
    assert [a.text() for a in entries] == [SENTENCES[0]]
    entries[0].trigger()
    assert ed.editor.textCursor().selectedText() == SENTENCES[0]


def test_a_mark_whose_sentence_changed_is_kept(app, tmp_path):
    from src.ui import listen_mark
    ed = _editor(tmp_path)
    sp = FakeSpeaker()
    s = listen_mark.start(ed, speaker=sp)
    s.mark()
    s.stop()
    ed.editor.setPlainText("A new opening. " + TEXT.replace("The storm broke", "Rain fell"))
    listen_mark._fill_marks_menu(ed)
    [entry] = ed.listen_marks_menu.actions()
    assert listen_marks.CHANGED_LABEL in entry.text()
    assert len(listen_marks.marks(ed.project, "c1")) == 1


def test_known_marks_show_on_the_next_listen(app, tmp_path):
    from src.ui import listen_mark
    ed = _editor(tmp_path)
    s = listen_mark.start(ed, speaker=FakeSpeaker())
    s.mark()
    s.stop()
    s2 = listen_mark.start(ed, speaker=FakeSpeaker())
    assert s2.marked_indices() == [0]
    assert s2.mark() is False                   # the same mark, unmarked
    assert listen_marks.marks(ed.project, "c1") == []
    s2.stop()


# ── The store ──────────────────────────────────────────────────────────

class _P:
    project_path = ""
    name = "x"


def test_store_keeps_every_other_key(tmp_path, monkeypatch):
    import src.data.companion_state as cs
    path = tmp_path / "cs.json"
    monkeypatch.setattr(cs, "state_path", lambda p: path)
    before = {"chapters": {"c1": {"last_session": "2026-11-01T10:00", "stopped_at": "x"}},
              "dismissed": ["k"], "sessions": {"a": {"date": "2026-11-01", "added": 3}}}
    path.write_text(json.dumps(before))
    m = listen_marks.new_mark("Nobody slept.", 10, 23, 1)
    listen_marks.add(_P(), "c1", m)
    data = json.loads(path.read_text())
    assert data["dismissed"] == ["k"] and data["sessions"] == before["sessions"]
    assert data["chapters"]["c1"]["last_session"] == "2026-11-01T10:00"
    assert data["chapters"]["c1"]["heard_marks"][0]["text"] == "Nobody slept."
    cs.record_session(_P(), "c1", 1, 2, "here")          # companion still works
    assert listen_marks.marks(_P(), "c1")[0]["id"] == m["id"]
    listen_marks.remove(_P(), "c1", m["id"])
    assert listen_marks.marks(_P(), "c1") == []
    assert json.loads(path.read_text())["chapters"]["c1"]["stopped_at"] == "here"


def test_store_with_damaged_or_missing_state_is_empty(tmp_path, monkeypatch):
    import src.data.companion_state as cs
    monkeypatch.setattr(cs, "state_path", lambda p: tmp_path / "none.json")
    assert listen_marks.marks(_P(), "c1") == []
    assert listen_marks.marks(None, "c1") == []
    path = tmp_path / "cs.json"
    path.write_text(json.dumps({"chapters": {"c1": {"heard_marks": ["junk", {"x": 1}]}}}))
    monkeypatch.setattr(cs, "state_path", lambda p: path)
    assert listen_marks.marks(_P(), "c1") == []


def test_resolve():
    m = {"text": "Nobody slept.", "start": 5, "end": 18}
    assert listen_marks.resolve(m, "Rain.Nobody slept.") == (5, 18, listen_marks.SAME)
    assert listen_marks.resolve(m, "Nobody slept. Yes.")[2] == listen_marks.MOVED
    assert listen_marks.resolve(m, "Everyone slept.")[2] == listen_marks.CHANGED
