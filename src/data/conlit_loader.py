"""CONLIT — contemporary-literature statistical dataset.

Andrew Piper's CONLIT (Figshare article 21166171) ships statistical
features for ~2,750 contemporary novels — token counts, sentence
lengths, character counts, POS distributions, supersense categories,
unigram frequencies — paired with genre and metadata labels.

It is **not full text** (license + copyright reasons), so it doesn't
feed the rephrase training corpus. Instead we use it as a
**genre-baseline reference**: "what does mystery's average sentence
length look like? how dense with adjectives is romance?"

Two consumer entry points:

  * ``load_conlit_metadata(csv_path)`` — parses CONLIT_META.csv and
    yields per-book dicts with our canonical genre keys folded in.
  * ``compute_genre_stats(metadata)`` — aggregates per-genre averages
    (token_count, avg_sentence_length, avg_word_length, character
    count, tuldava lexical-complexity score). Returns a dict the UI
    can show next to the user's own corpus stats: "Mystery baseline
    avg sentence length: 14.8 words; your draft is at 11.2."

Plus a Figshare API downloader (``download_conlit_to``) for users who
haven't manually downloaded the dataset.
"""

from __future__ import annotations

import csv
import json
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, Dict, Iterator, List, Optional


# ── CONLIT → canonical genre map ─────────────────────────────
#
# CONLIT mixes real literary genres (MY, SF, ROM…) with
# instrumentality buckets (NYT/PW/BS bestseller lists, BIO/MEM
# non-fiction) in the same Genre column. We map only the fiction
# genres to our taxonomy; the rest stay tagged with their CONLIT
# code so they can still be analyzed but won't auto-route to a
# canonical bucket.

CONLIT_GENRE_MAP: Dict[str, str] = {
    # Fiction genres that map cleanly
    "MY":   "mystery",
    "SF":   "scifi",
    "ROM":  "romance",
    "HIST": "literary",      # historical fiction → no canonical "historical";
                             # closest is literary fiction
    # Below stay as their CONLIT codes (no canonical mapping)
    # YA, MID, MIX, NYT, PW, BS, BIO, MEM — left unmapped so the
    # downstream analyzer can still report on them but the genre
    # filter doesn't conflate "young adult" with literary, etc.
}


CONLIT_GENRE_LABELS: Dict[str, str] = {
    "MY":   "Mystery",
    "SF":   "Science Fiction",
    "ROM":  "Romance",
    "HIST": "Historical Fiction",
    "YA":   "Young Adult",
    "MID":  "Middle Grade",
    "MIX":  "Mixed / Other Fiction",
    "NYT":  "NYT Bestsellers",
    "PW":   "Publishers Weekly Bestsellers",
    "BS":   "Mass-market Bestsellers",
    "BIO":  "Biography (non-fiction)",
    "MEM":  "Memoir (non-fiction)",
}


# Columns of CONLIT_META.csv we promote to typed fields. Anything
# else gets stashed in ``extras`` so we don't lose data if Piper
# adds columns later.
_META_NUMERIC_FIELDS = (
    "Pubdate", "token_count", "total_characters",
    "protagonist_concentration", "avg_sentence_length",
    "avg_word_length", "tuldava_score",
)


@dataclass
class ConlitBook:
    """One row of CONLIT_META.csv, normalized.

    ``canonical_genre`` is empty string when the CONLIT genre code
    doesn't map to our taxonomy (YA, BIO, NYT etc.) — callers should
    fall back to ``conlit_genre`` for display in that case.
    """
    id: str = ""
    category: str = ""              # FIC | NON
    language: str = ""
    conlit_genre: str = ""          # raw CONLIT code (MY, SF, …)
    canonical_genre: str = ""       # "" if unmapped
    pubdate: Optional[int] = None
    author_last: str = ""
    author_first: str = ""
    work_title: str = ""
    author_gender: str = ""
    author_nationality: str = ""
    token_count: Optional[int] = None
    total_characters: Optional[int] = None
    protagonist_concentration: Optional[float] = None
    avg_sentence_length: Optional[float] = None
    avg_word_length: Optional[float] = None
    tuldava_score: Optional[float] = None
    extras: Dict[str, str] = field(default_factory=dict)


