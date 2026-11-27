"""D.14 Undo and warnings.

* Undo after "Turn main manuscript into a novella…" (and every move that
  made a novella) also removes the novella while it is still empty.
* The last move stays undoable from the tree's right-click until the
  writer next saves the project, the next move, or another project; the
  autosaves do not end it.
* Video Studio: removing an action or an image deletes its files only when
  the editor closes with the change kept, and only files nothing else uses.
* A checkpoint restore unpacks beside the project, then swaps, so a
  failure leaves the project unchanged (real files, rule 15).
* Plot's Remove tension / theme and Consistency's hint say what is true.
* Every delete D.12 listed asks the same question first, Cancel the default.

No model runs; HOME is a scratch folder (conftest). Every question is
answered by the test.
"""

from __future__ import annotations

import inspect
import os
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QDialog, QMenu, QMessageBox  # noqa: E402

from src.models.project import Chapter, Manuscript, ManuscriptDraft, WriterProject  # noqa: E402

YES, CANCEL = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Cancel


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)


@pytest.fixture
def boxes(monkeypatch):
    """Every box answered and recorded: questions get ``said['reply']``."""
    said = {"reply": YES, "asked": [], "shown": [], "name": "Novella 1"}

    def question(parent, title, text, buttons=None, default=None):
        said["asked"].append((title, text, default))
        return said["reply"]
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    for n in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, n, staticmethod(
            lambda *a, _n=n, **k: said["shown"].append((_n, a[1], a[2] if len(a) > 2 else ""))))
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (said["name"], True)))
    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", True)))
    return said


# ── The shared question ────────────────────────────────────────────────

def test_the_shared_question_names_the_item_says_it_cant_be_undone_and_defaults_to_cancel(
        boxes):
    from src.ui.ui_kit import confirm_delete, delete_question
    assert delete_question("place", "Old Harbor") == (
        "Delete the place “Old Harbor”?\n\nThis can't be undone.")
    assert delete_question("note") == "Delete this note?\n\nThis can't be undone."
    assert delete_question("3 map items") == "Delete 3 map items?\n\nThis can't be undone."
    assert delete_question("take", "Take 2", verb="Remove", detail="Its audio file is kept.") == (
        "Remove the take “Take 2”?\n\nIts audio file is kept.\n\nThis can't be undone.")
    long = delete_question("x", "a" * 100)                          # long names shortened …
    assert "“" + "a" * 59 + "…”" in long
    assert confirm_delete(None, "place", "Old Harbor") is True
    title, text, default = boxes["asked"][-1]
    assert (title, default) == ("Delete place?", CANCEL)              # the safe answer
    boxes["reply"] = CANCEL
    assert confirm_delete(None, "place", "Old Harbor") is False
    n = len(boxes["asked"])
    assert confirm_delete(None, "note", "", empty=True) is True       # nothing typed: no question
    assert len(boxes["asked"]) == n


