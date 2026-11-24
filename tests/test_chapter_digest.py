"""The chapter digest (reverse outline) and the editor's checks built on it."""

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import chapter_digest as cd
from src.ai import readiness as rd
from src.data import readiness_state as rs
from src.models.project import Chapter, Character, Manuscript, WriterProject

ONE = ("Mara found the brass key under the loose stair and hid it in her coat. Tobias "
       "wondered whether she had seen him watching. She said nothing at supper.\n\n"
       "#\n\nThe next day they walked to the market and bought bread. The weather was mild.\n")
TWO = "Mara opened the cellar door with the brass key. Inside lay her father's ledgers.\n"
THREE = "The harvest came in. Everyone was tired. Nothing more was said about the cellar.\n"

DIGEST_ONE = (
    'SCENE | Mara | Mara finds a key and hides it | she now has a secret from Tobias | '
    '"Mara found the brass key"\n'
    'SCENE | Mara | they buy bread at the market | NONE | "The next day they walked"\n'
    'SCENE | Mara | invented | NONE | "The dragon rose over the hills"\n'
    'SLIP | "Tobias wondered whether she had seen him watching" | we were in Mara\'s head, '
    'and jump into Tobias\'s\n'
    'SETUP | the brass key will open something | "hid it in her coat"\n'
    'SETUP | a storm is coming | "The sky turned black as pitch"\n'            # not in the text
    'CHANGE | Mara | she is keeping a secret\n'
    'READER | 2 | the market scene lets the tension go | "The weather was mild"\n')


class FakeLLM:
    model = "outliner"

    def __init__(self, unpaid="NONE"):
        self.prompts, self.unpaid = [], unpaid

    def generate_text(self, prompt, system="", **kw):
        self.prompts.append(prompt)
        if "Outline this chapter" in prompt:
            if "CHAPTER (Chapter 1)" in prompt:
                return DIGEST_ONE
            if "CHAPTER (Chapter 2)" in prompt:
                return ('SCENE | Mara | Mara opens the cellar | she learns what her father hid '
                        '| "Mara opened the cellar door"\n'
                        'PAYOFF | the brass key opens the cellar | "with the brass key"\n'
                        'SETUP | the ledgers hold a secret | "her father\'s ledgers"\n'
                        'READER | 4 | a door opens on a secret | NONE\n')
            return 'SCENE | Mara | the harvest | NONE | "The harvest came in"\nREADER | 3 | ok | NONE'
        if prompt.startswith("OUTLINE OF THE BOOK"):
            return self.unpaid
        if prompt.startswith("Proofread") or "Look for three kinds of problem" in prompt:
            return "NONE"
        n = len(re.findall(r"^\d+\. \[", prompt, re.M))
        return "\n".join(f"{i + 1}. REAL — weak" for i in range(n))


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))


def _project(tmp_path, texts=(ONE, TWO, THREE)):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    for i, t in enumerate(texts):
        ch = Chapter(id=f"c{i + 1}", number=i + 1, title=f"Chapter {i + 1}",
                     folder_root=p.manuscript.folder_root)
        ch.content = t
        p.manuscript.chapters.append(ch)
    return p


def test_parse_keeps_what_it_can_point_to():
    d = cd.parse(DIGEST_ONE, ONE)
    assert [(s["pov"], bool(s["purpose"]), s["start"] >= 0) for s in d["scenes"]] == [
        ("Mara", True, True), ("Mara", False, True), ("Mara", False, False)]
    assert [s["quote"] for s in d["slips"]] == ["Tobias wondered whether she had seen him watching"]
    assert [s["what"] for s in d["setups"]] == ["the brass key will open something"]
    assert d["changes"] == [{"who": "Mara", "how": "she is keeping a secret"}]
    assert d["reader"]["pull"] == 2 and d["reader"]["quote"] == "The weather was mild"


def test_the_chapter_checks_read_the_digest_as_questions(tmp_path):
    p = _project(tmp_path)
    assert rd.chapter_report(p, p.manuscript.chapters[0]).results["scene_purpose"].status \
        == rd.Status.NEEDS_MODEL
    llm = FakeLLM()
    r = rd.chapter_report(p, p.manuscript.chapters[0], llm=llm).results
    purpose = r["scene_purpose"]
    assert purpose.count == 2 and purpose.items[0].text == "The next day they walked"
    assert purpose.items[0].reason.endswith("What should be different after it?")
    assert r["pov_slips"].count == 1 and "Is that intended?" in r["pov_slips"].items[0].reason
    pull = r["reader_pull"]
    assert pull.measure == 2 and pull.status == rd.Status.PROBLEM   # an early chapter weighs more
    assert pull.items[0].text == "The weather was mild"
    # One request for the three checks, stored, and not made again.
    assert len([x for x in llm.prompts if "Outline this chapter" in x]) == 1
    assert rs.load(p)["digest"]["main"]["c1"]["model"] == "outliner"
    llm2 = FakeLLM()
    rd.chapter_report(p, p.manuscript.chapters[0], llm=llm2, use_cache=False)
    assert not [x for x in llm2.prompts if "Outline this chapter" in x]


def test_setups_never_paid_off_across_the_book(tmp_path):
    p = _project(tmp_path)
    assert "loose_threads" in rd.book_report(p).book_results          # needs the outline
    llm = FakeLLM(unpaid="2 | what the ledgers show is never told\n9 | not a real number")
    report = rd.book_report(p, llm=llm)
    threads = report.book_results["loose_threads"]
    assert threads.count == 1
    item = threads.items[0]
    assert item.chapter_id == "c2" and item.text == "her father's ledgers"
    assert item.reason.startswith("Set up in “Chapter 2”: the ledgers hold a secret.")
    assert item.reason.endswith("Is it paid off, or left open on purpose?")
    asked = next(x for x in llm.prompts if x.startswith("OUTLINE OF THE BOOK"))
    assert "1. [Chapter 1] the brass key will open something" in asked
    assert "[Mara] Mara opens the cellar → she learns what her father hid" in asked
    assert "(changes nothing)" in asked and "payoff: the brass key opens the cellar" in asked
    assert rd.model_work(p) == (0, 3)


def test_a_character_who_drops_out_is_asked_about(tmp_path):
    texts = ["Mara and Tobias mended nets. Tobias laughed. Tobias sang. Tobias slept.\n",
             "Tobias rowed out with Mara. Tobias fished. Tobias swore. Tobias rowed home.\n"] + \
            [f"Mara worked alone on day {n}. Mara was tired.\n" for n in range(6)]
    p = _project(tmp_path, texts)
    p.characters.append(Character(id="t", name="Tobias", character_type="major"))
    p.characters.append(Character(id="m", name="Mara", character_type="major"))
    r = rd.book_report(p).book_results["character_threads"]
    assert [i.text for i in r.items] == ["Tobias"]
    assert "last seen in “Chapter 2” (2 of 8). Is their thread closed?" in r.items[0].reason
    # A short book isn't judged this way.
    assert "character_threads" not in rd.book_report(_project(tmp_path)).book_results
