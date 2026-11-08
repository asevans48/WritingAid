"""Turn rated critique analyses into fine-tuning rows.

Three granularities, all landing in the ``critique`` source bucket of
the training database:

  * **Section** — a whole report for one chapter (e.g. the Character
    report). Saved as one row per model call that produced it, so each
    row is the exact (system, prompt, output) the model saw. Local-model
    runs make several small focused calls; each becomes its own row,
    which is precisely the shape a small fine-tuned analysis model
    needs to learn.
  * **Part** — one call (one character's analysis, one batch of world
    elements) or, for single-call reports, one ``## Heading`` block.
  * **Item** — one finding, strength, recommendation or new element.
    Saved as a "give one [TAG] line" micro-task against the prompt that
    produced it. Good and bad items for the same prompt share a
    ``source_text`` and so pair up naturally for preference (DPO)
    training.

Item ratings also *curate* section and part rows: lines for items rated
poor/bad are removed from the saved output, so positive examples teach
only the findings the author endorsed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

NEGATIVE = ("poor", "bad")
POSITIVE = ("excellent", "good")

# Headed lists on a ReportSection → the tag a model would emit for them.
LIST_TAGS: Dict[str, str] = {
    "strengths": "ON TRACK",
    "major_issues": "DRIFT",
    "minor_issues": "NOTE",
    "suggestions": "RECOMMEND",
    "New elements (not in worldbuilding)": "NEW",
    "Profile updates to consider": "PROFILE UPDATE",
    "Arc position": "ARC",
    "Speakers with no character record": "NEW CHARACTER",
}
LIST_LABELS: Dict[str, str] = {
    "strengths": "Strengths",
    "major_issues": "Major issues",
    "minor_issues": "Minor issues",
    "suggestions": "Suggested actions",
}


@dataclass
class Part:
    id: str
    label: str
    kind: str          # report | focused | repair | heading
    system: str
    prompt: str
    output: str
    real: bool         # True when prompt/output is a genuine model call


def section_lists(section: Any) -> Dict[str, List[str]]:
    """All rateable lists on a section, in display order."""
    out: Dict[str, List[str]] = {}
    for key in ("strengths", "major_issues", "minor_issues", "suggestions"):
        items = getattr(section, key, None) or []
        if items:
            out[key] = list(items)
    for key, items in (getattr(section, "extra_lists", None) or {}).items():
        if items:
            out[key] = list(items)
    return out


def list_tag(section: Any, list_name: str) -> str:
    tag = LIST_TAGS.get(list_name, "NOTE")
    rt = getattr(getattr(section, "report_type", None), "value", "")
    if list_name == "major_issues" and rt == "worldbuilding":
        return "DIFFERS"
    return tag


def iter_parts(section: Any) -> List[Part]:
    """The rateable parts of a section.

    Multi-call sections (local-model runs) → one part per call.
    Single-call sections → one part per ``## Heading`` of the narrative,
    with a synthesised "write only this section" prompt.
    """
    calls = getattr(section, "calls", None) or []
    focused = [c for c in calls if c.get("kind") != "report"]
    if len(calls) > 1 or focused:
        return [Part(c["id"], c.get("label") or c["id"], c.get("kind", ""),
                     c.get("system", ""), c.get("prompt", ""),
                     c.get("output", ""), True)
                for c in calls]
    narrative = getattr(section, "narrative", "") or ""
    base_prompt = (calls[0]["prompt"] if calls else getattr(section, "prompt", "")) or ""
    base_system = (calls[0]["system"] if calls else getattr(section, "system_prompt", "")) or ""
    blocks = re.split(r"(?m)^(?=#{1,3} )", narrative)
    parts: List[Part] = []
    for i, block in enumerate(b for b in blocks if b.strip()):
        m = re.match(r"#{1,3} +(.+)", block)
        if not m:
            continue
        heading = m.group(1).strip().strip("*")
        prompt = (f"{base_prompt}\n\nWrite ONLY the \"{heading}\" section of this "
                  f"report.") if base_prompt else ""
        parts.append(Part(f"h{i + 1}", heading, "heading", base_system, prompt,
                          block.strip(), False))
    return parts


def curate(output: str, bad_items: Iterable[str]) -> str:
    """Remove lines carrying items the author rated poor/bad."""
    probes = []
    for item in bad_items:
        bits = re.split(r"\s+[—–]\s+", item, maxsplit=1)
        probes.append(item[:60])
        if len(bits) == 2:
            probes.append(bits[1][:60])
    probes = [p for p in probes if len(p) >= 12]
    if not probes:
        return output
    kept = [l for l in (output or "").splitlines()
            if not any(p in l for p in probes)]
    return "\n".join(kept).strip()


def _notes(meta: Dict[str, Any], **extra: Any) -> str:
    fields = {
        "critique_kind": meta.get("report_type", ""),
        "genre": meta.get("genre", ""),
        "has_llm": meta.get("has_llm", True),
        **extra,
        # Free-text values last so the key=value parser can't swallow
        # a following key.
        "chapter_title": meta.get("chapter_title", ""),
    }
    return " ".join(f"{k}={v}" for k, v in fields.items() if v not in ("", None))


def _row(source: str, output: str, system: str, rating: str,
         meta: Dict[str, Any], **notes: Any) -> Dict[str, Any]:
    return {
        "source_text": source,
        "output_text": output,
        "system_prompt": system,
        "rating": rating,
        "accepted": rating in POSITIVE,
        "notes": _notes(meta, **notes),
        "genre": meta.get("genre", ""),
        "project_path": meta.get("project_path", ""),
    }


def _bad_items(item_ratings: Optional[Dict[str, str]]) -> List[str]:
    return [i for i, r in (item_ratings or {}).items() if r in NEGATIVE]


def section_rows(section: Any, meta: Dict[str, Any], rating: str,
                 item_ratings: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Rows for rating a whole section."""
    rows: List[Dict[str, Any]] = []
    bad = _bad_items(item_ratings)
    calls = getattr(section, "calls", None) or []
    local = int(any(c.get("kind") == "focused" for c in calls))
    for c in calls:
        out = curate(c.get("output", ""), bad) if rating in POSITIVE else c.get("output", "")
        if not out.strip():
            continue
        rows.append(_row(c.get("prompt", ""), out, c.get("system", ""), rating, meta,
                         critique_unit="section", call_kind=c.get("kind", ""),
                         local=local, prompt_kind="real",
                         curated=int(out != c.get("output", "")),
                         part=c.get("label", "")))
    if rows:
        return rows

    # No recorded calls: legacy section (loaded from an older save) or
    # dashboard mode. Fall back to the section prompt / a synthesised one.
    pieces = [getattr(section, "narrative", "") or ""]
    for key, items in section_lists(section).items():
        keep = [i for i in items if i not in bad] if rating in POSITIVE else items
        if keep:
            pieces.append(f"{LIST_LABELS.get(key, key)}:\n" + "\n".join(f"- {i}" for i in keep))
    output = "\n\n".join(p for p in pieces if p.strip())
    if not output.strip():
        return []
    prompt = getattr(section, "prompt", "") or ""
    if prompt.strip():
        kind = "real"
    else:
        metrics = getattr(section, "metrics", None) or {}
        prompt = (f"Produce a {meta.get('report_type', '')} critique of this chapter for "
                  f"the {meta.get('genre_name', meta.get('genre', ''))} genre. Use the "
                  f"metrics provided as ground truth, name specific issues with quoted "
                  f"phrases, and end with concrete next-revision actions.\n\n"
                  f"Chapter: {meta.get('chapter_title', '')}\nMetrics:\n"
                  + "\n".join(f"- {k}: {v}" for k, v in metrics.items()))
        kind = "dashboard_synthesised"
    return [_row(prompt, output, getattr(section, "system_prompt", "") or "", rating, meta,
                 critique_unit="section", prompt_kind=kind)]


