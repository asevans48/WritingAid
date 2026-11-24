"""2.4: the readiness figure over time."""

import os
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from src.ai import readiness as rd
from src.data import readiness_state as rs
from src.models.project import Chapter, Manuscript, WriterProject

BAD = "Its a beutiful day and he dont care. The boats rocked.\n" * 8
GOOD = "It is a beautiful day and he does not care. The boats rocked.\n" * 8


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    """The scan uses LanguageTool when an earlier test left it running; these
    tests compare figures, so keep the checks the same on both days."""
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))


def _project(tmp_path, text):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    ch = Chapter(id=str(uuid.uuid4()), number=1, title="One", folder_root=p.manuscript.folder_root)
    ch.content = text
    p.manuscript.chapters.append(ch)
    return p


def test_two_checks_on_different_days_show_a_change(tmp_path, monkeypatch):
    p = _project(tmp_path, BAD)
    monkeypatch.setattr(rd, "_today", lambda: "2026-11-21")
    first = rd.book_report(p)
    assert rd.change_since_last(first) is None                  # nothing earlier yet
    p.manuscript.chapters[0].content = GOOD
    monkeypatch.setattr(rd, "_today", lambda: "2026-11-23")
    second = rd.book_report(p)
    delta, day = rd.change_since_last(second)
    seen = lambda r: {k: (v.status, v.count) for k, v in r.chapters[0].results.items()
                      if v.status != "info"}
    assert day == "2026-11-21" and delta > 0, (seen(first), seen(second))
    assert [e["date"] for e in second.history] == ["2026-11-21", "2026-11-23"]


def test_one_entry_a_day(tmp_path, monkeypatch):
    p = _project(tmp_path, BAD)
    monkeypatch.setattr(rd, "_today", lambda: "2026-11-23")
    rd.book_report(p)
    p.manuscript.chapters[0].content = GOOD
    rd.book_report(p)
    h = rs.history(p, None)
    assert len(h) == 1 and h[0]["readiness"] == pytest.approx(rd.book_report(p).readiness, abs=1e-4)


def test_a_changed_formula_shows_no_false_change(tmp_path, monkeypatch):
    p = _project(tmp_path, BAD)
    monkeypatch.setattr(rd, "_today", lambda: "2026-11-21")
    rd.book_report(p)
    monkeypatch.setattr(rd, "THRESHOLDS_VERSION", rd.THRESHOLDS_VERSION + 1)
    monkeypatch.setattr(rd, "_today", lambda: "2026-11-23")
    assert rd.change_since_last(rd.book_report(p)) is None


def test_the_scorecard_shows_the_change(qapp, tmp_path, monkeypatch):
    from src.ui.scorecard_widget import ScorecardWidget
    p = _project(tmp_path, BAD)
    for n in (2, 3):                              # misspellings across the book: a major issue
        ch = Chapter(id=str(uuid.uuid4()), number=n, title=f"C{n}",
                     folder_root=p.manuscript.folder_root)
        ch.content = BAD + f"Chapter {n} ends.\n"
        p.manuscript.chapters.append(ch)
    monkeypatch.setattr(rd, "_today", lambda: "2026-11-21")
    assert rd.verdict(rd.book_report(p)).majors >= 1
    for ch in p.manuscript.chapters:
        ch.content = ch.content.replace(BAD, GOOD)
    monkeypatch.setattr(rd, "_today", lambda: "2026-11-23")
    report = rd.book_report(p)
    sc = ScorecardWidget()
    sc.project = p
    sc._render(report)
    assert "▼" in sc.trend_label.text() and "major issue" in sc.trend_label.text()
    assert "since 21 Nov" in sc.trend_label.text()
    assert "2026-11-21" in sc.trend_label.toolTip()


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])



# ── The verdict: three tiers ──────────────────────────────────────────────

R, W, P, M = rd.Status.READY, rd.Status.NEEDS_WORK, rd.Status.PROBLEM, rd.Status.NEEDS_MODEL
STAGE = {"adverbs": "line", "spelling_grammar": "copyedit", "dialogue_problems": "scene",
         "plot_jumps": "structure", "character_disconnects": "scene"}


def _book(**checks):
    """A book from check name → one status per chapter."""
    rd.checks_for()
    book = rd.BookReport(scope=None, name="B", kind="novel")
    n = max(len(v) for v in checks.values())
    for i in range(n):
        ch = rd.ChapterReport(None, f"c{i}", i + 1, f"C{i}", 100, "h", is_opening=(i == 0))
        for name, statuses in checks.items():
            if i < len(statuses):
                ch.results[name] = rd.CheckResult(name, STAGE[name], statuses[i],
                                                  2 if statuses[i] in (W, P) else 0)
        book.chapters.append(ch)
    book.readiness, book.cells = rd._figure(book)
    return book


def test_polish_never_blocks():
    v = rd.verdict(_book(adverbs=[P, P, P, W], spelling_grammar=[R, R, R, R]))
    assert v.level == "ready" and v.title == "Ready to send"
    assert "No major issues." in v.detail and "4 optional polish items" in v.detail


def test_a_major_issue_at_problem_means_a_revision_pass():
    v = rd.verdict(_book(spelling_grammar=[P, R, R], adverbs=[R, R, R]))
    assert v.level == "revise" and v.majors == 1
    assert "Major issues: spelling and grammar left in 1 chapter." in v.detail
    story = rd.verdict(_book(spelling_grammar=[R, R], plot_jumps=[R, P],
                             character_disconnects=[W, R]))
    assert story.level == "revise"
    assert "2 plot jumps in 1 chapter" in story.detail
    assert "2 character disconnects in 1 chapter" in story.detail


def test_lighter_major_issues_or_another_factor_mean_nearly_there():
    light = rd.verdict(_book(spelling_grammar=[W, R, R]))
    assert light.level == "nearly"
    factor = rd.verdict(_book(spelling_grammar=[R, R], dialogue_problems=[P, R]))
    assert factor.level == "nearly" and "Before polish: dialogue problems in 1 chapter" in factor.detail
    both = rd.verdict(_book(spelling_grammar=[P, R], dialogue_problems=[P, R]))
    assert "Major issues:" in both.detail and "Then: dialogue problems" in both.detail


def test_unread_major_checks_are_said_plainly():
    v = rd.verdict(_book(spelling_grammar=[R, R], plot_jumps=[M, M], adverbs=[R, R]))
    assert v.level == "ready" and v.title == "Ready, as far as checked"
    assert "Not read yet (needs the model): plot jumps" in v.detail
    assert rd.verdict(rd.BookReport(None, "B", "novel")).level == "unchecked"
