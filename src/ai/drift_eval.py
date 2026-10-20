"""Performance side of drift checks: how well does a trained model handle
examples it never saw, compared with its validation loss at training time?

Rows are rendered and prompt-masked with :mod:`src.ai.sft_format`, the
same code the trainer uses, and loss is token-weighted over answer
tokens — the quantity the trainer's ``eval_loss`` reports. Needs torch,
transformers and (for LoRA adapters) peft; callers should treat a
``RuntimeError`` as "performance check unavailable".
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from src.ai.training_insights import row_content_key

_KEY_CHARS = 16


def split_rows_by_novelty(jsonl_path: Path, baseline_keys: Iterable[str], *,
                          max_rows: int = 64, seed: int = 0
                          ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Sample unique rows the model never saw, and rows it trained on."""
    known = set(baseline_keys)
    new_rows: List[Dict[str, Any]] = []
    old_rows: List[Dict[str, Any]] = []
    seen = set()
    with open(jsonl_path, "r", encoding="utf-8") as f:
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
            (old_rows if key in known else new_rows).append(rec)
    rng = random.Random(seed)
    if len(new_rows) > max_rows:
        new_rows = rng.sample(new_rows, max_rows)
    if len(old_rows) > max_rows:
        old_rows = rng.sample(old_rows, max_rows)
    return new_rows, old_rows


def evaluate_drift_performance(*, model_dir: Path, base_model: str,
                               jsonl_path: Path, baseline_keys: Iterable[str],
                               baseline_loss: Optional[float],
                               max_rows: int = 64, max_length: int = 512,
                               log: Callable[[str], None] = lambda _m: None
                               ) -> Dict[str, Any]:
    new_rows, old_rows = split_rows_by_novelty(
        jsonl_path, baseline_keys, max_rows=max_rows)
    if not new_rows:
        return {"new_loss": None, "known_loss": None, "baseline_loss": baseline_loss,
                "ratio": None, "n_new": 0, "n_known": len(old_rows),
                "note": "No unseen examples in the current mix."}
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except Exception as e:  # ImportError or broken installs
        raise RuntimeError(f"Training libraries unavailable: {e}")
    from src.ai.sft_format import tokenize_rows

    model_dir = Path(model_dir)
    is_adapter = (model_dir / "adapter_config.json").exists()
    tok_src = str(model_dir) if (model_dir / "tokenizer_config.json").exists() else base_model
    log(f"Loading tokenizer from {tok_src}…")
    tokenizer = AutoTokenizer.from_pretrained(tok_src)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    device = ("cuda" if torch.cuda.is_available() else
              "mps" if torch.backends.mps.is_available() else "cpu")
    dtype = torch.bfloat16 if device != "cpu" else torch.float32
    log(f"Loading {'base ' + base_model + ' + adapter' if is_adapter else model_dir} "
        f"on {device}…")
    import transformers
    # transformers ≥ 4.56 renamed torch_dtype → dtype (5.x warns on the old name).
    major_minor = tuple(int(x) for x in transformers.__version__.split(".")[:2])
    dtype_kw = "dtype" if major_minor >= (4, 56) else "torch_dtype"
    model = AutoModelForCausalLM.from_pretrained(
        base_model if is_adapter else str(model_dir), **{dtype_kw: dtype})
    if is_adapter:
        try:
            from peft import PeftModel
        except Exception as e:
            raise RuntimeError(f"peft unavailable: {e}")
        model = PeftModel.from_pretrained(model, str(model_dir))
    model.to(device).eval()
    has_chat_template = bool(getattr(tokenizer, "chat_template", None))

    def mean_loss(rows: List[Dict[str, Any]], label: str) -> Optional[float]:
        if not rows:
            return None
        total, n_tok = 0.0, 0
        for i, rec in enumerate(rows, 1):
            enc = tokenize_rows(tokenizer, [rec], max_length=max_length,
                                has_chat_template=has_chat_template)
            ids = torch.tensor([enc["input_ids"][0]], device=device)
            labels = torch.tensor([enc["labels"][0]], device=device)
            # The model shifts labels internally; count predicted tokens.
            count = int((labels[0, 1:] != -100).sum())
            if count == 0:
                continue
            with torch.no_grad():
                out = model(input_ids=ids, attention_mask=torch.ones_like(ids),
                            labels=labels)
            total += float(out.loss) * count
            n_tok += count
            if i % 16 == 0:
                log(f"  {label}: {i}/{len(rows)} examples scored")
        return total / n_tok if n_tok else None

    new_loss = mean_loss(new_rows, "unseen")
    known_loss = mean_loss(old_rows, "trained-on")
    ratio = (new_loss / baseline_loss
             if new_loss is not None and baseline_loss else None)
    return {"new_loss": new_loss, "known_loss": known_loss,
            "baseline_loss": baseline_loss, "ratio": ratio,
            "n_new": len(new_rows), "n_known": len(old_rows)}
