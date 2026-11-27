"""D.10: moving one chapter between manuscripts (``src/data/chapter_move``).

Rule 15: files are moved, never copied and deleted; nothing is written
over; a taken name gets a number; an id clash gets a new id; a failure
part-way puts everything back; Undo puts everything back byte for byte.
Every project here is built in ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data import chapter_move as cm
from src.models.project import Chapter, Manuscript, WriterProject


def _chapter(cid, n, title, text):
    ch = Chapter(id=cid, number=n, title=title, content=text)
    ch.planning.outline = f"Outline of {title}"
    return ch


@pytest.fixture
def saved(tmp_path):
    """Main (3 chapters, each with two drafts, an outline, saved copies, an
    annotation), novella "The Fall" (2) and novella "Ash Wardens" (1)."""
    path = tmp_path / "Saga.writerproj"
    p = WriterProject(name="Saga", manuscript=Manuscript(title="Main Manuscript"))
    p.manuscript.chapters = [_chapter(f"m{i}", i, t, f"Main chapter {i} text.")
                             for i, t in enumerate(["The Storm", "The Pier", "The Letter"], 1)]
    fall = p.create_subproject("The Fall")
    fall.manuscript.chapters = [_chapter(f"f{i}", i, f"Fall {i}", f"Fall chapter {i} text.")
                                for i in (1, 2)]
    ash = p.create_subproject("Ash Wardens")
    ash.manuscript.chapters = [_chapter("a1", 1, "Ash 1", "Ash chapter text.")]
    p._normalize_manuscript_roots()
    p.save_project(str(path))
    for _s, ms in p.iter_manuscripts():
        for ch in ms.chapters:
            ch.add_revision(notes="second", content=ch.content + " Revised.", project_dir=tmp_path)
            ch.content += " Revised."
    from src.models.project import Annotation
    p.manuscript.chapters[1].annotations.append(
        Annotation(id="n1", line_number=1, content="check the tide"))
    p.save_project(str(path))
    p.save_project(str(path))          # saved copies (backup_*.md) now exist
    p.save_project(str(path))          # and the disk is settled
    return tmp_path, path, p, fall.id, ash.id


def _tree(d: Path):
    """Every file except the project file: path → bytes."""
    return {str(f.relative_to(d)): f.read_bytes() for f in sorted(d.rglob("*"))
            if f.is_file() and not f.name.endswith(".writerproj")
            and ".pre-move-" not in f.name}


def _contents(d: Path):
    """The chapter files' contents, wherever they are (to show nothing was lost)."""
    return sorted(f.read_bytes() for f in d.rglob("*")
                  if f.is_file() and "chapter_" in str(f.parent.name) and f.suffix == ".md")


def _model(p):
    return {s: [(c.id, c.number, c.title, c.folder_path, c.content,
                 [r.file_path for r in c.revisions]) for c in ms.chapters]
            for s, ms in p.iter_manuscripts()}


def _ids(p, scope):
    return [c.id for c in p.get_manuscript_for(scope).chapters]


# ── Moving ───────────────────────────────────────────────────────────

def test_main_to_novella_moves_the_folder_with_everything_in_it(saved):
    d, path, p, fall, _ash = saved
    before = _tree(d)
    old = {k[len("chapters/chapter_002/"):]: v for k, v in before.items()
           if k.startswith("chapters/chapter_002/")}
    assert any(k.startswith("backup_") for k in old) and "plan.md" in old
    assert "revision_001.md" in old and "revision_002.md" in old
    contents = _contents(d)

    r = cm.move_chapters(p, [(None, "m2")], fall, project_file=str(path))

    assert _ids(p, None) == ["m1", "m3"] and _ids(p, fall) == ["f1", "f2", "m2"]
    new = d / "subprojects" / fall / "chapters" / "chapter_003"
    assert {str(f.relative_to(new)): f.read_bytes() for f in new.rglob("*") if f.is_file()} == old
    # The chapter after it in main took its place; nothing was lost.
    assert (d / "chapters" / "chapter_002" / "revision_002.md").read_text() == \
        "Main chapter 3 text. Revised."
    assert not (d / "chapters" / "chapter_003").exists()
    assert _contents(d) == contents
    assert r.moved[0].from_scope is None and r.moved[0].from_index == 1
    # Travels in the project file: annotations, outline, drafts list.
    moved = p.get_manuscript_for(fall).chapters[2]
    assert moved.annotations and moved.planning.outline == "Outline of The Pier"
    assert len(moved.revisions) == 2
    # Saved: the project reopens with it in the novella.
    q = WriterProject.load_project(str(path))
    ch = q.get_manuscript_for(fall).chapters[2]
    assert ch.id == "m2" and ch.content == "Main chapter 2 text. Revised."
    assert [c.title for c in q.get_main_manuscript().chapters] == ["The Storm", "The Letter"]


