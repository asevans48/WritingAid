"""P.4: proofreading with a model: corrections only, and only small ones."""

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import proofread
from src.ai import readiness as rd
from src.data import readiness_state as rs
from src.models.project import Chapter, Character, Manuscript, WriterProject
from src.utils import proof_store

KNOWN = {"there", "their", "coats", "were", "wet", "ain't", "gonna", "the", "he", "went",
         "to", "town", "then", "than", "more", "walked", "home", "slowly"}
is_known = lambda w: w in KNOWN


def test_narrow_keeps_only_the_words_that_differ():
    assert proofread.narrow("hung there coats up", "hung their coats up") == (5, 10, "their")
    assert proofread.narrow("more then he", "more than he") == (5, 9, "than")
    # A doubled word: the pair is flagged, one word suggested.
    assert proofread.narrow("to the the town", "to the town") == (3, 10, "the")
    # A missing word is anchored on its neighbour.
    assert proofread.narrow("went the town", "went to the town") == (0, 4, "went to")
    # Not corrections: a rewrite, and a change of quote style only.
    assert proofread.narrow("He walked home slowly that night", "Slowly he made his way") is None
    assert proofread.narrow("“Stop,” he said", '"Stop," he said') is None


def test_parse_keeps_small_real_corrections_and_drops_the_rest():
    paras = ["They hung there coats by the door, more then a little wet.",
             "“I ain't gonna go their,” said Dorcas. “Its a long way to to town.”",
             "Dorcas walked home."]
    reply = ('"hung there coats" -> "hung their coats" | wrong word\n'
             '"more then a" -> "more than a" | then/than\n'
             '"I ain\'t gonna" -> "I am not going to" | grammar\n'           # dialect in speech
             '"gonna go their" -> "gonna go there" | wrong word\n'           # speech: left alone
             '"way to to town" -> "way to town" | doubled word\n'            # doubled: kept
             '"Dorcas walked" -> "Dorothy walked" | name\n'                   # a project name
             '"the moon rose" -> "the moon rises" | not in the text\n'
             '"by the door, more" -> "beside the entrance, far more" | style\n')
    found = proofread.parse(reply, paras, is_known, {"dorcas"})
    assert [(c["t"], c["r"]) for c in found[0]] == [("there", "their"), ("then", "than")]
    assert [(c["t"], c["r"]) for c in found[1]] == [("to to", "to")]
    assert 2 not in found


class FakeLLM:
    model = "proofer"

    def __init__(self, fail=False):
        self.prompts, self.fail = [], fail

    def generate_text(self, prompt, system="", **kw):
        self.prompts.append(prompt)
        if prompt.startswith("Proofread the text below"):
            if self.fail:
                return "Error generating text: the server went away"
            out = []
            if "hung there coats" in prompt:
                out.append('"hung there coats" -> "hung their coats" | wrong word')
            if "allways" in prompt:                    # a rule already flags this one
                out.append('"was allways late" -> "was always late" | misspelling')
            return "\n".join(out) or "NONE"
        if "Outline this chapter" in prompt:                     # the chapter digest
            return "SCENE | She | they wait | she decides to go | NONE\nREADER | 3 | fine | NONE"
        if prompt.startswith("OUTLINE OF THE BOOK"):
            return "NONE"
        if "Look for three kinds of problem" in prompt:
            return "NONE"
        n = len(re.findall(r"^\d+\. \[", prompt, re.M))
        return "\n".join(f"{i + 1}. REAL — weak" for i in range(n))


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))


TEXT = ("They hung there coats by the door. He was allways late.\n\n"
        "The rain fell on the harbor all morning.\n")


def _project(tmp_path):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    ch = Chapter(id="c1", number=1, title="Chapter 1", folder_root=p.manuscript.folder_root)
    ch.content = TEXT
    p.manuscript.chapters.append(ch)
    return p


def test_without_a_model_nothing_changes(tmp_path):
    p = _project(tmp_path)
    r = rd.chapter_report(p, p.manuscript.chapters[0]).results["spelling_grammar"]
    assert [i.text for i in r.items] == ["allways"]
    assert "proof" not in rs.load(p)


def test_the_model_finds_what_the_rules_miss_and_it_shows_as_a_grammar_flag(tmp_path):
    p = _project(tmp_path)
    llm = FakeLLM()
    report = rd.chapter_report(p, p.manuscript.chapters[0], llm=llm)
    r = report.results["spelling_grammar"]
    assert sorted(i.text for i in r.items) == ["allways", "there"]     # the rule's flag once
    found = next(i for i in r.items if i.text == "there")
    assert found.suggestions == ["their"] and "found by the model" in found.reason
    assert TEXT[found.start:found.end] == "there" and r.count == 2
    # Remembered by paragraph: nothing is sent again, and it is saved.
    assert len([x for x in llm.prompts if x.startswith("Proofread")]) == 1
    assert proofread.requests_needed(TEXT) == 0
    assert rs.load(p)["proof"]["model"] == "proofer"
    # The editor's grammar check shows it, naming the model.
    from src.utils import editor_flags as ef
    flags = ef.state_for_project(p).flags_for_text(TEXT)
    mine = [e for _, e in flags if getattr(e, "rule_id", "") == proof_store.RULE_ID]
    assert len(mine) == 1 and mine[0].word == "there" and mine[0].suggestions == ["their"]
    assert "found by proofer" in mine[0].reason
    # A new session reads them back from the project's file.
    proof_store.clear()
    assert not proof_store.has(TEXT.split("\n")[0])
    proof_store.load(p)
    assert proof_store.corrections(TEXT.split("\n")[0])[0]["r"] == "their"


def test_a_changed_paragraph_is_read_again_and_the_rest_is_not(tmp_path):
    p = _project(tmp_path)
    rd.chapter_report(p, p.manuscript.chapters[0], llm=FakeLLM())
    p.manuscript.chapters[0].content = TEXT + "\nA new paragraph about the gulls.\n"
    llm = FakeLLM()
    rd.chapter_report(p, p.manuscript.chapters[0], llm=llm)
    sent = [x for x in llm.prompts if x.startswith("Proofread")]
    assert len(sent) == 1 and "gulls" in sent[0] and "hung there coats" not in sent[0]


def test_a_failed_proofread_is_tried_again(tmp_path):
    p = _project(tmp_path)
    ch = p.manuscript.chapters[0]
    report = rd.chapter_report(p, ch, llm=FakeLLM(fail=True))
    assert not report.judged
    assert [i.text for i in report.results["spelling_grammar"].items] == ["allways"]
    report = rd.chapter_report(p, ch, llm=FakeLLM())
    assert report.judged and report.results["spelling_grammar"].count == 2


def test_small_models_get_smaller_pieces():
    text = "\n".join(f"Paragraph {i} " + "word " * 120 for i in range(10))
    assert proofread.requests_needed(text) == 2
    assert proofread.requests_needed(text, compact=True) == 5
