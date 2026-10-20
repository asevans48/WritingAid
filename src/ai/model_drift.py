"""Model drift — has the chosen corpora mix moved away from what a model
was trained on, and is retraining worthwhile?

At training time :func:`compute_fingerprint` records what the model saw:
the recipe (sources, rating bar, genres, collections, tasks), a compact
hash of every example, and the distributions that matter for a
fine-tune (source / task / genre / rating mix, input and output
lengths, vocabulary). It's saved next to the model.

Later, :func:`compare_fingerprints` measures the currently chosen mix
against that baseline:

  * **Coverage** — share of current examples the model has never seen,
    and share of its training examples no longer in the mix.
  * **Distribution shift** — Jensen–Shannon divergence for categorical
    mixes and vocabulary, Population Stability Index for lengths.
  * **Recipe changes** — sources, tasks, rating bar, genres, collections.
  * **Performance** (optional, needs torch) — the model's loss on unseen
    examples vs. its validation loss at training time
    (see :mod:`src.ai.drift_eval`).

and turns them into a recommendation: no action, monitor, continue
training (more of the same kind of data), or retrain from scratch
(the distribution or the scope changed).

Thresholds follow common practice: PSI < 0.1 stable, 0.1–0.25 moderate,
> 0.25 significant; JS divergence (base 2, 0..1) < 0.05 small,
0.05–0.15 moderate, > 0.15 large.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.ai.training_insights import _row_texts, _passage_of, analyze_dataset, row_content_key

FINGERPRINT_FILENAME = "training_fingerprint.json"
DRIFT_LOG_FILENAME = "drift_checks.json"
_KEY_CHARS = 16          # 64-bit content keys — collisions negligible
_TOP_TERMS = 400
LENGTH_BINS = (0, 40, 80, 160, 320, 640, 1280, 2560, 5120)

_STOP = frozenset("""
the and that with for was his her you are not but have had they from this
she him were their what when there been would which them then into could
than your more about will said one all out like just over only some can
its our who has did any other these those also very upon where after
before through again because while being each most such should here
""".split())
_TERM = re.compile(r"[a-z][a-z'\-]{2,}")


# ── Fingerprint ────────────────────────────────────────────


@dataclass
class DataFingerprint:
    created_at: str = ""
    recipe: Dict[str, Any] = field(default_factory=dict)
    tasks: List[str] = field(default_factory=list)
    n_rows: int = 0
    n_unique: int = 0
    quality_score: float = 0.0
    keys: List[str] = field(default_factory=list)       # truncated content hashes
    source_mix: Dict[str, int] = field(default_factory=dict)
    task_mix: Dict[str, int] = field(default_factory=dict)
    genre_mix: Dict[str, int] = field(default_factory=dict)
    rating_mix: Dict[str, int] = field(default_factory=dict)
    input_len_hist: List[int] = field(default_factory=list)
    output_len_hist: List[int] = field(default_factory=list)
    top_terms: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DataFingerprint":
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


def _bin(n: int) -> int:
    for i in range(len(LENGTH_BINS) - 1, -1, -1):
        if n >= LENGTH_BINS[i]:
            return i
    return 0


def compute_fingerprint(jsonl_path: Path, *, tasks: Sequence[str],
                        recipe: Optional[Dict[str, Any]] = None) -> DataFingerprint:
    """Fingerprint the exact dataset a model is trained on."""
    report = analyze_dataset(jsonl_path, tasks)
    fp = DataFingerprint(
        created_at=datetime.now().isoformat(timespec="seconds"),
        recipe=dict(recipe or {}),
        tasks=list(report.tasks),
        n_rows=report.n_rows,
        n_unique=report.n_unique,
        quality_score=report.quality_score,
        source_mix=dict(report.by_source),
        task_mix={c.task: c.rows for c in report.coverage},
        rating_mix=dict(report.rating_counts),
        input_len_hist=[0] * len(LENGTH_BINS),
        output_len_hist=[0] * len(LENGTH_BINS),
    )
    if report.n_off_task:
        fp.task_mix["off-task"] = report.n_off_task
    seen = set()
    terms: Counter = Counter()
    genres: Counter = Counter()
    path = Path(jsonl_path)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = row_content_key(rec)[:_KEY_CHARS]
                if key in seen:
                    continue
                seen.add(key)
                _instr, inp, out = _row_texts(rec)
                fp.input_len_hist[_bin(len(_passage_of(inp)))] += 1
                fp.output_len_hist[_bin(len(out))] += 1
                terms.update(t for t in _TERM.findall(out.lower()) if t not in _STOP)
                meta = rec.get("metadata") or {}
                for g in (meta.get("genre") or "").lower().replace(";", ",").split(","):
                    if g.strip():
                        genres[g.strip()] += 1
    fp.keys = sorted(seen)
    fp.genre_mix = dict(genres)
    fp.top_terms = dict(terms.most_common(_TOP_TERMS))
    return fp


def save_fingerprint(model_dir: Path, fp: DataFingerprint) -> Path:
    path = Path(model_dir) / FINGERPRINT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fp.to_dict()), encoding="utf-8")
    return path


def load_fingerprint(model_dir: Path) -> Optional[DataFingerprint]:
    path = Path(model_dir) / FINGERPRINT_FILENAME
    if not path.exists():
        return None
    try:
        return DataFingerprint.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


# ── Divergence measures ────────────────────────────────────


def _normalize(counts: Dict[str, float], keys: Iterable[str]) -> List[float]:
    vals = [max(0.0, float(counts.get(k, 0))) for k in keys]
    total = sum(vals)
    return [v / total for v in vals] if total else [0.0] * len(vals)


def js_divergence(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Jensen–Shannon divergence (base 2) in [0, 1]; 0 when both empty."""
    keys = sorted(set(a) | set(b))
    if not keys:
        return 0.0
    p, q = _normalize(a, keys), _normalize(b, keys)
    if not any(p) or not any(q):
        return 0.0 if not any(p) and not any(q) else 1.0
    m = [(x + y) / 2 for x, y in zip(p, q)]

    def kl(x, y):
        return sum(xi * math.log2(xi / yi) for xi, yi in zip(x, y) if xi > 0)
    return max(0.0, min(1.0, (kl(p, m) + kl(q, m)) / 2))


