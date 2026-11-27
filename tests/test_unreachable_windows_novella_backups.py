"""D.12 Unreachable windows, the novella move, and backup copies.

* The old Suggestions and Overly descriptive? windows are gone; the
  helpers the Improve window uses stay where they were.
* "Turn main manuscript into a novella…" makes the novella and moves every
  main chapter with ``chapter_move.move_chapters`` (renamed in place, never
  copied), the main manuscript's drafts with them, and offers Undo. Its
  question, and "Move main chapters into this novella"'s, say what Undo
  covers and what it does not.
* Two saves in one second keep two copies of the chapter (``backup_*.md``);
  copies named before D.12 are still listed, sorted, pruned and restored.

No model runs; HOME is a scratch folder (conftest).
"""

from __future__ import annotations

import importlib
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QMessageBox  # noqa: E402

from src.models.project import Chapter, Manuscript, ManuscriptDraft, WriterProject  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    """No LanguageTool server is started by these tests."""
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)


# ── 1. The unreachable windows ─────────────────────────────────────────

def test_the_two_old_windows_are_gone_and_the_improve_windows_helpers_stay():
    pd = importlib.import_module("src.ui.passage_critique_dialog")
    op = importlib.import_module("src.ui.overdescription_panel")
    assert not hasattr(pd, "PassageCritiqueDialog")
    assert not hasattr(op, "ExpandStatementDialog")
    for name in ("SuggestionWorker", "widened_note", "discussion_html", "chat_turn_fn",
                 "log_rating", "avoid_phrase", "EXPANDED_ANGLE", "_build_llm", "_RUNNING"):
        assert hasattr(pd, name), name
    for name in ("OverdescriptionPanel", "ReviewWorker", "MoreWorker", "ExpansionState",
                 "log_accepted", "highlight_flags", "flag_html", "_RUNNING"):
        assert hasattr(op, name), name
    root = Path(__file__).resolve().parent.parent
    for folder in ("src", "scripts"):
        for f in (root / folder).rglob("*.py"):
            text = f.read_text(errors="ignore")
            for gone in ("PassageCritiqueDialog(", "ExpandStatementDialog("):
                assert gone not in text, f"{f}: {gone}"


def test_every_way_in_still_opens_the_improve_window(app, monkeypatch):
    """What the old windows did is the Improve window's (D.2b, D.2c):
    the right-click entries land on its tabs."""
    from PyQt6.QtWidgets import QDialog
    import src.ui.improve_window as iw
    from src.ui.manuscript_editor import ChapterEditor
    opened = []

    class Recorder:
        def __init__(self, text, start, end, project, chapter, parent, **kw):
            opened.append(kw.get("tab"))
            self.replacement, self.span, self.tool = None, (start, end), kw.get("tab")

        def exec(self):
            return QDialog.DialogCode.Rejected
    monkeypatch.setattr(iw, "ImproveWindow", Recorder)
    text = "The room was almost too dark to see. She almost fell."
    ed = ChapterEditor(Chapter(id="c", number=1, title="A", content=text),
                       project=WriterProject(name="P"))
    ed.suggest_for_span(0, 36)
    ed.expand_statement(0, 36)
    assert opened == ["suggestions", "expand"]


# ── 2. The novella move ────────────────────────────────────────────────

def _project(tmp_path, drafts=True, novella=False):
    path = tmp_path / "Saga.writerproj"
    p = WriterProject(name="Saga", manuscript=Manuscript(title="Main Manuscript"))
    p.manuscript.chapters = [Chapter(id=f"m{i}", number=i, title=t, content=f"Main {i}.")
                             for i, t in enumerate(["The Storm", "The Pier", "The Letter"], 1)]
    if novella:
        fall = p.create_subproject("The Fall")
        fall.manuscript.chapters = [Chapter(id="f1", number=1, title="Fall 1",
                                            content="Fall 1.")]
    p._normalize_manuscript_roots()
    if drafts:
        p.drafts = [ManuscriptDraft(id="d1", name="Main draft",
                                    chapters=[Chapter(id="x", number=1, title="X", content="x")])]
    p.save_project(str(path))
    p.save_project(str(path))
    for ch in p.manuscript.chapters:                       # a saved copy and a note too
        folder = tmp_path / ch.folder_path
        (folder / "backup_20260101_090000.md").write_text(f"Older {ch.title}.")
        (folder / "notes.txt").write_text(f"Notes for {ch.title}.")
    return p


