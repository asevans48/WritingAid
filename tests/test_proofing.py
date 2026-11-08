"""Spelling / grammar highlighting in the manuscript editor, and readability."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.utils.proofing import (
    GrammarIssue, LanguageToolEngine, builtin_grammar, count_syllables, merge_issues,
    readability,
)


def _rules(text):
    return {i.rule_id for i in builtin_grammar(text)}


# ── Built-in grammar rules ────────────────────────────────────────

@pytest.mark.parametrize("text,rule", [
    ("Their going home.", "THEIR_THEYRE"),
    ("Their is a problem.", "THEIR_THERE"),
    ("its raining outside", "ITS_ITS"),
    ("I could of gone.", "MODAL_OF"),
    ("He dont know nothing.", "DOUBLE_NEGATIVE"),
    ("I has a dog.", "AGREEMENT"),
    ("They was late.", "AGREEMENT"),
    ("She recieve a a letter.", "REPEATED_WORD"),
    ("It took a hour.", "A_VS_AN"),
    ("an university", "AN_VS_A"),
    ("He said i was right.", "LOWERCASE_I"),
    ("It ended. then we left.", "SENTENCE_CAPITAL"),
    ("We left.Then it rained.", "SPACE_AFTER_PERIOD"),
    ("Better then ever.", "THEN_THAN"),
])
def test_builtin_rules_catch(text, rule):
    assert rule in _rules(text)


@pytest.mark.parametrize("text", [
    "He had had enough.", "An honest man.", "A unicorn.", "A European city.",
    "Mr. smith arrived.", "If he were king.", "\"Where?\" she asked.", "An apple.",
])
def test_builtin_rules_leave_correct_text_alone(text):
    assert not builtin_grammar(text), [(i.rule_id, i.text) for i in builtin_grammar(text)]


def test_merge_keeps_overlapping_but_drops_contained():
    lt = [GrammarIssue(3, 7, "dont", "contraction", rule_id="LT", source="languagetool")]
    bi = [GrammarIssue(3, 20, "dont know nothing", "double negative", rule_id="DN"),
          GrammarIssue(3, 7, "dont", "contraction", rule_id="CA")]
    merged = merge_issues(lt, bi)
    assert [i.rule_id for i in merged] == ["DN", "LT"]


# ── Readability ───────────────────────────────────────────────────

def test_syllables():
    assert [count_syllables(w) for w in
            ["the", "cat", "table", "little", "beautiful", "walked", "readability"]] \
        == [1, 1, 2, 2, 3, 1, 5]


def test_readability_scores():
    easy = readability("The cat sat on the mat. The dog ran. It was a nice day.")
    hard = readability("Notwithstanding considerable institutional resistance, the "
                       "administration's comprehensive reorganization ultimately "
                       "facilitated unprecedented interdepartmental collaboration.")
    assert easy.fk_grade < 4 and easy.reading_ease > 85 and easy.ease_label in ("easy", "very easy")
    assert hard.fk_grade > 16 and hard.reading_ease < 30
    assert readability("Hi.") is None


# ── Editor highlighting ───────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _underlines(editor):
    out = []
    b = editor.document().begin()
    while b.isValid():
        for f in b.layout().formats():
            if f.format.underlineStyle() != 0:
                kind = "S" if f.format.underlineColor().red() == 255 else "G"
                out.append((b.blockNumber(), b.text()[f.start:f.start + f.length], kind))
        b = b.next()
    return out


def _editor(app, text, lt=False, monkeypatch=None):
    from src.ui.enhanced_text_editor import EnhancedTextEditor
    if not lt and monkeypatch is not None:
        monkeypatch.setattr(LanguageToolEngine, "ensure_started", lambda self: False)
    e = EnhancedTextEditor()
    e.setPlainText(text)
    e.do_initial_check()
    e.writing_highlighter.wait_for_grammar(90000)
    return e


def test_underlines_show_on_load_and_survive_edits(app, monkeypatch):
    from PyQt6.QtGui import QTextCursor
    e = _editor(app, "He went tommorow.\nShe recieve a a letter.", monkeypatch=monkeypatch)
    before = _underlines(e)
    assert (0, "tommorow", "S") in before and (1, "recieve", "S") in before
    assert (1, "a a", "G") in before
    c = e.textCursor()
    c.movePosition(QTextCursor.MoveOperation.End)
    e.setTextCursor(c)
    e.textCursor().insertText(" More text.")
    after = _underlines(e)
    assert (1, "recieve", "S") in after and (1, "a a", "G") in after   # the old bug
    assert (0, "tommorow", "S") in after


def test_word_being_typed_is_not_flagged_until_finished(app, monkeypatch):
    from PyQt6.QtGui import QTextCursor
    e = _editor(app, "Start here.", monkeypatch=monkeypatch)
    c = e.textCursor()
    c.movePosition(QTextCursor.MoveOperation.End)
    e.setTextCursor(c)
    for ch in " speling":
        e.textCursor().insertText(ch)
    assert not any(w == "speling" for _, w, _ in _underlines(e))
    e.textCursor().insertText(" ")
    assert (0, "speling", "S") in _underlines(e)


def test_names_vs_sentence_start_typos(app, monkeypatch):
    e = _editor(app, "Kessa said nothing. Tommorow we sail. Ysolde laughed. "
                     "Aldric left. Later, Aldric returned. Beleive me.", monkeypatch=monkeypatch)
    spelled = [w for _, w, k in _underlines(e) if k == "S"]
    assert spelled == ["Tommorow", "Beleive"]


def test_project_vocabulary_and_suggestions(app, monkeypatch):
    from types import SimpleNamespace as NS
    e = _editor(app, "the greywater docks. Walk to the saltmarket. Go tommorow.",
                monkeypatch=monkeypatch)
    e.set_project_vocabulary(NS(characters=[], worldbuilding=None,
                                dictionary=NS(words=["Greywater", "Saltmarket"])))
    spelled = [w for _, w, k in _underlines(e) if k == "S"]
    assert spelled == ["tommorow"]
    err = e.writing_highlighter.get_error_at(0, e.toPlainText().index("tommorow"))
    assert err.suggestions[0] == "tomorrow"


def test_toggling_grammar_off_and_on(app, monkeypatch):
    from src.ui.enhanced_text_editor import CheckMode
    e = _editor(app, "I could of gone.", monkeypatch=monkeypatch)
    assert any(k == "G" for _, _, k in _underlines(e))
    e.set_grammar_mode(CheckMode.OFF)
    assert not any(k == "G" for _, _, k in _underlines(e))
    e.set_grammar_mode(CheckMode.ON_DEMAND)
    assert any(k == "G" for _, _, k in _underlines(e))


@pytest.mark.skipif(not LanguageToolEngine.prerequisites()[0],
                    reason="LanguageTool needs language-tool-python + Java")
def test_languagetool_results_are_highlighted(app):
    e = _editor(app, "She go to the store every days. It were raining.", lt=True)
    grammar = [w for _, w, k in _underlines(e) if k == "G"]
    assert grammar, "LanguageTool found nothing"
    assert any(i.source == "languagetool"
               for issues in e.writing_highlighter._lt_cache.values() for i in issues)


# ── Highlights (background) that follow the text ─────────────────

def _marks(editor):
    """[(block, text, kind)] for background highlights: S=spelling, G=grammar."""
    out = []
    b = editor.document().begin()
    while b.isValid():
        for f in b.layout().formats():
            bg = f.format.background()
            if bg.style() == 0:
                continue
            name = bg.color().name()
            kind = {"#fca5a5": "S", "#86efac": "G"}.get(name)
            if kind:
                out.append((b.blockNumber(), b.text()[f.start:f.start + f.length], kind))
        b = b.next()
    return out


def _type_at(editor, pos, text):
    from PyQt6.QtGui import QTextCursor
    c = editor.textCursor()
    c.setPosition(pos)
    editor.setTextCursor(c)
    editor.textCursor().insertText(text)
    editor._update_realtime_analysis()        # typing pause


def test_errors_are_background_highlights(app, monkeypatch):
    e = _editor(app, "She recieve a a letter.", monkeypatch=monkeypatch)
    assert (0, "recieve", "S") in _marks(e) and (0, "a a", "G") in _marks(e)


def test_highlights_follow_the_words_and_clear_when_fixed(app, monkeypatch):
    from PyQt6.QtGui import QTextCursor
    e = _editor(app, "First line.\nShe recieve the letter tommorow.", monkeypatch=monkeypatch)
    _type_at(e, len("First line.\nShe "), "quietly ")          # edit before the error
    assert (1, "recieve", "S") in _marks(e) and (1, "tommorow", "S") in _marks(e)
    _type_at(e, 0, "A brand new opening paragraph.\n")         # new paragraph above
    assert (2, "recieve", "S") in _marks(e)
    # Fix the word → its highlight goes, the other stays.
    text = e.toPlainText()
    c = e.textCursor()
    c.setPosition(text.index("recieve"))
    c.setPosition(text.index("recieve") + len("recieve"), QTextCursor.MoveMode.KeepAnchor)
    e.setTextCursor(c)
    e.textCursor().insertText("receive")
    e._update_realtime_analysis()
    words = [w for _, w, _ in _marks(e)]
    assert "receive" not in words and "recieve" not in words and "tommorow" in words


def test_languagetool_highlights_survive_edits_elsewhere(app, monkeypatch):
    from src.utils.proofing import GrammarIssue
    e = _editor(app, "Mara walk home slowly. The sky was grey.", monkeypatch=monkeypatch)
    hl = e.writing_highlighter
    text = e.toPlainText()
    s = text.index("walk")
    hl._lt_cache[text] = [GrammarIssue(s, s + 4, "walk", "Agreement", ["walks"],
                                       "AGREE", "languagetool")]
    hl.rehighlight()
    assert (0, "walk", "G") in _marks(e)
    _type_at(e, len(text), " It rained.")                     # edit elsewhere in paragraph
    assert (0, "walk", "G") in _marks(e)                       # carried over, still on "walk"
    _type_at(e, 0, "Then ")                                    # shift it right
    marks = _marks(e)
    assert (0, "walk", "G") in marks
    from PyQt6.QtGui import QTextCursor
    t = e.toPlainText()
    c = e.textCursor()
    c.setPosition(t.index("walk"))
    c.setPosition(t.index("walk") + 4, QTextCursor.MoveMode.KeepAnchor)
    e.setTextCursor(c)
    e.textCursor().insertText("walked")                       # the flagged word changes
    e._update_realtime_analysis()
    assert not [m for m in _marks(e) if m[2] == "G"]


def test_highlights_can_be_hidden_and_shown(app, monkeypatch):
    e = _editor(app, "She recieve a a letter.", monkeypatch=monkeypatch)
    e.set_highlights_visible(False)
    assert _marks(e) == [] and not e.writing_highlighter._errors.get(0)
    e.set_highlights_visible(True)
    assert (0, "recieve", "S") in _marks(e)


def test_checks_menu_show_highlights_toggle(app, monkeypatch):
    monkeypatch.setattr(LanguageToolEngine, "ensure_started", lambda self: False)
    from src.models.project import Chapter, WriterProject
    from src.ui.manuscript_editor import ChapterEditor
    ed = ChapterEditor(Chapter(id="c1", number=1, title="One", content="She recieve it."),
                       project=WriterProject(name="t"))
    act = ed._show_highlights_action
    assert act.isChecked() and act.shortcut().toString() == "Ctrl+Shift+H"
    act.setChecked(False)
    assert not ed.editor.highlights_visible() and ed.checks_btn.text().startswith("✓ Checks · hidden")
    act.setChecked(True)
    assert ed.editor.highlights_visible() and ed.checks_btn.text().startswith("✓ Checks · 3")


# ── Clickable suggestion card ─────────────────────────────────────

def _hover(e, word, occurrence=0):
    """Show the card for ``word`` as a hover would."""
    from PyQt6.QtGui import QTextCursor
    text = e.toPlainText()
    pos = -1
    for _ in range(occurrence + 1):
        pos = text.index(word, pos + 1)
    cur = QTextCursor(e.document())
    cur.setPosition(pos + 1)
    vp = e.cursorRect(cur).center()
    return e._show_error_tooltip(e.viewport().mapToGlobal(vp), vp)


def _card_buttons(e):
    from PyQt6.QtWidgets import QPushButton
    return {b.text(): b for b in e.error_card.findChildren(QPushButton) if b.isVisibleTo(e.error_card)}


def test_card_suggestion_click_replaces_word(app, monkeypatch):
    e = _editor(app, "She will leave tommorow at dawn.", monkeypatch=monkeypatch)
    e.show()
    assert _hover(e, "tommorow")
    card = e.error_card
    assert card.isVisible() and card.error.word == "tommorow"
    buttons = _card_buttons(e)
    assert "tomorrow" in buttons and "Add to dictionary" in buttons and "Ignore" in buttons
    buttons["tomorrow"].click()
    assert e.toPlainText() == "She will leave tomorrow at dawn."
    assert not card.isVisible()
    assert not [m for m in _marks(e) if m[2] == "S"]


def test_card_multiword_grammar_fix_and_case(app, monkeypatch):
    e = _editor(app, "Tommorow we sail. I could of gone.", monkeypatch=monkeypatch)
    e.show()
    assert _hover(e, "Tommorow")
    _card_buttons(e)["Tomorrow"].click()                       # keeps sentence case
    assert e.toPlainText().startswith("Tomorrow we sail.")
    assert _hover(e, "could of")
    _card_buttons(e)["could have"].click()
    assert e.toPlainText() == "Tomorrow we sail. I could have gone."


def test_card_style_delete_and_ignore(app, monkeypatch):
    from src.ui.enhanced_text_editor import CheckMode
    e = _editor(app, "It was very cold. It was very dark.", monkeypatch=monkeypatch)
    e.show()
    e.set_style_mode(CheckMode.ON_DEMAND)
    assert _hover(e, "very")
    buttons = _card_buttons(e)
    assert "✨ Rewrite with AI" in buttons
    buttons["Delete “very”"].click()
    assert e.toPlainText() == "It was cold. It was very dark."
    assert _hover(e, "very")
    _card_buttons(e)["Ignore"].click()
    assert not _hover(e, "very")                               # ignored → no card


def test_card_add_to_dictionary_and_stale_guard(app, monkeypatch):
    from PyQt6.QtGui import QTextCursor
    e = _editor(app, "The zorbling sang. Then tommorow came.", monkeypatch=monkeypatch)
    e.show()
    assert _hover(e, "zorbling")
    _card_buttons(e)["Add to dictionary"].click()
    assert not _hover(e, "zorbling")
    assert _hover(e, "tommorow")
    card = e.error_card
    # The text under the card changes without a keystroke reaching the card.
    card.blockSignals(True)
    cur = QTextCursor(e.document())
    cur.setPosition(e.toPlainText().index("tommorow"))
    cur.setPosition(e.toPlainText().index("tommorow") + 3, QTextCursor.MoveMode.KeepAnchor)
    e.textChanged.disconnect(card.hide)
    cur.insertText("XYZ")
    card._apply("tomorrow")
    assert "XYZmorow" in e.toPlainText()                      # stale fix not applied


def test_card_hides_when_mouse_leaves_or_typing(app, monkeypatch):
    e = _editor(app, "She left tommorow.", monkeypatch=monkeypatch)
    e.show()
    assert _hover(e, "tommorow")
    card = e.error_card
    from PyQt6.QtGui import QCursor
    QCursor.setPos(card.geometry().bottomRight() + card.geometry().topLeft() * 0 + __import__(
        "PyQt6.QtCore", fromlist=["QPoint"]).QPoint(400, 400))
    card.schedule_hide()
    card._maybe_hide()
    assert not card.isVisible()
    assert _hover(e, "tommorow") and card.isVisible()
    e.textCursor().insertText("x")
    assert not card.isVisible()
