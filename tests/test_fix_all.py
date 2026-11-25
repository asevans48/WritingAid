"""3.4: Accept all like this — mechanical fixes only, one undo."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.models.project import Chapter, WriterProject
from src.utils.editor_flags import ErrorType

TEXT = ("Teh rain fell on teh harbor.\n"
        "She watched teh boats from the window, and the the gulls cried.\n"
        "By noon teh tide had turned , and the the boats came in.")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def project():
    p = WriterProject(name="Saga")
    p.manuscript.chapters = [Chapter(id="c1", number=1, title="One", content="")]
    return p


def editor(app, project, text=TEXT):
    from src.ui.enhanced_text_editor import EnhancedTextEditor
    ed = EnhancedTextEditor()
    ed.resize(800, 400)
    ed.show()
    ed.setPlainText(text)
    ed.set_project_vocabulary(project)
    ed.do_initial_check()
    return ed


def error_at(ed, word, nth=0):
    at = -1
    for _ in range(nth + 1):
        at = ed.toPlainText().find(word, at + 1)
    block = ed.document().findBlock(at)
    return ed.writing_highlighter.get_error_at(block.blockNumber(), at - block.position())


def test_a_repeated_misspelling_is_fixed_in_one_action_and_undone_in_one(app, project):
    from src.ui import fix_all
    ed = editor(app, project)
    err = error_at(ed, "teh")
    assert err.error_type == ErrorType.SPELLING and fix_all.is_mechanical(err)
    assert "the" in err.suggestions and fix_all.worth_offering(ed, err)
    places = fix_all.places(ed, err, "the")
    assert [p.found for p in places] == ["Teh", "teh", "teh", "teh"]
    assert places[0].replacement == "The"                      # the writer's case is kept
    assert fix_all.apply(ed, places) == 4
    after = ed.toPlainText()
    assert "teh" not in after.lower() and after.startswith("The rain fell on the harbor.")
    ed.undo()
    assert ed.toPlainText() == TEXT                            # one undo, all of them


def test_the_list_lets_the_writer_leave_some_and_choose_the_word(app, project):
    from PyQt6.QtCore import Qt
    from src.ui import fix_all
    ed = editor(app, project)
    err = error_at(ed, "teh")
    dlg = fix_all.FixAllDialog(ed, err, "the")
    assert dlg.list.count() == 4 and dlg.ok.text() == "Fix all 4"
    assert "[Teh → The]" in dlg.list.item(0).text()
    dlg.list.item(1).setCheckState(Qt.CheckState.Unchecked)
    assert dlg.ok.text() == "Fix 3"
    fix_all.apply(ed, dlg.chosen())
    assert ed.toPlainText().count("teh") == 1                  # the unticked one is left
    if dlg.choice is not None:                                 # other spellings on offer
        assert dlg.choice.count() == len(fix_all._fixes(err))


def test_a_doubled_word_is_mechanical_too_and_each_keeps_its_own_fix(app, project):
    from src.ui import fix_all
    ed = editor(app, project)
    err = error_at(ed, "the the")
    assert err.error_type == ErrorType.GRAMMAR and fix_all.is_mechanical(err)
    places = fix_all.places(ed, err, err.suggestions[0])
    assert len(places) == 2 and all(p.replacement.lower() == "the" for p in places)
    fix_all.apply(ed, places)
    assert "the the" not in ed.toPlainText()


def test_any_kind_of_flag_can_be_fixed_everywhere_but_not_a_rewrite(app, project):
    from types import SimpleNamespace as NS
    from src.ui import fix_all
    ed = editor(app, project)
    overuse = NS(error_type=ErrorType.OVERUSE, word="boats", suggestions=["ships"], rule_id="")
    rewrite = NS(error_type=ErrorType.SPELLING, word="teh", rule_id="",
                 suggestions=["the boats were rocking gently along the quay"])
    assert fix_all.worth_offering(ed, overuse)              # the writer asked for every kind
    assert not fix_all.worth_offering(ed, rewrite)          # a long rewrite is not a fix


def test_a_single_misspelling_is_not_offered(app, project):
    from src.ui import fix_all
    ed = editor(app, project, "Teh rain fell.\nThe boats came in.")
    assert not fix_all.worth_offering(ed, error_at(ed, "Teh"))


def test_a_place_changed_since_the_list_is_left_alone(app, project):
    from src.ui import fix_all
    ed = editor(app, project)
    places = fix_all.places(ed, error_at(ed, "teh"), "the")
    cursor = ed.textCursor()
    cursor.setPosition(places[-1].start)
    cursor.setPosition(places[-1].end, cursor.MoveMode.KeepAnchor)
    cursor.insertText("tex")
    assert fix_all.apply(ed, places) == 3
    assert "tex tide" in ed.toPlainText()


def test_the_card_and_the_menu_offer_it(app, project, monkeypatch):
    ed = editor(app, project)
    at = ed.toPlainText().find("teh")
    rect = ed.cursorRect(ed._cursor_at(at + 1))
    assert ed._show_error_tooltip(ed.viewport().mapToGlobal(rect.center()), rect.center())
    from PyQt6.QtWidgets import QCheckBox, QPushButton
    assert "See all 4…" in {b.text() for b in ed.error_card.findChildren(QPushButton)}
    assert "Fix all 4 like this" in {b.text() for b in ed.error_card.findChildren(QCheckBox)}
    labels = []
    monkeypatch.setattr("PyQt6.QtWidgets.QMenu.exec", lambda self, *a: labels.extend(
        x.text() for x in self.actions()))
    ed._show_context_menu(rect.center())
    assert "Fix all like this…" in labels


def _card(ed, word):
    at = ed.toPlainText().find(word)
    rect = ed.cursorRect(ed._cursor_at(at + 1))
    assert ed._show_error_tooltip(ed.viewport().mapToGlobal(rect.center()), rect.center())
    return ed.error_card


def test_ticking_the_box_keeps_the_card_open_and_the_chosen_fix_goes_everywhere(app, project):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QCheckBox, QPushButton
    ed = editor(app, project)
    card = _card(ed, "teh")
    box = next(b for b in card.findChildren(QCheckBox) if b.text().startswith("Fix all"))
    from PyQt6.QtCore import QPoint
    QTest.mouseClick(box, Qt.MouseButton.LeftButton, pos=QPoint(8, box.height() // 2))
    app.processEvents()
    assert box.isChecked() and card.isVisible()               # ticking does not close it
    the = next(b for b in card.findChildren(QPushButton) if b.objectName() == "fix"
               and b.text() == "the")
    the.click()
    app.processEvents()
    after = ed.toPlainText()
    assert "teh" not in after.lower() and after.startswith("The rain")
    ed.undo()
    assert ed.toPlainText() == TEXT                            # one undo, all of them


def test_unticked_the_fix_is_made_in_one_place_only(app, project):
    from PyQt6.QtWidgets import QPushButton
    ed = editor(app, project)
    card = _card(ed, "teh")
    next(b for b in card.findChildren(QPushButton) if b.objectName() == "fix"
         and b.text() == "the").click()
    app.processEvents()
    assert ed.toPlainText().lower().count("teh") == 3


def test_the_menu_box_sits_under_replace_with_and_applies_the_chosen_fix(app, project,
                                                                         monkeypatch):
    from PyQt6.QtWidgets import QCheckBox, QWidgetAction
    ed = editor(app, project)
    at = ed.toPlainText().find("teh")
    rect = ed.cursorRect(ed._cursor_at(at + 1))
    seen = {}

    def run(menu, *a):
        acts = menu.actions()
        i = next(n for n, x in enumerate(acts) if x.text() == "Replace with:")
        holder = acts[i + 1]
        assert isinstance(holder, QWidgetAction)
        box = holder.defaultWidget()
        assert isinstance(box, QCheckBox) and box.text() == "Fix all 4 like this"
        box.setChecked(True)
        seen["menu_open"] = True
        next(x for x in acts if x.text().strip() == "the").trigger()
    monkeypatch.setattr("PyQt6.QtWidgets.QMenu.exec", run)
    ed._show_context_menu(rect.center())
    assert seen and "teh" not in ed.toPlainText().lower()


def test_the_list_offers_a_choice_of_fix_for_grammar_too(app, project):
    from types import SimpleNamespace as NS
    from src.ui import fix_all
    ed = editor(app, project)
    err = error_at(ed, "the the")
    err2 = NS(**{**err.__dict__, "suggestions": ["the", "they"]}) if hasattr(err, "__dict__") \
        else err
    if hasattr(err, "__dict__"):
        dlg = fix_all.FixAllDialog(ed, err2, "the")
        assert dlg.choice is not None and dlg.choice.count() == 2
