"""Voice fingerprints of ratings, stored beside them (piece V.1).

A side table, ``voice_fingerprints``, in the ratings database, linked by
the rating's id (``rephrases.id``). The ``rephrases`` table, its columns
and its rows are never altered; an older app ignores the extra table.
The rating's ``project_path`` and ``character_name`` stay where they are,
in ``rephrases``; :func:`fingerprinted_ratings` joins them in.

Which rows get one: :data:`FINGERPRINT_SOURCE_TYPES` (rated rewrites of
prose). Chat, critique, plot and catalog corpus rows are prompts or
downloaded text, not ratings of the writer's prose, and are left out.

Safety (rule 15): before the table is first created in a database that
already holds rows, the database is copied aside once, to
``<name>.before-voice`` (SQLite's backup API, so the copy is consistent
even while the app writes; written to a temporary name and renamed when
complete). If the copy cannot be made (not enough disk space, an error),
the table is not created and nothing else changes; the next start tries
again. A database with no rows gets the table at once (nothing to keep).

Existing ratings get fingerprints by :func:`backfill`: in batches, each
committed on its own, so it resumes where it stopped. The app runs it
on a background thread a little after start-up
(:func:`start_background_backfill`); V.2 can call :func:`backfill`
directly before grouping.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from src.ai import voice_fingerprint as vf

TABLE = "voice_fingerprints"
BACKUP_SUFFIX = ".before-voice"
FINGERPRINT_SOURCE_TYPES = ("rephrase",)
BATCH = 200
_DISK_MARGIN = 512 * 1024 * 1024        # keep half a gigabyte free after the copy

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    rephrase_id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL,
    status TEXT NOT NULL,
    vector TEXT NOT NULL DEFAULT '',
    word_count INTEGER DEFAULT 0,
    sentence_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT ''
);
"""

_lock = threading.Lock()


# ── Table and the copy aside ─────────────────────────────────────────

def backup_path(db) -> Path:
    p = Path(db.db_path)
    return p.with_name(p.name + BACKUP_SUFFIX)


def _table_exists(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (TABLE,)).fetchone() is not None


def prepare_on_open(db) -> bool:
    """Called when the database opens. True when the table is ready. Never
    copies or creates anything in a database that has rows (that waits for
    the background job); a new, empty database gets the table at once."""
    try:
        conn = db._conn()
        if _table_exists(conn):
            return True
        if conn.execute("SELECT 1 FROM rephrases LIMIT 1").fetchone() is None:
            with conn:
                conn.executescript(_SCHEMA)
            return True
    except Exception as e:
        print(f"[voice fingerprint] not ready: {e}")
    return False


def _copy_aside(db) -> bool:
    """Copy the database to ``<name>.before-voice`` once. True when the
    copy exists (made now or before)."""
    target = backup_path(db)
    if target.exists():
        return True
    src_path = Path(db.db_path)
    partial = target.with_name(target.name + ".partial")
    try:
        if partial.exists():
            partial.unlink()               # an interrupted copy from an earlier run
        size = src_path.stat().st_size
        if shutil.disk_usage(src_path.parent).free < size + _DISK_MARGIN:
            print("[voice fingerprint] not enough disk space to copy the ratings "
                  "database aside; fingerprints wait")
            return False
        src = sqlite3.connect(str(src_path))
        dst = sqlite3.connect(str(partial))
        try:
            # In steps, so the app's own writes are not held up for long;
            # SQLite restarts the copy if one lands in the middle.
            src.backup(dst, pages=4096, sleep=0.01)
            n_src = src.execute("SELECT COUNT(*) FROM rephrases").fetchone()[0]
            n_dst = dst.execute("SELECT COUNT(*) FROM rephrases").fetchone()[0]
        finally:
            dst.close()
            src.close()
        if n_dst < n_src:
            raise RuntimeError(f"copy has {n_dst} rows, database has {n_src}")
        os.replace(partial, target)
        print(f"[voice fingerprint] ratings database copied aside to {target}")
        return True
    except Exception as e:
        print(f"[voice fingerprint] could not copy the ratings database aside: {e}")
        try:
            if partial.exists():
                partial.unlink()
        except Exception:
            pass
        return False