_KEEP = []        # windows outlive their test, so no editor's worker thread is cut off


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


def _files(root: Path):
    return {str(f.relative_to(root)): f.read_bytes() for f in root.rglob("*")
            if f.is_file() and "chapter_" in str(f.relative_to(root))}


def _ids(p, scope):
    return [c.id for c in p.get_manuscript_for(scope).chapters]


@pytest.fixture
def answer(monkeypatch):
    """The question before the move answered Yes (or No), the name asked
    for given; other boxes recorded."""
    said = {"reply": QMessageBox.StandardButton.Yes, "boxes": [], "name": "Novella 1"}
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: said["boxes"].append(("question", a[1], a[2])) or said["reply"]))
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: said["boxes"].append((_n, a[1] if len(a) > 1 else ""))))
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(
        lambda *a, **k: (said["name"], True)))
    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(
        lambda *a, **k: ("", True)))
    return said


# D.14 changed these words: Undo now removes the empty novella and stays on
# the tree's right-click until the next save.
UNTIL_SAVED = ("It is also on the manuscript tree's right-click (“Undo the last move”) until "
               "you next save the project yourself (Save Project, Ctrl+S; the app's own "
               "autosaves don't count), make another move or close the app.")
UNDO_WITH_DRAFTS = (
    "Undo, on the status bar for 30 seconds (until another message replaces it), puts the "
    "chapters and drafts back and removes “Novella 1” (unless something has been added to "
    "it or saved for it since). " + UNTIL_SAVED + " After that you can still move the chapters back "
    "(right-click ▸ Move to), but the drafts stay with “Novella 1”.")


def test_the_questions_say_what_undo_covers(app, tmp_path):
    from src.ui import manuscript_tree as mt
    assert mt.undo_note(1, "Novella 1", new=True) == UNDO_WITH_DRAFTS
    assert mt.undo_note(0, "The Fall") == (
        "Undo, on the status bar for 30 seconds (until another message replaces it), puts the "
        "chapters back. " + UNTIL_SAVED + " After that you can still move the chapters back "
        "(right-click ▸ Move to).")
    assert mt.undo_note(2, new=True).endswith("but the drafts stay with the new novella.")
    p = _project(tmp_path)
    assert mt.turn_main_question(p, "Novella 1") == (
        "Move the main manuscript's 3 chapter(s) and 1 draft(s) into a new novella "
        "'Novella 1'?\n\nThe folders are moved, not copied, and the main manuscript will "
        "be empty afterwards. " + UNDO_WITH_DRAFTS)
    assert mt.NOTICE_MS == 30000                       # the 30 seconds the words promise


