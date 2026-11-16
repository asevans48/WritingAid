"""Style, grammar and spelling flags: a model decides which are worth
showing; without one, quick rules trim the obvious false alarms."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import flag_judge as fj


@pytest.fixture(autouse=True)
def fresh_cache():
    fj._CACHE.clear()
    yield
    fj._CACHE.clear()


# ── Quick rules ───────────────────────────────────────────────────

def test_style_flags_inside_dialogue_are_the_characters_voice():
    para = '"I really, truly hate this," she said slowly.'
    assert fj.quick_style_ok("intensifier", para, para.index("really"), para.index("really") + 6)
    assert not fj.quick_style_ok("adverb", para, para.index("slowly"), para.index("slowly") + 6)
    assert not fj.quick_style_ok("cliche", para, 1, 5)


def test_grammar_fragment_in_dialogue_is_fine_but_real_errors_are_not():
    para = '"Gone. All of it," she said.'
    assert fj.quick_grammar_ok("This sentence is a fragment.", para, 1, 6)
    assert not fj.quick_grammar_ok("“Their” is possessive", para, 1, 6)
    assert not fj.quick_grammar_ok("This sentence is a fragment.", "Gone. All of it.", 0, 5)


def test_repeated_invented_word_is_intended_but_a_repeated_typo_is_not():
    from src.ui.enhanced_text_editor import SpellChecker
    sc = SpellChecker()
    text = "The vethari sang. Every vethari knew it. A vethari never lies."
    assert fj.quick_word_intended("vethari", text, sc)
    assert not fj.quick_word_intended("vethari", "The vethari sang.", sc)
    typos = "I recieve it. You recieve it. They recieve it."
    assert not fj.quick_word_intended("recieve", typos, sc)


# ── The judge ─────────────────────────────────────────────────────

ITEMS = [{"key": "a", "text": "was opened", "detail": "Passive voice", "sentence": "The door was opened by Mara."},
         {"key": "b", "text": "slowly", "detail": "Adverb", "sentence": "He walked slowly."}]


def test_prompt_and_lenient_parse():
    prompt = fj.build_prompt("style", ITEMS)
    assert "1. “was opened” — Passive voice: «The door was opened by Mara.»" in prompt
    assert "KEEP" in prompt and "DROP" in prompt
    got = fj.parse("style", "**1. DROP** — keeps focus on the door\n2. KEEP: weak verb", ITEMS)
    assert got == {"a": (False, "keeps focus on the door"), "b": (True, "weak verb")}


def test_spelling_answers_typo_or_intended():
    items = [{"key": "x", "text": "vethari", "sentences": ["The vethari sang."]},
             {"key": "y", "text": "recieve", "sentences": ["I recieve it."]}]
    prompt = fj.build_prompt("spelling", items, "Names and terms in this story: Mara.")
    assert "TYPO" in prompt and "INTENDED" in prompt and "Mara" in prompt
    got = fj.parse("spelling", "1. INTENDED — a creature of this world\n2. TYPO — receive", items)
    assert got["x"][0] is False and got["y"][0] is True


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.calls += 1
        return self.reply


def test_judge_caches_verdicts_and_dropped_reads_them():
    llm = FakeLLM("1. DROP — fine\n2. KEEP — weak")
    items = [dict(ITEMS[0], key=fj.key("style", "was opened", ITEMS[0]["sentence"], "passive")),
             dict(ITEMS[1], key=fj.key("style", "slowly", ITEMS[1]["sentence"], "adverb"))]
    fj.judge(llm, "style", items)
    fj.judge(llm, "style", items)
    assert llm.calls == 1
    assert fj.dropped("style", "was opened", "The door was opened by Mara.", "passive")
    assert not fj.dropped("style", "slowly", "He walked slowly.", "adverb")
    assert not fj.dropped("style", "was opened", "A different sentence.", "passive")


def test_spelling_verdict_applies_everywhere():
    fj.remember({fj.key("spelling", "Vethari"): (False, "invented")})
    assert fj.dropped("spelling", "vethari") and fj.dropped("spelling", "VETHARI")


# ── In the editor ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


TEXT = ("The door was opened by Mara. He walked slowly to the boat.\n"
        "A glimmerwhale surfaced. Tobin recieved the letter.")


def editor(app):
    from src.ui.enhanced_text_editor import CheckMode, EnhancedTextEditor
    ed = EnhancedTextEditor()
    ed.writing_highlighter.set_style_mode(CheckMode.REALTIME)
    ed.setPlainText(TEXT)
    ed.do_initial_check()
    return ed


def flags(ed):
    from src.ui.enhanced_text_editor import ErrorType
    out = set()
    for errs in ed.writing_highlighter._errors.values():
        for e in errs:
            if e.error_type in (ErrorType.STYLE, ErrorType.SPELLING):
                out.add(e.word)
    return out


def run_review(ed, app):
    ed._start_flag_review()
    if ed._flag_worker is not None:
        ed._flag_worker.wait(5000)
    app.processEvents()


def test_collect_finds_unjudged_flags(app):
    ed = editor(app)
    items = fj.collect(ed.writing_highlighter, ed.document(), 0)
    assert {i["text"] for i in items["style"]} >= {"was opened", "slowly"}
    spelling = {i["text"] for i in items["spelling"]}
    # Only capitalised words (possible names) go to the model; a lowercase
    # misspelling is always marked, so there's nothing to ask.
    assert "Tobin" in spelling and not {"glimmerwhale", "recieved"} & spelling


def test_model_hides_false_alarms_and_keeps_real_ones(app, monkeypatch):
    import src.ai.word_suggest as ws

    class Judge:
        def generate_text(self, prompt, system_prompt=None, **kw):
            lines = [l for l in prompt.splitlines() if l[:1].isdigit() and "“" in l]
            answers = []
            for n, line in enumerate(lines, 1):
                word = line.split("“")[1].split("”")[0]
                verdict = {"was opened": "DROP", "slowly": "KEEP", "glimmerwhale": "INTENDED",
                           "Tobin": "INTENDED", "recieved": "TYPO"}.get(word, "KEEP")
                answers.append(f"{n}. {verdict} — reason")
            return "\n".join(answers)

    monkeypatch.setattr(ws, "get_llm", lambda: Judge())
    monkeypatch.setattr(fj, "enabled", lambda: True)
    ed = editor(app)
    assert {"was opened", "slowly", "glimmerwhale", "recieved", "Tobin"} <= flags(ed)
    run_review(ed, app)
    shown = flags(ed)
    assert "was opened" not in shown and "Tobin" not in shown   # a name
    assert {"slowly", "recieved", "glimmerwhale"} <= shown           # lowercase: always marked


def test_without_a_model_everything_stays(app):
    ed = editor(app)
    run_review(ed, app)
    assert ed._no_repetition_judge and {"was opened", "slowly", "glimmerwhale"} <= flags(ed)


def test_style_panel_follows_the_verdicts(app):
    from src.ai.word_suggest import sentence_around
    ed = editor(app)
    para = TEXT.split("\n")[0]
    sentence = sentence_around(para, 0, 10).text
    fj.remember({fj.key("style", "was opened", sentence, "passive"): (False, "fine")})
    kinds = [i.text for i in ed.writing_highlighter.style_issues_for(para)]
    assert "was opened" not in kinds and "slowly" in kinds