def test_novella_to_novella_and_novella_to_main_at_a_place(saved):
    d, path, p, fall, ash = saved
    cm.move_chapters(p, [(fall, "f1")], ash, 0, project_file=str(path))
    assert _ids(p, ash) == ["f1", "a1"] and _ids(p, fall) == ["f2"]
    assert (d / "subprojects" / ash / "chapters" / "chapter_001" / "revision_002.md").read_text() \
        == "Fall chapter 1 text. Revised."
    assert (d / "subprojects" / ash / "chapters" / "chapter_002" / "revision_002.md").read_text() \
        == "Ash chapter text. Revised."
    cm.move_chapters(p, [(ash, "a1")], None, 1, project_file=str(path))
    assert _ids(p, None) == ["m1", "a1", "m2", "m3"]
    assert [c.number for c in p.get_main_manuscript().chapters] == [1, 2, 3, 4]
    assert (d / "chapters" / "chapter_002" / "revision_002.md").read_text() == \
        "Ash chapter text. Revised."
    assert (d / "chapters" / "chapter_004" / "revision_002.md").read_text() == \
        "Main chapter 3 text. Revised."
    q = WriterProject.load_project(str(path))
    assert [c.content for c in q.get_main_manuscript().chapters][1] == "Ash chapter text. Revised."


def test_several_chapters_move_at_once_in_their_order(saved):
    d, path, p, fall, _ash = saved
    r = cm.move_chapters(p, [(None, "m3"), (None, "m1")], fall, 1, project_file=str(path))
    assert _ids(p, fall) == ["f1", "m1", "m3", "f2"] and _ids(p, None) == ["m2"]
    assert [m.chapter_id for m in r.moved] == ["m1", "m3"]
    assert (d / "chapters" / "chapter_001" / "revision_002.md").read_text() == \
        "Main chapter 2 text. Revised."


def test_files_are_renamed_never_copied(saved, monkeypatch):
    d, path, p, fall, _ash = saved
    import shutil
    for name in ("copy", "copy2", "copytree", "copyfile"):
        monkeypatch.setattr(shutil, name, lambda *a, **k: pytest.fail("a copy was made"))
    renames = []
    real = cm._rename
    monkeypatch.setattr(cm, "_rename", lambda s, t: (renames.append((s, t)), real(s, t)))
    p._backup_before_upgrade = lambda *_a: None
    cm.move_chapters(p, [(None, "m1")], fall, project_file=str(path))
    assert renames


def test_a_taken_name_gets_a_number_and_nothing_is_overwritten(saved):
    d, path, p, fall, _ash = saved
    stray = d / "subprojects" / fall / "chapters" / "chapter_003"
    stray.mkdir(parents=True)
    (stray / "revision_001.md").write_text("Something left here by hand.")
    r = cm.move_chapters(p, [(None, "m1")], fall, project_file=str(path))
    kept = d / "subprojects" / fall / "chapters" / "chapter_003_2"
    assert (kept / "revision_001.md").read_text() == "Something left here by hand."
    assert (stray / "revision_002.md").read_text() == "Main chapter 1 text. Revised."
    assert r.set_aside == [(f"subprojects/{fall}/chapters/chapter_003",
                            f"subprojects/{fall}/chapters/chapter_003_2")]
    cm.undo(p, r, project_file=str(path))
    assert (stray / "revision_001.md").read_text() == "Something left here by hand."
    assert not kept.exists()