def ensure_table(db) -> bool:
    """The table, created after the copy aside when the database has rows."""
    if getattr(db, "_voice_fp_ready", False):
        return True
    with _lock:
        conn = db._conn()
        if not _table_exists(conn):
            has_rows = conn.execute("SELECT 1 FROM rephrases LIMIT 1").fetchone() is not None
            if has_rows and not _copy_aside(db):
                return False
            with conn:
                conn.executescript(_SCHEMA)
        db._voice_fp_ready = True
        return True


# ── Writing fingerprints ─────────────────────────────────────────────

def _row_values(rid: int, fp: "vf.Fingerprint"):
    return (int(rid), fp.version, fp.status, json.dumps(fp.vector) if fp.ok else "",
            fp.word_count, fp.sentence_count, datetime.now().isoformat(timespec="seconds"))


_INSERT = (f"INSERT OR REPLACE INTO {TABLE} (rephrase_id, version, status, vector, "
           "word_count, sentence_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)")


def record_new_rating(db, row_id: int, source_type: str, before: str,
                      source: str, after: str) -> bool:
    """Fingerprint a rating as it is saved. Does nothing until the table
    is ready (the background job catches the row up later)."""
    try:
        if not row_id or source_type not in FINGERPRINT_SOURCE_TYPES:
            return False
        if not getattr(db, "_voice_fp_ready", False):
            if not _table_exists(db._conn()):      # made since this copy opened?
                return False
            db._voice_fp_ready = True
        fp = vf.fingerprint(vf.rating_text(before, source, after))
        with db._conn() as c:
            c.execute(_INSERT, _row_values(row_id, fp))
        return True
    except Exception as e:
        print(f"[voice fingerprint] not saved for rating {row_id}: {e}")
        return False


def _missing(conn, limit: int, source_types: Iterable[str]) -> List[sqlite3.Row]:
    types = list(source_types)
    marks = ",".join("?" * len(types))
    return conn.execute(
        f"SELECT r.id, r.source_text, r.surrounding_before, r.surrounding_after "
        f"FROM rephrases r LEFT JOIN {TABLE} f ON f.rephrase_id = r.id "
        f"WHERE r.source_type IN ({marks}) AND (f.rephrase_id IS NULL OR f.version != ?) "
        f"ORDER BY r.id LIMIT ?", types + [vf.VERSION, int(limit)]).fetchall()


def missing_count(db, source_types: Iterable[str] = FINGERPRINT_SOURCE_TYPES) -> int:
    """Ratings still without a fingerprint of the current version (all of
    them when the table is not there yet)."""
    conn = db._conn()
    types = list(source_types)
    marks = ",".join("?" * len(types))
    if not _table_exists(conn):
        return int(conn.execute(f"SELECT COUNT(*) FROM rephrases WHERE source_type IN ({marks})",
                                types).fetchone()[0])
    return int(conn.execute(
        f"SELECT COUNT(*) FROM rephrases r LEFT JOIN {TABLE} f ON f.rephrase_id = r.id "
        f"WHERE r.source_type IN ({marks}) AND (f.rephrase_id IS NULL OR f.version != ?)",
        types + [vf.VERSION]).fetchone()[0])


def backfill(db, *, batch: int = BATCH, should_stop: Optional[Callable[[], bool]] = None,
             pause: float = 0.0, source_types: Iterable[str] = FINGERPRINT_SOURCE_TYPES) -> int:
    """Fingerprint every rating that has none (or an older version's).
    Batches are committed one at a time, so stopping loses nothing and the
    next run carries on. Returns the number fingerprinted now."""
    if not ensure_table(db):
        return 0
    done = 0
    conn = db._conn()
    while True:
        if should_stop and should_stop():
            break
        rows = _missing(conn, batch, source_types)
        if not rows:
            break
        values = [_row_values(r["id"], vf.fingerprint(vf.rating_text(
                      r["surrounding_before"] or "", r["source_text"] or "",
                      r["surrounding_after"] or "")))
                  for r in rows]
        with conn:
            conn.executemany(_INSERT, values)
        done += len(values)
        if len(rows) < batch:
            break
        if pause:
            time.sleep(pause)
    return done


