"""The next-fix queue (piece 3.2): what to fix next in a chapter.

The chapter's readiness findings, one at a time, most important first, for
the chapter's **current stage** (``chapter_stages``). A chapter at
copyedit is not offered a structure fix; a chapter with no stage set is
offered everything, structure first.

**Order.** Stage (when none is set), then tier (major issues, other
factors, polish), then a check at "problem" before one at "needs work",
then the check's ``weight``, then where it is in the chapter.

**Left out:** findings the model cleared, findings with no place in the
text, and findings about other chapters. What the writer dismissed or said
is intended is already gone from the report.

**Skip** moves a finding to the back of the queue for this session.
**Not a problem** (3.3) dismisses its *pattern* (the item's key: the word,
the rule) in this project: stored in the readiness file's ``"dismissed"``,
which every report applies, in every chapter, after a restart. It is
marked ``"as": "not a problem"``, so it stays out of the editor's brief
(which lists what the writer said is *intended*). The Critique lists it
with the others, with "take that back".

No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.ai import readiness as rd


@dataclass
class Entry:
    check: str             # the check's name
    label: str             # the check's label
    stage: str
    tier: str
    item: Any              # readiness.Item

    @property
    def key(self) -> str:
        return f"{self.check}:{self.item.key or self.item.text}:{self.item.start}"


# The Style tab's kinds that no readiness check reports (D.3): the queue's
# line stage takes them from the editor's live style flags.
STYLE_ONLY_KINDS = ("repeated_start", "long_sentence", "hard_sentence")
STYLE_WEIGHT = 10


def style_entries(issues: Iterable[Any]) -> List[Entry]:
    """Entries for the editor's style flags of ``STYLE_ONLY_KINDS``;
    ``issues``: [(absolute start, StyleIssue)]."""
    from src.utils.style_checks import KINDS
    out = []
    for start, issue in issues:
        if issue.kind not in STYLE_ONLY_KINDS or issue.end <= issue.start:
            continue
        item = rd.Item(start=start, end=start + (issue.end - issue.start), text=issue.text[:200],
                       reason=issue.message or issue.kind, kind=issue.kind,
                       key=f"{issue.kind}:{issue.text.strip().lower()[:80]}",
                       suggestions=list(issue.suggestions or [])[:3])
        out.append(Entry(f"style:{issue.kind}", KINDS[issue.kind][0], "line", "polish", item))
    return out


def entries(chapter_report: Any, stage: str = "", intended: Iterable[str] = (),
            skipped: Sequence[str] = (), extra: Sequence[Entry] = ()) -> List[Entry]:
    """The queue for one chapter: its findings for ``stage`` ("" — every
    stage), most important first; skipped ones at the back, in the order
    they were skipped. ``extra``: entries from outside the report (the
    editor's style flags, ``style_entries``)."""
    rd._load_checks()
    intended = set(intended)
    out: List[tuple] = []
    for e in extra:
        if not stage or e.stage == stage:
            out.append(((rd.STAGES.index(e.stage), rd.TIERS.index(e.tier), 1, -STYLE_WEIGHT,
                         e.item.start), e))
    for name, result in (getattr(chapter_report, "results", None) or {}).items():
        spec = rd.REGISTRY.get(name)
        if spec is None or (stage and spec.stage != stage):
            continue
        if result.status not in (rd.Status.NEEDS_WORK, rd.Status.PROBLEM):
            continue
        for item in result.items:
            if item.verdict == "cleared" or item.end <= item.start \
                    or getattr(item, "dismissed", False):
                continue
            if item.chapter_id and item.chapter_id != chapter_report.chapter_id:
                continue
            if f"{name}:{item.key}" in intended or item.key in intended:
                continue
            order = (rd.STAGES.index(spec.stage) if spec.stage in rd.STAGES else 9,
                     rd.TIERS.index(spec.tier) if spec.tier in rd.TIERS else 9,
                     0 if result.status == rd.Status.PROBLEM else 1,
                     -spec.weight, item.start)
            out.append((order, Entry(name, spec.label, spec.stage, spec.tier, item)))
    out.sort(key=lambda pair: pair[0])
    queue = [e for _, e in out]
    if skipped:
        rank = {k: n for n, k in enumerate(skipped)}
        queue.sort(key=lambda e: (e.key in rank, rank.get(e.key, 0)))
    return queue


def counts(queue: Sequence[Entry]) -> Dict[str, int]:
    """How many per stage (for the header)."""
    out: Dict[str, int] = {}
    for e in queue:
        out[e.stage] = out.get(e.stage, 0) + 1
    return out


# ── Not a problem (3.3) ──────────────────────────────────────────────

NOT_A_PROBLEM = "not a problem"


def dismiss(project: Any, entry: Entry, chapter_title: str = "") -> bool:
    """Stop this pattern being raised again in this project."""
    import time
    from src.data import readiness_state as rs
    item = entry.item
    if not item.key:
        return False

    def change(data):
        d = data.get("dismissed")
        if not isinstance(d, dict):
            d = data["dismissed"] = {}
        d[item.key] = {"text": item.text[:200], "reason": item.reason[:300],
                       "label": entry.label, "chapter": chapter_title,
                       "at": time.strftime("%Y-%m-%d"), "as": NOT_A_PROBLEM}
    return bool(rs.update(project, change))


def undismiss(project: Any, key: str) -> bool:
    from src.data import readiness_state as rs

    def change(data):
        d = data.get("dismissed")
        if isinstance(d, dict):
            d.pop(key, None)
    return bool(rs.update(project, change))
