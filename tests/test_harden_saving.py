"""Piece 0.4: saving survives interruptions, unreadable files are never
saved over, backups reach back two weeks, and nested unknown fields survive.

Every test works in a temporary folder; nothing touches real projects or
the writer's settings.
"""

import json
import os
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from src.data import safe_store
from src.models import chapter_backups
from src.models.project import Chapter, Character, Manuscript, WriterProject


@pytest.fixture(autouse=True)
def _fresh_store_state():
    safe_store._reset_for_tests()
    yield
    safe_store._reset_for_tests()


@pytest.fixture
def notices():
    got = []
    safe_store.set_notifier(got.append)
    return got


def _project(tmp_path, name="Book"):
    path = tmp_path / "book.writerproj"
    p = WriterProject(name=name, manuscript=Manuscript(title=name))
    p.project_path = str(path)
    return path, p


def _chapter(ms, title, content):
    ch = Chapter(id=str(uuid.uuid4()), number=len(ms.chapters) + 1, title=title,
                 folder_root=ms.folder_root)
    ch.content = content
    ms.chapters.append(ch)
    return ch


def _fail_replace(monkeypatch):
    def boom(*a, **k):
        raise OSError("drive pulled")
    monkeypatch.setattr(safe_store.os, "replace", boom)


def _no_temp_files(folder: Path):
    return [p.name for p in folder.rglob("*.tmp")] == []


# ── Side files: unreadable is not empty ────────────────────────────────

@pytest.mark.parametrize("module", ["companion_state", "critique_history"])
def test_unreadable_side_file_is_set_aside_not_overwritten(tmp_path, notices, module):
    import importlib
    mod = importlib.import_module(f"src.data.{module}")
    path = (mod.state_path if module == "companion_state" else mod.history_path)(None)
    path.write_text('{"half written', encoding="utf-8")

    assert mod.load(None) == {}
    aside = [p for p in path.parent.iterdir() if ".unreadable-" in p.name]
    assert len(aside) == 1 and aside[0].read_text() == '{"half written'
    assert not path.exists()
    assert len(notices) == 1 and aside[0].name in notices[0]

    # Saving now writes a fresh file; the set-aside copy is untouched.
    if module == "companion_state":
        mod.save(None, {"chapters": {}})
    else:
        safe_store.save(path, {"x": []})
    assert path.exists() and aside[0].read_text() == '{"half written'


def test_missing_side_file_starts_empty_without_a_warning(tmp_path, notices):
    from src.data import companion_state
    path = companion_state.state_path(None)
    assert not path.exists()
    assert companion_state.load(None) == {}
    assert notices == [] and not path.exists()


def test_wrong_shape_counts_as_unreadable(tmp_path, notices):
    path = tmp_path / "store.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert safe_store.load(path, {}, expect=dict) == {}
    assert any(".unreadable-" in p.name for p in tmp_path.iterdir())
    assert len(notices) == 1


def test_writer_told_once_per_file(tmp_path, notices):
    path = tmp_path / "store.json"
    for _ in range(3):
        path.write_text("not json", encoding="utf-8")
        safe_store.load(path, {})
    assert len(notices) == 1


def test_notice_before_a_notifier_is_delivered_later(tmp_path):
    path = tmp_path / "store.json"
    path.write_text("not json", encoding="utf-8")
    safe_store.load(path, {})
    got = []
    safe_store.set_notifier(got.append)
    assert len(got) == 1


def test_unreadable_file_that_cannot_be_set_aside_is_never_saved_over(tmp_path, monkeypatch, notices):
    path = tmp_path / "store.json"
    path.write_text("not json", encoding="utf-8")
    _fail_replace(monkeypatch)
    assert safe_store.load(path, {"default": True}) == {"default": True}
    monkeypatch.undo()
    assert safe_store.save(path, {"new": 1}) is False
    assert path.read_text() == "not json"
    assert "will not save over it" in notices[0]


def test_good_file_loads_and_saves_in_the_same_format(tmp_path):
    path = tmp_path / "store.json"
    data = {"chapters": {"c1": {"words_at_open": 10}}, "dismissed": ["a"]}
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    assert safe_store.load(path, {}) == data
    assert safe_store.save(path, data)
    assert path.read_text() == json.dumps(data, indent=1)


