"""The draft beside the plan, in the scene outline (piece 7.3).

Part of the Critique's "Scene outline (N scenes)" section (7.1), so it
moves with the Critique into its own window. Opened, each scene shows the
planned event it holds (``plan_match``), or "Not in the plan"; planned
events with no scene are listed after the scenes; one small chart shows
every scene of the book (``outline_chart``). The match is a suggestion:
"change" beside a scene opens a short menu to pick its events, say it is
not in the plan, or go back to the suggestion. The choice is kept in the
readiness file (``plan_matches``).

No new widget or button: links on the issue list's page.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from src.ui.ui_kit import PALETTE

_chart_serial = [0]


def _e(text: Any) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _project(issues: Any) -> Any:
    fn = getattr(issues, "outline_project", None)
    try:
        return fn() if fn else None
    except Exception:
        return None


def comparison(issues: Any, chapter_report: Any, text: str, scenes) -> Optional[Any]:
    """The plan comparison for the chapter shown, or None (no project or
    no planned events)."""
    from src.ai import plan_match as pm
    project = _project(issues)
    if project is None:
        return None
    try:
        _scope, chapter = project.find_chapter_with_scope(chapter_report.chapter_id)
    except Exception:
        chapter = None
    events = pm.planned_events(chapter)
    if not events:
        return None
    from src.data import plan_matches
    fixes = plan_matches.corrections(project, getattr(chapter_report, "scope", None),
                                     chapter_report.chapter_id)
    names_fn = getattr(issues, "outline_names", None) or (lambda: [])
    return pm.compare(scenes, text, events, names_fn(), fixes)


def summary(comp: Any) -> str:
    """For the closed line: " · 1 planned event not drafted · 1 scene not in the plan"."""
    if comp is None:
        return ""
    bits = []
    if comp.missing:
        n = len(comp.missing)
        bits.append(f"{n} planned event{'s' if n != 1 else ''} not drafted")
    if comp.unplanned:
        n = len(comp.unplanned)
        bits.append(f"{n} scene{'s' if n != 1 else ''} not in the plan")
    return "".join(f" · {b}" for b in bits)


def scene_line(issues: Any, comp: Any, index: int) -> str:
    """The plan line under one scene."""
    if comp is None:
        return ""
    m = comp.scenes[index]
    change = f" · <a href='{issues._link('plan', m.key)}'>change</a>"
    if not m.event_ids:
        why = "your choice" if m.source == "yours" else "no planned event shares its words"
        return (f"<br><span style='color:{PALETTE['warning_ink']}'>Not in the plan</span>"
                f"<span style='color:{PALETTE['ink_faint']}'> ({why})</span>{change}")
    labels = "; ".join(_e(comp.event(i).label) for i in m.event_ids if comp.event(i))
    how = "yours" if m.source == "yours" else "suggested"
    return (f"<br><span style='color:{PALETTE['ink_soft']}'>Plan: {labels}</span>"
            f"<span style='color:{PALETTE['ink_faint']}'> ({how})</span>{change}")


def after_html(comp: Any) -> str:
    """Below the scenes: planned events with no scene."""
    if comp is None:
        return ""
    if not comp.missing:
        return (f"<div style='color:{PALETTE['success_ink']}'>Every planned event has a "
                "scene.</div>")
    rows = "".join(f"<li>{_e(e.label)}</li>" for e in comp.missing)
    return (f"<div style='color:{PALETTE['warning_ink']}; font-weight:bold'>Planned, not "
            f"found in the draft ({len(comp.missing)}):</div><ul style='margin-top:2px'>"
            f"{rows}</ul><div style='color:{PALETTE['ink_faint']}'>Matched by shared names "
            "and words, so check it: “change” beside a scene puts it right.</div>")


def no_plan_html(issues: Any) -> str:
    if _project(issues) is None:
        return ""
    return (f"<div style='color:{PALETTE['ink_faint']}'>No planned events for this chapter "
            "to compare with. Add them in the chapter's outline in the side panel.</div>")


# ── The chart ───────────────────────────────────────────────────────

def chart_html(issues: Any, chapter_report: Any, text: str) -> str:
    """One small chart: every scene of the manuscript (or this chapter's,
    when the book is not known)."""
    from src.ai import plan_match as pm
    from src.ui import outline_chart
    book_fn = getattr(issues, "outline_book", None)
    try:
        chapters = book_fn(getattr(chapter_report, "scope", None)) if book_fn else []
    except Exception:
        chapters = []
    if not any(cid == chapter_report.chapter_id for cid, _t in chapters):
        chapters = list(chapters) + [(chapter_report.chapter_id, text)]
    points = pm.book_pacing(chapters)
    if not points:
        return ""
    try:
        width = issues.viewport().width() - 40
    except Exception:
        width = 480
    width = max(240, min(900, width))
    ratio = 2.0
    try:
        ratio = max(1.0, float(issues.devicePixelRatioF()))
    except Exception:
        pass
    _chart_serial[0] += 1
    name = f"wa-chart:pacing-{_chart_serial[0]}"
    issues.outline_charts = {name: outline_chart.render(points, chapter_report.chapter_id,
                                                        width, ratio)}
    tension = any(p.tension is not None for p in points)
    n_ch = len({p.chapter_id for p in points})
    scope = "the book" if n_ch > 1 else "this chapter"
    if tension:
        legend = (f"<span style='color:{PALETTE['error_ink']}'>—</span> tension, from the "
                  f"model · <span style='color:{PALETTE['primary_border']}'>■</span> words per "
                  "scene")
    else:
        legend = (f"<span style='color:{PALETTE['primary']}'>■</span> words per scene"
                  + (" (this chapter in colour)" if n_ch > 1 else "")
                  + f" · <span style='color:{PALETTE['accent_ink']}'>—</span> share in "
                  "dialogue. Without a model this shows pacing, not tension.")
    return (f"<div style='margin-top:6px; color:{PALETTE['ink_soft']}'>Scenes across {scope} "
            f"({len(points)}):</div><div><img src='{name}' width='{width}' height='"
            f"{outline_chart.HEIGHT}'></div><div style='color:{PALETTE['ink_faint']}'>{legend}</div>")


def load_chart(issues: Any, name: str):
    """The chart image for ``ChapterIssues.loadResource``, or None."""
    return (getattr(issues, "outline_charts", None) or {}).get(name)


# ── Corrections ─────────────────────────────────────────────────────

def _current(issues: Any) -> Optional[Tuple[Any, Any, Any]]:
    """(chapter report, comparison, project) for the chapter shown."""
    shown = getattr(issues, "_shown", None)
    project = _project(issues)
    if not shown or project is None or not shown[2]:
        return None
    from src.ai import reverse_outline as ro
    ch, text = shown[0], shown[2]
    names_fn = getattr(issues, "outline_names", None) or (lambda: [])
    from src.ui import scene_marks_ui                                         # 7.4
    comp = comparison(issues, ch, text, ro.outline(text, names_fn(),
                                                   scene_marks_ui.offsets(issues, ch, text)))
    return (ch, comp, project) if comp is not None else None


def correct(issues: Any, scene_key: str, event_ids: Optional[List[str]]) -> bool:
    """Store the writer's choice for a scene (None: back to the
    suggestion) and redraw."""
    cur = _current(issues)
    if cur is None:
        return False
    ch, _comp, project = cur
    from src.data import plan_matches
    ok = plan_matches.set_correction(project, getattr(ch, "scope", None), ch.chapter_id,
                                     scene_key, event_ids)
    if getattr(issues, "_shown", None):
        issues.show_chapter(*issues._shown)
    return ok


def plan_menu(issues: Any, scene_key: str):
    """The menu "change" opens: each planned event (ticked when the scene
    holds it), Not in the plan, and Use the suggestion."""
    from PyQt6.QtWidgets import QMenu
    cur = _current(issues)
    if cur is None:
        return None
    _ch, comp, _project_ = cur
    m = next((s for s in comp.scenes if s.key == scene_key), None)
    if m is None:
        return None
    menu = QMenu(issues)
    held = list(m.event_ids)
    for e in comp.events:
        act = menu.addAction(e.label[:80])
        act.setCheckable(True)
        act.setChecked(e.id in held)
        act.triggered.connect(lambda _on=False, i=e.id: correct(
            issues, scene_key, [x for x in held if x != i] if i in held else held + [i]))
    menu.addSeparator()
    menu.addAction("Not in the plan").triggered.connect(
        lambda _on=False: correct(issues, scene_key, []))
    back = menu.addAction("Use the suggestion")
    back.setEnabled(m.source == "yours")
    back.triggered.connect(lambda _on=False: correct(issues, scene_key, None))
    return menu


def on_link(issues: Any, scene_key: str) -> None:
    from PyQt6.QtGui import QCursor
    menu = plan_menu(issues, scene_key)
    if menu is not None:
        menu.exec(QCursor.pos())