# ── Reading (for V.2) ────────────────────────────────────────────────

def fingerprint_for(db, row_id: int) -> Optional["vf.Fingerprint"]:
    """A rating's fingerprint, computed and stored the first time it is
    asked for. None when the row does not exist."""
    conn = db._conn()
    if ensure_table(db):
        got = conn.execute(f"SELECT * FROM {TABLE} WHERE rephrase_id = ?", (int(row_id),)).fetchone()
        if got is not None and got["version"] == vf.VERSION:
            return _to_fp(got)
    r = conn.execute("SELECT source_text, surrounding_before, surrounding_after "
                     "FROM rephrases WHERE id = ?", (int(row_id),)).fetchone()
    if r is None:
        return None
    fp = vf.fingerprint(vf.rating_text(r["surrounding_before"] or "", r["source_text"] or "",
                                       r["surrounding_after"] or ""))
    if getattr(db, "_voice_fp_ready", False):
        with conn:
            conn.execute(_INSERT, _row_values(row_id, fp))
    return fp


def _to_fp(row) -> "vf.Fingerprint":
    vector = json.loads(row["vector"]) if row["vector"] else []
    return vf.Fingerprint(version=row["version"], status=row["status"], vector=vector,
                          word_count=row["word_count"] or 0,
                          sentence_count=row["sentence_count"] or 0)


def fingerprinted_ratings(db, *, include_unsorted: bool = False) -> List[Dict[str, Any]]:
    """Every rating with a current fingerprint, with what V.2 groups by:
    ``id, project_path, character_name, rating, accepted, source_type,
    status, vector`` (a list in ``MEASURES`` order; [] when unsorted)."""
    conn = db._conn()
    if not _table_exists(conn):
        return []
    where = "" if include_unsorted else "AND f.status = 'ok'"
    rows = conn.execute(
        f"SELECT r.id, r.project_path, r.character_name, r.rating, r.accepted, "
        f"r.source_type, f.status, f.vector FROM rephrases r "
        f"JOIN {TABLE} f ON f.rephrase_id = r.id WHERE f.version = ? {where} "
        f"ORDER BY r.id", (vf.VERSION,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["vector"] = json.loads(d["vector"]) if d["vector"] else []
        out.append(d)
    return out


# ── Background job ───────────────────────────────────────────────────

_job: Dict[str, Any] = {"thread": None, "stop": False}


def start_background_backfill(db=None) -> Optional[threading.Thread]:
    """Run :func:`backfill` on a background thread (once per session).
    Quitting the app mid-way loses nothing: the next start resumes."""
    t = _job.get("thread")
    if t is not None and t.is_alive():
        return t
    def run():
        nonlocal db
        try:
            if db is None:       # opening the database (its own checks) off the GUI thread too
                from src.data.rephrase_database import get_rephrase_database
                db = get_rephrase_database()
            n = backfill(db, should_stop=lambda: _job["stop"], pause=0.05)
            if n:
                print(f"[voice fingerprint] {n} rating(s) fingerprinted")
        except Exception as e:
            print(f"[voice fingerprint] background fingerprints stopped: {e}")
        finally:
            try:
                c = getattr(getattr(db, "_local", None), "conn", None)
                if c is not None:
                    c.close()
                    db._local.conn = None
            except Exception:
                pass

    _job["stop"] = False
    t = threading.Thread(target=run, name="voice-fingerprints", daemon=True)
    _job["thread"] = t
    t.start()
    return t


def stop_background_backfill(timeout: float = 2.0) -> None:
    _job["stop"] = True
    t = _job.get("thread")
    if t is not None:
        t.join(timeout)