# Every delete D.12 listed (and the Studio's), with what it calls to ask.
LISTED = [
    ("src.ui.worldbuilding.place_builder", "PlaceBuilderWidget._remove_place"),
    ("src.ui.worldbuilding.fauna_builder", "FaunaBuilderWidget._remove_fauna"),
    ("src.ui.worldbuilding.flora_builder", "FloraBuilderWidget._remove_flora"),
    ("src.ui.worldbuilding.mythology_builder", "MythologyBuilderWidget._remove_myth"),
    ("src.ui.worldbuilding.technology_builder", "TechnologyBuilderWidget._remove_technology"),
    ("src.ui.worldbuilding.economy_builder", "EconomyBuilderWidget._remove_economy"),
    ("src.ui.worldbuilding.economy_builder", "EconomyEditorDialog._remove_good"),
    ("src.ui.worldbuilding.economy_builder", "EconomyEditorDialog._remove_route"),
    ("src.ui.worldbuilding.magic_system_builder", "MagicSystemBuilderWidget._remove_magic_system"),
    ("src.ui.worldbuilding.planet_builder", "PlanetBuilderWidget._remove_planet"),
    ("src.ui.worldbuilding.planet_builder", "PlanetEditor._remove_moon"),
    ("src.ui.worldbuilding.planet_builder", "PlanetEditor._remove_continent"),
    ("src.ui.worldbuilding.planet_builder", "PlanetEditor._remove_city"),
    ("src.ui.worldbuilding.planet_builder", "PlanetEditor._remove_climate"),
    ("src.ui.worldbuilding.enhanced_star_system_builder",
     "EnhancedStarSystemBuilderWidget._remove_system"),
    ("src.ui.worldbuilding.enhanced_star_system_builder", "EnhancedStarSystemEditor._remove_star"),
    ("src.ui.worldbuilding.enhanced_star_system_builder", "EnhancedStarSystemEditor._remove_planet"),
    ("src.ui.worldbuilding.enhanced_star_system_builder", "PlanetEditorDialog._remove_climate_zone"),
    ("src.ui.worldbuilding.politics_builder", "PoliticsBuilderWidget._remove_system"),
    ("src.ui.worldbuilding.politics_builder", "GovernmentTreeWidget._remove_branch"),
    ("src.ui.worldbuilding.politics_builder", "GovernmentBranchEditor._remove_member"),
    ("src.ui.worldbuilding.politics_builder", "GovernmentBranchEditor._remove_power"),
    ("src.ui.worldbuilding.politics_builder", "PoliticalSystemEditor._remove_opposition"),
    ("src.ui.worldbuilding.hierarchy_builder", "HierarchyBuilderWidget._remove_hierarchy"),
    ("src.ui.worldbuilding.hierarchy_builder", "HierarchyTreeWidget._remove_node"),
    ("src.ui.worldbuilding.hierarchy_builder", "HierarchyNodeEditor._remove_responsibility"),
    ("src.ui.worldbuilding.hierarchy_builder", "HierarchyEditor._remove_ally"),
    ("src.ui.worldbuilding.hierarchy_builder", "HierarchyEditor._remove_enemy"),
    ("src.ui.worldbuilding.climate_preset_builder", "ClimatePresetBuilderWidget._remove_preset"),
    ("src.ui.worldbuilding.culture_builder", "CultureElementList._remove_element"),
    ("src.ui.worldbuilding.military_builder", "ArmyEditorDialog._remove_branch"),
    ("src.ui.worldbuilding._system_builder_base", "SystemBuilderBase._remove_system"),
    ("src.ui.worldbuilding._system_builder_base", "StringListWidget._remove"),
    ("src.ui.worldbuilding._system_builder_base", "SubRecordList._remove"),
    ("src.ui.worldbuilding.enhanced_map_canvas", "EnhancedMapCanvas.show_context_menu"),
    ("src.ui.worldbuilding.enhanced_map_canvas", "EnhancedMapCanvas.keyPressEvent"),
    ("src.ui.plot.plot_manager", "PlotManagerWidget._remove_event_by_id"),
    ("src.ui.plot.plot_manager", "PlotManagerWidget._remove_subplot"),
    ("src.ui.plot.plot_manager", "PlotManagerWidget._remove_promise"),
    ("src.ui.plot.plot_manager", "PlotManagerWidget._remove_tension"),
    ("src.ui.plot.plot_manager", "PlotManagerWidget._remove_theme"),
    ("src.ui.characters_widget", "CharacterWidget._remove_snapshot"),
    ("src.ui.characters_widget", "CharacterWidget._remove_love_interest"),
    ("src.ui.characters.character_timeline", "CharacterTimelineWidget._remove_event"),
    ("src.ui.characters.character_timeline", "LifeEventEditor._remove_witness"),
    ("src.ui.companion_panel", "CompanionPanel._delete_memory"),
    ("src.ui.companion_panel", "CompanionPanel._delete_rule"),
    ("src.ui.chapter_planner_widget", "ChapterPlannerWidget._remove_event_item"),
    ("src.ui.chapter_planner_widget", "ChapterPlannerWidget._remove_todo_item"),
    ("src.ui.chapter_planner_widget", "ChapterPlannerWidget._remove_note_entry"),
    ("src.ui.chapter_planner_widget", "ChapterPlannerWidget._remove_subplot_note"),
    ("src.ui.feedback_widget", "FeedbackWidget._remove_entry"),
    ("src.ui.grader_widget", "GraderWidget._clear_context_fields"),
    ("src.ui.video_studio.video_editor_dialog", "VideoEditorDialog._on_remove"),
    ("src.ui.video_studio.scene_editor", "SceneEditorDialog._on_remove_action"),
    ("src.ui.video_studio.scene_action_dialog", "SceneActionDialog._on_delete_image"),
]


