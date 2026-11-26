"""Sentences marked while listening to a chapter (piece 6.1).

Stored per chapter in the project's companion file
(``<project>.companion_state.json``, see ``companion_state``) under the
key ``heard_marks``::

    {"chapters": {"<chapter id>": {"heard_marks": [
        {"id": "3f9c0a1b2c4d",          # stable, for 6.2 to clear it by
         "text": "The storm broke at dusk.",   # the sentence as it was heard
         "start": 0, "end": 24,         # its place in the chapter's text
         "paragraph": 0,                # its paragraph (0-based)
         "made": "2026-11-25T10:31:05", # when it was marked
         "source": "listen"}            # how it was made
    ]}}}

Every other key in the file is left exactly as it was. A mark whose
sentence has since changed is kept: ``resolve`` says so ("changed"), and
it is never dropped on its own. Nothing here writes the chapter.

No Qt.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

KEY = "heard_marks"

# What resolve() says about a mark against the chapter's text now.
SAME = "same"          # the sentence is where it was
MOVED = "moved"        # the same words, somewhere else in the chapter
CHANGED = "changed"    # the words are gone: "the text has changed"

CHANGED_LABEL = "the text has changed"


def marks(project: Any, chapter_id: str) -> List[Dict[str, Any]]:
    """The chapter's marks, in the order they were made ([] if none)."""
    if project is None or not chapter_id:
        return []
    from src.data import companion_state
    ch = companion_state.load(project).get("chapters", {}).get(chapter_id, {})
    out = ch.get(KEY, []) if isinstance(ch, dict) else []
    return [dict(m) for m in out if isinstance(m, dict) and m.get("text")]


def new_mark(text: str, start: int, end: int, paragraph: int = 0) -> Dict[str, Any]:
    return {"id": uuid.uuid4().hex[:12], "text": text, "start": int(start),
            "end": int(end), "paragraph": int(paragraph),
            "made": datetime.now().isoformat(timespec="seconds"), "source": "listen"}


def _write(project: Any, chapter_id: str, change) -> List[Dict[str, Any]]:
    from src.data import companion_state
    data = companion_state.load(project)
    ch = companion_state.chapter_state(data, chapter_id)
    current = [m for m in ch.get(KEY, []) if isinstance(m, dict)]
    ch[KEY] = change(current)
    companion_state.save(project, data)
    return [dict(m) for m in ch[KEY]]


def add(project: Any, chapter_id: str, mark: Dict[str, Any]) -> None:
    """Keep ``mark`` (saved at once, so a crash loses nothing)."""
    if project is None or not chapter_id:
        return
    _write(project, chapter_id, lambda ms: ms + [dict(mark)])


def remove(project: Any, chapter_id: str, mark_id: str) -> None:
    """Drop one mark by its id (the writer pressed the key again; 6.2 when
    a mark is fixed or dismissed)."""
    if project is None or not chapter_id or not mark_id:
        return
    _write(project, chapter_id, lambda ms: [m for m in ms if m.get("id") != mark_id])


def find(marks_: List[Dict[str, Any]], text: str, start: int) -> Optional[Dict[str, Any]]:
    """The mark already on this sentence (same words, same place), if any."""
    for m in marks_:
        if m.get("text") == text and int(m.get("start", -1)) == int(start):
            return m
    return None


def resolve(mark: Dict[str, Any], chapter_text: str) -> Tuple[int, int, str]:
    """Where the mark's sentence is in ``chapter_text`` now.

    ``(start, end, SAME)`` when it is where it was; ``(start, end, MOVED)``
    when the same words are elsewhere (the nearest copy to the old place);
    ``(old start, old end, CHANGED)`` when the words are gone."""
    words = mark.get("text", "") or ""
    start, end = int(mark.get("start", 0)), int(mark.get("end", 0))
    text = chapter_text or ""
    if words and text[start:end] == words:
        return start, end, SAME
    if words:
        best, pos = None, text.find(words)
        while pos >= 0:
            if best is None or abs(pos - start) < abs(best - start):
                best = pos
            pos = text.find(words, pos + 1)
        if best is not None:
            return best, best + len(words), MOVED
    return start, end, CHANGED
