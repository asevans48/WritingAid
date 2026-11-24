"""Before an editor: the ordered pass, answering queries, and the brief."""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))

from src.ai import editor_pass as ep
from src.ai import editorial_letter as el
from src.ai import readiness as rd
from test_chapter_digest import _project
from test_editorial_letter import LLM


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))


def _read(tmp_path):
    p = _project(tmp_path)
    llm = LLM(unpaid="2 | what the ledgers show is never told")
    return p, llm, rd.book_report(p, llm=llm)


def test_the_plan_is_three_steps_in_order(tmp_path):
    p = _project(tmp_path)
    scan = ep.plan(rd.book_report(p))
    assert [s.title for s in scan.steps] == ["Clear the mechanical", "Answer the queries",
                                             "Know the big picture"]
    assert not scan.ready and scan.title == "Not yet read by the model"
    assert "has read 0 of 3 chapters" in scan.steps[1].line
    assert scan.steps[2].line == "No editorial letter yet."
    p, llm, report = _read(tmp_path)
    full = ep.plan(report, el.write(llm, p, None, report))
    assert full.ready and full.title == "Ready for an editor"      # open questions don't block
    assert full.steps[0].done and not full.steps[1].done and full.steps[2].done
    assert "questions from the read" in full.steps[1].line and full.steps[1].count >= 3
    # Mechanical work left: not ready, and it says where to start.
    p.manuscript.chapters[1].content += "Its a beutiful day and he dont no were he is.\n"
    left = ep.plan(rd.book_report(p, llm=llm))
    assert not left.steps[0].done and left.steps[0].chapter_id == "c2"
    assert left.title == "Mechanical work left before an editor"


def test_an_intended_choice_stops_counting_and_can_be_taken_back(tmp_path):
    p, llm, report = _read(tmp_path)
    before = len(ep.open_queries(report))
    slip = report.chapters[0].results["pov_slips"].items[0]
    assert ep.is_query(slip)
    assert ep.set_intended(p, slip, "Point-of-view slips", "Chapter 1")
    again = rd.book_report(p, llm=llm)
    assert again.chapters[0].results["pov_slips"].count == 0
    assert again.chapters[0].results["pov_slips"].status == rd.Status.READY
    assert len(ep.open_queries(again)) == before - 1
    assert ep.intended(p)[0]["label"] == "Point-of-view slips"
    assert ep.set_intended(p, slip, "", "", on=False)
    assert rd.book_report(p, llm=llm).chapters[0].results["pov_slips"].count == 1


def test_the_brief_gives_an_editor_what_they_would_otherwise_build(tmp_path):
    p, llm, report = _read(tmp_path)
    el.write(llm, p, None, report)
    slip = report.chapters[0].results["pov_slips"].items[0]
    ep.set_intended(p, slip, "Point-of-view slips", "Chapter 1")
    report = rd.book_report(p, llm=llm)
    text = ep.brief(p, None, report)
    for want in ("# Editor's brief: ", "## What I'd like from this edit",
                 "## State of the manuscript", "1. **Clear the mechanical:**",
                 "a model read every chapter", "neither is a guarantee",
                 "## The big picture (a model's editorial letter)",
                 "1. **Plot: The ledgers are set up and never opened again.**",
                 "## Open questions", "**Chapter 1**", "Scenes that change nothing:",
                 "## Deliberate choices (please don't correct)", "American spellings only",
                 "Intended (Chapter 1): “Tobias wondered whether she had seen him watching”",
                 "## Style sheet: characters, places, timeline",
                 "## Outline, as the model read it", "## Chapter 2 (reader's pull 4/5)"):
        assert want in text, want
    # The intended slip is not also an open question.
    questions = text.split("## Open questions")[1].split("## Deliberate choices")[0]
    assert "Tobias wondered" not in questions
    # Without a model it still reads, and says what is missing.
    plain = ep.brief(_project(tmp_path / "b") if not (tmp_path / "b").mkdir() else None,
                     None, rd.book_report(_project(tmp_path / "b")))
    assert "a model read no chapters" in plain and "Not outlined yet." in plain


def test_the_scorecard_shows_the_pass_and_saves_the_brief(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QFileDialog
    app = QApplication.instance() or QApplication([])
    from src.ui.scorecard_widget import ScorecardWidget
    p, llm, report = _read(tmp_path)
    sc = ScorecardWidget()
    sc.project, sc.report = p, report
    sc._selected = rd.BOOK_ROW
    sc.issues.editor_plan = ep.plan(report)
    sc.issues.show_chapter(rd.book_row(report))
    text = sc.issues.toPlainText()
    assert "Before an editor:" in text and "Clear the mechanical." in text
    assert "Save the editor's brief…" in text
    out = tmp_path / "brief.md"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    sc.issues.brief_requested.emit()
    assert out.read_text(encoding="utf-8").startswith("# Editor's brief: ")
    # A query in a chapter offers "That's intended"; saying so moves it.
    sc._selected = "c1"
    sc.issues.show_chapter(report.chapters[0])
    assert "That's intended" in sc.issues.toPlainText()
    slip = report.chapters[0].results["pov_slips"].items[0]
    sc.issues.intended_requested.emit(slip, "pov_slips", True)
    assert report.chapters[0].results["pov_slips"].count == 0
    assert ep.intended(p) and ep.intended(p)[0]["chapter"] == "Chapter 1"
    sc.issues.show_chapter(report.chapters[0])
    assert "You said these are intended" in sc.issues.toPlainText()
    # Spelling flags are not queries: no such link on them.
    assert not ep.is_query(rd.Item(start=0, end=3, text="teh", reason="x", kind="spelling"))
