"""Where the retired trial screens went (piece D.6).

The side panel's **Style** tab and the Companion's **Today's three fixes**
list were retired on the writer's word (decision 11, 24 Nov 2026). Nothing
they did is lost:

* The Style tab's list of every style issue is the Companion's next-fix
  card (``open_style_issues``): ✓ Checks ▾ → "Style issues panel…" still
  opens it, as does switching Style on. Its switches and counts are
  ✓ Checks ▾ → Style checks (D.3), with the summary line at the top.
* Today's three fixes show on the same card (``next_fixes``).

The side panel had four tabs (Planner, Style, Feedback, Companion) and now
has three. Code that still opens a tab by its old number gets the tab it
meant (``panel_tab``); the Style tab's number opens the Companion. No
setting or saved layout records the side panel's tab, so there is nothing
stored to move; nothing stored is deleted.
"""

from __future__ import annotations

from typing import Any

# The side panel's tabs before D.6, by number. "style" is now the Companion.
OLD_TABS = ("planner", "style", "feedback", "companion")
NOTE_KEY = "d6/style_tab_moved_note_shown"
NOTE = ("The Style tab has moved: its list is this card, its switches and counts are "
        "in ✓ Checks ▾ → Style checks.")


def panel_tab(chapter_editor: Any, tab: Any) -> Any:
    """The widget an old tab number (0 to 3, the four-tab panel) meant;
    anything else is returned as it is."""
    if not isinstance(tab, int) or isinstance(tab, bool) or not 0 <= tab < len(OLD_TABS):
        return tab
    name = OLD_TABS[tab]
    if name == "planner":
        return chapter_editor.planner_widget
    if name == "feedback":
        return chapter_editor.feedback_widget
    companion = getattr(chapter_editor, "companion", None)
    return companion.panel if companion is not None else tab


def open_style_issues(chapter_editor: Any) -> None:
    """The shortcut that opened the Style tab: the Companion, its Next fixes
    section open, the card stepping through every style issue in the
    chapter. The first time, a line on the card says where the tab went."""
    companion = getattr(chapter_editor, "companion", None)
    if companion is None:
        return
    chapter_editor._show_right_panel(companion.panel)
    companion.panel.open_section("fixes")
    companion.queue.show_style_issues()
    if not _note_shown():
        status = companion.queue.card.status
        status.setText(NOTE + " " + status.text())
        _mark_note_shown()


def _note_shown() -> bool:
    try:
        from src.ui import ui_kit
        return str(ui_kit._settings().value(NOTE_KEY, "")) == "1"
    except Exception:
        return True                     # never fail over a note


def _mark_note_shown() -> None:
    try:
        from src.ui import ui_kit
        settings = ui_kit._settings()
        settings.setValue(NOTE_KEY, "1")
        settings.sync()
    except Exception:
        pass
