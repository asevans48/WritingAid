"""Streamlined chapter-editor toolbar: grouped menus instead of rows of
buttons, with every feature still reachable."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def editor(monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)
    from src.models.project import Chapter, WriterProject
    from src.ui.manuscript_editor import ChapterEditor
    ed = ChapterEditor(Chapter(id="c1", number=1, title="One", content="It was very cold."),
                       project=WriterProject(name="t"))
    ed.resize(1100, 600)
    ed.show()
    app.processEvents()
    yield ed
    ed.close()


def _visible_buttons(ed):
    from PyQt6.QtWidgets import QPushButton, QToolButton
    return [b for b in ed.findChildren((QPushButton, QToolButton))
            if b.isVisibleTo(ed) and b.text()]


def test_toolbar_is_compact(editor):
    texts = [b.text() for b in _visible_buttons(editor)]
    for gone in ("ABC", "Gr", "Ov", "Sty", "🔄", "Clean", "Import", "Export", "Hints", "Check",
                 "Prose", "Chars", "World", "Plot", "Save Draft", "Drafts", "Feedback", "⏹ Stop"):
        assert gone not in texts
    assert len(texts) <= 12


def test_checks_menu_controls_modes(editor):
    from src.ui.enhanced_text_editor import CheckMode
    acts = editor._check_actions
    assert [k for k, a in acts.items() if a.isChecked()] == ["spell", "grammar", "overuse"]
    assert editor.checks_btn.text().startswith("✓ Checks · 3")
    acts["grammar"].setChecked(False)
    assert editor.editor.get_grammar_mode() == CheckMode.OFF
    assert editor.checks_btn.text().startswith("✓ Checks · 2")
    acts["grammar"].setChecked(True)
    editor._realtime_action.setChecked(True)
    assert editor.editor.get_grammar_mode() == CheckMode.REALTIME
    assert editor.editor.get_overuse_mode() == CheckMode.REALTIME
    assert editor.editor.get_spell_mode() == CheckMode.ON_DEMAND
    acts["style"].setChecked(True)
    assert editor.editor.get_style_mode() == CheckMode.ON_DEMAND
    assert editor.right_panel.currentWidget() is editor.style_panel
    # The Style panel's own toggle stays in sync with the menu.
    editor.style_panel.highlight_cb.setChecked(False)
    assert not acts["style"].isChecked()


def test_every_analysis_and_draft_action_is_in_a_menu(editor):
    analyze = [a.text() for a in editor.analyze_btn.menu().actions() if a.text()]
    draft = [a.text() for a in editor.draft_btn.menu().actions() if a.text()]
    for label in ("Critique this chapter (all reports)", "Writing hints", "Characters",
                  "Worldbuilding", "Check consistency (names, spellings)…"):
        assert label in analyze
    assert any(t.startswith("Promises") for t in analyze)
    for label in ("Save draft", "View drafts…", "Import from Word…", "Export to Word…",
                  "Clean up formatting"):
        assert label in draft
    tts = [a.text() for a in editor.tts_speak_btn.menu().actions()]
    assert tts == ["⏹ Stop reading", "Read chapters…", "🎙 Export audio file…"]


def test_side_panel_toggle_and_tabs(editor):
    assert not editor.right_panel.isVisible()
    editor.toggle_planner_btn.click()
    assert editor.right_panel.isVisible() and editor.toggle_planner_btn.isChecked()
    editor._toggle_feedback()
    assert editor.right_panel.currentWidget() is editor.feedback_widget
    editor.toggle_planner_btn.click()
    assert not editor.right_panel.isVisible()
