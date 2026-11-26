"""Checks earn their place, on screen (piece 4.3).

Call lines for the next-fix card (``next_fixes.Queue``), "Fix all N like
this" (``fix_all``), the Critique's grid (``scorecard_widget``) and the
✓ Checks ▾ menu (``style_checks_menu``). The counting itself is in
``src/data/check_outcomes.py``.

What the writer sees:

* **The Critique.** Each check's column tooltip says how often its fixes
  are accepted in this project. A check the writer mostly turns down is
  drawn fainter, with the reason in the tooltip; its details below the grid
  say why, with "Bring it back".
* **The next-fix card.** A toned-down check's findings come after the
  others of their stage. Its card says so, with "bring it back". When the
  writer's Not a problem tones a check down, the status line says so and
  offers "Switch it off" (only for a check with a ✓ Checks ▾ switch, never
  spelling or overused words) — the switch changes only if the writer
  clicks it, through the same tick box as the menu.
* **✓ Checks ▾ › Style checks.** Each switch's tooltip gives the rate; a
  toned-down one says so in its name.

No new buttons: links in the lines that were already there.
"""

from __future__ import annotations

import html
from typing import Any, Optional

from src.data import check_outcomes as co

TONED_MARK = " · toned down"


def _project(queue: Any):
    return getattr(queue.cc, "project", None)


# ── The next-fix card ────────────────────────────────────────────────

def toned(queue: Any) -> set:
    """The project's toned-down checks, for the queue's order."""
    return co.toned_down(_project(queue))


def accepted(queue: Any, entry: Any) -> None:
    if entry is not None:
        co.record(_project(queue), entry.check, co.ACCEPTED)


def skipped(queue: Any, entry: Any) -> None:
    if entry is not None:
        co.record(_project(queue), entry.check, co.SKIPPED)


def before_dismiss(queue: Any, entry: Any) -> bool:
    """Whether the check was toned down before this Not a problem."""
    return entry.check in co.toned_down(_project(queue))


def dismissed(queue: Any, entry: Any, was_toned: bool, stored: bool) -> str:
    """Count a Not a problem the store did not count (a style flag's
    session ignore); returns the status line's addition when this answer
    tones the check down."""
    project = _project(queue)
    if not stored:
        co.record(project, entry.check, co.NOT_A_PROBLEM)
    o = co.outcome(project, entry.check)
    if was_toned or not o.toned_down:
        return ""
    label = html.escape(co.label_of(entry.check))
    judged = o.since_accepted + o.since_rejected
    line = (f"<br>You've turned down {o.since_rejected} of {judged} {label} fixes in this "
            "book, so it's toned down: later in this list, fainter in the Critique. ")
    if co.can_switch_off(entry.check, _ticked(queue)):
        line += f"<a href='switch-off:{entry.check}'>Switch it off</a> · "
    return line + f"<a href='bring-back:{entry.check}'>Keep it as it was</a>"


def undone(queue: Any, entry: Any) -> None:
    """Undo right after Not a problem: the answer is taken back too."""
    if entry is not None:
        co.record(_project(queue), entry.check, co.NOT_A_PROBLEM, -1)


def card_link(queue: Any, entry: Any) -> str:
    """The card's status line for a toned-down check."""
    if entry is None or entry.check not in co.toned_down(_project(queue)):
        return ""
    return f" · toned down for this book: <a href='bring-back:{entry.check}'>bring it back</a>"


def _ticked(queue: Any) -> Optional[set]:
    try:
        return set(queue.cc.ce.editor.writing_highlighter._style_kinds)
    except Exception:
        return None


def on_link(queue: Any, href: str) -> None:
    """"bring-back:<check>" or "switch-off:<check>" from the card."""
    action, _, check = href.partition(":")
    project = _project(queue)
    if not check or project is None:
        return
    label = co.label_of(check)
    if action == "bring-back":
        co.bring_back(project, check)
        message = f"{label} is back as it was. Its counts are kept."
    elif action == "switch-off":
        actions = getattr(queue.cc.ce, "_style_check_actions", None) or {}
        kinds = co.can_switch_off(check, _ticked(queue))
        for kind in kinds:                  # the ✓ Checks ▾ tick box: remembered per project
            act = actions.get(kind)
            if act is not None:
                act.setChecked(False)
        message = (f"{label} is switched off for this book. Tick it again in "
                   "✓ Checks ▾ › Style checks." if kinds else "")
        queue.extra = [e for e in queue.extra if e.item.kind not in kinds]
        queue.entries = [e for e in queue.entries if e.item.kind not in kinds]
        queue.show()
    else:
        return
    if action == "bring-back" and queue.report is not None:   # the order follows at once
        queue.set_report(queue.report, queue.stage)
    if message:
        rest = queue.card.status.text() if queue.card.fix is not None else ""
        queue.card.status.setText(html.escape(message) + (" · " + rest if rest else ""))


# ── Fix all N like this ──────────────────────────────────────────────

def fixed_everywhere(editor: Any, error: Any, n: int) -> None:
    if n > 0:
        co.record(getattr(editor, "_project", None), co.check_for_error(error),
                  co.ACCEPTED, n)


# ── The Critique ─────────────────────────────────────────────────────

def header_tip(project: Any, check: str) -> str:
    o = co.outcome(project, check)
    tip = o.rate_line()
    if o.toned_down:
        tip += "\n" + o.toned_line() + " Bring it back from its details below."
    return tip


def toned_lines(project: Any) -> dict:
    """{check: why it is toned down}, for the details below the grid."""
    return {c: co.outcome(project, c).toned_line() for c in co.toned_down(project)}


# ── ✓ Checks ▾ › Style checks ────────────────────────────────────────

def menu_tip(project: Any, kind: str) -> str:
    check = co.check_for_kind(kind)
    o = co.outcome(project, check)
    tip = o.rate_line()
    if o.toned_down:
        tip += "\n" + o.toned_line() + " Untick to switch it off."
    return tip


def menu_toned(project: Any, kind: str) -> bool:
    return co.outcome(project, co.check_for_kind(kind)).toned_down


def fade(item: Any) -> None:
    """Draw a grid cell of a toned-down check fainter: its colour half way
    to white, its text in the faint ink."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor
    from src.ui.ui_kit import PALETTE
    brush = item.background()
    if brush.style() != Qt.BrushStyle.NoBrush:     # a coloured cell: lighter still
        c = brush.color()
        item.setBackground(QColor(round(c.red() + (255 - c.red()) * 0.6),
                                  round(c.green() + (255 - c.green()) * 0.6),
                                  round(c.blue() + (255 - c.blue()) * 0.6)))
    item.setForeground(QColor(PALETTE["ink_faint"]))
