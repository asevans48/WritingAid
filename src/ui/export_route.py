"""The Export menu follows the publishing goal (piece 9.2).

* **Order.** The format that matches the manuscript's publishing route
  comes first: "Export Publisher Ready" (standard manuscript format) for
  agent submission, "Export for Kindle" for self-publishing. The other
  entries follow in their usual order. Nothing is added or removed.
* **Kind.** The standard manuscript's title page says "A Novel by …" or
  "A Novella by …" from the publishing goal.
"""

from __future__ import annotations

from typing import Any

FIRST = {"agent": "Export &Publisher Ready", "self": "Export for &Kindle"}
FORMATS = ("Export for &Kindle", "Export for &Barnes && Noble", "Export &Publisher Ready",
           "Export as &Word Document")


def _goal(project: Any):
    from src.data import publishing_goal as pg
    return pg.publishing_goal(project, getattr(project, "active_subproject_id", None))


def kind_label(project: Any) -> str:
    try:
        return "Novella" if _goal(project).kind == "novella" else "Novel"
    except Exception:
        return "Novel"


def order(menu: Any, project: Any) -> None:
    """Put the route's format first among the four manuscript formats."""
    if project is None:
        return
    try:
        first = FIRST.get(_goal(project).route)
    except Exception:
        return
    actions = [a for a in menu.actions() if a.text() in FORMATS]
    if not first or len(actions) != len(FORMATS):
        return
    wanted = sorted(actions, key=lambda a: (a.text() != first, FORMATS.index(a.text())))
    if [a.text() for a in actions] == [a.text() for a in wanted]:
        return
    anchor = next((a for a in menu.actions() if a not in actions), None)
    for a in actions:
        menu.removeAction(a)
    for a in wanted:
        menu.insertAction(anchor, a) if anchor is not None else menu.addAction(a)


def install(main_window: Any, menu: Any) -> None:
    menu.aboutToShow.connect(lambda: order(menu, getattr(main_window, "current_project", None)))
