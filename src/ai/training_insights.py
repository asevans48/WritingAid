"""Training insights — dataset readiness, overfitting control, run assessment.

Pure Python (no Qt, no torch) so it can be unit-tested and reused by
both the local trainer and the Modal path.

Three stages of a training run are covered:

  * **Before training** — :func:`analyze_dataset` measures the size
    and quality of the exported JSONL against the task(s) the user
    is training for, and :func:`estimate_requirements` turns that
    into "you have N effective examples, the task needs ~M".
  * **Configuring training** — :func:`recommend_regularization`
    picks anti-overfitting settings (validation split, evaluation
    frequency, early stopping, weight decay, LoRA dropout, NEFTune)
    for the measured dataset, and :func:`grouped_split_indices`
    builds a validation split that cannot leak duplicated rows.
  * **After training** — :func:`assess_training` reads the trainer's
    loss history and reports fit/validation metrics plus alerts for
    overfitting, underfitting, divergence and noisy validation.

Sample-size targets are rules of thumb for LoRA fine-tunes of
instruction-tuned 1-8B bases, not guarantees: a few hundred curated
examples teach a format or style (cf. LIMA: ~1k examples), while
skills that must generalise to new inputs (copyediting, critique)
need low thousands. Quality matters more than raw count, so counts
are discounted for duplicates, defects and low ratings.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


# ── Task catalogue ─────────────────────────────────────────


@dataclass(frozen=True)
class TaskSpec:
    key: str
    label: str
    # Database source types whose rows can teach this task.
    source_types: Tuple[str, ...]
    # Effective (unique, quality-weighted) examples needed.
    minimum: int        # below this the model mostly memorises
    recommended: int    # reliable results for most users
    strong: int         # diminishing returns beyond this
    description: str


# Rows from these sources are rewrites of a passage; copyediting rows
# are the subset whose rewrite is a light touch.
_REWRITE_SOURCES = ("rephrase", "agent", "chat_writing")

TASKS: Dict[str, TaskSpec] = {
    "rephrase": TaskSpec(
        "rephrase", "Rephrasing", _REWRITE_SOURCES,
        minimum=150, recommended=600, strong=2000,
        description="Rewrite passages in a target voice or tone."),
    "worldbuilding": TaskSpec(
        "worldbuilding", "Worldbuilding", ("worldbuilding",),
        minimum=100, recommended=500, strong=1500,
        description="Generate setting elements consistent with your world."),
    "copyedit": TaskSpec(
        "copyedit", "Copyediting", _REWRITE_SOURCES,
        minimum=300, recommended=1200, strong=4000,
        description=("Light-touch corrections that keep wording. Learned from "
                     "rewrite pairs whose output stays close to the input.")),
    "critique": TaskSpec(
        "critique", "Critiquing", ("critique",),
        minimum=150, recommended=600, strong=2000,
        description="Structured feedback on a passage or chapter."),
}

TASK_ORDER = ("rephrase", "worldbuilding", "copyedit", "critique")

# Rating → how much one example is worth relative to an excellent one.
_RATING_WEIGHT = {"excellent": 1.0, "good": 0.9, "neutral": 0.7}
_UNRATED_WEIGHT = 0.8

# A rewrite counts as a copyedit when its words mostly survive.
COPYEDIT_MIN_SIMILARITY = 0.75
# Similarity is O(n²); beyond this many candidates we sample.
_SIMILARITY_SAMPLE_CAP = 4000

_MIN_OUTPUT_CHARS = 20


def tasks_label(tasks: Sequence[str]) -> str:
    return " + ".join(TASKS[t].label for t in tasks if t in TASKS) or "—"


# ── Row helpers ────────────────────────────────────────────


def _row_texts(rec: Dict[str, Any]) -> Tuple[str, str, str]:
    """(instruction, input, output) for Alpaca or chat-format rows."""
    if "messages" in rec:
        msgs = rec.get("messages") or []
        user = "\n".join(m.get("content", "") for m in msgs
                         if m.get("role") == "user")
        out = "\n".join(m.get("content", "") for m in msgs
                        if m.get("role") == "assistant")
        return "", user, out
    return (rec.get("instruction", "") or "", rec.get("input", "") or "",
            rec.get("output", "") or "")


def row_content_key(rec: Dict[str, Any]) -> str:
    """Stable hash of a row's content; copies share a key."""
    instr, inp, out = _row_texts(rec)
    norm = "\x1f".join(" ".join(s.split()).lower() for s in (instr, inp, out))
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def _passage_of(input_text: str) -> str:
    """The passage being rewritten (exporter puts it after 'Passage:')."""
    marker = "Passage:\n"
    idx = input_text.rfind(marker)
    return input_text[idx + len(marker):] if idx >= 0 else input_text


