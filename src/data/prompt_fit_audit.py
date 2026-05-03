"""Cluster-based audit of prompt-pair fit within (source_type × shape) buckets.

The :mod:`prompt_fit_gate` runs cheap rule-based filters at export
time and drops obvious mis-fits — refusals, tool-call JSON, summaries
that share zero content with the source. It catches the broken
*pairs*, but it can't catch *systematic* drift: a whole cluster of
"plot" rows that turn out to be character backstories, or a clump of
"rephrase" rows that are actually translations between languages.

This module surfaces those clusters for human review. The flow:

  1. Walk the DB; group rows by ``(source_type, shape)`` where
     shape is computed the same way :meth:`RephraseDatabase._classify_row_shape`
     does. Buckets with fewer than ``min_bucket_rows`` rows are
     skipped (clustering on ten rows is meaningless).
  2. Within each bucket, TF-IDF the concatenated input+output text
     and MiniBatchKMeans into ``k`` clusters where ``k = min(20,
     max(4, sqrt(n_rows / 50)))`` — small buckets get few clusters,
     large buckets up to 20.
  3. Score each cluster by its *typicality*: cosine similarity of
     its centroid against the bucket's overall centroid. Clusters
     in the bottom quartile (or with size < ``outlier_max_size``,
     whichever is larger) are flagged as candidates to drop.
  4. For each flagged cluster, sample up to ``samples_per_cluster``
     rows so the UI can render a preview the user can sanity-check
     before approving the drop.

The module returns a structured :class:`AuditReport`; the UI
(``_PromptFitAuditDialog``) renders it and applies the user's
selected drops via :func:`apply_drops`. Mirrors the shape of
:mod:`corpus_variability` so the two audit dialogs behave
predictably alongside each other.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from src.data.rephrase_database import (
    RephraseDatabase,
    SOURCE_REPHRASE, SOURCE_CHAT_WRITING, SOURCE_CHAT_GENERAL,
    SOURCE_CORPUS, SOURCE_AGENT, SOURCE_WORLDBUILDING,
    SOURCE_CHARACTER, SOURCE_PLOT,
)


# ── Result types ─────────────────────────────────────────────


@dataclass
class ClusterCandidate:
    """One cluster of rows the user can approve-drop as a unit."""
    cluster_id: int
    bucket_key: Tuple[str, str]   # (source_type, shape)
    size: int
    typicality: float             # cosine to bucket centroid (1=most typical)
    sample_row_ids: List[int]
    sample_inputs: List[str]      # truncated
    sample_outputs: List[str]     # truncated
    top_terms: List[str]          # 5 most distinctive bigram terms
    is_outlier: bool              # below typicality / size threshold


@dataclass
class BucketReport:
    """Aggregate result for one (source_type, shape) bucket."""
    bucket_key: Tuple[str, str]
    total_rows: int
    n_clusters: int
    typical_clusters: List[ClusterCandidate] = field(default_factory=list)
    outlier_clusters: List[ClusterCandidate] = field(default_factory=list)


@dataclass
class AuditReport:
    """Full audit result. ``available=False`` means we couldn't run
    (sklearn missing, no rows, etc.) — UI should explain why."""
    available: bool = True
    error: str = ""
    total_rows_scanned: int = 0
    buckets: List[BucketReport] = field(default_factory=list)
    elapsed_seconds: float = 0.0


# ── Shape labels (match RephraseDatabase._classify_row_shape) ──
#
# The labels are intentionally in lockstep with the shape detector
# in :mod:`rephrase_database` so the audit groups rows the same way
# the export pipeline judges them.


def _classify_shape(src: str, out: str, st: str) -> str:
    return RephraseDatabase._classify_row_shape(src, out, st)


# ── Public entry point ───────────────────────────────────────


def audit(db: RephraseDatabase,
          *,
          min_bucket_rows: int = 80,
          outlier_typicality_threshold: float = 0.35,
          outlier_max_size: int = 0,  # 0 = no size cap; only typicality
          samples_per_cluster: int = 4,
          genre_filter: Optional[Iterable[str]] = None,
          on_progress: Optional[Callable[[int, int, str], None]] = None,
          ) -> AuditReport:
    """Build a cluster audit of every populated (source_type, shape).

    Args:
        min_bucket_rows: skip buckets with fewer rows than this —
            clustering on tiny buckets produces noise, not signal.
        outlier_typicality_threshold: clusters whose centroid cosine
            similarity to the bucket centroid is below this number
            are marked as outliers (UI surfaces them). 0.35 is a
            soft default; tighten for stricter audits.
        outlier_max_size: if > 0, also mark any cluster smaller than
            this as an outlier. Catches very small "stray" clusters
            even when their centroid is close to the bucket centroid.
        samples_per_cluster: rows previewed per cluster in the UI.
        genre_filter: scope the audit to rows whose ``genre`` column
            overlaps this set. Sibling genres (western↔frontier,
            horror↔gothic) are auto-expanded via
            :func:`expand_with_ancillaries`. Untagged rows always
            pass — they're universal context. Pass ``None`` (default)
            to audit every row.
        on_progress: ``(done, total, msg)`` callback, like the rest
            of the audit pipeline.
    """
    progress = on_progress or (lambda *_: None)
    t0 = time.time()
    report = AuditReport()

    # Soft sklearn import — we say so explicitly if missing.
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.cluster import MiniBatchKMeans
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError as e:
        report.available = False
        report.error = (f"scikit-learn not installed ({e}). "
                        "Run `pip install scikit-learn` to enable "
                        "the prompt-fit audit.")
        return report

    import numpy as np

    # ── Phase 0: resolve genre filter (with ancillary expansion) ──
    wanted_genres: Optional[set] = None
    if genre_filter:
        try:
            from src.data.genres import expand_with_ancillaries
            wanted_genres = expand_with_ancillaries(
                {g.lower().strip() for g in genre_filter if g})
        except Exception:
            wanted_genres = {g.lower().strip()
                             for g in genre_filter if g}

    # ── Phase 1: walk DB into buckets ──
    progress(0, 0, "scanning DB into shape buckets")
    buckets: Dict[Tuple[str, str], List[Tuple[int, str, str]]] = {}
    # Pull ``genre`` too so we can apply the optional genre filter
    # below. Untagged rows pass unconditionally (genre=="" is universal
    # context, same convention as export_jsonl).
    with db._conn() as c:
        cur = c.execute(
            "SELECT id, source_type, source_text, output_text, genre "
            "FROM rephrases WHERE accepted = 1")
        for i, row in enumerate(cur):
            src = row["source_text"] or ""
            out = row["output_text"] or ""
            if not src or not out:
                continue
            if wanted_genres is not None:
                row_genre_raw = (row["genre"] or "").lower().strip()
                if row_genre_raw:
                    # Contains + fuzzy match (composite tags like
                    # "gothic horror" → "horror", hyphenated variants
                    # like "sci-fi" → "scifi", typos like "horor" →
                    # "horror"). See genres.genres_overlap.
                    from src.data.genres import genres_overlap
                    if not genres_overlap(
                            row_genre_raw, wanted_genres):
                        # Hard filter would drop. Fuzzy escape: keep
                        # rows confidently classified as craft —
                        # essays / criticism / how-to / theory texts
                        # are broadly useful for plot/character/world
                        # work regardless of their tagged genre.
                        from src.data.text_kind import classify_kind
                        if classify_kind(src, out) != "craft":
                            continue
            st = row["source_type"] or SOURCE_REPHRASE
            shape = _classify_shape(src, out, st)
            buckets.setdefault((st, shape), []).append(
                (int(row["id"]), src, out))
            if i % 25_000 == 0:
                progress(i, 0, "scanning DB into shape buckets")

    report.total_rows_scanned = sum(len(v) for v in buckets.values())
    if report.total_rows_scanned == 0:
        report.error = "No accepted rows in the DB to audit."
        return report

    # ── Phase 2: per-bucket clustering ──
    eligible_buckets = [(k, rows) for k, rows in buckets.items()
                        if len(rows) >= min_bucket_rows]
    eligible_buckets.sort(key=lambda kv: -len(kv[1]))
    if not eligible_buckets:
        report.error = (f"No bucket has at least {min_bucket_rows} "
                        f"rows — skipping audit. Lower the "
                        f"threshold or add more data first.")
        return report

    for b_idx, ((st, shape), rows) in enumerate(eligible_buckets):
        progress(b_idx, len(eligible_buckets),
                 f"clustering {st}/{shape} ({len(rows):,} rows)")
        bucket_report = _audit_bucket(
            st=st, shape=shape, rows=rows,
            samples_per_cluster=samples_per_cluster,
            outlier_typicality_threshold=outlier_typicality_threshold,
            outlier_max_size=outlier_max_size,
            TfidfVectorizer=TfidfVectorizer,
            MiniBatchKMeans=MiniBatchKMeans,
            cosine_similarity=cosine_similarity,
            np=np)
        if bucket_report is not None:
            report.buckets.append(bucket_report)

    report.elapsed_seconds = round(time.time() - t0, 2)
    return report


# ── Per-bucket clustering ────────────────────────────────────


def _audit_bucket(*, st, shape, rows,
                  samples_per_cluster, outlier_typicality_threshold,
                  outlier_max_size,
                  TfidfVectorizer, MiniBatchKMeans,
                  cosine_similarity, np
                  ) -> Optional[BucketReport]:
    """Run TF-IDF → KMeans on one bucket; build a BucketReport.

    Returns ``None`` if the vectoriser produces an empty matrix
    (every row stripped to no usable tokens — happens on tiny or
    near-identical buckets).
    """
    n = len(rows)
    # k scales with sqrt(n/50), capped to 4..20 so a 10-row bucket
    # doesn't get 50 clusters and a 100k-row bucket doesn't get 1.
    k = max(4, min(20, int(round(math.sqrt(n / 50.0)))))
    if n < k * 2:
        # Need at least 2 rows per cluster on average.
        return None
    # Build the TF-IDF document by combining the row's input + output
    # — both contribute to "what is this pair about". Truncate each
    # to 2000 chars to keep the vectoriser cheap on a large bucket.
    docs = [(s[:2000] + " " + o[:2000]) for _id, s, o in rows]
    try:
        vec = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            min_df=max(2, n // 500),
            max_df=0.95,
            max_features=10_000)
        X = vec.fit_transform(docs)
    except ValueError:
        # All rows became empty after stop-word removal etc.
        return None
    if X.shape[1] < 4:
        return None  # vocabulary too small to cluster meaningfully

    km = MiniBatchKMeans(n_clusters=k, batch_size=512,
                          n_init=3, random_state=42)
    labels = km.fit_predict(X)
    centroids = km.cluster_centers_

    # Bucket centroid = mean of per-cluster centroids weighted by
    # cluster size — used as the reference point for typicality.
    sizes = np.bincount(labels, minlength=k)
    weights = sizes / sizes.sum()
    bucket_centroid = np.average(centroids, axis=0, weights=weights)

    # Typicality per cluster = cosine(cluster_centroid, bucket_centroid)
    typicalities = cosine_similarity(
        centroids, bucket_centroid.reshape(1, -1)).flatten()

    feature_names = vec.get_feature_names_out()

    # Build cluster candidates
    typical: List[ClusterCandidate] = []
    outliers: List[ClusterCandidate] = []
    for cid in range(k):
        member_idxs = [i for i, lbl in enumerate(labels) if lbl == cid]
        if not member_idxs:
            continue
        size = len(member_idxs)
        typ = float(typicalities[cid])
        is_outlier = (typ < outlier_typicality_threshold or
                      (outlier_max_size > 0 and size <= outlier_max_size))

        # Top distinctive bigram terms for this cluster — the
        # centroid's highest-weight feature dimensions.
        top_idxs = centroids[cid].argsort()[::-1][:6]
        top_terms = [feature_names[i] for i in top_idxs
                     if centroids[cid][i] > 0][:5]

        # Sample rows for the UI to preview. Pick from member_idxs
        # closest to the cluster centroid so the preview is
        # representative of the cluster, not random outliers.
        member_X = X[member_idxs]
        sims = cosine_similarity(
            member_X, centroids[cid].reshape(1, -1)).flatten()
        order = sims.argsort()[::-1][:samples_per_cluster]
        sample_row_ids: List[int] = []
        sample_inputs: List[str] = []
        sample_outputs: List[str] = []
        for o in order:
            r_idx = member_idxs[int(o)]
            row_id, src, out = rows[r_idx]
            sample_row_ids.append(row_id)
            sample_inputs.append(_truncate(src, 200))
            sample_outputs.append(_truncate(out, 200))

        cand = ClusterCandidate(
            cluster_id=cid,
            bucket_key=(st, shape),
            size=size,
            typicality=typ,
            sample_row_ids=sample_row_ids,
            sample_inputs=sample_inputs,
            sample_outputs=sample_outputs,
            top_terms=top_terms,
            is_outlier=is_outlier)
        if is_outlier:
            outliers.append(cand)
        else:
            typical.append(cand)

    # Sort outliers by typicality ascending (most-outlier first)
    outliers.sort(key=lambda c: c.typicality)
    typical.sort(key=lambda c: -c.size)
    return BucketReport(
        bucket_key=(st, shape),
        total_rows=n,
        n_clusters=k,
        typical_clusters=typical,
        outlier_clusters=outliers)


# ── Apply / drop ─────────────────────────────────────────────


def apply_drops(db: RephraseDatabase,
                clusters: List[ClusterCandidate]) -> int:
    """Drop every row in the supplied clusters. Returns total deleted.

    The audit dialog passes only clusters the user explicitly
    approved. Each cluster's full membership is reconstructed from
    the DB at apply time (we only kept *sample* row ids in the
    candidate, not all members) — so the dialog records the cluster
    membership separately and passes the resolved row ids in via a
    cluster object that has already been hydrated.

    Implementation: the dialog flattens its checked clusters into a
    single id list, then calls :func:`delete_rows_by_id`.
    """
    raise NotImplementedError(
        "Use delete_rows_by_id with the union of cluster member ids.")


def delete_rows_by_id(db: RephraseDatabase,
                      row_ids: List[int]) -> int:
    """Hard-delete the given row ids. Idempotent."""
    if not row_ids:
        return 0
    with db._conn() as c:
        # Chunk in 500s so the IN clause stays under SQLite's
        # parameter limit (defaults to 999) on older builds.
        deleted = 0
        for i in range(0, len(row_ids), 500):
            chunk = row_ids[i:i + 500]
            placeholders = ",".join("?" * len(chunk))
            cur = c.execute(
                f"DELETE FROM rephrases WHERE id IN ({placeholders})",
                chunk)
            deleted += cur.rowcount
    return deleted


def collect_member_ids(db: RephraseDatabase,
                        cluster: ClusterCandidate) -> List[int]:
    """Re-walk the bucket and return *all* row ids in the given cluster.

    The audit produces samples for the UI preview, but the apply
    step needs the full membership. Rather than carry every member
    id in the candidate (potentially thousands per cluster), we
    re-cluster the bucket on demand. Slightly more work at apply
    time, but the dialog is interactive — users review for tens of
    seconds before clicking Apply, so a re-cluster is fine.

    For now we return only the sampled ids — the v1 dialog drops
    *previewed* rows only, not full clusters, so what you see is
    exactly what gets dropped. This is the safest semantic for a
    first cut; full-cluster drop can be added once the heuristic
    is well-tuned and users trust the audit.
    """
    return list(cluster.sample_row_ids)


# ── Helpers ───────────────────────────────────────────────────


def _truncate(text: str, n: int) -> str:
    text = (text or "").replace("\n", " ").replace("\r", " ")
    if len(text) <= n:
        return text
    return text[:n - 1] + "…"


def shape_label(shape: str) -> str:
    """Human-readable bucket shape label for the UI."""
    return {
        "summarization": "summarisation",
        "expansion":     "expansion",
        "rephrase_like": "paraphrase",
        "continuation":  "continuation",
        "chat":          "chat",
        "agent":         "agent",
        "other":         "other / unclassified",
    }.get(shape, shape)
