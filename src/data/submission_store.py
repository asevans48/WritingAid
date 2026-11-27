"""Where the submission package's drafts are kept (piece 9.3).

One file per project, beside the project file and named after it, the R.7
way (``state_files``)::

    Teller County.writerproj  →  Teller County.submission.json

A project not yet saved keeps its file under ``~/.creativeos/submission/``.
Nothing here writes the project file or a chapter: the drafts are never
part of the manuscript, and an older version of the app, which does not
know the file, simply leaves it alone.

* Written only through ``safe_store`` (a temporary file swapped in; an
  unreadable file is set aside and the writer told, never saved over).
* Every change is load → change one part → save, under one lock. Keys this
  version does not know are kept.
* A file stamped with a newer ``format_version`` is read, never written.
* **Nothing the writer wrote is lost.** A new draft never replaces the
  current text silently: the current text goes into the document's
  ``versions`` first (unless it is empty or the same), and restoring an
  earlier version keeps the current one the same way.

Layout (``format_version`` 1)::

    {"format_version": 1,
     "manuscripts": {"main": {
         "synopsis": {"text": "…", "source": "template" | "model" | "writer",
                      "generated": "… as the app or model made it",
                      "made_at": "2026-11-26 10:04", "model": "", "fit": 0.82,
                      "versions": [{"text": "…", "source": "…", "saved_at": "…"}]},
         "query": {…, "to": {"id": "…", "name": "…", "agency": "…",
                             "email": "…", "represents": "…"}},   # 9.3 addendum
         "blurb": {…}, "audience": {…},
         "comps": {"chosen": ["Dracula — Bram Stoker"], "own": "…"}}}}

No Qt.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.data import safe_store

FORMAT_VERSION = 1
KIND = "submission"            # <project>.submission.json
MAIN = "main"
DOCS = ("synopsis", "query", "blurb", "audience")
_lock = threading.RLock()


def path_for(project: Any) -> Path:
    """Where this project's drafts are kept."""
    from src.data import state_files
    return state_files.own_path(project, KIND, "submission")


def where(project: Any) -> str:
    """Where the drafts are kept, in words for the writer."""
    p = path_for(project)
    if getattr(project, "project_path", ""):
        return f"“{p.name}”, beside the project file (never in the manuscript)"
    return f"“{p.name}” in the app's own folder until the project is saved"


def scope_key(scope: Optional[str]) -> str:
    return scope or MAIN


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


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


def update(project: Any, change: Callable[[Dict[str, Any]], Any]) -> bool:
    """Load, ``change(data)`` in place, save; under the lock."""
    with _lock:
        data = load(project)
        if is_read_only(data):
            print("[submission] the drafts file is from a newer version; not saving")
            return False
        change(data)
        return safe_store.save(path_for(project), data)


def _manuscript(data: Dict[str, Any], scope: Optional[str]) -> Dict[str, Any]:
    m = data["manuscripts"].setdefault(scope_key(scope), {})
    if not isinstance(m, dict):
        m = data["manuscripts"][scope_key(scope)] = {}
    return m


def _doc(data: Dict[str, Any], scope: Optional[str], kind: str) -> Dict[str, Any]:
    m = _manuscript(data, scope)
    d = m.setdefault(kind, {})
    if not isinstance(d, dict):
        d = m[kind] = {}
    if not isinstance(d.get("versions"), list):
        d["versions"] = []
    return d


# ── Reading ────────────────────────────────────────────────────────────

def document(project: Any, scope: Optional[str], kind: str) -> Dict[str, Any]:
    """One document's entry (a copy; empty text when there is none)."""
    m = load(project)["manuscripts"].get(scope_key(scope), {})
    d = m.get(kind) if isinstance(m, dict) else None
    d = dict(d) if isinstance(d, dict) else {}
    d.setdefault("text", "")
    d["versions"] = [v for v in (d.get("versions") or []) if isinstance(v, dict)]
    return d


def text(project: Any, scope: Optional[str], kind: str) -> str:
    t = document(project, scope, kind).get("text")
    return t if isinstance(t, str) else ""


def is_edited(entry: Dict[str, Any]) -> bool:
    """The writer has changed the text since the app or model made it."""
    return (entry.get("text") or "").strip() != (entry.get("generated") or "").strip() \
        and bool((entry.get("text") or "").strip())