def test_an_id_clash_gets_a_new_id_and_its_state_follows(saved):
    d, path, p, fall, _ash = saved
    # The novella's first chapter has the same id as main's "The Pier".
    p.get_manuscript_for(fall).chapters[0].id = "m2"
    p.save_project(str(path))
    from src.data import companion_state as cs
    from src.data import readiness_state as rs
    rs.update(p, lambda data: (
        rs.chapter_entry(data, None, "m2").update(stage="line"),
        data.setdefault("digest", {}).setdefault("main", {}).__setitem__("m2", {"text_hash": "x"}),
        rs.chapter_entry(data, fall, "m2").update(stage="proof")))
    data = cs.load(p)
    cs.chapter_state(data, "m2")["heard_marks"] = [{"id": "h1", "text": "The storm"}]
    cs.save(p, data)
    p.characters = []

    r = cm.move_chapters(p, [(None, "m2")], fall, project_file=str(path))
    new = r.moved[0].chapter_id
    assert new != "m2" and r.moved[0].original_id == "m2"
    fall_ids = _ids(p, fall)
    assert fall_ids == ["m2", "f2", new] and len(set(fall_ids)) == 3
    stored = rs.load(p)
    assert stored["manuscripts"][fall]["chapters"][new] == {"stage": "line"}
    assert stored["manuscripts"][fall]["chapters"]["m2"] == {"stage": "proof"}   # not overwritten
    assert stored["digest"][fall][new] == {"text_hash": "x"}
    assert "m2" not in stored["manuscripts"]["main"].get("chapters", {})
    assert cs.load(p)["chapters"][new]["heard_marks"][0]["id"] == "h1"
    q = WriterProject.load_project(str(path))
    assert q.get_manuscript_for(fall).chapters[2].id == new

    cm.undo(p, r, project_file=str(path))
    assert _ids(p, None) == ["m1", "m2", "m3"] and _ids(p, fall) == ["m2", "f2"]
    assert rs.load(p)["manuscripts"]["main"]["chapters"]["m2"] == {"stage": "line"}


def test_readiness_and_plan_state_travel_with_the_chapter(saved):
    d, path, p, fall, _ash = saved
    from src.data import readiness_state as rs

    def put(data):
        rs.chapter_entry(data, None, "m1").update(stage="copyedit", results={"x": 1})
        data["ledger"] = {"main": {"m1": {"facts": [1]}, "m3": {"facts": [3]}}}
        data["plan_matches"] = {"main": {"m1": {"the storm": ["e1"]}}}
        data["voice"] = {"main": {"m1": "not a chapter's"}}
    rs.update(p, put)
    cm.move_chapters(p, [(None, "m1")], fall, project_file=str(path))
    data = rs.load(p)
    assert data["manuscripts"][fall]["chapters"]["m1"]["stage"] == "copyedit"
    assert data["ledger"][fall]["m1"] == {"facts": [1]} and data["ledger"]["main"] == {"m3": {"facts": [3]}}
    assert data["plan_matches"][fall]["m1"] == {"the storm": ["e1"]}
    from src.ai import chapter_stages
    assert chapter_stages.stage_of(p, fall, "m1") == "copyedit"


# ── Undo ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("src,target,index,cids", [
    (None, "fall", None, ["m2"]),
    ("fall", "ash", 0, ["f1"]),
    ("fall", None, 0, ["f2", "f1"]),
    (None, "ash", 1, ["m1", "m3"]),
])
def test_undo_puts_everything_back_byte_for_byte(saved, src, target, index, cids):
    d, path, p, fall, ash = saved
    scope = {"fall": fall, "ash": ash, None: None}
    from src.data import readiness_state as rs
    rs.update(p, lambda data: [rs.chapter_entry(data, scope[src], c).update(stage="line")
                               for c in cids])
    files, model = _tree(d), _model(p)
    r = cm.move_chapters(p, [(scope[src], c) for c in cids], scope[target], index,
                         project_file=str(path))
    assert _tree(d) != files
    cm.undo(p, r, project_file=str(path))
    assert _model(p) == model
    after = _tree(d)
    assert sorted(after) == sorted(files)
    for k in files:
        assert after[k] == files[k], k
    q = WriterProject.load_project(str(path))
    assert _model(q) == model


def test_undo_after_the_writer_changed_things_still_moves_back(saved):
    d, path, p, fall, _ash = saved
    r = cm.move_chapters(p, [(None, "m1")], fall, project_file=str(path))
    from src.data import readiness_state as rs
    rs.update(p, lambda data: rs.chapter_entry(data, fall, "m1").update(stage="proof"))
    ch = p.find_chapter("m1")
    ch.content = "Written after the move."
    p.save_project(str(path))
    cm.undo(p, r, project_file=str(path))
    assert _ids(p, None) == ["m1", "m2", "m3"]
    assert (d / "chapters" / "chapter_001" / "revision_002.md").read_text() == "Written after the move."
    assert rs.load(p)["manuscripts"]["main"]["chapters"]["m1"]["stage"] == "proof"


