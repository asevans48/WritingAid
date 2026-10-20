"""Tests for subprojects (novellas sharing one project's universe).

Run:
    python -m tests.test_subprojects

Covers:
  * Creation: a new subproject starts empty and never touches main.
  * Isolation: chapters of different manuscripts live in separate
    folders on disk; same chapter numbers never collide.
  * Routing: edits made through ``project.manuscript`` land in the
    active subproject; lookups by chapter id find the right chapter
    in any manuscript.
  * Round trip: save → load restores every manuscript's prose and the
    active subproject.
  * Backwards compatibility: projects without subprojects load
    unchanged, and on disk ``manuscript`` is always the main one.
  * Safety: reordering in a subproject never moves main's folders,
    cross-scope manuscript assignment is refused, deleting a
    subproject archives (not erases) its files, drafts stay scoped.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import traceback
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.project import Chapter, Manuscript, WriterProject  # noqa: E402


def _tmp_project(name="Universe"):
    d = Path(tempfile.mkdtemp(prefix="wa_subproj_"))
    path = d / "project.writerproj"
    project = WriterProject(name=name, manuscript=Manuscript(title=name))
    project.project_path = str(path)
    return d, path, project


def _add_chapter(ms: Manuscript, title: str, content: str) -> Chapter:
    # Mirrors ManuscriptEditor._add_chapter.
    ch = Chapter(id=str(uuid.uuid4()), number=len(ms.chapters) + 1,
                 title=title, folder_root=ms.folder_root)
    ch.content = content
    ms.chapters.append(ch)
    return ch


def _add_chapter_ui_legacy(ms: Manuscript, title: str, content: str) -> Chapter:
    # A caller that does not know about folder roots (e.g. older code).
    ch = Chapter(id=str(uuid.uuid4()), number=len(ms.chapters) + 1, title=title)
    ch.content = content
    ms.chapters.append(ch)
    return ch


def test_new_project_has_no_subprojects_and_main_active():
    _, _, p = _tmp_project()
    assert p.subprojects == []
    assert p.active_subproject_id is None
    assert p.get_main_manuscript() is p.manuscript


def test_create_subproject_starts_empty_and_leaves_main_untouched():
    d, path, p = _tmp_project()
    _add_chapter(p.manuscript, "Main One", "main prose one")
    p.save_project(str(path))
    sp = p.create_subproject("Novella A", "first novella")
    assert p.active_subproject_id is None, "creation must not switch scope"
    assert sp.manuscript.chapters == []
    assert sp.manuscript.folder_root == f"subprojects/{sp.id}/chapters"
    assert len(p.manuscript.chapters) == 1
    assert p.manuscript.chapters[0].content == "main prose one"
    p.activate_subproject(sp.id)
    assert p.manuscript is sp.manuscript
    assert p.manuscript.chapters == []
    p.save_project(str(path))
    p2 = WriterProject.load_project(str(path))
    assert p2.active_subproject_id == sp.id
    assert p2.manuscript.chapters == []
    assert p2.get_main_manuscript().chapters[0].content == "main prose one"
    shutil.rmtree(d)


def test_same_chapter_numbers_never_collide_on_disk():
    d, path, p = _tmp_project()
    main_ch = _add_chapter(p.manuscript, "Main 1", "MAIN CONTENT")
    sp = p.create_subproject("Novella A")
    p.activate_subproject(sp.id)
    nov_ch = _add_chapter(p.manuscript, "Nov 1", "NOVELLA CONTENT")
    p.save_project(str(path))

    assert main_ch.folder_path == "chapters/chapter_001"
    assert nov_ch.folder_path == f"subprojects/{sp.id}/chapters/chapter_001"
    assert (d / main_ch.folder_path / "revision_001.md").read_text() == "MAIN CONTENT"
    assert (d / nov_ch.folder_path / "revision_001.md").read_text() == "NOVELLA CONTENT"
    shutil.rmtree(d)


def test_chapter_created_without_root_still_lands_in_its_subproject():
    d, path, p = _tmp_project()
    _add_chapter(p.manuscript, "Main 1", "MAIN")
    sp = p.create_subproject("Novella A")
    p.activate_subproject(sp.id)
    ch = _add_chapter_ui_legacy(p.manuscript, "Nov 1", "NOV")
    p.save_project(str(path))
    assert ch.folder_path.startswith(f"subprojects/{sp.id}/"), ch.folder_path
    assert (d / "chapters/chapter_001/revision_001.md").read_text() == "MAIN"
    shutil.rmtree(d)


def test_round_trip_restores_all_manuscripts_and_active_scope():
    d, path, p = _tmp_project()
    _add_chapter(p.manuscript, "M1", "main one")
    _add_chapter(p.manuscript, "M2", "main two")
    a = p.create_subproject("A")
    b = p.create_subproject("B")
    p.activate_subproject(a.id)
    _add_chapter(p.manuscript, "A1", "alpha one")
    p.activate_subproject(b.id)
    _add_chapter(p.manuscript, "B1", "beta one")
    _add_chapter(p.manuscript, "B2", "beta two")
    p.save_project(str(path))

    p2 = WriterProject.load_project(str(path))
    assert p2.active_subproject_id == b.id
    assert [c.content for c in p2.manuscript.chapters] == ["beta one", "beta two"]
    assert [c.content for c in p2.get_main_manuscript().chapters] == ["main one", "main two"]
    assert [c.content for c in p2.get_subproject(a.id).manuscript.chapters] == ["alpha one"]

    # JSON is canonical: 'manuscript' is main even though B was active.
    raw = json.loads(path.read_text())
    assert [c["title"] for c in raw["manuscript"]["chapters"]] == ["M1", "M2"]
    assert raw["active_subproject_id"] == b.id
    # Prose is stored in files, not JSON, for subprojects too.
    for sp in raw["subprojects"]:
        for ch in sp["manuscript"]["chapters"]:
            assert ch["content"] == ""
    shutil.rmtree(d)


def test_edits_through_project_manuscript_go_to_active_subproject():
    d, path, p = _tmp_project()
    m1 = _add_chapter(p.manuscript, "M1", "main")
    a = p.create_subproject("A")
    p.activate_subproject(a.id)
    a1 = _add_chapter(p.manuscript, "A1", "alpha")
    p.manuscript.chapters[0].content = "alpha edited"
    p.activate_subproject(None)
    assert p.manuscript.chapters[0] is m1
    assert m1.content == "main"
    assert a1.content == "alpha edited"
    # Lookups by id work across manuscripts regardless of active scope.
    assert p.find_chapter(a1.id) is a1
    assert p.find_chapter_with_scope(a1.id) == (a.id, a1)
    assert p.find_chapter_with_scope(m1.id) == (None, m1)
    shutil.rmtree(d)


def test_switch_back_and_forth_does_not_lose_content():
    d, path, p = _tmp_project()
    _add_chapter(p.manuscript, "M1", "main")
    a = p.create_subproject("A")
    for i in range(5):
        p.activate_subproject(a.id)
        if i == 0:
            _add_chapter(p.manuscript, "A1", "alpha")
        p.save_project(str(path))
        p.activate_subproject(None)
        p.save_project(str(path))
    p2 = WriterProject.load_project(str(path))
    assert [c.content for c in p2.get_main_manuscript().chapters] == ["main"]
    assert [c.content for c in p2.get_subproject(a.id).manuscript.chapters] == ["alpha"]
    shutil.rmtree(d)


def test_reorder_in_subproject_does_not_touch_main_folders():
    d, path, p = _tmp_project()
    _add_chapter(p.manuscript, "M1", "main one")
    _add_chapter(p.manuscript, "M2", "main two")
    a = p.create_subproject("A")
    p.activate_subproject(a.id)
    _add_chapter(p.manuscript, "A1", "alpha one")
    _add_chapter(p.manuscript, "A2", "alpha two")
    p.save_project(str(path))

    # Same steps as ManuscriptEditor._move_chapter_down + relocation.
    chs = p.manuscript.chapters
    chs[0], chs[1] = chs[1], chs[0]
    for i, ch in enumerate(chs, 1):
        ch.relocate_to_number(i, d)
    for ch in chs:
        ch.finalize_relocation(d)
    p.save_project(str(path))

    assert (d / "chapters/chapter_001/revision_001.md").read_text() == "main one"
    assert (d / "chapters/chapter_002/revision_001.md").read_text() == "main two"
    root = d / f"subprojects/{a.id}/chapters"
    assert (root / "chapter_001/revision_001.md").read_text() == "alpha two"
    assert (root / "chapter_002/revision_001.md").read_text() == "alpha one"
    p2 = WriterProject.load_project(str(path))
    assert [c.content for c in p2.get_subproject(a.id).manuscript.chapters] == ["alpha two", "alpha one"]
    assert [c.content for c in p2.get_main_manuscript().chapters] == ["main one", "main two"]
    shutil.rmtree(d)


def test_cross_scope_manuscript_assignment_is_refused():
    _, _, p = _tmp_project()
    main = p.manuscript
    _add_chapter(main, "M1", "main")
    a = p.create_subproject("A")
    p.activate_subproject(a.id)
    # A stale editor hands back main's manuscript while A is active.
    p.manuscript = main
    assert p.get_main_manuscript() is main
    assert a.manuscript is not main
    assert p.manuscript is a.manuscript


def test_new_manuscript_object_is_adopted_by_active_scope():
    _, _, p = _tmp_project()
    a = p.create_subproject("A")
    p.activate_subproject(a.id)
    replacement = Manuscript(title="Replaced")
    p.manuscript = replacement
    p._sync_active_manuscript()
    assert a.manuscript is replacement
    assert p.get_main_manuscript() is not replacement


def test_legacy_project_without_subprojects_loads_unchanged():
    d = Path(tempfile.mkdtemp(prefix="wa_legacy_"))
    src = ROOT / "test_project" / "project.json"
    data = json.loads(src.read_text())
    assert "subprojects" not in data
    path = d / "project.json"
    path.write_text(json.dumps(data))
    p = WriterProject.load_project(str(path))
    assert p.subprojects == []
    assert p.active_subproject_id is None
    assert len(p.manuscript.chapters) == len(data["manuscript"]["chapters"])
    p.save_project(str(path))
    p2 = WriterProject.load_project(str(path))
    assert [c.title for c in p2.manuscript.chapters] == [c["title"] for c in data["manuscript"]["chapters"]]
    shutil.rmtree(d)


def test_legacy_main_chapter_folders_keep_their_paths():
    d, path, p = _tmp_project()
    _add_chapter(p.manuscript, "M1", "main one")
    p.save_project(str(path))
    raw = json.loads(path.read_text())
    # Simulate a file written before folder_root existed.
    for ch in raw["manuscript"]["chapters"]:
        ch.pop("folder_root", None)
    raw["manuscript"].pop("folder_root", None)
    path.write_text(json.dumps(raw))
    p2 = WriterProject.load_project(str(path))
    ch = p2.manuscript.chapters[0]
    assert ch.folder_path == "chapters/chapter_001"
    assert ch.content == "main one"
    shutil.rmtree(d)


def test_dangling_active_id_and_bad_subproject_data_are_repaired():
    d, path, p = _tmp_project()
    _add_chapter(p.manuscript, "M1", "main")
    p.save_project(str(path))
    raw = json.loads(path.read_text())
    raw["active_subproject_id"] = "missing"
    raw["subprojects"] = [
        {"id": "../../evil", "name": "", "manuscript": "garbage"},
        "not a dict",
    ]
    path.write_text(json.dumps(raw))
    p2 = WriterProject.load_project(str(path))
    assert p2.active_subproject_id is None
    assert len(p2.subprojects) == 1
    sp = p2.subprojects[0]
    assert "/" not in sp.id and "." not in sp.id
    assert sp.name
    assert p2.manuscript.chapters[0].content == "main"
    shutil.rmtree(d)


def test_delete_subproject_archives_files_and_drops_its_drafts():
    d, path, p = _tmp_project()
    _add_chapter(p.manuscript, "M1", "main")
    a = p.create_subproject("A")
    p.activate_subproject(a.id)
    _add_chapter(p.manuscript, "A1", "alpha")
    p.create_draft_from_current("A draft")
    p.save_project(str(path))
    assert len(p.drafts) == 1 and p.drafts[0].subproject_id == a.id

    assert p.delete_subproject(a.id, project_dir=d)
    assert p.active_subproject_id is None
    assert p.manuscript.chapters[0].content == "main"
    assert p.drafts == []
    assert not (d / "subprojects" / a.id).exists()
    archived = list((d / "subprojects" / "_deleted").iterdir())
    assert len(archived) == 1
    assert (archived[0] / "chapters/chapter_001/revision_001.md").read_text() == "alpha"
    p.save_project(str(path))
    p2 = WriterProject.load_project(str(path))
    assert p2.subprojects == []
    assert p2.manuscript.chapters[0].content == "main"
    shutil.rmtree(d)


def test_drafts_are_scoped_and_merge_into_their_own_manuscript():
    d, path, p = _tmp_project()
    m1 = _add_chapter(p.manuscript, "M1", "main")
    main_draft = p.create_draft_from_current("Main draft")
    a = p.create_subproject("A")
    p.activate_subproject(a.id)
    a1 = _add_chapter(p.manuscript, "A1", "alpha")
    a_draft = p.create_draft_from_current("A draft")
    assert main_draft.subproject_id is None
    assert a_draft.subproject_id == a.id
    assert p.drafts_for_active() == [a_draft]
    assert p.drafts_for_scope(None) == [main_draft]

    # Drop main's draft while A is active: revisions go to main, not A.
    main_revs, a_revs = len(m1.revisions), len(a1.revisions)
    p.delete_draft(main_draft.id, preserve_chapter_revisions=True)
    assert len(m1.revisions) > main_revs
    assert len(a1.revisions) == a_revs
    shutil.rmtree(d)


def test_model_dump_is_canonical():
    _, _, p = _tmp_project()
    _add_chapter(p.manuscript, "M1", "main")
    a = p.create_subproject("A")
    p.activate_subproject(a.id)
    _add_chapter(p.manuscript, "A1", "alpha")
    dumped = p.model_dump()
    assert [c["title"] for c in dumped["manuscript"]["chapters"]] == ["M1"]
    assert [c["title"] for c in dumped["subprojects"][0]["manuscript"]["chapters"]] == ["A1"]
    rebuilt = WriterProject(**json.loads(p.model_dump_json()))
    assert rebuilt.active_subproject_id == a.id
    assert [c.title for c in rebuilt.manuscript.chapters] == ["A1"]
    assert [c.title for c in rebuilt.get_main_manuscript().chapters] == ["M1"]


def test_rename_keeps_manuscript_title_in_sync():
    _, _, p = _tmp_project()
    a = p.create_subproject("A")
    assert p.rename_subproject(a.id, "  The Long Night ")
    assert a.name == "The Long Night" and a.manuscript.title == "The Long Night"
    assert p.rename_subproject(None, "Book One")
    assert p.get_main_manuscript().title == "Book One"
    assert not p.rename_subproject(a.id, "   ")


def test_folder_conflict_across_manuscripts_refuses_to_save():
    d, path, p = _tmp_project()
    m1 = _add_chapter(p.manuscript, "M1", "main")
    a = p.create_subproject("A")
    p.activate_subproject(a.id)
    a1 = _add_chapter(p.manuscript, "A1", "alpha")
    p.save_project(str(path))
    a1.folder_path = m1.folder_path  # corrupt on purpose
    try:
        p.save_project(str(path))
    except RuntimeError:
        pass
    else:
        raise AssertionError("save should refuse a cross-manuscript folder clash")
    assert (d / "chapters/chapter_001/revision_001.md").read_text() == "main"
    shutil.rmtree(d)


def _run_all() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL {t.__name__}")
            traceback.print_exc()
    print()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