@pytest.mark.parametrize("module,qual", LISTED)
def test_every_listed_delete_asks_the_shared_question(module, qual):
    import importlib
    obj = importlib.import_module(module)
    for part in qual.split("."):
        obj = getattr(obj, part)
    src = inspect.getsource(obj)
    assert "confirm_delete(" in src or "planner_deletes." in src, qual


def _ask_then(boxes, reply, fn):
    boxes["reply"] = reply
    n = len(boxes["asked"])
    fn()
    return boxes["asked"][n:]


def test_world_plot_companion_feedback_and_planner_deletes_ask_and_cancel_keeps(
        app, boxes, tmp_path):
    from src.models.worldbuilding_objects import Place
    from src.ui.worldbuilding.place_builder import PlaceBuilderWidget
    w = PlaceBuilderWidget()
    w.load_places([Place(id="p1", name="Old Harbor", place_type="city")])
    w.list_widget.setCurrentRow(0)
    asked = _ask_then(boxes, CANCEL, w._remove_place)
    assert [a[0] for a in asked] == ["Delete place?"] and "Old Harbor" in asked[0][1]
    assert len(w.places_list) == 1                                # Cancel keeps it
    _ask_then(boxes, YES, w._remove_place)
    assert w.places_list == []

    # Plot: Remove tension and Remove theme now say what is true.
    from src.ui.plot.plot_manager import PlotManagerWidget
    src = inspect.getsource(PlotManagerWidget._remove_tension) + inspect.getsource(
        PlotManagerWidget._remove_theme)
    assert "re-add" not in src and 'verb="Remove"' in src

    # The Companion's story memory.
    from src.ui.companion_panel import CompanionPanel
    from src.ai import story_memory
    p = WriterProject(name="P")
    panel = CompanionPanel()
    panel.set_project(p)
    story_memory.add(p, "Tobin doesn't know about the schedule")
    panel.refresh_memory()
    panel.memory_list.setCurrentRow(0)
    asked = _ask_then(boxes, CANCEL, panel._delete_memory)
    assert asked[0][0] == "Delete story memory?" and len(p.story_memory) == 1
    _ask_then(boxes, YES, panel._delete_memory)
    assert p.story_memory == []

    # Feedback: an empty entry goes without a question; one with text asks.
    from src.ui.feedback_widget import FeedbackWidget
    fw = FeedbackWidget()
    fw._feedback_data = [{"title": "", "content": ""}, {"title": "Beta reader", "content": "Slow"}]
    fw._refresh_entries()
    assert _ask_then(boxes, CANCEL, lambda: fw._remove_entry(0)) == []
    assert len(fw._feedback_data) == 1
    asked = _ask_then(boxes, CANCEL, lambda: fw._remove_entry(0))
    assert "“Beta reader”" in asked[0][1] and len(fw._feedback_data) == 1

    # The Planner: a story event with text asks; Cancel keeps it.
    from src.ui.chapter_planner_widget import ChapterPlannerWidget
    pl = ChapterPlannerWidget()
    pl._add_event_item(text="The pier collapses")
    eid = pl._event_widgets[-1].event_id
    asked = _ask_then(boxes, CANCEL, lambda: pl._remove_event_item(eid))
    assert asked[0][0] == "Delete event?" and "The pier collapses" in asked[0][1]
    assert any(e.event_id == eid for e in pl._event_widgets)
    _ask_then(boxes, YES, lambda: pl._remove_event_item(eid))
    assert not any(e.event_id == eid for e in pl._event_widgets)
    for wdg in (w, panel, fw, pl):
        wdg.deleteLater()


def test_the_critique_context_clear_asks_only_when_something_is_there(app, boxes):
    from src.ui.grader_widget import GraderWidget
    g = GraderWidget()
    assert _ask_then(boxes, CANCEL, g._clear_context_fields) == []      # all empty: no question
    g.tone_edit.setPlainText("wry") if hasattr(g.tone_edit, "setPlainText") else \
        g.tone_edit.setText("wry")
    asked = _ask_then(boxes, CANCEL, g._clear_context_fields)
    assert asked[0][:2] == ("Clear 7 context fields?",
                            "Clear 7 context fields?\n\nThis can't be undone.")
    text = g.tone_edit.toPlainText() if hasattr(g.tone_edit, "toPlainText") else g.tone_edit.text()
    assert text == "wry"
    assert _ask_then(boxes, CANCEL, lambda: g._clear_context_fields(silent=True)) == []  # a reload
    g.deleteLater()


