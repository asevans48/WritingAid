"""Late LanguageTool results are dropped quietly when the editor is gone
or half torn down, and applied as before otherwise. Results are faked;
LanguageTool is never started."""

import pytest
from PyQt6 import sip


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    from src.utils.proofing import LanguageToolEngine
    monkeypatch.setattr(LanguageToolEngine, "ensure_started", lambda self: False)


TEXT = "Mara walk home slowly."


def _editor(app):
    from src.ui.enhanced_text_editor import EnhancedTextEditor
    e = EnhancedTextEditor()
    e.setPlainText(TEXT)
    e.writing_highlighter.wait_for_grammar(5000)
    return e


def _result():
    from src.utils.proofing import GrammarIssue
    s = TEXT.index("walk")
    return {TEXT: [GrammarIssue(s, s + 4, "walk", "Agreement", ["walks"],
                                "AGREE", "languagetool")]}


def _underlined(e):
    b = e.document().begin()
    return [b.text()[f.start:f.start + f.length]
            for f in b.layout().formats() if f.format.underlineStyle() != 0]


def test_a_result_for_a_live_editor_is_applied(app):
    e = _editor(app)
    hl = e.writing_highlighter
    from src.ui.grammar_results import stale_reason
    assert stale_reason(hl) is None
    hl._on_grammar_results(_result())
    assert TEXT in hl._lt_cache
    assert "walk" in _underlined(e)


def test_a_result_for_text_no_longer_there_changes_nothing_on_screen(app):
    e = _editor(app)
    hl = e.writing_highlighter
    before = _underlined(e)
    from src.utils.proofing import GrammarIssue
    hl._on_grammar_results({"Some old paragraph.": [GrammarIssue(0, 4, "Some", "x")]})
    assert _underlined(e) == before


def test_a_result_after_the_editor_is_torn_down_is_dropped(app, capsys):
    """The editor's Python helpers (its typing timer) are already deleted
    while the widget waits for deletion: applying the result would make
    the editor's text-changed slot raise and abort the app."""
    e = _editor(app)
    hl = e.writing_highlighter
    sip.delete(e._update_timer)
    hl._on_grammar_results(_result())          # must not raise
    assert TEXT not in hl._lt_cache
    assert "[grammar]" in capsys.readouterr().out


def test_a_result_after_the_editor_is_deleted_is_dropped(app, capsys):
    from src.ui.grammar_results import drop_if_stale
    e = _editor(app)
    hl = e.writing_highlighter
    sip.delete(e)                              # takes the document and highlighter with it
    assert sip.isdeleted(hl)
    hl._on_grammar_results(_result())          # must not raise
    assert drop_if_stale(hl) is True
    assert "[grammar]" in capsys.readouterr().out


def test_a_highlighter_whose_document_is_gone_is_stale(app):
    from PyQt6.QtGui import QTextDocument
    from src.ui.grammar_results import stale_reason
    from src.ui.enhanced_text_editor import WritingHighlighter
    doc = QTextDocument()
    hl = WritingHighlighter(doc, None, None, None)
    assert stale_reason(hl) is None
    sip.delete(doc)
    assert stale_reason(hl) is not None
