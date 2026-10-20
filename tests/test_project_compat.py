"""Backward/forward compatibility of the project file format.

Run:
    python -m tests.test_project_compat

Covers upgrading pre-subproject (format 1) projects without corrupting
them: loading never rewrites a healthy old file, the first save keeps a
backup of the original, legacy flat-file chapters migrate safely, all
original data survives a load/save round trip, subprojects lost by an
older app version's save are recovered, and fields written by a newer
version are preserved.
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

from src.models.project import (  # noqa: E402
    CURRENT_SCHEMA_VERSION, Chapter, Manuscript, WriterProject,
)

V1_FIXTURE = ROOT / "test_project" / "project.json"
VOLATILE = {"updated_at", "project_path", "schema_version"}
# Recomputed from the chapter files on load — refreshing them is correct.
DERIVED = {"word_count", "total_word_count"}


def _v1_project_dir():
    """A format-1 project on disk: fixture JSON + chapter folders."""
    d = Path(tempfile.mkdtemp(prefix="wa_compat_"))
    data = json.loads(V1_FIXTURE.read_text())
    assert "schema_version" not in data and "subprojects" not in data
    for i, ch in enumerate(data["manuscript"]["chapters"], 1):
        folder = d / f"chapters/chapter_{i:03d}"
        folder.mkdir(parents=True)
        (folder / "revision_001.md").write_text(f"Old prose of chapter {i}.")
        ch.update(folder_path=f"chapters/chapter_{i:03d}", number=i,
                  file_path=f"chapters/chapter_{i:03d}/revision_001.md",
                  active_revision_number=1,
                  revisions=[{"revision_number": 1, "file_path":
                              f"chapters/chapter_{i:03d}/revision_001.md"}])
    data["drafts"] = [{"id": "d1", "name": "Old draft", "chapters": []}]
    path = d / "Old.writerproj"
    path.write_text(json.dumps(data, indent=2))
    return d, path


def _strip(obj, keys=VOLATILE):
    if isinstance(obj, dict):
        return {k: _strip(v, keys) for k, v in obj.items() if k not in keys}
    if isinstance(obj, list):
        return [_strip(v, keys) for v in obj]
    return obj


def _subset(old, new, path="$"):
    """Every value in ``old`` is present and equal in ``new``."""
    if isinstance(old, dict):
        assert isinstance(new, dict), path
        for k, v in old.items():
            assert k in new, f"{path}.{k} missing after save"
            _subset(v, new[k], f"{path}.{k}")
    elif isinstance(old, list):
        assert isinstance(new, list) and len(old) == len(new), path
        for i, (a, b) in enumerate(zip(old, new)):
            _subset(a, b, f"{path}[{i}]")
    elif old not in ("", None) or new not in ("", None):
        # content fields are blanked in JSON by design (prose lives in files)
        assert old == new or path.endswith((".content", ".html_content")), \
            f"{path}: {old!r} → {new!r}"


def test_loading_healthy_old_file_does_not_rewrite_it():
    d, path = _v1_project_dir()
    before = path.read_bytes()
    p = WriterProject.load_project(str(path))
    assert path.read_bytes() == before
    assert not list(d.glob("*.v1-backup*"))
    assert p._loaded_schema_version == 1
    assert [c.content for c in p.manuscript.chapters][0] == "Old prose of chapter 1."
    shutil.rmtree(d)


def test_first_save_backs_up_original_once():
    d, path = _v1_project_dir()
    original = path.read_bytes()
    p = WriterProject.load_project(str(path))
    p.save_project(str(path))
    backup = path.with_name(path.name + ".v1-backup")
    assert backup.read_bytes() == original
    assert json.loads(path.read_text())["schema_version"] == CURRENT_SCHEMA_VERSION
    p.save_project(str(path))
    assert len(list(d.glob("*.v1-backup*"))) == 1  # only once per load
    # Reloaded as current format: no further backups.
    p2 = WriterProject.load_project(str(path))
    p2.save_project(str(path))
    assert len(list(d.glob("*.v1-backup*"))) == 1
    shutil.rmtree(d)


def test_existing_backup_is_never_overwritten():
    d, path = _v1_project_dir()
    backup = path.with_name(path.name + ".v1-backup")
    backup.write_text("an older backup")
    WriterProject.load_project(str(path)).save_project(str(path))
    assert backup.read_text() == "an older backup"
    assert len(list(d.glob("*.v1-backup-*"))) == 1  # timestamped sibling
    shutil.rmtree(d)


def test_round_trip_preserves_every_original_value():
    d, path = _v1_project_dir()
    old = _strip(json.loads(path.read_text()), VOLATILE | DERIVED)
    p = WriterProject.load_project(str(path))
    p.save_project(str(path))
    new = _strip(json.loads(path.read_text()), VOLATILE | DERIVED)
    _subset(old, new)
    assert new["subprojects"] == [] and new["active_subproject_id"] is None
    assert new["drafts"][0]["subproject_id"] is None  # old drafts → main
    for i in range(1, len(p.manuscript.chapters) + 1):
        assert (d / f"chapters/chapter_{i:03d}/revision_001.md").read_text() \
            == f"Old prose of chapter {i}."
    assert not (d / "subprojects").exists()
    shutil.rmtree(d)


def test_legacy_flat_file_chapters_migrate_after_backup():
    d = Path(tempfile.mkdtemp(prefix="wa_flat_"))
    (d / "chapters" / "plans").mkdir(parents=True)
    (d / "chapters" / "chapter_001.md").write_text("Flat prose one.")
    (d / "chapters" / "plans" / "chapter_001_plan.md").write_text("Plan one.")
    data = {"name": "Flat", "manuscript": {"title": "Flat", "chapters": [{
        "id": "c1", "number": 1, "title": "One",
        "file_path": "chapters/chapter_001.md",
        "plan_file_path": "chapters/plans/chapter_001_plan.md"}]}}
    path = d / "Flat.writerproj"
    path.write_text(json.dumps(data))
    original = path.read_bytes()
    p = WriterProject.load_project(str(path))  # migrates + repair-saves
    assert path.with_name(path.name + ".v1-backup").read_bytes() == original
    ch = p.manuscript.chapters[0]
    assert ch.folder_path == "chapters/chapter_001"
    assert ch.content == "Flat prose one."
    assert ch.planning.outline == "Plan one."
    assert (d / "chapters/chapter_001/revision_001.md").read_text() == "Flat prose one."
    shutil.rmtree(d)


def _project_with_subproject():
    d = Path(tempfile.mkdtemp(prefix="wa_sp_"))
    path = d / "U.writerproj"
    p = WriterProject(name="U", manuscript=Manuscript(title="U"))
    m = Chapter(id=str(uuid.uuid4()), number=1, title="M1")
    m.content = "main prose"
    p.manuscript.chapters.append(m)
    sp = p.create_subproject("Novella A", "first")
    p.activate_subproject(sp.id)
    a = Chapter(id=str(uuid.uuid4()), number=1, title="A1",
                folder_root=p.manuscript.folder_root)
    a.content = "novella prose"
    p.manuscript.chapters.append(a)
    p.create_draft_from_current("A draft")
    p.save_project(str(path))
    return d, path, sp.id


def test_sidecar_written_for_each_subproject():
    d, path, sp_id = _project_with_subproject()
    side = json.loads((d / f"subprojects/{sp_id}/subproject.json").read_text())
    assert side["subproject"]["name"] == "Novella A"
    assert side["subproject"]["manuscript"]["chapters"][0]["content"] == ""
    assert len(side["draft_ids"]) == 1
    shutil.rmtree(d)


def test_subproject_recovered_after_older_app_resave():
    d, path, sp_id = _project_with_subproject()
    # What a pre-subproject build writes: unknown keys dropped.
    data = json.loads(path.read_text())
    for k in ("subprojects", "active_subproject_id", "schema_version"):
        data.pop(k, None)
    for dr in data["drafts"]:
        dr.pop("subproject_id", None)
    path.write_text(json.dumps(data))
    p = WriterProject.load_project(str(path))
    sp = p.get_subproject(sp_id)
    assert sp is not None and sp.name == "Novella A"
    assert [c.content for c in sp.manuscript.chapters] == ["novella prose"]
    assert p.get_main_manuscript().chapters[0].content == "main prose"
    assert p.drafts[0].subproject_id == sp_id
    # Recovery is persisted (load repair-saves).
    assert [s["id"] for s in json.loads(path.read_text())["subprojects"]] == [sp_id]
    shutil.rmtree(d)


def test_archived_subproject_is_not_resurrected():
    d, path, sp_id = _project_with_subproject()
    p = WriterProject.load_project(str(path))
    p.delete_subproject(sp_id, project_dir=d)
    p.save_project(str(path))
    p2 = WriterProject.load_project(str(path))
    assert p2.subprojects == []
    shutil.rmtree(d)


def test_corrupt_sidecar_is_ignored():
    d, path, sp_id = _project_with_subproject()
    (d / "subprojects" / "zz99" ).mkdir(parents=True)
    (d / "subprojects" / "zz99" / "subproject.json").write_text("{not json")
    p = WriterProject.load_project(str(path))
    assert [s.id for s in p.subprojects] == [sp_id]
    shutil.rmtree(d)


def test_fields_from_newer_versions_are_preserved():
    d, path = _v1_project_dir()
    data = json.loads(path.read_text())
    data["schema_version"] = CURRENT_SCHEMA_VERSION + 1
    data["future_feature"] = {"x": [1, 2, 3]}
    path.write_text(json.dumps(data))
    p = WriterProject.load_project(str(path))
    p.save_project(str(path))
    out = json.loads(path.read_text())
    assert out["future_feature"] == {"x": [1, 2, 3]}
    assert out["schema_version"] == CURRENT_SCHEMA_VERSION + 1  # never downgraded
    assert not list(d.glob("*-backup*"))
    shutil.rmtree(d)


def test_garbage_schema_version_treated_as_v1():
    d, path = _v1_project_dir()
    data = json.loads(path.read_text())
    data["schema_version"] = "two"
    path.write_text(json.dumps(data))
    p = WriterProject.load_project(str(path))
    assert p._loaded_schema_version == 1
    p.save_project(str(path))
    assert json.loads(path.read_text())["schema_version"] == CURRENT_SCHEMA_VERSION
    shutil.rmtree(d)


def test_new_project_has_current_version_and_no_backup():
    d = Path(tempfile.mkdtemp(prefix="wa_new_"))
    p = WriterProject(name="N", manuscript=Manuscript(title="N"))
    p.save_project(str(d / "N.writerproj"))
    p.save_project(str(d / "N.writerproj"))
    assert json.loads((d / "N.writerproj").read_text())["schema_version"] == CURRENT_SCHEMA_VERSION
    assert not list(d.glob("*-backup*"))
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
