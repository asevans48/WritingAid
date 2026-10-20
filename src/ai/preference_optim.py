"""Preference optimization — the reinforcement-learning-from-feedback stage.

Runs after supervised fine-tuning (SFT) and pushes the model toward
outputs the writer preferred and away from ones they rejected. Two
offline RLHF methods are supported; both optimize the KL-regularized
RL objective directly from feedback, without training a separate
reward model or sampling rollouts (practical on a laptop):

  * **DPO** (Rafailov et al., 2023) — needs *pairs*: two answers to the
    same prompt, one preferred. Sources: 👍/⭐ vs 👎 on the same passage,
    and suggestions the writer edited (edited ≻ original).
  * **KTO** (Ethayarajh et al., 2024) — needs only *unpaired* binary
    feedback (👍 or 👎 per output), which is most of what gets rated.

:func:`plan_preference_stage` decides whether the stage is appropriate
and which method to use; :func:`run_preference_stage` trains it. The
reference policy is the post-SFT model: its log-probs are computed once,
before any preference update, so no second model copy is kept. Online
RL (PPO / GRPO) is deliberately not used — it needs a reward model or
programmatic reward plus generation in the loop.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# Minimum signal before the stage is worth running. Below these, the
# preference loss mostly memorizes a handful of pairs.
MIN_DPO_PAIRS = 40
MIN_KTO_EACH = 30          # desirable AND undesirable examples
METHODS = ("auto", "dpo", "kto", "off")


# ── Planning ───────────────────────────────────────────────


@dataclass
class PreferencePlan:
    method: str = "off"              # dpo | kto | off
    reason: str = ""
    n_pairs: int = 0
    n_edit_pairs: int = 0
    n_desirable: int = 0
    n_undesirable: int = 0
    beta: float = 0.1
    learning_rate: float = 2e-5
    epochs: int = 2
    eval_fraction: float = 0.1
    desirable_weight: float = 1.0    # KTO class balancing
    undesirable_weight: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def summarize_preference_data(data: Dict[str, List[Dict[str, Any]]]) -> Dict[str, int]:
    pairs = data.get("pairs") or []
    unpaired = data.get("unpaired") or []
    return {
        "pairs": len(pairs),
        "edit_pairs": sum(p.get("kind") == "edit" for p in pairs),
        "desirable": sum(bool(u.get("desirable")) for u in unpaired),
        "undesirable": sum(not u.get("desirable") for u in unpaired),
    }


def plan_preference_stage(data: Dict[str, List[Dict[str, Any]]], *,
                          requested: str = "auto",
                          sft_learning_rate: float = 2e-4,
                          tasks: Sequence[str] = ()) -> PreferencePlan:
    """Decide whether preference optimization is appropriate, and how."""
    s = summarize_preference_data(data)
    plan = PreferencePlan(n_pairs=s["pairs"], n_edit_pairs=s["edit_pairs"],
                          n_desirable=s["desirable"],
                          n_undesirable=s["undesirable"])
    # LoRA preference tuning wants a much smaller step than SFT.
    plan.learning_rate = max(5e-6, min(5e-5, sft_learning_rate / 10))
    dpo_ok = s["pairs"] >= MIN_DPO_PAIRS
    kto_ok = min(s["desirable"], s["undesirable"]) >= MIN_KTO_EACH
    requested = (requested or "auto").lower()

    if requested == "off":
        plan.reason = "Preference optimization turned off."
        return plan
    if requested == "dpo" and not dpo_ok:
        plan.reason = (f"DPO needs ≥{MIN_DPO_PAIRS} same-prompt preference pairs; "
                       f"only {s['pairs']} available. Skipped.")
        return plan
    if requested == "kto" and not kto_ok:
        plan.reason = (f"KTO needs ≥{MIN_KTO_EACH} liked AND ≥{MIN_KTO_EACH} "
                       f"disliked outputs; have {s['desirable']} / "
                       f"{s['undesirable']}. Skipped.")
        return plan

    if requested == "dpo" or (requested == "auto" and dpo_ok):
        plan.method = "dpo"
        plan.epochs = 2 if s["pairs"] < 500 else 1
        plan.reason = (f"DPO on {s['pairs']} same-prompt pairs "
                       f"({s['edit_pairs']} from your edits): paired comparisons "
                       f"are the most direct preference signal.")
    elif requested == "kto" or (requested == "auto" and kto_ok):
        plan.method = "kto"
        plan.epochs = 2 if s["desirable"] + s["undesirable"] < 1000 else 1
        nd, nu = s["desirable"], s["undesirable"]
        # Paper guidance: keep λ_D·n_D / λ_U·n_U in [1, 4/3]. Weights are
        # capped at 4 for stability; past the cap the other class is
        # down-weighted instead so the ratio still lands in range.
        if nd and nu:
            ratio = nd / nu
            if ratio < 1:
                w = 1 / ratio
                if w <= 4.0:
                    plan.desirable_weight = round(w, 3)
                else:
                    plan.desirable_weight, plan.undesirable_weight = 4.0, round(4.0 * ratio, 3)
            elif ratio > 4 / 3:
                w = ratio / (4 / 3)
                if w <= 4.0:
                    plan.undesirable_weight = round(w, 3)
                else:
                    plan.undesirable_weight = 4.0
                    plan.desirable_weight = round((4 / 3) * 4.0 / ratio, 3)
        plan.reason = (f"KTO on {nd} liked and {nu} disliked outputs: your "
                       f"feedback is mostly unpaired thumbs up/down, which KTO "
                       f"uses directly.")
    else:
        plan.reason = (
            f"Not enough feedback yet: {s['pairs']} same-prompt pairs (need "
            f"{MIN_DPO_PAIRS} for DPO) and {s['desirable']} liked / "
            f"{s['undesirable']} disliked outputs (need {MIN_KTO_EACH} of each "
            f"for KTO). Rate weak suggestions 👎 or edit them before accepting "
            f"to collect preferences.")
        return plan
    if "copyedit" in tasks and plan.method != "off":
        plan.beta = 0.2  # stay closer to SFT: copyedits need exact fidelity
        plan.reason += " β raised to 0.2 to keep copyedits close to the SFT model."
    return plan


# ── Losses (torch) ─────────────────────────────────────────


def dpo_loss(policy_chosen, policy_rejected, ref_chosen, ref_rejected, beta: float):
    """DPO loss on summed answer log-probs. Returns (loss, chosen_reward,
    rejected_reward) — rewards are β·(policy − reference) per example."""
    import torch.nn.functional as F
    chosen_r = beta * (policy_chosen - ref_chosen)
    rejected_r = beta * (policy_rejected - ref_rejected)
    loss = -F.logsigmoid(chosen_r - rejected_r).mean()
    return loss, chosen_r.detach(), rejected_r.detach()


def kto_loss(policy_logps, ref_logps, desirable, beta: float,
             desirable_weight: float = 1.0, undesirable_weight: float = 1.0):
    """KTO loss with a batch-level KL reference point.

    The reference point z₀ is estimated as the detached, clamped mean of
    (policy − reference) over the batch — a cheap stand-in for the
    paper's mismatched-pair estimate.
    """
    import torch
    log_ratio = policy_logps - ref_logps
    z0 = log_ratio.detach().mean().clamp(min=0)
    d = desirable.bool()
    losses = torch.where(
        d,
        desirable_weight * (1 - torch.sigmoid(beta * (log_ratio - z0))),
        undesirable_weight * (1 - torch.sigmoid(beta * (z0 - log_ratio))))
    return losses.mean(), (beta * log_ratio).detach()


def sequence_logps(model, input_ids, labels):
    """Sum of log-probs of the answer tokens (labels != -100)."""
    import torch
    logits = model(input_ids=input_ids,
                   attention_mask=torch.ones_like(input_ids)).logits[:, :-1, :]
    targets = labels[:, 1:]
    mask = targets != -100
    logp = torch.log_softmax(logits.float(), dim=-1)
    tok = torch.gather(logp, 2, targets.clamp(min=0).unsqueeze(-1)).squeeze(-1)
    return (tok * mask).sum(-1)


# ── Training loop ──────────────────────────────────────────


def _encode(tokenizer, prompt: Dict[str, Any], completion: str, *,
            max_length: int, has_chat_template: bool, device):
    import torch
    from src.ai.sft_format import tokenize_rows
    rec = dict(prompt)
    rec["output"] = completion
    rec["metadata"] = dict(rec.get("metadata") or {}, format_type="instruction")
    enc = tokenize_rows(tokenizer, [rec], max_length=max_length,
                        has_chat_template=has_chat_template)
    return (torch.tensor([enc["input_ids"][0]], device=device),
            torch.tensor([enc["labels"][0]], device=device))


def run_preference_stage(model, tokenizer, data: Dict[str, List[Dict[str, Any]]],
                         plan: PreferencePlan, *, max_length: int = 512,
                         seed: int = 42,
                         log: Callable[[str], None] = lambda _m: None,
                         on_metrics: Callable[[Dict[str, Any]], None] = lambda _m: None,
                         should_stop: Callable[[], bool] = lambda: False,
                         ) -> Dict[str, Any]:
    """Train ``model`` (a PEFT model, already SFT-tuned) with DPO or KTO.

    Holds out ``plan.eval_fraction`` of examples (grouped by prompt),
    evaluates after every epoch and restores the best epoch's adapter
    weights. Returns a history dict for the training report.
    """
    import torch
    if plan.method not in ("dpo", "kto"):
        return {"method": "off", "reason": plan.reason}
    device = next(model.parameters()).device
    has_chat_template = bool(getattr(tokenizer, "chat_template", None))
    rng = random.Random(seed)

    if plan.method == "dpo":
        items = [(p["prompt"], p["chosen"], p["rejected"]) for p in data["pairs"]]
    else:
        items = [(u["prompt"], u["completion"], bool(u["desirable"]))
                 for u in data["unpaired"]]

    # Grouped split by prompt so eval prompts are unseen.
    def pkey(prompt):
        return (prompt.get("instruction", ""), prompt.get("input", ""))
    keys = sorted({pkey(it[0]) for it in items})
    rng.shuffle(keys)
    n_eval_keys = max(1, int(round(len(keys) * plan.eval_fraction))) if len(keys) >= 10 else 0
    eval_keys = set(keys[:n_eval_keys])
    train_items = [it for it in items if pkey(it[0]) not in eval_keys]
    eval_items = [it for it in items if pkey(it[0]) in eval_keys]
    log(f"  preference data: {len(train_items)} train / {len(eval_items)} "
        f"held out ({plan.method.upper()}, β={plan.beta:g}, "
        f"lr={plan.learning_rate:g}, {plan.epochs} epoch(s))")

    # Encode once; reference log-probs from the post-SFT model, frozen.
    def encode_item(it):
        prompt, a, b = it
        if plan.method == "dpo":
            return {"c": _encode(tokenizer, prompt, a, max_length=max_length,
                                 has_chat_template=has_chat_template, device=device),
                    "r": _encode(tokenizer, prompt, b, max_length=max_length,
                                 has_chat_template=has_chat_template, device=device)}
        return {"x": _encode(tokenizer, prompt, a, max_length=max_length,
                             has_chat_template=has_chat_template, device=device),
                "d": b}

    train_enc = [encode_item(it) for it in train_items]
    eval_enc = [encode_item(it) for it in eval_items]
    model.eval()
    with torch.no_grad():
        for e in train_enc + eval_enc:
            for k in ("c", "r", "x"):
                if k in e:
                    e["ref_" + k] = sequence_logps(model, *e[k]).detach()
    log("  reference log-probs computed from the SFT model")

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=plan.learning_rate, weight_decay=0.0)
    batch = 4
    steps_total = max(1, math.ceil(len(train_enc) / batch)) * plan.epochs
    step = 0
    history: List[Dict[str, Any]] = []

    def batch_loss(es):
        if plan.method == "dpo":
            pc = torch.cat([sequence_logps(model, *e["c"]) for e in es])
            pr = torch.cat([sequence_logps(model, *e["r"]) for e in es])
            rc = torch.cat([e["ref_c"] for e in es])
            rr = torch.cat([e["ref_r"] for e in es])
            loss, cr, rj = dpo_loss(pc, pr, rc, rr, plan.beta)
            # Ties (e.g. before any update, all rewards are 0) count as
            # half — chance level is 50%, not 0%.
            acc = (cr > rj).float() + 0.5 * (cr == rj).float()
            return loss, {"accuracy": float(acc.mean()),
                          "margin": float((cr - rj).mean()),
                          "chosen_logp_shift": float((pc - rc).detach().mean()),
                          "rejected_logp_shift": float((pr - rr).detach().mean())}
        px = torch.cat([sequence_logps(model, *e["x"]) for e in es])
        rx = torch.cat([e["ref_x"] for e in es])
        d = torch.tensor([e["d"] for e in es], device=px.device)
        loss, rew = kto_loss(px, rx, d, plan.beta, plan.desirable_weight,
                             plan.undesirable_weight)
        dm = d.bool()
        hit = torch.where(dm, (rew > 0).float(), (rew < 0).float())
        acc = float((hit + 0.5 * (rew == 0).float()).mean())
        return loss, {"accuracy": acc,
                      "desirable_reward": float(rew[dm].mean()) if dm.any() else 0.0,
                      "undesirable_reward": float(rew[~dm].mean()) if (~dm).any() else 0.0}

    def evaluate():
        if not eval_enc:
            return None
        model.eval()
        tot, n, agg = 0.0, 0, {}
        with torch.no_grad():
            for i in range(0, len(eval_enc), batch):
                es = eval_enc[i:i + batch]
                loss, m = batch_loss(es)
                tot += float(loss) * len(es)
                n += len(es)
                for k, v in m.items():
                    agg[k] = agg.get(k, 0.0) + v * len(es)
        return {"loss": tot / n, **{k: v / n for k, v in agg.items()}}

    def adapter_state():
        return {k: v.detach().clone() for k, v in model.named_parameters()
                if v.requires_grad}

    best = evaluate()
    if best is not None:
        history.append({"epoch": 0, "step": 0, **{f"eval_{k}": v for k, v in best.items()}})
        on_metrics(history[-1])
        log(f"  before preference training: eval loss {best['loss']:.4f}, "
            f"preference accuracy {best['accuracy']:.0%}")
    best_state, best_epoch = adapter_state(), 0

    for epoch in range(1, plan.epochs + 1):
        rng.shuffle(train_enc)
        model.train()
        for i in range(0, len(train_enc), batch):
            if should_stop():
                break
            es = train_enc[i:i + batch]
            loss, m = batch_loss(es)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            step += 1
            rec = {"epoch": epoch, "step": step, "pref_loss": float(loss), **m}
            history.append(rec)
            on_metrics(rec)
            if step % 10 == 0 or step == steps_total:
                log(f"  pref step {step}/{steps_total}: loss={float(loss):.4f} "
                    f"acc={m['accuracy']:.0%}")
        ev = evaluate()
        if ev is not None:
            history.append({"epoch": epoch, "step": step,
                            **{f"eval_{k}": v for k, v in ev.items()}})
            on_metrics(history[-1])
            log(f"  epoch {epoch}: eval loss {ev['loss']:.4f}, preference "
                f"accuracy {ev['accuracy']:.0%}")
            if ev["loss"] < best["loss"]:
                best, best_state, best_epoch = ev, adapter_state(), epoch
        else:
            best_state, best_epoch = adapter_state(), epoch

    # Restore the best epoch (epoch 0 = the SFT model itself).
    with torch.no_grad():
        named = dict(model.named_parameters())
        for k, v in best_state.items():
            named[k].copy_(v)
    log(f"  kept {'the SFT model (preference epochs did not improve held-out loss)' if best_epoch == 0 else f'preference epoch {best_epoch}'}")
    return {"method": plan.method, "plan": plan.to_dict(), "history": history,
            "best_epoch": best_epoch, "n_train": len(train_enc),
            "n_eval": len(eval_enc), "reason": plan.reason}


# ── Assessment ─────────────────────────────────────────────


def assess_preference_stage(result: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Alerts (as TrainingAlert-compatible dicts) for the preference stage."""
    if not result or result.get("method") in (None, "off"):
        return []
    alerts: List[Dict[str, str]] = []
    evals = [h for h in result.get("history", []) if "eval_loss" in h]
    method = result["method"].upper()
    if not evals:
        alerts.append({"level": "info", "title": f"{method}: no held-out check",
                       "detail": "Too few prompts to hold any out; preference "
                                 "accuracy couldn't be verified.",
                       "suggestion": "Collect more ratings/edits."})
        return alerts
    first, best = evals[0], min(evals, key=lambda h: h["eval_loss"])
    if result.get("best_epoch", 0) == 0:
        alerts.append({"level": "warning", "title": f"{method} didn't help",
                       "detail": "Held-out preference loss never improved on the "
                                 "SFT model, so the SFT weights were kept.",
                       "suggestion": "Check that ratings are consistent; more "
                                     "pairs or a smaller β may help."})
    elif best.get("eval_accuracy", 0) <= 0.55:
        alerts.append({"level": "warning", "title": f"{method}: weak preference learning",
                       "detail": f"Held-out preference accuracy is "
                                 f"{best.get('eval_accuracy', 0):.0%} — barely "
                                 f"better than chance.",
                       "suggestion": "More (and more consistent) feedback is needed."})
    else:
        alerts.append({"level": "info", "title": f"{method} improved preferences",
                       "detail": f"Held-out preference accuracy "
                                 f"{first.get('eval_accuracy', 0):.0%} → "
                                 f"{best.get('eval_accuracy', 0):.0%}.",
                       "suggestion": ""})
    if result["method"] == "dpo" and result.get("best_epoch", 0):
        if (best.get("eval_chosen_logp_shift", 0) < -5
                and best.get("eval_rejected_logp_shift", 0) < -5):
            alerts.append({
                "level": "warning", "title": "DPO likelihood displacement",
                "detail": "Both preferred and rejected answers became much less "
                          "likely — the model may drift toward unusual text.",
                "suggestion": "Raise β (e.g. 0.2–0.5) or lower the learning rate."})
    return alerts
