"""The book's style sheet: facts recorded per chapter, later chapters read against them."""

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import readiness as rd
from src.ai import story_ledger
from src.data import readiness_state as rs
from src.models.project import Chapter, Manuscript, WriterProject

ONE = ("Mara had never learned to swim, and the sea frightened her. Her eyes were grey as "
       "slate. The rain fell on the harbor all that March morning.\n")
TWO = "Tobias mended the nets by the wall. Nothing else happened that day at all.\n"
THREE = ("Mara dived off the quay and swam hard for the far buoy. Tobias watched her blue eyes "
         "as she climbed out.\n")


class FakeLLM:
    model = "fake"

    def __init__(self):
        self.prompts = []

    def generate_text(self, prompt, system="", **kw):
        self.prompts.append(prompt)
        if "Outline this chapter" in prompt:                     # the chapter digest
            return "SCENE | She | they wait | she decides to go | NONE\nREADER | 3 | fine | NONE"
        if prompt.startswith("OUTLINE OF THE BOOK"):
            return "NONE"
        if prompt.startswith("Proofread the text below"):
            return "NONE"
        if "Look for three kinds of problem" not in prompt:
            n = len(re.findall(r"^\d+\. \[", prompt, re.M))
            return "\n".join(f"{i + 1}. REAL — weak" for i in range(n))
        if "CHAPTER (Chapter 1)" in prompt:
            return ('NONE\n'
                    'FACT | Mara | cannot swim | "Mara had never learned to swim"\n'
                    'FACT | Mara | grey eyes | "Her eyes were grey as slate"\n'
                    'FACT | TIMELINE | a morning in March | "all that March morning"\n'
                    'FACT | Mara | owns a boat | "her little boat rode at anchor"\n')
        if "CHAPTER (Chapter 3)" in prompt and "never learned to swim" in prompt:
            return ('CHARACTER | "Mara dived off the quay and swam hard" | '
                    '"Mara had never learned to swim" | She cannot swim\n'
                    'CONTINUITY | "watched her blue eyes" | "Her eyes were grey as slate" | '
                    'Her eyes were grey\n')
        return "NONE"


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))


def _project(tmp_path):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    for i, t in enumerate((ONE, TWO, THREE)):
        ch = Chapter(id=f"c{i + 1}", number=i + 1, title=f"Chapter {i + 1}",
                     folder_root=p.manuscript.folder_root)
        ch.content = t
        p.manuscript.chapters.append(ch)
    return p


def test_facts_are_recorded_and_a_later_chapter_is_read_against_them(tmp_path):
    p = _project(tmp_path)
    llm = FakeLLM()
    report = rd.book_report(p, llm=llm)
    ledger = story_ledger.for_project(p)
    facts = ledger.all_facts()
    assert [f["fact"] for f in facts] == ["cannot swim", "grey eyes", "a morning in March"]
    assert all(f["chapter"] == "Chapter 1" for f in facts)       # the invented one is dropped
    # Chapter 3 mentions Mara: it was shown her facts, two chapters back.
    reads = [x for x in llm.prompts if "Look for three kinds of problem" in x]
    third = next(x for x in reads if "CHAPTER (Chapter 3)" in x)
    assert "STYLE SHEET" in third and '[Chapter 1] Mara: cannot swim' in third
    first = next(x for x in reads if "CHAPTER (Chapter 1)" in x)
    assert "STYLE SHEET" not in first
    c3 = report.chapters[2].results
    assert c3["character_disconnects"].items[0].reason == (
        "In “Chapter 1”: “Mara had never learned to swim”. She cannot swim. Which is intended?")
    assert "In “Chapter 1”" in c3["continuity"].items[0].reason
    assert "facts recorded from earlier chapters" in c3["continuity"].message
    assert rd.model_work(p) == (0, 3)


def test_only_what_the_facts_touch_is_read_again(tmp_path):
    p = _project(tmp_path)
    rd.book_report(p, llm=FakeLLM())
    # An edit that leaves the facts' words alone: only that chapter is read again.
    p.manuscript.chapters[0].content = ONE + "A gull cried over the water.\n"
    assert rd.model_work(p) == (1, 3)
    llm = FakeLLM()
    rd.book_report(p, llm=llm)
    read = [x for x in llm.prompts if "Look for three kinds of problem" in x]
    assert len(read) == 1 and "CHAPTER (Chapter 1)" in read[0]
    assert rd.model_work(p) == (0, 3)
    assert len(story_ledger.for_project(p).all_facts()) == 3      # kept, not doubled
    # An edit that removes a fact's words: the chapter that was read against it too.
    p.manuscript.chapters[0].content = ONE.replace("Mara had never learned to swim, and the",
                                                   "The")
    assert rd.model_work(p) == (2, 3)                             # chapters 1 and 3
    report = rd.book_report(p)                                    # a scan: not read again yet
    assert report.chapters[2].results["continuity"].status == rd.Status.NEEDS_MODEL


