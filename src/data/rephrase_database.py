"""Learning database — captures input/output pairs from every place in
CreativeOS where the user evaluates AI output, so they can later
fine-tune a model on their own taste and voice.

Storage is opt-in (gated by ``enable_rephrase_data_collection`` /
``enable_chat_data_collection`` in CreativeOS settings) and lives in
a per-user SQLite database at ``~/.creativeos/rephrase_history.db``
(legacy filename kept for backwards compat).

Each row has a ``source_type`` so the training tool can combine or
filter freely:

  * ``rephrase``    — accepted/rejected suggestions from the Rephrase tool
  * ``chat_writing`` — chat responses tagged as writing assistance
  * ``chat_general`` — chat responses in general / lookup modes
  * ``corpus``      — synthetic pairs derived from user-uploaded writing
  * ``agent``       — outputs from other agents (worldbuilding, etc.)

Other recorded fields:
  * source_text, output_text — the input/output pair
  * style, character_name, genre — context tags
  * surrounding_before / surrounding_after — narrative context
  * accepted — whether the user actually used the suggestion
  * rating — excellent / good / neutral / poor / bad
  * project_path, notes, created_at

The exporter combines selected source types and writes JSONL for SFT
or DPO training.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_DB_PATH = Path.home() / ".creativeos" / "rephrase_history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rephrases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source_text TEXT NOT NULL,
    output_text TEXT NOT NULL,
    source_type TEXT DEFAULT 'rephrase',
    style TEXT DEFAULT '',
    voice TEXT DEFAULT '',
    surrounding_before TEXT DEFAULT '',
    surrounding_after TEXT DEFAULT '',
    character_name TEXT DEFAULT '',
    genre TEXT DEFAULT '',
    accepted INTEGER DEFAULT 1,
    rating TEXT DEFAULT 'neutral',
    project_path TEXT DEFAULT '',
    notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_rephrases_created_at ON rephrases(created_at);
CREATE INDEX IF NOT EXISTS idx_rephrases_source_type ON rephrases(source_type);
CREATE INDEX IF NOT EXISTS idx_rephrases_genre ON rephrases(genre);
CREATE INDEX IF NOT EXISTS idx_rephrases_character ON rephrases(character_name);
CREATE INDEX IF NOT EXISTS idx_rephrases_voice ON rephrases(voice);
CREATE INDEX IF NOT EXISTS idx_rephrases_rating ON rephrases(rating);
"""

# Source-type taxonomy
SOURCE_REPHRASE = "rephrase"
SOURCE_CHAT_WRITING = "chat_writing"
SOURCE_CHAT_GENERAL = "chat_general"
SOURCE_CORPUS = "corpus"
SOURCE_AGENT = "agent"
SOURCE_WORLDBUILDING = "worldbuilding"
SOURCE_CHARACTER = "character"
SOURCE_PLOT = "plot"
SOURCE_TYPES = (SOURCE_REPHRASE, SOURCE_CHAT_WRITING, SOURCE_CHAT_GENERAL,
                SOURCE_CORPUS, SOURCE_AGENT,
                SOURCE_WORLDBUILDING, SOURCE_CHARACTER, SOURCE_PLOT)

# Rating taxonomy — kept in sync with src.ai.conversation_store.ConversationRating
# so the same vocabulary is used across chat and rephrase data.
RATING_VALUES = ("excellent", "good", "neutral", "poor", "bad")
POSITIVE_RATINGS = ("excellent", "good")
NEGATIVE_RATINGS = ("poor", "bad")


