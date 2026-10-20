"""Tests for model drift detection and the retraining recommendation.

Run:
    python -m tests.test_model_drift
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import traceback
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ai.drift_eval import split_rows_by_novelty  # noqa: E402
from src.ai.model_drift import (  # noqa: E402
    append_drift_log, compare_fingerprints, compute_fingerprint,
    js_divergence, load_drift_log, load_fingerprint, psi, save_fingerprint,
)

FANTASY = ("dragon castle sword wizard spell kingdom knight throne realm "
           "enchanted forest goblin rune prophecy").split()
SCIFI = ("starship orbit reactor android quantum colony hyperdrive nebula "
         "terminal cybernetic plasma airlock galaxy drone").split()


def _text(words, i, n=40):
    return f"s{i} " + " ".join(words[(i * 5 + j * 3) % len(words)] for j in range(n)) + "."


def _rows(source, words, start, count, genre="fantasy", rating="good"):
    return [{"instruction": "Rewrite.", "input": f"Passage:\n{_text(words, i + 77777)}",
             "output": _text(words, i),
             "metadata": {"source_type": source, "rating": rating, "genre": genre}}
            for i in range(start, start + count)]


RECIPE = {"sources": ["rephrase"], "tasks": ["rephrase"], "min_rating": "good",
          "genres": [], "collections": None}


def _fp(rows, tasks=("rephrase",), recipe=None):
    d = Path(tempfile.mkdtemp(prefix="wa_drift_"))
    p = d / "ds.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    fp = compute_fingerprint(p, tasks=list(tasks), recipe=recipe or dict(RECIPE))
    return d, p, fp


def test_divergence_measures():
    assert js_divergence({"a": 1}, {"a": 5}) == 0.0
    assert abs(js_divergence({"a": 1}, {"b": 1}) - 1.0) < 1e-9
    assert js_divergence({}, {}) == 0.0
    assert psi([10, 10, 10], [10, 10, 10]) == 0.0
    assert psi([30, 0, 0], [0, 0, 30]) > 1.0


def test_unchanged_mix_needs_no_retraining():
    rows = _rows("rephrase", FANTASY, 0, 300)
    d1, _, base = _fp(rows)
    d2, _, cur = _fp(list(reversed(rows)))  # same data, different order
    r = compare_fingerprints(base, cur)
    assert r.new_examples == 0 and r.removed_examples == 0
    assert r.recommendation == "none", (r.recommendation, r.reasons)
    shutil.rmtree(d1); shutil.rmtree(d2)


def test_small_addition_is_monitor():
    base_rows = _rows("rephrase", FANTASY, 0, 300)
    d1, _, base = _fp(base_rows)
    d2, _, cur = _fp(base_rows + _rows("rephrase", FANTASY, 300, 45))
    r = compare_fingerprints(base, cur)
    assert 0.1 < r.new_fraction < 0.3
    assert r.recommendation == "monitor", (r.recommendation, r.reasons)
    shutil.rmtree(d1); shutil.rmtree(d2)


def test_lots_of_same_kind_data_means_continue_training():
    base_rows = _rows("rephrase", FANTASY, 0, 300)
    d1, _, base = _fp(base_rows)
    d2, _, cur = _fp(base_rows + _rows("rephrase", FANTASY, 300, 250))
    r = compare_fingerprints(base, cur)
    assert r.new_fraction > 0.4
    assert r.recommendation == "continue", (r.recommendation, [
        (s.name, s.value, s.level) for s in r.signals])
    shutil.rmtree(d1); shutil.rmtree(d2)


def test_distribution_shift_means_retrain():
    base_rows = _rows("rephrase", FANTASY, 0, 300)
    d1, _, base = _fp(base_rows)
    d2, _, cur = _fp(base_rows + _rows("rephrase", SCIFI, 0, 400, genre="scifi"))
    r = compare_fingerprints(base, cur)
    levels = {s.name: s.level for s in r.signals}
    assert levels["Vocabulary"] == "high" and levels["Genre mix"] == "high"
    assert r.recommendation == "retrain"
    assert any("distribution shift" in x for x in r.reasons)
    shutil.rmtree(d1); shutil.rmtree(d2)


def test_new_task_scope_means_retrain():
    base_rows = _rows("rephrase", FANTASY, 0, 300)
    d1, _, base = _fp(base_rows)
    recipe = dict(RECIPE, sources=["rephrase", "critique"],
                  tasks=["rephrase", "critique"])
    d2, _, cur = _fp(base_rows + _rows("critique", FANTASY, 400, 20),
                     tasks=("rephrase", "critique"), recipe=recipe)
    r = compare_fingerprints(base, cur)
    assert r.recommendation == "retrain"
    assert any("Sources added: critique" in c for c in r.recipe_changes)
    assert any("Tasks changed" in c for c in r.recipe_changes)
    shutil.rmtree(d1); shutil.rmtree(d2)


def test_ticked_source_without_rows_is_not_a_scope_change():
    rows = _rows("rephrase", FANTASY, 0, 300)
    d1, _, base = _fp(rows)
    d2, _, cur = _fp(rows, recipe=dict(RECIPE, sources=["rephrase", "corpus"]))
    r = compare_fingerprints(base, cur)
    assert r.recipe_changes == [
        "Sources ticked but contributing no examples: corpus"]
    assert r.recommendation == "none"
    shutil.rmtree(d1); shutil.rmtree(d2)


def test_dropped_training_data_means_retrain():
    base_rows = _rows("rephrase", FANTASY, 0, 300)
    d1, _, base = _fp(base_rows)
    d2, _, cur = _fp(base_rows[:150])
    r = compare_fingerprints(base, cur)
    assert r.removed_fraction == 0.5
    assert r.recommendation == "retrain"
    shutil.rmtree(d1); shutil.rmtree(d2)


def test_recipe_setting_change_reported_without_forcing_retrain():
    rows = _rows("rephrase", FANTASY, 0, 300)
    d1, _, base = _fp(rows)
    d2, _, cur = _fp(rows, recipe=dict(RECIPE, min_rating="excellent"))
    r = compare_fingerprints(base, cur)
    assert r.recipe_changes == ["Rating bar: good → excellent"]
    assert r.recommendation == "none"
    shutil.rmtree(d1); shutil.rmtree(d2)


def test_performance_degradation_drives_recommendation():
    base_rows = _rows("rephrase", FANTASY, 0, 300)
    d1, _, base = _fp(base_rows)
    d2, _, cur = _fp(base_rows + _rows("rephrase", FANTASY, 300, 45))
    ok = compare_fingerprints(base, cur, performance={
        "new_loss": 1.02, "baseline_loss": 1.0, "ratio": 1.02})
    assert ok.recommendation == "monitor"
    worse = compare_fingerprints(base, cur, performance={
        "new_loss": 1.12, "baseline_loss": 1.0, "ratio": 1.12})
    assert worse.recommendation == "continue"
    bad = compare_fingerprints(base, cur, performance={
        "new_loss": 1.5, "baseline_loss": 1.0, "ratio": 1.5})
    assert bad.recommendation in ("continue", "retrain")
    assert any(s.name == "Loss on unseen data" and s.level == "high"
               for s in bad.signals)
    shutil.rmtree(d1); shutil.rmtree(d2)


def test_measured_performance_softens_shift_only_retrain():
    base_rows = _rows("rephrase", FANTASY, 0, 300)
    d1, _, base = _fp(base_rows)
    d2, _, cur = _fp(base_rows + _rows("rephrase", SCIFI, 0, 400, genre="scifi"))
    assert compare_fingerprints(base, cur).recommendation == "retrain"
    fine = compare_fingerprints(base, cur, performance={
        "new_loss": 1.01, "baseline_loss": 1.0, "ratio": 1.01})
    assert fine.recommendation == "continue", fine.reasons
    assert any("already scores" in x for x in fine.reasons)
    # Dropped training data still forces a retrain regardless.
    d3, _, cur2 = _fp(base_rows[:100] + _rows("rephrase", SCIFI, 0, 400, genre="scifi"))
    assert compare_fingerprints(base, cur2, performance={
        "new_loss": 1.0, "baseline_loss": 1.0, "ratio": 1.0}).recommendation == "retrain"
    shutil.rmtree(d1); shutil.rmtree(d2); shutil.rmtree(d3)


def test_drift_log_replace_last():
    rows = _rows("rephrase", FANTASY, 0, 30)
    d, _, fp = _fp(rows)
    r = compare_fingerprints(fp, fp)
    append_drift_log(d, r)
    append_drift_log(d, r, replace_last=True)
    assert len(load_drift_log(d)) == 1
    shutil.rmtree(d)


def test_age_and_fingerprint_persistence():
    rows = _rows("rephrase", FANTASY, 0, 50)
    d, _, fp = _fp(rows)
    fp.created_at = (datetime.now() - timedelta(days=40)).isoformat(timespec="seconds")
    save_fingerprint(d, fp)
    loaded = load_fingerprint(d)
    assert loaded.keys == fp.keys and loaded.recipe == RECIPE
    assert load_fingerprint(d / "nope") is None
    r = compare_fingerprints(loaded, fp)
    assert r.days_since_training == 40
    append_drift_log(d, r)
    append_drift_log(d, r)
    log = load_drift_log(d)
    assert len(log) == 2 and log[0]["recommendation"] == r.recommendation
    shutil.rmtree(d)


def test_fingerprint_dedupes_and_keys_are_compact():
    rows = _rows("rephrase", FANTASY, 0, 40)
    d, _, fp = _fp(rows * 3)
    assert fp.n_rows == 120 and len(fp.keys) == 40
    assert all(len(k) == 16 for k in fp.keys)
    assert sum(fp.output_len_hist) == 40
    shutil.rmtree(d)


def test_split_rows_by_novelty():
    base_rows = _rows("rephrase", FANTASY, 0, 30)
    d, p, fp = _fp(base_rows + _rows("rephrase", FANTASY, 30, 10))
    _, _, base = _fp(base_rows)
    new, old = split_rows_by_novelty(p, base.keys, max_rows=64)
    assert len(new) == 10 and len(old) == 30
    new, old = split_rows_by_novelty(p, base.keys, max_rows=5)
    assert len(new) == 5 and len(old) == 5
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
