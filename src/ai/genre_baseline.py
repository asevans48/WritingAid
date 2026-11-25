"""Every measure beside published books in the book's genre (piece P.3).

A **genre baseline** gives, for each genre, the range published chapters
show on the measures the readiness checks use: sentence length and
variety, dialogue share, adverbs, passive voice, readability and chapter
length. It is computed once from the public-domain books the Training
Studio has downloaded (``~/.creativeos/corpus_downloads``, the books each
genre lists in ``src/data/genres.py``), with the same code the checks
use, and stored in ``~/.creativeos/genre_baseline.json``::

    venv/bin/python scripts/genre_baseline.py

* **One function per question.** ``threshold(name, genre, fixed)`` is
  what ``CheckContext.threshold`` asks: the genre's figure when there is
  one, else the fixed figure, unchanged. ``usable(genre, measure)`` gives a
  measure's range, or None.
* **Honest about thin data.** A genre needs ``MIN_BOOKS`` books before its
  range is used; with fewer, the check keeps its fixed figure and says so
  (``line``). No baseline file at all: nothing changes, not even a message.
* **CONLIT for sentence length only.** Where the Training Studio's CONLIT
  statistics (about 2,750 contemporary books) give ``MIN_BOOKS`` or more
  books for a genre, its sentence length replaces the Gutenberg books'
  (contemporary is closer to the writer's market). CONLIT counts tokens
  (punctuation marks and the parts of "didn't" each count), so its figures
  are divided by ``CONLIT_RATIO`` to give the app's words per sentence.
  Without CONLIT, nothing here changes.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

FORMAT_VERSION = 1
MIN_BOOKS = 5                 # fewer books than this: too little data to compare
CHAPTERS_PER_BOOK = 6         # measured per book, from the middle, so each book weighs the same
MIN_CHAPTER_WORDS, MAX_CHAPTER_WORDS = 500, 15_000

# measure → (what the writer reads, unit after a value)
MEASURES: Dict[str, Tuple[str, str]] = {
    "sentence_length": ("Sentences", " words"),
    "sentence_variety": ("Sentence variety", " of 100"),
    "dialogue_share": ("Dialogue", "%"),
    "adverbs": ("Adverbs", " per 1,000 words"),
    "passive": ("Passive voice", " per 1,000 words"),
    "readability": ("Readability", ""),
    "chapter_length": ("Length", " words"),
}
# Checks whose per-1,000-words threshold the genre sets (the check's name is the measure).
PER_1000 = ("adverbs", "passive")

PLURAL = {"horror": "horror novels", "gothic": "gothic novels", "romance": "romances",
          "mystery": "mysteries", "thriller": "thrillers", "scifi": "science fiction novels",
          "western": "westerns", "frontier": "frontier novels", "fantasy": "fantasy novels",
          "adventure": "adventure novels", "literary": "literary novels"}

SOURCE = ("public-domain books downloaded in the Training Studio (Project Gutenberg), "
          "measured with the app's own checks")

# CONLIT (sentence length only). Its avg_sentence_length is tokens per sentence,
# tokens as BookNLP/spaCy make them; the app counts words per sentence. Measured on
# the repo's benchmark prose with spaCy's rule-based tokenizer and sentencizer
# beside the app's own counter (docs/publishing/pieces/33-P.3-…, Outcome):
# 1.12 tokens per word-equivalent on modern prose (95% 1.10 to 1.14 by passage;
# 0.99 to 1.20 on older prose and by sentence-splitting method).
CONLIT_RATIO = 1.12
CONLIT_RATIO_RANGE = (1.05, 1.20)
CONLIT_DIRECT = {"MY", "SF", "ROM"}      # codes that are the genre itself; others are named


# ── The stored baseline ────────────────────────────────────────────────

def baseline_path() -> Path:
    return Path.home() / ".creativeos" / "genre_baseline.json"


_LOADED: Dict[str, Any] = {"key": None, "data": {}}


def load() -> Dict[str, Any]:
    """The stored baseline, or {} when there is none. Read once and reused
    while the file is unchanged; an unreadable file is set aside (safe_store)."""
    path = baseline_path()
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    if _LOADED["key"] != key:
        from src.data import safe_store
        data = safe_store.load(path, {}, expect=dict) or {}
        if not isinstance(data.get("genres"), dict):
            data = {}
        _LOADED.update(key=key, data=data)
    return _LOADED["data"]


def save(data: Dict[str, Any]) -> bool:
    from src.data import safe_store
    path = baseline_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = safe_store.save(path, data)
    _LOADED["key"] = None
    return ok


@dataclass
class GenreRange:
    genre: str
    measure: str
    low: float                 # 10th percentile of published chapters
    mid: float                 # median
    high: float                # 90th percentile
    books: int
    chapters: int
    note: str = ""             # where the figure is from, when not the Gutenberg books

    @property
    def enough(self) -> bool:
        return self.books >= MIN_BOOKS

    @property
    def spread(self) -> bool:
        """False when nine in ten published chapters show the same figure
        (sentence variety is 100 in every book measured: the score tops out,
        so it cannot set a bar). Such a measure is not used."""
        return self.high > self.low

    def span(self) -> str:
        return f"{_fmt(self.measure, self.low)} to {_fmt(self.measure, self.high)}"


def plural(genre: str) -> str:
    if genre in PLURAL:
        return PLURAL[genre]
    try:
        from src.data.genres import display_name
        return f"{display_name(genre).lower()} books"
    except Exception:
        return f"{genre} books"


def range_for(genre: str, measure: str) -> Optional[GenreRange]:
    """The genre's range for a measure, however few books back it; None
    when the baseline has nothing for that genre."""
    if not genre:
        return None
    block = (load().get("genres") or {}).get(genre)
    if not isinstance(block, dict):
        return None
    m = (block.get("measures") or {}).get(measure)
    if not isinstance(m, dict):
        return None
    try:
        return GenreRange(genre, measure, float(m["p10"]), float(m["p50"]), float(m["p90"]),
                          int(m.get("books", block.get("books", 0))), int(m.get("chapters", 0)),
                          str(m.get("note") or ""))
    except (KeyError, TypeError, ValueError):
        return None


def usable(genre: str, measure: str) -> Optional[GenreRange]:
    """The range when enough books back it, else None (use the fixed figure)."""
    r = range_for(genre, measure)
    return r if r is not None and r.enough and r.spread else None


def books_for(genre: str) -> int:
    block = (load().get("genres") or {}).get(genre) if genre else None
    return int(block.get("books", 0)) if isinstance(block, dict) else 0


def per_1000_threshold(r: GenreRange):
    """Needs work above what nine in ten published chapters of the genre show;
    a problem above half as much again (the fixed figures follow the same rule)."""
    from src.ai.readiness import Threshold
    a = round(max(r.high, 0.5), 1)
    b = round(max(a * 1.5, a + 1.0), 1)
    return Threshold(per_1000=(a, b))


def threshold(name: str, genre: str, fixed):
    """The threshold a check uses: the genre's when there is one, else
    ``fixed`` exactly."""
    if name not in PER_1000 or fixed is None or not getattr(fixed, "per_1000", None):
        return fixed
    r = usable(genre, name)
    return per_1000_threshold(r) if r is not None else fixed


def fingerprint(genre: str, used_only: bool = False) -> str:
    """Changes when the genre's figures do; "" when there are none (with
    ``used_only``, also "" when too few books back them to be used)."""
    if not genre:
        return ""
    block = (load().get("genres") or {}).get(genre)
    if not isinstance(block, dict):
        return ""
    if used_only and books_for(genre) < MIN_BOOKS and usable(genre, "sentence_length") is None:
        return ""
    blob = json.dumps(block.get("measures") or {}, sort_keys=True) + f"|{MIN_BOOKS}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def depends(ctx) -> str:
    """For a check's cache key: recompute when the genre's figures change."""
    return "genre:" + fingerprint(getattr(ctx, "genre", "") or "")


# ── What the writer reads ──────────────────────────────────────────────

def _fmt(measure: str, v: float) -> str:
    if measure == "chapter_length":
        return f"{int(round(v, -1)):,}"
    if measure in ("dialogue_share", "readability", "sentence_variety"):
        return f"{v:.0f}"
    return f"{v:.1f}".rstrip("0").rstrip(".") if v < 100 else f"{v:.0f}"


def line(genre: str, measure: str, value: Optional[float] = None) -> str:
    """"Dialogue 31%; published thrillers 35 to 50% (12 books)." for one
    measure; a "too little data" line when the books are too few; "" when
    the baseline has nothing for the genre."""
    r = range_for(genre, measure)
    if r is None:
        return ""
    if not r.enough:
        return thin(genre)
    if not r.spread:                 # the same in every book: says nothing
        return ""
    label, unit = MEASURES[measure]
    head = f"{label} {_fmt(measure, value)}{unit};" if value is not None else f"{label}:"
    books = f"{r.note}, {r.books:,} books" if r.note else f"{r.books} books"
    return f"{head} published {plural(genre)} {r.span()}{unit} ({books})."


def thin(genre: str) -> str:
    n = books_for(genre)
    return (f"Published {plural(genre)}: too little data to compare ({n} book"
            f"{'s' if n != 1 else ''}; {MIN_BOOKS} needed), so the app's usual figure is used.")


def stricter(genre: str) -> List[str]:
    """Labels of the checks whose genre figure is stricter than the fixed one."""
    from src.ai import readiness as rd
    out = []
    for name in PER_1000:
        fixed = rd._thresholds().get(name)
        r = usable(genre, name)
        if r is not None and fixed is not None and fixed.per_1000 \
                and per_1000_threshold(r).per_1000[0] < fixed.per_1000[0]:
            spec = rd.REGISTRY.get(name)
            out.append((spec.label if spec else name).lower())
    r = usable(genre, "sentence_variety")
    if r is not None:
        try:
            from src.ai.chapter_analysis_agent import resolve_genre_profile
            if r.low > resolve_genre_profile(genre).variety_score_target:
                out.append("sentence variety")
        except Exception:
            pass
    return out


def change_note(genre: str, before: str, now: str) -> str:
    """Said once, on the first check after the comparison changed."""
    if before == now:
        return ""
    if not now:
        return "These checks use the app's fixed figures again (no genre figures now)."
    tighter = stricter(genre)
    named = (", ".join(tighter[:-1]) + " and " + tighter[-1]) if len(tighter) > 1 else \
        "".join(tighter)
    tail = (f" Stricter than before for {named}, so a chapter that was ready may now need "
            "work." if tighter else "")
    n = books_for(genre)
    sl = usable(genre, "sentence_length")
    if n < MIN_BOOKS:            # only CONLIT's sentence length is used
        return (f"Sentence length now compared with published {plural(genre)} "
                f"({sl.note}, {sl.books:,} books) rather than a fixed figure.")
    if before and sl is not None and sl.note:   # had genre figures: CONLIT's sentence length is the change
        return (f"Sentence length now compared with published {plural(genre)} "
                f"({sl.note}, {sl.books:,} books); the other measures as before.")
    also = f"; sentence length: {sl.note}, {sl.books:,} books" if sl and sl.note else ""
    return (f"Now compared with published {plural(genre)} ({n} books{also}) "
            f"rather than fixed figures.{tail}")


# ── Building it, once, from the downloaded books ───────────────────────

_HEADING = re.compile(r"\n\s*\n\s*(?:CHAPTER|Chapter|BOOK|[IVXLC]+\.)\s*[IVXLC\d]*[^\n]{0,60}\n",
                      re.M)


def chapters_of(text: str) -> List[str]:
    """A Gutenberg book's chapters (by their headings), lines unwrapped,
    front and back matter dropped. Approximate: a book with no headings
    gives none."""
    text = text.replace("\r\n", "\n")
    start, end = text.find("*** START"), text.find("*** END")
    if start >= 0:
        nl = text.find("\n", start)
        start = nl + 1 if nl >= 0 else start
    body = text[max(start, 0): end if end > 0 else None]
    parts = [p.strip() for p in _HEADING.split(body)]
    parts = [re.sub(r"(?<!\n)\n(?!\n)", " ", p) for p in parts
             if MIN_CHAPTER_WORDS <= len(p.split()) <= MAX_CHAPTER_WORDS]
    return parts


def _middle(items: List[str], take: int) -> List[str]:
    if len(items) <= take:
        return list(items)
    start = (len(items) - take) // 2
    return items[start: start + take]


def measure_chapter(text: str, project=None, scanner=None) -> Dict[str, float]:
    """The chapter's value on every measure, counted the way the checks
    count them (the editor's own style rules for adverbs and passive)."""
    from src.ai import readiness as rd
    rd._load_checks()
    if project is None:
        from src.models.project import Manuscript, WriterProject
        project = WriterProject(name="Genre baseline", manuscript=Manuscript(title="Baseline"))
    chapter = SimpleNamespace(id="genre-baseline", title="", number=1)
    ctx = rd.CheckContext(project, None, chapter, text, is_opening=False, route="agent",
                          genre="", scanner=scanner)
    s = ctx.stats()
    return {
        "sentence_length": round(float(s.avg_sentence_length), 3),
        "sentence_variety": round(float(s.sentence_length_score), 2),
        "dialogue_share": round(float(s.dialogue_percentage), 2),
        "adverbs": float(rd.REGISTRY["adverbs"].fn(ctx).measure or 0.0),
        "passive": float(rd.REGISTRY["passive"].fn(ctx).measure or 0.0),
        "readability": round(float(s.flesch_reading_ease), 2),
        "chapter_length": float(ctx.words),
    }


def _percentiles(values: List[float]) -> Tuple[float, float, float]:
    vals = sorted(values)
    if len(vals) == 1:
        return vals[0], vals[0], vals[0]
    q = statistics.quantiles(vals, n=10, method="inclusive")
    return round(q[0], 2), round(statistics.median(vals), 2), round(q[-1], 2)


def build(books: Iterable[Tuple[str, str, str]], *, source: str = SOURCE,
          progress: Optional[Callable[[str], None]] = None,
          conlit: Optional[List[Any]] = None) -> Dict[str, Any]:
    """The baseline from ``(genre, title, full text)`` per book; with
    ``conlit`` (``ConlitBook`` rows), sentence length from CONLIT where it
    has enough books (``add_conlit``)."""
    from src.ai import readiness as rd
    from src.models.project import Manuscript, WriterProject
    per_genre: Dict[str, Dict[str, Any]] = {}
    for genre, title, text in books:
        chapters = chapters_of(text)
        if not chapters:
            if progress:
                progress(f"  {title}: no chapters found, skipped")
            continue
        project = WriterProject(name=title, manuscript=Manuscript(title=title))
        scanner = rd.Scanner(project, languagetool=False)
        g = per_genre.setdefault(genre, {"titles": [], "values": {}, "lengths": []})
        g["titles"].append(title)
        g["lengths"].extend(float(len(c.split())) for c in chapters)
        for c in _middle(chapters, CHAPTERS_PER_BOOK):
            for k, v in measure_chapter(c, project, scanner).items():
                if k != "chapter_length":
                    g["values"].setdefault(k, []).append(v)
        if progress:
            progress(f"  {genre}: {title} ({len(chapters)} chapters)")
    genres: Dict[str, Any] = {}
    for genre, g in per_genre.items():
        n = len(g["titles"])
        measures = {}
        for k, vals in list(g["values"].items()) + [("chapter_length", g["lengths"])]:
            if not vals:
                continue
            lo, mid, hi = _percentiles(vals)
            measures[k] = {"p10": lo, "p50": mid, "p90": hi, "books": n, "chapters": len(vals)}
        genres[genre] = {"books": n, "titles": sorted(g["titles"]), "measures": measures}
    data = {"format_version": FORMAT_VERSION, "made_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": source, "min_books": MIN_BOOKS, "genres": genres}
    if conlit:
        add_conlit(data, conlit)
    return data


# ── CONLIT, for sentence length ────────────────────────────────────────

def conlit_csv(path: Optional[Path] = None) -> Optional[Path]:
    """CONLIT_META.csv: ``path`` if given, else where the Training Studio
    keeps it (``~/.creativeos/conlit_path.txt`` or ``~/.creativeos/conlit/``)."""
    if path is not None:
        return Path(path) if Path(path).is_file() else None
    from src.data.conlit_loader import get_configured_conlit_path
    return get_configured_conlit_path()


def _conlit_note(codes: List[str]) -> str:
    from src.data.conlit_loader import CONLIT_GENRE_LABELS
    named = [CONLIT_GENRE_LABELS.get(c, c).lower() for c in codes if c not in CONLIT_DIRECT]
    return "contemporary" + (f" {' and '.join(named)}" if named else "") + ", CONLIT"


def add_conlit(data: Dict[str, Any], conlit_books: List[Any]) -> Dict[str, Any]:
    """Per-genre sentence length from CONLIT, converted to the app's words per
    sentence (÷ ``CONLIT_RATIO``). Used in place of the Gutenberg books' figure
    where CONLIT has ``MIN_BOOKS`` or more books for the genre; both are kept in
    the block's ``sentence_length_sources``. Other measures are untouched."""
    from src.data.conlit_loader import CONLIT_GENRE_MAP
    by_genre: Dict[str, Dict[str, Any]] = {}
    chars, wordlen = [], []
    for b in conlit_books:
        tc, ch, wl = getattr(b, "token_count", None), getattr(b, "total_characters", None), \
            getattr(b, "avg_word_length", None)
        if tc and ch:
            chars.append(ch / tc)
        if wl:
            wordlen.append(wl)
        genre = CONLIT_GENRE_MAP.get(getattr(b, "conlit_genre", "") or "", "")
        v = getattr(b, "avg_sentence_length", None)
        if not genre or v is None or not (0 < v < 200):
            continue
        g = by_genre.setdefault(genre, {"values": [], "codes": set()})
        g["values"].append(float(v))
        g["codes"].add(b.conlit_genre)
    genres = data.setdefault("genres", {})
    used = {}
    for genre, g in sorted(by_genre.items()):
        lo, mid, hi = _percentiles(g["values"])
        n = len(g["values"])
        entry = {"p10": round(lo / CONLIT_RATIO, 2), "p50": round(mid / CONLIT_RATIO, 2),
                 "p90": round(hi / CONLIT_RATIO, 2), "books": n, "chapters": 0,
                 "source": "conlit", "note": _conlit_note(sorted(g["codes"])),
                 "tokens": {"p10": lo, "p50": mid, "p90": hi}, "ratio": CONLIT_RATIO}
        if genre not in genres and n < MIN_BOOKS:
            continue                 # nothing to add: too few books, and no Gutenberg figures
        block = genres.setdefault(genre, {"books": 0, "titles": [], "measures": {}})
        measures = block.setdefault("measures", {})
        sources = {"conlit": entry}
        if "sentence_length" in measures:
            sources["gutenberg"] = measures["sentence_length"]
        block["sentence_length_sources"] = sources
        if n >= MIN_BOOKS:
            measures["sentence_length"] = entry
            used[genre] = n
    data["source"] = (data.get("source") or SOURCE) + (
        "; sentence length from CONLIT (contemporary books) where it has "
        f"{MIN_BOOKS} or more for the genre")
    data["conlit"] = {
        "books": len(conlit_books), "ratio": CONLIT_RATIO, "ratio_range": list(CONLIT_RATIO_RANGE),
        "genres": {k: len(v["values"]) for k, v in sorted(by_genre.items())}, "used": used,
        # For the writer's run to confirm what CONLIT counts (see --show).
        "chars_per_token": round(statistics.median(chars), 2) if chars else None,
        "avg_word_length": round(statistics.median(wordlen), 2) if wordlen else None,
    }
    return data


# When CONLIT_META.csv has moved or been deleted, the Training Studio's saved
# summary (conlit_stats.json: mean, median and spread per genre) still holds
# sentence length. It has no percentiles, so the 10th and 90th come from the
# mean and spread (per-book averages are close to a bell curve): mean ∓ 1.2816 sd.
_Z90 = 1.2816


def conlit_summary_path() -> Path:
    return Path.home() / ".creativeos" / "conlit_stats.json"


def load_conlit_summary(path: Optional[Path] = None) -> Dict[str, Any]:
    """The saved CONLIT summary, or {} (missing or unreadable)."""
    try:
        d = json.loads(Path(path or conlit_summary_path()).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("by_genre"), dict) else {}
    except Exception:
        return {}


def add_conlit_summary(data: Dict[str, Any], summary: Dict[str, Any]) -> Dict[str, Any]:
    """``add_conlit`` from the saved summary instead of the CSV's rows."""
    from src.data.conlit_loader import CONLIT_GENRE_MAP
    codes_for = {}
    for code, genre in CONLIT_GENRE_MAP.items():
        codes_for.setdefault(genre, []).append(code)
    genres = data.setdefault("genres", {})
    used, counts = {}, {}
    for genre, s in sorted((summary.get("by_genre") or {}).items()):
        try:
            mean = float(s["avg_sentence_length__mean"])
            sd = float(s["avg_sentence_length__stdev"])
            mid = float(s.get("avg_sentence_length__median", mean))
            n = int(s.get("avg_sentence_length__n", s.get("n_books", 0)))
        except (KeyError, TypeError, ValueError):
            continue
        counts[genre] = n
        lo, hi = round(mean - _Z90 * sd, 2), round(mean + _Z90 * sd, 2)
        entry = {"p10": round(lo / CONLIT_RATIO, 2), "p50": round(mid / CONLIT_RATIO, 2),
                 "p90": round(hi / CONLIT_RATIO, 2), "books": n, "chapters": 0,
                 "source": "conlit", "note": _conlit_note(sorted(codes_for.get(genre, []))),
                 "tokens": {"p10": lo, "p50": mid, "p90": hi}, "ratio": CONLIT_RATIO,
                 "from_summary": True}
        if genre not in genres and n < MIN_BOOKS:
            continue
        block = genres.setdefault(genre, {"books": 0, "titles": [], "measures": {}})
        measures = block.setdefault("measures", {})
        sources = {"conlit": entry}
        if "sentence_length" in measures:
            sources["gutenberg"] = measures["sentence_length"]
        block["sentence_length_sources"] = sources
        if n >= MIN_BOOKS:
            measures["sentence_length"] = entry
            used[genre] = n
    if counts:
        data["source"] = (data.get("source") or SOURCE) + (
            "; sentence length from CONLIT's saved summary (contemporary books) where it has "
            f"{MIN_BOOKS} or more for the genre")
        data["conlit"] = {"books": int(summary.get("n_books_total") or sum(counts.values())),
                          "ratio": CONLIT_RATIO, "ratio_range": list(CONLIT_RATIO_RANGE),
                          "genres": counts, "used": used, "from_summary": True,
                          "chars_per_token": None, "avg_word_length": None}
    return data


def downloaded_books(corpus_dir: Optional[Path] = None) -> List[Tuple[str, str, Path]]:
    """(genre, title, file) for every single-book corpus a genre lists that
    has been downloaded. A book listed under two genres counts in both."""
    from src.data.corpus_catalog import find_entry
    from src.data.genres import GENRES
    corpus_dir = Path(corpus_dir) if corpus_dir else Path.home() / ".creativeos" / "corpus_downloads"
    out = []
    for genre, info in GENRES.items():
        for cid in info.get("corpora", []) or []:
            entry = find_entry(cid)
            if entry is None or entry.format != "gutenberg":
                continue
            f = corpus_dir / f"{cid}.txt"
            if f.is_file():
                out.append((genre, entry.name or cid, f))
    return out


def load_conlit(path: Optional[Path] = None) -> List[Any]:
    """CONLIT's rows, or [] when it isn't there or can't be read."""
    csv_path = conlit_csv(path)
    if csv_path is None:
        return []
    try:
        from src.data.conlit_loader import load_conlit_metadata
        return load_conlit_metadata(csv_path)
    except Exception:
        return []


def build_from_downloads(corpus_dir: Optional[Path] = None,
                         progress: Optional[Callable[[str], None]] = None,
                         conlit: Optional[List[Any]] = None) -> Dict[str, Any]:
    def books():
        for genre, title, f in downloaded_books(corpus_dir):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            yield genre, title, text
    return build(books(), progress=progress, conlit=conlit)