def test_the_consistency_hint_says_only_the_open_chapter_can_be_undone():
    src = Path("src/ui/consistency_dialog.py").read_text()
    assert "can be undone per chapter" not in src
    assert ("Only the open chapter's changes can be undone (Ctrl+Z in it); the "
            "other chapters are changed directly, with no undo.") in src.replace(
        '"\n                      "', "")


# ── Undo: the empty novella, and until the next save ───────────────────

def _project(tmp_path, drafts=True, novella=False):
    path = tmp_path / "Saga.writerproj"
    p = WriterProject(name="Saga", manuscript=Manuscript(title="Main Manuscript"))
    p.manuscript.chapters = [Chapter(id=f"m{i}", number=i, title=t, content=f"Main {i}.")
                             for i, t in enumerate(["The Storm", "The Pier", "The Letter"], 1)]
    if novella:
        fall = p.create_subproject("The Fall")
        fall.manuscript.chapters = [Chapter(id="f1", number=1, title="Fall 1", content="Fall 1.")]
    p._normalize_manuscript_roots()
    if drafts:
        p.drafts = [ManuscriptDraft(id="d1", name="Main draft",
                                    chapters=[Chapter(id="x", number=1, title="X", content="x")])]
    p.save_project(str(path))
    p.save_project(str(path))
    for ch in p.manuscript.chapters:
        (tmp_path / ch.folder_path / "notes.txt").write_text(f"Notes for {ch.title}.")
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


def _files(root: Path):
    return {str(f.relative_to(root)): f.read_bytes() for f in root.rglob("*")
            if f.is_file() and "chapter_" in str(f.relative_to(root))}


def _ids(p, scope):
    return [c.id for c in p.get_manuscript_for(scope).chapters]


def _menu_undo(w, scope=None):
    menu, actions = w.manuscript_tree.manuscript_menu(scope)
    return next((a for a in actions if a.text().startswith("Undo the last move")), None), actions


def test_undo_from_the_tree_after_the_status_bar_has_gone_removes_the_empty_novella(
        app, tmp_path, boxes):
    p = _project(tmp_path)
    win, w = _editor(app, p)
    before = _files(tmp_path)
    assert _menu_undo(w)[0] is None                              # no move yet: no entry
    assert w._create_novella_from_main("Novella 1")
    sp = p.subprojects[0]
    box = [b for b in boxes["shown"] if b[1] == "Chapters Moved"][0]
    assert box[2].endswith(
        "Undo is on the status bar for 30 seconds, and on the manuscript tree's right-click "
        "until you next save the project yourself (Save Project, Ctrl+S; the app's own "
        "autosaves don't count), make another move or close the app.")
    win.statusBar().clearMessage()                               # the 30 seconds are over
    assert not win._tree_undo_btn.isVisible()
    p.save_project(p.project_path)                               # an autosave: Undo stays
    act, actions = _menu_undo(w, sp.id)
    assert act.text() == "Undo the last move (3 chapters to Novella 1)"
    actions[act]()
    app.processEvents()
    assert _ids(p, None) == ["m1", "m2", "m3"] and p.get_subproject(sp.id) is None
    assert [(d.id, d.subproject_id) for d in p.drafts] == [("d1", None)]
    assert _files(tmp_path) == before                             # every file back, nothing lost
    assert not (tmp_path / "subprojects" / sp.id).exists()
    assert win.statusBar().currentMessage() == "Put back where it was. “Novella 1” was removed."
    again = WriterProject.load_project(p.project_path)
    assert again.subprojects == [] and [c.id for c in again.manuscript.chapters] == [
        "m1", "m2", "m3"]
    assert _menu_undo(w)[0] is None                               # used: gone


