"""Refinement in the rephrase agent: feedback-led prompt, new RAG
context, and rejection of options that don't change the draft."""

from src.ai.rephrasing_agent import RephrasingAgent, RephraseStyle

DRAFT = "The ship drifted toward the station, its hull scarred by the long voyage."


class FakeLLM:
    model = "fake"

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []
        self.temps = []

    def generate_text(self, prompt, system, max_tokens=800, temperature=0.7):
        self.prompts.append(prompt)
        self.temps.append(temperature)
        return self.responses.pop(0)


def _resp(text):
    return f"OPTION 1 (concise):\n{text}\nEXPLANATION: changed it"


def _refinement():
    return {
        "instructions": ["make it more ominous", "mention the Veyr beacon"],
        "current_draft": DRAFT,
        "previous_options": [DRAFT],
        "new_context": "[PLACE: Veyr Beacon]\nA dead lighthouse that still pulses.",
    }


def test_refinement_prompt_leads_with_feedback_and_new_context():
    llm = FakeLLM([_resp("Past the dead pulse of the Veyr beacon, the scarred ship slid "
                         "toward the station like something already lost.")])
    agent = RephrasingAgent(llm_client=llm)
    result = agent.rephrase("A ship came to the station.", styles=[RephraseStyle.CONCISE],
                            refinement=_refinement())
    prompt = llm.prompts[0]
    assert prompt.startswith("REVISION REQUEST")
    assert prompt.index("mention the Veyr beacon") < prompt.index("DRAFT TO REVISE")
    assert "Veyr Beacon" in prompt and "NEW CONTEXT" in prompt
    assert llm.temps[0] > 0.7
    assert len(llm.prompts) == 1
    assert "Veyr" in result.options[0].text


def test_near_identical_option_is_rejected_and_retried():
    llm = FakeLLM([
        _resp("The ship drifted toward the station, its hull scarred by a long voyage."),
        _resp("Beneath the Veyr beacon's dying pulse, the wounded ship crept in."),
    ])
    agent = RephrasingAgent(llm_client=llm)
    result = agent.rephrase("A ship came to the station.", styles=[RephraseStyle.CONCISE],
                            refinement=_refinement())
    assert len(llm.prompts) == 2
    assert "PREVIOUS ATTEMPT WAS REJECTED" in llm.prompts[1]
    assert [o.text for o in result.options] == [
        "Beneath the Veyr beacon's dying pulse, the wounded ship crept in."]


def test_plain_rephrase_unchanged():
    llm = FakeLLM([_resp("A ship reached the station.")])
    agent = RephrasingAgent(llm_client=llm)
    agent.rephrase("A ship came to the station.", styles=[RephraseStyle.CONCISE])
    assert llm.prompts[0].startswith("Please rephrase")
    assert llm.temps == [0.7]


# --- Writer voice -------------------------------------------------------

from src.ai.writer_voice import analyze_writer_voice, character_dialog_samples

CHAPTER = """Mara walked the length of the pier. The boards were wet. She didn't look back.

The harbor lights burned low — orange, then red, then nothing at all. She counted the boats. Seven. There had been eight that morning.

"You're late," Tobin said, not looking up from the nets. "Tide won't wait for anyone, least of all you."

She dropped her bag on the deck. The wind came off the water hard and cold — the kind of wind that found every gap in a coat. She'd grown up with it. She hated it anyway.

"Where's the Gull?" she asked.

Tobin shrugged. "Gone out before dawn. Didn't say where." He spat over the rail. "Never does, that one."

Mara watched the horizon. Nothing moved out there. The fog sat on the water like something waiting, and she knew, the way she always knew, that the Gull was not coming back.
"""


def test_voice_analysis_measures_author_habits():
    v = analyze_writer_voice(CHAPTER, selection="She counted the boats.",
                             stated_targets={"Voice": "terse, coastal, fatalistic", "Tone": ""})
    assert v.has_measurements
    assert v.person == "third" and v.tense == "past"
    assert v.punctuation_per_100_sentences["em-dashes"] > 0
    assert v.punctuation_per_100_sentences["semicolons"] == 0
    assert v.stated_targets == {"Voice": "terse, coastal, fatalistic"}
    assert all('"' not in e for e in v.exemplars) and v.exemplars
    assert "She counted the boats." not in v.exemplars
    prompt = v.to_prompt()
    assert "AUTHOR'S VOICE" in prompt and "terse, coastal" in prompt
    # Too little text to claim the author "never" uses something.
    assert "Never uses" not in prompt
    long_v = analyze_writer_voice(CHAPTER * 4, selection="She counted the boats.")
    assert "Never uses: semicolons" in long_v.to_prompt()
    v = long_v
    # A rewrite that switches to first person and adds semicolons scores lower.
    good = "She counted the boats. Seven. One was missing — the Gull, again."
    bad = "I counted the vessels in the harbour; there were seven; one had departed."
    assert v.fit_score(good) > v.fit_score(bad)


def test_character_dialog_samples_from_manuscript():
    lines = character_dialog_samples(CHAPTER, "Tobin")
    assert any("Tide won't wait" in l for l in lines)
    assert any("Never does" in l for l in lines)
    assert not any("Where's the Gull" in l for l in lines)  # Mara's line


def test_voice_and_character_in_initial_and_refinement_prompts():
    v = analyze_writer_voice(CHAPTER, selection="She counted the boats.")
    char = ("Name: Mara\nRole: protagonist\nFears: open water at night\n"
            "Lines this character actually says in the manuscript:\n  » \"Where's the Gull?\"")
    llm = FakeLLM([_resp("She counted the boats. Seven. Not eight."),
                   _resp("Seven boats, she counted — and the dark water where the Gull should be.")])
    agent = RephrasingAgent(llm_client=llm)
    first = agent.rephrase("She counted the boats.", styles=[RephraseStyle.CONCISE],
                           character_context=char, writer_voice=v)
    agent.rephrase("She counted the boats.", styles=[RephraseStyle.CONCISE],
                   character_context=char, writer_voice=v,
                   refinement={"instructions": ["more dread"],
                               "current_draft": first.options[0].text,
                               "previous_options": [first.options[0].text]})
    for p in llm.prompts:
        assert "AUTHOR'S VOICE" in p
        assert "Fears: open water at night" in p
        assert "HOW THE VOICES COMBINE" in p
    refine = llm.prompts[1]
    assert refine.index("AUTHOR'S VOICE") < refine.index("DRAFT TO REVISE")
    assert "Voice match" in first.options[0].explanation
