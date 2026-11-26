"""Where the voice groups live, and the check that keeps them current
(piece V.2).

The groups, the writer's own groups and placed sources, the proposals
waiting for the writer (V.5) and the events for naming (V.3) are one
small JSON file, ``~/.creativeos/voice_groups.json``, shared across
projects like the ratings (:func:`groups_path`; tests point it at a
temporary folder). The ratings database is only read: no table or row is
added or changed. A missing, empty or damaged file means no groups yet,
and every rating is used as today. The file is written to a temporary
name and renamed, so a crash mid-write leaves the last good one.

Which ratings are grouped: rated rewrites with a current fingerprint
(V.1), a project path, and not made from a corpus (``synthesized=`` in
their notes). Everything else stays Unsorted and is used as today.

:func:`run_check` rebuilds when it is due (a source became ready, the
ratings grew by about a fifth) or when asked (``force=True``). The app
runs it once on a background thread after V.1's start-up fingerprints
(:func:`start_background_check`), never on the GUI thread.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.ai import voice_fingerprint as vf
from src.ai import voice_groups as vg

_lock = threading.RLock()


def groups_path() -> Path:
    return Path.home() / ".creativeos" / "voice_groups.json"


def load_state() -> Dict[str, Any]:
    """The stored groups, or an empty state (never an error)."""
    try:
        data = json.loads(groups_path().read_text(encoding="utf-8"))
    except Exception:
        data = None
    return vg.normalise_state(data)


def save_state(state: Dict[str, Any]) -> bool:
    path = groups_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"[voice groups] not saved: {e}")
        return False


def read_rows(db) -> List[Dict[str, Any]]:
    """Every rating with a current fingerprint, with its notes, read only."""
    from src.data import voice_fingerprint_store as vfs
    conn = db._conn()
    if not vfs._table_exists(conn):
        return []
    rows = conn.execute(
        f"SELECT r.id, r.project_path, r.character_name, r.notes, f.status, f.vector "
        f"FROM rephrases r JOIN {vfs.TABLE} f ON f.rephrase_id = r.id "
        f"WHERE f.version = ? AND f.status = 'ok' ORDER BY r.id", (vf.VERSION,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["vector"] = json.loads(d["vector"]) if d["vector"] else []
        except ValueError:
            d["vector"] = []
        out.append(d)
    return out


def _db(db):
    if db is None:
        from src.data.rephrase_database import get_rephrase_database
        db = get_rephrase_database()
    return db


def run_check(db=None, *, force: bool = False, now: Optional[str] = None) -> Dict[str, Any]:
    """Regroup when due (or when ``force``), save, and return the state."""
    with _lock:
        state = load_state()
        rows = read_rows(_db(db))
        if not force and not vg.needs_check(rows, state):
            return state
        state = vg.regroup(rows, state, now=now)
        save_state(state)
        return state


def apply(change: Callable[..., Any], *args, db=None, **kwargs) -> Dict[str, Any]:
    """A change by the writer (V.5): e.g. ``apply(vg.rename_group, "g2",
    "Teller")``. Loads, applies, regroups with the change in place, saves.
    The state before is returned beside it for undo: ``(after, before)``."""
    with _lock:
        before = load_state()
        got = change(before, *args, **kwargs)
        state = got[0] if isinstance(got, tuple) else got
        state = vg.regroup(read_rows(_db(db)), state)
        save_state(state)
        return state, before


def restore(state: Dict[str, Any]) -> bool:
    """Undo: put back a state returned by :func:`apply`."""
    with _lock:
        return save_state(vg.normalise_state(state))


def membership(db=None) -> Dict[int, str]:
    """Every fingerprinted rating's group id, or ``"unsorted"``."""
    return vg.membership(read_rows(_db(db)), load_state())


def group_for(project_path: str, character_name: str = "", vector=None) -> Optional[str]:
    """The group a passage from this project and narrator learns from, or
    None (Unsorted: the whole store, as today)."""
    return vg.group_for(load_state(), project_path, character_name, vector)


# ── Background check at start-up ─────────────────────────────────────

_job: Dict[str, Any] = {"thread": None}


def start_background_check(db=None) -> Optional[threading.Thread]:
    """Run :func:`run_check` on a background thread, after V.1's start-up
    fingerprints have finished. Never blocks the caller."""
    t = _job.get("thread")
    if t is not None and t.is_alive():
        return t

    def run():
        nonlocal db
        try:
            from src.data import voice_fingerprint_store as vfs
            fp = vfs._job.get("thread")
            if fp is not None and fp.is_alive():
                fp.join()
            db = _db(db)
            state = run_check(db)
            n = len(state.get("groups") or {})
            if n:
                print(f"[voice groups] {n} group(s)")
            from src.ai import voice_naming      # V.3: names, when a model is free
            if voice_naming.is_app_db(db):
                voice_naming.name_groups(db)
        except Exception as e:
            print(f"[voice groups] check stopped: {e}")
        finally:
            try:
                c = getattr(getattr(db, "_local", None), "conn", None)
                if c is not None:
                    c.close()
                    db._local.conn = None
            except Exception:
                pass

    t = threading.Thread(target=run, name="voice-groups", daemon=True)
    _job["thread"] = t
    t.start()
    return t