def load_conlit_metadata(csv_path: Path) -> List[ConlitBook]:
    """Parse CONLIT_META.csv. Returns one ``ConlitBook`` per row.

    Tolerant of missing fields; rows without a usable Genre or
    token_count are still returned (so the caller sees the full
    corpus) but won't influence the per-genre stats.
    """
    books: List[ConlitBook] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            book = ConlitBook(
                id=(row.get("ID") or "").strip(),
                category=(row.get("Category") or "").strip(),
                language=(row.get("Language") or "").strip(),
                conlit_genre=(row.get("Genre") or "").strip(),
                author_last=(row.get("Author_Last") or "").strip(),
                author_first=(row.get("Author_First") or "").strip(),
                work_title=(row.get("Work_Title") or "").strip(),
                author_gender=(row.get("Author_Gender") or "").strip(),
                author_nationality=(row.get("Author_Nationality") or "").strip(),
            )
            book.canonical_genre = CONLIT_GENRE_MAP.get(
                book.conlit_genre, "")
            for col in _META_NUMERIC_FIELDS:
                raw = (row.get(col) or "").strip()
                if not raw:
                    continue
                try:
                    val = float(raw)
                    setattr(book, col.lower(),
                            int(val) if col in ("Pubdate", "token_count",
                                                 "total_characters")
                            else val)
                except ValueError:
                    book.extras[col] = raw

            # Pubdate uses "pubdate" attr; the loop above sets it.
            # Capture any extra columns we haven't promoted.
            promoted = {"ID", "Category", "Language", "Genre", "Genre2",
                        "Pubdate", "Author_Last", "Author_First",
                        "Work_Title", "Author_Gender",
                        "Author_Nationality"} | set(_META_NUMERIC_FIELDS)
            for k, v in row.items():
                if k not in promoted and v:
                    book.extras[k] = v
            books.append(book)
    return books


def compute_genre_stats(books: List[ConlitBook],
                        *,
                        use_canonical: bool = True
                        ) -> Dict[str, Dict[str, Any]]:
    """Per-genre averages of the numeric features.

    Args:
        books: ``ConlitBook`` records from ``load_conlit_metadata``.
        use_canonical: True (default) → group by our canonical genre
            keys (mystery, scifi, romance, literary). False → group
            by raw CONLIT codes (preserves YA/MID/HIST/etc).

    Returns a dict ``{genre_key: {n_books, avg_sentence_length, ...,
    label}}`` ready to surface in the Training Studio.
    """
    buckets: Dict[str, List[ConlitBook]] = {}
    for b in books:
        key = (b.canonical_genre if use_canonical else b.conlit_genre)
        if not key:
            continue
        buckets.setdefault(key, []).append(b)

    out: Dict[str, Dict[str, Any]] = {}
    for key, group in buckets.items():
        stats: Dict[str, Any] = {
            "n_books": len(group),
            "label": (CONLIT_GENRE_LABELS.get(key, key)
                      if not use_canonical else key.title()),
        }
        for field_name in ("token_count", "total_characters",
                           "protagonist_concentration",
                           "avg_sentence_length", "avg_word_length",
                           "tuldava_score"):
            values = [getattr(b, field_name) for b in group
                      if getattr(b, field_name) is not None]
            if not values:
                continue
            stats[f"{field_name}__mean"] = round(mean(values), 3)
            stats[f"{field_name}__median"] = round(median(values), 3)
            if len(values) >= 2:
                stats[f"{field_name}__stdev"] = round(stdev(values), 3)
            stats[f"{field_name}__n"] = len(values)
        # Author-gender breakdown — useful Piper-style demographic
        gender_counts: Dict[str, int] = {}
        for b in group:
            gender_counts[b.author_gender or "?"] = (
                gender_counts.get(b.author_gender or "?", 0) + 1)
        stats["author_gender"] = gender_counts
        out[key] = stats
    return out


def get_genre_baseline(canonical_genre: str,
                       genre_stats: Dict[str, Dict[str, Any]]
                       ) -> Dict[str, Any]:
    """Return the per-genre stat block for a canonical genre key.

    Empty dict when the genre isn't represented in CONLIT (e.g.
    horror, western, fantasy — none of which CONLIT covers cleanly).
    """
    return genre_stats.get(canonical_genre, {})