def test_the_style_sheet_leaves_the_rest_of_the_file_alone(tmp_path):
    p = _project(tmp_path)
    rs.update(p, lambda d: d.update({"voice": {"main": {"voice": "plain"}}, "mine": 1}))
    rd.book_report(p, llm=FakeLLM())
    data = rs.load(p)
    assert data["voice"] == {"main": {"voice": "plain"}} and data["mine"] == 1
    assert set(data["ledger"]["main"]) == {"c1", "c2", "c3"}
    assert data["manuscripts"]["main"]["chapters"]["c1"]["judged"]


def test_grouped_for_showing():
    facts = [{"subject": "Mara", "fact": "a"}, {"subject": "TIMELINE", "fact": "t"},
             {"subject": "Ada", "fact": "b"}, {"subject": "Mara", "fact": "c"}]
    assert list(story_ledger.grouped(facts)) == ["Ada", "Mara", "Timeline"]


def test_the_style_sheet_is_shown_from_the_whole_manuscript_row(tmp_path):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from src.ui.readiness_issues import ChapterIssues
    p = _project(tmp_path)
    report = rd.book_report(p, llm=FakeLLM())
    panel = ChapterIssues()
    panel.style_sheet = story_ledger.for_project(p).all_facts()
    panel.show_chapter(rd.book_row(report))
    assert "3 facts recorded from 1 chapter" in panel.toPlainText()
    got = []
    panel.show_requested.connect(lambda cid, quote, at: got.append((cid, quote)))
    panel.show_style_sheet()
    text = panel.toPlainText()
    assert "Mara" in text and "cannot swim" in text and "Timeline" in text
    kind, fact = next(l for l in panel._links if l[0] == "fact")
    from PyQt6.QtCore import QUrl
    panel._on_link(QUrl(f"issue:{panel._links.index((kind, fact))}"))
    assert got == [("c1", fact["quote"])]
    # A chapter row doesn't offer it.
    panel.show_chapter(report.chapters[0])
    assert "Style sheet" not in panel.toPlainText()


def test_the_writer_can_reword_remove_and_put_back_a_fact(tmp_path):
    p = _project(tmp_path)
    rd.book_report(p, llm=FakeLLM())
    ledger = story_ledger.for_project(p)
    swim = "Mara had never learned to swim"
    assert ledger.edit("c1", swim, "Mara", "afraid of deep water")
    assert not ledger.edit("c1", swim, "", "x")                 # empty parts are refused
    assert ledger.remove("c1", "Her eyes were grey as slate")
    fresh = story_ledger.for_project(p)                          # saved
    assert [f["fact"] for f in fresh.all_facts()] == ["afraid of deep water",
                                                      "a morning in March"]
    assert [f["fact"] for f in fresh.removed_facts()] == ["grey eyes"]
    # Chapter 3 was read against those facts: it is read again; chapter 2 is not.
    assert rd.model_work(p) == (1, 3)
    # Reading chapter 1 again (the model lists the same facts) keeps the
    # writer's wording and doesn't bring the removed fact back.
    p.manuscript.chapters[0].content = ONE + "A gull cried.\n"
    rd.book_report(p, llm=FakeLLM())
    again = story_ledger.for_project(p)
    assert [f["fact"] for f in again.all_facts()] == ["afraid of deep water",
                                                      "a morning in March"]
    assert again.restore("c1", "Her eyes were grey as slate")
    assert len(story_ledger.for_project(p).all_facts()) == 3


def test_the_scorecard_changes_the_sheet_from_its_links(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QInputDialog
    app = QApplication.instance() or QApplication([])
    from src.ui.scorecard_widget import ScorecardWidget
    p = _project(tmp_path)
    report = rd.book_report(p, llm=FakeLLM())
    sc = ScorecardWidget()
    sc.project, sc.report = p, report
    sc._load_style_sheet()
    sc.issues.show_style_sheet()
    assert "reword" in sc.issues.toPlainText() and "remove" in sc.issues.toPlainText()
    fact = next(f for f in sc.issues.style_sheet if f["fact"] == "grey eyes")
    sc.issues.sheet_change_requested.emit("remove", fact)
    assert "Removed by you" in sc.issues.toPlainText() and "put back" in sc.issues.toPlainText()
    assert len(sc.issues.style_sheet) == 2
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("Mara: fears the sea", True)))
    swim = next(f for f in sc.issues.style_sheet if f["fact"] == "cannot swim")
    sc.issues.sheet_change_requested.emit("edit", swim)
    assert "fears the sea" in sc.issues.toPlainText()
    sc.issues.sheet_change_requested.emit("restore", sc.issues.style_sheet_removed[0])
    assert len(sc.issues.style_sheet) == 3 and "Removed by you" not in sc.issues.toPlainText()


def test_a_local_model_is_named_by_what_it_loads(monkeypatch):
    from src.ai import llm_client as lc
    monkeypatch.setattr(lc.LLMClient, "_init_mlx_local", lambda self: None)
    cfg = lc.HuggingFaceConfig(model_id="mlx-community/Some-24B-4bit", use_local=True)
    assert lc.LLMClient(provider=lc.LLMProvider.MLX_LOCAL, hf_config=cfg).model == \
        "mlx-community/Some-24B-4bit"
    assert lc.LLMClient(provider=lc.LLMProvider.MLX_LOCAL, hf_config=cfg, model="x").model == "x"
