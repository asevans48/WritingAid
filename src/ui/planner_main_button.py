"""The Planner's one coloured button (D.8, the writer's choice).

The plan comes first: without AI, "+ Add" (a chapter event) is the main
button. With AI set up, the conversation is the centrepiece, so
"🤖 AI Assistant" is the main button instead. Checked each time the
Planner is shown, so turning AI on or off in Settings is followed.
Colour only: both buttons keep their size, text and behaviour.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QEvent, QObject

from src.ui.ui_kit import PRIMARY_BUTTON, plain_qss

ADD_PLAIN = plain_qss(pad="2px 6px")
ADD_MAIN = PRIMARY_BUTTON + "QPushButton { font-size: 11px; padding: 2px 6px; }"
AI_PLAIN = plain_qss(pad="4px 8px", bold=True) + "QPushButton { text-align: left; }"
AI_MAIN = PRIMARY_BUTTON + "QPushButton { font-size: 11px; padding: 4px 8px; text-align: left; }"


def _ai_on() -> bool:
    from src.ui.scorecard_model_run import ai_available
    return ai_available()


def apply(planner: Any) -> None:
    ai = _ai_on()
    add = getattr(planner, "add_event_btn", None)
    talk = getattr(planner, "ai_toggle_btn", None)
    if add is not None:
        add.setStyleSheet(ADD_PLAIN if ai else ADD_MAIN)
    if talk is not None:
        talk.setStyleSheet(AI_MAIN if ai else AI_PLAIN)


class _OnShow(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show:
            apply(obj)
        return False


def install(planner: Any) -> None:
    """The call line in ``ChapterPlannerWidget``."""
    try:
        apply(planner)
        planner._main_button_filter = _OnShow(planner)
        planner.installEventFilter(planner._main_button_filter)
    except Exception as e:                     # never break the Planner
        print(f"[planner] main button not set: {e}")