def summary_lines(genre_stats: Dict[str, Dict[str, Any]],
                  genre_key: str) -> List[str]:
    """Format a compact CONLIT baseline for display in the UI.

    Returns lines like::

        Mystery baseline (n=234 books):
          avg sentence length: 14.4 words (median 14.1, σ 2.6)
          avg word length:      4.2 chars
          tuldava (lexical):    3.5
          protagonist concentration: 0.34
          token count:          76,500 words/book

    Returns an empty list if the genre isn't in the stats dict.
    """
    s = genre_stats.get(genre_key)
    if not s:
        return []
    label = s.get("label", genre_key.title())
    lines = [f"<b>{label}</b> CONLIT baseline (n={s.get('n_books', 0)} books):"]

    def _fmt(field, name, unit=""):
        m = s.get(f"{field}__mean")
        if m is None:
            return None
        med = s.get(f"{field}__median")
        sd = s.get(f"{field}__stdev")
        bits = []
        if isinstance(m, float):
            bits.append(f"{m:.2f}")
        else:
            bits.append(f"{m:,}")
        if med is not None:
            bits.append(f"median {med:.2f}"
                        if isinstance(med, float) else f"median {med:,}")
        if sd is not None:
            bits.append(f"σ {sd:.2f}")
        return f"  {name}: " + " · ".join(bits) + (f" {unit}" if unit else "")

    for field, name, unit in (
        ("avg_sentence_length",       "avg sentence length",        "words"),
        ("avg_word_length",           "avg word length",            "chars"),
        ("tuldava_score",             "Tuldava (lexical complexity)", ""),
        ("protagonist_concentration", "protagonist concentration",  ""),
        ("total_characters",          "characters per book",        ""),
        ("token_count",               "tokens per book",            "words"),
    ):
        line = _fmt(field, name, unit)
        if line:
            lines.append(line)
    return lines


# ── Figshare downloader ────────────────────────────────────────

CONLIT_FIGSHARE_ARTICLE_ID = "21166171"
_FIGSHARE_API = "https://api.figshare.com/v2/articles/{article_id}"


def download_conlit_to(dest_dir: Path,
                       *,
                       article_id: str = CONLIT_FIGSHARE_ARTICLE_ID,
                       file_name_filter: Optional[List[str]] = None,
                       on_log=None,
                       on_progress=None) -> List[Path]:
    """Fetch CONLIT files from Figshare's public API.

    Args:
        dest_dir: where to save the files (will be created).
        article_id: Figshare article id; defaults to CONLIT 21166171.
        file_name_filter: only download files whose name contains
            any string in this list (case-insensitive). ``None`` →
            download every file in the article. Useful to grab just
            CONLIT_META.csv (~850KB) and skip the multi-hundred-MB
            wordcount zips.
        on_log: optional callable(str) for log lines.
        on_progress: optional callable(bytes_so_far) for byte updates.

    Returns the list of destination paths actually saved.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    log = on_log or (lambda *_: None)

    log(f"Querying Figshare article {article_id}…")
    api_url = _FIGSHARE_API.format(article_id=article_id)
    req = urllib.request.Request(
        api_url, headers={"User-Agent": "CreativeOS/1.0 (CONLIT loader)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        article = json.load(resp)
    files = article.get("files", []) or []
    if not files:
        raise RuntimeError(
            f"No files in Figshare article {article_id}.")

    saved: List[Path] = []
    needles = ([n.lower() for n in file_name_filter]
               if file_name_filter else None)

    for f in files:
        fname = f.get("name") or ""
        if needles and not any(n in fname.lower() for n in needles):
            log(f"  skip {fname}")
            continue
        url = f.get("download_url")
        size = f.get("size", 0)
        if not url:
            log(f"  no download_url for {fname}, skipping")
            continue
        out_path = dest_dir / fname
        log(f"  downloading {fname} ({size:,} bytes)…")
        _stream(url, out_path, on_progress=on_progress)
        saved.append(out_path)
    log(f"Saved {len(saved)} file(s) to {dest_dir}")
    return saved


def _stream(url: str, dest: Path, *,
            on_progress=None,
            chunk: int = 64 * 1024) -> int:
    """Stream a URL to disk; return bytes written."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "CreativeOS/1.0"})
    total = 0
    with urllib.request.urlopen(req, timeout=120) as resp, \
            open(dest, "wb") as out:
        while True:
            buf = resp.read(chunk)
            if not buf:
                break
            out.write(buf)
            total += len(buf)
            if on_progress:
                on_progress(total)
    return total


