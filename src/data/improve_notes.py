"""The Improve window's notes, kept per project (piece D.14b).

What each Improve window said about a passage (its 📝 Critique's points and
every version a tab made, with "accepted" or its rating) is appended here
when the window closes, so the side panel's Feedback tab can show it in
later sessions (D.13c kept it in memory only).

**The file.** ``<project>.improve_notes.json`` beside the project file
(``~/.creativeos/improve_notes/`` for a project not yet saved), like the
other state files (R.7). It is its own file, not a part of the readiness
file, because it holds whole passages and versions: the readiness file is
rewritten (compact) on every check and read often, and is kept small; and
damage to one never touches the other. Layout, the readiness file's, so a
moved chapter's notes go with it through ``chapter_move.move_entries``::

    {"format_version": 1,
     "manuscripts": {"main" | <novella id>: {"chapters": {<chapter id>:
         {"notes": [{"id", "when", "passage", "accepted",
                     "critique": {"issues": [...], "dialogue": [...],
                                  "order": [...], "works": [...]},
                     "versions": [{"text", "source", "why", "rating"}],
                     "dismissed": ["c:issues:0", "v:1", ...]}]}}}}}

* **Appended, never rewritten.** A window's notes are added as one record;
  nothing in an earlier record changes except its ``dismissed`` list (the
  Feedback tab's Dismiss hides an item and keeps it in the file).
* **Cap.** The newest ``CAP`` (200) records per chapter are kept; the oldest
  goes when the 201st is added. (The versions you rated are also in the
  ratings database when data collection is on.)
* **Safe.** Written through ``safe_store`` (a temporary file swapped in);
  an unreadable file is set aside and the writer told, never saved over;
  one from a newer version of the app (``format_version``) is read-only.
  Every change is load → change → save under one lock.
* **Never sent anywhere.** Nothing else reads it but the Feedback tab and a
  chapter move. No file means nothing to show: a project without it opens
  as before.

No Qt.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.data import safe_store

FORMAT_VERSION = 1
KIND = "improve_notes"         # <project>.improve_notes.json
MAIN = "main"
CAP = 200                      # records (Improve windows) kept per chapter
CRITIQUE_PARTS = ("issues", "dialogue", "order", "works")
_lock = threading.RLock()


def path_for(project: Any) -> Path:
    from src.data import state_files
    return state_files.own_path(project, KIND, KIND)


def scope_key(scope: Optional[str]) -> str:
    return scope or MAIN


def load(project: Any) -> Dict[str, Any]:
    """The whole file, or an empty one (missing → empty, quietly;
    unreadable → set aside, the writer told, then empty)."""
    data = safe_store.load(path_for(project), {}, expect=dict) or {}
    data.setdefault("format_version", FORMAT_VERSION)
    if not isinstance(data.get("manuscripts"), dict):
        data["manuscripts"] = {}
    return data


def is_read_only(data: Dict[str, Any]) -> bool:
    try:
        return int(data.get("format_version", FORMAT_VERSION)) > FORMAT_VERSION
    except (TypeError, ValueError):
        return True


def save(project: Any, data: Dict[str, Any]) -> bool:
    if is_read_only(data):
        print("[improve notes] the file is from a newer version; not saving")
        return False
    return safe_store.save(path_for(project), data, indent=1)


def _notes_list(data: Dict[str, Any], scope: Optional[str], chapter_id: str) -> List[Any]:
    m = data["manuscripts"].setdefault(scope_key(scope), {})
    if not isinstance(m, dict):
        m = data["manuscripts"][scope_key(scope)] = {}
    chapters = m.setdefault("chapters", {})
    if not isinstance(chapters, dict):
        chapters = m["chapters"] = {}
    entry = chapters.setdefault(chapter_id, {})
    if not isinstance(entry, dict):
        entry = chapters[chapter_id] = {}
    notes = entry.setdefault("notes", [])
    if not isinstance(notes, list):
        notes = entry["notes"] = []
    return notes


def append(project: Any, scope: Optional[str], chapter_id: str,
           record: Dict[str, Any]) -> Optional[str]:
    """Add one window's notes for the chapter; the record's id, or None when
    it could not be written (a newer file, an unreadable one, a failed write)."""
    if project is None or not chapter_id:
        return None
    rec = dict(record)
    rec.setdefault("id", uuid.uuid4().hex[:12])
    rec.setdefault("dismissed", [])
    with _lock:
        data = load(project)
        if is_read_only(data):
            return None
        notes = _notes_list(data, scope, chapter_id)
        notes.append(rec)
        del notes[:-CAP]
        return rec["id"] if save(project, data) else None


def read(project: Any, scope: Optional[str], chapter_id: str) -> List[Dict[str, Any]]:
    """The chapter's records, oldest first, read directly: reading never
    sets a damaged file aside or writes anything ([] when unreadable)."""
    import json
    try:
        path = path_for(project)
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        ms = (data.get("manuscripts") or {}).get(scope_key(scope)) or {}
        entry = ((ms.get("chapters") or {}) if isinstance(ms, dict) else {}).get(chapter_id)
        notes = entry.get("notes") if isinstance(entry, dict) else None
        return [n for n in notes if isinstance(n, dict)] if isinstance(notes, list) else []
    except Exception:
        return []


def dismiss(project: Any, scope: Optional[str], chapter_id: str, record_id: str,
            item: str) -> bool:
    """Hide one item (``c:<part>:<n>`` or ``v:<n>``) of a record: noted in
    its ``dismissed`` list, nothing removed. True when saved."""
    with _lock:
        data = load(project)
        if is_read_only(data):
            return False
        for rec in _notes_list(data, scope, chapter_id):
            if isinstance(rec, dict) and rec.get("id") == record_id:
                gone = rec.get("dismissed")
                if not isinstance(gone, list):
                    gone = rec["dismissed"] = []
                if item not in gone:
                    gone.append(item)
                return save(project, data)
    return False
