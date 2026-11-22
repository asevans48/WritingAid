"""What the writing companion remembers between sessions.

Per chapter: when you last worked on it, how many words it had when you
opened and when you left, and where you stopped. Per day: words written.
Plus margin notes you dismissed (so they stay dismissed). Stored next to
the project file (``companion_state.json``), or under
``~/.creativeos/companion/`` for unsaved projects.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict


def state_path(project: Any) -> Path:
    pp = getattr(project, "project_path", "") or ""
    if pp:
        return Path(pp).parent / "companion_state.json"
    name = re.sub(r"[^\w-]+", "_", getattr(project, "name", "") or "untitled")
    return Path.home() / ".creativeos" / "companion" / f"{name}.json"


def load(project: Any) -> Dict[str, Any]:
    try:
        data = json.loads(state_path(project).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(project: Any, data: Dict[str, Any]) -> None:
    path = state_path(project)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except Exception as e:
        print(f"[companion] could not save state: {e}")


def chapter_state(data: Dict[str, Any], chapter_id: str) -> Dict[str, Any]:
    return data.setdefault("chapters", {}).setdefault(chapter_id or "?", {})


def record_session(project: Any, chapter_id: str, words_at_open: int, words_now: int,
                   stopped_at: str) -> None:
    """Called when the writer leaves a chapter (or saves)."""
    data = load(project)
    ch = chapter_state(data, chapter_id)
    ch["last_session"] = datetime.now().isoformat(timespec="minutes")
    ch["words_at_open"] = words_at_open
    ch["words_at_close"] = words_now
    ch["stopped_at"] = (stopped_at or "")[:240]
    today = date.today().isoformat()
    # Count each session's growth once (a session can be recorded several times).
    session_key = f"{chapter_id}@{ch.get('opened_at', '')}"
    sessions = data.setdefault("sessions", {})
    sessions[session_key] = {"date": today, "added": max(0, words_now - words_at_open)}
    if len(sessions) > 400:
        for k in sorted(sessions, key=lambda k: sessions[k]["date"])[:100]:
            del sessions[k]
    save(project, data)


def mark_opened(project: Any, chapter_id: str) -> Dict[str, Any]:
    """Note the chapter was opened; returns its state from before."""
    data = load(project)
    before = dict(chapter_state(data, chapter_id))
    chapter_state(data, chapter_id)["opened_at"] = datetime.now().isoformat(timespec="seconds")
    save(project, data)
    return before


def words_today(project: Any) -> int:
    today = date.today().isoformat()
    return sum(s.get("added", 0) for s in load(project).get("sessions", {}).values()
               if s.get("date") == today)


def dismissed(project: Any) -> set:
    return set(load(project).get("dismissed", []))


def dismiss(project: Any, key: str) -> None:
    data = load(project)
    keys = data.setdefault("dismissed", [])
    if key not in keys:
        keys.append(key)
        del keys[:-2000]
    save(project, data)


# Companion sections the writer collapsed (or opened), by key.
DEFAULT_COLLAPSED = {"memory", "style_sheet"}       # whole-book sections start closed


def collapsed_sections(project: Any) -> set:
    ui = load(project).get("ui", {}) if project is not None else {}
    if "collapsed" not in ui:
        return set(DEFAULT_COLLAPSED)
    return set(ui.get("collapsed") or [])


def set_section_collapsed(project: Any, key: str, collapsed: bool) -> None:
    if project is None:
        return
    data = load(project)
    ui = data.setdefault("ui", {})
    keys = set(ui.get("collapsed", DEFAULT_COLLAPSED))
    (keys.add if collapsed else keys.discard)(key)
    ui["collapsed"] = sorted(keys)
    save(project, data)
