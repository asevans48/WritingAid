"""Critique history — progress across revisions.

Every critique run is snapshotted (per chapter: major / minor findings
per report, numeric metrics, and the instant style-check counts). The
next run of the same scope is compared with the previous one: issues
fixed, issues new, counts and metric trends — so a revision pass shows
what it actually improved.

Stored as JSON next to the project file (``critique_history.json``), or
under ``~/.creativeos/critique_history/`` for unsaved projects.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_RUNS_PER_SCOPE = 20
_STOP = set("""the a an and or but of to in on at by for with from as is was were be been are it
its this that these those not no so than then into about over chapter""".split())

# Metrics worth trending, with which direction is better.
TRACKED_METRICS = {
    "adverb_pct": ("Adverbs %", "down"), "passive_pct": ("Passive %", "down"),
    "sticky_sentence_pct": ("Sticky sentences %", "down"), "cliche_count": ("Clichés", "down"),
    "echo_count": ("Echoes", "down"), "flesch_reading_ease": ("Reading ease", "up"),
    "flesch_grade_level": ("Grade level", "down"), "readability_grade": ("Grade level", "down"),
    "grammar_issue_count": ("Grammar issues", "down"), "misspelled_count": ("Misspellings", "down"),
    "hard_paragraph_count": ("Hard-to-read paragraphs", "down"),
    "long_sentence_pct": ("Long sentences %", "down"), "variety_score": ("Sentence variety", "up"),
    "bookism_tag_count": ("Said-bookisms", "down"), "tag_adverbs": ("Adverb dialogue tags", "down"),
    "planned_missing": ("Planned characters missing", "down"),
    "new_element_candidates": ("Unrecorded world elements", "down"),
}


def history_path(project: Any) -> Path:
    pp = getattr(project, "project_path", "") or ""
    if pp:
        return Path(pp).parent / "critique_history.json"
    name = re.sub(r"[^\w-]+", "_", getattr(project, "name", "") or "untitled")
    return Path.home() / ".creativeos" / "critique_history" / f"{name}.json"


def _titles(report: Any) -> List[str]:
    return [c.chapter_title for c in getattr(report, "chapters", []) or []]


def scope_key(report: Any) -> str:
    """History bucket for a run. Novella ids are stable, so renaming one
    keeps its history, and "Chapter 1" of two novellas stay separate."""
    kind = getattr(report, "run_kind", None)
    scope_id = getattr(report, "scope_id", None)
    if kind:
        return f"{kind}:{scope_id or 'main'}"
    label = getattr(report, "scope_label", "") or ""
    if kind is None and label:         # a report from before run_kind
        return f"scope:{label}"
    prefix = f"chapter@{scope_id}:" if scope_id else "chapter:"
    return prefix + "|".join(_titles(report))


def _earlier_keys(project: Any, report: Any, data: Dict[str, Any]) -> List[str]:
    """Where this run's history may be stored under an older key."""
    titles = _titles(report)
    bare = "chapter:" + "|".join(titles)
    kind = getattr(report, "run_kind", None)
    scope_id = getattr(report, "scope_id", None)
    get_main = getattr(project, "get_main_manuscript", None)
    main_chapters = get_main().chapters if get_main else []
    main_titles = {c.title for c in main_chapters}
    still_main = bool(set(titles) & main_titles)
    keys: List[str] = []
    if kind:
        keys.append(f"scope:{getattr(report, 'scope_label', '') or ''}")
    if not scope_id:
        return keys + ([bare] if kind else [])
    if not still_main:
        keys.append(bare)              # recorded before novellas had keys, or moved
    if kind and not main_chapters:     # the main manuscript was moved into this novella
        main_key = f"{kind}:main"
        previous = (data.get(main_key) or [{}])[-1].get("chapters", {})
        if set(titles) & set(previous):
            keys.append(main_key)
    return keys


def snapshot(report: Any) -> Dict[str, Any]:
    style = getattr(report, "style_stats", None) or {}
    chapters = {}
    for ch in getattr(report, "chapters", []) or []:
        reports = {}
        for s in ch.sections:
            metrics = {k: v for k, v in (s.metrics or {}).items()
                       if isinstance(v, (int, float)) and not isinstance(v, bool)}
            reports[s.report_type.value] = {
                "major": list(s.major_issues or []), "minor": list(s.minor_issues or []),
                "metrics": metrics}
        chapters[ch.chapter_title] = {"words": ch.word_count, "reports": reports,
                                      "style": style.get(ch.chapter_title)}
    return {"timestamp": datetime.now().isoformat(timespec="seconds"),
            "scope_label": getattr(report, "scope_label", "") or "",
            "has_llm": bool(getattr(report, "has_llm", False)), "chapters": chapters}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z']+", (text or "").lower())
            if len(w) > 2 and w not in _STOP}


