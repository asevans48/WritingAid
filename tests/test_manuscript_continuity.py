"""Manuscript critique from the menu / tab right-click, and continuity
across novellas."""

import os
import time
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai.continuity_analysis import (
    ContinuityAnalyzer, has_cross_manuscript_content, manuscripts_with_text,
)
from src.models.project import Chapter, Character, WriterProject
from src.models.worldbuilding_objects import Faction, FactionType

MAIN = ("Mara walked the pier at Greywater. The Ash Wardens watched from the wall. "
        "Tobin met her at the Saltmarket.\n\n"
        "In the storm Tobin drowned off the pier, and Mara watched him die.")
BOOK2 = ("Years later Mara sailed north with the Ash Wardens. Tobin laughed at the helm "
         "and said the Saltmarket would never change.\n\nTobin mended the nets again.")
BOOK3 = "A quiet book about the Saltmarket traders, far from anyone we know."


def _project():
    p = WriterProject(name="Saga")
    p.characters = [Character(id="c1", name="Mara", character_type="protagonist",
                              personality="guarded"),
                    Character(id="c2", name="Tobin", character_type="minor")]
    p.worldbuilding.factions = [Faction(id="f1", name="Ash Wardens",
                                        faction_type=FactionType.MILITARY,
                                        description="Seized Greywater ten years ago.")]
    p.manuscript.title = "The Pier"
    p.manuscript.chapters = [Chapter(id="m1", number=1, title="Storm", content=MAIN)]
    for name, text, cid in (("Northward", BOOK2, "n1"), ("Traders", BOOK3, "t1")):
        sp = p.create_subproject(name)
        sp.manuscript.chapters = [Chapter(id=cid, number=1, title=f"{name} 1", content=text)]
    return p


def test_manuscripts_and_presence_map():
    p = _project()
    books = manuscripts_with_text(p)
    assert [b["label"] for b in books] == ["The Pier", "Northward", "Traders"]
    assert has_cross_manuscript_content(p)
    s = ContinuityAnalyzer(p).run()
    shared = s.extra_lists["Shared across manuscripts"]
    assert any(x.startswith("Mara — The Pier") and "Northward" in x for x in shared)
    assert any(x.startswith("Ash Wardens") for x in shared)
    assert s.metrics["manuscripts_compared"] == 3


def test_resurrection_and_unrecorded_shared_names():
    s = ContinuityAnalyzer(_project()).run()
    res = [x for x in s.major_issues if x.startswith("Tobin — described as dead in The Pier")]
    assert res and "appears in Northward" in res[0] and "drowned" in res[0]
    assert not any(x.startswith("Mara — described as dead") for x in s.major_issues)
    assert any(x.startswith("Saltmarket — in The Pier, Northward, Traders")
               for x in s.extra_lists["Shared names with no record"])


def test_single_manuscript_has_nothing_to_compare():
    p = WriterProject(name="Solo")
    p.manuscript.chapters = [Chapter(id="m1", number=1, title="One", content=MAIN)]
    assert not has_cross_manuscript_content(p)
    s = ContinuityAnalyzer(p).run()
    assert "Fewer than two manuscripts" in s.minor_issues[0]


class ContinuityLLM:
    compact_prompts = True

    def __init__(self):
        self.prompts = []

    def generate_text(self, prompt, system=None, **kw):
        self.prompts.append(prompt)
        if "HOW TOBIN APPEARS" in prompt:
            return ("[CONFLICT] Tobin — The Pier vs Northward: \"Tobin drowned off the pier\" "
                    "vs \"Tobin laughed at the helm\"")
        if "HOW MARA APPEARS" in prompt:
            return ("[CONSISTENT] Mara — still guarded in both\n"
                    "[CONFLICT] Mara — The Pier vs Northward: green eyes vs grey eyes")
        if "Check continuity ACROSS the books" in prompt:
            return ("[TIMELINE] none\n[THREAD] The Pier's missing Gull is never mentioned again\n"
                    "[RECOMMEND] Explain Tobin's survival in Northward ch. 1")
        return "[CONSISTENT] Ash Wardens — same order in both"


def test_model_checks_shared_elements_and_threads():
    llm = ContinuityLLM()
    s = ContinuityAnalyzer(_project(), llm).run()
    # The model's Tobin conflict repeats the deterministic resurrection
    # finding, so only one Tobin entry remains; distinct conflicts stay.
    assert sum(x.startswith("Tobin") for x in s.major_issues) == 1
    assert "Mara — The Pier vs Northward: green eyes vs grey eyes" in s.major_issues
    assert "Mara — still guarded in both" in s.strengths
    assert any("missing Gull" in x for x in s.extra_lists["Open threads across books"])
    assert s.suggestions[-1] == "Explain Tobin's survival in Northward ch. 1"
    assert any(c["label"] == "timeline & threads" for c in s.calls)
    tobin_prompt = next(p for p in llm.prompts if "HOW TOBIN APPEARS" in p)
    assert "[BOOK: The Pier]" in tobin_prompt and "[BOOK: Northward]" in tobin_prompt


