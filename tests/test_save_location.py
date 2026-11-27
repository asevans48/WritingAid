"""Warn before saving a project into a folder that holds another project."""

import os
from types import SimpleNamespace as NS

import pytest

from src.ui import save_location as sl


def _touch(path, text="{}"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- finding other project files ---------------------------------------

def test_other_project_in_folder_is_found(tmp_path):
    other = _touch(tmp_path / "Teller County.writerproj")
    _touch(tmp_path / "Teller County.ratings.json")  # a sidecar, not a project
    found = sl.other_project_files(tmp_path / "Adelphus.writerproj")
    assert found == [other]


def test_older_project_file_name_is_found(tmp_path):
    old = _touch(tmp_path / "writerproj.json")
    assert sl.other_project_files(tmp_path / "New.writerproj") == [old]


def test_own_file_is_not_a_collision(tmp_path):
    own = _touch(tmp_path / "Adelphus.writerproj")
    assert sl.other_project_files(own) == []


def test_empty_or_missing_folder_has_nothing(tmp_path):
    assert sl.other_project_files(tmp_path / "A.writerproj") == []
    assert sl.other_project_files(tmp_path / "nope" / "A.writerproj") == []


# --- the subfolder never overwrites -------------------------------------

def test_subfolder_is_new_and_named_after_project(tmp_path):
    target = sl.make_subfolder_target(tmp_path / "Adelphus.writerproj")
    assert target == tmp_path / "Adelphus" / "Adelphus.writerproj"
    assert target.parent.is_dir() and not target.exists()


def test_subfolder_adds_number_when_name_taken(tmp_path):
    kept = _touch(tmp_path / "Adelphus" / "notes.txt", "keep me")
    _touch(tmp_path / "Adelphus 2", "a file, not a folder")
    target = sl.make_subfolder_target(tmp_path / "Adelphus.writerproj")
    assert target == tmp_path / "Adelphus 3" / "Adelphus.writerproj"
    assert kept.read_text() == "keep me"
    assert (tmp_path / "Adelphus 2").read_text() == "a file, not a folder"
    assert sorted(p.name for p in (tmp_path / "Adelphus").iterdir()) == ["notes.txt"]


# --- choose_save_path ----------------------------------------------------

def test_no_question_when_folder_is_clear(tmp_path):
    def ask(*a):
        raise AssertionError("should not ask")
    path = str(tmp_path / "A.writerproj")
    assert sl.choose_save_path(None, path, ask=ask) == path
    assert sl.choose_save_path(None, "", ask=ask) is None


def test_answers(tmp_path):
    _touch(tmp_path / "Other.writerproj")
    path = str(tmp_path / "Mine.writerproj")
    seen = {}

    def ask(parent, target, others, sub_name):
        seen["sub"] = sub_name
        seen["others"] = [p.name for p in others]
        return answer

    answer = sl.HERE
    assert sl.choose_save_path(None, path, ask=ask) == path
    assert seen == {"sub": "Mine", "others": ["Other.writerproj"]}
    answer = sl.CANCEL
    assert sl.choose_save_path(None, path, ask=ask) is None
    answer = sl.SUBFOLDER
    assert sl.choose_save_path(None, path, ask=ask) == str(
        tmp_path / "Mine" / "Mine.writerproj")


# --- wiring through Save As ---------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _save_as(tmp_path, monkeypatch, answer):
    from PyQt6.QtWidgets import QFileDialog
    from src.ui.main_window import MainWindow

    chosen = str(tmp_path / "Mine.writerproj")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (chosen, "")))
    asked = []

    def fake_ask(*a):
        asked.append(a)
        return answer
    monkeypatch.setattr(sl, "ask_where", fake_ask)
    saved = []
    win = NS(current_project=NS(name="Mine"),
             _save_to_path=lambda p: saved.append(p))
    MainWindow._save_project_as(win)
    return saved, asked


def test_save_as_clear_folder_saves(qapp, tmp_path, monkeypatch):
    saved, asked = _save_as(tmp_path, monkeypatch, sl.CANCEL)
    assert asked == []
    assert saved == [str(tmp_path / "Mine.writerproj")]


def test_save_as_other_project_cancel_and_subfolder(qapp, tmp_path, monkeypatch):
    _touch(tmp_path / "Other.writerproj")
    saved, asked = _save_as(tmp_path, monkeypatch, sl.CANCEL)
    assert len(asked) == 1 and saved == []
    saved, asked = _save_as(tmp_path, monkeypatch, sl.SUBFOLDER)
    assert saved == [str(tmp_path / "Mine" / "Mine.writerproj")]
    saved, asked = _save_as(tmp_path, monkeypatch, sl.HERE)
    assert saved == [str(tmp_path / "Mine.writerproj")]


def test_ordinary_save_never_asks(qapp, tmp_path, monkeypatch):
    from src.ui.main_window import MainWindow
    _touch(tmp_path / "Other.writerproj")
    monkeypatch.setattr(sl, "ask_where",
                        lambda *a: pytest.fail("should not ask"))
    saved = []
    own = str(tmp_path / "Mine.writerproj")
    win = NS(current_project=NS(name="Mine", project_path=own),
             _save_to_path=lambda p: saved.append(p))
    MainWindow._save_project(win)
    assert saved == [own]


def test_real_save_into_subfolder(tmp_path):
    """The real project save lands in the new folder; the other project's
    folder contents are untouched."""
    from src.models.project import WriterProject
    from src.models.project import Manuscript
    other = _touch(tmp_path / "Other.writerproj", '{"name": "Other"}')
    target = sl.choose_save_path(None, str(tmp_path / "Mine.writerproj"),
                                 ask=lambda *a: sl.SUBFOLDER)
    project = WriterProject(name="Mine", manuscript=Manuscript(title="Mine"))
    project.save_project(target)
    assert (tmp_path / "Mine" / "Mine.writerproj").is_file()
    assert other.read_text() == '{"name": "Other"}'
