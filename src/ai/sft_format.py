"""Rendering + tokenization of SFT rows, shared by the trainer and evaluators.

Each JSONL row (Alpaca ``instruction``/``input``/``output`` or chat
``messages``) is rendered with the tokenizer's chat template when it has
one, otherwise an Alpaca template. Labels mask the prompt tokens with
-100 for ``instruction`` rows so loss only covers the assistant's
answer; ``continuation`` rows are learned in full.

Keeping this in one place guarantees that post-training evaluation
(e.g. drift checks) measures loss exactly the way training did.
"""

from __future__ import annotations

from typing import Any, Dict, List


def build_messages(rec: Dict[str, Any]) -> List[Dict[str, str]]:
    """Render a record as chat-template messages.

    Pulls metadata.system_prompt when set. The user turn folds
    instruction + input together; the assistant turn is the output.
    """
    if "messages" in rec:
        # Already a chat-format row (e.g. ShareGPT export)
        return rec["messages"]
    meta = rec.get("metadata") or {}
    instr = rec.get("instruction", "") or ""
    inp = rec.get("input", "") or ""
    out = rec.get("output", "") or ""
    user_msg = f"{instr}\n\n{inp}".strip() if inp else instr
    msgs = []
    system = meta.get("system_prompt", "")
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": user_msg})
    msgs.append({"role": "assistant", "content": out})
    return msgs


def render_full(tokenizer, rec: Dict[str, Any], has_chat_template: bool) -> str:
    """Full sequence (prompt + response) — what the model sees."""
    if has_chat_template:
        return tokenizer.apply_chat_template(build_messages(rec), tokenize=False)
    instr = rec.get("instruction", "")
    inp = rec.get("input", "")
    out = rec.get("output", "")
    if inp:
        return (f"### Instruction:\n{instr}\n\n"
                f"### Input:\n{inp}\n\n"
                f"### Response:\n{out}")
    return f"### Instruction:\n{instr}\n\n### Response:\n{out}"


def render_prompt(tokenizer, rec: Dict[str, Any], has_chat_template: bool) -> str:
    """Prompt portion only, to find the token boundary for loss masking."""
    if has_chat_template:
        msgs = build_messages(rec)[:-1]  # drop assistant
        return tokenizer.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=True)
    instr = rec.get("instruction", "")
    inp = rec.get("input", "")
    if inp:
        return (f"### Instruction:\n{instr}\n\n"
                f"### Input:\n{inp}\n\n"
                f"### Response:\n")
    return f"### Instruction:\n{instr}\n\n### Response:\n"


def format_type(rec: Dict[str, Any]) -> str:
    meta = rec.get("metadata") or {}
    return (meta.get("format_type") or "instruction").lower()


def tokenize_rows(tokenizer, rows: List[Dict[str, Any]], *, max_length: int,
                  has_chat_template: bool) -> Dict[str, List]:
    """Tokenize rows into input_ids / attention_mask / labels (prompt-masked)."""
    full_texts = [render_full(tokenizer, r, has_chat_template) for r in rows]
    prompt_texts = [render_prompt(tokenizer, r, has_chat_template) for r in rows]
    # Same special-token policy so prompts form a clean prefix of full
    # sequences.
    tokens = tokenizer(full_texts, truncation=True, max_length=max_length,
                       padding=False)
    prompt_tokens = tokenizer(prompt_texts, truncation=True,
                              max_length=max_length)
    labels = []
    for full_ids, prompt_ids, ftype in zip(
            tokens["input_ids"], prompt_tokens["input_ids"],
            (format_type(r) for r in rows)):
        lab = list(full_ids)
        if ftype == "instruction":
            # ``min`` guards against prompt tokenization running longer
            # than the (truncated) full sequence.
            for i in range(min(len(prompt_ids), len(lab))):
                lab[i] = -100
        labels.append(lab)
    tokens["labels"] = labels
    return tokens
