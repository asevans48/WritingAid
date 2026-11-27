"""What a novella holds of its own (piece D.14b).

Undo after a move that made a novella removes the novella only when it is
truly empty (the writer, 27 Nov: "if there are no chapters in it and no
metadata"). ``holds`` lists what it has, in the writer's words; an empty
list means it can go.

**What a novella can hold.** Worldbuilding, characters, plot planning,
story memory, the style sheet, the dictionary, the prose profile and the
Video Studio are the project's, shared by every manuscript (the model:
``Subproject`` owns only its manuscript), so nothing in them belongs to a
novella and they are not looked at. What is its own:

* in the project file: its chapters (with their outlines, planning,
  feedback and annotations), its drafts (Drafts ▾), and its name,
  description and kind and its manuscript's title and author: these count
  only when changed since the move made it (``snapshot``), since the move
  gave them;
* in its folder ``subprojects/<id>/``: any file but its ``subproject.json``
  (and its chapters' own folders, said as "chapters");
* in the files beside the project, under its id, **only what the writer
  made** (the writer's answer, 27 Nov: "count only what you wrote"): the
  publishing route chosen for it and the scene markers placed in it (the
  readiness file), and its submission drafts (``<project>.submission.json``).

What the app worked out by itself for the novella (readiness results, book
checks and their history, digests, ledger, plan matches, scene tension, the
editorial letter, the voice reading, Improve notes, the Critique's reports)
does not keep it: all of it can be made again. It is not deleted either
(rule 15): it stays in its file under the novella's id, unread.

Empty containers do not count (Undo moves the chapters' entries back and
can leave ``{"chapters": {}}``). Files are read directly; nothing is
written, and an unreadable file counts as holding something (it is never
assumed empty). No Qt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

FIELDS = ("name", "description", "kind")


def snapshot(sp: Any) -> Dict[str, Any]:
    """What the novella was given when it was made (compared at Undo)."""
    ms = getattr(sp, "manuscript", None)
    out = {f: getattr(sp, f, None) for f in FIELDS}
    out["title"] = getattr(ms, "title", None)
    out["author"] = getattr(ms, "author", None)
    return out


def _filled(value: Any) -> bool:
    """Anything but empty containers, None and empty strings."""
    if isinstance(value, dict):
        return any(_filled(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_filled(v) for v in value)
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


_UNREADABLE = object()


def _read(path: Optional[Path]) -> Any:
    try:
        if path is None or not Path(path).is_file():
            return {}
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else _UNREADABLE
    except Exception:
        return _UNREADABLE


# Only what the writer made keeps a novella (27 Nov); the rest is the
# app's own results, which can be made again.
READINESS_WORDS = {"route": "a publishing route"}
SECTION_WORDS = {"scene_marks": "scene markers"}


def _add(out: List[str], words: str) -> None:
    if words not in out:
        out.append(words)


def holds(project: Any, sp_id: str, project_dir: Optional[Path] = None,
          made: Optional[Dict[str, Any]] = None) -> List[str]:
    """What novella ``sp_id`` holds of its own, in words ("chapters",
    "a description", "Critique reports" …); [] when it is empty."""
    out: List[str] = []
    sp = project.get_subproject(sp_id) if project is not None else None
    if sp is None:
        return out
    if sp.manuscript.chapters:
        _add(out, "chapters")
    if project.drafts_for_scope(sp_id):
        _add(out, "drafts")
    if made:
        now = snapshot(sp)
        if now.get("description") != made.get("description"):
            _add(out, "a description")
        if now.get("name") != made.get("name") or now.get("title") != made.get("title"):
            _add(out, "a new name")
        for f in ("kind", "author"):
            if now.get(f) != made.get(f):
                _add(out, f"a changed {f}")
    elif (getattr(sp, "description", "") or "").strip():
        _add(out, "a description")
    if project_dir:
        folder = Path(project_dir) / "subprojects" / sp_id
        own = [Path(project_dir) / c.folder_path for c in sp.manuscript.chapters
               if getattr(c, "folder_path", None)]          # said as "chapters"
        try:
            if folder.is_dir() and any(
                    p.is_file() and p.name != "subproject.json"
                    and not any(d == p.parent or d in p.parents for d in own)
                    for p in folder.rglob("*")):
                _add(out, "files in its folder")
        except OSError:
            _add(out, "files in its folder")
    out.extend(w for w in _in_state_files(project, sp_id) if w not in out)
    return out


def _in_state_files(project: Any, sp_id: str) -> List[str]:
    out: List[str] = []
    from src.data import readiness_state as rs
    data = _read(rs.read_path(project))
    if data is _UNREADABLE:
        _add(out, "saved checks (the readiness file could not be read)")
    else:
        for key, top in data.items():
            if not isinstance(top, dict):
                continue
            if key == "manuscripts":
                part = top.get(sp_id)
                if isinstance(part, dict):
                    for sub, value in part.items():
                        if sub in READINESS_WORDS and _filled(value):
                            _add(out, READINESS_WORDS[sub])
            elif key in SECTION_WORDS and sp_id in top and _filled(top.get(sp_id)):
                _add(out, SECTION_WORDS[key])
    from src.data import submission_store
    data = _read(submission_store.path_for(project))
    if data is _UNREADABLE:
        _add(out, "submission drafts (the file could not be read)")
    elif _filled((data.get("manuscripts") or {}).get(sp_id)
                 if isinstance(data.get("manuscripts"), dict) else None):
        _add(out, "submission drafts")
    return out


def because(what: List[str]) -> str:
    """"it has chapters", "it has drafts and Critique reports", …"""
    if not what:
        return ""
    words = what[0] if len(what) == 1 else ", ".join(what[:-1]) + " and " + what[-1]
    return f"it has {words}"
