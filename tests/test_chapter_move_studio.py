"""The Studio's cards follow a moved chapter (the small fix F.0 found).

When D.10's move gives a chapter a new id (the target already has a chapter
with its id), the Video Studio's cards, chapter decks, slide decks and chosen
chapter that meant it take the new id too; Undo and a failed move put the
old ids back. The Studio lists only the main manuscript's chapters, so only
a chapter leaving the main manuscript carries them. Built in ``tmp_path``.
"""

from __future__ import annotations

import pytest

from src.data import chapter_move as cm
from src.models.project import WriterProject
from src.video_studio.models import ChapterDeck, Scene, SlideDeckProject, VideoStudio

from tests.test_chapter_move import _ids, saved  # noqa: F401  (the fixture)


def _studio(p, cid="m2", active="m2"):
    p.video_studio = VideoStudio(
        scenes=[Scene(id="s_pier", name="At the pier", chapter_id=cid),
                Scene(id="s_storm", name="The storm", chapter_id="m1"),
                Scene(id="s_loose", name="No chapter")],
        chapter_decks=[ChapterDeck(id="deck_pier", chapter_id=cid)],
        slide_decks=[SlideDeckProject(id="sdp_pier", chapter_id=cid,
                                      working_dir="/kept/slide_decks/m2")],
        active_chapter_id=active)
    return p.video_studio


def _studio_ids(studio):
    return ({s.id: s.chapter_id for s in studio.scenes},
            [d.chapter_id for d in studio.chapter_decks],
            [d.chapter_id for d in studio.slide_decks],
            studio.active_chapter_id)


def _clash(p, path, fall):
    p.get_manuscript_for(fall).chapters[0].id = "m2"   # same id as main's "The Pier"
    p.save_project(str(path))


def test_after_a_clash_the_studio_follows_a_chapter_leaving_main(saved):
    d, path, p, fall, _ash = saved
    _clash(p, path, fall)
    studio = _studio(p)
    p.save_project(str(path))

    r = cm.move_chapters(p, [(None, "m2")], fall, project_file=str(path))
    new = r.moved[0].chapter_id
    assert new != "m2"
    scenes, decks, slides, active = _studio_ids(studio)
    assert scenes == {"s_pier": new, "s_storm": "m1", "s_loose": None}
    assert decks == [new] and slides == [new] and active == new
    assert studio.slide_decks[0].working_dir == "/kept/slide_decks/m2"   # no folder moved
    q = WriterProject.load_project(str(path))                            # and it is saved
    assert _studio_ids(q.video_studio) == (scenes, decks, slides, active)

    cm.undo(p, r, project_file=str(path))
    assert _ids(p, None) == ["m1", "m2", "m3"]
    assert _studio_ids(studio) == ({"s_pier": "m2", "s_storm": "m1", "s_loose": None},
                                   ["m2"], ["m2"], "m2")
    q = WriterProject.load_project(str(path))
    assert _studio_ids(q.video_studio) == _studio_ids(studio)


def test_a_chapter_from_a_novella_leaves_the_studio_alone(saved):
    d, path, p, fall, _ash = saved
    _clash(p, path, fall)          # the novella's "m2" clashes with main's
    studio = _studio(p)
    before = _studio_ids(studio)
    r = cm.move_chapters(p, [(fall, "m2")], None, project_file=str(path))
    assert r.moved[0].chapter_id != "m2"   # it got a new id ...
    assert _studio_ids(studio) == before   # ... but the cards mean main's "The Pier"


def test_without_a_clash_nothing_in_the_studio_changes(saved):
    d, path, p, fall, _ash = saved
    studio = _studio(p)
    before = _studio_ids(studio)
    r = cm.move_chapters(p, [(None, "m2")], fall, project_file=str(path))
    assert r.moved[0].chapter_id == "m2" and r.refs == []
    assert _studio_ids(studio) == before


def test_a_failed_move_puts_the_studio_ids_back(saved, monkeypatch):
    d, path, p, fall, _ash = saved
    _clash(p, path, fall)
    studio = _studio(p)
    p.save_project(str(path))
    before = _studio_ids(studio)
    real, calls = WriterProject.save_project, []

    def save(self, file_path, *a, **k):
        calls.append(file_path)
        if len(calls) == 2:                       # the save after the move
            raise OSError("disk full")
        return real(self, file_path, *a, **k)
    monkeypatch.setattr(WriterProject, "save_project", save)
    with pytest.raises(cm.ChapterMoveError, match="disk full"):
        cm.move_chapters(p, [(None, "m2")], fall, project_file=str(path))
    assert _studio_ids(studio) == before


def test_a_project_without_a_studio_moves_as_before(saved):
    d, path, p, fall, _ash = saved
    _clash(p, path, fall)
    p.video_studio = None
    r = cm.move_chapters(p, [(None, "m2")], fall, project_file=str(path))
    assert r.moved[0].chapter_id != "m2"