# ── Safe writes ─────────────────────────────────────────────────────────

def test_interrupted_side_file_write_leaves_old_file_whole(tmp_path, monkeypatch):
    path = tmp_path / "companion_state.json"
    path.write_text('{"old": 1}', encoding="utf-8")
    _fail_replace(monkeypatch)
    assert safe_store.save(path, {"new": 2}) is False
    assert path.read_text() == '{"old": 1}'
    assert _no_temp_files(tmp_path)


def test_write_keeps_permissions(tmp_path):
    path = tmp_path / "a.md"
    path.write_text("old", encoding="utf-8")
    os.chmod(path, 0o640)
    safe_store.write_text(path, "new")
    assert path.read_text() == "new" and (os.stat(path).st_mode & 0o777) == 0o640


def test_unchanged_file_is_not_rewritten(tmp_path):
    path = tmp_path / "a.md"
    safe_store.write_text(path, "same")
    before = os.stat(path).st_mtime_ns
    assert safe_store.write_text_if_changed(path, "same") is False
    assert os.stat(path).st_mtime_ns == before
    assert safe_store.write_text_if_changed(path, "different") is True


def test_interrupted_settings_write_leaves_old_settings(tmp_path, monkeypatch):
    from src.config.ai_config import AIConfig
    cfg = AIConfig.__new__(AIConfig)
    cfg.config_dir = tmp_path
    cfg.config_file = tmp_path / "ai_config.json"
    cfg.config_file.write_text('{"default_llm": "claude"}', encoding="utf-8")
    cfg.settings = {"default_llm": "claude"}
    _fail_replace(monkeypatch)
    assert cfg.save_settings({"default_llm": "server"}) is False
    assert json.loads(cfg.config_file.read_text()) == {"default_llm": "claude"}
    monkeypatch.undo()
    assert cfg.save_settings({"default_llm": "server"}) is True
    assert json.loads(cfg.config_file.read_text())["default_llm"] == "server"


def test_interrupted_creativeos_settings_write_leaves_old_settings(tmp_path, monkeypatch):
    from src.config.creativeos_config import CreativeOSConfig
    cfg = CreativeOSConfig.__new__(CreativeOSConfig)
    cfg.config_dir = tmp_path
    cfg.config_file = tmp_path / "config.json"
    cfg.config_file.write_text('{"a": 1}', encoding="utf-8")
    cfg.settings = {"a": 2}
    _fail_replace(monkeypatch)
    assert cfg.save() is False
    assert cfg.config_file.read_text() == '{"a": 1}'
    monkeypatch.undo()
    assert cfg.save() is True
    assert json.loads(cfg.config_file.read_text()) == {"a": 2}


def test_interrupted_chapter_write_leaves_old_text(tmp_path, monkeypatch):
    path, p = _project(tmp_path)
    ch = _chapter(p.manuscript, "One", "The original chapter text.")
    p.save_project(str(path))
    rev_file = tmp_path / ch.revisions[-1].file_path
    assert rev_file.read_text() == "The original chapter text."

    ch.content = "A replacement that never finishes writing."
    _fail_replace(monkeypatch)
    with pytest.raises(OSError):
        p.save_project(str(path))
    assert rev_file.read_text() == "The original chapter text."
    assert _no_temp_files(tmp_path)

    monkeypatch.undo()
    p.save_project(str(path))
    assert rev_file.read_text() == "A replacement that never finishes writing."


# ── Backups ─────────────────────────────────────────────────────────────

def _backups(times):
    return [(t, Path(f"backup_{t:%Y%m%d_%H%M%S}.md")) for t in times]


def test_backups_keep_three_recent_and_first_of_each_day():
    today = date(2026, 11, 22)
    times = [datetime(2026, 11, 22, 10, 0, s) for s in range(6)]            # six today
    times += [datetime(2026, 11, d, h) for d in (20, 15, 9) for h in (9, 17)]  # two a day
    times += [datetime(2026, 10, 1, 12)]                                    # long ago
    remove = {p.name for p in chapter_backups.to_remove(_backups(times), today=today)}
    keep = {p.name for _, p in _backups(times)} - remove

    assert {f"backup_20261122_1000{s:02d}.md" for s in (3, 4, 5)} <= keep    # newest three
    assert "backup_20261122_100000.md" in keep                              # first of today
    assert "backup_20261120_090000.md" in keep and "backup_20261120_170000.md" in remove
    assert "backup_20261115_090000.md" in keep
    assert "backup_20261109_090000.md" in keep                              # 14th day back
    assert "backup_20261001_120000.md" in remove                            # too old