_WORD = re.compile(r"\w+|[^\w\s]")


def edit_similarity(source: str, output: str, max_words: int = 200) -> float:
    """Word-level similarity in [0, 1] between a passage and its rewrite."""
    a = _WORD.findall(source.lower())[:max_words]
    b = _WORD.findall(output.lower())[:max_words]
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _length_ratio_ok(source: str, output: str) -> bool:
    ls, lo = len(source), len(output)
    return ls > 0 and 0.7 <= lo / ls <= 1.4


# ── Dataset analysis ───────────────────────────────────────


@dataclass
class TaskCoverage:
    task: str
    rows: int = 0                 # unique on-task rows
    effective: float = 0.0        # rows × quality
    minimum: int = 0
    recommended: int = 0
    strong: int = 0
    status: str = "insufficient"  # insufficient | workable | good | strong
    estimated: bool = False       # count extrapolated from a sample

    @property
    def label(self) -> str:
        return TASKS[self.task].label if self.task in TASKS else self.task

    @property
    def shortfall(self) -> int:
        return max(0, int(math.ceil(self.recommended - self.effective)))


@dataclass
class DatasetReport:
    tasks: List[str] = field(default_factory=list)
    n_rows: int = 0
    n_unique: int = 0
    n_empty: int = 0              # no output
    n_identity: int = 0           # output == passage (nothing to learn)
    n_too_short: int = 0
    n_truncated: int = 0          # longer than max_length tokens
    n_off_task: int = 0           # unique rows not serving any chosen task
    rating_counts: Dict[str, int] = field(default_factory=dict)
    by_source: Dict[str, int] = field(default_factory=dict)
    median_output_chars: int = 0
    max_length_tokens: int = 512
    quality_score: float = 0.0    # 0..1
    quality_notes: List[str] = field(default_factory=list)
    coverage: List[TaskCoverage] = field(default_factory=list)
    total_recommended: int = 0
    readiness: str = "insufficient"
    eval_fraction: float = 0.15

    @property
    def duplicate_rate(self) -> float:
        return 1 - self.n_unique / self.n_rows if self.n_rows else 0.0

    @property
    def effective_total(self) -> float:
        return sum(c.effective for c in self.coverage)

    @property
    def eval_rows(self) -> int:
        """Validation rows a grouped split would hold out."""
        return int(round(self.n_unique * self.eval_fraction))

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["duplicate_rate"] = self.duplicate_rate
        d["eval_rows"] = self.eval_rows
        return d


_STATUS_ORDER = ("insufficient", "workable", "good", "strong")


def _status_for(effective: float, spec: TaskSpec) -> str:
    if effective >= spec.strong:
        return "strong"
    if effective >= spec.recommended:
        return "good"
    if effective >= spec.minimum:
        return "workable"
    return "insufficient"


def _classify_task(source_type: str, is_light_edit: Optional[bool],
                   tasks: Sequence[str]) -> Optional[str]:
    """The single chosen task a row counts toward, or None (off-task).

    Light-edit rewrites go to copyediting when it's chosen; other
    rewrites go to rephrasing. Each row counts once so combined
    targets aren't met by double counting.
    """
    if (source_type in _REWRITE_SOURCES and "copyedit" in tasks
            and is_light_edit):
        return "copyedit"
    for t in tasks:
        if t == "copyedit":
            continue
        if source_type in TASKS[t].source_types:
            return t
    return None