def part_rows(section: Any, part: Part, meta: Dict[str, Any], rating: str,
              item_ratings: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Row for rating one part."""
    if not part.prompt.strip() or not part.output.strip():
        return []
    out = curate(part.output, _bad_items(item_ratings)) if rating in POSITIVE else part.output
    if not out.strip():
        return []
    return [_row(part.prompt, out, part.system, rating, meta,
                 critique_unit="part", call_kind=part.kind,
                 prompt_kind="real" if part.real else "part_synthesised",
                 curated=int(out != part.output), part=part.label)]


def item_rows(section: Any, list_name: str, item: str, meta: Dict[str, Any],
              rating: str) -> List[Dict[str, Any]]:
    """Row for rating one finding.

    The prompt is the call that produced the item plus a fixed
    "one [TAG] line" instruction, so every item from that call shares a
    ``source_text`` — good and bad items then form preference pairs.
    """
    tag = list_tag(section, list_name)
    call_id = (getattr(section, "item_sources", None) or {}).get(item, "")
    call = next((c for c in getattr(section, "calls", None) or [] if c["id"] == call_id), None)
    base = (call or {}).get("prompt") or getattr(section, "prompt", "") or ""
    system = (call or {}).get("system") or getattr(section, "system_prompt", "") or ""
    if not base.strip():
        base = (f"Chapter: {meta.get('chapter_title', '')}\nReport: "
                f"{meta.get('report_type', '')} critique.")
        kind = "item_synthesised"
    else:
        kind = "real" if call else "section_prompt"
    prompt = (f"{base}\n\nReply with a single [{tag}] line — the most important "
              f"{LIST_LABELS.get(list_name, list_name).lower()} finding.")
    return [_row(prompt, f"[{tag}] {item}", system, rating, meta,
                 critique_unit="item", item_list=list_name, prompt_kind=kind,
                 part=(call or {}).get("label", ""))]


def save_rows(rows: List[Dict[str, Any]], db: Any, source_type: str) -> int:
    saved = 0
    for r in rows:
        if db.log(r["source_text"], r["output_text"], source_type=source_type,
                  rating=r["rating"], accepted=r["accepted"], notes=r["notes"],
                  project_path=r["project_path"], genre=r["genre"],
                  system_prompt=r["system_prompt"]):
            saved += 1
    return saved
