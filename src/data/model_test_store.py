"""Persistent store for trained-model test runs + user ratings.

The Hub and Training Studio both let users probe a loaded model
with arbitrary prompts. Until now, those interactions were
ephemeral — output went to a text box, the user closed the tab,
and the next session started fresh.

This module stores them. Each test gets:
  * A unique id + timestamp
  * The prompt + response + generation params
  * A user-assigned **rating** (1-5 stars) and **category**
  * Free-form notes

Stats are computed on demand: overall and per-category averages
+ counts per model. The Hub and the Studio Step-4 surface both
read from this store; ratings entered in either place are visible
in the other.

**Storage** — single JSON file at
``~/.creativeos/model_tests.json``. We use JSON rather than
SQLite because:

  * Test counts stay small (10s-100s per model in normal use)
    so the linear-scan cost of compute is negligible.
  * It matches the existing registry pattern
    (``trained_models.json``, ``pinned_models.json``,
    ``modal_jobs.json``).
  * The user can hand-edit / inspect / version-control the file.

**Public API**:

  * :class:`TestResult` — one stored record.
  * :class:`ModelStats` — overall + per-category aggregates.
  * :func:`save_test_result` — append a new record.
  * :func:`load_results` — filter by model / category.
  * :func:`compute_stats` — overall + per-category averages.
  * :func:`update_test_rating` — re-rate an existing record.
  * :func:`delete_test` — drop a record.
  * :func:`list_models_with_results` / :func:`list_categories`
    for UI dropdowns.

**Default categories** mirror the training intents
(``voice``, ``rephrase``, ``plot``, ``character``,
``worldbuilding``, ``chat``) plus an open-ended user category.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_STORE_PATH = Path.home() / ".creativeos" / "model_tests.json"
# Lock to keep parallel save_test_result calls from clobbering
# each other on the read-modify-write cycle. Best-effort across
# processes (most users only run one studio); strict within one
# process.
_LOCK = threading.RLock()


DEFAULT_CATEGORIES = [
    "voice",
    "rephrase",
    "plot",
    "character",
    "worldbuilding",
    "chat",
    "other",
]


@dataclass
class TestResult:
    """One stored model-test record."""
    id: str
    model_name: str
    model_path: str
    category: str
    prompt: str
    response: str
    rating: int = 0       # 1-5 stars; 0 = unrated
    notes: str = ""
    created_at: str = ""  # ISO8601
    intent_used: str = ""
    generation_params: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TestResult":
        # Drop unknown keys defensively so older / newer versions
        # of the schema can coexist.
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in d.items() if k in known}
        return cls(**clean)


@dataclass
class CategoryStats:
    """Aggregate for one (model, category) combination."""
    category: str
    n_tests: int = 0
    n_rated: int = 0
    mean_rating: float = 0.0
    rating_distribution: Dict[int, int] = field(default_factory=dict)
    most_recent: str = ""

    @property
    def has_data(self) -> bool:
        return self.n_tests > 0


@dataclass
class ModelStats:
    """Overall + per-category aggregates for one model."""
    model_name: str
    n_tests: int = 0
    n_rated: int = 0
    mean_rating: float = 0.0
    rating_distribution: Dict[int, int] = field(default_factory=dict)
    by_category: List[CategoryStats] = field(default_factory=list)
    most_recent: str = ""


# ── Storage I/O ────────────────────────────────────────────


def _ensure_dir() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _read_all() -> List[Dict[str, Any]]:
    if not _STORE_PATH.exists():
        return []
    try:
        with open(_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError) as e:
        print(f"[model_test_store] Could not read {_STORE_PATH}: {e}")
        return []


def _write_all(records: List[Dict[str, Any]]) -> bool:
    """Atomic-ish write: write to a temp file and rename so a
    crash mid-write doesn't truncate the store."""
    _ensure_dir()
    tmp = _STORE_PATH.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _STORE_PATH)
        return True
    except OSError as e:
        print(f"[model_test_store] Could not write {_STORE_PATH}: {e}")
        return False


# ── Public API ─────────────────────────────────────────────


def save_test_result(*,
                     model_name: str,
                     model_path: str,
                     category: str,
                     prompt: str,
                     response: str,
                     rating: int = 0,
                     notes: str = "",
                     intent_used: str = "",
                     generation_params: Optional[Dict[str, Any]] = None,
                     duration_ms: int = 0,
                     test_id: str = "",
                     ) -> TestResult:
    """Append a new test record. Returns the saved record.

    ``test_id`` is generated when not provided. ``rating`` of 0
    means unrated — the user can rate later via
    :func:`update_test_rating`.
    """
    if not model_name:
        raise ValueError("model_name is required")
    rating = max(0, min(5, int(rating or 0)))
    record = TestResult(
        id=test_id or str(uuid.uuid4()),
        model_name=model_name,
        model_path=model_path or "",
        category=(category or "other").strip().lower(),
        prompt=prompt or "",
        response=response or "",
        rating=rating,
        notes=notes or "",
        created_at=datetime.now().isoformat(timespec="seconds"),
        intent_used=(intent_used or "").lower(),
        generation_params=dict(generation_params or {}),
        duration_ms=int(duration_ms or 0),
    )
    with _LOCK:
        existing = _read_all()
        existing.append(record.to_dict())
        _write_all(existing)
    return record


