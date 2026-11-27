"""The model's reading of a chapter's scenes, for the outline (piece 7.2).

Joins two stored results to 7.1's rules-based scenes
(``reverse_outline.outline``), without running a model:

* the chapter's reverse outline from ``chapter_digest`` (made when the
  book is checked with the model): for each scene the model found, whose
  point of view, what happens and what the scene is for (or that it
  changes nothing);
* the tension of each scene from ``scene_tension`` (when stored).

The model splits scenes at a change of time or place as well as at
breaks, so one rules-based scene may hold several of the model's scenes.
Each of the model's scenes goes to the rules-based scene its first words
are in; one whose words could not be found follows the scene before it.

Read only; no Qt. Both stores are matched by the chapter text's hash, so
a reading of an older draft is never shown as this one's.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def digest_entry(project: Any, chapter_id: str, text: str) -> Optional[Dict[str, Any]]:
    """The chapter's stored reverse outline if made from ``text``; looks in
    every manuscript of the project (chapter ids are unique). None on any error."""
    if project is None or not (text or "").strip():
        return None
    try:
        from src.ai import chapter_digest
        from src.ai.readiness import text_hash
        from src.data import readiness_state as rs
        store = rs.load(project).get(chapter_digest.KEY, {})
        want = text_hash(text)
        for entries in (store.values() if isinstance(store, dict) else []):
            entry = entries.get(chapter_id) if isinstance(entries, dict) else None
            if (isinstance(entry, dict) and entry.get("text_hash") == want
                    and entry.get("v") == chapter_digest.VERSION):
                return entry
    except Exception as e:
        print(f"[outline] model reading unavailable: {e}")
    return None


def per_scene(entry: Optional[Dict[str, Any]], scenes: Sequence[Any]) -> List[List[Dict[str, Any]]]:
    """For each rules-based scene, the model's scenes that start in it, in order."""
    from src.ai import chapter_digest
    out: List[List[Dict[str, Any]]] = [[] for _ in scenes]
    if not entry or not scenes:
        return out
    last = 0
    for s in entry.get("scenes", []) or []:
        if not isinstance(s, dict) or chapter_digest.is_template_echo(s.get("pov") or "",
                                                                      s.get("what") or ""):
            continue                       # an outline stored before the echo was caught
        start = s.get("start", -1)
        where = last
        if isinstance(start, int) and start >= 0:
            where = 0
            for i, sc in enumerate(scenes):
                if sc.start <= start or i == 0:
                    where = i
        out[where].append(s)
        last = where
    return out


def line(s: Dict[str, Any]) -> str:
    """One model scene in words: "Dane · finds the mine flooded → he must turn back"."""
    pov = (s.get("pov") or "").strip()
    what = (s.get("what") or "").strip()
    purpose = (s.get("purpose") or "").strip()
    named = pov and what.lower().startswith(pov.lower())      # "Samuel wakes…": no "Samuel ·"
    head = f"{pov} · {what}" if pov and what and not named else (what or pov)
    return head + (f" → {purpose}" if purpose else " → changes nothing?")


def tension(project: Any, chapter_id: str, text: str) -> Optional[Dict[str, Any]]:
    """The chapter's stored tension ratings (``scene_tension``), or None."""
    try:
        from src.ai import scene_tension
        return scene_tension.stored(project, chapter_id, text)
    except Exception:
        return None
