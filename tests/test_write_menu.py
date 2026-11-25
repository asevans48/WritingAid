"""D.1: the Write tab's right-click menu: short, nothing lost."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.models.project import Annotation, Chapter, WriterProject

TEXT = ("Teh rain fell on teh harbor all night.\n"
        "She watched the boats from the window.")

# Every entry of the menu before this piece (screens.md), by its text.
OLD_SELECTION = {"📝 Add Annotation", "Undo", "Redo", "Cut", "Copy", "Paste",
                 "Look Up Context", "Character Reference", "Worldbuilding Reference",
                 "Plot Reference", "Technology Reference", "Advanced Search...",
                 "Find Similar Content", "🤖 AI Thesaurus (world-aware)...",
                 "✨ Rephrase with AI...", "💡 Suggestions (critique + rewrites)...",
                 "🔍 Overly descriptive? (ways to expand)...", "Heading Style", "Normal",
                 "Heading 1", "Heading 2", "Heading 3", "🔊 Text to Speech",
                 "Read Selection Aloud", "Generate TTS Doc from Selection...",
                 "Read Entire Chapter", "Generate TTS Doc for Chapter...", "Stop Playback"}


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ce(app):
    from src.ui.manuscript_editor import ChapterEditor
    p = WriterProject(name="Saga")
    ch = Chapter(id="c1", number=1, title="One", content=TEXT)
    p.manuscript.chapters = [ch]
    ed = ChapterEditor(ch, project=p)
    ed.resize(900, 500)
    ed.show()
    ed.editor.set_project_vocabulary(p)
    ed.editor.do_initial_check()
    app.processEvents()
    return ed


def _menu(ce, position, monkeypatch):
    from PyQt6.QtWidgets import QMenu
    from src.ui import write_menu
    shown = {}
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: shown.setdefault("menu", self))
    write_menu.show(ce, position)
    return shown["menu"]


def _all(menu, out=None):
    out = [] if out is None else out
    for a in menu.actions():
        if a.text():
            out.append(a.text())
        if a.menu() is not None:
            _all(a.menu(), out)
    return out


def _top(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator() and a.text()]


def _select(ce, start, end):
    c = ce.editor.textCursor()
    c.setPosition(start)
    c.setPosition(end, c.MoveMode.KeepAnchor)
    ce.editor.setTextCursor(c)


def test_with_a_selection_everything_is_still_there_and_the_top_is_short(ce, monkeypatch):
    text = ce.editor.toPlainText()
    start = text.index("She watched")
    _select(ce, start, start + len("She watched the boats"))
    ce.chapter.annotations = [Annotation(id="a1", line_number=2, content="note")]
    pos = ce.editor.cursorRect().center()
    menu = _menu(ce, pos, monkeypatch)
    labels = set(_all(menu))
    missing = {x for x in OLD_SELECTION if x not in labels
               and not any(l.startswith(x.split(" (")[0]) for l in labels)}
    assert not missing, missing
    assert "📋 View Annotations (1)" in labels
    assert any(l.startswith('Look Up "She watched') for l in labels)   # the selection is seen
    assert "Cut" in _top(menu) and "Copy" in _top(menu)                # they appear now
    assert len(_top(menu)) <= 9, _top(menu)


def test_one_word_gets_synonyms_and_cut_and_copy(ce, monkeypatch):
    text = ce.editor.toPlainText()
    start = text.index("window")
    _select(ce, start, start + len("window"))
    menu = _menu(ce, ce.editor.cursorRect().center(), monkeypatch)
    top = _top(menu)
    assert any(t.startswith("📖 Synonyms for") for t in top)
    assert "Cut" in top and "Copy" in top


def test_a_flagged_word_shows_its_fixes_first(ce, monkeypatch):
    at = ce.editor.toPlainText().index("teh")
    c = ce.editor.textCursor()
    c.setPosition(at + 1)
    pos = ce.editor.cursorRect(c).center()
    menu = _menu(ce, pos, monkeypatch)
    top = _top(menu)
    assert "Replace with:" in top and top.index("Replace with:") < top.index("Paste")
    assert "💬 Ask about this…" in top and "Fix all like this…" in top
    from PyQt6.QtWidgets import QWidgetAction
    boxes = [a for a in menu.actions() if isinstance(a, QWidgetAction)
             and a.defaultWidget().__class__.__name__ == "QCheckBox"]
    assert boxes                                                       # the Fix-all box
    # Picking a fix from the Write tab's menu changes the text.
    the = next(a for a in menu.actions() if a.text().strip() == "the")
    the.trigger()
    after = ce.editor.toPlainText()
    assert "on the harbor" in after and after.startswith("Teh rain")     # that place only


def test_without_a_selection(ce, monkeypatch):
    c = ce.editor.textCursor()
    c.setPosition(len(ce.editor.toPlainText()))
    ce.editor.setTextCursor(c)
    menu = _menu(ce, ce.editor.cursorRect().center(), monkeypatch)
    top = _top(menu)
    assert "Cut" not in top and "Paste" in top and "More" in top
    labels = _all(menu)
    for x in ("📝 Add Annotation", "Read Entire Chapter", "Stop Playback", "Character Reference"):
        assert x in labels


def test_each_entry_calls_the_same_method_as_before(ce, monkeypatch):
    called = []
    for name in ("_rephrase_selection", "_suggest_for_selection", "_expand_selection",
                 "_lookup_character", "_tts_speak_chapter", "_add_annotation"):
        monkeypatch.setattr(ce, name, lambda *a, n=name: called.append(n))
    text = ce.editor.toPlainText()
    start = text.index("She watched")
    _select(ce, start, start + 11)
    menu = _menu(ce, ce.editor.cursorRect().center(), monkeypatch)

    def find(m, label):
        for a in m.actions():
            if a.text() == label:
                return a
            if a.menu() is not None:
                f = find(a.menu(), label)
                if f:
                    return f
    for label in ("✨ Rephrase with AI...", "💡 Suggestions (critique + rewrites)...",
                  "🔍 Overly descriptive? (ways to expand)...", "Character Reference",
                  "Read Entire Chapter", "📝 Add Annotation"):
        find(menu, label).trigger()
    assert called == ["_rephrase_selection", "_suggest_for_selection", "_expand_selection",
                      "_lookup_character", "_tts_speak_chapter", "_add_annotation"]


def test_improve_is_there_without_a_selection_and_works_on_the_sentence(ce, monkeypatch):
    called = []
    for name in ("_rephrase_selection", "_suggest_for_selection", "_expand_selection"):
        monkeypatch.setattr(ce, name, lambda n=name: called.append(
            (n, ce.editor.textCursor().selectedText())))
    text = ce.editor.toPlainText()
    c = ce.editor.textCursor()
    c.setPosition(text.index("boats") + 2)                 # no selection
    ce.editor.setTextCursor(c)
    menu = _menu(ce, ce.editor.cursorRect(c).center(), monkeypatch)
    top = _top(menu)
    assert top[0] == "✨ Improve this sentence", top        # first entry
    improve = next(a.menu() for a in menu.actions() if a.text() == "✨ Improve this sentence")
    labels = [a.text() for a in improve.actions()]
    assert labels == ["✨ Rephrase with AI...", "💡 Suggestions (critique + rewrites)...",
                      "🔍 Overly descriptive? (ways to expand)..."]
    for a in improve.actions():
        a.trigger()
    assert [n for n, _ in called] == ["_rephrase_selection", "_suggest_for_selection",
                                      "_expand_selection"]
    assert all(sel == "She watched the boats from the window." for _, sel in called)


def test_improve_comes_after_a_flag_s_fixes(ce, monkeypatch):
    at = ce.editor.toPlainText().index("teh")
    c = ce.editor.textCursor()
    c.setPosition(at + 1)
    ce.editor.setTextCursor(c)
    top = _top(_menu(ce, ce.editor.cursorRect(c).center(), monkeypatch))
    assert top.index("✨ Improve this sentence") > top.index("Replace with:")
