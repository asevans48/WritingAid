"""The Critique in parts: results as ready, Stop, and resuming a stopped run."""

import os
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import critique_parts as cp
from src.ai.chapter_analysis_agent import CritiqueOrchestrator, ReportType
from src.data import critique_resume as resume
from src.models.project import Chapter, Manuscript, WriterProject

TEXT = ("The rain came in off the river. She waited by the door, listening. "
        "\"Go,\" he said. She did not move.\n\n") * 30
REPORTS = [ReportType.PACING, ReportType.STYLE, ReportType.DIALOG]


class FakeLLM:
    provider = "fake"
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    def generate_text(self, prompt, system_prompt="", **kw):
        self.calls += 1
        return f"Narrative {self.calls}. The prose moves well and the scene lands."


def _project(tmp_path):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    ch = Chapter(id=str(uuid.uuid4()), number=1, title="One", folder_root=p.manuscript.folder_root)
    ch.content = TEXT
    p.manuscript.chapters.append(ch)
    return p


def _chapters(text=TEXT):
    return [{"title": "One", "text": text, "index": 0}]


def _run(p, llm, stop=None, parts=None, text=TEXT, reports=REPORTS):
    orch = CritiqueOrchestrator(primary_llm=llm, project=p)
    return cp.run_in_parts(orch, _chapters(text), reports, "literary", "", None,
                           on_part=(parts.append if parts is not None else None),
                           stop=stop, project=p, model="fake-model" if llm else "",
                           extra={"scope_label": "Book"})


def test_results_arrive_report_by_report(tmp_path):
    p, parts = _project(tmp_path), []
    report = _run(p, FakeLLM(), parts=parts)
    assert [len(r.chapters[0].sections) for r in parts] == [1, 2, 3]
    assert [r.parts_done for r in parts] == [1, 2, 3] and parts[0].parts_total == 3
    assert all(r.scope_label == "Book" for r in parts)
    assert [s.report_type for s in report.chapters[0].sections] == REPORTS
    assert not report.stopped and report.overall_summary.startswith("Narrative")


def test_same_reports_as_the_one_shot_run(tmp_path):
    p = _project(tmp_path)
    whole = CritiqueOrchestrator(primary_llm=FakeLLM(), project=p).run(
        _chapters(), REPORTS, "literary", "", None)
    parts = _run(p, FakeLLM())
    for a, b in zip(whole.chapters[0].sections, parts.chapters[0].sections):
        assert (a.report_type, a.summary, a.metrics, a.findings) == \
               (b.report_type, b.summary, b.metrics, b.findings)


def test_stop_keeps_what_is_finished_and_the_next_run_resumes(tmp_path):
    p, llm = _project(tmp_path), FakeLLM()
    parts = []
    stopped = _run(p, llm, stop=lambda: len(parts) >= 2, parts=parts)
    assert stopped.stopped and len(stopped.chapters[0].sections) == 2
    assert "Stopped after 2 of 3 reports" in stopped.overall_summary
    assert resume.count(p) == 2
    first_calls = llm.calls

    llm2 = FakeLLM()
    again = _run(p, llm2)
    assert again.parts_reused == 2 and not again.stopped
    assert [s.narrative for s in again.chapters[0].sections[:2]] == \
           [s.narrative for s in stopped.chapters[0].sections]
    assert llm2.calls < first_calls + 1                       # only the missing report + summary
    cp.finished(p, again)
    assert resume.count(p) == 0                               # a completed run leaves nothing


def test_a_changed_chapter_or_model_is_not_reused(tmp_path):
    p, parts = _project(tmp_path), []
    _run(p, FakeLLM(), stop=lambda: len(parts) >= 1, parts=parts)
    assert _run(p, FakeLLM(), text=TEXT + "One more line.\n").parts_reused == 0
    orch = CritiqueOrchestrator(primary_llm=FakeLLM(), project=p)
    other = cp.run_in_parts(orch, _chapters(), REPORTS, "literary", "", None, project=p,
                            model="another-model")
    assert other.parts_reused == 0


def test_dashboard_mode_keeps_nothing(tmp_path):
    p = _project(tmp_path)
    report = _run(p, None, stop=lambda: False)
    assert len(report.chapters[0].sections) == 3 and resume.count(p) == 0


def test_saved_critique_format_is_unchanged(qapp):
    from src.ui.grader_widget import GraderWidget
    g = GraderWidget()
    report = _run(None, FakeLLM())
    data = g._serialize_report(report)
    keys = set(data["chapters"][0]["sections"][0])
    assert keys == {"report_type", "summary", "narrative", "metrics", "findings", "suggestions",
                    "strengths", "major_issues", "minor_issues", "extra_lists", "prompt",
                    "system_prompt", "calls", "item_sources"}
    back = g._deserialize_report(data)
    assert [s.narrative for s in back.chapters[0].sections] == \
           [s.narrative for s in report.chapters[0].sections]


def test_run_button_becomes_stop_and_partial_results_show(qapp, monkeypatch):
    from PyQt6.QtCore import QObject, pyqtSignal
    import src.ui.grader_widget as gw
    from src.ui.critique_live import watch_run

    warnings = []
    monkeypatch.setattr(gw.QMessageBox, "warning", lambda *a, **k: warnings.append(a))

    class Worker(QObject):
        finished = pyqtSignal(object)
        error = pyqtSignal(str)
        partial = pyqtSignal(object)
        stop_requested = False

    g = gw.GraderWidget()
    w = Worker()
    watch_run(g, w)
    assert g.critique_btn.text() == "Stop" and g.critique_btn.isEnabled()
    parts = []
    _run(None, FakeLLM(), parts=parts)
    w.partial.emit(parts[0])
    labels = [g.results_tabs.tabText(i) for i in range(g.results_tabs.count())]
    assert "Pacing" in labels and "Style" not in labels
    assert "Working… 1 of 3" in g._summary_browser.toPlainText()
    g.results_tabs.setCurrentIndex(labels.index("Pacing"))
    w.partial.emit(parts[1])
    assert g.results_tabs.tabText(g.results_tabs.currentIndex()) == "Pacing"   # reader's place kept
    g.critique_btn.click()                                   # Stop: runs nothing
    assert w.stop_requested and g.critique_btn.text() == "Stopping…" and not warnings
    w.finished.emit(parts[1])
    assert g.critique_btn.text() == "Run Critique" and g.critique_btn.isEnabled()
    w.stop_requested = False
    g.critique_btn.click()                                   # runs again (no chapter → a warning)
    assert not w.stop_requested and len(warnings) == 1


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
