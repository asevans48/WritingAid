"""1.7: a model judges the readiness checks' candidates."""

import os
import re
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import readiness as rd
from src.ai import readiness_judge as rj
from src.models.project import Chapter, Character, Manuscript, WriterProject

TEXT = ("She walked slowly to the door. He smiled warmly at the dog.\n\n"
        "The rain came in off the river before dawn, and the boats rocked at their ropes.\n")


class FakeLLM:
    """Answers each numbered item from a list of verdicts (cycled)."""
    model = "fake"

    def __init__(self, verdicts=("REAL",), reply=None, story="NONE"):
        self.verdicts, self.reply, self.prompts = list(verdicts), reply, []
        self.story, self.story_prompts = story, []

    def generate_text(self, prompt, system="", **kw):
        if "Look for three kinds of problem" in prompt:        # the story read
            self.story_prompts.append(prompt)
            return self.story if self.reply is None else self.reply
        if "Outline this chapter" in prompt:                     # the chapter digest
            return "SCENE | She | they wait | she decides to go | NONE\nREADER | 3 | fine | NONE"
        if prompt.startswith("OUTLINE OF THE BOOK"):
            return "NONE"
        if prompt.startswith("Proofread the text below"):       # the proofreading pass (P.4)
            self.proof_prompts = getattr(self, "proof_prompts", []) + [prompt]
            return "NONE" if self.reply is None else self.reply
        self.prompts.append(prompt)
        if self.reply is not None:
            return self.reply
        n = len(re.findall(r"^\d+\. \[", prompt, re.M))
        return "\n".join(f"{i + 1}. {self.verdicts[i % len(self.verdicts)]} — because"
                         for i in range(n))


def _project(tmp_path, text=TEXT):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    p.characters.append(Character(id="m", name="Mara", character_type="major"))
    ch = Chapter(id=str(uuid.uuid4()), number=1, title="One", folder_root=p.manuscript.folder_root)
    ch.content = text
    p.manuscript.chapters.append(ch)
    return p


def _report(p, llm=None, **kw):
    return rd.chapter_report(p, p.manuscript.chapters[0], llm=llm, **kw)


def test_model_clears_one_and_confirms_another(tmp_path):
    p = _project(tmp_path)
    scan = _report(p)
    assert scan.results["adverbs"].count == 2 and not scan.judged
    llm = FakeLLM(["REAL", "FINE"])
    judged = _report(p, llm)
    adv = judged.results["adverbs"]
    assert judged.judged and adv.judged
    assert adv.count == 1
    verdicts = sorted(i.verdict for i in adv.items)
    assert verdicts == ["cleared", "problem"]
    assert all(i.note == "because" for i in adv.items)
    assert "cleared 1 of 2" in adv.message
    # Only where the model decided does the report differ from the scan.
    for name, r in judged.results.items():
        if name != "adverbs" and not any(i.verdict for i in r.items):
            assert r.count == scan.results[name].count, name


def test_an_empty_or_failed_reply_keeps_the_scan(tmp_path):
    p = _project(tmp_path)
    for llm in (FakeLLM(reply=""), FakeLLM(reply="Error generating text: timeout")):
        r = _report(p, llm)
        assert r.results["adverbs"].count == 2 and not r.results["adverbs"].judged
    # Not cached as judged: a working model next time judges it.
    assert _report(p, FakeLLM(["FINE", "REAL"])).results["adverbs"].judged


def test_judged_results_are_cached_and_kept_by_the_scan(tmp_path):
    p = _project(tmp_path)
    llm = FakeLLM(["REAL", "FINE"])
    _report(p, llm)
    calls = len(llm.prompts)
    again = _report(p, llm)
    assert len(llm.prompts) == calls                         # unchanged: no new request
    assert _report(p).results["adverbs"].count == 1          # the automatic scan keeps the verdicts
    p.manuscript.chapters[0].content = TEXT + "He ran quickly.\n"
    _report(p, llm)
    assert len(llm.prompts) > calls                          # changed: judged again


def test_one_request_per_stage(tmp_path):
    p = _project(tmp_path, TEXT + "Its a beutiful day. The night was very dark and terribly "
                                  "cold and so very lonely.\n")
    llm = FakeLLM(["REAL"])
    r = _report(p, llm)
    stages = {rd.REGISTRY[n].stage for n, res in r.results.items()
              if res.judged and any(i.verdict for i in res.items)}
    assert len(llm.prompts) == len(stages) >= 2


def test_needs_model_checks_count_once_judged(tmp_path):
    p = _project(tmp_path, TEXT + "The night was very dark and terribly cold and so very "
                                  "lonely and frightening.\n")
    assert _report(p).results["overdescribed"].status == rd.Status.NEEDS_MODEL
    r = _report(p, FakeLLM(["REAL"]), use_cache=False).results["overdescribed"]
    assert r.status in rd.Status.VERDICTS and r.judged


def test_checks_a_model_cant_settle_stay_honest(tmp_path):
    from src.models.project import StoryPromise
    p = _project(tmp_path)
    p.story_planning.promises.append(StoryPromise(id="p", promise_type="plot", title="X"))
    book = rd.book_report(p, llm=FakeLLM(["REAL"]))
    assert book.book_results["promises"].status == rd.Status.NEEDS_MODEL