def load_results(*,
                 model_name: Optional[str] = None,
                 category: Optional[str] = None,
                 limit: Optional[int] = None,
                 ) -> List[TestResult]:
    """Read records, newest first.

    Both filters are optional. ``limit`` caps the number of
    records returned (after filtering + sorting), useful for the
    UI list views.
    """
    raw = _read_all()
    out: List[TestResult] = []
    for d in raw:
        if model_name and d.get("model_name") != model_name:
            continue
        if category and (d.get("category") or "").lower() != category.lower():
            continue
        out.append(TestResult.from_dict(d))
    # Newest first by created_at.
    out.sort(key=lambda r: r.created_at or "", reverse=True)
    if limit is not None and limit > 0:
        out = out[:limit]
    return out


def update_test_rating(test_id: str,
                       *,
                       rating: Optional[int] = None,
                       category: Optional[str] = None,
                       notes: Optional[str] = None,
                       ) -> bool:
    """Update fields on an existing record. Returns True if found.

    Pass ``None`` for any field to leave it unchanged. Empty
    string is meaningful — pass ``""`` to clear notes / category.
    """
    if not test_id:
        return False
    with _LOCK:
        raw = _read_all()
        changed = False
        for d in raw:
            if d.get("id") != test_id:
                continue
            if rating is not None:
                d["rating"] = max(0, min(5, int(rating)))
            if category is not None:
                d["category"] = (category or "other").strip().lower()
            if notes is not None:
                d["notes"] = notes
            changed = True
            break
        if changed:
            _write_all(raw)
        return changed


def delete_test(test_id: str) -> bool:
    """Remove a record. Returns True if anything was deleted."""
    if not test_id:
        return False
    with _LOCK:
        raw = _read_all()
        before = len(raw)
        raw = [d for d in raw if d.get("id") != test_id]
        if len(raw) == before:
            return False
        _write_all(raw)
        return True


def delete_all_for_model(model_name: str) -> int:
    """Drop every record for a model. Used when the model is
    deleted via the Hub or Training Studio so test history doesn't
    accumulate orphaned rows. Returns the count removed."""
    if not model_name:
        return 0
    with _LOCK:
        raw = _read_all()
        kept = [d for d in raw if d.get("model_name") != model_name]
        n_dropped = len(raw) - len(kept)
        if n_dropped > 0:
            _write_all(kept)
        return n_dropped


def compute_stats(model_name: str) -> ModelStats:
    """Build the per-model aggregate (overall + per-category).

    ``mean_rating`` and ``rating_distribution`` ignore unrated
    (rating=0) records — averaging across "I haven't decided yet"
    would be misleading.
    """
    results = load_results(model_name=model_name)
    stats = ModelStats(model_name=model_name)
    if not results:
        return stats

    stats.n_tests = len(results)
    stats.most_recent = results[0].created_at  # newest first

    # Overall ratings.
    rated = [r for r in results if r.rating > 0]
    stats.n_rated = len(rated)
    if rated:
        stats.mean_rating = sum(r.rating for r in rated) / len(rated)
    for r in rated:
        stats.rating_distribution[r.rating] = (
            stats.rating_distribution.get(r.rating, 0) + 1)

    # Per-category aggregates.
    by_cat: Dict[str, List[TestResult]] = {}
    for r in results:
        by_cat.setdefault(r.category or "other", []).append(r)
    cat_stats: List[CategoryStats] = []
    for cat, recs in sorted(by_cat.items()):
        rated_recs = [r for r in recs if r.rating > 0]
        cs = CategoryStats(
            category=cat,
            n_tests=len(recs),
            n_rated=len(rated_recs),
            mean_rating=(
                sum(r.rating for r in rated_recs) / len(rated_recs)
                if rated_recs else 0.0),
            most_recent=max(
                (r.created_at for r in recs if r.created_at),
                default=""),
        )
        for r in rated_recs:
            cs.rating_distribution[r.rating] = (
                cs.rating_distribution.get(r.rating, 0) + 1)
        cat_stats.append(cs)
    # Sort by recent activity within categories — most-active first.
    cat_stats.sort(key=lambda c: c.most_recent or "", reverse=True)
    stats.by_category = cat_stats
    return stats


def list_models_with_results() -> List[Tuple[str, int]]:
    """Return ``[(model_name, n_tests), …]`` sorted by test count
    descending. Used by the Hub's leaderboard view."""
    counts: Dict[str, int] = {}
    for d in _read_all():
        name = d.get("model_name") or ""
        if name:
            counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def list_categories(*, model_name: Optional[str] = None) -> List[str]:
    """Distinct categories that exist in the store, optionally
    scoped to one model. The default categories are merged in so
    the UI dropdown is never empty even on a fresh install."""
    seen = set(DEFAULT_CATEGORIES)
    for d in _read_all():
        if model_name and d.get("model_name") != model_name:
            continue
        cat = (d.get("category") or "").strip().lower()
        if cat:
            seen.add(cat)
    return sorted(seen)
