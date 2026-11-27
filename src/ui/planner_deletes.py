"""The Planner's questions before a delete (piece D.14).

``chapter_planner_widget.py`` is over 3,000 lines, so each of its four
delete buttons (a story event, a to-do, a note, a subplot note) calls one
function here, which names the item and asks the shared question
(``ui_kit.confirm_delete``). An item with nothing typed in it yet goes
without asking: there is nothing to lose.
"""

from __future__ import annotations

from typing import Any, Iterable

from src.ui.ui_kit import confirm_delete


def _blank(values: Iterable[Any]) -> bool:
    return not any(str(v or "").strip() for v in values)


def _widget_data(widgets: Iterable[Any], attr: str, wanted: str) -> dict:
    for w in widgets:
        if getattr(w, attr, None) == wanted:
            try:
                return w.get_data()
            except Exception:
                return {}
    return {}


def event(planner: Any, event_id: str) -> bool:
    data = _widget_data(planner._event_widgets, "event_id", event_id)
    return confirm_delete(planner, "event", data.get("text", ""),
                          empty=_blank((data.get("text"), data.get("description"))))


def todo(planner: Any, item_id: str) -> bool:
    data = _widget_data(planner._todo_widgets, "item_id", item_id)
    return confirm_delete(planner, "to-do", data.get("text", ""),
                          empty=_blank((data.get("text"),)))


def _entry(planner: Any, kind: str, entry: dict) -> bool:
    return confirm_delete(planner, kind, entry.get("title", ""),
                          empty=_blank((entry.get("title"), entry.get("content"))))


def note(planner: Any, index: int) -> bool:
    """A note in the open subject (what is typed is saved first, so the
    question names it)."""
    try:
        planner._save_current_entries()
        entries = planner._notes_data[planner._current_subject_index]["entries"]
    except Exception:
        return confirm_delete(planner, "note")
    return _entry(planner, "note", entries[index]) if 0 <= index < len(entries) else False


def subplot_note(planner: Any, index: int) -> bool:
    try:
        planner._save_subplot_entries()
        data = planner._subplot_data
    except Exception:
        return confirm_delete(planner, "subplot note")
    return _entry(planner, "subplot note", data[index]) if 0 <= index < len(data) else False
