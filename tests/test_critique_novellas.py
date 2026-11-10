"""The Critique tab across the main manuscript and its novellas."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.ai.chapter_analysis_agent import ChapterReport, CritiqueReport, resolve_genre_profile
from src.data import critique_history as history
from src.models.project import Chapter, WriterProject
from src.ui import grader_widget as gw


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def chapter(cid, title, text="She went to the pier."):
    return Chapter(id=cid, number=1, title=title, content=text)


@pytest.fixture
def project(tmp_path):
    p = WriterProject(name="Saga")
    p.project_path = str(tmp_path / "project.json")
    p.manuscript.title = "Main Book"
    p.manuscript.chapters = [chapter("m1", "Chapter 1", "Main text."), chapter("m2", "Harbor")]
    a = p.create_subproject("Alpha")
    a.manuscript.chapters = [chapter("a1", "Chapter 1", "Alpha text."), chapter("a2", "Tide")]
    b = p.create_subproject("Beta")
    b.manuscript.chapters = [chapter("b1", "Chapter 1", "Beta text.")]
    return p


@pytest.fixture
def ids(project):
    return {sp.name: sp.id for sp in project.subprojects}


@pytest.fixture
def started(monkeypatch):
    """Captures what would be sent to the critique worker."""
    runs = []

    class FakeWorker:
        def __init__(self, **kwargs):
            runs.append(kwargs)
            self.finished = self.error = self.progress = self

        def connect(self, *_):
            pass

        def start(self):
            pass

        def isRunning(self):
            return False

    monkeypatch.setattr(gw, "CritiqueWorker", FakeWorker)
    return runs


@pytest.fixture
def widget(app, project, tmp_path, monkeypatch):
    store = gw.CritiqueMetadataStore.__new__(gw.CritiqueMetadataStore)
    store.config_dir, store.metadata_file = tmp_path, tmp_path / "meta.json"
    store._metadata = {}
    monkeypatch.setattr(gw, "get_critique_metadata_store", lambda: store)
    w = gw.GraderWidget()
    w.set_project(project)
    return w


def picker_titles(w):
    return [w.chapter_picker.item(i).text() for i in range(w.chapter_picker.count())]


def choose(w, scope):
    w.manuscript_combo.setCurrentIndex(w.manuscript_combo.findData(scope or ""))


def tick(w, *rows):
    for row in rows:
        w.chapter_picker.item(row).setSelected(True)


def test_manuscript_choice_is_hidden_without_novellas(app, tmp_path, monkeypatch):
    p = WriterProject(name="Solo")
    p.manuscript.chapters = [chapter("x", "One")]
    w = gw.GraderWidget()
    w.set_project(p)
    w.scope_manuscript_radio.setChecked(True)
    assert w.manuscript_row.isHidden()
    assert w._selected_manuscript() is p.manuscript


def test_row_lists_every_manuscript(widget, ids):
    widget.scope_multi_radio.setChecked(True)
    combo = widget.manuscript_combo
    assert [combo.itemText(i) for i in range(combo.count())] == ["Main Book", "Alpha", "Beta"]
    assert not widget.manuscript_row.isHidden()
    widget.scope_single_radio.setChecked(True)
    assert widget.manuscript_row.isHidden()


def test_picker_follows_a_novella_switch(widget, project, ids):
    assert len(picker_titles(widget)) == 2 and "Harbor" in picker_titles(widget)[1]
    project.activate_subproject(ids["Alpha"])
    widget.refresh_manuscripts(follow_active=True)
    assert "Tide" in picker_titles(widget)[1]
    assert widget._selected_scope() == ids["Alpha"]


def test_selected_chapters_come_from_the_shown_manuscript(widget, project, ids):
    widget.scope_multi_radio.setChecked(True)
    project.activate_subproject(ids["Alpha"])
    widget.refresh_manuscripts(follow_active=True)
    widget.chapter_picker.clearSelection()
    tick(widget, 1)
    run = widget._get_chapters_for_run()
    assert [(c["title"], c["scope"]) for c in run] == [("Tide", ids["Alpha"])]


def test_can_critique_a_novella_that_is_not_open(widget, project, ids, started):
    widget.scope_manuscript_radio.setChecked(True)
    choose(widget, ids["Beta"])
    assert project.active_subproject_id is None
    widget._run_reports()
    run = started[-1]
    assert [c["text"] for c in run["chapters"]] == ["Beta text."]
    assert run["manuscript_override"] is project.get_manuscript_for(ids["Beta"])
    assert (run["scope_id"], run["run_kind"], run["scope_label"]) == (ids["Beta"], "manuscript", "Beta")
    assert run["include_continuity"] is False
    assert run["include_promise_check"] is False


def test_full_manuscript_can_include_continuity(widget, project, ids, started):
    widget.scope_manuscript_radio.setChecked(True)
    assert not widget.continuity_check.isHidden()
    widget.continuity_check.setChecked(True)
    widget._run_reports()
    assert started[-1]["include_continuity"] is True
    assert started[-1]["run_kind"] == "manuscript+continuity"


def test_synopses_and_position_use_the_critiqued_manuscript(widget, project, ids, started):
    project.get_manuscript_for(ids["Beta"]).chapters[0].planning.description = "Beta synopsis"
    project.manuscript.chapters[0].planning.description = "Main synopsis"
    widget._current_chapter_title = "Chapter 1"
    widget.run_manuscript_critique(ids["Beta"], report_types=[gw.ReportType.PACING], confirm=False)
    assert started[-1]["chapter_synopses"] == {"Chapter 1": "Beta synopsis"}
    assert "Chapter 1 of" not in started[-1]["manuscript_context"]


def test_rag_searches_the_critiqued_manuscript(widget, project, ids, monkeypatch):
    seen = {}
    widget.window = lambda: type("W", (), {
        "_rag_top_chunks_per_type": lambda self, **k: seen.update(k) or ""})()
    widget._make_rag_provider(ids["Beta"])("q", ["chapter"])
    assert seen["chapter_scope"] == ids["Beta"]


def test_rag_scope_is_per_thread():
    import threading
    from src.ai.enhanced_rag import EnhancedRAGSystem
    rag = EnhancedRAGSystem.__new__(EnhancedRAGSystem)
    rag.chapter_scope_filter = {"open"}
    rag._scope_override = threading.local()
    with rag.scoped_to({"other"}):
        assert rag._scope_override.scopes == {"other"}
        seen = []
        t = threading.Thread(target=lambda: seen.append(
            getattr(rag._scope_override, "scopes", rag.chapter_scope_filter)))
        t.start(), t.join()
        assert seen == [{"open"}]
    assert not hasattr(rag._scope_override, "scopes")


def test_renamed_novella_updates_the_list(widget, project, ids):
    project.rename_subproject(ids["Alpha"], "Omega")
    widget.refresh_manuscripts()
    combo = widget.manuscript_combo
    assert combo.itemText(combo.findData(ids["Alpha"])) == "Omega"


def test_dropped_novella_falls_back_to_open_manuscript(widget, project, ids):
    choose(widget, ids["Beta"])
    project.delete_subproject(ids["Beta"])
    widget.refresh_manuscripts()
    assert widget._selected_scope() is None
    assert widget.manuscript_combo.findData(ids["Beta"]) == -1
    assert "Harbor" in picker_titles(widget)[1]


def test_new_chapter_refresh_keeps_ticked_chapters(widget, project):
    widget.chapter_picker.clearSelection()
    tick(widget, 1)
    project.manuscript.chapters.append(chapter("m3", "New"))
    widget.refresh_manuscripts()
    assert [i.row() for i in widget.chapter_picker.selectedIndexes()] == [1]
    assert widget.chapter_picker.count() == 3


# ── Notes and saved critiques ─────────────────────────────────────

def open_chapter(widget, project, scope, title):
    project.activate_subproject(scope)
    widget.set_current_chapter("text", title)


def test_chapter_notes_do_not_leak_between_novellas(widget, project, ids):
    open_chapter(widget, project, ids["Alpha"], "Chapter 1")
    widget.style_edit.setText("alpha noir")
    widget._save_chapter_context(silent=True)
    widget.style_edit.clear()
    open_chapter(widget, project, ids["Beta"], "Chapter 1")
    assert widget.style_edit.text() != "alpha noir"
    open_chapter(widget, project, ids["Alpha"], "Chapter 1")
    assert widget.style_edit.text() == "alpha noir"


def test_main_notes_keep_their_existing_key(widget, project):
    widget.set_current_chapter("text", "Chapter 1")
    assert widget._context_lookup_keys() == ["Chapter 1"]


def test_notes_follow_a_chapter_moved_out_of_main(widget, project, ids):
    widget._metadata_store.save_context(widget._project_path, "Tide", {"style": "moved note"})
    open_chapter(widget, project, ids["Alpha"], "Tide")
    assert widget.style_edit.text() == "moved note"


def test_saved_report_round_trips_its_manuscript(widget, ids):
    report = CritiqueReport(chapters=[], genre=resolve_genre_profile("default"))
    report.scope_label, report.scope_id = "Alpha", ids["Alpha"]
    back = widget._deserialize_report(widget._serialize_report(report))
    assert (back.scope_label, back.scope_id) == ("Alpha", ids["Alpha"])


def test_saved_reports_load_without_manuscript_fields(widget):
    report = CritiqueReport(chapters=[], genre=resolve_genre_profile("default"))
    data = widget._serialize_report(report)
    del data["scope_label"], data["scope_id"]
    back = widget._deserialize_report(data)
    assert back.scope_id is None


def test_saved_critiques_are_separate_per_novella(widget, project, ids, monkeypatch):
    report = CritiqueReport(chapters=[ChapterReport("Chapter 1", 0, 5, [])],
                            genre=resolve_genre_profile("default"))
    report.scope_id = ids["Alpha"]
    widget._last_report = report
    widget._save_critique_results()
    assert widget._metadata_store.list_critiques(widget._project_path, "Chapter 1") == []
    assert widget._metadata_store.list_critiques(
        widget._project_path, f"{ids['Alpha']}::Chapter 1")


def test_load_dialog_names_the_manuscript(widget, project, ids, monkeypatch):
    from PyQt6 import QtWidgets
    report = CritiqueReport(chapters=[ChapterReport("Chapter 1", 0, 5, [])],
                            genre=resolve_genre_profile("default"))
    report.scope_id = ids["Alpha"]
    widget._last_report = report
    widget._save_critique_results()
    shown = {}

    def fake_get_item(_parent, _title, _label, labels, *_):
        shown["labels"] = labels
        return "", False

    monkeypatch.setattr(QtWidgets.QInputDialog, "getItem", fake_get_item)
    widget._load_critique_results()
    assert any(label.startswith("[Alpha › Chapter 1]") for label in shown["labels"])


# ── Progress history ──────────────────────────────────────────────

def report_of(titles, scope_id=None, kind="", label=""):
    r = CritiqueReport(chapters=[ChapterReport(t, i, 10, []) for i, t in enumerate(titles)],
                       genre=resolve_genre_profile("default"))
    r.scope_id, r.run_kind, r.scope_label = scope_id, kind, label
    return r


def test_same_titled_chapters_have_separate_history(project, ids):
    assert history.record(project, report_of(["Chapter 1"], ids["Alpha"])) is None
    assert history.record(project, report_of(["Chapter 1"], ids["Beta"])) is None
    assert history.record(project, report_of(["Chapter 1"], ids["Alpha"])) is not None


def test_main_chapter_keeps_its_existing_history_key():
    assert history.scope_key(report_of(["A", "B"])) == "chapter:A|B"


def test_rename_keeps_a_novellas_history(project, ids):
    history.record(project, report_of(["Tide"], ids["Alpha"], "manuscript", "Alpha"))
    project.rename_subproject(ids["Alpha"], "Omega")
    assert history.record(project, report_of(["Tide"], ids["Alpha"], "manuscript", "Omega")) is not None


def test_history_saved_under_a_label_carries_over(project, ids):
    path = history.history_path(project)
    first = history.snapshot(report_of(["Tide"], ids["Alpha"], "manuscript", "Alpha"))
    path.parent.mkdir(parents=True, exist_ok=True)
    import json
    path.write_text(json.dumps({"scope:Alpha": [first]}), encoding="utf-8")
    assert history.record(project, report_of(["Tide"], ids["Alpha"], "manuscript", "Alpha")) is not None
    saved = history.load(project)
    assert "scope:Alpha" not in saved and f"manuscript:{ids['Alpha']}" in saved


def test_history_follows_chapters_moved_from_main(project, ids):
    history.record(project, report_of(["Harbor"], None, "manuscript", "Main Book"))
    project.get_main_manuscript().chapters = []
    moved = report_of(["Harbor"], ids["Alpha"], "manuscript", "Alpha")
    assert history.record(project, moved) is not None


def test_unrelated_main_history_is_not_taken(project, ids):
    history.record(project, report_of(["Harbor"], None, "manuscript", "Main Book"))
    project.get_main_manuscript().chapters = []
    assert history.record(project, report_of(["Tide"], ids["Alpha"], "manuscript", "Alpha")) is None


def test_worker_stamps_the_report(project, ids, monkeypatch):
    """A real dashboard run on a novella that isn't open."""
    ms = project.get_manuscript_for(ids["Alpha"])
    worker = gw.CritiqueWorker(
        chapters=[{"title": "Tide", "text": "She went to the pier. " * 20, "index": 1,
                   "scope": ids["Alpha"]}],
        report_types=[gw.ReportType.PACING], genre_key="default", critique_context=None,
        manuscript_context="", chapter_synopses={}, story_planning=None, rag_provider=None,
        force_dashboard=True, project=project, manuscript_override=ms,
        scope_label="Alpha", scope_id=ids["Alpha"], run_kind="manuscript")
    done, failed = [], []
    worker.finished.connect(done.append)
    worker.error.connect(failed.append)
    worker.run()
    assert not failed
    assert done[0].scope_id == ids["Alpha"] and done[0].run_kind == "manuscript"
    assert history.scope_key(done[0]) == f"manuscript:{ids['Alpha']}"
