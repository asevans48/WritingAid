"""The next-fix queue (piece 3.2): what to fix next in a chapter.

The chapter's readiness findings, one at a time, most important first, for
the chapter's **current stage** (``chapter_stages``). A chapter at
copyedit is not offered a structure fix; a chapter with no stage set is
offered everything, structure first.

**Order.** Stage (when none is set), then a check the writer mostly turns
down after the rest (4.3), then tier (major issues, other factors,
polish), then a check at "problem" before one at "needs work", then the
check's ``weight``, then where it is in the chapter.

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
# line stage takes them from the editor's live style flags. The P.2a kinds
# (transitions, pronouns, alliteration, acronyms) and the P.2b kinds (homonyms,
# sensory detail, sentence structure, vague words) join only when ticked.
STYLE_ONLY_KINDS = ("repeated_start", "long_sentence", "hard_sentence",
                    "transition", "pronoun", "alliteration", "acronym",
                    "homonym", "sensory", "sentence_structure", "vague")
STYLE_WEIGHT = 10


def style_entries(issues: Iterable[Any],
                  only: Optional[Iterable[str]] = STYLE_ONLY_KINDS) -> List[Entry]:
    """Entries for the editor's style flags of ``STYLE_ONLY_KINDS`` (of
    every kind with ``only=None``: the retired Style tab's list, D.6);
    ``issues``: [(absolute start, StyleIssue)]."""
    from src.utils.style_checks import KINDS
    out = []
    for start, issue in issues:
        if (only is not None and issue.kind not in only) or issue.end <= issue.start:
            continue
        item = rd.Item(start=start, end=start + (issue.end - issue.start), text=issue.text[:200],
                       reason=issue.message or issue.kind, kind=issue.kind,
                       key=f"{issue.kind}:{issue.text.strip().lower()[:80]}",
                       suggestions=list(issue.suggestions or [])[:3])
        out.append(Entry(f"style:{issue.kind}", KINDS[issue.kind][0], "line", "polish", item))
    return out


def entries(chapter_report: Any, stage: str = "", intended: Iterable[str] = (),
            skipped: Sequence[str] = (), extra: Sequence[Entry] = (),
            toned: Iterable[str] = ()) -> List[Entry]:
    """The queue for one chapter: its findings for ``stage`` ("" — every
    stage), most important first; skipped ones at the back, in the order
    they were skipped. ``extra``: entries from outside the report (the
    editor's style flags, ``style_entries``). ``toned``: checks the writer
    mostly turns down (4.3, ``check_outcomes.toned_down``), after the
    others of their stage."""
    rd._load_checks()
    intended = set(intended)
    toned = set(toned)
    out: List[tuple] = []
    for e in extra:
        if not stage or e.stage == stage:
            out.append(((rd.STAGES.index(e.stage), e.check in toned, rd.TIERS.index(e.tier), 1,
                         -STYLE_WEIGHT, e.item.start), e))
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
                     name in toned,
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
    from src.ai import intentional
    item = entry.item
    if not item.key:
        return False
    return intentional.store(project, item.key, {
        "text": item.text[:200], "reason": item.reason[:300], "label": entry.label,
        "chapter": chapter_title, "at": time.strftime("%Y-%m-%d"), "as": NOT_A_PROBLEM},
        check=entry.check)


def undismiss(project: Any, key: str) -> bool:
    """Take a dismissal back; one marked intentional (4.1) takes its style
    sheet line with it."""
    from src.ai import intentional
    return intentional.unmark(project, key)[0]
