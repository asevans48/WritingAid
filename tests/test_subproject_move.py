"""Tests for moving the main manuscript into a new novella (subproject).

Run:
    python -m tests.test_subproject_move
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


def _saved_project(n=3, revisions=True):
    """A saved project with ``n`` main chapters (2 revisions each), a plan,
    chapter backups, an annotation and a main draft."""
    d = Path(tempfile.mkdtemp(prefix="wa_move_"))
    path = d / "P.writerproj"
    p = WriterProject(name="P", manuscript=Manuscript(title="Book"))
    for i in range(1, n + 1):
        ch = Chapter(id=f"ch{i}-{uuid.uuid4().hex[:6]}", number=i, title=f"Ch {i}")
        ch.content = f"First draft of chapter {i}."
        ch.planning.outline = f"Outline {i}"
        p.manuscript.chapters.append(ch)
    p.save_project(str(path))
    if revisions:
        for ch in p.manuscript.chapters:
            ch.add_revision(notes="second", content=f"Second draft of chapter {ch.number}.",
                            project_dir=d)
            ch.content = f"Second draft of chapter {ch.number}."
    p.save_project(str(path))
    p.save_project(str(path))  # creates backup_*.md files
    p.create_draft_from_current("Main draft")
    p.save_project(str(path))
    return d, path, p


def _files(d: Path, sub: str):
    base = d / sub
    return sorted(str(f.relative_to(base)) for f in base.rglob("*") if f.is_file()) \
        if base.exists() else []


def test_accept_moves_everything_and_reloads_only_in_novella():
    d, path, p = _saved_project()
    ids = [c.id for c in p.manuscript.chapters]
    before = {f: (d / "chapters" / f).read_bytes() for f in _files(d, "chapters")}
    sp = p.create_subproject("Novella A")
    assert p.move_main_content_to_subproject(sp.id, project_file=str(path)) == 3

    # Disk: old folders gone, novella folders hold byte-identical files.
    assert _files(d, "chapters") == []
    root = f"subprojects/{sp.id}/chapters"
    after = {f: (d / root / f).read_bytes() for f in _files(d, root)}
    assert after == before, set(before) ^ set(after)
    assert list(d.glob("P.writerproj.pre-move-*"))

    # Reload: main empty, novella has every chapter with its active prose,
    # revisions (loadable from the new paths), outline and draft.
    p2 = WriterProject.load_project(str(path))
    assert p2.get_main_manuscript().chapters == []
    chs = p2.get_subproject(sp.id).manuscript.chapters
    assert [c.id for c in chs] == ids
    for c in chs:
        assert c.content == f"Second draft of chapter {c.number}."
        assert c.folder_path == f"{root}/chapter_{c.number:03d}"
        assert c.load_revision_content(d, 1) == f"First draft of chapter {c.number}."
        assert c.planning.outline == f"Outline {c.number}"
    assert p2.drafts_for_scope(None) == []
    assert [x.name for x in p2.drafts_for_scope(sp.id)] == ["Main draft"]
    # JSON: main is empty on disk too (old apps see an empty main).
    raw = json.loads(path.read_text())
    assert raw["manuscript"]["chapters"] == []
    shutil.rmtree(d)


def test_edits_after_move_save_to_the_novella():
    d, path, p = _saved_project()
    sp = p.create_subproject("Novella A")
    p.move_main_content_to_subproject(sp.id, project_file=str(path))
    p.activate_subproject(sp.id)
    p.manuscript.chapters[0].content = "Edited inside the novella."
    new = Chapter(id="new1", number=4, title="Ch 4", folder_root=p.manuscript.folder_root)
    new.content = "A brand new novella chapter."
    p.manuscript.chapters.append(new)
    # And a fresh chapter in the (now empty) main tab.
    p.activate_subproject(None)
    m = Chapter(id="m1", number=1, title="Main again", folder_root=p.manuscript.folder_root)
    m.content = "New main chapter."
    p.manuscript.chapters.append(m)
    p.save_project(str(path))

    root = d / f"subprojects/{sp.id}/chapters"
    active = p.get_subproject(sp.id).manuscript.chapters[0].active_revision_number
    assert (root / f"chapter_001/revision_{active:03d}.md").read_text() == "Edited inside the novella."
    assert (root / "chapter_004/revision_001.md").read_text() == "A brand new novella chapter."
    # The main tab's new chapter_001 is a fresh folder — no leftover files.
    assert _files(d, "chapters") == ["chapter_001/revision_001.md"]
    p2 = WriterProject.load_project(str(path))
    assert [c.content for c in p2.get_main_manuscript().chapters] == ["New main chapter."]
    assert p2.get_subproject(sp.id).manuscript.chapters[0].content == "Edited inside the novella."
    shutil.rmtree(d)


def test_decline_keeps_main_and_empty_novella():
    d, path, p = _saved_project()
    before = _files(d, "chapters")
    sp = p.create_subproject("Novella A")   # created without moving
    p.save_project(str(path))
    p2 = WriterProject.load_project(str(path))
    assert len(p2.get_main_manuscript().chapters) == 3
    assert p2.get_subproject(sp.id).manuscript.chapters == []
    assert _files(d, "chapters") == before
    shutil.rmtree(d)


def test_adding_more_novellas_after_move_does_not_disturb_others():
    d, path, p = _saved_project()
    a = p.create_subproject("A")
    p.move_main_content_to_subproject(a.id, project_file=str(path))
    a_files = {f: (d / f"subprojects/{a.id}" / f).read_bytes()
               for f in _files(d, f"subprojects/{a.id}") if f != "subproject.json"}
    b = p.create_subproject("B")
    p.activate_subproject(b.id)
    c = Chapter(id="b1", number=1, title="B1", folder_root=p.manuscript.folder_root)
    c.content = "B prose."
    p.manuscript.chapters.append(c)
    p.save_project(str(path))
    p.create_subproject("C")
    p.save_project(str(path))
    for f, data in a_files.items():
        if "backup_" not in f:
            assert (d / f"subprojects/{a.id}" / f).read_bytes() == data, f
    p2 = WriterProject.load_project(str(path))
    assert [s.name for s in p2.subprojects] == ["A", "B", "C"]
    assert len(p2.get_subproject(a.id).manuscript.chapters) == 3
    assert [x.content for x in p2.get_subproject(b.id).manuscript.chapters] == ["B prose."]
    assert p2.get_main_manuscript().chapters == []
    shutil.rmtree(d)


def test_unsaved_project_moves_in_memory_then_saves_under_novella():
    p = WriterProject(name="U", manuscript=Manuscript(title="U"))
    ch = Chapter(id="u1", number=1, title="U1")
    ch.content = "Unsaved prose."
    p.manuscript.chapters.append(ch)
    sp = p.create_subproject("N")
    assert p.move_main_content_to_subproject(sp.id) == 1
    d = Path(tempfile.mkdtemp(prefix="wa_move_"))
    p.save_project(str(d / "U.writerproj"))
    assert (d / f"subprojects/{sp.id}/chapters/chapter_001/revision_001.md").read_text() \
        == "Unsaved prose."
    assert not (d / "chapters").exists()
    shutil.rmtree(d)


def test_moves_append_after_existing_chapters_and_refuse_unknown_id():
    d, path, p = _saved_project(n=2)
    sp = p.create_subproject("N")
    p.activate_subproject(sp.id)
    t = Chapter(id="t1", number=1, title="test", folder_root=p.manuscript.folder_root)
    t.content = "Novella's own chapter."
    p.manuscript.chapters.append(t)
    p.activate_subproject(None)
    p.save_project(str(path))
    assert p.move_main_content_to_subproject(sp.id, project_file=str(path)) == 2
    p2 = WriterProject.load_project(str(path))
    chs = p2.get_subproject(sp.id).manuscript.chapters
    assert [(c.number, c.title) for c in chs] == [(1, "test"), (2, "Ch 1"), (3, "Ch 2")]
    assert [c.content for c in chs] == ["Novella's own chapter.",
                                        "Second draft of chapter 1.", "Second draft of chapter 2."]
    root = d / f"subprojects/{sp.id}/chapters"
    assert sorted(x.name for x in root.iterdir()) == ["chapter_001", "chapter_002", "chapter_003"]
    assert chs[-1].load_revision_content(d, 1) == "First draft of chapter 2."
    assert p2.get_main_manuscript().chapters == []
    try:
        p2.move_main_content_to_subproject("nope", project_file=str(path))
    except KeyError:
        pass
    else:
        raise AssertionError("should refuse unknown id")
    shutil.rmtree(d)


def _simulate_exfat(monkey_target):
    """On exFAT macOS deletes "._name" along with "name"; plain rmtree then
    hits FileNotFoundError on the companion. Reproduce that on any disk."""
    import os as _os
    real_unlink = _os.unlink

    def unlink(path, *, dir_fd=None):
        real_unlink(path, dir_fd=dir_fd)
        name = _os.path.basename(_os.fsdecode(path))
        if not name.startswith("._"):
            companion = _os.path.join(_os.path.dirname(_os.fsdecode(path)), "._" + name)
            try:
                real_unlink(companion, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
    monkey_target.unlink = unlink
    return real_unlink


def test_move_and_drop_are_true_moves_on_exfat_style_volumes():
    import os as _os
    d, path, p = _saved_project(n=2)
    # AppleDouble companions next to every chapter file, as on exFAT.
    for f in list((d / "chapters").rglob("*.md")):
        (f.parent / f"._{f.name}").write_bytes(b"\x00\x05\x16\x07metadata")
    for folder in (d / "chapters").iterdir():
        if folder.is_dir():
            (folder.parent / f"._{folder.name}").write_bytes(b"meta")
    real = _simulate_exfat(_os)
    try:
        sp = p.create_subproject("N")
        p.move_main_content_to_subproject(sp.id, project_file=str(path))
        assert p.cleanup_leftovers == []
        assert sorted(x.name for x in (d / "chapters").iterdir()) == []  # moved, not copied
        root = d / f"subprojects/{sp.id}/chapters"
        assert not any(x.name.startswith("._") for x in root.rglob("*"))  # metadata not copied
        p2 = WriterProject.load_project(str(path))
        assert [c.content for c in p2.get_subproject(sp.id).manuscript.chapters] == [
            "Second draft of chapter 1.", "Second draft of chapter 2."]
        for f in root.rglob("*.md"):
            (f.parent / f"._{f.name}").write_bytes(b"meta")
        p2.delete_subproject(sp.id, permanently=True, project_file=str(path))
        assert p2.cleanup_leftovers == []
        assert not (d / "subprojects" / sp.id).exists()
    finally:
        _os.unlink = real
    shutil.rmtree(d)


def test_copy_failure_rolls_back_cleanly():
    import shutil as _sh
    d, path, p = _saved_project()
    before_files = _files(d, "chapters")
    json_before = path.read_text()
    sp = p.create_subproject("N")
    real = _sh.copytree
    calls = {"n": 0}

    def flaky(src, dst, *a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real(src, dst, *a, **k)
    _sh.copytree = flaky
    try:
        try:
            p.move_main_content_to_subproject(sp.id, project_file=str(path))
        except OSError:
            pass
        else:
            raise AssertionError("expected failure")
    finally:
        _sh.copytree = real
    assert len(p.get_main_manuscript().chapters) == 3
    assert sp.manuscript.chapters == []
    assert _files(d, "chapters") == before_files
    assert not any(f.startswith("chapters/") for f in _files(d, f"subprojects/{sp.id}"))
    p2 = WriterProject.load_project(str(path))
    assert [c.content for c in p2.get_main_manuscript().chapters] == [
        f"Second draft of chapter {i}." for i in (1, 2, 3)]
    assert json.loads(json_before)["manuscript"]["chapters"]  # sanity
    shutil.rmtree(d)


def test_save_failure_rolls_back_model_and_copies():
    d, path, p = _saved_project()
    sp = p.create_subproject("N")
    orig_save = WriterProject.save_project
    calls = {"n": 0}

    def failing_save(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 2:  # the save after re-pointing
            raise OSError("read-only volume")
        return orig_save(self, *a, **k)
    WriterProject.save_project = failing_save
    try:
        try:
            p.move_main_content_to_subproject(sp.id, project_file=str(path))
        except OSError:
            pass
        else:
            raise AssertionError("expected failure")
    finally:
        WriterProject.save_project = orig_save
    main = p.get_main_manuscript()
    assert [c.folder_path for c in main.chapters] == [
        f"chapters/chapter_{i:03d}" for i in (1, 2, 3)]
    assert all(r.file_path.startswith("chapters/") for c in main.chapters for r in c.revisions)
    assert p.drafts[0].subproject_id is None
    assert not (d / f"subprojects/{sp.id}/chapters").exists()
    p.save_project(str(path))
    p2 = WriterProject.load_project(str(path))
    assert [c.content for c in p2.get_main_manuscript().chapters] == [
        f"Second draft of chapter {i}." for i in (1, 2, 3)]
    shutil.rmtree(d)


def test_moved_novella_survives_older_app_resave():
    d, path, p = _saved_project()
    sp = p.create_subproject("Novella A")
    p.move_main_content_to_subproject(sp.id, project_file=str(path))
    data = json.loads(path.read_text())
    for k in ("subprojects", "active_subproject_id", "schema_version"):
        data.pop(k)
    for dr in data["drafts"]:
        dr.pop("subproject_id", None)
    path.write_text(json.dumps(data))
    p2 = WriterProject.load_project(str(path))
    chs = p2.get_subproject(sp.id).manuscript.chapters
    assert [c.content for c in chs] == [f"Second draft of chapter {i}." for i in (1, 2, 3)]
    assert p2.drafts[0].subproject_id == sp.id
    shutil.rmtree(d)


def test_drop_archives_by_default_and_erases_on_request():
    d, path, p = _saved_project(n=2)
    a = p.create_subproject("A")
    p.move_main_content_to_subproject(a.id, project_file=str(path))
    b = p.create_subproject("B")
    p.activate_subproject(b.id)
    c = Chapter(id="b1", number=1, title="B1", folder_root=p.manuscript.folder_root)
    c.content = "B prose."
    p.manuscript.chapters.append(c)
    p.save_project(str(path))

    assert p.delete_subproject(b.id, permanently=True, project_file=str(path))
    assert not (d / "subprojects" / b.id).exists()
    assert not any(x.name.startswith(b.id) for x in (d / "subprojects" / "_deleted").glob("*")) \
        if (d / "subprojects" / "_deleted").exists() else True
    assert p.delete_subproject(a.id, project_file=str(path))  # archive
    archived = list((d / "subprojects" / "_deleted").glob(f"{a.id}_*"))
    assert len(archived) == 1
    assert (archived[0] / "chapters/chapter_001").is_dir()
    p2 = WriterProject.load_project(str(path))
    assert p2.subprojects == [] and p2.active_subproject_id is None
    assert p2.drafts == []  # the moved main draft belonged to A
    shutil.rmtree(d)


def test_drop_saves_before_touching_files():
    d, path, p = _saved_project(n=1)
    a = p.create_subproject("A")
    p.move_main_content_to_subproject(a.id, project_file=str(path))
    orig = WriterProject.save_project

    def failing(self, *a_, **k):
        raise OSError("read-only volume")
    WriterProject.save_project = failing
    try:
        try:
            p.delete_subproject(a.id, permanently=True, project_file=str(path))
        except OSError:
            pass
        else:
            raise AssertionError("expected failure")
    finally:
        WriterProject.save_project = orig
    # The save failed: the novella is restored in memory, the files are
    # untouched, and the file on disk still loads it with its prose.
    assert p.get_subproject(a.id) is not None and len(p.drafts) == 1
    assert len(p.get_subproject(a.id).manuscript.chapters) == 1
    assert (d / "subprojects" / a.id / "chapters").is_dir()
    p2 = WriterProject.load_project(str(path))
    assert [c.content for c in p2.get_subproject(a.id).manuscript.chapters] == [
        "Second draft of chapter 1."]
    shutil.rmtree(d)


def test_name_counter_restarts():
    p = WriterProject(name="U", manuscript=Manuscript(title="U"))
    assert p.next_subproject_name() == "Novella 1"
    s1 = p.create_subproject(p.next_subproject_name())
    s2 = p.create_subproject(p.next_subproject_name())
    s3 = p.create_subproject(p.next_subproject_name())
    assert [s.name for s in (s1, s2, s3)] == ["Novella 1", "Novella 2", "Novella 3"]
    p.delete_subproject(s2.id)
    assert p.next_subproject_name() == "Novella 2"   # fills the gap
    p.delete_subproject(s1.id)
    p.delete_subproject(s3.id)
    assert p.next_subproject_name() == "Novella 1"   # none left → starts over


def test_drop_last_then_turn_main_into_novella():
    d, path, p = _saved_project(n=2)
    a = p.create_subproject("A")
    p.save_project(str(path))
    p.delete_subproject(a.id, project_file=str(path))
    assert p.subprojects == [] and len(p.get_main_manuscript().chapters) == 2
    n = p.create_subproject(p.next_subproject_name())
    assert n.name == "Novella 1"
    p.move_main_content_to_subproject(n.id, project_file=str(path))
    p2 = WriterProject.load_project(str(path))
    assert p2.get_main_manuscript().chapters == []
    assert [c.content for c in p2.get_subproject(n.id).manuscript.chapters] == [
        "Second draft of chapter 1.", "Second draft of chapter 2."]
    # A's archived folder is never resurrected.
    assert [s.id for s in p2.subprojects] == [n.id]
    shutil.rmtree(d)


def test_turn_main_into_novella_when_novellas_exist():
    d, path, p = _saved_project(n=2)
    other = p.create_subproject("Other")
    p.activate_subproject(other.id)
    oc = Chapter(id="o1", number=1, title="O1", folder_root=p.manuscript.folder_root)
    oc.content = "Other prose."
    p.manuscript.chapters.append(oc)
    p.activate_subproject(None)
    p.save_project(str(path))
    new = p.create_subproject("From Main")
    p.move_main_content_to_subproject(new.id, project_file=str(path))
    p2 = WriterProject.load_project(str(path))
    assert [c.content for c in p2.get_subproject(other.id).manuscript.chapters] == ["Other prose."]
    assert len(p2.get_subproject(new.id).manuscript.chapters) == 2
    assert p2.get_main_manuscript().chapters == []
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
