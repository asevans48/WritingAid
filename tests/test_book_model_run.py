"""2.3: check the book with the model, in the background."""

import os
import re
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import readiness as rd
from src.data import readiness_state as rs
from src.models.project import Chapter, Manuscript, WriterProject

TEXT = "She walked slowly to the door. He smiled warmly at the dog. The boats rocked.\n"


class FakeLLM:
    model = "fake"

    def __init__(self, fail_on=None):
        self.prompts, self.fail_on = [], fail_on

    def generate_text(self, prompt, system="", **kw):
        self.prompts.append(prompt)
        if self.fail_on and self.fail_on in prompt:
            raise RuntimeError("the server went away")
        if "Look for three kinds of problem" in prompt:        # the story read
            return "NONE"
        if prompt.startswith("Proofread the text below"):       # the proofreading pass
            return "NONE"
        if "Outline this chapter" in prompt:                     # the chapter digest
            return "SCENE | She | they wait | she decides to go | NONE\nREADER | 3 | fine | NONE"
        if prompt.startswith("OUTLINE OF THE BOOK"):
            return "NONE"
        n = len(re.findall(r"^\d+\. \[", prompt, re.M))
        return "\n".join(f"{i + 1}. REAL — weak" for i in range(n))


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))


def _project(tmp_path, n=4):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    for i in range(n):
        ch = Chapter(id=f"c{i + 1}", number=i + 1, title=f"Chapter {i + 1}",
                     folder_root=p.manuscript.folder_root)
        ch.content = TEXT.replace("dog", f"dog number {i + 1}")
        p.manuscript.chapters.append(ch)
    return p


def test_stopping_keeps_finished_chapters_and_the_next_run_carries_on(tmp_path):
    p = _project(tmp_path)
    assert rd.model_work(p) == (4, 4)
    seen = []
    partial = rd.book_report(p, llm=FakeLLM(), partial=seen.append,
                             stop=lambda: len(seen) >= 2)
    assert not partial.complete and len(seen) == 2
    assert [len(s.chapters) for s in seen] == [1, 2]            # the grid fills as it goes
    stored = rs.load(p)["manuscripts"]["main"]["chapters"]
    assert set(stored) == {"c1", "c2"}                          # saved as each finished
    assert rd.model_work(p) == (2, 4)                           # only the rest left
    llm = FakeLLM()
    full = rd.book_report(p, llm=llm)
    assert full.complete and full.tier == "model"
    chapter_prompts = [x for x in llm.prompts if not x.startswith("OPENING PAGES")
                       and "CHAPTER (Chapter 3)" not in x]   # ch. 3's read quotes ch. 2's ending
    assert all("dog number 1" not in x and "dog number 2" not in x for x in chapter_prompts)


def test_a_model_error_on_one_chapter_does_not_stop_the_rest(tmp_path):
    p = _project(tmp_path)
    report = rd.book_report(p, llm=FakeLLM(fail_on="dog number 2"))
    assert report.complete and len(report.chapters) == 4
    judged = {ch.chapter_id: ch.results["adverbs"].judged for ch in report.chapters}
    # Chapter 3's story read includes chapter 2's ending, so it fails too.
    assert judged["c1"] and not judged["c2"] and judged["c4"]   # the rest carried on
    assert report.tier == "mixed"
    assert rd.model_work(p) == (2, 4)                           # only those to retry


def test_the_estimate_reads_plainly():
    from src.ui.scorecard_model_run import estimate
    text = estimate(10, 40)
    assert "10 of 40 chapters" in text and "about 70 requests" in text and "Stop keeps" in text
    assert "nothing new to judge" in estimate(0, 40)


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wait(qapp, sc):
    from src.ui import background
    for _ in range(100):
        background.wait_all(5000)
        qapp.processEvents()
        if sc._task is None:
            return