def analyze_dataset(jsonl_path: Path, tasks: Sequence[str], *,
                    max_length_tokens: int = 512,
                    chars_per_token: float = 4.0,
                    eval_fraction: float = 0.15,
                    seed: int = 42) -> DatasetReport:
    """Measure size and quality of an exported dataset for ``tasks``."""
    tasks = [t for t in TASK_ORDER if t in set(tasks)] or ["rephrase"]
    report = DatasetReport(tasks=list(tasks),
                           max_length_tokens=max_length_tokens,
                           eval_fraction=eval_fraction)
    seen: set = set()
    output_lens: List[int] = []
    rating_weight_sum = 0.0
    # Unique rows per task (rewrite rows are resolved after sampling).
    task_rows: Dict[str, int] = {t: 0 for t in tasks}
    rewrite_rows: List[Tuple[str, str]] = []  # (passage, output) to score
    max_chars = max_length_tokens * chars_per_token

    path = Path(jsonl_path)
    if not path.exists():
        return _finalize(report, task_rows, 0, 0, 0, output_lens, 0.0)

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            report.n_rows += 1
            key = row_content_key(rec)
            if key in seen:
                continue          # copies add no information
            seen.add(key)
            report.n_unique += 1

            meta = rec.get("metadata") or {}
            st = (meta.get("source_type") or "unknown").lower()
            report.by_source[st] = report.by_source.get(st, 0) + 1
            rating = (meta.get("rating") or "").lower()
            report.rating_counts[rating or "unrated"] = (
                report.rating_counts.get(rating or "unrated", 0) + 1)
            rating_weight_sum += _RATING_WEIGHT.get(rating, _UNRATED_WEIGHT)

            instr, inp, out = _row_texts(rec)
            passage = _passage_of(inp)
            output_lens.append(len(out))
            if not out.strip():
                report.n_empty += 1
                continue
            if passage.strip() and " ".join(passage.split()) == " ".join(out.split()):
                report.n_identity += 1
                continue
            if len(out.strip()) < _MIN_OUTPUT_CHARS:
                report.n_too_short += 1
            if len(instr) + len(inp) + len(out) > max_chars:
                report.n_truncated += 1

            if (st in _REWRITE_SOURCES and "copyedit" in tasks
                    and passage.strip()):
                rewrite_rows.append((passage, out))
                continue
            t = _classify_task(st, None, tasks)
            if t is None:
                report.n_off_task += 1
            else:
                task_rows[t] += 1

    # Score rewrite rows for edit distance (sampled when large).
    n_light, n_heavy, estimated = _split_rewrites(rewrite_rows, seed)
    if n_light:
        task_rows["copyedit"] = task_rows.get("copyedit", 0) + n_light
    if n_heavy:
        if "rephrase" in tasks:
            task_rows["rephrase"] += n_heavy
        else:
            report.n_off_task += n_heavy
    avg_rating = (rating_weight_sum / report.n_unique) if report.n_unique else 0.0
    return _finalize(report, task_rows, n_light, n_heavy, estimated,
                     output_lens, avg_rating)


def _split_rewrites(rows: List[Tuple[str, str]], seed: int) -> Tuple[int, int, bool]:
    if not rows:
        return 0, 0, False
    candidates = rows
    estimated = len(rows) > _SIMILARITY_SAMPLE_CAP
    if estimated:
        candidates = random.Random(seed).sample(rows, _SIMILARITY_SAMPLE_CAP)
    light = sum(1 for src, out in candidates
                if _length_ratio_ok(src, out)
                and edit_similarity(src, out) >= COPYEDIT_MIN_SIMILARITY)
    if estimated:
        light = int(round(light / len(candidates) * len(rows)))
    return light, len(rows) - light, estimated


