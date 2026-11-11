"""Rules aimed at Gemma's habits: stock phrases, near-twin suggestions,
voice as ranges, no invented facts, dialogue speakers."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import passage_critique as pc
from src.ai import rewrite_quality as rq
from src.ai.dialogue_speakers import attribute_lines, speaker_notes

ORIGINAL = "Mara crouched behind the crates and watched the patrol boat pass the pier."
BEFORE = "The harbor was quiet. Tobin waited in the skiff with the oars across his knees."


def check(candidate, **kw):
    return rq.check_rewrite(ORIGINAL, candidate, known_names=["Mara", "Tobin"],
                            before=BEFORE, **kw)


# ── 1. Stock phrases ──────────────────────────────────────────────

@pytest.mark.parametrize("text,label", [
    ("Under a bruised sky she waited.", "bruised (sky / light)"),
    ("Her heart hammering, she waited.", "heart hammering"),
    ("She let out a breath she didn't know she was holding.", "breath she didn't know"),
    ("The fog clung to the pier.", "fog / mist clung"),
    ("The weight of the night pressed down.", "the weight of …"),
])
def test_stock_phrases_found(text, label):
    assert any(f.startswith(label.split(" (")[0][:12]) for f in rq.stock_phrases_in(text)), \
        rq.stock_phrases_in(text)


def test_one_stock_phrase_is_a_note_two_is_replaced():
    one = check("Mara crouched behind the crates, heart hammering, as the patrol boat passed.")
    assert one.ok and any("stock phrase" in n for n in one.minor)
    two = check("Under a bruised sky Mara crouched, heart hammering, as the patrol boat passed.")
    assert not two.ok and any("stock phrasing" in p for p in two.serious)


def test_stock_phrase_already_in_the_scene_is_the_authors_own():
    c = rq.check_rewrite("The fog clung to the pier and Mara waited by the crates.",
                         "The fog clung to the pier while Mara waited behind the crates.")
    assert not any("stock" in n for n in c.notes)


def test_writers_own_avoided_phrase_always_triggers_a_retry():
    c = check("Mara crouched in the gloaming behind the crates as the patrol boat passed.",
              avoid=["gloaming"])
    assert not c.ok and "gloaming" in c.serious[0]


def test_avoid_list_is_saved_to_settings(monkeypatch):
    saved = {}

    class Cfg:
        def get(self, key, default=None):
            return saved.get(key, default)

        def set(self, key, value):
            saved[key] = value

    import src.config.creativeos_config as cc
    monkeypatch.setattr(cc, "get_creativeos_config", lambda: Cfg())
    assert rq.add_avoid_phrase("  the  gloaming ") is True
    assert rq.add_avoid_phrase("The Gloaming") is False
    assert saved["avoid_phrases"] == ["the gloaming"]


def test_avoid_prompt_lists_stock_and_personal_phrases():
    line = rq.avoid_prompt(["gloaming"])
    assert "heart hammering" in line and "gloaming" in line


# ── 2. Different suggestions ──────────────────────────────────────

def test_twins_are_judged_on_narration_and_openings_are_only_noted():
    texts = ["Mara dropped flat as the shot split the night across the water.",
             "A shot cracked over the harbor. Mara fell flat behind the crates.",
             "Mara dropped flat as the shot split the night over the water.",
             "A shot cracked. She rolled under the tarp and lay still, listening."]
    twins = rq.twin_problems(texts)
    assert twins == {2: "is nearly the same as suggestion 1"}
    assert rq.same_openings(texts) == {2: "opens the same way as suggestion 1",
                                       3: "opens the same way as suggestion 2"}


def test_shared_dialogue_does_not_make_twins():
    line = '"Please, Mara, tell me you brought the papers," he whispered. "Of course," she said.'
    texts = [f"Tobin leaned on the oars and rowed hard. {line}",
             f"The skiff lurched with every desperate stroke. {line}"]
    assert rq.twin_problems(texts) == {}


def reply(*rewrites):
    return ("WHAT WORKS:\n- ok\n\n" + "\n\n".join(
        f"SUGGESTION {i}:\n{r}\nWHY: w" for i, r in enumerate(rewrites, 1)))


class FakeLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else ""


def test_twin_suggestion_is_replaced_with_a_different_angle():
    text = BEFORE + " " + ORIGINAL
    ctx = pc.build_context(None, None, text, len(BEFORE) + 1, len(text))
    llm = FakeLLM(reply("Mara crouched behind the crates while the patrol boat slid past.",
                        "Mara crouched behind the crates as the patrol boat went by.",
                        "Behind the crates, Mara held still until the patrol boat passed."),
                  reply("The patrol boat passed the pier; Mara stayed low behind the crates."))
    r = pc.critique_passage(llm, ctx)
    texts = [s.text for s in r.suggestions]
    assert "Mara crouched behind the crates as the patrol boat went by." not in texts
    assert "The patrol boat passed the pier; Mara stayed low behind the crates." in texts
    assert "REWRITES ALREADY KEPT" in llm.prompts[-1]
    assert "SUGGESTION 2 (restructured)" in llm.prompts[0]
    assert "(new focus)" in llm.prompts[-1] or "(restructured)" in llm.prompts[-1]


# ── 3. Voice as ranges ────────────────────────────────────────────

def test_voice_is_given_as_a_range_not_a_target():
    from src.ai.writer_voice import analyze_writer_voice
    v = analyze_writer_voice("She ran. The dock was cold and empty that night. Nobody spoke. "
                             "Rain fell on the boats in the harbor. She waited. " * 10)
    low, high = v.sentence_range()
    assert low < v.avg_sentence_len < high
    assert f"usually {low}–{high} words" in v.to_prompt()
    assert "not limits" in v.to_prompt() and "Variety is part of the voice" in v.to_prompt()
    assert "never fault a sentence just for being longer" in v.to_critique_prompt()


def test_critique_prompt_says_length_alone_is_no_fault():
    ctx = pc.build_context(None, None, ORIGINAL, 0, len(ORIGINAL))
    assert "don't fault a sentence only for its length" in pc.build_prompt(ctx)


# ── 4. No invented facts ──────────────────────────────────────────

def test_invented_weapon_is_serious():
    c = check("Mara crouched behind the crates, gripping her knife, as the patrol boat passed.")
    assert not c.ok and "“knife”" in c.serious[0]


def test_fact_from_the_notes_or_scene_is_fine():
    assert check("Mara crouched behind the crates, gripping her knife, as the patrol passed.",
                 notes="Mara Venn always carries her father's knife.").ok
    c = rq.check_rewrite("He raised the rifle and fired at the boat.",
                         "He lifted the rifle and fired at the boat.")
    assert c.ok


def test_figurative_words_are_not_facts():
    assert check("In the dead calm, Mara crouched behind the crates while the patrol passed.").ok


# ── 5. Who is speaking ────────────────────────────────────────────

NAMES = ["Mara Venn", "Tobin"]


def labels(text):
    return [(l.speaker, l.certainty, l.addressed) for l in attribute_lines(text, NAMES)]


def test_tags_beats_and_addressees():
    text = ('"Go," Tobin said.\n'
            '"Not yet," said Mara. "The bells."\n'
            'Tobin pushed off. "Now, Mara."\n'
            'Mara asked, "Why?"')
    assert labels(text) == [("Tobin", "tag", ""), ("Mara Venn", "tag", ""),
                            ("Mara Venn", "tag", ""), ("Tobin", "beat", "Mara Venn"),
                            ("Mara Venn", "tag", "")]


def test_pronoun_tag_is_only_probable():
    text = 'Mara looked at the water.\n"We wait," she said.'
    assert labels(text) == [("Mara Venn", "likely", "")]
    assert "probably Mara Venn" in speaker_notes(text, NAMES)


def test_name_in_the_quote_is_not_the_speaker():
    lines = attribute_lines('Tobin was waiting. "Please, Mara, we need to go," said Mara.', NAMES)
    assert "check the tag" in lines[0].label()


def test_speakers_in_the_critique_prompt():
    text = 'Tobin pushed off. "Now, Mara," he whispered. Mara didn\'t move.'
    ctx = pc.build_context(type("P", (), {"characters": [
        type("C", (), {"name": n, "id": n, "character_type": "major"})() for n in NAMES],
        "story_planning": None, "worldbuilding": None})(), None, text, 0, len(text))
    prompt = pc.build_prompt(ctx)
    assert "WHO SPEAKS EACH LINE" in prompt and "“Now, Mara,” — Tobin (speaking to Mara Venn)" in prompt


def test_short_sentence_sharing_a_place_is_not_retelling():
    earlier = ("Mara crouched behind the crates on the pier and held her breath. "
               "Tobin was already in the skiff, oars across his knees.")
    assert rq.restated_sentences("Tobin pushed the skiff from the pier.", earlier) == []


def test_fog_swallowing_anything_is_stock():
    assert "swallowed by / swallowed them" in rq.stock_phrases_in("The fog swallowed the pier.")
    assert rq.stock_phrases_in("He swallowed hard and nodded.") == []
