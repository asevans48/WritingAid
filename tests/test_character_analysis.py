"""P.8: character analysis across the book.

No model is ever run: the arc's model tier uses a fake with a fixed reply.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

USUAL = ('Mara looked at the harbour. "I don\'t know where it\'s gone," Mara said.\n'
         '"We\'ll look again when it\'s light, won\'t we?" Mara said.\n'
         '"It isn\'t far. I\'m sure it\'s past the rocks," Mara said.\n'
         '"Don\'t wait for me," Mara said.\n"I\'ll get the lamp," Mara said.')
FORMAL = ('Mara looked at the harbour. "I shall not go," Mara said.\n'
          '"Indeed, I do not know where it is," Mara said.\n"It is not possible," Mara said.\n'
          '"We shall see what the morning brings," Mara said.\n"I do not wait," Mara said.')
TOBIN = '\n\nTobin came in from the rain. "Go," Tobin said. "Now."'


def _book(n=20, away=range(4, 14), formal=(15,), dropout_after=None):
    """``n`` chapters; Tobin away for the chapters in ``away``; Mara formal
    in ``formal``; Tobin gone after ``dropout_after`` if given."""
    from src.models.project import Chapter, Character, WriterProject
    p = WriterProject(name="Book")
    p.characters = [Character(id="m", name="Mara Venn", character_type="protagonist"),
                    Character(id="t", name="Tobin", character_type="supporting"),
                    Character(id="v", name="Voss", character_type="minor")]
    for i in range(n):
        text = FORMAL if i in formal else USUAL
        gone = dropout_after is not None and i > dropout_after
        if i not in away and not gone:
            text += TOBIN
        p.manuscript.chapters.append(Chapter(id=f"c{i + 1}", number=i + 1,
                                             title=f"Chapter {i + 1}", content=text))
    return p


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ── Without a model ────────────────────────────────────────────────────

def test_a_character_away_for_ten_chapters_is_shown_as_absent():
    from src.ai import character_analysis as ca
    a = ca.analyse(_book())["Tobin"]
    assert a.chapters_present == 10
    [gap] = a.books[0].gaps
    assert gap.chapters == 10
    assert (gap.after.title, gap.back.title) == ("Chapter 4", "Chapter 15")
    assert any("away for 10 chapters" in line for line in ca.summary_lines(a))
    # Present throughout: no gap.
    assert not ca.analyse(_book())["Mara Venn"].books[0].gaps


def test_a_character_whose_speech_changes_sharply_is_marked():
    from src.ai import character_analysis as ca
    a = ca.analyse(_book())["Mara Venn"]
    [shift] = a.shifts
    assert shift.title == "Chapter 16"
    assert any("contractions" in c for c in shift.changes)
    assert any("formal" in c for c in shift.changes)
    assert shift.sample                                   # a line to link to
    assert "changes sharply in 1 chapter" in a.consistency()


def test_shorter_lines_are_marked_and_a_steady_speaker_is_not():
    from src.ai import character_analysis as ca
    from src.ai.dialogue_craft import _measure
    long = _measure("x", ["I have been walking along the shore all morning looking for "
                          "the little boat my father left there years ago"] * 5)
    short = _measure("x", ["No.", "Go now.", "Not here.", "Later.", "Fine."])
    assert any("lines average" in c for c in ca.compare(short, long))
    steady = ca.analyse(_book(formal=()))["Mara Venn"]
    assert not steady.shifts
    assert "holds" in steady.consistency()


def test_speech_share_counts_attributed_lines():
    from src.ai import character_analysis as ca
    found = ca.analyse(_book())
    mara, tobin, voss = found["Mara Venn"], found["Tobin"], found["Voss"]
    assert mara.lines == 100 and tobin.lines == 20
    assert abs(mara.share + tobin.share - 1) < 1e-9
    assert (mara.rank, tobin.rank, voss.rank) == (1, 2, 0)
    assert not voss.books and "not named" in ca.summary_lines(voss)[0]


def test_the_drop_out_check_is_used_not_repeated():
    from src.ai import character_analysis as ca
    from src.ai.readiness import Book, BookContext
    from src.ai.readiness_checks.editor import character_threads
    p = _book(n=12, away=(), formal=(), dropout_after=5)
    expected = character_threads(BookContext(p, None, Book(p, None), [], route="", genre=""))
    [item] = expected.items
    b = ca.analyse(p)["Tobin"].books[0]
    assert b.dropped == item.reason and b.dropped_chapter == item.chapter_id == "c6"


def test_results_are_cached_by_chapter_text(monkeypatch):
    from src.ai import canon_index, character_analysis as ca
    calls = []
    real = canon_index.find_mentions
    monkeypatch.setattr(canon_index, "find_mentions",
                        lambda text, names: calls.append(text) or real(text, names))
    ca._SCAN_CACHE.clear()
    ca._RESULT_CACHE.clear()
    p = _book()
    ca.analyse(p)
    first = len(calls)
    assert first >= 20
    calls.clear()
    assert ca.analyse(p)["Tobin"].chapters_present == 10      # opening it again
    assert calls == []                                        # nothing read again
    scanned = len(ca._SCAN_CACHE)
    p.manuscript.chapters[0].content += "\nMara slept."
    assert ca.analyse(p)["Mara Venn"].chapters_present == 20
    assert len(ca._SCAN_CACHE) == scanned + 1                 # only the changed chapter


def test_the_analysis_changes_nothing_in_the_project():
    from src.ai import character_analysis as ca
    p = _book()
    before = p.model_dump_json()
    ca.analyse(p)
    ca.describe_arc(p, p.characters[0], None)
    assert p.model_dump_json() == before


# ── The arc ────────────────────────────────────────────────────────────

class FakeLLM:
    model = "fake"

    def __init__(self, reply="START: Mara hides.\nTURNS: none\nEND: Mara speaks.\nEARNED: yes."):
        self.reply, self.prompts = reply, []

    def generate_text(self, prompt, system_prompt="", **kw):
        self.prompts.append(prompt)
        return self.reply


def test_without_a_model_the_arc_says_it_needs_one():
    from src.ai import character_analysis as ca
    p = _book()
    assert "needs a model" in ca.describe_arc(p, p.characters[0], None)


def test_with_a_model_the_arc_asks_once_with_the_passages():
    from src.ai import character_analysis as ca
    from src.models.project import PersonalitySnapshot
    p = _book()
    p.characters[0].personality_arc = [PersonalitySnapshot(
        chapter_id="c3", chapter_number=3, chapter_title="Chapter 3",
        emotional_state="wary", growth_notes="starts to trust Tobin")]
    llm = FakeLLM()
    assert ca.describe_arc(p, p.characters[0], llm).startswith("START: Mara hides.")
    [prompt] = llm.prompts
    assert "[Chapter 1]" in prompt and "[Chapter 20]" in prompt
    assert "starts to trust Tobin" in prompt
    with pytest.raises(RuntimeError):
        ca.describe_arc(p, p.characters[0], FakeLLM("Error generating text: offline"))
    # Named nowhere: nothing to ask.
    quiet = FakeLLM()
    assert "not named" in ca.describe_arc(p, p.characters[2], quiet) and not quiet.prompts


# ── The Characters screen ──────────────────────────────────────────────

def _page(qapp, project, index):
    from src.ui.characters_widget import CharacterWidget
    return CharacterWidget(project.characters[index], project=project,
                           available_characters=project.characters)


def test_the_section_is_closed_by_default_and_remembers(qapp):
    p = _book()
    page = _page(qapp, p, 1)
    s = page.across_book
    assert not s.is_open() and s.analysis is None          # the book is not read until opened
    s.header.click()                                       # open: remembered, and it reads
    from src.ui import background
    background.wait_all()
    qapp.processEvents()
    assert s.is_open()
    page2 = _page(qapp, p, 1)
    assert page2.across_book.is_open()                     # the next character opens open
    background.wait_all()
    qapp.processEvents()
    assert page2.across_book.analysis is not None


def test_the_section_shows_absence_and_a_change_of_speech(qapp, monkeypatch):
    from src.ui import character_book_section as cbs
    monkeypatch.setattr(cbs, "model_available", lambda: False)
    p = _book()
    tobin = _page(qapp, p, 1).across_book
    cbs.refresh(tobin, sync=True)
    text = tobin.label.text()
    assert "In 10 of 20 chapters" in text and "Away for 10 chapters" in text
    assert "wa-goto:c4" in text and "wa-goto:c15" in text            # chapter links
    assert "needs a model" in text
    mara = _page(qapp, p, 0).across_book
    cbs.refresh(mara, sync=True)
    text = mara.label.text()
    assert "Chapter 16" in text and "contractions" in text and "wa-goto:c16" in text


def test_a_link_opens_the_passage_in_write(qapp, monkeypatch):
    from src.ui import analysis_menu, character_book_section as cbs
    import src.ui.revision_controller as rc
    shown = []

    class _RC:
        def __init__(self, mw):
            self.mw = mw

        def show_passage(self, cid, passage, offset=0):
            shown.append((cid, passage))
            return True
    monkeypatch.setattr(rc, "RevisionController", _RC)
    monkeypatch.setattr(analysis_menu, "main_window_of", lambda w: object())
    p = _book()
    s = _page(qapp, p, 1).across_book
    cbs.refresh(s, sync=True)
    from src.ai.text_links import make_link
    url = make_link("c4", "Tobin came in from the rain.").split("](", 1)[1][:-1]
    cbs.on_link(s, url)
    assert shown == [("c4", "Tobin came in from the rain.")]


def test_the_arc_link_asks_the_model_and_shows_the_answer(qapp, monkeypatch):
    from src.ui import character_book_section as cbs
    monkeypatch.setattr(cbs, "model_available", lambda: True)
    p = _book()
    s = _page(qapp, p, 0).across_book
    cbs.refresh(s, sync=True)
    assert cbs.ARC_LINK in s.label.text()
    llm = FakeLLM()
    cbs.ask_arc(s, llm=llm, sync=True)
    assert "Mara hides." in s.label.text() and len(llm.prompts) == 1
    # No model after all (nothing set up): it says so in place.
    from src.ai import character_analysis as ca
    monkeypatch.setattr(ca, "arc_llm", lambda: None)
    s2 = _page(qapp, p, 0).across_book
    cbs.refresh(s2, sync=True)
    cbs.ask_arc(s2, sync=True)
    assert "needs a model" in s2.label.text()


# ── The Critique's Character check ─────────────────────────────────────

def _check(project, at, llm):
    from src.ai.analysis_reports import AnalysisKind
    from src.ai.chapter_analysis_agent import CritiqueOrchestrator
    from src.ai.critique_parts import run_in_parts
    ch = project.manuscript.chapters[at]
    report = run_in_parts(CritiqueOrchestrator(primary_llm=llm, project=project),
                          [{"title": ch.title, "text": ch.content, "index": at, "id": ch.id}],
                          [AnalysisKind.CHARACTER_CHECK], "default", "",
                          extra={"run_kind": "analysis:characters"})
    return report.chapters[0].sections[0]


def test_the_character_check_shows_the_scan_without_a_model():
    p = _book()
    s = _check(p, 14, None)                       # Chapter 15: Tobin is back
    assert s.summary.startswith("No model is set up") and "\n" not in s.summary
    assert "Across the book (a scan)" in s.narrative
    assert "back after 10 chapters away" in s.narrative and "wa-goto:c4" in s.narrative
    s = _check(p, 15, None)                       # Chapter 16: Mara speaks formally
    assert "their speech changes" in s.narrative and "wa-goto:c16" in s.narrative


def test_the_character_check_with_a_model_keeps_its_prompt_and_adds_the_scan():
    from src.ai import analysis_prompts
    p = _book()
    llm = FakeLLM("## Mara\nMara stays guarded throughout the chapter, as her record says.")
    s = _check(p, 15, llm)
    assert analysis_prompts.character_prompt(p, p.manuscript.chapters[15],
                                             p.manuscript.chapters[15].content) in llm.prompts
    assert len(llm.prompts) == 1                  # no extra request for the scan
    assert s.narrative.startswith("## Mara") and "Across the book (a scan)" in s.narrative
