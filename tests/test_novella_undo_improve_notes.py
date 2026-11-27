"""D.14b: Undo removes a novella only when it is truly empty; the Improve
window's notes are kept per project.

Projects are built in ``tmp_path``; HOME is a scratch folder (conftest); no
model runs; LanguageTool is never started; every box is answered here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QMessageBox  # noqa: E402

from src.data import improve_notes as notes  # noqa: E402
from src.data import novella_content as nc  # noqa: E402
from src.data import readiness_state as rs  # noqa: E402
from src.models.project import Chapter, Manuscript, ManuscriptDraft, WriterProject  # noqa: E402
from src.ui import feedback_sources as fs  # noqa: E402

YES = QMessageBox.StandardButton.Yes
TEXT = ("Rain fell on the harbor all night. Mara watched the boats.\n\n"
        "It was very, very cold on the pier.\n\n"
        "That evening Tobin burned the letter in the stove.")
PASSAGE = "It was very, very cold on the pier."


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)
    fs._SESSION.clear()
    yield
    fs._SESSION.clear()


@pytest.fixture
def boxes(monkeypatch):
    said = {"shown": [], "name": "Novella 1", "description": ""}
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: YES))
    for n in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, n, staticmethod(
            lambda *a, _n=n, **k: said["shown"].append((_n, a[1], a[2] if len(a) > 2 else ""))))
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (said["name"], True)))
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        staticmethod(lambda *a, **k: (said["description"], True)))
    return said


def _project(tmp_path, n=3):
    p = WriterProject(name="Saga", manuscript=Manuscript(title="Main Manuscript"))
    p.manuscript.chapters = [Chapter(id=f"m{i}", number=i, title=f"Chapter {i}", content=TEXT)
                             for i in range(1, n + 1)]
    p._normalize_manuscript_roots()
    p.save_project(str(tmp_path / "Saga.writerproj"))
    p.save_project(str(tmp_path / "Saga.writerproj"))
    return p


_KEEP = []


def _editor(app, p):
    from PyQt6.QtWidgets import QMainWindow
    from src.ui.manuscript_editor import ManuscriptEditor
    win = QMainWindow()
    _KEEP.append(win)
    w = ManuscriptEditor()
    win.setCentralWidget(w)
    win.statusBar()
    w.set_project(p)
    w.load_manuscript(p.manuscript)
    w.open_chapter("m1")
    win.resize(1440, 900)
    win.show()
    app.processEvents()
    w.manuscript_tree.rebuild()
    return win, w


def _done(app, w):
    from src.ui import background, companion_panel
    for t in list(companion_panel._RUNNING):
        try:
            t.wait(10000)
        except RuntimeError:
            pass
    background.wait_all(10000)
    app.processEvents()


def _ids(p, scope):
    return [c.id for c in p.get_manuscript_for(scope).chapters]


# ── 1. What a novella holds ────────────────────────────────────────────

def test_a_new_novella_holds_nothing_and_each_kind_of_content_counts(tmp_path):
    p = _project(tmp_path)
    sp = p.create_subproject("Novella 1", "A winter story.")
    made = nc.snapshot(sp)
    p.save_project(p.project_path)                     # its subproject.json only
    assert nc.holds(p, sp.id, tmp_path, made) == []    # its description came with it
    # Empty containers left by Undo do not count.
    rs.update(p, lambda d: d["manuscripts"].setdefault(sp.id, {"chapters": {}}))
    rs.update(p, lambda d: d.setdefault("digest", {}).setdefault(sp.id, {}))
    assert nc.holds(p, sp.id, tmp_path, made) == []

    def check(change, words, undo):
        change()
        assert words in nc.holds(p, sp.id, tmp_path, made), words
        undo()
        assert nc.holds(p, sp.id, tmp_path, made) == [], words

    ch = Chapter(id="n1", number=1, title="N", content="x")
    check(lambda: sp.manuscript.chapters.append(ch), "chapters",
          lambda: sp.manuscript.chapters.clear())
    check(lambda: p.drafts.append(ManuscriptDraft(id="d", name="D", subproject_id=sp.id)),
          "drafts", lambda: p.drafts.clear())
    f = tmp_path / "subprojects" / sp.id / "cover.png"
    check(lambda: f.write_bytes(b"png"), "files in its folder", f.unlink)
    check(lambda: setattr(sp, "description", "Changed."), "a description",
          lambda: setattr(sp, "description", "A winter story."))
    check(lambda: p.rename_subproject(sp.id, "Winter"), "a new name",
          lambda: p.rename_subproject(sp.id, "Novella 1"))
    route = lambda v: rs.update(p, lambda d: d["manuscripts"][sp.id].__setitem__("route", v))
    check(lambda: route("self"), "a publishing route",
          lambda: rs.update(p, lambda d: d["manuscripts"][sp.id].pop("route")))
    check(lambda: rs.update(p, lambda d: d.setdefault("scene_marks", {}).__setitem__(
        sp.id, {"text": "something"})), "scene markers",
          lambda: rs.update(p, lambda d: d["scene_marks"].pop(sp.id)))
    # The app's own results don't keep it (the writer, 27 Nov: count only
    # what you wrote); they stay in their files, unread.
    for key in ("letter", "voice", "digest", "tension", "someday"):
        rs.update(p, lambda d, k=key: d.setdefault(k, {}).__setitem__(sp.id, {"text": "x"}))
    rs.update(p, lambda d: d["manuscripts"][sp.id].__setitem__("book", {"checks": [1]}))
    assert nc.holds(p, sp.id, tmp_path, made) == []
    assert "voice" in json.loads(rs.readiness_path(p).read_text())   # not deleted
    from src.data import submission_store as ss
    check(lambda: ss.update(p, lambda d: d["manuscripts"].__setitem__(
        sp.id, {"synopsis": {"text": "A synopsis."}})), "submission drafts",
          lambda: ss.update(p, lambda d: d["manuscripts"].pop(sp.id)))
    notes.append(p, sp.id, "n1", {"passage": "x", "versions": []})
    from src.data import critique_history as chist
    chist.history_path(p).write_text(json.dumps({f"chapter@{sp.id}:N": [{"timestamp": "t"}]}))
    assert nc.holds(p, sp.id, tmp_path, made) == []    # Improve notes, Critique reports: the app's
    # An unreadable file is never assumed empty.
    rs.readiness_path(p).write_text("{damaged")
    assert any("could not be read" in w for w in nc.holds(p, sp.id, tmp_path, made))
    assert rs.readiness_path(p).read_text() == "{damaged"      # left as it is


def test_the_words_for_why():
    assert nc.because(["chapters"]) == "it has chapters"
    assert nc.because(["drafts", "Critique reports"]) == "it has drafts and Critique reports"
    assert nc.because(["a", "b", "c"]) == "it has a, b and c"


# ── 2. Undo keeps a novella with content of its own, and says why ─────

def test_undo_keeps_a_novella_with_its_own_submission_drafts(app, tmp_path, boxes):
    from src.data import submission_store as ss
    p = _project(tmp_path)
    win, w = _editor(app, p)
    assert w._create_novella_from_main("Novella 1")
    sp = p.subprojects[0]
    ss.update(p, lambda d: d["manuscripts"].__setitem__(sp.id, {"query": {"text": "Dear agent"}}))
    assert w.manuscript_tree.undo_last()
    assert _ids(p, None) == ["m1", "m2", "m3"] and p.get_subproject(sp.id) is not None
    assert win.statusBar().currentMessage() == (
        "Put back where it was. “Novella 1” was kept: it has submission drafts.")
    _done(app, w)


def test_undo_removes_a_named_novella_whose_chapter_results_went_back(app, tmp_path, boxes):
    """Readiness results made while the chapter was in the novella go back
    with it, so the novella is empty again and goes."""
    p = _project(tmp_path)
    win, w = _editor(app, p)
    boxes["description"] = "Told by Tobin."
    assert w.manuscript_tree.move_to_new_novella([(None, "m2")])   # ＋ A new novella…
    sp = p.subprojects[0]
    assert sp.description == "Told by Tobin."
    rs.store_chapter(p, sp.id, "m2", {"made_at": "2026-11-27T10:00:00",
                                      "results": {"repetition": {"status": "ok"}}})
    assert w.manuscript_tree.undo_last()
    assert p.get_subproject(sp.id) is None
    assert win.statusBar().currentMessage() == "Put back where it was. “Novella 1” was removed."
    data = json.loads(rs.readiness_path(p).read_text())
    assert "repetition" in data["manuscripts"]["main"]["chapters"]["m2"]["results"]
    _done(app, w)


def test_undo_keeps_a_named_novella_whose_description_changed_since(app, tmp_path, boxes):
    p = _project(tmp_path)
    win, w = _editor(app, p)
    assert w.manuscript_tree.move_to_new_novella([(None, "m2")])
    sp = p.subprojects[0]
    sp.description = "Written later."
    assert w.manuscript_tree.undo_last()
    assert p.get_subproject(sp.id) is not None
    assert win.statusBar().currentMessage().endswith("was kept: it has a description.")
    _done(app, w)


def test_the_undo_words_name_the_rule():
    from src.ui import manuscript_tree as mt
    assert "unless something has been added to it or saved for it since" in \
        mt.undo_note(0, "Novella 1", new=True)


# ── 3. The Improve notes file ──────────────────────────────────────────

def test_notes_are_appended_capped_and_dismissed_never_removed(tmp_path):
    p = _project(tmp_path, 1)
    assert not notes.path_for(p).exists()
    assert notes.path_for(p) == tmp_path / "Saga.improve_notes.json"
    first = notes.append(p, None, "m1", {"passage": "p0", "versions": []})
    for i in range(1, notes.CAP + 5):
        notes.append(p, None, "m1", {"passage": f"p{i}", "versions": []})
    kept = notes.read(p, None, "m1")
    assert len(kept) == notes.CAP == 200
    assert kept[0]["passage"] == "p5" and kept[-1]["passage"] == f"p{notes.CAP + 4}"
    assert first not in {r["id"] for r in kept}                       # the oldest went
    rid = kept[-1]["id"]
    assert notes.dismiss(p, None, "m1", rid, "v:0")
    after = notes.read(p, None, "m1")
    assert len(after) == notes.CAP and after[-1]["dismissed"] == ["v:0"]
    assert not list(tmp_path.glob("*.tmp"))                           # written atomically


def test_a_newer_or_damaged_file_is_never_saved_over(tmp_path):
    p = _project(tmp_path, 1)
    path = notes.path_for(p)
    path.write_text(json.dumps({"format_version": 99, "manuscripts": {}}))
    before = path.read_bytes()
    assert notes.append(p, None, "m1", {"passage": "x"}) is None
    assert path.read_bytes() == before
    path.write_text("{damaged")
    assert notes.read(p, None, "m1") == [] and path.read_text() == "{damaged"   # reading
    notes.append(p, None, "m1", {"passage": "x"})                    # set aside, kept
    aside = list(tmp_path.glob("Saga.improve_notes.json.unreadable-*"))
    assert aside and aside[0].read_text() == "{damaged"


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


def _feedback(app, w):
    ce = w.current_chapter_editor
    ce._show_right_panel(ce.feedback_widget)
    for _ in range(6):
        app.processEvents()
    view = ce.feedback_sources
    view.refresh()
    return ce, view


def _improve(view):
    return [i for i in view.items if i.source == fs.IMPROVE]


def test_notes_survive_reopening_show_while_the_passage_is_there_and_dismiss(
        app, tmp_path, boxes):
    p = _project(tmp_path, 2)
    chapter = p.manuscript.chapters[0]
    fs.remember_improve(_Window(p, chapter, PASSAGE,
                                [_Version("The pier bit with cold.", why="Shows it.",
                                          rating="good")]), 0)
    stored = json.loads(notes.path_for(p).read_text())
    rec = stored["manuscripts"]["main"]["chapters"]["m1"]["notes"][0]
    assert rec["passage"] == PASSAGE and rec["critique"]["issues"] == ["It tells the cold."]
    assert fs._SESSION == {}                                   # written, not kept in memory
    # Closing and reopening the project.
    again = WriterProject.load_project(p.project_path)
    win, w = _editor(app, again)
    ce, view = _feedback(app, w)
    texts = [i.text for i in _improve(view)]
    assert "It tells the cold." in texts and "The image is clear." in texts
    assert any(t.startswith("The pier bit with cold.") for t in texts)
    # Dismiss: hidden here, kept in the file as dismissed.
    item = next(i for i in _improve(view) if i.text == "It tells the cold.")
    view._link(f"dismiss:{view.items.index(item)}")
    assert "It tells the cold." not in [i.text for i in _improve(view)]
    kept = notes.read(again, None, "m1")[0]
    assert kept["dismissed"] == ["c:issues:0"] and kept["critique"]["issues"] == [
        "It tells the cold."]
    # The passage gone from the chapter: its notes are not shown (and stay in the file).
    ce.editor.setPlainText(TEXT.replace(PASSAGE, "The pier was cold."))
    view.refresh()
    assert _improve(view) == []
    assert len(notes.read(again, None, "m1")) == 1
    _done(app, w)


def test_each_improve_item_has_a_dismiss_link(app, tmp_path, boxes):
    p = _project(tmp_path, 1)
    fs.remember_improve(_Window(p, p.manuscript.chapters[0], PASSAGE, []), 0)
    win, w = _editor(app, p)
    ce, view = _feedback(app, w)
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QLabel
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    labels = [lb for lb in view.findChildren(QLabel) if "dismiss:" in lb.text()]
    assert len(labels) == len(_improve(view)) == 2
    _done(app, w)


def test_a_file_that_cannot_be_written_keeps_them_for_the_session(app, tmp_path, boxes):
    p = _project(tmp_path, 1)
    notes.path_for(p).write_text(json.dumps({"format_version": 99}))
    fs.remember_improve(_Window(p, p.manuscript.chapters[0], PASSAGE, []), 0)
    assert len(fs._SESSION) == 1
    win, w = _editor(app, p)
    ce, view = _feedback(app, w)
    item = next(i for i in _improve(view) if i.text == "It tells the cold.")
    view._link(f"dismiss:{view.items.index(item)}")                # hidden for the session
    assert "It tells the cold." not in [i.text for i in _improve(view)]
    _done(app, w)


def test_notes_follow_a_moved_chapter_and_undo_puts_them_back(app, tmp_path, boxes):
    p = _project(tmp_path)
    fs.remember_improve(_Window(p, p.manuscript.chapters[1], PASSAGE, []), 0)
    before = notes.path_for(p).read_bytes()
    win, w = _editor(app, p)
    assert w.manuscript_tree.move_to_new_novella([(None, "m2")])
    sp = p.subprojects[0]
    data = json.loads(notes.path_for(p).read_text())
    assert "m2" in data["manuscripts"][sp.id]["chapters"]
    assert "m2" not in data["manuscripts"]["main"].get("chapters", {})
    assert [r["passage"] for r in notes.read(p, sp.id, "m2")] == [PASSAGE]
    w.open_chapter("m2")
    ce, view = _feedback(app, w)
    assert "It tells the cold." in [i.text for i in _improve(view)]
    assert w.manuscript_tree.undo_last()
    assert notes.path_for(p).read_bytes() == before                  # byte for byte
    assert p.get_subproject(sp.id) is None                           # and the novella went
    _done(app, w)


def test_notes_added_in_the_novella_go_back_with_the_chapter(app, tmp_path, boxes):
    p = _project(tmp_path)
    win, w = _editor(app, p)
    assert w._create_novella_from_main("Novella 1")
    sp = p.subprojects[0]
    ch = p.get_manuscript_for(sp.id).chapters[0]
    fs.remember_improve(_Window(p, ch, PASSAGE, []), 0)
    assert notes.read(p, sp.id, ch.id)
    assert w.manuscript_tree.undo_last()
    assert [r["passage"] for r in notes.read(p, None, "m1")] == [PASSAGE]
    assert p.get_subproject(sp.id) is None                           # its part is empty again
    _done(app, w)


def test_a_project_without_the_file_opens_as_before_and_reading_writes_nothing(
        app, tmp_path, boxes):
    p = _project(tmp_path, 1)
    before = {f: f.read_bytes() for f in tmp_path.rglob("*") if f.is_file()}
    again = WriterProject.load_project(p.project_path)
    win, w = _editor(app, again)
    ce, view = _feedback(app, w)
    assert _improve(view) == [] and not notes.path_for(again).exists()
    again.save_project(again.project_path)
    third = WriterProject.load_project(again.project_path)
    assert [c.content for c in third.manuscript.chapters] == [TEXT]
    assert not notes.path_for(third).exists()
    assert set(before) <= {f for f in tmp_path.rglob("*") if f.is_file()}
    _done(app, w)
