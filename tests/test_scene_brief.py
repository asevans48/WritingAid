"""What's going on around the passage — for Rephrase and Suggestions."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import scene_brief as sb
from src.models.project import Chapter, Character, WriterProject
from src.models.worldbuilding_objects import Faction, FactionType

LEAD_UP = ("The bells rang over Greywater as the fog came in. Mara crossed the market and "
           "slipped down the steps to the pier, where Tobin was already untying the skiff. "
           "He would not look at her. ") * 4


@pytest.fixture
def project():
    p = WriterProject(name="Saga")
    p.characters = [Character(id="m", name="Mara", character_type="protagonist"),
                    Character(id="t", name="Tobin", character_type="major"),
                    Character(id="v", name="Voss", character_type="minor")]
    p.worldbuilding.factions = [Faction(id="f", name="Ash Wardens",
                                        faction_type=FactionType.MILITARY)]
    first = Chapter(id="c1", number=1, title="Nets", content="Earlier.")
    first.planning.description = "Mara learns the Wardens took her brother."
    ch = Chapter(id="c2", number=2, title="Night Run", content=LEAD_UP)
    ch.planning.description = "Mara and Tobin slip past the patrol."
    ch.planning.pov_character = "Mara"
    ch.planning.locations = ["Greywater harbor"]
    from src.models.project import StoryEvent
    ch.planning.events = [StoryEvent(id="e1", text="Meet Tobin at the pier", completed=True),
                          StoryEvent(id="e2", text="Get past the patrol boat"),
                          StoryEvent(id="e3", text="Reach the wreck")]
    p.manuscript.chapters = [first, ch]
    return p


def chapter(project):
    return project.manuscript.chapters[1]


def test_brief_from_notes_and_text(project):
    brief = sb.scene_brief(project, chapter(project), LEAD_UP, "Tobin pushed off.")
    assert "Night Run" in brief and "slip past the patrol" in brief
    assert "point of view: Mara" in brief and "present: " in brief and "Tobin" in brief
    assert "Voss" not in brief
    assert "location: Greywater harbor" in brief
    assert "Already happened: Meet Tobin at the pier." in brief
    assert "Building toward: Get past the patrol boat." in brief
    assert "Previously — Mara learns the Wardens took her brother." in brief


def test_brief_without_chapter_notes_for_suggestions(project):
    brief = sb.scene_brief(project, chapter(project), LEAD_UP, "x", chapter_notes=False)
    assert "Night Run" not in brief and "Previously" not in brief
    assert "Building toward" in brief and "present:" in brief


def test_brief_is_empty_without_anything_to_say():
    assert sb.scene_brief(None, None, "", "") == ""


class FakeLLM:
    def __init__(self, reply="Mara meets Tobin at the pier in fog; he won't look at her. "
                             "Tension hangs over whether he trusts her. Extra sentence. Fourth."):
        self.reply, self.calls = reply, 0

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.calls += 1
        self.prompt = prompt
        return self.reply


def test_moment_summary_is_short_cached_and_refreshable(project):
    sb._CACHE.clear()
    llm = FakeLLM()
    first = sb.moment_summary(llm, chapter(project), LEAD_UP, ["Mara", "Tobin"])
    assert first.startswith("Mara meets Tobin") and "Fourth" not in first
    assert "TEXT LEADING UP TO THE PASSAGE" in llm.prompt and "Mara, Tobin" in llm.prompt
    assert sb.moment_summary(llm, chapter(project), LEAD_UP) == first and llm.calls == 1
    assert sb.cached_moment(chapter(project), LEAD_UP) == first
    sb.moment_summary(llm, chapter(project), LEAD_UP, refresh=True)
    assert llm.calls == 2


def test_summary_regenerated_only_when_the_lead_up_changes(project):
    sb._CACHE.clear()
    llm = FakeLLM()
    sb.moment_summary(llm, chapter(project), LEAD_UP)
    sb.moment_summary(llm, chapter(project), LEAD_UP)        # same scene, any passage
    sb.moment_summary(llm, chapter(project), LEAD_UP + " Then the lamp went out.")
    assert llm.calls == 2


def test_no_summary_for_a_short_lead_up_or_without_a_model(project):
    assert sb.moment_summary(FakeLLM(), chapter(project), "Too short.") == ""
    assert sb.moment_summary(None, chapter(project), LEAD_UP) == ""


def test_meta_tokens_and_labels_cleaned(project):
    sb._CACHE.clear()
    llm = FakeLLM("<|channel>thought\nplan<channel|>Summary: Mara waits on the pier.")
    assert sb.moment_summary(llm, chapter(project), LEAD_UP) == "Mara waits on the pier."


def test_compose_keeps_the_instruction_first():
    text = sb.compose("Mara waits.", "Scene — present: Mara.", "Fix the passive voice: x")
    assert text.splitlines() == ["Fix the passive voice: x", "What's happening: Mara waits.",
                                 "Scene — present: Mara."]


# ── Rephrase dialog ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog_factory(app, project, monkeypatch):
    from src.ai.rephrasing_agent import RephrasingAgent
    from src.ui import rephrase_dialog as rd
    llm = FakeLLM("Mara meets Tobin at the pier; he won't look at her.")

    def fake_agent(self):
        self.agent = RephrasingAgent(project=self.project)

    monkeypatch.setattr(rd.RephraseDialog, "_init_agent", fake_agent)
    monkeypatch.setattr(rd.RephraseDialog, "_moment_llm", lambda self: llm)

    def make(**kw):
        sb._CACHE.clear()
        dlg = rd.RephraseDialog("Tobin pushed off.", project, None,
                                surrounding_context=(LEAD_UP[-500:], ""),
                                chapter_content=LEAD_UP + "Tobin pushed off.",
                                chapter=chapter(project), text_before=LEAD_UP, **kw)
        if dlg._moment_worker is not None:
            dlg._moment_worker.wait(5000)
        app.processEvents()
        return dlg

    make.llm = llm
    return make


def test_dialog_fills_the_scene_box(dialog_factory):
    dlg = dialog_factory()
    text = dlg.scene_desc_edit.text()
    assert text.startswith("What's happening: Mara meets Tobin at the pier")
    assert "Building toward: Get past the patrol boat." in text
    assert "edit if anything's off" in dlg.scene_status_label.text()


def test_dialog_keeps_the_writers_edits(dialog_factory, app):
    dlg = dialog_factory()
    dlg.scene_desc_edit.setText("My own scene notes.")
    dlg._on_moment("A newer summary.")
    assert dlg.scene_desc_edit.text() == "My own scene notes."
    assert "Refresh to put it in" in dlg.scene_status_label.text()


def test_dialog_instruction_from_a_style_issue_stays_on_top(dialog_factory):
    dlg = dialog_factory(instruction="Fix the passive voice: “was taken”")
    assert dlg.scene_desc_edit.text().splitlines()[0] == "Fix the passive voice: “was taken”"


def test_refresh_calls_the_model_again(dialog_factory, app):
    dlg = dialog_factory()
    calls = dialog_factory.llm.calls
    dlg._start_moment_summary(refresh=True)
    dlg._moment_worker.wait(5000)
    app.processEvents()
    assert dialog_factory.llm.calls == calls + 1


def test_scene_box_reaches_the_rephrase_prompt(dialog_factory, monkeypatch):
    dlg = dialog_factory()
    seen = {}

    class Worker:
        def __init__(self, *a, **kw):
            seen.update(kw)
            self.finished = self.error = self

        def connect(self, *_):
            pass

        def start(self):
            pass

    from src.ui import rephrase_dialog as rd
    monkeypatch.setattr(rd, "RephraseWorker", Worker)
    dlg._generate_options()
    assert "What's happening: Mara meets Tobin" in seen["scene_description"]


# ── Suggestions ───────────────────────────────────────────────────

def test_suggestions_get_where_we_are(project):
    from src.ai import passage_critique as pc
    text = LEAD_UP + "Tobin pushed off."
    ctx = pc.build_context(project, chapter(project), text, len(LEAD_UP), len(text))
    prompt = pc.build_prompt(ctx)
    assert "WHERE WE ARE IN THE SCENE" in prompt and "Building toward: Get past the patrol" in prompt
