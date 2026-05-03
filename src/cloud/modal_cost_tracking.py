"""Modal cost tracking — running tally + persistent run log.

Two surfaces:

  * **Live tally** for an in-flight run. The training UI calls
    :func:`live_estimated_cost` on a 1s timer with the JobHandle and
    gets back the accrued $ since submission, computed at the
    *current* user-configured pricing (so editing the rate while a
    run is mid-flight updates the displayed estimate the next tick).

  * **Persistent run log** under ``~/.creativeos/modal_cost_log.json``
    — one entry per submission. Updated on submit (status="running"),
    on completion (status="done"), on cancel (status="cancelled"),
    and on failure (status="failed"). Stores actual elapsed seconds,
    final estimated $ at the rate that was active at the time, and a
    snapshot of the GPU/base/adapter so the UI can render a history
    table without joining against other state.

Estimates are *estimates* — Modal bills per-second from container
start to container stop. Our elapsed clock starts at submit time
(slightly pessimistic — counts cold-start as billable) and stops
when the worker reports done/cancelled/failed. Good enough for an
"are we burning money?" UI; not a substitute for the Modal billing
dashboard.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


_COST_LOG_PATH = Path.home() / ".creativeos" / "modal_cost_log.json"


@dataclass
class RunRecord:
    """One entry in the cost log. Mirrors the JSON schema 1:1 so
    serialise/deserialise is straight ``__dict__`` copies."""
    call_id: str
    adapter_name: str
    base_model: str
    gpu: str
    submitted_at: float
    ended_at: float = 0.0
    elapsed_seconds: float = 0.0
    rate_usd_per_hour: float = 0.0     # rate snapshot at end-of-run
    estimated_cost_usd: float = 0.0    # elapsed × rate
    status: str = "running"            # running|done|cancelled|failed
    estimate_low: float = 0.0          # planning estimate, for diff
    estimate_high: float = 0.0
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RunRecord":
        # Strip any unknown keys defensively so a future schema bump
        # doesn't break older logs on read.
        valid = {k: d.get(k) for k in cls.__dataclass_fields__.keys()}
        return cls(**valid)


# ── Log read / write ──────────────────────────────────────────


def _load_all() -> List[RunRecord]:
    if not _COST_LOG_PATH.exists():
        return []
    try:
        data = json.loads(_COST_LOG_PATH.read_text())
        if not isinstance(data, list):
            return []
        return [RunRecord.from_dict(d) for d in data
                if isinstance(d, dict)]
    except Exception:
        return []


def _save_all(records: List[RunRecord]) -> None:
    try:
        _COST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _COST_LOG_PATH.write_text(
            json.dumps([r.to_dict() for r in records], indent=2))
    except Exception:
        # Best-effort — losing a cost log entry is annoying but not
        # blocking. The user's actual Modal bill is the source of
        # truth; we're a local mirror.
        pass


def list_runs(limit: Optional[int] = None) -> List[RunRecord]:
    """Most-recent first. ``limit`` caps the returned count."""
    rows = sorted(_load_all(), key=lambda r: r.submitted_at,
                  reverse=True)
    if limit is not None:
        rows = rows[:max(0, limit)]
    return rows


def lifetime_total() -> float:
    """Sum of estimated $ across every run on file (any status)."""
    return round(sum(r.estimated_cost_usd
                     for r in _load_all()), 4)


def lifetime_total_completed_only() -> float:
    """Sum across done + cancelled + failed runs (excludes "running"
    so an in-flight run doesn't get double-counted alongside the
    live tally the UI shows separately)."""
    return round(sum(r.estimated_cost_usd
                     for r in _load_all()
                     if r.status != "running"), 4)


# ── Run lifecycle ─────────────────────────────────────────────


def record_run_start(*,
                     call_id: str,
                     adapter_name: str,
                     base_model: str,
                     gpu: str,
                     submitted_at: float,
                     estimate_low: float = 0.0,
                     estimate_high: float = 0.0) -> None:
    """Add a "running" entry to the log at submission time."""
    records = _load_all()
    # Don't double-record if the same call_id is already on file
    # (e.g. UI restarted and reattached to a persisted job).
    for r in records:
        if r.call_id == call_id:
            return
    records.append(RunRecord(
        call_id=call_id,
        adapter_name=adapter_name,
        base_model=base_model,
        gpu=gpu,
        submitted_at=submitted_at,
        estimate_low=estimate_low,
        estimate_high=estimate_high,
        status="running",
    ))
    _save_all(records)


def record_run_end(*,
                   call_id: str,
                   status: str,
                   note: str = "",
                   ended_at: Optional[float] = None) -> Optional[RunRecord]:
    """Mark a run as ``done`` / ``cancelled`` / ``failed``.

    Computes elapsed_seconds = ended_at - submitted_at and snapshots
    the *current* rate for the GPU at end-of-run time (so editing
    the price after the fact doesn't rewrite history). Returns the
    updated RunRecord, or None if no matching call_id was found.
    """
    from src.cloud.modal_pricing import price_for
    records = _load_all()
    target: Optional[RunRecord] = None
    for r in records:
        if r.call_id == call_id:
            target = r
            break
    if target is None:
        return None
    target.ended_at = ended_at if ended_at is not None else time.time()
    target.elapsed_seconds = max(0.0,
                                 target.ended_at - target.submitted_at)
    target.rate_usd_per_hour = price_for(target.gpu)
    target.estimated_cost_usd = round(
        target.elapsed_seconds / 3600.0 * target.rate_usd_per_hour, 4)
    target.status = status
    if note:
        target.note = note
    _save_all(records)
    return target


def update_running_estimate(call_id: str) -> Optional[RunRecord]:
    """Update a still-running entry's estimated_cost_usd in place.

    Called periodically by the UI worker so the persisted log stays
    fresh — important if the studio crashes mid-run; the next launch
    sees the last recorded estimate rather than $0.
    """
    from src.cloud.modal_pricing import price_for
    records = _load_all()
    target: Optional[RunRecord] = None
    for r in records:
        if r.call_id == call_id:
            target = r
            break
    if target is None or target.status != "running":
        return target
    now = time.time()
    target.elapsed_seconds = max(0.0, now - target.submitted_at)
    target.rate_usd_per_hour = price_for(target.gpu)
    target.estimated_cost_usd = round(
        target.elapsed_seconds / 3600.0 * target.rate_usd_per_hour, 4)
    _save_all(records)
    return target


# ── Live tally (no log write) ─────────────────────────────────


def live_estimated_cost(*,
                        gpu: str,
                        submitted_at: float,
                        now: Optional[float] = None) -> float:
    """Compute (now - submitted_at) hours × current $/hr rate.

    Pure function — doesn't touch the log. The UI calls this on a
    QTimer and renders the result. Periodically the worker also calls
    :func:`update_running_estimate` so the persisted snapshot trends
    upward in step.
    """
    from src.cloud.modal_pricing import price_for
    end = now if now is not None else time.time()
    elapsed_h = max(0.0, (end - submitted_at) / 3600.0)
    return round(elapsed_h * price_for(gpu), 4)


def clear_log() -> bool:
    """Delete the cost log entirely. UI ``Clear history`` action."""
    if not _COST_LOG_PATH.exists():
        return True
    try:
        _COST_LOG_PATH.unlink()
        return True
    except Exception:
        return False
