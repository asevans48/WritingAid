"""Character and Worldbuilding critique reports."""

from types import SimpleNamespace as NS

from src.ai.canon_index import collect_world_entities, find_unknown_proper_nouns
from src.ai.chapter_analysis_agent import (
    CritiqueOrchestrator, ReportType, resolve_genre_profile,
)
from src.models.project import (
    Character, Chapter, ChapterPlanning, Manuscript, PersonalitySnapshot, WorldBuilding,
)
from src.models.worldbuilding_objects import Faction, FactionType, Place, PlaceType

CHAPTER = """Mara walked the length of the pier at Greywater. The boards were wet. She didn't look back.

"You're late," Tobin said, not looking up from the nets. "Tide won't wait for anyone."

The Ash Wardens had held Greywater for a century, and their banners still hung from the harbor wall.

Mara laughed and told Tobin she wasn't afraid of the water. She dove off the pier into the black sea without a second thought.

Past the Saltmarket, a lamplighter was hanging lanterns. Kessa said nothing as they passed. The Saltmarket smelled of brine.
"""


def _project():
    mara = Character(
        id="c1", name="Mara", character_type="protagonist",
        personality="guarded, wry", fears="deep water since her brother drowned",
        speaking_style="short, dry sentences", want="to leave Greywater",
        personality_arc=[
            PersonalitySnapshot(chapter_number=1, emotional_state="numb"),
            PersonalitySnapshot(chapter_number=4, emotional_state="ready to face the sea"),
        ])
    tobin = Character(id="c2", name="Tobin", character_type="minor",
                      speaking_style="clipped, nautical")
    wb = WorldBuilding(
        factions=[Faction(id="f1", name="Ash Wardens", faction_type=FactionType.MILITARY,
                          description="Order that seized Greywater ten years ago.")],
        places=[Place(id="p1", name="Greywater", place_type=PlaceType.CITY,
                      description="A drowned port city.", controlling_faction="Ash Wardens")],
    )
    ch = Chapter(id="ch2", number=2, title="Chapter 2", content=CHAPTER,
                 planning=ChapterPlanning(characters_featured=["c1", "c2", "Eli"],
                                          locations=["Greywater", "The Lighthouse"]))
    return NS(characters=[mara, tobin], worldbuilding=wb,
              manuscript=Manuscript(chapters=[ch]), story_planning=None)


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def generate_text(self, prompt, system, max_tokens=900, temperature=0.5):
        self.prompts.append(prompt)
        return self.reply


def _run(rt, llm=None):
    orch = CritiqueOrchestrator(primary_llm=llm, project=_project())
    report = orch.run(
        chapters=[{"title": "Chapter 2", "text": CHAPTER, "index": 1}],
        report_types=[rt], genre_key_or_text="default", manuscript_context="")
    return report.chapters[0].sections[0]


def test_world_entities_and_unknown_names():
    names = {e.name for e in collect_world_entities(_project().worldbuilding)}
    assert {"Ash Wardens", "Greywater"} <= names
    unknown = [n for n, _, _ in find_unknown_proper_nouns(
        CHAPTER, list(names) + ["Mara", "Tobin"])]
    assert "Saltmarket" in unknown and "Kessa" in unknown
    assert "Greywater" not in unknown and "Mara" not in unknown


def test_character_report_dashboard():
    s = _run(ReportType.CHARACTER)
    assert s.metrics["characters_appearing"] == 2
    assert any("Mara" in x and "Tobin" in x for x in s.strengths)
    assert any("Eli" in x for x in s.major_issues)          # planned, absent
    assert any("Tobin" in x for x in s.minor_issues)        # thin profile
    assert any(x.startswith("Kessa") for x in s.extra_lists["Speakers with no character record"])


def test_character_report_llm_profiles_and_tags():
    reply = ("## Mara\nShe dives in fearlessly.\n\n=== TAGGED SUMMARY ===\n"
             "- [ON TRACK] Mara — dry humor matches her speaking style\n"
             "- [DRIFT] Mara — Fears: dives into deep water with no hesitation\n"
             "- [RECOMMEND] Mara — show her hesitate at the pier edge\n"
             "- [PROFILE UPDATE] Kessa — new character: silent watcher at the Saltmarket\n")
    llm = FakeLLM(reply)
    s = _run(ReportType.CHARACTER, llm)
    p = llm.prompts[0]
    assert "Fears: deep water since her brother drowned" in p
    assert "Arc checkpoint (ch. 1)" in p and "Next planned checkpoint (ch. 4)" in p
    assert "Tide won't wait for anyone." in p   # Tobin's real line
    assert "TAGGED SUMMARY" not in s.narrative
    assert any("Fears" in x for x in s.major_issues)
    assert s.suggestions == ["Mara — show her hesitate at the pier edge"]
    assert s.extra_lists["Profile updates to consider"]


def test_worldbuilding_report_dashboard():
    s = _run(ReportType.WORLDBUILDING)
    assert s.metrics["elements_referenced"] == 2
    new = s.extra_lists["New elements (not in worldbuilding)"]
    assert any(x.startswith("Saltmarket") for x in new)
    assert not any(x.startswith("Kessa") for x in new)      # speaker → character report
    assert any("The Lighthouse" in x for x in s.major_issues)


def test_worldbuilding_report_llm_tags():
    reply = ("## New elements\n...\n=== TAGGED SUMMARY ===\n"
             "- [NEW] Saltmarket | Place | Brine-smelling market district of Greywater\n"
             "- [ON TRACK] Greywater — still under Ash Warden control\n"
             "- [DIFFERS] Ash Wardens — page: held for a century; record: seized ten years ago\n"
             "- [RECOMMEND] Add the Saltmarket as a Place\n")
    llm = FakeLLM(reply)
    s = _run(ReportType.WORLDBUILDING, llm)
    p = llm.prompts[0]
    assert "Order that seized Greywater ten years ago." in p
    assert "Saltmarket" in p
    assert s.extra_lists["New elements (not in worldbuilding)"] == [
        "Saltmarket — Place — Brine-smelling market district of Greywater"]
    assert any("century" in x for x in s.major_issues)
    assert "TAGGED SUMMARY" not in s.narrative