def _same_issue(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return a.strip().lower() == b.strip().lower()
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def _diff(prev: List[str], cur: List[str]):
    fixed = [p for p in prev if not any(_same_issue(p, c) for c in cur)]
    new = [c for c in cur if not any(_same_issue(c, p) for p in prev)]
    return fixed, new


def compare(prev: Dict[str, Any], cur: Dict[str, Any]) -> Dict[str, Any]:
    out = {"since": prev.get("timestamp", ""), "chapters": [], "added": [], "removed": []}
    pch, cch = prev.get("chapters", {}), cur.get("chapters", {})
    out["added"] = [t for t in cch if t not in pch]
    out["removed"] = [t for t in pch if t not in cch]
    for title in (t for t in cch if t in pch):
        p, c = pch[title], cch[title]
        entry = {"title": title, "majors": [0, 0], "minors": [0, 0], "fixed": [], "new": [],
                 "style": None, "metrics": []}
        for rt, cr in c["reports"].items():
            pr = p["reports"].get(rt)
            entry["majors"][1] += len(cr["major"])
            entry["minors"][1] += len(cr["minor"])
            if pr is None:
                continue
            entry["majors"][0] += len(pr["major"])
            entry["minors"][0] += len(pr["minor"])
            fixed, new = _diff(pr["major"], cr["major"])
            entry["fixed"] += [(rt, f) for f in fixed]
            entry["new"] += [(rt, n) for n in new]
            for key, (label, better) in TRACKED_METRICS.items():
                a, b = pr["metrics"].get(key), cr["metrics"].get(key)
                if a is None or b is None or a == b:
                    continue
                if abs(b - a) < max(0.5, abs(a) * 0.05):
                    continue
                improved = (b < a) if better == "down" else (b > a)
                entry["metrics"].append((label, a, b, improved))
        ps, cs = p.get("style"), c.get("style")
        if ps and cs:
            entry["style"] = (ps.get("total", 0), cs.get("total", 0),
                              ps.get("per_1000", 0), cs.get("per_1000", 0))
        out["chapters"].append(entry)
    return out


def load(project: Any) -> Dict[str, List[Dict[str, Any]]]:
    path = history_path(project)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def record(project: Any, report: Any) -> Optional[Dict[str, Any]]:
    """Save this run; return the comparison with the previous run of the
    same scope (None on the first run)."""
    data = load(project)
    key = scope_key(report)
    if key not in data:
        for earlier in _earlier_keys(project, report, data):
            if earlier in data:
                data[key] = data.pop(earlier)
                break
    runs = data.setdefault(key, [])
    cur = snapshot(report)
    progress = compare(runs[-1], cur) if runs else None
    if progress is not None:
        progress["trend"] = trend(runs + [cur])
    runs.append(cur)
    del runs[:-MAX_RUNS_PER_SCOPE]
    path = history_path(project)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except Exception as e:
        print(f"[critique-history] could not save: {e}")
    return progress


def trend(runs: List[Dict[str, Any]], last: int = 6) -> List[Dict[str, Any]]:
    rows = []
    for r in runs[-last:]:
        majors = sum(len(x["major"]) for ch in r["chapters"].values() for x in ch["reports"].values())
        minors = sum(len(x["minor"]) for ch in r["chapters"].values() for x in ch["reports"].values())
        style_total = sum((ch.get("style") or {}).get("total", 0) for ch in r["chapters"].values())
        words = sum(ch.get("words", 0) for ch in r["chapters"].values())
        rows.append({"timestamp": r["timestamp"], "majors": majors, "minors": minors,
                     "style": style_total,
                     "style_per_1000": round(1000 * style_total / words, 1) if words else 0})
    return rows


def _arrow(a, b, better="down") -> str:
    if a == b:
        return "→"
    good = (b < a) if better == "down" else (b > a)
    return ("▼" if b < a else "▲") + ("✓" if good else "")


def format_progress_markdown(progress: Optional[Dict[str, Any]], max_items: int = 4) -> str:
    """Markdown block describing progress since the previous critique."""
    if not progress:
        return ""
    when = progress.get("since", "").replace("T", " ")[:16]
    lines = [f"**Progress since the last critique** ({when})", ""]
    for e in progress.get("chapters", []):
        bits = [f"major issues {e['majors'][0]} → {e['majors'][1]} {_arrow(*e['majors'])}",
                f"minor {e['minors'][0]} → {e['minors'][1]} {_arrow(*e['minors'])}"]
        if e.get("style"):
            a, b, pa, pb = e["style"]
            bits.append(f"style issues {a} → {b} {_arrow(a, b)} ({pa} → {pb} per 1,000 words)")
        lines.append(f"- **{e['title']}:** " + " · ".join(bits))
        for rt, f in e["fixed"][:max_items]:
            lines.append(f"    - ✓ fixed ({rt}): {f[:160]}")
        for rt, n in e["new"][:max_items]:
            lines.append(f"    - ＋ new ({rt}): {n[:160]}")
        for label, a, b, improved in e["metrics"][:6]:
            lines.append(f"    - {label}: {a:g} → {b:g} {'✓' if improved else '⚠️'}")
    if progress.get("added"):
        lines.append("- New in this run: " + ", ".join(progress["added"]))
    if progress.get("removed"):
        lines.append("- No longer included: " + ", ".join(progress["removed"]))
    rows = progress.get("trend") or []
    if len(rows) >= 2:
        lines += ["", "**History** (major / minor / style issues per 1,000 words):"]
        for r in rows:
            lines.append(f"- {r['timestamp'].replace('T', ' ')[:16]}: {r['majors']} / "
                         f"{r['minors']} / {r['style_per_1000']}")
    return "\n".join(lines)
