"""V.1: a voice fingerprint on every rating."""

import sqlite3
import time

import pytest

from src.ai import voice_fingerprint as vf
from src.data import voice_fingerprint_store as vfs
from src.data.rephrase_database import RephraseDatabase, _SCHEMA


TERSE = ("He ran. The door held. She waited by the stairs. Nobody came. "
         "The rain kept on. He did not look back. The car was gone. "
         "She lit the lamp. It smoked. He sat down hard.\n\n") * 3
LUSH = ("I remember the long summer evenings at my grandmother's house, when the light "
        "lay across the orchard like honey and I thought, foolishly, that it would last; "
        "I'd wander the rows until the bats came out — and then I'd run home, breathless, "
        "certain that something wonderful was waiting for me there. We were young; we "
        "believed everything... My brother said it was nonsense, but he came with me "
        "anyway, every single night, until the summer ended and the house was sold.\n\n") * 3


def test_fingerprint_fixed_order_and_pure():
    fp = vf.fingerprint(TERSE)
    assert fp.ok and fp.version == vf.VERSION
    assert len(fp.vector) == len(vf.MEASURES) == len(set(vf.MEASURES))
    assert all(isinstance(x, float) for x in fp.vector)
    assert vf.fingerprint(TERSE).vector == fp.vector          # same text, same numbers
    assert set(vf.LABELS) == set(vf.MEASURES)


def test_fingerprint_tells_voices_apart():
    a, b = vf.fingerprint(TERSE).as_dict(), vf.fingerprint(LUSH).as_dict()
    assert a["sentence_len_mean"] < b["sentence_len_mean"]
    assert b["first_person_pct"] > 50 > a["first_person_pct"]
    assert b["semicolons_per_100_sentences"] > a["semicolons_per_100_sentences"] == 0
    assert b["contractions_per_100_words"] > a["contractions_per_100_words"]


def test_too_little_text_is_unsorted():
    fp = vf.fingerprint("She left. He stayed.")
    assert fp.status == vf.STATUS_UNSORTED and fp.vector == [] and not fp.ok
    assert vf.vector_of("Short.") is None


def test_dialogue_share():
    text = TERSE + '"Come here," she said. "Now, before they see us and call the others."\n'
    assert vf.fingerprint(text).as_dict()["dialogue_pct"] > 0
    assert vf.fingerprint(TERSE).as_dict()["dialogue_pct"] == 0


def test_rating_text_uses_surrounding_narration():
    t = vf.rating_text("Before.", "The passage.", "After.")
    assert t.index("Before") < t.index("passage") < t.index("After")
    assert len(vf.rating_text("x" * 50000, "y", "")) < 7000


def test_fast_enough():
    text = (TERSE + LUSH) * 3                          # ~1,000 words
    t0 = time.perf_counter()
    for _ in range(20):
        vf.fingerprint(text)
    assert (time.perf_counter() - t0) / 20 < 0.05


# ── Storage ──────────────────────────────────────────────────────────

def test_new_database_fingerprints_new_ratings(tmp_path):
    db = RephraseDatabase(tmp_path / "new.db")
    assert db._voice_fp_ready
    rid = db.log_rephrase("The passage.", "A rewrite.", surrounding_before=TERSE,
                          rating="good", project_path="/p/book.json", character_name="Ann")
    short = db.log_rephrase("x", "y")
    other = db.log("a prompt", "a reply", source_type="chat_writing")
    rows = {r["id"]: r for r in vfs.fingerprinted_ratings(db, include_unsorted=True)}
    assert rows[rid]["status"] == "ok" and len(rows[rid]["vector"]) == len(vf.MEASURES)
    assert rows[rid]["project_path"] == "/p/book.json" and rows[rid]["character_name"] == "Ann"
    assert rows[short]["status"] == "unsorted"
    assert other not in rows
    assert [r["id"] for r in vfs.fingerprinted_ratings(db)] == [rid]
    assert not vfs.backup_path(db).exists()            # nothing to copy aside


def _old_database(path, n=30):
    """A ratings database as the app made it before V.1."""
    con = sqlite3.connect(path)
    con.executescript(_SCHEMA)
    for i in range(n):
        con.execute(
            "INSERT INTO rephrases (created_at, source_text, output_text, source_type, "
            "surrounding_before, surrounding_after, character_name, project_path, rating) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-01-01T00:00:00", f"Passage {i}.", f"Rewrite {i}.",
             "rephrase" if i % 3 else "corpus", TERSE if i % 2 else "", LUSH if i % 2 else "",
             "Ann" if i % 2 else "", "/p/a.json", "good"))
    con.commit()
    con.close()


def _dump(path):
    con = sqlite3.connect(path)
    cols = [r[1] for r in con.execute("PRAGMA table_info(rephrases)")]
    rows = con.execute("SELECT * FROM rephrases ORDER BY id").fetchall()
    con.close()
    return cols, rows