# ── Failing part-way ─────────────────────────────────────────────────

@pytest.mark.parametrize("fail_at", [1, 2, 3, 5])
def test_a_rename_failing_part_way_puts_everything_back(saved, monkeypatch, fail_at):
    d, path, p, fall, _ash = saved
    stray = d / "subprojects" / fall / "chapters" / "chapter_003"
    stray.mkdir(parents=True)
    (stray / "note.txt").write_text("keep me")
    files, model = _tree(d), _model(p)
    calls = []
    real = cm._rename

    def flaky(s, t):
        calls.append(s)
        if len(calls) == fail_at:
            raise OSError("the disk said no")
        real(s, t)
    monkeypatch.setattr(cm, "_rename", flaky)
    with pytest.raises(cm.ChapterMoveError, match="the disk said no"):
        cm.move_chapters(p, [(None, "m1")], fall, project_file=str(path))
    assert _model(p) == model
    assert _tree(d) == files
    assert not list(d.rglob("_moving_*"))


def test_a_save_failing_puts_everything_back(saved, monkeypatch):
    d, path, p, fall, _ash = saved
    from src.data import readiness_state as rs
    rs.update(p, lambda data: rs.chapter_entry(data, None, "m1").update(stage="line"))
    files, model = _tree(d), _model(p)
    project_bytes = path.read_bytes()
    real = WriterProject.save_project
    calls = []

    def save(self, file_path, *a, **k):
        calls.append(file_path)
        if len(calls) == 2:                       # the save after the move
            raise OSError("disk full")
        return real(self, file_path, *a, **k)
    monkeypatch.setattr(WriterProject, "save_project", save)
    with pytest.raises(cm.ChapterMoveError, match="disk full"):
        cm.move_chapters(p, [(None, "m1")], fall, project_file=str(path))
    assert _model(p) == model
    assert _tree(d) == files
    assert json.loads(path.read_bytes())["manuscript"] == json.loads(project_bytes)["manuscript"]


def test_nothing_to_move_and_unknown_chapters(saved):
    d, path, p, fall, _ash = saved
    assert cm.move_chapters(p, [(fall, "f1")], fall, project_file=str(path)) is None
    with pytest.raises(cm.ChapterMoveError):
        cm.move_chapters(p, [(None, "nope")], fall, project_file=str(path))
    with pytest.raises(cm.ChapterMoveError):
        cm.move_chapters(p, [(None, "m1")], "gone", project_file=str(path))


def test_an_unsaved_project_moves_in_memory_and_saves_under_the_novella(tmp_path):
    p = WriterProject(name="New")
    p.manuscript.chapters = [_chapter("a", 1, "A", "Alpha."), _chapter("b", 2, "B", "Beta.")]
    sp = p.create_subproject("N")
    cm.move_chapters(p, [(None, "a")], sp.id)
    assert _ids(p, None) == ["b"] and _ids(p, sp.id) == ["a"]
    path = tmp_path / "New.writerproj"
    p.save_project(str(path))
    assert (tmp_path / "subprojects" / sp.id / "chapters" / "chapter_001" /
            "revision_001.md").read_text() == "Alpha."
    assert (tmp_path / "chapters" / "chapter_001" / "revision_001.md").read_text() == "Beta."


# ── Projects from before the piece ───────────────────────────────────

def test_a_project_from_before_opens_and_saves_unchanged(saved):
    """Rule 11: a project saved before D.10 opens, saves and reopens with
    its chapter text unchanged and no new fields in its file."""
    d, path, p, fall, _ash = saved
    raw = json.loads(path.read_text())
    texts = {c.id: c.content for _s, ms in p.iter_manuscripts() for c in ms.chapters}
    q = WriterProject.load_project(str(path))
    q.save_project(str(path))
    r = WriterProject.load_project(str(path))
    assert {c.id: c.content for _s, ms in r.iter_manuscripts() for c in ms.chapters} == texts
    assert set(json.loads(path.read_text())) == set(raw)
