"""The reverse outline in the Critique (piece 7.1).

One line under the chapter's stage in the Critique's issue list:
"Scene outline (3 scenes) ▸". Opened, it lists each scene: where it
starts (a link that opens the chapter there), its length, how much is
dialogue and who speaks. Closed by default; open or closed is kept while
the app runs. It moves with the Critique into its own window (2.5), which
puts the outline beside the draft.

Opened, it also shows the draft beside the chapter's plan and one small
chart of the book's scenes (7.3, ``plan_section``), and, once the chapter
has been checked with the model, the model's reading under each scene:
whose point of view, what happens and what the scene is for (7.2,
``scene_reading``; stored results only, the model is never run from here).

Scenes start at the writer's scene markers too (7.4, ``scene_marks_ui``):
a ✕ after each scene a marker starts, "Use the model's scenes" and Undo.

No new widget: it is part of the issue list's page (``ChapterIssues``).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, List, Optional

from src.ui.ui_kit import PALETTE


def _e(text: Any) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _reading_html(model_scenes: List[dict]) -> str:
    """The model's scenes inside one of the outline's scenes (7.2)."""
    from src.ai import scene_reading as sr
    return "".join(f"<br><span style='color:{PALETTE['ink_soft']}'>{_e(sr.line(m))}</span>"
                   for m in model_scenes)


def _tension_html(rated: Optional[dict], index: int) -> str:
    """"Tension 4 of 5: why", from the stored ratings (7.2), or ""."""
    values = (rated or {}).get("values") or []
    if index >= len(values) or values[index] is None:
        return ""
    why = ((rated.get("why") or [""] * len(values))[index:index + 1] or [""])[0]
    return (f"<br><span style='color:{PALETTE['ink_faint']}'>Tension {int(values[index])} of 5"
            f"{': ' + _e(why) if why else ''}</span>")


def install(scorecard: Any) -> None:
    """Give the issue list the project's character names (for speakers)."""
    def names() -> List[str]:
        chars = getattr(getattr(scorecard, "project", None), "characters", None) or []
        return [getattr(c, "name", "") for c in chars if getattr(c, "name", "")]
    scorecard.issues.outline_names = names
    scorecard.issues.outline_project = lambda: getattr(scorecard, "project", None)   # 7.3
    try:                                 # the chart's tension line: stored ratings only (7.2)
        from src.ai import scene_tension
        scene_tension.install(lambda: getattr(scorecard, "project", None))
    except Exception as e:
        print(f"[outline] tension unavailable: {e}")

    def book(scope):                     # the manuscript's chapters, for the chart (7.3)
        report = getattr(scorecard, "report", None)
        if report is None or getattr(report, "scope", None) != scope:
            return []
        from src.ai.readiness import BOOK_ROW, OPENING_ROW
        return [(c.chapter_id, scorecard._chapter_text(c.chapter_id) or "")
                for c in report.chapters if c.chapter_id not in (BOOK_ROW, OPENING_ROW)]
    scorecard.issues.outline_book = book
    try:                                 # the scene markers (7.4)
        from src.ui import scene_marks_ui
        scene_marks_ui.install_outline(scorecard)
    except Exception as e:
        print(f"[outline] scene markers unavailable: {e}")


def html(issues: Any, chapter_report: Any, text: Optional[str]) -> str:
    """The outline's part of the page, or "" (no text: the Whole manuscript row)."""
    if not text or not text.strip():
        return ""
    from src.ai import reverse_outline as ro
    names_fn: Callable[[], List[str]] = getattr(issues, "outline_names", None) or (lambda: [])
    from src.ui import scene_marks_ui                                         # 7.4
    scenes = ro.outline(text, names_fn(), scene_marks_ui.offsets(issues, chapter_report, text))
    from src.ui import plan_section
    comp = plan_section.comparison(issues, chapter_report, text, scenes)   # 7.3
    is_open = bool(getattr(issues, "outline_open", False))
    count = f"{len(scenes)} scene{'s' if len(scenes) != 1 else ''}"
    head = (f"<div style='margin-top:6px; color:{PALETTE['ink_soft']}'>"
            f"<a href='{issues._link('outline', None)}'>Scene outline ({count}) "
            f"{'▾' if is_open else '▸'}</a>{_e(plan_section.summary(comp))}</div>")
    if not is_open:
        return head
    from src.ai import scene_reading as sr                                    # 7.2
    project = plan_section._project(issues)
    digest = sr.digest_entry(project, chapter_report.chapter_id, text)
    reading = sr.per_scene(digest, scenes)
    rated = sr.tension(project, chapter_report.chapter_id, text)
    marks = scene_marks_ui._resolved(issues, chapter_report, text)
    rows = []
    for index, s in enumerate(scenes):
        place = SimpleNamespace(chapter_id=chapter_report.chapter_id, text=s.opening,
                                start=s.start, end=s.start + len(s.opening))
        rows.append(f"<li style='margin-bottom:3px'><a href='{issues._link('show', place)}'>"
                    f"“{_e(s.opening)}…”</a>"
                    f"{scene_marks_ui.row_html(issues, chapter_report, text, s, marks)}<br><span style='color:{PALETTE['ink_faint']}'>"
                    f"{_e(ro.describe(s))}</span>"
                    f"{_reading_html(reading[index])}{_tension_html(rated, index)}"
                    f"{plan_section.scene_line(issues, comp, index)}</li>")
    note = ("" if len(scenes) > 1 else
            f"<div style='color:{PALETTE['ink_faint']}'>No scene breaks found: a break is a "
            "line of *** (or * * *, #) or two blank lines, or a scene marker kept beside the "
            "text (on Write, right-click a paragraph: More ▸ 📝 Note or scene break ▸ Scene break here).</div>")
    note += (f"<div style='color:{PALETTE['ink_faint']}'>What happens in each scene, whose "
             "point of view and what it is for appear here once the chapter is checked with "
             "the model.</div>" if digest is None else
             f"<div style='color:{PALETTE['ink_faint']}'>The model's reading of the chapter: "
             "one reader's view.</div>")
    if marks is not None:
        note += scene_marks_ui.after_html(issues, chapter_report, text, digest is not None, marks)
    plan = plan_section.after_html(comp) if comp is not None else plan_section.no_plan_html(issues)
    return (head + f"<ol style='margin-top:2px'>{''.join(rows)}</ol>" + note + plan
            + plan_section.chart_html(issues, chapter_report, text))
