"""Tests for training readiness, regularization and post-run assessment.

Run:
    python -m tests.test_training_insights
"""

from __future__ import annotations

import json
import math
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ai.training_insights import (  # noqa: E402
    TASKS, analyze_dataset, assess_training, edit_similarity,
    grouped_split_indices, load_training_report, recommend_regularization,
    row_content_key, save_training_report,
)

WORDS = ("amber river lantern quiet storm harbor velvet ember ridge willow "
         "cinder meadow falcon granite hollow ivory juniper kestrel").split()


def _sentence(i: int, n: int = 30) -> str:
    return f"s{i} " + " ".join(WORDS[(i * 7 + j * 3) % len(WORDS)] + str((i + j) % 97)
                               for j in range(n)) + "."


def _row(source_type, inp, out, rating="good", instruction="Rewrite this."):
    return {"instruction": instruction, "input": f"Passage:\n{inp}",
            "output": out,
            "metadata": {"source_type": source_type, "rating": rating}}


def _write(rows):
    d = Path(tempfile.mkdtemp(prefix="wa_ti_"))
    p = d / "ds.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return d, p


# ── Dataset analysis ────────────────────────────────────────

def test_duplicates_counted_once_and_reported():
    rows = [_row("rephrase", _sentence(i), _sentence(i + 500)) for i in range(50)]
    rows = rows * 4  # oversampled ×4
    d, p = _write(rows)
    rep = analyze_dataset(p, ["rephrase"])
    assert rep.n_rows == 200 and rep.n_unique == 50
    assert abs(rep.duplicate_rate - 0.75) < 1e-9
    assert rep.coverage[0].rows == 50
    assert any("copies" in n for n in rep.quality_notes)
    shutil.rmtree(d)


def test_copyedit_rows_split_from_rephrase_by_edit_distance():
    light = []
    for i in range(40):
        s = _sentence(i)
        light.append(_row("rephrase", s, s.replace("amber", "ambre", 1) + " ok"))
    heavy = [_row("rephrase", _sentence(i), _sentence(i + 900)) for i in range(60)]
    d, p = _write(light + heavy)
    rep = analyze_dataset(p, ["rephrase", "copyedit"])
    cov = {c.task: c for c in rep.coverage}
    assert cov["copyedit"].rows == 40, cov["copyedit"].rows
    assert cov["rephrase"].rows == 60
    # Only rephrase chosen: every rewrite counts as rephrase.
    rep2 = analyze_dataset(p, ["rephrase"])
    assert rep2.coverage[0].rows == 100
    # Only copyedit chosen: heavy rewrites are off-task.
    rep3 = analyze_dataset(p, ["copyedit"])
    assert rep3.coverage[0].rows == 40 and rep3.n_off_task == 60
    shutil.rmtree(d)


def test_task_sources_and_off_task_rows():
    rows = ([_row("worldbuilding", f"q{i}", _sentence(i)) for i in range(30)]
            + [_row("critique", f"c{i}", _sentence(i + 50)) for i in range(20)]
            + [_row("plot", f"p{i}", _sentence(i + 90)) for i in range(10)])
    d, p = _write(rows)
    rep = analyze_dataset(p, ["worldbuilding", "critique"])
    cov = {c.task: c.rows for c in rep.coverage}
    assert cov == {"worldbuilding": 30, "critique": 20}
    assert rep.n_off_task == 10
    shutil.rmtree(d)


def test_defects_lower_quality_and_effective_count():
    good = [_row("worldbuilding", f"q{i}", _sentence(i), "excellent") for i in range(80)]
    bad = ([_row("worldbuilding", f"e{i}", "", "excellent") for i in range(10)]
           + [_row("worldbuilding", _sentence(i + 300), _sentence(i + 300), "excellent")
              for i in range(10)])
    d, p = _write(good + bad)
    rep = analyze_dataset(p, ["worldbuilding"])
    assert rep.n_empty == 10 and rep.n_identity == 10
    assert 0.75 < rep.quality_score < 0.85, rep.quality_score
    assert rep.coverage[0].rows == 80
    assert rep.coverage[0].effective < 80
    shutil.rmtree(d)


def test_truncation_detected():
    long_out = " ".join(_sentence(i) for i in range(20))
    rows = [_row("critique", f"c{i}", long_out + str(i)) for i in range(30)]
    d, p = _write(rows)
    rep = analyze_dataset(p, ["critique"], max_length_tokens=128)
    assert rep.n_truncated == 30
    assert any("cut off" in n for n in rep.quality_notes)
    shutil.rmtree(d)