def test_turn_main_into_a_novella_moves_by_rename_with_its_drafts_and_undo(
        app, tmp_path, answer, monkeypatch):
    p = _project(tmp_path)
    win, w = _editor(app, p)
    before = _files(tmp_path)
    monkeypatch.setattr(shutil, "copytree", lambda *a, **k: pytest.fail("a chapter was copied"))
    monkeypatch.setattr(WriterProject, "move_main_content_to_subproject",
                        lambda *a, **k: pytest.fail("the old copy-and-delete ran"))
    inode = os.stat(tmp_path / p.manuscript.chapters[0].folder_path
                    / "backup_20260101_090000.md").st_ino
    from src.ui import manuscript_tree as mt
    expected = mt.turn_main_question(p, "Novella 1")
    menu, actions = w.manuscript_tree.manuscript_menu(None)
    act = next(a for a in actions if a.text() == "Turn main manuscript into a novella…")
    actions[act]()                                      # the same entry, the same place
    app.processEvents()
    question = [b for b in answer["boxes"] if b[0] == "question"]
    assert question == [("question", "Turn into novella", expected)]
    assert expected.endswith(UNDO_WITH_DRAFTS)
    sp = next(s for s in p.subprojects if s.name == "Novella 1")
    assert _ids(p, None) == [] and _ids(p, sp.id) == ["m1", "m2", "m3"]
    moved = tmp_path / "subprojects" / sp.id / "chapters"
    assert (moved / "chapter_001" / "revision_001.md").read_text() == "Main 1."
    assert (moved / "chapter_001" / "backup_20260101_090000.md").read_text() == "Older The Storm."
    assert (moved / "chapter_003" / "notes.txt").read_text() == "Notes for The Letter."
    assert os.stat(moved / "chapter_001" / "backup_20260101_090000.md").st_ino == inode
    assert not list(tmp_path.glob("*.pre-move-*"))
    assert [(d.id, d.subproject_id) for d in p.drafts] == [("d1", sp.id)]
    # The same result as before: the novella open, the main manuscript empty, saved.
    assert p.active_subproject_id == sp.id and w._current_chapter_id == "m1"
    again = WriterProject.load_project(p.project_path)
    assert [c.id for c in again.get_manuscript_for(sp.id).chapters] == ["m1", "m2", "m3"]
    assert again.get_main_manuscript().chapters == []
    assert {d.id: d.subproject_id for d in again.drafts} == {"d1": sp.id}
    assert win.statusBar().currentMessage() == "Moved 3 chapters to Novella 1"
    assert win._tree_undo_btn.isVisible()
    # The box kept since D.9, then Undo shown again for its full time.
    assert [b for b in answer["boxes"] if b[0] != "question"] == [("information",
                                                                  "Chapters Moved")]

    win._tree_undo_btn.click()
    app.processEvents()
    assert _ids(p, None) == ["m1", "m2", "m3"] and p.get_subproject(sp.id) is None
    assert [(d.id, d.subproject_id) for d in p.drafts] == [("d1", None)]
    assert _files(tmp_path) == before                                   # every file, back
    # As the question says (D.14): the empty novella is removed.
    assert p.subprojects == [] and p.active_subproject_id is None
    again = WriterProject.load_project(p.project_path)
    assert [c.id for c in again.get_main_manuscript().chapters] == ["m1", "m2", "m3"]
    assert {d.id: d.subproject_id for d in again.drafts} == {"d1": None}


def test_undo_goes_when_another_message_replaces_it(app, tmp_path, answer):
    p = _project(tmp_path, drafts=False)
    win, w = _editor(app, p)
    w._create_novella_from_main("Novella 1")
    assert win._tree_undo_btn.isVisible()
    win.statusBar().showMessage("Saved: somewhere")
    assert not win._tree_undo_btn.isVisible()           # as the question says
    w.manuscript_tree.announce("Moved 3 chapters to Novella 1")
    win.statusBar().clearMessage()                      # what the 30 seconds' end does
    assert not win._tree_undo_btn.isVisible()


def test_no_moves_nothing_and_makes_no_novella(app, tmp_path, answer):
    p = _project(tmp_path)
    _win, w = _editor(app, p)
    before = _files(tmp_path)
    answer["reply"] = QMessageBox.StandardButton.No
    assert not w._turn_main_into_novella()
    assert _ids(p, None) == ["m1", "m2", "m3"] and p.subprojects == []
    assert _files(tmp_path) == before


def test_a_failure_part_way_puts_everything_back_and_takes_the_novella_away(
        app, tmp_path, answer, monkeypatch):
    p = _project(tmp_path)
    _win, w = _editor(app, p)
    before = _files(tmp_path)
    from src.data import chapter_move as cm
    real, calls = cm._rename, []

    def flaky(s, t):
        calls.append(s)
        if len(calls) == 3:
            raise OSError("the disk said no")
        real(s, t)
    monkeypatch.setattr(cm, "_rename", flaky)
    assert not w._create_novella_from_main("Novella 1")
    assert _ids(p, None) == ["m1", "m2", "m3"] and p.subprojects == []
    assert _files(tmp_path) == before
    assert [(d.id, d.subproject_id) for d in p.drafts] == [("d1", None)]
    assert ("critical", "Move Failed") in answer["boxes"]
    again = WriterProject.load_project(p.project_path)
    assert again.subprojects == [] and len(again.get_main_manuscript().chapters) == 3


