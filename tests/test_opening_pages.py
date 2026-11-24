"""1.8: the opening pages, held to a stricter standard."""

import os
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import readiness as rd
from src.data import publishing_goal as pg
from src.models.project import Chapter, Manuscript, PlotEvent, WriterProject

BACK = ("Years ago she had lived by the sea. Her father had been a fisherman. "
        "She used to walk the shore at dawn. ") * 6
ACTION = ("Mara grabbed the rope and pulled. \"Hold on,\" she said. "
          "The boat lurched toward the dock. ") * 40


def _project(tmp_path, *texts, novella=None):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    for i, t in enumerate(texts):
        ch = Chapter(id=str(uuid.uuid4()), number=i + 1, title=f"Chapter {i + 1}",
                     folder_root=p.manuscript.folder_root)
        ch.content = t
        p.manuscript.chapters.append(ch)
    if novella:
        sp = p.create_subproject("Novella")
        for i, t in enumerate(novella):
            ch = Chapter(id=str(uuid.uuid4()), number=i + 1, title=f"N{i + 1}",
                         folder_root=sp.manuscript.folder_root)
            ch.content = t
            sp.manuscript.chapters.append(ch)
    return p


def test_an_opening_row_for_each_manuscript(tmp_path):
    p = _project(tmp_path, BACK + ACTION, ACTION, novella=(ACTION, ACTION))
    for book in rd.project_report(p):
        g = rd.grid(book)
        assert g.rows[0][0].chapter_id == rd.OPENING_ROW and g.rows[0][0].title == "Opening pages"
        assert 0 < book.opening_words <= rd.OPENING_WORDS + 60


def test_words_before_something_happens(tmp_path):
    late = _project(tmp_path, BACK * 3 + ACTION)
    r = rd.book_report(late).opening_results["first_action"]
    assert r.measure > 300 and r.status != rd.Status.READY
    assert r.items[0].chapter_id == late.manuscript.chapters[0].id
    assert r.items[0].text.startswith("Mara grabbed")
    soon = _project(tmp_path, ACTION)
    assert rd.book_report(soon).opening_results["first_action"].status == rd.Status.READY


def test_backstory_up_front_and_the_route(tmp_path):
    p = _project(tmp_path, BACK * 2 + ACTION)
    agent = rd.book_report(p).opening_results["backstory"]
    assert agent.status == rd.Status.PROBLEM and agent.count > 5
    assert all("Looks back" in i.reason for i in agent.items)
    pg.set_route(p, None, "self")
    assert rd.book_report(p).opening_results["backstory"].status in (
        rd.Status.NEEDS_WORK, rd.Status.PROBLEM)
    clean = _project(tmp_path, ACTION)
    assert rd.book_report(clean).opening_results["backstory"].status == rd.Status.READY


def test_chapter_one_is_held_to_a_tighter_bar(tmp_path):
    adverby = ("He walked slowly. She smiled warmly. The rain fell softly on the roof. "
               "They waited quietly by the door for an hour or more. ") * 20
    p = _project(tmp_path, adverby, adverby)
    first, second = (c.results["adverbs"] for c in rd.book_report(p).chapters)
    assert first.count == second.count
    order = [rd.Status.READY, rd.Status.NEEDS_WORK, rd.Status.PROBLEM]
    assert order.index(first.status) >= order.index(second.status)
    ctx = lambda route: rd.CheckContext(p, None, p.manuscript.chapters[0], adverby,
                                        is_opening=True, route=route, genre="")
    assert ctx("agent").threshold("adverbs").per_1000[0] < ctx("self").threshold("adverbs").per_1000[0]
    assert ctx("self").threshold("adverbs").per_1000[0] < rd._thresholds()["adverbs"].per_1000[0]


def test_first_plot_event_is_a_labelled_scan(tmp_path):
    p = _project(tmp_path, ACTION, ACTION + " At last Mara reached the harbor lights.")
    assert "first_plot_event" not in rd.book_report(p).opening_results     # no plan events
    p.story_planning.freytag_pyramid.events.append(
        PlotEvent(id="e1", title="The harbor lights", description="Mara reaches them",
                  stage="exposition"))
    r = rd.book_report(p).opening_results["first_plot_event"]
    assert r.items and r.items[0].chapter_id == p.manuscript.chapters[1].id
    assert r.measure > len(ACTION.split()) - 1 and "found by its words" in r.message


class HookLLM:
    model = "fake"

    def __init__(self, reply):
        self.reply = reply

    def generate_text(self, prompt, system="", **kw):
        if prompt.startswith("OPENING PAGES"):
            return self.reply
        return ""                                    # the stage judges: nothing usable


def test_hook_needs_a_model(tmp_path):
    p = _project(tmp_path, ACTION)
    assert rd.book_report(p).opening_results["hook"].status == rd.Status.NEEDS_MODEL
    llm = HookLLM("HOOK: YES — who sent the boat?\nINCIDENT: NO — nothing changes yet\n"
                  "QUOTE: NONE")
    r = rd.book_report(p, llm=llm, use_cache=False).opening_results["hook"]
    assert r.status == rd.Status.NEEDS_WORK and r.judged
    assert any(i.kind == "incident" for i in r.items)
    bad = rd.book_report(p, llm=HookLLM("I liked it."), use_cache=False).opening_results["hook"]
    assert bad.status == rd.Status.COULD_NOT_CHECK


def test_opening_spans_short_chapters(tmp_path):
    short = "Mara grabbed the rope. " * 30
    p = _project(tmp_path, short, short, BACK * 4 + ACTION)
    book = rd.book_report(p)
    assert book.opening_words > len(short.split()) * 2          # reaches into chapter 3
    back = book.opening_results["backstory"]
    ids = {i.chapter_id for i in back.items}
    assert ids <= {c.id for c in p.manuscript.chapters}