def test_readiness_status_tiers_and_combo_total():
    spec = TASKS["worldbuilding"]
    rows = [_row("worldbuilding", f"q{i}", _sentence(i), "excellent")
            for i in range(spec.recommended + 10)]
    d, p = _write(rows)
    rep = analyze_dataset(p, ["worldbuilding"])
    assert rep.coverage[0].status == "good", rep.coverage[0]
    rep2 = analyze_dataset(p, ["worldbuilding", "critique"])
    assert rep2.readiness == "insufficient"  # no critique rows
    assert rep2.total_recommended == (TASKS["worldbuilding"].recommended
                                      + TASKS["critique"].recommended)
    crit = [c for c in rep2.coverage if c.task == "critique"][0]
    assert crit.shortfall == TASKS["critique"].recommended
    shutil.rmtree(d)


def test_missing_file_is_empty_report():
    rep = analyze_dataset(Path("/nonexistent/x.jsonl"), ["rephrase"])
    assert rep.n_rows == 0 and rep.readiness == "insufficient"


def test_edit_similarity_bounds():
    s = _sentence(1)
    assert edit_similarity(s, s) == 1.0
    assert edit_similarity(s, _sentence(400)) < 0.5
    assert edit_similarity("", s) == 0.0


# ── Split ───────────────────────────────────────────────────

def test_grouped_split_never_leaks_copies():
    keys = [f"k{i % 40}" for i in range(200)]  # 40 groups ×5 copies
    tr, ev = grouped_split_indices(keys, 0.2, seed=1)
    tr_keys = {keys[i] for i in tr}
    ev_keys = {keys[i] for i in ev}
    assert not (tr_keys & ev_keys)
    assert len(ev) == len(ev_keys) == 8  # one copy per eval group
    assert len(tr) == 32 * 5


def test_grouped_split_too_small_skips_eval():
    tr, ev = grouped_split_indices(["a", "a", "b"], 0.15, min_eval=1)
    assert ev == [] and tr == [0, 1, 2]


def test_row_content_key_ignores_whitespace_and_case():
    a = {"instruction": "Hi", "input": "x  y", "output": "Z"}
    b = {"instruction": "hi", "input": "x y", "output": "z"}
    assert row_content_key(a) == row_content_key(b)


# ── Regularization ─────────────────────────────────────────

def test_regularization_scales_with_dataset():
    small = [_row("worldbuilding", f"q{i}", _sentence(i)) for i in range(60)]
    d, p = _write(small)
    plan_s = recommend_regularization(analyze_dataset(p, ["worldbuilding"]))
    assert plan_s.weight_decay >= 0.1 and plan_s.lora_dropout >= 0.1
    assert plan_s.max_lora_r <= 8 and plan_s.early_stopping_patience > 0
    assert plan_s.eval_fraction * 60 >= 12  # bumped toward ≥30 held out (capped 30%)
    assert plan_s.neftune_alpha > 0
    shutil.rmtree(d)
    big = [_row("rephrase", _sentence(i), _sentence(i + 5000), "excellent")
           for i in range(2500)]
    d, p = _write(big)
    plan_b = recommend_regularization(analyze_dataset(p, ["rephrase"]))
    assert plan_b.weight_decay < plan_s.weight_decay
    assert plan_b.max_lora_r > plan_s.max_lora_r
    assert plan_b.eval_fraction == 0.1
    shutil.rmtree(d)


def test_copyedit_only_disables_neftune():
    rows = []
    for i in range(100):
        s = _sentence(i)
        rows.append(_row("rephrase", s, s + " fixed"))
    d, p = _write(rows)
    plan = recommend_regularization(analyze_dataset(p, ["copyedit"]))
    assert plan.neftune_alpha == 0
    shutil.rmtree(d)


# ── Assessment ──────────────────────────────────────────────

def _hist(train, evals, step_per_eval=10):
    h = [{"loss": v, "step": i + 1, "epoch": (i + 1) / 10} for i, v in enumerate(train)]
    for j, v in enumerate(evals):
        h.append({"eval_loss": v, "step": (j + 1) * step_per_eval})
    return sorted(h, key=lambda x: x["step"])


def _titles(a):
    return {al.title for al in a.alerts}


