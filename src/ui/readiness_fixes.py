"""From a scorecard cell to the fix (piece 2.2).

Double-click a cell in the scorecard, or click **Work through these in the
Companion** above a check's findings: the chapter opens in Write, the
Companion lists that check's findings as fixes (each with the editor's own
suggestion as a quick fix, where it has one, and 💡 More options… for
rewrites), and the first one is selected in the text.

The chapter is opened through the editor's normal chapter switch (so the
chapter being left is saved as usual), and a fix is applied through the
Companion's own Accept, which goes through the editor's ``_replace_span``.
"""

from __future__ import annotations

import re
from typing import Any, List, Sequence

MAX_FIXES = 25


def _sentence(text: str, start: int, end: int):
    """(sentence start, sentence end) around ``text[start:end]``."""
    left = max(text.rfind(c, 0, start) for c in ".!?\n") + 1
    rights = [i for i in (text.find(c, end) for c in ".!?\n") if i != -1]
    right = min(rights) + 1 if rights else len(text)
    while left < start and text[left].isspace():
        left += 1
    return left, right


def fixes_from_items(label: str, items: Sequence[Any], text: str) -> List[Any]:
    """Companion ``Fix``es for readiness items in ``text`` (the chapter as it
    is now). Items whose text has changed are left out."""
    from src.ai.companion import Fix, FixOption
    out = []
    for item in items:
        if item.verdict == "cleared" or item.end <= item.start:
            continue
        start, end = item.start, item.end
        if text[start:end] != item.text[:end - start] or end > len(text):
            at = text.find(item.text)
            if at < 0:
                continue                           # changed since the check
            start, end = at, at + len(item.text)
        s0, s1 = _sentence(text, start, end)
        sentence = text[s0:s1].strip()
        options = []
        for sug in item.suggestions[:2]:
            if sug is not None and sug != item.text:
                rel = start - s0
                fixed = (text[s0:start] + sug + text[end:s1]).strip()
                if not sug:                      # a cut ("very"): no double space left
                    fixed = re.sub(r"  +", " ", re.sub(r" +([,.;:!?])", r"\1", fixed))
                if fixed and fixed != sentence and rel >= 0:
                    options.append(FixOption(fixed, "Cuts it, as the editor suggests."
                                             if not sug else "Applies the editor's suggestion.",
                                             by_ai=False))
        short = item.text if len(item.text) <= 40 else item.text[:39] + "…"
        out.append(Fix(f"{label}: “{short}” — {item.reason[:90]}", item.note or "",
                       excerpt=text[start:end], paragraph=text.count("\n", 0, start),
                       sentence=sentence, kind=item.kind or "readiness", options=options))
        if len(out) >= MAX_FIXES:
            break
    return out


def open_in_companion(main_window, chapter_id: str, label: str, items: Sequence[Any]) -> bool:
    """Open the chapter with these findings in the Companion, the first
    selected. Kept for callers; the work is the revision controller's (R.5)."""
    from src.ui.revision_controller import RevisionController
    return RevisionController(main_window).open_fixes(chapter_id, label, items)