class RephraseDatabase:
    """Thread-safe SQLite wrapper around the rephrase history."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        """Return a per-thread SQLite connection. SQLite connections aren't
        safe to share across threads, so we cache one per thread.
        """
        c = getattr(self._local, 'conn', None)
        if c is None:
            c = sqlite3.connect(str(self.db_path))
            c.row_factory = sqlite3.Row
            self._local.conn = c
        return c

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)
            # Migration: older rows didn't have a rating column. Add it
            # and default existing accepted rows to 'good' so they're
            # still useful as positive training data; reject rows stay
            # 'neutral' until the user re-rates.
            cur = c.execute("PRAGMA table_info(rephrases)")
            cols = {row[1] for row in cur.fetchall()}
            if "rating" not in cols:
                c.execute("ALTER TABLE rephrases ADD COLUMN rating TEXT DEFAULT 'neutral'")
                c.execute(
                    "UPDATE rephrases SET rating = 'good' "
                    "WHERE accepted = 1 AND (rating IS NULL OR rating = '')")
            if "source_type" not in cols:
                # Older rows are all rephrase data
                c.execute(
                    "ALTER TABLE rephrases ADD COLUMN source_type "
                    "TEXT DEFAULT 'rephrase'")
                c.execute("UPDATE rephrases SET source_type = 'rephrase' "
                          "WHERE source_type IS NULL OR source_type = ''")
            if "voice" not in cols:
                # New column: capture the author/character voice
                # explicitly so the trainer can condition on it
                c.execute(
                    "ALTER TABLE rephrases ADD COLUMN voice TEXT DEFAULT ''")

            # Backfill: pacing-synth rows used to bake "Rewrite the
            # following passage to match X pacing… Keep the meaning
            # intact:\n\n<passage>" into ``source_text``, then the
            # trainer's plot/pacing template wrapped that AGAIN
            # with another instruction at render time → doubled
            # prompts. New rows skip the framing; existing rows
            # are repaired here. The match is anchored on the
            # exact prefix the old synthesiser emitted, so
            # legitimate user content isn't at risk. Idempotent:
            # subsequent runs find no rows whose source_text
            # still starts with the legacy prefix.
            cur = c.execute(
                "SELECT id, source_text FROM rephrases "
                "WHERE source_type = ? "
                "AND notes LIKE '%pacing_target=%' "
                "AND source_text LIKE 'Rewrite the following passage to match%Keep the meaning intact:__%'",
                (SOURCE_PLOT,))
            to_fix = cur.fetchall()
            if to_fix:
                import re as _re
                # The framing ends with "Keep the meaning intact:\n\n"
                # — the passage starts after the double newline.
                # Use re.split with the exact suffix so we don't
                # accidentally lop off legitimate prose that
                # contains the same words elsewhere.
                splitter = _re.compile(
                    r"^Rewrite the following passage to match "
                    r".*?Keep the meaning intact:\n\n",
                    flags=_re.DOTALL)
                for rid, st in to_fix:
                    stripped = splitter.sub("", st or "", count=1)
                    if stripped and stripped != st:
                        c.execute(
                            "UPDATE rephrases SET source_text = ? "
                            "WHERE id = ?",
                            (stripped, int(rid)))

            # Backfill: catalog corpora used to land as source_type
            # 'corpus' regardless of their declared purpose, because
            # corpus_downloader always called ``log_corpus_pair``.
            # That meant a BookSum download (purpose='plot') wouldn't
            # appear in the "plot" filter / source-type bucket. The
            # downloader is now purpose-aware, but rows ingested
            # before that fix retain the wrong source_type. The notes
            # column carries ``purpose=<x>`` so we can repair them in
            # place without re-downloading anything. Idempotent — a
            # second run finds zero candidates because the first run
            # cleared them.
            for purpose, sst in (("plot", SOURCE_PLOT),
                                  ("character", SOURCE_CHARACTER),
                                  ("worldbuilding", SOURCE_WORLDBUILDING)):
                c.execute(
                    "UPDATE rephrases SET source_type = ? "
                    "WHERE source_type = ? AND notes LIKE ?",
                    (sst, SOURCE_CORPUS, f"%purpose={purpose}%"))

    # ── Writes ──

    def log(
        self,
        source_text: str,
        output_text: str,
        *,
        source_type: str = SOURCE_REPHRASE,
        style: str = "",
        voice: str = "",
        surrounding_before: str = "",
        surrounding_after: str = "",
        character_name: str = "",
        genre: str = "",
        accepted: bool = True,
        rating: str = "neutral",
        project_path: str = "",
        notes: str = "",
    ) -> int:
        """Insert one row tagged with ``source_type``.

        ``rating`` is one of RATING_VALUES (excellent | good | neutral |
        poor | bad). Negative ratings (poor / bad) are stored deliberately
        so DPO-style preference training can use them as "rejected"
        samples paired with positive rows for the same source.
        """
        if not source_text.strip() or not output_text.strip():
            return 0
        if rating not in RATING_VALUES:
            rating = "neutral"
        if source_type not in SOURCE_TYPES:
            source_type = SOURCE_REPHRASE
        ts = datetime.now().isoformat(timespec='seconds')
        with self._conn() as c:
            cur = c.execute(
                """
                INSERT INTO rephrases
                  (created_at, source_text, output_text, source_type, style,
                   voice, surrounding_before, surrounding_after,
                   character_name, genre, accepted, rating,
                   project_path, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, source_text, output_text, source_type, style,
                 voice, surrounding_before, surrounding_after,
                 character_name, genre, 1 if accepted else 0, rating,
                 project_path, notes),
            )
            return cur.lastrowid or 0

    # Convenience aliases — keep call sites readable

    def log_rephrase(self, source_text: str, output_text: str, **kw) -> int:
        return self.log(source_text, output_text,
                        source_type=SOURCE_REPHRASE, **kw)

    def log_chat(self, prompt: str, response: str,
                 mode: str = "general", **kw) -> int:
        """Log a chat turn. ``mode`` is the chat mode label
        ('writer', 'critique', 'general', etc.); we route writing-aware
        modes to ``chat_writing`` and the rest to ``chat_general``.
        """
        writing_modes = {"writer", "writing", "critique", "creative",
                         "story", "draft"}
        st = (SOURCE_CHAT_WRITING if mode.lower() in writing_modes
              else SOURCE_CHAT_GENERAL)
        notes = kw.pop("notes", "")
        if mode and mode not in notes:
            notes = (f"chat_mode={mode} " + notes).strip()
        return self.log(prompt, response, source_type=st,
                        notes=notes, **kw)

    def log_corpus_pair(self, prompt: str, completion: str,
                        title: str = "", **kw) -> int:
        """Log a synthetic example derived from user-uploaded writing."""
        notes = kw.pop("notes", "")
        if title and title not in notes:
            notes = f"corpus_title={title} {notes}".strip()
        # Corpus rows default to 'good' so they're included in SFT exports.
        kw.setdefault("rating", "good")
        return self.log(prompt, completion, source_type=SOURCE_CORPUS,
                        notes=notes, **kw)

    def log_worldbuilding(self, prompt: str, completion: str,
                          element_type: str = "", **kw) -> int:
        """Log a worldbuilding example.

        ``element_type`` is the kind of element (faction, culture,
        magic_system, religion, etc.). Stored in notes so the trainer
        can shape per-type prompts. Used to teach a model to GENERATE
        worldbuilding elements from short briefs.
        """
        notes = kw.pop("notes", "")
        if element_type:
            notes = f"element={element_type} {notes}".strip()
        kw.setdefault("rating", "good")
        return self.log(prompt, completion, source_type=SOURCE_WORLDBUILDING,
                        notes=notes, **kw)

    def log_character(self, prompt: str, completion: str,
                      character_name: str = "", **kw) -> int:
        """Log a character-generation example.

        Used to teach a model to GENERATE characters (or expand
        skeletons into full profiles) from a short brief.
        """
        kw["character_name"] = character_name or kw.get("character_name", "")
        kw.setdefault("rating", "good")
        return self.log(prompt, completion, source_type=SOURCE_CHARACTER, **kw)

    def log_plot(self, prompt: str, completion: str, **kw) -> int:
        """Log a plot-generation example (premise → outline / story)."""
        kw.setdefault("rating", "good")
        return self.log(prompt, completion, source_type=SOURCE_PLOT, **kw)

    def update_rating(self, row_id: int, rating: str) -> bool:
        """Re-rate an existing row (e.g. user changed their mind)."""
        if rating not in RATING_VALUES:
            return False
        with self._conn() as c:
            cur = c.execute(
                "UPDATE rephrases SET rating = ? WHERE id = ?",
                (rating, row_id))
            return cur.rowcount > 0

    def clear_all(self) -> int:
        """Delete every row. Returns the number deleted."""
        with self._conn() as c:
            cur = c.execute("DELETE FROM rephrases")
            return cur.rowcount

    def catalog_rows_summary(self) -> Dict[str, Any]:
        """Summarize rows ingested via the catalog downloader.

        Catalog-downloaded rows have ``corpus_id=<id>`` in their notes
        (set by ``corpus_downloader._download_one``). User uploads,
        characters, worldbuilding and plot rows do not, so this is a
        clean way to identify the catalog subset for the rebuild flow.

        Returns ``{"total": int, "by_id": {corpus_id: count, ...}}``.
        """
        import re
        with self._conn() as c:
            cur = c.execute(
                "SELECT notes, COUNT(*) AS n FROM rephrases "
                "WHERE notes LIKE '%corpus_id=%' GROUP BY notes")
            by_id: Dict[str, int] = {}
            total = 0
            for row in cur.fetchall():
                m = re.search(r'corpus_id=(\S+)', row["notes"] or "")
                if not m:
                    continue
                cid = m.group(1)
                by_id[cid] = by_id.get(cid, 0) + int(row["n"])
                total += int(row["n"])
        return {"total": total, "by_id": by_id}

    def delete_catalog_rows(self) -> int:
        """Delete every row whose notes contain ``corpus_id=`` — i.e.
        every row inserted by the catalog downloader. User uploads,
        manually-ingested project text, and character/worldbuilding/
        plot rows are preserved.
        """
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM rephrases WHERE notes LIKE '%corpus_id=%'")
            return cur.rowcount

    def delete_one(self, row_id: int) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM rephrases WHERE id = ?", (row_id,))
            return cur.rowcount > 0

    # ── Reads ──

    def count(self) -> int:
        with self._conn() as c:
            cur = c.execute("SELECT COUNT(*) FROM rephrases")
            return int(cur.fetchone()[0])

    def all_rows(self, limit: Optional[int] = None,
                 only_accepted: bool = True) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM rephrases"
        params: List[Any] = []
        if only_accepted:
            sql += " WHERE accepted = 1"
        sql += " ORDER BY created_at DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        with self._conn() as c:
            cur = c.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def stats(self) -> Dict[str, Any]:
        """Return a summary of database contents — total rows, counts by
        genre and character. Used by the training tool to brief the user.
        """
        with self._conn() as c:
            total = int(c.execute("SELECT COUNT(*) FROM rephrases").fetchone()[0])
            accepted = int(c.execute(
                "SELECT COUNT(*) FROM rephrases WHERE accepted = 1"
            ).fetchone()[0])
            by_genre = {
                r['genre'] or '(none)': r['n']
                for r in c.execute(
                    "SELECT genre, COUNT(*) AS n FROM rephrases "
                    "GROUP BY genre ORDER BY n DESC")
            }
            by_char = {
                r['character_name'] or '(none)': r['n']
                for r in c.execute(
                    "SELECT character_name, COUNT(*) AS n FROM rephrases "
                    "GROUP BY character_name ORDER BY n DESC LIMIT 10")
            }
            by_rating = {
                r['rating'] or 'neutral': r['n']
                for r in c.execute(
                    "SELECT rating, COUNT(*) AS n FROM rephrases "
                    "GROUP BY rating")
            }
            # Pairs of (positive output, negative output) for the same
            # source — i.e. how many DPO training pairs we could build.
            pair_count = int(c.execute(
                """
                SELECT COUNT(*) FROM rephrases p
                WHERE p.rating IN ('excellent', 'good')
                  AND EXISTS (
                    SELECT 1 FROM rephrases n
                    WHERE n.source_text = p.source_text
                      AND n.rating IN ('poor', 'bad'))
                """).fetchone()[0])
            return {
                "total": total,
                "accepted": accepted,
                "by_genre": by_genre,
                "top_characters": by_char,
                "by_rating": by_rating,
                "dpo_pairs_available": pair_count,
            }

    def counts_by_source(self,
                         min_rating: Optional[str] = None,
                         only_accepted: bool = False) -> Dict[str, int]:
        """Return {source_type: count} so the training UI can show what's
        available before the user picks which to combine.

        Args:
            min_rating: If given, only count rows whose rating meets this
                threshold (same scale as ``export_jsonl``). The training
                setup log uses this to show *eligible* counts per source
                — i.e. what's actually going to feed the trainer after
                the rating filter — rather than total rows on disk.
            only_accepted: If True, restrict to rows with ``accepted=1``.
                Matches the default behavior of ``export_jsonl``.
        """
        out = {st: 0 for st in SOURCE_TYPES}
        sql = ("SELECT source_type, COUNT(*) AS n FROM rephrases ")
        clauses: List[str] = []
        params: List[Any] = []
        if only_accepted:
            clauses.append("accepted = 1")
        if min_rating:
            rating_order = {"excellent": 4, "good": 3, "neutral": 2,
                            "poor": 1, "bad": 0}
            threshold = rating_order.get(min_rating, 2)
            allowed = [r for r, v in rating_order.items() if v >= threshold]
            clauses.append(
                "(rating IN (" + ",".join("?" * len(allowed)) + "))")
            params.extend(allowed)
        if clauses:
            sql += "WHERE " + " AND ".join(clauses) + " "
        sql += "GROUP BY source_type"
        with self._conn() as c:
            for row in c.execute(sql, params):
                st = row["source_type"] or SOURCE_REPHRASE
                out[st] = out.get(st, 0) + row["n"]
        return out

    def list_corpus_collections(self) -> List[Dict[str, Any]]:
        """Enumerate distinct corpus collections in the DB.

        A "collection" is a group of corpus rows that share an origin —
        a catalog corpus, a local file upload, or a project import.
        We identify each by parsing the ``notes`` column (the downloader
        and project-import dialog tag rows with ``corpus_id=…``,
        ``corpus_title=…``, and/or ``project_source=…``).

        Returns a list of dicts:
            ``{"key": "<unique id>",
              "label": "<human readable>",
              "kind": "catalog"|"upload"|"project"|"unknown",
              "row_count": N}``

        Used by the per-corpus filter dialog so the user can pick which
        collections feed the next training run.
        """
        out: Dict[str, Dict[str, Any]] = {}
        with self._conn() as c:
            cur = c.execute(
                "SELECT notes, COUNT(*) AS n FROM rephrases "
                "WHERE source_type = 'corpus' AND accepted = 1 "
                "GROUP BY notes")
            for row in cur:
                notes = row["notes"] or ""
                key, label, kind = self._parse_collection_id(notes)
                if key not in out:
                    out[key] = {"key": key, "label": label,
                                "kind": kind, "row_count": 0}
                out[key]["row_count"] += row["n"]
        # Stable sort: catalog first (alphabetical), uploads, projects,
        # unknowns last
        kind_order = {"catalog": 0, "upload": 1, "project": 2, "unknown": 3}
        return sorted(out.values(),
                      key=lambda d: (kind_order.get(d["kind"], 9),
                                     d["label"]))

    def available_sources(self) -> List[Dict[str, Any]]:
        """Every distinct training source the user has ingested.

        Wider than ``list_corpus_collections`` in two ways:

          1. Includes non-corpus sources (character/worldbuilding/
             plot generations, chat history, etc.) so a corpus can
             pull from them too — the user said "everything we
             upload or any project we import has to make it."
          2. Returns a normalized ``key`` shape (``catalog:<id>``,
             ``project:<name>``, ``upload:<title>``, ``other:<src>``)
             that ``corpus_collection.parse_source_key`` understands.

        Each result is ``{"key", "label", "kind", "row_count",
        "source_type", "median_output_chars", "bytes_estimate"}``.
        ``bytes_estimate`` sums ``LEN(source_text) + LEN(output_text)``
        across all rows in the source — a UTF-8 byte count is
        ~ ``bytes_estimate`` for ASCII-dominant prose and a small
        constant factor higher for accented text, so it's a good
        approximation for "how big is this dataset" without paying
        the cost of an exact byte tally.
        """
        out: Dict[str, Dict[str, Any]] = {}
        with self._conn() as c:
            cur = c.execute(
                "SELECT source_type, notes, source_text, output_text "
                "FROM rephrases WHERE accepted = 1")
            for row in cur:
                st = row["source_type"] or "unknown"
                notes = row["notes"] or ""
                if st == "corpus":
                    key, label, kind = self._parse_collection_id(notes)
                else:
                    # Non-corpus source_types are their own buckets
                    # (e.g. ``other:character`` for character rows).
                    # The label is the source_type spelled prettily.
                    key = f"other:{st}"
                    label = st.replace("_", " ").title()
                    kind = "other"
                bucket = out.setdefault(key, {
                    "key": key,
                    "label": label,
                    "kind": kind,
                    "source_type": st,
                    "row_count": 0,
                    "bytes_estimate": 0,
                    "_output_lens": [],
                })
                bucket["row_count"] += 1
                src_len = len(row["source_text"] or "")
                out_len = len(row["output_text"] or "")
                bucket["bytes_estimate"] += src_len + out_len
                bucket["_output_lens"].append(out_len)
        # Compute medians and drop the temp list before returning.
        result = []
        for b in out.values():
            lens = sorted(b.pop("_output_lens"))
            n = len(lens)
            b["median_output_chars"] = int(lens[n // 2]) if n else 0
            result.append(b)
        kind_order = {"catalog": 0, "upload": 1, "project": 2,
                      "other": 3, "unknown": 4}
        return sorted(result,
                      key=lambda d: (kind_order.get(d["kind"], 9),
                                     -d["row_count"], d["label"]))

    def rows_for_corpus(self,
                        source_keys: Iterable[str],
                        *,
                        only_accepted: bool = True,
                        limit: Optional[int] = None,
                        offset: int = 0
                        ) -> List[Dict[str, Any]]:
        """Fetch every row that belongs to any of ``source_keys``.

        Reuses the same ``notes LIKE '%marker%'`` pattern that the
        ``corpus_collection`` module documents — one OR clause per
        key. ``other:<source_type>`` keys are matched against the
        ``source_type`` column instead of ``notes``.

        If ``source_keys`` is empty the result is also empty (so an
        empty corpus reasonably has zero rows rather than "all").
        """
        from src.data.corpus_collection import parse_source_key
        keys = list(source_keys or [])
        if not keys:
            return []

        clauses: List[str] = []
        params: List[Any] = []
        for key in keys:
            parsed = parse_source_key(key)
            if not parsed:
                continue
            kind = parsed["kind"]
            value = parsed["value"]
            if kind == "catalog":
                clauses.append("notes LIKE ?")
                params.append(f"%corpus_id={value}%")
            elif kind == "project":
                clauses.append("notes LIKE ?")
                params.append(f"%project_source={value}%")
            elif kind == "upload":
                clauses.append("notes LIKE ?")
                params.append(f"%corpus_title={value}%")
            elif kind == "other":
                clauses.append("source_type = ?")
                params.append(value)

        if not clauses:
            return []

        sql = f"SELECT * FROM rephrases WHERE ({' OR '.join(clauses)})"
        if only_accepted:
            sql += " AND accepted = 1"
        sql += " ORDER BY id DESC"
        if limit:
            sql += " LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])

        with self._conn() as c:
            cur = c.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def size_estimate_for_corpus(self,
                                 source_keys: Iterable[str],
                                 *,
                                 only_accepted: bool = True
                                 ) -> Dict[str, int]:
        """Row count + byte estimate for a corpus's source list.

        Returns ``{"rows": N, "bytes": B}`` — ``B`` is
        ``SUM(LENGTH(source_text) + LENGTH(output_text))`` over the
        matching rows. For UI: format with ``format_bytes(B)`` to
        get "3.2 MB" / "847 KB" etc.

        One SQL pass instead of iterating Python rows; on the user's
        800K-row DB this runs in well under a second even when the
        corpus pulls from many sources.
        """
        from src.data.corpus_collection import parse_source_key
        keys = list(source_keys or [])
        if not keys:
            return {"rows": 0, "bytes": 0}

        clauses: List[str] = []
        params: List[Any] = []
        for key in keys:
            parsed = parse_source_key(key)
            if not parsed:
                continue
            kind = parsed["kind"]
            value = parsed["value"]
            if kind == "catalog":
                clauses.append("notes LIKE ?")
                params.append(f"%corpus_id={value}%")
            elif kind == "project":
                clauses.append("notes LIKE ?")
                params.append(f"%project_source={value}%")
            elif kind == "upload":
                clauses.append("notes LIKE ?")
                params.append(f"%corpus_title={value}%")
            elif kind == "other":
                clauses.append("source_type = ?")
                params.append(value)

        if not clauses:
            return {"rows": 0, "bytes": 0}

        sql = (
            "SELECT COUNT(*) AS rows, "
            "COALESCE(SUM(LENGTH(source_text) + LENGTH(output_text)), 0) "
            "AS bytes "
            f"FROM rephrases WHERE ({' OR '.join(clauses)})")
        if only_accepted:
            sql += " AND accepted = 1"
        with self._conn() as c:
            row = c.execute(sql, params).fetchone()
            return {"rows": int(row["rows"]),
                    "bytes": int(row["bytes"])}

    def count_rows_for_corpus(self,
                              source_keys: Iterable[str],
                              *,
                              only_accepted: bool = True) -> int:
        """Total row count across the given source keys.

        Cheaper than ``len(rows_for_corpus(...))`` because it doesn't
        materialize rows. Used by the manager dialog to render
        "<corpus> contains 12,438 rows" without paying the IO cost.
        """
        from src.data.corpus_collection import parse_source_key
        keys = list(source_keys or [])
        if not keys:
            return 0

        clauses: List[str] = []
        params: List[Any] = []
        for key in keys:
            parsed = parse_source_key(key)
            if not parsed:
                continue
            kind = parsed["kind"]
            value = parsed["value"]
            if kind == "catalog":
                clauses.append("notes LIKE ?")
                params.append(f"%corpus_id={value}%")
            elif kind == "project":
                clauses.append("notes LIKE ?")
                params.append(f"%project_source={value}%")
            elif kind == "upload":
                clauses.append("notes LIKE ?")
                params.append(f"%corpus_title={value}%")
            elif kind == "other":
                clauses.append("source_type = ?")
                params.append(value)

        if not clauses:
            return 0

        sql = f"SELECT COUNT(*) FROM rephrases WHERE ({' OR '.join(clauses)})"
        if only_accepted:
            sql += " AND accepted = 1"
        with self._conn() as c:
            return int(c.execute(sql, params).fetchone()[0])

    def delete_source(self, source_key: str) -> int:
        """Drop every row belonging to one source.

        Powers the "delete download" button in the corpus manager.
        ``other:<source_type>`` is intentionally NOT supported here
        because it would nuke whole categories (every character
        generation ever) and that's almost certainly a mistake; the
        UI hides the button for those.

        Returns the number of rows deleted.
        """
        from src.data.corpus_collection import parse_source_key
        parsed = parse_source_key(source_key)
        if not parsed:
            return 0
        kind = parsed["kind"]
        value = parsed["value"]
        if kind == "catalog":
            marker = f"%corpus_id={value}%"
        elif kind == "project":
            marker = f"%project_source={value}%"
        elif kind == "upload":
            marker = f"%corpus_title={value}%"
        else:
            return 0
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM rephrases WHERE notes LIKE ?",
                (marker,))
            return cur.rowcount

    def search_row_ids(self,
                       query: str = "",
                       *,
                       source_types: Optional[Iterable[str]] = None,
                       genre: str = "",
                       corpus_id: str = "",
                       min_rating: Optional[str] = None,
                       only_accepted: bool = True) -> List[int]:
        """Return every row id matching the same filters as
        :meth:`search_rows`, with no paging cap.

        Used by the Browse Rows dialog's "Drop matching" action so
        the deletion covers the full result set, not just the
        visible page. Returns a list of integers; deletion goes
        through :func:`prompt_fit_audit.delete_rows_by_id` or
        :func:`genre_scope_apply.apply_drops`.
        """
        clauses, params = self._search_clauses(
            query=query, source_types=source_types, genre=genre,
            corpus_id=corpus_id, min_rating=min_rating,
            only_accepted=only_accepted)
        sql = "SELECT id FROM rephrases"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC"
        with self._conn() as c:
            cur = c.execute(sql, params)
            return [int(r["id"]) for r in cur]

    def _search_clauses(self, *, query, source_types, genre,
                         corpus_id, min_rating,
                         only_accepted) -> Tuple[List[str], List[Any]]:
        """Build the WHERE clause + params shared by ``search_rows``
        and ``search_row_ids``. Extracted so the two callers stay
        in lockstep — adding a new filter means changing one place,
        not both."""
        clauses: List[str] = []
        params: List[Any] = []
        if only_accepted:
            clauses.append("accepted = 1")
        if source_types:
            sts = list(source_types)
            placeholders = ",".join("?" * len(sts))
            clauses.append(f"source_type IN ({placeholders})")
            params.extend(sts)
        if genre:
            clauses.append("genre LIKE ?")
            params.append(f"%{genre}%")
        if corpus_id:
            clauses.append("notes LIKE ?")
            params.append(f"%corpus_id={corpus_id}%")
        if min_rating:
            order = ["excellent", "good", "neutral", "poor", "bad"]
            try:
                cutoff = order.index(min_rating)
                allowed = order[:cutoff + 1]
            except ValueError:
                allowed = ["excellent", "good"]
            placeholders = ",".join("?" * len(allowed))
            clauses.append(
                f"(rating IN ({placeholders}) OR rating IS NULL)")
            params.extend(allowed)
        if query:
            clauses.append(
                "(source_text LIKE ? OR output_text LIKE ? "
                "OR notes LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like])
        return clauses, params

    def search_rows(self,
                    query: str = "",
                    *,
                    source_types: Optional[Iterable[str]] = None,
                    genre: str = "",
                    corpus_id: str = "",
                    min_rating: Optional[str] = None,
                    only_accepted: bool = True,
                    limit: int = 200,
                    offset: int = 0) -> List[Dict[str, Any]]:
        """Browse the DB with filters + a free-text query.

        Powers the corpus-browser window. The query matches in
        ``source_text`` OR ``output_text`` OR title (the
        ``corpus_title=…`` value extracted from notes via a LIKE
        match). All other arguments are AND-combined with the
        query. ``corpus_id`` filters to one ingested catalog corpus
        (matches notes containing ``corpus_id=<value>``).

        Args:
            query: free-text search across source/output/title; empty
                string means "no text filter".
            source_types: restrict to these source_type values
                (rephrase, corpus, character, …).
            genre: substring-match the (free-text, comma-separated)
                ``genre`` column.
            corpus_id: substring-match a ``corpus_id=<id>`` token in
                the notes column.
            min_rating: rating threshold (same scale as
                ``export_jsonl``); rows below the threshold are
                dropped.
            only_accepted: when True, hides rows with accepted=0.
            limit: max rows to return (default 200; UI pages by 200).
            offset: page offset for paging.
        """
        clauses, params = self._search_clauses(
            query=query, source_types=source_types, genre=genre,
            corpus_id=corpus_id, min_rating=min_rating,
            only_accepted=only_accepted)
        sql = "SELECT * FROM rephrases"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])

        with self._conn() as c:
            cur = c.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def count_search_rows(self,
                          query: str = "",
                          *,
                          source_types: Optional[Iterable[str]] = None,
                          genre: str = "",
                          corpus_id: str = "",
                          min_rating: Optional[str] = None,
                          only_accepted: bool = True) -> int:
        """Total row count for the same filters as ``search_rows``.

        Used by the browser window to render "showing 200 of 12,438
        matches" — without this, paging is confusing because the
        user can't see whether they've reached the end.
        """
        clauses: List[str] = []
        params: List[Any] = []
        if only_accepted:
            clauses.append("accepted = 1")
        if source_types:
            sts = list(source_types)
            placeholders = ",".join("?" * len(sts))
            clauses.append(f"source_type IN ({placeholders})")
            params.extend(sts)
        if genre:
            clauses.append("genre LIKE ?")
            params.append(f"%{genre}%")
        if corpus_id:
            clauses.append("notes LIKE ?")
            params.append(f"%corpus_id={corpus_id}%")
        if min_rating:
            order = ["excellent", "good", "neutral", "poor", "bad"]
            try:
                cutoff = order.index(min_rating)
                allowed = order[:cutoff + 1]
            except ValueError:
                allowed = ["excellent", "good"]
            placeholders = ",".join("?" * len(allowed))
            clauses.append(f"(rating IN ({placeholders}) OR rating IS NULL)")
            params.extend(allowed)
        if query:
            clauses.append(
                "(source_text LIKE ? OR output_text LIKE ? "
                "OR notes LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like])
        sql = "SELECT COUNT(*) FROM rephrases"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self._conn() as c:
            return int(c.execute(sql, params).fetchone()[0])

    def per_genre_metrics(self,
                          *,
                          only_accepted: bool = True
                          ) -> List[Dict[str, Any]]:
        """Per-genre row count and median output length.

        ``genre`` is free-text comma-separated; we split each row's
        value and tally each tag separately so a row tagged
        ``"horror,gothic"`` shows up under both buckets. Rows with
        no genre are bucketed under ``"(untagged)"``.

        Returns ``[{"genre", "rows", "median_output_chars",
        "voice_tagged"}]`` sorted by row count descending. Median is
        computed in Python; the row count per genre dominates so
        the cost is O(N log N) for the sort, not the median.
        """
        with self._conn() as c:
            sql = ("SELECT genre, voice, output_text FROM rephrases")
            if only_accepted:
                sql += " WHERE accepted = 1"
            cur = c.execute(sql)
            buckets: Dict[str, Dict[str, Any]] = {}
            for row in cur:
                raw = (row["genre"] or "").strip()
                tags = [t.strip().lower() for t in raw.split(",") if t.strip()]
                if not tags:
                    tags = ["(untagged)"]
                out_len = len(row["output_text"] or "")
                voiced = bool((row["voice"] or "").strip())
                for tag in tags:
                    b = buckets.setdefault(tag, {
                        "genre": tag,
                        "rows": 0,
                        "voice_tagged": 0,
                        "_output_lens": [],
                    })
                    b["rows"] += 1
                    if voiced:
                        b["voice_tagged"] += 1
                    b["_output_lens"].append(out_len)
        out = []
        for b in buckets.values():
            lens = sorted(b.pop("_output_lens"))
            n = len(lens)
            median = lens[n // 2] if n else 0
            b["median_output_chars"] = int(median)
            out.append(b)
        out.sort(key=lambda d: -d["rows"])
        return out

    def per_corpus_metrics(self,
                           *,
                           only_accepted: bool = True
                           ) -> List[Dict[str, Any]]:
        """Per-corpus row count, median output length, short-source rate.

        Identifies a "corpus" the same way ``list_corpus_collections``
        does — parsing the ``notes`` column for ``corpus_id`` /
        ``project_source`` / ``corpus_title``. Restricted to
        ``source_type='corpus'`` (the only place these tags appear).

        Returns ``[{"key", "label", "kind", "rows",
        "median_output_chars", "short_source_pct"}]`` sorted by
        row count descending. ``short_source_pct`` is the % of rows
        whose ``source_text`` is below 60 chars — a leading
        indicator that the splitter ran on bad data and the corpus
        should be re-ingested.
        """
        with self._conn() as c:
            sql = ("SELECT notes, source_text, output_text "
                   "FROM rephrases WHERE source_type = 'corpus'")
            if only_accepted:
                sql += " AND accepted = 1"
            cur = c.execute(sql)
            buckets: Dict[str, Dict[str, Any]] = {}
            for row in cur:
                key, label, kind = self._parse_collection_id(
                    row["notes"] or "")
                src_len = len(row["source_text"] or "")
                out_len = len(row["output_text"] or "")
                b = buckets.setdefault(key, {
                    "key": key,
                    "label": label,
                    "kind": kind,
                    "rows": 0,
                    "_output_lens": [],
                    "_short_source": 0,
                })
                b["rows"] += 1
                b["_output_lens"].append(out_len)
                if src_len < 60:
                    b["_short_source"] += 1
        out = []
        for b in buckets.values():
            lens = sorted(b.pop("_output_lens"))
            n = len(lens)
            median = lens[n // 2] if n else 0
            short = b.pop("_short_source")
            b["median_output_chars"] = int(median)
            b["short_source_pct"] = (
                short / b["rows"] * 100.0 if b["rows"] else 0.0)
            out.append(b)
        out.sort(key=lambda d: -d["rows"])
        return out

    @staticmethod
    def _parse_collection_id(notes: str) -> tuple:
        """Pull (key, label, kind) out of a row's notes string.

        Notes are key=value pairs where values can contain spaces
        (e.g. ``corpus_title=The Iron Fen project_source=Iron Fen``).
        We extract pairs with a regex that looks for ``\\w+=`` boundaries
        so multi-word values aren't truncated at the first space.

        Returns (collection_key, display_label, kind).
        """
        import re
        kv = {}
        if notes:
            # Match "key=value" where value runs until the next "
            # word=" boundary or the end of the string. The negative
            # lookahead is what handles spaces inside values.
            for m in re.finditer(r'(\w+)=(.+?)(?=\s+\w+=|$)', notes,
                                 flags=re.DOTALL):
                kv.setdefault(m.group(1), m.group(2).strip())

        if "corpus_id" in kv:
            return (f"catalog:{kv['corpus_id']}",
                    kv["corpus_id"], "catalog")
        if "project_source" in kv:
            ps = kv["project_source"]
            return (f"project:{ps}", f"Project: {ps}", "project")
        if "corpus_title" in kv:
            t = kv["corpus_title"]
            return (f"upload:{t}", f"Upload: {t}", "upload")
        return ("unknown:", "(untagged)", "unknown")

    def positive_rows(self,
                      source_types: Optional[Iterable[str]] = None
                      ) -> List[Dict[str, Any]]:
        """Rows the user rated positively (excellent / good).

        Optionally restricted to one or more source types — used by the
        training tool to assemble a corpus matching the user's intent.
        """
        sql = ("SELECT * FROM rephrases WHERE rating IN ('excellent','good')")
        params: List[Any] = []
        if source_types:
            placeholders = ",".join("?" * len(list(source_types)))
            sql += f" AND source_type IN ({placeholders})"
            params.extend(source_types)
        sql += " ORDER BY created_at DESC"
        with self._conn() as c:
            cur = c.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def negative_rows(self) -> List[Dict[str, Any]]:
        """Rows the user rated negatively (poor / bad)."""
        with self._conn() as c:
            cur = c.execute(
                "SELECT * FROM rephrases WHERE rating IN ('poor','bad') "
                "ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]

    def dpo_pairs(self) -> List[Dict[str, Any]]:
        """Build chosen/rejected pairs for preference fine-tuning (DPO).

        Pairs are constructed across rows with the SAME ``source_text``:
        positive ratings supply the "chosen" output; negative ratings on
        the same source supply the "rejected" output. If no perfect
        same-source match exists, falls back to pairing each positive
        with the most-recent negative globally so the model learns
        general avoidance patterns from the user's voice.
        """
        positives = self.positive_rows()
        negatives = self.negative_rows()
        if not positives or not negatives:
            return []

        neg_by_source: Dict[str, List[Dict[str, Any]]] = {}
        for n in negatives:
            neg_by_source.setdefault(n["source_text"], []).append(n)

        pairs: List[Dict[str, Any]] = []
        for p in positives:
            same_source = neg_by_source.get(p["source_text"])
            if same_source:
                for n in same_source:
                    pairs.append({"chosen": p, "rejected": n,
                                  "matched": "same_source"})
            else:
                # Fallback: cross-source — useful for general avoidance
                # patterns ("user dislikes purple prose") even when the
                # source text differs.
                pairs.append({"chosen": p, "rejected": negatives[0],
                              "matched": "cross_source"})
        return pairs

    # ── Export ──

    # Source types that represent the *user's own writing voice*. When
    # an export oversamples user-voice rows (so the user's style
    # dominates the LoRA loss instead of being drowned by larger genre
    # corpora), these are the rows that get repeated.
    USER_VOICE_SOURCES = {SOURCE_REPHRASE, SOURCE_CHAT_WRITING}

    def export_jsonl(self, output_path: Path,
                     fmt: str = "instruction",
                     only_accepted: bool = True,
                     min_rating: str = "neutral",
                     source_types: Optional[Iterable[str]] = None,
                     user_voice_oversample: int = 1,
                     genre_filter: Optional[Iterable[str]] = None,
                     corpus_collection_keys: Optional[Iterable[str]] = None,
                     expand_corpus_windows: bool = False,
                     enforce_purpose_fit: bool = False,
                     ) -> int:
        """Write the database to a JSONL file in the chosen training format.

        Args:
            source_types: If given, restrict export to rows whose
                ``source_type`` is in this iterable. Used by the
                training tool to combine arbitrary source mixes
                (e.g. rephrase + chat_writing + corpus, leaving out
                chat_general).
            user_voice_oversample: Repeat each row whose source is in
                ``USER_VOICE_SOURCES`` this many times in the output
                JSONL. ``1`` (default) means no oversampling; values
                like ``5`` or ``10`` make the user's own voice dominate
                the loss when the rest of the dataset is large genre
                corpora. Useful for "rephrase in *my* voice" trainings.
            genre_filter: Iterable of canonical genre keys (e.g.
                ``["horror", "thriller"]``) the user is training on.
                Only applies to **corpus** rows: if a corpus row's
                ``genre`` field contains *any* of these keys, it's
                included; rows with empty genre tags are always
                included as generic context. Pass ``None`` (default)
                to disable genre filtering and include every corpus
                row regardless of tag. User-voice rows (rephrase,
                chat_*) and other source types are unaffected — they
                always pass through.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if fmt == "dpo":
            return self._export_dpo(output_path, source_types=source_types)

        rating_order = {"excellent": 4, "good": 3, "neutral": 2,
                        "poor": 1, "bad": 0}
        threshold = rating_order.get(min_rating, 2)
        rows = self.all_rows(only_accepted=only_accepted)
        st_filter = set(source_types) if source_types else None
        repeat = max(1, int(user_voice_oversample))
        wanted_genres = (set(g.lower().strip() for g in genre_filter)
                         if genre_filter else None)
        # Expand the wanted set with sibling/ancillary genres
        # (western↔frontier, horror↔gothic) so filtering for one
        # automatically pulls in the other. Declared in
        # :mod:`src.data.genres`. Symmetric — re-expanding is a
        # no-op. Skipped silently if the genres module isn't
        # importable for some reason.
        if wanted_genres:
            try:
                from src.data.genres import expand_with_ancillaries
                wanted_genres = (expand_with_ancillaries(wanted_genres)
                                 | wanted_genres)
            except Exception:
                pass
        # Per-corpus collection filter — applies only to corpus rows.
        # Each row's collection key is derived from its notes via
        # ``_parse_collection_id``. Default ``None`` = include every
        # collection; an explicit empty list excludes all corpus rows.
        collection_filter = (set(corpus_collection_keys)
                             if corpus_collection_keys is not None
                             else None)
        # Per-pair heuristic gate. Drops obvious mis-fits before
        # they reach the JSONL — refusal templates, raw tool-call
        # JSON, trivially short outputs, and shape-aware content
        # checks (summarisation pairs with no source overlap, etc.).
        # Counts are aggregated and stashed on ``self`` so the UI
        # / training worker can report what was dropped without
        # changing the function's return signature.
        from src.data.prompt_fit_gate import evaluate_pair, GateReport
        gate_report = GateReport()
        n = 0
        with open(output_path, 'w', encoding='utf-8') as f:
            for r in rows:
                # ``src`` here is the row's *native* source_type — the
                # bucket it was ingested into. Genre + collection
                # filters apply to the underlying data, so they fire
                # against this value. The decision of whether to
                # *emit* the row (and which template family to pick)
                # is now deferred to ``_format_row``: it consults the
                # row's actual data shape and the user's checked set
                # so a row whose native type isn't ticked can still
                # be emitted under a checked alternative when the
                # shape supports it (e.g. a corpus row repurposed
                # into the plot bucket because only "plot" is on).
                src = r.get("source_type") or SOURCE_REPHRASE
                row_rating = r.get("rating", "neutral") or "neutral"
                if rating_order.get(row_rating, 2) < threshold:
                    continue
                # Genre filter (hard + fuzzy compose):
                #   * Default behaviour — restrict CORPUS rows only.
                #     Untagged corpus rows (genre=="") are universal
                #     context and always pass; tagged ones must
                #     overlap the wanted set.
                #   * With ``enforce_purpose_fit=True`` — same rule
                #     extended to plot/character/worldbuilding rows
                #     so a horror corpus doesn't bleed into a romance
                #     plot training run. Chat / rephrase / agent rows
                #     are still exempt (they're either user voice
                #     data, which is genre-agnostic, or tool traces).
                #   * **Fuzzy keep-craft escape** — when the hard
                #     genre check would drop a row, run the kind
                #     classifier; rows confidently identified as
                #     ``craft`` (essays / criticism / how-to /
                #     theory) are kept regardless of their tagged
                #     genre. A craft essay on plotting is broadly
                #     useful for plot/character/worldbuilding
                #     training even when its tag doesn't match the
                #     target genre. Voice training (corpus bucket)
                #     still drops these via the per-bucket craft
                #     filter further down — the escape composes
                #     correctly with the bucket rules.
                if wanted_genres:
                    genre_filtered_buckets = (
                        {SOURCE_CORPUS, SOURCE_PLOT, SOURCE_CHARACTER,
                         SOURCE_WORLDBUILDING}
                        if enforce_purpose_fit
                        else {SOURCE_CORPUS})
                    if src in genre_filtered_buckets:
                        row_genre_raw = (r.get("genre")
                                         or "").lower().strip()
                        if row_genre_raw:
                            # Contains + fuzzy match so composite
                            # tags ("gothic horror" → "horror"),
                            # hyphenated variants ("sci-fi" →
                            # "scifi"), and typos ("horor" →
                            # "horror") all match. See
                            # :func:`src.data.genres.genres_overlap`.
                            from src.data.genres import genres_overlap
                            if not genres_overlap(
                                    row_genre_raw, wanted_genres):
                                # Hard filter says drop. Fuzzy
                                # escape: keep if confidently craft.
                                from src.data.text_kind import (
                                    classify_kind)
                                kind = classify_kind(
                                    r.get("source_text", "") or "",
                                    r.get("output_text", "") or "")
                                if kind != "craft":
                                    continue
                                # Stamp the kind hint so the
                                # resolver in ``_format_row`` knows
                                # this is a craft row and can
                                # repurpose it into a checked plot/
                                # character/world bucket regardless
                                # of physical shape. The hint also
                                # avoids a second classify_kind call.
                                r = {**r, "_kind_hint": "craft"}
                # Per-collection filter: corpus rows whose collection
                # key isn't in the user's selection get skipped. User-
                # voice rows (rephrase / chat) and other source types
                # are unaffected — the filter is corpus-specific.
                if collection_filter is not None and src == SOURCE_CORPUS:
                    key, _label, _kind = self._parse_collection_id(
                        r.get("notes") or "")
                    if key not in collection_filter:
                        continue
                # Build the (src, out) windows we'll format under.
                # Sliding-window expansion (opt-in) multiplies a
                # multi-paragraph corpus row into 2-4 (context, next)
                # pairs so the trainer sees more supervision per row
                # at varying context lengths. Only fires for native
                # corpus rows — repurposed rows (shape != continuation)
                # wouldn't make sense to window.
                if (expand_corpus_windows
                        and src == SOURCE_CORPUS):
                    windows = self._expand_corpus_windows(
                        r.get("source_text", "") or "",
                        r.get("output_text", "") or "")
                else:
                    windows = [(r.get("source_text", "") or "",
                                r.get("output_text", "") or "")]

                for win_src, win_out in windows:
                    # Synthesise a per-window row dict. We force the
                    # shape to ``continuation`` for windowed pairs:
                    # the parent row was a corpus continuation and
                    # every window IS a continuation pair — but as
                    # context grows the per-window length ratio
                    # drifts and the auto-classifier would flip
                    # later windows to "summarisation", which doesn't
                    # fit the corpus bucket and would drop the row.
                    if len(windows) > 1:
                        row_for_format = {**r,
                                          "source_text": win_src,
                                          "output_text": win_out,
                                          "_force_shape": "continuation"}
                    else:
                        row_for_format = r
                    obj = self._format_row(
                        row_for_format, fmt, checked_types=st_filter)
                    if obj is None:
                        continue
                    # Purpose-fit kind filter. Voice training (corpus
                    # bucket) wants narrative prose, not "How to Write
                    # a Thriller" — even a well-shaped craft passage
                    # mis-trains voice. Plot / character / worldbuilding
                    # buckets KEEP craft passages because they teach
                    # structure explicitly. Classifier returns
                    # "narrative" / "craft" / "unknown"; we only DROP
                    # on a confident "craft" verdict so unknown rows
                    # still feed voice training.
                    if enforce_purpose_fit:
                        eff_st_for_kind = (
                            (obj.get("metadata") or {}).get("source_type")
                            if isinstance(obj, dict) else src) or src
                        if eff_st_for_kind == SOURCE_CORPUS:
                            from src.data.text_kind import classify_kind
                            kind = classify_kind(win_src, win_out)
                            if kind == "craft":
                                gate_report.record(
                                    "voice-bucket-craft-text")
                                continue
                    # Heuristic fit gate. Operates on the *emitted*
                    # pair's input/output and the effective family's
                    # shape so a row repurposed into a different bucket
                    # is judged against the bucket's expectations.
                    emit_meta = (obj.get("metadata") or {}
                                 if isinstance(obj, dict) else {})
                    gate_input = (obj.get("input")
                                  if isinstance(obj, dict)
                                  else "") or ""
                    gate_output = (obj.get("output")
                                   if isinstance(obj, dict)
                                   else "") or ""
                    # In chat-format we don't have an "input" key —
                    # use the user message as the input proxy. The
                    # gate is mainly looking at the *output* anyway
                    # (refusals, tool-calls, length); the input only
                    # matters for the shape-overlap checks.
                    if not gate_input and isinstance(obj, dict) \
                            and obj.get("messages"):
                        for m in obj["messages"]:
                            if m.get("role") == "user":
                                gate_input = m.get("content", "") or ""
                                break
                        for m in obj["messages"]:
                            if m.get("role") == "assistant":
                                gate_output = m.get("content", "") or ""
                                break
                    drop_reason = evaluate_pair(
                        src=gate_input, out=gate_output,
                        source_type=emit_meta.get("source_type", src),
                        shape=emit_meta.get("shape", "other"))
                    gate_report.record(drop_reason)
                    if drop_reason is not None:
                        continue
                    # Oversample user-voice rows by repeating them.
                    # The check uses the *effective* source_type
                    # (post-repurposing) so a corpus row promoted
                    # into the plot bucket doesn't accidentally
                    # inherit voice-oversampling and a rephrase row
                    # repurposed into corpus loses it as you'd expect.
                    eff_src = (obj.get("metadata", {}).get("source_type")
                               if isinstance(obj, dict)
                               else None) or src
                    copies = (repeat
                              if eff_src in self.USER_VOICE_SOURCES
                              else 1)
                    for _ in range(copies):
                        f.write(json.dumps(obj, ensure_ascii=False))
                        f.write("\n")
                        n += 1
        # Stash the gate report on self so callers (training UI,
        # corpus quality dialog) can pull it without changing this
        # method's return signature. Always overwritten — only the
        # most recent export's report is kept.
        self.last_gate_report = gate_report
        return n

    def _export_dpo(self, output_path: Path,
                    source_types: Optional[Iterable[str]] = None) -> int:
        """Write DPO preference pairs in the standard chosen/rejected format
        used by HuggingFace TRL's DPOTrainer. Optionally filter by source.
        """
        pairs = self.dpo_pairs()
        if source_types:
            st_filter = set(source_types)
            pairs = [p for p in pairs
                     if (p["chosen"].get("source_type") or SOURCE_REPHRASE)
                     in st_filter]
        n = 0
        with open(output_path, 'w', encoding='utf-8') as f:
            for pair in pairs:
                chosen = pair["chosen"]
                rejected = pair["rejected"]
                # Build the same prompt for both sides
                instr_parts = ["Rephrase the following passage"]
                if chosen.get("style"):
                    instr_parts.append(f"in a {chosen['style']} tone")
                if chosen.get("character_name"):
                    instr_parts.append(f"in {chosen['character_name']}'s voice")
                if chosen.get("genre"):
                    instr_parts.append(f"({chosen['genre']} genre)")
                instruction = " ".join(instr_parts) + "."
                ctx_before = chosen.get("surrounding_before", "")
                ctx_after = chosen.get("surrounding_after", "")
                ctx_block = ""
                if ctx_before or ctx_after:
                    ctx_block = (f"Context:\n[before] {ctx_before}\n"
                                 f"[after] {ctx_after}\n\n")
                prompt = (f"{instruction}\n\n{ctx_block}"
                          f"Passage:\n{chosen['source_text']}\n")
                obj = {
                    "prompt": prompt,
                    "chosen": chosen["output_text"],
                    "rejected": rejected["output_text"],
                    "metadata": {
                        "matched": pair.get("matched", "cross_source"),
                        "chosen_rating": chosen.get("rating", ""),
                        "rejected_rating": rejected.get("rating", ""),
                    },
                }
                f.write(json.dumps(obj, ensure_ascii=False))
                f.write("\n")
                n += 1
        return n

    @staticmethod
    def _parse_notes_kv(notes: str) -> Dict[str, str]:
        """Pull every ``key=value`` pair out of the ``notes`` column.

        Values can contain spaces (e.g. ``corpus_title=The Iron Fen``);
        the regex stops at the next ``word=`` boundary or end of string.
        """
        import re
        kv: Dict[str, str] = {}
        if notes:
            for m in re.finditer(r'(\w+)=(.+?)(?=\s+\w+=|$)', notes,
                                 flags=re.DOTALL):
                kv.setdefault(m.group(1), m.group(2).strip())
        return kv

    # ── Shape-aware repurposing ───────────────────────────────
    #
    # A training row's *stored* source_type only tells us which
    # bucket the data was ingested into — it doesn't tell us what
    # shape the (source_text, output_text) pair actually is. BookSum
    # is the canonical mismatch: stored as ``plot``, but the data is
    # ``(chapter, summary)`` — a summarisation pair. Asking the
    # model to "Generate a story outline from the premise below"
    # against (chapter, summary) trains it to confuse outline
    # generation with chapter summarisation.
    #
    # ``_classify_row_shape`` looks at length ratios + source_type
    # to label what the pair physically is. ``_SHAPE_FITS`` then
    # maps each shape to the source_types whose template families
    # can faithfully serve it. The picker (`_resolve_effective_source_type`)
    # combines those with the user's checked source_types so a row
    # gets emitted under whichever checked type its shape can serve
    # well — repurposing where it makes sense, skipping where it
    # doesn't.

    # Per-shape: source_types whose templates can faithfully serve a
    # row of that shape, in priority order. Used both to pick a
    # better-fitting template under the row's native source_type and
    # to repurpose a row under a different (checked) source_type
    # when the native one isn't selected.
    #
    # The lists are *strict* — only source_types whose template
    # family makes sense for that data direction appear. E.g.
    # ``rephrase_like`` lists only SOURCE_REPHRASE because the
    # corpus templates are continuation/style-imitation prompts that
    # would mis-train on a (passage, paraphrase) pair. A row whose
    # shape doesn't match any checked source_type's family is dropped
    # — better to skip than to emit a mis-shaped pair.
    _SHAPE_FITS: Dict[str, List[str]] = {
        "summarization": [SOURCE_PLOT],
        # ``expansion`` (short→long) is intentionally empty: the
        # shape is shared by plot outline, character profile, and
        # worldbuilding element generation — but the *content
        # direction* differs (a character profile is not a story
        # outline). Length alone isn't enough to repurpose across
        # them safely. Expansion-shape rows still get their full
        # native template family; they just can't be cross-emitted.
        "expansion":     [],
        "rephrase_like": [SOURCE_REPHRASE],
        "continuation":  [SOURCE_CORPUS],
        "chat":          [SOURCE_CHAT_WRITING, SOURCE_CHAT_GENERAL],
        "agent":         [SOURCE_AGENT],
        "other":         [],  # unclassified — fall back to native source_type
    }

    @staticmethod
    def _expand_corpus_windows(src: str, out: str,
                                *, max_windows: int = 4,
                                min_para_chars: int = 80
                                ) -> List[Tuple[str, str]]:
        """Split one corpus row into N sliding (context, next) pairs.

        Many corpus passages span 4+ paragraphs — the ingest pipeline
        stores them as a single (opener, rest_of_passage) row, so the
        trainer sees one supervision pair per row. Reconstructing the
        full passage and slicing it into sliding windows turns each
        row into 2-4 pairs:

            (p1, p2)
            (p1+p2, p3)
            (p1+p2+p3, p4)
            …

        Each window teaches "given this much context, what comes
        next?" — same content, more training signal, and the model
        learns to handle varying context lengths.

        Returns ``[(src, out)]`` unchanged when the passage is too
        short to slice (fewer than 2 substantial paragraphs).
        Capped at ``max_windows`` so a 50-paragraph passage doesn't
        produce 49 pairs; we want the multiplier bounded.

        Paragraphs are split on blank lines (the standard Markdown/
        novel convention); short fragments (< ``min_para_chars``)
        are dropped so chapter-heading lines and stray newlines
        don't fragment the windowing.
        """
        import re as _re
        full = ((src or "").rstrip() + "\n\n"
                + (out or "").lstrip())
        paras = [p.strip() for p in _re.split(r"\n{2,}", full)
                 if p.strip() and len(p.strip()) >= min_para_chars]
        if len(paras) < 2:
            # Nothing to slice — emit the original pair so the row
            # still trains. Equivalent to "expansion off" for this row.
            return [(src or "", out or "")]
        pairs: List[Tuple[str, str]] = []
        for i in range(1, len(paras)):
            context = "\n\n".join(paras[:i])
            nxt = paras[i]
            pairs.append((context, nxt))
            if len(pairs) >= max_windows:
                break
        return pairs

    @staticmethod
    def _classify_row_shape(src: str, out: str, st: str) -> str:
        """Return a shape label describing what the pair physically is.

        Cheap heuristics based on lengths + source_type. Categories:

          * ``summarization`` — long input → much shorter output.
            BookSum-style (chapter → summary) lands here.
          * ``expansion`` — short input → much longer output. Brief
            → profile / element / outline / scene-from-event.
          * ``rephrase_like`` — both ≈ same length. Paraphrase pair.
          * ``continuation`` — opener → continuation, mid-range
            length variation but content is plausibly contiguous
            prose.
          * ``chat`` — chat source_type, regardless of lengths.
          * ``agent`` — agent source_type, regardless of lengths.
          * ``other`` — doesn't fit the heuristics; emit only under
            native source_type with the default template family.
        """
        if st == SOURCE_AGENT:
            return "agent"
        if st in (SOURCE_CHAT_WRITING, SOURCE_CHAT_GENERAL):
            return "chat"
        s_len = len(src or "")
        o_len = len(out or "")
        if s_len < 1 or o_len < 1:
            return "other"
        ratio = o_len / s_len
        if s_len > 400 and ratio < 0.4:
            return "summarization"
        if s_len < 800 and ratio > 2.5:
            return "expansion"
        if s_len >= 30 and 0.7 <= ratio <= 1.4:
            return "rephrase_like"
        if s_len >= 200 and 0.4 <= ratio <= 2.5:
            return "continuation"
        return "other"

    # When the row has been confidently classified as ``craft``
    # (essay / criticism / how-to / theory), it can be repurposed
    # into any of these target buckets regardless of physical shape.
    # The data is *about* writing, which is exactly what these
    # buckets train against — even a (long_excerpt, longer_analysis)
    # pair (rephrase_like shape) is valid plot/structure training.
    _CRAFT_REPURPOSE_TARGETS: List[str] = [
        SOURCE_PLOT, SOURCE_CHARACTER, SOURCE_WORLDBUILDING,
    ]

    @classmethod
    def _resolve_effective_source_type(
            cls, native_st: str, shape: str,
            checked_types: Optional[set],
            *, kind: Optional[str] = None
            ) -> Optional[str]:
        """Pick the source_type whose templates we'll format this row under.

        Rules — in order:

          1. **Legacy callers** (no checked filter) → keep ``native_st``
             so behaviour matches the old "format under whatever
             source_type the row stores" path. No drops.
          2. **Craft repurposing escape** — if the row is confidently
             ``kind="craft"`` AND any of plot/character/worldbuilding
             is checked, emit under the first such checked target.
             Craft texts (essays / criticism / theory) carry their
             value through *content*, not data shape, so the shape
             constraint shouldn't drop them. Native bucket still
             wins if it's checked AND it's one of the craft targets.
          3. **Shape "other"** (couldn't be classified) or shapes
             with no fits table entry: defer to native — emit if
             checked, drop if not.
          4. **Shape *can* be classified**: walk
             :attr:`_SHAPE_FITS` ``[shape]`` in priority order. Prefer
             native when native is among the fits AND in checked_types
             (keeps stable behaviour and respects the user's bucket);
             otherwise pick the first checked alternative.
          5. **Nothing fits any checked type** → return None; caller
             drops the row. Better to skip than emit a mis-shaped pair
             (the whole point of repurposing is to give the model
             *good* training examples, not just any examples).
        """
        if not checked_types:
            return native_st
        # Craft escape — runs before the shape-fit check because a
        # craft pair's value is in its content, not its length ratio.
        if kind == "craft":
            # Prefer native if native is one of the craft targets
            # AND checked (so a plot row stays plot, etc.).
            if (native_st in cls._CRAFT_REPURPOSE_TARGETS
                    and native_st in checked_types):
                return native_st
            for craft_target in cls._CRAFT_REPURPOSE_TARGETS:
                if craft_target in checked_types:
                    return craft_target
            # No craft target checked — fall through to standard
            # shape-fit logic. Voice/corpus is intentionally NOT a
            # craft target; if only voice is checked, the craft row
            # gets dropped (voice training shouldn't learn from
            # craft essays — that's what the purpose-fit filter
            # already enforces).
        fits = cls._SHAPE_FITS.get(shape, [])
        # When the shape table has no opinion (``other``, or shapes
        # like ``expansion`` that are too ambiguous to safely re-
        # purpose across buckets), defer to native — emit if checked,
        # drop if not.
        if not fits:
            return native_st if native_st in checked_types else None
        # Prefer native when it's a confirmed shape-fit AND checked.
        if native_st in fits and native_st in checked_types:
            return native_st
        # Otherwise take the first checked source_type whose family
        # the shape can faithfully serve.
        for alt in fits:
            if alt in checked_types:
                return alt
        return None

    @staticmethod
    def _format_row(row: Dict[str, Any], fmt: str,
                     *, checked_types: Optional[set] = None
                     ) -> Optional[Dict[str, Any]]:
        src = row.get("source_text", "")
        out = row.get("output_text", "")
        if not src or not out:
            return None

        native_st = row.get("source_type",
                            SOURCE_REPHRASE) or SOURCE_REPHRASE
        # Classify the pair's actual shape, then pick which
        # source_type's templates to render under. ``effective_st``
        # may differ from ``native_st`` when the user's checked set
        # excludes the native bucket but the shape supports a checked
        # one — e.g. a corpus row with summarisation-shape data
        # repurposed into the plot bucket because only "plot" was
        # ticked. Returns None when no checked type can serve the
        # shape, in which case the caller drops the row rather than
        # emit a mis-shaped training pair.
        #
        # Caller can stamp ``_force_shape`` on the row dict to skip
        # classification — used by the sliding-window expander in
        # ``export_jsonl`` so a windowed corpus row stays classified
        # as ``continuation`` even when the growing context makes
        # the per-window ratio drift toward summarisation territory.
        shape = (row.get("_force_shape")
                 or RephraseDatabase._classify_row_shape(
                     src, out, native_st))
        # Optional content-kind hint (``craft`` / ``narrative`` /
        # ``unknown``) — supplied by the export pipeline when it has
        # already classified the row (e.g. for the genre filter's
        # fuzzy keep-craft escape) so we avoid re-classifying. When
        # absent, the resolver falls back to shape-only logic.
        text_kind = row.get("_kind_hint")
        st = RephraseDatabase._resolve_effective_source_type(
            native_st, shape, checked_types, kind=text_kind)
        if st is None:
            return None
        style = row.get("style", "")
        voice = row.get("voice", "")
        ctx_before = row.get("surrounding_before", "")
        ctx_after = row.get("surrounding_after", "")
        char = row.get("character_name", "")
        genre = row.get("genre", "")
        notes = row.get("notes", "") or ""
        meta = RephraseDatabase._parse_notes_kv(notes)

        # Vary instruction phrasing across rows so the model doesn't
        # memorise one stock template (which then leaks into outputs
        # at inference time as boilerplate like "USER: Continue this
        # passage…"). The variant index is deterministic per row —
        # derived from the row id — so every row always exports the
        # same way but the dataset as a whole shows healthy variety.
        # Each ``templates`` list reduces this index modulo its
        # own length, so different source types can have different
        # pool sizes (corpus has 16, plot variants have 8, etc.).
        # Pools mix register on purpose: formal imperatives, casual
        # lowercase, questions, fragments, and direct one-liners —
        # the realistic distribution of how a user might actually
        # word the same request.
        row_id = row.get("id") or 0
        try:
            variant_seed = int(row_id)
        except (TypeError, ValueError):
            variant_seed = 0

        # Source-aware instruction shaping. Rephrase rows pose a
        # rephrasing task; chat rows are conversational; corpus rows
        # are continuation/style-imitation tasks; worldbuilding/
        # character/plot rows are structured generation.
        if st in (SOURCE_CHAT_WRITING, SOURCE_CHAT_GENERAL):
            instruction = src  # the user's chat message IS the prompt
            input_block = ""
            system = ("You are a helpful writing assistant."
                      if st == SOURCE_CHAT_WRITING
                      else "You are a helpful assistant.")
        elif st == SOURCE_CORPUS:
            # Anchor the instruction in the actual source when we
            # know what it is. The downloader records corpus_title
            # (human-readable) and author for every catalog row.
            title = meta.get("corpus_title", "")
            author = meta.get("author", "") if meta.get("author", "") not in (
                "", "PD", "Public Domain") else ""
            # Catalog titles often already embed the author (e.g.
            # "Frankenstein — Mary Shelley (1818)"). When they do,
            # drop the redundant "by <author>" so the instruction
            # reads naturally instead of doubling the attribution.
            if author and title and author.lower() in title.lower():
                author = ""
            attribution = ""
            if title and author:
                attribution = f" of *{title}* by {author}"
            elif title:
                attribution = f" of *{title}*"
            elif author:
                attribution = f" of {author}"
            elif voice:
                attribution = f" of {voice}"
            genre_tail = f" ({genre} genre)" if genre else ""
            attr_or = attribution or ""
            attr_voice = (
                f", staying in the style{attribution}"
                if attribution else "")
            templates = [
                # Formal imperatives — the original 4
                f"Continue this passage in the prose style"
                f"{attribution}{genre_tail}.",
                f"Write the next paragraphs as the author"
                f"{attribution} would{genre_tail}.",
                f"Pick up where this passage leaves off, matching "
                f"the voice and rhythm{attribution}{genre_tail}.",
                f"Continue this passage. Match the diction, "
                f"pacing, and sentence shape{attribution}{genre_tail}.",
                # Casual / lowercase
                f"keep going in the same voice{attr_or}",
                f"more like this{attr_or}",
                f"same voice — keep going",
                # Questions
                f"What comes next{attr_voice}?",
                f"How would this passage continue{attr_or}?",
                # Short fragments
                f"Continue.",
                f"More.",
                f"Next paragraph{attr_or}.",
                # Polite / spoken-style
                f"Could you continue this passage"
                f"{attribution}{genre_tail}?",
                f"Please pick up from here"
                f"{attribution}{genre_tail}.",
                # Direct
                f"Extend this excerpt{attribution}{genre_tail}.",
                f"Finish the paragraph in the same authorial "
                f"register{attribution}{genre_tail}.",
            ]
            instruction = templates[variant_seed % len(templates)]
            input_block = src
            system = ("You imitate the prose style of the source text "
                      "you are given — diction, sentence rhythm, and "
                      "voice — without breaking out into commentary.")
        elif st == SOURCE_WORLDBUILDING:
            element = meta.get("element", "") or "element"
            # Pretty-print the element name (e.g. "magic_system"
            # → "magic system") so the prompt reads naturally.
            etype = element.replace("_", " ")
            setting = ""
            if genre:
                setting = f" for a {genre} setting"
            elif meta.get("setting"):
                setting = f" for the {meta['setting']} setting"
            templates = [
                # Formal imperatives
                f"Design a worldbuilding {etype}{setting} from "
                f"the brief.",
                f"Expand this brief into a complete worldbuilding "
                f"{etype}{setting}.",
                f"Generate a rich, internally-consistent {etype}"
                f"{setting} from the seed below.",
                f"Build out a {etype}{setting} that fits the brief.",
                f"Develop the {etype}{setting} from this seed.",
                # Casual / fragment
                f"flesh out this {etype}{setting}",
                f"make me a {etype}{setting}",
                f"full {etype}{setting}, please",
                # Questions
                f"What does this {etype} look like{setting}?",
                f"How does this {etype} work{setting}?",
                # Direct
                f"Worldbuild this {etype}{setting}.",
                f"Render the {etype}{setting} described here.",
                f"Take this brief and design a {etype}{setting}.",
                f"Sketch out the {etype}{setting}.",
            ]
            instruction = templates[variant_seed % len(templates)]
            input_block = src  # The brief / seed text
            system = ("You are a worldbuilding assistant. You take a "
                      "brief and expand it into a coherent, vivid "
                      "element that fits the setting it is for.")
        elif st == SOURCE_CHARACTER:
            # When the row has a character name we name them in the
            # instruction — the model is being shown a brief→profile
            # mapping for that specific character.
            who = f" for {char}" if char else ""
            genre_tail = f" in a {genre} story" if genre else ""
            templates = [
                # Formal imperatives
                f"Write a complete character profile{who}{genre_tail} "
                f"from the brief below.",
                f"Expand this brief into a vivid character profile"
                f"{who}{genre_tail}.",
                f"Build out a character profile{who}{genre_tail} — "
                f"appearance, voice, motivations, contradictions.",
                f"Generate a fully-realised character{who}{genre_tail} "
                f"from the seed below.",
                f"Develop the character{who}{genre_tail} from this brief.",
                # Casual / fragment
                f"make me a character{who}{genre_tail}",
                f"sketch out{who}{genre_tail} from this brief",
                f"give me the full character{who}{genre_tail}",
                # Questions
                f"Who is this person{(' — ' + char) if char else ''}"
                f"{genre_tail}?",
                f"How would you describe{who}{genre_tail}?",
                # Direct
                f"Profile{who}{genre_tail}, full detail.",
                f"Flesh out{who}{genre_tail}: appearance, voice, "
                f"motivation, flaws.",
                f"Take this brief and turn it into a character"
                f"{who}{genre_tail}.",
                f"From this seed, write the character"
                f"{who}{genre_tail}.",
            ]
            instruction = templates[variant_seed % len(templates)]
            input_block = src  # Brief / traits / archetype
            system = ("You are a character designer. You take a brief "
                      "and expand it into a vivid character with "
                      "internal consistency, contradictions, and a "
                      "clear voice.")
        elif st == SOURCE_PLOT:
            # Different sub-shapes of plot row: pacing pairs, full
            # outlines, story-event seeds, and (new) chapter-summary
            # pairs from corpora like BookSum. We pick a sub-family
            # by data shape first (cheaper, more reliable) and fall
            # back to notes-based hints for the synthesis-pipeline
            # variants. ``shape == "summarization"`` is the BookSum
            # case: long input → short output, where the right task
            # is plot extraction, not "expand this premise".
            if shape == "summarization":
                kind = "summarize"
            else:
                kind = meta.get("plot_kind", "")
                if not kind:
                    if "pacing" in notes.lower():
                        kind = "pacing"
                    elif "event" in notes.lower():
                        kind = "event"
                    else:
                        kind = "outline"
            genre_tail = f" in the {genre} genre" if genre else ""
            voice_tail = f" in {voice}'s voice" if voice else ""
            if kind == "summarize":
                # New family for (long_text, short_summary) pairs.
                # The instruction asks the model to PRODUCE a plot
                # summary FROM the chapter — matching the actual
                # data direction. Repurposing-friendly: a corpus row
                # with summarisation shape gets these templates when
                # the user has plot checked but not corpus.
                templates = [
                    # Formal imperatives
                    f"Summarise this chapter into its key plot beats"
                    f"{genre_tail}{voice_tail}.",
                    f"Extract the plot from this chapter as an "
                    f"ordered beat list{genre_tail}{voice_tail}.",
                    f"Write a tight plot summary of the chapter "
                    f"below{genre_tail}{voice_tail}.",
                    f"Condense this chapter into a "
                    f"{genre or 'plot-focused'} summary"
                    f"{voice_tail}.",
                    f"Reduce the chapter below to its essential "
                    f"plot moves{genre_tail}{voice_tail}.",
                    # Casual / fragment
                    f"plot summary of this{genre_tail}",
                    f"key beats only{genre_tail}",
                    f"what actually happens here{voice_tail}",
                    # Questions
                    f"What are the plot beats of this chapter"
                    f"{genre_tail}?",
                    f"Could you summarise the plot of this"
                    f"{voice_tail}?",
                    # Direct
                    f"Beat-list this chapter{genre_tail}{voice_tail}.",
                    f"Strip this down to plot{genre_tail}{voice_tail}.",
                ]
            elif kind == "pacing":
                templates = [
                    # Formal
                    f"Rewrite this passage to match the pacing of "
                    f"{genre or 'the target'} fiction{voice_tail}.",
                    f"Adjust the sentence length and beat rhythm of "
                    f"this passage{genre_tail}{voice_tail}.",
                    f"Pace this passage like a "
                    f"{genre or 'genre-appropriate'} scene"
                    f"{voice_tail}.",
                    f"Tighten or loosen this passage so its pacing "
                    f"fits{genre_tail}{voice_tail}.",
                    # Casual / fragment
                    f"make this read like {genre or 'the target'} "
                    f"fiction{voice_tail}",
                    f"same content, {genre or 'genre'} pacing"
                    f"{voice_tail}",
                    # Questions / polite
                    f"Could you re-pace this{genre_tail}{voice_tail}?",
                    f"Rework the rhythm of this passage"
                    f"{genre_tail}{voice_tail}.",
                ]
            elif kind == "event":
                templates = [
                    # Formal
                    f"Develop this story-event seed into a full beat"
                    f"{genre_tail}{voice_tail}.",
                    f"Expand this plot event into the scene it "
                    f"implies{genre_tail}{voice_tail}.",
                    f"Write the beat that this event seed describes"
                    f"{genre_tail}{voice_tail}.",
                    f"Turn this seed into a story event with stakes "
                    f"and outcome{genre_tail}{voice_tail}.",
                    # Casual / fragment
                    f"build out the event{genre_tail}{voice_tail}",
                    f"flesh out this beat{genre_tail}{voice_tail}",
                    # Questions
                    f"What happens in this event{genre_tail}"
                    f"{voice_tail}?",
                    f"How does this beat play out{genre_tail}"
                    f"{voice_tail}?",
                ]
            else:
                templates = [
                    # Formal
                    f"Generate a story outline{genre_tail}{voice_tail}"
                    f" from the premise below.",
                    f"Expand this premise into an outline with clear "
                    f"beats{genre_tail}{voice_tail}.",
                    f"Build an act-structured outline{genre_tail}"
                    f"{voice_tail} from the brief.",
                    f"Outline the story implied by the premise below"
                    f"{genre_tail}{voice_tail}.",
                    # Casual / fragment
                    f"plot it out{genre_tail}{voice_tail}",
                    f"map out this story{genre_tail}{voice_tail}",
                    f"give me the outline{genre_tail}{voice_tail}",
                    # Questions
                    f"Where does this premise go{genre_tail}"
                    f"{voice_tail}?",
                ]
            instruction = templates[variant_seed % len(templates)]
            input_block = src
            # The summarize sub-family teaches plot extraction from a
            # full chapter — different task than the premise→outline
            # / event→beat / pacing-rewrite families, so it gets its
            # own system prompt. The other three share the generic
            # plot-structure prompt because they all build narrative
            # forward from a seed.
            if kind == "summarize":
                system = ("You are a plot-extraction assistant. You "
                          "read a chapter or scene and produce a "
                          "tight, beat-level summary that captures "
                          "the story moves without lapsing into "
                          "prose imitation.")
            else:
                system = ("You are a plot-structure assistant. You "
                          "take a premise and produce coherent, "
                          "well-paced narrative beats.")
        else:  # rephrase / agent / default
            tone_clauses = []
            if style:
                tone_clauses.append(f"in a {style} tone")
            if voice:
                tone_clauses.append(f"in {voice}'s voice")
            elif char:
                tone_clauses.append(f"in {char}'s voice")
            if genre:
                tone_clauses.append(f"({genre} genre)")
            tone_tail = (" " + " ".join(tone_clauses)) if tone_clauses else ""
            templates = [
                # Formal imperatives
                f"Rephrase the following passage{tone_tail}.",
                f"Rewrite this passage{tone_tail}, preserving "
                f"meaning.",
                f"Revise the passage below{tone_tail}.",
                f"Reword the passage{tone_tail} while keeping the "
                f"meaning intact.",
                f"Restate the passage below{tone_tail}.",
                # Casual / fragment
                f"same meaning, different words{tone_tail}",
                f"polish this{tone_tail}",
                f"tighten this{tone_tail}",
                f"same idea, fresh phrasing{tone_tail}",
                # Questions / polite
                f"Could you rewrite this{tone_tail}?",
                f"Could you say this another way{tone_tail}?",
                # Direct
                f"Try this passage another way{tone_tail}.",
                f"Edit for clarity{tone_tail}.",
                f"Find a different way to say this{tone_tail}.",
            ]
            instruction = templates[variant_seed % len(templates)]
            ctx = ""
            if ctx_before or ctx_after:
                ctx = (f"Context:\n[before] {ctx_before}\n"
                       f"[after] {ctx_after}\n\n")
            input_block = f"{ctx}Passage:\n{src}".strip()
            system = ("You are a creative writing assistant who rewrites "
                      "prose while preserving voice.")

        # ``format_type`` is always ``instruction`` now: every row
        # the formatter emits carries a real instruction template
        # ("Continue this passage in the prose style of *Frankenstein*",
        # "Summarise this chapter into beats", etc.) and a clear
        # prompt/output boundary. The trainer masks the prompt
        # tokens during loss computation so the model only learns
        # to predict the assistant turn — not the variable
        # instruction template, which would otherwise leak in as
        # boilerplate. Corpus rows used to default to
        # ``continuation`` (no masking, learn-the-whole-passage),
        # but that polluted voice signal with template memorisation
        # — switching to ``instruction`` keeps voice training
        # (the continuation IS the author) without the leak.
        format_type = "instruction"

        # ``source_type`` in the emitted metadata is the *effective*
        # type (what the model is being trained on). When the row
        # was repurposed (effective != native), we also record
        # ``original_source_type`` so the trainer + downstream
        # tooling can audit the repurposing without losing the trail.
        meta_block = {
            "source_type": st,
            "format_type": format_type,
            "system_prompt": system,
            "style": style,
            "voice": voice,
            "character": char,
            "genre": genre,
            "rating": row.get("rating", ""),
            "created_at": row.get("created_at", ""),
            "shape": shape,
        }
        if native_st != st:
            meta_block["original_source_type"] = native_st

        if fmt == "chat":
            user_msg = (f"{instruction}\n\n{input_block}"
                        if input_block else instruction)
            return {
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                    {"role": "assistant", "content": out},
                ],
                "metadata": meta_block,
            }
        if fmt == "raw":
            return row
        # Alpaca-style instruction format. Metadata carries enough
        # for the trainer to reconstruct chat-template messages and
        # apply correct loss masking — the trainer doesn't have to
        # second-guess what kind of row it's looking at.
        return {
            "instruction": instruction,
            "input": input_block,
            "output": out,
            "metadata": meta_block,
        }


# ── Singleton helper ──

_instance: Optional[RephraseDatabase] = None


def get_rephrase_database(path: Optional[Path] = None) -> RephraseDatabase:
    global _instance
    if _instance is None or (path and _instance.db_path != Path(path)):
        _instance = RephraseDatabase(path)
    return _instance


def is_collection_enabled() -> bool:
    """Read the OS-level opt-in flag."""
    try:
        from src.config.creativeos_config import get_creativeos_config
        return bool(get_creativeos_config().get(
            "enable_rephrase_data_collection", False))
    except Exception:
        return False
