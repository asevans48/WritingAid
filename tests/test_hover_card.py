"""The editor's hover card stays open while the writer uses it.

It used to close on every highlight redraw (background checks fire the
editor's ``textChanged``), on a scroll over the card, and while the pointer
crossed from the word to the card."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TEXT = "The gate was barred by the Wardens before dusk. Mara waited by the zorbleflax."


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ed(app, monkeypatch):
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)
    from src.models.project import Chapter, WriterProject
    from src.ui.enhanced_text_editor import CheckMode, EnhancedTextEditor
    project = WriterProject(name="Saga")
    project.manuscript.chapters = [Chapter(id="c1", number=1, title="One", content="")]
    e = EnhancedTextEditor()
    e.resize(800, 400)
    e.show()
    e.writing_highlighter.set_style_mode(CheckMode.REALTIME)
    e.setPlainText(TEXT)
    e.set_project_vocabulary(project)
    e.do_initial_check()
    app.processEvents()
    yield e
    if getattr(e, "_error_card", None) is not None:
        e._error_card.hide()
    e.close()


def _open_card(ed, app, word="zorbleflax"):
    """Hover the flagged word; return the card's global position of the word."""
    pos = TEXT.index(word) + 2
    rect = ed.cursorRect(ed._cursor_at(pos))
    global_pos = ed.viewport().mapToGlobal(rect.center())
    assert ed._show_error_tooltip(global_pos, rect.center())
    app.processEvents()
    card = ed.error_card
    assert card.isVisible() and card.error.word == word
    return card, global_pos


def test_card_survives_a_highlight_redraw(ed, app):
    card, _ = _open_card(ed, app)
    ed.writing_highlighter.rehighlight()       # what background checks do
    app.processEvents()
    assert card.isVisible()


def test_card_closes_when_the_text_is_edited(ed, app):
    from PyQt6.QtGui import QTextCursor
    card, _ = _open_card(ed, app)
    cur = ed.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    cur.insertText(" More.")
    app.processEvents()
    assert not card.isVisible()


def test_card_closes_when_a_redraw_removes_its_flag(ed, app):
    from src.ui.enhanced_text_editor import ErrorType
    card, _ = _open_card(ed, app)
    ed.writing_highlighter.ignore_error(card.block_number, card.error.start, card.error.word,
                                        ErrorType.SPELLING)
    ed.writing_highlighter.rehighlight()
    app.processEvents()
    assert not card.isVisible()


def test_scrolling_over_the_card_keeps_it_open(ed, app):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent
    card, _ = _open_card(ed, app)

    def wheel_at(global_point):
        local = ed.viewport().mapFromGlobal(global_point)
        return QWheelEvent(QPointF(local), QPointF(global_point), QPoint(0, 0), QPoint(0, -120),
                           Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                           Qt.ScrollPhase.NoScrollPhase, False)
    ed.viewportEvent(wheel_at(card.geometry().center()))
    assert card.isVisible()
    ed.viewportEvent(wheel_at(ed.viewport().mapToGlobal(QPoint(5, 300))))   # over the text
    assert not card.isVisible()


def test_card_stays_while_the_pointer_crosses_to_it(ed, app, monkeypatch):
    import src.ui.hover_card as hc
    card, word_pos = _open_card(ed, app)
    geo = card.geometry()
    gap = word_pos.__class__(geo.left() + 10, geo.top() - 3)      # between word and card
    for point in (word_pos, gap, geo.center()):
        monkeypatch.setattr(hc.QCursor, "pos", staticmethod(lambda p=point: p))
        card._maybe_hide()
        assert card.isVisible(), point
    far = word_pos.__class__(geo.right() + 300, geo.bottom() + 300)
    monkeypatch.setattr(hc.QCursor, "pos", staticmethod(lambda: far))
    card._maybe_hide()
    assert not card.isVisible()


def test_losing_focus_does_not_close_it_while_the_pointer_is_on_it(ed, app, monkeypatch):
    import src.ui.hover_card as hc
    from PyQt6.QtGui import QFocusEvent
    from PyQt6.QtCore import QEvent
    card, _ = _open_card(ed, app)
    monkeypatch.setattr(hc.QCursor, "pos", staticmethod(lambda: card.geometry().center()))
    ed.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    card._maybe_hide()
    assert card.isVisible()
