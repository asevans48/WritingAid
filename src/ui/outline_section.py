"""The reverse outline in the Critique (piece 7.1).

One line under the chapter's stage in the Critique's issue list:
"Scene outline (3 scenes) ▸". Opened, it lists each scene: where it
starts (a link that opens the chapter there), its length, how much is
dialogue and who speaks. Closed by default; open or closed is kept while
the app runs. It moves with the Critique into its own window (2.5), which
puts the outline beside the draft.

Opened, it also shows the draft beside the chapter's plan and one small
chart of the book's scenes (7.3, ``plan_section``).

No new widget: it is part of the issue list's page (``ChapterIssues``).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, List, Optional

from src.ui.ui_kit import PALETTE


def _e(text: Any) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def install(scorecard: Any) -> None:
    """Give the issue list the project's character names (for speakers)."""
    def names() -> List[str]:
        chars = getattr(getattr(scorecard, "project", None), "characters", None) or []
        return [getattr(c, "name", "") for c in chars if getattr(c, "name", "")]
    scorecard.issues.outline_names = names
    scorecard.issues.outline_project = lambda: getattr(scorecard, "project", None)   # 7.3

    def book(scope):                     # the manuscript's chapters, for the chart (7.3)
        report = getattr(scorecard, "report", None)
        if report is None or getattr(report, "scope", None) != scope:
            return []
        from src.ai.readiness import BOOK_ROW, OPENING_ROW
        return [(c.chapter_id, scorecard._chapter_text(c.chapter_id) or "")
                for c in report.chapters if c.chapter_id not in (BOOK_ROW, OPENING_ROW)]
    scorecard.issues.outline_book = book


def html(issues: Any, chapter_report: Any, text: Optional[str]) -> str:
    """The outline's part of the page, or "" (no text: the Whole manuscript row)."""
    if not text or not text.strip():
        return ""
    from src.ai import reverse_outline as ro
    names_fn: Callable[[], List[str]] = getattr(issues, "outline_names", None) or (lambda: [])
    scenes = ro.outline(text, names_fn())
    from src.ui import plan_section
    comp = plan_section.comparison(issues, chapter_report, text, scenes)   # 7.3
    is_open = bool(getattr(issues, "outline_open", False))
    count = f"{len(scenes)} scene{'s' if len(scenes) != 1 else ''}"
    head = (f"<div style='margin-top:6px; color:{PALETTE['ink_soft']}'>"
            f"<a href='{issues._link('outline', None)}'>Scene outline ({count}) "
            f"{'▾' if is_open else '▸'}</a>{_e(plan_section.summary(comp))}</div>")
    if not is_open:
        return head
    rows = []
    for index, s in enumerate(scenes):
        place = SimpleNamespace(chapter_id=chapter_report.chapter_id, text=s.opening,
                                start=s.start, end=s.start + len(s.opening))
        rows.append(f"<li style='margin-bottom:3px'><a href='{issues._link('show', place)}'>"
                    f"“{_e(s.opening)}…”</a><br><span style='color:{PALETTE['ink_faint']}'>"
                    f"{_e(ro.describe(s))}</span>"
                    f"{plan_section.scene_line(issues, comp, index)}</li>")
    note = ("" if len(scenes) > 1 else
            f"<div style='color:{PALETTE['ink_faint']}'>No scene breaks found: a break is a "
            "line of *** (or * * *, #) or two blank lines.</div>")
    plan = plan_section.after_html(comp) if comp is not None else plan_section.no_plan_html(issues)
    return (head + f"<ol style='margin-top:2px'>{''.join(rows)}</ol>" + note + plan
            + plan_section.chart_html(issues, chapter_report, text))
