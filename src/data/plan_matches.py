"""The writer's corrections to the draft-beside-plan matches (piece 7.3).

Kept in the project's readiness file (``readiness_state``) under a new
top-level key, so older versions of the app keep it untouched (they keep
keys they do not know) and older files open with no corrections::

    "plan_matches": {
        "<manuscript: main or novella id>": {
            "<chapter id>": {"<scene key>": ["<event id>", ...], ...}
        }
    }

A scene key is the scene's first words (``plan_match.scene_key``); an
empty list means the writer said the scene is not in the plan. Written
through ``readiness_state.update`` (safe writes, one lock).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.data import readiness_state as rs

KEY = "plan_matches"


def corrections(project: Any, scope: Optional[str], chapter_id: str) -> Dict[str, List[str]]:
    """The writer's choices for one chapter ({} when none or unreadable)."""
    try:
        book = rs.load(project).get(KEY)
        ch = ((book or {}).get(rs.scope_key(scope)) or {}).get(chapter_id) \
            if isinstance(book, dict) else None
    except Exception:
        return {}
    if not isinstance(ch, dict):
        return {}
    return {str(k): [str(i) for i in v] for k, v in ch.items() if isinstance(v, list)}


def set_correction(project: Any, scope: Optional[str], chapter_id: str, scene_key: str,
                   event_ids: Optional[List[str]]) -> bool:
    """Store the events a scene holds (``[]``: not in the plan), or, with
    ``None``, go back to the suggestion."""
    def change(data):
        book = data.get(KEY) if isinstance(data.get(KEY), dict) else {}
        ms = book.get(rs.scope_key(scope)) if isinstance(book.get(rs.scope_key(scope)), dict) else {}
        ch = ms.get(chapter_id) if isinstance(ms.get(chapter_id), dict) else {}
        if event_ids is None:
            ch.pop(scene_key, None)
        else:
            ch[scene_key] = list(event_ids)
        ms[chapter_id] = ch
        book[rs.scope_key(scope)] = ms
        data[KEY] = book
    return rs.update(project, change)
