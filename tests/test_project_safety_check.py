"""The project safety check: passes a healthy project, catches lost text,
and never writes to the project it is given."""

import importlib.util
import shutil
from pathlib import Path

import pytest

from src.models.project import WriterProject

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "check_project_safety", ROOT / "scripts" / "check_project_safety.py")
safety = importlib.util.module_from_spec(spec)
spec.loader.exec_module(safety)


@pytest.fixture
def project_file(tmp_path):
    """A saved project with real text in each chapter."""
    folder = tmp_path / "book"
    folder.mkdir()
    shutil.copy(ROOT / "test_project" / "project.json", folder / "project.json")
    project = WriterProject.load_project(str(folder / "project.json"))
    for n, ch in enumerate(project.manuscript.chapters, 1):
        ch.content = f"Chapter {n}. " + "The rain kept on. " * 40
    project.save_project(str(folder / "project.json"))
    return folder / "project.json"


def test_healthy_project_passes_and_is_untouched(project_file):
    before = safety.snapshot(project_file.parent)
    assert safety.check(project_file) is True
    assert safety.snapshot(project_file.parent) == before


def test_lost_text_is_caught(project_file, monkeypatch):
    real_save = WriterProject.save_project

    def lossy_save(self, file_path, *a, **k):
        real_save(self, file_path, *a, **k)
        first = sorted(Path(file_path).parent.rglob("revision_*.md"))[0]
        first.write_text("", encoding="utf-8")        # a save that blanks a chapter

    monkeypatch.setattr(WriterProject, "save_project", lossy_save)
    assert safety.check(project_file) is False


def test_dropped_field_is_caught(project_file, monkeypatch):
    real_save = WriterProject.save_project

    def forgetful_save(self, file_path, *a, **k):
        self.description = ""
        self.characters = []
        real_save(self, file_path, *a, **k)

    project = WriterProject.load_project(str(project_file))
    project.description = "A book."
    project.save_project(str(project_file))
    monkeypatch.setattr(WriterProject, "save_project", forgetful_save)
    assert safety.check(project_file) is False


def test_store_comparison_catches_removed_settings_and_rows():
    before = {"~/a.json": {"kind": "json", "keys": ["default_llm", "server_url"], "items": 2},
              "~/r.db": {"kind": "db", "rows": {"rephrases": 10}},
              "~/gone.json": {"kind": "json", "keys": [], "items": 0}}
    same = {k: dict(v) for k, v in before.items()}
    assert safety.compare_stores(before, same) == []
    grown = {"~/a.json": {"kind": "json", "keys": ["default_llm", "server_url", "new"], "items": 3},
             "~/r.db": {"kind": "db", "rows": {"rephrases": 12, "voices": 3}},
             "~/gone.json": {"kind": "json", "keys": [], "items": 0}}
    assert safety.compare_stores(before, grown) == []          # adding is fine
    after = {"~/a.json": {"kind": "json", "keys": ["default_llm"], "items": 1},
             "~/r.db": {"kind": "db", "rows": {"rephrases": 4}}}
    problems = " ".join(safety.compare_stores(before, after))
    assert "lost 1 setting" in problems and "fewer rows" in problems and "is gone" in problems
