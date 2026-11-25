"""R.7: one state file per project, not per folder; nothing lost on the way."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.models.project import Chapter, WriterProject


@pytest.fixture(autouse=True)
def _real_companion_paths(monkeypatch):
    """conftest sends companion state to a fixed temporary file; these tests
    need the real naming, still inside each test's temporary folder."""
    import importlib
    import src.data.companion_state as cs
    monkeypatch.setattr(cs, "state_path", importlib.reload(cs).state_path)


def _project(folder, name):
    p = WriterProject(name=name)
    p.manuscript.chapters = [Chapter(id="c1", number=1, title="One", content="Rain fell.")]
    p.project_path = str(folder / f"{name}.writerproj")
    return p


def test_two_projects_in_one_folder_keep_their_own_state(tmp_path):
    from src.ai import chapter_stages as cst
    from src.data import companion_state as cs
    from src.data import readiness_state as rs
    a, b = _project(tmp_path, "Alpha"), _project(tmp_path, "Beta")
    assert rs.readiness_path(a) == tmp_path / "Alpha.readiness.json"
    assert cs.state_path(b) == tmp_path / "Beta.companion_state.json"
    cst.set_stage(a, None, ["c1"], "copyedit")
    rs.update(a, lambda d: d.setdefault("dismissed", {}).update({"spelling:teh": {}}))
    assert cst.stage_of(a, None, "c1") == "copyedit"
    assert cst.stage_of(b, None, "c1") == ""                    # not shared any more
    assert "spelling:teh" in rs.dismissed_keys(a) and not rs.dismissed_keys(b)
    cs.save(a, {"chapters": {"c1": {"x": 1}}})
    assert cs.load(b) == {} and cs.load(a)["chapters"]["c1"]["x"] == 1


def test_a_project_with_only_the_old_shared_files_keeps_everything(tmp_path):
    from src.ai import chapter_stages as cst
    from src.data import companion_state as cs
    from src.data import readiness_state as rs
    old_r = {"format_version": 1, "dismissed": {"spelling:teh": {"as": "not a problem"}},
             "manuscripts": {"main": {"route": "self",
                                      "chapters": {"c1": {"stage": "line"}}}}, "extra": [1]}
    old_c = {"chapters": {"c1": {"stopped_at": 42}}, "dismissed": ["n1"]}
    (tmp_path / "readiness.json").write_text(json.dumps(old_r))
    (tmp_path / "companion_state.json").write_text(json.dumps(old_c))
    before_r = (tmp_path / "readiness.json").read_bytes()
    before_c = (tmp_path / "companion_state.json").read_bytes()
    p = _project(tmp_path, "Teller County")

    assert cst.stage_of(p, None, "c1") == "line"                # read from the old file
    assert "spelling:teh" in rs.dismissed_keys(p)
    assert cs.load(p)["chapters"]["c1"]["stopped_at"] == 42
    assert not rs.readiness_path(p).exists()                    # reading writes nothing

    cst.set_stage(p, None, ["c1"], "copyedit")                  # the first save
    data = cs.load(p)
    data["chapters"]["c1"]["seen"] = True
    cs.save(p, data)

    own = json.loads(rs.readiness_path(p).read_text())
    assert own["extra"] == [1] and own["manuscripts"]["main"]["route"] == "self"
    assert own["dismissed"] == old_r["dismissed"]               # everything carried over
    assert own["manuscripts"]["main"]["chapters"]["c1"]["stage"] == "copyedit"
    assert json.loads(cs.state_path(p).read_text())["dismissed"] == ["n1"]
    # The old shared files are byte-for-byte as they were (an older app still reads them).
    assert (tmp_path / "readiness.json").read_bytes() == before_r
    assert (tmp_path / "companion_state.json").read_bytes() == before_c


def test_an_unreadable_old_file_is_left_alone(tmp_path):
    from src.data import readiness_state as rs
    (tmp_path / "readiness.json").write_text("{half")
    p = _project(tmp_path, "Alpha")
    assert rs.load(p)["manuscripts"] == {}
    rs.update(p, lambda d: d.update(route_seen=True))
    assert (tmp_path / "readiness.json").read_text() == "{half"   # not moved, not changed
    assert json.loads(rs.readiness_path(p).read_text())["route_seen"] is True


def test_stored_proofreading_is_found_before_and_after_the_changeover(tmp_path):
    from src.data import readiness_state as rs
    from src.utils import proof_store
    para = "Their was a storm."
    key = proof_store.key(para)
    stored = {proof_store.KEY: {"paragraphs": {key: [{"s": 0, "e": 5, "t": "Their",
                                                      "r": "There"}]}, "model": "m"}}
    (tmp_path / "readiness.json").write_text(json.dumps({"format_version": 1, **stored}))
    p = _project(tmp_path, "Alpha")
    proof_store.clear()
    proof_store.load(p)
    assert key in proof_store._entries                          # from the old shared file
    rs.update(p, lambda d: d.update(x=1))
    proof_store.clear()
    proof_store.load(p)
    assert key in proof_store._entries                          # from the project's own file


def test_an_unsaved_project_keeps_its_place(tmp_path):
    from src.data import state_files
    p = WriterProject(name="No Path")
    assert state_files.own_path(p, "readiness", "readiness").parent.name == "readiness"
    assert state_files.legacy_path(p, "readiness.json") is None
