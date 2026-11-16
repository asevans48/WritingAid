"""Rewrites must not reverse the order things happen in."""

import pytest

from src.ai import event_order as eo
from src.ai import passage_critique as pc
from src.ai.rewrite_quality import check_rewrite

ORIGINAL = ("Mara went to the bathroom and washed her face. "
            "Then she returned to her room and locked the door.")


def test_events_listed_in_order():
    assert [e.text for e in eo.events(ORIGINAL)] == [
        "Mara went to the bathroom", "washed her face", "Then she returned to her room",
        "locked the door"]


@pytest.mark.parametrize("sentence,first", [
    ("Before returning to her room, Mara went to the bathroom.", "Mara went to the bathroom"),
    ("After she washed her face, Mara returned to her room.", "she washed her face"),
    ("Mara returned to her room after she washed her face.", "she washed her face"),
    ("Mara washed her face before she returned to her room.", "Mara washed her face"),
])
def test_time_words_read_correctly(sentence, first):
    assert eo.events(sentence)[0].text == first


@pytest.mark.parametrize("rewrite", [
    "Mara slipped into the bathroom and splashed water on her face. Back in her room, she "
    "locked the door.",
    "Before returning to her room, Mara went to the bathroom and washed her face. She locked "
    "the door.",
    "Mara returned to her room after she went to the bathroom and washed her face, then "
    "locked the door.",
    "Mara returned to her room and locked the door. She had gone to the bathroom and washed "
    "her face first.",
])
def test_order_kept(rewrite):
    assert eo.order_problems(ORIGINAL, rewrite) == []


@pytest.mark.parametrize("rewrite", [
    "Mara returned to her room and locked the door. She went to the bathroom and washed her face.",
    "Mara locked the door of her room. Then she went to the bathroom and washed her face.",
])
def test_reversals_caught(rewrite):
    problems = eo.order_problems(ORIGINAL, rewrite)
    assert problems and problems[0].startswith("reverses the order of events")


def test_moving_a_description_is_not_a_reversal():
    original = "The room was dark. Mara opened the door and stepped inside."
    assert eo.order_problems(original, "Mara opened the door and stepped inside. The room "
                                       "was dark.") == []


def test_reorder_the_critique_asked_for_is_allowed():
    original = "She flinched and dropped flat. A shot cracked across the water."
    rewrite = "A shot cracked across the water. She flinched and dropped flat."
    assert eo.order_problems(original, rewrite)
    allowed = eo.allowed_swaps(["[2] should come before [1] — cause first."])
    assert eo.order_problems(original, rewrite, allowed) == []


def test_reversal_is_serious_unless_the_writer_asked_for_a_reorder():
    rewrite = ("Mara returned to her room and locked the door. She went to the bathroom and "
               "washed her face.")
    assert not check_rewrite(ORIGINAL, rewrite).ok
    asked = check_rewrite(ORIGINAL, rewrite, focus="swap the order of these")
    assert asked.ok and any("reverses" in n for n in asked.minor)


# ── Suggestions + Rephrase ────────────────────────────────────────

class FakeLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else ""


def test_suggestions_show_the_timeline_and_replace_a_reversal():
    ctx = pc.build_context(None, None, ORIGINAL, 0, len(ORIGINAL))
    prompt = pc.build_prompt(ctx)
    assert "EVENTS IN THE ORDER THEY HAPPEN" in prompt and "1. Mara went to the bathroom" in prompt
    assert "bathroom before they return to their room" in prompt
    reversed_ = ("Mara returned to her room and locked the door. She went to the bathroom and "
                 "washed her face.")
    good = ("Mara slipped into the bathroom and splashed water on her face. Back in her room, "
            "she locked the door.")
    llm = FakeLLM("WHAT WORKS:\n- ok\n\nORDER AND FLOW:\n- In order.\n\n"
                  f"SUGGESTION 1 (tightened):\n{reversed_}\nWHY: a\n\n"
                  f"SUGGESTION 2 (restructured):\n{good}\nWHY: b",
                  "SUGGESTION 1 (new focus):\nMara ducked into the bathroom and washed her face, "
                  "then went back to her room and bolted the door.\nWHY: c",
                  "SUGGESTION 1 (tightened):\nIn the bathroom Mara washed her face. Then she "
                  "returned to her room and locked the door.\nWHY: d")
    r = pc.critique_passage(llm, ctx)
    assert reversed_ not in [s.text for s in r.suggestions]
    assert "EVENTS IN THE ORDER THEY HAPPEN" in llm.prompts[-1]


def test_suggestion_may_apply_the_reorder_its_critique_named():
    text = "She flinched and dropped flat. A shot cracked across the water."
    ctx = pc.build_context(None, None, text, 0, len(text))
    fixed = "A shot cracked across the water. She flinched and dropped flat."
    llm = FakeLLM("ORDER AND FLOW:\n- [1] should come after [2].\n\n"
                  f"SUGGESTION 1 (tightened):\n{fixed}\nWHY: cause first")
    r = pc.critique_passage(llm, ctx)
    assert r.suggestions[0].text == fixed and not r.suggestions[0].notes


def test_rephrase_gets_the_timeline_and_retries_a_reversal():
    from types import SimpleNamespace as NS
    from src.ai.rephrasing_agent import RephraseStyle, RephrasingAgent
    from src.ui.rephrase_dialog import RephraseDialog
    guidance = RephraseDialog._order_guidance(NS(original_text=ORIGINAL))
    assert "1. Mara went to the bathroom" in guidance and "bathroom before" in guidance

    class LLM:
        def __init__(self):
            self.prompts = []
            self.out = ["OPTION 1 (concise):\nMara returned to her room and locked the door. "
                        "She went to the bathroom and washed her face.\nEXPLANATION: e",
                        "OPTION 1 (concise):\nMara washed up in the bathroom, then returned to "
                        "her room and locked the door.\nEXPLANATION: e"]

        def generate_text(self, prompt, *a, **k):
            self.prompts.append(prompt)
            return self.out.pop(0)

    llm = LLM()
    out = RephrasingAgent(llm_client=llm).rephrase(ORIGINAL, styles=[RephraseStyle.CONCISE],
                                                  examples_note=guidance)
    assert len(llm.prompts) == 2 and "reverses the order" in llm.prompts[1]
    assert out.options[0].text.startswith("Mara washed up in the bathroom")
