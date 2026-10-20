"""Tests for the RL-from-feedback (DPO / KTO) stage.

Run:
    python -m tests.test_preference_optim
"""

from __future__ import annotations

import math
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ai.preference_optim import (  # noqa: E402
    MIN_DPO_PAIRS, MIN_KTO_EACH, assess_preference_stage, plan_preference_stage,
)
from src.data.rephrase_database import RephraseDatabase  # noqa: E402


def _db():
    d = Path(tempfile.mkdtemp(prefix="wa_pref_"))
    return d, RephraseDatabase(d / "r.db")


def _passage(i):
    return f"The lantern guttered in passage number {i} while rain fell."


# ── Data ────────────────────────────────────────────────────

def test_explicit_pairs_only_within_same_prompt():
    d, db = _db()
    db.log(_passage(1), "A lovely rewrite one.", rating="good")
    db.log(_passage(1), "A clumsy rewrite one.", rating="bad", accepted=False)
    db.log(_passage(2), "A lovely rewrite two.", rating="excellent")
    db.log(_passage(3), "A clumsy rewrite three.", rating="poor", accepted=False)
    data = db.preference_examples()
    pairs = data["pairs"]
    assert len(pairs) == 1, pairs
    assert pairs[0]["chosen"] == "A lovely rewrite one."
    assert pairs[0]["rejected"] == "A clumsy rewrite one."
    assert pairs[0]["kind"] == "explicit"
    assert _passage(1) in pairs[0]["prompt"]["input"]
    # Unpaired: every rated output, labelled.
    lab = {u["completion"]: u["desirable"] for u in data["unpaired"]}
    assert lab == {"A lovely rewrite one.": True, "A clumsy rewrite one.": False,
                   "A lovely rewrite two.": True, "A clumsy rewrite three.": False}
    shutil.rmtree(d)


def test_edit_pairs_from_rewritten_suggestions():
    d, db = _db()
    # What the rephrase dialog logs when a suggestion is edited then accepted.
    db.log(_passage(1), "Edited, better version.", rating="good", style="vivid | edited")
    db.log(_passage(1), "Original AI suggestion.", rating="neutral", accepted=False)
    # Unedited acceptance next to an unrelated neutral row: no pair.
    db.log(_passage(2), "Accepted as-is.", rating="good", style="vivid")
    db.log(_passage(2), "Some other neutral row.", rating="neutral", accepted=False)
    pairs = db.preference_examples()["pairs"]
    assert len(pairs) == 1
    assert pairs[0]["kind"] == "edit"
    assert (pairs[0]["chosen"], pairs[0]["rejected"]) == (
        "Edited, better version.", "Original AI suggestion.")
    shutil.rmtree(d)


def test_pairs_capped_per_prompt_and_filtered_by_source():
    d, db = _db()
    db.log(_passage(1), "Good answer.", rating="excellent")
    for i in range(10):
        db.log(_passage(1), f"Bad answer {i}.", rating="bad", accepted=False)
    db.log_worldbuilding("Describe the harbor city.", "Great harbor text.", rating="good")
    db.log_worldbuilding("Describe the harbor city.", "Dull harbor text.", rating="poor",
                         accepted=False)
    all_pairs = db.preference_examples()["pairs"]
    assert sum(p["chosen"] == "Good answer." for p in all_pairs) == 4
    wb = db.preference_examples(["worldbuilding"])["pairs"]
    assert [p["chosen"] for p in wb] == ["Great harbor text."]
    shutil.rmtree(d)


# ── Planning ────────────────────────────────────────────────

def _fake(n_pairs=0, n_pos=0, n_neg=0, edits=0):
    pairs = [{"prompt": {}, "chosen": "a", "rejected": "b",
              "kind": "edit" if i < edits else "explicit"} for i in range(n_pairs)]
    unpaired = ([{"prompt": {}, "completion": "x", "desirable": True}] * n_pos
                + [{"prompt": {}, "completion": "y", "desirable": False}] * n_neg)
    return {"pairs": pairs, "unpaired": unpaired}


def test_auto_prefers_dpo_then_kto_then_skips():
    p = plan_preference_stage(_fake(MIN_DPO_PAIRS, 100, 100, edits=10))
    assert p.method == "dpo" and p.n_edit_pairs == 10
    p = plan_preference_stage(_fake(5, MIN_KTO_EACH, MIN_KTO_EACH))
    assert p.method == "kto"
    p = plan_preference_stage(_fake(5, 200, 3))
    assert p.method == "off" and "Not enough feedback" in p.reason


def test_explicit_request_without_data_is_skipped():
    p = plan_preference_stage(_fake(3, 100, 100), requested="dpo")
    assert p.method == "off" and "DPO needs" in p.reason
    p = plan_preference_stage(_fake(100, 100, 100), requested="off")
    assert p.method == "off"
    p = plan_preference_stage(_fake(100, 100, 100), requested="kto")
    assert p.method == "kto"


