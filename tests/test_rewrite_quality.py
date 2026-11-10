"""Voice, quality checks and learned examples for Suggestions, Rephrase and Critique."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import passage_critique as pc
from src.ai import rewrite_quality as rq
from src.data.rephrase_database import RephraseDatabase
from src.models.project import Chapter, Character, WriterProject

NAMES = ["Mara Venn", "Tobin", "Greywater"]
ORIGINAL = "Mara walked down to the pier and looked out at the grey water for a while."
BEFORE = "The bells rang over Greywater. She had waited all day for the boat."


def check(candidate, **kw):
    return rq.check_rewrite(ORIGINAL, candidate, known_names=NAMES, before=BEFORE, **kw)


def test_a_good_rewrite_passes():
    c = check("Mara went down to the pier and watched the grey water for a long time.")
    assert c.ok and not c.notes


def test_possessive_and_sentence_start_words_are_fine():
    assert check("Mara's boots rang on the pier. Fog hid the grey water from her.").ok


@pytest.mark.parametrize("candidate,problem", [
    ("Marra walked down to the pier and stared at the grey water for a while.", "your notes have “Mara”"),
    ("Mara walked to the pier where Kelvaro waited by the grey water for a while.", "introduces “Kelvaro”"),
    ("I walked down to the pier and I looked out at my grey water for a while.", "first person"),
    ("Mara walks down to the pier. She looks at the water. She is tired and she sees it.",
     "present tense"),
    ("Mara walked.", "much shorter"),
    ("The bells rang over Greywater. She had waited all day for the boat. Mara watched.",
     "repeats text from before"),
])
def test_serious_problems(candidate, problem):
    c = check(candidate)
    assert not c.ok and any(problem in p for p in c.serious), c.serious


def test_length_change_allowed_when_asked():
    assert check("Mara watched the water.", focus="make it shorter").ok


def test_new_cliche_is_a_minor_note():
    c = check("Mara walked to the pier, and at the end of the day the grey water looked back.")
    assert c.ok and any("cliché" in n for n in c.minor), c.minor


def test_voice_fit_ranks_and_flags():
    from src.ai.writer_voice import analyze_writer_voice
    prose = ("She ran. The dock was cold. Nobody spoke. Rain fell on the boats. "
             "She waited by the rope. The tide turned. ") * 10
    voice = analyze_writer_voice(prose)
    rambling = ("Mara, who had for many long and complicated years wondered about the meaning of "
                "the sea and its many moods and secrets, walked slowly and thoughtfully and "
                "extremely carefully down to the old pier beside the grey water.")
    plain = "Mara walked to the pier. She looked at the grey water. She waited there a while."
    assert check(rambling, voice=voice).voice_fit < check(plain, voice=voice).voice_fit

    class FarVoice:
        person = tense = ""

        def fit_score(self, _text):
            return 0.4

    c = check(plain, voice=FarVoice())
    assert c.ok and any("weak match for your voice (40%)" in n for n in c.minor)


def test_person_and_tense_detection():
    assert rq.person_and_tense("I ran. I looked at my hands.") == ("first", "past")
    assert rq.person_and_tense("He runs. He looks at his hands. She is there.")[1] == "present"
    assert rq.person_and_tense("\"I am here,\" he said. He looked away.")[0] == "third"


def test_diff_marks_changes():
    out = rq.diff_html("the cold sea", "the bitter sea")
    assert "line-through'>cold" in out and ">bitter</span>" in out and "sea" in out


# ── Learned examples ──────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    d = RephraseDatabase(tmp_path / "r.db")
    d.log("The ship came in.", "The ship limped home.", source_type="rephrase",
          rating="excellent", accepted=True, project_path="/p/a.json")
    d.log("The ship came in slow.", "The vessel arrived slowly.", source_type="rephrase",
          rating="bad", accepted=False, project_path="/p/a.json")
    d.log("Other book text.", "Other choice.", source_type="rephrase",
          rating="good", accepted=True, project_path="/p/other.json")
    d.log("Chat prompt", "Chat answer", source_type="chat_general", rating="excellent")
    return d


def test_examples_prefer_this_project_and_include_rejections(db):
    block = rq.examples_prompt("The ship came in at dawn.", "/p/a.json", chosen=1, db=db)
    assert "They chose: \"The ship limped home.\"" in block
    assert "They rejected: \"The vessel arrived slowly.\"" in block
    assert "Other choice" not in block and "Chat answer" not in block


def test_no_examples_without_ratings(tmp_path):
    assert rq.examples_prompt("x", db=RephraseDatabase(tmp_path / "empty.db")) == ""


def test_logging_respects_the_collection_switch(monkeypatch):
    import src.data.rephrase_database as rd
    monkeypatch.setattr(rd, "is_collection_enabled", lambda: False)
    assert rq.log_rated_rewrite("a b", "c d", "good", accepted=True) is False
    monkeypatch.setattr(rd, "is_collection_enabled", lambda: True)
    assert rq.log_rated_rewrite("a b", "c d", "good", accepted=True) is True
    assert rd.get_rephrase_database().rated_examples()["chosen"][0]["output_text"] == "c d"


# ── Suggestions ───────────────────────────────────────────────────

TEXT = ("Mara Venn reached the pier at dusk. The bells were ringing. "
        "Mara looked at the water and thought about her brother. Tobin waited.")


@pytest.fixture
def project():
    p = WriterProject(name="Saga")
    p.project_path = "/p/a.json"
    p.characters = [Character(id="c1", name="Mara Venn", character_type="protagonist"),
                    Character(id="c2", name="Tobin", character_type="major")]
    ch1 = Chapter(id="c-1", number=1, title="Arrival", content="Before.")
    ch1.planning.description = "Mara learns her brother was taken."
    ch2 = Chapter(id="c-2", number=2, title="Pier", content=TEXT)
    p.manuscript.chapters = [ch1, ch2]
    return p


def passage_ctx(project, **kw):
    s = TEXT.index("Mara looked")
    e = TEXT.index("Tobin waited")
    return pc.build_context(project, project.manuscript.chapters[1], TEXT, s, e - 1, **kw)


def test_context_carries_voice_examples_and_earlier_chapters(project):
    from src.ai.writer_voice import WriterVoice
    voice = WriterVoice(stated_targets={"Tone": "spare, cold"})
    ctx = passage_ctx(project, voice=voice, examples="REWRITES THIS AUTHOR RATED: x")
    prompt = pc.build_prompt(ctx)
    assert "spare, cold" in prompt and "REWRITES THIS AUTHOR RATED" in prompt
    assert "Mara learns her brother was taken" in ctx.earlier
    assert "Tobin" in ctx.known_names


class FakeLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else ""


def reply(*rewrites):
    return ("WHAT WORKS:\n- Clear.\n\nWHAT DOESN'T WORK:\n- Flat.\n\n"
            + "\n\n".join(f"SUGGESTION {i}:\n{r}\nWHY: w{i}" for i, r in enumerate(rewrites, 1)))


def test_failing_suggestion_is_replaced_quietly(project):
    good = "Mara stared at the water and thought of her brother out there."
    bad = "Marra stared at the water and thought about her brother again."
    llm = FakeLLM(reply(good, bad, "Mara watched the dark water and thought of her brother."),
                  "SUGGESTION 1:\nMara studied the water, her brother on her mind.\nWHY: fix")
    r = pc.critique_passage(llm, passage_ctx(project))
    texts = [s.text for s in r.suggestions]
    assert bad not in texts and "Mara studied the water, her brother on her mind." in texts
    assert "your notes have" in llm.prompts[-1] or "Mara" in llm.prompts[-1]


def test_unfixable_suggestion_is_kept_last_with_a_warning(project):
    bad = "Marra stared at the water and thought about her brother again."
    llm = FakeLLM(reply("Mara stared at the water and thought of her brother out there.",
                        bad, "Mara watched the dark water and thought of her brother."),
                  "SUGGESTION 1:\nMarra again stared at the water and thought.\nWHY: x")
    r = pc.critique_passage(llm, passage_ctx(project))
    assert r.suggestions[-1].text == bad and r.suggestions[-1].notes


# ── Dialog ratings + changes ──────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_rates_shows_changes_and_logs_use(app, project, monkeypatch):
    import src.data.rephrase_database as rd
    from src.ui.passage_critique_dialog import PassageCritiqueDialog, SuggestionWorker
    monkeypatch.setattr(rd, "is_collection_enabled", lambda: True)
    llm = FakeLLM(reply("Mara stared at the water and thought of her brother out there.",
                        "Mara watched the dark water and thought of her brother.",
                        "Mara eyed the water, thinking of her brother."))

    class Now(SuggestionWorker):
        def __init__(self, *a):
            super().__init__(*a, llm_factory=lambda: (llm, ""), search_factory=lambda p: None)

        def start(self):
            self.run()

    s, e = TEXT.index("Mara looked"), TEXT.index("Tobin waited") - 1
    dlg = PassageCritiqueDialog(TEXT, s, e, project, project.manuscript.chapters[1],
                                worker_factory=Now)
    assert dlg.suggestion_list.count() == 3
    assert "line-through" in dlg.changes_view.toHtml()
    dlg.suggestion_list.setCurrentRow(1)
    dlg.rate_buttons["bad"].click()
    assert dlg.rating_status.text() == "Saved."
    dlg.suggestion_list.setCurrentRow(0)
    dlg._use_selected()
    rows = rd.get_rephrase_database().rated_examples(project_path="/p/a.json")
    assert [r["rating"] for r in rows["rejected"]] == ["bad"]
    assert rows["chosen"][0]["output_text"] == dlg.replacement


# ── Rephrase ──────────────────────────────────────────────────────

def _resp(*texts):
    return "\n\n".join(f"OPTION {i}:\n{t}\nEXPLANATION: e" for i, t in enumerate(texts, 1))


def test_rephrase_replaces_option_that_switches_person(project):
    from src.ai.rephrasing_agent import RephraseStyle, RephrasingAgent

    class LLM:
        def __init__(self):
            self.prompts = []
            self.out = [_resp("I walked down to the pier and I looked at my grey water a while."),
                        _resp("Mara went to the pier and watched the grey water for a while.")]

        def generate_text(self, prompt, *a, **k):
            self.prompts.append(prompt)
            return self.out.pop(0)

    llm = LLM()
    agent = RephrasingAgent(llm_client=llm, project=project)
    result = agent.rephrase(ORIGINAL, styles=[RephraseStyle.CONCISE],
                            surrounding_before=BEFORE, examples_note="REWRITES THIS AUTHOR RATED: x")
    assert "REWRITES THIS AUTHOR RATED" in llm.prompts[0]
    assert "REJECTED" in llm.prompts[1]
    assert result.options[0].text.startswith("Mara went")


# ── Critique ──────────────────────────────────────────────────────

def test_critique_reports_see_the_measured_voice(project):
    from src.ai.chapter_analysis_agent import CritiqueOrchestrator, ReportType
    from src.ai.writer_voice import analyze_writer_voice
    orch = CritiqueOrchestrator(project=project)
    orch.writer_voice = analyze_writer_voice("She ran. The dock was cold. Nobody spoke. " * 10)
    analyzer = orch._build_analyzer(ReportType.PACING, "Pier")
    block = analyzer._format_context_block("", "", None, "Pier", 1)
    assert "AUTHOR'S MEASURED VOICE" in block and "deliberate style" in block


def test_project_voice_tops_up_from_other_chapters(project):
    from src.ai.writer_voice import manuscript_sample
    project.manuscript.chapters[0].content = "Other chapter words. " * 50
    sample = manuscript_sample(project, project.manuscript.chapters[1], TEXT, min_words=100)
    assert TEXT in sample and "Other chapter words" in sample
