"""The Critique in its own window, beside Write (piece 2.5).

Since D.4 there is one way to put a screen in its own window, for every
screen: ``screen_groups`` (right-click a tab → "Open … in Its Own
Window"). This module keeps the Critique's own entries on that mover:

* "Critique in Its Own Window" in the Critique menu (``add_to_menu``),
  which becomes "Bring the Critique Back to Its Tab" while it is out;
* ``PopOut``, the object the main window keeps as ``critique_popout``
  (``is_out``, ``pop_out``, ``bring_back``, ``toggle``, ``raise_window``);
* links in the Critique bring the main window forward with the passage
  selected.

The first time, the main window goes to the left of the screen and the
Critique to the right; after that it opens where it was left
(``critique_window/geometry``, still read and written). While it is out the
tab says "Show it · Bring it back here", and choosing the tab raises the
window. ``grader_widget`` is the screen that moves; ``setCurrentWidget``
with it still shows it, wherever it is.

The "⧉ Own window" button on the Critique's top row was retired in D.4
(it replaced nothing; the menu entry and the right-click do the same).
"""

from __future__ import annotations

from typing import Any, Optional

from src.ui import screen_groups

GEOMETRY_KEY = screen_groups.CRITIQUE_GEOMETRY_KEY
OUT_KEY = screen_groups.CRITIQUE_OUT_KEY
SHARE = screen_groups.SHARE


class PopOut:
    """The Critique's handle on the one mover."""

    def __init__(self, main_window: Any, grader: Any):
        self.main_window = main_window
        self.grader = grader
        self.groups = screen_groups.ensure(main_window)
        self.unit = self.groups.screen_unit(grader) if self.groups is not None else None
        if self.unit is None:
            raise RuntimeError("the Critique is not one of the main window's tabs")

    @property
    def window(self):
        return self.unit.window

    @property
    def note(self):
        return self.unit.slot.note

    @property
    def is_out(self) -> bool:
        return self.unit.is_out

    def toggle(self) -> None:
        self.groups.toggle(self.unit)

    def pop_out(self) -> None:
        self.groups.detach(self.unit)

    def bring_back(self, from_close: bool = False) -> None:
        self.groups.bring_back(self.unit, from_close=from_close)

    def raise_window(self) -> None:
        self.unit.raise_window()

    def bring_main_forward(self) -> None:
        """A link in the Critique window opened something in Write."""
        if self.is_out:
            self.main_window.raise_()
            self.main_window.activateWindow()


# ── Call lines (rule 14) ─────────────────────────────────────────────

def install(main_window: Any) -> Optional[PopOut]:
    """Called once the Critique tab is built."""
    grader = getattr(main_window, "grader_widget", None)
    if grader is None:
        return None
    try:
        main_window.critique_popout = PopOut(main_window, grader)
    except Exception as e:                    # never break the tab
        print(f"[critique window] not available: {e}")
        return None
    issues = getattr(getattr(grader, "scorecard", None), "issues", None)
    if issues is not None:
        bring = lambda *a: main_window.critique_popout.bring_main_forward()
        issues.show_requested.connect(bring)
        issues.companion_requested.connect(bring)
        issues.expand_requested.connect(bring)
    return main_window.critique_popout


def add_to_menu(main_window: Any, menu: Any) -> None:
    """In the Critique menu, beside "Open Critique Tab"."""
    pop = getattr(main_window, "critique_popout", None)
    if pop is None:
        return
    text = "Bring the Critique Back to Its Tab" if pop.is_out else "Critique in Its Own Window"
    menu.addAction(text).triggered.connect(lambda _=False: pop.toggle())
