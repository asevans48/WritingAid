"""8.2: the editorial letter, with and without a model."""

import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))

from src.ai import editorial_letter as el
from src.ai import readiness as rd
from src.data import readiness_state as rs
from test_chapter_digest import FakeLLM as DigestLLM, _project

LETTER = (
    "WORKS | The key gives the opening a clear secret | Chapter 1\n"
    "ISSUE | Plot | The ledgers are set up and never opened again | Chapter 2; Chapter 3 | "
    "A reader waits for an answer that never comes | Show what the ledgers hold, or cut "
    "their weight in chapter 2\n"
    "ISSUE | Structure | The market scene changes nothing | Chapter 1 | The tension the key "
    "built drains away | If the scene is a deliberate rest, keep it; if not, fold it into "
    "the supper\n"
    "ISSUE | Plot | Invented | Chapter 99 | x | y\n"                       # no such chapter
    "ISSUE | Marketing | Not an element | Chapter 1 | x | y\n"
    "CANNOT | Whether the prose carries the mood\n")


class LLM(DigestLLM):
    def generate_text(self, prompt, system="", **kw):
        if "Write the manuscript evaluation" in prompt:
            self.prompts.append(prompt)
            self.system = system
            return LETTER
        return super().generate_text(prompt, system, **kw)


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))


def test_the_letter_is_written_from_the_outline_and_points_to_real_chapters(tmp_path):
    p = _project(tmp_path)
    llm = LLM(unpaid="2 | what the ledgers show is never told")
    report = rd.book_report(p, llm=llm)
    letter = el.write(llm, p, None, report)
    asked = llm.prompts[-1]
    assert "## Chapter 2 (reader's pull 4/5)" in asked            # the outline, not the text
    assert "Setups never paid off (Plot): 1" in asked              # the scorecard's findings
    assert "Inside lay her father's ledgers." not in asked
    assert "HOW TO PUT A FINDING" in llm.system
    assert [(i["element"], i["chapters"]) for i in letter["issues"]] == [
        ("Plot", ["c2", "c3"]), ("Structure", ["c1"])]             # the two it can't place: dropped
    assert letter["works"][0]["chapters"] == ["c1"] and letter["model"] == "outliner"
    saved = el.stored(p)
    assert saved["issues"] == letter["issues"] and saved["stale"] is False
    p.manuscript.chapters[0].content += "More.\n"
    assert el.stored(p)["stale"] is True
    assert set(rs.load(p)) >= {"letter", "digest", "ledger", "manuscripts"}


def test_without_a_model_it_is_assembled_from_the_scorecard(tmp_path):
    p = _project(tmp_path)
    llm = LLM(unpaid="2 | what the ledgers show is never told")
    report = rd.book_report(p, llm=llm)
    letter = el.write(None, p, None, report)
    assert letter["from_scan"] and "No model is set up" in letter["note"]
    first = letter["issues"][0]
    assert first["issue"].startswith(("Setups never paid off", "Scenes that change nothing",
                                      "Reader's pull"))
    assert all(i["chapters"] for i in letter["issues"])
    # Before anything is outlined, the same.
    q = _project(tmp_path / "other") if (tmp_path / "other").mkdir() is None else None
    scan = el.write(LLM(), q, None, rd.book_report(q))
    assert scan["from_scan"] and "haven't been outlined yet" in scan["note"]


def test_the_letter_reads_as_a_letter_and_says_what_it_cannot_judge(tmp_path):
    p = _project(tmp_path)
    llm = LLM()
    report = rd.book_report(p, llm=llm)
    letter = el.write(llm, p, None, report)
    titles = {c.id: c.title for c in p.manuscript.chapters}
    page = el.to_html(letter, titles, lambda cid: f"ch:{cid}",
                      {"ink": "#000", "ink_soft": "#333", "ink_faint": "#666"})
    text = re.sub(r"<[^>]+>", " ", page)
    for want in ("Editorial letter", "one reader's view", "What works",
                 "1. Plot: The ledgers are set up and never opened again.",
                 "Effect on a reader:", "An option:", "What this letter couldn't judge",
                 "Whether the prose carries the mood.", "least reliable part",
                 "cannot tell whether an agent"):
        assert want in text, want
    assert "href='ch:c2'" in page


def test_the_scorecard_writes_and_shows_it_from_the_whole_manuscript_row(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import src.ui.scorecard_model_run as smr
    from src.ui import background
    from src.ui.scorecard_widget import ScorecardWidget
    monkeypatch.setattr(smr, "ai_available", lambda: True)
    p = _project(tmp_path)
    llm = LLM()
    report = rd.book_report(p, llm=llm)
    sc = ScorecardWidget()
    sc.llm_factory = lambda: llm
    sc.project, sc.report = p, report
    sc.issues.show_chapter(rd.book_row(report))
    assert "Write the letter" in sc.issues.toPlainText()
    sc.issues.letter_requested.emit("write")
    for _ in range(100):
        background.wait_all(5000)
        app.processEvents()
        if sc._letter_task is None:
            break
    text = sc.issues.toPlainText()
    assert "Editorial letter" in text and "What to work on, most important first" in text
    assert "write it again" in text and "back to the checks" in text
    sc.issues.show_chapter(rd.book_row(report))
    assert "Show the letter" in sc.issues.toPlainText()
