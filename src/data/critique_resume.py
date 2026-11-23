"""Finished reports of a critique that hasn't completed, so it can resume.

A critique runs report by report. Each report a model writes is kept here as
soon as it is done. If the writer stops the run, or the app closes, the next
run with the same chapter text, report, model and settings reuses it instead
of asking the model again. When a run completes, the file is emptied: a
fresh run always gets fresh reports.

Stored beside the project (``critique_resume.json``), or under
``~/.creativeos/critique_resume/`` for a project not yet saved. Written
through ``safe_store``; an unreadable file is set aside, never saved over.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from src.data import safe_store

FORMAT_VERSION = 1
MAX_PARTS = 400                 # oldest dropped beyond this
_lock = threading.RLock()


def resume_path(project: Any) -> Path:
    pp = getattr(project, "project_path", "") or ""
    if pp:
        return Path(pp).parent / "critique_resume.json"
    name = re.sub(r"[^\w-]+", "_", getattr(project, "name", "") or "untitled")
    return Path.home() / ".creativeos" / "critique_resume" / f"{name}.json"


def part_key(**fields: Any) -> str:
    """A key over everything that shapes a report: chapter text, report,
    model, genre, writing context, manuscript context, voice."""
    blob = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _load(project: Any) -> Dict[str, Any]:
    data = safe_store.load(resume_path(project), {}, expect=dict)
    if not isinstance(data.get("parts"), dict):
        data["parts"] = {}
    data.setdefault("format_version", FORMAT_VERSION)
    return data


def get(project: Any, key: str) -> Optional[Dict[str, Any]]:
    if project is None:
        return None
    try:
        entry = _load(project)["parts"].get(key)
    except Exception as e:
        print(f"[critique-resume] {e}")
        return None
    return entry if isinstance(entry, dict) and isinstance(entry.get("section"), dict) else None


def put(project: Any, key: str, section: Dict[str, Any], entities=()) -> None:
    if project is None:
        return
    with _lock:
        try:
            data = _load(project)
            if int(data.get("format_version", FORMAT_VERSION)) > FORMAT_VERSION:
                return                      # a newer app's file: leave it be
            data["parts"][key] = {"section": section, "entities": [list(e) for e in entities],
                                  "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            if len(data["parts"]) > MAX_PARTS:
                oldest = sorted(data["parts"], key=lambda k: data["parts"][k].get("saved_at", ""))
                for k in oldest[:len(data["parts"]) - MAX_PARTS]:
                    del data["parts"][k]
            safe_store.save(resume_path(project), data, indent=None)
        except Exception as e:
            print(f"[critique-resume] could not keep the report: {e}")


def clear(project: Any) -> None:
    """A run completed: nothing to resume."""
    if project is None:
        return
    with _lock:
        path = resume_path(project)
        if not path.exists():
            return
        try:
            data = _load(project)
            if int(data.get("format_version", FORMAT_VERSION)) > FORMAT_VERSION:
                return
            if data["parts"]:
                data["parts"] = {}
                safe_store.save(path, data, indent=None)
        except Exception as e:
            print(f"[critique-resume] {e}")


def count(project: Any) -> int:
    try:
        return len(_load(project)["parts"]) if project is not None else 0
    except Exception:
        return 0