def test_while_a_draft_is_open_nothing_is_made_or_moved(app, tmp_path, answer):
    p = _project(tmp_path)
    _win, w = _editor(app, p)
    draft = p.create_draft_from_current("Try")
    w.switch_to_draft(draft)
    answer["boxes"].clear()
    assert not w._create_novella_from_main("Novella 1")
    assert _ids(p, None) == ["m1", "m2", "m3"] and p.subprojects == []
    assert any(b[0] == "information" for b in answer["boxes"])


def test_the_other_ways_in_ask_with_the_same_undo_words(app, tmp_path, answer, monkeypatch):
    # "Move main chapters into this novella": the same words, for that novella.
    p = _project(tmp_path, novella=True)
    _win, w = _editor(app, p)
    fall = p.subprojects[0].id
    answer["reply"] = QMessageBox.StandardButton.No
    w._move_main_into_existing(fall)
    from src.ui import manuscript_tree as mt
    assert answer["boxes"][-1][2].endswith("\n\nThe folders are moved, not copied, and the main "
                                           "manuscript will be empty afterwards. "
                                           + mt.undo_note(1, "The Fall"))
    # The first novella's "Move into …" box, and the offer after dropping
    # the last novella, end on the same words; both go through the move.
    shown = {}
    real_exec = QMessageBox.exec

    def exec_(box):
        shown["text"] = box.informativeText()
        move = next(b for b in box.buttons() if b.text().startswith("Move into"))
        box.clickedButton = lambda: move
        return 0
    monkeypatch.setattr(QMessageBox, "exec", exec_)
    (tmp_path / "second").mkdir()
    q = _project(tmp_path / "second")
    _win2, w2 = _editor(app, q)
    w2._create_subproject()
    monkeypatch.setattr(QMessageBox, "exec", real_exec)
    assert shown["text"].endswith("If you move them: " + mt.undo_note(1, "Novella 1", new=True))
    sp = q.subprojects[0]
    assert _ids(q, sp.id) == ["m1", "m2", "m3"] and _ids(q, None) == []


# ── 3. Backup copies (rule 15) ─────────────────────────────────────────

def _saved_chapter(tmp_path):
    p = WriterProject(name="B", manuscript=Manuscript(title="B"))
    ch = Chapter(id="c1", number=1, title="One", content="first")
    p.manuscript.chapters = [ch]
    path = tmp_path / "B.writerproj"
    p.save_project(str(path))
    return p, ch, path


def test_two_saves_in_one_second_keep_two_copies(tmp_path, monkeypatch):
    import src.models.project as pm
    p, ch, path = _saved_chapter(tmp_path)
    folder = tmp_path / ch.folder_path
    for f in folder.glob("backup_*.md"):
        f.unlink()
    frozen = datetime(2026, 11, 27, 10, 0, 5)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen
    monkeypatch.setattr(pm, "datetime", Clock)
    for text in ("second", "third", "fourth"):
        ch.content = text
        p.save_project(str(path))
    names = sorted(f.name for f in folder.glob("backup_*.md"))
    assert names == ["backup_20261127_100005.md", "backup_20261127_100005_2.md",
                     "backup_20261127_100005_3.md"]
    assert [(folder / n).read_text() for n in names] == ["first", "second", "third"]
    # Newest first, each with its own time, and each one restores.
    listed = ch._list_backups(tmp_path)
    assert [f.name for _dt, f in listed] == list(reversed(names))
    times = ch.get_backup_timestamps(tmp_path)
    assert len(set(times)) == 3 and times == sorted(times, reverse=True)
    assert ch.revert_to_backup(tmp_path, timestamp=times[2]) and ch.content == "first"
    assert ch.revert_to_backup(tmp_path, timestamp=times[1]) and ch.content == "second"


