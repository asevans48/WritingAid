"""The safety check's screen step (0.3): the main screens open on a copy of
a project, the window saves it unchanged, and the original is never touched.
Made-up projects only."""

import importlib.util
import os
import pwd
import sys
from pathlib import Path

import pytest

from src.models.project import Chapter, Character, WriterProject

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


safety = _load("check_project_safety")
screens = _load("check_project_screens")

TEXT = ('Mara looked at the harbour. "I don\'t know where it\'s gone," she said.\n\n'
        "The rain kept on. " * 30)


def _real_home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


@pytest.fixture
def book(tmp_path):
    """A saved project: text in the main manuscript, characters, and a
    novella with one written and one empty chapter."""
    folder = tmp_path / "book"
    folder.mkdir()
    path = folder / "Book.writerproj"
    p = WriterProject(name="Book")
    p.characters = [Character(id="m", name="Mara Venn", character_type="protagonist")]
    for i in (1, 2):
        p.manuscript.chapters.append(Chapter(id=f"c{i}", number=i, title=f"Chapter {i}",
                                             content=f"Chapter {i}. " + TEXT))
    sp = p.create_subproject("Saltmarsh")
    p.activate_subproject(sp.id)
    p.manuscript.chapters.append(Chapter(id="n1", number=1, title="One", content=TEXT))
    p.manuscript.chapters.append(Chapter(id="n2", number=2, title="Two", content=""))
    p.activate_subproject(None)
    p.save_project(str(path))
    return path


def test_the_screens_open_and_the_window_saves_unchanged(book, capsys):
    """The whole check, as the writer runs it, with the window in its own process."""
    before = safety.snapshot(book.parent)
    assert safety.check(book, screens=True) is True
    out = capsys.readouterr().out
    assert "screens: opened" in out and "(2 manuscript(s))" in out
    assert "PROBLEM" not in out
    assert safety.snapshot(book.parent) == before          # the original is untouched


def test_the_screens_are_left_out_by_default_in_code_and_on_request(book, capsys):
    assert safety.check(book) is True
    assert "screens:" not in capsys.readouterr().out
    assert safety.main(["--no-screens", str(book)]) == 0
    assert "screens:" not in capsys.readouterr().out


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window_run(app, monkeypatch, tmp_path):
    """Run the screen step in this process (so a fault can be planted)."""
    if Path.home() == _real_home():
        pytest.skip("needs HOME set to a scratch folder (the main window reads settings)")
    from PyQt6.QtWidgets import QToolTip
    style, tips = app.styleSheet(), QToolTip.palette()
    home = tmp_path / "home"
    home.mkdir()

    def go(copy_file):
        return screens.open_and_save(Path(copy_file), home, app, put=monkeypatch.setattr)
    go.home = home
    yield go
    app.setStyleSheet(style)
    QToolTip.setPalette(tips)


def _copy(book, tmp_path):
    work = tmp_path / "copy"
    safety.copy_project(book.parent, work)
    return work / book.name


def test_every_screen_and_panel_is_opened_for_every_manuscript(book, tmp_path, window_run):
    report = window_run(_copy(book, tmp_path))
    assert report["problems"] == []
    opened = report["screens"]
    for where in ("main manuscript", "novella 1"):
        assert f"Write ({where}, chapter 1)" in opened
        for panel in ("Companion", "Planner", "Feedback"):
            assert f"{panel} panel ({where})" in opened
    from src.ui import screen_groups as sg
    for key, _ in sg.OLD_TABS:
        assert f"{key} screen" in opened
    assert report["manuscripts"] == 2
    # Remembered panel sizes went to the scratch home, not the writer's preferences.
    assert list(window_run.home.glob("qsettings_WritingAid_*.ini"))


def test_a_window_save_that_blanks_a_chapter_is_caught(book, tmp_path, window_run, monkeypatch):
    real_save = WriterProject.save_project

    def lossy_save(self, file_path, *a, **k):
        real_save(self, file_path, *a, **k)
        first = sorted(Path(file_path).parent.rglob("revision_*.md"))[0]
        first.write_text("", encoding="utf-8")

    copy_file = _copy(book, tmp_path)
    monkeypatch.setattr(WriterProject, "save_project", lossy_save)
    report = window_run(copy_file)
    assert any("chapter file" in p for p in report["problems"])
    assert any("differs after the window saved it" in p for p in report["problems"])


def test_a_screen_that_fails_to_open_is_reported(book, tmp_path, window_run, monkeypatch):
    from src.ui import screen_groups as sg
    real_show = sg.show

    def show(win, widget):
        if widget is getattr(win, "grader_widget", None):
            raise RuntimeError("drawn wrong")
        real_show(win, widget)

    monkeypatch.setattr(sg, "show", show)
    report = window_run(_copy(book, tmp_path))
    assert any(p.startswith("showing the critique screen: RuntimeError")
               for p in report["problems"])
    assert "plot screen" in report["screens"]                 # the rest still opened
