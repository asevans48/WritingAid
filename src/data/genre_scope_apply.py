"""Apply the genre scope filter to the DB — drop rows that don't fit.

Companion to the read-only filtering in ``export_jsonl`` and the
``prompt_fit_audit``: those compose the scope at *export* time, leaving
the underlying DB untouched. This module *mutates* the DB by deleting
rows that fall outside the scope so subsequent operations (audits,
training runs that don't pass a scope, downstream tools) see only
the in-scope subset.

The keep/drop rule mirrors the export pipeline so the user gets a
consistent answer to "what's in scope?":

  * **Keep** — row's ``genre`` column overlaps the scope set
    (sibling/ancillary genres auto-included via
    :func:`expand_with_ancillaries`).
  * **Keep** — row is confidently classified as ``craft`` by
    :func:`text_kind.classify_kind` (essays / criticism / theory /
    how-to writing about a genre stays useful regardless of its
    tagged genre).
  * **Keep** — row has no genre tag (``genre==""``) AND
    ``drop_untagged=False`` (default). Untagged rows are universal
    context in the export pipeline; matching that here lets users
    apply a scope without nuking generic content.
  * **Drop** — everything else.

Two-phase API:

  1. :func:`plan_scope_filter` — read-only scan; computes the
     IDs to drop, the kept count, sample drop rows, and a
     reason-bucket breakdown. The UI renders this for review.
  2. :func:`apply_plan` — destructive; deletes the planned IDs.
     Idempotent (re-applying the same plan after IDs are gone is
     a no-op).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from src.data.rephrase_database import RephraseDatabase


@dataclass
class ScopeFilterPlan:
    """Read-only plan describing what would happen if applied.

    The dialog uses ``drops_by_genre`` to show a per-genre review
    list with checkboxes — users can keep individual genres'
    rows by unchecking them before clicking Apply, instead of
    accepting the all-or-nothing planned drop.
    """
    wanted_genres: List[str] = field(default_factory=list)
    expanded_genres: List[str] = field(default_factory=list)
    drop_untagged: bool = False

    drop_ids: List[int] = field(default_factory=list)
    kept_count: int = 0
    total_scanned: int = 0

    # Per-reason breakdown of why each row landed in drop_ids.
    by_reason: Dict[str, int] = field(default_factory=dict)

    # Per-genre breakdown for the dialog's selective-drop UI:
    # ``genre_label → list of row ids whose tag matched that
    # label``. ``"(untagged)"`` is the label for empty-genre rows
    # when ``drop_untagged=True``. Sample preview text is in
    # :attr:`first_samples_by_genre` for each genre.
    drops_by_genre: Dict[str, List[int]] = field(default_factory=dict)
    first_samples_by_genre: Dict[str, str] = field(default_factory=dict)

    # Up to N sample drop rows for the UI preview, each as
    # ``(id, source_text_truncated, output_text_truncated, genre, reason)``.
    sample_drops: List[Tuple[int, str, str, str, str]] = field(
        default_factory=list)

    elapsed_seconds: float = 0.0


# ── Plan ─────────────────────────────────────────────────────


def plan_scope_filter(
        db: RephraseDatabase,
        wanted_genres: Iterable[str],
        *,
        drop_untagged: bool = False,
        sample_limit: int = 8,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        ) -> ScopeFilterPlan:
    """Walk the DB; return a :class:`ScopeFilterPlan` describing the
    rows that would be dropped if the scope filter were applied.

    Doesn't mutate the DB. The dialog uses the returned plan to
    show the user what they're about to do; once confirmed, the
    same plan is passed to :func:`apply_plan` to perform deletion.
    """
    progress = on_progress or (lambda *_: None)
    t0 = time.time()
    plan = ScopeFilterPlan(
        wanted_genres=sorted(wanted_genres or []),
        drop_untagged=drop_untagged)

    if not plan.wanted_genres:
        # No scope = nothing to filter. Caller should disable the
        # tool button when scope is empty; this fallback is defensive.
        plan.elapsed_seconds = round(time.time() - t0, 2)
        return plan

    # Expand with sibling/ancillary genres so the scope filter
    # matches what the export pipeline does for the same scope.
    try:
        from src.data.genres import expand_with_ancillaries
        expanded = expand_with_ancillaries(set(plan.wanted_genres))
    except Exception:
        expanded = set(plan.wanted_genres)
    plan.expanded_genres = sorted(expanded)

    progress(0, 0, "scanning DB")
    samples_collected: List[Tuple[int, str, str, str, str]] = []

    with db._conn() as c:
        cur = c.execute(
            "SELECT id, source_text, output_text, genre, source_type "
            "FROM rephrases WHERE accepted = 1")
        for i, row in enumerate(cur):
            plan.total_scanned += 1
            if i % 5_000 == 0:
                progress(i, 0,
                         f"scanning DB ({plan.total_scanned:,})")
            row_id = int(row["id"])
            src = row["source_text"] or ""
            out = row["output_text"] or ""
            row_genre_raw = (row["genre"] or "").lower().strip()

            # Bucket 1: untagged. Kept by default (universal context),
            # dropped if the user opted into the stricter mode.
            if not row_genre_raw:
                if drop_untagged:
                    _drop(plan, samples_collected, row_id,
                          src, out, "(untagged)",
                          "untagged-row", sample_limit)
                else:
                    plan.kept_count += 1
                continue

            # Bucket 2: genre tag overlaps the expanded scope → keep.
            # Uses contains + fuzzy match so composite tags like
            # "gothic horror" hit "horror", "sci-fi" hits "scifi",
            # and typos like "horor" hit "horror".
            from src.data.genres import genres_overlap
            if genres_overlap(row_genre_raw, expanded):
                plan.kept_count += 1
                continue

            # Bucket 3: hard filter would drop. Try the fuzzy
            # craft-keep escape — confidently-craft rows are useful
            # regardless of their tagged genre.
            try:
                from src.data.text_kind import classify_kind
                kind = classify_kind(src, out)
            except Exception:
                kind = "unknown"
            if kind == "craft":
                plan.kept_count += 1
                continue

            # Otherwise: drop.
            _drop(plan, samples_collected, row_id, src, out,
                  row_genre_raw, "off-genre", sample_limit)

    plan.sample_drops = samples_collected
    plan.elapsed_seconds = round(time.time() - t0, 2)
    return plan


def _drop(plan: ScopeFilterPlan,
          samples: List[Tuple[int, str, str, str, str]],
          row_id: int, src: str, out: str,
          row_genre: str, reason: str, sample_limit: int) -> None:
    """Record a drop in the plan + collect samples for preview."""
    plan.drop_ids.append(row_id)
    plan.by_reason[reason] = plan.by_reason.get(reason, 0) + 1
    # Per-genre breakdown for the selective-drop UI.
    plan.drops_by_genre.setdefault(row_genre, []).append(row_id)
    if row_genre not in plan.first_samples_by_genre:
        plan.first_samples_by_genre[row_genre] = _trunc(src, 120)
    if len(samples) < sample_limit:
        samples.append((
            row_id, _trunc(src, 160), _trunc(out, 160),
            row_genre, reason))


def _trunc(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ")
    return s if len(s) <= n else s[:n - 1] + "…"


# ── Apply ────────────────────────────────────────────────────


def apply_plan(db: RephraseDatabase, plan: ScopeFilterPlan) -> int:
    """Delete every row in ``plan.drop_ids``. Returns rows deleted."""
    return apply_drops(db, plan.drop_ids)


def apply_drops(db: RephraseDatabase, row_ids: List[int]) -> int:
    """Delete the supplied row ids. Returns rows deleted.

    Used by the dialog when the user has unchecked some genres to
    *keep* — the dialog computes the filtered id list from the
    plan's ``drops_by_genre`` and passes it here directly. Chunked
    into 500-id batches so the SQL ``IN`` clause stays under
    SQLite's parameter cap on older builds. Idempotent — re-running
    on already-deleted IDs is a no-op (rowcount returns 0 for
    those).
    """
    if not row_ids:
        return 0
    deleted = 0
    with db._conn() as c:
        for i in range(0, len(row_ids), 500):
            chunk = row_ids[i:i + 500]
            placeholders = ",".join("?" * len(chunk))
            cur = c.execute(
                f"DELETE FROM rephrases WHERE id IN ({placeholders})",
                chunk)
            deleted += cur.rowcount
    return deleted