def psi(expected: Sequence[int], actual: Sequence[int], eps: float = 1e-4) -> float:
    """Population Stability Index between two histograms with equal bins."""
    te, ta = sum(expected), sum(actual)
    if not te or not ta:
        return 0.0
    total = 0.0
    for e, a in zip(expected, actual):
        pe, pa = max(e / te, eps), max(a / ta, eps)
        total += (pa - pe) * math.log(pa / pe)
    return total


# ── Comparison ─────────────────────────────────────────────


@dataclass
class DriftSignal:
    name: str
    value: str
    level: str        # low | moderate | high | info
    explanation: str


@dataclass
class DriftReport:
    model_name: str = ""
    trained_at: str = ""
    days_since_training: Optional[int] = None
    baseline_unique: int = 0
    current_unique: int = 0
    new_examples: int = 0
    removed_examples: int = 0
    new_fraction: float = 0.0
    removed_fraction: float = 0.0
    signals: List[DriftSignal] = field(default_factory=list)
    recipe_changes: List[str] = field(default_factory=list)
    performance: Optional[Dict[str, Any]] = None
    drift_score: float = 0.0          # 0..1 summary
    recommendation: str = "none"      # none | monitor | continue | retrain
    headline: str = ""
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_RECOMMENDATION_TEXT = {
    "none": "No retraining needed — the model still matches your chosen mix.",
    "monitor": "Minor drift — no retraining yet; check again after adding more data.",
    "continue": ("Continue training this model on the current mix — there's new "
                 "data of the same kind it was trained on."),
    "retrain": ("Retrain from the base model on the current mix — what you're "
                "training for has shifted too far for incremental training."),
}


def _js_level(v: float) -> str:
    return "low" if v < 0.05 else "moderate" if v < 0.15 else "high"


def _psi_level(v: float) -> str:
    return "low" if v < 0.1 else "moderate" if v < 0.25 else "high"


def _recipe_diff(old: Dict[str, Any], new: Dict[str, Any],
                 current_sources: Optional[Dict[str, int]] = None
                 ) -> Tuple[List[str], bool]:
    """Human-readable recipe changes, and whether the scope changed.

    A newly ticked source only changes the scope when it actually
    contributes examples to the current mix.
    """
    changes: List[str] = []
    scope = False
    o_src, n_src = set(old.get("sources") or []), set(new.get("sources") or [])
    if old and (o_src or n_src) and o_src != n_src:
        added = sorted(n_src - o_src)
        if added:
            live = [a for a in added if (current_sources or {}).get(a, 0) > 0]
            empty = [a for a in added if a not in live]
            if live:
                changes.append("Sources added: " + ", ".join(live))
                scope = True
            if empty:
                changes.append("Sources ticked but contributing no examples: "
                               + ", ".join(empty))
        if o_src - n_src:
            changes.append("Sources removed: " + ", ".join(sorted(o_src - n_src)))
    o_t, n_t = set(old.get("tasks") or []), set(new.get("tasks") or [])
    if old and o_t and n_t and o_t != n_t:
        changes.append(f"Tasks changed: {', '.join(sorted(o_t))} → "
                       f"{', '.join(sorted(n_t))}")
        if n_t - o_t:
            scope = True
    for key, label in (("min_rating", "Rating bar"), ("genres", "Genre filter"),
                       ("collections", "Corpus collections"),
                       ("expand_corpus_windows", "Corpus expansion"),
                       ("enforce_purpose_fit", "Purpose-fit filter")):
        if key in old and key in new:
            ov, nv = old[key], new[key]
            if isinstance(ov, list) and isinstance(nv, list):
                ov, nv = sorted(ov), sorted(nv)
            if ov != nv:
                changes.append(f"{label}: {_short(ov)} → {_short(nv)}")
    return changes, scope