def test_old_names_are_still_listed_sorted_pruned_and_restored(tmp_path):
    from src.models import chapter_backups as cb
    p, ch, path = _saved_chapter(tmp_path)
    folder = tmp_path / ch.folder_path
    for f in folder.glob("backup_*.md"):
        f.unlink()
    (folder / "backup_20261126_090000.md").write_text("old A")
    (folder / "backup_20261126_090000_2.md").write_text("new form, same second")
    (folder / "backup_20261125_120000.md").write_text("old B")
    (folder / "backup_1.md").write_text("not a copy")          # never read as one
    (folder / "backup_20261126_090000_1.md").write_text("not a copy either")
    listed = [f.name for _dt, f in ch._list_backups(tmp_path)]
    assert listed == ["backup_20261126_090000_2.md", "backup_20261126_090000.md",
                      "backup_20261125_120000.md"]
    first = ch.get_backup_timestamps(tmp_path)[1]
    assert first == datetime(2026, 11, 26, 9, 0, 0)
    assert ch.revert_to_backup(tmp_path, timestamp=first) and ch.content == "old A"
    # Pruning reads both forms (the first of a day is kept, the newest three too).
    backups = ch._list_backups(tmp_path)
    assert cb.to_remove(backups, today=datetime(2026, 11, 27).date()) == []
    # How the menu shows them.
    assert cb.label(first) == "Nov 26, 2026  09:00:00 AM"
    assert cb.label(first + timedelta(microseconds=1)) == "Nov 26, 2026  09:00:00 AM (2)"


def test_a_new_name_is_never_one_already_there(tmp_path):
    from src.models import chapter_backups as cb
    when = datetime(2026, 11, 27, 10, 0, 5)
    assert cb.new_path(tmp_path, when).name == "backup_20261127_100005.md"
    (tmp_path / "backup_20261127_100005.md").write_text("a")
    (tmp_path / "backup_20261127_100005_4.md").write_text("b")
    # One higher than the highest of that second, so order is kept even if a
    # lower one was pruned.
    assert cb.new_path(tmp_path, when).name == "backup_20261127_100005_5.md"
    src = tmp_path / "src.md"
    src.write_text("text")
    made = [cb.copy_new(src, tmp_path, when) for _ in range(2)]
    assert [m.name for m in made] == ["backup_20261127_100005_5.md",
                                      "backup_20261127_100005_6.md"]
    assert (tmp_path / "backup_20261127_100005.md").read_text() == "a"


def test_the_old_single_copy_is_never_moved_onto_a_copy(tmp_path):
    p, ch, path = _saved_chapter(tmp_path)
    folder = tmp_path / ch.folder_path
    legacy = folder / "working_backup.md"
    legacy.write_text("legacy")
    stamp = datetime.fromtimestamp(legacy.stat().st_mtime).strftime("%Y%m%d_%H%M%S")
    taken = folder / f"backup_{stamp}.md"
    taken.write_text("already here")
    ch.content = "changed"
    p.save_project(str(path))
    assert taken.read_text() == "already here"
    assert (folder / f"backup_{stamp}_2.md").read_text() == "legacy"
    assert not legacy.exists()


def test_a_project_from_before_opens_saves_and_reopens_unchanged(tmp_path):
    """Rule 11: a project with copies named before D.12 opens, saves and
    reopens with its chapter text and its copies as they were."""
    p, ch, path = _saved_chapter(tmp_path)
    folder = tmp_path / ch.folder_path
    old = folder / "backup_20250101_080000.md"
    old.write_text("an old copy")
    again = WriterProject.load_project(str(path))
    again.save_project(str(path))
    third = WriterProject.load_project(str(path))
    third.manuscript.chapters[0].load_content_from_file(tmp_path)
    assert third.manuscript.chapters[0].content == "first"
    assert old.read_text() == "an old copy"