def test_the_voice_reading_goes_in_the_prompt(tmp_path, monkeypatch):
    from src.ai import voice_profile as vp
    p = _project(tmp_path)
    monkeypatch.setattr(vp, "ai_enabled", lambda: True)
    monkeypatch.setattr(vp, "cached", lambda project, scope=None: {
        "voice": "Wry and close.", "style": "Short.", "habits": ["Adverbs in tags, deliberately"]})
    llm = FakeLLM(["FINE"])
    _report(p, llm)
    assert "Adverbs in tags, deliberately" in llm.prompts[0]


def test_a_model_that_clears_everything_is_not_trusted(tmp_path):
    p = _project(tmp_path, "He walked slowly and softly, quietly, gently, sadly, warmly, "
                           "kindly, firmly and finally home.\n" * 2)
    r = _report(p, FakeLLM(["FINE"])).results["adverbs"]
    assert r.count >= 8 and not r.judged


def test_local_models_get_a_shorter_prompt(tmp_path):
    p = _project(tmp_path, "He walked slowly. " * 60)
    llm = FakeLLM(["REAL"])
    llm.compact_prompts = True
    _report(p, llm)
    sizes = [len(re.findall(r"^\d+\. \[", x, re.M)) for x in llm.prompts]
    assert sizes and max(sizes) == rj.MAX_ITEMS_COMPACT          # capped for a local model


def test_the_book_report_says_it_was_judged(tmp_path):
    p = _project(tmp_path)
    assert rd.book_report(p).tier == "scan"
    assert rd.book_report(p, llm=FakeLLM(["REAL"])).tier == "model"



# ── The story read: character disconnects, plot jumps, continuity ────────

STORY = ("Mara had never learned to swim, and she stayed well back from the water.\n\n"
         "She locked the red door behind her and pocketed the key.\n\n"
         "Mara dived off the quay and swam hard for the far bank. By the time she reached "
         "Paris it was already winter. The blue door stood open, as she had left it.\n")
FOUND = (
    'CHARACTER | "Mara dived off the quay and swam hard" | "Mara had never learned to swim" '
    '| She cannot swim\n'
    'JUMP | TIME | "By the time she reached Paris it was already winter" | No journey or '
    'passing of months is shown\n'
    'JUMP | PLACE | "The blue door stood open" | We are somewhere else\n'
    'CONTINUITY | "The blue door stood open" | "She locked the red door behind her" | The '
    'door was red and locked\n'
    'CONTINUITY | "The moon was a perfect circle of cheese" | "the water" | invented\n'
    'CHARACTER | "pocketed the key" | "she was famously careless" | no such earlier words\n')


def test_story_read_finds_the_three_major_issues_with_quotes(tmp_path):
    p = _project(tmp_path, STORY)
    scan = _report(p)
    for name in ("character_disconnects", "plot_jumps", "continuity"):
        assert scan.results[name].status == rd.Status.NEEDS_MODEL        # no scan stands in
    llm = FakeLLM(story=FOUND)
    r = _report(p, llm)
    assert len(llm.story_prompts) == 1                                   # one read for all three
    ch = r.results["character_disconnects"]
    assert ch.count == 1 and ch.items[0].text.startswith("Mara dived off the quay")
    assert STORY[ch.items[0].start:ch.items[0].end] == ch.items[0].text  # anchored in the text
    # A query that shows both passages and doesn't rule on which is right.
    assert ch.items[0].reason == ("Earlier: “Mara had never learned to swim”. She cannot swim. "
                                  "Which is intended?")
    jumps = r.results["plot_jumps"]
    assert jumps.count == 1 and "A break in time" in jumps.items[0].reason   # place alone: dropped
    cont = r.results["continuity"]
    assert cont.count == 1 and "blue door" in cont.items[0].text         # invented quotes are dropped
    assert "She locked the red door behind her" in cont.items[0].reason
    assert all(r.results[n].judged for n in ("character_disconnects", "plot_jumps", "continuity"))
    assert "CHARACTER RECORDS" in llm.story_prompts[0] and "Mara" in llm.story_prompts[0]


def test_story_read_is_cached_and_kept_by_the_scan(tmp_path):
    p = _project(tmp_path, STORY)
    llm = FakeLLM(story=FOUND)
    _report(p, llm)
    _report(p, llm)
    assert len(llm.story_prompts) == 1
    assert _report(p).results["plot_jumps"].count == 1                   # the scan keeps it


def test_a_failed_story_read_is_could_not_check_and_retried(tmp_path):
    p = _project(tmp_path, STORY)
    bad = _report(p, FakeLLM(story="I enjoyed this chapter."))
    assert bad.results["continuity"].status == rd.Status.COULD_NOT_CHECK and not bad.judged
    good = _report(p, FakeLLM(story="NONE"))
    assert good.results["continuity"].status == rd.Status.READY and good.judged


def test_tiers():
    rd.checks_for()
    tier = lambda n: rd.REGISTRY[n].tier
    assert {tier(n) for n in ("spelling_grammar", "character_disconnects", "plot_jumps",
                              "continuity", "continuity_novellas")} == {"major"}
    assert {tier(n) for n in ("adverbs", "sticky", "passive", "echoes", "cliches",
                              "repetition", "overdescribed")} == {"polish"}
    assert {tier(n) for n in ("pacing", "dialogue_problems", "consistency", "backstory",
                              "subplots")} == {"factor"}
