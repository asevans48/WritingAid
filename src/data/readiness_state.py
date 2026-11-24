"""The readiness file, ``readiness.json`` (pieces 1.1 and 1.2b).

One file per project, beside the project file (``~/.creativeos/readiness/``
for a project not yet saved). It holds each manuscript's publishing route
(1.1), the readiness results per chapter (1.2b) and, later, stages,
dismissals and history; the voice reading (``voice_profile``) lives here
too. Layout: piece 1.2a, *Design* §7.

* Written only through ``safe_store``: a temporary file swapped in, and an
  unreadable file set aside (the writer is told), never saved over.
* Every change is load → change one part → save, under one lock, so a
  background check and the screen never overwrite each other's parts.
  Keys this version does not know are kept.
* A file stamped with a newer ``format_version`` is **read-only** here: it
  is read, never written, so a newer app's data can't be lost.
* Before the first write of results into a file written by 1.1 (route
  only), that file is copied aside once (``readiness.before-1.2.json``).
* Nothing here writes the project file or a chapter file.
"""

from __future__ import annotations

import re
import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

from src.data import safe_store

FORMAT_VERSION = 1
MAIN = "main"
_lock = threading.RLock()


def readiness_path(project: Any) -> Path:
    pp = getattr(project, "project_path", "") or ""
    if pp:
        return Path(pp).parent / "readiness.json"
    name = re.sub(r"[^\w-]+", "_", getattr(project, "name", "") or "untitled")
    return Path.home() / ".creativeos" / "readiness" / f"{name}.json"


def scope_key(scope: Optional[str]) -> str:
    """The file's key for a manuscript: "main", or the novella's id."""
    return scope or MAIN


def load(project: Any) -> Dict[str, Any]:
    """The whole file, or an empty one. Missing → empty, quietly;
    unreadable → set aside, the writer told, then empty."""
    data = safe_store.load(readiness_path(project), {}, expect=dict)
    data.setdefault("format_version", FORMAT_VERSION)
    if not isinstance(data.get("manuscripts"), dict):
        data["manuscripts"] = {}
    return data


def is_read_only(data: Dict[str, Any]) -> bool:
    """Made by a newer version of the app: read it, never write it."""
    try:
        return int(data.get("format_version", FORMAT_VERSION)) > FORMAT_VERSION
    except (TypeError, ValueError):
        return True


def save(project: Any, data: Dict[str, Any]) -> bool:
    if is_read_only(data):
        print("[readiness] the readiness file is from a newer version; not saving")
        return False
    path = readiness_path(project)
    _copy_aside_before_results(path, data)
    # Compact: the file holds every chapter's results and can run to a few
    # megabytes; indentation made each save several times slower.
    return safe_store.save(path, data, indent=None)


def update(project: Any, change: Callable[[Dict[str, Any]], Any]) -> bool:
    """Load, ``change(data)`` in place, save; under the lock. Returns
    whether it was saved."""
    with _lock:
        data = load(project)
        if is_read_only(data):
            return False
        change(data)
        return save(project, data)


def _has_results(data: Dict[str, Any]) -> bool:
    return any(isinstance(m, dict) and m.get("chapters")
               for m in (data.get("manuscripts") or {}).values())


def _copy_aside_before_results(path: Path, new: Dict[str, Any]) -> None:
    """Rule 15: before the first write in the fuller layout, keep the 1.1
    file as it was."""
    if not _has_results(new) or not path.exists():
        return
    aside = path.with_name(path.stem + ".before-1.2.json")
    if aside.exists():
        return
    try:
        old = safe_store.load(path, {}, expect=dict)
        if not _has_results(old):
            shutil.copy2(path, aside)
    except Exception as e:
        print(f"[readiness] could not copy the old file aside: {e}")


# ── Parts of the file ──────────────────────────────────────────────────

def manuscript_entry(data: Dict[str, Any], scope: Optional[str]) -> Dict[str, Any]:
    """The manuscript's part of ``data``, created if missing."""
    entry = data["manuscripts"].setdefault(scope_key(scope), {})
    if not isinstance(entry, dict):
        entry = data["manuscripts"][scope_key(scope)] = {}
    return entry


