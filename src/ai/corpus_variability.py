"""Variability audit for the training DB — finds duplicates, repeated
openers, and oversampled sources, then drops them on user approval.

Different intent from ``text_cleaner`` (which detects junk on a
per-row basis: page numbers, JSON blobs, refusals). This module
looks at the *distribution* of rows: which rows are redundant
relative to others, which sources dominate, where the diversity is
weak. Pruning here doesn't remove "bad" rows — it removes
*redundant* ones. The Clean and Prune actions are kept separate so
the user knows which lever they're pulling.

The report is computed without making any changes; the caller
decides which categories to apply (each is opt-in checkbox in the
UI). Backups are written to ``~/.creativeos/cleanup_backup/`` in
the same format the cleaner uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import random
import re
import zlib


# Thresholds. Treated as defaults; the UI exposes them as knobs.

# When dropping near-duplicates, we group by the FIRST N chars of
# output_text. 80 chars ≈ a sentence — long enough to be discriminating
# and short enough that a real duplicate group has identical openers.
DEFAULT_OPENER_HASH_LEN = 80

# Cap any one source at this fraction of the total dataset. Beyond
# this, the model overfits to that source's voice and treats it as
# the prior. 0.40 is a defensible default — strong dominance allowed
# (e.g. a single corpus you actually care about) but not so much
# that other sources drop out of the gradient.
DEFAULT_SOURCE_CAP_PCT = 40.0

# ── Per-row text metrics ──
#
# Two cheap signals for "this row is shallow":
#
# 1. **Compression ratio** = ``len(zlib(text)) / len(text)``. English
#    prose is around 0.35–0.45. Repetitive text — dialogue-tag spam,
#    list-of-features outputs, "the the the" garbage — drops to
#    0.10–0.20. Lower ratio = more repetitive.
# 2. **Type-token ratio** = ``unique_words / total_words``. Captures
#    repeated *vocabulary* even when the surface bytes don't compress
#    well. A row that says "Alice said. Bob said. Carol said." has
#    decent compression but very low TTR.
#
# Both are noisy on short rows so we only flag rows above length
# thresholds. Defaults below were picked by spot-checking the user's
# DB — high enough to skip normal prose, low enough to catch
# pathological rows. UI can expose them as knobs later.

DEFAULT_REPETITIVE_RATIO = 0.25       # rows below this are flagged
DEFAULT_REPETITIVE_MIN_CHARS = 200    # ignore tiny rows
DEFAULT_LOW_TTR = 0.35                # rows below this are flagged
DEFAULT_LOW_TTR_MIN_WORDS = 50        # ignore tiny rows

# ── MinHash near-duplicate detection ──
#
# Catches paraphrased / lightly-edited duplicates that exact-dedup
# misses — e.g. the same passage with different punctuation, one
# word swapped, or extra whitespace. Approach: shingle each row's
# output_text into 5-word windows, MinHash the shingle set into a
# fixed-length signature, and bucket signatures via LSH banding so
# pairwise comparison stays O(N·B) instead of O(N²).
#
# Tuning:
#   * Signature length 64, 16 bands of 4 rows each.
#   * The probability that a pair with similarity ``s`` lands in
#     the same bucket of at least one band is
#     ``1 - (1 - s^4)^16``. At s=0.85 this is ~100%; at s=0.5 it's
#     ~64%. Candidates are cheap to verify, so a higher recall
#     (more candidates) is fine — false positives get filtered
#     by the explicit Jaccard check before pruning.

DEFAULT_MINHASH_NUM_HASHES = 64
DEFAULT_MINHASH_BANDS = 16
DEFAULT_MINHASH_SHINGLE_SIZE = 5
DEFAULT_MINHASH_THRESHOLD = 0.85
DEFAULT_MINHASH_MIN_WORDS = 30   # rows shorter than this can't shingle reliably

# Mersenne prime for universal hashing. (1<<61)-1 is the largest
# Mersenne prime that still leaves room for 64-bit products
# without overflow when reduced via numpy uint64 arithmetic.
_MERSENNE_PRIME = (1 << 61) - 1

# Language detection — opt-in category. ``langdetect`` is the
# simplest pure-Python option. We lazy-import it so the module
# loads even when the dep isn't installed; the audit just skips
# this pass with a "not installed" status in that case.
DEFAULT_LANG_TARGET = "en"
DEFAULT_LANG_MIN_WORDS = 20      # below this langdetect is unreliable

# ── Topic clustering ──
#
# TF-IDF vectorize → TruncatedSVD reduce → MiniBatchKMeans cluster.
# Catches *content* over-representation that surface measures miss:
# two rows about "swords and dragons" written entirely differently
# pass exact-dedup and near-dedup but together over-train the
# model on fantasy combat. This category caps any cluster
# carrying more than ``DEFAULT_TOPIC_CAP_PCT`` of the total to
# that share, randomly down-sampling the surplus.
#
# Optional dep: scikit-learn (~100 MB). Module loads without it;
# the audit returns ``available=False`` and the UI displays a
# "pip install scikit-learn" hint instead of crashing.
DEFAULT_TOPIC_CLUSTERS = 50         # k for k-means
DEFAULT_TOPIC_CAP_PCT = 5.0         # any cluster bigger than this is capped
DEFAULT_TOPIC_MAX_FEATURES = 10000  # vocab size for TF-IDF
DEFAULT_TOPIC_REDUCED_DIM = 50      # SVD dim before clustering

_WORD_RE = re.compile(r"[A-Za-z']+")


def compression_ratio(text: str) -> float:
    """``len(zlib_compress(utf8)) / len(utf8)`` — repetitiveness proxy.

    Returns 1.0 for empty input (treat as "incompressible" so it
    never gets flagged on length grounds alone). zlib level 6 is
    the default — same compression Python's gzip uses, fast in C.
    """
    if not text:
        return 1.0
    raw = text.encode("utf-8", errors="replace")
    if not raw:
        return 1.0
    compressed = zlib.compress(raw, 6)
    return len(compressed) / len(raw)


def type_token_ratio(text: str) -> Tuple[float, int]:
    """Unique-word ratio of ``text``. Returns ``(ratio, n_words)``.

    Tokenisation is a simple A-Za-z word regex — punctuation and
    numbers are dropped. This makes the measure robust to
    formatting differences (curly quotes, em dashes) without
    needing a real NLP tokenizer. Lower-cased so capitalisation
    differences don't inflate uniqueness.

    Returns ``(0.0, 0)`` for empty / wordless input so the caller
    can skip those rows without a divide-by-zero.
    """
    words = _WORD_RE.findall(text or "")
    n = len(words)
    if n == 0:
        return 0.0, 0
    return len(set(w.lower() for w in words)) / n, n


# ── MinHash signing ──

class _MinHasher:
    """Compute MinHash signatures over k-shingles of text.

    Signatures are tuples of length ``num_hashes`` so they can act
    as dict keys for LSH banding. The hash family is universal:
    ``h_i(x) = (a_i * x + b_i) mod P`` where each ``(a_i, b_i)``
    pair is drawn once from a fixed seed so signatures are stable
    across runs in the same Python process.
    """

    def __init__(self, num_hashes: int = DEFAULT_MINHASH_NUM_HASHES,
                 shingle_size: int = DEFAULT_MINHASH_SHINGLE_SIZE,
                 seed: int = 42):
        import numpy as np  # local — keeps module-load cheap on systems w/o numpy
        rng = random.Random(seed)
        self.num_hashes = num_hashes
        self.shingle_size = shingle_size
        # 32-bit (a, b) pairs so the (a * shingle_hash) product
        # fits in uint64 even when the shingle hash is 32-bit too.
        self._A = np.array(
            [rng.randrange(1, _MERSENNE_PRIME) for _ in range(num_hashes)],
            dtype=np.uint64)
        self._B = np.array(
            [rng.randrange(0, _MERSENNE_PRIME) for _ in range(num_hashes)],
            dtype=np.uint64)
        self._np = np
        self._mersenne = self._np.uint64(_MERSENNE_PRIME)
        self._max = self._np.uint64(_MERSENNE_PRIME)

    def signature(self, text: str) -> Optional[Tuple[int, ...]]:
        """Return a length-``num_hashes`` signature for ``text``.

        Returns ``None`` if the text is too short to shingle —
        fewer than ``shingle_size`` words means we can't form even
        one shingle, so there's no signature to compare.
        """
        words = _WORD_RE.findall((text or "").lower())
        if len(words) < self.shingle_size:
            return None
        # Build the shingle set. Python's built-in hash() is fast
        # (~50ns) and randomized per process — fine here because we
        # never persist signatures across runs.
        shingles = set()
        k = self.shingle_size
        for i in range(len(words) - k + 1):
            # 64-bit mask so the value fits in numpy uint64.
            shingles.add(hash(tuple(words[i:i + k])) & ((1 << 64) - 1))
        if not shingles:
            return None
        np = self._np
        # Reduce shingle hashes to 32-bit so (a * x) doesn't
        # overflow uint64 when (a, x) are both 32-bit.
        arr = np.fromiter(
            (s & ((1 << 32) - 1) for s in shingles),
            dtype=np.uint64, count=len(shingles))
        # Vectorized: (a * x + b) mod P for every (a_i, b_i) and
        # every shingle, then take min along the shingle axis.
        # Result shape: (num_hashes,)
        candidates = (self._A[:, None] * arr[None, :]
                      + self._B[:, None]) % self._mersenne
        sig = candidates.min(axis=1)
        return tuple(int(v) for v in sig)


def jaccard_estimate(sig_a: Tuple[int, ...],
                     sig_b: Tuple[int, ...]) -> float:
    """Estimate Jaccard similarity from two MinHash signatures.

    The fraction of positions where the two signatures agree is an
    unbiased estimator of the Jaccard similarity of the underlying
    shingle sets. Variance shrinks as ``1/sqrt(num_hashes)`` — at
    64 hashes the standard error is ~0.06.
    """
    if not sig_a or not sig_b or len(sig_a) != len(sig_b):
        return 0.0
    matches = sum(1 for a, b in zip(sig_a, sig_b) if a == b)
    return matches / len(sig_a)


# ── Language detection ──

_LANGDETECT_AVAILABLE: Optional[bool] = None


def _ensure_langdetect() -> bool:
    """Try to import langdetect once; cache the result.

    ``langdetect`` is an optional dependency declared in
    ``requirements.txt``. If a user runs without it installed we
    skip the language-detect category gracefully rather than
    crashing the whole audit.
    """
    global _LANGDETECT_AVAILABLE
    if _LANGDETECT_AVAILABLE is not None:
        return _LANGDETECT_AVAILABLE
    try:
        import langdetect  # noqa: F401
        from langdetect import DetectorFactory
        # Make detection deterministic — without this the same row
        # can produce different language guesses on different
        # invocations because the bag-of-trigrams hash table
        # iteration order varies.
        DetectorFactory.seed = 42
        _LANGDETECT_AVAILABLE = True
    except ImportError:
        _LANGDETECT_AVAILABLE = False
    return _LANGDETECT_AVAILABLE


def detect_language(text: str) -> Optional[str]:
    """Return the ISO-639-1 language code for ``text``, or None.

    Returns None if langdetect isn't installed, the text is too
    short, or langdetect can't make a confident call.
    """
    if not _ensure_langdetect():
        return None
    if not text or len(text.split()) < DEFAULT_LANG_MIN_WORDS:
        return None
    try:
        from langdetect import detect, LangDetectException
        try:
            return detect(text)
        except LangDetectException:
            return None
    except Exception:
        return None


@dataclass
class DuplicateGroup:
    """Used to surface example groups in the report UI."""
    representative_id: int
    n_dupes: int
    sample_text: str  # first ~120 chars for display


@dataclass
class SourceDominance:
    label: str
    source_key: str        # for ``corpus_collection.parse_source_key``
    rows: int
    pct_of_total: float
    target_rows: int
    drops: int


@dataclass
class TopicCluster:
    """One over-represented topic cluster.

    ``top_terms`` are the most distinctive vocabulary in the cluster
    (highest tf-idf in the centroid) — gives the user a one-line
    sense of "what is this cluster about" so they can decide
    whether the over-representation is OK or needs trimming.
    """
    cluster_id: int
    rows: int
    pct_of_total: float
    target_rows: int
    drops: int
    top_terms: List[str] = field(default_factory=list)
    sample_text: str = ""


@dataclass
class TopicAnalysis:
    """Result of ``analyze_topic_distribution``.

    ``available`` is False when scikit-learn isn't installed; the
    caller should surface that as a "install via pip" hint rather
    than treating it as "no topics found".

    ``ids_to_drop`` is the precomputed deterministic-random
    down-sample list — the apply path uses it as-is rather than
    re-clustering, so the user's preview matches the actual delete.
    """
    total_rows: int = 0
    n_clusters: int = 0
    available: bool = True
    over_cap_clusters: List[TopicCluster] = field(default_factory=list)
    total_drops: int = 0
    ids_to_drop: List[int] = field(default_factory=list)
    error: str = ""


@dataclass
class VariabilityReport:
    total_rows: int = 0
    # Exact-duplicate output_text. Most aggressive — these rows teach
    # the model nothing beyond their first appearance.
    exact_groups: int = 0
    exact_drops: int = 0
    exact_examples: List[DuplicateGroup] = field(default_factory=list)
    # Same first-80-char opener (different bodies). Most catalog
    # rows that hit this are real distinct passages but share a
    # cliché opener — the model still benefits from seeing each
    # body, but if there are 200+ of them we've overdone it.
    opener_groups: int = 0
    opener_drops: int = 0
    opener_examples: List[DuplicateGroup] = field(default_factory=list)
    # Sources that exceed the cap. Random down-sampling of the
    # excess rows; we keep MIN(id) deterministically so a re-run
    # produces the same "to drop" list (helpful for testing).
    source_dominance: List[SourceDominance] = field(default_factory=list)
    source_dominance_drops: int = 0
    # Repetitive rows — high zlib compressibility on output_text.
    # Catches dialogue-tag spam, "the the the" garbage, list outputs.
    repetitive_drops: int = 0
    repetitive_examples: List[DuplicateGroup] = field(default_factory=list)
    # Low type-token ratio — repeated vocabulary even when surface
    # bytes don't compress. Different signal from compression.
    low_diversity_drops: int = 0
    low_diversity_examples: List[DuplicateGroup] = field(default_factory=list)
    # Near-duplicate clusters via MinHash + LSH. Catches paraphrased
    # / lightly-edited duplicates exact-dedup misses.
    near_dup_clusters: int = 0
    near_dup_drops: int = 0
    near_dup_examples: List[DuplicateGroup] = field(default_factory=list)
    # Non-target-language rows. Skipped silently when langdetect
    # is not installed; the UI surfaces that state in the card.
    non_target_lang_drops: int = 0
    non_target_lang_examples: List[DuplicateGroup] = field(default_factory=list)
    lang_breakdown: Dict[str, int] = field(default_factory=dict)
    langdetect_available: bool = True

    @property
    def total_drops_max(self) -> int:
        """Upper bound if every category is approved.

        Categories overlap (a row can be exact-dup AND repetitive),
        so this double-counts. The UI surfaces it as an "up to"
        number; ``collect_ids_to_drop`` resolves to disjoint sets
        at apply time.
        """
        return (self.exact_drops + self.opener_drops
                + self.source_dominance_drops
                + self.repetitive_drops
                + self.low_diversity_drops
                + self.near_dup_drops
                + self.non_target_lang_drops)


def audit_variability(db,
                      *,
                      opener_hash_len: int = DEFAULT_OPENER_HASH_LEN,
                      source_cap_pct: float = DEFAULT_SOURCE_CAP_PCT,
                      repetitive_ratio: float = DEFAULT_REPETITIVE_RATIO,
                      repetitive_min_chars: int = DEFAULT_REPETITIVE_MIN_CHARS,
                      low_ttr: float = DEFAULT_LOW_TTR,
                      low_ttr_min_words: int = DEFAULT_LOW_TTR_MIN_WORDS,
                      minhash_threshold: float = DEFAULT_MINHASH_THRESHOLD,
                      lang_target: str = DEFAULT_LANG_TARGET,
                      on_progress: Optional[Callable[[int, int, str], None]] = None,
                      ) -> VariabilityReport:
    """Scan the DB and return a non-destructive report.

    Side-effect-free — the caller decides what to apply.

    The compression + TTR phases iterate every accepted row in
    Python (~30s on 800K rows). If ``on_progress`` is provided
    we call it with ``(current, total, label)`` tuples — same
    shape as the corpus downloader — so the dialog can show a
    real progress bar instead of a spinner.
    """
    report = VariabilityReport()
    progress = on_progress or (lambda *_: None)

    with db._conn() as c:
        # Total accepted rows. The trainer only sees accepted=1 so
        # we measure variability against that pool.
        report.total_rows = int(c.execute(
            "SELECT COUNT(*) FROM rephrases WHERE accepted = 1"
        ).fetchone()[0])
        if report.total_rows == 0:
            return report

        # ── Exact duplicates ──
        # Hash on output_text only — that's what the model learns.
        # Two rows with the same output but different prompts are
        # still teaching the same completion behavior. We compute
        # the totals via a single aggregate (no row limit so the
        # report counts every duplicate group), and fetch only the
        # top 8 examples for the UI.
        agg = c.execute(
            "SELECT COUNT(*) AS groups, SUM(n - 1) AS drops FROM ("
            "  SELECT COUNT(*) AS n FROM rephrases "
            "  WHERE accepted = 1 GROUP BY output_text "
            "  HAVING COUNT(*) > 1)").fetchone()
        report.exact_groups = int(agg["groups"] or 0)
        report.exact_drops = int(agg["drops"] or 0)
        cur = c.execute(
            "SELECT MIN(id) AS keep_id, COUNT(*) AS n, "
            "SUBSTR(output_text, 1, 120) AS preview "
            "FROM rephrases WHERE accepted = 1 "
            "GROUP BY output_text HAVING COUNT(*) > 1 "
            "ORDER BY n DESC LIMIT 8")
        for row in cur:
            report.exact_examples.append(DuplicateGroup(
                representative_id=int(row["keep_id"]),
                n_dupes=int(row["n"]),
                sample_text=(row["preview"] or "").strip(),
            ))

        # ── Opener duplicates ──
        # Same first-N chars of output. We detect distinct *full
        # outputs* sharing an opener — the body differs but the
        # model has already seen plenty of rows starting that way.
        # Cap each opener at 5 distinct rows (enough to see
        # variation, beyond which we're just oversampling).
        cap = 5
        agg = c.execute(
            f"""SELECT COUNT(*) AS groups,
                       COALESCE(SUM(n_distinct - {cap}), 0) AS drops FROM (
                  SELECT COUNT(DISTINCT output_text) AS n_distinct
                  FROM rephrases WHERE accepted = 1
                  GROUP BY SUBSTR(output_text, 1, {opener_hash_len})
                  HAVING n_distinct > {cap})"""
        ).fetchone()
        report.opener_groups = int(agg["groups"] or 0)
        report.opener_drops = int(agg["drops"] or 0)
        cur = c.execute(
            f"""SELECT SUBSTR(output_text, 1, {opener_hash_len}) AS op,
                       COUNT(DISTINCT output_text) AS n_distinct,
                       MIN(id) AS keep_id,
                       SUBSTR(output_text, 1, 120) AS preview
                FROM rephrases WHERE accepted = 1
                GROUP BY op HAVING n_distinct > {cap}
                ORDER BY n_distinct DESC LIMIT 8""")
        for row in cur:
            report.opener_examples.append(DuplicateGroup(
                representative_id=int(row["keep_id"]),
                n_dupes=int(row["n_distinct"]),
                sample_text=(row["preview"] or "").strip(),
            ))

        # ── Source dominance ──
        # We label sources with the same shape ``available_sources``
        # uses so the UI/manager can display consistent names. The
        # underlying matcher just needs to know which rows belong to
        # which bucket — for that we re-use the GROUP-BY-notes
        # collection key shape that ``list_corpus_collections`` produces.
        cap_target = int(report.total_rows * (source_cap_pct / 100.0))
        cur = c.execute(
            "SELECT source_type, notes, COUNT(*) AS n "
            "FROM rephrases WHERE accepted = 1 "
            "GROUP BY source_type, notes")
        # Aggregate by source-key (collapse all rows with the same
        # corpus_id / project_source / corpus_title).
        per_source: Dict[str, Dict[str, Any]] = {}
        for row in cur:
            st = row["source_type"] or "unknown"
            notes = row["notes"] or ""
            if st == "corpus":
                key, label, kind = db._parse_collection_id(notes)
            else:
                key = f"other:{st}"
                label = st.replace("_", " ").title()
                kind = "other"
            bucket = per_source.setdefault(key, {
                "key": key, "label": label, "kind": kind,
                "rows": 0,
            })
            bucket["rows"] += int(row["n"])
        for s in per_source.values():
            pct = s["rows"] / report.total_rows * 100.0
            if s["rows"] > cap_target:
                drops = s["rows"] - cap_target
                report.source_dominance.append(SourceDominance(
                    label=s["label"],
                    source_key=s["key"],
                    rows=s["rows"],
                    pct_of_total=pct,
                    target_rows=cap_target,
                    drops=drops,
                ))
                report.source_dominance_drops += drops
        report.source_dominance.sort(key=lambda d: -d.drops)

        # ── Per-row scans: repetitive, low-diversity, near-dup
        # signatures, language detection ──
        #
        # Single Python pass over every accepted row so we don't
        # load output_text more than once. Counts + small example
        # lists go in the report; ID lists are resolved at apply
        # time so concurrent edits to the DB can't desync the
        # count from the actual delete list.
        progress(0, report.total_rows, "scanning rows")
        cur = c.execute(
            "SELECT id, output_text FROM rephrases "
            "WHERE accepted = 1")
        rep_examples: List[Tuple[float, int, str]] = []
        ttr_examples: List[Tuple[float, int, str]] = []
        lang_examples: List[Tuple[str, int, str]] = []
        # Build MinHash signatures alongside the other metrics.
        # ``signatures`` is keyed by row id; we feed it into the
        # LSH pass after the main loop completes.
        hasher = _MinHasher()
        signatures: Dict[int, Tuple[int, ...]] = {}
        previews: Dict[int, str] = {}
        report.langdetect_available = _ensure_langdetect()
        i = 0
        for row in cur:
            i += 1
            if i % 5000 == 0:
                progress(i, report.total_rows, "scanning rows")
            text = row["output_text"] or ""
            rid = int(row["id"])
            n_chars = len(text)
            # Repetitiveness: only score rows long enough that the
            # zlib overhead doesn't dominate.
            if n_chars >= repetitive_min_chars:
                ratio = compression_ratio(text)
                if ratio < repetitive_ratio:
                    report.repetitive_drops += 1
                    if len(rep_examples) < 8:
                        rep_examples.append((ratio, rid, text[:120]))
            # Low TTR: skip very short rows where the measure is noisy.
            ttr_val, n_words = type_token_ratio(text)
            if n_words >= low_ttr_min_words and ttr_val < low_ttr:
                report.low_diversity_drops += 1
                if len(ttr_examples) < 8:
                    ttr_examples.append((ttr_val, rid, text[:120]))
            # MinHash signature (None for rows shorter than the
            # shingle size — tiny rows can't form a signature, and
            # exact-dedup already covered them anyway).
            if n_words >= DEFAULT_MINHASH_MIN_WORDS:
                sig = hasher.signature(text)
                if sig is not None:
                    signatures[rid] = sig
                    previews[rid] = text[:120]
            # Language detection — opt-in, gracefully degrades when
            # langdetect isn't installed.
            if report.langdetect_available:
                lang = detect_language(text)
                if lang:
                    report.lang_breakdown[lang] = (
                        report.lang_breakdown.get(lang, 0) + 1)
                    if lang != lang_target:
                        report.non_target_lang_drops += 1
                        if len(lang_examples) < 8:
                            lang_examples.append(
                                (lang, rid, text[:120]))
        progress(report.total_rows, report.total_rows, "scanning rows")
        # Sort examples worst-first so the user sees the most
        # extreme cases. ``DuplicateGroup`` is reused for display
        # consistency — ``n_dupes`` slot carries the metric value
        # rendered as int×100 (e.g. ratio=0.12 → 12, ttr=0.31 → 31)
        # so the dialog can label it accordingly.
        rep_examples.sort()
        for ratio, rid, preview in rep_examples:
            report.repetitive_examples.append(DuplicateGroup(
                representative_id=rid,
                n_dupes=int(round(ratio * 100)),
                sample_text=preview,
            ))
        ttr_examples.sort()
        for ttr_val, rid, preview in ttr_examples:
            report.low_diversity_examples.append(DuplicateGroup(
                representative_id=rid,
                n_dupes=int(round(ttr_val * 100)),
                sample_text=preview,
            ))
        for lang, rid, preview in lang_examples:
            # Encode the lang as a short int via ord-of-first-char so
            # the example is tagged with something searchable; the
            # UI displays the actual language code from a parallel
            # list rather than from this slot.
            report.non_target_lang_examples.append(DuplicateGroup(
                representative_id=rid,
                n_dupes=0,  # unused for this category
                sample_text=f"[{lang}] {preview}",
            ))

        # ── Near-duplicate clustering via MinHash + LSH ──
        # We bucket signatures by 4-row bands, walk each non-trivial
        # bucket, and verify candidate pairs with an explicit
        # Jaccard estimate. Clusters are computed via union-find.
        # Skipped silently if too few rows have signatures (the
        # banding logic produces nonsense for empty input).
        if signatures:
            progress(0, len(signatures), "computing near-duplicate clusters")
            sig_items = list(signatures.items())
            num_hashes = DEFAULT_MINHASH_NUM_HASHES
            num_bands = DEFAULT_MINHASH_BANDS
            rows_per_band = num_hashes // num_bands
            # Bucket sigs by band.
            bands: List[Dict[Tuple[int, ...], List[int]]] = [
                {} for _ in range(num_bands)]
            for j, (rid, sig) in enumerate(sig_items):
                if j % 5000 == 0:
                    progress(j, len(sig_items),
                             "computing near-duplicate clusters")
                for b in range(num_bands):
                    band_key = sig[b * rows_per_band:
                                   (b + 1) * rows_per_band]
                    bands[b].setdefault(band_key, []).append(rid)

            # Collect candidate pairs from non-trivial buckets.
            candidate_pairs: set = set()
            for band in bands:
                for bucket in band.values():
                    if len(bucket) < 2:
                        continue
                    # Cap bucket size — pathological cases (e.g.
                    # 10,000 rows that all share an opener) would
                    # produce 50M pairs. We sample the first 50
                    # rows of any oversize bucket; the sample is
                    # already enough to anchor the cluster via
                    # transitive closure across other bands.
                    if len(bucket) > 50:
                        bucket = sorted(bucket)[:50]
                    for x in range(len(bucket)):
                        for y in range(x + 1, len(bucket)):
                            a, b = bucket[x], bucket[y]
                            if a > b:
                                a, b = b, a
                            candidate_pairs.add((a, b))

            # Verify candidates and run union-find on the survivors.
            parent: Dict[int, int] = {}

            def _find(x: int) -> int:
                while parent.setdefault(x, x) != x:
                    parent[x] = parent.get(parent[x], parent[x])
                    x = parent[x]
                return x

            def _union(a: int, b: int) -> None:
                ra, rb = _find(a), _find(b)
                if ra != rb:
                    parent[ra] = rb

            for a, b in candidate_pairs:
                if jaccard_estimate(signatures[a],
                                    signatures[b]) >= minhash_threshold:
                    _union(a, b)

            clusters: Dict[int, List[int]] = {}
            for x in list(parent):
                clusters.setdefault(_find(x), []).append(x)

            for members in clusters.values():
                if len(members) < 2:
                    continue
                report.near_dup_clusters += 1
                # Drop all but oldest (min id) — same convention as
                # exact-dedup. Counts the dropped tail.
                report.near_dup_drops += len(members) - 1
                if len(report.near_dup_examples) < 8:
                    rep_id = min(members)
                    report.near_dup_examples.append(DuplicateGroup(
                        representative_id=rep_id,
                        n_dupes=len(members),
                        sample_text=previews.get(rep_id, ""),
                    ))
            progress(len(sig_items), len(sig_items),
                     "computing near-duplicate clusters")

    return report


# ── Topic clustering (TF-IDF + KMeans) ────────────────────────

def analyze_topic_distribution(
    db,
    *,
    n_clusters: int = DEFAULT_TOPIC_CLUSTERS,
    cap_pct: float = DEFAULT_TOPIC_CAP_PCT,
    max_features: int = DEFAULT_TOPIC_MAX_FEATURES,
    reduced_dim: int = DEFAULT_TOPIC_REDUCED_DIM,
    seed: int = 42,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> TopicAnalysis:
    """TF-IDF + TruncatedSVD + MiniBatchKMeans on the corpus.

    Identifies clusters of rows whose content is similar by
    distinctive vocabulary, then recommends row-level drops for
    any cluster exceeding ``cap_pct`` of the total. Different from
    every other category in the audit because it works on
    *content* rather than surface text or origin metadata — two
    rows worded differently but covering the same subject end up
    in the same cluster.

    Run on demand (not from the default audit) because it's slow
    (~2-3 min on 800K rows) and pulls in scikit-learn. Reports
    ``available=False`` if sklearn isn't installed.

    Steps + progress phases:
      1. ``loading rows`` — pull (id, output_text) for every accepted row
      2. ``vectorizing TF-IDF`` — sklearn's TfidfVectorizer.fit_transform
      3. ``reducing dimensions`` — TruncatedSVD on the sparse matrix
      4. ``clustering with k-means`` — MiniBatchKMeans
      5. ``sampling drops`` — random down-sample of over-cap clusters

    Each phase reports start + end at minimum; the row-loading
    and cluster-summarising loops report finer-grained progress.
    """
    progress = on_progress or (lambda *_: None)
    result = TopicAnalysis()

    # Soft sklearn import — graceful fallback if missing.
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import TruncatedSVD
        from sklearn.cluster import MiniBatchKMeans
    except ImportError as e:
        result.available = False
        result.error = (f"scikit-learn not installed ({e}). "
                        f"Run `pip install scikit-learn` to enable "
                        f"topic-cluster analysis.")
        return result

    import numpy as np

    # ── Phase 1: load rows ──
    progress(0, 0, "loading rows from DB")
    row_ids: List[int] = []
    texts: List[str] = []
    with db._conn() as c:
        cur = c.execute(
            "SELECT id, output_text FROM rephrases "
            "WHERE accepted = 1")
        for i, row in enumerate(cur):
            text = row["output_text"] or ""
            # Skip very short rows — they don't survive TF-IDF's
            # min_df cutoff anyway and clutter the matrix.
            if len(text) < 80:
                continue
            row_ids.append(int(row["id"]))
            texts.append(text)
            if i % 25000 == 0:
                progress(i, 0, "loading rows from DB")

    result.total_rows = len(texts)
    if result.total_rows < n_clusters * 4:
        # Too few rows for meaningful clustering — fewer than ~4×k
        # rows produces noisy clusters with poor centroids.
        result.error = (f"Need at least {n_clusters * 4:,} rows for "
                        f"{n_clusters}-way clustering; have "
                        f"{result.total_rows:,}.")
        return result

    # ── Phase 2: TF-IDF ──
    progress(0, result.total_rows, "vectorizing TF-IDF")
    # min_df=5: term must appear in ≥5 rows to count (drops
    # one-off tokens). max_df=0.5: term appearing in >50% of rows
    # is a stop-word in this corpus, drop it. ngram (1,2)
    # captures both unigrams and bigrams ("dragon" + "fire dragon").
    vectorizer = TfidfVectorizer(
        max_features=max_features,
        min_df=5,
        max_df=0.5,
        ngram_range=(1, 2),
        stop_words="english",
        lowercase=True,
        sublinear_tf=True,
    )
    try:
        tfidf = vectorizer.fit_transform(texts)
    except Exception as e:
        result.error = f"TF-IDF vectorization failed: {e}"
        return result
    progress(result.total_rows, result.total_rows, "vectorizing TF-IDF")

    # ── Phase 3: SVD ──
    progress(0, 0, "reducing dimensions (SVD)")
    actual_dim = min(reduced_dim, tfidf.shape[1] - 1, len(texts) - 1)
    if actual_dim < 2:
        result.error = (f"Vocabulary too small for SVD "
                        f"(features={tfidf.shape[1]}).")
        return result
    svd = TruncatedSVD(n_components=actual_dim, random_state=seed)
    try:
        reduced = svd.fit_transform(tfidf)
    except Exception as e:
        result.error = f"SVD failed: {e}"
        return result
    progress(0, 0, "reducing dimensions (SVD)")

    # ── Phase 4: KMeans ──
    actual_k = min(n_clusters, len(texts) // 4)
    progress(0, actual_k, "clustering with k-means")
    # MiniBatchKMeans is ~10× faster than KMeans on this scale
    # with negligible quality loss for our use case (we don't
    # need optimal cluster centers, just decent groupings).
    kmeans = MiniBatchKMeans(
        n_clusters=actual_k,
        random_state=seed,
        batch_size=10000,
        max_iter=100,
        n_init=3,
    )
    try:
        labels = kmeans.fit_predict(reduced)
    except Exception as e:
        result.error = f"KMeans failed: {e}"
        return result
    progress(actual_k, actual_k, "clustering with k-means")
    result.n_clusters = actual_k

    # ── Phase 5: identify over-cap clusters + sample drops ──
    progress(0, actual_k, "sampling drops")
    cluster_target = int(result.total_rows * (cap_pct / 100.0))

    # Pre-compute centroid → top-term lookup so the report can
    # explain each cluster ("magic_systems, spell, conjure, …").
    feature_names = vectorizer.get_feature_names_out()
    # Centroids in TF-IDF space — multiply SVD components back in.
    # ``inverse_transform`` is exact since SVD is linear.
    centroids_tfidf = svd.inverse_transform(kmeans.cluster_centers_)

    rng = random.Random(seed)
    to_drop: List[int] = []
    cluster_indices: Dict[int, List[int]] = {}
    for idx, lbl in enumerate(labels):
        cluster_indices.setdefault(int(lbl), []).append(idx)

    for k, members in cluster_indices.items():
        n = len(members)
        pct = n / result.total_rows * 100.0
        if k % 5 == 0:
            progress(k, actual_k, "sampling drops")
        if n <= cluster_target:
            continue
        # This cluster is over-cap. Sample (n - target) for drop.
        drops_needed = n - cluster_target
        chosen = rng.sample(members, drops_needed)
        # Build a top-terms list: top 8 features by absolute
        # weight in this centroid. ``argsort`` returns smallest
        # first; ``-`` flips to largest first.
        center = centroids_tfidf[k]
        top_idx = (-center).argsort()[:8]
        top_terms = [feature_names[t] for t in top_idx
                     if center[t] > 0]
        # Closest-to-centroid sample: pick the row in this cluster
        # with the highest cosine similarity to the centroid in
        # reduced space.
        center_reduced = kmeans.cluster_centers_[k]
        sims = np.dot(reduced[members], center_reduced)
        rep_idx = members[int(np.argmax(sims))]
        sample = (texts[rep_idx][:120]).replace("\n", " ")

        result.over_cap_clusters.append(TopicCluster(
            cluster_id=k,
            rows=n,
            pct_of_total=pct,
            target_rows=cluster_target,
            drops=drops_needed,
            top_terms=top_terms,
            sample_text=sample,
        ))
        for chosen_idx in chosen:
            to_drop.append(row_ids[chosen_idx])

    result.over_cap_clusters.sort(key=lambda c: -c.drops)
    result.ids_to_drop = to_drop
    result.total_drops = len(to_drop)
    progress(actual_k, actual_k, "sampling drops")
    return result


# ── Pruning plan ──────────────────────────────────────────────

@dataclass
class PruningPlan:
    """User's per-category approval. Each flag toggles one category
    of the audit. The apply step computes the actual ID list at
    apply time so concurrent edits to the DB don't cause the wrong
    rows to be deleted.
    """
    apply_exact: bool = False
    apply_opener: bool = False
    apply_source_dominance: bool = False
    apply_repetitive: bool = False
    apply_low_diversity: bool = False
    apply_near_dup: bool = False
    apply_non_target_lang: bool = False
    apply_topic_clustering: bool = False
    opener_hash_len: int = DEFAULT_OPENER_HASH_LEN
    opener_cap_per_group: int = 5
    source_cap_pct: float = DEFAULT_SOURCE_CAP_PCT
    repetitive_ratio: float = DEFAULT_REPETITIVE_RATIO
    repetitive_min_chars: int = DEFAULT_REPETITIVE_MIN_CHARS
    low_ttr: float = DEFAULT_LOW_TTR
    low_ttr_min_words: int = DEFAULT_LOW_TTR_MIN_WORDS
    minhash_threshold: float = DEFAULT_MINHASH_THRESHOLD
    lang_target: str = DEFAULT_LANG_TARGET
    # Topic-clustering uses precomputed IDs from a prior call to
    # ``analyze_topic_distribution``. We store them here so the
    # apply path doesn't need to re-run the 2-3 minute TF-IDF +
    # KMeans pipeline; the dialog stashes the analysis result and
    # threads its ``ids_to_drop`` list through this field when
    # the user approves the category.
    topic_ids_override: Optional[List[int]] = None
    seed: int = 0


def collect_ids_to_drop(db, plan: PruningPlan) -> Dict[str, List[int]]:
    """Resolve the plan into concrete ID lists, by category.

    Returned shape:
      ``{"exact": [...], "opener": [...], "source_dominance": [...],
        "repetitive": [...], "low_diversity": [...]}``

    Categories with their flag set to False return an empty list.
    Each list is **disjoint** from the others — if a row is in
    multiple categories it's only listed under the first one
    encountered (in the order: exact → opener → source_dominance →
    repetitive → low_diversity). This avoids double-counting in
    the apply step.
    """
    ids: Dict[str, List[int]] = {
        "exact": [], "opener": [], "source_dominance": [],
        "repetitive": [], "low_diversity": [],
        "near_dup": [], "non_target_lang": [],
        "topic_clustering": []}

    with db._conn() as c:
        seen: set = set()

        if plan.apply_exact:
            # For each duplicate output_text, keep MIN(id) and drop
            # the rest. Subquery picks the keepers; outer query drops
            # everything else with a duplicate output.
            cur = c.execute(
                "SELECT id FROM rephrases WHERE accepted = 1 "
                "AND output_text IN ("
                "  SELECT output_text FROM rephrases WHERE accepted = 1 "
                "  GROUP BY output_text HAVING COUNT(*) > 1) "
                "AND id NOT IN ("
                "  SELECT MIN(id) FROM rephrases WHERE accepted = 1 "
                "  GROUP BY output_text)")
            for row in cur:
                rid = int(row["id"])
                seen.add(rid)
                ids["exact"].append(rid)

        if plan.apply_opener:
            # Distinct outputs per opener, keep the first ``cap``
            # by id, drop the rest. We need per-row ranking which
            # SQLite handles via a window function.
            cap = plan.opener_cap_per_group
            cur = c.execute(
                f"""
                WITH ranked AS (
                  SELECT id, output_text,
                    ROW_NUMBER() OVER (
                      PARTITION BY SUBSTR(output_text, 1,
                                          {plan.opener_hash_len})
                      ORDER BY id
                    ) AS rn
                  FROM rephrases WHERE accepted = 1
                )
                SELECT id FROM ranked WHERE rn > {cap}
                """)
            for row in cur:
                rid = int(row["id"])
                if rid in seen:
                    continue
                seen.add(rid)
                ids["opener"].append(rid)

        if plan.apply_source_dominance:
            # We compute caps against the *surviving* row set —
            # i.e. excluding everything already marked by exact or
            # opener. After heavy dedup, a source that looked
            # dominant at audit time may no longer exceed the cap,
            # which is the right outcome (don't drop more than
            # necessary).
            from src.data.corpus_collection import parse_source_key
            rng = random.Random(plan.seed)
            # Pull every (id, source_key) once so we can both count
            # surviving rows per source AND know which IDs to draw
            # from when sampling.
            per_source: Dict[str, List[int]] = {}
            cur = c.execute(
                "SELECT id, source_type, notes FROM rephrases "
                "WHERE accepted = 1")
            for row in cur:
                rid = int(row["id"])
                if rid in seen:
                    continue
                st = row["source_type"] or "unknown"
                notes = row["notes"] or ""
                if st == "corpus":
                    key, _, _ = db._parse_collection_id(notes)
                else:
                    key = f"other:{st}"
                per_source.setdefault(key, []).append(rid)

            total_surviving = sum(len(v) for v in per_source.values())
            cap_target = int(
                total_surviving * (plan.source_cap_pct / 100.0))
            for key, row_ids in per_source.items():
                if len(row_ids) <= cap_target:
                    continue
                drops_needed = len(row_ids) - cap_target
                if not parse_source_key(key):
                    continue
                if drops_needed >= len(row_ids):
                    chosen = row_ids
                else:
                    chosen = rng.sample(row_ids, drops_needed)
                for rid in chosen:
                    seen.add(rid)
                    ids["source_dominance"].append(rid)

        # ── Repetitive + low-diversity passes ──
        # These iterate row contents in Python, so we only run them
        # when at least one is approved. We also skip any row
        # already in ``seen`` so a row that's already going to be
        # dropped doesn't show up under a second category — keeps
        # the per-category counts honest.
        # Per-row passes: rep, low-div, MinHash, language all read
        # output_text in Python so we batch them into one cursor.
        # We only run the cursor if at least one of these flags is
        # set — saves the ~15s+ scan when the user only approved
        # SQL-based categories.
        do_per_row = (plan.apply_repetitive or plan.apply_low_diversity
                      or plan.apply_near_dup
                      or plan.apply_non_target_lang)
        if do_per_row:
            hasher = _MinHasher() if plan.apply_near_dup else None
            signatures: Dict[int, Tuple[int, ...]] = {}
            langdetect_ok = (
                _ensure_langdetect() if plan.apply_non_target_lang
                else False)
            cur = c.execute(
                "SELECT id, output_text FROM rephrases "
                "WHERE accepted = 1")
            for row in cur:
                rid = int(row["id"])
                if rid in seen:
                    continue
                text = row["output_text"] or ""
                if (plan.apply_repetitive
                        and len(text) >= plan.repetitive_min_chars):
                    if compression_ratio(text) < plan.repetitive_ratio:
                        seen.add(rid)
                        ids["repetitive"].append(rid)
                        continue  # don't double-flag under other cats
                if plan.apply_low_diversity:
                    ttr_val, n_words = type_token_ratio(text)
                    if (n_words >= plan.low_ttr_min_words
                            and ttr_val < plan.low_ttr):
                        seen.add(rid)
                        ids["low_diversity"].append(rid)
                        continue
                if (plan.apply_non_target_lang and langdetect_ok
                        and rid not in seen):
                    lang = detect_language(text)
                    if lang and lang != plan.lang_target:
                        seen.add(rid)
                        ids["non_target_lang"].append(rid)
                        continue
                if plan.apply_near_dup and hasher and rid not in seen:
                    sig = hasher.signature(text)
                    if sig is not None:
                        signatures[rid] = sig

            # MinHash post-pass: LSH banding + cluster + drop tail.
            # Same algorithm as ``audit_variability``; we duplicate
            # here rather than refactor because the audit also
            # needs the example list which the apply path doesn't.
            if plan.apply_near_dup and signatures:
                num_hashes = DEFAULT_MINHASH_NUM_HASHES
                num_bands = DEFAULT_MINHASH_BANDS
                rows_per_band = num_hashes // num_bands
                bands: List[Dict[Tuple[int, ...], List[int]]] = [
                    {} for _ in range(num_bands)]
                for rid, sig in signatures.items():
                    for b in range(num_bands):
                        band_key = sig[b * rows_per_band:
                                       (b + 1) * rows_per_band]
                        bands[b].setdefault(band_key, []).append(rid)

                candidate_pairs: set = set()
                for band in bands:
                    for bucket in band.values():
                        if len(bucket) < 2:
                            continue
                        if len(bucket) > 50:
                            bucket = sorted(bucket)[:50]
                        for x in range(len(bucket)):
                            for y in range(x + 1, len(bucket)):
                                a, bb = bucket[x], bucket[y]
                                if a > bb:
                                    a, bb = bb, a
                                candidate_pairs.add((a, bb))

                parent: Dict[int, int] = {}

                def _find(x: int) -> int:
                    while parent.setdefault(x, x) != x:
                        parent[x] = parent.get(parent[x], parent[x])
                        x = parent[x]
                    return x

                def _union(a: int, b: int) -> None:
                    ra, rb = _find(a), _find(b)
                    if ra != rb:
                        parent[ra] = rb

                for a, b in candidate_pairs:
                    if jaccard_estimate(
                            signatures[a],
                            signatures[b]) >= plan.minhash_threshold:
                        _union(a, b)

                clusters: Dict[int, List[int]] = {}
                for x in list(parent):
                    clusters.setdefault(_find(x), []).append(x)
                for members in clusters.values():
                    if len(members) < 2:
                        continue
                    members.sort()  # keep oldest, drop the rest
                    for rid in members[1:]:
                        if rid in seen:
                            continue
                        seen.add(rid)
                        ids["near_dup"].append(rid)

        # ── Topic clustering ──
        # Uses precomputed IDs from a prior ``analyze_topic_distribution``
        # call (the dialog stashes the result and passes its
        # ``ids_to_drop`` list via ``topic_ids_override``). Skipping
        # rows already seen keeps categories disjoint.
        if (plan.apply_topic_clustering
                and plan.topic_ids_override is not None):
            for rid in plan.topic_ids_override:
                if rid in seen:
                    continue
                seen.add(rid)
                ids["topic_clustering"].append(rid)

    return ids


def apply_pruning(db, ids: Dict[str, List[int]]) -> int:
    """Delete every ID in ``ids`` (any category). Caller is expected
    to have already written the backup JSONL.

    Returns the number of rows actually deleted.
    """
    all_ids: List[int] = []
    for v in ids.values():
        all_ids.extend(v)
    if not all_ids:
        return 0
    deleted = 0
    CHUNK = 500
    with db._conn() as c:
        for i in range(0, len(all_ids), CHUNK):
            chunk = all_ids[i:i + CHUNK]
            placeholders = ",".join("?" * len(chunk))
            cur = c.execute(
                f"DELETE FROM rephrases WHERE id IN ({placeholders})",
                chunk)
            deleted += cur.rowcount
    return deleted
