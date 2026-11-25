"""D.8, the writer's answers: every unstyled button is plain app-wide; the
Critique's main button is Run Critique; the Planner's is "+ Add" without
AI and the AI Assistant with it. Colour only: same buttons, same sizes."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_app_wide_buttons_are_plain_and_keep_their_size():
    from src.ui.styles import COLORS, MODERN_STYLE as css
    first = css[css.index("QPushButton {"):css.index("}", css.index("QPushButton {"))]
    assert COLORS["surface"] in first and COLORS["primary"] not in first
    assert "padding: 7px 15px" in first and "border: 1px solid" in first   # 8px 16px before, borderless
    assert "QPushButton:default" in css                                   # a dialog's OK stays coloured


def test_run_critique_is_the_main_button(app):
    from src.ui.grader_widget import GraderWidget
    from src.ui.ui_kit import PRIMARY_BUTTON, PALETTE
    g = GraderWidget()
    assert g.critique_btn.styleSheet().startswith(PRIMARY_BUTTON)
    check = getattr(g, "scorecard", None) or getattr(g, "readiness", None)
    if check is None:
        from src.ui.scorecard_widget import ScorecardWidget
        check = ScorecardWidget()
    assert PALETTE["primary"] not in check.check_btn.styleSheet().split("hover")[0]
    assert not check.check_btn.isDefault()


@pytest.mark.parametrize("ai", [False, True])
def test_planner_main_button_follows_ai(app, monkeypatch, ai):
    import src.ui.planner_main_button as pmb
    from src.ui.chapter_planner_widget import ChapterPlannerWidget
    monkeypatch.setattr(pmb, "_ai_on", lambda: ai)
    p = ChapterPlannerWidget()
    pmb.apply(p)
    assert (p.ai_toggle_btn.styleSheet() == pmb.AI_MAIN) is ai
    assert (p.add_event_btn.styleSheet() == pmb.ADD_MAIN) is (not ai)
    monkeypatch.setattr(pmb, "_ai_on", lambda: not ai)      # AI switched in Settings
    p.show(); app.processEvents()
    assert (p.ai_toggle_btn.styleSheet() == pmb.AI_MAIN) is (not ai)
    p.close()