def test_a_novella_with_something_added_since_is_kept_and_undo_says_so(app, tmp_path, boxes):
    p = _project(tmp_path, drafts=False)
    win, w = _editor(app, p)
    assert w._create_novella_from_main("Novella 1")
    sp = p.subprojects[0]
    extra = Chapter(id="n9", number=4, title="New in the novella", content="Fresh.")
    sp.manuscript.chapters.append(extra)                          # added since the move
    assert w.manuscript_tree.undo_last()
    assert _ids(p, None) == ["m1", "m2", "m3"] and _ids(p, sp.id) == ["n9"]
    assert win.statusBar().currentMessage() == (
        "Put back where it was. “Novella 1” was kept: it has chapters.")


def test_the_writers_save_another_move_or_another_project_ends_the_tree_undo(
        app, tmp_path, boxes):
    from src.ui import manuscript_tree as mt
    p = _project(tmp_path, novella=True, drafts=False)
    win, w = _editor(app, p)
    tree = w.manuscript_tree
    fall = p.subprojects[0].id
    assert tree.move_to([(None, "m3")], fall)
    assert tree.undo_available()
    # The chapter's right-click has it too, under Move to ▸.
    menu = QMenu()
    menu.addAction("Rename")
    menu.addSeparator()
    menu.addAction("Delete Chapter")
    tree._menu_chapters = [(fall, "m3")]
    tree.fill_move_menu(menu)
    texts = [a.text() for a in menu.actions()]
    at = texts.index("Undo the last move (“The Letter” to The Fall)")
    assert texts[at - 1] == "Move to" and "Delete Chapter" in texts[at:]
    tree._menu_chapters = None
    mt.forget_last(w)                                             # File ▸ Save Project
    assert not tree.undo_available() and _menu_undo(w)[0] is None
    assert not tree.undo_last()
    assert _ids(p, fall) == ["f1", "m3"]                          # nothing moved
    # The call line is in the writer's save, not in the autosave.
    src = Path("src/ui/main_window.py").read_text()
    save = src[src.index("    def _save_to_path"):src.index("    def _flush_video_studio_autosave")]
    auto = src[src.index("    def _auto_save_project"):src.index("    def _find_chapter_by_id")]
    assert "manuscript_tree.forget_last(" in save and "forget_last" not in auto
    # Another project open: the old move is not offered there.
    assert tree.move_to([(fall, "m3")], None)
    assert tree.undo_available()
    (tmp_path / "other").mkdir()
    q = _project(tmp_path / "other", drafts=False)
    w.set_project(q)
    w.load_manuscript(q.manuscript)
    assert not tree.undo_available()


def test_move_to_a_new_novella_undo_removes_it_and_the_words_promise_it(app, tmp_path, boxes):
    from src.ui import manuscript_tree as mt
    assert "removes “Novella 1” (unless something has been added to it or saved for it since)" in \
        mt.undo_note(1, "Novella 1", new=True)
    p = _project(tmp_path, drafts=False)
    _win, w = _editor(app, p)
    assert w.manuscript_tree.move_to_new_novella([(None, "m2")])
    sp = p.subprojects[0]
    assert _ids(p, sp.id) == ["m2"]
    assert w.manuscript_tree.undo_last()
    assert _ids(p, None) == ["m1", "m2", "m3"] and p.subprojects == []


def test_undo_waits_while_a_draft_is_open(app, tmp_path, boxes):
    p = _project(tmp_path, novella=True, drafts=False)
    _win, w = _editor(app, p)
    fall = p.subprojects[0].id
    assert w.manuscript_tree.move_to([(None, "m1")], fall)
    draft = p.create_draft_from_current("Try")
    w.switch_to_draft(draft)
    assert not w.manuscript_tree.undo_last()
    assert w.manuscript_tree.undo_available()                     # still there for later
    assert any(b[0] == "information" for b in boxes["shown"])


# ── Video Studio: files go only when the change is kept ────────────────

def _studio_project(tmp_path):
    from src.video_studio.models import ActionImage, Scene, VideoStudio
    p = WriterProject(name="S")
    p.video_studio = VideoStudio()
    scene = Scene(name="Pier")
    p.video_studio.scenes.append(scene)
    folder = tmp_path / "S_video_studio"
    folder.mkdir()
    a1 = scene.add_action(name="Mara runs")
    a2 = scene.add_action(name="The pier falls")
    imgs = {}
    for name in ("one.png", "two.png", "shared.png"):
        (folder / name).write_bytes(b"\x89PNG " + name.encode())
        (folder / (name + ".json")).write_text("{}")
    for a, names in ((a1, ("one.png", "shared.png")), (a2, ("two.png", "shared.png"))):
        for n in names:
            img = ActionImage(file_path=str(folder / n), sidecar_path=str(folder / (n + ".json")))
            a.images.append(img)
            imgs[(a.name, n)] = img
    return p, scene, a1, a2, folder