# --- Local / small-model behaviour ------------------------------------

from src.ai.canon_index import parse_tagged_lines
from src.ai.chapter_analysis_agent import is_local_llm


class LocalLLM:
    """Gemma-ish: answers each focused prompt, with sloppy formatting."""
    compact_prompts = True

    def __init__(self):
        self.prompts = []
        self.kwargs = []

    def generate_text(self, prompt, system, max_tokens=900, temperature=0.5, **kw):
        self.prompts.append(prompt)
        self.kwargs.append({"max_tokens": max_tokens, "temperature": temperature, **kw})
        if "CHARACTER RECORD" in prompt and "MARA APPEARS" in prompt:
            return ("PORTRAYAL: Mara is wry but reckless here.\n"
                    "1. **On Track:** Speaking style — \"She didn't look back.\"\n"
                    "2. **[Drift]** Fears — dives into the black sea without a second thought\n"
                    "[VOICE] fits\n[ARC] Ahead of the numb checkpoint\n"
                    "- Recommendation: make her hesitate at the pier edge")
        if "CHARACTER RECORD" in prompt:
            return "PORTRAYAL: Tobin grumbles.\n[ON TRACK] Speaking style — clipped\n[DRIFT] none"
        if "no character record" in prompt:
            return "[NEW CHARACTER] Kessa — silent watcher at the Saltmarket; needs a record: yes"
        if "For each world element" in prompt:
            return ("[ON TRACK] Greywater — still a harbor under the Wardens\n"
                    "[DIFFERS] Ash Wardens — page: held Greywater for a century; "
                    "record: seized ten years ago; real contradiction")
        if "no worldbuilding record" in prompt:
            return "[NEW] Saltmarket | Place | Brine-smelling market quarter"
        return "Error generating text: out of memory"


def test_is_local_llm_detection():
    assert is_local_llm(NS(provider=NS(value="mlx_local")))
    assert is_local_llm(NS(provider="huggingface_local"))
    assert not is_local_llm(NS(provider=NS(value="claude")))
    assert is_local_llm(NS(compact_prompts=True, provider="claude"))


def test_parser_accepts_small_model_formats():
    tags = parse_tagged_lines("1. **On Track:** a\n**[Drift]** b\n- Recommendation: c\n[DRIFT] none")
    assert tags == {"ON TRACK": ["a"], "DRIFT": ["b"], "RECOMMEND": ["c"]}


def test_character_report_local_focused_calls():
    llm = LocalLLM()
    s = _run(ReportType.CHARACTER, llm)
    char_prompts = [p for p in llm.prompts if "CHARACTER RECORD" in p]
    assert len(char_prompts) == 2                      # one per character
    assert all(len(p.split()) < 900 for p in char_prompts)   # small prompts
    assert "EXAMPLE" in char_prompts[0]
    assert "dove off the pier" in char_prompts[0]      # evidence from the passages
    # Structured answers: low temperature, no auto-continuation (it makes
    # small models repeat the format).
    assert llm.kwargs[0]["temperature"] == 0.3
    assert llm.kwargs[0]["continue_if_truncated"] is False
    assert "Mara — Fears — dives into the black sea without a second thought" in s.major_issues
    assert any(x.startswith("Mara — Speaking style") for x in s.strengths)
    assert s.suggestions == ["Mara — make her hesitate at the pier edge"]
    assert not any("Tobin — none" in x for x in s.major_issues)
    assert s.extra_lists["Arc position"] == ["Mara: Ahead of the numb checkpoint"]
    assert any("Kessa" in x for x in s.extra_lists["Profile updates to consider"])
    assert "## Mara" in s.narrative and "[Drift]" not in s.narrative


def test_worldbuilding_report_local_focused_calls():
    llm = LocalLLM()
    s = _run(ReportType.WORLDBUILDING, llm)
    assert any("ten years ago" in x for x in s.major_issues)
    assert any(x.startswith("Greywater") for x in s.strengths)
    assert s.extra_lists["New elements (not in worldbuilding)"] == [
        "Saltmarket — Place — Brine-smelling market quarter"]
    assert "Add Saltmarket to Worldbuilding (Place)." in s.suggestions
    assert any(x.startswith("Reconcile Ash Wardens") for x in s.suggestions)


def test_local_error_string_is_not_a_narrative():
    llm = LocalLLM()
    s = _run(ReportType.PACING, llm)
    assert "out of memory" not in s.narrative
    assert any("narrative skipped" in f for f in s.findings)


def test_cloud_report_repairs_missing_tags():
    class Forgetful(FakeLLM):
        def generate_text(self, prompt, system, max_tokens=900, temperature=0.5, **kw):
            self.prompts.append(prompt)
            if prompt.startswith("Below is an editor's report"):
                return "- [DRIFT] Mara — Fears: dives in fearlessly\n- [RECOMMEND] Mara — add hesitation"
            return "## Mara\nShe dives in fearlessly, against her fear of water."
    llm = Forgetful("")
    s = _run(ReportType.CHARACTER, llm)
    assert sum(p.startswith("Below is an editor's report") for p in llm.prompts) == 1
    assert any("dives in fearlessly" in x for x in s.major_issues)
    assert s.suggestions == ["Mara — add hesitation"]
    assert "TAGGED SUMMARY" not in s.narrative