def chapter_entry(data: Dict[str, Any], scope: Optional[str], chapter_id: str) -> Dict[str, Any]:
    m = manuscript_entry(data, scope)
    chapters = m.setdefault("chapters", {})
    if not isinstance(chapters, dict):
        chapters = m["chapters"] = {}
    entry = chapters.setdefault(chapter_id, {})
    if not isinstance(entry, dict):
        entry = chapters[chapter_id] = {}
    return entry


def stored_chapter(project: Any, scope: Optional[str], chapter_id: str) -> Dict[str, Any]:
    """The stored results for one chapter (a copy; {} when none)."""
    m = load(project)["manuscripts"].get(scope_key(scope), {})
    ch = (m.get("chapters") or {}).get(chapter_id) if isinstance(m, dict) else None
    return dict(ch) if isinstance(ch, dict) else {}


def store_chapter(project: Any, scope: Optional[str], chapter_id: str,
                  fields: Dict[str, Any]) -> bool:
    """Update a chapter's stored fields. ``fields["results"]`` is merged by
    check name (results of checks not re-run are kept); the chapter's other
    keys (its stage …) are kept."""
    fields = dict(fields)
    new_results = fields.pop("results", {}) or {}

    def change(data):
        entry = chapter_entry(data, scope, chapter_id)
        results = entry.get("results") if isinstance(entry.get("results"), dict) else {}
        results.update(new_results)
        entry.update(fields)
        entry["results"] = results
    return update(project, change)


def store_chapters(project: Any, scope: Optional[str],
                   fields_by_chapter: Dict[str, Dict[str, Any]]) -> bool:
    """``store_chapter`` for several chapters in one save."""
    if not fields_by_chapter:
        return True
    prepared = {}
    for cid, fields in fields_by_chapter.items():
        fields = dict(fields)
        prepared[cid] = (fields.pop("results", {}) or {}, fields)

    def change(data):
        for cid, (new_results, fields) in prepared.items():
            entry = chapter_entry(data, scope, cid)
            results = entry.get("results") if isinstance(entry.get("results"), dict) else {}
            results.update(new_results)
            entry.update(fields)
            entry["results"] = results
    return update(project, change)


def stored_book(project: Any, scope: Optional[str]) -> Dict[str, Any]:
    """The stored whole-book results for a manuscript (a copy; {} when none)."""
    m = load(project)["manuscripts"].get(scope_key(scope), {})
    b = m.get("book") if isinstance(m, dict) else None
    return dict(b) if isinstance(b, dict) else {}


def store_book(project: Any, scope: Optional[str], results: Dict[str, Any]) -> bool:
    """Merge whole-book results (by check name) for a manuscript."""
    def change(data):
        m = manuscript_entry(data, scope)
        book = m.get("book") if isinstance(m.get("book"), dict) else {}
        merged = book.get("results") if isinstance(book.get("results"), dict) else {}
        merged.update(results)
        book["results"] = merged
        m["book"] = book
    return update(project, change)


HISTORY_DAYS = 365


def history(project: Any, scope: Optional[str]) -> list:
    """The manuscript's daily readiness record, oldest first (2.4)."""
    m = load(project)["manuscripts"].get(scope_key(scope), {})
    h = m.get("history") if isinstance(m, dict) else None
    return [e for e in (h or []) if isinstance(e, dict) and "date" in e]


def record_history(project: Any, scope: Optional[str], entry: Dict[str, Any]) -> bool:
    """Today's figure for a manuscript: one entry per day (the latest check
    of the day wins), at most a year kept."""
    def change(data):
        m = manuscript_entry(data, scope)
        h = [e for e in (m.get("history") or []) if isinstance(e, dict)]
        if h and h[-1].get("date") == entry.get("date"):
            h[-1] = entry
        else:
            h.append(entry)
        m["history"] = h[-HISTORY_DAYS:]
    return update(project, change)


def dismissed_keys(project: Any) -> Set[str]:
    """Pattern keys the writer dismissed (3.3); empty until then."""
    d = load(project).get("dismissed")
    return set(d) if isinstance(d, dict) else set()