def test_removing_an_action_deletes_its_unshared_images_only_when_the_editor_closes(
        app, tmp_path, boxes):
    from src.ui.video_studio.scene_editor import SceneEditorDialog
    p, scene, a1, a2, folder = _studio_project(tmp_path)
    dlg = SceneEditorDialog(scene, project=p, project_dir=str(tmp_path))
    dlg._refresh_actions_list()
    dlg._actions_list.setCurrentRow(0)
    asked = _ask_then(boxes, CANCEL, dlg._on_remove_action)
    assert asked[0][0] == "Remove action?" and "“Mara runs”" in asked[0][1]
    assert "Its 2 image file(s) are deleted when you close this window" in asked[0][1]
    assert [a.name for a in scene.actions] == ["Mara runs", "The pier falls"]   # Cancel: kept
    _ask_then(boxes, YES, dlg._on_remove_action)
    assert [a.name for a in scene.actions] == ["The pier falls"]
    assert (folder / "one.png").exists() and (folder / "one.png.json").exists()  # still open
    dlg.reject()                                                  # Close keeps the change
    assert not (folder / "one.png").exists() and not (folder / "one.png.json").exists()
    assert (folder / "shared.png").read_bytes() == b"\x89PNG shared.png"         # still used
    assert (folder / "two.png").exists()


def test_deleting_an_image_waits_for_close_and_a_rejected_close_deletes_nothing(
        app, tmp_path, boxes):
    from src.ui.video_studio.scene_action_dialog import SceneActionDialog
    p, scene, a1, _a2, folder = _studio_project(tmp_path)
    dlg = SceneActionDialog(a1, project=p, scene=scene)
    dlg._refresh_image_list()
    row = next(i for i in range(dlg._images_list.count())
               if a1.images[0].id == dlg._images_list.item(i).data(0x0100))
    dlg._images_list.setCurrentRow(row)
    asked = _ask_then(boxes, YES, dlg._on_delete_image)
    assert asked[0][0] == "Delete image?" and "The file is deleted when you close this window" \
        in asked[0][1]
    assert [i.file_path for i in a1.images] == [str(folder / "shared.png")]
    assert (folder / "one.png").exists()                          # not while open
    dlg._pending_removals.finish(False, p.video_studio)           # a close that keeps nothing
    assert (folder / "one.png").exists()
    # Kept this time: the file goes when the window closes.
    dlg._pending_removals.add(str(folder / "one.png"), str(folder / "one.png.json"))
    dlg.done(QDialog.DialogCode.Accepted)
    assert not (folder / "one.png").exists()
    assert (folder / "shared.png").exists() and (folder / "two.png").exists()


def test_a_file_named_anywhere_else_in_the_studio_is_never_deleted(tmp_path):
    from src.video_studio.pending_removals import PendingRemovals, still_used
    p, scene, a1, a2, folder = _studio_project(tmp_path)
    assert still_used(str(folder / "shared.png"), p.video_studio)
    assert still_used(str(folder / "anything.png"), None)         # can't tell: keep
    a2.images = []
    a1.images = []
    pr = PendingRemovals()
    pr.add(str(folder / "two.png"))
    removed, left = pr.finish(True, p.video_studio)
    assert removed == [str(folder / "two.png")] and left == []


# ── Checkpoint restore: unpack beside, then swap ───────────────────────

def _cp_project(tmp_path):
    proj = tmp_path / "Book"
    (proj / "chapters" / "chapter_001").mkdir(parents=True)
    (proj / "Book.writerproj").write_text('{"name": "Book", "v": 1}')
    (proj / "chapters" / "chapter_001" / "revision_001.md").write_text("Old text.")
    (proj / "Book_video_studio").mkdir()
    (proj / "Book_video_studio" / "take.wav").write_bytes(b"RIFF....")
    return proj


def _all(root: Path):
    return {str(f.relative_to(root)): f.read_bytes() for f in root.rglob("*")
            if f.is_file() and "_checkpoints" not in f.relative_to(root).parts}