def comps(project: Any, scope: Optional[str]) -> Dict[str, Any]:
    m = load(project)["manuscripts"].get(scope_key(scope), {})
    c = m.get("comps") if isinstance(m, dict) else None
    c = dict(c) if isinstance(c, dict) else {}
    chosen = c.get("chosen")
    c["chosen"] = [x for x in chosen if isinstance(x, str)] if isinstance(chosen, list) else []
    c["own"] = c.get("own") if isinstance(c.get("own"), str) else ""
    return c


# ── Writing ────────────────────────────────────────────────────────────

def _keep(d: Dict[str, Any], new_text: str) -> bool:
    """Put the current text into the versions before it is replaced.
    Returns whether something was kept."""
    cur = d.get("text") if isinstance(d.get("text"), str) else ""
    if not cur.strip() or cur.strip() == (new_text or "").strip():
        return False
    if any(isinstance(v, dict) and (v.get("text") or "").strip() == cur.strip()
           for v in d["versions"]):
        return False                     # already kept
    d["versions"].append({"text": cur,
                          "source": "writer" if is_edited(d) else (d.get("source") or "template"),
                          "saved_at": now()})
    return True


def put_draft(project: Any, scope: Optional[str], kind: str, new_text: str,
              source: str, model: str = "", fit: Optional[float] = None,
              to: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """A new draft from the template or the model. The text it replaces is
    kept as an earlier version. ``to``: the agent a query letter is
    addressed to (9.3 addendum; left as it was when None). Returns
    {"saved": bool, "kept": bool}."""
    out = {"saved": False, "kept": False}

    def change(data):
        d = _doc(data, scope, kind)
        out["kept"] = _keep(d, new_text)
        d.update(text=new_text, generated=new_text, source=source, model=model,
                 made_at=now(), fit=fit)
        if to is not None:
            d["to"] = dict(to)
    out["saved"] = update(project, change)
    return out


def set_text(project: Any, scope: Optional[str], kind: str, new_text: str) -> bool:
    """The writer's edit. Stored as typed; nothing else changes."""
    def change(data):
        d = _doc(data, scope, kind)
        d["text"] = new_text
        d.setdefault("generated", "")
        d.setdefault("source", "writer")
    return update(project, change)


def set_to(project: Any, scope: Optional[str], to: Optional[Dict[str, str]]) -> bool:
    """Which agent the query letter is addressed to (9.3 addendum). An
    older app does not know the key and leaves it alone."""
    def change(data):
        _doc(data, scope, "query")["to"] = dict(to or {})
    return update(project, change)


def readdress(project: Any, scope: Optional[str], new_text: str,
              to: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """The query letter with a new greeting (9.3 addendum). The text it
    replaces is kept as an earlier version; a letter the writer hadn't
    edited stays unedited (its made text moves with it), an edited one
    stays the writer's. Returns {"saved": bool, "kept": bool}."""
    out = {"saved": False, "kept": False}

    def change(data):
        d = _doc(data, scope, "query")
        unedited = not is_edited(d)
        out["kept"] = _keep(d, new_text)
        d["text"] = new_text
        if unedited:
            d["generated"] = new_text
        d["to"] = dict(to or {})
    out["saved"] = update(project, change)
    return out


def restore(project: Any, scope: Optional[str], kind: str, index: int) -> Optional[str]:
    """Make an earlier version current; the current text is kept as a
    version first. Returns the restored text, or None."""
    out: Dict[str, Any] = {}

    def change(data):
        d = _doc(data, scope, kind)
        versions = d["versions"]
        if not 0 <= index < len(versions) or not isinstance(versions[index], dict):
            return
        chosen = versions[index].get("text") or ""
        _keep(d, chosen)
        d["text"] = chosen
        out["text"] = chosen
    update(project, change)
    return out.get("text")


def set_comps(project: Any, scope: Optional[str], chosen: List[str], own: str) -> bool:
    def change(data):
        m = _manuscript(data, scope)
        c = m.get("comps") if isinstance(m.get("comps"), dict) else {}
        c.update(chosen=list(chosen), own=own or "")
        m["comps"] = c
    return update(project, change)