def test_healthy_run():
    train = [2.0 - i * 0.018 for i in range(40)]  # ends ~1.3
    evals = [1.9, 1.6, 1.45, 1.4]
    a = assess_training(_hist(train, evals))
    assert a.verdict == "healthy", [x.title for x in a.alerts]
    assert a.best_eval_loss == 1.4 and a.best_eval_step == 40
    assert a.train_loss_reduction > 0.3
    assert a.generalization_gap < 0.2
    assert math.isclose(a.eval_perplexity, math.exp(1.4), rel_tol=1e-2)


def test_overfitting_detected_and_rollback_mentioned():
    train = [2.0 - i * 0.045 for i in range(40)]
    evals = [1.5, 1.3, 1.45, 1.7]
    a = assess_training(_hist(train, evals), restored_best=True)
    assert "Overfitting" in _titles(a)
    assert a.verdict == "problem"
    over = [x for x in a.alerts if x.title == "Overfitting"][0]
    assert "best checkpoint" in over.detail
    assert a.eval_rise_from_best > 0.15
    # restored best → perplexity reflects the best checkpoint
    assert math.isclose(a.eval_perplexity, math.exp(1.3), rel_tol=1e-3)


def test_mild_overfit_is_warning():
    train = [2.0 - i * 0.02 for i in range(40)]
    evals = [1.5, 1.4, 1.48]
    a = assess_training(_hist(train, evals))
    assert "Early signs of overfitting" in _titles(a)
    assert a.verdict == "review"


def test_memorization_detected():
    train = [2.0 * (0.9 ** i) for i in range(40)]  # → ~0.03
    evals = [1.5, 1.3, 1.25, 1.2]
    a = assess_training(_hist(train, evals))
    assert "Memorization" in _titles(a)


def test_underfitting_and_still_improving():
    train = [2.0 - i * 0.002 for i in range(40)]
    evals = [1.99, 1.95, 1.9]
    a = assess_training(_hist(train, evals))
    assert "Possible underfitting" in _titles(a)
    assert "Still improving" in _titles(a)


def test_divergence_detected():
    train = [2.0, 2.5, float("nan"), 3.0]
    a = assess_training(_hist(train, []))
    assert "Training diverged (NaN/∞ loss)" in _titles(a)
    assert a.verdict == "problem"


def test_rising_train_loss_is_critical():
    train = [1.0 + i * 0.1 for i in range(30)]
    a = assess_training(_hist(train, [1.5, 2.0]))
    assert "Training loss went up" in _titles(a)


def test_no_eval_warns():
    a = assess_training(_hist([2.0 - i * 0.03 for i in range(30)], []))
    assert "No validation measured" in _titles(a)


def test_early_stop_and_dataset_alerts():
    rows = [_row("critique", f"c{i}", _sentence(i)) for i in range(30)]
    d, p = _write(rows)
    rep = analyze_dataset(p, ["critique"])
    train = [2.0 - i * 0.03 for i in range(40)]
    a = assess_training(_hist(train, [1.6, 1.5, 1.45, 1.44]),
                        report=rep, planned_steps=100)
    t = _titles(a)
    assert a.early_stopped and "Stopped early" in t
    assert "Trained on too little data" in t
    assert "Noisy validation set" in t
    shutil.rmtree(d)


def test_actual_held_out_count_overrides_estimate():
    a = assess_training(_hist([2.0 - i * 0.018 for i in range(40)], [1.6, 1.5]),
                        n_eval=12)
    noisy = [x for x in a.alerts if x.title == "Noisy validation set"]
    assert noisy and "Only 12 examples" in noisy[0].detail
    a2 = assess_training(_hist([2.0 - i * 0.018 for i in range(40)], [1.6, 1.5]),
                         n_eval=200)
    assert "Noisy validation set" not in _titles(a2)


def test_report_round_trip():
    rows = [_row("critique", f"c{i}", _sentence(i)) for i in range(30)]
    d, p = _write(rows)
    rep = analyze_dataset(p, ["critique"])
    a = assess_training(_hist([2.0 - i * 0.03 for i in range(40)], [1.6, 1.5]),
                        report=rep)
    save_training_report(d, assessment=a, dataset=rep, settings={"epochs": 3})
    loaded = load_training_report(d)
    assert loaded["settings"] == {"epochs": 3}
    la = loaded["assessment"]
    assert la.verdict == a.verdict and la.best_eval_loss == a.best_eval_loss
    assert [x.title for x in la.alerts] == [x.title for x in a.alerts]
    assert la.eval_curve == a.eval_curve
    assert loaded["dataset"]["n_unique"] == 30
    assert load_training_report(d / "missing") is None
    shutil.rmtree(d)


def _run_all() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL {t.__name__}")
            traceback.print_exc()
    print()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