def _checkpointed(tmp_path):
    from src.services import project_checkpoint as pc
    proj = _cp_project(tmp_path)
    cp = pc.create_checkpoint(proj, "Before", include_video_studio=False)
    (proj / "Book.writerproj").write_text('{"name": "Book", "v": 2}')
    (proj / "chapters" / "chapter_001" / "revision_001.md").write_text("New text.")
    (proj / "chapters" / "chapter_002").mkdir()
    (proj / "chapters" / "chapter_002" / "revision_001.md").write_text("A new chapter.")
    return pc, proj, cp


def test_a_restore_that_works_is_the_checkpoint_and_keeps_the_video_studio(tmp_path):
    pc, proj, cp = _checkpointed(tmp_path)
    auto = pc.restore_checkpoint(proj, cp)
    files = _all(proj)
    assert files["chapters/chapter_001/revision_001.md"] == b"Old text."
    assert "chapters/chapter_002/revision_001.md" not in files
    assert files["Book_video_studio/take.wav"] == b"RIFF...."
    assert auto is not None and Path(auto.zip_path).exists()
    assert not [d for d in (proj / "_checkpoints").iterdir() if d.is_dir()]   # nothing left over


def test_a_failure_while_unpacking_leaves_the_project_unchanged(tmp_path, monkeypatch):
    pc, proj, cp = _checkpointed(tmp_path)
    before = _all(proj)
    real, calls = zipfile.ZipFile.extract, []

    def flaky(self, member, path=None, pwd=None):
        calls.append(member)
        if len(calls) == 2:
            raise OSError("No space left on device")
        return real(self, member, path, pwd)
    monkeypatch.setattr(zipfile.ZipFile, "extract", flaky)
    with pytest.raises(OSError):
        pc.restore_checkpoint(proj, cp)
    assert _all(proj) == before                                    # truly unchanged


def test_a_failure_during_the_swap_puts_everything_back(tmp_path, monkeypatch):
    pc, proj, cp = _checkpointed(tmp_path)
    before = _all(proj)
    real, calls = pc._rename, []

    def flaky(s, t):
        calls.append(s)
        if len(calls) == 4:                                        # after some are moved in
            raise OSError("the disk said no")
        real(s, t)
    monkeypatch.setattr(pc, "_rename", flaky)
    with pytest.raises(OSError) as err:
        pc.restore_checkpoint(proj, cp)
    assert getattr(err.value, "unchanged", True)
    assert _all(proj) == before


def test_when_putting_back_fails_too_it_says_where_everything_is_and_nothing_is_lost(
        tmp_path, monkeypatch):
    pc, proj, cp = _checkpointed(tmp_path)
    before = _all(proj)
    real, calls = pc._rename, []

    def broken(s, t):
        calls.append(s)
        if len(calls) >= 4:
            raise OSError("the disk said no")
        real(s, t)
    monkeypatch.setattr(pc, "_rename", broken)
    with pytest.raises(pc.RestoreIncomplete) as err:
        pc.restore_checkpoint(proj, cp)
    msg = str(err.value)
    assert ".before-restore-" in msg and ".restore-" in msg and not err.value.unchanged
    # Every file the project had is still on disk, in the project or set aside.
    everywhere = {}
    for f in proj.rglob("*"):
        if f.is_file() and f.suffix != ".zip" and not f.name.startswith("_meta_"):
            rel = f.relative_to(proj).parts
            if rel[0] == "_checkpoints" and rel[1].startswith(".before-restore-"):
                rel = rel[2:]
            elif rel[0] == "_checkpoints":
                continue
            everywhere.setdefault("/".join(rel), f.read_bytes())
    for name, data in before.items():
        assert name in everywhere, name


def test_the_restore_box_says_unchanged_only_when_it_is():
    src = Path("src/ui/project_checkpoints_dialog.py").read_text()
    assert 'getattr(e, "unchanged", True)' in src
    assert "was either not needed or" not in src


def test_a_project_from_before_opens_saves_and_reopens_unchanged(tmp_path):
    p = _project(tmp_path)
    again = WriterProject.load_project(p.project_path)
    again.save_project(p.project_path)
    third = WriterProject.load_project(p.project_path)
    assert [(c.id, c.title, c.content) for c in third.manuscript.chapters] == [
        (c.id, c.title, c.content) for c in p.manuscript.chapters]