def test_old_database_gains_fingerprints_without_changing_a_row(tmp_path):
    path = tmp_path / "rephrase_history.db"
    _old_database(path)
    RephraseDatabase(path)              # the app's usual checks on open
    before = _dump(path)
    db = RephraseDatabase(path)
    assert not db._voice_fp_ready       # opening never copies or adds a table
    con = sqlite3.connect(path)
    assert con.execute("SELECT name FROM sqlite_master WHERE name=?", (vfs.TABLE,)).fetchone() is None
    con.close()
    assert vfs.missing_count(db) == 20

    n = vfs.backfill(db, batch=7)
    assert n == 20 and vfs.missing_count(db) == 0
    assert vfs.backup_path(db).exists()
    assert _dump(vfs.backup_path(db)) == before   # the copy is the database as it was
    assert _dump(path) == before                  # no row or column changed
    got = vfs.fingerprinted_ratings(db, include_unsorted=True)
    assert len(got) == 20
    assert {r["status"] for r in got} == {"ok", "unsorted"}
    assert all(r["project_path"] == "/p/a.json" for r in got)

    # Copied aside once only; a second run has nothing to do.
    stamp = vfs.backup_path(db).stat().st_mtime_ns
    assert vfs.backfill(db) == 0
    assert vfs.backup_path(db).stat().st_mtime_ns == stamp

    # New ratings are fingerprinted as they are saved from now on.
    rid = db.log_rephrase("New.", "Newer.", surrounding_before=LUSH)
    assert vfs.fingerprint_for(db, rid).ok
    assert vfs.missing_count(db) == 0


def test_backfill_resumes_after_a_stop(tmp_path):
    path = tmp_path / "r.db"
    _old_database(path)
    db = RephraseDatabase(path)
    calls = {"n": 0}

    def stop_after_one():
        calls["n"] += 1
        return calls["n"] > 1
    assert vfs.backfill(db, batch=5, should_stop=stop_after_one) == 5
    assert vfs.missing_count(db) == 15
    assert vfs.backfill(db, batch=5) == 15
    assert vfs.missing_count(db) == 0


def test_no_table_when_the_copy_cannot_be_made(tmp_path, monkeypatch):
    path = tmp_path / "r.db"
    _old_database(path)
    before = _dump(path)
    db = RephraseDatabase(path)
    monkeypatch.setattr(vfs, "_DISK_MARGIN", 1 << 62)      # "disk full"
    assert vfs.backfill(db) == 0
    assert not vfs.backup_path(db).exists()
    assert not list(tmp_path.glob("*.partial"))
    con = sqlite3.connect(path)
    assert con.execute("SELECT name FROM sqlite_master WHERE name=?", (vfs.TABLE,)).fetchone() is None
    con.close()
    assert _dump(path) == before
    # Saving a rating still works, and is caught up later.
    rid = db.log_rephrase("A.", "B.", surrounding_before=TERSE)
    assert rid
    monkeypatch.setattr(vfs, "_DISK_MARGIN", 0)
    assert vfs.backfill(db) == 21


def test_stale_partial_copy_is_replaced(tmp_path):
    path = tmp_path / "r.db"
    _old_database(path)
    db = RephraseDatabase(path)
    partial = vfs.backup_path(db).with_name(vfs.backup_path(db).name + ".partial")
    partial.write_bytes(b"half a copy")
    vfs.backfill(db)
    assert not partial.exists()
    assert _dump(vfs.backup_path(db))[1]


def test_older_app_still_reads_the_database(tmp_path):
    """What an app from before V.1 does on open and read still works, and
    sees the same table it always did."""
    path = tmp_path / "r.db"
    _old_database(path)
    db = RephraseDatabase(path)
    vfs.backfill(db)
    db.log_rephrase("New.", "Newer.", surrounding_before=TERSE)
    con = sqlite3.connect(path)
    con.executescript(_SCHEMA)                      # the old app's schema step
    cols = [r[1] for r in con.execute("PRAGMA table_info(rephrases)")]
    assert cols == ["id", "created_at", "source_text", "output_text", "source_type", "style",
                    "voice", "surrounding_before", "surrounding_after", "character_name",
                    "genre", "accepted", "rating", "project_path", "notes", "system_prompt"]
    assert con.execute("SELECT COUNT(*) FROM rephrases").fetchone()[0] == 31
    # an older app deletes a rating: allowed, and the fingerprint is simply ignored
    con.execute("DELETE FROM rephrases WHERE id = 2")
    con.commit()
    con.close()
    assert 2 not in {r["id"] for r in vfs.fingerprinted_ratings(db, include_unsorted=True)}


def test_background_backfill(tmp_path):
    path = tmp_path / "r.db"
    _old_database(path)
    db = RephraseDatabase(path)
    t = vfs.start_background_backfill(db)
    t.join(20)
    assert not t.is_alive()
    assert vfs.missing_count(db) == 0


def test_voice_column_left_alone(tmp_path):
    db = RephraseDatabase(tmp_path / "v.db")
    rid = db.log_rephrase("A.", "B.", voice="adelphus", surrounding_before=TERSE)
    con = sqlite3.connect(tmp_path / "v.db")
    assert con.execute("SELECT voice FROM rephrases WHERE id=?", (rid,)).fetchone()[0] == "adelphus"
    con.close()
