"""1.1: the publishing route, per manuscript, kept in the readiness file."""

import json
import os
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.data import publishing_goal as pg
from src.data import safe_store
from src.models.project import Chapter, Manuscript, WriterProject


def _project(tmp_path, genre="noir thriller"):
    path = tmp_path / "book.writerproj"
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(path)
    p.prose_profile.genre = genre
    ch = Chapter(id=str(uuid.uuid4()), number=1, title="One", folder_root=p.manuscript.folder_root)
    ch.content = "word " * 1200
    p.manuscript.chapters.append(ch)
    return path, p


def test_defaults_with_nothing_set(tmp_path):
    _, p = _project(tmp_path)
    goal = pg.publishing_goal(p)
    assert goal.route == "agent" and goal.kind == "novel"
    assert goal.genre == "thriller" and goal.typical == (80_000, 100_000)
    assert goal.words == 1200
    assert not pg.readiness_path(p).exists()          # reading never creates the file


def test_route_survives_save_and_load(tmp_path):
    path, p = _project(tmp_path)
    p.save_project(str(path))
    assert pg.set_route(p, None, "self")
    again = WriterProject.load_project(str(path))
    assert pg.route_for(again) == "self"
    assert pg.readiness_path(again) == tmp_path / "readiness.json"
    data = json.loads((tmp_path / "readiness.json").read_text())
    assert data == {"format_version": 1, "manuscripts": {"main": {"route": "self"}}}


def test_old_project_with_no_readiness_file_opens_with_the_default(tmp_path):
    path, p = _project(tmp_path)
    p.save_project(str(path))
    again = WriterProject.load_project(str(path))      # saved before 1.1 existed
    assert pg.route_for(again) == "agent"
    assert pg.publishing_goal(again).route_label == "Agent submission"


def test_a_novella_keeps_its_own_route(tmp_path):
    path, p = _project(tmp_path)
    sp = p.create_subproject("The Pier")
    p.save_project(str(path))
    pg.set_route(p, sp.id, "self")
    assert pg.route_for(p, sp.id) == "self"
    assert pg.route_for(p, None) == "agent"
    goal = pg.publishing_goal(p, sp.id)
    assert goal.kind == "novella" and goal.typical == pg.TYPICAL_NOVELLA


def test_other_keys_in_the_file_are_kept(tmp_path):
    path, p = _project(tmp_path)
    p.save_project(str(path))
    pg.readiness_path(p).write_text(json.dumps(
        {"format_version": 1, "manuscripts": {"main": {"route": "agent", "results": [1]}},
         "future": True}))
    pg.set_route(p, None, "self")
    data = json.loads(pg.readiness_path(p).read_text())
    assert data["future"] is True and data["manuscripts"]["main"]["results"] == [1]


def test_unreadable_file_is_set_aside_not_overwritten(tmp_path):
    path, p = _project(tmp_path)
    p.save_project(str(path))
    pg.readiness_path(p).write_text("{half")
    safe_store._reset_for_tests()
    assert pg.route_for(p) == "agent"
    assert any(".unreadable-" in f.name for f in tmp_path.iterdir())


def test_unknown_route_is_refused_and_bad_values_read_as_default(tmp_path):
    path, p = _project(tmp_path)
    p.save_project(str(path))
    with pytest.raises(ValueError):
        pg.set_route(p, None, "vanity press")
    pg.readiness_path(p).write_text(json.dumps({"manuscripts": {"main": {"route": "??"}}}))
    assert pg.route_for(p) == "agent"


def test_length_is_information_not_a_verdict(tmp_path):
    _, p = _project(tmp_path, genre="")
    goal = pg.publishing_goal(p)
    assert goal.genre == "" and goal.typical == pg.DEFAULT_NOVEL["agent"]
    note = goal.length_note
    assert "1,200 words" in note and "rough guide" in note
    for verdict in ("too short", "too long", "fail", "pass"):
        assert verdict not in note.lower()


def test_the_publishing_tab_sets_the_route(tmp_path):
    from PyQt6.QtWidgets import QApplication, QComboBox
    app = QApplication.instance() or QApplication([])
    from src.ui.agent_manager_widget import AgentManagerWidget
    path, p = _project(tmp_path)
    sp = p.create_subproject("The Pier")
    p.save_project(str(path))
    w = AgentManagerWidget()
    w.set_project(p)
    w.show()
    app.processEvents()
    combos = w.route_form.findChildren(QComboBox)
    assert len(combos) == 2                              # main + the novella
    combos[1].setCurrentIndex(combos[1].findData("self"))
    app.processEvents()
    assert pg.route_for(p, sp.id) == "self" and pg.route_for(p) == "agent"
    w.close()
