"""Corrections a model found while proofreading, kept by paragraph.

The proofreading pass (``src/ai/proofread.py``, piece P.4) stores what it
kept here, and the editor's grammar check reads it, so a model's correction
shows as an ordinary grammar flag with the model named as its source.

* **By paragraph text.** An entry belongs to the exact words of a
  paragraph: change the paragraph and its entry no longer applies (and the
  paragraph is proofread again next time). An empty entry means "read,
  nothing found".
* **Saved** in the project's readiness file (``readiness.json``, key
  ``"proof"``); every other key is left alone.
* Without a model nothing is ever stored, so nothing changes.

No Qt.
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any, Dict, List, Optional

KEY = "proof"
MAX_PARAGRAPHS = 30000
RULE_ID = "MODEL"

_lock = threading.Lock()
_entries: Dict[str, List[Dict[str, Any]]] = {}
_state = {"model": "", "loaded": ""}


def key(paragraph: str) -> str:
    return hashlib.sha1(paragraph.encode("utf-8", "replace")).hexdigest()[:14]


def has(paragraph: str) -> bool:
    return key(paragraph) in _entries


def corrections(paragraph: str) -> List[Dict[str, Any]]:
    return list(_entries.get(key(paragraph), ()))


def put(paragraph: str, found: List[Dict[str, Any]], model: str = "") -> None:
    """``found``: [{"s", "e", "t", "r", "w"}] (start, end, the words, the
    correction, why), offsets within the paragraph."""
    with _lock:
        if len(_entries) >= MAX_PARAGRAPHS:
            for old in list(_entries)[:MAX_PARAGRAPHS // 10]:
                del _entries[old]
        _entries[key(paragraph)] = list(found)
        if model:
            _state["model"] = model


def issues_for(paragraph: str) -> list:
    """The stored corrections for this paragraph as grammar issues."""
    found = _entries.get(key(paragraph)) if _entries else None
    if not found:
        return []
    from src.utils.proofing import GrammarIssue
    by = f" (found by {_state['model']})" if _state["model"] else " (found by the model)"
    out = []
    for c in found:
        try:
            s, e = int(c["s"]), int(c["e"])
            if paragraph[s:e] != c["t"]:
                continue
            out.append(GrammarIssue(s, e, c["t"], (c.get("w") or "Possible error") + by,
                                    [c["r"]] if c.get("r") else [], RULE_ID, "model"))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def clear() -> None:
    with _lock:
        _entries.clear()
        _state.update(model="", loaded="")


def load(project: Any) -> None:
    """Bring the project's stored corrections into memory (once per
    project file and change of it)."""
    try:
        from src.data import readiness_state as rs
        path = rs.readiness_path(project)
        stamp = f"{path}:{path.stat().st_mtime_ns}" if path.exists() else ""
        if not stamp or stamp == _state["loaded"]:
            return
        data = rs.load(project).get(KEY)
        _state["loaded"] = stamp
        if not isinstance(data, dict):
            return
        with _lock:
            for k, v in (data.get("paragraphs") or {}).items():
                if isinstance(v, list):
                    _entries.setdefault(k, v)
            if data.get("model") and not _state["model"]:
                _state["model"] = str(data["model"])
    except Exception as e:
        print(f"[proofreading] stored corrections not read: {e}")


def save(project: Any, paragraphs: List[str]) -> bool:
    """Write the entries of ``paragraphs`` (those just proofread)."""
    try:
        from src.data import readiness_state as rs
        new = {key(p): _entries[key(p)] for p in paragraphs if key(p) in _entries}
        if not new:
            return True

        def change(data):
            proof = data.get(KEY)
            if not isinstance(proof, dict):
                proof = data[KEY] = {}
            stored = proof.setdefault("paragraphs", {})
            stored.update(new)
            if len(stored) > MAX_PARAGRAPHS:
                for old in list(stored)[:len(stored) - MAX_PARAGRAPHS]:
                    del stored[old]
            proof["model"] = _state["model"]
        return bool(rs.update(project, change))
    except Exception as e:
        print(f"[proofreading] corrections not saved: {e}")
        return False