def test_the_scorecard_runs_it_with_stop_and_fills_as_it_goes(qapp, tmp_path, monkeypatch):
    import src.ui.scorecard_model_run as smr
    from src.ui.scorecard_widget import ScorecardWidget
    monkeypatch.setattr(smr, "ai_available", lambda: True)
    monkeypatch.setattr(smr, "confirm", lambda parent, todo, total: (True, False))
    p = _project(tmp_path)
    sc = ScorecardWidget()
    sc.llm_factory = FakeLLM
    sc.set_project(p)
    sc.refresh()
    _wait(qapp, sc)
    assert sc.model_link.isVisibleTo(sc) and "Check the book with the model" in sc.model_link.text()
    rendered = []
    real = sc._partial
    monkeypatch.setattr(sc, "_partial", lambda r: (rendered.append(r), real(r)))
    sc.start_model_check()
    assert sc.check_btn.text() == "Stop"
    _wait(qapp, sc)
    assert sc.check_btn.text() == "Check readiness" and sc.report.tier == "model"
    assert "Judged by the model" in sc.status_label.text()
    assert not sc.model_link.isVisibleTo(sc)                    # fully judged


def test_no_model_means_a_scan_and_says_so(qapp, tmp_path, monkeypatch):
    import src.ui.scorecard_model_run as smr
    from src.ui.scorecard_widget import ScorecardWidget
    monkeypatch.setattr(smr, "confirm", lambda parent, todo, total: (True, False))
    p = _project(tmp_path)
    sc = ScorecardWidget()
    sc.llm_factory = lambda: None
    sc.set_project(p)
    sc.start_model_check()
    _wait(qapp, sc)
    assert sc.report.tier == "scan" and "this was a scan" in sc.status_label.text()


def test_judging_in_the_background_only_when_chosen(qapp, tmp_path, monkeypatch):
    import src.ui.scorecard_model_run as smr
    from src.ui.scorecard_widget import ScorecardWidget
    monkeypatch.setattr(smr, "ai_available", lambda: True)
    state = {"on": False}
    monkeypatch.setattr(smr, "background_on", lambda: state["on"])
    p = _project(tmp_path)
    sc = ScorecardWidget()
    calls = []
    sc.llm_factory = lambda: calls.append(1) or FakeLLM()
    sc.set_project(p)
    sc._sync_background()
    assert not sc._bg_timer.isActive()
    sc._background_tick()
    _wait(qapp, sc)
    assert not calls                                           # off: no model use
    state["on"] = True
    sc._sync_background()
    assert sc._bg_timer.isActive()
    sc._background_tick()
    _wait(qapp, sc)
    assert calls and rd.model_work(p) == (0, 4)


def test_progress_shows_chapter_count_and_time_left(qapp):
    from src.ui.scorecard_widget import ScorecardWidget
    sc = ScorecardWidget()
    sc._run_todo = 8
    sc._partial(("progress", 2, 10, "Chapter 3", 2, 120.0))     # 2 judged in 2 minutes
    assert sc.progress_row.isVisibleTo(sc)
    assert sc.progress_bar.value() == 2 and sc.progress_bar.maximum() == 10
    assert sc.progress_bar.format() == "Chapter 3 of 10 · about 6 minutes left"
    assert sc.progress_label.text() == "Judging “Chapter 3”…"
    sc._partial(("progress", 0, 10, "Chapter 1", 0, 0.0))
    assert "working out the time left" in sc.progress_bar.format()
    sc._partial(("progress", 10, 10, "", 9, 500.0))
    assert sc.progress_bar.format() == "Chapter 10 of 10"
    assert "whole-book" in sc.progress_label.text()


def test_progress_during_a_run_then_hidden(qapp, tmp_path, monkeypatch):
    import src.ui.scorecard_model_run as smr
    from src.ui.scorecard_widget import ScorecardWidget
    monkeypatch.setattr(smr, "ai_available", lambda: True)
    monkeypatch.setattr(smr, "confirm", lambda parent, todo, total: (True, False))
    p = _project(tmp_path)
    sc = ScorecardWidget()
    sc.llm_factory = FakeLLM
    sc.set_project(p)
    seen = []
    real = sc._show_progress
    monkeypatch.setattr(sc, "_show_progress", lambda *a: (seen.append(a[:3]), real(*a)))
    sc.start_model_check()
    assert sc.progress_row.isVisibleTo(sc) and sc.progress_bar.format() == "Starting the model…"
    _wait(qapp, sc)
    assert [s[0] for s in seen][:4] == [0, 1, 2, 3] and seen[-1][0] == 4
    assert seen[0][2] == "Chapter 1"
    assert not sc.progress_row.isVisibleTo(sc)                  # gone when done