def test_chat_continuity_intent():
    from src.ai.chat_actions import detect_intent
    assert detect_intent("check continuity across the novellas") == \
        {"kind": "critique", "scope": "continuity"}
    assert detect_intent("Is the series continuity holding up between books?") == \
        {"kind": "critique", "scope": "continuity"}


# ── UI ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wait(grader, results, n=1):
    from PyQt6.QtCore import QCoreApplication
    grader._worker.wait(60000)
    end = time.time() + 10
    while len(results) < n and time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def test_critique_a_novella_that_isnt_open(app, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    import src.ai.task_llm as tl
    from src.ai.chapter_analysis_agent import ReportType
    from src.ui.grader_widget import GraderWidget
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(tl, "build_critique_llm", lambda spec="": None)
    monkeypatch.setattr(tl, "build_default_llm", lambda: None)      # dashboard mode
    p = _project()
    g = GraderWidget()
    g.set_project(p)
    sp_id = p.subprojects[0].id
    done = []
    err = g.run_manuscript_critique(sp_id, report_types=[ReportType.CHARACTER],
                                    on_done=lambda r, e: done.append((r, e)))
    assert err is None
    _wait(g, done)
    report, e = done[0]
    assert e is None and [c.chapter_title for c in report.chapters] == ["Northward 1"]
    assert report.scope_label == "Northward"
    assert "Continuity" not in [g.results_tabs.tabText(i) for i in range(g.results_tabs.count())]


def test_main_project_with_continuity(app, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    import src.ai.task_llm as tl
    from src.ai.chapter_analysis_agent import ReportType
    from src.ui.grader_widget import GraderWidget
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(tl, "build_critique_llm", lambda spec="": ContinuityLLM())
    p = _project()
    g = GraderWidget()
    g.set_project(p)
    done = []
    assert g.run_manuscript_critique(None, include_continuity=True,
                                     report_types=[ReportType.CHARACTER],
                                     on_done=lambda r, e: done.append(r)) is None
    _wait(g, done)
    report = done[0]
    assert [c.chapter_title for c in report.chapters] == ["Storm", "Across novellas"]
    assert "Continuity across novellas" in report.overall_summary
    tabs = [g.results_tabs.tabText(i) for i in range(g.results_tabs.count())]
    assert "Continuity" in tabs and "Characters" in tabs
    # Continuity-only run skips chapter reports.
    done.clear()
    assert g.run_manuscript_critique(None, include_continuity=True, report_types=[],
                                     on_done=lambda r, e: done.append(r)) is None
    _wait(g, done)
    assert [c.chapter_title for c in done[0].chapters] == ["Across novellas"]


def test_tab_right_click_and_review_menu_route_to_grader(app):
    from PyQt6.QtWidgets import QMenu
    from src.ui.main_window import MainWindow
    p = _project()
    calls = []
    win = NS(current_project=p, manuscript_editor=NS(current_chapter_editor=None),
             tab_widget=NS(setCurrentWidget=lambda w: None),
             grader_widget=NS(run_manuscript_critique=lambda scope, **kw: calls.append((scope, kw))))
    win._run_manuscript_critique = MainWindow._run_manuscript_critique.__get__(win)
    win._critique_current_chapter_from_menu = lambda: None
    win._open_consistency_dialog = lambda: None
    MainWindow._on_manuscript_critique_requested(win, p.subprojects[0].id, False)
    MainWindow._on_manuscript_critique_requested(win, "", True)
    MainWindow._on_manuscript_critique_requested(win, "__continuity__", True)
    assert calls == [
        (p.subprojects[0].id, {"include_continuity": False, "report_types": None}),
        (None, {"include_continuity": True, "report_types": None}),
        (None, {"include_continuity": True, "report_types": []}),
    ]
    win.review_menu = QMenu()
    MainWindow._populate_review_menu(win)
    labels = [a.text() for a in win.review_menu.actions()]
    assert "Critique Main Manuscript “The Pier”…" in labels
    assert "Critique Main Project + Continuity Across Novellas…" in labels
    assert "Check Continuity Across Novellas…" in labels
    assert "Check Consistency (names, spellings, style)…" in labels
    novellas = next(a.menu() for a in win.review_menu.actions() if a.text() == "Critique Novella")
    assert [a.text() for a in novellas.actions()] == ["“Northward”…", "“Traders”…"]
