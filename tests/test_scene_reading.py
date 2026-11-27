"""7.2: the model's reading of each scene in the outline (stored results, a fake model)."""

import os
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import chapter_digest, scene_reading as sr
from src.ai import reverse_outline as ro
from src.ai.readiness import text_hash

TEXT = ("Rain fell on the harbor. Mara watched the boats.\n"
        "Later, at the inn, Tobin counted his coins.\n"
        "\n"
        "***\n"
        "\n"
        "Morning came cold and grey. Mara left.")


class FakeLLM:
    model = "fake"

    def __init__(self):
        self.calls = 0

    def generate_text(self, prompt, system, **kw):
        self.calls += 1
        return ('SCENE | Mara | watches the boats come in | none | "Rain fell on the harbor"\n'
                'SCENE | Tobin | counts his coins at the inn | he is short of money | '
                '"Later, at the inn, Tobin counted"\n'
                'SCENE | Mara | leaves at dawn | she has chosen to go | "Morning came cold"\n'
                'READER | 3 | fine | NONE')


def _project(tmp_path):
    return NS(project_path=str(tmp_path / "Book.writerproj"), name="Book")


def _store_digest(project, chapter_id, text):
    from src.data import readiness_state as rs
    entry = dict(chapter_digest.read_chapter(FakeLLM(), NS(title="One"), text),
                 text_hash=text_hash(text), v=chapter_digest.VERSION)

    def change(data):
        data.setdefault(chapter_digest.KEY, {}).setdefault(rs.scope_key(None), {})[chapter_id] = entry
    assert rs.update(project, change)
    return entry


def test_model_scenes_go_to_the_outline_scene_they_start_in(tmp_path):
    project = _project(tmp_path)
    _store_digest(project, "c1", TEXT)
    scenes = ro.outline(TEXT, [])
    assert len(scenes) == 2
    entry = sr.digest_entry(project, "c1", TEXT)
    got = sr.per_scene(entry, scenes)
    assert [len(g) for g in got] == [2, 1]                 # two model scenes before the break
    assert sr.line(got[0][0]) == "Mara · watches the boats come in → changes nothing?"
    assert sr.line(got[1][0]) == "Mara · leaves at dawn → she has chosen to go"


def test_a_scene_whose_words_were_not_found_follows_the_one_before():
    scenes = ro.outline(TEXT, [])
    entry = {"scenes": [{"start": TEXT.index("Morning"), "what": "a"},
                        {"start": -1, "what": "b"}]}
    assert [[m["what"] for m in g] for g in sr.per_scene(entry, scenes)] == [[], ["a", "b"]]


def test_an_older_drafts_reading_is_not_shown(tmp_path):
    project = _project(tmp_path)
    _store_digest(project, "c1", TEXT)
    assert sr.digest_entry(project, "c1", TEXT + " More.") is None
    assert sr.digest_entry(project, "other", TEXT) is None
    assert sr.digest_entry(None, "c1", TEXT) is None


def test_a_damaged_readiness_file_means_no_reading(tmp_path, monkeypatch):
    from src.data import safe_store
    monkeypatch.setattr(safe_store, "_notifier", None)       # no window to tell here
    project = _project(tmp_path)
    (tmp_path / "Book.readiness.json").write_text("{not json")
    assert sr.digest_entry(project, "c1", TEXT) is None


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _open_outline(view, ch, text):
    from PyQt6.QtCore import QUrl
    view.show_chapter(ch, None, text, {})
    toggle = next(i for i, (k, _) in enumerate(view._links) if k == "outline")
    view._on_link(QUrl(f"issue:{toggle}"))
    return view.toPlainText()


def test_the_outline_shows_the_models_reading_under_each_scene(app, tmp_path):
    from src.ui.readiness_issues import ChapterIssues
    project = _project(tmp_path)
    _store_digest(project, "c1", TEXT)
    view = ChapterIssues()
    view.outline_names = lambda: ["Mara", "Tobin"]
    view.outline_project = lambda: project
    ch = NS(chapter_id="c1", number=1, title="One", words=27, text_hash="", is_opening=False,
            results={}, stage="", scope=None)
    page = _open_outline(view, ch, TEXT)
    assert "Tobin · counts his coins at the inn → he is short of money" in page
    assert "Mara · watches the boats come in → changes nothing?" in page
    assert "one reader's view" in page


def test_without_a_reading_the_outline_says_where_it_comes_from(app, tmp_path):
    from src.ui.readiness_issues import ChapterIssues
    view = ChapterIssues()
    view.outline_project = lambda: _project(tmp_path)
    ch = NS(chapter_id="c1", number=1, title="One", words=27, text_hash="", is_opening=False,
            results={}, stage="", scope=None)
    page = _open_outline(view, ch, TEXT)
    assert "once the chapter is checked with the model" in page
    assert "→" not in page


def test_a_model_that_copies_the_lines_field_names_gives_no_scene():
    reply = ('SCENE | point-of-view character | what happens, under 25 words | what the scene '
             'changes | "the first words"\n'
             'SCENE | POV | what happens | what the scene changes | NONE\n' + FakeLLM().generate_text("", ""))
    assert len(chapter_digest.parse(reply, TEXT)["scenes"]) == 3
    stored = {"scenes": [{"pov": "POV", "what": "what happens", "start": -1}]}  # stored before the fix
    assert sr.per_scene(stored, ro.outline(TEXT, [])) == [[], []]


def test_the_point_of_view_is_not_repeated_when_the_line_starts_with_it():
    assert sr.line({"pov": "Samuel", "what": "Samuel wakes", "purpose": "x"}) == "Samuel wakes → x"
