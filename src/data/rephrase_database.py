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
                     corpus_collection_keys: Optional[Iterable[str]] = None
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
        # Per-corpus collection filter — applies only to corpus rows.
        # Each row's collection key is derived from its notes via
        # ``_parse_collection_id``. Default ``None`` = include every
        # collection; an explicit empty list excludes all corpus rows.
        collection_filter = (set(corpus_collection_keys)
                             if corpus_collection_keys is not None
                             else None)
        n = 0
        with open(output_path, 'w', encoding='utf-8') as f:
            for r in rows:
                src = r.get("source_type") or SOURCE_REPHRASE
                if st_filter and src not in st_filter:
                    continue
                row_rating = r.get("rating", "neutral") or "neutral"
                if rating_order.get(row_rating, 2) < threshold:
                    continue
                # Genre filter: only restrict CORPUS rows. Untagged
                # corpus rows (genre=="") are universal context and
                # always pass; tagged ones must overlap the wanted set.
                if wanted_genres and src == SOURCE_CORPUS:
                    row_genre_raw = (r.get("genre") or "").lower().strip()
                    if row_genre_raw:
                        row_genres = {g.strip() for g in row_genre_raw
                                      .replace(";", ",").split(",")
                                      if g.strip()}
                        if not (row_genres & wanted_genres):
                            continue
                # Per-collection filter: corpus rows whose collection
                # key isn't in the user's selection get skipped. User-
                # voice rows (rephrase / chat) and other source types
                # are unaffected — the filter is corpus-specific.
                if collection_filter is not None and src == SOURCE_CORPUS:
                    key, _label, _kind = self._parse_collection_id(
                        r.get("notes") or "")
                    if key not in collection_filter:
                        continue
                obj = self._format_row(r, fmt)
                if obj is None:
                    continue
                # Oversample user-voice rows by repeating them in the
                # output. The trainer sees identical-looking but
                # repeated examples, which is exactly what shifts the
                # loss toward those rows.
                copies = repeat if src in self.USER_VOICE_SOURCES else 1
                for _ in range(copies):
                    f.write(json.dumps(obj, ensure_ascii=False))
                    f.write("\n")
                    n += 1
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
    def _format_row(row: Dict[str, Any], fmt: str) -> Optional[Dict[str, Any]]:
        src = row.get("source_text", "")
        out = row.get("output_text", "")
        if not src or not out:
            return None

        st = row.get("source_type", SOURCE_REPHRASE) or SOURCE_REPHRASE
        style = row.get("style", "")
        voice = row.get("voice", "")
        ctx_before = row.get("surrounding_before", "")
        ctx_after = row.get("surrounding_after", "")
        char = row.get("character_name", "")
        genre = row.get("genre", "")
        notes = row.get("notes", "") or ""

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
            extras = []
            if voice:
                extras.append(f"in {voice}'s voice")
            if genre:
                extras.append(f"({genre} genre)")
            tail = (" " + " ".join(extras)) if extras else ""
            instruction = (f"Continue this passage in the same voice "
                           f"and style as the author{tail}.")
            input_block = src
            system = ("You write in the voice of the user's chosen "
                      "author corpus.")
        elif st == SOURCE_WORLDBUILDING:
            # Pull element type out of notes if present
            element = ""
            for tok in notes.split():
                if tok.startswith("element="):
                    element = tok.split("=", 1)[1]
                    break
            etype = element or "element"
            instruction = (f"Generate a worldbuilding {etype}"
                           + (f" for a {genre} setting" if genre else "")
                           + ".")
            input_block = src  # The brief / seed text
            system = ("You are a worldbuilding assistant. Generate rich, "
                      "internally-consistent fictional worlds.")
        elif st == SOURCE_CHARACTER:
            instruction = (f"Generate a complete character profile"
                           + (f" for a {genre} story" if genre else "")
                           + ".")
            input_block = src  # Brief / traits / archetype
            system = ("You are a character designer. Create vivid, "
                      "internally-consistent characters with depth.")
        elif st == SOURCE_PLOT:
            instruction = (f"Generate a story outline"
                           + (f" in the {genre} genre" if genre else "")
                           + (f" in {voice}'s voice" if voice else "")
                           + ".")
            input_block = src
            system = ("You are a plot-structure assistant. Generate "
                      "compelling narratives with clear beats.")
        else:  # rephrase / agent / default
            instr_parts = ["Rephrase the following passage"]
            if style:
                instr_parts.append(f"in a {style} tone")
            if voice:
                instr_parts.append(f"in {voice}'s voice")
            elif char:
                instr_parts.append(f"in {char}'s voice")
            if genre:
                instr_parts.append(f"({genre} genre)")
            instruction = " ".join(instr_parts) + "."
            ctx = ""
            if ctx_before or ctx_after:
                ctx = (f"Context:\n[before] {ctx_before}\n"
                       f"[after] {ctx_after}\n\n")
            input_block = f"{ctx}Passage:\n{src}".strip()
            system = ("You are a creative writing assistant who rewrites "
                      "prose while preserving voice.")

        # ``format_type`` tells the trainer how to apply the chat
        # template + loss masking at training time:
        #   * ``instruction`` — clear user-question/assistant-answer
        #     split. Mask the prompt; only learn to predict the
        #     assistant turn. Used for rephrase, character, world-
        #     building, plot, chat.
        #   * ``continuation`` — no real prompt boundary; the model
        #     should learn to imitate the whole passage. Used only
        #     for legacy raw corpus rows where the "input" is just an
        #     opener sentence (any modern run uses the instruction
        #     template above for corpus too — kept for fallback).
        if st == SOURCE_CORPUS:
            format_type = "continuation"
        else:
            format_type = "instruction"

        if fmt == "chat":
            user_msg = (f"{instruction}\n\n{input_block}"
                        if input_block else instruction)
            return {
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                    {"role": "assistant", "content": out},
                ],
                "metadata": {
                    "source_type": st,
                    "format_type": format_type,
                    "system_prompt": system,
                },
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
            "metadata": {
                "source_type": st,
                "format_type": format_type,
                "system_prompt": system,
                "style": style,
                "voice": voice,
                "character": char,
                "genre": genre,
                "rating": row.get("rating", ""),
                "created_at": row.get("created_at", ""),
            },
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
