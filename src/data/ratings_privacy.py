""""Keep this project's ratings to itself" (README decision 5, pieces V.4
and V.5).

A per-project switch, off by default. On: rewrites in *other* projects
never learn from this project's ratings; this project still learns from
its own and from the shared store. Nothing is deleted or moved: the
switch lives in the project's own side file (R.7, ``state_files``),
``<project>.ratings.json`` beside the project file, never in the ratings
database. A missing, empty or unreadable file means off.

The one shared function for V.4 (which examples a rewrite learns from)
and V.5 (where the writer manages groups): :func:`is_private` and
:func:`set_private`. Both take a project path (the string stored with
each rating) or a project object. No Qt.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Tuple

from src.data import safe_store

KIND = "ratings"
KEY = "keep_to_itself"
FORMAT_VERSION = 1

_lock = threading.RLock()
_cache: Dict[str, Tuple[float, bool]] = {}     # path -> (mtime, value)


def _project(project_or_path: Any) -> Any:
    if isinstance(project_or_path, (str, Path)):
        return SimpleNamespace(project_path=str(project_or_path), name="")
    return project_or_path


def _path_of(project_or_path: Any) -> str:
    if isinstance(project_or_path, (str, Path)):
        return str(project_or_path)
    return str(getattr(project_or_path, "project_path", "") or "")


def settings_path(project_or_path: Any) -> Path:
    """Where the switch is kept for this project."""
    from src.data import state_files
    return state_files.own_path(_project(project_or_path), KIND, KIND)


def is_private(project_path: Any) -> bool:
    """Whether this project's ratings are kept to itself. False for a
    project not yet saved (its ratings carry no project path) and when
    the file is missing or unreadable. Cheap: cached by file time."""
    pp = _path_of(project_path).strip()
    if not pp:
        return False
    try:
        path = settings_path(pp)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return False
        key = str(path)
        hit = _cache.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        data = safe_store.load(path, {}, expect=dict)
        value = bool(data.get(KEY, False))
        _cache[key] = (mtime, value)
        return value
    except Exception as e:                       # noqa: BLE001
        print(f"[ratings privacy] could not read the switch ({e}); treated as off")
        return False


def set_private(project_path: Any, value: bool) -> bool:
    """Turn the switch on or off. Returns whether it was saved. A project
    not yet saved has nowhere to keep it (False)."""
    pp = _path_of(project_path).strip()
    if not pp:
        return False
    with _lock:
        path = settings_path(pp)
        data = safe_store.load(path, {}, expect=dict) if path.exists() else {}
        data.setdefault("format_version", FORMAT_VERSION)
        data[KEY] = bool(value)
        ok = bool(safe_store.save(path, data))
        _cache.pop(str(path), None)
        return ok
