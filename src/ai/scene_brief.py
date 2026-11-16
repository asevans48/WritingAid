"""Where the passage sits in its scene — for Rephrase and Suggestions.

Two layers:

* ``scene_brief`` — instant, from the writer's own notes and the text, with
  no model call: the chapter's summary and outline, which planned beats
  are done and which is next, the point-of-view character, who is present
  in the last few paragraphs, the location, and what the previous
  chapter covered. Grounded, so it can't invent anything.
* ``moment_summary`` — a model-written two or three sentences about the
  text leading up to the passage: who is there, what was just said or
  done, the mood, what's unresolved. Cached per scene (keyed on that
  lead-up text), so it's only regenerated when the scene before the
  passage changes, not on every rephrase.
"""

from __future__ import annotations

import re
import threading
from typing import Any, Dict, List, Optional, Tuple

_LEAD_UP_WORDS = 1500        # how much of the text before the passage to summarise
_MIN_LEAD_UP_WORDS = 40      # less than this: nothing worth summarising
_PLACE_HINTS = ("place", "location", "city", "town", "planet", "region", "building",
                "landmark", "realm", "kingdom", "country", "district", "settlement")


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rsplit(" ", 1)[0] + "…"


def _present(project: Any, chapter: Any, recent: str) -> List[str]:
    """Characters in the last few paragraphs (and the POV character)."""
    from src.ai.canon_index import character_name_variants, find_mentions
    people = list(getattr(project, "characters", None) or [])
    if not people:
        return []
    found = find_mentions(recent, character_name_variants(people))
    names = sorted(found, key=lambda n: -found[n].get("count", 0))
    pov = (getattr(getattr(chapter, "planning", None), "pov_character", "") or "").strip()
    if pov and pov not in names:
        names.insert(0, pov)
    return names[:6]


def _location(project: Any, chapter: Any, recent: str) -> str:
    plan = getattr(chapter, "planning", None)
    places = [p for p in getattr(plan, "locations", None) or [] if p]
    try:
        from src.ai.canon_index import collect_world_entities, find_mentions, world_name_variants
        entities = [e for e in collect_world_entities(getattr(project, "worldbuilding", None))
                    if any(h in (e.category or "").lower() for h in _PLACE_HINTS)]
        mentioned = find_mentions(recent, world_name_variants(entities))
        if mentioned:
            # The place named last in the recent text is most likely where we are.
            last = max(mentioned, key=lambda n: recent.rfind(n))
            return last
    except Exception:
        pass
    return places[0] if places else ""


def _beats(chapter: Any) -> Tuple[List[str], str]:
    events = [e for e in getattr(getattr(chapter, "planning", None), "events", None) or []
              if getattr(e, "text", "")]
    done = [e.text for e in events if getattr(e, "completed", False)]
    upcoming = next((e.text for e in events if not getattr(e, "completed", False)), "")
    return done, upcoming


def scene_brief(project: Any, chapter: Any, before: str, passage: str = "",
                *, chapter_notes: bool = True) -> str:
    """A few short lines placing the passage in its scene. ``chapter_notes``
    False leaves out the chapter summary and outline (for callers that
    already include them)."""
    recent = (before or "")[-2500:] + "\n" + (passage or "")
    lines: List[str] = []
    if chapter is not None and chapter_notes:
        plan = getattr(chapter, "planning", None)
        title = getattr(chapter, "title", "") or ""
        about = (getattr(plan, "description", "") or getattr(plan, "outline", "") or "").strip()
        if title or about:
            head = f"Chapter {getattr(chapter, 'number', '') or ''} “{title}”".replace("  ", " ")
            lines.append(f"{head.strip()}: {_clip(about, 260)}" if about else head.strip())
    if project is not None:
        pov = (getattr(getattr(chapter, "planning", None), "pov_character", "") or "").strip()
        present = _present(project, chapter, recent)
        where = _location(project, chapter, recent)
        bits = []
        if pov:
            bits.append(f"point of view: {pov}")
        if present:
            bits.append("present: " + ", ".join(present))
        if where:
            bits.append(f"location: {where}")
        if bits:
            lines.append("Scene — " + "; ".join(bits) + ".")
    if chapter is not None:
        done, upcoming = _beats(chapter)
        if done:
            lines.append("Already happened: " + _clip("; ".join(done[-3:]), 220) + ".")
        if upcoming:
            lines.append(f"Building toward: {_clip(upcoming, 160)}.")
    if project is not None and chapter is not None and chapter_notes:
        try:
            from src.ai.passage_critique import _earlier_chapters
            previous = _earlier_chapters(project, chapter, 300, count=1)
            if previous:
                lines.append("Previously — " + previous.split(": ", 1)[-1])
        except Exception:
            pass
    return "\n".join(l for l in lines if l.strip())


# ── The moment, summarised by the model (cached per scene) ───────────

_CACHE: Dict[Tuple[str, int], str] = {}
_CACHE_LOCK = threading.Lock()

MOMENT_SYSTEM = ("You summarise fiction for an editor. Be factual and brief; use the "
                 "characters' names; no advice, no quotes longer than five words.")


def lead_up(before: str) -> str:
    """The text the moment summary is made from: the last ~1,500 words."""
    words = (before or "").split()
    return " ".join(words[-_LEAD_UP_WORDS:])


def cache_key(chapter: Any, before: str) -> Tuple[str, int]:
    return (str(getattr(chapter, "id", "") or ""), hash(lead_up(before)))


def cached_moment(chapter: Any, before: str) -> Optional[str]:
    with _CACHE_LOCK:
        return _CACHE.get(cache_key(chapter, before))


def moment_prompt(before: str, names: List[str]) -> str:
    who = f"Characters in the story: {', '.join(names[:12])}.\n\n" if names else ""
    return (f"{who}TEXT LEADING UP TO THE PASSAGE:\n{lead_up(before)}\n\n"
            "In two or three sentences, say what is happening at the end of this text: who "
            "is there, what was just said or done, the mood, and what is unresolved. "
            "Describe only this text — not what comes next — and give no advice.")


def _clean(reply: str) -> str:
    from src.ai.output_sanitizer import strip_meta_tokens
    text = strip_meta_tokens(reply or "")
    text = re.sub(r"^\s*(?:summary|here is a summary|what's happening)\s*[:\-–—]\s*", "", text,
                  flags=re.I)
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return _clip(" ".join(sentences[:3]), 420)


def moment_summary(llm: Any, chapter: Any, before: str, names: List[str] = (),
                   *, refresh: bool = False) -> str:
    """Two or three sentences on what's happening right before the passage,
    or "" when there's too little text (or no model)."""
    if llm is None or len(lead_up(before).split()) < _MIN_LEAD_UP_WORDS:
        return ""
    key = cache_key(chapter, before)
    if not refresh:
        with _CACHE_LOCK:
            if key in _CACHE:
                return _CACHE[key]
    try:
        reply = llm.generate_text(moment_prompt(before, list(names)), MOMENT_SYSTEM,
                                  max_tokens=180, temperature=0.3)
    except Exception as e:
        print(f"[scene] summary failed: {e}")
        return ""
    summary = _clean(reply)
    if summary:
        with _CACHE_LOCK:
            if len(_CACHE) > 200:
                _CACHE.clear()
            _CACHE[key] = summary
    return summary


def compose(moment: str, brief: str, instruction: str = "") -> str:
    """The text that goes in Rephrase's Scene description box."""
    parts = [p.strip() for p in (instruction, f"What's happening: {moment}" if moment else "",
                                 brief) if p and p.strip()]
    return "\n".join(parts)
