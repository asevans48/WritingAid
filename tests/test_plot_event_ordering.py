"""Tests for normalize_sort_orders — the backward-compat migration
that runs on plot data load. Pure-Python, no Qt.

Run:
    python -m tests.test_plot_event_ordering
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.project import PlotEvent  # noqa: E402
from src.ui.plot.plot_event_ordering import normalize_sort_orders  # noqa: E402


def _ev(eid: str, act: int = 1, stage: str = "rising_action",
        sort_order: int = 0, title: str = "") -> PlotEvent:
    return PlotEvent(
        id=eid, title=title or eid, act=act,
        stage=stage, sort_order=sort_order)


def test_normalize_assigns_sequential_within_act_stage_group() -> None:
    """The whole point: events all at sort_order=0 within the same
    (act, stage) get sequential 0, 1, 2 in their original order."""
    events = [
        _ev("a"), _ev("b"), _ev("c"),  # all act=1, rising_action, 0
    ]
    changed = normalize_sort_orders(events)
    assert changed == 2  # 'a' was already 0, 'b' and 'c' changed
    assert [e.sort_order for e in events] == [0, 1, 2]
    # Original list order is preserved (no reordering of the list)
    assert [e.id for e in events] == ["a", "b", "c"]


def test_normalize_preserves_creation_order_on_ties() -> None:
    """Pre-redesign data has every event at sort_order=0. After
    migration, events keep their original list order — no shuffling."""
    events = [_ev(eid) for eid in
              ("opening", "trial", "twist", "midpoint", "fall")]
    normalize_sort_orders(events)
    assert [e.id for e in events] == [
        "opening", "trial", "twist", "midpoint", "fall"]
    assert [e.sort_order for e in events] == [0, 1, 2, 3, 4]


def test_normalize_respects_existing_explicit_ordering() -> None:
    """When some events have meaningful sort_orders, those win over
    insertion-order tie-breaking."""
    events = [
        _ev("a", sort_order=5),
        _ev("b", sort_order=0),
        _ev("c", sort_order=2),
    ]
    normalize_sort_orders(events)
    # New ordering: b (was 0) -> 0, c (was 2) -> 1, a (was 5) -> 2
    by_id = {e.id: e.sort_order for e in events}
    assert by_id == {"b": 0, "c": 1, "a": 2}


def test_normalize_buckets_by_act_and_stage_independently() -> None:
    """Events in different (act, stage) groups have independent
    sort_order sequences — Act I rising_action restarts at 0
    independently of Act I exposition."""
    events = [
        _ev("a", act=1, stage="exposition"),
        _ev("b", act=1, stage="exposition"),
        _ev("c", act=1, stage="rising_action"),
        _ev("d", act=1, stage="rising_action"),
        _ev("e", act=2, stage="exposition"),
        _ev("f", act=2, stage="climax"),
    ]
    normalize_sort_orders(events)
    by_id = {e.id: e.sort_order for e in events}
    # Each (act, stage) group restarts at 0
    assert by_id == {"a": 0, "b": 1, "c": 0, "d": 1, "e": 0, "f": 0}


def test_normalize_is_idempotent() -> None:
    """Running migration twice produces zero changes the second time."""
    events = [_ev(eid) for eid in ("a", "b", "c", "d")]
    first = normalize_sort_orders(events)
    second = normalize_sort_orders(events)
    assert first > 0
    assert second == 0


def test_normalize_handles_empty_input() -> None:
    assert normalize_sort_orders([]) == 0


def test_normalize_does_not_lose_events() -> None:
    """The migration must never drop an event — the load-bearing
    backward-compat guarantee. Counts the events before and after."""
    events = [_ev(f"e{i}", act=(i % 3) + 1,
                  stage=["exposition", "rising_action", "climax"][i % 3])
              for i in range(30)]
    before_ids = {e.id for e in events}
    normalize_sort_orders(events)
    after_ids = {e.id for e in events}
    assert before_ids == after_ids
    assert len(events) == 30


def test_normalize_does_not_change_act_or_stage() -> None:
    """The migration touches sort_order only — act and stage are
    untouched, so events stay in the correct bucket."""
    events = [
        _ev("a", act=1, stage="exposition"),
        _ev("b", act=2, stage="climax"),
        _ev("c", act=3, stage="resolution"),
    ]
    before = [(e.id, e.act, e.stage) for e in events]
    normalize_sort_orders(events)
    after = [(e.id, e.act, e.stage) for e in events]
    assert before == after


def test_normalize_handles_missing_act_default() -> None:
    """Defensive: if an event somehow has act=None (legacy data), the
    helper treats it as act=1 rather than crashing."""
    e = _ev("legacy")
    e.act = None  # type: ignore[assignment]
    # Should not raise
    normalize_sort_orders([e])


def _run_all() -> int:
    tests = [
        test_normalize_assigns_sequential_within_act_stage_group,
        test_normalize_preserves_creation_order_on_ties,
        test_normalize_respects_existing_explicit_ordering,
        test_normalize_buckets_by_act_and_stage_independently,
        test_normalize_is_idempotent,
        test_normalize_handles_empty_input,
        test_normalize_does_not_lose_events,
        test_normalize_does_not_change_act_or_stage,
        test_normalize_handles_missing_act_default,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL {t.__name__}")
            traceback.print_exc()
    print()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