def test_kto_class_balancing_and_lr_and_copyedit_beta():
    p = plan_preference_stage(_fake(0, 300, 50))
    assert p.method == "kto"
    assert p.undesirable_weight == 4.0 and p.desirable_weight < 1.0  # cap binds
    ratio = (300 * p.desirable_weight) / (50 * p.undesirable_weight)
    assert 1.0 <= ratio <= 4 / 3 + 1e-2, ratio
    for pos, neg in ((40, 200), (35, 1000), (1000, 35), (60, 50)):
        p = plan_preference_stage(_fake(0, pos, neg))
        r = (pos * p.desirable_weight) / (neg * p.undesirable_weight)
        assert 1.0 - 1e-2 <= r <= 4 / 3 + 1e-2, (pos, neg, r)
        assert max(p.desirable_weight, p.undesirable_weight) <= 4.0
    p = plan_preference_stage(_fake(MIN_DPO_PAIRS), sft_learning_rate=2e-4)
    assert p.learning_rate == 2e-5
    p = plan_preference_stage(_fake(MIN_DPO_PAIRS), tasks=["copyedit"])
    assert p.beta == 0.2


# ── Losses ──────────────────────────────────────────────────

def test_dpo_loss_values_and_gradient_direction():
    import torch
    from src.ai.preference_optim import dpo_loss
    z = torch.zeros(2)
    loss, cr, rr = dpo_loss(z, z, z, z, beta=0.1)
    assert math.isclose(float(loss), math.log(2), rel_tol=1e-6)
    pc = torch.tensor([0.0], requires_grad=True)
    pr = torch.tensor([0.0], requires_grad=True)
    loss, _, _ = dpo_loss(pc, pr, torch.zeros(1), torch.zeros(1), beta=0.5)
    loss.backward()
    assert pc.grad.item() < 0 < pr.grad.item()  # raise chosen, lower rejected
    loss2, _, _ = dpo_loss(torch.tensor([5.0]), torch.tensor([-5.0]),
                           torch.zeros(1), torch.zeros(1), beta=0.5)
    assert float(loss2) < math.log(2)


def test_kto_loss_direction():
    import torch
    from src.ai.preference_optim import kto_loss
    lp = torch.tensor([0.0, 0.0], requires_grad=True)
    loss, rew = kto_loss(lp, torch.zeros(2), torch.tensor([1, 0]), beta=0.5)
    loss.backward()
    assert math.isclose(float(loss.detach()), 0.5, rel_tol=1e-6)  # 1 − σ(0) each
    assert lp.grad[0].item() < 0 < lp.grad[1].item()


def test_sequence_logps_masks_prompt():
    import torch
    from src.ai.preference_optim import sequence_logps

    class Uniform(torch.nn.Module):
        def forward(self, input_ids, attention_mask=None):
            class O: pass
            o = O()
            o.logits = torch.zeros(input_ids.shape[0], input_ids.shape[1], 4)
            return o
    ids = torch.tensor([[1, 2, 3, 0]])
    labels = torch.tensor([[-100, -100, 3, 0]])
    lp = sequence_logps(Uniform(), ids, labels)
    assert math.isclose(float(lp), 2 * math.log(1 / 4), rel_tol=1e-6)


# ── Assessment ──────────────────────────────────────────────

def test_assessment_alerts():
    assert assess_preference_stage(None) == []
    assert assess_preference_stage({"method": "off"}) == []
    hist = [{"eval_loss": 0.69, "eval_accuracy": 0.5},
            {"eval_loss": 0.55, "eval_accuracy": 0.8}]
    ok = assess_preference_stage({"method": "dpo", "history": hist, "best_epoch": 1})
    assert [a["title"] for a in ok] == ["DPO improved preferences"]
    none = assess_preference_stage({"method": "dpo", "history": hist[:1], "best_epoch": 0})
    assert none[0]["title"] == "DPO didn't help"
    weak = assess_preference_stage({"method": "kto", "best_epoch": 1, "history": [
        {"eval_loss": 0.5, "eval_accuracy": 0.5}, {"eval_loss": 0.49, "eval_accuracy": 0.52}]})
    assert weak[0]["title"] == "KTO: weak preference learning"
    disp = assess_preference_stage({"method": "dpo", "best_epoch": 1, "history": [
        {"eval_loss": 0.69, "eval_accuracy": 0.5},
        {"eval_loss": 0.3, "eval_accuracy": 0.9, "eval_chosen_logp_shift": -9,
         "eval_rejected_logp_shift": -20}]})
    assert "DPO likelihood displacement" in [a["title"] for a in disp]


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
