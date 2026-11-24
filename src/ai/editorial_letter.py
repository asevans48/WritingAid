"""The editorial letter (piece 8.2): a manuscript evaluation of the whole book.

A short letter naming the three to five most important issues, biggest
first, each with where it shows, its effect on a reader and one option;
what the book does well; and what the letter could not judge. One per
manuscript, so a novella gets its own.

* **With a model**, it is written from the book's reverse outline
  (``chapter_digest``) and the scorecard's findings, not from the full
  text, so it fits any model. Every issue must name chapters that exist;
  one that names none is dropped.
* **Without a model** (or before the chapters are outlined), it is
  assembled from the scorecard's worst results in the same layout.

It follows the rules every Critique report follows (``editorial_standards``:
passage, effect, option; questions where the author may have meant it) and
covers the elements of a manuscript evaluation. It is one reader's view and
says so, with what it couldn't judge. Sources: ``docs/publishing/
background.md``. Stored in ``readiness.json`` under ``"letter"``. No Qt.
"""

from __future__ import annotations

import html
import re
import time
from typing import Any, Callable, Dict, List, Optional

KEY = "letter"
# The headings: what Editors Canada's definition of a manuscript evaluation
# lists for fiction (characterization, dialogue, setting, plot, structure,
# believability; voice and tone among what it "can also involve"), with
# point of view from CIEP's description of a manuscript critique.
ELEMENTS = ("Plot", "Structure", "Characterisation", "Dialogue", "Setting", "Believability",
            "Point of view", "Voice and tone")
MAX_ISSUES = 5

# Which element of the evaluation each check speaks to.
CHECK_ELEMENT = {
    "plot_jumps": "Plot", "loose_threads": "Plot", "subplots": "Plot",
    "promises": "Plot", "first_plot_event": "Plot",
    "continuity": "Believability", "continuity_novellas": "Believability",
    "pacing": "Structure", "scene_purpose": "Structure", "reader_pull": "Structure",
    "first_action": "Structure", "backstory": "Structure", "hook": "Structure",
    "character_disconnects": "Characterisation", "character_threads": "Characterisation",
    "dialogue_fit": "Dialogue", "dialogue_problems": "Dialogue",
    "pov_slips": "Point of view",
}

ALWAYS_CANNOT = (
    "It was written from an outline of each chapter and the checks' findings, not from "
    "the full text, so the prose itself (voice and tone sentence by sentence, the quality "
    "of description) is not judged here.",
    "Judgements across the whole book (what is never paid off, what contradicts something "
    "far back) are the least reliable part: models miss key events and misstate what "
    "characters know, more so in invented worlds. Check each against the chapters it names.",
    "Finding nothing is not the same as nothing to find: models often miss a story's "
    "biggest problem.",
    "It cannot tell whether an agent or publisher will take the book, or how it will sell, "
    "or where a real reader will stop.",
    "It is one reader's view. Where it disagrees with what you intend, your intention wins.",
)

SYSTEM = ("You are a developmental editor writing a manuscript evaluation for the author "
          "of a novel. You work only from the outline and findings you are given, you say "
          "nothing you cannot tie to a chapter, and you never judge the writer.")


def findings(report: Any) -> List[Dict[str, Any]]:
    """What the scorecard found, one entry per check that needs work:
    the biggest picture first."""
    from src.ai import readiness as rd
    out: Dict[str, Dict[str, Any]] = {}

    def add(name: str, result: Any, chapter_id: Optional[str]):
        spec = rd.REGISTRY.get(name)
        if spec is None or result.status not in (rd.Status.NEEDS_WORK, rd.Status.PROBLEM):
            return
        if name not in CHECK_ELEMENT:
            return                               # line and copyedit polish: not a letter's business
        e = out.setdefault(name, {"check": name, "label": spec.label, "tier": spec.tier,
                                  "element": CHECK_ELEMENT[name], "chapters": [],
                                  "problems": 0, "total": 0, "examples": [],
                                  "about": spec.description.split(". ")[0].rstrip(".")})
        e["total"] += max(result.count, 1)
        e["problems"] += result.status == rd.Status.PROBLEM
        live = [i for i in result.items if i.verdict != "cleared" and not i.dismissed]
        for item in live[:2]:
            cid = item.chapter_id or chapter_id
            if cid and cid not in e["chapters"]:
                e["chapters"].append(cid)
            if len(e["examples"]) < 2 and (item.text or item.reason):
                e["examples"].append({"chapter": cid, "text": item.text[:120],
                                      "reason": item.reason[:200]})
        if chapter_id and chapter_id not in e["chapters"]:
            e["chapters"].append(chapter_id)
    for ch in report.chapters:
        for name, result in ch.results.items():
            add(name, result, ch.chapter_id)
    for name, result in list(report.book_results.items()) + list(report.opening_results.items()):
        add(name, result, None)
    order = {t: i for i, t in enumerate(rd.TIERS)}
    return sorted(out.values(), key=lambda e: (order.get(e["tier"], 9), -e["problems"],
                                               -len(e["chapters"]), -e["total"]))