def _short(v: Any) -> str:
    if v is None:
        return "all"
    if isinstance(v, list):
        return ", ".join(map(str, v[:6])) + ("…" if len(v) > 6 else "") if v else "none"
    return str(v)


_LEVEL_POINTS = {"low": 0.0, "moderate": 0.5, "high": 1.0}


def compare_fingerprints(baseline: DataFingerprint, current: DataFingerprint, *,
                         model_name: str = "",
                         performance: Optional[Dict[str, Any]] = None,
                         now: Optional[datetime] = None) -> DriftReport:
    """Measure drift of ``current`` (chosen mix now) from ``baseline``
    (what the model was trained on) and recommend an action."""
    r = DriftReport(model_name=model_name, trained_at=baseline.created_at,
                    baseline_unique=len(baseline.keys) or baseline.n_unique,
                    current_unique=len(current.keys) or current.n_unique,
                    performance=performance)
    try:
        r.days_since_training = ((now or datetime.now())
                                 - datetime.fromisoformat(baseline.created_at)).days
    except (TypeError, ValueError):
        pass

    old_keys, new_keys = set(baseline.keys), set(current.keys)
    r.new_examples = len(new_keys - old_keys)
    r.removed_examples = len(old_keys - new_keys)
    r.new_fraction = r.new_examples / len(new_keys) if new_keys else 0.0
    r.removed_fraction = r.removed_examples / len(old_keys) if old_keys else 0.0
    sig = r.signals

    lvl = ("low" if r.new_fraction < 0.1 else
           "moderate" if r.new_fraction < 0.3 else "high")
    sig.append(DriftSignal(
        "Unseen examples", f"{r.new_examples:,} ({r.new_fraction:.0%} of current mix)",
        lvl, "Examples in the current mix the model never trained on."))
    lvl = ("low" if r.removed_fraction < 0.1 else
           "moderate" if r.removed_fraction < 0.3 else "high")
    sig.append(DriftSignal(
        "Dropped examples", f"{r.removed_examples:,} ({r.removed_fraction:.0%} of training set)",
        lvl, "Training examples no longer in the mix (deleted, re-rated, "
             "filtered out). The model still reflects them."))

    for name, a, b, why in (
            ("Source mix", baseline.source_mix, current.source_mix,
             "Which capture sources the examples come from."),
            ("Task mix", baseline.task_mix, current.task_mix,
             "Balance between rephrasing / worldbuilding / copyediting / critique."),
            ("Genre mix", baseline.genre_mix, current.genre_mix,
             "Genre tags on the examples."),
            ("Rating mix", baseline.rating_mix, current.rating_mix,
             "Share of excellent / good / neutral examples.")):
        if not a and not b:
            continue
        v = js_divergence(a, b)
        sig.append(DriftSignal(name, f"JS {v:.3f}", _js_level(v), why))

    v = js_divergence(baseline.top_terms, current.top_terms)
    # Vocabulary from samples is noisier — slightly looser bands.
    vlvl = "low" if v < 0.08 else "moderate" if v < 0.2 else "high"
    sig.append(DriftSignal("Vocabulary", f"JS {v:.3f}", vlvl,
                           "Distribution of frequent content words in outputs."))
    for name, a, b, why in (
            ("Output length", baseline.output_len_hist, current.output_len_hist,
             "How long the answers the model should produce are."),
            ("Input length", baseline.input_len_hist, current.input_len_hist,
             "How long the passages/prompts it receives are.")):
        if sum(a) and sum(b):
            v = psi(a, b)
            sig.append(DriftSignal(name, f"PSI {v:.3f}", _psi_level(v), why))

    dq = current.quality_score - baseline.quality_score
    if abs(dq) >= 0.05:
        sig.append(DriftSignal(
            "Data quality", f"{baseline.quality_score:.2f} → {current.quality_score:.2f}",
            "moderate" if dq < 0 else "info",
            "Quality score of the dataset (ratings, defects)."))

    if r.days_since_training is not None:
        sig.append(DriftSignal("Age", f"{r.days_since_training} day(s)", "info",
                               "Time since the model was trained."))

    perf_level = None
    if performance and performance.get("ratio") is not None:
        ratio = float(performance["ratio"])
        perf_level = ("low" if ratio < 1.05 else
                      "moderate" if ratio < 1.2 else "high")
        sig.append(DriftSignal(
            "Loss on unseen data",
            f"{performance.get('new_loss', 0):.3f} vs {performance.get('baseline_loss', 0):.3f} "
            f"at training (×{ratio:.2f})",
            perf_level,
            "Model loss on examples it never saw, vs. its validation loss "
            "when trained. Higher = the model handles the new data worse."))

    r.recipe_changes, scope_changed = _recipe_diff(
        baseline.recipe, current.recipe, current.source_mix)

    # ── Recommendation ──
    shift_names = ("Source mix", "Task mix", "Genre mix", "Vocabulary",
                   "Output length", "Input length")
    shift = [s for s in sig if s.name in shift_names]
    high_shift = [s.name for s in shift if s.level == "high"]
    mod_shift = [s.name for s in shift if s.level == "moderate"]
    scored = [s for s in sig if s.level in _LEVEL_POINTS]
    r.drift_score = round(sum(_LEVEL_POINTS[s.level] for s in scored)
                          / len(scored), 3) if scored else 0.0
    reasons = r.reasons

    if scope_changed:
        reasons.append("The recipe now includes sources or tasks the model was "
                       "never trained for.")
    if high_shift:
        reasons.append("Large distribution shift in: " + ", ".join(high_shift) + ".")
    if r.removed_fraction >= 0.3:
        reasons.append(f"{r.removed_fraction:.0%} of the training examples are no "
                       f"longer in the mix — the model still reflects them, and "
                       f"continued training can't unlearn them.")
    if perf_level == "high":
        reasons.append("The model performs clearly worse on unseen data than it "
                       "did at training time.")

    # A measured loss outranks proxy statistics: if the model already
    # handles the shifted data as well as its validation set, a
    # distribution shift alone doesn't justify starting over.
    shift_tolerated = bool(high_shift) and perf_level == "low"
    if shift_tolerated:
        reasons.append("…but the model already scores the unseen data as well "
                       "as its validation set, so continued training on the "
                       "current mix is enough.")
    if scope_changed or r.removed_fraction >= 0.3 or (
            high_shift and not shift_tolerated) or (
            perf_level == "high" and (mod_shift or r.new_fraction >= 0.3)):
        r.recommendation = "retrain"
    elif shift_tolerated:
        r.recommendation = "continue"
    elif (r.new_fraction >= 0.3 or perf_level in ("moderate", "high")
          or (r.new_fraction >= 0.1 and mod_shift)):
        r.recommendation = "continue"
        if r.new_fraction >= 0.1:
            reasons.append(f"{r.new_fraction:.0%} of the current mix is new to the "
                           f"model, and it's similar to what it already learned.")
        if perf_level in ("moderate", "high"):
            reasons.append("Loss on unseen data is up — the model would benefit "
                           "from seeing it.")
        if mod_shift:
            reasons.append("Moderate shift in: " + ", ".join(mod_shift) + ".")
    elif r.new_fraction >= 0.1 or mod_shift or r.removed_fraction >= 0.1:
        r.recommendation = "monitor"
        if r.new_fraction >= 0.1:
            reasons.append(f"{r.new_fraction:.0%} new examples — not yet enough "
                           f"to be worth a training run.")
        if mod_shift:
            reasons.append("Moderate shift in: " + ", ".join(mod_shift) + ".")
    else:
        r.recommendation = "none"
        reasons.append("The current mix is essentially what the model was trained on.")
    if performance is None:
        reasons.append("Run the performance check for a direct measurement of how "
                       "the model does on the new data.")
    r.headline = _RECOMMENDATION_TEXT[r.recommendation]
    return r


# ── Drift history ──────────────────────────────────────────


def append_drift_log(model_dir: Path, report: DriftReport, *,
                     replace_last: bool = False) -> None:
    """Keep a small per-model history of drift checks (newest last).

    ``replace_last`` updates the latest entry instead (e.g. when the
    performance measurement completes for the same check).
    """
    path = Path(model_dir) / DRIFT_LOG_FILENAME
    try:
        history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, json.JSONDecodeError):
        history = []
    if replace_last and history:
        history.pop()
    history.append({
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "recommendation": report.recommendation,
        "drift_score": report.drift_score,
        "new_fraction": round(report.new_fraction, 4),
        "removed_fraction": round(report.removed_fraction, 4),
        "performance_ratio": (report.performance or {}).get("ratio"),
    })
    path.write_text(json.dumps(history[-50:], indent=2), encoding="utf-8")


def load_drift_log(model_dir: Path) -> List[Dict[str, Any]]:
    path = Path(model_dir) / DRIFT_LOG_FILENAME
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, json.JSONDecodeError):
        return []
