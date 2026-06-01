"""Pure-Python ordering / migration helpers for PlotEvent lists.

Lives in a Qt-free module so it can be unit-tested without spinning
up QApplication. Both ``plot_manager`` and ``plot_timeline`` import
from here.

Why this exists: pre-redesign plot data may have all events at
``sort_order=0`` (the model default). Under the new timeline view
that bunches every tie into a single, ambiguously-ordered block —
and the per-card Up/Down buttons can't swap anything meaningful
because every neighbor has the same sort_order. Normalizing once at
load time assigns sequential sort_orders per (act, stage) group
**without changing the visible order** users already see, so:

  * existing creation order is preserved (events stay in the order
    they were added);
  * Up/Down moves work correctly afterward;
  * no events are lost or reshuffled across acts/stages.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def normalize_sort_orders(events: List[Any]) -> int:
    """Assign sequential ``sort_order`` (0, 1, 2, ...) within each
    ``(act, stage)`` group, preserving each event's current visible
    order.

    Visible order is defined as: first by existing ``sort_order``
    (so deliberate ordering is respected), then by original list
    index (so events with tied sort_orders keep their creation
    order). The function mutates events in place and returns the
    number whose ``sort_order`` actually changed.

    Idempotent: running on already-normalized data is a no-op
    (returns 0). Safe to call on every load.
    """
    if not events:
        return 0
    # Group events by (act, stage), remembering each event's original
    # index so we can break ties consistently.
    groups: Dict[Tuple[int, str], List[Tuple[int, Any]]] = {}
    for idx, ev in enumerate(events):
        act = getattr(ev, "act", 1) or 1
        stage = getattr(ev, "stage", "") or ""
        groups.setdefault((act, stage), []).append((idx, ev))

    changed = 0
    for items in groups.values():
        # Stable sort: tie on sort_order falls back to original
        # index, so ties resolve by creation order.
        items.sort(key=lambda pair: (getattr(pair[1], "sort_order", 0)
                                      or 0,
                                      pair[0]))
        for new_order, (_orig_idx, ev) in enumerate(items):
            if getattr(ev, "sort_order", 0) != new_order:
                ev.sort_order = new_order
                changed += 1
    return changed