def assemble(report: Any, note: str = "") -> Dict[str, Any]:
    """The letter without a model: the scorecard's worst results, in the
    letter's layout."""
    issues = []
    for f in findings(report)[:MAX_ISSUES]:
        example = f["examples"][0] if f["examples"] else None
        n = len(f["chapters"])
        issues.append({
            "element": f["element"],
            "issue": f"{f['label']}: {f['total']} found"
                     + (f" in {n} chapter{'s' if n != 1 else ''}" if n else ""),
            "chapters": f["chapters"][:8],
            "effect": f["about"] + ".",
            "option": (example["reason"] if example and example["reason"]
                       else "Open the scorecard cell to see each one."),
        })
    return {"made_at": time.strftime("%Y-%m-%d"), "model": "", "from_scan": True,
            "works": [], "issues": issues, "cannot": [], "note": note}


def build_prompt(outline: str, found: List[Dict[str, Any]], titles: Dict[str, str],
                 route: str = "", genre: str = "") -> str:
    lines = []
    for f in found[:14]:
        where = "; ".join(titles.get(c, "") for c in f["chapters"][:6] if titles.get(c))
        example = ""
        if f["examples"]:
            x = f["examples"][0]
            example = f" For example: “{x['text'][:80]}” — {x['reason'][:120]}"
        lines.append(f"- {f['label']} ({f['element']}): {f['total']}"
                     + (f" in {where}." if where else ".") + example)
    aim = (f"The author is writing {genre or 'a novel'}"
           + (", to send to agents." if route == "agent" else
              ", to publish themselves." if route == "self" else "."))
    return (
        f"{aim}\n\nTHE BOOK'S OUTLINE, chapter by chapter ([point of view] what happens → "
        f"what it changes):\n{outline}\n\n"
        "WHAT THE CHECKS FOUND:\n" + ("\n".join(lines) or "- nothing that needs work") + "\n\n"
        "Write the manuscript evaluation as these lines only.\n"
        "Two or three, for what the book does well:\n"
        "WORKS | what works, under 25 words | the chapter that shows it best\n"
        f"Three to {MAX_ISSUES}, the most important first, the big picture (plot, structure, "
        "character) before smaller things. Group related findings into one issue:\n"
        "ISSUE | one of " + ", ".join(ELEMENTS) + " | the issue, under 30 words | the "
        "chapters that show it, by their exact titles, separated by ; | its effect on a "
        "reader, under 25 words | one option for the author, under 30 words\n"
        "One or two, for what you could not judge from an outline:\n"
        "CANNOT | what, under 20 words")


def _chapters(field: str, titles: Dict[str, str]) -> List[str]:
    by_title = {t.strip().lower(): cid for cid, t in titles.items() if t}
    out = []
    for part in re.split(r"[;,]| and ", field):
        cid = by_title.get(part.strip().strip('"“”.').lower())
        if cid and cid not in out:
            out.append(cid)
    return out


def parse(reply: str, titles: Dict[str, str]) -> Dict[str, Any]:
    works, issues, cannot = [], [], []
    for m in re.finditer(r"^\W*(WORKS|ISSUE|CANNOT)\W*\|(.+)$", reply or "", re.I | re.M):
        kind = m.group(1).upper()
        f = [x.strip().strip("*_ ") for x in m.group(2).split("|")]
        if kind == "WORKS" and f[0]:
            works.append({"what": f[0].rstrip("."),
                          "chapters": _chapters(f[1], titles) if len(f) > 1 else []})
        elif kind == "CANNOT" and f[0]:
            cannot.append(f[0].rstrip(".") + ".")
        elif kind == "ISSUE" and len(f) >= 5:
            element = next((e for e in ELEMENTS if e.lower() == f[0].lower()
                            or e.lower().startswith(f[0].lower()[:5])), None)
            chapters = _chapters(f[2], titles)
            if element is None or not chapters or not f[1]:
                continue                         # nothing it can point to: not said
            issues.append({"element": element, "issue": f[1].rstrip("."),
                           "chapters": chapters, "effect": f[3].rstrip(".") + ".",
                           "option": f[4].rstrip(".") + "."})
    return {"works": works[:3], "issues": issues[:MAX_ISSUES], "cannot": cannot[:3]}