def _finalize(report: DatasetReport, task_rows: Dict[str, int],
              n_light: int, n_heavy: int, estimated: bool,
              output_lens: List[int], avg_rating: float) -> DatasetReport:
    if output_lens:
        output_lens.sort()
        report.median_output_chars = output_lens[len(output_lens) // 2]

    u = report.n_unique
    notes = report.quality_notes
    if u:
        unusable = report.n_empty + report.n_identity
        defect_rate = (unusable + 0.5 * report.n_too_short
                       + 0.5 * report.n_truncated) / u
        quality = max(0.0, min(1.0, avg_rating * (1.0 - defect_rate)))
        report.quality_score = round(quality, 3)
        if report.duplicate_rate > 0.05:
            notes.append(
                f"{report.duplicate_rate:.0%} of rows are copies (oversampling "
                f"or duplicates); only {u:,} unique examples carry information.")
        if unusable:
            notes.append(f"{unusable:,} rows have an empty output or an output "
                         f"identical to the input — nothing to learn from them.")
        if report.n_too_short:
            notes.append(f"{report.n_too_short:,} outputs are under "
                         f"{_MIN_OUTPUT_CHARS} characters.")
        if report.n_truncated / u > 0.05:
            notes.append(
                f"{report.n_truncated / u:.0%} of rows exceed the "
                f"{report.max_length_tokens}-token context and will be cut off "
                f"mid-answer during training.")
        if avg_rating < 0.8:
            notes.append("Most rows are neutral or unrated — rate your best "
                         "outputs 👍/⭐ to raise quality.")
        if report.n_off_task / u > 0.25:
            notes.append(
                f"{report.n_off_task / u:.0%} of rows don't match the chosen "
                f"task(s) and dilute training. Untick unrelated sources on Step 1.")

    for t in report.tasks:
        spec = TASKS[t]
        rows = task_rows.get(t, 0)
        eff = rows * report.quality_score
        report.coverage.append(TaskCoverage(
            task=t, rows=rows, effective=round(eff, 1),
            minimum=spec.minimum, recommended=spec.recommended,
            strong=spec.strong, status=_status_for(eff, spec),
            estimated=estimated and t in ("copyedit", "rephrase")))

    report.total_recommended = sum(c.recommended for c in report.coverage)
    worst = min((_STATUS_ORDER.index(c.status) for c in report.coverage),
                default=0)
    report.readiness = _STATUS_ORDER[worst]
    if len(report.coverage) > 1:
        shares = [c.effective for c in report.coverage]
        if min(shares) > 0 and max(shares) / min(shares) > 5:
            notes.append(
                "Tasks are badly imbalanced — the smallest task will be "
                "under-learned. Add data for it or train it separately.")
    return report


# ── Leakage-free validation split ──────────────────────────


def grouped_split_indices(keys: Sequence[str], eval_fraction: float, *,
                          seed: int = 42, min_eval: int = 1
                          ) -> Tuple[List[int], List[int]]:
    """Split row indices so identical rows never straddle train/eval.

    Rows sharing a content key (e.g. oversampled copies) are grouped;
    whole groups go to one side. The eval side keeps one copy per
    group so validation loss isn't skewed by repetition. Returns
    ``(train_idx, eval_idx)``; eval is empty when too few groups.
    """
    groups: Dict[str, List[int]] = {}
    for i, k in enumerate(keys):
        groups.setdefault(k, []).append(i)
    order = list(groups)
    n_eval_groups = int(round(len(order) * eval_fraction))
    if n_eval_groups < min_eval or len(order) - n_eval_groups < 1:
        return list(range(len(keys))), []
    random.Random(seed).shuffle(order)
    eval_keys = set(order[:n_eval_groups])
    train_idx: List[int] = []
    eval_idx: List[int] = []
    for k in groups:
        if k in eval_keys:
            eval_idx.append(groups[k][0])
        else:
            train_idx.extend(groups[k])
    return sorted(train_idx), sorted(eval_idx)


# ── Anti-overfitting recommendation ────────────────────────


@dataclass
class RegularizationPlan:
    eval_fraction: float = 0.15
    evals_per_epoch: int = 2
    early_stopping_patience: int = 3   # 0 = off
    weight_decay: float = 0.01
    lora_dropout: float = 0.05
    neftune_alpha: float = 0.0         # 0 = off
    max_lora_r: int = 16
    epochs: int = 3
    rationale: List[str] = field(default_factory=list)


def recommend_regularization(report: DatasetReport) -> RegularizationPlan:
    """Pick overfitting protection for the measured dataset.

    Smaller effective datasets get stronger regularization and more
    frequent evaluation (so early stopping reacts within an epoch);
    epochs are allowed to run longer because early stopping, not the
    epoch count, decides when to stop.
    """
    eff = report.effective_total
    plan = RegularizationPlan()
    why = plan.rationale
    if eff < 300:
        plan.eval_fraction, plan.evals_per_epoch = 0.2, 4
        plan.early_stopping_patience, plan.weight_decay = 2, 0.1
        plan.lora_dropout, plan.max_lora_r, plan.epochs = 0.1, 8, 5
        why.append(f"Small dataset (~{eff:.0f} effective examples): strong "
                   f"regularization (dropout 0.1, weight decay 0.1), LoRA rank "
                   f"≤ 8, and evaluation 4× per epoch so early stopping halts "
                   f"as soon as validation loss turns up.")
    elif eff < 2000:
        plan.eval_fraction, plan.evals_per_epoch = 0.15, 2
        plan.early_stopping_patience, plan.weight_decay = 3, 0.05
        plan.lora_dropout, plan.max_lora_r, plan.epochs = 0.05, 16, 3
        why.append(f"Medium dataset (~{eff:.0f} effective examples): moderate "
                   f"regularization, LoRA rank ≤ 16, evaluation twice per epoch.")
    else:
        plan.eval_fraction, plan.evals_per_epoch = 0.1, 4
        plan.early_stopping_patience, plan.weight_decay = 3, 0.01
        plan.lora_dropout, plan.max_lora_r, plan.epochs = 0.05, 32, 2
        why.append(f"Large dataset (~{eff:.0f} effective examples): light "
                   f"regularization; a 10% holdout is already statistically "
                   f"solid. Evaluating 4× per epoch keeps long epochs observable.")
    if report.n_unique and report.n_unique * plan.eval_fraction < 30:
        plan.eval_fraction = min(0.3, max(plan.eval_fraction,
                                          30 / max(report.n_unique, 1)))
        why.append(f"Validation share raised to {plan.eval_fraction:.0%} so at "
                   f"least ~30 examples are held out — fewer makes validation "
                   f"loss too noisy to trust.")
    generative = [t for t in report.tasks if t != "copyedit"]
    if generative and eff < 5000:
        plan.neftune_alpha = 5.0
        why.append("NEFTune (embedding noise, α=5) on: it reduces "
                   "memorization on small instruction datasets for "
                   "generative tasks.")
    elif "copyedit" in report.tasks:
        why.append("NEFTune off: copyediting needs exact token fidelity.")
    if report.duplicate_rate > 0.05:
        why.append("Duplicate rows are kept together on one side of the "
                   "train/validation split so validation loss can't be "
                   "flattered by memorized copies.")
    return plan


# ── Post-training assessment ───────────────────────────────


@dataclass
class TrainingAlert:
    level: str        # critical | warning | info
    title: str
    detail: str
    suggestion: str = ""


@dataclass
class TrainingAssessment:
    verdict: str = "unknown"       # healthy | review | problem | unknown
    train_curve: List[Tuple[int, float]] = field(default_factory=list)
    eval_curve: List[Tuple[int, float]] = field(default_factory=list)
    initial_train_loss: Optional[float] = None
    final_train_loss: Optional[float] = None
    best_eval_loss: Optional[float] = None
    best_eval_step: Optional[int] = None
    final_eval_loss: Optional[float] = None
    eval_perplexity: Optional[float] = None
    generalization_gap: Optional[float] = None   # final eval − final train
    train_loss_reduction: Optional[float] = None  # fraction, 0..1
    eval_rise_from_best: Optional[float] = None   # fraction
    total_steps: int = 0
    early_stopped: bool = False
    restored_best: bool = False
    alerts: List[TrainingAlert] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TrainingAssessment":
        d = dict(d or {})
        d["alerts"] = [TrainingAlert(**a) for a in d.get("alerts", [])]
        d["train_curve"] = [tuple(p) for p in d.get("train_curve", [])]
        d["eval_curve"] = [tuple(p) for p in d.get("eval_curve", [])]
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def _mean(xs: Iterable[float]) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def assess_training(log_history: Sequence[Dict[str, Any]], *,
                    report: Optional[DatasetReport] = None,
                    planned_steps: Optional[int] = None,
                    restored_best: bool = False,
                    n_eval: Optional[int] = None) -> TrainingAssessment:
    """Turn a Hugging Face ``trainer.state.log_history`` into metrics + alerts.

    ``n_eval`` is the number of validation rows the trainer actually held
    out; when omitted, the dataset report's estimate is used.
    """
    a = TrainingAssessment(restored_best=restored_best)
    raw_train = [(int(h.get("step", 0)), h["loss"]) for h in log_history
                 if "loss" in h]
    raw_eval = [(int(h.get("step", 0)), h["eval_loss"]) for h in log_history
                if "eval_loss" in h]
    a.train_curve = [(s, float(v)) for s, v in raw_train if _finite(v)]
    a.eval_curve = [(s, float(v)) for s, v in raw_eval if _finite(v)]
    steps = [int(h.get("step", 0)) for h in log_history]
    a.total_steps = max(steps) if steps else 0
    if planned_steps:
        a.early_stopped = 0 < a.total_steps < planned_steps
    alerts = a.alerts

    if any(not _finite(v) for _, v in raw_train + raw_eval):
        alerts.append(TrainingAlert(
            "critical", "Training diverged (NaN/∞ loss)",
            "The loss became non-numeric, so the weights are unreliable.",
            "Lower the learning rate (e.g. halve it) and retrain."))

    if a.train_curve:
        vals = [v for _, v in a.train_curve]
        k = max(1, min(5, len(vals) // 10 or 1))
        a.initial_train_loss = round(_mean(vals[:k]), 4)
        a.final_train_loss = round(_mean(vals[-k:]), 4)
        if a.initial_train_loss > 0:
            a.train_loss_reduction = round(
                1 - a.final_train_loss / a.initial_train_loss, 4)
        if a.final_train_loss > a.initial_train_loss * 1.1:
            alerts.append(TrainingAlert(
                "critical", "Training loss went up",
                f"Training loss rose from {a.initial_train_loss:.3f} to "
                f"{a.final_train_loss:.3f} — the optimizer is unstable.",
                "Lower the learning rate and retrain."))
        elif a.train_loss_reduction is not None and a.train_loss_reduction < 0.1:
            alerts.append(TrainingAlert(
                "warning", "Possible underfitting",
                f"Training loss only fell {a.train_loss_reduction:.0%} "
                f"({a.initial_train_loss:.3f} → {a.final_train_loss:.3f}). "
                f"The model has barely adapted to your data.",
                "Train for more epochs, raise the learning rate a little, or "
                "check that the data actually differs from what the base "
                "model already produces."))
        if len(vals) >= 20:
            med = sorted(vals)[len(vals) // 2]
            spikes = sum(1 for v in vals[len(vals) // 10:] if v > 2.5 * med)
            if spikes:
                alerts.append(TrainingAlert(
                    "info", "Loss spikes",
                    f"{spikes} training step(s) had loss over 2.5× the median.",
                    "Occasional spikes come from unusual rows; many spikes "
                    "suggest a learning rate that is too high."))

    if not a.eval_curve:
        alerts.append(TrainingAlert(
            "warning", "No validation measured",
            "Without held-out validation loss, overfitting can't be detected "
            "and the best checkpoint can't be chosen.",
            "Add more data (≥ 20 unique rows) or raise the validation share."))
    else:
        best_step, best = min(a.eval_curve, key=lambda p: p[1])
        a.best_eval_loss, a.best_eval_step = round(best, 4), best_step
        a.final_eval_loss = round(a.eval_curve[-1][1], 4)
        reported = a.best_eval_loss if restored_best else a.final_eval_loss
        a.eval_perplexity = round(math.exp(min(reported, 20)), 2)
        if a.final_train_loss is not None:
            a.generalization_gap = round(reported - a.final_train_loss, 4)
        if best > 0:
            a.eval_rise_from_best = round(a.final_eval_loss / best - 1, 4)

        rise = a.eval_rise_from_best or 0.0
        train_still_falling = (a.train_loss_reduction or 0) > 0
        kept = (" The saved model is the best checkpoint "
                f"(step {best_step}), so the damage was rolled back."
                if restored_best else "")
        if rise >= 0.15 and train_still_falling:
            alerts.append(TrainingAlert(
                "critical", "Overfitting",
                f"Validation loss rose {rise:.0%} from its best "
                f"({a.best_eval_loss:.3f} at step {best_step}) to "
                f"{a.final_eval_loss:.3f} while training loss kept falling: "
                f"the model is memorizing rather than generalizing.{kept}",
                "Use fewer epochs, enable early stopping, raise dropout / "
                "weight decay, lower LoRA rank, or add more varied data."))
        elif rise >= 0.05 and train_still_falling:
            alerts.append(TrainingAlert(
                "warning", "Early signs of overfitting",
                f"Validation loss is {rise:.0%} above its best "
                f"({a.best_eval_loss:.3f} at step {best_step}).{kept}",
                "One fewer epoch or early stopping would likely give an "
                "equally good model sooner."))

        gap = a.generalization_gap
        if gap is not None and a.final_train_loss is not None:
            if a.final_train_loss < 0.2 and gap > 0.5:
                alerts.append(TrainingAlert(
                    "critical", "Memorization",
                    f"Training loss is very low ({a.final_train_loss:.3f}) but "
                    f"validation loss is {gap:.2f} higher: the model reproduces "
                    f"training rows instead of learning the task.",
                    "Reduce epochs and LoRA rank, enable NEFTune, and add data."))
            elif gap > 0.5:
                alerts.append(TrainingAlert(
                    "warning", "Large generalization gap",
                    f"Validation loss exceeds training loss by {gap:.2f}.",
                    "Strengthen regularization or add more varied examples."))

        if len(a.eval_curve) >= 2 and rise < 0.005:
            prev = a.eval_curve[-2][1]
            if prev > 0 and (prev - a.eval_curve[-1][1]) / prev > 0.02:
                alerts.append(TrainingAlert(
                    "info", "Still improving",
                    "Validation loss was still dropping at the end of training.",
                    "Another epoch could help (use 'Train More on This Model')."))
        if len(a.eval_curve) == 1:
            alerts.append(TrainingAlert(
                "info", "Only one validation point",
                "A single measurement can't show a trend.",
                "Evaluate more often per epoch to see the curve."))

    if a.early_stopped:
        alerts.append(TrainingAlert(
            "info", "Stopped early",
            f"Early stopping ended training at step {a.total_steps} of "
            f"{planned_steps} because validation loss stopped improving.", ""))

    held_out = n_eval if n_eval is not None else (
        report.eval_rows if report is not None else None)
    if held_out and held_out < 20 and a.eval_curve:
        alerts.append(TrainingAlert(
            "warning", "Noisy validation set",
            f"Only {held_out} examples were held out, so validation "
            f"numbers can swing a lot between runs.",
            "Treat the metrics as rough; add data for firmer numbers."))

    if report is not None:
        short = [c for c in report.coverage if c.status == "insufficient"]
        if short:
            alerts.append(TrainingAlert(
                "warning", "Trained on too little data",
                "Below the minimum for: " + ", ".join(
                    f"{c.label} ({c.effective:.0f} of ≥{c.minimum})"
                    for c in short) + ".",
                "Expect inconsistent output on these tasks until more "
                "examples are collected."))
        if report.quality_score and report.quality_score < 0.6:
            alerts.append(TrainingAlert(
                "warning", "Low dataset quality",
                f"Quality score {report.quality_score:.2f}: "
                + " ".join(report.quality_notes[:2]),
                "Clean and re-rate the data before the next run."))

    levels = {al.level for al in alerts}
    if "critical" in levels:
        a.verdict = "problem"
    elif "warning" in levels:
        a.verdict = "review"
    elif a.train_curve:
        a.verdict = "healthy"
    return a


# ── Persistence ────────────────────────────────────────────

REPORT_FILENAME = "training_report.json"


def save_training_report(model_dir: Path, *, assessment: TrainingAssessment,
                         dataset: Optional[DatasetReport] = None,
                         settings: Optional[Dict[str, Any]] = None) -> Path:
    path = Path(model_dir) / REPORT_FILENAME
    payload = {
        "version": 1,
        "assessment": assessment.to_dict(),
        "dataset": dataset.to_dict() if dataset else None,
        "settings": settings or {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def load_training_report(model_dir: Path) -> Optional[Dict[str, Any]]:
    """Return ``{"assessment": TrainingAssessment, "dataset": dict|None,
    "settings": dict}`` or None when the model has no report."""
    path = Path(model_dir) / REPORT_FILENAME
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "assessment": TrainingAssessment.from_dict(raw.get("assessment") or {}),
        "dataset": raw.get("dataset"),
        "settings": raw.get("settings") or {},
    }