# ── Convenience: load + analyze in one call ──────────────────

def load_and_summarize(meta_csv_path: Path,
                       *, use_canonical: bool = True) -> Dict[str, Any]:
    """One-shot: parse CONLIT_META.csv and compute the full stats dict.

    Returns ``{"books": [...], "by_genre": {...}, "n_books_total": N,
    "n_genres_with_stats": M}``.
    """
    books = load_conlit_metadata(meta_csv_path)
    by_genre = compute_genre_stats(books, use_canonical=use_canonical)
    return {
        "books": books,
        "by_genre": by_genre,
        "n_books_total": len(books),
        "n_genres_with_stats": len(by_genre),
    }


# ── On-disk cache of computed stats ────────────────────────────
# CONLIT_META.csv is ~850KB and parses fast, but recomputing the
# per-genre aggregates on every UI refresh would be wasteful. We
# write the computed stats dict to ~/.creativeos/conlit_stats.json
# once, then reload from there. The cache is invalidated by
# checking the source CSV's mtime against the cached timestamp.

_CONLIT_CACHE_FILE = Path.home() / ".creativeos" / "conlit_stats.json"
_CONLIT_PATH_HINT_FILE = Path.home() / ".creativeos" / "conlit_path.txt"
_DEFAULT_LOCAL_CONLIT_DIR = Path.home() / ".creativeos" / "conlit"


def set_conlit_path(meta_csv_path: Path) -> None:
    """Persist the path to CONLIT_META.csv so the lazy loader finds it."""
    _CONLIT_PATH_HINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONLIT_PATH_HINT_FILE.write_text(str(meta_csv_path))


def get_configured_conlit_path() -> Optional[Path]:
    """Return the user's saved CONLIT_META.csv path, if any."""
    if _CONLIT_PATH_HINT_FILE.exists():
        try:
            p = Path(_CONLIT_PATH_HINT_FILE.read_text().strip())
            if p.exists():
                return p
        except Exception:
            pass
    # Fallback: check the default CreativeOS location.
    candidate = _DEFAULT_LOCAL_CONLIT_DIR / "CONLIT_META.csv"
    if candidate.exists():
        return candidate
    return None


def get_genre_stats_cached(*, force_reload: bool = False
                           ) -> Optional[Dict[str, Any]]:
    """Return the cached per-canonical-genre stats dict, or None.

    Lazy: parses CONLIT_META.csv on first call, caches to JSON, and
    returns the cached version on subsequent calls. Returns ``None``
    when the user hasn't configured a CONLIT path yet.

    Stats dict is keyed by canonical genre (mystery, scifi, romance,
    literary) — the same keys the rest of CreativeOS uses, so it
    drops in next to genre-mapped corpus stats.
    """
    csv_path = get_configured_conlit_path()
    if csv_path is None:
        return None

    # Cache validity: CSV mtime must not exceed cached mtime.
    csv_mtime = csv_path.stat().st_mtime
    if not force_reload and _CONLIT_CACHE_FILE.exists():
        try:
            cached = json.loads(_CONLIT_CACHE_FILE.read_text())
            if (cached.get("source_path") == str(csv_path)
                    and cached.get("source_mtime", 0) >= csv_mtime):
                return cached.get("by_genre", {})
        except Exception:
            pass  # malformed cache → recompute

    # Recompute and cache
    try:
        books = load_conlit_metadata(csv_path)
    except Exception as e:
        print(f"[conlit_loader] could not parse {csv_path}: {e}")
        return None
    by_genre = compute_genre_stats(books, use_canonical=True)
    by_raw = compute_genre_stats(books, use_canonical=False)

    payload = {
        "source_path": str(csv_path),
        "source_mtime": csv_mtime,
        "n_books_total": len(books),
        "by_genre": by_genre,        # canonical genre keys
        "by_raw_genre": by_raw,      # raw CONLIT codes (YA/HIST/etc)
    }
    try:
        _CONLIT_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONLIT_CACHE_FILE.write_text(json.dumps(payload, indent=2))
    except Exception as e:
        print(f"[conlit_loader] could not write cache: {e}")
    return by_genre
