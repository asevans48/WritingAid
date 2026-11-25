"""Remembered ✓ Checks ▾ switches, per project (P.2a, 24 Nov 2026)."""

import json
from datetime import datetime

import pytest

from src.utils.style_checks import DEFAULT_KINDS


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _own_files(monkeypatch):
    """conftest sends every project's companion file to one place; these
    tests need each project's own file beside it (R.7)."""
    import src.data.companion_state as cs
    from src.data import state_files
    monkeypatch.setattr(cs, "state_path",
                        lambda p: state_files.own_path(p, "companion_state", "companion"))
    # These tests open many editors; none needs LanguageTool started.
    from src.utils.proofing import LanguageToolEngine
    monkeypatch.setattr(LanguageToolEngine, "ensure_started", lambda self: False)


def _saved_project(tmp_path, name, created=None):
    from src.models.project import Chapter, Manuscript, WriterProject
    p = WriterProject(name=name, manuscript=Manuscript(title=name))
    if created is not None:
        p.created_at = created
    ch = Chapter(id="c1", number=1, title="One", folder_root=p.manuscript.folder_root)
    ch.content = "He went home. She stayed. They waited for the NTSB.\n"
    p.manuscript.chapters.append(ch)
    path = tmp_path / f"{name}.writerproj"
    p.save_project(str(path))
    return path


def _open(path):
    from src.models.project import WriterProject
    return WriterProject.load_project(str(path))


def _editor(project):
    from src.ui.manuscript_editor import ChapterEditor
    return _keep(ChapterEditor(project.manuscript.chapters[0], project=project))


def _stored(state):
    return json.loads(state.read_text()) if state.exists() else {}


_OPEN = []


def _keep(ed):
    _OPEN.append(ed)          # closed at the end of each test (no early GC)
    return ed


@pytest.fixture(autouse=True)
def _close_editors():
    yield
    from PyQt6.QtCore import QThread
    while _OPEN:
        ed = _OPEN.pop()
        for t in ed.findChildren(QThread):
            t.wait(5000)
        ed.close()
        ed.deleteLater()


def _state(ed):
    return (set(ed.editor.writing_highlighter._style_kinds),
            {k: a.isChecked() for k, a in ed._check_actions.items()})


OLD = datetime(2026, 3, 1, 10, 0)


def test_ticks_survive_save_and_reopen(app, tmp_path):
    path = _saved_project(tmp_path, "Book", created=OLD)
    ed = _editor(_open(path))
    ed._style_check_actions["alliteration"].setChecked(True)
    ed._style_check_actions["adverb"].setChecked(False)
    ed._check_actions["style"].setChecked(True)
    ed._check_actions["grammar"].setChecked(False)
   

    ed2 = _editor(_open(path))
    kinds, on = _state(ed2)
    assert "alliteration" in kinds and "adverb" not in kinds
    assert on == {"spell": True, "grammar": False, "overuse": True, "style": True}
    # The menu and the editor agree.
    assert ed2._style_check_actions["alliteration"].isChecked()
    assert not ed2._style_check_actions["adverb"].isChecked()
    from src.utils.editor_flags import CheckMode
    assert ed2.editor.writing_highlighter.get_style_mode() != CheckMode.OFF
    assert "Grammar" not in ed2.checks_btn.toolTip()


def test_two_projects_keep_separate_ticks(app, tmp_path):
    a = _saved_project(tmp_path, "Alpha", created=OLD)
    b = _saved_project(tmp_path, "Beta", created=OLD)
    ea = _editor(_open(a))
    ea._style_check_actions["transition"].setChecked(True)
    eb = _editor(_open(b))
    eb._style_check_actions["cliche"].setChecked(False)

    ka, _ = _state(_editor(_open(a)))
    kb, _ = _state(_editor(_open(b)))
    assert "transition" in ka and "cliche" in ka
    assert "transition" not in kb and "cliche" not in kb
    assert (tmp_path / "Alpha.companion_state.json").exists()
    assert (tmp_path / "Beta.companion_state.json").exists()


def test_existing_project_without_stored_ticks_gets_todays_defaults(app, tmp_path):
    path = _saved_project(tmp_path, "Old", created=OLD)
    kinds, on = _state(_editor(_open(path)))
    assert kinds == set(DEFAULT_KINDS)
    assert on == {"spell": True, "grammar": True, "overuse": True, "style": False}


def test_new_project_starts_with_the_checks_that_meet_four_in_five(app, tmp_path):
    """Decision 3: a new project ticks only the style checks that meet 4 in 5
    (Pronouns and Acronyms among them); spelling, grammar and overuse stay on."""
    from src.data import check_switches
    from src.models.project import Manuscript, WriterProject
    fresh = WriterProject(name="Fresh", manuscript=Manuscript(title="Fresh"))
    assert check_switches.is_new_project(fresh)
    path = _saved_project(tmp_path, "New")                    # created now
    kinds, on = _state(_editor(_open(path)))
    assert kinds == set(check_switches.MEETS_TARGET)
    assert {"pronoun", "acronym"} <= kinds and not {"sticky_sentence", "echo", "adverb"} & kinds
    assert on["style"] is False and on["spell"] and on["overuse"]
    # Not written until the writer changes something.
    assert "checks" not in _stored(tmp_path / "New.companion_state.json")


def test_a_project_whose_date_was_filled_in_at_load_is_not_new(tmp_path):
    from src.data import check_switches
    from src.models.project import Manuscript, WriterProject
    path = tmp_path / "x.writerproj"
    path.write_text("{}")
    p = WriterProject(name="X", manuscript=Manuscript(title="X"))
    p.project_path = str(path)
    p.created_at = datetime(2099, 1, 1)
    assert not check_switches.is_new_project(p)


def test_ticks_made_before_the_first_save_are_kept(tmp_path):
    from src.data import check_switches
    from src.models.project import Manuscript, WriterProject
    p = WriterProject(name="Draft", manuscript=Manuscript(title="Draft"))
    check_switches.remember(p, {"echo"}, {"style": True})
    p.project_path = str(tmp_path / "Draft.writerproj")
    kinds, on = check_switches.resolve(p)
    assert kinds == {"echo"} and on["style"] is True


def test_an_older_companion_file_opens_unchanged(app, tmp_path):
    path = _saved_project(tmp_path, "Kept", created=OLD)
    state = tmp_path / "Kept.companion_state.json"
    old = {"chapters": {"c1": {"stopped_at": "here"}}, "dismissed": ["k"],
           "ui": {"collapsed": ["memory"]}, "future_key": {"x": 1}}
    state.write_text(json.dumps(old, indent=1))
    ed = _editor(_open(path))
    assert _state(ed)[0] == set(DEFAULT_KINDS)
    data = _stored(state)
    assert "checks" not in data                       # opening adds nothing of ours
    for k, v in old.items():
        if k != "chapters":                           # the companion notes the visit
            assert data[k] == v
    # A change adds the key and keeps everything else (and unknown kinds).
    ed = _editor(_open(path))
    ed._style_check_actions["echo"].setChecked(False)
    data = json.loads(state.read_text())
    assert data["chapters"]["c1"]["stopped_at"] == "here"
    for k, v in old.items():
        if k != "chapters":
            assert data[k] == v
    assert "echo" not in data["checks"]["style_kinds"]
    data["checks"]["style_kinds"].append("newer_app_kind")
    state.write_text(json.dumps(data))
    ed._style_check_actions["echo"].setChecked(True)
    assert "newer_app_kind" in json.loads(state.read_text())["checks"]["style_kinds"]
   
