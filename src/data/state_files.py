"""Where a project's side files live (piece R.7).

The readiness file and the companion's memory used to be named by folder
(``readiness.json``, ``companion_state.json`` beside the project file), so
two projects saved in one folder shared them. Now each project has its
own, named after its project file:

    Teller County.writerproj  →  Teller County.readiness.json
                                 Teller County.companion_state.json

**Nothing is lost on the way.** The old shared file (the *legacy* file) is
read while the project has no file of its own, and the first save writes
everything read from it into the project's own file. The legacy file is
never written, renamed or deleted again, so an older version of the app
still finds it as it was at the changeover. An unreadable legacy file is
treated as empty and left where it is (the project's own file is the one
the safe store protects).

A project not yet saved keeps its file under ``~/.creativeos/`` as before.

No Qt.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Optional


def own_path(project: Any, kind: str, unsaved_dir: str) -> Path:
    """Where this project's ``kind`` file is written."""
    pp = getattr(project, "project_path", "") or ""
    if pp:
        p = Path(pp)
        return p.parent / f"{p.stem}.{kind}.json"
    name = re.sub(r"[^\w-]+", "_", getattr(project, "name", "") or "untitled")
    return Path.home() / ".creativeos" / unsaved_dir / f"{name}.json"


def legacy_path(project: Any, legacy_name: str) -> Optional[Path]:
    """The old file shared by the folder, or None (an unsaved project)."""
    pp = getattr(project, "project_path", "") or ""
    return Path(pp).parent / legacy_name if pp else None


def read_path(own: Path, legacy: Optional[Path]) -> Path:
    """The file to read: the project's own once it exists, else the legacy
    file when there is one, else the own path (missing: empty)."""
    if own.exists() or legacy is None or legacy == own or not legacy.exists():
        return own
    return legacy


def is_legacy(path: Path, legacy: Optional[Path]) -> bool:
    return legacy is not None and path == legacy and path.exists()


def read_legacy(path: Path, default: Any, expect: Optional[type] = None) -> Any:
    """Read the legacy file without ever moving or changing it."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if expect is not None and not isinstance(data, expect):
            raise ValueError(f"expected {expect.__name__}")
        return data
    except Exception as e:                      # noqa: BLE001
        print(f"[state files] the shared file {path.name} could not be read ({e}); "
              "left as it is")
        return copy.deepcopy(default)