def test_blanking_a_chapter_keeps_the_last_copy_with_text():
    today = date(2026, 11, 22)
    old = datetime(2026, 9, 1, 12)
    times = [old] + [datetime(2026, 11, 22, 10, 0, s) for s in range(5)]
    with_text = {f"backup_{old:%Y%m%d_%H%M%S}.md"}
    remove = chapter_backups.to_remove(
        _backups(times), today=today, saving_empty=True,
        has_text=lambda p: p.name in with_text)
    assert not with_text & {p.name for p in remove}
    # Without blanking, the old copy goes as before.
    remove = chapter_backups.to_remove(_backups(times), today=today)
    assert with_text <= {p.name for p in remove}


def test_saving_prunes_backups_on_disk(tmp_path):
    path, p = _project(tmp_path)
    ch = _chapter(p.manuscript, "One", "v0")
    p.save_project(str(path))
    folder = tmp_path / ch.folder_path
    now = datetime.now()
    old_days = [now - timedelta(days=d) for d in (1, 2, 30, 31)]
    for t in old_days:
        (folder / f"backup_{t:%Y%m%d_%H%M%S}.md").write_text(f"text {t:%d}", encoding="utf-8")
    for i in range(1, 5):
        ch.content = f"v{i}"
        p.save_project(str(path))
    names = {f.name for f in folder.glob("backup_*.md")}
    assert f"backup_{old_days[0]:%Y%m%d_%H%M%S}.md" in names       # yesterday's first
    assert f"backup_{old_days[1]:%Y%m%d_%H%M%S}.md" in names
    assert f"backup_{old_days[3]:%Y%m%d_%H%M%S}.md" not in names   # a month ago


# ── Unknown fields inside the project ───────────────────────────────────

def test_unknown_nested_fields_survive_open_save_reopen(tmp_path):
    path, p = _project(tmp_path)
    _chapter(p.manuscript, "One", "Main text.")
    p.characters.append(Character(id="m", name="Mara", character_type="protagonist"))
    sp = p.create_subproject("Novella")
    p.activate_subproject(sp.id)
    _chapter(p.manuscript, "N1", "Novella text.")
    p.save_project(str(path))

    raw = json.loads(path.read_text())
    raw["manuscript"]["chapters"][0]["future_chapter_field"] = {"stage": "line"}
    raw["characters"][0]["future_character_field"] = [1, 2]
    raw["subprojects"][0]["future_novella_field"] = "kept"
    raw["subprojects"][0]["manuscript"]["chapters"][0]["future_chapter_field"] = "n"
    raw["future_top_field"] = True
    path.write_text(json.dumps(raw), encoding="utf-8")

    for _ in range(2):
        WriterProject.load_project(str(path)).save_project(str(path))

    again = json.loads(path.read_text())
    assert again["manuscript"]["chapters"][0]["future_chapter_field"] == {"stage": "line"}
    assert again["characters"][0]["future_character_field"] == [1, 2]
    assert again["subprojects"][0]["future_novella_field"] == "kept"
    assert again["subprojects"][0]["manuscript"]["chapters"][0]["future_chapter_field"] == "n"
    assert again["future_top_field"] is True
    # Prose still lives in files, not in the project file.
    assert again["manuscript"]["chapters"][0]["content"] == ""
    reopened = WriterProject.load_project(str(path))
    assert reopened.get_main_manuscript().chapters[0].content == "Main text."


def test_project_without_unknown_fields_gains_none(tmp_path):
    path, p = _project(tmp_path)
    _chapter(p.manuscript, "One", "Text.")
    p.save_project(str(path))
    first = json.loads(path.read_text())
    WriterProject.load_project(str(path)).save_project(str(path))
    second = json.loads(path.read_text())
    for d in (first, second):
        d.pop("updated_at", None)
    assert first.keys() == second.keys()
    assert first["manuscript"]["chapters"][0].keys() == second["manuscript"]["chapters"][0].keys()
