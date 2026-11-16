"""Light repeats (a word 3–5 times, a phrase 2–3 times) are marked only
when they weaken the writing — judged by a model, or by quick rules."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import repetition_judge as rj
from src.ui.enhanced_text_editor import OveruseDetector

def _filler(gap: int, words: int = 70) -> str:
    """Unique made-up words (each used once), so the gap adds no repeats."""
    letters = "bcdfghjklmnprstvz"
    out = []
    for i in range(words):
        n = gap * 1000 + i
        token = ""
        for _ in range(4):
            token += letters[n % len(letters)] + "aeiou"[n % 5]
            n //= len(letters)
        out.append(token)
    return " ".join(out) + "."


FILLER = _filler(99)


def spaced(*sentences):
    """Sentences far apart (70 unique filler words between each)."""
    out = sentences[0]
    for i, s in enumerate(sentences[1:]):
        out += " " + _filler(i) + " " + s
    return out


def detector(text, **kw):
    d = OveruseDetector(**kw)
    d.review_low_counts = True
    d.update_cache(text)
    return d


def flagged(d, word, text):
    return d.is_overused(word, text)[0]


def test_common_word_used_three_times_far_apart_is_fine():
    text = spaced("She opened the door.", "He shut the door.", "The door stayed shut.")
    assert not flagged(detector(text), "door", text)


def test_close_echo_is_flagged():
    text = "She opened the door and the door creaked. " + FILLER + " The door shut."
    d = detector(text)
    assert flagged(d, "door", text)
    assert "within" in d.word_verdict("door", 3)[1]


def test_distinctive_word_is_flagged_even_far_apart():
    text = spaced("A luminous fog.", "Her luminous eyes.", "The luminous sea.")
    d = detector(text)
    assert flagged(d, "luminous", text) and "distinctive" in d.word_verdict("luminous", 3)[1]


def test_heavy_repetition_is_always_flagged():
    text = spaced(*["She opened the door."] * 7)
    assert flagged(detector(text), "door", text)


def test_names_are_never_flagged():
    text = "Mara ran. Mara hid. Mara waited. Mara wept. Mara slept. Mara woke. Mara left."
    d = detector(text)
    d.set_names(["Mara Venn"])
    d.update_cache(text)
    assert not flagged(d, "Mara", text)


def test_phrase_twice_far_apart_is_fine_close_is_flagged():
    far = spaced("She stood at the old gate.", "Rain fell on the old gate.")
    d = detector(far)
    assert "the old gate" not in d._cached_phrase_positions
    near = "She stood at the old gate. Rain fell on the old gate."
    assert "the old gate" in detector(near)._cached_phrase_positions


def test_off_by_default_keeps_the_old_counting():
    text = spaced("She opened the door.", "He shut the door.", "The door stayed shut.")
    assert OveruseDetector().is_overused("door", text)[0]


def test_verdicts_override_the_quick_rules():
    text = spaced("She opened the door.", "He shut the door.", "The door stayed shut.")
    d = detector(text)
    d.apply_verdicts({"w:door": (True, "Three flat door beats in a row.")})
    assert flagged(d, "door", text) and d.verdict_reason("w:door") == "Three flat door beats in a row."
    d.apply_verdicts({"w:door": (False, "Needed.")})
    assert not flagged(d, "door", text) and d.verdict_reason("w:door") == ""


def test_phrase_verdict_brings_back_a_phrase():
    far = spaced("She stood at the old gate.", "Rain fell on the old gate.")
    d = detector(far)
    d.apply_verdicts({"p:the old gate": (True, "A pet image.")})
    assert "the old gate" in d._cached_phrase_positions


def test_review_items_have_sentences_and_suspects_first():
    text = spaced("She opened the door.", "He shut the door.", "The door stayed shut.",
                  "A luminous fog.", "Her luminous eyes.", "The luminous sea.")
    items = detector(text).review_items()
    keys = [i["key"] for i in items]
    assert "w:door" in keys and keys.index("w:luminous") < keys.index("w:door")
    door = next(i for i in items if i["key"] == "w:door")
    assert door["sentences"][0] == "She opened the door." and door["count"] == 3


# ── The judge ─────────────────────────────────────────────────────

ITEMS = [{"key": "w:door", "text": "door", "count": 3, "sentences": ["She opened the door."]},
         {"key": "w:luminous", "text": "luminous", "count": 3, "sentences": ["A luminous fog."]},
         {"key": "p:the old gate", "text": "the old gate", "count": 2,
          "sentences": ["She stood at the old gate."]}]


def test_prompt_lists_each_item_with_its_sentences():
    prompt = rj.build_prompt(ITEMS)
    assert "1. word “door” (3 times): «She opened the door.»" in prompt
    assert "3. phrase “the old gate” (2 times)" in prompt and "LESS POWERFUL" in prompt


def test_parse_is_lenient():
    reply = ("1. OK — needed, nothing better.\n**2. FLAG** — a pet adjective, it loses force.\n"
             "3. “the old gate” — KEEP: a deliberate motif.")
    got = rj.parse(reply, ITEMS)
    assert got["w:door"] == (False, "needed, nothing better.")
    assert got["w:luminous"] == (True, "a pet adjective, it loses force.")
    assert got["p:the old gate"][0] is False


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.calls += 1
        return self.reply


def test_judge_caches_by_the_sentences():
    rj._CACHE.clear()
    llm = FakeLLM("1. OK — fine.\n2. FLAG — pet word.\n3. OK — motif.")
    first = rj.judge(llm, ITEMS)
    assert first["w:luminous"][0] and llm.calls == 1
    assert rj.judge(llm, ITEMS) == first and llm.calls == 1
    changed = [dict(ITEMS[0], sentences=["She kicked the door."])] + ITEMS[1:]
    rj.judge(llm, changed)
    assert llm.calls == 2


# ── In the editor ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def editor(app, text):
    from src.ui.enhanced_text_editor import CheckMode, EnhancedTextEditor
    ed = EnhancedTextEditor()
    ed.writing_highlighter.set_overuse_mode(CheckMode.REALTIME)
    ed.setPlainText(text)
    ed.do_initial_check()
    return ed


def overuse_marks(ed):
    from src.ui.enhanced_text_editor import ErrorType
    return {e.word.lower() for errs in ed.writing_highlighter._errors.values() for e in errs
            if e.error_type == ErrorType.OVERUSE}


TEXT = spaced("She opened the door.", "He shut the door.", "The door stayed shut.",
              "A luminous fog.", "Her luminous eyes.", "The luminous sea.")


def run_review(ed, app):
    ed._start_repetition_review()
    if ed._review_worker is not None:
        ed._review_worker.wait(5000)
    app.processEvents()


def test_model_verdicts_decide_what_is_marked(app, monkeypatch):
    import src.ai.word_suggest as ws
    rj._CACHE.clear()
    monkeypatch.setattr(rj, "enabled", lambda: True)

    class Judge:
        def generate_text(self, prompt, system_prompt=None, **kw):
            lines = []
            for n, line in enumerate(l for l in prompt.splitlines()
                                     if l[:1].isdigit() and "“" in l):
                word = line.split("“")[1].split("”")[0]
                lines.append(f"{n + 1}. {'FLAG — three flat door beats' if word == 'door' else 'OK — deliberate'}")
            return "\n".join(lines)

    monkeypatch.setattr(ws, "get_llm", lambda: Judge())
    ed = editor(app, TEXT)
    assert overuse_marks(ed) == {"luminous"}               # quick rules, before the model
    run_review(ed, app)
    assert overuse_marks(ed) == {"door"}
    error = next(e for errs in ed.writing_highlighter._errors.values() for e in errs
                 if e.word.lower() == "door")
    assert "three flat door beats" in error.reason


def test_without_a_model_the_quick_rules_stay(app):
    rj._CACHE.clear()
    ed = editor(app, TEXT)
    run_review(ed, app)
    assert ed._no_repetition_judge and overuse_marks(ed) == {"luminous"}


def test_review_can_be_switched_off(app, monkeypatch):
    monkeypatch.setattr(rj, "enabled", lambda: False)
    ed = editor(app, TEXT)
    ed._start_repetition_review()
    assert ed._review_worker is None


def test_project_names_are_not_marked(app):
    from types import SimpleNamespace as NS
    text = "Mara ran. Mara hid. Mara waited. Mara wept. Mara slept. Mara woke. Mara left."
    ed = editor(app, text)
    assert "mara" in overuse_marks(ed)
    ed.set_project_vocabulary(NS(characters=[NS(name="Mara Venn")], worldbuilding=None,
                                 dictionary=None))
    assert "mara" not in overuse_marks(ed)


def test_grammar_words_and_article_phrases_are_not_marked():
    text = "He went out and back out, then back into the boat and out of the boat again."
    d = detector(text)
    assert not flagged(d, "out", text) and not flagged(d, "back", text)
    assert not any(p in d._cached_phrase_positions for p in ("out of the", "the boat"))
