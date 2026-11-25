"""Before an editor: one ordered pass, and a brief to hand over.

The aim is not to replace an editor but to make their time count: the
mechanical work is done before they start, the questions a first read
raises are already answered or listed, and they are handed what a
copyeditor would otherwise build from scratch. Three steps, in order:

1. **Clear the mechanical.** Spelling and grammar left (with the model's
   proofreading), consistency, the style sheet's rules. Work no editor
   should be paid to do.
2. **Answer the queries.** What the story read and the outline raised
   (contradictions, jumps, scenes that change nothing, point-of-view
   slips, open threads). For each: fix it, or say it's intended. An
   intended choice stops counting and goes into the brief, so the editor
   doesn't raise it again.
3. **Know the big picture.** The editorial letter.

``plan`` says where the manuscript stands on each; ``brief`` writes the
document to send with it (``Editor's brief``): the state of the
manuscript, the letter, open questions, deliberate choices, the style
sheet and the outline. No Qt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

MECHANICAL = ("spelling_grammar", "consistency", "style_sheet")
# Checks whose findings are questions for the author.
QUERIES = ("character_disconnects", "plot_jumps", "continuity", "continuity_novellas",
           "scene_purpose", "pov_slips", "reader_pull", "loose_threads", "character_threads")
QUERY_KINDS = ("character", "jump", "continuity", "scene_purpose", "pov_slip", "reader_pull",
               "loose_thread", "character_thread")


def is_query(item: Any) -> bool:
    return getattr(item, "kind", "") in QUERY_KINDS


@dataclass
class Step:
    title: str
    done: bool
    line: str                         # where it stands, in a sentence
    chapter_id: str = ""              # where to start (a scorecard row), if anywhere
    count: int = 0


@dataclass
class Plan:
    ready: bool
    title: str
    steps: List[Step] = field(default_factory=list)
    read: int = 0                     # chapters a model has read
    chapters: int = 0


def _rows(report: Any):
    from src.ai import readiness as rd
    for ch in report.chapters:
        yield ch.chapter_id, ch.results
    yield rd.BOOK_ROW, report.book_results


def open_queries(report: Any) -> List[Dict[str, Any]]:
    """Questions not yet answered: [{check, label, chapter_id, item}]."""
    from src.ai import readiness as rd
    out = []
    for row, results in _rows(report):
        for name in QUERIES:
            r = results.get(name)
            if r is None:
                continue
            for i in r.items:
                if i.verdict != "cleared" and not i.dismissed:
                    out.append({"check": name, "label": rd.REGISTRY[name].label,
                                "chapter_id": i.chapter_id or (row if row != rd.BOOK_ROW else ""),
                                "item": i})
    return out


def plan(report: Any, letter: Optional[Dict[str, Any]] = None) -> Plan:
    from src.ai import readiness as rd
    plural = lambda n, w: f"{n} {w}{'s' if n != 1 else ''}"
    left, worst, worst_n = 0, "", 0
    for row, results in _rows(report):
        n = sum(results[name].count for name in MECHANICAL
                if name in results and results[name].status in (rd.Status.NEEDS_WORK,
                                                               rd.Status.PROBLEM))
        left += n
        if n > worst_n and row != rd.BOOK_ROW:
            worst, worst_n = row, n
    queries = open_queries(report)
    read = sum(1 for ch in report.chapters if ch.judged)
    total = len(report.chapters)
    titles = {ch.chapter_id: ch.title for ch in report.chapters}
    steps = [Step(
        "Clear the mechanical", left == 0,
        "Spelling, grammar and consistency are at the level of a published book."
        if left == 0 else
        f"{plural(left, 'spelling, grammar or consistency item')} above that level"
        + (f"; most are in “{titles.get(worst, '')}”." if worst else "."),
        worst, left)]
    first = next((q["chapter_id"] for q in queries if q["chapter_id"]), "")
    if read < total:
        steps.append(Step(
            "Answer the queries", False,
            (f"The model has read {read} of {plural(total, 'chapter')}. Check the book with the "
             "model so the story is read for contradictions, jumps and open threads")
            + (f"; {plural(len(queries), 'question')} so far." if queries else "."),
            first, len(queries)))
    else:
        steps.append(Step(
            "Answer the queries", not queries,
            "Every question the read raised is answered." if not queries else
            f"{plural(len(queries), 'question')} from the read: fix each, or say it's "
            "intended. What's left goes to the editor as open questions.",
            first, len(queries)))
    if letter and not letter.get("stale"):
        n = len(letter.get("issues") or [])
        steps.append(Step("Know the big picture", True,
                          f"The editorial letter names {plural(n, 'issue')} to weigh before "
                          "paying for a developmental edit.", "", n))
    else:
        steps.append(Step("Know the big picture", False,
                          "The book has changed since the editorial letter was written."
                          if letter else "No editorial letter yet.", "", 0))
    ready = left == 0 and read == total and total > 0
    title = ("Ready for an editor" if ready else
             "Not yet read by the model" if left == 0 else
             "Mechanical work left before an editor")
    return Plan(ready, title, steps, read, total)


# ── The editor's brief ─────────────────────────────────────────────────

def intended(project: Any) -> List[Dict[str, Any]]:
    """What the author marked as intended: [{key, text, reason, label, chapter}]."""
    try:
        from src.data import readiness_state as rs
        d = rs.load(project).get("dismissed")
        return [dict(v, key=k) for k, v in d.items()           # not "not a problem" (3.3)
                if isinstance(v, dict) and v.get("as") != "not a problem"] \
            if isinstance(d, dict) else []
    except Exception:
        return []


def set_intended(project: Any, item: Any, label: str, chapter: str, on: bool = True) -> bool:
    """Mark a query as intended (or take that back). Other keys are kept."""
    from src.data import readiness_state as rs
    key = getattr(item, "key", "") if not isinstance(item, dict) else item.get("key", "")
    if not key:
        return False

    def change(data):
        d = data.get("dismissed")
        if not isinstance(d, dict):
            d = data["dismissed"] = {}
        if on:
            d[key] = {"text": item.text[:200], "reason": item.reason[:300], "label": label,
                      "chapter": chapter, "at": time.strftime("%Y-%m-%d")}
        else:
            d.pop(key, None)
    return bool(rs.update(project, change))


def brief(project: Any, scope: Optional[str], report: Any,
          texts: Optional[Dict[str, str]] = None) -> str:
    """The document to send an editor with the manuscript, as Markdown."""
    from src.ai import chapter_digest, editorial_letter, story_ledger
    from src.ai import readiness as rd
    from src.ai.readiness import Book
    book = Book(project, scope, texts)
    titles = {ch.id: chapter_digest.title_of(ch) for ch in book.chapters}
    letter = editorial_letter.stored(project, scope, texts)
    p = plan(report, letter)
    goal = report.info.get("length") if isinstance(report.info, dict) else None
    out: List[str] = [f"# Editor's brief: {report.name}", ""]
    facts = [f"{book.words():,} words in {len(book.chapters)} chapters"]
    if goal is not None:
        if getattr(goal, "genre_label", ""):
            facts.append(goal.genre_label)
        if getattr(goal, "route_label", ""):
            facts.append(goal.route_label)
    out += [" · ".join(facts) + f" · prepared {time.strftime('%d %B %Y').lstrip('0')}", "",
            "*Prepared by the author with WritingAid's checks, to save you the mechanical "
            "work and the first round of questions. It was made by software; where it and "
            "the manuscript disagree, the manuscript is right.*", "",
            "## What I'd like from this edit", "",
            "_(Author: say what kind of edit you want and what worries you most.)_", "",
            "## State of the manuscript", ""]
    for n, step in enumerate(p.steps, 1):
        out.append(f"{n}. **{step.title}:** {step.line}")
    tier = {"model": "every chapter", "mixed": f"{p.read} of {p.chapters} chapters",
            "scan": "no chapters"}.get(report.tier, "")
    out += ["", f"How it was checked: spelling, grammar and consistency rules on every "
            f"chapter; a model read {tier} for errors the rules miss, for contradictions and "
            "for structure. The rules alone miss many wrong-word and missing-word errors, "
            "and a model's read is one reader's view: neither is a guarantee.", ""]

    if letter:
        out += ["## The big picture (a model's editorial letter)", ""]
        if letter.get("stale"):
            out += ["_The manuscript has changed since this was written._", ""]
        for w in letter.get("works") or []:
            where = ", ".join(titles.get(c, c) for c in w.get("chapters") or [])
            out.append(f"- Works: {w['what']}" + (f" ({where})" if where else "") + ".")
        for n, i in enumerate(letter.get("issues") or [], 1):
            where = ", ".join(titles.get(c, c) for c in i["chapters"])
            out += ["", f"{n}. **{i['element']}: {i['issue']}.** Where: {where}. "
                    f"Effect on a reader: {i['effect']} An option: {i['option']}"]
        out.append("")

    queries = open_queries(report)
    out += ["## Open questions", ""]
    if not queries:
        out += ["None left open." if p.read == p.chapters else
                "None so far; the model has not read every chapter.", ""]
    by_chapter: Dict[str, List[Dict[str, Any]]] = {}
    for q in queries:
        by_chapter.setdefault(q["chapter_id"], []).append(q)
    for cid, group in by_chapter.items():
        out.append(f"**{titles.get(cid, 'Across the book')}**")
        for q in group[:12]:
            i = q["item"]
            quote = f"“{i.text[:140]}” — " if i.text else ""
            out.append(f"- {q['label']}: {quote}{i.reason}")
        out.append("")

    choices = intended(project)
    out += ["## Deliberate choices (please don't correct)", ""]
    try:
        from src.utils import spelling_varieties
        out.append(f"- Spelling: {spelling_varieties.describe()}.")
    except Exception:
        pass
    try:
        from src.ai.style_sheet import describe, rules
        for r in rules(project)[:40]:
            out.append("- " + describe(r.kind, r.subject, getattr(r, "replacement", "") or ""))
    except Exception:
        pass
    for c in choices[:60]:
        where = f" ({c['chapter']})" if c.get("chapter") else ""
        out.append(f"- Intended{where}: “{c.get('text', '')[:140]}” — raised as: "
                   f"{c.get('reason', '')[:200]}")
    out.append("")

    ledger = story_ledger.for_book(book)
    facts_by = story_ledger.grouped(ledger.all_facts())
    out += ["## Style sheet: characters, places, timeline", ""]
    if not facts_by:
        out += ["Not recorded yet (the model records it as it reads each chapter).", ""]
    for subject, fs in facts_by.items():
        out.append(f"**{subject}**")
        out += [f"- {f['fact']} ({f['chapter']}: “{f['quote'][:100]}”)" for f in fs]
        out.append("")
    try:
        names = [c.name for c in getattr(project, "characters", None) or [] if c.name]
        if names:
            out += ["**Names as spelled:** " + ", ".join(sorted(names)[:80]), ""]
    except Exception:
        pass

    digests = chapter_digest.for_book(book)
    out += ["## Outline, as the model read it", ""]
    outline = chapter_digest.outline(digests, 60000)
    out += [outline if outline else "Not outlined yet.", ""]
    return "\n".join(out).rstrip() + "\n"