def write(llm: Any, project: Any, scope: Optional[str], report: Any,
          texts: Optional[Dict[str, str]] = None, save: bool = True) -> Dict[str, Any]:
    """The letter for one manuscript. With no model, or no chapter outlined
    yet, it is assembled from the scorecard."""
    from src.ai import chapter_digest
    from src.ai.readiness import Book
    book = Book(project, scope, texts)
    digests = chapter_digest.for_book(book)
    titles = {ch.id: chapter_digest.title_of(ch) for ch in book.chapters}
    outlined = len(digests.current())
    if llm is None or not outlined:
        letter = assemble(report, "No model is set up, so this letter is assembled from the "
                          "scorecard." if llm is None else
                          "The chapters haven't been outlined yet (Check the book with the "
                          "model), so this letter is assembled from the scorecard.")
    else:
        goal = report.info.get("length") if isinstance(report.info, dict) else None
        compact = False
        try:
            from src.ai.chapter_analysis_agent import is_local_llm
            compact = bool(is_local_llm(llm))
        except Exception:
            pass
        from src.ai.editorial_standards import with_standards
        prompt = build_prompt(chapter_digest.outline(digests, 9000 if compact else 24000),
                              findings(report), titles, getattr(goal, "route", ""),
                              getattr(goal, "genre", ""))
        reply = llm.generate_text(prompt, with_standards(SYSTEM, compact),
                                  max_tokens=1100, temperature=0.3) or ""
        if reply.startswith("Error generating text:"):
            raise RuntimeError(reply.split(":", 1)[1].strip())
        try:
            from src.ai.output_sanitizer import strip_meta_tokens
            reply = strip_meta_tokens(reply)
        except Exception:
            pass
        parsed = parse(reply, titles)
        if not parsed["issues"] and not parsed["works"]:
            raise RuntimeError("the model's letter couldn't be read")
        letter = dict(parsed, made_at=time.strftime("%Y-%m-%d"),
                      model=str(getattr(llm, "model", "") or "model"), from_scan=False,
                      note="" if outlined == len(book.chapters) else
                      f"Written from {outlined} of {len(book.chapters)} chapters: the others "
                      "haven't been outlined since they changed.")
    letter["book_hash"] = book.hash
    if save:
        try:
            from src.data import readiness_state as rs

            def change(data):                     # every other key is kept
                store = data.get(KEY)
                if not isinstance(store, dict):
                    store = data[KEY] = {}
                store[rs.scope_key(scope)] = letter
            rs.update(project, change)
        except Exception as e:
            print(f"[letter] not saved: {e}")
    return letter


def stored(project: Any, scope: Optional[str] = None,
           texts: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """The last letter, with ``"stale"`` set when the book has changed since."""
    try:
        from src.ai.readiness import Book
        from src.data import readiness_state as rs
        letter = (rs.load(project).get(KEY) or {}).get(rs.scope_key(scope))
        if not isinstance(letter, dict):
            return None
        return dict(letter, stale=letter.get("book_hash") != Book(project, scope, texts).hash)
    except Exception:
        return None


def to_html(letter: Dict[str, Any], titles: Dict[str, str],
            link: Callable[[str], str], palette: Dict[str, str]) -> str:
    """The letter for the scorecard's panel. ``link(chapter_id)`` gives an href."""
    e = html.escape
    faint, soft, ink = palette["ink_faint"], palette["ink_soft"], palette["ink"]

    def where(ids):
        return ", ".join(f"<a href='{link(c)}'>{e(titles.get(c, c))}</a>" for c in ids)
    by = (f"written by {e(letter.get('model') or 'the model')}" if not letter.get("from_scan")
          else "assembled from the scorecard")
    parts = [f"<div style='font-size:14px; font-weight:bold; color:{ink}'>Editorial letter</div>",
             f"<div style='color:{faint}'>{e(letter.get('made_at', ''))} · {by} · one reader's "
             "view</div>"]
    if letter.get("stale"):
        parts.append(f"<p style='color:{palette.get('warning', soft)}'>The book has changed "
                     "since this letter was written.</p>")
    if letter.get("note"):
        parts.append(f"<p style='color:{soft}'>{e(letter['note'])}</p>")
    if letter.get("works"):
        parts.append(f"<p style='margin-top:10px'><b>What works</b></p>")
        for w in letter["works"]:
            parts.append(f"<div style='margin-left:12px'>{e(w['what'])}."
                         + (f" <span style='color:{faint}'>({where(w['chapters'])})</span>"
                            if w.get("chapters") else "") + "</div>")
    issues = letter.get("issues") or []
    parts.append("<p style='margin-top:10px'><b>"
                 + ("What to work on, most important first" if issues
                    else "The checks found nothing to raise at the level of plot, "
                         "structure, character or dialogue. That is not a clean bill of "
                         "health (see below).") + "</b></p>")
    for n, i in enumerate(issues, 1):
        parts.append(
            f"<div style='margin:8px 0 0 12px'><b>{n}. {e(i['element'])}: {e(i['issue'])}.</b>"
            f"<br><span style='color:{soft}'>Where:</span> {where(i['chapters'])}"
            f"<br><span style='color:{soft}'>Effect on a reader:</span> {e(i['effect'])}"
            f"<br><span style='color:{soft}'>An option:</span> {e(i['option'])}</div>")
    parts.append("<p style='margin-top:12px'><b>What this letter couldn't judge</b></p>")
    for c in list(letter.get("cannot") or []) + list(ALWAYS_CANNOT):
        parts.append(f"<div style='margin-left:12px; color:{soft}'>{e(c)}</div>")
    return "".join(parts)
