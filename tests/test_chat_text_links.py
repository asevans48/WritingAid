"""Chat findings link to the manuscript passage that needs work."""

import os
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import text_links as tl

TEXT = ("Mara walked the length of the pier at Greywater. The boards were wet.\n\n"
        "“You’re late,” Tobin said, not looking up from the nets.\n\n"
        "She dove off the pier into the black sea without a second thought.")
CHAPTERS = [("c1", "The Pier", TEXT), ("c2", "Other", "Something else entirely happens here.")]


@pytest.mark.parametrize("snippet", [
    "the boards were wet",                                   # case
    "\"You're late,\" Tobin said",                           # straight vs curly quotes
    "dove off the pier   into the black sea",                # whitespace
    "Mara walked the length … at Greywater",                 # elision
    "she dives off the pier into the black sea, careless",   # paraphrase (shared run)
])
def test_locate_tolerates_model_quoting(snippet):
    hit = tl.locate(TEXT, snippet)
    assert hit is not None
    assert len(TEXT[hit[0]:hit[1]].split()) >= 3


def test_locate_rejects_filler_and_absent_text():
    assert tl.locate(TEXT, "at the end of the day and then") is None
    assert tl.locate(TEXT, "the dragon burned the abbey to ash") is None


def test_link_roundtrip():
    link = tl.make_link("c 1/x", "Tobin said, “go” & leave")
    url = link[link.index("(") + 1:-1]
    assert tl.parse_link(url) == ("c 1/x", "Tobin said, “go” & leave")


def test_add_passage_links_to_reply():
    reply = ('The line "She dove off the pier into the black sea" undercuts her fear. '
             'Compare "a line that is not in the book at all".\n```\n"She dove off the pier" in code\n```')
    out = tl.add_passage_links(reply, CHAPTERS, "c1")
    assert out.count("](wa-goto:c1?q=") == 1                       # only the real quote, not code
    assert '"She dove off the pier into the black sea" [↗](wa-goto:' in out
    assert tl.add_passage_links(out, CHAPTERS, "c1") == out          # idempotent


def test_critique_findings_get_links():
    import tests.test_critique_canon_reports as canon
    from src.ai.chat_actions import format_critique_for_chat
    from src.ai.chapter_analysis_agent import CritiqueOrchestrator, ReportType
    report = CritiqueOrchestrator(primary_llm=canon.LocalLLM(), project=canon._project()).run(
        chapters=[{"title": "Chapter 2", "text": canon.CHAPTER, "index": 1}],
        report_types=[ReportType.CHARACTER], genre_key_or_text="default", manuscript_context="")
    out = format_critique_for_chat(report, [], chapters=[("ch2", "Chapter 2", canon.CHAPTER)])
    drift = next(l for l in out.splitlines() if "Mara — Fears" in l)
    assert "[↗ go to text](wa-goto:ch2?q=" in drift
    planned = next(l for l in out.splitlines() if "missing from the prose: Eli" in l)
    assert "wa-goto" not in planned                                   # nothing to point at


def test_promise_check_quotes_get_links():
    from src.ai.chapter_analysis_agent import PromiseCheckResult, PromiseViolation
    from src.ai.chat_actions import format_critique_for_chat
    res = PromiseCheckResult("The Pier", "needs_attention",
                             [PromiseViolation("Mara fears water", "character", "Dives in fearlessly",
                                               "She dove off the pier", "high", "Add hesitation")],
                             [], "", "", "Stalls.")
    out = format_critique_for_chat(NS(overall_summary="", chapters=[]), [res], chapters=CHAPTERS)
    assert "wa-goto:c1?q=She%20dove%20off%20the%20pier" in out


# ── UI ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_chat_widget_renders_clickable_link(app):
    from PyQt6.QtCore import QUrl
    from src.ui.chat_widget import ChatWidget
    w = ChatWidget()
    got = []
    w.passage_link_clicked.connect(lambda cid, q: got.append((cid, q)))
    w.add_message("Assistant", "**Fix:** tighten this " + tl.make_link("c1", "The boards were wet"))
    assert 'href="wa-goto:c1?q=The%20boards%20were%20wet"' in w.chat_history.toHtml()
    w._on_chat_link_clicked(QUrl("wa-goto:c1?q=The%20boards%20were%20wet"))
    assert got == [("c1", "The boards were wet")]


def test_navigate_selects_passage_in_other_chapter(app):
    from src.models.project import Chapter, WriterProject
    from src.ui.manuscript_editor import ManuscriptEditor
    from src.ui.main_window import MainWindow
    proj = WriterProject(name="t")
    proj.manuscript.chapters = [Chapter(id="c1", number=1, title="One", content="Nothing here."),
                                Chapter(id="c2", number=2, title="The Pier", content=TEXT)]
    me = ManuscriptEditor(proj)
    me.load_manuscript(proj.manuscript)
    me.open_chapter("c1")
    status = []
    win = NS(current_project=proj, manuscript_editor=me,
             tab_widget=NS(setCurrentWidget=lambda w: None),
             statusBar=lambda: NS(showMessage=lambda *a: status.append(a[0])))
    MainWindow._navigate_to_passage(win, "c2", "dove off the pier into the black sea")
    ce = me.current_chapter_editor
    assert ce.chapter.id == "c2"
    assert ce.editor.textCursor().selectedText() == "dove off the pier into the black sea"
    assert any(s.format.background().color().name() == "#fde68a"
               for s in ce.editor.extraSelections())
    MainWindow._navigate_to_passage(win, "c2", "a dragon burned the abbey")
    assert "wasn't found" in status[-1]
