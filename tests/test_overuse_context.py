"""Overused-word suggestions that fit the sentence."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import word_suggest as ws
from src.ui.enhanced_text_editor import OveruseDetector
from src.utils.word_forms import base_of, form_of, inflect, match_form


# ── Word forms ────────────────────────────────────────────────────

@pytest.mark.parametrize("candidate,target,expected", [
    ("glance", "looked", "glanced"), ("glanced", "looking", "glancing"),
    ("stare", "looks", "stares"), ("stride", "walked", "strode"),
    ("show up", "came", "showed up"), ("study", "looked", "studied"),
    ("stop", "walked", "stopped"), ("watch", "looks", "watches"),
    ("Glance", "Looked", "Glanced"), ("ponder", "thinking", "pondering"),
])
def test_match_form(candidate, target, expected):
    assert match_form(candidate, target) == expected


def test_base_and_forms():
    assert base_of("glanced") == "glance" and base_of("strode") == "stride"
    assert base_of("studied") == "study" and base_of("stopping") == "stop"
    assert form_of("walked") == "past" and form_of("walking") == "ing"
    assert inflect("cry", "s") == "cries" and inflect("lie", "ing") == "lying"


# ── Instant, context-fitted list ──────────────────────────────────

def test_synonyms_take_the_words_form_and_skip_whats_nearby():
    d = OveruseDetector(threshold=3)
    text = ("She looked at the sea. He looked away. They looked tired. "
            "She glanced back once. He stared and stared and stared at the boats.")
    out = d.contextual_synonyms("looked", "She looked at the sea. She glanced back once.", text)
    assert "glanced" not in out                 # already in this paragraph
    assert "stared" not in out                  # itself overused (3 times)
    assert all(w.endswith("ed") or " " in w for w in out[:3]), out


def test_words_the_author_already_uses_come_first():
    d = OveruseDetector(threshold=5)
    text = "He walked in. He walked out. He walked on. Later he trudged home and paced."
    out = d.contextual_synonyms("walked", "He walked in.", text)
    assert out[:2] == ["trudged", "paced"] or set(out[:2]) == {"trudged", "paced"}


def test_a_form_without_its_own_list_falls_back_to_the_base():
    d = OveruseDetector()
    out = d.contextual_synonyms("thinking", "", "")
    assert out and all(w.endswith("ing") for w in out[:4]), out


# ── AI suggestions ────────────────────────────────────────────────

PARA = "The storm passed. Mara looked exhausted, her hair plastered to her face. Tobin waited."


def test_sentence_around_the_word():
    start = PARA.index("looked")
    s = ws.sentence_around(PARA, start, start + 6)
    assert s.text == "Mara looked exhausted, her hair plastered to her face."
    assert s.previous == "The storm passed."


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls, self.prompt = reply, 0, ""

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.calls += 1
        self.prompt = prompt
        return self.reply


def test_prompt_is_small_and_specific():
    start = PARA.index("looked")
    prompt = ws.build_prompt("looked", ws.sentence_around(PARA, start, start + 6), 12)
    assert "Sentence: Mara looked exhausted" in prompt and "appears 12 times" in prompt
    assert "Tobin waited" not in prompt and len(prompt) < 900


def test_parse_keeps_fitting_words_and_rewrites_that_avoid_the_word():
    reply = ("WORDS: seemed; appeared; looks; **was**; glanced at; a very long phrase "
             "that goes on\nREWRITE: Exhaustion hung on Mara, her hair plastered to her face.\n"
             "REWRITE: Mara looked done in.\nREWRITE: Tired.")
    r = ws.parse(reply, "looked", "Mara looked exhausted, her hair plastered to her face.")
    assert r.words == ["seemed", "appeared", "was", "glanced at"]
    assert r.rewrites == ["Exhaustion hung on Mara, her hair plastered to her face."]


def test_suggest_is_cached_per_sentence():
    ws._CACHE.clear()
    llm = FakeLLM("WORDS: seemed; appeared\nREWRITE: Mara sagged, her hair plastered to her face.")
    start = PARA.index("looked")
    sentence = ws.sentence_around(PARA, start, start + 6)
    first = ws.suggest(llm, "looked", sentence)
    assert ws.suggest(llm, "looked", sentence) is first and llm.calls == 1
    assert ws.cached("Looked", sentence.text) is first


# ── Editor menu ───────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def overused_editor(app, text):
    from src.ui.enhanced_text_editor import CheckMode, EnhancedTextEditor
    ed = EnhancedTextEditor()
    ed.resize(700, 300)
    ed.show()
    ed.setPlainText(text)
    ed.writing_highlighter.set_overuse_mode(CheckMode.REALTIME)
    ed.overuse_detector.update_cache(text)
    ed.writing_highlighter.update_full_text(text)
    ed.writing_highlighter.rehighlight()
    return ed


TEXT = ("Mara looked exhausted. She looked at Tobin. Tobin looked away. "
        "The sea looked grey.")


def test_menu_shows_ai_words_and_rewrites_and_replaces(app, monkeypatch):
    from src.ui.enhanced_text_editor import ErrorType
    ws._CACHE.clear()
    ed = overused_editor(app, TEXT)
    block = ed.document().begin()
    error = ed.writing_highlighter.get_error_at(0, TEXT.index("looked") + 1)
    assert error.error_type == ErrorType.OVERUSE
    sentence = ws.sentence_around(block.text(), error.start, error.end)
    ws._CACHE[("looked", sentence.text)] = ws.WordSuggestions(
        ["seemed", "looked"], ["Exhaustion hung on Mara."])
    shown = {}
    monkeypatch.setattr("PyQt6.QtWidgets.QMenu.popup",
                        lambda self, *a: shown.setdefault("labels", [x.text() for x in self.actions()]))
    ed.suggest_in_context(block, error)
    labels = shown["labels"]
    assert "Instead of “looked”:" in labels and "  seemed" in labels
    assert "  looked" not in labels             # still overused — filtered
    assert "  Exhaustion hung on Mara." in labels
    next(a for a in ed._context_menu.actions() if a.text() == "  Exhaustion hung on Mara.").trigger()
    assert ed.toPlainText().startswith("Exhaustion hung on Mara. She looked at Tobin.")


def test_menu_offers_suggest_in_context_for_overused_words(app, monkeypatch):
    ed = overused_editor(app, TEXT)
    labels = []
    monkeypatch.setattr("PyQt6.QtWidgets.QMenu.exec",
                        lambda self, *a: labels.extend(x.text() for x in self.actions()))
    rect = ed.cursorRect(ed._cursor_at(TEXT.index("looked") + 2))
    ed._show_context_menu(rect.center())
    assert "✨ Suggest in context…" in labels


def test_changed_paragraph_is_not_overwritten(app, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    ws._CACHE.clear()
    ed = overused_editor(app, TEXT)
    block = ed.document().begin()
    error = ed.writing_highlighter.get_error_at(0, TEXT.index("looked") + 1)
    sentence = ws.sentence_around(block.text(), error.start, error.end)
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: messages.append(a[2]))
    old_text = block.text()
    ed.setPlainText("Completely different.")
    ed._show_context_suggestions(ed.document().begin(), old_text, 0, error, sentence,
                                 ws.WordSuggestions(["seemed"], []))
    assert messages and "changed" in messages[0]


# ── Set phrases and senses (e.g. "mobile home park") ──────────────

def test_set_phrase_found_with_its_own_synonyms():
    p = "They lived in a mobile home park outside town."
    c = ws.compound_around(p, p.index("home"), p.index("home") + 4)
    assert (c.phrase, c.synonyms) == ("mobile home", ["manufactured home"])
    assert p[c.start:c.end] == "mobile home"
    p2 = "He hit a home run."
    assert ws.compound_around(p2, p2.index("home"), p2.index("home") + 4).synonyms == ["homer"]


def test_words_split_by_punctuation_are_not_a_phrase():
    p = "She left the mobile, home at last."
    assert ws.compound_around(p, p.index("home"), p.index("home") + 4) is None


@pytest.mark.parametrize("sentence,word,expected", [
    ("She went home after dark.", "home", []),                       # adverb: no swap
    ("The house stood empty.", "house", []),                         # never "firm"
])
def test_no_wrong_sense_suggestions(sentence, word, expected):
    d = OveruseDetector()
    assert d.contextual_synonyms(word, sentence, sentence,
                                 position=sentence.index(word)) == expected


def test_noun_keeps_noun_forms():
    d = OveruseDetector()
    p = "Their home was quiet."
    out = d.contextual_synonyms("home", p, p, position=p.index("home"))
    assert "dwelling" in out and "dwell" not in out and "plate" not in out


def test_menu_replaces_the_whole_set_phrase(app, monkeypatch):
    from src.ui.enhanced_text_editor import ErrorType
    text = "A mobile home park. Their home was small. My home, my rules. Home again."
    ed = overused_editor(app, text)
    error = ed.writing_highlighter.get_error_at(0, text.index("home") + 1)
    assert error.error_type == ErrorType.OVERUSE
    assert error.suggestions == ["manufactured home"] and "mobile home" in error.reason
    labels = {}
    monkeypatch.setattr("PyQt6.QtWidgets.QMenu.exec", lambda self, *a: labels.setdefault(
        "menu", self))
    rect = ed.cursorRect(ed._cursor_at(text.index("home") + 2))
    ed._show_context_menu(rect.center())
    next(a for a in labels["menu"].actions() if a.text().strip() == "manufactured home").trigger()
    assert ed.toPlainText().startswith("A manufactured home park.")


def test_suggest_in_context_asks_about_the_whole_phrase(app, monkeypatch):
    ws._CACHE.clear()
    text = "A mobile home park. Their home was small. My home, my rules. Home again."
    ed = overused_editor(app, text)
    block = ed.document().begin()
    error = ed.writing_highlighter.get_error_at(0, text.index("home") + 1)
    seen = {}

    class Worker:
        def __init__(self, word, sentence, count):
            seen.update(word=word, sentence=sentence.text)
            self.done = self.finished = self

        def connect(self, *_):
            pass

        def start(self):
            pass

    import src.ui.enhanced_text_editor as ete
    monkeypatch.setattr(ete, "_ContextSuggestWorker", Worker)
    ed.suggest_in_context(block, error)
    assert seen == {"word": "mobile home", "sentence": "A mobile home park."}
    assert "set phrase" in ws.build_prompt("home", ws.sentence_around(text, 9, 13))


def test_suggestion_covering_the_next_word_is_trimmed():
    r = ws.parse("WORDS: trailer park; manufactured home; park",
                 "mobile home", "They lived in a mobile home park outside town.")
    assert r.words == ["trailer", "manufactured home"]


# ── Repeated phrases ──────────────────────────────────────────────

@pytest.mark.parametrize("phrase,part,options", [
    ("for a moment", "for a moment", ["", "briefly"]),
    ("She nodded her head", "nodded her head", ["nodded"]),
    ("turned around and", "turned around", ["turned"]),
    ("All of a sudden the", "All of a sudden", ["Suddenly", ""]),
    ("in order to", "in order to", ["to"]),                       # from the Style checker
    ("stood up slowly", "stood up", ["stood", "rose"]),
])
def test_phrase_standard_fixes(phrase, part, options):
    start, end, got = OveruseDetector().phrase_alternatives(phrase)
    assert phrase[start:end] == part and got == options


def test_phrase_without_a_standard_fix_offers_nothing():
    assert OveruseDetector().phrase_alternatives("the end of the pier") is None


PHRASE_TEXT = ("She nodded her head and left. Later he nodded her head away. "
               "Then she nodded her head again. The end of the pier was dark. "
               "The end of the pier was cold. The end of the pier was gone.")


def phrase_error(ed, text, at):
    """The repeated phrase under a right-click on ``at``."""
    return ed.writing_highlighter.phrase_error_at(0, text.index(at) + 1)


def test_menu_fixes_the_part_with_a_standard_fix(app, monkeypatch):
    ed = overused_editor(app, PHRASE_TEXT)
    error = phrase_error(ed, PHRASE_TEXT, "head and left")
    assert error.suggestions == ["nodded"]
    block = ed.document().begin()
    assert block.text()[slice(*error.replace_span)] == "nodded her head"


def test_suggest_in_context_for_a_phrase_counts_the_phrase(app, monkeypatch):
    ws._CACHE.clear()
    ed = overused_editor(app, PHRASE_TEXT)
    error = phrase_error(ed, PHRASE_TEXT, "pier was dark")
    seen = {}

    class Worker:
        def __init__(self, word, sentence, count):
            seen.update(word=word, sentence=sentence.text, count=count)
            self.done = self.finished = self

        def connect(self, *_):
            pass

        def start(self):
            pass

    import src.ui.enhanced_text_editor as ete
    monkeypatch.setattr(ete, "_ContextSuggestWorker", Worker)
    ed.suggest_in_context(ed.document().begin(), error)
    assert seen["count"] == 3 and seen["word"] in error.word
    assert seen["sentence"] == "The end of the pier was dark."


def test_phrase_under_an_overused_word_gets_its_own_submenu(app, monkeypatch):
    ed = overused_editor(app, PHRASE_TEXT)
    menus = []
    monkeypatch.setattr("PyQt6.QtWidgets.QMenu.exec", lambda self, *a: menus.append(self))
    rect = ed.cursorRect(ed._cursor_at(PHRASE_TEXT.index("head and left") + 2))
    ed._show_context_menu(rect.center())
    top = [a.text() for a in menus[0].actions()]
    assert any(t.startswith("Repeated phrase: “") for t in top), top
    sub = next(a.menu() for a in menus[0].actions() if a.text().startswith("Repeated phrase"))
    labels = [a.text() for a in sub.actions()]
    assert "  nodded" in labels and "✨ Suggest in context…" in labels
    next(a for a in sub.actions() if a.text() == "  nodded").trigger()
    assert ed.toPlainText().startswith("She nodded and left.")


def test_misspelled_suggestions_are_dropped():
    r = ws.parse("WORDS: Briefly; Stillly; Momentarily", "For a moment",
                 "For a moment, neither of them spoke.")
    assert r.words == ["Briefly", "Momentarily"]


# ── The hover card (what you see when pointing at a highlight) ────

def hover(ed, text, at):
    from PyQt6.QtCore import QPoint
    rect = ed.cursorRect(ed._cursor_at(text.index(at) + 2))
    pos = rect.center()
    assert ed._show_error_tooltip(ed.viewport().mapToGlobal(pos), pos)
    from PyQt6.QtWidgets import QPushButton
    return ed.error_card, {b.text(): b for b in ed.error_card.findChildren(QPushButton)}


def test_card_shows_the_repeated_phrase_under_an_overused_word(app):
    ed = overused_editor(app, PHRASE_TEXT)
    card, buttons = hover(ed, PHRASE_TEXT, "head and left")
    from PyQt6.QtWidgets import QLabel
    text = " ".join(l.text() for l in card.findChildren(QLabel))
    assert "Overused word" in text and "Repeated phrase" in text
    assert "nodded" in buttons and "✨ Suggest in context" in buttons and "Ignore phrase" in buttons
    buttons["nodded"].click()
    assert ed.toPlainText().startswith("She nodded and left.")


def test_card_for_a_phrase_offers_ai_even_without_a_standard_fix(app, monkeypatch):
    text = ("We met at the old mill gate. Later, the old mill gate creaked. "
            "Rain fell on the old mill gate.")
    ed = overused_editor(app, text)
    ed.overuse_detector.threshold = 99            # only the phrase is flagged
    ed.overuse_detector.update_cache(text + " ")
    ed.overuse_detector.update_cache(text)
    ed.writing_highlighter.rehighlight()
    card, buttons = hover(ed, text, "mill gate creaked")
    from PyQt6.QtWidgets import QLabel
    labels = " ".join(l.text() for l in card.findChildren(QLabel))
    assert "Repeated phrase" in labels and "No standard fix" in labels
    asked = []
    monkeypatch.setattr(ed, "suggest_in_context", lambda block, error: asked.append(error.word))
    buttons["✨ Suggest in context"].click()
    assert asked and "mill gate" in asked[0]


def test_card_for_an_overused_word_offers_ai(app, monkeypatch):
    ed = overused_editor(app, TEXT)
    card, buttons = hover(ed, TEXT, "looked exhausted")
    asked = []
    monkeypatch.setattr(ed, "suggest_in_context", lambda block, error: asked.append(error.word))
    buttons["✨ Suggest in context"].click()
    assert asked == ["looked"]
